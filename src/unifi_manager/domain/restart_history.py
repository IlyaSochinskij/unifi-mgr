"""RestartHistory — state-файл для cooldown и rate-limit рестартов.

Заменяет inline JSON manipulation из _legacy/auto_restart_problem_aps.py.
Поддерживает legacy format (flat dict) для migration без data loss.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from unifi_manager.utils.atomic import atomic_write_json
from unifi_manager.utils.time import now_utc

_logger = logging.getLogger(__name__)

CURRENT_VERSION = 1


class RestartHistoryEntry(BaseModel):
    """Запись истории рестарта одного устройства."""

    name: str
    last_restart: datetime  # tz-aware UTC
    action: str  # "restart" | "poe_cycle" | "skipped"
    reason: str
    count: int = 1


class RestartHistory:
    """Cooldown + counter state для RestartService.

    Использование:
        history = RestartHistory(state_file=Path("/var/lib/unifi-mgr/restart_history.json"))
        allowed, why = history.can_restart("aa:bb", cooldown=timedelta(minutes=60))
        if allowed:
            ... # call client API
            history.record_restart(mac="aa:bb", name="AP-01", action="restart",
                                    reason="Lost contact > 3")
        history.save()
    """

    def __init__(self, state_file: Path) -> None:
        self.state_file = state_file
        self._corrupt = False
        self._entries: dict[str, RestartHistoryEntry] = self._load()

    def _load(self) -> dict[str, RestartHistoryEntry]:
        if not self.state_file.is_file():
            # Legitimate first run — not corrupt
            return {}
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            self._corrupt = True
            _logger.error(
                "Restart history %s corrupt/unreadable — failing CLOSED (no restarts until fixed): %s",
                self.state_file,
                e,
            )
            return {}
        if not isinstance(data, dict):
            self._corrupt = True
            _logger.error(
                "Restart history %s corrupt/unreadable — failing CLOSED (no restarts until fixed): "
                "top-level value is not a dict",
                self.state_file,
            )
            return {}
        return self._parse_data(data)

    @staticmethod
    def _parse_data(data: Any) -> dict[str, RestartHistoryEntry]:
        """Парсит и legacy (flat dict) и new (versioned) format."""
        if not isinstance(data, dict):
            return {}

        # New format: {"version": 1, "entries": {...}}; legacy format: flat dict mac → entry
        raw_entries = data.get("entries", {}) if "version" in data and "entries" in data else data

        result: dict[str, RestartHistoryEntry] = {}
        for mac, raw_entry in raw_entries.items():
            if not isinstance(raw_entry, dict):
                continue
            try:
                # Legacy last_restart мог быть naive "2026-05-15T22:00:00" — добавляем UTC tz
                ts_str = raw_entry.get("last_restart", "")
                if isinstance(ts_str, str) and "+" not in ts_str and "Z" not in ts_str:
                    raw_entry["last_restart"] = ts_str + "+00:00"
                result[mac] = RestartHistoryEntry.model_validate(raw_entry)
            except Exception as e:
                _logger.warning("Bad restart history entry for %s: %s", mac, e)
        return result

    def reload(self) -> None:
        """Перечитать state с диска поверх текущего (in-place).

        Нужно для повторного чтения ПОД локом: реальный ран должен видеть записи
        конкурентных ранов, не потеряв identity объекта (RestartService держит ссылку).
        """
        self._corrupt = False
        self._entries = self._load()

    def get_entry(self, mac: str) -> RestartHistoryEntry | None:
        return self._entries.get(mac)

    def can_restart(self, mac: str, *, cooldown: timedelta) -> tuple[bool, str]:
        """Returns (allowed, reason_text)."""
        if self._corrupt:
            return False, "history corrupt — failing closed (skip)"
        entry = self._entries.get(mac)
        if entry is None:
            return True, "no prior restart"
        elapsed = now_utc() - entry.last_restart
        if elapsed < cooldown:
            remaining = cooldown - elapsed
            return False, f"cooldown active, {int(remaining.total_seconds() // 60)} min remaining"
        return True, "cooldown expired"

    def record_restart(self, *, mac: str, name: str, action: str, reason: str) -> None:
        """Обновить state — увеличить count если запись была."""
        existing = self._entries.get(mac)
        new_count = (existing.count + 1) if existing else 1
        self._entries[mac] = RestartHistoryEntry(
            name=name,
            last_restart=now_utc(),
            action=action,
            reason=reason,
            count=new_count,
        )

    def save(self) -> None:
        """Atomically save state via os.replace(). OSError logs (cron-safety, не raise).

        When the history file is corrupt, refuses to overwrite it so the corrupt
        file is preserved for operator inspection / forensics.
        """
        if self._corrupt:
            _logger.warning(
                "Refusing to overwrite corrupt history %s (preserve for inspection)",
                self.state_file,
            )
            return

        payload = {
            "version": CURRENT_VERSION,
            "entries": {mac: entry.model_dump(mode="json") for mac, entry in self._entries.items()},
        }
        atomic_write_json(self.state_file, payload)
