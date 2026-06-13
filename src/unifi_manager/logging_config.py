"""Полное логирование для unifi-mgr (Phase 1).

Handlers:
- console: RichHandler (color, читаемо в TUI)
- file: RotatingFileHandler с JSON форматом (для grep/jq на сервере)

Дополнительно:
- SecretsFilter: сканирует сообщения и заменяет зарегистрированные секреты на ***REDACTED***
- register_secret / register_secrets_from_settings — публичные API

В фазе 2 добавится TelegramHandler с rate-limit.
"""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from typing import Any

from pydantic import SecretStr
from rich.console import Console
from rich.logging import RichHandler

from unifi_manager.settings import LoggingSettings, Settings

_LOGGING_CONFIGURED = False
_REGISTERED_SECRETS: set[str] = set()

# Standard LogRecord fields — used by SecretsFilter (skip when scanning extra={})
# and by JsonFormatter (skip when building payload to avoid duplicating built-ins).
_STANDARD_LOG_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "getMessage",
        "taskName",
    }
)


# === Public API ===


def setup_logging(
    settings: LoggingSettings,
    verbose: int = 0,
    quiet: int = 0,
) -> None:
    """Конфигурирует root logger с двумя handler'ами.

    Args:
        settings: настройки из Settings.logging
        verbose: 1+ → DEBUG для console
        quiet: 1+ → WARNING для console
    """
    global _LOGGING_CONFIGURED

    root = logging.getLogger()

    if quiet > 0:
        level = logging.WARNING
    elif verbose > 0:
        level = logging.DEBUG
    else:
        level = logging.getLevelNamesMapping()[settings.level]

    # Root всегда на DEBUG — handlers фильтруют независимо.
    # Это критично: file handler требует DEBUG записей (для post-mortem grep),
    # a console показывает только нужный пользователю level (INFO/DEBUG/WARNING).
    root.setLevel(logging.DEBUG)

    if _LOGGING_CONFIGURED:
        return

    # SecretsFilter — глобально, перед всеми handlers
    secrets_filter = SecretsFilter()

    # === Console handler (Rich) → STDERR ===
    # stdout зарезервирован под machine-readable data (export CSV/JSON, --json).
    console_handler = RichHandler(
        console=Console(stderr=True),
        show_path=False,
        rich_tracebacks=True,
        markup=False,
    )
    console_handler.setLevel(level)  # фильтр уровня — только на console
    console_handler.addFilter(secrets_filter)
    root.addHandler(console_handler)

    # === File handler (rotating JSON) ===
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    log_file = settings.log_dir / "unifi-mgr.log"
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=settings.max_bytes,
        backupCount=settings.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(JsonFormatter())
    file_handler.setLevel(logging.DEBUG)  # файл всегда DEBUG
    file_handler.addFilter(secrets_filter)
    root.addHandler(file_handler)

    _LOGGING_CONFIGURED = True


def register_secret(value: str) -> None:
    """Зарегистрировать секрет для SecretsFilter.

    Любое появление `value` в логах будет заменено на '***REDACTED***'.
    """
    if value and len(value) >= 4:  # игнорируем тривиально-короткие
        _REGISTERED_SECRETS.add(value)


def register_secrets_from_settings(settings: Settings) -> None:
    """Извлекает все SecretStr поля из Settings и регистрирует их.

    Рекурсивно проходит по всем sub-models.
    """
    _walk_and_register(settings)


def _walk_and_register(obj: Any) -> None:
    """Рекурсивно обходит структуру Pydantic моделей и регистрирует SecretStr."""
    if isinstance(obj, SecretStr):
        register_secret(obj.get_secret_value())
    elif hasattr(obj, "__pydantic_fields__"):
        # Pydantic model — iterate over fields
        for field_name in obj.__pydantic_fields__:
            _walk_and_register(getattr(obj, field_name))
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk_and_register(v)
    elif isinstance(obj, list | tuple):
        for v in obj:
            _walk_and_register(v)


# === Internal helpers ===


class SecretsFilter(logging.Filter):
    """Logger filter заменяющий зарегистрированные секреты на ***REDACTED***."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not _REGISTERED_SECRETS:
            return True

        # Replace в основном message
        if isinstance(record.msg, str):
            record.msg = _redact(record.msg)

        # Replace в args (для % форматирования)
        if record.args:
            args_tuple = record.args if isinstance(record.args, tuple) else (record.args,)
            new_args = tuple(_redact(a) if isinstance(a, str) else a for a in args_tuple)
            record.args = new_args

        # Replace в extra={} полях (попадают прямо в record.__dict__)
        for key, value in list(record.__dict__.items()):
            if key in _STANDARD_LOG_FIELDS or key.startswith("_"):
                continue
            if isinstance(value, str):
                record.__dict__[key] = _redact(value)

        return True


def _redact(s: str) -> str:
    for secret in _REGISTERED_SECRETS:
        if secret in s:
            s = s.replace(secret, "***REDACTED***")
    return s


class JsonFormatter(logging.Formatter):
    """JSON formatter — одна строка = одна запись, поля грепаются через jq."""

    def format(self, record: logging.LogRecord) -> str:
        import datetime

        # strftime does not support %f on Windows; build ISO timestamp manually.
        dt = datetime.datetime.fromtimestamp(record.created, tz=datetime.UTC)
        ts = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond:06d}Z"

        payload: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # extra kwargs из logger.info("...", extra={...}) попадают в record.__dict__
        for k, v in record.__dict__.items():
            if k not in _STANDARD_LOG_FIELDS and not k.startswith("_"):
                payload[k] = v

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)
