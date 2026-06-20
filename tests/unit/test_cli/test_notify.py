"""Тесты CLI notify (test/send) — через NotifyService."""

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from unifi_manager.settings import Settings, TelegramSettings, UnifiAuthSettings


def _settings(
    *, telegram_send: bool = True, enabled: bool = True, token: str | None = "t"
) -> Settings:
    s = Settings(
        unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="t"),
        telegram=TelegramSettings(
            bot_token=SecretStr(token) if token else None, chat_id="1", enabled=enabled
        ),
    )
    s.permissions.cli.notify.telegram_send = telegram_send
    return s


@pytest.mark.fast
def test_notify_send_rejects_bad_level(tmp_path: Path) -> None:
    """T5: --level мусор → Typer отвергает (exit 2), не молчаливый no-op."""
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with patch("unifi_manager.cli.notify.load_settings") as ms:
        ms.return_value = _settings()
        result = runner.invoke(app, ["notify", "send", "x", "--level", "bogus"])
    assert result.exit_code == 2


@pytest.mark.fast
def test_notify_test_respects_kill_switch(tmp_path: Path) -> None:
    """SEC4: telegram_send=false → exit 1, нотифаер не строится (нет сети/отправки)."""
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with patch("unifi_manager.cli.notify.load_settings") as ms:
        ms.return_value = _settings(telegram_send=False)
        result = runner.invoke(app, ["notify", "test"])
    assert result.exit_code == 1


@pytest.mark.fast
def test_notify_send_respects_kill_switch(tmp_path: Path) -> None:
    """SEC4 для send: telegram_send=false → exit 1."""
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with patch("unifi_manager.cli.notify.load_settings") as ms:
        ms.return_value = _settings(telegram_send=False)
        result = runner.invoke(app, ["notify", "send", "hi", "--level", "warn"])
    assert result.exit_code == 1


@pytest.mark.fast
def test_notify_test_broken_config_no_traceback(tmp_path: Path) -> None:
    """enabled + нет токена → channel_unavailable, exit 1, БЕЗ traceback (ValueError не утёк)."""
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with patch("unifi_manager.cli.notify.load_settings") as ms:
        ms.return_value = _settings(enabled=True, token=None)
        result = runner.invoke(app, ["notify", "test"])
    assert result.exit_code == 1
    assert "Traceback" not in result.output


@pytest.mark.fast
def test_notify_test_sent_exits_0(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.services.notify import NotifyReport, NotifyStatus

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.notify.load_settings") as ms,
        patch("unifi_manager.cli.notify.build_notify_service") as bns,
    ):
        ms.return_value = _settings()
        bns.return_value.test.return_value = NotifyReport(status=NotifyStatus.sent, sent=1)
        result = runner.invoke(app, ["notify", "test"])
    assert result.exit_code == 0


@pytest.mark.fast
def test_notify_send_passes_level_enum_and_exits_0(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.services.notify import AlertLevel, NotifyReport, NotifyStatus

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.notify.load_settings") as ms,
        patch("unifi_manager.cli.notify.build_notify_service") as bns,
    ):
        ms.return_value = _settings()
        bns.return_value.send.return_value = NotifyReport(status=NotifyStatus.sent, sent=1)
        result = runner.invoke(app, ["notify", "send", "Test alert", "--level", "warn"])
    assert result.exit_code == 0
    _, kwargs = bns.return_value.send.call_args
    assert kwargs["level"] is AlertLevel.warn
