"""Тесты для unifi_manager.clients.integration.IntegrationClient."""

import json
from pathlib import Path

import pytest
import responses
from pydantic import SecretStr

from unifi_manager.clients.exceptions import UnifiAuthError
from unifi_manager.settings import Settings, UnifiAuthSettings

SITE_UUID = "bbffb94c-1234-5678-9abc-def012345678"


@pytest.fixture()
def integration_settings() -> Settings:
    """Settings с api_key и site_id_uuid для Integration API."""
    return Settings(
        unifi=UnifiAuthSettings(
            host="192.0.2.1",
            port=11443,
            site="site-1",  # short slug, не используется Integration API
            site_id_uuid=SITE_UUID,
            api_key=SecretStr("test-api-key-placeholder"),
        )
    )


@pytest.mark.fast()
def test_integration_client_uses_api_key_header(integration_settings: Settings) -> None:
    """X-API-KEY ставится в session headers при инициализации."""
    from unifi_manager.clients.integration import IntegrationClient

    client = IntegrationClient(integration_settings.unifi)
    assert client.session.headers.get("X-API-KEY") == "test-api-key-placeholder"


@pytest.mark.fast()
def test_missing_api_key_raises(minimal_unifi_settings: Settings) -> None:
    """Без api_key — UnifiAuthError при создании."""
    from unifi_manager.clients.integration import IntegrationClient

    with pytest.raises(UnifiAuthError, match="api_key required"):
        IntegrationClient(minimal_unifi_settings.unifi)


@pytest.mark.fast()
def test_missing_site_uuid_raises(integration_settings: Settings) -> None:
    """site_id_uuid обязателен для Integration API."""
    from unifi_manager.clients.integration import IntegrationClient

    # Зануляем UUID для теста
    integration_settings.unifi.site_id_uuid = None
    with pytest.raises(UnifiAuthError, match="site_id_uuid required"):
        IntegrationClient(integration_settings.unifi)


@pytest.mark.fast()
@responses.activate
def test_list_devices_uses_integration_path(integration_settings: Settings) -> None:
    """Endpoint: /proxy/network/integration/v1/sites/<UUID>/devices."""
    from unifi_manager.clients.integration import IntegrationClient

    expected_url = f"https://192.0.2.1:11443/proxy/network/integration/v1/sites/{SITE_UUID}/devices"
    responses.get(
        expected_url,
        json={"data": [{"id": "x", "macAddress": "aa:bb:cc:dd:ee:01", "model": "U7IW"}]},
        status=200,
    )

    client = IntegrationClient(integration_settings.unifi)
    raw = client.list_devices_raw()
    assert len(raw) == 1


@pytest.mark.fast()
@responses.activate
def test_list_clients_uses_integration_path(integration_settings: Settings) -> None:
    """Endpoint: /proxy/network/integration/v1/sites/<UUID>/clients."""
    from unifi_manager.clients.integration import IntegrationClient

    expected_url = f"https://192.0.2.1:11443/proxy/network/integration/v1/sites/{SITE_UUID}/clients"
    responses.get(expected_url, json={"data": []}, status=200)

    client = IntegrationClient(integration_settings.unifi)
    raw = client.list_clients_raw()
    assert raw == []


@pytest.mark.fast()
@responses.activate
def test_full_integration_response_parses(
    integration_settings: Settings, fixtures_dir: Path
) -> None:
    """Реальный response от Integration API парсится."""
    from unifi_manager.clients.integration import IntegrationClient

    raw_response = json.loads(
        (fixtures_dir / "integration_devices.json").read_text(encoding="utf-8")
    )
    expected_url = f"https://192.0.2.1:11443/proxy/network/integration/v1/sites/{SITE_UUID}/devices"
    responses.get(expected_url, json=raw_response, status=200)

    client = IntegrationClient(integration_settings.unifi)
    raw = client.list_devices_raw()
    assert len(raw) == 2
    assert raw[0]["macAddress"] == "aa:bb:cc:dd:ee:01"


@pytest.mark.fast()
@responses.activate
def test_extract_data_raises_on_non_list_response(integration_settings: Settings) -> None:
    """_extract_data поднимает UnifiAPIError если 'data' не список."""
    from unifi_manager.clients.exceptions import UnifiAPIError
    from unifi_manager.clients.integration import IntegrationClient

    expected_url = f"https://192.0.2.1:11443/proxy/network/integration/v1/sites/{SITE_UUID}/devices"
    responses.get(expected_url, json={"data": "not-a-list"}, status=200)

    client = IntegrationClient(integration_settings.unifi)
    with pytest.raises(UnifiAPIError, match="unexpected Integration API response"):
        client.list_devices_raw()
