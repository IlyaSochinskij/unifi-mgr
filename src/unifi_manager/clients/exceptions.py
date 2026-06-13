"""Исключения HTTP-клиентов UniFi.

Все клиентские ошибки наследуются от UnifiError для удобного catch-all.
"""

from __future__ import annotations


class UnifiError(Exception):
    """Базовое исключение для всех ошибок взаимодействия с UniFi API."""


class UnifiAuthError(UnifiError):
    """Ошибка авторизации: неверные credentials, истёкшая сессия, отсутствие CSRF."""


class UnifiAPIError(UnifiError):
    """Ошибка ответа API: 4xx/5xx, неожиданный формат, rc != ok.

    Сохраняет status_code и тело ответа для post-mortem отладки.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class UnifiTimeoutError(UnifiError):
    """Сетевой таймаут (после исчерпания retry попыток)."""
