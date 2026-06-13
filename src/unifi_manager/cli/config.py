"""CLI: config validate, config show."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import SecretStr, ValidationError

from unifi_manager.cli._common import load_settings, setup_logging_from_cli

config_app = typer.Typer(help="Управление конфигурацией", no_args_is_help=True)


@config_app.command("validate", help="Валидация config.yaml + .env")
def config_validate(
    config: Annotated[Path | None, typer.Option("--config")] = None,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
    strict: Annotated[
        bool, typer.Option("--strict", help="Также проверить, что секреты подгрузились (.env)")
    ] = False,
) -> None:
    try:
        settings = load_settings(config_path=config)
    except ValidationError as e:
        typer.echo(f"Validation error:\n{e}", err=True)
        raise typer.Exit(code=1) from e
    except Exception as e:
        typer.echo(f"Error loading config: {e}", err=True)
        raise typer.Exit(code=1) from e

    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)
    u = settings.unifi
    has_legacy = u.username is not None and u.password is not None
    has_integration = u.api_key is not None and u.site_id_uuid is not None
    if strict and not (has_legacy or has_integration):
        typer.echo(
            "[FAIL] Strict: no usable credentials - need (username+password) or "
            "(api_key+site_id_uuid). Check that .env was found "
            "(see --env-file / UNIFI_ENV_FILE / beside config.yaml).",
            err=True,
        )
        raise typer.Exit(code=1)
    typer.echo(f"[OK] Config valid (host={u.host}, site={u.site})")
    if strict:
        typer.echo(
            f"[OK] Strict: credentials present (legacy={has_legacy}, integration={has_integration})"
        )


@config_app.command("show", help="Показать рассчитанный config (--secrets для unmask)")
def config_show(
    secrets: Annotated[
        bool, typer.Option("--secrets", help="Показать секреты в открытую (требует TTY)")
    ] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    import sys

    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    # Защита от случайного pipe — секреты только в TTY
    if secrets and not sys.stdout.isatty():
        typer.echo(
            "Error: --secrets refuses to print to non-TTY (use TTY interactive shell)", err=True
        )
        raise typer.Exit(code=2)

    data = settings.model_dump(mode="json")
    if secrets:
        data = _unmask_secrets(settings)
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _unmask_secrets(settings: object) -> dict[str, object]:
    """Заменяет masked SecretStr на actual values при walk через model."""

    def walk(model: object) -> dict[str, object]:
        out: dict[str, object] = {}
        for field_name, value in model.__dict__.items():
            if isinstance(value, SecretStr):
                out[field_name] = value.get_secret_value()
            elif hasattr(value, "__dict__") and not isinstance(
                value, list | dict | str | int | float | bool | type(None)
            ):
                out[field_name] = walk(value)
            else:
                out[field_name] = value
        return out

    return walk(settings)
