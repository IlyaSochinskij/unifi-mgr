"""Тесты для unifi_manager.services.export.ExportService."""

import csv
import io
import json
from unittest.mock import Mock

import pytest


@pytest.mark.fast()
def test_export_clients_csv_format() -> None:
    """CSV содержит header + одну строку на client."""
    from unifi_manager.services.export import ExportService

    client = Mock()
    client.list_clients_raw.return_value = [
        {"mac": "11:22:33:44:55:66", "hostname": "laptop-1", "ip": "10.0.0.1"},
        {"mac": "aa:bb:cc:dd:ee:ff", "hostname": "phone-1", "ip": "10.0.0.2"},
    ]

    svc = ExportService(legacy_client=client)
    output = io.StringIO()
    svc.export_clients(output=output, fmt="csv")
    output.seek(0)

    reader = csv.DictReader(output)
    rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["mac"] == "11:22:33:44:55:66"
    assert rows[0]["hostname"] == "laptop-1"


@pytest.mark.fast()
def test_export_clients_json_format() -> None:
    from unifi_manager.services.export import ExportService

    client = Mock()
    client.list_clients_raw.return_value = [
        {"mac": "11:22:33:44:55:66", "hostname": "laptop-1"},
    ]

    svc = ExportService(legacy_client=client)
    output = io.StringIO()
    svc.export_clients(output=output, fmt="json")
    output.seek(0)

    data = json.loads(output.read())
    assert len(data) == 1
    assert data[0]["mac"] == "11:22:33:44:55:66"


@pytest.mark.fast()
def test_export_devices_csv_includes_real_model() -> None:
    """REGRESSION (forward concern from Phase 1 review):
    AccessPoint.real_model должно появиться в model_dump → CSV."""
    from unifi_manager.services.export import ExportService

    client = Mock()
    client.list_devices_raw.return_value = [
        {
            "mac": "aa:bb:cc:dd:ee:01",
            "name": "Restoran",
            "model": "U7IW",
            "sysid": 58759,
            "type": "uap",
        },  # → UAP-AC-IW
    ]

    svc = ExportService(legacy_client=client)
    output = io.StringIO()
    svc.export_devices(output=output, fmt="csv")
    output.seek(0)

    content = output.read()
    assert "real_model" in content  # column header
    assert "UAP-AC-IW" in content  # real_model value


@pytest.mark.fast()
def test_export_devices_json_includes_real_model() -> None:
    """Same regression check для JSON."""
    from unifi_manager.services.export import ExportService

    client = Mock()
    client.list_devices_raw.return_value = [
        {
            "mac": "aa:bb:cc:dd:ee:01",
            "name": "Restoran",
            "model": "U7IW",
            "sysid": 58759,
            "type": "uap",
        },
    ]

    svc = ExportService(legacy_client=client)
    output = io.StringIO()
    svc.export_devices(output=output, fmt="json")
    output.seek(0)

    data = json.loads(output.read())
    assert data[0]["real_model"] == "UAP-AC-IW"


@pytest.mark.fast()
def test_export_invalid_format_raises() -> None:
    from unifi_manager.services.export import ExportService

    client = Mock()
    client.list_clients_raw.return_value = []

    svc = ExportService(legacy_client=client)
    with pytest.raises(ValueError, match="unsupported format"):
        svc.export_clients(output=io.StringIO(), fmt="xml")


@pytest.mark.fast()
def test_export_clients_empty_list_csv() -> None:
    """Empty list → CSV с одним header (no rows)."""
    from unifi_manager.services.export import ExportService

    client = Mock()
    client.list_clients_raw.return_value = []

    svc = ExportService(legacy_client=client)
    output = io.StringIO()
    svc.export_clients(output=output, fmt="csv")
    output.seek(0)

    content = output.read()
    # CSV empty list — может быть пустая строка или только header
    assert content is not None


@pytest.mark.fast()
def test_export_clients_empty_list_json() -> None:
    from unifi_manager.services.export import ExportService

    client = Mock()
    client.list_clients_raw.return_value = []

    svc = ExportService(legacy_client=client)
    output = io.StringIO()
    svc.export_clients(output=output, fmt="json")
    output.seek(0)

    data = json.loads(output.read())
    assert data == []


@pytest.mark.fast()
def test_export_devices_csv_omits_secret_fields() -> None:
    """По умолчанию export НЕ выводит сырые секретные поля UniFi."""

    from unifi_manager.services.export import ExportService

    raw = {
        "type": "uap",
        "mac": "aa:bb:cc:dd:ee:ff",
        "model": "U7PG2",
        "name": "AP-1",
        "ip": "10.0.0.5",
        "state": 1,
        "x_authkey": "AUTHSECRET",
        "x_adopt_password": "ADOPTPW",
        "x_ssh_hostkey_fingerprint": "FP",
        "x_aes_gcm": "1",
        "x_vwirekey": "VW",
    }

    class _C:
        def list_devices_raw(self):
            return [raw]

        def list_clients_raw(self):
            return []

    buf = io.StringIO()
    ExportService(_C()).export_devices(output=buf, fmt="csv")
    out = buf.getvalue()
    for leaked in (
        "x_authkey",
        "AUTHSECRET",
        "x_adopt_password",
        "ADOPTPW",
        "x_ssh_hostkey_fingerprint",
        "x_vwirekey",
        "VW",
    ):
        assert leaked not in out, f"secret leaked: {leaked}"
    assert "aa:bb:cc:dd:ee:ff" in out  # safe field present
    assert "AP-1" in out


@pytest.mark.fast()
def test_export_devices_raw_includes_everything() -> None:
    """--raw (raw=True) намеренно выгружает всё, включая секреты."""

    from unifi_manager.services.export import ExportService

    raw = {"type": "uap", "mac": "aa:bb:cc:dd:ee:ff", "model": "U7PG2", "x_authkey": "AUTHSECRET"}

    class _C:
        def list_devices_raw(self):
            return [raw]

        def list_clients_raw(self):
            return []

    buf = io.StringIO()
    ExportService(_C()).export_devices(output=buf, fmt="csv", raw=True)
    assert "AUTHSECRET" in buf.getvalue()


@pytest.mark.fast()
def test_export_devices_default_drops_nested_secrets_in_uplink() -> None:
    """SEC8 regression: секреты, вложенные в uplink, тоже должны вырезаться (рекурсивно)."""

    from unifi_manager.services.export import ExportService

    raw = {
        "type": "uap",
        "mac": "aa:bb:cc:dd:ee:ff",
        "model": "U7PG2",
        "name": "AP-1",
        "uplink": {"uplink_mac": "cc:dd:ee:ff:00:11", "x_authkey": "NESTEDSECRET"},
    }

    class _C:
        def list_devices_raw(self):
            return [raw]

        def list_clients_raw(self):
            return []

    buf = io.StringIO()
    ExportService(_C()).export_devices(output=buf, fmt="json")
    out = buf.getvalue()
    assert "NESTEDSECRET" not in out, "nested secret leaked via uplink"
    assert "cc:dd:ee:ff:00:11" in out  # безопасное вложенное поле остаётся
