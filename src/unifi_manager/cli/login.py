"""CLI: login test — проверка credentials против UniFi."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from unifi_manager.cli._common import (
    ApiChoice,
    build_integration_client,
    build_legacy_client,
    load_settings,
    setup_logging_from_cli,
)
from unifi_manager.clients.exceptions import UnifiError

login_app = typer.Typer(help="Проверка аутентификации", no_args_is_help=True)


@login_app.command("test", help="Проверить login против UniFi (Legacy и/или Integration API)")
def login_test(
    api: Annotated[
        ApiChoice, typer.Option("--api", help="legacy | integration | both")
    ] = ApiChoice.both,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    failures = []

    if api in ("legacy", "both"):
        try:
            legacy_client = build_legacy_client(settings)
            legacy_client.login()
            typer.echo("[OK] Legacy API login OK")
        except UnifiError as e:
            failures.append(f"Legacy: {e}")
            typer.echo(f"[FAIL] Legacy API login failed: {e}", err=True)

    if api in ("integration", "both"):
        try:
            integration_client = build_integration_client(settings)
            integration_client.list_devices_raw()
            typer.echo("[OK] Integration API access OK")
        except UnifiError as e:
            failures.append(f"Integration: {e}")
            typer.echo(f"[FAIL] Integration API failed: {e}", err=True)

    if failures:
        raise typer.Exit(code=1)
