"""Тесты для unifi_manager.cli.audit."""

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from unifi_manager.settings import Settings, UnifiAuthSettings


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(
        unifi=UnifiAuthSettings(
            host="1.2.3.4", port=11443, site="t", username=SecretStr("u"), password=SecretStr("p")
        ),
    )


@pytest.mark.fast
def test_audit_critical_no_issues_exits_0(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.audit.load_settings") as mock_settings,
        patch("unifi_manager.cli.audit.build_legacy_client"),
        patch("unifi_manager.cli.audit.AuditService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.critical.return_value = []
        result = runner.invoke(app, ["audit", "critical"])
    assert result.exit_code == 0


@pytest.mark.fast
def test_audit_critical_with_issues_exits_1(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.services.audit import AuditIssue

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.audit.load_settings") as mock_settings,
        patch("unifi_manager.cli.audit.build_legacy_client"),
        patch("unifi_manager.cli.audit.AuditService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.critical.return_value = [
            AuditIssue(
                issue_type="offline",
                device_mac="aa:bb",
                device_name="Restoran",
                severity="critical",
            ),
        ]
        result = runner.invoke(app, ["audit", "critical"])
    assert result.exit_code == 1
    assert "Restoran" in result.stdout or "aa:bb" in result.stdout


@pytest.mark.fast
def test_audit_critical_json_format(tmp_path: Path) -> None:
    import json

    from unifi_manager.cli.main import app
    from unifi_manager.services.audit import AuditIssue

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.audit.load_settings") as mock_settings,
        patch("unifi_manager.cli.audit.build_legacy_client"),
        patch("unifi_manager.cli.audit.AuditService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.critical.return_value = [
            AuditIssue(
                issue_type="offline",
                device_mac="aa:bb",
                device_name="Restoran",
                severity="critical",
            ),
        ]
        result = runner.invoke(app, ["audit", "critical", "--json"])

    assert result.exit_code == 1
    parsed = json.loads(result.stdout)
    assert len(parsed) == 1
    assert parsed[0]["device_mac"] == "aa:bb"


@pytest.mark.fast
def test_audit_status_prints_summary(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.services.audit import StatusSummary

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.audit.load_settings") as mock_settings,
        patch("unifi_manager.cli.audit.build_legacy_client"),
        patch("unifi_manager.cli.audit.AuditService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.status.return_value = StatusSummary(
            total=270,
            online=268,
            offline=2,
            by_type={"uap": 260, "usw": 10},
        )
        result = runner.invoke(app, ["audit", "status"])

    assert result.exit_code == 0
    assert "270" in result.stdout
    assert "uap" in result.stdout.lower() or "ap" in result.stdout.lower()


@pytest.mark.fast
def test_audit_full_uses_both_apis_when_api_both(tmp_path: Path) -> None:
    """--api both → передаёт оба клиента в AuditService."""
    from unifi_manager.cli.main import app
    from unifi_manager.services.audit import FullAuditReport

    runner = CliRunner()
    settings = _test_settings(tmp_path)
    settings.unifi.site_id_uuid = "bbffb94c-1234-5678-9abc-def012345678"
    settings.unifi.api_key = SecretStr("k")

    with (
        patch("unifi_manager.cli.audit.load_settings") as mock_settings,
        patch("unifi_manager.cli.audit.build_legacy_client"),
        patch("unifi_manager.cli.audit.build_integration_client"),
        patch("unifi_manager.cli.audit.AuditService") as mock_svc,
    ):
        mock_settings.return_value = settings
        mock_svc.return_value.full.return_value = FullAuditReport(devices=[])
        result = runner.invoke(app, ["audit", "full", "--api", "both"])

    assert result.exit_code == 0
    # AuditService должен быть вызван с обоими клиентами
    call_kwargs = mock_svc.call_args.kwargs
    assert "integration_client" in call_kwargs


@pytest.mark.fast
def test_audit_full_api_integration_skips_legacy(tmp_path: Path) -> None:
    """audit full --api integration → строит integration client, НЕ legacy (integration-only)."""
    from unifi_manager.cli.main import app
    from unifi_manager.services.audit import FullAuditReport

    runner = CliRunner()
    settings = _test_settings(tmp_path)
    settings.unifi.site_id_uuid = "bbffb94c-1234-5678-9abc-def012345678"
    settings.unifi.api_key = SecretStr("k")

    with (
        patch("unifi_manager.cli.audit.load_settings") as mock_settings,
        patch("unifi_manager.cli.audit.build_legacy_client") as mock_legacy,
        patch("unifi_manager.cli.audit.build_integration_client") as mock_integration,
        patch("unifi_manager.cli.audit.AuditService") as mock_svc,
    ):
        mock_settings.return_value = settings
        mock_svc.return_value.full.return_value = FullAuditReport(devices=[])
        result = runner.invoke(app, ["audit", "full", "--api", "integration"])

    assert result.exit_code == 0
    mock_legacy.assert_not_called()
    mock_integration.assert_called_once()
    assert mock_svc.call_args.kwargs["legacy_client"] is None


@pytest.mark.fast
def test_audit_light_runs(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.services.audit import LightAuditReport

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.audit.load_settings") as mock_settings,
        patch("unifi_manager.cli.audit.build_legacy_client"),
        patch("unifi_manager.cli.audit.AuditService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.light.return_value = LightAuditReport(
            duplicate_macs=[],
            locally_administered=[],
            clients_per_ap={},
        )
        result = runner.invoke(app, ["audit", "light"])

    assert result.exit_code == 0


@pytest.mark.fast
def test_audit_trends_default_days(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.services.audit import TrendsReport

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.audit.load_settings") as mock_settings,
        patch("unifi_manager.cli.audit.build_legacy_client"),
        patch("unifi_manager.cli.audit.AuditService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.trends.return_value = TrendsReport(data_points=[])
        result = runner.invoke(app, ["audit", "trends", "--days", "14"])

    assert result.exit_code == 0
    mock_svc.return_value.trends.assert_called_once_with(days=14)


@pytest.mark.fast
def test_audit_critical_telegram_notifies_and_exits_by_issues(tmp_path: Path) -> None:
    """--telegram → NotifyService.notify_audit_issues(issues); exit-код по issues."""
    from unifi_manager.cli.main import app
    from unifi_manager.services.audit import AuditIssue
    from unifi_manager.services.notify import NotifyReport, NotifyStatus

    runner = CliRunner()
    issues = [
        AuditIssue(issue_type="offline", device_mac="aa:bb", device_name="x", severity="critical")
    ]
    with (
        patch("unifi_manager.cli.audit.load_settings") as mock_settings,
        patch("unifi_manager.cli.audit.build_legacy_client"),
        patch("unifi_manager.cli.audit.AuditService") as mock_svc,
        patch("unifi_manager.cli.audit.build_notify_service") as bns,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.critical.return_value = issues
        bns.return_value.notify_audit_issues.return_value = NotifyReport(
            status=NotifyStatus.sent, sent=1
        )
        result = runner.invoke(app, ["audit", "critical", "--telegram"])

    assert result.exit_code == 1  # по issues
    bns.return_value.notify_audit_issues.assert_called_once_with(issues)


@pytest.mark.fast
def test_audit_critical_broken_telegram_exits_by_issues(tmp_path: Path) -> None:
    """test #3 / acceptance #8: issues + broken Telegram (enabled, нет токена) → exit 1
    ПОТОМУ ЧТО issues, а не из-за notify-краха; ValueError не утекает (нет traceback)."""
    from unifi_manager.cli.main import app
    from unifi_manager.services.audit import AuditIssue

    settings = _test_settings(tmp_path)
    settings.telegram = settings.telegram.model_copy(update={"enabled": True, "bot_token": None})
    issues = [
        AuditIssue(issue_type="offline", device_mac="aa:bb", device_name="x", severity="critical")
    ]
    runner = CliRunner()
    with (
        patch("unifi_manager.cli.audit.load_settings") as mock_settings,
        patch("unifi_manager.cli.audit.build_legacy_client"),
        patch("unifi_manager.cli.audit.AuditService") as mock_svc,
    ):
        mock_settings.return_value = settings
        mock_svc.return_value.critical.return_value = issues
        result = runner.invoke(app, ["audit", "critical", "--telegram"])

    assert result.exit_code == 1
    assert "Traceback" not in result.output


@pytest.mark.fast
def test_audit_full_rejects_invalid_api(tmp_path: Path) -> None:
    """audit full --api typo → CLI отвергает (exit 2), не игнорирует молча."""
    from unifi_manager.cli.main import app
    from unifi_manager.services.audit import FullAuditReport

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.audit.load_settings") as mock_settings,
        patch("unifi_manager.cli.audit.build_legacy_client"),
        patch("unifi_manager.cli.audit.AuditService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.full.return_value = FullAuditReport(devices=[])
        result = runner.invoke(app, ["audit", "full", "--api", "typo"])

    assert result.exit_code == 2, f"expected rejection, got {result.exit_code}: {result.output}"
    mock_svc.return_value.full.assert_not_called()


@pytest.mark.fast
def test_audit_full_json_redacts_secrets_by_default(tmp_path: Path) -> None:
    """audit full --json НЕ должен сливать device-секреты (x_authkey и т.п.) в stdout/лог."""
    from unifi_manager.cli.main import app
    from unifi_manager.services.audit import FullAuditReport

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.audit.load_settings") as mock_settings,
        patch("unifi_manager.cli.audit.build_legacy_client"),
        patch("unifi_manager.cli.audit.AuditService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.full.return_value = FullAuditReport(
            devices=[{"mac": "aa:bb", "name": "AP-01", "x_authkey": "TOPSECRET"}]
        )
        result = runner.invoke(app, ["audit", "full", "--api", "legacy", "--json"])

    assert result.exit_code == 0
    assert "TOPSECRET" not in result.output
    assert "x_authkey" not in result.output
    assert "aa:bb" in result.output  # несекретные поля остаются


@pytest.mark.fast
def test_audit_full_json_raw_includes_secrets_with_warning(tmp_path: Path) -> None:
    """audit full --json --raw — явный opt-in: сырой payload + warning в stderr."""
    from unifi_manager.cli.main import app
    from unifi_manager.services.audit import FullAuditReport

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.audit.load_settings") as mock_settings,
        patch("unifi_manager.cli.audit.build_legacy_client"),
        patch("unifi_manager.cli.audit.AuditService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.full.return_value = FullAuditReport(
            devices=[{"mac": "aa:bb", "name": "AP-01", "x_authkey": "TOPSECRET"}]
        )
        result = runner.invoke(app, ["audit", "full", "--api", "legacy", "--json", "--raw"])

    assert result.exit_code == 0
    assert "TOPSECRET" in result.output  # raw → секреты присутствуют
    assert "raw" in result.stderr.lower()  # предупреждение об опасности
