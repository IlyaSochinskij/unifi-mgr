"""Тесты root CLI app."""

import re

import pytest
from typer.testing import CliRunner

from unifi_manager import __version__


@pytest.mark.fast()
def test_version_flag_prints_version() -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


@pytest.mark.fast()
def test_help_flag_works() -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "unifi-mgr" in result.stdout.lower() or "Usage" in result.stdout


@pytest.mark.fast()
def test_invoking_without_args_shows_help() -> None:
    """Запуск unifi-mgr без аргументов показывает help, exit 0 или 2."""
    from unifi_manager.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, [])
    # Typer по умолчанию exit 2 + help; либо app настроен no_args_is_help=True
    assert result.exit_code in (0, 2)
    assert "Usage" in result.stdout or "Usage" in (result.stderr or "")


@pytest.mark.fast()
def test_subcommand_audit_exists() -> None:
    """Подкоманда audit зарегистрирована (stub, ничего не делает в фазе 0)."""
    from unifi_manager.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["audit", "--help"])
    assert result.exit_code == 0


@pytest.mark.fast()
def test_subcommand_restart_exists() -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["restart", "--help"])
    assert result.exit_code == 0


@pytest.mark.fast()
def test_subcommand_config_exists() -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["config", "--help"])
    assert result.exit_code == 0


@pytest.mark.fast()
def test_subcommand_audit_critical_is_real_command() -> None:
    """audit critical зарегистрирована как реальная команда (Phase 4 — не stub).
    Без config.yaml завершается с ненулевым exit code (Settings validation error)."""
    from unifi_manager.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["audit", "critical", "--help"])
    assert result.exit_code == 0
    # Убедились что команда реальная (не stub): --help показывает описание
    assert re.search(r"critical|issues|telegram", result.stdout, re.IGNORECASE)


@pytest.mark.fast()
def test_global_config_flag_sets_env(tmp_path) -> None:
    """`unifi-mgr --config X config validate` (флаг ДО подкоманды) работает."""
    from typer.testing import CliRunner

    from unifi_manager.cli.main import app

    cfg = tmp_path / "config.yaml"
    cfg.write_text("unifi:\n  host: 10.0.0.1\n  site: default\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["--config", str(cfg), "config", "validate"])
    assert result.exit_code == 0, result.output
    assert "Config valid" in result.output
