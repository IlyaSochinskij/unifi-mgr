"""Тесты для unifi_manager.services.audit.AuditService."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from unifi_manager.settings import Settings, ThresholdsSettings, UnifiAuthSettings


@pytest.fixture()
def thresholds() -> ThresholdsSettings:
    return ThresholdsSettings(
        critical_temp_c=70,
        critical_poe_percent=90,
        high_cu_percent=50,
    )


@pytest.fixture()
def audit_settings(thresholds: ThresholdsSettings) -> Settings:
    return Settings(
        unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="test"),
        thresholds=thresholds,
    )


@pytest.fixture()
def mock_legacy_with_critical_devices(fixtures_dir: Path) -> Mock:
    """Mock LegacyClient возвращающий audit_critical_sample.json devices."""
    raw = json.loads((fixtures_dir / "audit_critical_sample.json").read_text(encoding="utf-8"))
    client = Mock()
    client.list_devices_raw.return_value = raw["data"]
    return client


# === AuditService.critical() ===


@pytest.mark.fast()
def test_critical_returns_no_issues_on_clean_state(audit_settings: Settings) -> None:
    """Все устройства online + температура ОК → пустой list issues."""
    from unifi_manager.services.audit import AuditService

    client = Mock()
    client.list_devices_raw.return_value = [
        {"mac": "aa:bb", "model": "U7IW", "type": "uap", "state": 1, "name": "OK AP"},
    ]
    svc = AuditService(legacy_client=client, settings=audit_settings)
    issues = svc.critical()
    assert issues == []


@pytest.mark.fast()
def test_critical_detects_offline_device(
    audit_settings: Settings, mock_legacy_with_critical_devices: Mock
) -> None:
    """state=0 (offline) → issue."""
    from unifi_manager.services.audit import AuditService

    svc = AuditService(legacy_client=mock_legacy_with_critical_devices, settings=audit_settings)
    issues = svc.critical()
    offline_issues = [i for i in issues if i.issue_type == "offline"]
    assert len(offline_issues) == 1
    assert offline_issues[0].device_mac == "aa:bb:cc:dd:ee:02"


@pytest.mark.fast()
def test_critical_detects_high_temperature(
    audit_settings: Settings, mock_legacy_with_critical_devices: Mock
) -> None:
    """general_temperature > critical_temp_c → issue."""
    from unifi_manager.services.audit import AuditService

    svc = AuditService(legacy_client=mock_legacy_with_critical_devices, settings=audit_settings)
    issues = svc.critical()
    temp_issues = [i for i in issues if i.issue_type == "high_temperature"]
    assert len(temp_issues) == 1
    assert temp_issues[0].device_mac == "aa:bb:cc:dd:ee:99"
    assert temp_issues[0].context["temperature"] == 85


@pytest.mark.fast()
def test_critical_skips_devices_under_threshold(
    audit_settings: Settings, mock_legacy_with_critical_devices: Mock
) -> None:
    """Normal Switch (temp=45) не должен попасть в issues."""
    from unifi_manager.services.audit import AuditService

    svc = AuditService(legacy_client=mock_legacy_with_critical_devices, settings=audit_settings)
    issues = svc.critical()
    macs_with_issues = {i.device_mac for i in issues}
    assert "aa:bb:cc:dd:ee:98" not in macs_with_issues


@pytest.mark.fast()
def test_critical_skips_malformed_device_and_processes_rest(audit_settings: Settings) -> None:
    """EH1: один битый device-payload не должен валить всю cron-проверку алертинга."""
    from unifi_manager.services.audit import AuditService

    client = Mock()
    client.list_devices_raw.return_value = [
        {"type": "uap", "state": 0},  # битый: нет mac/model → ValidationError
        {"mac": "aa:bb:cc:dd:ee:02", "model": "U7IW", "type": "uap", "state": 0, "name": "Off"},
    ]
    svc = AuditService(legacy_client=client, settings=audit_settings)
    issues = svc.critical()  # не должно бросить
    offline = [i for i in issues if i.issue_type == "offline"]
    assert len(offline) == 1
    assert offline[0].device_mac == "aa:bb:cc:dd:ee:02"


@pytest.mark.fast()
def test_light_skips_malformed_client_and_processes_rest(audit_settings: Settings) -> None:
    """SC5: один битый client-payload не должен валить audit light."""
    from unifi_manager.services.audit import AuditService

    client = Mock()
    client.list_clients_raw.return_value = [
        {"hostname": "no-mac"},  # битый: нет mac → ValidationError
        {"mac": "11:22:33:44:55:66", "hostname": "laptop", "ap_mac": "aa:bb"},
    ]
    svc = AuditService(legacy_client=client, settings=audit_settings)
    report = svc.light()  # не должно бросить
    assert report.clients_per_ap == {"aa:bb": 1}


# === AuditService.status() ===


@pytest.mark.fast()
def test_status_returns_inventory_summary(audit_settings: Settings) -> None:
    """status() возвращает сводку: total devices, online, offline по типам."""
    from unifi_manager.services.audit import AuditService

    client = Mock()
    client.list_devices_raw.return_value = [
        {"mac": "aa:01", "model": "U7IW", "type": "uap", "state": 1},
        {"mac": "aa:02", "model": "U7IW", "type": "uap", "state": 1},
        {"mac": "aa:03", "model": "U7IW", "type": "uap", "state": 0},
        {"mac": "aa:99", "model": "US-24-250W", "type": "usw", "state": 1},
    ]
    svc = AuditService(legacy_client=client, settings=audit_settings)
    status = svc.status()
    assert status.total == 4
    assert status.online == 3
    assert status.offline == 1
    assert status.by_type == {"uap": 3, "usw": 1}


@pytest.mark.fast()
def test_status_empty_inventory(audit_settings: Settings) -> None:
    from unifi_manager.services.audit import AuditService

    client = Mock()
    client.list_devices_raw.return_value = []
    svc = AuditService(legacy_client=client, settings=audit_settings)
    status = svc.status()
    assert status.total == 0
    assert status.online == 0
    assert status.offline == 0


# === AuditService.light() — MAC analysis ===


@pytest.mark.fast()
def test_light_detects_duplicate_macs(audit_settings: Settings, fixtures_dir: Path) -> None:
    """Два клиента с одинаковым MAC → duplicate issue."""
    from unifi_manager.services.audit import AuditService

    raw = json.loads((fixtures_dir / "mac_duplicates_sample.json").read_text(encoding="utf-8"))
    client = Mock()
    client.list_clients_raw.return_value = raw["data"]
    client.list_devices_raw.return_value = []

    svc = AuditService(legacy_client=client, settings=audit_settings)
    report = svc.light()

    dup_macs = [d.mac for d in report.duplicate_macs]
    assert "11:22:33:44:55:66" in dup_macs


@pytest.mark.fast()
def test_light_detects_locally_administered_mac(
    audit_settings: Settings, fixtures_dir: Path
) -> None:
    """MAC с bit 0x02 в первом байте — locally administered (potential spoof)."""
    from unifi_manager.services.audit import AuditService

    raw = json.loads((fixtures_dir / "mac_duplicates_sample.json").read_text(encoding="utf-8"))
    client = Mock()
    client.list_clients_raw.return_value = raw["data"]
    client.list_devices_raw.return_value = []

    svc = AuditService(legacy_client=client, settings=audit_settings)
    report = svc.light()

    spoof_macs = [s.mac for s in report.locally_administered]
    assert "02:00:00:11:22:33" in spoof_macs


@pytest.mark.fast()
def test_light_counts_clients_per_ap(audit_settings: Settings, fixtures_dir: Path) -> None:
    """Сколько клиентов на каждой AP — для выявления перекосов."""
    from unifi_manager.services.audit import AuditService

    raw = json.loads((fixtures_dir / "mac_duplicates_sample.json").read_text(encoding="utf-8"))
    client = Mock()
    client.list_clients_raw.return_value = raw["data"]
    client.list_devices_raw.return_value = []

    svc = AuditService(legacy_client=client, settings=audit_settings)
    report = svc.light()

    assert report.clients_per_ap["ap-1"] == 4  # alice, spoof, normal, client-x
    assert report.clients_per_ap["ap-2"] == 1  # duplicate-mac


# === AuditService.full() — both APIs ===


@pytest.mark.fast()
def test_full_uses_both_apis(audit_settings: Settings) -> None:
    """full() запрашивает devices через оба клиента и объединяет данные."""
    from unifi_manager.services.audit import AuditService

    legacy_client = Mock()
    legacy_client.list_devices_raw.return_value = [
        {"mac": "aa:01", "model": "U7IW", "type": "uap", "state": 1, "general_temperature": 40},
    ]
    integration_client = Mock()
    integration_client.list_devices_raw.return_value = [
        {
            "id": "x",
            "macAddress": "aa:01",
            "model": "U7IW",
            "state": "ONLINE",
            "ipAddress": "10.3.0.10",
        },
    ]

    svc = AuditService(
        legacy_client=legacy_client,
        integration_client=integration_client,
        settings=audit_settings,
    )
    report = svc.full()
    assert len(report.devices) == 1
    # Объединённое: mac + ip (from Integration) + temp (from Legacy)
    assert report.devices[0]["mac"] == "aa:01"
    assert (
        report.devices[0].get("ip") == "10.3.0.10"
        or report.devices[0].get("ipAddress") == "10.3.0.10"
    )


@pytest.mark.fast()
def test_full_merges_mac_case_insensitively(audit_settings: Settings) -> None:
    """Legacy (lower) и Integration (UPPER) MAC одного устройства → один merged dict.

    Регрессия: без нормализации ключа дедупа устройство дублировалось в выводе.
    """
    from unifi_manager.services.audit import AuditService

    legacy_client = Mock()
    legacy_client.list_devices_raw.return_value = [
        {"mac": "aa:bb:cc:dd:ee:01", "model": "U7IW", "type": "uap", "state": 1},
    ]
    integration_client = Mock()
    integration_client.list_devices_raw.return_value = [
        {"id": "x", "macAddress": "AA:BB:CC:DD:EE:01", "ipAddress": "10.3.0.10"},
    ]

    svc = AuditService(
        legacy_client=legacy_client,
        integration_client=integration_client,
        settings=audit_settings,
    )
    report = svc.full()
    assert len(report.devices) == 1
    merged = report.devices[0]
    # Legacy-поля сохранены, Integration-поля домержены
    assert merged["mac"] == "aa:bb:cc:dd:ee:01"
    assert merged.get("ipAddress") == "10.3.0.10"


@pytest.mark.fast()
def test_full_works_without_integration_client(audit_settings: Settings) -> None:
    """Если integration_client=None — работаем только с Legacy данными."""
    from unifi_manager.services.audit import AuditService

    legacy_client = Mock()
    legacy_client.list_devices_raw.return_value = [
        {"mac": "aa:01", "model": "U7IW", "type": "uap", "state": 1},
    ]

    svc = AuditService(
        legacy_client=legacy_client,
        integration_client=None,
        settings=audit_settings,
    )
    report = svc.full()
    assert len(report.devices) == 1


@pytest.mark.fast()
def test_full_works_without_legacy_client(audit_settings: Settings) -> None:
    """Integration-only: legacy_client=None → full() работает через Integration, не трогая legacy."""
    from unifi_manager.services.audit import AuditService

    integration_client = Mock()
    integration_client.list_devices_raw.return_value = [
        {
            "id": "x",
            "macAddress": "aa:01",
            "model": "U7IW",
            "state": "ONLINE",
            "ipAddress": "10.3.0.10",
        },
    ]

    svc = AuditService(
        legacy_client=None,
        integration_client=integration_client,
        settings=audit_settings,
    )
    report = svc.full()
    assert len(report.devices) == 1
    assert report.devices[0]["macAddress"] == "aa:01"
    integration_client.list_devices_raw.assert_called_once()


# === AuditService.trends() — historical analysis ===


@pytest.mark.fast()
def test_trends_parses_recent_reports(audit_settings: Settings, fixtures_dir: Path) -> None:
    """trends читает .txt файлы из reports_dir, парсит ключевые метрики."""
    from unifi_manager.services.audit import AuditService

    # Подменяем reports_dir на fixtures_dir для теста
    audit_settings.paths.reports_dir = fixtures_dir

    client = Mock()
    svc = AuditService(legacy_client=client, settings=audit_settings)
    report = svc.trends(days=7)

    # Минимум 2 файла найдены (day1, day2)
    assert len(report.data_points) >= 2
    # Проверка что числа извлеклись
    totals = [d.get("total") for d in report.data_points]
    assert 270 in totals
    assert 271 in totals


@pytest.mark.fast()
def test_trends_empty_directory(audit_settings: Settings, tmp_path: Path) -> None:
    """Пустая reports_dir → пустой report (не ошибка)."""
    from unifi_manager.services.audit import AuditService

    audit_settings.paths.reports_dir = tmp_path
    client = Mock()
    svc = AuditService(legacy_client=client, settings=audit_settings)
    report = svc.trends(days=7)
    assert report.data_points == []
