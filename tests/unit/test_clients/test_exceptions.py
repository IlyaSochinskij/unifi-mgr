"""Тесты для unifi_manager.clients.exceptions."""

import pytest


@pytest.mark.fast()
def test_unifi_error_is_base() -> None:
    from unifi_manager.clients.exceptions import UnifiError

    assert issubclass(UnifiError, Exception)


@pytest.mark.fast()
def test_unifi_auth_error_inherits_unifi_error() -> None:
    from unifi_manager.clients.exceptions import UnifiAuthError, UnifiError

    assert issubclass(UnifiAuthError, UnifiError)


@pytest.mark.fast()
def test_unifi_api_error_inherits_unifi_error() -> None:
    from unifi_manager.clients.exceptions import UnifiAPIError, UnifiError

    assert issubclass(UnifiAPIError, UnifiError)


@pytest.mark.fast()
def test_unifi_timeout_error_inherits_unifi_error() -> None:
    from unifi_manager.clients.exceptions import UnifiError, UnifiTimeoutError

    assert issubclass(UnifiTimeoutError, UnifiError)


@pytest.mark.fast()
def test_unifi_api_error_carries_status_code() -> None:
    """UnifiAPIError содержит status_code и body для отладки."""
    from unifi_manager.clients.exceptions import UnifiAPIError

    err = UnifiAPIError("Server error", status_code=500, body='{"error": "internal"}')
    assert err.status_code == 500
    assert err.body == '{"error": "internal"}'
    assert "Server error" in str(err)


@pytest.mark.fast()
def test_unifi_api_error_optional_fields() -> None:
    """status_code и body — optional (default None)."""
    from unifi_manager.clients.exceptions import UnifiAPIError

    err = UnifiAPIError("Just message")
    assert err.status_code is None
    assert err.body is None


@pytest.mark.fast()
def test_unifi_auth_error_raisable() -> None:
    from unifi_manager.clients.exceptions import UnifiAuthError

    with pytest.raises(UnifiAuthError, match="bad password"):
        raise UnifiAuthError("bad password")
