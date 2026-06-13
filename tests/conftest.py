"""Global pytest fixtures."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from unifi_manager.settings import Settings, UnifiAuthSettings


@pytest.fixture()
def fixtures_dir() -> Path:
    """Путь к директории с тестовыми fixtures (YAML, JSON snapshots)."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture()
def tmp_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Изолированная директория для конфига в одном тесте.

    Меняет cwd на tmp_path, так что любой `./config.yaml` относителен к нему.
    """
    monkeypatch.chdir(tmp_path)
    yield tmp_path


@pytest.fixture
def minimal_unifi_settings() -> Settings:
    """Settings с минимальным валидным unifi блоком — без секретов."""
    return Settings(
        unifi=UnifiAuthSettings(
            host="192.0.2.1",
            port=11443,
            site="site-1",
        )
    )
