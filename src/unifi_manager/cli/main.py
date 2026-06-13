"""Root Typer app для unifi-mgr.

В фазе 0 — только структура подкоманд + --version. Все команды кроме --version/--help
возвращают exit 1 со stub-сообщением. Имплементация подкоманд — в фазах 1-7.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from unifi_manager import __version__
from unifi_manager.cli.audit import audit_app
from unifi_manager.cli.config import config_app
from unifi_manager.cli.export import export_app
from unifi_manager.cli.legacy import legacy_app
from unifi_manager.cli.login import login_app
from unifi_manager.cli.notify import notify_app
from unifi_manager.cli.restart import restart_app
from unifi_manager.cli.zabbix import zabbix_app

app = typer.Typer(
    name="unifi-mgr",
    help="UniFi network management toolkit",
    no_args_is_help=True,
    add_completion=False,
)
diag_app = typer.Typer(help="Диагностика и расследования", no_args_is_help=True)

app.add_typer(audit_app, name="audit")
app.add_typer(restart_app, name="restart")
app.add_typer(export_app, name="export")
app.add_typer(diag_app, name="diag")
app.add_typer(notify_app, name="notify")
app.add_typer(zabbix_app, name="zabbix")
app.add_typer(config_app, name="config")
app.add_typer(login_app, name="login")
app.add_typer(legacy_app, name="legacy")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"unifi-mgr {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Показать версию и выйти"
        ),
    ] = False,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Путь к config.yaml (глобально, до подкоманды)"),
    ] = None,
    env_file: Annotated[
        Path | None,
        typer.Option("--env-file", help="Путь к .env (глобально)"),
    ] = None,
) -> None:
    """UniFi network management toolkit."""
    if config is not None:
        os.environ["UNIFI_CONFIG_PATH"] = str(config)
    if env_file is not None:
        os.environ["UNIFI_ENV_FILE"] = str(env_file)


def _stub(cmd: str) -> None:
    """Помощник для stub-подкоманд фазы 0."""
    typer.echo(f"[phase 0 stub] '{cmd}' not implemented yet — see refactor plan.")
    raise typer.Exit(code=1)


# === Stub подкоманд (фаза 0) ===
# Заменяются настоящими в фазах 1-7. Сейчас существуют только чтобы --help работал
# для всех групп.


if __name__ == "__main__":
    app()
