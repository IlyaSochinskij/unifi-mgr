from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from unifi_manager.settings import Settings, UnifiAuthSettings


@pytest.mark.fast
def test_login_test_legacy_success(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.login.load_settings") as mock_settings,
        patch("unifi_manager.cli.login.build_legacy_client") as mock_client,
    ):
        mock_settings.return_value = Settings(
            unifi=UnifiAuthSettings(
                host="1.2.3.4",
                port=11443,
                site="t",
                username=SecretStr("u"),
                password=SecretStr("p"),
            ),
        )
        mock_client.return_value.login.return_value = True

        result = runner.invoke(app, ["login", "test", "--api", "legacy"])

    assert result.exit_code == 0
    assert "OK" in result.stdout


@pytest.mark.fast
def test_login_test_failure_exits_1(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.clients.exceptions import UnifiAuthError

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.login.load_settings") as mock_settings,
        patch("unifi_manager.cli.login.build_legacy_client") as mock_client,
    ):
        mock_settings.return_value = Settings(
            unifi=UnifiAuthSettings(
                host="1.2.3.4",
                port=11443,
                site="t",
                username=SecretStr("u"),
                password=SecretStr("p"),
            ),
        )
        mock_client.return_value.login.side_effect = UnifiAuthError("bad password")

        result = runner.invoke(app, ["login", "test", "--api", "legacy"])

    assert result.exit_code == 1


@pytest.mark.fast
def test_login_test_rejects_invalid_api(tmp_path: Path) -> None:
    """--api typo → CLI отвергает (exit 2). Раньше тихо выходил 0 без единой проверки."""
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.login.load_settings") as mock_settings,
        patch("unifi_manager.cli.login.build_legacy_client") as mock_legacy,
        patch("unifi_manager.cli.login.build_integration_client") as mock_integration,
    ):
        mock_settings.return_value = Settings(
            unifi=UnifiAuthSettings(
                host="1.2.3.4",
                port=11443,
                site="t",
                username=SecretStr("u"),
                password=SecretStr("p"),
            ),
        )
        result = runner.invoke(app, ["login", "test", "--api", "typo"])

    assert result.exit_code == 2, f"expected rejection, got {result.exit_code}: {result.output}"
    mock_legacy.assert_not_called()
    mock_integration.assert_not_called()
