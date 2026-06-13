"""CLI: notify test, notify send."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from unifi_manager.cli._common import load_settings, setup_logging_from_cli
from unifi_manager.integrations.telegram import TelegramNotifier

notify_app = typer.Typer(help="Уведомления (Telegram)", no_args_is_help=True)


@notify_app.command("test", help="Отправить тестовое сообщение")
def notify_test(
    config: Annotated[Path | None, typer.Option("--config")] = None,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    try:
        notifier = TelegramNotifier(
            settings=settings.telegram,
            rate_limit_state=settings.paths.cache_dir / "telegram_throttle.json",
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e
    ok = notifier.send_message("✓ unifi-mgr test message", hash_key="cli-test")
    if ok:
        typer.echo("Sent test message")
    else:
        typer.echo("Failed to send (rate-limit, disabled, or HTTP error)", err=True)
        raise typer.Exit(code=1)


@notify_app.command("send", help="Отправить custom сообщение")
def notify_send(
    text: Annotated[str, typer.Argument(help="Текст сообщения")],
    level: Annotated[str, typer.Option("--level", help="info | warn | crit")] = "info",
    config: Annotated[Path | None, typer.Option("--config")] = None,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    icon = {"info": "ℹ", "warn": "⚠", "crit": "🚨"}.get(level, "")
    try:
        notifier = TelegramNotifier(
            settings=settings.telegram,
            rate_limit_state=settings.paths.cache_dir / "telegram_throttle.json",
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e
    ok = notifier.send_message(f"{icon} {text}", hash_key=f"cli-send:{level}:{text[:32]}")
    raise typer.Exit(code=0 if ok else 1)
