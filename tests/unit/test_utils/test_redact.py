"""Тесты для unifi_manager.utils.redact — общий рекурсивный санитайзер секретов."""

import pytest


@pytest.mark.fast()
def test_is_secret_key_matches_known_tokens() -> None:
    from unifi_manager.utils.redact import is_secret_key

    assert is_secret_key("x_authkey")
    assert is_secret_key("x_aes_gcm")
    assert is_secret_key("x_ssh_hostkey_fingerprint")
    assert is_secret_key("PASSWORD")  # case-insensitive
    assert is_secret_key("private_key")


@pytest.mark.fast()
def test_is_secret_key_keeps_safe_keys() -> None:
    from unifi_manager.utils.redact import is_secret_key

    assert not is_secret_key("mac")
    assert not is_secret_key("name")
    assert not is_secret_key("state")
    assert not is_secret_key("ip")


@pytest.mark.fast()
def test_redact_secrets_drops_top_level_secret_keys() -> None:
    from unifi_manager.utils.redact import redact_secrets

    row = {"mac": "aa:bb", "x_authkey": "SECRET", "name": "AP-01"}
    assert redact_secrets(row) == {"mac": "aa:bb", "name": "AP-01"}


@pytest.mark.fast()
def test_redact_secrets_drops_nested_secret_keys() -> None:
    """SEC8 regression: вложенные секреты (например в uplink) тоже режутся."""
    from unifi_manager.utils.redact import redact_secrets

    row = {
        "mac": "aa:bb",
        "uplink": {"uplink_mac": "cc:dd", "x_authkey": "NESTED", "ssh_key": "SSHSECRET"},
    }
    assert redact_secrets(row) == {"mac": "aa:bb", "uplink": {"uplink_mac": "cc:dd"}}


@pytest.mark.fast()
def test_redact_secrets_recurses_into_lists() -> None:
    from unifi_manager.utils.redact import redact_secrets

    data = [{"mac": "aa:bb", "x_vwirekey": "K"}, {"mac": "cc:dd"}]
    assert redact_secrets(data) == [{"mac": "aa:bb"}, {"mac": "cc:dd"}]


@pytest.mark.fast()
def test_redact_secrets_passes_through_scalars() -> None:
    from unifi_manager.utils.redact import redact_secrets

    assert redact_secrets("plain") == "plain"
    assert redact_secrets(42) == 42
    assert redact_secrets(None) is None
