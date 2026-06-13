"""CLI commands для export (clients, devices)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Annotated, Literal, cast

import typer

from unifi_manager.cli._common import (
    build_legacy_client,
    load_settings,
    setup_logging_from_cli,
)
from unifi_manager.services.export import ExportService

_logger = logging.getLogger(__name__)

export_app = typer.Typer(help="Экспорт данных", no_args_is_help=True)


@export_app.command("clients", help="Экспорт списка клиентов в CSV/JSON")
def export_clients(
    fmt: Annotated[str, typer.Option("--format", help="csv | json")] = "csv",
    out: Annotated[
        Path | None, typer.Option("--out", help="Файл для записи (default — stdout)")
    ] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    if fmt not in ("csv", "json"):
        typer.echo(f"Error: unsupported format {fmt!r}", err=True)
        raise typer.Exit(code=2)

    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    client = build_legacy_client(settings)
    svc = ExportService(legacy_client=client)

    fmt_lit = cast(Literal["csv", "json"], fmt)
    if out is None:
        svc.export_clients(output=sys.stdout, fmt=fmt_lit)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            svc.export_clients(output=f, fmt=fmt_lit)
        typer.echo(f"Wrote {out}", err=True)


@export_app.command("devices", help="Экспорт списка устройств в CSV/JSON")
def export_devices(
    fmt: Annotated[str, typer.Option("--format", help="csv | json")] = "csv",
    out: Annotated[Path | None, typer.Option("--out")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
    raw: Annotated[
        bool,
        typer.Option("--raw", help="Сырые поля UniFi, ВКЛЮЧАЯ СЕКРЕТЫ (x_authkey и т.п.) — опасно"),
    ] = False,
) -> None:
    if fmt not in ("csv", "json"):
        typer.echo(f"Error: unsupported format {fmt!r}", err=True)
        raise typer.Exit(code=2)

    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    if raw:
        _logger.warning(
            "export devices --raw: вывод содержит сырые поля UniFi, включая секреты "
            "(x_authkey, x_adopt_password, x_vwirekey, ...). "
            "DO NOT commit or share this file."
        )

    client = build_legacy_client(settings)
    svc = ExportService(legacy_client=client)

    fmt_lit = cast(Literal["csv", "json"], fmt)
    if out is None:
        svc.export_devices(output=sys.stdout, fmt=fmt_lit, raw=raw)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            svc.export_devices(output=f, fmt=fmt_lit, raw=raw)
        typer.echo(f"Wrote {out}", err=True)
