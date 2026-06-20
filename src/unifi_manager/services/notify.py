"""NotifyService + AlertHistory.

AlertHistory predotvrashchaet shtorm uvedomleniy — kazhdyy alert identifitsiruetsya
hash_key (naprimer "ap-down:aa:bb:cc:dd:ee:ff") i shlyotsya tolko esli:
- Etot hash ranshe ne alertilsya, ILI
- Proshyol cooldown s poslednego alerta (dlya napominaniya)

State khranitsya v JSON-fayle (paths.cache_dir/alert_history.json po umolchaniyu).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

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
