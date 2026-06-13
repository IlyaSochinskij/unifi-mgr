"""Тесты для unifi_manager.domain.client."""

import pytest


@pytest.mark.fast()
def test_wireless_client_basic_parse() -> None:
    from unifi_manager.domain.client import WirelessClient

    c = WirelessClient.model_validate(
        {
            "mac": "11:22:33:44:55:66",
            "hostname": "user-laptop",
            "ip": "10.3.0.42",
            "ap_mac": "aa:bb:cc:dd:ee:01",
            "signal": -55,
            "rx_bytes": 1024,
            "tx_bytes": 2048,
        }
    )
    assert c.mac == "11:22:33:44:55:66"
    assert c.hostname == "user-laptop"
    assert c.ip == "10.3.0.42"
    assert c.signal == -55


@pytest.mark.fast()
def test_wireless_client_minimal() -> None:
    """Только mac обязателен."""
    from unifi_manager.domain.client import WirelessClient

    c = WirelessClient.model_validate({"mac": "11:22:33:44:55:66"})
    assert c.mac == "11:22:33:44:55:66"
    assert c.hostname is None
    assert c.ip is None


@pytest.mark.fast()
def test_wireless_client_extra_preserved() -> None:
    from unifi_manager.domain.client import WirelessClient

    c = WirelessClient.model_validate(
        {
            "mac": "11:22:33:44:55:66",
            "new_unifi_field": "future-value",
        }
    )
    assert c.model_extra is not None
    assert c.model_extra["new_unifi_field"] == "future-value"
