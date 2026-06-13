"""Проверка что example конфиги валидны и парсятся."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.fast()
def test_config_yaml_example_exists() -> None:
    assert (REPO_ROOT / "config.yaml.example").is_file()


@pytest.mark.fast()
def test_env_example_exists() -> None:
    assert (REPO_ROOT / ".env.example").is_file()


@pytest.mark.fast()
def test_config_yaml_example_parses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """config.yaml.example парсится как валидный Settings (с минимальными
    обязательными env переменными для секретов)."""
    monkeypatch.chdir(tmp_path)
    example_src = (REPO_ROOT / "config.yaml.example").read_bytes()
    (tmp_path / "config.yaml").write_bytes(example_src)

    # Минимальные env, которые могут понадобиться (если они в example placeholders)
    monkeypatch.setenv("UNIFI_UNIFI__USERNAME", "test")
    monkeypatch.setenv("UNIFI_UNIFI__PASSWORD", "test")

    from unifi_manager.settings import Settings

    settings = Settings()  # type: ignore[call-arg]
    assert settings.unifi.host
    assert settings.unifi.site


@pytest.mark.fast()
def test_env_example_has_required_keys() -> None:
    """В .env.example должны быть все главные ключи (как комментарий или value)."""
    content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    required = [
        "UNIFI_UNIFI__USERNAME",
        "UNIFI_UNIFI__PASSWORD",
        "UNIFI_UNIFI__API_KEY",
        "UNIFI_TELEGRAM__BOT_TOKEN",
    ]
    for key in required:
        assert key in content, f"missing {key} in .env.example"
