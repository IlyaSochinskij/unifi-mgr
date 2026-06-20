"""NotifyService + AlertHistory.

AlertHistory predotvrashchaet shtorm uvedomleniy — kazhdyy alert identifitsiruetsya
hash_key (naprimer "ap-down:aa:bb:cc:dd:ee:ff") i shlyotsya tolko esli:
- Etot hash ranshe ne alertilsya, ILI
- Proshyol cooldown s poslednego alerta (dlya napominaniya)

State khranitsya v JSON-fayle (paths.cache_dir/alert_history.json po umolchaniyu).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from unifi_manager.services.audit import AuditIssue
from unifi_manager.settings import Settings
from unifi_manager.utils.atomic import atomic_write_json
from unifi_manager.utils.time import now_utc

DEFAULT_COOLDOWN = timedelta(minutes=60)

_logger = logging.getLogger(__name__)


class AlertHistory:
    """Dedup state dlya critical alerts.

    Ispolzovanie:
        history = AlertHistory(state_file=Path("/var/lib/unifi-mgr/alerts.json"))
        if history.is_new_alert(hash_key="ap-down:aa:bb"):
            telegram.send_message("...")
            history.record_alert(hash_key="ap-down:aa:bb")
        history.save()
    """

    def __init__(
        self,
        state_file: Path,
        *,
        cooldown: timedelta = DEFAULT_COOLDOWN,
    ) -> None:
        self.state_file = state_file
        self.cooldown = cooldown
        self._state: dict[str, str] = self._load_state()

    def _load_state(self) -> dict[str, str]:
        """Prochitat state-fayl (ili vernut {} pri otsutstvii/povrezhdenii)."""
        if not self.state_file.is_file():
            return {}
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {k: str(v) for k, v in data.items()}
            _logger.warning("Alert state file %s: unexpected format", self.state_file)
            return {}
        except (json.JSONDecodeError, OSError) as e:
            _logger.warning("Failed to load alert state %s: %s", self.state_file, e)
            return {}

    def is_new_alert(self, *, hash_key: str) -> bool:
        """True esli etot hash ranshe ne alertilsya ili proshyol cooldown."""
        last_alert_str = self._state.get(hash_key)
        if last_alert_str is None:
            return True

        try:
            last_alert = datetime.fromisoformat(last_alert_str)
        except ValueError:
            _logger.warning(
                "Bad timestamp in alert state for %s: %s",
                hash_key,
                last_alert_str,
            )
            return True

        return (now_utc() - last_alert) > self.cooldown

    def record_alert(self, *, hash_key: str) -> None:
        """Zapisat chto alert po etomu hash otpravlen seychas."""
        self._state[hash_key] = now_utc().isoformat()

    def save(self) -> None:
        """Сохранить state на диск атомарно (graceful — OSError logged в helper)."""
        atomic_write_json(self.state_file, self._state)


class Notifier(Protocol):
    """Канал доставки. Seam: TelegramNotifier соответствует; будущий MatrixNotifier — тоже."""

    def send_message(self, text: str, *, hash_key: str) -> bool: ...


class AlertLevel(StrEnum):
    """Уровень для `notify send --level` (Typer отвергает прочее → exit 2)."""

    info = "info"
    warn = "warn"
    crit = "crit"


class _ChannelState(StrEnum):
    """Internal: исход проверки канала (НЕ входит в публичный NotifyStatus)."""

    enabled = "enabled"
    skipped_permissions = "skipped_permissions"
    skipped_disabled = "skipped_disabled"


class NotifyStatus(StrEnum):
    """Public исход в NotifyReport. `enabled` сюда НЕ входит — это internal channel-state."""

    sent = "sent"
    completed = "completed"
    partial = "partial"
    failed = "failed"
    channel_unavailable = "channel_unavailable"
    skipped_permissions = "skipped_permissions"
    skipped_disabled = "skipped_disabled"
    no_issues = "no_issues"


@dataclass(frozen=True)
class NotifyReport:
    """Результат notify-операции — статус + счётчики (стиль RestartReport)."""

    status: NotifyStatus
    sent: int = 0
    skipped_dedup: int = 0
    failed: int = 0


_LEVEL_ICON: dict[AlertLevel, str] = {
    AlertLevel.info: "ℹ",
    AlertLevel.warn: "⚠",
    AlertLevel.crit: "🚨",
}


class NotifyService:
    """Единственный authority по permission/status политике уведомлений.

    CLI строит сервис через build_notify_service и делает один вызов
    (notify_audit_issues / send / test). Permission/enabled-gate, dedup и
    форматирование — здесь, не в CLI. Нотифаер строится лениво и один раз.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        history: AlertHistory,
        notifier_factory: Callable[[], Notifier],
    ) -> None:
        self.settings = settings
        self.history = history
        self._notifier_factory = notifier_factory
        self._notifier: Notifier | None = None
        self._notifier_attempted = False
        self._channel_error: str | None = None

    def _channel_state(self) -> _ChannelState:
        if not self.settings.permissions.cli.notify.telegram_send:
            return _ChannelState.skipped_permissions
        if not self.settings.telegram.enabled:
            return _ChannelState.skipped_disabled
        return _ChannelState.enabled

    def _get_notifier(self) -> Notifier | None:
        """Safe-lazy + memoize (успех И провал) — build once, reuse за время жизни сервиса."""
        if self._notifier_attempted:
            return self._notifier
        self._notifier_attempted = True
        try:
            self._notifier = self._notifier_factory()
        except ValueError as e:
            self._channel_error = str(e)
            self._notifier = None
        return self._notifier

    def notify_audit_issues(self, issues: Sequence[AuditIssue]) -> NotifyReport:
        """Per-issue dedup + send для `audit critical --telegram`. Статус по §3.1."""
        if not issues:
            return NotifyReport(status=NotifyStatus.no_issues)
        state = self._channel_state()
        if state is _ChannelState.skipped_permissions:
            _logger.info("notify: suppressed — permissions.cli.notify.telegram_send=false")
            return NotifyReport(status=NotifyStatus.skipped_permissions)
        if state is _ChannelState.skipped_disabled:
            return NotifyReport(status=NotifyStatus.skipped_disabled)
        notifier = self._get_notifier()
        if notifier is None:
            _logger.warning("notify: channel unavailable: %s", self._channel_error)
            return NotifyReport(status=NotifyStatus.channel_unavailable)

        sent = failed = skipped = 0
        for issue in issues:
            hash_key = f"{issue.issue_type}:{issue.device_mac}"
            if not self.history.is_new_alert(hash_key=hash_key):
                skipped += 1
                continue
            if notifier.send_message(self._format_issue(issue), hash_key=hash_key):
                sent += 1
                self.history.record_alert(hash_key=hash_key)  # record ТОЛЬКО после успеха
            else:
                failed += 1
        self.history.save()  # один раз в конце

        if sent and not failed:
            status = NotifyStatus.sent
        elif sent and failed:
            status = NotifyStatus.partial
        elif failed:
            status = NotifyStatus.failed
        else:
            status = NotifyStatus.completed  # всё задедуплено
        return NotifyReport(status=status, sent=sent, skipped_dedup=skipped, failed=failed)

    def send(self, text: str, *, level: AlertLevel) -> NotifyReport:
        """Ручная отправка (`notify send`). Без dedup-completed."""
        return self._single(f"{_LEVEL_ICON[level]} {text}", self._send_hash(level, text))

    def test(self) -> NotifyReport:
        """Тестовое сообщение (`notify test`)."""
        return self._single("✓ unifi-mgr test message", "cli-test")

    def _single(self, text: str, hash_key: str) -> NotifyReport:
        state = self._channel_state()
        if state is _ChannelState.skipped_permissions:
            return NotifyReport(status=NotifyStatus.skipped_permissions)
        if state is _ChannelState.skipped_disabled:
            return NotifyReport(status=NotifyStatus.skipped_disabled)
        notifier = self._get_notifier()
        if notifier is None:
            return NotifyReport(status=NotifyStatus.channel_unavailable)
        ok = notifier.send_message(text, hash_key=hash_key)
        return NotifyReport(
            status=NotifyStatus.sent if ok else NotifyStatus.failed,
            sent=1 if ok else 0,
            failed=0 if ok else 1,
        )

    @staticmethod
    def _format_issue(issue: AuditIssue) -> str:
        return f"⚠ {issue.severity}: {issue.device_name} — {issue.issue_type}"

    @staticmethod
    def _send_hash(level: AlertLevel, text: str) -> str:
        digest = hashlib.sha256(f"{level.value}\0{text}".encode()).hexdigest()[:16]
        return f"cli-send:{level.value}:{digest}"
