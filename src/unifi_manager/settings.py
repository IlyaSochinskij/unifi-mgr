"""Типизированная конфигурация через pydantic-settings.

Источники (приоритет от низкого к высокому):
    defaults в коде → config.yaml → .env → env vars → CLI флаги

Места поиска config.yaml (первый найденный выигрывает):
    1. --config PATH (CLI флаг, передаётся через UNIFI_CONFIG_PATH env)
    2. ./config.yaml
    3. ~/.config/unifi-mgr/config.yaml
    4. /etc/unifi-mgr/config.yaml
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


def _find_yaml() -> Path | None:
    """Найти config.yaml в стандартных местах."""
    cli_path = os.environ.get("UNIFI_CONFIG_PATH")
    if cli_path:
        p = Path(cli_path)
        if not p.is_file():
            raise ValueError(f"UNIFI_CONFIG_PATH={cli_path!r}: config file not found")
        return p

    candidates = [
        Path.cwd() / "config.yaml",
        Path.home() / ".config" / "unifi-mgr" / "config.yaml",
        Path("/etc/unifi-mgr/config.yaml"),
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def find_env_file() -> Path | None:
    """Найти .env по цепочке приоритетов (первый существующий выигрывает).

    1. UNIFI_ENV_FILE (CLI --env-file пишет сюда, либо прямой env var)
    2. в той же директории, что и config.yaml
    3. /etc/unifi-mgr/.env
    None → дефолт model_config (./.env, dev).
    """
    explicit = os.environ.get("UNIFI_ENV_FILE")
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise ValueError(f"UNIFI_ENV_FILE={explicit!r}: .env file not found")
        return p

    cfg = _find_yaml()
    if cfg is not None:
        beside = cfg.parent / ".env"
        if beside.is_file():
            return beside

    etc = Path("/etc/unifi-mgr/.env")
    if etc.is_file():
        return etc

    return None


class YamlConfigSource(PydanticBaseSettingsSource):
    """pydantic-settings source: читает YAML файл найденный через _find_yaml()."""

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False  # реализация через __call__

    def __call__(self) -> dict[str, Any]:
        path = _find_yaml()
        if not path:
            return {}
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path}: top-level YAML must be a mapping")
        return data


class UnifiAuthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    port: int = 11443
    site: str
    site_id_uuid: str | None = None
    username: SecretStr | None = None
    password: SecretStr | None = None
    api_key: SecretStr | None = None
    verify_ssl: bool | Path = True


class TelegramSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_token: SecretStr | None = None
    chat_id: str | None = None
    enabled: bool = True
    parse_mode: Literal["MarkdownV2", "HTML", "None"] = "MarkdownV2"
    rate_limit_per_hash_seconds: int = 30
    rate_limit_total_per_minute: int = 5


class RestartProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter_names: list[str] = Field(default_factory=list)
    filter_patterns: list[str] = Field(default_factory=list)
    exclude_names: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    # Триггер: count EVT_AP_Lost_Contact СТРОГО БОЛЬШЕ threshold за window_hours.
    lost_contact_threshold: int = Field(default=3, ge=0)
    window_hours: int = Field(default=24, ge=1)
    max_restarts: int = Field(default=5, ge=1, le=20)
    cooldown_minutes: int = Field(default=60, ge=0)


class AutoRestartSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    max_restarts_per_run: int = Field(default=5, ge=1, le=20)
    cooldown_minutes: int = Field(default=60, ge=0)
    offline_threshold_min: int = Field(default=15, ge=0)
    exclude_patterns: list[str] = Field(default_factory=list)
    statefile: Path = Path("/var/lib/unifi-mgr/restart_history.json")


class ThresholdsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    critical_temp_c: int = 70
    critical_poe_percent: int = 90
    high_cu_percent: int = 50
    # Фаза 7: триггер WARNING если на любом порту счётчик ошибок
    # вырос больше чем на N. 0 = отключено.
    port_error_delta_threshold: int = 50


class LoggingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    log_dir: Path = Path("/var/log/unifi-mgr")
    console_format: Literal["human", "json"] = "human"
    file_format: Literal["json"] = "json"
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    max_bytes: int = 10_000_000
    backup_count: int = 5


class PathsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reports_dir: Path = Path("/var/lib/unifi-mgr/reports")
    export_dir: Path = Path("/var/lib/unifi-mgr/exports")
    cache_dir: Path = Field(default_factory=lambda: Path.home() / ".cache" / "unifi-mgr")


class AuditHealthCheckSettings(BaseModel):
    """Фаза 7: pre-check контроллера перед audit critical."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    dns_servers: list[str] = Field(default_factory=lambda: ["8.8.8.8", "1.1.1.1"])
    http_endpoints: list[str] = Field(
        default_factory=lambda: ["https://www.cloudflare.com", "https://www.google.com"]
    )
    timeout_seconds: int = 5


class MaintenanceSettings(BaseModel):
    """Фаза 7: maintenance mode для защиты от ложных рестартов."""

    model_config = ConfigDict(extra="forbid")

    mute_state_file: Path = Path("/var/lib/unifi-mgr/mute_state.json")
    audit_baseline_file: Path = Path("/var/lib/unifi-mgr/audit_baseline.json")
    default_mute_duration_minutes: int = 30
    max_mute_duration_hours: int = 24


class _PermRestart(BaseModel):
    """Kill-switches для restart-операций (D30)."""

    model_config = ConfigDict(extra="forbid")

    execute: bool = True  # глобальный: отключает auto() и все перезапуски
    profile_apply: bool = True  # отключает только `restart profile *`
    device_apply: bool = True  # отключает только `restart device --apply`


class _PermNotify(BaseModel):
    """Kill-switches для notify-операций (D30)."""

    model_config = ConfigDict(extra="forbid")

    telegram_send: bool = True  # доп. kill поверх telegram.enabled


class _CliPermissions(BaseModel):
    """D30 refinement: cli namespace.

    Default permissive (True) — backward compat для existing cron-задач.
    Если в config.yaml блок `permissions:` отсутствует, ничего не ломается.
    """

    model_config = ConfigDict(extra="forbid")

    restart: _PermRestart = Field(default_factory=_PermRestart)
    notify: _PermNotify = Field(default_factory=_PermNotify)


class _McpPermissions(BaseModel):
    """D30 refinement: mcp namespace (Phase 4M).

    Default RESTRICTIVE (False) — opt-in оператором.
    LLM нет `--apply` barrier, поэтому MCP-вызовы должны быть явно разрешены.
    """

    model_config = ConfigDict(extra="forbid")

    restart_execute: bool = False
    notify_send: bool = False


class PermissionsSettings(BaseModel):
    """D30: config-level kill-switches.

    Refinement: split на `cli` (default True) и `mcp` (default False)
    namespaces для подготовки к Phase 4M без поломки config schema.

    Пример: чтобы экстренно отключить весь автоматический рестарт из cron,
    оператор ставит `permissions.cli.restart.execute: false` в config.yaml.
    """

    model_config = ConfigDict(extra="forbid")

    cli: _CliPermissions = Field(default_factory=_CliPermissions)
    mcp: _McpPermissions = Field(default_factory=_McpPermissions)


class Settings(BaseSettings):
    """Главный конфиг приложения."""

    model_config = SettingsConfigDict(
        env_prefix="UNIFI_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    unifi: UnifiAuthSettings
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    auto_restart: AutoRestartSettings = Field(default_factory=AutoRestartSettings)
    restart_profiles: dict[str, RestartProfile] = Field(default_factory=dict)
    thresholds: ThresholdsSettings = Field(default_factory=ThresholdsSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    paths: PathsSettings = Field(default_factory=PathsSettings)
    # D30 (Phase 3): permission kill-switches (config-level emergency override).
    permissions: PermissionsSettings = Field(default_factory=PermissionsSettings)
    # Фаза 7: имеют дефолты, в фазах 0-6 не используются.
    audit_health_check: AuditHealthCheckSettings = Field(default_factory=AuditHealthCheckSettings)
    maintenance: MaintenanceSettings = Field(default_factory=MaintenanceSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Приоритет (от низкого к высокому = справа налево):
        # defaults → file_secrets → YAML → .env → env → init (CLI)
        # Note: file_secret_settings (Docker /run/secrets/) намеренно ниже YAML.
        # На bare-metal деплое secrets_dir=None, file_secrets не используется.  # noqa: RUF003
        # Если в будущем понадобится Docker-style secrets — пересмотреть порядок.
        yaml_source = YamlConfigSource(settings_cls)
        return (init_settings, env_settings, dotenv_settings, yaml_source, file_secret_settings)
