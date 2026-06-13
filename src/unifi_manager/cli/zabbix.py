"""CLI: zabbix stats."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from unifi_manager.cli._common import (
    build_legacy_client,
    load_settings,
    setup_logging_from_cli,
)
from unifi_manager.domain.device import AccessPoint, Device, Switch
from unifi_manager.integrations.zabbix import format_lld_json

zabbix_app = typer.Typer(help="Интеграция с Zabbix", no_args_is_help=True)


@zabbix_app.command("stats", help="LLD JSON для Zabbix external check")
def zabbix_stats(
    config: Annotated[Path | None, typer.Option("--config")] = None,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    client = build_legacy_client(settings)
    raw_devices = client.list_devices_raw()

    devices: list[Device] = []
    for raw in raw_devices:
        try:
            if raw.get("type") == "uap":
                devices.append(AccessPoint.model_validate(raw))
            elif raw.get("type") == "usw":
                devices.append(Switch.model_validate(raw))
        except Exception:
            continue

    typer.echo(format_lld_json(devices))
