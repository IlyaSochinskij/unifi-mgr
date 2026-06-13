"""Shared fixtures для tests/unit/test_cli/."""

import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    """Сбрасываем logging state между CLI тестами."""
    from unifi_manager import logging_config

    logging_config._LOGGING_CONFIGURED = False
    logging.getLogger().handlers.clear()


@pytest.fixture(autouse=True)
def _isolate_runtime_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI-команды вызывают setup_logging → mkdir(log_dir). Дефолт — /var/log/unifi-mgr,
    который non-root CI-раннер не может создать (PermissionError). Перенаправляем runtime-
    каталоги в tmp, чтобы CLI-тесты никогда не трогали системные пути (на root-раннере/Windows
    баг был замаскирован, всплыл на non-root GitHub Actions)."""
    monkeypatch.setenv("UNIFI_LOGGING__LOG_DIR", str(tmp_path / "log"))
    monkeypatch.setenv("UNIFI_PATHS__REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("UNIFI_PATHS__EXPORT_DIR", str(tmp_path / "exports"))


_UNIFI_ENV_VARS = ("UNIFI_CONFIG_PATH", "UNIFI_ENV_FILE")


@pytest.fixture(autouse=True)
def _clean_unifi_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove UNIFI_* env vars before each test; restore to absent after."""
    for var in _UNIFI_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield
    # Direct os.environ mutations (e.g. from the CLI callback) bypass monkeypatch
    # tracking — purge them explicitly so they don't leak into other test modules.
    for var in _UNIFI_ENV_VARS:
        os.environ.pop(var, None)
