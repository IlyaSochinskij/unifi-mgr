# Phase 1 — Core Layers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать core слои (HTTP клиенты для двух API UniFi, типизированные domain модели, time utils с Hypothesis) — фундамент на котором Phase 2+ построит services и CLI команды.

**Architecture:** Слоистая структура из дизайн-спека: `clients/` (HTTP + retry + auth) → `domain/` (Pydantic models со строгой валидацией + SYSID_MAP) → `utils/time.py` (UTC-aware helpers). Никакой бизнес-логики, никакого CLI — только переиспользуемые примитивы. Расширение `logging_config.py` финальной формой (RichHandler + JSON formatter + SecretsFilter).

**Tech Stack:** Python 3.12, requests, pydantic v2, rich, responses (HTTP mock), freezegun, hypothesis (property-based).

**Гейт готовности:** `mypy --strict` зелёный для `clients/`, `domain/`, `services/`, `integrations/`, `diagnostics/`, `settings.py`, `logging_config.py`. Coverage 90%+ для core слоёв. Все тесты зелёные.

**Ветка работы:** `worktree-refactor+v2` (продолжение с Phase 0).

**Связанный спек:** [docs/superpowers/specs/2026-05-16-unifi-manager-refactor-design.md](../specs/2026-05-16-unifi-manager-refactor-design.md)

**Предыдущая фаза:** [phase-0-foundation.md](2026-05-16-phase-0-foundation.md) — Foundation, tag `phase-0-complete`

**Platform notes:** Windows worktree. Use `.venv/Scripts/python`, `.venv/Scripts/pytest`. На Linux заменить `Scripts/` на `bin/`.

---

## File Structure

### Создаются (новые):

```
src/unifi_manager/
├── clients/
│   ├── exceptions.py        # UnifiAuthError, UnifiAPIError, UnifiTimeoutError
│   ├── base.py              # BaseUnifiClient — session, retry, GET/POST с timeout/SSL
│   ├── legacy.py            # LegacyClient(BaseUnifiClient) — login+CSRF, /proxy/network/api/...
│   └── integration.py       # IntegrationClient(BaseUnifiClient) — X-API-KEY, /proxy/network/integration/...
│
├── domain/
│   ├── device.py            # Device base, AccessPoint (с SYSID_MAP + real_model), Switch
│   ├── event.py             # EventKey enum + ApEvent
│   └── client.py            # WirelessClient
│
└── utils/
    └── time.py              # parse_unifi_utc, is_within_window, now_utc
```

### Расширяется:

```
src/unifi_manager/
└── logging_config.py        # +RichHandler, +JSON formatter, +SecretsFilter (заменяет minimal stub)
```

### Тесты (новые):

```
tests/
├── conftest.py              # +фикстуры: mock_legacy_client, mock_integration_client, sample_device_dict
├── fixtures/
│   ├── stat_device_response.json        # реальный ответ Legacy /stat/device (anonymized)
│   ├── integration_devices.json         # реальный ответ Integration /devices
│   └── ap_event_sample.json             # пример EVT_AP_Lost_Contact
│
└── unit/
    ├── test_clients/
    │   ├── test_exceptions.py
    │   ├── test_base.py                 # mock HTTP через responses, retry, timeout, SSL
    │   ├── test_legacy.py               # CSRF flow, login, GET/POST endpoints
    │   └── test_integration.py          # X-API-KEY, endpoints structure
    │
    ├── test_domain/
    │   ├── __init__.py
    │   ├── test_device.py               # SYSID_MAP, AccessPoint.real_model, extra='allow', ValidationError fallback
    │   ├── test_event.py                # EventKey enum, ApEvent parsing
    │   └── test_client.py               # WirelessClient parsing
    │
    ├── test_utils/
    │   ├── __init__.py
    │   └── test_time.py                 # parse_unifi_utc, is_within_window, Hypothesis property-based
    │
    └── test_logging.py                  # ОБНОВЛЁН: + RichHandler, + JSON formatter, + SecretsFilter
```

### НЕ трогаются:

- `src/unifi_manager/cli/` — Phase 4
- `src/unifi_manager/services/` — Phase 2
- `src/unifi_manager/integrations/` — Phase 2
- `src/unifi_manager/diagnostics/` — Phase 4
- Legacy скрипты в корне репы
- `pyproject.toml` (кроме потенциальных правок exclude / per-file-ignores при необходимости)
- `.github/workflows/ci.yml` (mypy --strict список расширяется в Task 9)

---

## Common patterns (read before starting)

**TDD цикл (как в Phase 0):**
1. Write failing test → 2. Run, see fail → 3. Implement → 4. Run, see pass → 5. Commit

**Test invocation:** `.venv/Scripts/pytest <path> -v --no-cov` (быстро, без coverage). Полный suite в конце task: `.venv/Scripts/pytest --no-cov`.

**Coverage check:** `.venv/Scripts/pytest --cov=unifi_manager --cov-report=term-missing --cov-fail-under=90 src/unifi_manager/<layer>` (только при необходимости).

**Mypy strict:** `.venv/Scripts/mypy --strict src/unifi_manager/<file>` после каждой задачи в core.

**Ruff:** `.venv/Scripts/ruff check src/unifi_manager/<file> tests/unit/<file>` после каждой задачи. Если cyrillic в docstrings/help — добавить per-file-ignore в `pyproject.toml`.

**Commit message format:** `phase1: <short description>`. Все commits на ветке `worktree-refactor+v2`.

**Existing decisions from Phase 0 to honor:**
- `pyproject.toml` `addopts` НЕ содержит `--cov*` (используется в CI отдельно).
- pre-commit включает `ruff --fix`, может auto-format ваши новые файлы — это OK.
- Cyrillic в production коде → per-file-ignore `RUF001`, `RUF002`.
- Tests маркируются `@pytest.mark.fast`.
- При создании fixture-методов в conftest, `tmp_*` фикстуры используют `yield` если есть teardown через monkeypatch.

---

## Task 1: Exceptions

**Files:**
- Create: `src/unifi_manager/clients/exceptions.py`
- Create: `tests/unit/test_clients/__init__.py` (empty)
- Create: `tests/unit/test_clients/test_exceptions.py`

**Goal:** Иерархия исключений для всех HTTP клиентов. Используется в Tasks 2-4 + всеми Phase 2 services.

- [ ] **Step 1.1: Write failing test**

`tests/unit/test_clients/__init__.py` — empty (create).

`tests/unit/test_clients/test_exceptions.py`:

```python
"""Тесты для unifi_manager.clients.exceptions."""
import pytest


@pytest.mark.fast
def test_unifi_error_is_base() -> None:
    from unifi_manager.clients.exceptions import UnifiError
    assert issubclass(UnifiError, Exception)


@pytest.mark.fast
def test_unifi_auth_error_inherits_unifi_error() -> None:
    from unifi_manager.clients.exceptions import UnifiAuthError, UnifiError
    assert issubclass(UnifiAuthError, UnifiError)


@pytest.mark.fast
def test_unifi_api_error_inherits_unifi_error() -> None:
    from unifi_manager.clients.exceptions import UnifiAPIError, UnifiError
    assert issubclass(UnifiAPIError, UnifiError)


@pytest.mark.fast
def test_unifi_timeout_error_inherits_unifi_error() -> None:
    from unifi_manager.clients.exceptions import UnifiTimeoutError, UnifiError
    assert issubclass(UnifiTimeoutError, UnifiError)


@pytest.mark.fast
def test_unifi_api_error_carries_status_code() -> None:
    """UnifiAPIError содержит status_code и body для отладки."""
    from unifi_manager.clients.exceptions import UnifiAPIError

    err = UnifiAPIError("Server error", status_code=500, body='{"error": "internal"}')
    assert err.status_code == 500
    assert err.body == '{"error": "internal"}'
    assert "Server error" in str(err)


@pytest.mark.fast
def test_unifi_api_error_optional_fields() -> None:
    """status_code и body — optional (default None)."""
    from unifi_manager.clients.exceptions import UnifiAPIError

    err = UnifiAPIError("Just message")
    assert err.status_code is None
    assert err.body is None


@pytest.mark.fast
def test_unifi_auth_error_raisable() -> None:
    from unifi_manager.clients.exceptions import UnifiAuthError

    with pytest.raises(UnifiAuthError, match="bad password"):
        raise UnifiAuthError("bad password")
```

- [ ] **Step 1.2: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_clients/test_exceptions.py -v --no-cov
```
Expected: ModuleNotFoundError.

- [ ] **Step 1.3: Implement**

`src/unifi_manager/clients/exceptions.py`:

```python
"""Исключения HTTP-клиентов UniFi.

Все клиентские ошибки наследуются от UnifiError для удобного catch-all.
"""
from __future__ import annotations


class UnifiError(Exception):
    """Базовое исключение для всех ошибок взаимодействия с UniFi API."""


class UnifiAuthError(UnifiError):
    """Ошибка авторизации: неверные credentials, истёкшая сессия, отсутствие CSRF."""


class UnifiAPIError(UnifiError):
    """Ошибка ответа API: 4xx/5xx, неожиданный формат, rc != ok.

    Сохраняет status_code и тело ответа для post-mortem отладки.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class UnifiTimeoutError(UnifiError):
    """Сетевой таймаут (после исчерпания retry попыток)."""
```

- [ ] **Step 1.4: Run, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_clients/test_exceptions.py -v --no-cov
```
Expected: 7/7 PASS.

- [ ] **Step 1.5: Mypy + ruff**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/clients/exceptions.py
.venv/Scripts/ruff check src/unifi_manager/clients/exceptions.py tests/unit/test_clients/
```
Expected: оба зелёные.

- [ ] **Step 1.6: Commit**

```bash
git add src/unifi_manager/clients/exceptions.py tests/unit/test_clients/__init__.py tests/unit/test_clients/test_exceptions.py
git commit -m "phase1: clients/exceptions.py — UnifiError hierarchy"
```

---

## Task 2: Time utils (with Hypothesis)

**Files:**
- Create: `src/unifi_manager/utils/time.py`
- Create: `tests/unit/test_utils/__init__.py` (empty)
- Create: `tests/unit/test_utils/test_time.py`

**Goal:** UTC-aware helpers — фикс **критического timezone-бага** из аудита. Используется в Phase 2-3 для cooldown логики, event window сравнений.

- [ ] **Step 2.1: Write failing tests**

`tests/unit/test_utils/__init__.py` — empty.

`tests/unit/test_utils/test_time.py`:

```python
"""Тесты для unifi_manager.utils.time.

КРИТИЧНО: эти функции — фикс timezone-бага из аудита 2026-05-16.
UniFi API возвращает время в UTC ("2026-05-15T22:00:00Z"), а старый код
сравнивал с datetime.now() (local time без TZ). На сервере в UTC+3 это
давало сдвиг окна на 3 часа.
"""
from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time
from hypothesis import given
from hypothesis import strategies as st


@pytest.mark.fast
def test_parse_unifi_utc_basic() -> None:
    from unifi_manager.utils.time import parse_unifi_utc

    result = parse_unifi_utc("2026-05-15T22:00:00Z")
    assert result == datetime(2026, 5, 15, 22, 0, 0, tzinfo=UTC)


@pytest.mark.fast
def test_parse_unifi_utc_result_is_timezone_aware() -> None:
    """Результат ВСЕГДА tz-aware (главный фикс бага)."""
    from unifi_manager.utils.time import parse_unifi_utc

    result = parse_unifi_utc("2026-05-15T22:00:00Z")
    assert result.tzinfo is not None
    assert result.utcoffset() == timedelta(0)


@pytest.mark.fast
def test_parse_unifi_utc_invalid_raises() -> None:
    from unifi_manager.utils.time import parse_unifi_utc

    with pytest.raises(ValueError):
        parse_unifi_utc("not-a-date")


@pytest.mark.fast
@pytest.mark.parametrize("input_str", ["", "  ", None])
def test_parse_unifi_utc_empty_raises(input_str: str | None) -> None:
    from unifi_manager.utils.time import parse_unifi_utc

    with pytest.raises((ValueError, TypeError)):
        parse_unifi_utc(input_str)  # type: ignore[arg-type]


@pytest.mark.fast
def test_now_utc_returns_tz_aware() -> None:
    from unifi_manager.utils.time import now_utc

    n = now_utc()
    assert n.tzinfo is not None
    assert n.utcoffset() == timedelta(0)


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00", tz_offset=3)
def test_now_utc_returns_utc_not_local() -> None:
    """now_utc() должна вернуть UTC даже когда системные часы в UTC+3."""
    from unifi_manager.utils.time import now_utc

    n = now_utc()
    # freeze_time замораживает на 2026-05-16 10:00:00 *local*, system offset +3
    # → UTC = 2026-05-16 07:00:00
    assert n == datetime(2026, 5, 16, 7, 0, 0, tzinfo=UTC)


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00", tz_offset=3)
def test_is_within_window_event_within() -> None:
    """Событие за 1 час до — в окне 2 часа."""
    from unifi_manager.utils.time import is_within_window, parse_unifi_utc

    # local 10:00 = UTC 07:00. Событие 1 час назад в UTC = 06:00 → "2026-05-16T06:00:00Z"
    event_ts = parse_unifi_utc("2026-05-16T06:00:00Z")
    assert is_within_window(event_ts, hours=2) is True


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00", tz_offset=3)
def test_is_within_window_event_outside() -> None:
    from unifi_manager.utils.time import is_within_window, parse_unifi_utc

    # Событие 3 часа назад в UTC = 04:00 → за окном 2 часов
    event_ts = parse_unifi_utc("2026-05-16T04:00:00Z")
    assert is_within_window(event_ts, hours=2) is False


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00", tz_offset=3)
def test_is_within_window_old_24h_audit_case() -> None:
    """Прямой тест воспроизводящий audit-баг.

    Старый код: cutoff = datetime.now() - timedelta(hours=24)
    + ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ")
    + if ts > cutoff (naive vs naive с разными зонами)

    Новая логика должна правильно работать с UTC.
    Сервер локально 10:00 (UTC+3) = UTC 07:00.
    Cutoff 24 часа назад в UTC = вчера 07:00.
    Событие в UTC 08:00 вчера (за 23 часа до сейчас) — должно быть В окне.
    """
    from unifi_manager.utils.time import is_within_window, parse_unifi_utc

    event_ts = parse_unifi_utc("2026-05-15T08:00:00Z")
    assert is_within_window(event_ts, hours=24) is True


@pytest.mark.fast
def test_is_within_window_rejects_naive_datetime() -> None:
    """is_within_window требует tz-aware datetime — naive должен падать."""
    from unifi_manager.utils.time import is_within_window

    naive = datetime(2026, 5, 16, 10, 0, 0)  # без tzinfo
    with pytest.raises(ValueError, match="tz-aware"):
        is_within_window(naive, hours=2)


# === Hypothesis property-based tests ===

@pytest.mark.fast
@given(
    year=st.integers(min_value=2020, max_value=2030),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),
    hour=st.integers(min_value=0, max_value=23),
    minute=st.integers(min_value=0, max_value=59),
    second=st.integers(min_value=0, max_value=59),
)
def test_parse_unifi_utc_roundtrip(
    year: int, month: int, day: int, hour: int, minute: int, second: int
) -> None:
    """parse_unifi_utc(formatted) == datetime(...) для любого валидного UTC."""
    from unifi_manager.utils.time import parse_unifi_utc

    ts_str = f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}Z"
    result = parse_unifi_utc(ts_str)
    expected = datetime(year, month, day, hour, minute, second, tzinfo=UTC)
    assert result == expected


@pytest.mark.fast
@given(
    hours=st.integers(min_value=1, max_value=1000),
    offset_hours=st.integers(min_value=-12, max_value=12),
)
def test_is_within_window_monotonic(hours: int, offset_hours: int) -> None:
    """Если событие в окне X часов, то и в окне X+1 часов тоже.

    Property: монотонность окна — больше окно ⇒ больше включающихся событий.
    """
    from unifi_manager.utils.time import is_within_window, now_utc

    event_ts = now_utc() - timedelta(hours=hours - offset_hours)
    if is_within_window(event_ts, hours=hours):
        assert is_within_window(event_ts, hours=hours + 1)
```

- [ ] **Step 2.2: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_utils/test_time.py -v --no-cov
```
Expected: ModuleNotFoundError.

- [ ] **Step 2.3: Implement**

`src/unifi_manager/utils/time.py`:

```python
"""Timezone-aware time utilities.

КРИТИЧНО: фикс timezone-бага из аудита.
Старый код сравнивал tz-naive datetime.now() с UTC временем UniFi API,
что на сервере в non-UTC timezone (например UTC+3) давало сдвиг окна на соответствующее количество часов.

Все функции здесь возвращают и работают с tz-aware datetime в UTC.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta


def parse_unifi_utc(ts_str: str) -> datetime:
    """Парсит timestamp в UniFi-формате ('2026-05-15T22:00:00Z') в tz-aware UTC datetime.

    Args:
        ts_str: ISO-подобная строка, оканчивающаяся на 'Z' (UTC marker).

    Raises:
        ValueError: если строка пустая, не соответствует формату или некорректна.
        TypeError: если передан не str.
    """
    if not isinstance(ts_str, str):
        raise TypeError(f"expected str, got {type(ts_str).__name__}")
    if not ts_str.strip():
        raise ValueError("empty timestamp string")
    # 'Z' → '+00:00' для fromisoformat
    normalized = ts_str.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def now_utc() -> datetime:
    """Текущее время в UTC (tz-aware).

    В отличие от datetime.now() (local), всегда возвращает UTC.
    """
    return datetime.now(UTC)


def is_within_window(event_ts: datetime, *, hours: float) -> bool:
    """True если событие произошло в последние `hours` часов от now_utc().

    Args:
        event_ts: tz-aware datetime события (обычно из parse_unifi_utc).
        hours: размер окна в часах (положительное число).

    Raises:
        ValueError: если event_ts naive (нет tzinfo) — нельзя сравнивать
                    с UTC безопасно.
    """
    if event_ts.tzinfo is None:
        raise ValueError(
            "event_ts must be tz-aware datetime (parsed via parse_unifi_utc)"
        )
    cutoff = now_utc() - timedelta(hours=hours)
    return event_ts > cutoff
```

- [ ] **Step 2.4: Run, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_utils/test_time.py -v --no-cov
```
Expected: all PASS (12+ regular tests + 2 Hypothesis tests, каждый ~50-100 examples).

- [ ] **Step 2.5: Mypy + ruff**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/utils/time.py
.venv/Scripts/ruff check src/unifi_manager/utils/time.py tests/unit/test_utils/
```
Expected: оба зелёные. Если ruff требует RUF002 (Cyrillic) — добавить в `pyproject.toml` per-file-ignore для `src/unifi_manager/utils/time.py`.

- [ ] **Step 2.6: Coverage check**

```bash
.venv/Scripts/pytest --cov=unifi_manager.utils.time --cov-report=term-missing tests/unit/test_utils/
```
Expected: **100%** на utils/time.py (это критичный bug-fix модуль).

- [ ] **Step 2.7: Commit**

```bash
git add src/unifi_manager/utils/time.py tests/unit/test_utils/
git commit -m "phase1: utils/time.py — UTC-aware helpers with Hypothesis (fixes audit timezone bug)"
```

---

## Task 3: Domain — Device, AccessPoint (SYSID_MAP), Switch

**Files:**
- Create: `src/unifi_manager/domain/device.py`
- Create: `tests/unit/test_domain/__init__.py` (empty)
- Create: `tests/unit/test_domain/test_device.py`
- Create: `tests/fixtures/stat_device_response.json` (anonymized sample)

**Goal:** Pydantic-модели для устройств. Главная фича — `SYSID_MAP` + `AccessPoint.real_model` computed_field (переносим из `infra/external_repos/.../diagnostics/infra_deep_v2.py`).

- [ ] **Step 3.1: Create test fixture**

`tests/fixtures/stat_device_response.json` — anonymized sample реального ответа `/stat/device` UniFi Legacy API. Минимум 3 устройства: 1 AP с известным sysid, 1 AP с неизвестным sysid, 1 switch.

```json
{
  "meta": {"rc": "ok"},
  "data": [
    {
      "_id": "device-uuid-1",
      "mac": "aa:bb:cc:dd:ee:01",
      "name": "Restoran",
      "model": "U7IW",
      "sysid": 58759,
      "state": 1,
      "type": "uap",
      "last_seen": 1747397800,
      "uplink": {
        "uplink_mac": "aa:bb:cc:dd:ee:99",
        "uplink_remote_port": 5
      }
    },
    {
      "_id": "device-uuid-2",
      "mac": "aa:bb:cc:dd:ee:02",
      "name": "Office AP 1",
      "model": "U7PG2",
      "sysid": 999999,
      "state": 0,
      "type": "uap",
      "last_seen": 1747390000
    },
    {
      "_id": "device-uuid-3",
      "mac": "aa:bb:cc:dd:ee:99",
      "name": "Core Switch",
      "model": "US-24-250W",
      "sysid": 12345,
      "state": 1,
      "type": "usw",
      "last_seen": 1747397900,
      "general_temperature": 45,
      "port_table": [
        {"port_idx": 1, "rx_errors": 0, "tx_errors": 0},
        {"port_idx": 5, "rx_errors": 12, "tx_errors": 0}
      ]
    }
  ]
}
```

- [ ] **Step 3.2: Write failing tests**

`tests/unit/test_domain/__init__.py` — empty.

`tests/unit/test_domain/test_device.py`:

```python
"""Тесты для unifi_manager.domain.device."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError


@pytest.mark.fast
def test_sysid_map_contains_known_models() -> None:
    """SYSID_MAP — константа с маппингом sysid → реальное имя модели.

    Перенесена из infra/external_repos/.../diagnostics/infra_deep_v2.py
    где была единственной точкой её определения.
    """
    from unifi_manager.domain.device import SYSID_MAP

    assert SYSID_MAP[58759] == "UAP-AC-IW"
    assert SYSID_MAP[58679] == "UAP-AC-Pro"
    assert SYSID_MAP[58727] == "UAP-AC-M"
    assert SYSID_MAP[58711] == "UAP-AC-M-Pro"


@pytest.mark.fast
def test_access_point_basic_parse() -> None:
    from unifi_manager.domain.device import AccessPoint

    ap = AccessPoint.model_validate({
        "mac": "aa:bb:cc:dd:ee:01",
        "model": "U7IW",
        "sysid": 58759,
    })
    assert ap.mac == "aa:bb:cc:dd:ee:01"
    assert ap.reported_model == "U7IW"
    assert ap.sysid == 58759


@pytest.mark.fast
def test_access_point_real_model_via_sysid() -> None:
    """sysid известен → real_model = маппинг, не reported_model."""
    from unifi_manager.domain.device import AccessPoint

    ap = AccessPoint.model_validate({
        "mac": "aa:bb:cc:dd:ee:01",
        "model": "U7IW",  # UniFi сообщает неправильно
        "sysid": 58759,
    })
    assert ap.reported_model == "U7IW"
    assert ap.real_model == "UAP-AC-IW"  # реальная модель из SYSID_MAP


@pytest.mark.fast
def test_access_point_real_model_fallback_to_reported() -> None:
    """sysid отсутствует или неизвестен → real_model = reported_model."""
    from unifi_manager.domain.device import AccessPoint

    ap = AccessPoint.model_validate({
        "mac": "aa:bb:cc:dd:ee:02",
        "model": "U7PG2",
        "sysid": 999999,  # неизвестный
    })
    assert ap.real_model == "U7PG2"

    ap2 = AccessPoint.model_validate({
        "mac": "aa:bb:cc:dd:ee:03",
        "model": "U6-LR",
        # sysid отсутствует
    })
    assert ap2.real_model == "U6-LR"


@pytest.mark.fast
def test_access_point_extra_fields_preserved() -> None:
    """extra='allow' → новые поля UniFi сохраняются в model_extra без потерь."""
    from unifi_manager.domain.device import AccessPoint

    ap = AccessPoint.model_validate({
        "mac": "aa:bb:cc:dd:ee:01",
        "model": "U7IW",
        "sysid": 58759,
        "future_field_from_new_unifi_version": {"x": 42},
        "another_unknown": "value",
    })
    assert ap.model_extra is not None
    assert ap.model_extra["future_field_from_new_unifi_version"] == {"x": 42}
    assert ap.model_extra["another_unknown"] == "value"


@pytest.mark.fast
def test_access_point_missing_mac_raises() -> None:
    """mac — обязательное поле."""
    from unifi_manager.domain.device import AccessPoint

    with pytest.raises(ValidationError) as exc_info:
        AccessPoint.model_validate({"model": "U7IW"})
    assert "mac" in str(exc_info.value)


@pytest.mark.fast
def test_access_point_uplink_optional() -> None:
    from unifi_manager.domain.device import AccessPoint

    ap = AccessPoint.model_validate({
        "mac": "aa:bb:cc:dd:ee:01",
        "model": "U7IW",
    })
    assert ap.uplink is None


@pytest.mark.fast
def test_access_point_uplink_parsed() -> None:
    from unifi_manager.domain.device import AccessPoint

    ap = AccessPoint.model_validate({
        "mac": "aa:bb:cc:dd:ee:01",
        "model": "U7IW",
        "uplink": {
            "uplink_mac": "aa:bb:cc:dd:ee:99",
            "uplink_remote_port": 5,
        },
    })
    assert ap.uplink is not None
    assert ap.uplink.uplink_mac == "aa:bb:cc:dd:ee:99"
    assert ap.uplink.uplink_remote_port == 5


@pytest.mark.fast
def test_switch_basic_parse() -> None:
    from unifi_manager.domain.device import Switch

    sw = Switch.model_validate({
        "mac": "aa:bb:cc:dd:ee:99",
        "model": "US-24-250W",
        "name": "Core Switch",
        "general_temperature": 45,
        "port_table": [
            {"port_idx": 1, "rx_errors": 0, "tx_errors": 0},
        ],
    })
    assert sw.mac == "aa:bb:cc:dd:ee:99"
    assert sw.general_temperature == 45
    assert len(sw.port_table) == 1
    assert sw.port_table[0].port_idx == 1


@pytest.mark.fast
def test_full_response_parses(fixtures_dir: Path) -> None:
    """Реальный ответ /stat/device парсится без ошибок."""
    from unifi_manager.domain.device import AccessPoint, Switch

    raw = json.loads((fixtures_dir / "stat_device_response.json").read_text(encoding="utf-8"))
    devices = raw["data"]

    # Первое устройство — AP с известным sysid
    ap1 = AccessPoint.model_validate(devices[0])
    assert ap1.real_model == "UAP-AC-IW"

    # Второе — AP с неизвестным sysid
    ap2 = AccessPoint.model_validate(devices[1])
    assert ap2.real_model == "U7PG2"  # fallback

    # Третье — switch
    sw = Switch.model_validate(devices[2])
    assert sw.general_temperature == 45
    assert sw.port_table[1].rx_errors == 12
```

- [ ] **Step 3.3: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_domain/test_device.py -v --no-cov
```
Expected: ModuleNotFoundError.

- [ ] **Step 3.4: Implement**

`src/unifi_manager/domain/device.py`:

```python
"""Доменные модели сетевых устройств UniFi.

ВАЖНО: SYSID_MAP перенесён из infra/external_repos/.../diagnostics/infra_deep_v2.py
(где он был единственной точкой определения, не в основной репе).
UniFi API для некоторых старых моделей возвращает в поле "model" короткое
неправильное имя (U7IW вместо UAP-AC-IW). real_model даёт каноническое имя.
"""
from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, computed_field


SYSID_MAP: Final[dict[int, str]] = {
    58759: "UAP-AC-IW",
    58679: "UAP-AC-Pro",
    58727: "UAP-AC-M",
    58711: "UAP-AC-M-Pro",
}


class UplinkInfo(BaseModel):
    """Информация об uplink-подключении устройства к upstream-свитчу."""

    model_config = ConfigDict(extra="allow")

    uplink_mac: str | None = None
    uplink_remote_port: int | None = None


class Device(BaseModel):
    """Базовая модель сетевого устройства UniFi (общее поле для AP и Switch)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    mac: str
    name: str | None = None
    reported_model: str = Field(alias="model")
    sysid: int | None = None
    state: int = 0  # 1=online, 0=offline, 10=connection_interrupted, etc.
    type: str | None = None  # "uap" | "usw" | "ugw" | ...
    last_seen: int | None = None  # unix timestamp
    device_id: str | None = Field(default=None, alias="_id")


class AccessPoint(Device):
    """Wi-Fi точка доступа с обогащением real_model через SYSID_MAP."""

    uplink: UplinkInfo | None = None
    radio_table: list[dict[str, Any]] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def real_model(self) -> str:
        """Каноническое имя модели — из SYSID_MAP по sysid, fallback на reported_model."""
        if self.sysid is not None and self.sysid in SYSID_MAP:
            return SYSID_MAP[self.sysid]
        return self.reported_model


class SwitchPort(BaseModel):
    """Порт коммутатора с метриками ошибок (для Phase 7 port-errors monitoring)."""

    model_config = ConfigDict(extra="allow")

    port_idx: int
    rx_errors: int = 0
    tx_errors: int = 0
    rx_dropped: int = 0
    tx_dropped: int = 0


class Switch(Device):
    """Коммутатор UniFi с port_table и метриками температуры/PoE."""

    general_temperature: int | None = None
    port_table: list[SwitchPort] = Field(default_factory=list)
```

- [ ] **Step 3.5: Run, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_domain/test_device.py -v --no-cov
```
Expected: all PASS (10+ tests).

- [ ] **Step 3.6: Mypy + ruff + coverage**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/domain/device.py
.venv/Scripts/ruff check src/unifi_manager/domain/device.py tests/unit/test_domain/
.venv/Scripts/pytest --cov=unifi_manager.domain.device --cov-report=term-missing tests/unit/test_domain/test_device.py
```
Expected: mypy clean, ruff clean, coverage 95%+.

- [ ] **Step 3.7: Commit**

```bash
git add src/unifi_manager/domain/device.py tests/unit/test_domain/ tests/fixtures/stat_device_response.json
git commit -m "phase1: domain/device.py — Device/AccessPoint/Switch with SYSID_MAP"
```

---

## Task 4: Domain — Event + WirelessClient

**Files:**
- Create: `src/unifi_manager/domain/event.py`
- Create: `src/unifi_manager/domain/client.py`
- Create: `tests/unit/test_domain/test_event.py`
- Create: `tests/unit/test_domain/test_client.py`
- Create: `tests/fixtures/ap_event_sample.json`

**Goal:** Простые модели для событий AP (используется в Phase 2 restart-логике) и беспроводных клиентов (Phase 2 export).

- [ ] **Step 4.1: Create test fixture**

`tests/fixtures/ap_event_sample.json`:

```json
{
  "meta": {"rc": "ok"},
  "data": [
    {
      "_id": "evt-uuid-1",
      "key": "EVT_AP_Lost_Contact",
      "datetime": "2026-05-15T22:00:00Z",
      "ap": "aa:bb:cc:dd:ee:01",
      "ap_name": "Restoran",
      "msg": "AP[aa:bb:cc:dd:ee:01] was disconnected"
    },
    {
      "_id": "evt-uuid-2",
      "key": "EVT_AP_Connected",
      "datetime": "2026-05-15T22:05:00Z",
      "ap": "aa:bb:cc:dd:ee:01",
      "ap_name": "Restoran"
    },
    {
      "_id": "evt-uuid-3",
      "key": "EVT_AP_Disconnected",
      "datetime": "2026-05-15T23:00:00Z",
      "ap": "aa:bb:cc:dd:ee:01"
    }
  ]
}
```

- [ ] **Step 4.2: Write failing tests for event**

`tests/unit/test_domain/test_event.py`:

```python
"""Тесты для unifi_manager.domain.event."""
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.mark.fast
def test_event_key_enum_values() -> None:
    from unifi_manager.domain.event import EventKey

    assert EventKey.AP_LOST_CONTACT.value == "EVT_AP_Lost_Contact"
    assert EventKey.AP_DISCONNECTED.value == "EVT_AP_Disconnected"
    assert EventKey.AP_CONNECTED.value == "EVT_AP_Connected"


@pytest.mark.fast
def test_ap_event_basic_parse() -> None:
    from unifi_manager.domain.event import ApEvent, EventKey

    evt = ApEvent.model_validate({
        "key": "EVT_AP_Lost_Contact",
        "datetime": "2026-05-15T22:00:00Z",
        "ap": "aa:bb:cc:dd:ee:01",
        "ap_name": "Restoran",
    })
    assert evt.key == EventKey.AP_LOST_CONTACT
    assert evt.timestamp == datetime(2026, 5, 15, 22, 0, 0, tzinfo=UTC)
    assert evt.ap_mac == "aa:bb:cc:dd:ee:01"
    assert evt.ap_name == "Restoran"


@pytest.mark.fast
def test_ap_event_timestamp_is_tz_aware() -> None:
    """ApEvent.timestamp всегда tz-aware (фикс audit-бага)."""
    from unifi_manager.domain.event import ApEvent

    evt = ApEvent.model_validate({
        "key": "EVT_AP_Lost_Contact",
        "datetime": "2026-05-15T22:00:00Z",
        "ap": "aa:bb:cc:dd:ee:01",
    })
    assert evt.timestamp.tzinfo is not None


@pytest.mark.fast
def test_ap_event_unknown_key_preserved_as_string() -> None:
    """Если UniFi выдаёт новый event key — не падаем, сохраняем raw строку."""
    from unifi_manager.domain.event import ApEvent

    evt = ApEvent.model_validate({
        "key": "EVT_SOME_NEW_EVENT",
        "datetime": "2026-05-15T22:00:00Z",
        "ap": "aa:bb:cc:dd:ee:01",
    })
    # key либо EventKey enum, либо raw string (Literal или str union)
    assert evt.key == "EVT_SOME_NEW_EVENT" or str(evt.key) == "EVT_SOME_NEW_EVENT"


@pytest.mark.fast
def test_ap_event_optional_ap_name() -> None:
    from unifi_manager.domain.event import ApEvent

    evt = ApEvent.model_validate({
        "key": "EVT_AP_Disconnected",
        "datetime": "2026-05-15T23:00:00Z",
        "ap": "aa:bb:cc:dd:ee:01",
    })
    assert evt.ap_name is None


@pytest.mark.fast
def test_full_event_response_parses(fixtures_dir: Path) -> None:
    from unifi_manager.domain.event import ApEvent

    raw = json.loads((fixtures_dir / "ap_event_sample.json").read_text(encoding="utf-8"))
    events = [ApEvent.model_validate(e) for e in raw["data"]]
    assert len(events) == 3
    assert events[0].ap_name == "Restoran"
    assert events[2].ap_name is None
```

- [ ] **Step 4.3: Implement event**

`src/unifi_manager/domain/event.py`:

```python
"""События AP UniFi.

Используется RestartService для анализа частоты EVT_AP_Lost_Contact
в окне 24 часов для решения о рестарте.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from unifi_manager.utils.time import parse_unifi_utc


class EventKey(StrEnum):
    """Известные ключи событий UniFi (расширяется при необходимости).

    Неизвестные ключи API сохраняются как raw строка (через str | EventKey union).
    """

    AP_LOST_CONTACT = "EVT_AP_Lost_Contact"
    AP_DISCONNECTED = "EVT_AP_Disconnected"
    AP_CONNECTED = "EVT_AP_Connected"


def _parse_event_key(v: str) -> EventKey | str:
    """Парсер: known key → EventKey enum, иначе raw string (forward compat)."""
    try:
        return EventKey(v)
    except ValueError:
        return v


def _parse_timestamp(v: str | datetime) -> datetime:
    """Парсер datetime: UniFi-формат 'YYYY-MM-DDTHH:MM:SSZ' → tz-aware UTC."""
    if isinstance(v, datetime):
        return v
    return parse_unifi_utc(v)


class ApEvent(BaseModel):
    """Событие AP из /stat/event."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    key: Annotated[EventKey | str, BeforeValidator(_parse_event_key)]
    timestamp: Annotated[datetime, BeforeValidator(_parse_timestamp)] = Field(alias="datetime")
    ap_mac: str = Field(alias="ap")
    ap_name: str | None = None
    msg: str | None = None
```

- [ ] **Step 4.4: Write failing tests for client**

`tests/unit/test_domain/test_client.py`:

```python
"""Тесты для unifi_manager.domain.client."""
import pytest


@pytest.mark.fast
def test_wireless_client_basic_parse() -> None:
    from unifi_manager.domain.client import WirelessClient

    c = WirelessClient.model_validate({
        "mac": "11:22:33:44:55:66",
        "hostname": "user-laptop",
        "ip": "10.3.0.42",
        "ap_mac": "aa:bb:cc:dd:ee:01",
        "signal": -55,
        "rx_bytes": 1024,
        "tx_bytes": 2048,
    })
    assert c.mac == "11:22:33:44:55:66"
    assert c.hostname == "user-laptop"
    assert c.ip == "10.3.0.42"
    assert c.signal == -55


@pytest.mark.fast
def test_wireless_client_minimal() -> None:
    """Только mac обязателен."""
    from unifi_manager.domain.client import WirelessClient

    c = WirelessClient.model_validate({"mac": "11:22:33:44:55:66"})
    assert c.mac == "11:22:33:44:55:66"
    assert c.hostname is None
    assert c.ip is None


@pytest.mark.fast
def test_wireless_client_extra_preserved() -> None:
    from unifi_manager.domain.client import WirelessClient

    c = WirelessClient.model_validate({
        "mac": "11:22:33:44:55:66",
        "new_unifi_field": "future-value",
    })
    assert c.model_extra is not None
    assert c.model_extra["new_unifi_field"] == "future-value"
```

- [ ] **Step 4.5: Implement client**

`src/unifi_manager/domain/client.py`:

```python
"""Беспроводные клиенты сети (используется export командой)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class WirelessClient(BaseModel):
    """Подключённый Wi-Fi клиент."""

    model_config = ConfigDict(extra="allow")

    mac: str
    hostname: str | None = None
    ip: str | None = None
    ap_mac: str | None = None  # MAC AP к которой подключён
    signal: int | None = None  # dBm, обычно отрицательный
    rx_bytes: int | None = None
    tx_bytes: int | None = None
    first_seen: int | None = None
    last_seen: int | None = None
```

- [ ] **Step 4.6: Run all domain tests**

```bash
.venv/Scripts/pytest tests/unit/test_domain/ -v --no-cov
```
Expected: all PASS.

- [ ] **Step 4.7: Mypy + ruff + coverage**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/domain/event.py src/unifi_manager/domain/client.py
.venv/Scripts/ruff check src/unifi_manager/domain/ tests/unit/test_domain/
.venv/Scripts/pytest --cov=unifi_manager.domain --cov-report=term-missing tests/unit/test_domain/
```
Expected: clean, coverage 90%+.

- [ ] **Step 4.8: Commit**

```bash
git add src/unifi_manager/domain/event.py src/unifi_manager/domain/client.py tests/unit/test_domain/test_event.py tests/unit/test_domain/test_client.py tests/fixtures/ap_event_sample.json
git commit -m "phase1: domain/event.py + domain/client.py with tz-aware timestamps"
```

---

## Task 5: BaseUnifiClient (HTTP + retry + SSL)

**Files:**
- Create: `src/unifi_manager/clients/base.py`
- Create: `tests/unit/test_clients/test_base.py`
- Modify: `tests/conftest.py` (add fixture for Settings with minimal unifi config)

**Goal:** Базовый HTTP-клиент с retry, timeout, SSL опциями. Используется LegacyClient и IntegrationClient.

- [ ] **Step 5.1: Extend conftest.py with settings fixture**

В `tests/conftest.py` добавить:

```python
import pytest

from unifi_manager.settings import Settings, UnifiAuthSettings


@pytest.fixture
def minimal_unifi_settings() -> Settings:
    """Settings с минимальным валидным unifi блоком — без секретов."""
    return Settings(
        unifi=UnifiAuthSettings(
            host="192.0.2.1",
            port=11443,
            site="site-1",
        )
    )
```

(Add import + fixture — оставить существующие fixtures intact.)

- [ ] **Step 5.2: Write failing tests**

`tests/unit/test_clients/test_base.py`:

```python
"""Тесты для unifi_manager.clients.base.BaseUnifiClient."""
import pytest
import responses

from unifi_manager.clients.exceptions import UnifiAPIError, UnifiTimeoutError
from unifi_manager.settings import Settings


@pytest.fixture
def client(minimal_unifi_settings: Settings) -> "BaseUnifiClient":  # noqa: F821
    from unifi_manager.clients.base import BaseUnifiClient
    return BaseUnifiClient(minimal_unifi_settings.unifi)


@pytest.mark.fast
def test_base_client_initializes_with_settings(minimal_unifi_settings: Settings) -> None:
    from unifi_manager.clients.base import BaseUnifiClient

    c = BaseUnifiClient(minimal_unifi_settings.unifi)
    assert c.base_url == "https://192.0.2.1:11443"


@pytest.mark.fast
def test_base_client_ssl_disabled_by_default(minimal_unifi_settings: Settings) -> None:
    """verify_ssl=False по умолчанию из settings."""
    from unifi_manager.clients.base import BaseUnifiClient

    c = BaseUnifiClient(minimal_unifi_settings.unifi)
    assert c.session.verify is False


@pytest.mark.fast
@responses.activate
def test_get_returns_json_on_success(client: "BaseUnifiClient") -> None:  # noqa: F821
    responses.get(
        "https://192.0.2.1:11443/some/path",
        json={"meta": {"rc": "ok"}, "data": [{"x": 1}]},
        status=200,
    )
    result = client.get_json("/some/path")
    assert result == {"meta": {"rc": "ok"}, "data": [{"x": 1}]}


@pytest.mark.fast
@responses.activate
def test_get_retries_on_5xx_then_succeeds(client: "BaseUnifiClient") -> None:  # noqa: F821
    """3 retries: первые 2 раза 503, третий — 200 OK."""
    url = "https://192.0.2.1:11443/some/path"
    responses.get(url, status=503)
    responses.get(url, status=503)
    responses.get(url, json={"data": []}, status=200)

    result = client.get_json("/some/path")
    assert result == {"data": []}
    assert len(responses.calls) == 3


@pytest.mark.fast
@responses.activate
def test_get_exhausts_retries_raises(client: "BaseUnifiClient") -> None:  # noqa: F821
    """После 3 ретраев 503 — UnifiAPIError со status=503."""
    url = "https://192.0.2.1:11443/some/path"
    for _ in range(3):
        responses.get(url, status=503, body="Service Unavailable")

    with pytest.raises(UnifiAPIError) as exc_info:
        client.get_json("/some/path")
    assert exc_info.value.status_code == 503
    assert len(responses.calls) == 3


@pytest.mark.fast
@responses.activate
def test_get_4xx_does_not_retry(client: "BaseUnifiClient") -> None:  # noqa: F821
    """401/403/404 — без retry, сразу UnifiAPIError."""
    responses.get(
        "https://192.0.2.1:11443/some/path",
        status=401,
        body="Unauthorized",
    )

    with pytest.raises(UnifiAPIError) as exc_info:
        client.get_json("/some/path")
    assert exc_info.value.status_code == 401
    assert len(responses.calls) == 1  # NO retry


@pytest.mark.fast
@responses.activate
def test_post_returns_json(client: "BaseUnifiClient") -> None:  # noqa: F821
    responses.post(
        "https://192.0.2.1:11443/cmd/devmgr",
        json={"meta": {"rc": "ok"}},
        status=200,
    )
    result = client.post_json("/cmd/devmgr", json_body={"cmd": "restart"})
    assert result == {"meta": {"rc": "ok"}}


@pytest.mark.fast
@responses.activate
def test_post_with_retry(client: "BaseUnifiClient") -> None:  # noqa: F821
    url = "https://192.0.2.1:11443/cmd/devmgr"
    responses.post(url, status=502)
    responses.post(url, json={"meta": {"rc": "ok"}}, status=200)

    result = client.post_json("/cmd/devmgr", json_body={"cmd": "restart"})
    assert result == {"meta": {"rc": "ok"}}
    assert len(responses.calls) == 2


@pytest.mark.fast
@responses.activate
def test_get_timeout_raises(client: "BaseUnifiClient") -> None:  # noqa: F821
    """Connection timeout → UnifiTimeoutError после retries."""
    import requests

    url = "https://192.0.2.1:11443/some/path"
    responses.get(url, body=requests.exceptions.ConnectTimeout("timed out"))
    responses.get(url, body=requests.exceptions.ConnectTimeout("timed out"))
    responses.get(url, body=requests.exceptions.ConnectTimeout("timed out"))

    with pytest.raises(UnifiTimeoutError):
        client.get_json("/some/path")
```

- [ ] **Step 5.3: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_clients/test_base.py -v --no-cov
```
Expected: ModuleNotFoundError.

- [ ] **Step 5.4: Implement**

`src/unifi_manager/clients/base.py`:

```python
"""BaseUnifiClient: HTTP-фундамент для Legacy и Integration клиентов.

Особенности:
- requests.Session для keep-alive
- retry на 5xx (3 попытки, без backoff в Phase 1 — добавим если понадобится)
- 4xx сразу raise (auth/perm/not-found)
- timeout по умолчанию 15 секунд
- SSL verify из settings (False / путь к pem)
- Логирование каждой неудачной попытки через logging
"""
from __future__ import annotations

import logging
from typing import Any

import requests
from requests import Response, Session
from requests.exceptions import RequestException, Timeout

from unifi_manager.clients.exceptions import UnifiAPIError, UnifiTimeoutError
from unifi_manager.settings import UnifiAuthSettings


DEFAULT_TIMEOUT = 15
DEFAULT_MAX_RETRIES = 3

_logger = logging.getLogger(__name__)


class BaseUnifiClient:
    """Базовый HTTP-клиент для UniFi контроллера.

    Подклассы (LegacyClient, IntegrationClient) добавляют свою аутентификацию
    и используют get_json/post_json для запросов.
    """

    def __init__(
        self,
        config: UnifiAuthSettings,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.config = config
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = f"https://{config.host}:{config.port}"
        self.session: Session = self._build_session()

    def _build_session(self) -> Session:
        session = requests.Session()
        # verify_ssl: False | Path
        session.verify = (
            False if self.config.verify_ssl is False else str(self.config.verify_ssl)
        )
        return session

    def get_json(self, path: str) -> dict[str, Any]:
        """GET с retry для 5xx и raise для 4xx/timeout."""
        return self._request("GET", path, json_body=None)

    def post_json(self, path: str, *, json_body: dict[str, Any]) -> dict[str, Any]:
        """POST с retry для 5xx и raise для 4xx/timeout."""
        return self._request("POST", path, json_body=json_body)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                resp: Response = self.session.request(
                    method=method,
                    url=url,
                    json=json_body,
                    timeout=self.timeout,
                )
            except Timeout as e:
                last_exc = e
                _logger.warning(
                    "Timeout on attempt %d/%d for %s %s",
                    attempt, self.max_retries, method, path,
                )
                continue
            except RequestException as e:
                last_exc = e
                _logger.warning(
                    "Request failed on attempt %d/%d for %s %s: %s",
                    attempt, self.max_retries, method, path, e,
                )
                continue

            # 4xx — не ретраим
            if 400 <= resp.status_code < 500:
                raise UnifiAPIError(
                    f"{method} {path} failed: {resp.status_code}",
                    status_code=resp.status_code,
                    body=resp.text[:500],
                )

            # 5xx — ретраим
            if resp.status_code >= 500:
                _logger.warning(
                    "Server error %d on attempt %d/%d for %s %s",
                    resp.status_code, attempt, self.max_retries, method, path,
                )
                if attempt == self.max_retries:
                    raise UnifiAPIError(
                        f"{method} {path} failed after {self.max_retries} attempts",
                        status_code=resp.status_code,
                        body=resp.text[:500],
                    )
                continue

            # 2xx/3xx — успех
            try:
                return resp.json()  # type: ignore[no-any-return]
            except ValueError as e:
                raise UnifiAPIError(
                    f"{method} {path} returned non-JSON: {e}",
                    status_code=resp.status_code,
                    body=resp.text[:500],
                ) from e

        # Все retry исчерпаны (только при Timeout/RequestException)
        if isinstance(last_exc, Timeout):
            raise UnifiTimeoutError(
                f"{method} {path} timed out after {self.max_retries} attempts"
            ) from last_exc
        raise UnifiAPIError(
            f"{method} {path} failed after {self.max_retries} attempts: {last_exc}"
        ) from last_exc
```

- [ ] **Step 5.5: Run tests**

```bash
.venv/Scripts/pytest tests/unit/test_clients/test_base.py -v --no-cov
```
Expected: all PASS.

- [ ] **Step 5.6: Mypy + ruff + coverage**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/clients/base.py
.venv/Scripts/ruff check src/unifi_manager/clients/base.py tests/unit/test_clients/test_base.py
.venv/Scripts/pytest --cov=unifi_manager.clients.base --cov-report=term-missing tests/unit/test_clients/test_base.py
```
Expected: clean, coverage 90%+.

- [ ] **Step 5.7: Commit**

```bash
git add src/unifi_manager/clients/base.py tests/unit/test_clients/test_base.py tests/conftest.py
git commit -m "phase1: clients/base.py — BaseUnifiClient with retry/timeout/SSL"
```

---

## Task 6: LegacyClient (session + CSRF)

**Files:**
- Create: `src/unifi_manager/clients/legacy.py`
- Create: `tests/unit/test_clients/test_legacy.py`

**Goal:** Legacy API клиент: `POST /api/auth/login` с логином+паролем, CSRF token из заголовков, endpoints `/proxy/network/api/s/<site>/...`. Используется большинством сервисов.

Reference: `_legacy/unifi_client.py:51-67` (login flow) и `_legacy/restart_restaurant_aps.py:34-50` (CSRF extraction).

- [ ] **Step 6.1: Write failing tests**

`tests/unit/test_clients/test_legacy.py`:

```python
"""Тесты для unifi_manager.clients.legacy.LegacyClient."""
import pytest
import responses
from pydantic import SecretStr

from unifi_manager.clients.exceptions import UnifiAuthError
from unifi_manager.settings import Settings, UnifiAuthSettings


@pytest.fixture
def legacy_settings() -> Settings:
    """Settings с username/password для login."""
    return Settings(
        unifi=UnifiAuthSettings(
            host="192.0.2.1",
            port=11443,
            site="site-1",
            username=SecretStr("unifi_user"),
            password=SecretStr("test-password"),
        )
    )


@pytest.mark.fast
@responses.activate
def test_login_success_extracts_csrf(legacy_settings: Settings) -> None:
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login",
        json={"meta": {"rc": "ok"}},
        status=200,
        headers={"X-Csrf-Token": "fake-csrf-token-abc123"},
    )

    client = LegacyClient(legacy_settings.unifi)
    assert client.login() is True
    assert client.session.headers.get("X-Csrf-Token") == "fake-csrf-token-abc123"


@pytest.mark.fast
@responses.activate
def test_login_success_without_csrf_header(legacy_settings: Settings) -> None:
    """Некоторые версии контроллера не возвращают CSRF — это OK, login успешен."""
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login",
        json={"meta": {"rc": "ok"}},
        status=200,
    )

    client = LegacyClient(legacy_settings.unifi)
    assert client.login() is True


@pytest.mark.fast
@responses.activate
def test_login_401_raises_auth_error(legacy_settings: Settings) -> None:
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login",
        json={"meta": {"rc": "error", "msg": "Invalid credentials"}},
        status=401,
    )

    client = LegacyClient(legacy_settings.unifi)
    with pytest.raises(UnifiAuthError, match="login failed"):
        client.login()


@pytest.mark.fast
@responses.activate
def test_login_sends_credentials(legacy_settings: Settings) -> None:
    """Тело запроса должно содержать username/password из SecretStr."""
    from unifi_manager.clients.legacy import LegacyClient

    responses.post(
        "https://192.0.2.1:11443/api/auth/login",
        json={"meta": {"rc": "ok"}},
        status=200,
    )

    client = LegacyClient(legacy_settings.unifi)
    client.login()

    sent_body = responses.calls[0].request.body
    assert b"unifi_user" in sent_body
    assert b"test-password" in sent_body


@pytest.mark.fast
def test_missing_credentials_raises(minimal_unifi_settings: Settings) -> None:
    """LegacyClient без username/password не может login → raise в login()."""
    from unifi_manager.clients.legacy import LegacyClient

    client = LegacyClient(minimal_unifi_settings.unifi)
    with pytest.raises(UnifiAuthError, match="username and password required"):
        client.login()


@pytest.mark.fast
@responses.activate
def test_get_devices_uses_proxy_network_path(legacy_settings: Settings) -> None:
    """get_devices() обращается к /proxy/network/api/s/<site>/stat/device."""
    from unifi_manager.clients.legacy import LegacyClient

    responses.post("https://192.0.2.1:11443/api/auth/login", json={"meta": {"rc": "ok"}}, status=200)
    responses.get(
        "https://192.0.2.1:11443/proxy/network/api/s/site-1/stat/device",
        json={"meta": {"rc": "ok"}, "data": [{"mac": "aa:bb", "model": "U7IW"}]},
        status=200,
    )

    client = LegacyClient(legacy_settings.unifi)
    client.login()
    raw_devices = client.list_devices_raw()
    assert len(raw_devices) == 1
    assert raw_devices[0]["mac"] == "aa:bb"


@pytest.mark.fast
@responses.activate
def test_get_events_for_mac(legacy_settings: Settings) -> None:
    """get_events_raw фильтрует по mac параметру."""
    from unifi_manager.clients.legacy import LegacyClient

    responses.post("https://192.0.2.1:11443/api/auth/login", json={"meta": {"rc": "ok"}}, status=200)
    responses.get(
        "https://192.0.2.1:11443/proxy/network/api/s/site-1/stat/event",
        json={"meta": {"rc": "ok"}, "data": [{"key": "EVT_AP_Lost_Contact"}]},
        status=200,
    )

    client = LegacyClient(legacy_settings.unifi)
    client.login()
    events = client.list_events_raw(mac="aa:bb:cc:dd:ee:01")
    assert len(events) == 1


@pytest.mark.fast
@responses.activate
def test_send_command(legacy_settings: Settings) -> None:
    """send_command POST в /cmd/devmgr."""
    from unifi_manager.clients.legacy import LegacyClient

    responses.post("https://192.0.2.1:11443/api/auth/login", json={"meta": {"rc": "ok"}}, status=200)
    responses.post(
        "https://192.0.2.1:11443/proxy/network/api/s/site-1/cmd/devmgr",
        json={"meta": {"rc": "ok"}},
        status=200,
    )

    client = LegacyClient(legacy_settings.unifi)
    client.login()
    result = client.send_command({"cmd": "restart", "mac": "aa:bb:cc:dd:ee:01"})
    assert result["meta"]["rc"] == "ok"
```

- [ ] **Step 6.2: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_clients/test_legacy.py -v --no-cov
```
Expected: ModuleNotFoundError.

- [ ] **Step 6.3: Implement**

`src/unifi_manager/clients/legacy.py`:

```python
"""LegacyClient: session-based UniFi Network API клиент.

Authentication: POST /api/auth/login c username+password, получает session cookie
и (опционально) X-Csrf-Token который автоматически добавляется в session headers
для последующих POST запросов.

Endpoints: /proxy/network/api/s/<site>/...
"""
from __future__ import annotations

import logging
from typing import Any

from unifi_manager.clients.base import BaseUnifiClient
from unifi_manager.clients.exceptions import UnifiAPIError, UnifiAuthError
from unifi_manager.settings import UnifiAuthSettings


_logger = logging.getLogger(__name__)


class LegacyClient(BaseUnifiClient):
    """UniFi Legacy API клиент (session + CSRF)."""

    def __init__(
        self,
        config: UnifiAuthSettings,
        *,
        timeout: int = 15,
        max_retries: int = 3,
    ) -> None:
        super().__init__(config, timeout=timeout, max_retries=max_retries)
        self._logged_in = False

    @property
    def site_path_prefix(self) -> str:
        """Префикс path для запросов к этому site."""
        return f"/proxy/network/api/s/{self.config.site}"

    def login(self) -> bool:
        """Авторизация через session. Извлекает CSRF token если возвращается.

        Raises:
            UnifiAuthError: если credentials отсутствуют или 401/403.
        """
        if self.config.username is None or self.config.password is None:
            raise UnifiAuthError("username and password required for LegacyClient login")

        login_url = f"{self.base_url}/api/auth/login"
        body = {
            "username": self.config.username.get_secret_value(),
            "password": self.config.password.get_secret_value(),
        }
        try:
            resp = self.session.post(login_url, json=body, timeout=self.timeout)
        except Exception as e:
            raise UnifiAuthError(f"login request failed: {e}") from e

        if resp.status_code in (401, 403):
            raise UnifiAuthError(f"login failed: {resp.status_code}")
        if not resp.ok:
            raise UnifiAuthError(f"login failed with status {resp.status_code}")

        csrf = resp.headers.get("X-Csrf-Token")
        if csrf:
            self.session.headers["X-Csrf-Token"] = csrf

        self._logged_in = True
        _logger.info("LegacyClient logged in to %s", self.base_url)
        return True

    def _ensure_logged_in(self) -> None:
        if not self._logged_in:
            self.login()

    def list_devices_raw(self) -> list[dict[str, Any]]:
        """GET /stat/device — список всех устройств site (raw dicts).

        Parsing into Device/AccessPoint/Switch — задача вызывающего кода (Phase 2 service).
        """
        self._ensure_logged_in()
        result = self.get_json(f"{self.site_path_prefix}/stat/device")
        return self._extract_data(result)

    def list_events_raw(self, *, mac: str | None = None) -> list[dict[str, Any]]:
        """GET /stat/event — события (опционально фильтр по mac)."""
        self._ensure_logged_in()
        path = f"{self.site_path_prefix}/stat/event"
        if mac:
            path += f"?mac={mac}"
        result = self.get_json(path)
        return self._extract_data(result)

    def list_clients_raw(self) -> list[dict[str, Any]]:
        """GET /stat/sta — подключённые клиенты."""
        self._ensure_logged_in()
        result = self.get_json(f"{self.site_path_prefix}/stat/sta")
        return self._extract_data(result)

    def send_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /cmd/devmgr — отправить команду (restart, power-cycle, ...).

        Args:
            payload: e.g. {"cmd": "restart", "mac": "aa:bb:cc:dd:ee:01"}
        """
        self._ensure_logged_in()
        return self.post_json(
            f"{self.site_path_prefix}/cmd/devmgr",
            json_body=payload,
        )

    @staticmethod
    def _extract_data(response: dict[str, Any]) -> list[dict[str, Any]]:
        """Извлечь список 'data' из стандартного UniFi response wrapper."""
        data = response.get("data")
        if not isinstance(data, list):
            raise UnifiAPIError(f"unexpected response format: {response}")
        return data
```

- [ ] **Step 6.4: Run tests**

```bash
.venv/Scripts/pytest tests/unit/test_clients/test_legacy.py -v --no-cov
```
Expected: all PASS.

- [ ] **Step 6.5: Mypy + ruff + coverage**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/clients/legacy.py
.venv/Scripts/ruff check src/unifi_manager/clients/legacy.py tests/unit/test_clients/test_legacy.py
.venv/Scripts/pytest --cov=unifi_manager.clients.legacy --cov-report=term-missing tests/unit/test_clients/test_legacy.py
```
Expected: clean, coverage 90%+.

- [ ] **Step 6.6: Commit**

```bash
git add src/unifi_manager/clients/legacy.py tests/unit/test_clients/test_legacy.py
git commit -m "phase1: clients/legacy.py — LegacyClient with CSRF flow"
```

---

## Task 7: IntegrationClient (X-API-KEY)

**Files:**
- Create: `src/unifi_manager/clients/integration.py`
- Create: `tests/unit/test_clients/test_integration.py`
- Create: `tests/fixtures/integration_devices.json`

**Goal:** Integration API клиент: X-API-KEY auth, endpoints `/proxy/network/integration/v1/sites/<UUID>/...`. Принципиально отличается от Legacy: использует API key (не session), site_id в UUID формате (не slug), другая структура endpoints.

Reference: `_legacy/audit_unifi.py:14-30` и `_legacy/check_unifi.py:7-22`.

- [ ] **Step 7.1: Create fixture**

`tests/fixtures/integration_devices.json` — реальная структура ответа Integration API (минимизированная):

```json
{
  "data": [
    {
      "id": "ap-uuid-1",
      "macAddress": "aa:bb:cc:dd:ee:01",
      "name": "Restoran",
      "model": "U7IW",
      "state": "ONLINE",
      "ipAddress": "10.3.0.10"
    },
    {
      "id": "ap-uuid-2",
      "macAddress": "aa:bb:cc:dd:ee:02",
      "name": "Office AP",
      "model": "U7PG2",
      "state": "OFFLINE"
    }
  ],
  "offset": 0,
  "limit": 100,
  "count": 2,
  "totalCount": 2
}
```

- [ ] **Step 7.2: Write failing tests**

`tests/unit/test_clients/test_integration.py`:

```python
"""Тесты для unifi_manager.clients.integration.IntegrationClient."""
import json
from pathlib import Path

import pytest
import responses
from pydantic import SecretStr

from unifi_manager.clients.exceptions import UnifiAuthError
from unifi_manager.settings import Settings, UnifiAuthSettings


SITE_UUID = "bbffb94c-1234-5678-9abc-def012345678"


@pytest.fixture
def integration_settings() -> Settings:
    """Settings с api_key и site_id_uuid для Integration API."""
    return Settings(
        unifi=UnifiAuthSettings(
            host="192.0.2.1",
            port=11443,
            site="site-1",  # short slug, не используется Integration API
            site_id_uuid=SITE_UUID,
            api_key=SecretStr("test-api-key-placeholder"),
        )
    )


@pytest.mark.fast
def test_integration_client_uses_api_key_header(integration_settings: Settings) -> None:
    """X-API-KEY ставится в session headers при инициализации."""
    from unifi_manager.clients.integration import IntegrationClient

    client = IntegrationClient(integration_settings.unifi)
    assert client.session.headers.get("X-API-KEY") == "test-api-key-placeholder"


@pytest.mark.fast
def test_missing_api_key_raises(minimal_unifi_settings: Settings) -> None:
    """Без api_key — UnifiAuthError при создании."""
    from unifi_manager.clients.integration import IntegrationClient

    with pytest.raises(UnifiAuthError, match="api_key required"):
        IntegrationClient(minimal_unifi_settings.unifi)


@pytest.mark.fast
def test_missing_site_uuid_raises(integration_settings: Settings) -> None:
    """site_id_uuid обязателен для Integration API."""
    from unifi_manager.clients.integration import IntegrationClient

    # Зануляем UUID для теста
    integration_settings.unifi.site_id_uuid = None
    with pytest.raises(UnifiAuthError, match="site_id_uuid required"):
        IntegrationClient(integration_settings.unifi)


@pytest.mark.fast
@responses.activate
def test_list_devices_uses_integration_path(integration_settings: Settings) -> None:
    """Endpoint: /proxy/network/integration/v1/sites/<UUID>/devices."""
    from unifi_manager.clients.integration import IntegrationClient

    expected_url = (
        f"https://192.0.2.1:11443/proxy/network/integration/v1/sites/{SITE_UUID}/devices"
    )
    responses.get(
        expected_url,
        json={"data": [{"id": "x", "macAddress": "aa:bb:cc:dd:ee:01", "model": "U7IW"}]},
        status=200,
    )

    client = IntegrationClient(integration_settings.unifi)
    raw = client.list_devices_raw()
    assert len(raw) == 1


@pytest.mark.fast
@responses.activate
def test_list_clients_uses_integration_path(integration_settings: Settings) -> None:
    """Endpoint: /proxy/network/integration/v1/sites/<UUID>/clients."""
    from unifi_manager.clients.integration import IntegrationClient

    expected_url = (
        f"https://192.0.2.1:11443/proxy/network/integration/v1/sites/{SITE_UUID}/clients"
    )
    responses.get(expected_url, json={"data": []}, status=200)

    client = IntegrationClient(integration_settings.unifi)
    raw = client.list_clients_raw()
    assert raw == []


@pytest.mark.fast
@responses.activate
def test_full_integration_response_parses(
    integration_settings: Settings, fixtures_dir: Path
) -> None:
    """Реальный response от Integration API парсится."""
    from unifi_manager.clients.integration import IntegrationClient

    raw_response = json.loads(
        (fixtures_dir / "integration_devices.json").read_text(encoding="utf-8")
    )
    expected_url = (
        f"https://192.0.2.1:11443/proxy/network/integration/v1/sites/{SITE_UUID}/devices"
    )
    responses.get(expected_url, json=raw_response, status=200)

    client = IntegrationClient(integration_settings.unifi)
    raw = client.list_devices_raw()
    assert len(raw) == 2
    assert raw[0]["macAddress"] == "aa:bb:cc:dd:ee:01"
```

- [ ] **Step 7.3: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_clients/test_integration.py -v --no-cov
```
Expected: ModuleNotFoundError.

- [ ] **Step 7.4: Implement**

`src/unifi_manager/clients/integration.py`:

```python
"""IntegrationClient: API-key based UniFi Network Integration API клиент.

Authentication: X-API-KEY header (статичный токен, не сессия).
Endpoints: /proxy/network/integration/v1/sites/<UUID>/...

ВАЖНО: site_id_uuid отличается от site (short slug) в Legacy API.
Получается отдельно через `GET /proxy/network/integration/v1/sites` для конкретного контроллера.
"""
from __future__ import annotations

import logging
from typing import Any

from unifi_manager.clients.base import BaseUnifiClient
from unifi_manager.clients.exceptions import UnifiAPIError, UnifiAuthError
from unifi_manager.settings import UnifiAuthSettings


_logger = logging.getLogger(__name__)


class IntegrationClient(BaseUnifiClient):
    """UniFi Integration API клиент (X-API-KEY auth)."""

    def __init__(
        self,
        config: UnifiAuthSettings,
        *,
        timeout: int = 15,
        max_retries: int = 3,
    ) -> None:
        if config.api_key is None:
            raise UnifiAuthError("api_key required for IntegrationClient")
        if config.site_id_uuid is None:
            raise UnifiAuthError("site_id_uuid required for IntegrationClient")

        super().__init__(config, timeout=timeout, max_retries=max_retries)
        self.session.headers["X-API-KEY"] = config.api_key.get_secret_value()
        _logger.info("IntegrationClient initialized for site %s", config.site_id_uuid)

    @property
    def site_path_prefix(self) -> str:
        return f"/proxy/network/integration/v1/sites/{self.config.site_id_uuid}"

    def list_devices_raw(self) -> list[dict[str, Any]]:
        """GET /devices — список устройств site."""
        result = self.get_json(f"{self.site_path_prefix}/devices")
        return self._extract_data(result)

    def list_clients_raw(self) -> list[dict[str, Any]]:
        """GET /clients — подключённые клиенты."""
        result = self.get_json(f"{self.site_path_prefix}/clients")
        return self._extract_data(result)

    @staticmethod
    def _extract_data(response: dict[str, Any]) -> list[dict[str, Any]]:
        """Integration API возвращает {data: [...], offset, limit, count, totalCount}."""
        data = response.get("data")
        if not isinstance(data, list):
            raise UnifiAPIError(f"unexpected Integration API response: {response}")
        return data
```

- [ ] **Step 7.5: Run tests**

```bash
.venv/Scripts/pytest tests/unit/test_clients/test_integration.py -v --no-cov
```
Expected: all PASS.

- [ ] **Step 7.6: Mypy + ruff + coverage**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/clients/integration.py
.venv/Scripts/ruff check src/unifi_manager/clients/integration.py tests/unit/test_clients/test_integration.py
.venv/Scripts/pytest --cov=unifi_manager.clients.integration --cov-report=term-missing tests/unit/test_clients/test_integration.py
```
Expected: clean, coverage 90%+.

- [ ] **Step 7.7: Commit**

```bash
git add src/unifi_manager/clients/integration.py tests/unit/test_clients/test_integration.py tests/fixtures/integration_devices.json
git commit -m "phase1: clients/integration.py — IntegrationClient with X-API-KEY"
```

---

## Task 8: Logging expand (Rich + JSON + SecretsFilter)

**Files:**
- Modify: `src/unifi_manager/logging_config.py` (rewrite from minimal stub)
- Modify: `tests/unit/test_logging.py` (extend tests)

**Goal:** Полная логирование инфраструктура — RichHandler для console (color, читаемо), JSON formatter для файла, SecretsFilter для защиты от утечки токенов.

- [ ] **Step 8.1: Write failing tests (extend existing)**

В `tests/unit/test_logging.py` ДОБАВИТЬ новые тесты (старые сохранить):

```python
"""Тесты для logging_config (расширенная Phase 1 версия)."""
import json
import logging
from io import StringIO
from pathlib import Path

import pytest
from pydantic import SecretStr

import unifi_manager.logging_config as logging_config_module
from unifi_manager.settings import LoggingSettings, Settings, UnifiAuthSettings


@pytest.fixture(autouse=True)
def _reset_logging_state() -> None:
    """Сбрасывает глобальный state модуля logging_config + root handlers
    перед каждым тестом, чтобы тесты не зависели от порядка выполнения."""
    logging_config_module._LOGGING_CONFIGURED = False
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.WARNING)


# === Existing Phase 0 tests preserved ===
# (test_setup_logging_callable, test_setup_logging_returns_none,
#  test_setup_logging_levels parametrized, test_setup_logging_idempotent)
# Сохранить их как было.


# === New Phase 1 tests ===

@pytest.mark.fast
def test_setup_logging_adds_console_and_file_handler(tmp_path: Path) -> None:
    """В Phase 1 — два handler'а: console (Rich) + file (JSON)."""
    from unifi_manager.logging_config import setup_logging

    settings = LoggingSettings(log_dir=tmp_path)
    setup_logging(settings, verbose=0, quiet=0)

    root = logging.getLogger()
    handler_types = [type(h).__name__ for h in root.handlers]
    assert any("Rich" in t for t in handler_types), f"No Rich handler in {handler_types}"
    assert any(
        "FileHandler" in t or "RotatingFileHandler" in t for t in handler_types
    ), f"No FileHandler in {handler_types}"


@pytest.mark.fast
def test_log_file_is_created_with_json_format(tmp_path: Path) -> None:
    """File handler пишет JSON-форматированные строки."""
    from unifi_manager.logging_config import setup_logging

    settings = LoggingSettings(log_dir=tmp_path)
    setup_logging(settings, verbose=0, quiet=0)

    logger = logging.getLogger("test")
    logger.warning("test message", extra={"custom_field": 42})

    # flush handlers
    for h in logging.getLogger().handlers:
        h.flush()

    log_file = tmp_path / "unifi-mgr.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8").strip()
    lines = content.splitlines()
    assert len(lines) >= 1
    # последняя строка должна быть валидным JSON
    record = json.loads(lines[-1])
    assert record["msg"] == "test message"
    assert record["level"] == "WARNING"
    assert record["custom_field"] == 42


@pytest.mark.fast
def test_secrets_filter_redacts_password(tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """SecretsFilter сканирует сообщения и заменяет значения SecretStr на ***REDACTED***."""
    from unifi_manager.logging_config import register_secret, setup_logging

    settings = LoggingSettings(log_dir=tmp_path)
    setup_logging(settings, verbose=0, quiet=0)

    # Регистрируем секрет
    register_secret("super-secret-password-do-not-leak")

    logger = logging.getLogger("test")
    logger.error("Login failed for user with password=super-secret-password-do-not-leak")

    for h in logging.getLogger().handlers:
        h.flush()

    log_file = tmp_path / "unifi-mgr.log"
    content = log_file.read_text(encoding="utf-8")
    assert "super-secret-password-do-not-leak" not in content
    assert "***REDACTED***" in content


@pytest.mark.fast
def test_register_secret_from_secret_str(tmp_path: Path) -> None:
    """register_secret_from_settings извлекает все SecretStr из Settings."""
    from unifi_manager.logging_config import register_secrets_from_settings, setup_logging

    setup_logging(LoggingSettings(log_dir=tmp_path), verbose=0, quiet=0)

    settings = Settings(
        unifi=UnifiAuthSettings(
            host="1.2.3.4", port=11443, site="test",
            password=SecretStr("the-password"),
            api_key=SecretStr("the-api-key"),
        )
    )
    register_secrets_from_settings(settings)

    logger = logging.getLogger("test")
    logger.error("Debug dump: password=the-password and key=the-api-key")

    for h in logging.getLogger().handlers:
        h.flush()

    log_file = tmp_path / "unifi-mgr.log"
    content = log_file.read_text(encoding="utf-8")
    assert "the-password" not in content
    assert "the-api-key" not in content
    assert content.count("***REDACTED***") >= 2


@pytest.mark.fast
def test_console_handler_uses_rich(tmp_path: Path) -> None:
    """Console handler — это RichHandler."""
    from rich.logging import RichHandler

    from unifi_manager.logging_config import setup_logging

    setup_logging(LoggingSettings(log_dir=tmp_path), verbose=0, quiet=0)

    root = logging.getLogger()
    rich_handlers = [h for h in root.handlers if isinstance(h, RichHandler)]
    assert len(rich_handlers) == 1
```

- [ ] **Step 8.2: Run, verify failures (new tests fail, old still pass)**

```bash
.venv/Scripts/pytest tests/unit/test_logging.py -v --no-cov
```
Expected: 7 old tests PASS, new tests FAIL (нет RotatingFileHandler/JSON/SecretsFilter).

- [ ] **Step 8.3: Rewrite `src/unifi_manager/logging_config.py`**

```python
"""Полное логирование для unifi-mgr (Phase 1).

Handlers:
- console: RichHandler (color, читаемо в TUI)
- file: RotatingFileHandler с JSON форматом (для grep/jq на сервере)

Дополнительно:
- SecretsFilter: сканирует сообщения и заменяет зарегистрированные секреты на ***REDACTED***
- register_secret / register_secrets_from_settings — публичные API

В фазе 2 добавится TelegramHandler с rate-limit.
"""
from __future__ import annotations

import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

from pydantic import SecretStr
from rich.logging import RichHandler

from unifi_manager.settings import LoggingSettings, Settings

_LOGGING_CONFIGURED = False
_REGISTERED_SECRETS: set[str] = set()


# === Public API ===

def setup_logging(
    settings: LoggingSettings,
    verbose: int = 0,
    quiet: int = 0,
) -> None:
    """Конфигурирует root logger с двумя handler'ами.

    Args:
        settings: настройки из Settings.logging
        verbose: 1+ → DEBUG для console
        quiet: 1+ → WARNING для console
    """
    global _LOGGING_CONFIGURED

    root = logging.getLogger()

    if quiet > 0:
        level = logging.WARNING
    elif verbose > 0:
        level = logging.DEBUG
    else:
        level = logging.getLevelNamesMapping()[settings.level]

    root.setLevel(level)

    if _LOGGING_CONFIGURED:
        return

    # SecretsFilter — глобально, перед всеми handlers
    secrets_filter = SecretsFilter()

    # === Console handler (Rich) ===
    console_handler = RichHandler(
        show_path=False,
        rich_tracebacks=True,
        markup=False,
    )
    console_handler.addFilter(secrets_filter)
    root.addHandler(console_handler)

    # === File handler (rotating JSON) ===
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    log_file = settings.log_dir / "unifi-mgr.log"
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=settings.max_bytes,
        backupCount=settings.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(JsonFormatter())
    file_handler.setLevel(logging.DEBUG)  # файл всегда DEBUG
    file_handler.addFilter(secrets_filter)
    root.addHandler(file_handler)

    _LOGGING_CONFIGURED = True


def register_secret(value: str) -> None:
    """Зарегистрировать секрет для SecretsFilter.

    Любое появление `value` в логах будет заменено на '***REDACTED***'.
    """
    if value and len(value) >= 4:  # игнорируем тривиально-короткие
        _REGISTERED_SECRETS.add(value)


def register_secrets_from_settings(settings: Settings) -> None:
    """Извлекает все SecretStr поля из Settings и регистрирует их.

    Рекурсивно проходит по всем sub-models.
    """
    _walk_and_register(settings.model_dump(mode="python"))


def _walk_and_register(obj: Any) -> None:
    """Рекурсивно обходит структуру и регистрирует SecretStr значения."""
    if isinstance(obj, SecretStr):
        register_secret(obj.get_secret_value())
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk_and_register(v)
    elif isinstance(obj, list | tuple):
        for v in obj:
            _walk_and_register(v)


# === Internal helpers ===

class SecretsFilter(logging.Filter):
    """Logger filter заменяющий зарегистрированные секреты на ***REDACTED***."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not _REGISTERED_SECRETS:
            return True

        # Replace в основном message
        if isinstance(record.msg, str):
            for secret in _REGISTERED_SECRETS:
                if secret in record.msg:
                    record.msg = record.msg.replace(secret, "***REDACTED***")

        # Replace в args (для % форматирования)
        if record.args:
            new_args = tuple(
                _redact(a) if isinstance(a, str) else a
                for a in (record.args if isinstance(record.args, tuple) else (record.args,))
            )
            record.args = new_args

        return True


def _redact(s: str) -> str:
    for secret in _REGISTERED_SECRETS:
        if secret in s:
            s = s.replace(secret, "***REDACTED***")
    return s


class JsonFormatter(logging.Formatter):
    """JSON formatter — одна строка = одна запись, поля грепаются через jq."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S.%f"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # extra kwargs из logger.info("...", extra={...}) попадают в record.__dict__
        # стандартные LogRecord поля — исключаем
        standard_fields = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName",
            "processName", "process", "getMessage",
        }
        for k, v in record.__dict__.items():
            if k not in standard_fields and not k.startswith("_"):
                payload[k] = v

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)
```

- [ ] **Step 8.4: Run all tests**

```bash
.venv/Scripts/pytest tests/unit/test_logging.py -v --no-cov
```
Expected: all PASS (old + new).

```bash
.venv/Scripts/pytest --no-cov
```
Expected: full suite зелёный.

- [ ] **Step 8.5: Mypy + ruff + coverage**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/logging_config.py
.venv/Scripts/ruff check src/unifi_manager/logging_config.py tests/unit/test_logging.py
.venv/Scripts/pytest --cov=unifi_manager.logging_config --cov-report=term-missing tests/unit/test_logging.py
```
Expected: clean, coverage 85%+.

- [ ] **Step 8.6: Commit**

```bash
git add src/unifi_manager/logging_config.py tests/unit/test_logging.py
git commit -m "phase1: logging_config full — Rich console + JSON file + SecretsFilter"
```

---

## Task 9: CI update — mypy --strict для всех core модулей

**Files:**
- Modify: `.github/workflows/ci.yml`

**Goal:** Расширить mypy --strict scope в CI чтобы покрыть все новые core модули (clients/, domain/, utils/).

- [ ] **Step 9.1: Update `.github/workflows/ci.yml`**

Найти строку:
```yaml
      - name: Mypy strict (core)
        # В фазе 0 ещё нет core модулей, только settings/logging — проверяем их.
        run: mypy --strict src/unifi_manager/settings.py src/unifi_manager/logging_config.py
```

Заменить на:
```yaml
      - name: Mypy strict (core)
        # Phase 1: settings, logging_config + clients + domain + utils.
        # Services, integrations, diagnostics добавятся в Phase 2-3.
        run: |
          mypy --strict \
            src/unifi_manager/settings.py \
            src/unifi_manager/logging_config.py \
            src/unifi_manager/clients \
            src/unifi_manager/domain \
            src/unifi_manager/utils
```

- [ ] **Step 9.2: Verify locally что mypy --strict проходит на всё**

```bash
.venv/Scripts/mypy --strict \
  src/unifi_manager/settings.py \
  src/unifi_manager/logging_config.py \
  src/unifi_manager/clients \
  src/unifi_manager/domain \
  src/unifi_manager/utils
```
Expected: `Success: no issues found in N source files`.

Если что-то ругается на strict — поправить тут же (добавить annotations, etc.).

- [ ] **Step 9.3: Run full pre-commit**

```bash
.venv/Scripts/pre-commit run --all-files
```
Expected: all PASS.

- [ ] **Step 9.4: Full suite + coverage**

```bash
.venv/Scripts/pytest --cov=unifi_manager --cov-report=term-missing --cov-fail-under=90
```
Expected: all PASS, coverage 90%+.

Если coverage < 90% — посмотреть какие линии не покрыты, добавить тесты для bizарных или critical paths.

- [ ] **Step 9.5: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "phase1: CI mypy --strict expanded to all core modules"
```

---

## Task 10: Final acceptance + tag

- [ ] **Step 10.1: Fresh venv install + acceptance**

```bash
rm -rf .venv-acceptance
py -3.12 -m venv .venv-acceptance
.venv-acceptance/Scripts/pip install -e ".[dev]"

.venv-acceptance/Scripts/pytest --cov=unifi_manager --cov-report=term-missing --cov-fail-under=90 -v
```
Expected: all PASS, coverage 90%+.

- [ ] **Step 10.2: CLI smoke (regression check from Phase 0)**

```bash
.venv-acceptance/Scripts/unifi-mgr --version
.venv-acceptance/Scripts/unifi-mgr --help
```
Expected: version + 9 subcommand groups (как в Phase 0).

- [ ] **Step 10.3: Cleanup acceptance venv**

```bash
rm -rf .venv-acceptance
```

- [ ] **Step 10.4: Move phase tag forward**

```bash
git tag -d phase-1-complete 2>/dev/null || true
git tag -a phase-1-complete -m "Phase 1 (Core Layers) complete: clients + domain + utils/time + logging expanded"
git describe --tags
```
Expected: `phase-1-complete` указывает на текущий HEAD.

---

## Definition of Done — Phase 1

| Check | Command | Expected |
|---|---|---|
| Все Phase 0 тесты ещё проходят | `pytest --no-cov` | 35 (Phase 0) + новые → 80+ |
| Coverage всего проекта | `pytest --cov=unifi_manager --cov-fail-under=90` | ≥ 90% |
| Coverage utils/time.py | `pytest --cov=unifi_manager.utils.time` | 100% (критичный bugfix) |
| Coverage clients/ | `pytest --cov=unifi_manager.clients` | ≥ 90% |
| Coverage domain/ | `pytest --cov=unifi_manager.domain` | ≥ 90% |
| Mypy strict core | `mypy --strict src/unifi_manager/{settings.py,logging_config.py,clients,domain,utils}` | Success |
| Ruff clean | `ruff check .` | All checks passed |
| Pre-commit green | `pre-commit run --all-files` | all PASS |
| CI yaml updated | `.github/workflows/ci.yml` mypy line | covers new modules |
| Tag created | `git tag -l phase-1-complete` | exists |
| Logging produces JSON | manual test or test_log_file_is_created_with_json_format | PASS |
| SecretsFilter redacts | test_secrets_filter_redacts_password | PASS |

**What is NOT in this phase:**
- ❌ Services (audit, restart, export) — Phase 2-3
- ❌ Telegram/Zabbix integrations — Phase 2
- ❌ Real CLI commands — Phase 4 (stub'ы остаются)
- ❌ Legacy scripts trogаются — Phase 5/6

---

## After Phase 1

Когда `phase-1-complete` тег есть и CI зелёный — переходим к написанию плана **Phase 2 (Services + Integrations)**:
- `services/audit.py` — AuditService с критическими проверками
- `services/export.py` — CSV/JSON/XLSX
- `services/lock.py` — FileLock через fasteners
- `services/notify.py` + AlertHistory
- `integrations/telegram.py` — send_message + TelegramRateLimiter
- `integrations/zabbix.py` — LLD JSON

Создание плана Phase 2 — отдельная сессия с `superpowers:writing-plans`.
