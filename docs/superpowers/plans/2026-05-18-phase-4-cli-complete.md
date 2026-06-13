# Phase 4 — CLI Complete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire все Phase 2-3 services (AuditService, RestartService, ExportService, TelegramNotifier, Zabbix LLD, Settings) к Typer CLI commands. Заменить Phase 0 stub-команды реальной имплементацией. Переписать `dashboard.sh` под новый CLI.

**Architecture:** Каждая CLI group — отдельный модуль `cli/<group>.py`. `cli/_common.py` — shared infrastructure (Settings loader, output formatters, client builders). `cli/main.py` registers все sub-apps. Tests через `typer.testing.CliRunner` с mocked services (НЕ HTTP).

**Tech Stack:** Typer, Rich (для tables/colors), pydantic-settings, существующие services из Phase 2-3.

**Гейт готовности:** `unifi-mgr --help` показывает 9 групп; каждая `unifi-mgr <group> --help` показывает реальные subcommands (не stubs); CliRunner smoke-tests проходят; mypy strict для services/+clients/+domain/+integrations/ остаётся зелёным; coverage 90%+.

**Ветка работы:** `worktree-refactor+v2` (продолжение с Phase 3).

**Связанный спек:** [docs/superpowers/specs/2026-05-16-unifi-manager-refactor-design.md](../specs/2026-05-16-unifi-manager-refactor-design.md), Раздел 2 CLI поверхность.

**Предыдущая фаза:** [phase-3-restart-service.md](2026-05-17-phase-3-restart-service.md) — RestartService, tag `phase-3-complete`.

**Platform notes:** Windows worktree, `.venv/Scripts/`. CLI tests cross-platform.

---

## File Structure

### Создаются (новые):

```
src/unifi_manager/cli/
├── _common.py          # load_settings, setup_logging_from_cli, output_json/human, build_*_client
├── audit.py            # 5 commands: critical, status, full, light, trends
├── restart.py          # 3 commands: auto, profile, device (с правильными dry-run defaults)
├── export.py           # 2 commands: clients, devices
├── notify.py           # 2 commands: test, send
├── zabbix.py           # 1 command: stats (stdout JSON для external check)
├── config.py           # 2 commands: validate, show
├── login.py            # 1 command: test
└── legacy.py           # 1 command: run <script_name>
                        # diag оставляется как stub (Phase 6 при diagnostics port)
                        # device/site mute — Phase 7 (deferred)

scripts/
└── dashboard.sh        # REWRITE под новый CLI (whiptail TUI, как было)
```

### Тесты (новые):

```
tests/unit/test_cli/
├── test_common.py
├── test_audit.py
├── test_restart.py
├── test_export.py
├── test_notify.py
├── test_zabbix.py
├── test_config.py
├── test_login.py
└── test_legacy.py
```

### Модифицируется:

```
src/unifi_manager/cli/main.py    # удаляются inline stub-команды (audit_critical, restart_auto и т.д.),
                                  # вместо них registers sub-apps из новых cli/<group>.py файлов.
                                  # Глобальные флаги остаются (--version, --config, --verbose, и т.д.)

src/unifi_manager/cli/__init__.py # без изменений (app re-export)
```

### НЕ трогаются:

- `src/unifi_manager/clients/`, `services/`, `domain/`, `utils/`, `integrations/`, `settings.py`, `logging_config.py` — Phase 1-3 готовы
- Legacy скрипты в корне репы — Phase 5
- `diag` подкоманды — Phase 6 (когда diagnostics scripts портируются)
- `device mute`/`site mute` — Phase 7 (deferred per D28)
- `audit critical --telegram` — частично работает (notify wire), но controller health check exit code 2 — Phase 7

---

## Common patterns (read before starting)

**TDD цикл:** failing test → run/see fail → implement → run/see pass → commit.

**Test invocation:** `.venv/Scripts/pytest <path> -v --no-cov`. Full suite в конце task: `.venv/Scripts/pytest --no-cov`.

**Mypy:** cli/ НЕ в strict scope per D16 (Phase 0 decision — Typer декораторы сложны для strict). Обычный `mypy src/unifi_manager/cli/` должен проходить.

**Ruff:** all checks pass. Cyrillic → per-file-ignore RUF001/RUF002/RUF003.

**Commit format:** `phase4: <short description>`.

**Existing decisions to honor:**
- `restart auto` — REAL execution по умолчанию (cron command, защиты внутри)
- `restart profile` — DRY-RUN default, `--apply` для real (D9)
- `restart device --mac` — DRY-RUN default, `--apply` для real (D9)
- `audit critical --telegram` — dedup через AlertHistory
- `permissions.cli.*` — гейтят `restart.*` команды (D30 refinement)
- SecretsFilter — register_secrets_from_settings() в _common.py при загрузке Settings
- `--json` глобальный флаг → output_json вместо human format
- Console JSON для cron (parseable), human для интерактива

**Mocking pattern для CLI tests:**
```python
from typer.testing import CliRunner
from unittest.mock import patch, Mock

def test_audit_critical_no_issues():
    runner = CliRunner()
    with patch("unifi_manager.cli.audit.AuditService") as mock_svc, \
         patch("unifi_manager.cli.audit.build_legacy_client") as mock_client, \
         patch("unifi_manager.cli.audit.load_settings") as mock_settings:
        mock_settings.return_value = make_test_settings()
        mock_svc.return_value.critical.return_value = []
        result = runner.invoke(app, ["audit", "critical"])
        assert result.exit_code == 0
```

---

## Task 1: cli/_common.py — Shared infrastructure

**Files:**
- Create: `src/unifi_manager/cli/_common.py`
- Create: `tests/unit/test_cli/test_common.py`

**Goal:** Foundation functions используемые всеми CLI commands: Settings loader, logging setup, output formatters, client builders.

- [ ] **Step 1.1: Write failing tests**

`tests/unit/test_cli/test_common.py`:

```python
"""Тесты для unifi_manager.cli._common."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr


@pytest.mark.fast
def test_load_settings_from_path(tmp_path: Path) -> None:
    """load_settings(config_path) парсит указанный YAML."""
    from unifi_manager.cli._common import load_settings

    config_yaml = tmp_path / "test.yaml"
    config_yaml.write_text(
        "unifi:\n  host: 5.6.7.8\n  port: 11443\n  site: test-site\n",
        encoding="utf-8",
    )

    settings = load_settings(config_path=config_yaml)
    assert settings.unifi.host == "5.6.7.8"
    assert settings.unifi.site == "test-site"


@pytest.mark.fast
def test_load_settings_default_search(tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """load_settings(None) использует _find_yaml() стандартный поиск."""
    from unifi_manager.cli._common import load_settings

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "unifi:\n  host: 1.2.3.4\n  port: 11443\n  site: t\n",
        encoding="utf-8",
    )

    settings = load_settings(config_path=None)
    assert settings.unifi.host == "1.2.3.4"


@pytest.mark.fast
def test_load_settings_registers_secrets(tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """load_settings регистрирует SecretStr поля в SecretsFilter."""
    from unifi_manager.cli._common import load_settings
    from unifi_manager import logging_config

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "unifi:\n  host: 1.2.3.4\n  port: 11443\n  site: t\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("UNIFI_UNIFI__PASSWORD", "super-secret-pass-xyz")

    # Clear any prior state
    logging_config._REGISTERED_SECRETS.clear()

    _ = load_settings(config_path=None)
    assert "super-secret-pass-xyz" in logging_config._REGISTERED_SECRETS


@pytest.mark.fast
def test_output_json_writes_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    """output_json печатает JSON в stdout."""
    from unifi_manager.cli._common import output_json

    output_json({"key": "value", "count": 42})
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed == {"key": "value", "count": 42}


@pytest.mark.fast
def test_output_json_handles_datetime(capsys: pytest.CaptureFixture[str]) -> None:
    """output_json сериализует datetime / pydantic models / dataclasses."""
    from datetime import UTC, datetime
    from unifi_manager.cli._common import output_json

    output_json({"ts": datetime(2026, 5, 18, 10, 0, 0, tzinfo=UTC)})
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert "2026-05-18" in parsed["ts"]


@pytest.mark.fast
def test_build_legacy_client_returns_legacy_client() -> None:
    """build_legacy_client(settings) возвращает LegacyClient инстанс."""
    from unifi_manager.cli._common import build_legacy_client
    from unifi_manager.clients.legacy import LegacyClient
    from unifi_manager.settings import Settings, UnifiAuthSettings

    settings = Settings(
        unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="t",
                                username=SecretStr("u"), password=SecretStr("p")),
    )
    client = build_legacy_client(settings)
    assert isinstance(client, LegacyClient)


@pytest.mark.fast
def test_build_integration_client_returns_integration_client() -> None:
    from unifi_manager.cli._common import build_integration_client
    from unifi_manager.clients.integration import IntegrationClient
    from unifi_manager.settings import Settings, UnifiAuthSettings

    settings = Settings(
        unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="t",
                                site_id_uuid="bbffb94c-1234-5678-9abc-def012345678",
                                api_key=SecretStr("k")),
    )
    client = build_integration_client(settings)
    assert isinstance(client, IntegrationClient)


@pytest.mark.fast
def test_setup_logging_from_cli_uses_verbose() -> None:
    """setup_logging_from_cli(verbose=1) — DEBUG level."""
    import logging
    from unifi_manager.cli._common import setup_logging_from_cli
    from unifi_manager.settings import LoggingSettings

    setup_logging_from_cli(LoggingSettings(log_dir=Path("/tmp/test")),
                           verbose=1, quiet=0)
    assert logging.getLogger().level == logging.DEBUG
```

- [ ] **Step 1.2: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_cli/test_common.py -v --no-cov
```
Expected: ModuleNotFoundError.

- [ ] **Step 1.3: Implement `src/unifi_manager/cli/_common.py`**

```python
"""Shared infrastructure для CLI commands.

Все CLI группы импортируют отсюда:
- load_settings(config_path) — pydantic Settings + secret registration
- setup_logging_from_cli(settings, verbose, quiet) — wraps logging_config
- output_json(data) / output_human(...) — formatters
- build_legacy_client / build_integration_client — construct from Settings
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from unifi_manager.clients.integration import IntegrationClient
from unifi_manager.clients.legacy import LegacyClient
from unifi_manager.logging_config import (
    register_secrets_from_settings,
    setup_logging,
)
from unifi_manager.settings import LoggingSettings, Settings


def load_settings(config_path: Path | None = None) -> Settings:
    """Загрузить Settings с опциональным указанием config.yaml пути.

    Args:
        config_path: явный путь к config.yaml (флаг --config).
                     None → стандартный поиск через _find_yaml().

    Side-effect: регистрирует все SecretStr из Settings в SecretsFilter
                 (защита от утечки в логах).
    """
    if config_path is not None:
        os.environ["UNIFI_CONFIG_PATH"] = str(config_path)

    settings = Settings()  # type: ignore[call-arg]
    register_secrets_from_settings(settings)
    return settings


def setup_logging_from_cli(
    settings: LoggingSettings,
    *,
    verbose: int = 0,
    quiet: int = 0,
) -> None:
    """Wrapper над logging_config.setup_logging — единая точка из CLI."""
    setup_logging(settings, verbose=verbose, quiet=quiet)


def output_json(data: Any) -> None:
    """Печать data как JSON в stdout (для cron, --json флаг)."""
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2, default=_json_default)
    sys.stdout.write("\n")


def _json_default(obj: Any) -> Any:
    """Default serializer для datetime, pydantic models, dataclasses."""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


def build_legacy_client(settings: Settings) -> LegacyClient:
    """LegacyClient (session + CSRF) из Settings.unifi."""
    return LegacyClient(settings.unifi)


def build_integration_client(settings: Settings) -> IntegrationClient:
    """IntegrationClient (X-API-KEY) из Settings.unifi.

    Raises:
        UnifiAuthError: если api_key или site_id_uuid отсутствуют.
    """
    return IntegrationClient(settings.unifi)
```

- [ ] **Step 1.4: Run, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_cli/test_common.py -v --no-cov
```
Expected: 8 PASS.

- [ ] **Step 1.5: Mypy + ruff**

```bash
.venv/Scripts/mypy src/unifi_manager/cli/_common.py
.venv/Scripts/ruff check src/unifi_manager/cli/_common.py tests/unit/test_cli/test_common.py
```
Expected: clean.

- [ ] **Step 1.6: Commit**

```bash
git add src/unifi_manager/cli/_common.py tests/unit/test_cli/test_common.py
git commit -m "phase4: cli/_common.py — shared CLI infrastructure"
```

---

## Task 2: cli/audit.py — 5 commands

**Files:**
- Create: `src/unifi_manager/cli/audit.py`
- Create: `tests/unit/test_cli/test_audit.py`
- Modify: `src/unifi_manager/cli/main.py` (remove `audit_critical`/`audit_full` stubs, register new audit_app)

**Goal:** Wire AuditService.{critical, status, full, light, trends} к Typer commands.

- [ ] **Step 2.1: Write failing tests**

`tests/unit/test_cli/test_audit.py`:

```python
"""Тесты для unifi_manager.cli.audit."""
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from unifi_manager.settings import Settings, UnifiAuthSettings


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(
        unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="t",
                                username=SecretStr("u"), password=SecretStr("p")),
    )


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    """Сбрасываем logging state между CLI тестами (как в test_logging)."""
    import logging
    from unifi_manager import logging_config
    logging_config._LOGGING_CONFIGURED = False
    logging.getLogger().handlers.clear()


@pytest.mark.fast
def test_audit_critical_no_issues_exits_0(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with patch("unifi_manager.cli.audit.load_settings") as mock_settings, \
         patch("unifi_manager.cli.audit.build_legacy_client") as mock_client, \
         patch("unifi_manager.cli.audit.AuditService") as mock_svc:
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.critical.return_value = []  # no issues
        result = runner.invoke(app, ["audit", "critical"])
    assert result.exit_code == 0


@pytest.mark.fast
def test_audit_critical_with_issues_exits_1(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.services.audit import AuditIssue

    runner = CliRunner()
    with patch("unifi_manager.cli.audit.load_settings") as mock_settings, \
         patch("unifi_manager.cli.audit.build_legacy_client") as mock_client, \
         patch("unifi_manager.cli.audit.AuditService") as mock_svc:
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.critical.return_value = [
            AuditIssue(issue_type="offline", device_mac="aa:bb",
                       device_name="Restoran", severity="critical"),
        ]
        result = runner.invoke(app, ["audit", "critical"])
    assert result.exit_code == 1
    assert "Restoran" in result.stdout or "aa:bb" in result.stdout


@pytest.mark.fast
def test_audit_critical_json_format(tmp_path: Path) -> None:
    """--json флаг → JSON output."""
    import json
    from unifi_manager.cli.main import app
    from unifi_manager.services.audit import AuditIssue

    runner = CliRunner()
    with patch("unifi_manager.cli.audit.load_settings") as mock_settings, \
         patch("unifi_manager.cli.audit.build_legacy_client"), \
         patch("unifi_manager.cli.audit.AuditService") as mock_svc:
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.critical.return_value = [
            AuditIssue(issue_type="offline", device_mac="aa:bb",
                       device_name="Restoran", severity="critical"),
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
    with patch("unifi_manager.cli.audit.load_settings") as mock_settings, \
         patch("unifi_manager.cli.audit.build_legacy_client"), \
         patch("unifi_manager.cli.audit.AuditService") as mock_svc:
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.status.return_value = StatusSummary(
            total=270, online=268, offline=2, by_type={"uap": 260, "usw": 10},
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

    with patch("unifi_manager.cli.audit.load_settings") as mock_settings, \
         patch("unifi_manager.cli.audit.build_legacy_client") as mock_legacy, \
         patch("unifi_manager.cli.audit.build_integration_client") as mock_integ, \
         patch("unifi_manager.cli.audit.AuditService") as mock_svc:
        mock_settings.return_value = settings
        mock_svc.return_value.full.return_value = FullAuditReport(devices=[])
        result = runner.invoke(app, ["audit", "full", "--api", "both"])

    assert result.exit_code == 0
    # AuditService должен быть вызван с обоими клиентами
    call_kwargs = mock_svc.call_args.kwargs
    assert "integration_client" in call_kwargs


@pytest.mark.fast
def test_audit_light_runs(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.services.audit import LightAuditReport

    runner = CliRunner()
    with patch("unifi_manager.cli.audit.load_settings") as mock_settings, \
         patch("unifi_manager.cli.audit.build_legacy_client"), \
         patch("unifi_manager.cli.audit.AuditService") as mock_svc:
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.light.return_value = LightAuditReport(
            duplicate_macs=[], locally_administered=[], clients_per_ap={},
        )
        result = runner.invoke(app, ["audit", "light"])

    assert result.exit_code == 0


@pytest.mark.fast
def test_audit_trends_default_days(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.services.audit import TrendsReport

    runner = CliRunner()
    with patch("unifi_manager.cli.audit.load_settings") as mock_settings, \
         patch("unifi_manager.cli.audit.build_legacy_client"), \
         patch("unifi_manager.cli.audit.AuditService") as mock_svc:
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.trends.return_value = TrendsReport(data_points=[])
        result = runner.invoke(app, ["audit", "trends", "--days", "14"])

    assert result.exit_code == 0
    # trends() должен быть вызван с days=14
    mock_svc.return_value.trends.assert_called_once_with(days=14)


@pytest.mark.fast
def test_audit_critical_telegram_dedup(tmp_path: Path) -> None:
    """--telegram → отправляет через TelegramNotifier + AlertHistory dedup."""
    from unifi_manager.cli.main import app
    from unifi_manager.services.audit import AuditIssue

    runner = CliRunner()
    with patch("unifi_manager.cli.audit.load_settings") as mock_settings, \
         patch("unifi_manager.cli.audit.build_legacy_client"), \
         patch("unifi_manager.cli.audit.AuditService") as mock_svc, \
         patch("unifi_manager.cli.audit.TelegramNotifier") as mock_notif, \
         patch("unifi_manager.cli.audit.AlertHistory") as mock_history:
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.critical.return_value = [
            AuditIssue(issue_type="offline", device_mac="aa:bb",
                       device_name="x", severity="critical"),
        ]
        mock_history.return_value.is_new_alert.return_value = True
        mock_notif.return_value.send_message.return_value = True

        result = runner.invoke(app, ["audit", "critical", "--telegram"])

    assert result.exit_code == 1
    mock_notif.return_value.send_message.assert_called()
```

- [ ] **Step 2.2: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_cli/test_audit.py -v --no-cov
```
Expected: ModuleNotFoundError или AttributeError (no audit_critical etc.).

- [ ] **Step 2.3: Implement `src/unifi_manager/cli/audit.py`**

```python
"""CLI commands для audit (critical, status, full, light, trends).

Реализация Phase 4 — заменяет stub-команды из Phase 0.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

from unifi_manager.cli._common import (
    build_integration_client,
    build_legacy_client,
    load_settings,
    output_json,
    setup_logging_from_cli,
)
from unifi_manager.integrations.telegram import TelegramNotifier
from unifi_manager.services.audit import AuditService
from unifi_manager.services.notify import AlertHistory


_logger = logging.getLogger(__name__)

audit_app = typer.Typer(help="Аудит и мониторинг сети", no_args_is_help=True)


@audit_app.command("critical", help="Быстрая проверка критических проблем")
def audit_critical(
    config: Annotated[Path | None, typer.Option("--config", help="Путь к config.yaml")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output для cron")] = False,
    telegram: Annotated[bool, typer.Option("--telegram", help="Отправить алерт в Telegram при наличии issues")] = False,
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
            typer.echo("✓ No critical issues found")
        else:
            typer.echo(f"⚠ {len(issues)} critical issue(s) found:")
            for issue in issues:
                typer.echo(f"  [{issue.severity.upper()}] {issue.issue_type}: "
                           f"{issue.device_name} ({issue.device_mac})")

    # Telegram уведомление с dedup
    if telegram and issues:
        history = AlertHistory(state_file=settings.paths.cache_dir / "alert_history.json")
        notifier = TelegramNotifier(
            settings=settings.telegram,
            rate_limit_state=settings.paths.cache_dir / "telegram_throttle.json",
        )
        for issue in issues:
            hash_key = f"{issue.issue_type}:{issue.device_mac}"
            if history.is_new_alert(hash_key=hash_key):
                msg = f"⚠ {issue.severity}: {issue.device_name} — {issue.issue_type}"
                if notifier.send_message(msg, hash_key=hash_key):
                    history.record_alert(hash_key=hash_key)
        history.save()

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
        output_json({"total": status.total, "online": status.online,
                     "offline": status.offline, "by_type": status.by_type})
    else:
        typer.echo(f"Total: {status.total}")
        typer.echo(f"Online: {status.online}")
        typer.echo(f"Offline: {status.offline}")
        typer.echo("By type:")
        for t, n in sorted(status.by_type.items()):
            typer.echo(f"  {t}: {n}")


@audit_app.command("full", help="Глубокий аудит (оба API)")
def audit_full(
    api: Annotated[str, typer.Option("--api", help="legacy | integration | both")] = "both",
    config: Annotated[Path | None, typer.Option("--config")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    legacy = build_legacy_client(settings)
    integration = None
    if api in ("integration", "both"):
        try:
            integration = build_integration_client(settings)
        except Exception as e:
            _logger.warning("Integration client unavailable: %s", e)
            if api == "integration":
                raise typer.Exit(code=2) from e

    svc = AuditService(legacy_client=legacy, settings=settings,
                       integration_client=integration)
    report = svc.full()

    if json_output:
        output_json({"devices": report.devices})
    else:
        typer.echo(f"Full audit: {len(report.devices)} devices")


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
        output_json({
            "duplicate_macs": [{"mac": d.mac, "hostnames": d.hostnames}
                                for d in report.duplicate_macs],
            "locally_administered": [{"mac": s.mac, "hostname": s.hostname,
                                        "ap_mac": s.ap_mac}
                                       for s in report.locally_administered],
            "clients_per_ap": report.clients_per_ap,
        })
    else:
        typer.echo(f"Duplicate MACs: {len(report.duplicate_macs)}")
        for d in report.duplicate_macs:
            typer.echo(f"  {d.mac}: {d.hostnames}")
        typer.echo(f"Locally-administered (potential spoof): "
                   f"{len(report.locally_administered)}")
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
            typer.echo(f"  {dp.get('file', '?')}: "
                       f"total={dp.get('total', '?')}, "
                       f"offline={dp.get('offline', '?')}")


def _issue_to_dict(issue: object) -> dict[str, object]:
    """Сериализация AuditIssue для --json."""
    return {
        "issue_type": getattr(issue, "issue_type", None),
        "device_mac": getattr(issue, "device_mac", None),
        "device_name": getattr(issue, "device_name", None),
        "severity": getattr(issue, "severity", None),
        "context": getattr(issue, "context", {}),
    }
```

- [ ] **Step 2.4: Update `src/unifi_manager/cli/main.py`**

Remove inline stubs for `audit_critical` and `audit_full`. Replace the existing `audit_app` definition with import from audit module.

Find в `main.py`:
```python
audit_app = typer.Typer(help="Аудит и мониторинг сети", no_args_is_help=True)
```

Заменить на:
```python
from unifi_manager.cli.audit import audit_app
```

И удалить stub commands:
```python
@audit_app.command("critical", help="[stub] Быстрая проверка критических проблем")
def audit_critical() -> None:
    _stub("audit critical")


@audit_app.command("full", help="[stub] Полный аудит")
def audit_full() -> None:
    _stub("audit full")
```

(Other stubs остаются для restart/config — заменим в их Task'ах.)

- [ ] **Step 2.5: Run tests, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_cli/test_audit.py -v --no-cov
```
Expected: 8 PASS.

```bash
.venv/Scripts/unifi-mgr audit --help
```
Expected: shows critical, status, full, light, trends (real commands, not stubs).

```bash
.venv/Scripts/unifi-mgr audit critical --help
```
Expected: shows --config, --json, --telegram flags.

- [ ] **Step 2.6: Mypy + ruff**

```bash
.venv/Scripts/mypy src/unifi_manager/cli/audit.py
.venv/Scripts/ruff check src/unifi_manager/cli/audit.py tests/unit/test_cli/test_audit.py
```
Expected: clean. Add per-file-ignore RUF001/RUF002 для audit.py если нужно.

- [ ] **Step 2.7: Commit**

```bash
git add src/unifi_manager/cli/audit.py src/unifi_manager/cli/main.py tests/unit/test_cli/test_audit.py
git commit -m "phase4: cli/audit.py — wire AuditService 5 commands"
```

---

## Task 3: cli/restart.py — 3 commands

**Files:**
- Create: `src/unifi_manager/cli/restart.py`
- Create: `tests/unit/test_cli/test_restart.py`
- Modify: `src/unifi_manager/cli/main.py` (replace restart_app stub)

**Goal:** Wire RestartService.{auto, profile, device} к Typer с правильными dry-run defaults (D9).

- [ ] **Step 3.1: Write failing tests**

`tests/unit/test_cli/test_restart.py`:

```python
"""Тесты для unifi_manager.cli.restart."""
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from unifi_manager.settings import Settings, UnifiAuthSettings


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(
        unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="t",
                                username=SecretStr("u"), password=SecretStr("p")),
    )


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    import logging
    from unifi_manager import logging_config
    logging_config._LOGGING_CONFIGURED = False
    logging.getLogger().handlers.clear()


@pytest.mark.fast
def test_restart_auto_default_is_real_execution(tmp_path: Path) -> None:
    """restart auto — REAL execution по умолчанию (cron command)."""
    from unifi_manager.cli.main import app
    from unifi_manager.services.restart import RestartReport

    runner = CliRunner()
    with patch("unifi_manager.cli.restart.load_settings") as mock_settings, \
         patch("unifi_manager.cli.restart.build_legacy_client"), \
         patch("unifi_manager.cli.restart.RestartService") as mock_svc:
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.auto.return_value = RestartReport(
            status="completed", dry_run=False, actions=[]
        )
        result = runner.invoke(app, ["restart", "auto"])

    assert result.exit_code == 0
    mock_svc.return_value.auto.assert_called_once_with(dry_run=False)


@pytest.mark.fast
def test_restart_auto_dry_run_flag(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.services.restart import RestartReport

    runner = CliRunner()
    with patch("unifi_manager.cli.restart.load_settings") as mock_settings, \
         patch("unifi_manager.cli.restart.build_legacy_client"), \
         patch("unifi_manager.cli.restart.RestartService") as mock_svc:
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.auto.return_value = RestartReport(
            status="completed", dry_run=True, actions=[]
        )
        result = runner.invoke(app, ["restart", "auto", "--dry-run"])

    assert result.exit_code == 0
    mock_svc.return_value.auto.assert_called_once_with(dry_run=True)


@pytest.mark.fast
def test_restart_profile_default_is_dry_run(tmp_path: Path) -> None:
    """restart profile NAME — DRY-RUN default (защита от случайного запуска)."""
    from unifi_manager.cli.main import app
    from unifi_manager.services.restart import RestartReport

    runner = CliRunner()
    with patch("unifi_manager.cli.restart.load_settings") as mock_settings, \
         patch("unifi_manager.cli.restart.build_legacy_client"), \
         patch("unifi_manager.cli.restart.RestartService") as mock_svc:
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.profile.return_value = RestartReport(
            status="completed", dry_run=True, actions=[]
        )
        result = runner.invoke(app, ["restart", "profile", "restaurant"])

    assert result.exit_code == 0
    mock_svc.return_value.profile.assert_called_once_with("restaurant", apply=False)
    assert "DRY-RUN" in result.stdout.upper() or "dry" in result.stdout.lower()


@pytest.mark.fast
def test_restart_profile_apply_flag(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.services.restart import RestartReport

    runner = CliRunner()
    with patch("unifi_manager.cli.restart.load_settings") as mock_settings, \
         patch("unifi_manager.cli.restart.build_legacy_client"), \
         patch("unifi_manager.cli.restart.RestartService") as mock_svc:
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.profile.return_value = RestartReport(
            status="completed", dry_run=False, actions=[]
        )
        result = runner.invoke(app, ["restart", "profile", "restaurant", "--apply"])

    assert result.exit_code == 0
    mock_svc.return_value.profile.assert_called_once_with("restaurant", apply=True)


@pytest.mark.fast
def test_restart_device_default_dry_run(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.services.restart import RestartReport

    runner = CliRunner()
    with patch("unifi_manager.cli.restart.load_settings") as mock_settings, \
         patch("unifi_manager.cli.restart.build_legacy_client"), \
         patch("unifi_manager.cli.restart.RestartService") as mock_svc:
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.device.return_value = RestartReport(
            status="completed", dry_run=True, actions=[]
        )
        result = runner.invoke(app, ["restart", "device", "--mac", "aa:bb:cc:dd:ee:01"])

    assert result.exit_code == 0
    mock_svc.return_value.device.assert_called_once_with(
        mac="aa:bb:cc:dd:ee:01", method="restart", apply=False,
    )


@pytest.mark.fast
def test_restart_device_apply_with_method(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.services.restart import RestartReport

    runner = CliRunner()
    with patch("unifi_manager.cli.restart.load_settings") as mock_settings, \
         patch("unifi_manager.cli.restart.build_legacy_client"), \
         patch("unifi_manager.cli.restart.RestartService") as mock_svc:
        mock_settings.return_value = _test_settings(tmp_path)
        mock_svc.return_value.device.return_value = RestartReport(
            status="completed", dry_run=False, actions=[]
        )
        result = runner.invoke(app, [
            "restart", "device", "--mac", "aa:bb:cc:dd:ee:01",
            "--method", "poe-cycle", "--apply",
        ])

    assert result.exit_code == 0
    mock_svc.return_value.device.assert_called_once_with(
        mac="aa:bb:cc:dd:ee:01", method="poe_cycle", apply=True,
    )
```

- [ ] **Step 3.2: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_cli/test_restart.py -v --no-cov
```
Expected: ModuleNotFoundError или AttributeError.

- [ ] **Step 3.3: Implement `src/unifi_manager/cli/restart.py`**

```python
"""CLI commands для restart (auto, profile, device).

Дефолты (D9):
- restart auto — REAL execution (cron command, защиты внутри service)
- restart profile NAME — DRY-RUN default, --apply для real
- restart device --mac — DRY-RUN default, --apply для real
"""
from __future__ import annotations

import logging
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

restart_app = typer.Typer(help="Рестарт устройств", no_args_is_help=True)


@restart_app.command("auto", help="Авто-рестарт проблемных AP (для cron)")
def restart_auto(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Только показать что будет сделано")] = False,
    max_n: Annotated[int | None, typer.Option("--max", help="Override max_restarts_per_run")] = None,
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
    apply: Annotated[bool, typer.Option("--apply", help="РЕАЛЬНЫЙ запуск (default — dry-run)")] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    client = build_legacy_client(settings)
    svc = RestartService(legacy_client=client, settings=settings)
    report = svc.profile(name, apply=apply)

    _print_report(report, json_output=json_output)


@restart_app.command("device", help="Точечный restart одного device (DRY-RUN default)")
def restart_device(
    mac: Annotated[str, typer.Option("--mac", help="MAC адрес устройства")],
    method: Annotated[str, typer.Option("--method", help="restart | poe-cycle")] = "restart",
    apply: Annotated[bool, typer.Option("--apply", help="РЕАЛЬНЫЙ запуск (default — dry-run)")] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    # CLI принимает "poe-cycle" (с дефисом), service ожидает "poe_cycle"
    method_normalized: Literal["restart", "poe_cycle"] = (
        "poe_cycle" if method == "poe-cycle" else "restart"
    )

    client = build_legacy_client(settings)
    svc = RestartService(legacy_client=client, settings=settings)
    report = svc.device(mac=mac, method=method_normalized, apply=apply)

    _print_report(report, json_output=json_output)


def _print_report(report: RestartReport, *, json_output: bool) -> None:
    if json_output:
        output_json({
            "status": report.status,
            "dry_run": report.dry_run,
            "actions": [{"mac": a.mac, "name": a.name, "action": a.action,
                          "reason": a.reason, "status": a.status}
                         for a in report.actions],
        })
        return

    mode = "DRY-RUN" if report.dry_run else "APPLY"
    typer.echo(f"[{mode}] Status: {report.status}, Actions: {len(report.actions)}")
    for action in report.actions:
        typer.echo(f"  {action.action} {action.mac} ({action.name}): {action.status}")
        typer.echo(f"    Reason: {action.reason}")
```

- [ ] **Step 3.4: Update `cli/main.py`**

Find:
```python
restart_app = typer.Typer(help="Рестарт устройств", no_args_is_help=True)
```
Replace:
```python
from unifi_manager.cli.restart import restart_app
```

Remove stub:
```python
@restart_app.command("auto", help="[stub] Авто-рестарт проблемных AP")
def restart_auto() -> None:
    _stub("restart auto")
```

- [ ] **Step 3.5: Run tests, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_cli/test_restart.py -v --no-cov
```
Expected: 6 PASS.

```bash
.venv/Scripts/unifi-mgr restart --help
```
Expected: shows auto, profile, device.

- [ ] **Step 3.6: Mypy + ruff + commit**

```bash
.venv/Scripts/mypy src/unifi_manager/cli/restart.py
.venv/Scripts/ruff check src/unifi_manager/cli/restart.py tests/unit/test_cli/test_restart.py
git add src/unifi_manager/cli/restart.py src/unifi_manager/cli/main.py tests/unit/test_cli/test_restart.py
git commit -m "phase4: cli/restart.py — wire RestartService 3 commands with D9 dry-run defaults"
```

---

## Task 4: cli/export.py — 2 commands

**Files:**
- Create: `src/unifi_manager/cli/export.py`
- Create: `tests/unit/test_cli/test_export.py`
- Modify: `cli/main.py` (replace export_app)

- [ ] **Step 4.1: Write failing tests**

`tests/unit/test_cli/test_export.py`:

```python
"""Тесты для unifi_manager.cli.export."""
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from unifi_manager.settings import Settings, UnifiAuthSettings


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(
        unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="t",
                                username=SecretStr("u"), password=SecretStr("p")),
    )


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    import logging
    from unifi_manager import logging_config
    logging_config._LOGGING_CONFIGURED = False
    logging.getLogger().handlers.clear()


@pytest.mark.fast
def test_export_clients_csv_to_stdout(tmp_path: Path) -> None:
    """Без --out — пишет в stdout."""
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with patch("unifi_manager.cli.export.load_settings") as mock_settings, \
         patch("unifi_manager.cli.export.build_legacy_client") as mock_client, \
         patch("unifi_manager.cli.export.ExportService") as mock_svc:
        mock_settings.return_value = _test_settings(tmp_path)
        # ExportService.export_clients принимает output stream — пишем туда mock_data
        def fake_export(output, fmt):
            output.write("mac,hostname\naa:bb,laptop\n")
        mock_svc.return_value.export_clients.side_effect = fake_export

        result = runner.invoke(app, ["export", "clients", "--format", "csv"])

    assert result.exit_code == 0
    assert "mac,hostname" in result.stdout


@pytest.mark.fast
def test_export_clients_csv_to_file(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    out_path = tmp_path / "clients.csv"
    runner = CliRunner()
    with patch("unifi_manager.cli.export.load_settings") as mock_settings, \
         patch("unifi_manager.cli.export.build_legacy_client"), \
         patch("unifi_manager.cli.export.ExportService") as mock_svc:
        mock_settings.return_value = _test_settings(tmp_path)
        def fake_export(output, fmt):
            output.write("mac\naa:bb\n")
        mock_svc.return_value.export_clients.side_effect = fake_export

        result = runner.invoke(app, ["export", "clients", "--format", "csv",
                                       "--out", str(out_path)])

    assert result.exit_code == 0
    assert out_path.exists()
    assert "mac" in out_path.read_text(encoding="utf-8")


@pytest.mark.fast
def test_export_devices_json(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with patch("unifi_manager.cli.export.load_settings") as mock_settings, \
         patch("unifi_manager.cli.export.build_legacy_client"), \
         patch("unifi_manager.cli.export.ExportService") as mock_svc:
        mock_settings.return_value = _test_settings(tmp_path)
        def fake_export(output, fmt):
            output.write('[{"mac": "aa:bb"}]')
        mock_svc.return_value.export_devices.side_effect = fake_export

        result = runner.invoke(app, ["export", "devices", "--format", "json"])

    assert result.exit_code == 0
    assert '"mac"' in result.stdout


@pytest.mark.fast
def test_export_invalid_format_exits_nonzero(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with patch("unifi_manager.cli.export.load_settings") as mock_settings, \
         patch("unifi_manager.cli.export.build_legacy_client"):
        mock_settings.return_value = _test_settings(tmp_path)

        result = runner.invoke(app, ["export", "clients", "--format", "xml"])

    assert result.exit_code != 0
```

- [ ] **Step 4.2: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_cli/test_export.py -v --no-cov
```

- [ ] **Step 4.3: Implement `src/unifi_manager/cli/export.py`**

```python
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
    out: Annotated[Path | None, typer.Option("--out", help="Файл для записи (default — stdout)")] = None,
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
        svc.export_devices(output=sys.stdout, fmt=fmt_lit)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            svc.export_devices(output=f, fmt=fmt_lit)
        typer.echo(f"Wrote {out}", err=True)
```

- [ ] **Step 4.4: Update `cli/main.py`**

Find:
```python
export_app = typer.Typer(help="Экспорт данных", no_args_is_help=True)
```
Replace:
```python
from unifi_manager.cli.export import export_app
```

- [ ] **Step 4.5: Run tests, verify pass + smoke**

```bash
.venv/Scripts/pytest tests/unit/test_cli/test_export.py -v --no-cov
.venv/Scripts/unifi-mgr export --help
```

- [ ] **Step 4.6: Commit**

```bash
.venv/Scripts/mypy src/unifi_manager/cli/export.py
.venv/Scripts/ruff check src/unifi_manager/cli/export.py tests/unit/test_cli/test_export.py
git add src/unifi_manager/cli/export.py src/unifi_manager/cli/main.py tests/unit/test_cli/test_export.py
git commit -m "phase4: cli/export.py — wire ExportService clients+devices"
```

---

## Task 5: cli/{notify,zabbix,config,login,legacy}.py — utility commands

Combined task потому что каждая — 1-2 commands, small footprint. Follow same pattern: test → impl → register in main → commit.

**Files:**
- Create: `src/unifi_manager/cli/notify.py`
- Create: `src/unifi_manager/cli/zabbix.py`
- Create: `src/unifi_manager/cli/config.py`
- Create: `src/unifi_manager/cli/login.py`
- Create: `src/unifi_manager/cli/legacy.py`
- Create: `tests/unit/test_cli/test_notify.py`
- Create: `tests/unit/test_cli/test_zabbix.py`
- Create: `tests/unit/test_cli/test_config.py`
- Create: `tests/unit/test_cli/test_login.py`
- Create: `tests/unit/test_cli/test_legacy.py`
- Modify: `cli/main.py` (register all 5 + remove last `config validate` stub)

### Task 5a: notify

`src/unifi_manager/cli/notify.py`:
```python
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

    notifier = TelegramNotifier(
        settings=settings.telegram,
        rate_limit_state=settings.paths.cache_dir / "telegram_throttle.json",
    )
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
    notifier = TelegramNotifier(
        settings=settings.telegram,
        rate_limit_state=settings.paths.cache_dir / "telegram_throttle.json",
    )
    ok = notifier.send_message(f"{icon} {text}", hash_key=f"cli-send:{level}:{text[:32]}")
    raise typer.Exit(code=0 if ok else 1)
```

`tests/unit/test_cli/test_notify.py`:
```python
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from unifi_manager.settings import (
    Settings, TelegramSettings, UnifiAuthSettings,
)


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    import logging
    from unifi_manager import logging_config
    logging_config._LOGGING_CONFIGURED = False
    logging.getLogger().handlers.clear()


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(
        unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="t"),
        telegram=TelegramSettings(bot_token=SecretStr("t"), chat_id="1",
                                    enabled=True),
    )


@pytest.mark.fast
def test_notify_test_calls_send(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with patch("unifi_manager.cli.notify.load_settings") as mock_settings, \
         patch("unifi_manager.cli.notify.TelegramNotifier") as mock_notif:
        mock_settings.return_value = _test_settings(tmp_path)
        mock_notif.return_value.send_message.return_value = True
        result = runner.invoke(app, ["notify", "test"])

    assert result.exit_code == 0
    mock_notif.return_value.send_message.assert_called_once()


@pytest.mark.fast
def test_notify_test_failure_exits_1(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with patch("unifi_manager.cli.notify.load_settings") as mock_settings, \
         patch("unifi_manager.cli.notify.TelegramNotifier") as mock_notif:
        mock_settings.return_value = _test_settings(tmp_path)
        mock_notif.return_value.send_message.return_value = False
        result = runner.invoke(app, ["notify", "test"])

    assert result.exit_code == 1


@pytest.mark.fast
def test_notify_send_with_level(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with patch("unifi_manager.cli.notify.load_settings") as mock_settings, \
         patch("unifi_manager.cli.notify.TelegramNotifier") as mock_notif:
        mock_settings.return_value = _test_settings(tmp_path)
        mock_notif.return_value.send_message.return_value = True
        result = runner.invoke(app, ["notify", "send", "Test alert", "--level", "warn"])

    assert result.exit_code == 0
    call_text = mock_notif.return_value.send_message.call_args.args[0]
    assert "Test alert" in call_text
```

### Task 5b: zabbix

`src/unifi_manager/cli/zabbix.py`:
```python
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
from unifi_manager.domain.device import AccessPoint, Switch
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

    # Parse via domain models
    devices = []
    for raw in raw_devices:
        try:
            if raw.get("type") == "uap":
                devices.append(AccessPoint.model_validate(raw))
            elif raw.get("type") == "usw":
                devices.append(Switch.model_validate(raw))
        except Exception:
            continue

    typer.echo(format_lld_json(devices))
```

`tests/unit/test_cli/test_zabbix.py`:
```python
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from unifi_manager.settings import Settings, UnifiAuthSettings


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    import logging
    from unifi_manager import logging_config
    logging_config._LOGGING_CONFIGURED = False
    logging.getLogger().handlers.clear()


@pytest.mark.fast
def test_zabbix_stats_outputs_lld_json(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with patch("unifi_manager.cli.zabbix.load_settings") as mock_settings, \
         patch("unifi_manager.cli.zabbix.build_legacy_client") as mock_client_fn:
        mock_settings.return_value = Settings(
            unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="t",
                                    username=SecretStr("u"), password=SecretStr("p")),
        )
        mock_client = mock_client_fn.return_value
        mock_client.list_devices_raw.return_value = [
            {"mac": "aa:01", "name": "AP1", "model": "U7IW", "sysid": 58759,
             "type": "uap", "state": 1},
        ]
        result = runner.invoke(app, ["zabbix", "stats"])

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "data" in parsed
    assert len(parsed["data"]) == 1
    assert parsed["data"][0]["{#MODEL}"] == "UAP-AC-IW"  # via SYSID_MAP
```

### Task 5c: config

`src/unifi_manager/cli/config.py`:
```python
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
    typer.echo(f"✓ Config valid (host={settings.unifi.host}, site={settings.unifi.site})")


@config_app.command("show", help="Показать рассчитанный config (--secrets для unmask)")
def config_show(
    secrets: Annotated[bool, typer.Option("--secrets", help="Показать секреты в открытую (требует TTY)")] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    import sys

    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    # Защита от случайного pipe — секреты только в TTY
    if secrets and not sys.stdout.isatty():
        typer.echo("Error: --secrets refuses to print to non-TTY (use TTY interactive shell)",
                   err=True)
        raise typer.Exit(code=2)

    data = settings.model_dump(mode="json")
    if secrets:
        # Manually unmask SecretStr
        data = _unmask_secrets(data, settings)
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _unmask_secrets(data: dict, settings) -> dict:
    """Заменяет '**********' на actual SecretStr values."""
    # pydantic model_dump masks SecretStr as "**********".
    # Walk settings recursively and replace masked values with actual.
    def walk(model, prefix=""):
        out = {}
        for field_name, value in model.__dict__.items():
            if isinstance(value, SecretStr):
                out[field_name] = value.get_secret_value()
            elif hasattr(value, "__dict__"):
                out[field_name] = walk(value)
            else:
                out[field_name] = value
        return out
    return walk(settings)
```

`tests/unit/test_cli/test_config.py`:
```python
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    import logging
    from unifi_manager import logging_config
    logging_config._LOGGING_CONFIGURED = False
    logging.getLogger().handlers.clear()


@pytest.mark.fast
def test_config_validate_valid(tmp_path: Path,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "unifi:\n  host: 1.2.3.4\n  port: 11443\n  site: t\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code == 0
    assert "valid" in result.stdout.lower()


@pytest.mark.fast
def test_config_validate_invalid_exits_1(tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "unifi:\n  # missing required host\n  port: 11443\n  site: t\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code == 1


@pytest.mark.fast
def test_config_show_without_secrets(tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "unifi:\n  host: 1.2.3.4\n  port: 11443\n  site: t\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("UNIFI_UNIFI__PASSWORD", "super-secret")

    runner = CliRunner()
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "super-secret" not in result.stdout
```

### Task 5d: login

`src/unifi_manager/cli/login.py`:
```python
"""CLI: login test — проверка credentials против UniFi."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from unifi_manager.cli._common import (
    build_integration_client,
    build_legacy_client,
    load_settings,
    setup_logging_from_cli,
)
from unifi_manager.clients.exceptions import UnifiError


login_app = typer.Typer(help="Проверка аутентификации", no_args_is_help=True)


@login_app.command("test", help="Проверить login против UniFi (Legacy и/или Integration API)")
def login_test(
    api: Annotated[str, typer.Option("--api", help="legacy | integration | both")] = "both",
    config: Annotated[Path | None, typer.Option("--config")] = None,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 0,
    quiet: Annotated[int, typer.Option("-q", "--quiet", count=True)] = 0,
) -> None:
    settings = load_settings(config_path=config)
    setup_logging_from_cli(settings.logging, verbose=verbose, quiet=quiet)

    failures = []

    if api in ("legacy", "both"):
        try:
            client = build_legacy_client(settings)
            client.login()
            typer.echo("✓ Legacy API login OK")
        except UnifiError as e:
            failures.append(f"Legacy: {e}")
            typer.echo(f"✗ Legacy API login failed: {e}", err=True)

    if api in ("integration", "both"):
        try:
            client = build_integration_client(settings)
            # Integration API не имеет explicit login — пробуем list_devices_raw
            client.list_devices_raw()
            typer.echo("✓ Integration API access OK")
        except UnifiError as e:
            failures.append(f"Integration: {e}")
            typer.echo(f"✗ Integration API failed: {e}", err=True)

    if failures:
        raise typer.Exit(code=1)
```

`tests/unit/test_cli/test_login.py`:
```python
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from unifi_manager.settings import Settings, UnifiAuthSettings


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    import logging
    from unifi_manager import logging_config
    logging_config._LOGGING_CONFIGURED = False
    logging.getLogger().handlers.clear()


@pytest.mark.fast
def test_login_test_legacy_success(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with patch("unifi_manager.cli.login.load_settings") as mock_settings, \
         patch("unifi_manager.cli.login.build_legacy_client") as mock_client:
        mock_settings.return_value = Settings(
            unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="t",
                                    username=SecretStr("u"), password=SecretStr("p")),
        )
        mock_client.return_value.login.return_value = True

        result = runner.invoke(app, ["login", "test", "--api", "legacy"])

    assert result.exit_code == 0
    assert "OK" in result.stdout


@pytest.mark.fast
def test_login_test_failure_exits_1(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app
    from unifi_manager.clients.exceptions import UnifiAuthError

    runner = CliRunner()
    with patch("unifi_manager.cli.login.load_settings") as mock_settings, \
         patch("unifi_manager.cli.login.build_legacy_client") as mock_client:
        mock_settings.return_value = Settings(
            unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="t",
                                    username=SecretStr("u"), password=SecretStr("p")),
        )
        mock_client.return_value.login.side_effect = UnifiAuthError("bad password")

        result = runner.invoke(app, ["login", "test", "--api", "legacy"])

    assert result.exit_code == 1
```

### Task 5e: legacy

`src/unifi_manager/cli/legacy.py`:
```python
"""CLI: legacy run <script_name> — deprecated wrapper для старых скриптов."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer


legacy_app = typer.Typer(help="Wrapper для старых скриптов (deprecated)",
                          no_args_is_help=True)


# Дата удаления _legacy/ — после Phase 6
LEGACY_REMOVAL_DATE = "2026-06-13"


def _legacy_dir() -> Path:
    """Путь к _legacy/ относительно current working directory или repo root."""
    # Сначала try cwd/_legacy
    cwd_legacy = Path.cwd() / "_legacy"
    if cwd_legacy.is_dir():
        return cwd_legacy
    # Fallback — пакет installed, _legacy не на disk → fail gracefully
    return Path("_legacy")


@legacy_app.command("run", help="Запустить старый скрипт из _legacy/ (с DeprecationWarning)")
def legacy_run(
    script_name: Annotated[str, typer.Argument(help="Имя файла из _legacy/ (e.g. restart_restaurant_v2.py)")],
    no_confirm: Annotated[bool, typer.Option("-y", "--no-confirm", help="Пропустить интерактивное подтверждение")] = False,
    list_scripts: Annotated[bool, typer.Option("--list", help="Показать доступные legacy скрипты вместо запуска")] = False,
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

    script_path = legacy_dir / script_name
    if not script_path.is_file():
        typer.echo(f"Script not found: {script_path}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"⚠  LEGACY MODE — running {script_path}", err=True)
    typer.echo(f"⚠  This script will be REMOVED on {LEGACY_REMOVAL_DATE}. "
               f"Use new `unifi-mgr ...` commands instead.", err=True)

    if not no_confirm:
        confirmed = typer.confirm("Continue?", default=False)
        if not confirmed:
            typer.echo("Aborted")
            raise typer.Exit(code=1)

    # Запуск через subprocess (legacy скрипты используют свой config.json + own deps)
    result = subprocess.run([sys.executable, str(script_path)], check=False)
    raise typer.Exit(code=result.returncode)
```

`tests/unit/test_cli/test_legacy.py`:
```python
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    import logging
    from unifi_manager import logging_config
    logging_config._LOGGING_CONFIGURED = False
    logging.getLogger().handlers.clear()


@pytest.mark.fast
def test_legacy_run_list_scripts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / "_legacy"
    legacy.mkdir()
    (legacy / "old_script.py").write_text("print('hi')", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["legacy", "run", "old_script.py", "--list"])

    assert result.exit_code == 0
    assert "old_script.py" in result.stdout


@pytest.mark.fast
def test_legacy_run_missing_script_exits_1(tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    (tmp_path / "_legacy").mkdir()

    runner = CliRunner()
    result = runner.invoke(app, ["legacy", "run", "nonexistent.py", "-y"])

    assert result.exit_code == 1


@pytest.mark.fast
def test_legacy_run_with_no_confirm(tmp_path: Path,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """С -y флагом — пропускает confirmation, запускает subprocess."""
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / "_legacy"
    legacy.mkdir()
    script = legacy / "hello.py"
    script.write_text("import sys; sys.exit(0)", encoding="utf-8")

    runner = CliRunner()
    with patch("unifi_manager.cli.legacy.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        result = runner.invoke(app, ["legacy", "run", "hello.py", "-y"])

    assert result.exit_code == 0
    mock_run.assert_called_once()
```

### Task 5 Steps

- [ ] **Step 5.1: Write all 5 failing tests + 5 impl files в одном TDD цикле**

(See above blocks для каждого файла.)

- [ ] **Step 5.2: Run all new tests**

```bash
.venv/Scripts/pytest tests/unit/test_cli/test_notify.py tests/unit/test_cli/test_zabbix.py tests/unit/test_cli/test_config.py tests/unit/test_cli/test_login.py tests/unit/test_cli/test_legacy.py -v --no-cov
```
Expected: ~14 tests PASS (3+1+3+2+3).

- [ ] **Step 5.3: Update `cli/main.py` — register все 5 sub-apps**

Find и replace:
```python
notify_app = typer.Typer(help="Уведомления (Telegram)", no_args_is_help=True)
zabbix_app = typer.Typer(help="Интеграция с Zabbix", no_args_is_help=True)
config_app = typer.Typer(help="Управление конфигурацией", no_args_is_help=True)
login_app = typer.Typer(help="Проверка аутентификации", no_args_is_help=True)
legacy_app = typer.Typer(help="Wrapper для старых скриптов (deprecated)", no_args_is_help=True)
```

Replace with imports:
```python
from unifi_manager.cli.notify import notify_app
from unifi_manager.cli.zabbix import zabbix_app
from unifi_manager.cli.config import config_app
from unifi_manager.cli.login import login_app
from unifi_manager.cli.legacy import legacy_app
```

Remove stub:
```python
@config_app.command("validate", help="[stub] Валидация config.yaml")
def config_validate() -> None:
    _stub("config validate")
```

`_stub()` helper и `diag_app` остаются (diag stubs — Phase 6).

- [ ] **Step 5.4: Smoke + mypy + ruff + commit**

```bash
.venv/Scripts/unifi-mgr --help
.venv/Scripts/unifi-mgr notify --help
.venv/Scripts/unifi-mgr config validate --help
```
Expected: все show real commands.

```bash
.venv/Scripts/mypy src/unifi_manager/cli/
.venv/Scripts/ruff check src/unifi_manager/cli/ tests/unit/test_cli/
git add src/unifi_manager/cli/ tests/unit/test_cli/
git commit -m "phase4: cli/{notify,zabbix,config,login,legacy}.py — utility commands wired"
```

---

## Task 6: dashboard.sh rewrite

**Files:**
- Modify: `scripts/dashboard.sh` (если экзистирует) OR Create в worktree если нет

**Goal:** Переписать `_legacy/dashboard.sh` (whiptail TUI) под новый CLI.

- [ ] **Step 6.1: Locate existing dashboard.sh**

```bash
ls _legacy/dashboard.sh
ls scripts/dashboard.sh 2>/dev/null || echo "Not in scripts yet"
```

- [ ] **Step 6.2: Create `scripts/dashboard.sh`**

```bash
#!/bin/bash
# UniFi Management Dashboard — new CLI version
# Заменяет _legacy/dashboard.sh

UNIFI_MGR="${UNIFI_MGR:-/opt/unifi-mgr/bin/unifi-mgr}"
LOG_DIR="${LOG_DIR:-/var/log/unifi-mgr}"

function check_status() {
    if [ -x "$UNIFI_MGR" ]; then
        VERSION=$("$UNIFI_MGR" --version 2>/dev/null | awk '{print $2}')
        echo "unifi-mgr $VERSION | logs: $LOG_DIR"
    else
        echo "unifi-mgr NOT FOUND at $UNIFI_MGR — set UNIFI_MGR env var"
    fi
}

while true; do
    STATUS=$(check_status)
    CHOICE=$(whiptail --title "📡 UniFi Network Dashboard" \
        --backtitle "$STATUS" \
        --menu "\nВыберите действие:" 20 70 12 \
        "1" "🔍 Быстрая проверка критических проблем (audit critical)" \
        "2" "📋 Полный аудит (audit full)" \
        "3" "📈 Анализ трендов (audit trends)" \
        "4" "🛡️ MAC analysis (audit light)" \
        "5" "🔄 Авто-рестарт (restart auto --dry-run)" \
        "6" "🔄 Профиль рестарта restaurant (restart profile restaurant --dry-run)" \
        "7" "📜 Логи (less /var/log/unifi-mgr/unifi-mgr.log)" \
        "8" "💾 Экспорт клиентов в CSV" \
        "9" "⚙️  Настройки (config show)" \
        "10" "✅ Валидация config" \
        "0" "❌ Выход" 3>&1 1>&2 2>&3)

    exitstatus=$?
    if [ $exitstatus != 0 ]; then
        clear
        echo "Выход..."
        break
    fi

    clear
    case $CHOICE in
        1) "$UNIFI_MGR" audit critical; read -p "Enter to continue..." ;;
        2) "$UNIFI_MGR" audit full; read -p "Enter to continue..." ;;
        3) "$UNIFI_MGR" audit trends; read -p "Enter to continue..." ;;
        4) "$UNIFI_MGR" audit light; read -p "Enter to continue..." ;;
        5) "$UNIFI_MGR" restart auto --dry-run; read -p "Enter to continue..." ;;
        6) "$UNIFI_MGR" restart profile restaurant; read -p "Enter to continue..." ;;
        7)
            if [ -f "$LOG_DIR/unifi-mgr.log" ]; then
                less "$LOG_DIR/unifi-mgr.log"
            else
                echo "Лог не найден: $LOG_DIR/unifi-mgr.log"
                read -p "Enter to continue..."
            fi
            ;;
        8) "$UNIFI_MGR" export clients --format csv --out /tmp/unifi-clients.csv && \
           echo "Сохранено в /tmp/unifi-clients.csv"; read -p "Enter to continue..." ;;
        9) "$UNIFI_MGR" config show; read -p "Enter to continue..." ;;
        10) "$UNIFI_MGR" config validate; read -p "Enter to continue..." ;;
        0) break ;;
    esac
done

clear
echo "Сеанс завершён."
```

- [ ] **Step 6.3: chmod +x и проверка**

```bash
chmod +x scripts/dashboard.sh
# Сам не запускаем (требует whiptail + TTY) — просто syntax check
bash -n scripts/dashboard.sh
```
Expected: no syntax errors.

- [ ] **Step 6.4: Commit**

```bash
git add scripts/dashboard.sh
git commit -m "phase4: scripts/dashboard.sh — rewrite using new unifi-mgr CLI"
```

---

## Task 7: CI + final acceptance + phase-4-complete tag

- [ ] **Step 7.1: Full suite + coverage + mypy**

```bash
.venv/Scripts/pre-commit run --all-files
.venv/Scripts/pytest --cov=unifi_manager --cov-report=term-missing --cov-fail-under=90
.venv/Scripts/mypy --strict \
  src/unifi_manager/settings.py \
  src/unifi_manager/logging_config.py \
  src/unifi_manager/clients \
  src/unifi_manager/domain \
  src/unifi_manager/utils \
  src/unifi_manager/services \
  src/unifi_manager/integrations
.venv/Scripts/mypy src/unifi_manager/cli
```
Expected: 270+ tests, coverage 90%+, mypy clean.

- [ ] **Step 7.2: Fresh venv acceptance**

```bash
rm -rf .venv-acceptance
py -3.12 -m venv .venv-acceptance
.venv-acceptance/Scripts/pip install -e ".[dev]"

.venv-acceptance/Scripts/pytest --cov-fail-under=90 -v

# CLI smoke — все группы должны иметь real commands (не stubs)
.venv-acceptance/Scripts/unifi-mgr --version
.venv-acceptance/Scripts/unifi-mgr --help
.venv-acceptance/Scripts/unifi-mgr audit --help
.venv-acceptance/Scripts/unifi-mgr restart --help
.venv-acceptance/Scripts/unifi-mgr export --help
.venv-acceptance/Scripts/unifi-mgr notify --help
.venv-acceptance/Scripts/unifi-mgr zabbix --help
.venv-acceptance/Scripts/unifi-mgr config --help
.venv-acceptance/Scripts/unifi-mgr login --help
.venv-acceptance/Scripts/unifi-mgr legacy --help
```
Expected: каждый --help показывает real commands.

`.venv-acceptance/Scripts/unifi-mgr diag --help` — должно показывать stubs (Phase 6).

```bash
rm -rf .venv-acceptance
```

- [ ] **Step 7.3: Tag**

```bash
git tag -d phase-4-complete 2>/dev/null || true
git tag -a phase-4-complete -m "Phase 4 (CLI complete) — all services wired to Typer commands, dashboard.sh rewritten"
git describe --tags
```

---

## Definition of Done — Phase 4

| Check | Expected |
|---|---|
| All tests pass | 270+ tests (224 Phase 3 + ~46 CLI) |
| Coverage ≥ 90% | PASS |
| Mypy strict (core) | Success — 24+ source files |
| Mypy (cli) | Success (non-strict, but no errors) |
| Ruff clean | All checks passed |
| Pre-commit green | all PASS |
| `unifi-mgr audit --help` | shows critical/status/full/light/trends (not stubs) |
| `unifi-mgr restart --help` | shows auto/profile/device (not stubs) |
| `unifi-mgr restart profile restaurant` | DRY-RUN default per D9 |
| `unifi-mgr restart auto` | REAL execution default per D9 |
| `unifi-mgr notify test` | wires TelegramNotifier |
| `unifi-mgr config validate` | catches missing required fields |
| dashboard.sh | rewritten, syntax valid |
| Tag created | `phase-4-complete` exists |

**Not in this phase:**
- ❌ `diag` подкоманды — Phase 6 (when diagnostics scripts ported)
- ❌ `device mute` / `site mute` — Phase 7 (deferred per D28)
- ❌ `audit critical --telegram` exit code 2 (controller unreachable) — Phase 7 health check
- ❌ Cron switch на проде — Phase 5
- ❌ Удаление legacy скриптов — Phase 6

---

## After Phase 4

`superpowers:writing-plans` для Phase 5 (Cron switch на проде):
- Cron migration table (5 steps, 24+ часов между)
- Deployment layout `/opt/unifi-mgr/` setup
- Observation period 1 неделя (D29 refinement)
- Документация для оператора
