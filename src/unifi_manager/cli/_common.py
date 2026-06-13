"""Shared infrastructure для CLI commands.

Все CLI группы импортируют отсюда:
- load_settings(config_path) — pydantic Settings + secret registration
- setup_logging_from_cli(settings, verbose, quiet) — wraps logging_config
- output_json(data) — formatter для --json флага
- build_legacy_client / build_integration_client — construct from Settings
"""

from __future__ import annotations

import json
import os
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any

from unifi_manager.clients.integration import IntegrationClient
from unifi_manager.clients.legacy import LegacyClient
from unifi_manager.logging_config import (
    register_secrets_from_settings,
    setup_logging,
)
from unifi_manager.settings import LoggingSettings, Settings, find_env_file


class ApiChoice(StrEnum):
    """Допустимые значения CLI-флага --api; typer отвергает прочее (exit 2)."""

    legacy = "legacy"
    integration = "integration"
    both = "both"


def load_settings(config_path: Path | None = None) -> Settings:
    """Загрузить Settings с опциональным указанием config.yaml пути.

    Args:
        config_path: явный путь к config.yaml (флаг --config).
                     None → стандартный поиск через _find_yaml().

    Side-effect: регистрирует все SecretStr из Settings в SecretsFilter
                 (защита от утечки в логах).
    """
    _prev = os.environ.get("UNIFI_CONFIG_PATH")
    try:
        if config_path is not None:
            os.environ["UNIFI_CONFIG_PATH"] = str(config_path)
        env_file = find_env_file()
        settings = (
            Settings(_env_file=env_file)  # type: ignore[call-arg]
            if env_file is not None
            else Settings()  # type: ignore[call-arg]
        )
    finally:
        # Восстановить исходное значение: не оставлять постоянных следов в os.environ.
        if _prev is None:
            os.environ.pop("UNIFI_CONFIG_PATH", None)
        else:
            os.environ["UNIFI_CONFIG_PATH"] = _prev

    register_secrets_from_settings(settings)
    return settings


def setup_logging_from_cli(
    settings: LoggingSettings,
    *,
    verbose: int = 0,
    quiet: int = 0,
) -> None:
    """Wrapper над logging_config.setup_logging — единая точка из CLI."""
    setup_logging(settings, verbose=verbose, quiet=quiet)


def output_json(data: Any) -> None:
    """Печать data как JSON в stdout (для cron, --json флаг)."""
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2, default=_json_default)
    sys.stdout.write("\n")


def _json_default(obj: Any) -> Any:
    """Default serializer для datetime, pydantic models, dataclasses."""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


def build_legacy_client(settings: Settings) -> LegacyClient:
    """LegacyClient (session + CSRF) из Settings.unifi."""
    return LegacyClient(settings.unifi)


def build_integration_client(settings: Settings) -> IntegrationClient:
    """IntegrationClient (X-API-KEY) из Settings.unifi.

    Raises:
        UnifiAuthError: если api_key или site_id_uuid отсутствуют.
    """
    return IntegrationClient(settings.unifi)
