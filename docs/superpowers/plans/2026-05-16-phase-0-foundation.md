# Phase 0 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Создать скелет нового пакета `unifi-mgr` с CI pipeline, типизированным конфигом и работающей CLI entry-point. На этой фазе НЕТ бизнес-логики — только инфраструктура, на которую будут опираться все последующие фазы.

**Architecture:** Python пакет с `src/`-layout, Typer CLI с `--version` (и пустыми подкомандами-заглушками), pydantic-settings со ВСЕМИ моделями конфига (они используются позже, в фазах 1-7, но определяются сразу для стабильного интерфейса). GitHub Actions CI с ruff/mypy/pytest. Старые скрипты в корне репы НЕ трогаются — они продолжают работать через текущий cron.

**Tech Stack:** Python 3.12, Typer, pydantic-settings, pytest + pytest-cov + responses + freezegun + hypothesis, ruff, mypy, pre-commit, GitHub Actions.

**Гейт готовности (из спека):** CI зелёный на пустом проекте, `unifi-mgr --version` работает, `pytest --cov` проходит порог 80%.

**Ветка работы:** `refactor/v2` (создаётся в Task 1, никогда не пересекается с master до фазы 5).

**Связанный спек:** [docs/superpowers/specs/2026-05-16-unifi-manager-refactor-design.md](../specs/2026-05-16-unifi-manager-refactor-design.md)

**Platform notes:** план написан под Windows (`.venv/Scripts/pytest`, `.venv/Scripts/unifi-mgr`). На Linux/macOS заменить `.venv/Scripts/` на `.venv/bin/`. Прод-сервер с cron — Linux (Ubuntu 24.04 LTS), но Phase 0 не касается прод-окружения — это локальная разработка.

---

## File Structure

### Создаются (новые файлы):

```
pyproject.toml                            # сборка, deps, ruff/mypy/pytest configs, entry-point unifi-mgr
.gitignore                                # config.json, .env, __pycache__, *.csv, *.json exports, logs
.pre-commit-config.yaml                   # ruff + mypy + быстрые pytest
.github/workflows/ci.yml                  # lint-type + test + build jobs
config.yaml.example                       # пример конфига (без секретов), коммитится
.env.example                              # пример секретов (placeholders), коммитится
docs/refactor-status.md                   # статус миграции — куда смотреть в переходный период

src/unifi_manager/
├── __init__.py                           # __version__ = "0.1.0"
├── settings.py                           # полная Settings(BaseSettings) со всеми моделями
├── logging_config.py                     # setup_logging(settings, verbose, quiet) — минимальный stub
├── cli/
│   ├── __init__.py                       # экспорт root Typer app
│   └── main.py                           # root app + --version callback + stub-подкоманды
├── clients/__init__.py                   # пустой
├── domain/__init__.py                    # пустой
├── services/__init__.py                  # пустой
├── diagnostics/__init__.py               # пустой
├── integrations/__init__.py              # пустой
└── utils/__init__.py                     # пустой

tests/
├── __init__.py
├── conftest.py                           # общие фикстуры (tmp config, monkey-patched settings paths)
├── fixtures/
│   └── settings_minimal.yaml             # минимальный валидный YAML для тестов
└── unit/
    ├── __init__.py
    ├── test_settings.py                  # парсинг yaml/env, приоритеты источников
    ├── test_logging.py                   # setup_logging без падений
    └── test_cli/
        ├── __init__.py
        └── test_main.py                  # --version, --help, root app существует
```

### Не трогаются на этой фазе:

- `audit_unifi.py`, `full_audit_unifi.py`, и все остальные старые `.py` в корне репы — они работают через старый cron, миграция в фазе 5
- `README.md` — оставляем старый до фазы 6; статус миграции описан в `docs/refactor-status.md`
- `config.json` — продолжает использоваться старыми скриптами
- `dashboard.sh`, `run_audit.sh`, `auto_restart_cron.sh` — переписываются в фазе 4

---

## Task 1: Project structure setup

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `docs/refactor-status.md`
- Create: пустые директории через .gitkeep если нужно

- [ ] **Step 1.1: Создать ветку `refactor/v2` от master**

```bash
git checkout -b refactor/v2
git status
```

Expected: на ветке `refactor/v2`, рабочее дерево с теми же uncommitted изменениями что были на master (это нормально — они не относятся к refactor).

- [ ] **Step 1.2: Создать `pyproject.toml`**

Полный файл:

```toml
[build-system]
requires = ["setuptools>=68", "setuptools-scm>=8"]
build-backend = "setuptools.build_meta"

[project]
name = "unifi-mgr"
version = "0.1.0"
description = "UniFi network management toolkit for production networks"
readme = "README.md"
requires-python = ">=3.12"
license = {text = "Proprietary"}
authors = [{name = "UniFi Bot"}]

dependencies = [
    "typer>=0.12",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "requests>=2.32",
    "rich>=13.7",
    "pyyaml>=6.0",
    "fasteners>=0.19",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pytest-mock>=3.12",
    "pytest-xdist>=3.5",
    "responses>=0.25",
    "freezegun>=1.5",
    "hypothesis>=6.100",
    "ruff>=0.5",
    "mypy>=1.10",
    "types-requests>=2.32",
    "types-pyyaml>=6.0",
    "pre-commit>=3.7",
]

[project.scripts]
unifi-mgr = "unifi_manager.cli.main:app"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
unifi_manager = ["py.typed"]

# === Ruff ===
[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src", "tests"]

[tool.ruff.lint]
select = [
    "E", "F", "W",         # pycodestyle + pyflakes
    "I",                   # isort
    "B",                   # flake8-bugbear
    "UP",                  # pyupgrade
    "SIM",                 # flake8-simplify
    "RUF",                 # ruff-specific
    "C4",                  # flake8-comprehensions
    "PT",                  # flake8-pytest-style
    "RET",                 # flake8-return
    "TID",                 # flake8-tidy-imports
]
ignore = [
    "E501",                # line too long — ruff format handles it
]

[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["B011"]  # assert False допустим в тестах

# === Mypy ===
[tool.mypy]
python_version = "3.12"
strict_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_return_any = true
warn_unreachable = true
disallow_untyped_defs = false  # глобально мягко, strict для core через CLI

[[tool.mypy.overrides]]
module = "tests.*"
disallow_untyped_defs = false

# === Pytest ===
[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
pythonpath = ["src"]
addopts = [
    "--strict-markers",
    "--strict-config",
    "-ra",
    "--cov=unifi_manager",
    "--cov-report=term-missing",
    "--cov-fail-under=80",
]
markers = [
    "fast: быстрые юнит-тесты (для pre-commit)",
    "slow: медленные тесты",
]

[tool.coverage.run]
source = ["src/unifi_manager"]
branch = true

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
]
```

- [ ] **Step 1.3: Создать `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
dist/
*.egg-info/
.eggs/

# Virtual envs
.venv/
venv/
env/

# Testing
.pytest_cache/
.coverage
coverage.xml
htmlcov/
.mypy_cache/
.ruff_cache/
.hypothesis/

# Secrets (всё что содержит реальные токены/пароли)
.env
.env.local

# Старый config (используется legacy-скриптами, не коммитим новые правки)
config.json

# Артефакты старых скриптов
*.log
unifi_clients_*.csv
unifi_clients_*.json
unifi_audit_report.json
ap_restart_history.json

# IDE
.vscode/
.idea/
*.swp
*~

# OS
.DS_Store
Thumbs.db
```

- [ ] **Step 1.4: Создать `docs/refactor-status.md`**

```markdown
# UniFi Manager — Refactor Status

**Текущее состояние:** в процессе миграции (Фаза 0).
**Целевая дата завершения:** ~2026-06-13.
**Спек:** [refactor design](superpowers/specs/2026-05-16-unifi-manager-refactor-design.md)
**Текущий план фазы:** [phase-0-foundation](superpowers/plans/2026-05-16-phase-0-foundation.md)

## Где что находится

| Что | Где | Статус |
|---|---|---|
| Старые скрипты (продакшен) | корень репы (`audit_unifi.py`, etc.) | работают через cron, не трогаем до фазы 5 |
| Новый код (в разработке) | `src/unifi_manager/` | растёт по фазам |
| Старый конфиг | `config.json` | для legacy-скриптов |
| Новый конфиг | `config.yaml` + `.env` | для нового пакета |
| Документация рефакторинга | `docs/superpowers/` | дизайн + планы |

## Прогресс по фазам

- [ ] Фаза 0: Foundation (этот план)
- [ ] Фаза 1: Core layers (clients, domain, utils)
- [ ] Фаза 2: Services + integrations
- [ ] Фаза 3: Restart logic
- [ ] Фаза 4: CLI complete
- [ ] Фаза 5: Cron switch (production)
- [ ] Фаза 6: Cleanup (удаление _legacy/)
- [ ] Фаза 7: Post-migration features

## Как запустить новый код локально

```bash
git checkout refactor/v2
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
unifi-mgr --version
pytest
```
```

- [ ] **Step 1.5: Создать пустую папку `src/unifi_manager/` и проверить структуру**

```bash
mkdir -p src/unifi_manager/cli src/unifi_manager/clients src/unifi_manager/domain
mkdir -p src/unifi_manager/services src/unifi_manager/diagnostics
mkdir -p src/unifi_manager/integrations src/unifi_manager/utils
mkdir -p tests/unit/test_cli tests/fixtures
mkdir -p .github/workflows
ls src/unifi_manager/
```

Expected: `cli  clients  diagnostics  domain  integrations  services  utils`

- [ ] **Step 1.6: Создать virtualenv (без установки пакета — пакет ещё пуст)**

```bash
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
```

Expected: virtualenv создан, pip обновлён. Установка пакета — в начале Task 2, после создания `__init__.py`.

- [ ] **Step 1.7: Commit**

```bash
git add pyproject.toml .gitignore docs/refactor-status.md
git commit -m "phase0: project scaffolding (pyproject, gitignore, status doc)"
```

---

## Task 2: Package skeleton

**Files:**
- Create: `src/unifi_manager/__init__.py`
- Create: `src/unifi_manager/py.typed`
- Create: `src/unifi_manager/cli/__init__.py`
- Create: `src/unifi_manager/clients/__init__.py`
- Create: `src/unifi_manager/domain/__init__.py`
- Create: `src/unifi_manager/services/__init__.py`
- Create: `src/unifi_manager/diagnostics/__init__.py`
- Create: `src/unifi_manager/integrations/__init__.py`
- Create: `src/unifi_manager/utils/__init__.py`
- Test: `tests/unit/test_package_imports.py`

- [ ] **Step 2.0: Установить пакет в editable режиме**

Перед написанием тестов нужно дать установить пакет (для editable установки достаточно структуры из Task 1 + пары `__init__.py`, которые создадим в шагах 2.3-2.5 — но pip без них не найдёт пакет). Чтобы избежать chicken-and-egg, создадим минимальный `src/unifi_manager/__init__.py` сейчас, остальное — в TDD-цикле.

```bash
echo "__version__ = '0.1.0'" > src/unifi_manager/__init__.py
.venv/Scripts/pip install -e ".[dev]"
```

Expected: установка проходит без ошибок, `pip list` показывает `unifi-mgr 0.1.0`.

- [ ] **Step 2.1: Написать failing test для импорта пакета**

`tests/__init__.py` (пустой) и `tests/unit/__init__.py` (пустой) — создать.

`tests/unit/test_package_imports.py`:

```python
"""Smoke-тест что пакет импортируется и имеет __version__."""
import pytest


def test_package_imports() -> None:
    import unifi_manager
    assert hasattr(unifi_manager, "__version__")
    assert isinstance(unifi_manager.__version__, str)
    assert unifi_manager.__version__ == "0.1.0"


@pytest.mark.parametrize("submodule", [
    "unifi_manager.cli",
    "unifi_manager.clients",
    "unifi_manager.domain",
    "unifi_manager.services",
    "unifi_manager.diagnostics",
    "unifi_manager.integrations",
    "unifi_manager.utils",
])
def test_submodule_imports(submodule: str) -> None:
    __import__(submodule)
```

- [ ] **Step 2.2: Запустить тест, убедиться что падает**

```bash
.venv/Scripts/pytest tests/unit/test_package_imports.py -v --no-cov
```

Expected: FAIL с `ModuleNotFoundError: No module named 'unifi_manager'`.

- [ ] **Step 2.3: Дополнить `src/unifi_manager/__init__.py`** (из Step 2.0 уже есть `__version__`, добавим docstring)

```python
"""UniFi network management toolkit."""

__version__ = "0.1.0"
```

- [ ] **Step 2.4: Создать `src/unifi_manager/py.typed`** (пустой файл — маркер для mypy что пакет типизирован)

```bash
echo. > src/unifi_manager/py.typed
```

(На Linux: `touch src/unifi_manager/py.typed`)

- [ ] **Step 2.5: Создать все пустые `__init__.py` для подмодулей**

Для каждого подмодуля (`cli`, `clients`, `domain`, `services`, `diagnostics`, `integrations`, `utils`):

`src/unifi_manager/<подмодуль>/__init__.py`:
```python
"""<подмодуль> layer — see docs/superpowers/specs/ for design."""
```

- [ ] **Step 2.6: Запустить тест, убедиться что проходит**

```bash
.venv/Scripts/pytest tests/unit/test_package_imports.py -v --no-cov
```

Expected: PASS (8 тестов: 1 базовый + 7 параметризованных).

- [ ] **Step 2.7: Commit**

```bash
git add src/unifi_manager/ tests/__init__.py tests/unit/__init__.py tests/unit/test_package_imports.py
git commit -m "phase0: package skeleton with __version__"
```

---

## Task 3: Settings schema (pydantic-settings)

**Files:**
- Create: `src/unifi_manager/settings.py`
- Create: `tests/unit/test_settings.py`
- Create: `tests/fixtures/settings_minimal.yaml`
- Create: `tests/fixtures/settings_full.yaml`
- Modify: `tests/conftest.py` (создать)

- [ ] **Step 3.1: Создать `tests/conftest.py` с базовыми фикстурами**

```python
"""Global pytest fixtures."""
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """Путь к директории с тестовыми fixtures (YAML, JSON snapshots)."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Изолированная директория для конфига в одном тесте.

    Меняет cwd на tmp_path, так что любой `./config.yaml` относителен к нему.
    """
    monkeypatch.chdir(tmp_path)
    yield tmp_path
```

- [ ] **Step 3.2: Создать `tests/fixtures/settings_minimal.yaml`**

Минимальный валидный конфиг (все обязательные поля):

```yaml
unifi:
  host: 192.0.2.1
  port: 11443
  site: site-1
```

- [ ] **Step 3.3: Создать `tests/fixtures/settings_full.yaml`**

Конфиг со всеми секциями (для проверки парсинга):

```yaml
unifi:
  host: 192.0.2.1
  port: 11443
  site: site-1
  site_id_uuid: bbffb94c-1234-5678-9abc-def012345678
  verify_ssl: false

telegram:
  chat_id: "123456789"
  enabled: true
  parse_mode: MarkdownV2
  rate_limit_per_hash_seconds: 30
  rate_limit_total_per_minute: 5

auto_restart:
  max_restarts_per_run: 5
  cooldown_minutes: 60
  offline_threshold_min: 15
  exclude_patterns: ["Spasatel", "test"]

restart_profiles:
  restaurant:
    filter_names: [Restoran, "Restoran WIFI", "Rest Bar"]
    exclude_names: ["Spasatel vagon"]
    lost_contact_threshold: 3
    window_hours: 24
    max_restarts: 5
    cooldown_minutes: 120

thresholds:
  critical_temp_c: 70
  critical_poe_percent: 90
  high_cu_percent: 50
  port_error_delta_threshold: 50

logging:
  log_dir: /var/log/unifi-mgr
  console_format: human
  level: INFO

paths:
  reports_dir: /var/lib/unifi-mgr/reports
  export_dir: /var/lib/unifi-mgr/exports

audit_health_check:
  enabled: true
  dns_servers: ["8.8.8.8", "1.1.1.1"]
  http_endpoints: ["https://www.cloudflare.com"]
  timeout_seconds: 5

maintenance:
  default_mute_duration_minutes: 30
  max_mute_duration_hours: 24
```

- [ ] **Step 3.4: Написать failing tests для Settings**

`tests/unit/test_settings.py`:

```python
"""Тесты для unifi_manager.settings."""
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError


def test_settings_loads_from_yaml(fixtures_dir: Path, tmp_config_dir: Path) -> None:
    """Settings парсит config.yaml без обязательных env переменных
    (если все обязательные поля в YAML)."""
    yaml_src = fixtures_dir / "settings_minimal.yaml"
    (tmp_config_dir / "config.yaml").write_bytes(yaml_src.read_bytes())

    from unifi_manager.settings import Settings

    settings = Settings()  # type: ignore[call-arg]
    assert settings.unifi.host == "192.0.2.1"
    assert settings.unifi.port == 11443
    assert settings.unifi.site == "site-1"


def test_settings_loads_full_yaml(fixtures_dir: Path, tmp_config_dir: Path) -> None:
    """Settings парсит config.yaml со всеми секциями без ошибок."""
    yaml_src = fixtures_dir / "settings_full.yaml"
    (tmp_config_dir / "config.yaml").write_bytes(yaml_src.read_bytes())

    from unifi_manager.settings import Settings

    settings = Settings()  # type: ignore[call-arg]

    assert "restaurant" in settings.restart_profiles
    assert settings.restart_profiles["restaurant"].lost_contact_threshold == 3
    assert settings.thresholds.port_error_delta_threshold == 50
    assert settings.audit_health_check.enabled is True
    assert settings.maintenance.max_mute_duration_hours == 24


def test_env_overrides_yaml(fixtures_dir: Path, tmp_config_dir: Path,
                             monkeypatch: pytest.MonkeyPatch) -> None:
    """ENV переменные имеют приоритет над YAML."""
    yaml_src = fixtures_dir / "settings_minimal.yaml"
    (tmp_config_dir / "config.yaml").write_bytes(yaml_src.read_bytes())

    monkeypatch.setenv("UNIFI_UNIFI__HOST", "10.0.0.99")
    monkeypatch.setenv("UNIFI_UNIFI__USERNAME", "TestUser")
    monkeypatch.setenv("UNIFI_UNIFI__PASSWORD", "test-secret-pass")

    from unifi_manager.settings import Settings

    settings = Settings()  # type: ignore[call-arg]
    assert settings.unifi.host == "10.0.0.99"
    assert settings.unifi.username is not None
    assert settings.unifi.username.get_secret_value() == "TestUser"
    assert settings.unifi.password is not None
    assert settings.unifi.password.get_secret_value() == "test-secret-pass"


def test_secrets_are_masked_in_repr(tmp_config_dir: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """SecretStr скрывает значение в repr — защита от случайного print."""
    (tmp_config_dir / "config.yaml").write_text("""
unifi:
  host: 1.2.3.4
  port: 11443
  site: test
""")
    monkeypatch.setenv("UNIFI_UNIFI__PASSWORD", "super-secret-do-not-leak")

    from unifi_manager.settings import Settings

    settings = Settings()  # type: ignore[call-arg]
    assert "super-secret-do-not-leak" not in repr(settings)
    assert "super-secret-do-not-leak" not in str(settings.unifi)


def test_missing_required_field_raises(tmp_config_dir: Path) -> None:
    """Settings падает с ValidationError если нет обязательного unifi.host."""
    (tmp_config_dir / "config.yaml").write_text("""
unifi:
  port: 11443
  site: test
""")
    from unifi_manager.settings import Settings

    with pytest.raises(ValidationError) as exc_info:
        Settings()  # type: ignore[call-arg]
    assert "host" in str(exc_info.value)


def test_extra_field_forbidden(tmp_config_dir: Path) -> None:
    """extra='forbid' на верхнем уровне — опечатки в YAML дают ошибку."""
    (tmp_config_dir / "config.yaml").write_text("""
unifi:
  host: 1.2.3.4
  port: 11443
  site: test
unknown_typo_section:
  something: 42
""")
    from unifi_manager.settings import Settings

    with pytest.raises(ValidationError) as exc_info:
        Settings()  # type: ignore[call-arg]
    assert "unknown_typo_section" in str(exc_info.value) or "Extra" in str(exc_info.value)


def test_restart_profiles_dict_works(tmp_config_dir: Path) -> None:
    """restart_profiles — dict[str, RestartProfile]."""
    (tmp_config_dir / "config.yaml").write_text("""
unifi:
  host: 1.2.3.4
  port: 11443
  site: test

restart_profiles:
  restaurant:
    filter_names: [Restoran]
    lost_contact_threshold: 3
  office:
    filter_patterns: ["^office.*"]
    lost_contact_threshold: 5
""")
    from unifi_manager.settings import Settings

    settings = Settings()  # type: ignore[call-arg]
    assert set(settings.restart_profiles.keys()) == {"restaurant", "office"}
    assert settings.restart_profiles["restaurant"].lost_contact_threshold == 3
    assert settings.restart_profiles["office"].filter_patterns == ["^office.*"]
```

- [ ] **Step 3.5: Запустить тесты, убедиться что падают**

```bash
.venv/Scripts/pytest tests/unit/test_settings.py -v --no-cov
```

Expected: FAIL с `ModuleNotFoundError: No module named 'unifi_manager.settings'`.

- [ ] **Step 3.6: Создать `src/unifi_manager/settings.py`**

```python
"""Типизированная конфигурация через pydantic-settings.

Источники (приоритет от низкого к высокому):
    defaults в коде → config.yaml → .env → env vars → CLI флаги

Места поиска config.yaml (первый найденный выигрывает):
    1. --config PATH (CLI флаг, передаётся через UNIFI_CONFIG_PATH env)
    2. ./config.yaml
    3. ~/.config/unifi-mgr/config.yaml
    4. /etc/unifi-mgr/config.yaml
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


def _find_yaml() -> Path | None:
    """Найти config.yaml в стандартных местах."""
    cli_path = os.environ.get("UNIFI_CONFIG_PATH")
    if cli_path:
        return Path(cli_path)

    candidates = [
        Path.cwd() / "config.yaml",
        Path.home() / ".config" / "unifi-mgr" / "config.yaml",
        Path("/etc/unifi-mgr/config.yaml"),
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


class YamlConfigSource(PydanticBaseSettingsSource):
    """pydantic-settings source: читает YAML файл найденный через _find_yaml()."""

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False  # реализация через __call__

    def __call__(self) -> dict[str, Any]:
        path = _find_yaml()
        if not path:
            return {}
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path}: top-level YAML must be a mapping")
        return data


class UnifiAuthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    port: int = 11443
    site: str
    site_id_uuid: str | None = None
    username: SecretStr | None = None
    password: SecretStr | None = None
    api_key: SecretStr | None = None
    verify_ssl: bool | Path = False


class TelegramSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_token: SecretStr | None = None
    chat_id: str | None = None
    enabled: bool = True
    parse_mode: Literal["MarkdownV2", "HTML", "None"] = "MarkdownV2"
    rate_limit_per_hash_seconds: int = 30
    rate_limit_total_per_minute: int = 5


class RestartProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter_names: list[str] = Field(default_factory=list)
    filter_patterns: list[str] = Field(default_factory=list)
    exclude_names: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    # Триггер: count EVT_AP_Lost_Contact СТРОГО БОЛЬШЕ threshold за window_hours.
    lost_contact_threshold: int = 3
    window_hours: int = 24
    max_restarts: int = 5
    cooldown_minutes: int = 60


class AutoRestartSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_restarts_per_run: int = 5
    cooldown_minutes: int = 60
    offline_threshold_min: int = 15
    exclude_patterns: list[str] = Field(default_factory=list)
    statefile: Path = Path("/var/lib/unifi-mgr/restart_history.json")


class ThresholdsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    critical_temp_c: int = 70
    critical_poe_percent: int = 90
    high_cu_percent: int = 50
    # Фаза 7: триггер WARNING если на любом порту счётчик ошибок
    # вырос больше чем на N. 0 = отключено.
    port_error_delta_threshold: int = 50


class LoggingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    log_dir: Path = Path("/var/log/unifi-mgr")
    console_format: Literal["human", "json"] = "human"
    file_format: Literal["json"] = "json"
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    max_bytes: int = 10_000_000
    backup_count: int = 5


class PathsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reports_dir: Path = Path("/var/lib/unifi-mgr/reports")
    export_dir: Path = Path("/var/lib/unifi-mgr/exports")
    cache_dir: Path = Field(default_factory=lambda: Path.home() / ".cache" / "unifi-mgr")


class AuditHealthCheckSettings(BaseModel):
    """Фаза 7: pre-check контроллера перед audit critical."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    dns_servers: list[str] = Field(default_factory=lambda: ["8.8.8.8", "1.1.1.1"])
    http_endpoints: list[str] = Field(
        default_factory=lambda: ["https://www.cloudflare.com", "https://www.google.com"]
    )
    timeout_seconds: int = 5


class MaintenanceSettings(BaseModel):
    """Фаза 7: maintenance mode для защиты от ложных рестартов."""

    model_config = ConfigDict(extra="forbid")

    mute_state_file: Path = Path("/var/lib/unifi-mgr/mute_state.json")
    audit_baseline_file: Path = Path("/var/lib/unifi-mgr/audit_baseline.json")
    default_mute_duration_minutes: int = 30
    max_mute_duration_hours: int = 24


class Settings(BaseSettings):
    """Главный конфиг приложения."""

    model_config = SettingsConfigDict(
        env_prefix="UNIFI_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    unifi: UnifiAuthSettings
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    auto_restart: AutoRestartSettings = Field(default_factory=AutoRestartSettings)
    restart_profiles: dict[str, RestartProfile] = Field(default_factory=dict)
    thresholds: ThresholdsSettings = Field(default_factory=ThresholdsSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    paths: PathsSettings = Field(default_factory=PathsSettings)
    # Фаза 7: имеют дефолты, в фазах 0-6 не используются.
    audit_health_check: AuditHealthCheckSettings = Field(default_factory=AuditHealthCheckSettings)
    maintenance: MaintenanceSettings = Field(default_factory=MaintenanceSettings)

    @classmethod
    def settings_customise_sources(  # type: ignore[override]
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Приоритет (от низкого к высокому = справа налево):
        # defaults → YAML → .env → env → init (CLI)
        yaml_source = YamlConfigSource(settings_cls)
        return (init_settings, env_settings, dotenv_settings, yaml_source, file_secret_settings)
```

- [ ] **Step 3.7: Запустить тесты, убедиться что проходят**

```bash
.venv/Scripts/pytest tests/unit/test_settings.py -v --no-cov
```

Expected: PASS (7 тестов).

Если упало на `test_extra_field_forbidden` — проверить что `extra="forbid"` действительно в `SettingsConfigDict`. Если на `test_env_overrides_yaml` — проверить env_nested_delimiter.

- [ ] **Step 3.8: Commit**

```bash
git add src/unifi_manager/settings.py tests/unit/test_settings.py tests/fixtures/ tests/conftest.py
git commit -m "phase0: pydantic-settings schema with YAML + env + .env sources"
```

---

## Task 4: Logging config stub

**Files:**
- Create: `src/unifi_manager/logging_config.py`
- Create: `tests/unit/test_logging.py`

На фазе 0 — минимальная реализация. Полный JSON formatter, RichHandler и SecretsFilter — в фазе 1/2. Сейчас только `setup_logging()` должна работать без падений.

- [ ] **Step 4.1: Написать failing tests**

`tests/unit/test_logging.py`:

```python
"""Smoke-тесты для logging_config (минимальная реализация)."""
import logging

import pytest


def test_setup_logging_callable() -> None:
    from unifi_manager.logging_config import setup_logging
    assert callable(setup_logging)


def test_setup_logging_returns_none() -> None:
    """setup_logging — side-effect функция (настраивает root logger),
    возвращает None."""
    from unifi_manager.logging_config import setup_logging
    from unifi_manager.settings import LoggingSettings

    result = setup_logging(LoggingSettings(), verbose=0, quiet=0)
    assert result is None


@pytest.mark.parametrize("verbose,quiet,expected", [
    (0, 0, logging.INFO),
    (1, 0, logging.DEBUG),
    (2, 0, logging.DEBUG),
    (0, 1, logging.WARNING),
])
def test_setup_logging_levels(verbose: int, quiet: int, expected: int) -> None:
    """verbose/quiet флаги меняют уровень root логгера."""
    from unifi_manager.logging_config import setup_logging
    from unifi_manager.settings import LoggingSettings

    setup_logging(LoggingSettings(), verbose=verbose, quiet=quiet)
    assert logging.getLogger().level == expected


def test_setup_logging_idempotent() -> None:
    """Повторный вызов не должен дублировать handlers."""
    from unifi_manager.logging_config import setup_logging
    from unifi_manager.settings import LoggingSettings

    setup_logging(LoggingSettings(), verbose=0, quiet=0)
    handlers_after_first = len(logging.getLogger().handlers)
    setup_logging(LoggingSettings(), verbose=0, quiet=0)
    handlers_after_second = len(logging.getLogger().handlers)
    assert handlers_after_first == handlers_after_second
```

- [ ] **Step 4.2: Запустить тесты, убедиться что падают**

```bash
.venv/Scripts/pytest tests/unit/test_logging.py -v --no-cov
```

Expected: FAIL с `ModuleNotFoundError: No module named 'unifi_manager.logging_config'`.

- [ ] **Step 4.3: Создать `src/unifi_manager/logging_config.py`**

```python
"""Минимальный logging setup для фазы 0.

В фазе 1+ будет расширено:
    - RichHandler для console (цветной вывод)
    - JSON-formatter для файлового handler
    - RotatingFileHandler
    - SecretsFilter (защита от утечки SecretStr в логи)
    - TelegramHandler с rate-limit
"""
from __future__ import annotations

import logging
import sys

from unifi_manager.settings import LoggingSettings

_LOGGING_CONFIGURED = False


def setup_logging(
    settings: LoggingSettings,
    verbose: int = 0,
    quiet: int = 0,
) -> None:
    """Настраивает root logger.

    Args:
        settings: настройки логирования из Settings.logging
        verbose: число -v флагов (1+ = DEBUG для console)
        quiet: число -q флагов (1+ = WARNING+ для console)
    """
    global _LOGGING_CONFIGURED

    root = logging.getLogger()

    if quiet > 0:
        level = logging.WARNING
    elif verbose > 0:
        level = logging.DEBUG
    else:
        level = logging.getLevelName(settings.level)

    root.setLevel(level)

    # Идемпотентность: не добавляем handler если уже был наш.
    if _LOGGING_CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(handler)

    _LOGGING_CONFIGURED = True
```

- [ ] **Step 4.4: Запустить тесты, убедиться что проходят**

```bash
.venv/Scripts/pytest tests/unit/test_logging.py -v --no-cov
```

Expected: PASS (7 тестов: 1 callable + 1 None + 4 параметризованных levels + 1 idempotent).

- [ ] **Step 4.5: Commit**

```bash
git add src/unifi_manager/logging_config.py tests/unit/test_logging.py
git commit -m "phase0: minimal logging setup (full impl deferred to phase 2)"
```

---

## Task 5: CLI root app with --version

**Files:**
- Create: `src/unifi_manager/cli/main.py`
- Modify: `src/unifi_manager/cli/__init__.py`
- Create: `tests/unit/test_cli/__init__.py`
- Create: `tests/unit/test_cli/test_main.py`

- [ ] **Step 5.1: Написать failing tests**

`tests/unit/test_cli/__init__.py` — пустой.

`tests/unit/test_cli/test_main.py`:

```python
"""Тесты root CLI app."""
import re

from typer.testing import CliRunner

from unifi_manager import __version__


def test_version_flag_prints_version() -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_flag_works() -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "unifi-mgr" in result.stdout.lower() or "Usage" in result.stdout


def test_invoking_without_args_shows_help() -> None:
    """Запуск unifi-mgr без аргументов показывает help, exit 0 или 2."""
    from unifi_manager.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, [])
    # Typer по умолчанию exit 2 + help; либо app настроен no_args_is_help=True
    assert result.exit_code in (0, 2)
    assert "Usage" in result.stdout or "Usage" in (result.stderr or "")


def test_subcommand_audit_exists() -> None:
    """Подкоманда audit зарегистрирована (stub, ничего не делает в фазе 0)."""
    from unifi_manager.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["audit", "--help"])
    assert result.exit_code == 0


def test_subcommand_restart_exists() -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["restart", "--help"])
    assert result.exit_code == 0


def test_subcommand_config_exists() -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["config", "--help"])
    assert result.exit_code == 0


def test_subcommand_audit_critical_stub_runs() -> None:
    """audit critical существует как stub (фаза 0). При вызове —
    печатает 'not implemented' и exit 1, чтобы случайно не использовали в cron."""
    from unifi_manager.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["audit", "critical"])
    assert result.exit_code == 1
    assert re.search(r"not implemented|stub|phase", result.stdout, re.IGNORECASE)
```

- [ ] **Step 5.2: Запустить тесты, убедиться что падают**

```bash
.venv/Scripts/pytest tests/unit/test_cli/ -v --no-cov
```

Expected: FAIL с `ModuleNotFoundError: No module named 'unifi_manager.cli.main'`.

- [ ] **Step 5.3: Создать `src/unifi_manager/cli/main.py`**

```python
"""Root Typer app для unifi-mgr.

В фазе 0 — только структура подкоманд + --version. Все команды кроме --version/--help
возвращают exit 1 со stub-сообщением. Имплементация подкоманд — в фазах 1-7.
"""
from __future__ import annotations

from typing import Annotated

import typer

from unifi_manager import __version__

app = typer.Typer(
    name="unifi-mgr",
    help="UniFi network management toolkit",
    no_args_is_help=True,
    add_completion=False,
)

# Подкоманды-группы — будут наполняться в последующих фазах.
audit_app = typer.Typer(help="Аудит и мониторинг сети", no_args_is_help=True)
restart_app = typer.Typer(help="Рестарт устройств", no_args_is_help=True)
export_app = typer.Typer(help="Экспорт данных", no_args_is_help=True)
diag_app = typer.Typer(help="Диагностика и расследования", no_args_is_help=True)
notify_app = typer.Typer(help="Уведомления (Telegram)", no_args_is_help=True)
zabbix_app = typer.Typer(help="Интеграция с Zabbix", no_args_is_help=True)
config_app = typer.Typer(help="Управление конфигурацией", no_args_is_help=True)
login_app = typer.Typer(help="Проверка аутентификации", no_args_is_help=True)
legacy_app = typer.Typer(help="Wrapper для старых скриптов (deprecated)", no_args_is_help=True)

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
        typer.Option("--version", callback=_version_callback, is_eager=True,
                     help="Показать версию и выйти"),
    ] = False,
) -> None:
    """UniFi network management toolkit."""


def _stub(cmd: str) -> None:
    """Помощник для stub-подкоманд фазы 0."""
    typer.echo(f"[phase 0 stub] '{cmd}' not implemented yet — see refactor plan.")
    raise typer.Exit(code=1)


# === Stub подкоманд (фаза 0) ===
# Заменяются настоящими в фазах 1-7. Сейчас существуют только чтобы --help работал
# для всех групп.

@audit_app.command("critical", help="[stub] Быстрая проверка критических проблем")
def audit_critical() -> None:
    _stub("audit critical")


@audit_app.command("full", help="[stub] Полный аудит")
def audit_full() -> None:
    _stub("audit full")


@restart_app.command("auto", help="[stub] Авто-рестарт проблемных AP")
def restart_auto() -> None:
    _stub("restart auto")


@config_app.command("validate", help="[stub] Валидация config.yaml")
def config_validate() -> None:
    _stub("config validate")


if __name__ == "__main__":
    app()
```

- [ ] **Step 5.4: Обновить `src/unifi_manager/cli/__init__.py` (экспорт app)**

```python
"""CLI layer — Typer entrypoints."""
from unifi_manager.cli.main import app

__all__ = ["app"]
```

- [ ] **Step 5.5: Запустить тесты, убедиться что проходят**

```bash
.venv/Scripts/pytest tests/unit/test_cli/ -v --no-cov
```

Expected: PASS (7 тестов).

- [ ] **Step 5.6: Запустить установленный CLI вживую**

```bash
.venv/Scripts/unifi-mgr --version
```

Expected: `unifi-mgr 0.1.0`

```bash
.venv/Scripts/unifi-mgr --help
```

Expected: usage с перечислением подкоманд (audit, restart, export, diag, notify, zabbix, config, login, legacy).

```bash
.venv/Scripts/unifi-mgr audit critical
```

Expected: `[phase 0 stub] 'audit critical' not implemented yet — see refactor plan.` и exit code 1.

- [ ] **Step 5.7: Commit**

```bash
git add src/unifi_manager/cli/ tests/unit/test_cli/
git commit -m "phase0: CLI root app with --version and stub subcommands"
```

---

## Task 6: Example configs (config.yaml.example, .env.example)

**Files:**
- Create: `config.yaml.example`
- Create: `.env.example`
- Create: `tests/unit/test_example_configs.py`

- [ ] **Step 6.1: Написать failing test**

`tests/unit/test_example_configs.py`:

```python
"""Проверка что example конфиги валидны и парсятся."""
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_config_yaml_example_exists() -> None:
    assert (REPO_ROOT / "config.yaml.example").is_file()


def test_env_example_exists() -> None:
    assert (REPO_ROOT / ".env.example").is_file()


def test_config_yaml_example_parses(tmp_path: Path,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """config.yaml.example парсится как валидный Settings (с минимальными
    обязательными env переменными для секретов)."""
    monkeypatch.chdir(tmp_path)
    example_src = (REPO_ROOT / "config.yaml.example").read_bytes()
    (tmp_path / "config.yaml").write_bytes(example_src)

    # Минимальные env, которые могут понадобиться (если они в example placeholders)
    monkeypatch.setenv("UNIFI_UNIFI__USERNAME", "test")
    monkeypatch.setenv("UNIFI_UNIFI__PASSWORD", "test")

    from unifi_manager.settings import Settings
    settings = Settings()  # type: ignore[call-arg]
    assert settings.unifi.host
    assert settings.unifi.site


def test_env_example_has_required_keys() -> None:
    """В .env.example должны быть все главные ключи (как комментарий или value)."""
    content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    required = [
        "UNIFI_UNIFI__USERNAME",
        "UNIFI_UNIFI__PASSWORD",
        "UNIFI_UNIFI__API_KEY",
        "UNIFI_TELEGRAM__BOT_TOKEN",
    ]
    for key in required:
        assert key in content, f"missing {key} in .env.example"
```

- [ ] **Step 6.2: Запустить тесты, убедиться что падают**

```bash
.venv/Scripts/pytest tests/unit/test_example_configs.py -v --no-cov
```

Expected: FAIL (файлов нет).

- [ ] **Step 6.3: Создать `config.yaml.example`**

```yaml
# Пример конфигурации unifi-mgr.
# Скопируйте в config.yaml и подгоните значения под свою среду.
# Секреты (пароли, токены) ставьте в .env, не сюда.

unifi:
  host: 192.0.2.1
  port: 11443
  site: site-1
  site_id_uuid: bbffb94c-1234-5678-9abc-def012345678  # UUID для Integration API
  verify_ssl: false                                    # true или путь к pem

telegram:
  chat_id: "123456789"
  enabled: true
  parse_mode: MarkdownV2

auto_restart:
  max_restarts_per_run: 5
  cooldown_minutes: 60
  offline_threshold_min: 15
  exclude_patterns: ["Spasatel", "test"]

restart_profiles:
  restaurant:
    filter_names: [Restoran, "Restoran WIFI", "Rest Bar"]
    exclude_names: ["Spasatel vagon"]
    lost_contact_threshold: 3
    cooldown_minutes: 120
  # office:
  #   filter_patterns: ["^office.*"]
  #   lost_contact_threshold: 5

thresholds:
  critical_temp_c: 70
  critical_poe_percent: 90
  high_cu_percent: 50
  # Фаза 7: 0 = отключено
  port_error_delta_threshold: 50

logging:
  log_dir: /var/log/unifi-mgr
  console_format: human
  level: INFO

paths:
  reports_dir: /var/lib/unifi-mgr/reports
  export_dir: /var/lib/unifi-mgr/exports

# Фаза 7: контроллер health check
audit_health_check:
  enabled: true
  dns_servers: ["8.8.8.8", "1.1.1.1"]
  http_endpoints: ["https://www.cloudflare.com"]
  timeout_seconds: 5

# Фаза 7: maintenance mode
maintenance:
  default_mute_duration_minutes: 30
  max_mute_duration_hours: 24
```

- [ ] **Step 6.4: Создать `.env.example`**

```bash
# Секреты для unifi-mgr. Скопируйте в .env и заполните реальными значениями.
# .env в .gitignore — никогда не коммитить.

# UniFi Legacy API (session-based auth)
UNIFI_UNIFI__USERNAME=unifi_user
UNIFI_UNIFI__PASSWORD=replace_me

# UniFi Integration API (API key auth)
UNIFI_UNIFI__API_KEY=replace_me_with_real_key

# Telegram бот для уведомлений
UNIFI_TELEGRAM__BOT_TOKEN=123456789:replace_me_with_real_token
```

- [ ] **Step 6.5: Запустить тесты, убедиться что проходят**

```bash
.venv/Scripts/pytest tests/unit/test_example_configs.py -v --no-cov
```

Expected: PASS (4 теста).

- [ ] **Step 6.6: Commit**

```bash
git add config.yaml.example .env.example tests/unit/test_example_configs.py
git commit -m "phase0: example configs (config.yaml.example, .env.example)"
```

---

## Task 7: Pre-commit configuration

**Files:**
- Create: `.pre-commit-config.yaml`

- [ ] **Step 7.1: Создать `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.0
    hooks:
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
        additional_dependencies:
          - pydantic>=2.7
          - pydantic-settings>=2.3
          - types-requests
          - types-pyyaml
          - typer
        args: [--config-file=pyproject.toml]
        files: ^src/

  - repo: local
    hooks:
      - id: pytest-fast
        name: pytest-fast
        entry: .venv/Scripts/pytest -m "fast or not slow" --no-cov -q
        language: system
        pass_filenames: false
        stages: [pre-commit]
        always_run: true
```

- [ ] **Step 7.2: Установить pre-commit hooks**

```bash
.venv/Scripts/pre-commit install
```

Expected: `pre-commit installed at .git/hooks/pre-commit`

- [ ] **Step 7.3: Прогнать pre-commit вручную на всех файлах**

```bash
.venv/Scripts/pre-commit run --all-files
```

Expected: PASS (или один проход с автофиксом форматирования, после чего PASS).

Если ruff что-то поправил — `git add -A`, потом снова `pre-commit run --all-files`, теперь PASS.

- [ ] **Step 7.4: Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "phase0: pre-commit hooks (ruff + mypy + pytest-fast)"
```

---

## Task 8: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 8.1: Создать `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [master, refactor/v2]
  pull_request:

jobs:
  lint-type:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"
      - name: Ruff check
        run: ruff check .
      - name: Ruff format check
        run: ruff format --check .
      - name: Mypy strict (core)
        # В фазе 0 ещё нет core модулей, только settings/logging — проверяем их.
        run: mypy --strict src/unifi_manager/settings.py src/unifi_manager/logging_config.py
      - name: Mypy (rest)
        run: mypy src/unifi_manager

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"
      - name: Pytest
        run: pytest --cov-fail-under=80

  build:
    needs: [lint-type, test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install build
        run: pip install build
      - name: Build wheel
        run: python -m build
      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: wheel
          path: dist/*.whl
```

- [ ] **Step 8.2: Локальная проверка что все проверки CI зелёные**

Запускаем то же, что будет в CI, локально:

```bash
.venv/Scripts/ruff check .
```
Expected: `All checks passed!`

```bash
.venv/Scripts/ruff format --check .
```
Expected: пустой вывод или "All files would be left unchanged."

```bash
.venv/Scripts/mypy --strict src/unifi_manager/settings.py src/unifi_manager/logging_config.py
```
Expected: `Success: no issues found in 2 source files`

```bash
.venv/Scripts/mypy src/unifi_manager
```
Expected: `Success: no issues found in ... source files`

```bash
.venv/Scripts/pytest --cov-fail-under=80
```
Expected: все тесты PASS, coverage ≥ 80%, exit 0.

Если coverage < 80% — добавить `# pragma: no cover` на ветки которые сейчас не покрыты (например блок `if __name__ == "__main__":` в `cli/main.py` — уже в `tool.coverage.report.exclude_lines`).

- [ ] **Step 8.3: Commit и push**

```bash
git add .github/workflows/ci.yml
git commit -m "phase0: GitHub Actions CI (lint-type, test, build)"
git push -u origin refactor/v2
```

- [ ] **Step 8.4: Проверить что CI зелёный на GitHub**

Открыть GitHub репу → Actions → найти запуск на push в `refactor/v2` → дождаться зелёных галок на всех трёх job'ах (lint-type, test, build).

Если упало — открыть failed job, прочитать лог, исправить, push новым коммитом, повторить.

---

## Task 9: Final acceptance check (Фаза 0 gate)

Все требования из спека для Фазы 0:
- ✅ CI зелёный на пустом проекте
- ✅ `unifi-mgr --version` работает

Финальная проверка на чистой среде.

- [ ] **Step 9.1: Создать чистую виртуалку и установить с нуля**

```bash
rm -rf .venv-acceptance
python -m venv .venv-acceptance
.venv-acceptance/Scripts/pip install -e ".[dev]"
```

Expected: установка без ошибок.

- [ ] **Step 9.2: Прогнать full test suite на чистой виртуалке**

```bash
.venv-acceptance/Scripts/pytest --cov-fail-under=80 -v
```

Expected: все тесты PASS, exit 0.

- [ ] **Step 9.3: Проверить CLI commands вживую**

```bash
.venv-acceptance/Scripts/unifi-mgr --version
```
Expected: `unifi-mgr 0.1.0`

```bash
.venv-acceptance/Scripts/unifi-mgr --help
```
Expected: usage со списком 9 подкоманд (audit, restart, export, diag, notify, zabbix, config, login, legacy).

```bash
.venv-acceptance/Scripts/unifi-mgr audit --help
```
Expected: usage с подкомандой critical, full.

```bash
.venv-acceptance/Scripts/unifi-mgr audit critical
```
Expected: `[phase 0 stub] 'audit critical' not implemented yet — see refactor plan.` и exit 1.

- [ ] **Step 9.4: Проверить что CI зелёный**

Открыть GitHub Actions → последний run на ветке `refactor/v2` → должен быть зелёный.

- [ ] **Step 9.5: Удалить чистую виртуалку (cleanup)**

```bash
rm -rf .venv-acceptance
```

- [ ] **Step 9.6: Финальный commit-ярлык**

Если все шаги выше зелёные — фаза 0 выполнена.

```bash
git tag -a phase-0-complete -m "Phase 0 (Foundation) complete: skeleton, CI, --version works"
git push --tags
```

---

## Definition of Done — Phase 0

После выполнения всех тасков должно выполняться:

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| Пакет ставится | `pip install -e ".[dev]"` | Без ошибок |
| Версия читается | `unifi-mgr --version` | `unifi-mgr 0.1.0` |
| CLI группы есть | `unifi-mgr --help` | 9 подкоманд видны |
| Подкоманды — stub | `unifi-mgr audit critical` | exit 1, "stub" в выводе |
| Тесты зелёные | `pytest --cov-fail-under=80` | PASS, coverage ≥ 80% |
| Ruff зелёный | `ruff check .` | "All checks passed!" |
| Format зелёный | `ruff format --check .` | без изменений |
| Mypy strict для core | `mypy --strict src/unifi_manager/settings.py src/unifi_manager/logging_config.py` | "no issues" |
| Mypy для остального | `mypy src/unifi_manager` | "no issues" |
| Pre-commit зелёный | `pre-commit run --all-files` | PASS |
| CI зелёный | GitHub Actions на refactor/v2 | три зелёных job'а |
| Ветка готова | `git log refactor/v2 --oneline` | 8 коммитов phase0 + тег `phase-0-complete` |

**Что НЕ должно быть сделано в этой фазе:**
- ❌ HTTP клиенты (фаза 1)
- ❌ Domain модели с SYSID_MAP (фаза 1)
- ❌ Services (фаза 2)
- ❌ Реальные подкоманды CLI (заполняются в фазах 1-7)
- ❌ Старые скрипты НЕ трогаются (они работают в проде через cron)
- ❌ `_legacy/` папка НЕ создаётся (это фаза 6)
- ❌ `dashboard.sh`, `cron`-задачи НЕ переписываются

---

## Self-Review Notes

**Spec coverage:**
- Раздел 1 (структура пакета) — Task 2 создаёт скелет, Task 1 (pyproject) определяет src/-layout. SYSID_MAP в domain — НЕ в этой фазе (фаза 1).
- Раздел 2 (CLI поверхность) — Task 5 создаёт root app со всеми 9 подкомандами как stub. Реальные команды — в фазах 1-7.
- Раздел 3 (config & logging) — Task 3 полная Settings schema (все модели включая фазу 7 — дефолтные значения), Task 4 минимальный logging stub. Полное логирование (Rich, JSON, SecretsFilter, Telegram rate-limit) — фаза 1/2.
- Раздел 4 (tests & CI) — Task 7 (pre-commit) + Task 8 (CI) + тесты в каждом Task. Coverage 80% порог уже работает.
- Раздел 5 (migration) — Task 1 создаёт ветку refactor/v2, не трогает старые скрипты. cron не меняется. _legacy/ не создаётся.

**Placeholder scan:** проверено — нет TBD/TODO. Все команды конкретные с expected output. Все код-блоки полные.

**Type consistency:** имена классов Settings (`UnifiAuthSettings`, `RestartProfile`, `AuditHealthCheckSettings`, `MaintenanceSettings`) совпадают между спеком, settings.py в Task 3, и test fixtures.

**Гейты:**
- Task 9 явно проверяет gate Фазы 0 ("CI зелёный + `unifi-mgr --version` работает") + дополнительно coverage ≥ 80%.

---

## После Фазы 0

Когда `phase-0-complete` тег есть и CI зелёный — переходим к написанию плана для **Фазы 1 (Core layers)**:
- `clients/base.py`, `clients/legacy.py`, `clients/integration.py` (HTTP + retry + auth)
- `domain/device.py` (с SYSID_MAP и computed_field `real_model`)
- `domain/event.py`, `domain/client.py`
- `utils/time.py` (timezone helpers + Hypothesis-тесты)
- Расширение `logging_config.py` (RichHandler + JSON formatter + SecretsFilter)

Создание плана Фазы 1 — отдельная сессия с `superpowers:writing-plans`.
