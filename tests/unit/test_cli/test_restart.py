"""Тесты для unifi_manager.cli.restart."""

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from unifi_manager.settings import Settings, UnifiAuthSettings


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(
        unifi=UnifiAuthSettings(
            host="1.2.3.4", port=11443, site="t", username=SecretStr("u"), password=SecretStr("p")
        ),
    )


@pytest.mark.fast
def test_restart_auto_default_is_real_execution(tmp_path: Path) -> None:
    """restart auto — REAL execution по умолчанию (cron command)."""
    from unifi_manager.cli.main import app
    from unifi_manager.services.restart import RestartReport

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.restart.load_settings") as mock_settings,
        patch("unifi_manager.cli.restart.build_legacy_client"),
        patch("unifi_manager.cli.restart.RestartService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.auto.return_value = RestartReport(
            status="completed", dry_run=False, actions=[]
        )
        result = runner.invoke(app, ["restart", "auto"])

    assert result.exit_code == 0
    mock_svc.return_value.auto.assert_called_once_with(dry_run=False)


@pytest.mark.fast
def test_restart_auto_dry_run_flag(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.services.restart import RestartReport

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.restart.load_settings") as mock_settings,
        patch("unifi_manager.cli.restart.build_legacy_client"),
        patch("unifi_manager.cli.restart.RestartService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.auto.return_value = RestartReport(
            status="completed", dry_run=True, actions=[]
        )
        result = runner.invoke(app, ["restart", "auto", "--dry-run"])

    assert result.exit_code == 0
    mock_svc.return_value.auto.assert_called_once_with(dry_run=True)


@pytest.mark.fast
def test_restart_profile_default_is_dry_run(tmp_path: Path) -> None:
    """restart profile NAME — DRY-RUN default."""
    from unifi_manager.cli.main import app
    from unifi_manager.services.restart import RestartReport

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.restart.load_settings") as mock_settings,
        patch("unifi_manager.cli.restart.build_legacy_client"),
        patch("unifi_manager.cli.restart.RestartService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.profile.return_value = RestartReport(
            status="completed", dry_run=True, actions=[]
        )
        result = runner.invoke(app, ["restart", "profile", "restaurant"])

    assert result.exit_code == 0
    mock_svc.return_value.profile.assert_called_once_with("restaurant", apply=False)
    assert "DRY" in result.stdout.upper()


@pytest.mark.fast
def test_restart_profile_apply_flag(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.services.restart import RestartReport

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.restart.load_settings") as mock_settings,
        patch("unifi_manager.cli.restart.build_legacy_client"),
        patch("unifi_manager.cli.restart.RestartService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.profile.return_value = RestartReport(
            status="completed", dry_run=False, actions=[]
        )
        result = runner.invoke(app, ["restart", "profile", "restaurant", "--apply"])

    assert result.exit_code == 0
    mock_svc.return_value.profile.assert_called_once_with("restaurant", apply=True)


@pytest.mark.fast
def test_restart_device_default_dry_run(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.services.restart import RestartReport

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.restart.load_settings") as mock_settings,
        patch("unifi_manager.cli.restart.build_legacy_client"),
        patch("unifi_manager.cli.restart.RestartService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.device.return_value = RestartReport(
            status="completed", dry_run=True, actions=[]
        )
        result = runner.invoke(app, ["restart", "device", "--mac", "aa:bb:cc:dd:ee:01"])

    assert result.exit_code == 0
    mock_svc.return_value.device.assert_called_once_with(
        mac="aa:bb:cc:dd:ee:01",
        method="restart",
        apply=False,
    )


@pytest.mark.fast
def test_restart_device_apply_with_poe_cycle(tmp_path: Path) -> None:
    """--method poe-cycle нормализуется в service-expected 'poe_cycle' (с underscore)."""
    from unifi_manager.cli.main import app
    from unifi_manager.services.restart import RestartReport

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.restart.load_settings") as mock_settings,
        patch("unifi_manager.cli.restart.build_legacy_client"),
        patch("unifi_manager.cli.restart.RestartService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.device.return_value = RestartReport(
            status="completed", dry_run=False, actions=[]
        )
        result = runner.invoke(
            app,
            [
                "restart",
                "device",
                "--mac",
                "aa:bb:cc:dd:ee:01",
                "--method",
                "poe-cycle",
                "--apply",
            ],
        )

    assert result.exit_code == 0
    mock_svc.return_value.device.assert_called_once_with(
        mac="aa:bb:cc:dd:ee:01",
        method="poe_cycle",
        apply=True,
    )


@pytest.mark.fast
def test_restart_device_rejects_invalid_method(tmp_path: Path) -> None:
    """Невалидный --method → CLI отвергает (exit 2); НЕ превращает молча в restart.

    Раньше любое значение кроме 'poe-cycle' становилось 'restart', поэтому опечатка
    (--method reboot --apply) выполняла реальный рестарт вместо отказа.
    """
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.restart.load_settings") as mock_settings,
        patch("unifi_manager.cli.restart.build_legacy_client"),
        patch("unifi_manager.cli.restart.RestartService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        result = runner.invoke(
            app,
            ["restart", "device", "--mac", "aa:bb:cc:dd:ee:01", "--method", "reboot", "--apply"],
        )

    assert result.exit_code == 2, (
        f"expected typer rejection, got {result.exit_code}: {result.output}"
    )
    mock_svc.return_value.device.assert_not_called()


@pytest.mark.fast
def test_restart_profile_unknown_name_exits_1(tmp_path: Path) -> None:
    """Unknown profile name → clean error message, exit 1 (не traceback)."""
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.restart.load_settings") as mock_settings,
        patch("unifi_manager.cli.restart.build_legacy_client"),
        patch("unifi_manager.cli.restart.RestartService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.profile.side_effect = ValueError("unknown profile: 'nonexistent'")
        result = runner.invoke(app, ["restart", "profile", "nonexistent"])

    assert result.exit_code == 1
    assert "Error" in (result.stdout + (result.stderr or ""))


@pytest.mark.fast
def test_restart_auto_rejects_negative_max(tmp_path: Path) -> None:
    """--max -1 → CLI отвергает (exit code != 0), не доходит до settings."""
    from unifi_manager.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["restart", "auto", "--max", "-1", "--dry-run"])
    assert result.exit_code != 0  # Typer range validation rejects


@pytest.mark.fast
def test_restart_auto_rejects_zero_max(tmp_path: Path) -> None:
    """--max 0 → CLI отвергает (exit code != 0)."""
    from unifi_manager.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["restart", "auto", "--max", "0", "--dry-run"])
    assert result.exit_code != 0


@pytest.mark.fast
def test_restart_auto_rejects_too_high_max(tmp_path: Path) -> None:
    """--max 21 → CLI отвергает (exit code != 0)."""
    from unifi_manager.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["restart", "auto", "--max", "21", "--dry-run"])
    assert result.exit_code != 0


# === Phase 4.5: _print_report coverage (lines 112-128, 133-134) ===


@pytest.mark.fast
def test_restart_auto_json_output_with_actions(tmp_path: Path) -> None:
    """--json flag → JSON output with actions array (lines 112-128)."""
    import json as _json

    from unifi_manager.cli.main import app
    from unifi_manager.services.restart import RestartAction, RestartReport

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.restart.load_settings") as mock_settings,
        patch("unifi_manager.cli.restart.build_legacy_client"),
        patch("unifi_manager.cli.restart.RestartService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.auto.return_value = RestartReport(
            status="completed",
            dry_run=False,
            actions=[
                RestartAction(
                    mac="aa:bb:cc:dd:ee:01",
                    name="Restoran",
                    action="restart",
                    reason="test",
                    status="success",
                )
            ],
        )
        result = runner.invoke(app, ["restart", "auto", "--json"])

    assert result.exit_code == 0
    parsed = _json.loads(result.stdout)
    assert parsed["status"] == "completed"
    assert len(parsed["actions"]) == 1
    assert parsed["actions"][0]["mac"] == "aa:bb:cc:dd:ee:01"


@pytest.mark.fast
def test_restart_auto_text_output_with_actions(tmp_path: Path) -> None:
    """Text output with actions → each action printed (lines 130-134)."""
    from unifi_manager.cli.main import app
    from unifi_manager.services.restart import RestartAction, RestartReport

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.restart.load_settings") as mock_settings,
        patch("unifi_manager.cli.restart.build_legacy_client"),
        patch("unifi_manager.cli.restart.RestartService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.auto.return_value = RestartReport(
            status="completed",
            dry_run=False,
            actions=[
                RestartAction(
                    mac="aa:bb:cc:dd:ee:01",
                    name="Restoran",
                    action="restart",
                    reason="lost contact",
                    status="success",
                )
            ],
        )
        result = runner.invoke(app, ["restart", "auto"])

    assert result.exit_code == 0
    assert "aa:bb:cc:dd:ee:01" in result.stdout
    assert "Restoran" in result.stdout


@pytest.mark.fast
def test_restart_auto_max_override(tmp_path: Path) -> None:
    """--max N overrides settings.auto_restart.max_restarts_per_run (line 49)."""
    from unifi_manager.cli.main import app
    from unifi_manager.services.restart import RestartReport

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.restart.load_settings") as mock_settings,
        patch("unifi_manager.cli.restart.build_legacy_client"),
        patch("unifi_manager.cli.restart.RestartService") as mock_svc,
    ):
        settings = _test_settings(tmp_path)
        mock_settings.return_value = settings
        mock_svc.return_value.auto.return_value = RestartReport(
            status="no_candidates", dry_run=False, actions=[]
        )
        result = runner.invoke(app, ["restart", "auto", "--max", "3"])

    assert result.exit_code == 0
    assert settings.auto_restart.max_restarts_per_run == 3
