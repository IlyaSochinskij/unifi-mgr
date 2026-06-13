from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from unifi_manager.settings import (
    Settings,
    TelegramSettings,
    UnifiAuthSettings,
)


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(
        unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="t"),
        telegram=TelegramSettings(bot_token=SecretStr("t"), chat_id="1", enabled=True),
    )


@pytest.mark.fast
def test_notify_test_calls_send(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.notify.load_settings") as mock_settings,
        patch("unifi_manager.cli.notify.TelegramNotifier") as mock_notif,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_notif.return_value.send_message.return_value = True
        result = runner.invoke(app, ["notify", "test"])

    assert result.exit_code == 0
    mock_notif.return_value.send_message.assert_called_once()


@pytest.mark.fast
def test_notify_test_failure_exits_1(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.notify.load_settings") as mock_settings,
        patch("unifi_manager.cli.notify.TelegramNotifier") as mock_notif,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_notif.return_value.send_message.return_value = False
        result = runner.invoke(app, ["notify", "test"])

    assert result.exit_code == 1


@pytest.mark.fast
def test_notify_send_with_level(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.notify.load_settings") as mock_settings,
        patch("unifi_manager.cli.notify.TelegramNotifier") as mock_notif,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_notif.return_value.send_message.return_value = True
        result = runner.invoke(app, ["notify", "send", "Test alert", "--level", "warn"])

    assert result.exit_code == 0
    call_text = mock_notif.return_value.send_message.call_args.args[0]
    assert "Test alert" in call_text


@pytest.mark.fast
def test_notify_test_missing_token_clean_error(tmp_path: Path) -> None:
    """telegram.enabled=True но bot_token=None → clean error message, exit 1."""
    from unifi_manager.cli.main import app

    settings = Settings(
        unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="t"),
        telegram=TelegramSettings(bot_token=None, chat_id="1", enabled=True),
    )

    runner = CliRunner()
    with patch("unifi_manager.cli.notify.load_settings") as mock_settings:
        mock_settings.return_value = settings
        result = runner.invoke(app, ["notify", "test"])

    assert result.exit_code == 1
    assert "Error" in (result.stdout + (result.stderr or ""))
