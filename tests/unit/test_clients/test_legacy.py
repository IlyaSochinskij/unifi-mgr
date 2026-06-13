"""Тесты для unifi_manager.clients.legacy.LegacyClient."""

import pytest
import responses
from pydantic import SecretStr

from unifi_manager.clients.exceptions import UnifiAuthError
from unifi_manager.settings import Settings, UnifiAuthSettings


@pytest.fixture()
def legacy_settings() -> Settings:
    """Settings с username/password для login."""
    return Settings(
        unifi=UnifiAuthSettings(
            host="192.0.2.1",
            port=11443,
            site="site-1",
            username=SecretStr("unifi_user"),
            password=SecretStr("test-password"),
        )
    )


@pytest.mark.fast()
@responses.activate
def test_login_success_extracts_csrf(legacy_settings: Settings) -> None:
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login",
        json={"meta": {"rc": "ok"}},
        status=200,
        headers={"X-Csrf-Token": "fake-csrf-token-abc123"},
    )

    client = LegacyClient(legacy_settings.unifi)
    assert client.login() is True
    assert client.session.headers.get("X-Csrf-Token") == "fake-csrf-token-abc123"


@pytest.mark.fast()
@responses.activate
def test_login_success_without_csrf_header(legacy_settings: Settings) -> None:
    """Некоторые версии контроллера не возвращают CSRF — это OK, login успешен."""
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login",
        json={"meta": {"rc": "ok"}},
        status=200,
    )

    client = LegacyClient(legacy_settings.unifi)
    assert client.login() is True


@pytest.mark.fast()
@responses.activate
def test_login_401_raises_auth_error(legacy_settings: Settings) -> None:
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login",
        json={"meta": {"rc": "error", "msg": "Invalid credentials"}},
        status=401,
    )

    client = LegacyClient(legacy_settings.unifi)
    with pytest.raises(UnifiAuthError, match="login failed"):
        client.login()


@pytest.mark.fast()
@responses.activate
def test_send_command_does_not_retry_on_server_error(legacy_settings: Settings) -> None:
    """CC2: неидемпотентный POST /cmd/devmgr НЕ должен ретраиться — 502 → один запрос, raise.

    Иначе timeout/5xx после того как контроллер уже принял команду = двойной рестарт.
    """
    from unifi_manager.clients.exceptions import UnifiAPIError
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login", json={"meta": {"rc": "ok"}}, status=200
    )
    responses.post(
        "https://192.0.2.1:11443/proxy/network/api/s/site-1/cmd/devmgr",
        json={"meta": {"rc": "error"}},
        status=502,
    )

    client = LegacyClient(legacy_settings.unifi)
    with pytest.raises(UnifiAPIError):
        client.send_command({"cmd": "restart", "mac": "aa:bb:cc:dd:ee:01"})

    cmd_calls = [c for c in responses.calls if "cmd/devmgr" in c.request.url]
    assert len(cmd_calls) == 1, f"expected no retry on command POST, got {len(cmd_calls)} calls"


@pytest.mark.fast()
@responses.activate
def test_login_sends_credentials(legacy_settings: Settings) -> None:
    """Тело запроса должно содержать username/password из SecretStr."""
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login",
        json={"meta": {"rc": "ok"}},
        status=200,
    )

    client = LegacyClient(legacy_settings.unifi)
    client.login()

    sent_body = responses.calls[0].request.body
    assert b"unifi_user" in sent_body
    assert b"test-password" in sent_body


@pytest.mark.fast()
def test_missing_credentials_raises(minimal_unifi_settings: Settings) -> None:
    """LegacyClient без username/password не может login → raise в login()."""
    from unifi_manager.clients.legacy import LegacyClient

    client = LegacyClient(minimal_unifi_settings.unifi)
    with pytest.raises(UnifiAuthError, match="username and password required"):
        client.login()


@pytest.mark.fast()
@responses.activate
def test_get_devices_uses_proxy_network_path(legacy_settings: Settings) -> None:
    """list_devices_raw() обращается к /proxy/network/api/s/<site>/stat/device."""
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login", json={"meta": {"rc": "ok"}}, status=200
    )
    responses.get(
        "https://192.0.2.1:11443/proxy/network/api/s/site-1/stat/device",
        json={"meta": {"rc": "ok"}, "data": [{"mac": "aa:bb", "model": "U7IW"}]},
        status=200,
    )

    client = LegacyClient(legacy_settings.unifi)
    client.login()
    raw_devices = client.list_devices_raw()
    assert len(raw_devices) == 1
    assert raw_devices[0]["mac"] == "aa:bb"


@pytest.mark.fast()
@responses.activate
def test_get_events_for_mac(legacy_settings: Settings) -> None:
    """list_events_raw фильтрует по mac параметру."""
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login", json={"meta": {"rc": "ok"}}, status=200
    )
    responses.get(
        "https://192.0.2.1:11443/proxy/network/api/s/site-1/stat/event",
        json={"meta": {"rc": "ok"}, "data": [{"key": "EVT_AP_Lost_Contact"}]},
        status=200,
    )

    client = LegacyClient(legacy_settings.unifi)
    client.login()
    events = client.list_events_raw(mac="aa:bb:cc:dd:ee:01")
    assert len(events) == 1


@pytest.mark.fast()
@responses.activate
def test_send_command(legacy_settings: Settings) -> None:
    """send_command POST в /cmd/devmgr."""
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login", json={"meta": {"rc": "ok"}}, status=200
    )
    responses.post(
        "https://192.0.2.1:11443/proxy/network/api/s/site-1/cmd/devmgr",
        json={"meta": {"rc": "ok"}},
        status=200,
    )

    client = LegacyClient(legacy_settings.unifi)
    client.login()
    result = client.send_command({"cmd": "restart", "mac": "aa:bb:cc:dd:ee:01"})
    assert result["meta"]["rc"] == "ok"


@pytest.mark.fast()
@responses.activate
def test_login_network_error_raises_auth_error(legacy_settings: Settings) -> None:
    """Сетевая ошибка во время login → UnifiAuthError."""
    import requests as req

    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login",
        body=req.exceptions.ConnectionError("connection refused"),
    )

    client = LegacyClient(legacy_settings.unifi)
    with pytest.raises(UnifiAuthError, match="login request failed"):
        client.login()


@pytest.mark.fast()
@responses.activate
def test_login_500_raises_auth_error(legacy_settings: Settings) -> None:
    """5xx (non-401/403) status → UnifiAuthError."""
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login",
        json={"meta": {"rc": "error"}},
        status=500,
    )

    client = LegacyClient(legacy_settings.unifi)
    with pytest.raises(UnifiAuthError, match="login failed with status"):
        client.login()


@pytest.mark.fast()
@responses.activate
def test_ensure_logged_in_auto_logins(legacy_settings: Settings) -> None:
    """list_devices_raw без явного login() → auto-login через _ensure_logged_in."""
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login", json={"meta": {"rc": "ok"}}, status=200
    )
    responses.get(
        "https://192.0.2.1:11443/proxy/network/api/s/site-1/stat/device",
        json={"meta": {"rc": "ok"}, "data": []},
        status=200,
    )

    client = LegacyClient(legacy_settings.unifi)
    # no explicit login — should auto-login
    result = client.list_devices_raw()
    assert result == []
    assert len(responses.calls) == 2  # login + device request


@pytest.mark.fast()
@responses.activate
def test_list_events_without_mac(legacy_settings: Settings) -> None:
    """list_events_raw без mac — запрос без query string."""
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login", json={"meta": {"rc": "ok"}}, status=200
    )
    responses.get(
        "https://192.0.2.1:11443/proxy/network/api/s/site-1/stat/event",
        json={"meta": {"rc": "ok"}, "data": [{"key": "EVT_AP_Adopted"}]},
        status=200,
    )

    client = LegacyClient(legacy_settings.unifi)
    client.login()
    events = client.list_events_raw()
    assert len(events) == 1


@pytest.mark.fast()
@responses.activate
def test_list_events_404_for_offline_ap_returns_empty(legacy_settings: Settings) -> None:
    """Offline AP: /stat/event?mac= отдаёт 404 → 'событий нет', не падаем.

    Иначе restart profile крашится ровно когда ресторанная точка оффлайн —
    регресс от legacy-скрипта, который терпел 404 через try/except.
    """
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login", json={"meta": {"rc": "ok"}}, status=200
    )
    responses.get(
        "https://192.0.2.1:11443/proxy/network/api/s/site-1/stat/event",
        json={"meta": {"rc": "error", "msg": "api.err.UnknownDevice"}},
        status=404,
    )

    client = LegacyClient(legacy_settings.unifi)
    client.login()
    assert client.list_events_raw(mac="f4:92:bf:56:5a:46") == []


@pytest.mark.fast()
@responses.activate
def test_list_events_non_404_still_raises(legacy_settings: Settings) -> None:
    """Не-404 ошибка эндпоинта событий по-прежнему raise — real errors не маскируем."""
    from unifi_manager.clients.exceptions import UnifiAPIError
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login", json={"meta": {"rc": "ok"}}, status=200
    )
    responses.get(
        "https://192.0.2.1:11443/proxy/network/api/s/site-1/stat/event",
        json={"meta": {"rc": "error"}},
        status=403,
    )

    client = LegacyClient(legacy_settings.unifi)
    client.login()
    with pytest.raises(UnifiAPIError):
        client.list_events_raw(mac="aa:bb")


@pytest.mark.fast()
@responses.activate
def test_list_clients_raw(legacy_settings: Settings) -> None:
    """list_clients_raw() обращается к /stat/sta."""
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login", json={"meta": {"rc": "ok"}}, status=200
    )
    responses.get(
        "https://192.0.2.1:11443/proxy/network/api/s/site-1/stat/sta",
        json={"meta": {"rc": "ok"}, "data": [{"mac": "de:ad:be:ef:00:01", "hostname": "laptop"}]},
        status=200,
    )

    client = LegacyClient(legacy_settings.unifi)
    client.login()
    clients = client.list_clients_raw()
    assert len(clients) == 1
    assert clients[0]["hostname"] == "laptop"


@pytest.mark.fast()
@responses.activate
def test_extract_data_bad_format_raises(legacy_settings: Settings) -> None:
    """_extract_data с data != list → UnifiAPIError."""
    from unifi_manager.clients.exceptions import UnifiAPIError
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login", json={"meta": {"rc": "ok"}}, status=200
    )
    responses.get(
        "https://192.0.2.1:11443/proxy/network/api/s/site-1/stat/sta",
        json={"meta": {"rc": "ok"}, "data": "not-a-list"},
        status=200,
    )

    client = LegacyClient(legacy_settings.unifi)
    client.login()
    with pytest.raises(UnifiAPIError, match="unexpected response format"):
        client.list_clients_raw()
