"""RestartService — orchestration auto/profile/device restart c permissions + cooldown.

Использует:  # noqa: RUF001
- LegacyClient (HTTP — Phase 1) для команд
- RestartHistory (state) для cooldown tracking
- restart_decisions (pure) для priority & action choice
- PermissionsSettings.cli (D30) для emergency kill-switch
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol

from unifi_manager.domain.device import AccessPoint
from unifi_manager.domain.event import ApEvent, EventKey
from unifi_manager.domain.restart_history import RestartHistory
from unifi_manager.services.lock import FileLock, LockAcquisitionError
from unifi_manager.services.restart_decisions import (
    Action,
    classify_action,
    priority_score,
    should_skip_by_exclude_pattern,
)
from unifi_manager.settings import RestartProfile, Settings
from unifi_manager.utils.time import is_within_window, now_utc

_logger = logging.getLogger(__name__)

# Sleep between commands (rate-limit на UniFi контроллер)
INTER_ACTION_DELAY_SECONDS = 2.0


class _RestartClient(Protocol):
    def list_devices_raw(self) -> list[dict[str, Any]]: ...
    def send_command(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def list_events_raw(self, *, mac: str) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class RestartAction:
    """Одно действие из run report."""

    mac: str
    name: str
    action: Action
    reason: str
    status: str  # "success" | "fail: ..." | "dry_run" | "cooldown_skip"


@dataclass(frozen=True)
class RestartReport:
    """Результат RestartService.auto()."""

    status: Literal["completed", "skipped_permissions", "no_candidates", "skipped_locked"]
    dry_run: bool
    actions: list[RestartAction] = field(default_factory=list)


class RestartService:
    """Auto-restart problem APs + profile-based + device targeted."""

    def __init__(
        self,
        legacy_client: _RestartClient,
        settings: Settings,
    ) -> None:
        self.client = legacy_client
        self.settings = settings
        self.history = RestartHistory(settings.auto_restart.statefile)
        self._lock_path = settings.auto_restart.statefile.parent / "restart.lock"

    def _reload_history(self) -> None:
        """Перечитать историю с диска. Вызывается ПОД локом: реальный ран должен
        видеть записи конкурентных ранов, иначе stale in-memory снапшот разрешит
        повторный рестарт и затрёт их при save() (lost-update). In-place reload
        сохраняет identity объекта (тесты/код держат ссылку на self.history)."""
        self.history.reload()

    def auto(self, *, dry_run: bool = False) -> RestartReport:
        """Smart auto-restart: priority по state+offline, cooldown, max_per_run."""
        # D30: permission kill-switch
        if not self.settings.permissions.cli.restart.execute:
            _logger.warning("auto: skipped — permissions.cli.restart.execute=false")
            return RestartReport(status="skipped_permissions", dry_run=dry_run)

        # dry-run is read-only — no lock needed; real runs acquire the lock to prevent overlap
        if not dry_run:
            try:
                with FileLock(self._lock_path, timeout=0):
                    return self._auto_locked(dry_run=False)
            except LockAcquisitionError:
                _logger.warning("auto: skipped — another instance holds %s", self._lock_path)
                return RestartReport(status="skipped_locked", dry_run=False, actions=[])

        return self._auto_locked(dry_run=True)

    def _auto_locked(self, *, dry_run: bool) -> RestartReport:
        """Inner auto logic — called either under lock (real run) or lock-free (dry-run)."""
        if not dry_run:
            self._reload_history()  # под локом — увидеть записи конкурентных ранов (SC1)
        cfg = self.settings.auto_restart
        cooldown = timedelta(minutes=cfg.cooldown_minutes)

        # 1. Collect problematic candidates
        candidates: list[tuple[int, AccessPoint]] = []
        for raw in self.client.list_devices_raw():
            if raw.get("type") != "uap":
                continue
            try:
                ap = AccessPoint.model_validate(raw)
            except Exception as e:
                _logger.debug("Skipping unparseable device: %s", e)
                continue

            # exclude patterns
            if ap.name and should_skip_by_exclude_pattern(ap.name, cfg.exclude_patterns):
                continue

            # online — skip
            if ap.state == 1:
                continue

            # cooldown check
            allowed, _reason = self.history.can_restart(ap.mac, cooldown=cooldown)
            if not allowed:
                continue

            offline_min = self._offline_minutes(ap)

            # offline_threshold_min: state=0 (OFFLINE) APs need recovery grace period.
            # state=10 (CONNECTION_INTERRUPTED) exempted — needs immediate action.
            if ap.state == 0 and offline_min < cfg.offline_threshold_min:
                continue

            priority = priority_score(state=ap.state, offline_min=offline_min)
            if priority >= 99:
                continue  # nothing to do

            candidates.append((priority, ap))

        if not candidates:
            return RestartReport(status="no_candidates", dry_run=dry_run)

        # 2. Sort by priority (lowest first)
        candidates.sort(key=lambda x: x[0])

        # 3. Process up to max_per_run
        batch = candidates[: cfg.max_restarts_per_run]
        actions: list[RestartAction] = []
        for idx, (_priority, ap) in enumerate(batch):
            has_uplink = ap.uplink is not None and ap.uplink.uplink_mac is not None
            action, reason = classify_action(state=ap.state, has_uplink=has_uplink)
            if action is None:
                continue

            if dry_run:
                actions.append(
                    RestartAction(
                        mac=ap.mac,
                        name=ap.name or ap.mac,
                        action=action,
                        reason=reason,
                        status="dry_run",
                    )
                )
                continue

            success, status_msg = self._execute(action, ap)
            actions.append(
                RestartAction(
                    mac=ap.mac,
                    name=ap.name or ap.mac,
                    action=action,
                    reason=reason,
                    status="success" if success else f"fail: {status_msg}",
                )
            )

            if success:
                self.history.record_restart(
                    mac=ap.mac,
                    name=ap.name or ap.mac,
                    action=action,
                    reason=reason,
                )
                self.history.save()  # incremental — persist cooldown even on mid-run crash

            # Inter-action delay — only between commands, not after the last one
            is_last = idx == len(batch) - 1
            if not is_last:
                time.sleep(INTER_ACTION_DELAY_SECONDS)

        return RestartReport(status="completed", dry_run=dry_run, actions=actions)

    def _execute(self, action: Action, ap: AccessPoint) -> tuple[bool, str]:
        """Реально вызвать API. Returns (success, status_msg)."""
        try:
            if action == "restart":
                resp = self.client.send_command({"cmd": "restart", "mac": ap.mac})
            else:  # poe_cycle
                if (
                    ap.uplink is None
                    or ap.uplink.uplink_mac is None
                    or ap.uplink.uplink_remote_port is None
                ):
                    return False, "no uplink info"
                resp = self.client.send_command(
                    {
                        "cmd": "power-cycle",
                        "mac": ap.uplink.uplink_mac,
                        "port_idx": ap.uplink.uplink_remote_port,
                    }
                )
            rc = resp.get("meta", {}).get("rc")
            return (rc == "ok"), f"rc={rc}"
        except Exception as e:
            _logger.error("Action %s failed for %s: %s", action, ap.mac, e)
            return False, str(e)

    def profile(self, profile_name: str, *, apply: bool = False) -> RestartReport:
        """Restart APs matching profile (заменяет легаси restart-скрипты).

        apply=False (default) — dry-run для safety.
        apply=True — реальный restart.
        """
        # D30: permissions (cli namespace)
        if not self.settings.permissions.cli.restart.execute:
            _logger.warning("profile: skipped — permissions.cli.restart.execute=false")
            return RestartReport(status="skipped_permissions", dry_run=not apply)
        if apply and not self.settings.permissions.cli.restart.profile_apply:
            _logger.warning("profile: skipped — permissions.cli.restart.profile_apply=false")
            return RestartReport(status="skipped_permissions", dry_run=False)

        profile = self.settings.restart_profiles.get(profile_name)
        if profile is None:
            raise ValueError(f"unknown profile: {profile_name!r}")

        cooldown = timedelta(minutes=profile.cooldown_minutes)

        # 1. List devices, filter by profile.filter_names/patterns
        all_devices = self.client.list_devices_raw()
        candidates: list[AccessPoint] = []
        for raw in all_devices:
            if raw.get("type") != "uap":
                continue
            name = raw.get("name", "") or ""
            # filter_names: exact match (case-sensitive)
            if profile.filter_names and name not in profile.filter_names:
                continue
            # filter_patterns: regex match (any pattern must match)
            if profile.filter_patterns and not any(
                re.search(pat, name) for pat in profile.filter_patterns
            ):
                continue
            # exclude_names: exact exclusion
            if profile.exclude_names and name in profile.exclude_names:
                continue
            # exclude_patterns: regex exclusion (any pattern matching → skip)
            if profile.exclude_patterns and any(
                re.search(pat, name) for pat in profile.exclude_patterns
            ):
                continue
            try:
                candidates.append(AccessPoint.model_validate(raw))
            except Exception as e:
                _logger.debug("Skipping unparseable device: %s", e)

        # apply=True: acquire lock to prevent overlapping real runs
        if apply:
            try:
                with FileLock(self._lock_path, timeout=0):
                    return self._profile_locked(
                        apply=True, candidates=candidates, profile=profile, cooldown=cooldown
                    )
            except LockAcquisitionError:
                _logger.warning("profile: skipped — another instance holds %s", self._lock_path)
                return RestartReport(status="skipped_locked", dry_run=False, actions=[])

        return self._profile_locked(
            apply=False, candidates=candidates, profile=profile, cooldown=cooldown
        )

    def _profile_locked(
        self,
        *,
        apply: bool,
        candidates: list[AccessPoint],
        profile: RestartProfile,
        cooldown: timedelta,
    ) -> RestartReport:
        """Inner profile logic — called either under lock (apply=True) or lock-free (dry-run)."""
        if apply:
            self._reload_history()  # под локом — увидеть записи конкурентных ранов (SC1)
        # 2. For each candidate, count lost-contact events in window
        actions: list[RestartAction] = []
        for idx, ap in enumerate(candidates):
            # cooldown check (использует profile cooldown_minutes)
            allowed, _ = self.history.can_restart(ap.mac, cooldown=cooldown)
            if not allowed:
                continue

            events_raw = self.client.list_events_raw(mac=ap.mac)
            lost_count = 0
            for evt_raw in events_raw:
                try:
                    evt = ApEvent.model_validate(evt_raw)
                except Exception:
                    continue
                if evt.key != EventKey.AP_LOST_CONTACT:
                    continue
                if is_within_window(evt.timestamp, hours=profile.window_hours):
                    lost_count += 1

            if lost_count <= profile.lost_contact_threshold:
                continue  # under threshold, skip

            reason = f"lost_contact count={lost_count} > threshold={profile.lost_contact_threshold}"
            if not apply:
                actions.append(
                    RestartAction(
                        mac=ap.mac,
                        name=ap.name or ap.mac,
                        action="restart",
                        reason=reason,
                        status="dry_run",
                    )
                )
                # Cap dry-run the same as apply, иначе preview > реального --apply.
                if len(actions) >= profile.max_restarts:
                    break
                continue

            success, msg = self._execute("restart", ap)
            actions.append(
                RestartAction(
                    mac=ap.mac,
                    name=ap.name or ap.mac,
                    action="restart",
                    reason=reason,
                    status="success" if success else f"fail: {msg}",
                )
            )
            if success:
                self.history.record_restart(
                    mac=ap.mac,
                    name=ap.name or ap.mac,
                    action="restart",
                    reason=reason,
                )
                self.history.save()  # incremental — persist cooldown even on mid-run crash
            if len(actions) >= profile.max_restarts:
                break
            # Sleep only if more candidates remain to process
            if idx < len(candidates) - 1:
                time.sleep(INTER_ACTION_DELAY_SECONDS)

        return RestartReport(
            status="completed",
            dry_run=not apply,
            actions=actions,
        )

    def device(
        self,
        *,
        mac: str,
        method: Literal["restart", "poe_cycle"],
        apply: bool = False,
    ) -> RestartReport:
        """Точечный restart одного device по MAC."""
        if not self.settings.permissions.cli.restart.execute:
            _logger.warning("device: skipped — permissions.cli.restart.execute=false")
            return RestartReport(status="skipped_permissions", dry_run=not apply)
        if apply and not self.settings.permissions.cli.restart.device_apply:
            _logger.warning("device: skipped — permissions.cli.restart.device_apply=false")
            return RestartReport(status="skipped_permissions", dry_run=False)

        # Find device
        target: AccessPoint | None = None
        for raw in self.client.list_devices_raw():
            if raw.get("mac") == mac and raw.get("type") == "uap":
                try:
                    target = AccessPoint.model_validate(raw)
                except Exception as e:
                    raise ValueError(f"device {mac} unparseable: {e}") from e
                break

        if target is None:
            raise ValueError(f"device {mac!r} not found in current site inventory")

        reason = f"manual targeted {method}"
        if not apply:
            return RestartReport(
                status="completed",
                dry_run=True,
                actions=[
                    RestartAction(
                        mac=mac,
                        name=target.name or mac,
                        action=method,
                        reason=reason,
                        status="dry_run",
                    )
                ],
            )

        # apply=True: acquire lock to prevent overlapping real runs
        try:
            with FileLock(self._lock_path, timeout=0):
                self._reload_history()  # под локом — не затереть записи конкурентных ранов (SC1)
                success, msg = self._execute(method, target)
                action_record = RestartAction(
                    mac=mac,
                    name=target.name or mac,
                    action=method,
                    reason=reason,
                    status="success" if success else f"fail: {msg}",
                )
                if success:
                    self.history.record_restart(
                        mac=mac,
                        name=target.name or mac,
                        action=method,
                        reason=reason,
                    )
                    self.history.save()
                return RestartReport(status="completed", dry_run=False, actions=[action_record])
        except LockAcquisitionError:
            _logger.warning("device: skipped — another instance holds %s", self._lock_path)
            return RestartReport(status="skipped_locked", dry_run=False, actions=[])

    @staticmethod
    def _offline_minutes(ap: AccessPoint) -> float:
        """Сколько минут устройство офлайн (last_seen → now)."""
        if ap.last_seen is None:
            return 0.0
        # last_seen — unix timestamp
        last_dt = datetime.fromtimestamp(ap.last_seen, tz=now_utc().tzinfo)
        return (now_utc() - last_dt).total_seconds() / 60.0
