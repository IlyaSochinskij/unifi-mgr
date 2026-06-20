"""CLI: notify test, notify send — через NotifyService (single authority)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from unifi_manager.cli._common import (
    build_notify_service,
    load_settings,
    setup_logging_from_cli,
)
from unifi_manager.services.notify import AlertLevel, NotifyReport, NotifyStatus

notify_app = typer.Typer(help="Уведомления (Telegram)", no_args_is_help=True)

_STATUS_LINE: dict[NotifyStatus, str] = {
    NotifyStatus.sent: "Sent",
    NotifyStatus.skipped_permissions: "Suppressed by permissions.cli.notify.telegram_send=false",
    NotifyStatus.skipped_disabled: "Telegram disabled (telegram.enabled=false)",
    NotifyStatus.channel_unavailable: "Telegram unavailable (missing bot_token/chat_id)",
    NotifyStatus.failed: "Failed (rate-limit or HTTP error)",
}


def _emit(report: NotifyReport) -> None:
    """Печать строки исхода + exit-код: 0 только при sent, иначе 1 (§5)."""
    sent = report.status is NotifyStatus.sent
    typer.echo(_STATUS_LINE.get(report.status, report.status.value), err=not sent)
    raise typer.Exit(code=0 if sent else 1)


@notify_app.command("test", help="Отправить тестовое сообщение")
def notify_test(
    config: Annotated[Path | None, typer.Option("--config")] = None,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)
    _emit(build_notify_service(settings).test())


@notify_app.command("send", help="Отправить custom сообщение")
def notify_send(
    text: Annotated[str, typer.Argument(help="Текст сообщения")],
    level: Annotated[
        AlertLevel, typer.Option("--level", help="info | warn | crit")
    ] = AlertLevel.info,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)
    _emit(build_notify_service(settings).send(text, level=level))
