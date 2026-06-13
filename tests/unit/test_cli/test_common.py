"""Тесты для unifi_manager.cli._common."""

import json
from pathlib import Path

import pytest
from pydantic import SecretStr


@pytest.mark.fast()
def test_load_settings_from_path(tmp_path: Path) -> None:
    """load_settings(config_path) парсит указанный YAML."""
    from unifi_manager.cli._common import load_settings

    config_yaml = tmp_path / "test.yaml"
    config_yaml.write_text(
        "unifi:\n  host: 5.6.7.8\n  port: 11443\n  site: test-site\n",
        encoding="utf-8",
    )

    settings = load_settings(config_path=config_yaml)
    assert settings.unifi.host == "5.6.7.8"
    assert settings.unifi.site == "test-site"


@pytest.mark.fast()
def test_load_settings_default_search(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """load_settings(None) использует _find_yaml() стандартный поиск."""
    from unifi_manager.cli._common import load_settings

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "unifi:\n  host: 1.2.3.4\n  port: 11443\n  site: t\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("UNIFI_CONFIG_PATH", raising=False)

    settings = load_settings(config_path=None)
    assert settings.unifi.host == "1.2.3.4"


@pytest.mark.fast()
def test_load_settings_registers_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """load_settings регистрирует SecretStr поля в SecretsFilter."""
    from unifi_manager import logging_config
    from unifi_manager.cli._common import load_settings

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "unifi:\n  host: 1.2.3.4\n  port: 11443\n  site: t\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("UNIFI_UNIFI__PASSWORD", "super-secret-pass-xyz")
    monkeypatch.delenv("UNIFI_CONFIG_PATH", raising=False)

    # Clear any prior state
    logging_config._REGISTERED_SECRETS.clear()

    _ = load_settings(config_path=None)
    assert "super-secret-pass-xyz" in logging_config._REGISTERED_SECRETS


@pytest.mark.fast()
def test_output_json_writes_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    """output_json печатает JSON в stdout."""
    from unifi_manager.cli._common import output_json

    output_json({"key": "value", "count": 42})
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed == {"key": "value", "count": 42}


@pytest.mark.fast()
def test_output_json_handles_datetime(capsys: pytest.CaptureFixture[str]) -> None:
    """output_json сериализует datetime / pydantic models / dataclasses."""
    from datetime import UTC, datetime

    from unifi_manager.cli._common import output_json

    output_json({"ts": datetime(2026, 5, 18, 10, 0, 0, tzinfo=UTC)})
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert "2026-05-18" in parsed["ts"]


@pytest.mark.fast()
def test_build_legacy_client_returns_legacy_client() -> None:
    """build_legacy_client(settings) возвращает LegacyClient инстанс."""
    from unifi_manager.cli._common import build_legacy_client
    from unifi_manager.clients.legacy import LegacyClient
    from unifi_manager.settings import Settings, UnifiAuthSettings

    settings = Settings(
        unifi=UnifiAuthSettings(
            host="1.2.3.4", port=11443, site="t", username=SecretStr("u"), password=SecretStr("p")
        ),
    )
    client = build_legacy_client(settings)
    assert isinstance(client, LegacyClient)


@pytest.mark.fast()
def test_build_integration_client_returns_integration_client() -> None:
    from unifi_manager.cli._common import build_integration_client
    from unifi_manager.clients.integration import IntegrationClient
    from unifi_manager.settings import Settings, UnifiAuthSettings

    settings = Settings(
        unifi=UnifiAuthSettings(
            host="1.2.3.4",
            port=11443,
            site="t",
            site_id_uuid="bbffb94c-1234-5678-9abc-def012345678",
            api_key=SecretStr("k"),
        ),
    )
    client = build_integration_client(settings)
    assert isinstance(client, IntegrationClient)


@pytest.mark.fast()
def test_setup_logging_from_cli_uses_verbose(tmp_path: Path) -> None:
    """setup_logging_from_cli(verbose=1) — DEBUG level."""
    import logging

    from unifi_manager import logging_config
    from unifi_manager.cli._common import setup_logging_from_cli
    from unifi_manager.settings import LoggingSettings

    # Reset state
    logging_config._LOGGING_CONFIGURED = False
    logging.getLogger().handlers.clear()

    setup_logging_from_cli(LoggingSettings(log_dir=tmp_path), verbose=1, quiet=0)
    assert logging.getLogger().level == logging.DEBUG
