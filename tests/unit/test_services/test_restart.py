"""Тесты для unifi_manager.services.restart.RestartService."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from freezegun import freeze_time

from tests.unit.test_services.conftest import lock_held_by_other_process
from unifi_manager.settings import (
    AutoRestartSettings,
    PermissionsSettings,
    Settings,
    UnifiAuthSettings,
)


@pytest.fixture()
def restart_settings(tmp_path: Path) -> Settings:
    """Settings с auto_restart + permissions defaults."""
    return Settings(
        unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="test"),
        auto_restart=AutoRestartSettings(
            max_restarts_per_run=5,
            cooldown_minutes=60,
            offline_threshold_min=15,
            exclude_patterns=["Spasatel"],
            statefile=tmp_path / "restart_history.json",
        ),
    )


@pytest.fixture()
def mock_client_problematic(fixtures_dir: Path) -> Mock:
    raw = json.loads((fixtures_dir / "problematic_devices.json").read_text(encoding="utf-8"))
    client = Mock()
    client.list_devices_raw.return_value = raw["data"]
    client.send_command.return_value = {"meta": {"rc": "ok"}}
    return client


# === auto() ===


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_processes_problematic_devices(
    restart_settings: Settings,
    mock_client_problematic: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto() обрабатывает state=10 и state=0 устройства."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.auto()

    # 2 problematic AP (ap-1 state=10, ap-2 state=0) + 1 excluded (ap-3 Spasatel) + 1 healthy (ap-4)
    # excluded и healthy не процессятся
    assert len(report.actions) == 2


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_respects_exclude_patterns(
    restart_settings: Settings,
    mock_client_problematic: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.auto()

    processed_macs = {a.mac for a in report.actions}
    assert "aa:bb:cc:dd:ee:03" not in processed_macs  # Spasatel excluded


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_dry_run_does_not_send_commands(
    restart_settings: Settings,
    mock_client_problematic: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.auto(dry_run=True)

    assert report.dry_run is True
    mock_client_problematic.send_command.assert_not_called()


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_sends_commands_when_not_dry_run(
    restart_settings: Settings,
    mock_client_problematic: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    svc.auto(dry_run=False)

    # 2 problematic → 2 send_command calls
    assert mock_client_problematic.send_command.call_count == 2


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_reloads_history_after_lock(
    restart_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SC1: историю надо перечитывать под локом — иначе stale-снапшот разрешает
    повторный рестарт уже рестартнутого (конкурентным раном) AP и теряет его записи."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.domain.restart_history import RestartHistory
    from unifi_manager.services.restart import RestartService

    client = Mock()
    client.list_devices_raw.return_value = [
        {"mac": "aa:bb:cc:dd:ee:10", "model": "U7IW", "type": "uap", "state": 10, "name": "AP-X"},
    ]
    client.send_command.return_value = {"meta": {"rc": "ok"}}

    # Конструируем сервис — он грузит (пустую) историю в память.
    svc = RestartService(legacy_client=client, settings=restart_settings)

    # Конкурентный ран рестартнул тот же AP ПОСЛЕ нашего __init__ и записал на диск.
    other = RestartHistory(restart_settings.auto_restart.statefile)
    other.record_restart(
        mac="aa:bb:cc:dd:ee:10", name="AP-X", action="restart", reason="concurrent"
    )
    other.save()

    report = svc.auto(dry_run=False)  # реальный ран берёт лок

    # cooldown=60min активен → AP должен быть пропущен, команда не отправлена.
    client.send_command.assert_not_called()
    assert report.status == "no_candidates"


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_respects_max_per_run(
    restart_settings: Settings,
    mock_client_problematic: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """max_restarts_per_run=1 → только 1 action даже если problematic больше."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    restart_settings.auto_restart.max_restarts_per_run = 1
    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.auto(dry_run=False)

    assert len(report.actions) == 1


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_skips_devices_in_cooldown(
    restart_settings: Settings,
    mock_client_problematic: Mock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если device в cooldown — не процессим."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.domain.restart_history import RestartHistory
    from unifi_manager.services.restart import RestartService

    # Pre-populate history для ap-1 (recent restart)
    history = RestartHistory(state_file=restart_settings.auto_restart.statefile)
    history.record_restart(
        mac="aa:bb:cc:dd:ee:01",
        name="Restoran",
        action="restart",
        reason="test setup",
    )
    history.save()

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.auto(dry_run=False)

    processed_macs = {a.mac for a in report.actions}
    assert "aa:bb:cc:dd:ee:01" not in processed_macs  # in cooldown


# === permissions D30 (cli namespace) ===


@pytest.mark.fast()
def test_auto_permissions_disabled_returns_empty(
    restart_settings: Settings,
    mock_client_problematic: Mock,
) -> None:
    """permissions.cli.restart.execute=false → skip всё, лог warning."""
    from unifi_manager.services.restart import RestartService

    restart_settings.permissions = PermissionsSettings()
    restart_settings.permissions.cli.restart.execute = False

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.auto(dry_run=False)

    assert report.status == "skipped_permissions"
    assert len(report.actions) == 0
    mock_client_problematic.send_command.assert_not_called()


# === edge cases for coverage ===


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_skips_non_uap_devices(
    restart_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-uap devices (switches etc) are ignored."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    client = Mock()
    client.list_devices_raw.return_value = [
        {"mac": "aa:bb:cc:00:00:01", "model": "US-24", "type": "usw", "state": 0},
    ]
    svc = RestartService(legacy_client=client, settings=restart_settings)
    report = svc.auto()

    assert report.status == "no_candidates"
    assert len(report.actions) == 0


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_handles_unparseable_device(
    restart_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Devices that fail model_validate are skipped without crash."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    client = Mock()
    # Missing required 'mac' field => model_validate will raise
    client.list_devices_raw.return_value = [
        {"type": "uap", "model": "U7IW", "state": 0},  # no mac
    ]
    svc = RestartService(legacy_client=client, settings=restart_settings)
    report = svc.auto()

    assert report.status == "no_candidates"


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_no_candidates_returns_correct_status(
    restart_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All devices healthy → no_candidates."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    client = Mock()
    client.list_devices_raw.return_value = [
        {"_id": "ap-1", "mac": "aa:00:00:00:00:01", "model": "U7IW", "type": "uap", "state": 1},
    ]
    svc = RestartService(legacy_client=client, settings=restart_settings)
    report = svc.auto()

    assert report.status == "no_candidates"


# === profile() ===


@pytest.fixture()
def profile_settings(restart_settings: Settings) -> Settings:
    """Settings с restart_profiles configured."""
    from unifi_manager.settings import RestartProfile

    restart_settings.restart_profiles = {
        "restaurant": RestartProfile(
            filter_names=["Restoran", "Restoran WIFI", "Rest Bar"],
            exclude_names=["Spasatel vagon"],
            lost_contact_threshold=3,
            window_hours=24,
            max_restarts=5,
            cooldown_minutes=120,
        ),
    }
    return restart_settings


@pytest.fixture()
def mock_client_for_profile() -> Mock:
    """Mock client с restaurant AP devices + events."""
    from typing import Any

    client = Mock()
    client.list_devices_raw.return_value = [
        {"mac": "aa:01", "name": "Restoran", "model": "U7IW", "type": "uap", "state": 1},
        {"mac": "aa:02", "name": "Rest Bar", "model": "U7IW", "type": "uap", "state": 1},
        {"mac": "aa:03", "name": "Office", "model": "U7IW", "type": "uap", "state": 1},
    ]

    # Restoran has 5 lost contact events (> threshold 3 → restart)
    # Rest Bar has 1 event (< threshold → skip)
    def events_for_mac(*, mac: str) -> list[dict[str, Any]]:
        if mac == "aa:01":
            return [
                {"key": "EVT_AP_Lost_Contact", "datetime": "2026-05-16T09:00:00Z", "ap": mac}
                for _ in range(5)
            ]
        if mac == "aa:02":
            return [{"key": "EVT_AP_Lost_Contact", "datetime": "2026-05-16T09:00:00Z", "ap": mac}]
        return []

    client.list_events_raw.side_effect = events_for_mac
    client.send_command.return_value = {"meta": {"rc": "ok"}}
    return client


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_profile_restarts_devices_over_threshold(
    profile_settings: Settings,
    mock_client_for_profile: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restoran (5 events > 3) → restart. Rest Bar (1) → skip."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_for_profile, settings=profile_settings)
    report = svc.profile("restaurant", apply=True)

    processed_macs = {a.mac for a in report.actions if a.status == "success"}
    assert "aa:01" in processed_macs  # over threshold
    assert "aa:02" not in processed_macs  # under threshold


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_profile_excludes_office_ap(
    profile_settings: Settings,
    mock_client_for_profile: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Office AP не в filter_names → не процессим вообще."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_for_profile, settings=profile_settings)
    report = svc.profile("restaurant", apply=True)

    processed_macs = {a.mac for a in report.actions}
    assert "aa:03" not in processed_macs  # not in filter_names


@pytest.mark.fast()
def test_profile_unknown_name_raises(profile_settings: Settings) -> None:
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=Mock(), settings=profile_settings)
    with pytest.raises(ValueError, match="unknown profile"):
        svc.profile("nonexistent", apply=True)


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_profile_dry_run_default(
    profile_settings: Settings,
    mock_client_for_profile: Mock,
) -> None:
    """apply=False (default) → dry_run, no send_command."""
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_for_profile, settings=profile_settings)
    report = svc.profile("restaurant")  # default apply=False

    assert report.dry_run is True
    mock_client_for_profile.send_command.assert_not_called()


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_profile_dry_run_respects_max_restarts(
    profile_settings: Settings,
) -> None:
    """Dry-run preview не должен показывать больше действий, чем выполнит --apply (max_restarts)."""
    from typing import Any

    from unifi_manager.services.restart import RestartService

    # 3 кандидата, все над threshold, но cap = 2
    profile_settings.restart_profiles["restaurant"].filter_names = ["AP1", "AP2", "AP3"]
    profile_settings.restart_profiles["restaurant"].max_restarts = 2

    client = Mock()
    client.list_devices_raw.return_value = [
        {"mac": "aa:01", "name": "AP1", "model": "U7IW", "type": "uap", "state": 1},
        {"mac": "aa:02", "name": "AP2", "model": "U7IW", "type": "uap", "state": 1},
        {"mac": "aa:03", "name": "AP3", "model": "U7IW", "type": "uap", "state": 1},
    ]

    def events_for_mac(*, mac: str) -> list[dict[str, Any]]:
        return [
            {"key": "EVT_AP_Lost_Contact", "datetime": "2026-05-16T09:00:00Z", "ap": mac}
            for _ in range(5)  # все над threshold 3
        ]

    client.list_events_raw.side_effect = events_for_mac

    svc = RestartService(legacy_client=client, settings=profile_settings)
    report = svc.profile("restaurant")  # dry-run default

    assert report.dry_run is True
    assert len(report.actions) == 2, (
        f"dry-run must cap at max_restarts=2 to match --apply, got {len(report.actions)}"
    )


@pytest.mark.fast()
def test_profile_permissions_disabled(
    profile_settings: Settings,
    mock_client_for_profile: Mock,
) -> None:
    """permissions.cli.restart.profile_apply=false → skip."""
    from unifi_manager.services.restart import RestartService

    profile_settings.permissions.cli.restart.profile_apply = False
    svc = RestartService(legacy_client=mock_client_for_profile, settings=profile_settings)
    report = svc.profile("restaurant", apply=True)

    assert report.status == "skipped_permissions"


# === device() ===


@pytest.mark.fast()
def test_device_dry_run_default(restart_settings: Settings, mock_client_problematic: Mock) -> None:
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.device(mac="aa:bb:cc:dd:ee:01", method="restart")

    assert report.dry_run is True
    mock_client_problematic.send_command.assert_not_called()


@pytest.mark.fast()
def test_device_apply_sends_command(
    restart_settings: Settings, mock_client_problematic: Mock
) -> None:
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.device(mac="aa:bb:cc:dd:ee:01", method="restart", apply=True)

    assert report.dry_run is False
    assert len(report.actions) == 1
    mock_client_problematic.send_command.assert_called_once()


@pytest.mark.fast()
def test_device_unknown_mac_raises(
    restart_settings: Settings, mock_client_problematic: Mock
) -> None:
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    with pytest.raises(ValueError, match="not found"):
        svc.device(mac="ff:ff:ff:ff:ff:ff", method="restart", apply=True)


@pytest.mark.fast()
def test_device_permissions_disabled(
    restart_settings: Settings, mock_client_problematic: Mock
) -> None:
    from unifi_manager.services.restart import RestartService

    restart_settings.permissions.cli.restart.device_apply = False
    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.device(mac="aa:bb:cc:dd:ee:01", method="restart", apply=True)

    assert report.status == "skipped_permissions"


# === filter_patterns regression (Issue 1 from final review) ===


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_profile_filter_patterns_match(
    restart_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D33 review Issue 1: filter_patterns должен фильтровать (regex)."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService
    from unifi_manager.settings import RestartProfile

    restart_settings.restart_profiles = {
        "office": RestartProfile(
            filter_patterns=["^office.*"],
            lost_contact_threshold=2,
            window_hours=24,
        ),
    }

    client = Mock()
    client.list_devices_raw.return_value = [
        {"mac": "aa:01", "name": "office-1", "model": "U7IW", "type": "uap", "state": 1},
        {"mac": "aa:02", "name": "office-2", "model": "U7IW", "type": "uap", "state": 1},
        {"mac": "aa:03", "name": "Restoran", "model": "U7IW", "type": "uap", "state": 1},
    ]
    client.list_events_raw.return_value = [
        {"key": "EVT_AP_Lost_Contact", "datetime": "2026-05-16T09:00:00Z", "ap": "x"}
        for _ in range(5)
    ]
    client.send_command.return_value = {"meta": {"rc": "ok"}}

    svc = RestartService(legacy_client=client, settings=restart_settings)
    report = svc.profile("office", apply=True)

    processed_macs = {a.mac for a in report.actions}
    # office-1 + office-2 match pattern → restarted (over threshold)
    assert "aa:01" in processed_macs
    assert "aa:02" in processed_macs
    # Restoran does NOT match pattern → skip
    assert "aa:03" not in processed_macs


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_profile_exclude_patterns_match(
    restart_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """exclude_patterns (regex) — исключает matching."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService
    from unifi_manager.settings import RestartProfile

    restart_settings.restart_profiles = {
        "all_aps": RestartProfile(
            filter_patterns=[".*"],
            exclude_patterns=["test.*"],
            lost_contact_threshold=2,
        ),
    }

    client = Mock()
    client.list_devices_raw.return_value = [
        {"mac": "aa:01", "name": "Restoran", "model": "U7IW", "type": "uap", "state": 1},
        {"mac": "aa:02", "name": "test-ap", "model": "U7IW", "type": "uap", "state": 1},
    ]
    client.list_events_raw.return_value = [
        {"key": "EVT_AP_Lost_Contact", "datetime": "2026-05-16T09:00:00Z", "ap": "x"}
        for _ in range(5)
    ]
    client.send_command.return_value = {"meta": {"rc": "ok"}}

    svc = RestartService(legacy_client=client, settings=restart_settings)
    report = svc.profile("all_aps", apply=True)

    processed_macs = {a.mac for a in report.actions}
    assert "aa:01" in processed_macs  # Restoran matches .*, not excluded
    assert "aa:02" not in processed_macs  # test-ap matches exclude pattern


# === offline_threshold_min regression (Issue 3 from final review) ===


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_respects_offline_threshold_min(
    restart_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D33 review Issue 3: state=0 AP offline < offline_threshold_min — skip."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    # Set threshold to 15 min
    restart_settings.auto_restart.offline_threshold_min = 15

    # AP offline только 30 секунд (last_seen 30s ago) — должен быть skipped
    # frozen now = 2026-05-16 10:00:00 UTC = epoch 1778925600
    # last_seen 30s ago = 1778925570
    recent_offline_ts = 1778925570

    client = Mock()
    client.list_devices_raw.return_value = [
        {
            "mac": "aa:01",
            "name": "Recent Offline",
            "model": "U7IW",
            "type": "uap",
            "state": 0,
            "last_seen": recent_offline_ts,
        },
    ]
    client.send_command.return_value = {"meta": {"rc": "ok"}}

    svc = RestartService(legacy_client=client, settings=restart_settings)
    report = svc.auto(dry_run=False)

    # Should NOT restart — under offline_threshold_min
    assert len(report.actions) == 0
    client.send_command.assert_not_called()


# === FileLock wiring (Phase 4.5 hardening) ===


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_skipped_when_lock_held(
    restart_settings: Settings,
    mock_client_problematic: Mock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Если другой инстанс держит lock — auto() возвращает skipped_locked, без рестартов.

    Uses a real subprocess so the test is valid on POSIX (fcntl locks are
    per-process; same-process double-acquire is a no-op on Linux).
    """
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    lock_path = restart_settings.auto_restart.statefile.parent / "restart.lock"
    # statefile.parent is tmp_path (created by pytest); ensure the lock dir exists.
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_held_by_other_process(lock_path, tmp_path):
        report = svc.auto(dry_run=False)

    assert report.status == "skipped_locked"
    assert report.actions == []
    mock_client_problematic.send_command.assert_not_called()


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_dry_run_works_even_when_locked(
    restart_settings: Settings, mock_client_problematic: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dry-run НЕ требует lock — preview работает даже во время реального прогона."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.lock import FileLock
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    lock_path = restart_settings.auto_restart.statefile.parent / "restart.lock"

    with FileLock(lock_path, timeout=0):
        report = svc.auto(dry_run=True)

    assert report.dry_run is True
    assert report.status in ("completed", "no_candidates")  # not skipped_locked


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_releases_lock_after_run(
    restart_settings: Settings, mock_client_problematic: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """После auto() lock освобождён — следующий прогон может его взять."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.lock import FileLock
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    svc.auto(dry_run=False)

    lock_path = restart_settings.auto_restart.statefile.parent / "restart.lock"
    with FileLock(lock_path, timeout=0):
        pass  # должно успешно acquire — не raise


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_profile_skipped_when_lock_held(
    profile_settings: Settings,
    mock_client_for_profile: Mock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Uses a real subprocess so the test is valid on POSIX (fcntl locks are
    per-process; same-process double-acquire is a no-op on Linux).
    """
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_for_profile, settings=profile_settings)
    lock_path = profile_settings.auto_restart.statefile.parent / "restart.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_held_by_other_process(lock_path, tmp_path):
        report = svc.profile("restaurant", apply=True)
    assert report.status == "skipped_locked"
    mock_client_for_profile.send_command.assert_not_called()


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_device_skipped_when_lock_held(
    restart_settings: Settings,
    mock_client_problematic: Mock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Uses a real subprocess so the test is valid on POSIX (fcntl locks are
    per-process; same-process double-acquire is a no-op on Linux).
    """
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    lock_path = restart_settings.auto_restart.statefile.parent / "restart.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_held_by_other_process(lock_path, tmp_path):
        report = svc.device(mac="aa:bb:cc:dd:ee:01", method="restart", apply=True)
    assert report.status == "skipped_locked"
    mock_client_problematic.send_command.assert_not_called()


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_saves_after_each_restart(
    restart_settings: Settings,
    mock_client_problematic: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Incremental save — history.save вызывается после каждого record (crash-safety)."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    save_spy = Mock(wraps=svc.history.save)
    monkeypatch.setattr(svc.history, "save", save_spy)

    report = svc.auto(dry_run=False)
    n_success = sum(1 for a in report.actions if a.status == "success")
    # save вызван минимум по разу на каждый успешный restart
    assert save_spy.call_count >= n_success >= 1


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_conn_interrupted_exempted_from_offline_threshold(
    restart_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """state=10 (CONNECTION_INTERRUPTED) immediate action — игнорирует threshold."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    restart_settings.auto_restart.offline_threshold_min = 15

    # state=10 AP, last_seen recent (10s ago) — должен быть restarted даже < threshold
    # frozen now = 2026-05-16 10:00:00 UTC = epoch 1778925600
    # last_seen 10s ago = 1778925590
    client = Mock()
    client.list_devices_raw.return_value = [
        {
            "mac": "aa:01",
            "name": "Just Disconnected",
            "model": "U7IW",
            "type": "uap",
            "state": 10,
            "last_seen": 1778925590,
            "uplink": {"uplink_mac": "sw:99", "uplink_remote_port": 5},
        },
    ]
    client.send_command.return_value = {"meta": {"rc": "ok"}}

    svc = RestartService(legacy_client=client, settings=restart_settings)
    report = svc.auto(dry_run=False)

    assert len(report.actions) == 1
    assert report.actions[0].action == "poe_cycle"  # has uplink → poe_cycle


# === Phase 4.5: new safety branch coverage ===


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_execute_poe_cycle_no_uplink_returns_failure(
    restart_settings: Settings,
) -> None:
    """_execute poe_cycle with ap that has no uplink → (False, 'no uplink info') (line 202)."""
    from unifi_manager.domain.device import AccessPoint
    from unifi_manager.services.restart import RestartService

    client = Mock()
    svc = RestartService(legacy_client=client, settings=restart_settings)

    ap = AccessPoint.model_validate(
        {"mac": "aa:01", "name": "AP-nolink", "model": "U7IW", "type": "uap", "state": 10}
    )
    # No uplink — _execute("poe_cycle", ap) should return (False, "no uplink info")
    success, msg = svc._execute("poe_cycle", ap)
    assert success is False
    assert "no uplink" in msg
    client.send_command.assert_not_called()


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_execute_exception_returns_failure(
    restart_settings: Settings,
) -> None:
    """_execute raises exception in send_command → (False, str(e)) (lines 212-214)."""
    from unifi_manager.domain.device import AccessPoint
    from unifi_manager.services.restart import RestartService

    client = Mock()
    client.send_command.side_effect = RuntimeError("connection refused")
    svc = RestartService(legacy_client=client, settings=restart_settings)

    ap = AccessPoint.model_validate(
        {"mac": "aa:01", "name": "AP", "model": "U7IW", "type": "uap", "state": 10}
    )
    success, msg = svc._execute("restart", ap)
    assert success is False
    assert "connection refused" in msg


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_priority_99_state_skipped(
    restart_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """priority_score >= 99 (state=1 ONLINE) → candidate skipped (lines 132-133)."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    # state=4 (GETTING_READY) → priority_score returns 99 → skip
    # But also classify_action returns None for state=4, so we need state that
    # passes the state==1 filter but hits priority>=99. State=4 gives priority=99.
    client = Mock()
    client.list_devices_raw.return_value = [
        {
            "mac": "aa:01",
            "name": "Getting Ready AP",
            "model": "U7IW",
            "type": "uap",
            "state": 4,  # GETTING_READY → priority_score=99
            "last_seen": 1778920000,  # long time ago
        },
    ]
    svc = RestartService(legacy_client=client, settings=restart_settings)
    report = svc.auto(dry_run=False)

    assert report.status == "no_candidates"  # priority>=99 → skipped → no candidates


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_classify_action_none_skips_ap(
    restart_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """classify_action returns (None, ...) → action skipped in batch (lines 149-150)."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unittest.mock import patch

    from unifi_manager.services.restart import RestartService

    # Use state=0 offline AP (passes priority<99) but monkeypatch classify_action → None
    client = Mock()
    client.list_devices_raw.return_value = [
        {
            "mac": "aa:01",
            "name": "AP1",
            "model": "U7IW",
            "type": "uap",
            "state": 0,
            "last_seen": 1778924600,  # 1000s ago → > offline_threshold_min (15min)
        },
    ]
    client.send_command.return_value = {"meta": {"rc": "ok"}}

    with patch("unifi_manager.services.restart.classify_action", return_value=(None, "skip me")):
        svc = RestartService(legacy_client=client, settings=restart_settings)
        report = svc.auto(dry_run=False)

    # action=None → skipped → no actions despite candidate
    assert len(report.actions) == 0
    client.send_command.assert_not_called()


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_profile_execute_permission_disabled(
    profile_settings: Settings,
    mock_client_for_profile: Mock,
) -> None:
    """profile: permissions.cli.restart.execute=False → skipped_permissions (lines 224-225)."""
    from unifi_manager.services.restart import RestartService

    profile_settings.permissions.cli.restart.execute = False
    svc = RestartService(legacy_client=mock_client_for_profile, settings=profile_settings)
    report = svc.profile("restaurant", apply=False)

    assert report.status == "skipped_permissions"
    mock_client_for_profile.send_command.assert_not_called()


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_profile_dry_run_while_lock_held(
    profile_settings: Settings,
    mock_client_for_profile: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """profile dry-run (apply=False) works even when lock is held — no lock acquired (line 241)."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.lock import FileLock
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_for_profile, settings=profile_settings)
    lock_path = profile_settings.auto_restart.statefile.parent / "restart.lock"
    with FileLock(lock_path, timeout=0):
        report = svc.profile("restaurant", apply=False)

    # dry-run doesn't need lock → should produce dry-run results, not skipped_locked
    assert report.dry_run is True
    assert report.status == "completed"
    mock_client_for_profile.send_command.assert_not_called()


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_profile_apply_true_success_records_history(
    profile_settings: Settings,
    mock_client_for_profile: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """profile apply=True with success → history.record_restart + history.save() (lines 253, 261-262)."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_for_profile, settings=profile_settings)
    save_spy = Mock(wraps=svc.history.save)
    monkeypatch.setattr(svc.history, "save", save_spy)

    report = svc.profile("restaurant", apply=True)

    assert report.dry_run is False
    success_actions = [a for a in report.actions if a.status == "success"]
    assert len(success_actions) >= 1
    assert save_spy.call_count >= 1


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_profile_apply_in_cooldown_skips(
    profile_settings: Settings,
    mock_client_for_profile: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """profile: ap in cooldown → skipped in _profile_locked (line 294)."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.domain.restart_history import RestartHistory
    from unifi_manager.services.restart import RestartService

    # Pre-populate cooldown for "Restoran" (aa:01)
    history = RestartHistory(state_file=profile_settings.auto_restart.statefile)
    history.record_restart(mac="aa:01", name="Restoran", action="restart", reason="prev")
    history.save()

    svc = RestartService(legacy_client=mock_client_for_profile, settings=profile_settings)
    report = svc.profile("restaurant", apply=True)

    # aa:01 is in cooldown → skipped
    processed = {a.mac for a in report.actions}
    assert "aa:01" not in processed


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_device_execute_permission_disabled(
    restart_settings: Settings,
    mock_client_problematic: Mock,
) -> None:
    """device: permissions.cli.restart.execute=False → skipped_permissions (lines 363-364)."""
    from unifi_manager.services.restart import RestartService

    restart_settings.permissions.cli.restart.execute = False
    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.device(mac="aa:bb:cc:dd:ee:01", method="restart", apply=False)

    assert report.status == "skipped_permissions"
    mock_client_problematic.send_command.assert_not_called()


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_device_apply_fail_status_recorded(
    restart_settings: Settings,
    mock_client_problematic: Mock,
) -> None:
    """device apply=True with failed send_command → action status starts with 'fail:' (lines 375-376)."""
    from unifi_manager.services.restart import RestartService

    # Return error rc to trigger fail status
    mock_client_problematic.send_command.return_value = {"meta": {"rc": "error"}}

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.device(mac="aa:bb:cc:dd:ee:01", method="restart", apply=True)

    assert report.dry_run is False
    assert len(report.actions) == 1
    assert report.actions[0].status.startswith("fail:")


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_auto_failed_action_status_recorded(
    restart_settings: Settings,
    mock_client_problematic: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto: failed send_command → action status starts with 'fail:' (no history.save called)."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    # Make all commands fail
    mock_client_problematic.send_command.return_value = {"meta": {"rc": "error"}}

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    save_spy = Mock(wraps=svc.history.save)
    monkeypatch.setattr(svc.history, "save", save_spy)

    report = svc.auto(dry_run=False)

    fail_actions = [a for a in report.actions if a.status.startswith("fail:")]
    assert len(fail_actions) >= 1
    # save NOT called on failure
    save_spy.assert_not_called()


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_profile_skips_non_uap_and_exclude_names(
    restart_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """profile: non-uap type skipped (line 241), exclude_names match skipped (line 253)."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService
    from unifi_manager.settings import RestartProfile

    restart_settings.restart_profiles = {
        "test": RestartProfile(
            exclude_names=["Excluded AP"],
            lost_contact_threshold=2,
            window_hours=24,
        ),
    }

    client = Mock()
    client.list_devices_raw.return_value = [
        {"mac": "sw:01", "name": "Switch", "type": "usw", "state": 0},  # non-uap → line 241
        {
            "mac": "ap:02",
            "name": "Excluded AP",
            "type": "uap",
            "model": "U7IW",
            "state": 1,
        },  # exclude_names → line 253
        {"mac": "ap:03", "name": "Valid AP", "type": "uap", "model": "U7IW", "state": 1},
    ]
    client.list_events_raw.return_value = []
    client.send_command.return_value = {"meta": {"rc": "ok"}}

    svc = RestartService(legacy_client=client, settings=restart_settings)
    report = svc.profile("test", apply=True)

    processed = {a.mac for a in report.actions}
    assert "sw:01" not in processed  # non-uap skipped
    assert "ap:02" not in processed  # excluded by name


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_profile_skips_unparseable_device(
    restart_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """profile: unparseable device → skipped with debug log (lines 261-262)."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService
    from unifi_manager.settings import RestartProfile

    restart_settings.restart_profiles = {
        "test": RestartProfile(lost_contact_threshold=2, window_hours=24),
    }

    client = Mock()
    client.list_devices_raw.return_value = [
        {"type": "uap", "model": "U7IW", "state": 1},  # missing 'mac' → model_validate raises
    ]
    client.list_events_raw.return_value = []

    svc = RestartService(legacy_client=client, settings=restart_settings)
    report = svc.profile("test", apply=True)

    assert report.status == "completed"
    assert len(report.actions) == 0


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_profile_locked_skips_unparseable_event_and_wrong_key(
    profile_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_profile_locked: unparseable event skipped (301-302), wrong key skipped (304)."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    client = Mock()
    client.list_devices_raw.return_value = [
        {"mac": "aa:01", "name": "Restoran", "model": "U7IW", "type": "uap", "state": 1},
    ]
    # Mix: one totally invalid event, one valid but wrong key, none of right key → under threshold
    client.list_events_raw.return_value = [
        "not-a-dict",  # unparseable → caught by except, continue (lines 301-302)
        {
            "key": "EVT_AP_Connected",
            "datetime": "2026-05-16T09:00:00Z",
            "ap": "aa:01",
        },  # wrong key → line 304
    ]

    svc = RestartService(legacy_client=client, settings=profile_settings)
    report = svc.profile("restaurant", apply=True)

    # No AP_LOST_CONTACT events → below threshold → no actions
    assert len(report.actions) == 0


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_profile_max_restarts_cap(
    profile_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """profile max_restarts cap: stop after N successful restarts (line 343 break)."""
    monkeypatch.setattr("unifi_manager.services.restart.INTER_ACTION_DELAY_SECONDS", 0.0)
    from unifi_manager.services.restart import RestartService

    # Override profile to max_restarts=1
    profile_settings.restart_profiles["restaurant"].max_restarts = 1

    client = Mock()
    # Two devices both over threshold
    client.list_devices_raw.return_value = [
        {"mac": "aa:01", "name": "Restoran", "model": "U7IW", "type": "uap", "state": 1},
        {"mac": "aa:02", "name": "Rest Bar", "model": "U7IW", "type": "uap", "state": 1},
    ]
    # Both over threshold
    client.list_events_raw.return_value = [
        {"key": "EVT_AP_Lost_Contact", "datetime": "2026-05-16T09:00:00Z", "ap": "x"}
        for _ in range(5)
    ]
    client.send_command.return_value = {"meta": {"rc": "ok"}}

    svc = RestartService(legacy_client=client, settings=profile_settings)
    report = svc.profile("restaurant", apply=True)

    # max_restarts=1 → only 1 action processed
    assert len(report.actions) == 1


@pytest.mark.fast()
def test_device_unparseable_raises_value_error(restart_settings: Settings) -> None:
    """device(): device found but fails model_validate → ValueError raised (lines 375-376)."""
    from unifi_manager.services.restart import RestartService

    client = Mock()
    client.list_devices_raw.return_value = [
        {"mac": "aa:01", "type": "uap"},  # missing required fields → model_validate raises
    ]

    svc = RestartService(legacy_client=client, settings=restart_settings)
    with pytest.raises(ValueError, match="unparseable"):
        svc.device(mac="aa:01", method="restart", apply=True)


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_offline_minutes_no_last_seen(restart_settings: Settings) -> None:
    """_offline_minutes returns 0.0 when ap.last_seen is None (line 426)."""
    from unifi_manager.domain.device import AccessPoint
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=Mock(), settings=restart_settings)
    ap = AccessPoint.model_validate(
        {"mac": "aa:01", "name": "AP", "model": "U7IW", "type": "uap", "state": 0}
        # no last_seen field → None
    )
    result = svc._offline_minutes(ap)
    assert result == 0.0
