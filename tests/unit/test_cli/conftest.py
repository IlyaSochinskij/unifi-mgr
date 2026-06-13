"""Shared fixtures для tests/unit/test_cli/."""

import logging
import os
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    """Сбрасываем logging state между CLI тестами."""
    from unifi_manager import logging_config

    logging_config._LOGGING_CONFIGURED = False
    logging.getLogger().handlers.clear()


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
