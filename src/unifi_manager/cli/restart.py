"""CLI commands для restart (auto, profile, device).

Дефолты (D9):
- restart auto — REAL execution (cron command, защиты внутри service)
- restart profile NAME — DRY-RUN default, --apply для real
- restart device --mac — DRY-RUN default, --apply для real
"""

from __future__ import annotations

import logging
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import typer

from unifi_manager.cli._common import (
    build_legacy_client,
    load_settings,
    output_json,
    setup_logging_from_cli,
)
from unifi_manager.services.restart import RestartReport, RestartService

_logger = logging.getLogger(__name__)


class RestartMethod(StrEnum):
    """Допустимые значения `restart device --method`; typer отвергает прочее (exit 2)."""

    restart = "restart"
    poe_cycle = "poe-cycle"


restart_app = typer.Typer(help="Рестарт устройств", no_args_is_help=True)


@restart_app.command("auto", help="Авто-рестарт проблемных AP (для cron)")
def restart_auto(
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Только показать что будет сделано")
    ] = False,
    max_n: Annotated[
        int | None,
        typer.Option("--max", min=1, max=20, help="Override max_restarts_per_run (1-20)"),
    ] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    """REAL execution по умолчанию (cron-friendly)."""
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    if max_n is not None:
        settings.auto_restart.max_restarts_per_run = max_n

    client = build_legacy_client(settings)
    svc = RestartService(legacy_client=client, settings=settings)
    report = svc.auto(dry_run=dry_run)

    _print_report(report, json_output=json_output)


@restart_app.command("profile", help="Restart APs по профилю (DRY-RUN default)")
def restart_profile(
    name: Annotated[str, typer.Argument(help="Имя профиля из restart_profiles config")],
    apply: Annotated[
        bool, typer.Option("--apply", help="РЕАЛЬНЫЙ запуск (default — dry-run)")
    ] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    client = build_legacy_client(settings)
    svc = RestartService(legacy_client=client, settings=settings)
    try:
        report = svc.profile(name, apply=apply)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e

    _print_report(report, json_output=json_output)


@restart_app.command("device", help="Точечный restart одного device (DRY-RUN default)")
def restart_device(
    mac: Annotated[str, typer.Option("--mac", help="MAC адрес устройства")],
    method: Annotated[
        RestartMethod, typer.Option("--method", help="restart | poe-cycle")
    ] = RestartMethod.restart,
    apply: Annotated[
        bool, typer.Option("--apply", help="РЕАЛЬНЫЙ запуск (default — dry-run)")
    ] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    # CLI Enum value "poe-cycle" (hyphen) maps to service-expected "poe_cycle"
    method_normalized: Literal["restart", "poe_cycle"] = (
        "poe_cycle" if method is RestartMethod.poe_cycle else "restart"
    )

    client = build_legacy_client(settings)
    svc = RestartService(legacy_client=client, settings=settings)
    report = svc.device(mac=mac, method=method_normalized, apply=apply)

    _print_report(report, json_output=json_output)


def _print_report(report: RestartReport, *, json_output: bool) -> None:
    if json_output:
        output_json(
            {
                "status": report.status,
                "dry_run": report.dry_run,
                "actions": [
                    {
                        "mac": a.mac,
                        "name": a.name,
                        "action": a.action,
                        "reason": a.reason,
                        "status": a.status,
                    }
                    for a in report.actions
                ],
            }
        )
        return

    mode = "DRY-RUN" if report.dry_run else "APPLY"
    typer.echo(f"[{mode}] Status: {report.status}, Actions: {len(report.actions)}")
    for action in report.actions:
        typer.echo(f"  {action.action} {action.mac} ({action.name}): {action.status}")
        typer.echo(f"    Reason: {action.reason}")
