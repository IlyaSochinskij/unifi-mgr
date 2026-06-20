"""CLI commands для audit (critical, status, full, light, trends).

Реализация Phase 4 — заменяет stub-команды из Phase 0.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

from unifi_manager.cli._common import (
    ApiChoice,
    build_integration_client,
    build_legacy_client,
    build_notify_service,
    load_settings,
    output_json,
    setup_logging_from_cli,
)
from unifi_manager.services.audit import AuditService
from unifi_manager.utils.redact import redact_secrets

_logger = logging.getLogger(__name__)

audit_app = typer.Typer(help="Аудит и мониторинг сети", no_args_is_help=True)


@audit_app.command("critical", help="Быстрая проверка критических проблем")
def audit_critical(
    config: Annotated[Path | None, typer.Option("--config", help="Путь к config.yaml")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output для cron")] = False,
    telegram: Annotated[
        bool, typer.Option("--telegram", help="Отправить алерт в Telegram при наличии issues")
    ] = False,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    """Returns exit code 0 = OK, 1 = критические проблемы найдены."""
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    client = build_legacy_client(settings)
    svc = AuditService(legacy_client=client, settings=settings)
    issues = svc.critical()

    if json_output:
        output_json([_issue_to_dict(i) for i in issues])
    else:
        if not issues:
            typer.echo("OK: No critical issues found")
        else:
            typer.echo(f"CRITICAL: {len(issues)} critical issue(s) found:")
            for issue in issues:
                typer.echo(
                    f"  [{issue.severity.upper()}] {issue.issue_type}: "
                    f"{issue.device_name} ({issue.device_mac})"
                )

    # Telegram уведомление — оркестрация в NotifyService (permission/dedup/format там).
    if telegram and issues:
        report = build_notify_service(settings).notify_audit_issues(issues)
        _logger.info(
            "notify: %s (sent=%d dedup=%d failed=%d)",
            report.status.value,
            report.sent,
            report.skipped_dedup,
            report.failed,
        )

    # exit-код строго по audit issues, НЕ по notify (broken Telegram не маскирует issues).
    raise typer.Exit(code=1 if issues else 0)


@audit_app.command("status", help="Inventory snapshot — total/online/offline по типам")
def audit_status(
    config: Annotated[Path | None, typer.Option("--config")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    client = build_legacy_client(settings)
    svc = AuditService(legacy_client=client, settings=settings)
    status = svc.status()

    if json_output:
        output_json(
            {
                "total": status.total,
                "online": status.online,
                "offline": status.offline,
                "by_type": status.by_type,
            }
        )
    else:
        typer.echo(f"Total: {status.total}")
        typer.echo(f"Online: {status.online}")
        typer.echo(f"Offline: {status.offline}")
        typer.echo("By type:")
        for t, n in sorted(status.by_type.items()):
            typer.echo(f"  {t}: {n}")


@audit_app.command("full", help="Глубокий аудит (оба API)")
def audit_full(
    api: Annotated[
        ApiChoice, typer.Option("--api", help="legacy | integration | both")
    ] = ApiChoice.both,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    raw: Annotated[
        bool,
        typer.Option(
            "--raw",
            help="Сырой payload UniFi без санитизации — ОПАСНО (содержит x_authkey и т.п.)",
        ),
    ] = False,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    legacy = build_legacy_client(settings) if api in (ApiChoice.legacy, ApiChoice.both) else None
    integration = None
    if api in (ApiChoice.integration, ApiChoice.both):
        try:
            integration = build_integration_client(settings)
        except Exception as e:
            _logger.warning("Integration client unavailable: %s", e)
            if api == ApiChoice.integration:
                raise typer.Exit(code=2) from e

    svc = AuditService(legacy_client=legacy, settings=settings, integration_client=integration)
    report = svc.full()

    # По умолчанию вырезаем секреты устройств (x_authkey, x_aes_gcm, ...): этот вывод
    # уходит в cron-лог. --raw — явный opt-in для отладки, с предупреждением в stderr.
    if raw:
        typer.echo(
            "WARNING: --raw emits unsanitized device payloads (secrets like x_authkey). "
            "Do not pipe into shared logs.",
            err=True,
        )
        devices = report.devices
    else:
        devices = [redact_secrets(d) for d in report.devices]

    if json_output:
        output_json({"devices": devices})
    else:
        typer.echo(f"Full audit: {len(devices)} devices")


@audit_app.command("light", help="MAC duplicates, locally-administered MACs, перекосы клиентов")
def audit_light(
    config: Annotated[Path | None, typer.Option("--config")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    client = build_legacy_client(settings)
    svc = AuditService(legacy_client=client, settings=settings)
    report = svc.light()

    if json_output:
        output_json(
            {
                "duplicate_macs": [
                    {"mac": d.mac, "hostnames": d.hostnames} for d in report.duplicate_macs
                ],
                "locally_administered": [
                    {"mac": s.mac, "hostname": s.hostname, "ap_mac": s.ap_mac}
                    for s in report.locally_administered
                ],
                "clients_per_ap": report.clients_per_ap,
            }
        )
    else:
        typer.echo(f"Duplicate MACs: {len(report.duplicate_macs)}")
        for d in report.duplicate_macs:
            typer.echo(f"  {d.mac}: {d.hostnames}")
        typer.echo(f"Locally-administered (potential spoof): {len(report.locally_administered)}")
        for s in report.locally_administered:
            typer.echo(f"  {s.mac} ({s.hostname or '<no hostname>'})")


@audit_app.command("trends", help="Анализ исторических отчётов за N дней")
def audit_trends(
    days: Annotated[int, typer.Option("--days", help="Глубина анализа в днях")] = 7,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    client = build_legacy_client(settings)
    svc = AuditService(legacy_client=client, settings=settings)
    report = svc.trends(days=days)

    if json_output:
        output_json({"data_points": report.data_points})
    else:
        typer.echo(f"Trends (last {days} days): {len(report.data_points)} reports")
        for dp in report.data_points:
            typer.echo(
                f"  {dp.get('file', '?')}: "
                f"total={dp.get('total', '?')}, "
                f"offline={dp.get('offline', '?')}"
            )


def _issue_to_dict(issue: object) -> dict[str, object]:
    """Сериализация AuditIssue для --json."""
    return {
        "issue_type": getattr(issue, "issue_type", None),
        "device_mac": getattr(issue, "device_mac", None),
        "device_name": getattr(issue, "device_name", None),
        "severity": getattr(issue, "severity", None),
        "context": getattr(issue, "context", {}),
    }
