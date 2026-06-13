"""CLI: legacy run <script_name> — deprecated wrapper для старых скриптов."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

legacy_app = typer.Typer(help="Wrapper для старых скриптов (deprecated)", no_args_is_help=True)


# Дата удаления _legacy/ — после Phase 6
LEGACY_REMOVAL_DATE = "2026-06-13"


def _legacy_dir() -> Path:
    """Путь к _legacy/ относительно current working directory или repo root."""
    cwd_legacy = Path.cwd() / "_legacy"
    if cwd_legacy.is_dir():
        return cwd_legacy
    return Path("_legacy")


@legacy_app.command("run", help="Запустить старый скрипт из _legacy/ (с DeprecationWarning)")
def legacy_run(
    script_name: Annotated[str | None, typer.Argument(help="Имя файла из _legacy/")] = None,
    no_confirm: Annotated[
        bool, typer.Option("-y", "--no-confirm", help="Пропустить confirmation")
    ] = False,
    list_scripts: Annotated[
        bool, typer.Option("--list", help="Показать доступные scripts")
    ] = False,
) -> None:
    legacy_dir = _legacy_dir()

    if list_scripts:
        if not legacy_dir.is_dir():
            typer.echo(f"_legacy/ not found at {legacy_dir}", err=True)
            raise typer.Exit(code=1)
        scripts = sorted(p.name for p in legacy_dir.glob("*.py"))
        for s in scripts:
            typer.echo(s)
        return

    if script_name is None:
        typer.echo("Error: script_name required (or pass --list)", err=True)
        raise typer.Exit(code=2)

    # Strip any path components / traversal — only a bare filename is allowed.
    safe_name = Path(script_name).name
    if safe_name != script_name or not safe_name:
        typer.echo(
            f"Error: invalid script name {script_name!r} (bare filename only, no path components)",
            err=True,
        )
        raise typer.Exit(code=2)

    script_path = legacy_dir / safe_name

    # Defense in depth: ensure the resolved path stays inside legacy_dir.
    if legacy_dir.resolve() not in script_path.resolve().parents:
        typer.echo(f"Error: {script_name!r} escapes _legacy/", err=True)
        raise typer.Exit(code=2)
    if not script_path.is_file():
        typer.echo(f"Script not found: {script_path}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"[WARN] LEGACY MODE - running {script_path}", err=True)
    typer.echo(
        f"[WARN] This script will be REMOVED on {LEGACY_REMOVAL_DATE}. "
        f"Use new `unifi-mgr ...` commands instead.",
        err=True,
    )

    if not no_confirm:
        confirmed = typer.confirm("Continue?", default=False)
        if not confirmed:
            typer.echo("Aborted")
            raise typer.Exit(code=1)

    result = subprocess.run([sys.executable, str(script_path)], check=False)
    raise typer.Exit(code=result.returncode)
