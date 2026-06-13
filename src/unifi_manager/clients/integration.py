"""IntegrationClient: API-key based UniFi Network Integration API клиент.

Authentication: X-API-KEY header (статичный токен, не сессия).
Endpoints: /proxy/network/integration/v1/sites/<UUID>/...

ВАЖНО: site_id_uuid отличается от site (short slug) в Legacy API.
Получается отдельно через `GET /proxy/network/integration/v1/sites` для конкретного контроллера.
"""

from __future__ import annotations

import logging
from typing import Any

from unifi_manager.clients.base import BaseUnifiClient
from unifi_manager.clients.exceptions import UnifiAPIError, UnifiAuthError
from unifi_manager.settings import UnifiAuthSettings

_logger = logging.getLogger(__name__)


class IntegrationClient(BaseUnifiClient):
    """UniFi Integration API клиент (X-API-KEY auth)."""

    def __init__(
        self,
        config: UnifiAuthSettings,
        *,
        timeout: int = 15,
        max_retries: int = 3,
    ) -> None:
        if config.api_key is None:
            raise UnifiAuthError("api_key required for IntegrationClient")
        if config.site_id_uuid is None:
            raise UnifiAuthError("site_id_uuid required for IntegrationClient")

        super().__init__(config, timeout=timeout, max_retries=max_retries)
        self.session.headers["X-API-KEY"] = config.api_key.get_secret_value()
        _logger.info("IntegrationClient initialized for site %s", config.site_id_uuid)

    @property
    def site_path_prefix(self) -> str:
        return f"/proxy/network/integration/v1/sites/{self.config.site_id_uuid}"

    def list_devices_raw(self) -> list[dict[str, Any]]:
        """GET /devices — список устройств site."""
        result = self.get_json(f"{self.site_path_prefix}/devices")
        return self._extract_data(result)

    def list_clients_raw(self) -> list[dict[str, Any]]:
        """GET /clients — подключённые клиенты."""
        result = self.get_json(f"{self.site_path_prefix}/clients")
        return self._extract_data(result)

    @staticmethod
    def _extract_data(response: dict[str, Any]) -> list[dict[str, Any]]:
        """Integration API возвращает {data: [...], offset, limit, count, totalCount}."""
        data = response.get("data")
        if not isinstance(data, list):
            raise UnifiAPIError(f"unexpected Integration API response: {response}")
        return data
