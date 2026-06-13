"""Тесты для unifi_manager.domain.device."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError


@pytest.mark.fast()
def test_sysid_map_contains_known_models() -> None:
    """SYSID_MAP — константа с маппингом sysid → реальное имя модели.

    Перенесена из infra/external_repos/.../diagnostics/infra_deep_v2.py
    где была единственной точкой её определения.
    """
    from unifi_manager.domain.device import SYSID_MAP

    assert SYSID_MAP[58759] == "UAP-AC-IW"
    assert SYSID_MAP[58679] == "UAP-AC-Pro"
    assert SYSID_MAP[58727] == "UAP-AC-M"
    assert SYSID_MAP[58711] == "UAP-AC-M-Pro"


@pytest.mark.fast()
def test_access_point_basic_parse() -> None:
    from unifi_manager.domain.device import AccessPoint

    ap = AccessPoint.model_validate(
        {
            "mac": "aa:bb:cc:dd:ee:01",
            "model": "U7IW",
            "sysid": 58759,
        }
    )
    assert ap.mac == "aa:bb:cc:dd:ee:01"
    assert ap.reported_model == "U7IW"
    assert ap.sysid == 58759


@pytest.mark.fast()
def test_access_point_real_model_via_sysid() -> None:
    """sysid известен → real_model = маппинг, не reported_model."""
    from unifi_manager.domain.device import AccessPoint

    ap = AccessPoint.model_validate(
        {
            "mac": "aa:bb:cc:dd:ee:01",
            "model": "U7IW",  # UniFi сообщает неправильно
            "sysid": 58759,
        }
    )
    assert ap.reported_model == "U7IW"
    assert ap.real_model == "UAP-AC-IW"  # реальная модель из SYSID_MAP


@pytest.mark.fast()
def test_access_point_real_model_fallback_to_reported() -> None:
    """sysid отсутствует или неизвестен → real_model = reported_model."""
    from unifi_manager.domain.device import AccessPoint

    ap = AccessPoint.model_validate(
        {
            "mac": "aa:bb:cc:dd:ee:02",
            "model": "U7PG2",
            "sysid": 999999,  # неизвестный
        }
    )
    assert ap.real_model == "U7PG2"

    ap2 = AccessPoint.model_validate(
        {
            "mac": "aa:bb:cc:dd:ee:03",
            "model": "U6-LR",
            # sysid отсутствует
        }
    )
    assert ap2.real_model == "U6-LR"


@pytest.mark.fast()
def test_access_point_extra_fields_preserved() -> None:
    """extra='allow' → новые поля UniFi сохраняются в model_extra без потерь."""
    from unifi_manager.domain.device import AccessPoint

    ap = AccessPoint.model_validate(
        {
            "mac": "aa:bb:cc:dd:ee:01",
            "model": "U7IW",
            "sysid": 58759,
            "future_field_from_new_unifi_version": {"x": 42},
            "another_unknown": "value",
        }
    )
    assert ap.model_extra is not None
    assert ap.model_extra["future_field_from_new_unifi_version"] == {"x": 42}
    assert ap.model_extra["another_unknown"] == "value"


@pytest.mark.fast()
def test_access_point_missing_mac_raises() -> None:
    """mac — обязательное поле."""
    from unifi_manager.domain.device import AccessPoint

    with pytest.raises(ValidationError) as exc_info:
        AccessPoint.model_validate({"model": "U7IW"})
    assert "mac" in str(exc_info.value)


@pytest.mark.fast()
def test_access_point_uplink_optional() -> None:
    from unifi_manager.domain.device import AccessPoint

    ap = AccessPoint.model_validate(
        {
            "mac": "aa:bb:cc:dd:ee:01",
            "model": "U7IW",
        }
    )
    assert ap.uplink is None


@pytest.mark.fast()
def test_access_point_uplink_parsed() -> None:
    from unifi_manager.domain.device import AccessPoint

    ap = AccessPoint.model_validate(
        {
            "mac": "aa:bb:cc:dd:ee:01",
            "model": "U7IW",
            "uplink": {
                "uplink_mac": "aa:bb:cc:dd:ee:99",
                "uplink_remote_port": 5,
            },
        }
    )
    assert ap.uplink is not None
    assert ap.uplink.uplink_mac == "aa:bb:cc:dd:ee:99"
    assert ap.uplink.uplink_remote_port == 5


@pytest.mark.fast()
def test_switch_basic_parse() -> None:
    from unifi_manager.domain.device import Switch

    sw = Switch.model_validate(
        {
            "mac": "aa:bb:cc:dd:ee:99",
            "model": "US-24-250W",
            "name": "Core Switch",
            "general_temperature": 45,
            "port_table": [
                {"port_idx": 1, "rx_errors": 0, "tx_errors": 0},
            ],
        }
    )
    assert sw.mac == "aa:bb:cc:dd:ee:99"
    assert sw.general_temperature == 45
    assert len(sw.port_table) == 1
    assert sw.port_table[0].port_idx == 1


@pytest.mark.fast()
def test_full_response_parses(fixtures_dir: Path) -> None:
    """Реальный ответ /stat/device парсится без ошибок."""
    from unifi_manager.domain.device import AccessPoint, Switch

    raw = json.loads((fixtures_dir / "stat_device_response.json").read_text(encoding="utf-8"))
    devices = raw["data"]

    # Первое устройство — AP с известным sysid
    ap1 = AccessPoint.model_validate(devices[0])
    assert ap1.real_model == "UAP-AC-IW"

    # Второе — AP с неизвестным sysid
    ap2 = AccessPoint.model_validate(devices[1])
    assert ap2.real_model == "U7PG2"  # fallback

    # Третье — switch
    sw = Switch.model_validate(devices[2])
    assert sw.general_temperature == 45
    assert sw.port_table[1].rx_errors == 12


@pytest.mark.fast()
def test_sysid_gap_warning_logged_once(caplog: pytest.LogCaptureFixture) -> None:
    """D32 refinement: unknown sysid → warning ОДИН раз (не spam)."""
    from unifi_manager.domain import device as device_module
    from unifi_manager.domain.device import AccessPoint

    # Reset state for test isolation
    device_module._WARNED_SYSIDS.clear()

    with caplog.at_level("WARNING"):
        # Same unknown sysid lookup twice
        ap1 = AccessPoint.model_validate({"mac": "aa:01", "model": "Unknown", "sysid": 99999})
        ap2 = AccessPoint.model_validate({"mac": "aa:02", "model": "Unknown", "sysid": 99999})
        _ = ap1.real_model
        _ = ap2.real_model

    sysid_gap_records = [r for r in caplog.records if "sysid_gap" in r.message]
    assert len(sysid_gap_records) == 1  # only one warning per sysid
