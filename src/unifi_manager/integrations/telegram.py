"""Telegram уведомления с rate-limit.

Особенности:
- escape_markdown_v2() для безопасного отображения device names с спецсимволами
- TelegramRateLimiter: per-hash (1 в 30s) + total (5 в минуту)
- State persistence в JSON для cron-runs
"""

from __future__ import annotations

import html
import json
import logging
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import requests

from unifi_manager.settings import TelegramSettings
from unifi_manager.utils.atomic import atomic_write_json
from unifi_manager.utils.time import now_utc

_MARKDOWN_V2_RESERVED = set("_*[]()~`>#+-=|{}.!")
_logger = logging.getLogger(__name__)


def escape_markdown_v2(text: str) -> str:
    """Экранирует все 18 reserved chars MarkdownV2 backslash'ом.

    Telegram MarkdownV2 требует экранирования _ * [ ] ( ) ~ ` > # + - = | { } . !
    в любом контексте (включая текст внутри обычных messages).
    """
    return "".join(f"\\{ch}" if ch in _MARKDOWN_V2_RESERVED else ch for ch in text)


class TelegramRateLimiter:
    """Per-hash + total rate-limit для Telegram алертов.

    Лимиты из settings.telegram:
    - rate_limit_per_hash_seconds (default 30): для одинаковых hash
    - rate_limit_total_per_minute (default 5): суммарный лимит разных hash в минуту

    State (timestamps) хранится в JSON для cron-persistence.
    """

    def __init__(self, state_file: Path, settings: TelegramSettings) -> None:
        self.state_file = state_file
        self.per_hash_window = timedelta(seconds=settings.rate_limit_per_hash_seconds)
        self.total_per_minute = settings.rate_limit_total_per_minute
        # {hash: last_sent_iso}
        self._hash_state: dict[str, str] = {}
        # deque of iso timestamps (общий счётчик)
        self._total_state: deque[str] = deque()
        self._load()

    def _load(self) -> None:
        if not self.state_file.is_file():
            return
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            self._hash_state = data.get("hashes", {})
            self._total_state = deque(data.get("total", []))
        except (json.JSONDecodeError, OSError) as e:
            _logger.warning("Failed to load telegram throttle state: %s", e)

    def _save(self) -> None:
        atomic_write_json(
            self.state_file,
            {"hashes": self._hash_state, "total": list(self._total_state)},
        )

    def check_allowed(self, *, hash_key: str) -> bool:
        """True если отправка сейчас разрешена. Read-only: НЕ записывает state.

        Бюджет тратится только в record() — после фактически успешной отправки,
        иначе провалившийся send блокировал бы собственный немедленный retry.
        """
        now = now_utc()

        # Чистим устаревшие total entries (>60 sec ago) — housekeeping, не «трата» бюджета
        minute_ago = now - timedelta(minutes=1)
        while self._total_state:
            try:
                oldest = datetime.fromisoformat(self._total_state[0])
                if oldest < minute_ago:
                    self._total_state.popleft()
                else:
                    break
            except ValueError:
                self._total_state.popleft()

        # Per-hash check
        last_hash_str = self._hash_state.get(hash_key)
        if last_hash_str:
            try:
                last_hash_ts = datetime.fromisoformat(last_hash_str)
                if (now - last_hash_ts) < self.per_hash_window:
                    _logger.debug("Telegram rate-limit per-hash blocked: %s", hash_key)
                    return False
            except ValueError:
                pass  # bad state, treat as allowed

        # Total check
        if len(self._total_state) >= self.total_per_minute:
            _logger.debug(
                "Telegram rate-limit total blocked: %d in last minute",
                len(self._total_state),
            )
            return False

        return True

    def record(self, *, hash_key: str) -> None:
        """Зафиксировать факт отправки + persist. Вызывать ТОЛЬКО после успешного send."""
        now_iso = now_utc().isoformat()
        self._hash_state[hash_key] = now_iso
        self._total_state.append(now_iso)
        self._save()

    def allow(self, *, hash_key: str) -> bool:
        """Backward-compat: check + record за один вызов (для прямых вызовов/тестов)."""
        if not self.check_allowed(hash_key=hash_key):
            return False
        self.record(hash_key=hash_key)
        return True


class TelegramNotifier:
    """Высокоуровневый wrapper вокруг send_message + rate-limit.

    Использование (в Phase 4 CLI):
        notifier = TelegramNotifier(
            settings=cfg.telegram,
            rate_limit_state=cfg.paths.cache_dir / "telegram.json",
        )
        notifier.send_message("AP Office-1 is offline", hash_key="ap-down:aa:bb")
    """

    TELEGRAM_API_BASE = "https://api.telegram.org"

    def __init__(
        self,
        settings: TelegramSettings,
        *,
        rate_limit_state: Path,
        timeout: int = 10,
    ) -> None:
        if settings.enabled and settings.bot_token is None:
            raise ValueError("bot_token required when telegram.enabled=True")
        if settings.enabled and not settings.chat_id:
            raise ValueError("chat_id required when telegram.enabled=True")
        self.settings = settings
        self.timeout = timeout
        self.rate_limiter = TelegramRateLimiter(rate_limit_state, settings)

    def send_message(self, text: str, *, hash_key: str) -> bool:
        """Отправить msg, уважая rate-limit. Returns True если отправлено.

        Порядок: check_allowed → send → record. Бюджет тратится только при успехе,
        чтобы провал не блокировал немедленный retry того же алерта.
        """
        if not self.settings.enabled:
            return False
        if not self.rate_limiter.check_allowed(hash_key=hash_key):
            return False

        # bot_token guaranteed non-None по __init__ check + enabled=True
        if self.settings.bot_token is None:
            raise RuntimeError("bot_token must be set when enabled — checked in __init__")
        token = self.settings.bot_token.get_secret_value()

        url = f"{self.TELEGRAM_API_BASE}/bot{token}/sendMessage"
        # Текст экранируется под выбранный parse_mode — иначе обычное имя устройства
        # с _ ( ) - . (MarkdownV2) или < > & (HTML) даёт Telegram 400 / mis-parse,
        # и алерт теряется.
        if self.settings.parse_mode == "MarkdownV2":
            text_out = escape_markdown_v2(text)
        elif self.settings.parse_mode == "HTML":
            text_out = html.escape(text)
        else:
            text_out = text
        body: dict[str, str] = {
            "chat_id": self.settings.chat_id or "",
            "text": text_out,
        }
        if self.settings.parse_mode != "None":
            body["parse_mode"] = self.settings.parse_mode

        try:
            resp = requests.post(url, json=body, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            # str(e) содержит URL с /bot<TOKEN>/ — вырезаем токен перед логированием (SEC2).
            _logger.error("Telegram send_message failed: %s", str(e).replace(token, "***"))
            return False

        self.rate_limiter.record(hash_key=hash_key)  # бюджет тратится только при успехе
        return True
