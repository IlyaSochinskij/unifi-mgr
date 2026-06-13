"""Тесты для unifi_manager.integrations.zabbix."""

import json
from pathlib import Path

import pytest


@pytest.mark.fast()
def test_lld_format_empty_list() -> None:
    """Пустой список устройств → {data: []}."""
    from unifi_manager.integrations.zabbix import format_lld

    assert format_lld([]) == {"data": []}


@pytest.mark.fast()
def test_lld_format_access_point() -> None:
    """AccessPoint → запись с {#NAME}, {#MAC}, {#MODEL} (real_model!), {#TYPE}, {#STATE}."""
    from unifi_manager.domain.device import AccessPoint
    from unifi_manager.integrations.zabbix import format_lld

    ap = AccessPoint.model_validate(
        {
            "mac": "aa:bb:cc:dd:ee:01",
            "name": "Restoran",
            "model": "U7IW",
            "sysid": 58759,  # → UAP-AC-IW
            "type": "uap",
            "state": 1,
        }
    )
    result = format_lld([ap])
    assert len(result["data"]) == 1
    entry = result["data"][0]
    assert entry["{#NAME}"] == "Restoran"
    assert entry["{#MAC}"] == "aa:bb:cc:dd:ee:01"
    assert entry["{#MODEL}"] == "UAP-AC-IW"  # real_model, не reported "U7IW"
    assert entry["{#TYPE}"] == "uap"
    assert entry["{#STATE}"] == "1"


@pytest.mark.fast()
def test_lld_format_switch() -> None:
    from unifi_manager.domain.device import Switch
    from unifi_manager.integrations.zabbix import format_lld

    sw = Switch.model_validate(
        {
            "mac": "aa:bb:cc:dd:ee:99",
            "name": "Core Switch",
            "model": "US-24-250W",
            "type": "usw",
            "state": 1,
        }
    )
    result = format_lld([sw])
    entry = result["data"][0]
    assert entry["{#TYPE}"] == "usw"
    assert entry["{#MODEL}"] == "US-24-250W"


@pytest.mark.fast()
def test_lld_format_unnamed_uses_mac() -> None:
    """Если name=None — {#NAME} = MAC."""
    from unifi_manager.domain.device import AccessPoint
    from unifi_manager.integrations.zabbix import format_lld

    ap = AccessPoint.model_validate(
        {
            "mac": "aa:bb:cc:dd:ee:01",
            "model": "U7IW",
            "type": "uap",
        }
    )
    result = format_lld([ap])
    assert result["data"][0]["{#NAME}"] == "aa:bb:cc:dd:ee:01"


@pytest.mark.fast()
def test_lld_full_response_matches_fixture(fixtures_dir: Path) -> None:
    """End-to-end: 2 устройства парсятся в expected JSON."""
    from unifi_manager.domain.device import AccessPoint, Switch
    from unifi_manager.integrations.zabbix import format_lld

    ap = AccessPoint.model_validate(
        {
            "mac": "aa:bb:cc:dd:ee:01",
            "name": "Restoran",
            "model": "U7IW",
            "sysid": 58759,
            "type": "uap",
            "state": 1,
        }
    )
    sw = Switch.model_validate(
        {
            "mac": "aa:bb:cc:dd:ee:99",
            "name": "Core Switch",
            "model": "US-24-250W",
            "type": "usw",
            "state": 1,
        }
    )
    result = format_lld([ap, sw])
    expected = json.loads((fixtures_dir / "zabbix_lld_expected.json").read_text(encoding="utf-8"))
    assert result == expected
