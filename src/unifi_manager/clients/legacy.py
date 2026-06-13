"""LegacyClient: session-based UniFi Network API клиент.

Authentication: POST /api/auth/login c username+password, получает session cookie
и (опционально) X-Csrf-Token который автоматически добавляется в session headers
для последующих POST запросов.

Endpoints: /proxy/network/api/s/<site>/...
"""

from __future__ import annotations

import logging
from typing import Any

from unifi_manager.clients.base import BaseUnifiClient
from unifi_manager.clients.exceptions import UnifiAPIError, UnifiAuthError
from unifi_manager.settings import UnifiAuthSettings

_logger = logging.getLogger(__name__)


class LegacyClient(BaseUnifiClient):
    """UniFi Legacy API клиент (session + CSRF)."""

    def __init__(
        self,
        config: UnifiAuthSettings,
        *,
        timeout: int = 15,
        max_retries: int = 3,
    ) -> None:
        super().__init__(config, timeout=timeout, max_retries=max_retries)
        self._logged_in = False

    @property
    def site_path_prefix(self) -> str:
        """Префикс path для запросов к этому site."""
        return f"/proxy/network/api/s/{self.config.site}"

    def login(self) -> bool:
        """Авторизация через session. Извлекает CSRF token если возвращается.

        Raises:
            UnifiAuthError: если credentials отсутствуют или 401/403.
        """
        if self.config.username is None or self.config.password is None:
            raise UnifiAuthError("username and password required for LegacyClient login")

        login_url = f"{self.base_url}/api/auth/login"
        body = {
            "username": self.config.username.get_secret_value(),
            "password": self.config.password.get_secret_value(),
        }
        try:
            resp = self.session.post(login_url, json=body, timeout=self.timeout)
        except Exception as e:
            raise UnifiAuthError(f"login request failed: {e}") from e

        if resp.status_code in (401, 403):
            raise UnifiAuthError(f"login failed: {resp.status_code}")
        if not resp.ok:
            raise UnifiAuthError(f"login failed with status {resp.status_code}")

        csrf = resp.headers.get("X-Csrf-Token")
        if csrf:
            self.session.headers["X-Csrf-Token"] = csrf

        self._logged_in = True
        _logger.info("LegacyClient logged in to %s", self.base_url)
        return True

    def _ensure_logged_in(self) -> None:
        if not self._logged_in:
            self.login()

    def list_devices_raw(self) -> list[dict[str, Any]]:
        """GET /stat/device — список всех устройств site (raw dicts).

        Parsing into Device/AccessPoint/Switch — задача вызывающего кода (Phase 2 service).
        """
        self._ensure_logged_in()
        result = self.get_json(f"{self.site_path_prefix}/stat/device")
        return self._extract_data(result)

    def list_events_raw(self, *, mac: str | None = None) -> list[dict[str, Any]]:
        """GET /stat/event — события (опционально фильтр по mac).

        Для offline/unknown AP контроллер отдаёт 404 на `/stat/event?mac=` —
        трактуем как «событий нет» (legacy-скрипт терпел это через try/except).
        Иначе restart profile падал бы ровно когда точка оффлайн, т.е. когда
        рестарт и нужен. Не-404 ошибки по-прежнему пробрасываем.
        """
        self._ensure_logged_in()
        path = f"{self.site_path_prefix}/stat/event"
        if mac:
            path += f"?mac={mac}"
        try:
            result = self.get_json(path)
        except UnifiAPIError as e:
            if e.status_code == 404:
                _logger.debug("list_events_raw: 404 for mac=%s — treating as no events", mac)
                return []
            raise
        return self._extract_data(result)

    def list_clients_raw(self) -> list[dict[str, Any]]:
        """GET /stat/sta — подключённые клиенты."""
        self._ensure_logged_in()
        result = self.get_json(f"{self.site_path_prefix}/stat/sta")
        return self._extract_data(result)

    def send_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /cmd/devmgr — отправить команду (restart, power-cycle, ...).

        Args:
            payload: e.g. {"cmd": "restart", "mac": "aa:bb:cc:dd:ee:01"}
        """
        self._ensure_logged_in()
        # retries=1: команда неидемпотентна — повтор после ambiguous timeout/5xx
        # рестартнул бы AP / power-cycle порт повторно.
        return self.post_json(
            f"{self.site_path_prefix}/cmd/devmgr",
            json_body=payload,
            retries=1,
        )

    @staticmethod
    def _extract_data(response: dict[str, Any]) -> list[dict[str, Any]]:
        """Извлечь список 'data' из стандартного UniFi response wrapper."""
        data = response.get("data")
        if not isinstance(data, list):
            raise UnifiAPIError(f"unexpected response format: {response}")
        return data
