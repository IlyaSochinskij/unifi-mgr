"""Тесты для logging_config (расширенная Phase 1 версия)."""

import json
import logging
import tempfile
from pathlib import Path

import pytest
from pydantic import SecretStr

import unifi_manager.logging_config as logging_config_module
from unifi_manager.settings import LoggingSettings, Settings, UnifiAuthSettings


@pytest.fixture(autouse=True)
def _reset_logging_state() -> None:
    """Сбрасывает глобальный state модуля logging_config + root handlers
    перед каждым тестом, чтобы тесты не зависели от порядка выполнения."""
    logging_config_module._LOGGING_CONFIGURED = False
    if hasattr(logging_config_module, "_REGISTERED_SECRETS"):
        logging_config_module._REGISTERED_SECRETS.clear()
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.WARNING)


# === Existing Phase 0 tests (preserved) ===


@pytest.mark.fast()
def test_setup_logging_callable() -> None:
    from unifi_manager.logging_config import setup_logging

    assert callable(setup_logging)


@pytest.mark.fast()
def test_setup_logging_returns_none(tmp_path: Path) -> None:
    """setup_logging — side-effect функция, возвращает None."""
    from unifi_manager.logging_config import setup_logging

    result = setup_logging(LoggingSettings(log_dir=tmp_path), verbose=0, quiet=0)
    assert result is None


@pytest.mark.fast()
@pytest.mark.parametrize(
    ("verbose", "quiet", "expected_console"),
    [
        (0, 0, logging.INFO),
        (1, 0, logging.DEBUG),
        (2, 0, logging.DEBUG),
        (0, 1, logging.WARNING),
    ],
)
def test_setup_logging_levels(
    tmp_path: Path, verbose: int, quiet: int, expected_console: int
) -> None:
    """verbose/quiet флаги меняют уровень console handler'а; root всегда DEBUG."""
    from rich.logging import RichHandler

    from unifi_manager.logging_config import setup_logging

    setup_logging(LoggingSettings(log_dir=tmp_path), verbose=verbose, quiet=quiet)
    root = logging.getLogger()
    # Root must always be DEBUG so file handler receives all records.
    assert root.level == logging.DEBUG
    # Console handler carries the user-facing level.
    rich_handlers = [h for h in root.handlers if isinstance(h, RichHandler)]
    assert rich_handlers, "Expected at least one RichHandler"
    assert rich_handlers[0].level == expected_console


@pytest.mark.fast()
def test_setup_logging_idempotent(tmp_path: Path) -> None:
    """Повторный вызов не должен дублировать handlers."""
    from unifi_manager.logging_config import setup_logging

    setup_logging(LoggingSettings(log_dir=tmp_path), verbose=0, quiet=0)
    handlers_after_first = len(logging.getLogger().handlers)
    setup_logging(LoggingSettings(log_dir=tmp_path), verbose=0, quiet=0)
    handlers_after_second = len(logging.getLogger().handlers)
    assert handlers_after_first == handlers_after_second


# === New Phase 1 tests ===


@pytest.mark.fast()
def test_setup_logging_adds_console_and_file_handler(tmp_path: Path) -> None:
    """В Phase 1 — два handler'а: console (Rich) + file (JSON)."""
    from unifi_manager.logging_config import setup_logging

    settings = LoggingSettings(log_dir=tmp_path)
    setup_logging(settings, verbose=0, quiet=0)

    root = logging.getLogger()
    handler_types = [type(h).__name__ for h in root.handlers]
    assert any("Rich" in t for t in handler_types), f"No Rich handler in {handler_types}"
    assert any("FileHandler" in t or "RotatingFileHandler" in t for t in handler_types), (
        f"No FileHandler in {handler_types}"
    )


@pytest.mark.fast()
def test_log_file_is_created_with_json_format(tmp_path: Path) -> None:
    """File handler пишет JSON-форматированные строки."""
    from unifi_manager.logging_config import setup_logging

    settings = LoggingSettings(log_dir=tmp_path)
    setup_logging(settings, verbose=0, quiet=0)

    logger = logging.getLogger("test")
    logger.warning("test message", extra={"custom_field": 42})

    # flush handlers
    for h in logging.getLogger().handlers:
        h.flush()

    log_file = tmp_path / "unifi-mgr.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8").strip()
    lines = content.splitlines()
    assert len(lines) >= 1
    # последняя строка должна быть валидным JSON
    record = json.loads(lines[-1])
    assert record["msg"] == "test message"
    assert record["level"] == "WARNING"
    assert record["custom_field"] == 42


@pytest.mark.fast()
def test_secrets_filter_redacts_password(tmp_path: Path) -> None:
    """SecretsFilter сканирует сообщения и заменяет значения SecretStr на ***REDACTED***."""
    from unifi_manager.logging_config import register_secret, setup_logging

    settings = LoggingSettings(log_dir=tmp_path)
    setup_logging(settings, verbose=0, quiet=0)

    # Регистрируем секрет
    register_secret("super-secret-password-do-not-leak")

    logger = logging.getLogger("test")
    logger.error("Login failed for user with password=super-secret-password-do-not-leak")

    for h in logging.getLogger().handlers:
        h.flush()

    log_file = tmp_path / "unifi-mgr.log"
    content = log_file.read_text(encoding="utf-8")
    assert "super-secret-password-do-not-leak" not in content
    assert "***REDACTED***" in content


@pytest.mark.fast()
def test_register_secret_from_secret_str(tmp_path: Path) -> None:
    """register_secrets_from_settings извлекает все SecretStr из Settings."""
    from unifi_manager.logging_config import register_secrets_from_settings, setup_logging

    setup_logging(LoggingSettings(log_dir=tmp_path), verbose=0, quiet=0)

    settings = Settings(
        unifi=UnifiAuthSettings(
            host="1.2.3.4",
            port=11443,
            site="test",
            password=SecretStr("the-password"),
            api_key=SecretStr("the-api-key"),
        )
    )
    register_secrets_from_settings(settings)

    logger = logging.getLogger("test")
    logger.error("Debug dump: password=the-password and key=the-api-key")

    for h in logging.getLogger().handlers:
        h.flush()

    log_file = tmp_path / "unifi-mgr.log"
    content = log_file.read_text(encoding="utf-8")
    assert "the-password" not in content
    assert "the-api-key" not in content
    assert content.count("***REDACTED***") >= 2


@pytest.mark.fast()
def test_console_handler_uses_rich(tmp_path: Path) -> None:
    """Console handler — это RichHandler."""
    from rich.logging import RichHandler

    from unifi_manager.logging_config import setup_logging

    setup_logging(LoggingSettings(log_dir=tmp_path), verbose=0, quiet=0)

    root = logging.getLogger()
    rich_handlers = [h for h in root.handlers if isinstance(h, RichHandler)]
    assert len(rich_handlers) == 1


@pytest.mark.fast()
def test_file_handler_captures_debug_even_when_console_is_info(tmp_path: Path) -> None:
    """File handler ВСЕГДА на DEBUG — даже когда console на INFO (default).

    Регрессия-тест на Critical fix: до фикса root.setLevel(INFO) filtered
    DEBUG записи до того как они достигнут file_handler.
    """
    from unifi_manager.logging_config import setup_logging

    settings = LoggingSettings(log_dir=tmp_path)  # level=INFO default
    setup_logging(settings, verbose=0, quiet=0)

    logger = logging.getLogger("test")
    logger.debug("important debug detail that should appear in file")
    logger.info("info message")

    for h in logging.getLogger().handlers:
        h.flush()

    log_file = tmp_path / "unifi-mgr.log"
    content = log_file.read_text(encoding="utf-8")
    assert "important debug detail" in content
    assert "info message" in content


@pytest.mark.fast()
def test_secrets_filter_redacts_extra_kwargs(tmp_path: Path) -> None:
    """SecretsFilter redacts secrets passed via extra={} (защита для Phase 2 services)."""
    from unifi_manager.logging_config import register_secret, setup_logging

    setup_logging(LoggingSettings(log_dir=tmp_path), verbose=0, quiet=0)
    register_secret("super-secret-token-value")

    logger = logging.getLogger("test")
    logger.warning("Login failed", extra={"api_key": "super-secret-token-value"})

    for h in logging.getLogger().handlers:
        h.flush()

    log_file = tmp_path / "unifi-mgr.log"
    content = log_file.read_text(encoding="utf-8")
    assert "super-secret-token-value" not in content
    assert "***REDACTED***" in content


@pytest.mark.fast()
def test_console_handler_writes_to_stderr() -> None:
    """Логи console-handler идут в stderr, чтобы не пачкать stdout (export/--json)."""
    import logging as _logging

    import unifi_manager.logging_config as lc
    from unifi_manager.logging_config import setup_logging
    from unifi_manager.settings import LoggingSettings

    lc._LOGGING_CONFIGURED = False
    for h in list(_logging.getLogger().handlers):
        _logging.getLogger().removeHandler(h)

    setup_logging(LoggingSettings(log_dir=Path(tempfile.mkdtemp())))
    rich_handlers = [
        h for h in _logging.getLogger().handlers if h.__class__.__name__ == "RichHandler"
    ]
    assert rich_handlers, "expected a RichHandler"
    assert rich_handlers[0].console.stderr is True
