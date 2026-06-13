from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.mark.fast
def test_config_validate_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UNIFI_CONFIG_PATH", raising=False)
    (tmp_path / "config.yaml").write_text(
        "unifi:\n  host: 1.2.3.4\n  port: 11443\n  site: t\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code == 0
    assert "valid" in result.stdout.lower()


@pytest.mark.fast
def test_config_validate_invalid_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UNIFI_CONFIG_PATH", raising=False)
    (tmp_path / "config.yaml").write_text(
        "unifi:\n  # missing required host\n  port: 11443\n  site: t\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code == 1


@pytest.mark.fast()
def test_config_validate_strict_fails_without_creds(tmp_path) -> None:
    """--strict: YAML валидна, но нет ни (user+pass), ни api_key → exit 1."""
    from typer.testing import CliRunner

    from unifi_manager.cli.main import app

    cfg = tmp_path / "config.yaml"
    cfg.write_text("unifi:\n  host: 10.0.0.1\n  site: default\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["config", "validate", "--config", str(cfg), "--strict"])
    assert result.exit_code == 1
    assert "credential" in result.output.lower()


@pytest.mark.fast
def test_config_validate_strict_fails_integration_without_site_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--strict: api_key без site_id_uuid непригоден для Integration API → exit 1.

    IntegrationClient требует и api_key, и site_id_uuid; раньше один api_key
    проходил strict, а потом `login test --api integration` падал.
    """
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UNIFI_CONFIG_PATH", raising=False)
    for var in ("UNIFI_UNIFI__USERNAME", "UNIFI_UNIFI__PASSWORD", "UNIFI_UNIFI__SITE_ID_UUID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("UNIFI_UNIFI__API_KEY", "deadbeef-key")
    cfg = tmp_path / "config.yaml"
    cfg.write_text("unifi:\n  host: 10.0.0.1\n  site: default\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["config", "validate", "--config", str(cfg), "--strict"])
    assert result.exit_code == 1
    assert "site_id_uuid" in result.output.lower()


@pytest.mark.fast
def test_config_validate_strict_passes_integration_with_site_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--strict: api_key + site_id_uuid — полные Integration-креды → exit 0."""
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UNIFI_CONFIG_PATH", raising=False)
    for var in ("UNIFI_UNIFI__USERNAME", "UNIFI_UNIFI__PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("UNIFI_UNIFI__API_KEY", "deadbeef-key")
    monkeypatch.setenv("UNIFI_UNIFI__SITE_ID_UUID", "00000000-0000-0000-0000-000000000000")
    cfg = tmp_path / "config.yaml"
    cfg.write_text("unifi:\n  host: 10.0.0.1\n  site: default\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["config", "validate", "--config", str(cfg), "--strict"])
    assert result.exit_code == 0


@pytest.mark.fast
def test_config_show_without_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UNIFI_CONFIG_PATH", raising=False)
    (tmp_path / "config.yaml").write_text(
        "unifi:\n  host: 1.2.3.4\n  port: 11443\n  site: t\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("UNIFI_UNIFI__PASSWORD", "super-secret")

    runner = CliRunner()
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "super-secret" not in result.stdout
