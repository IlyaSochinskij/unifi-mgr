"""Тесты для unifi_manager.clients.base.BaseUnifiClient."""

import pytest
import responses

from unifi_manager.clients.exceptions import UnifiAPIError, UnifiTimeoutError
from unifi_manager.settings import Settings


@pytest.fixture()
def client(minimal_unifi_settings: Settings) -> "BaseUnifiClient":  # noqa: F821
    from unifi_manager.clients.base import BaseUnifiClient

    return BaseUnifiClient(minimal_unifi_settings.unifi)


@pytest.mark.fast()
def test_base_client_initializes_with_settings(minimal_unifi_settings: Settings) -> None:
    from unifi_manager.clients.base import BaseUnifiClient

    c = BaseUnifiClient(minimal_unifi_settings.unifi)
    assert c.base_url == "https://192.0.2.1:11443"


@pytest.mark.fast()
def test_base_client_ssl_verify_default_true(minimal_unifi_settings: Settings) -> None:
    """verify_ssl=True по умолчанию (secure by default)."""
    from unifi_manager.clients.base import BaseUnifiClient

    c = BaseUnifiClient(minimal_unifi_settings.unifi)
    assert c.session.verify is True


@pytest.mark.fast()
def test_base_client_ssl_can_be_disabled(minimal_unifi_settings: Settings) -> None:
    """verify_ssl=False (явный opt-out для self-signed UniFi) пробрасывается в session."""
    from unifi_manager.clients.base import BaseUnifiClient

    minimal_unifi_settings.unifi.verify_ssl = False
    c = BaseUnifiClient(minimal_unifi_settings.unifi)
    assert c.session.verify is False


@pytest.mark.fast()
@responses.activate
def test_get_returns_json_on_success(client: "BaseUnifiClient") -> None:  # noqa: F821
    responses.get(
        "https://192.0.2.1:11443/some/path",
        json={"meta": {"rc": "ok"}, "data": [{"x": 1}]},
        status=200,
    )
    result = client.get_json("/some/path")
    assert result == {"meta": {"rc": "ok"}, "data": [{"x": 1}]}


@pytest.mark.fast()
@responses.activate
def test_get_retries_on_5xx_then_succeeds(client: "BaseUnifiClient") -> None:  # noqa: F821
    """3 retries: первые 2 раза 503, третий — 200 OK."""
    url = "https://192.0.2.1:11443/some/path"
    responses.get(url, status=503)
    responses.get(url, status=503)
    responses.get(url, json={"data": []}, status=200)

    result = client.get_json("/some/path")
    assert result == {"data": []}
    assert len(responses.calls) == 3


@pytest.mark.fast()
@responses.activate
def test_get_exhausts_retries_raises(client: "BaseUnifiClient") -> None:  # noqa: F821
    """После 3 ретраев 503 — UnifiAPIError со status=503."""
    url = "https://192.0.2.1:11443/some/path"
    for _ in range(3):
        responses.get(url, status=503, body="Service Unavailable")

    with pytest.raises(UnifiAPIError) as exc_info:
        client.get_json("/some/path")
    assert exc_info.value.status_code == 503
    assert len(responses.calls) == 3


@pytest.mark.fast()
@responses.activate
def test_get_4xx_does_not_retry(client: "BaseUnifiClient") -> None:  # noqa: F821
    """401/403/404 — без retry, сразу UnifiAPIError."""
    responses.get(
        "https://192.0.2.1:11443/some/path",
        status=401,
        body="Unauthorized",
    )

    with pytest.raises(UnifiAPIError) as exc_info:
        client.get_json("/some/path")
    assert exc_info.value.status_code == 401
    assert len(responses.calls) == 1  # NO retry


@pytest.mark.fast()
@responses.activate
def test_post_returns_json(client: "BaseUnifiClient") -> None:  # noqa: F821
    responses.post(
        "https://192.0.2.1:11443/cmd/devmgr",
        json={"meta": {"rc": "ok"}},
        status=200,
    )
    result = client.post_json("/cmd/devmgr", json_body={"cmd": "restart"})
    assert result == {"meta": {"rc": "ok"}}


@pytest.mark.fast()
@responses.activate
def test_post_with_retry(client: "BaseUnifiClient") -> None:  # noqa: F821
    url = "https://192.0.2.1:11443/cmd/devmgr"
    responses.post(url, status=502)
    responses.post(url, json={"meta": {"rc": "ok"}}, status=200)

    result = client.post_json("/cmd/devmgr", json_body={"cmd": "restart"})
    assert result == {"meta": {"rc": "ok"}}
    assert len(responses.calls) == 2


@pytest.mark.fast()
@responses.activate
def test_get_timeout_raises(client: "BaseUnifiClient") -> None:  # noqa: F821
    """Connection timeout → UnifiTimeoutError после retries."""
    import requests

    url = "https://192.0.2.1:11443/some/path"
    responses.get(url, body=requests.exceptions.ConnectTimeout("timed out"))
    responses.get(url, body=requests.exceptions.ConnectTimeout("timed out"))
    responses.get(url, body=requests.exceptions.ConnectTimeout("timed out"))

    with pytest.raises(UnifiTimeoutError):
        client.get_json("/some/path")


@pytest.mark.fast()
@responses.activate
def test_get_connection_error_retries_then_raises(client: "BaseUnifiClient") -> None:  # noqa: F821
    """Сетевая ошибка (не Timeout) исчерпывает retries → UnifiAPIError."""
    import requests

    url = "https://192.0.2.1:11443/some/path"
    for _ in range(3):
        responses.get(url, body=requests.exceptions.ConnectionError("connection refused"))

    with pytest.raises(UnifiAPIError):
        client.get_json("/some/path")
    assert len(responses.calls) == 3


@pytest.mark.fast()
@responses.activate
def test_get_non_json_response_raises(client: "BaseUnifiClient") -> None:  # noqa: F821
    """2xx с не-JSON телом → UnifiAPIError."""
    responses.get(
        "https://192.0.2.1:11443/some/path",
        body=b"<html>not json</html>",
        status=200,
        content_type="text/html",
    )

    with pytest.raises(UnifiAPIError) as exc_info:
        client.get_json("/some/path")
    assert exc_info.value.status_code == 200


@pytest.mark.fast()
def test_base_client_ssl_verify_path(minimal_unifi_settings: Settings) -> None:
    """verify_ssl=Path → session.verify is set to string path (base.py line 57)."""
    from pathlib import Path

    from unifi_manager.clients.base import BaseUnifiClient

    ca_path = Path("/etc/ssl/ca.pem")
    minimal_unifi_settings.unifi.verify_ssl = ca_path  # type: ignore[assignment]
    c = BaseUnifiClient(minimal_unifi_settings.unifi)
    assert c.session.verify == str(ca_path)
