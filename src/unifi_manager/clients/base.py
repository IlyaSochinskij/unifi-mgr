"""BaseUnifiClient: HTTP-фундамент для Legacy и Integration клиентов.

Особенности:
- requests.Session для keep-alive
- retry на 5xx (3 попытки, без backoff в Phase 1 — добавим если понадобится)
- 4xx сразу raise (auth/perm/not-found)
- timeout по умолчанию 15 секунд
- SSL verify из settings (False / путь к pem)
- Логирование каждой неудачной попытки через logging
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from requests import Response, Session
from requests.exceptions import RequestException, Timeout

from unifi_manager.clients.exceptions import UnifiAPIError, UnifiTimeoutError
from unifi_manager.settings import UnifiAuthSettings

DEFAULT_TIMEOUT = 15
DEFAULT_MAX_RETRIES = 3

_logger = logging.getLogger(__name__)


class BaseUnifiClient:
    """Базовый HTTP-клиент для UniFi контроллера.

    Подклассы (LegacyClient, IntegrationClient) добавляют свою аутентификацию
    и используют get_json/post_json для запросов.
    """

    def __init__(
        self,
        config: UnifiAuthSettings,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.config = config
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = f"https://{config.host}:{config.port}"
        self.session: Session = self._build_session()

    def _build_session(self) -> Session:
        session = requests.Session()
        # verify_ssl: True (secure default) | False (opt-out for self-signed) | Path (CA bundle)
        verify = self.config.verify_ssl
        if isinstance(verify, bool):
            session.verify = verify
        else:
            session.verify = str(verify)
        return session

    def get_json(self, path: str) -> dict[str, Any]:
        """GET с retry для 5xx и raise для 4xx/timeout."""
        return self._request("GET", path, json_body=None)

    def post_json(
        self, path: str, *, json_body: dict[str, Any], retries: int | None = None
    ) -> dict[str, Any]:
        """POST с retry для 5xx и raise для 4xx/timeout.

        retries=1 отключает повтор — обязательно для неидемпотентных команд
        (restart/power-cycle), иначе timeout/5xx после приёма командой = двойное действие.
        """
        return self._request("POST", path, json_body=json_body, retries=retries)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None,
        retries: int | None = None,
    ) -> dict[str, Any]:
        max_retries = retries if retries is not None else self.max_retries
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        last_exc: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                resp: Response = self.session.request(
                    method=method,
                    url=url,
                    json=json_body,
                    timeout=self.timeout,
                )
            except Timeout as e:
                last_exc = e
                _logger.warning(
                    "Timeout on attempt %d/%d for %s %s",
                    attempt,
                    max_retries,
                    method,
                    path,
                )
                continue
            except RequestException as e:
                last_exc = e
                _logger.warning(
                    "Request failed on attempt %d/%d for %s %s: %s",
                    attempt,
                    max_retries,
                    method,
                    path,
                    e,
                )
                continue

            # 4xx — не ретраим
            if 400 <= resp.status_code < 500:
                raise UnifiAPIError(
                    f"{method} {path} failed: {resp.status_code}",
                    status_code=resp.status_code,
                    body=resp.text[:500],
                )

            # 5xx — ретраим
            if resp.status_code >= 500:
                _logger.warning(
                    "Server error %d on attempt %d/%d for %s %s",
                    resp.status_code,
                    attempt,
                    max_retries,
                    method,
                    path,
                )
                if attempt == max_retries:
                    raise UnifiAPIError(
                        f"{method} {path} failed after {max_retries} attempts",
                        status_code=resp.status_code,
                        body=resp.text[:500],
                    )
                continue

            # 2xx/3xx — успех
            try:
                return resp.json()  # type: ignore[no-any-return]
            except ValueError as e:
                raise UnifiAPIError(
                    f"{method} {path} returned non-JSON: {e}",
                    status_code=resp.status_code,
                    body=resp.text[:500],
                ) from e

        # Все retry исчерпаны (только при Timeout/RequestException)
        if isinstance(last_exc, Timeout):
            raise UnifiTimeoutError(
                f"{method} {path} timed out after {max_retries} attempts"
            ) from last_exc
        raise UnifiAPIError(
            f"{method} {path} failed after {max_retries} attempts: {last_exc}"
        ) from last_exc
