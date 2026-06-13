# Phase 2 — Services & Integrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать бизнес-логику сервисов (audit, export, notify, lock) и интеграции (telegram, zabbix) поверх core слоёв Phase 1. Это последняя phase до CLI (Phase 4) и до cron switch (Phase 5).

**Architecture:** Services используют clients (Phase 1) для I/O и domain (Phase 1) для типизации данных. Integrations — outbound side (Telegram, Zabbix). Каждый service — отдельный модуль с одной ответственностью. Никакого CLI кода — только переиспользуемые service-объекты, которые Phase 4 CLI команды будут инстанцировать и вызывать.

**Tech Stack:** Python 3.12, pydantic v2, requests (для Telegram API), fasteners (FileLock), freezegun, responses (HTTP mocks).

**Гейт готовности:** mypy --strict зелёный для всех Phase 2 модулей. Все services unit-тестированы с mocked clients. Telegram rate-limit покрыт freezegun-тестами. AlertHistory dedup покрыт edge cases. Coverage 90%+ overall.

**Ветка работы:** `worktree-refactor+v2` (продолжение с Phase 1).

**Связанный спек:** [docs/superpowers/specs/2026-05-16-unifi-manager-refactor-design.md](../specs/2026-05-16-unifi-manager-refactor-design.md)

**Предыдущая фаза:** [phase-1-core-layers.md](2026-05-16-phase-1-core-layers.md) — Core Layers, tag `phase-1-complete`

**Platform notes:** Windows worktree. Use `.venv/Scripts/python`, `.venv/Scripts/pytest`. На Linux заменить `Scripts/` на `bin/`.

---

## File Structure

### Создаются (новые):

```
src/unifi_manager/
├── services/
│   ├── lock.py              # FileLock через fasteners (foundation для cron-safety)
│   ├── notify.py            # NotifyService + AlertHistory (dedup критических алертов)
│   ├── audit.py             # AuditService: critical, status, full, light, trends
│   └── export.py            # ExportService: CSV/JSON для clients и devices
│
└── integrations/
    ├── telegram.py          # TelegramRateLimiter + send_message
    └── zabbix.py            # LLD JSON formatter для Zabbix external check
```

### Тесты (новые):

```
tests/
├── conftest.py              # +фикстуры: mock_legacy_client, mock_integration_client,
│                            #  sample_devices, sample_clients
├── fixtures/
│   ├── audit_critical_sample.json     # devices с проблемами (offline, high temp, high PoE)
│   ├── mac_duplicates_sample.json     # клиенты с дубль-MAC и spoof MAC
│   ├── trends_report_day1.txt         # пример исторического отчёта (формат как unifi_trends.py)
│   ├── trends_report_day2.txt
│   ├── telegram_send_response.json    # успешный ответ Telegram Bot API
│   ├── zabbix_lld_expected.json       # ожидаемая структура LLD для теста
│   └── (existing fixtures from Phase 1)
│
└── unit/
    ├── test_services/
    │   ├── __init__.py
    │   ├── test_lock.py     # FileLock — параллельные processes блокируются
    │   ├── test_notify.py   # NotifyService + AlertHistory dedup
    │   ├── test_audit.py    # 5 sub-test classes по методу: critical/status/full/light/trends
    │   └── test_export.py   # CSV/JSON форматы, AccessPoint.real_model в model_dump
    │
    └── test_integrations/
        ├── __init__.py
        ├── test_telegram.py # MarkdownV2 escape, rate-limit с freezegun
        └── test_zabbix.py   # LLD JSON структура
```

### Расширяется:

```
.github/workflows/ci.yml     # mypy --strict scope: + services + integrations
```

### НЕ трогаются:

- `src/unifi_manager/services/restart.py` — Phase 3
- `src/unifi_manager/services/lock.py` НЕ называется так в Phase 0 spec, см. ниже — но "lock" уже в spec Section 1, OK.
- `src/unifi_manager/cli/` — Phase 4
- Legacy скрипты в корне репы — Phase 5

---

## Common patterns (read before starting)

**TDD цикл (как в Phase 0/1):**
1. Write failing test → 2. Run, see fail → 3. Implement → 4. Run, see pass → 5. Commit

**Test invocation:** `.venv/Scripts/pytest <path> -v --no-cov`. Полный suite в конце task: `.venv/Scripts/pytest --no-cov`.

**Mypy strict:** `.venv/Scripts/mypy --strict src/unifi_manager/<file>` после каждой задачи.

**Ruff:** `.venv/Scripts/ruff check src/unifi_manager/<file> tests/unit/<file>`. Cyrillic в docstrings/help → per-file-ignore RUF002/RUF003 в `pyproject.toml`.

**Commit message format:** `phase2: <short description>`.

**Existing decisions from Phase 0/1:**
- `pyproject.toml` `addopts` без `--cov*`.
- Tests маркируются `@pytest.mark.fast`.
- `SecretsFilter` уже handles `extra={}` fields (Phase 1 cleanup). Services могут безопасно использовать `logger.info("msg", extra={"key": value})`.
- File handler всегда DEBUG (Phase 1 cleanup). Console handler фильтрует по level.

**Mocking strategy для services:**
- Тесты services НЕ делают HTTP. Они мокают `LegacyClient` / `IntegrationClient` через `pytest-mock` (Mock objects).
- Тесты integrations мокают HTTP через `responses`.
- Это четкое разделение: clients tested против HTTP, services tested против client mocks.

---

## Task 1: services/lock.py — FileLock

**Files:**
- Create: `src/unifi_manager/services/lock.py`
- Create: `tests/unit/test_services/__init__.py` (empty)
- Create: `tests/unit/test_services/test_lock.py`

**Goal:** Атомарный FileLock через `fasteners` для cron-safety. Заменяет TOCTOU-race lock из `_legacy/auto_restart_cron.sh:9-18`. Используется RestartService (Phase 3) и любой cron-command в Phase 4.

- [ ] **Step 1.1: Write failing test**

`tests/unit/test_services/__init__.py` — empty.

`tests/unit/test_services/test_lock.py`:

```python
"""Тесты для unifi_manager.services.lock.FileLock."""
import multiprocessing as mp
from pathlib import Path

import pytest


@pytest.mark.fast
def test_lock_acquires_and_releases(tmp_path: Path) -> None:
    """Lock как context manager — acquire/release при входе/выходе."""
    from unifi_manager.services.lock import FileLock

    lock_path = tmp_path / "test.lock"
    with FileLock(lock_path) as lock:
        assert lock.locked is True
    assert lock.locked is False


@pytest.mark.fast
def test_lock_creates_file(tmp_path: Path) -> None:
    """Lock file создаётся на диске при acquire."""
    from unifi_manager.services.lock import FileLock

    lock_path = tmp_path / "test.lock"
    assert not lock_path.exists()

    with FileLock(lock_path):
        assert lock_path.exists()


@pytest.mark.fast
def test_lock_blocks_concurrent_acquisition(tmp_path: Path) -> None:
    """Второй FileLock на тот же путь НЕ может acquire пока первый держит."""
    from unifi_manager.services.lock import FileLock, LockAcquisitionError

    lock_path = tmp_path / "test.lock"
    with FileLock(lock_path):
        # Второй процесс/инстанс не сможет получить lock с timeout=0
        with pytest.raises(LockAcquisitionError):
            with FileLock(lock_path, timeout=0):
                pytest.fail("should not have acquired")


@pytest.mark.fast
def test_lock_releases_after_exception(tmp_path: Path) -> None:
    """Если в with-блоке raise — lock всё равно release."""
    from unifi_manager.services.lock import FileLock

    lock_path = tmp_path / "test.lock"
    with pytest.raises(RuntimeError, match="test error"):
        with FileLock(lock_path):
            raise RuntimeError("test error")

    # После исключения — lock доступен для нового acquire
    with FileLock(lock_path):
        pass  # успешно acquire


def _child_process_acquire(lock_path: str, result_queue: mp.Queue) -> None:
    """Helper для multiprocessing-теста — попытаться acquire lock из child процесса."""
    from unifi_manager.services.lock import FileLock, LockAcquisitionError

    try:
        with FileLock(Path(lock_path), timeout=0):
            result_queue.put("acquired")
    except LockAcquisitionError:
        result_queue.put("blocked")


@pytest.mark.slow  # slow — multiprocessing overhead
def test_lock_blocks_across_processes(tmp_path: Path) -> None:
    """Lock из разных процессов реально блокирует (atomicity via fasteners)."""
    from unifi_manager.services.lock import FileLock

    lock_path = tmp_path / "test.lock"
    result_queue: mp.Queue = mp.Queue()

    with FileLock(lock_path):
        # Запускаем child процесс который пытается acquire
        proc = mp.Process(target=_child_process_acquire,
                          args=(str(lock_path), result_queue))
        proc.start()
        proc.join(timeout=5)
        assert proc.exitcode == 0

    result = result_queue.get(timeout=1)
    assert result == "blocked"


@pytest.mark.fast
def test_lock_timeout_parameter(tmp_path: Path) -> None:
    """timeout=N — ждать до N секунд acquire, потом raise."""
    from unifi_manager.services.lock import FileLock, LockAcquisitionError

    lock_path = tmp_path / "test.lock"
    with FileLock(lock_path):
        # timeout=0 → сразу raise
        with pytest.raises(LockAcquisitionError):
            with FileLock(lock_path, timeout=0):
                pass
```

- [ ] **Step 1.2: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_services/test_lock.py -v --no-cov
```
Expected: ModuleNotFoundError.

- [ ] **Step 1.3: Implement**

`src/unifi_manager/services/lock.py`:

```python
"""FileLock — атомарный inter-process lock через fasteners.

Заменяет TOCTOU-race lock из _legacy/auto_restart_cron.sh.
Используется RestartService и любой cron-командой для защиты от
параллельных запусков.
"""
from __future__ import annotations

import logging
from pathlib import Path
from types import TracebackType

import fasteners

_logger = logging.getLogger(__name__)


class LockAcquisitionError(Exception):
    """Не удалось acquire lock в указанный timeout."""


class FileLock:
    """Inter-process file lock.

    Использование:
        with FileLock(Path("/var/lib/unifi-mgr/restart.lock")):
            ...  # work that must not overlap

    Если другой процесс держит lock — raises LockAcquisitionError
    после timeout секунд.
    """

    def __init__(self, path: Path, *, timeout: float = 10.0) -> None:
        self.path = path
        self.timeout = timeout
        self.locked = False
        # fasteners.InterProcessLock сам создаёт файл при acquire
        self._lock = fasteners.InterProcessLock(str(path))

    def __enter__(self) -> "FileLock":
        # delay=0.1 — fasteners poll interval
        acquired = self._lock.acquire(timeout=self.timeout, delay=0.1)
        if not acquired:
            raise LockAcquisitionError(
                f"Could not acquire lock {self.path} within {self.timeout}s"
            )
        self.locked = True
        _logger.debug("Acquired lock %s", self.path)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self.locked:
            self._lock.release()
            self.locked = False
            _logger.debug("Released lock %s", self.path)
```

- [ ] **Step 1.4: Run, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_services/test_lock.py -v --no-cov
```
Expected: 5 fast tests PASS, 1 slow test PASS (with multiprocessing — might take 2-3 seconds).

If `test_lock_blocks_across_processes` имеет timeout issues on Windows (multiprocessing slow start-up) — можно skip с `@pytest.mark.skipif(sys.platform == "win32", reason="multiprocessing slow on Windows")`, но сначала попробовать.

- [ ] **Step 1.5: Mypy + ruff**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/services/lock.py
.venv/Scripts/ruff check src/unifi_manager/services/lock.py tests/unit/test_services/
```
Expected: clean. Если ruff жалуется на Cyrillic — добавь per-file-ignore RUF002.

- [ ] **Step 1.6: Commit**

```bash
git add src/unifi_manager/services/lock.py tests/unit/test_services/__init__.py tests/unit/test_services/test_lock.py
git commit -m "phase2: services/lock.py — FileLock via fasteners"
```

---

## Task 2: services/notify.py — NotifyService + AlertHistory

**Files:**
- Create: `src/unifi_manager/services/notify.py`
- Create: `tests/unit/test_services/test_notify.py`

**Goal:** Dedup алертов чтобы не шторм-уведомлять оператора. Хэш по `(mac, error_type)` → state-файл с last_alert_time. Используется AuditService (Task 5-7) для `audit critical --telegram` команды (Phase 4).

- [ ] **Step 2.1: Write failing test**

`tests/unit/test_services/test_notify.py`:

```python
"""Тесты для unifi_manager.services.notify.AlertHistory."""
import json
from datetime import timedelta
from pathlib import Path

import pytest
from freezegun import freeze_time


@pytest.mark.fast
def test_alert_history_empty_initially(tmp_path: Path) -> None:
    """Свежий state-файл — нет prior alerts."""
    from unifi_manager.services.notify import AlertHistory

    history = AlertHistory(state_file=tmp_path / "alerts.json")
    assert history.is_new_alert(hash_key="ap-down:aa:bb") is True


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_alert_history_records_alert(tmp_path: Path) -> None:
    """После записи hash больше не считается новым."""
    from unifi_manager.services.notify import AlertHistory

    history = AlertHistory(state_file=tmp_path / "alerts.json")
    history.record_alert(hash_key="ap-down:aa:bb")
    assert history.is_new_alert(hash_key="ap-down:aa:bb") is False


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_alert_history_persists_to_disk(tmp_path: Path) -> None:
    """State сохраняется на диск — новый AlertHistory читает существующий state."""
    from unifi_manager.services.notify import AlertHistory

    state_file = tmp_path / "alerts.json"
    h1 = AlertHistory(state_file=state_file)
    h1.record_alert(hash_key="ap-down:aa:bb")
    h1.save()

    h2 = AlertHistory(state_file=state_file)
    assert h2.is_new_alert(hash_key="ap-down:aa:bb") is False


@pytest.mark.fast
def test_alert_history_cooldown_expires(tmp_path: Path) -> None:
    """После cooldown_minutes alert снова считается новым (для напоминания)."""
    from unifi_manager.services.notify import AlertHistory

    with freeze_time("2026-05-16 10:00:00") as frozen:
        history = AlertHistory(state_file=tmp_path / "alerts.json",
                               cooldown=timedelta(hours=1))
        history.record_alert(hash_key="ap-down:aa:bb")
        assert history.is_new_alert(hash_key="ap-down:aa:bb") is False

        frozen.move_to("2026-05-16 11:00:30")  # +1h 30s
        assert history.is_new_alert(hash_key="ap-down:aa:bb") is True


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_alert_history_different_hashes_independent(tmp_path: Path) -> None:
    """Разные hash — независимые dedup."""
    from unifi_manager.services.notify import AlertHistory

    history = AlertHistory(state_file=tmp_path / "alerts.json")
    history.record_alert(hash_key="ap-down:aa:bb")
    assert history.is_new_alert(hash_key="ap-down:cc:dd") is True
    assert history.is_new_alert(hash_key="high-temp:ee:ff") is True


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_alert_history_state_file_format(tmp_path: Path) -> None:
    """State JSON формат — для отладки оператором."""
    from unifi_manager.services.notify import AlertHistory

    state_file = tmp_path / "alerts.json"
    history = AlertHistory(state_file=state_file)
    history.record_alert(hash_key="ap-down:aa:bb")
    history.save()

    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert "ap-down:aa:bb" in data
    # ISO timestamp format
    assert "2026-05-16" in data["ap-down:aa:bb"]


@pytest.mark.fast
def test_alert_history_handles_missing_state_file(tmp_path: Path) -> None:
    """Если state-файл не существует — стартуем с пустого history."""
    from unifi_manager.services.notify import AlertHistory

    nonexistent = tmp_path / "subdir" / "alerts.json"
    history = AlertHistory(state_file=nonexistent)
    assert history.is_new_alert(hash_key="anything") is True


@pytest.mark.fast
def test_alert_history_handles_corrupt_state_file(tmp_path: Path) -> None:
    """Битый JSON в state-файле — лог warning, стартуем с пустого history."""
    from unifi_manager.services.notify import AlertHistory

    state_file = tmp_path / "alerts.json"
    state_file.write_text("not valid json {{{", encoding="utf-8")

    history = AlertHistory(state_file=state_file)
    assert history.is_new_alert(hash_key="anything") is True
```

- [ ] **Step 2.2: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_services/test_notify.py -v --no-cov
```
Expected: ModuleNotFoundError.

- [ ] **Step 2.3: Implement**

`src/unifi_manager/services/notify.py`:

```python
"""NotifyService + AlertHistory.

AlertHistory предотвращает шторм уведомлений — каждый алерт идентифицируется
hash_key (например "ap-down:aa:bb:cc:dd:ee:ff") и шлётся только если:
- Этот hash раньше не алертился, ИЛИ
- Прошёл cooldown с последнего алерта (для напоминания)

State хранится в JSON-файле (paths.cache_dir/alert_history.json по умолчанию).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from unifi_manager.utils.time import now_utc


DEFAULT_COOLDOWN = timedelta(minutes=60)

_logger = logging.getLogger(__name__)


class AlertHistory:
    """Dedup state для critical alerts.

    Использование:
        history = AlertHistory(state_file=Path("/var/lib/unifi-mgr/alerts.json"))
        if history.is_new_alert(hash_key="ap-down:aa:bb"):
            telegram.send_message("...")
            history.record_alert(hash_key="ap-down:aa:bb")
        history.save()
    """

    def __init__(
        self,
        state_file: Path,
        *,
        cooldown: timedelta = DEFAULT_COOLDOWN,
    ) -> None:
        self.state_file = state_file
        self.cooldown = cooldown
        self._state: dict[str, str] = self._load_state()

    def _load_state(self) -> dict[str, str]:
        """Прочитать state-файл (или вернуть {} при отсутствии/повреждении)."""
        if not self.state_file.is_file():
            return {}
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {k: str(v) for k, v in data.items()}
            _logger.warning("Alert state file %s: unexpected format", self.state_file)
            return {}
        except (json.JSONDecodeError, OSError) as e:
            _logger.warning("Failed to load alert state %s: %s", self.state_file, e)
            return {}

    def is_new_alert(self, *, hash_key: str) -> bool:
        """True если этот hash раньше не алертился или прошёл cooldown."""
        last_alert_str = self._state.get(hash_key)
        if last_alert_str is None:
            return True

        try:
            last_alert = datetime.fromisoformat(last_alert_str)
        except ValueError:
            _logger.warning("Bad timestamp in alert state for %s: %s",
                            hash_key, last_alert_str)
            return True

        return (now_utc() - last_alert) > self.cooldown

    def record_alert(self, *, hash_key: str) -> None:
        """Записать что алерт по этому hash отправлен сейчас."""
        self._state[hash_key] = now_utc().isoformat()

    def save(self) -> None:
        """Сохранить state на диск."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
```

- [ ] **Step 2.4: Run, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_services/test_notify.py -v --no-cov
```
Expected: 8 PASS.

- [ ] **Step 2.5: Mypy + ruff + coverage**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/services/notify.py
.venv/Scripts/ruff check src/unifi_manager/services/notify.py tests/unit/test_services/test_notify.py
.venv/Scripts/pytest --cov=unifi_manager.services.notify --cov-report=term-missing tests/unit/test_services/test_notify.py
```
Expected: clean, coverage 90%+.

- [ ] **Step 2.6: Commit**

```bash
git add src/unifi_manager/services/notify.py tests/unit/test_services/test_notify.py
git commit -m "phase2: services/notify.py — AlertHistory dedup"
```

---

## Task 3: integrations/telegram.py — Send + RateLimiter

**Files:**
- Create: `src/unifi_manager/integrations/telegram.py`
- Create: `tests/unit/test_integrations/__init__.py` (empty)
- Create: `tests/unit/test_integrations/test_telegram.py`
- Create: `tests/fixtures/telegram_send_response.json`

**Goal:** Отправка сообщений в Telegram + rate-limit (per-hash и total). Спасает оператора от шторма во время инцидента ("9-я ветка упала, 50 сообщений в секунду").

- [ ] **Step 3.1: Create fixture**

`tests/fixtures/telegram_send_response.json`:

```json
{
  "ok": true,
  "result": {
    "message_id": 42,
    "from": {"id": 123456789, "is_bot": true, "first_name": "UniFi Bot"},
    "chat": {"id": 987654321, "type": "private"},
    "date": 1747397800,
    "text": "Test message"
  }
}
```

- [ ] **Step 3.2: Write failing tests**

`tests/unit/test_integrations/__init__.py` — empty.

`tests/unit/test_integrations/test_telegram.py`:

```python
"""Тесты для unifi_manager.integrations.telegram."""
import json
from datetime import timedelta
from pathlib import Path

import pytest
import responses
from freezegun import freeze_time
from pydantic import SecretStr

from unifi_manager.settings import Settings, TelegramSettings, UnifiAuthSettings


@pytest.fixture
def telegram_settings() -> TelegramSettings:
    return TelegramSettings(
        bot_token=SecretStr("123456789:ABCdef-test-token"),
        chat_id="987654321",
        enabled=True,
        parse_mode="MarkdownV2",
        rate_limit_per_hash_seconds=30,
        rate_limit_total_per_minute=5,
    )


@pytest.fixture
def full_settings_with_telegram(telegram_settings: TelegramSettings) -> Settings:
    return Settings(
        unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="test"),
        telegram=telegram_settings,
    )


# === escape_markdown_v2 ===

@pytest.mark.fast
def test_escape_markdown_v2_basic() -> None:
    """MarkdownV2 reserved chars экранируются backslash."""
    from unifi_manager.integrations.telegram import escape_markdown_v2

    assert escape_markdown_v2("hello") == "hello"
    assert escape_markdown_v2("test.thing") == "test\\.thing"
    assert escape_markdown_v2("a+b=c") == "a\\+b\\=c"


@pytest.mark.fast
def test_escape_markdown_v2_all_reserved() -> None:
    """Все 18 reserved chars MarkdownV2: _ * [ ] ( ) ~ ` > # + - = | { } . !"""
    from unifi_manager.integrations.telegram import escape_markdown_v2

    raw = "_*[]()~`>#+-=|{}.!"
    escaped = escape_markdown_v2(raw)
    for ch in raw:
        assert f"\\{ch}" in escaped


@pytest.mark.fast
def test_escape_markdown_v2_preserves_normal_text() -> None:
    from unifi_manager.integrations.telegram import escape_markdown_v2

    assert escape_markdown_v2("Restoran AP offline 5 min") == "Restoran AP offline 5 min"


# === TelegramRateLimiter ===

@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_rate_limiter_allows_first_call(tmp_path: Path,
                                         telegram_settings: TelegramSettings) -> None:
    from unifi_manager.integrations.telegram import TelegramRateLimiter

    rl = TelegramRateLimiter(state_file=tmp_path / "throttle.json",
                              settings=telegram_settings)
    assert rl.allow(hash_key="ap-down:aa:bb") is True


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_rate_limiter_blocks_same_hash_within_window(
    tmp_path: Path, telegram_settings: TelegramSettings
) -> None:
    """Тот же hash в течение rate_limit_per_hash_seconds (30s) — blocked."""
    from unifi_manager.integrations.telegram import TelegramRateLimiter

    rl = TelegramRateLimiter(state_file=tmp_path / "throttle.json",
                              settings=telegram_settings)
    assert rl.allow(hash_key="ap-down:aa:bb") is True
    assert rl.allow(hash_key="ap-down:aa:bb") is False


@pytest.mark.fast
def test_rate_limiter_allows_after_hash_cooldown(
    tmp_path: Path, telegram_settings: TelegramSettings
) -> None:
    """После 31 секунды тот же hash снова allow."""
    from unifi_manager.integrations.telegram import TelegramRateLimiter

    with freeze_time("2026-05-16 10:00:00") as frozen:
        rl = TelegramRateLimiter(state_file=tmp_path / "throttle.json",
                                  settings=telegram_settings)
        rl.allow(hash_key="ap-down:aa:bb")

        frozen.tick(delta=timedelta(seconds=31))
        assert rl.allow(hash_key="ap-down:aa:bb") is True


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_rate_limiter_blocks_more_than_total_per_minute(
    tmp_path: Path, telegram_settings: TelegramSettings
) -> None:
    """Не более 5 разных msg в минуту суммарно."""
    from unifi_manager.integrations.telegram import TelegramRateLimiter

    rl = TelegramRateLimiter(state_file=tmp_path / "throttle.json",
                              settings=telegram_settings)
    # 5 разных hashes — все allow
    for i in range(5):
        assert rl.allow(hash_key=f"hash-{i}") is True
    # 6-й — blocked
    assert rl.allow(hash_key="hash-6") is False


@pytest.mark.fast
def test_rate_limiter_total_window_resets_after_minute(
    tmp_path: Path, telegram_settings: TelegramSettings
) -> None:
    """После 61 секунды старые алерты выпадают из total count."""
    from unifi_manager.integrations.telegram import TelegramRateLimiter

    with freeze_time("2026-05-16 10:00:00") as frozen:
        rl = TelegramRateLimiter(state_file=tmp_path / "throttle.json",
                                  settings=telegram_settings)
        for i in range(5):
            rl.allow(hash_key=f"hash-{i}")

        frozen.tick(delta=timedelta(seconds=61))
        # старые out of window — новый hash снова allow
        assert rl.allow(hash_key="hash-new") is True


# === send_message ===

@pytest.mark.fast
@responses.activate
@freeze_time("2026-05-16 10:00:00")
def test_send_message_calls_telegram_api(
    tmp_path: Path, full_settings_with_telegram: Settings, fixtures_dir: Path
) -> None:
    from unifi_manager.integrations.telegram import TelegramNotifier

    expected_url = "https://api.telegram.org/bot123456789:ABCdef-test-token/sendMessage"
    response_data = json.loads(
        (fixtures_dir / "telegram_send_response.json").read_text(encoding="utf-8")
    )
    responses.post(expected_url, json=response_data, status=200)

    notifier = TelegramNotifier(
        settings=full_settings_with_telegram.telegram,
        rate_limit_state=tmp_path / "throttle.json",
    )
    result = notifier.send_message("Hello world", hash_key="test")
    assert result is True
    assert len(responses.calls) == 1


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_send_message_blocked_by_rate_limit(
    tmp_path: Path, full_settings_with_telegram: Settings
) -> None:
    """Если rate-limit блокирует — send_message returns False, не делает HTTP."""
    from unifi_manager.integrations.telegram import TelegramNotifier

    notifier = TelegramNotifier(
        settings=full_settings_with_telegram.telegram,
        rate_limit_state=tmp_path / "throttle.json",
    )

    # Первый — отправляется (но без HTTP мока — мы не дойдём до HTTP)
    # Симулируем что rate-limit уже исчерпан для этого hash
    notifier.rate_limiter.allow(hash_key="test")  # records
    result = notifier.send_message("Spam", hash_key="test")
    assert result is False


@pytest.mark.fast
def test_send_message_disabled_returns_false(
    tmp_path: Path,
) -> None:
    """telegram.enabled=False → send_message всегда False, без HTTP."""
    from unifi_manager.integrations.telegram import TelegramNotifier

    settings = TelegramSettings(
        bot_token=SecretStr("test"),
        chat_id="123",
        enabled=False,
    )
    notifier = TelegramNotifier(
        settings=settings,
        rate_limit_state=tmp_path / "throttle.json",
    )
    assert notifier.send_message("ignored", hash_key="x") is False


@pytest.mark.fast
def test_send_message_missing_token_raises(tmp_path: Path) -> None:
    """bot_token=None → ValueError при init."""
    from unifi_manager.integrations.telegram import TelegramNotifier

    settings = TelegramSettings(bot_token=None, chat_id="123", enabled=True)
    with pytest.raises(ValueError, match="bot_token required"):
        TelegramNotifier(
            settings=settings,
            rate_limit_state=tmp_path / "throttle.json",
        )
```

- [ ] **Step 3.3: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_integrations/test_telegram.py -v --no-cov
```
Expected: ModuleNotFoundError.

- [ ] **Step 3.4: Implement**

`src/unifi_manager/integrations/telegram.py`:

```python
"""Telegram уведомления с rate-limit.

Особенности:
- escape_markdown_v2() для безопасного отображения device names с спецсимволами
- TelegramRateLimiter: per-hash (1 в 30s) + total (5 в минуту)
- State persistence в JSON для cron-runs
"""
from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import requests

from unifi_manager.settings import TelegramSettings
from unifi_manager.utils.time import now_utc


_MARKDOWN_V2_RESERVED = set("_*[]()~`>#+-=|{}.!")
_logger = logging.getLogger(__name__)


def escape_markdown_v2(text: str) -> str:
    """Экранирует все 18 reserved chars MarkdownV2 backslash'ом.

    Telegram MarkdownV2 требует экранирования _ * [ ] ( ) ~ ` > # + - = | { } . !
    в любом контексте (включая текст внутри обычных messages).
    """
    return "".join(f"\\{ch}" if ch in _MARKDOWN_V2_RESERVED else ch for ch in text)


class TelegramRateLimiter:
    """Per-hash + total rate-limit для Telegram алертов.

    Лимиты из settings.telegram:
    - rate_limit_per_hash_seconds (default 30): для одинаковых hash
    - rate_limit_total_per_minute (default 5): суммарный лимит разных hash в минуту

    State (timestamps) хранится в JSON для cron-persistence.
    """

    def __init__(self, state_file: Path, settings: TelegramSettings) -> None:
        self.state_file = state_file
        self.per_hash_window = timedelta(seconds=settings.rate_limit_per_hash_seconds)
        self.total_per_minute = settings.rate_limit_total_per_minute
        # {hash: last_sent_iso}
        self._hash_state: dict[str, str] = {}
        # deque of iso timestamps (общий счётчик)
        self._total_state: deque[str] = deque()
        self._load()

    def _load(self) -> None:
        if not self.state_file.is_file():
            return
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            self._hash_state = data.get("hashes", {})
            self._total_state = deque(data.get("total", []))
        except (json.JSONDecodeError, OSError) as e:
            _logger.warning("Failed to load telegram throttle state: %s", e)

    def _save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps({
                "hashes": self._hash_state,
                "total": list(self._total_state),
            }, indent=2),
            encoding="utf-8",
        )

    def allow(self, *, hash_key: str) -> bool:
        """True если можно отправить msg сейчас, и записать в state.

        False — заблокировано rate-limit'ом (за пределами per-hash или total).
        """
        now = now_utc()

        # Чистим устаревшие total entries (>60 sec ago)
        minute_ago = now - timedelta(minutes=1)
        while self._total_state:
            try:
                oldest = datetime.fromisoformat(self._total_state[0])
                if oldest < minute_ago:
                    self._total_state.popleft()
                else:
                    break
            except ValueError:
                self._total_state.popleft()

        # Per-hash check
        last_hash_str = self._hash_state.get(hash_key)
        if last_hash_str:
            try:
                last_hash_ts = datetime.fromisoformat(last_hash_str)
                if (now - last_hash_ts) < self.per_hash_window:
                    _logger.debug("Telegram rate-limit per-hash blocked: %s", hash_key)
                    return False
            except ValueError:
                pass  # bad state, treat as allowed

        # Total check
        if len(self._total_state) >= self.total_per_minute:
            _logger.debug(
                "Telegram rate-limit total blocked: %d in last minute",
                len(self._total_state),
            )
            return False

        # Record and save
        now_iso = now.isoformat()
        self._hash_state[hash_key] = now_iso
        self._total_state.append(now_iso)
        self._save()
        return True


class TelegramNotifier:
    """Высокоуровневый wrapper вокруг send_message + rate-limit.

    Использование (в Phase 4 CLI):
        notifier = TelegramNotifier(settings=cfg.telegram, rate_limit_state=cfg.paths.cache_dir/"telegram.json")
        notifier.send_message("AP Restoran is offline", hash_key="ap-down:aa:bb")
    """

    TELEGRAM_API_BASE = "https://api.telegram.org"

    def __init__(
        self,
        settings: TelegramSettings,
        *,
        rate_limit_state: Path,
        timeout: int = 10,
    ) -> None:
        if settings.enabled and settings.bot_token is None:
            raise ValueError("bot_token required when telegram.enabled=True")
        self.settings = settings
        self.timeout = timeout
        self.rate_limiter = TelegramRateLimiter(rate_limit_state, settings)

    def send_message(self, text: str, *, hash_key: str) -> bool:
        """Отправить msg, уважая rate-limit. Returns True если отправлено."""
        if not self.settings.enabled:
            return False
        if not self.rate_limiter.allow(hash_key=hash_key):
            return False

        # bot_token guaranteed non-None по __init__ check + enabled=True
        assert self.settings.bot_token is not None
        token = self.settings.bot_token.get_secret_value()

        url = f"{self.TELEGRAM_API_BASE}/bot{token}/sendMessage"
        body: dict[str, str] = {
            "chat_id": self.settings.chat_id or "",
            "text": text,
        }
        if self.settings.parse_mode != "None":
            body["parse_mode"] = self.settings.parse_mode

        try:
            resp = requests.post(url, json=body, timeout=self.timeout)
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            _logger.error("Telegram send_message failed: %s", e)
            return False
```

- [ ] **Step 3.5: Run, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_integrations/test_telegram.py -v --no-cov
```
Expected: all 12 PASS.

- [ ] **Step 3.6: Mypy + ruff + coverage**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/integrations/telegram.py
.venv/Scripts/ruff check src/unifi_manager/integrations/telegram.py tests/unit/test_integrations/
.venv/Scripts/pytest --cov=unifi_manager.integrations.telegram --cov-report=term-missing tests/unit/test_integrations/test_telegram.py
```
Expected: clean, coverage 90%+.

- [ ] **Step 3.7: Commit**

```bash
git add src/unifi_manager/integrations/telegram.py tests/unit/test_integrations/__init__.py tests/unit/test_integrations/test_telegram.py tests/fixtures/telegram_send_response.json
git commit -m "phase2: integrations/telegram.py — send_message + TelegramRateLimiter"
```

---

## Task 4: integrations/zabbix.py — LLD JSON

**Files:**
- Create: `src/unifi_manager/integrations/zabbix.py`
- Create: `tests/unit/test_integrations/test_zabbix.py`
- Create: `tests/fixtures/zabbix_lld_expected.json`

**Goal:** Zabbix Low-Level Discovery (LLD) формат для динамического создания триггеров на устройства. Output — stdout JSON для Zabbix external check. Преемник `_legacy/zabbix_unifi_stats.py`.

- [ ] **Step 4.1: Create fixture**

`tests/fixtures/zabbix_lld_expected.json`:

```json
{
  "data": [
    {
      "{#NAME}": "Restoran",
      "{#MAC}": "aa:bb:cc:dd:ee:01",
      "{#MODEL}": "UAP-AC-IW",
      "{#TYPE}": "uap",
      "{#STATE}": "1"
    },
    {
      "{#NAME}": "Core Switch",
      "{#MAC}": "aa:bb:cc:dd:ee:99",
      "{#MODEL}": "US-24-250W",
      "{#TYPE}": "usw",
      "{#STATE}": "1"
    }
  ]
}
```

- [ ] **Step 4.2: Write failing tests**

`tests/unit/test_integrations/test_zabbix.py`:

```python
"""Тесты для unifi_manager.integrations.zabbix."""
import json
from pathlib import Path

import pytest


@pytest.mark.fast
def test_lld_format_empty_list() -> None:
    """Пустой список устройств → {data: []}."""
    from unifi_manager.integrations.zabbix import format_lld

    assert format_lld([]) == {"data": []}


@pytest.mark.fast
def test_lld_format_access_point() -> None:
    """AccessPoint → запись с {#NAME}, {#MAC}, {#MODEL} (real_model!), {#TYPE}, {#STATE}."""
    from unifi_manager.domain.device import AccessPoint
    from unifi_manager.integrations.zabbix import format_lld

    ap = AccessPoint.model_validate({
        "mac": "aa:bb:cc:dd:ee:01",
        "name": "Restoran",
        "model": "U7IW",
        "sysid": 58759,  # → UAP-AC-IW
        "type": "uap",
        "state": 1,
    })
    result = format_lld([ap])
    assert len(result["data"]) == 1
    entry = result["data"][0]
    assert entry["{#NAME}"] == "Restoran"
    assert entry["{#MAC}"] == "aa:bb:cc:dd:ee:01"
    assert entry["{#MODEL}"] == "UAP-AC-IW"  # real_model, не reported "U7IW"
    assert entry["{#TYPE}"] == "uap"
    assert entry["{#STATE}"] == "1"


@pytest.mark.fast
def test_lld_format_switch() -> None:
    from unifi_manager.domain.device import Switch
    from unifi_manager.integrations.zabbix import format_lld

    sw = Switch.model_validate({
        "mac": "aa:bb:cc:dd:ee:99",
        "name": "Core Switch",
        "model": "US-24-250W",
        "type": "usw",
        "state": 1,
    })
    result = format_lld([sw])
    entry = result["data"][0]
    assert entry["{#TYPE}"] == "usw"
    assert entry["{#MODEL}"] == "US-24-250W"


@pytest.mark.fast
def test_lld_format_unnamed_uses_mac() -> None:
    """Если name=None — {#NAME} = MAC."""
    from unifi_manager.domain.device import AccessPoint
    from unifi_manager.integrations.zabbix import format_lld

    ap = AccessPoint.model_validate({
        "mac": "aa:bb:cc:dd:ee:01",
        "model": "U7IW",
        "type": "uap",
    })
    result = format_lld([ap])
    assert result["data"][0]["{#NAME}"] == "aa:bb:cc:dd:ee:01"


@pytest.mark.fast
def test_lld_full_response_matches_fixture(fixtures_dir: Path) -> None:
    """End-to-end: 2 устройства парсятся в expected JSON."""
    from unifi_manager.domain.device import AccessPoint, Switch
    from unifi_manager.integrations.zabbix import format_lld

    ap = AccessPoint.model_validate({
        "mac": "aa:bb:cc:dd:ee:01",
        "name": "Restoran",
        "model": "U7IW",
        "sysid": 58759,
        "type": "uap",
        "state": 1,
    })
    sw = Switch.model_validate({
        "mac": "aa:bb:cc:dd:ee:99",
        "name": "Core Switch",
        "model": "US-24-250W",
        "type": "usw",
        "state": 1,
    })
    result = format_lld([ap, sw])
    expected = json.loads(
        (fixtures_dir / "zabbix_lld_expected.json").read_text(encoding="utf-8")
    )
    assert result == expected
```

- [ ] **Step 4.3: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_integrations/test_zabbix.py -v --no-cov
```
Expected: ModuleNotFoundError.

- [ ] **Step 4.4: Implement**

`src/unifi_manager/integrations/zabbix.py`:

```python
"""Zabbix Low-Level Discovery (LLD) форматтер.

Output идёт в stdout как JSON, который Zabbix external check парсит и
автоматически создаёт хосты/триггеры на найденные устройства.

LLD формат: {"data": [{"{#KEY}": "value", ...}, ...]}
"""
from __future__ import annotations

from typing import Any

from unifi_manager.domain.device import Device


def format_lld(devices: list[Device]) -> dict[str, list[dict[str, str]]]:
    """Преобразовать список Device → LLD JSON для Zabbix.

    Для AP использует real_model (через SYSID_MAP), для других — reported_model.
    """
    entries: list[dict[str, str]] = []
    for device in devices:
        # real_model — computed_field на AccessPoint; на Switch его нет, fallback на reported_model
        model = getattr(device, "real_model", device.reported_model)
        entries.append({
            "{#NAME}": device.name or device.mac,
            "{#MAC}": device.mac,
            "{#MODEL}": model,
            "{#TYPE}": device.type or "",
            "{#STATE}": str(device.state),
        })
    return {"data": entries}


def format_lld_json(devices: list[Device]) -> str:
    """Convenience: format_lld + json.dumps for stdout."""
    import json
    return json.dumps(format_lld(devices), ensure_ascii=False)
```

- [ ] **Step 4.5: Run, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_integrations/test_zabbix.py -v --no-cov
```
Expected: 5 PASS.

- [ ] **Step 4.6: Mypy + ruff + coverage**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/integrations/zabbix.py
.venv/Scripts/ruff check src/unifi_manager/integrations/zabbix.py tests/unit/test_integrations/test_zabbix.py
.venv/Scripts/pytest --cov=unifi_manager.integrations.zabbix --cov-report=term-missing tests/unit/test_integrations/test_zabbix.py
```
Expected: clean, coverage 90%+.

- [ ] **Step 4.7: Commit**

```bash
git add src/unifi_manager/integrations/zabbix.py tests/unit/test_integrations/test_zabbix.py tests/fixtures/zabbix_lld_expected.json
git commit -m "phase2: integrations/zabbix.py — LLD JSON formatter"
```

---

## Task 5: services/audit.py — critical + status

**Files:**
- Create: `src/unifi_manager/services/audit.py`
- Create: `tests/unit/test_services/test_audit.py`
- Create: `tests/fixtures/audit_critical_sample.json`

**Goal:** Базовые методы AuditService — `critical()` (threshold checks, exit-code-friendly) и `status()` (read-only снимок). Используются audit команды Phase 4.

- [ ] **Step 5.1: Create fixture**

`tests/fixtures/audit_critical_sample.json`:

```json
{
  "meta": {"rc": "ok"},
  "data": [
    {
      "_id": "ap-1", "mac": "aa:bb:cc:dd:ee:01", "name": "Restoran",
      "model": "U7IW", "sysid": 58759, "type": "uap", "state": 1,
      "last_seen": 1747397800
    },
    {
      "_id": "ap-2", "mac": "aa:bb:cc:dd:ee:02", "name": "Lobby AP",
      "model": "U7PG2", "type": "uap", "state": 0,
      "last_seen": 1747390000
    },
    {
      "_id": "sw-1", "mac": "aa:bb:cc:dd:ee:99", "name": "Hot Switch",
      "model": "US-24-250W", "type": "usw", "state": 1,
      "general_temperature": 85,
      "port_table": []
    },
    {
      "_id": "sw-2", "mac": "aa:bb:cc:dd:ee:98", "name": "Normal Switch",
      "model": "US-24-250W", "type": "usw", "state": 1,
      "general_temperature": 45,
      "port_table": []
    }
  ]
}
```

- [ ] **Step 5.2: Write failing tests**

`tests/unit/test_services/test_audit.py`:

```python
"""Тесты для unifi_manager.services.audit.AuditService."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from unifi_manager.settings import Settings, ThresholdsSettings, UnifiAuthSettings


@pytest.fixture
def thresholds() -> ThresholdsSettings:
    return ThresholdsSettings(
        critical_temp_c=70,
        critical_poe_percent=90,
        high_cu_percent=50,
    )


@pytest.fixture
def audit_settings(thresholds: ThresholdsSettings) -> Settings:
    return Settings(
        unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="test"),
        thresholds=thresholds,
    )


@pytest.fixture
def mock_legacy_with_critical_devices(fixtures_dir: Path) -> Mock:
    """Mock LegacyClient возвращающий audit_critical_sample.json devices."""
    raw = json.loads((fixtures_dir / "audit_critical_sample.json").read_text(encoding="utf-8"))
    client = Mock()
    client.list_devices_raw.return_value = raw["data"]
    return client


# === AuditService.critical() ===

@pytest.mark.fast
def test_critical_returns_no_issues_on_clean_state(audit_settings: Settings) -> None:
    """Все устройства online + температура ОК → пустой list issues."""
    from unifi_manager.services.audit import AuditService

    client = Mock()
    client.list_devices_raw.return_value = [
        {"mac": "aa:bb", "model": "U7IW", "type": "uap", "state": 1,
         "name": "OK AP"},
    ]
    svc = AuditService(legacy_client=client, settings=audit_settings)
    issues = svc.critical()
    assert issues == []


@pytest.mark.fast
def test_critical_detects_offline_device(
    audit_settings: Settings, mock_legacy_with_critical_devices: Mock
) -> None:
    """state=0 (offline) → issue."""
    from unifi_manager.services.audit import AuditService

    svc = AuditService(legacy_client=mock_legacy_with_critical_devices,
                       settings=audit_settings)
    issues = svc.critical()
    offline_issues = [i for i in issues if i.issue_type == "offline"]
    assert len(offline_issues) == 1
    assert offline_issues[0].device_mac == "aa:bb:cc:dd:ee:02"


@pytest.mark.fast
def test_critical_detects_high_temperature(
    audit_settings: Settings, mock_legacy_with_critical_devices: Mock
) -> None:
    """general_temperature > critical_temp_c → issue."""
    from unifi_manager.services.audit import AuditService

    svc = AuditService(legacy_client=mock_legacy_with_critical_devices,
                       settings=audit_settings)
    issues = svc.critical()
    temp_issues = [i for i in issues if i.issue_type == "high_temperature"]
    assert len(temp_issues) == 1
    assert temp_issues[0].device_mac == "aa:bb:cc:dd:ee:99"
    assert temp_issues[0].context["temperature"] == 85


@pytest.mark.fast
def test_critical_skips_devices_under_threshold(
    audit_settings: Settings, mock_legacy_with_critical_devices: Mock
) -> None:
    """Normal Switch (temp=45) не должен попасть в issues."""
    from unifi_manager.services.audit import AuditService

    svc = AuditService(legacy_client=mock_legacy_with_critical_devices,
                       settings=audit_settings)
    issues = svc.critical()
    macs_with_issues = {i.device_mac for i in issues}
    assert "aa:bb:cc:dd:ee:98" not in macs_with_issues


# === AuditService.status() ===

@pytest.mark.fast
def test_status_returns_inventory_summary(audit_settings: Settings) -> None:
    """status() возвращает сводку: total devices, online, offline по типам."""
    from unifi_manager.services.audit import AuditService

    client = Mock()
    client.list_devices_raw.return_value = [
        {"mac": "aa:01", "model": "U7IW", "type": "uap", "state": 1},
        {"mac": "aa:02", "model": "U7IW", "type": "uap", "state": 1},
        {"mac": "aa:03", "model": "U7IW", "type": "uap", "state": 0},
        {"mac": "aa:99", "model": "US-24-250W", "type": "usw", "state": 1},
    ]
    svc = AuditService(legacy_client=client, settings=audit_settings)
    status = svc.status()
    assert status.total == 4
    assert status.online == 3
    assert status.offline == 1
    assert status.by_type == {"uap": 3, "usw": 1}


@pytest.mark.fast
def test_status_empty_inventory(audit_settings: Settings) -> None:
    from unifi_manager.services.audit import AuditService

    client = Mock()
    client.list_devices_raw.return_value = []
    svc = AuditService(legacy_client=client, settings=audit_settings)
    status = svc.status()
    assert status.total == 0
    assert status.online == 0
    assert status.offline == 0
```

- [ ] **Step 5.3: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_services/test_audit.py -v --no-cov
```
Expected: ModuleNotFoundError.

- [ ] **Step 5.4: Implement**

`src/unifi_manager/services/audit.py`:

```python
"""AuditService — мониторинг и аналитика UniFi сети.

Методы:
- critical() — exit-code-friendly список критических проблем для cron
- status() — read-only inventory snapshot
- light() — MAC duplicates / spoofing / client distribution (Task 6)
- full() — глубокий аудит используя оба API (Task 7)
- trends() — анализ исторических отчётов за N дней (Task 7)
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol

from unifi_manager.domain.device import AccessPoint, Switch
from unifi_manager.settings import Settings


class _DeviceClient(Protocol):
    """Минимальный интерфейс для LegacyClient (для type-checking тестов)."""

    def list_devices_raw(self) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class AuditIssue:
    """Критическая проблема найденная audit critical."""

    issue_type: str  # "offline" | "high_temperature" | "high_poe" | ...
    device_mac: str
    device_name: str
    severity: str  # "critical" | "warning"
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StatusSummary:
    """Inventory snapshot — для status команды."""

    total: int
    online: int
    offline: int
    by_type: dict[str, int]


class AuditService:
    """Бизнес-логика аудита. НЕ делает HTTP сам — использует переданный client."""

    def __init__(
        self,
        legacy_client: _DeviceClient,
        settings: Settings,
    ) -> None:
        self.client = legacy_client
        self.settings = settings

    def critical(self) -> list[AuditIssue]:
        """Найти критические проблемы (для cron + exit code 1 в Phase 4)."""
        issues: list[AuditIssue] = []
        thresholds = self.settings.thresholds

        for raw in self.client.list_devices_raw():
            device_type = raw.get("type")
            if device_type == "uap":
                ap = AccessPoint.model_validate(raw)
                issues.extend(self._check_device_state(ap.mac, ap.name, ap.state))
            elif device_type == "usw":
                sw = Switch.model_validate(raw)
                issues.extend(self._check_device_state(sw.mac, sw.name, sw.state))
                if sw.general_temperature is not None and \
                   sw.general_temperature > thresholds.critical_temp_c:
                    issues.append(AuditIssue(
                        issue_type="high_temperature",
                        device_mac=sw.mac,
                        device_name=sw.name or sw.mac,
                        severity="critical",
                        context={"temperature": sw.general_temperature,
                                 "threshold": thresholds.critical_temp_c},
                    ))

        return issues

    @staticmethod
    def _check_device_state(mac: str, name: str | None, state: int) -> list[AuditIssue]:
        if state == 1:  # online
            return []
        return [AuditIssue(
            issue_type="offline",
            device_mac=mac,
            device_name=name or mac,
            severity="critical",
            context={"state": state},
        )]

    def status(self) -> StatusSummary:
        """Inventory snapshot — кратко для оператора."""
        devices = self.client.list_devices_raw()
        total = len(devices)
        online = sum(1 for d in devices if d.get("state") == 1)
        offline = total - online
        type_counts = Counter(d.get("type", "unknown") for d in devices)
        return StatusSummary(
            total=total,
            online=online,
            offline=offline,
            by_type=dict(type_counts),
        )
```

- [ ] **Step 5.5: Run, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_services/test_audit.py -v --no-cov
```
Expected: 7 PASS (4 critical + 2 status + 1 setup).

- [ ] **Step 5.6: Mypy + ruff + coverage**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/services/audit.py
.venv/Scripts/ruff check src/unifi_manager/services/audit.py tests/unit/test_services/test_audit.py
```
Expected: clean.

- [ ] **Step 5.7: Commit**

```bash
git add src/unifi_manager/services/audit.py tests/unit/test_services/test_audit.py tests/fixtures/audit_critical_sample.json
git commit -m "phase2: services/audit.py — AuditService.critical + .status"
```

---

## Task 6: services/audit.py — light (MAC duplicates + spoofing)

**Files:**
- Modify: `src/unifi_manager/services/audit.py` (add `.light()` method)
- Modify: `tests/unit/test_services/test_audit.py` (add light tests)
- Create: `tests/fixtures/mac_duplicates_sample.json`

**Goal:** Аудит дубликатов MAC, locally-administered MAC (spoof indicator), перекосов клиентов на AP. Преемник `_legacy/audit_unifi.py`.

- [ ] **Step 6.1: Create fixture**

`tests/fixtures/mac_duplicates_sample.json`:

```json
{
  "meta": {"rc": "ok"},
  "data": [
    {"mac": "11:22:33:44:55:66", "hostname": "laptop-alice", "ip": "10.3.0.10", "ap_mac": "ap-1"},
    {"mac": "11:22:33:44:55:66", "hostname": "duplicate-mac", "ip": "10.3.0.99", "ap_mac": "ap-2"},
    {"mac": "02:00:00:11:22:33", "hostname": "spoofed-device", "ip": "10.3.0.50", "ap_mac": "ap-1"},
    {"mac": "aa:bb:cc:dd:ee:ff", "hostname": "normal-laptop", "ip": "10.3.0.20", "ap_mac": "ap-1"},
    {"mac": "11:11:11:22:22:22", "hostname": "client-x", "ip": "10.3.0.30", "ap_mac": "ap-1"}
  ]
}
```

- [ ] **Step 6.2: Add tests to test_audit.py**

В `tests/unit/test_services/test_audit.py` добавь:

```python
# === AuditService.light() — MAC analysis ===

@pytest.mark.fast
def test_light_detects_duplicate_macs(audit_settings: Settings,
                                        fixtures_dir: Path) -> None:
    """Два клиента с одинаковым MAC → duplicate issue."""
    from unifi_manager.services.audit import AuditService

    raw = json.loads(
        (fixtures_dir / "mac_duplicates_sample.json").read_text(encoding="utf-8")
    )
    client = Mock()
    client.list_clients_raw.return_value = raw["data"]
    client.list_devices_raw.return_value = []

    svc = AuditService(legacy_client=client, settings=audit_settings)
    report = svc.light()

    dup_macs = [d.mac for d in report.duplicate_macs]
    assert "11:22:33:44:55:66" in dup_macs


@pytest.mark.fast
def test_light_detects_locally_administered_mac(audit_settings: Settings,
                                                  fixtures_dir: Path) -> None:
    """MAC с bit 0x02 в первом байте — locally administered (potential spoof)."""
    from unifi_manager.services.audit import AuditService

    raw = json.loads(
        (fixtures_dir / "mac_duplicates_sample.json").read_text(encoding="utf-8")
    )
    client = Mock()
    client.list_clients_raw.return_value = raw["data"]
    client.list_devices_raw.return_value = []

    svc = AuditService(legacy_client=client, settings=audit_settings)
    report = svc.light()

    spoof_macs = [s.mac for s in report.locally_administered]
    assert "02:00:00:11:22:33" in spoof_macs


@pytest.mark.fast
def test_light_counts_clients_per_ap(audit_settings: Settings,
                                       fixtures_dir: Path) -> None:
    """Сколько клиентов на каждой AP — для выявления перекосов."""
    from unifi_manager.services.audit import AuditService

    raw = json.loads(
        (fixtures_dir / "mac_duplicates_sample.json").read_text(encoding="utf-8")
    )
    client = Mock()
    client.list_clients_raw.return_value = raw["data"]
    client.list_devices_raw.return_value = []

    svc = AuditService(legacy_client=client, settings=audit_settings)
    report = svc.light()

    assert report.clients_per_ap["ap-1"] == 4  # alice, spoof, normal, client-x
    assert report.clients_per_ap["ap-2"] == 1  # duplicate-mac
```

- [ ] **Step 6.3: Add implementation to audit.py**

В `src/unifi_manager/services/audit.py`:

```python
# Add to imports section:
from unifi_manager.domain.client import WirelessClient


# Update _DeviceClient Protocol to add list_clients_raw:
class _DeviceClient(Protocol):
    """Минимальный интерфейс для LegacyClient (для type-checking тестов)."""

    def list_devices_raw(self) -> list[dict[str, Any]]: ...
    def list_clients_raw(self) -> list[dict[str, Any]]: ...


# Add dataclasses (после AuditIssue/StatusSummary):

@dataclass(frozen=True)
class DuplicateMAC:
    """Дубликат MAC — несколько клиентов с одинаковым MAC."""

    mac: str
    hostnames: list[str]


@dataclass(frozen=True)
class SpoofedMAC:
    """Locally-administered MAC — потенциальный spoof."""

    mac: str
    hostname: str | None
    ap_mac: str | None


@dataclass(frozen=True)
class LightAuditReport:
    """Результат audit light — MAC analysis + client distribution."""

    duplicate_macs: list[DuplicateMAC]
    locally_administered: list[SpoofedMAC]
    clients_per_ap: dict[str, int]


# Add method to AuditService:

    def light(self) -> "LightAuditReport":
        """MAC duplicates, locally-administered (spoof), client distribution."""
        clients_raw = self.client.list_clients_raw()

        # Parse all clients via Pydantic for type safety
        clients = [WirelessClient.model_validate(c) for c in clients_raw]

        # Duplicates
        mac_to_clients: dict[str, list[WirelessClient]] = {}
        for c in clients:
            mac_to_clients.setdefault(c.mac, []).append(c)
        duplicates = [
            DuplicateMAC(
                mac=mac,
                hostnames=[cl.hostname or "<no hostname>" for cl in cls],
            )
            for mac, cls in mac_to_clients.items()
            if len(cls) > 1
        ]

        # Locally administered (bit 0x02 в первом байте)
        spoofed = [
            SpoofedMAC(mac=c.mac, hostname=c.hostname, ap_mac=c.ap_mac)
            for c in clients
            if self._is_locally_administered(c.mac)
        ]

        # Clients per AP
        per_ap: dict[str, int] = {}
        for c in clients:
            if c.ap_mac:
                per_ap[c.ap_mac] = per_ap.get(c.ap_mac, 0) + 1

        return LightAuditReport(
            duplicate_macs=duplicates,
            locally_administered=spoofed,
            clients_per_ap=per_ap,
        )

    @staticmethod
    def _is_locally_administered(mac: str) -> bool:
        """True если первый байт MAC имеет bit 0x02 (locally administered)."""
        try:
            first_byte = int(mac.split(":")[0], 16)
            return bool(first_byte & 0x02)
        except (ValueError, IndexError):
            return False
```

- [ ] **Step 6.4: Run, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_services/test_audit.py -v --no-cov
```
Expected: 10 PASS (7 existing + 3 new light tests).

- [ ] **Step 6.5: Mypy + ruff**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/services/audit.py
.venv/Scripts/ruff check src/unifi_manager/services/audit.py tests/unit/test_services/test_audit.py
```
Expected: clean.

- [ ] **Step 6.6: Commit**

```bash
git add src/unifi_manager/services/audit.py tests/unit/test_services/test_audit.py tests/fixtures/mac_duplicates_sample.json
git commit -m "phase2: services/audit.py — AuditService.light (MAC duplicates + spoofing)"
```

---

## Task 7: services/audit.py — full + trends

**Files:**
- Modify: `src/unifi_manager/services/audit.py` (add `.full()` + `.trends()`)
- Modify: `tests/unit/test_services/test_audit.py` (add tests)
- Create: `tests/fixtures/trends_report_day1.txt`
- Create: `tests/fixtures/trends_report_day2.txt`

**Goal:** Глубокий аудит используя оба API (Integration + Legacy параллельно) + анализ исторических текстовых отчётов из `paths.reports_dir`.

- [ ] **Step 7.1: Create trends fixtures**

Реальный формат — простой текст с metric строками:

`tests/fixtures/trends_report_day1.txt`:

```
=== UniFi Audit Report 2026-05-14 ===
Total devices: 270
Online: 268
Offline: 2
PoE total: 450W / 720W (62.5%)
Critical issues: 1
  - aa:bb:cc:dd:ee:01 Restoran offline
```

`tests/fixtures/trends_report_day2.txt`:

```
=== UniFi Audit Report 2026-05-15 ===
Total devices: 271
Online: 269
Offline: 2
PoE total: 460W / 720W (63.9%)
Critical issues: 0
```

- [ ] **Step 7.2: Add tests to test_audit.py**

```python
# === AuditService.full() — both APIs ===

@pytest.mark.fast
def test_full_uses_both_apis(audit_settings: Settings) -> None:
    """full() запрашивает devices через оба клиента и объединяет данные."""
    from unifi_manager.services.audit import AuditService

    legacy_client = Mock()
    legacy_client.list_devices_raw.return_value = [
        {"mac": "aa:01", "model": "U7IW", "type": "uap", "state": 1,
         "general_temperature": 40},
    ]
    integration_client = Mock()
    integration_client.list_devices_raw.return_value = [
        {"id": "x", "macAddress": "aa:01", "model": "U7IW", "state": "ONLINE",
         "ipAddress": "10.3.0.10"},
    ]

    svc = AuditService(
        legacy_client=legacy_client,
        integration_client=integration_client,
        settings=audit_settings,
    )
    report = svc.full()
    assert len(report.devices) == 1
    # Объединённое: mac + ip (from Integration) + temp (from Legacy)
    assert report.devices[0]["mac"] == "aa:01"
    assert report.devices[0].get("ip") == "10.3.0.10" or \
           report.devices[0].get("ipAddress") == "10.3.0.10"


@pytest.mark.fast
def test_full_works_without_integration_client(audit_settings: Settings) -> None:
    """Если integration_client=None — работаем только с Legacy данными."""
    from unifi_manager.services.audit import AuditService

    legacy_client = Mock()
    legacy_client.list_devices_raw.return_value = [
        {"mac": "aa:01", "model": "U7IW", "type": "uap", "state": 1},
    ]

    svc = AuditService(
        legacy_client=legacy_client,
        integration_client=None,
        settings=audit_settings,
    )
    report = svc.full()
    assert len(report.devices) == 1


# === AuditService.trends() — historical analysis ===

@pytest.mark.fast
def test_trends_parses_recent_reports(audit_settings: Settings,
                                        fixtures_dir: Path) -> None:
    """trends читает .txt файлы из reports_dir, парсит ключевые метрики."""
    from unifi_manager.services.audit import AuditService

    # Symlink fixtures в settings.paths.reports_dir для теста
    # (или подменяем reports_dir на fixtures_dir)
    audit_settings.paths.reports_dir = fixtures_dir

    client = Mock()
    svc = AuditService(legacy_client=client, settings=audit_settings)
    report = svc.trends(days=7)

    # Минимум 2 файла найдены (day1, day2)
    assert len(report.data_points) >= 2
    # Проверка что числа извлеклись
    totals = [d.get("total") for d in report.data_points]
    assert 270 in totals
    assert 271 in totals


@pytest.mark.fast
def test_trends_empty_directory(audit_settings: Settings, tmp_path: Path) -> None:
    """Пустая reports_dir → пустой report (не ошибка)."""
    from unifi_manager.services.audit import AuditService

    audit_settings.paths.reports_dir = tmp_path
    client = Mock()
    svc = AuditService(legacy_client=client, settings=audit_settings)
    report = svc.trends(days=7)
    assert report.data_points == []
```

- [ ] **Step 7.3: Add implementation**

В `src/unifi_manager/services/audit.py`:

```python
# Add imports:
import re
from pathlib import Path


# Add dataclasses:

@dataclass(frozen=True)
class FullAuditReport:
    """Результат audit full — объединённые данные из обоих API."""

    devices: list[dict[str, Any]]


@dataclass(frozen=True)
class TrendsReport:
    """Результат audit trends — точки данных из исторических отчётов."""

    data_points: list[dict[str, Any]]  # каждый dict — отдельный day report


# Update __init__ to accept optional integration_client:
class AuditService:
    def __init__(
        self,
        legacy_client: "_DeviceClient",
        settings: Settings,
        *,
        integration_client: "_DeviceClient | None" = None,
    ) -> None:
        self.client = legacy_client
        self.integration_client = integration_client
        self.settings = settings


# Add methods:

    def full(self) -> FullAuditReport:
        """Глубокий аудит — объединяет данные из обоих API.

        Если integration_client=None, использует только Legacy.
        """
        legacy_devices = self.client.list_devices_raw()

        if self.integration_client is None:
            return FullAuditReport(devices=legacy_devices)

        integration_devices = self.integration_client.list_devices_raw()
        merged = self._merge_devices(legacy_devices, integration_devices)
        return FullAuditReport(devices=merged)

    @staticmethod
    def _merge_devices(
        legacy: list[dict[str, Any]],
        integration: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge by mac: Legacy data + Integration data → один dict per device."""
        # Integration uses 'macAddress', Legacy uses 'mac'
        by_mac: dict[str, dict[str, Any]] = {}
        for d in legacy:
            mac = d.get("mac")
            if mac:
                by_mac[mac] = dict(d)
        for d in integration:
            mac = d.get("macAddress") or d.get("mac")
            if mac:
                if mac in by_mac:
                    # Add integration-specific fields (ipAddress, etc.)
                    for k, v in d.items():
                        if k not in by_mac[mac]:
                            by_mac[mac][k] = v
                else:
                    by_mac[mac] = dict(d)
        return list(by_mac.values())

    def trends(self, *, days: int = 7) -> TrendsReport:
        """Анализ исторических текстовых отчётов из paths.reports_dir."""
        reports_dir = self.settings.paths.reports_dir
        if not reports_dir.is_dir():
            return TrendsReport(data_points=[])

        data_points: list[dict[str, Any]] = []
        for report_file in sorted(reports_dir.glob("*.txt")):
            data_points.append(self._parse_report(report_file))

        # Простой crop по days (если файлов больше, берём последние days)
        return TrendsReport(data_points=data_points[-days:])

    @staticmethod
    def _parse_report(path: Path) -> dict[str, Any]:
        """Извлечь ключевые метрики из текстового отчёта."""
        text = path.read_text(encoding="utf-8")
        result: dict[str, Any] = {"file": path.name}

        # "Total devices: 270" → result["total"] = 270
        for label, key in [("Total devices", "total"),
                            ("Online", "online"),
                            ("Offline", "offline"),
                            ("Critical issues", "critical_issues")]:
            match = re.search(rf"{label}:\s*(\d+)", text)
            if match:
                result[key] = int(match.group(1))

        # PoE percent
        poe_match = re.search(r"PoE total:.*?\(([\d.]+)%\)", text)
        if poe_match:
            result["poe_percent"] = float(poe_match.group(1))

        return result
```

- [ ] **Step 7.4: Run, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_services/test_audit.py -v --no-cov
```
Expected: 14 PASS (10 existing + 4 new).

- [ ] **Step 7.5: Mypy + ruff + coverage**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/services/audit.py
.venv/Scripts/ruff check src/unifi_manager/services/audit.py tests/unit/test_services/test_audit.py
.venv/Scripts/pytest --cov=unifi_manager.services.audit --cov-report=term-missing tests/unit/test_services/test_audit.py
```
Expected: clean, coverage 85%+ для всего audit.py.

- [ ] **Step 7.6: Commit**

```bash
git add src/unifi_manager/services/audit.py tests/unit/test_services/test_audit.py tests/fixtures/trends_report_day1.txt tests/fixtures/trends_report_day2.txt
git commit -m "phase2: services/audit.py — AuditService.full + .trends"
```

---

## Task 8: services/export.py — CSV/JSON exports

**Files:**
- Create: `src/unifi_manager/services/export.py`
- Create: `tests/unit/test_services/test_export.py`

**Goal:** Экспорт clients и devices в CSV/JSON. Используется CLI команды Phase 4 (`unifi-mgr export clients --format csv`). Также — тест что `AccessPoint.real_model` присутствует в `model_dump()` output (forward concern из Phase 1 review).

- [ ] **Step 8.1: Write failing tests**

`tests/unit/test_services/test_export.py`:

```python
"""Тесты для unifi_manager.services.export.ExportService."""
import csv
import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.mark.fast
def test_export_clients_csv_format() -> None:
    """CSV содержит header + одну строку на client."""
    from unifi_manager.services.export import ExportService

    client = Mock()
    client.list_clients_raw.return_value = [
        {"mac": "11:22:33:44:55:66", "hostname": "laptop-1", "ip": "10.0.0.1"},
        {"mac": "aa:bb:cc:dd:ee:ff", "hostname": "phone-1", "ip": "10.0.0.2"},
    ]

    svc = ExportService(legacy_client=client)
    output = io.StringIO()
    svc.export_clients(output=output, fmt="csv")
    output.seek(0)

    reader = csv.DictReader(output)
    rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["mac"] == "11:22:33:44:55:66"
    assert rows[0]["hostname"] == "laptop-1"


@pytest.mark.fast
def test_export_clients_json_format() -> None:
    from unifi_manager.services.export import ExportService

    client = Mock()
    client.list_clients_raw.return_value = [
        {"mac": "11:22:33:44:55:66", "hostname": "laptop-1"},
    ]

    svc = ExportService(legacy_client=client)
    output = io.StringIO()
    svc.export_clients(output=output, fmt="json")
    output.seek(0)

    data = json.loads(output.read())
    assert len(data) == 1
    assert data[0]["mac"] == "11:22:33:44:55:66"


@pytest.mark.fast
def test_export_devices_csv_includes_real_model() -> None:
    """REGRESSION (forward concern from Phase 1 review):
    AccessPoint.real_model должно появиться в model_dump → CSV."""
    from unifi_manager.services.export import ExportService

    client = Mock()
    client.list_devices_raw.return_value = [
        {"mac": "aa:bb:cc:dd:ee:01", "name": "Restoran",
         "model": "U7IW", "sysid": 58759, "type": "uap"},  # → UAP-AC-IW
    ]

    svc = ExportService(legacy_client=client)
    output = io.StringIO()
    svc.export_devices(output=output, fmt="csv")
    output.seek(0)

    content = output.read()
    assert "real_model" in content  # column header
    assert "UAP-AC-IW" in content  # real_model value


@pytest.mark.fast
def test_export_devices_json_includes_real_model() -> None:
    """Same regression check для JSON."""
    from unifi_manager.services.export import ExportService

    client = Mock()
    client.list_devices_raw.return_value = [
        {"mac": "aa:bb:cc:dd:ee:01", "name": "Restoran",
         "model": "U7IW", "sysid": 58759, "type": "uap"},
    ]

    svc = ExportService(legacy_client=client)
    output = io.StringIO()
    svc.export_devices(output=output, fmt="json")
    output.seek(0)

    data = json.loads(output.read())
    assert data[0]["real_model"] == "UAP-AC-IW"


@pytest.mark.fast
def test_export_invalid_format_raises() -> None:
    from unifi_manager.services.export import ExportService

    client = Mock()
    client.list_clients_raw.return_value = []

    svc = ExportService(legacy_client=client)
    with pytest.raises(ValueError, match="unsupported format"):
        svc.export_clients(output=io.StringIO(), fmt="xml")


@pytest.mark.fast
def test_export_clients_empty_list_csv() -> None:
    """Empty list → CSV с одним header (no rows)."""
    from unifi_manager.services.export import ExportService

    client = Mock()
    client.list_clients_raw.return_value = []

    svc = ExportService(legacy_client=client)
    output = io.StringIO()
    svc.export_clients(output=output, fmt="csv")
    output.seek(0)

    content = output.read()
    # CSV empty list — может быть пустая строка или только header
    # Принимаем оба варианта; тест что не падает
    assert content is not None


@pytest.mark.fast
def test_export_clients_empty_list_json() -> None:
    from unifi_manager.services.export import ExportService

    client = Mock()
    client.list_clients_raw.return_value = []

    svc = ExportService(legacy_client=client)
    output = io.StringIO()
    svc.export_clients(output=output, fmt="json")
    output.seek(0)

    data = json.loads(output.read())
    assert data == []
```

- [ ] **Step 8.2: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_services/test_export.py -v --no-cov
```
Expected: ModuleNotFoundError.

- [ ] **Step 8.3: Implement**

`src/unifi_manager/services/export.py`:

```python
"""ExportService — CSV/JSON выгрузка clients и devices.

Devices экспортируются через AccessPoint / Switch модели — это значит
real_model (computed_field SYSID_MAP) попадает в output (regression-prone
по audit fix).
"""
from __future__ import annotations

import csv
import json
from typing import IO, Any, Literal, Protocol

from unifi_manager.domain.client import WirelessClient
from unifi_manager.domain.device import AccessPoint, Switch


Format = Literal["csv", "json"]


class _DeviceClient(Protocol):
    def list_devices_raw(self) -> list[dict[str, Any]]: ...
    def list_clients_raw(self) -> list[dict[str, Any]]: ...


class ExportService:
    """Экспорт типизированных данных в CSV или JSON."""

    def __init__(self, legacy_client: _DeviceClient) -> None:
        self.client = legacy_client

    def export_clients(self, *, output: IO[str], fmt: Format) -> None:
        """Выгрузить всех клиентов site."""
        clients = [
            WirelessClient.model_validate(c).model_dump(mode="json")
            for c in self.client.list_clients_raw()
        ]
        self._write(output, clients, fmt)

    def export_devices(self, *, output: IO[str], fmt: Format) -> None:
        """Выгрузить все устройства (с real_model для AP)."""
        rows: list[dict[str, Any]] = []
        for raw in self.client.list_devices_raw():
            device_type = raw.get("type")
            if device_type == "uap":
                rows.append(AccessPoint.model_validate(raw).model_dump(mode="json"))
            elif device_type == "usw":
                rows.append(Switch.model_validate(raw).model_dump(mode="json"))
            else:
                rows.append(raw)
        self._write(output, rows, fmt)

    @staticmethod
    def _write(output: IO[str], rows: list[dict[str, Any]], fmt: Format) -> None:
        if fmt == "json":
            json.dump(rows, output, ensure_ascii=False, indent=2, default=str)
        elif fmt == "csv":
            if not rows:
                return  # empty CSV — no header to write
            # Объединяем все ключи для полного header (некоторые device могут не иметь полей)
            fieldnames: list[str] = []
            seen: set[str] = set()
            for row in rows:
                for k in row:
                    if k not in seen:
                        seen.add(k)
                        fieldnames.append(k)
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: _stringify(v) for k, v in row.items()})
        else:
            raise ValueError(f"unsupported format: {fmt!r}")


def _stringify(value: Any) -> str:
    """Преобразовать значение для CSV cell (lists/dicts → JSON string)."""
    if isinstance(value, list | dict):
        return json.dumps(value, ensure_ascii=False, default=str)
    if value is None:
        return ""
    return str(value)
```

- [ ] **Step 8.4: Run, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_services/test_export.py -v --no-cov
```
Expected: 7 PASS.

- [ ] **Step 8.5: Mypy + ruff + coverage**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/services/export.py
.venv/Scripts/ruff check src/unifi_manager/services/export.py tests/unit/test_services/test_export.py
.venv/Scripts/pytest --cov=unifi_manager.services.export --cov-report=term-missing tests/unit/test_services/test_export.py
```
Expected: clean, coverage 90%+.

- [ ] **Step 8.6: Commit**

```bash
git add src/unifi_manager/services/export.py tests/unit/test_services/test_export.py
git commit -m "phase2: services/export.py — CSV/JSON export with real_model"
```

---

## Task 9: CI update — mypy strict expand для Phase 2

**Files:**
- Modify: `.github/workflows/ci.yml`

**Goal:** Расширить mypy --strict scope на services + integrations.

- [ ] **Step 9.1: Update ci.yml**

Найти секцию "Mypy strict (core)" — она была после Phase 1:
```yaml
        run: |
          mypy --strict \
            src/unifi_manager/settings.py \
            src/unifi_manager/logging_config.py \
            src/unifi_manager/clients \
            src/unifi_manager/domain \
            src/unifi_manager/utils
```

Заменить на:
```yaml
        run: |
          mypy --strict \
            src/unifi_manager/settings.py \
            src/unifi_manager/logging_config.py \
            src/unifi_manager/clients \
            src/unifi_manager/domain \
            src/unifi_manager/utils \
            src/unifi_manager/services \
            src/unifi_manager/integrations
```

И обновить комментарий выше:
```yaml
      - name: Mypy strict (core)
        # Phase 2: settings, logging_config, clients, domain, utils, services, integrations.
        # diagnostics добавится в Phase 4.
        run: |
          ...
```

- [ ] **Step 9.2: Verify локально**

```bash
.venv/Scripts/mypy --strict \
  src/unifi_manager/settings.py \
  src/unifi_manager/logging_config.py \
  src/unifi_manager/clients \
  src/unifi_manager/domain \
  src/unifi_manager/utils \
  src/unifi_manager/services \
  src/unifi_manager/integrations
```
Expected: `Success: no issues found in N source files`.

- [ ] **Step 9.3: Pre-commit full**

```bash
.venv/Scripts/pre-commit run --all-files
```
Expected: all PASS.

- [ ] **Step 9.4: Full suite + coverage**

```bash
.venv/Scripts/pytest --cov=unifi_manager --cov-report=term-missing --cov-fail-under=90
```
Expected: 140+ tests, coverage 90%+.

- [ ] **Step 9.5: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "phase2: CI mypy --strict expanded to services + integrations"
```

---

## Task 10: Final acceptance + phase-2-complete tag

- [ ] **Step 10.1: Fresh venv install + full acceptance**

```bash
rm -rf .venv-acceptance
py -3.12 -m venv .venv-acceptance
.venv-acceptance/Scripts/pip install -e ".[dev]"

.venv-acceptance/Scripts/pytest --cov=unifi_manager --cov-report=term-missing --cov-fail-under=90 -v
```
Expected: 140+ tests PASS, coverage 90%+.

- [ ] **Step 10.2: CLI smoke (regression check)**

```bash
.venv-acceptance/Scripts/unifi-mgr --version
.venv-acceptance/Scripts/unifi-mgr --help
```
Expected: version + 9 subcommand groups (как в Phase 0/1).

- [ ] **Step 10.3: Mypy strict — все core+services+integrations**

```bash
.venv-acceptance/Scripts/mypy --strict \
  src/unifi_manager/settings.py \
  src/unifi_manager/logging_config.py \
  src/unifi_manager/clients \
  src/unifi_manager/domain \
  src/unifi_manager/utils \
  src/unifi_manager/services \
  src/unifi_manager/integrations
```
Expected: Success.

- [ ] **Step 10.4: Cleanup acceptance venv**

```bash
rm -rf .venv-acceptance
```

- [ ] **Step 10.5: Create phase-2-complete tag**

```bash
git tag -d phase-2-complete 2>/dev/null || true
git tag -a phase-2-complete -m "Phase 2 (Services + Integrations) complete: audit, export, lock, notify, telegram, zabbix"
git describe --tags
```

---

## Definition of Done — Phase 2

| Check | Command | Expected |
|---|---|---|
| All tests pass | `pytest --no-cov` | 140+ tests |
| Coverage ≥ 90% | `pytest --cov-fail-under=90` | PASS |
| Mypy strict для всех | `mypy --strict src/unifi_manager/{settings.py,logging_config.py,clients,domain,utils,services,integrations}` | Success |
| Ruff clean | `ruff check .` | All checks passed |
| Pre-commit green | `pre-commit run --all-files` | all PASS |
| AccessPoint.real_model в model_dump | test_export_devices_*_includes_real_model | PASS |
| Telegram rate-limit | test_rate_limiter_* | PASS |
| AlertHistory dedup | test_alert_history_* | PASS |
| FileLock atomic | test_lock_blocks_concurrent_* | PASS |
| Tag created | `git tag -l phase-2-complete` | exists |

**Not in this phase:**
- ❌ RestartService — Phase 3
- ❌ Реальные CLI commands — Phase 4
- ❌ Cron switch — Phase 5
- ❌ Legacy scripts trogаются — Phase 5/6

---

## After Phase 2

`superpowers:writing-plans` для Phase 3:
- `services/restart.py` — RestartService (auto + profile, cooldown, history, priority sort)
- `services/restart.py:auto` — пrior проблемных AP, миграция формата restart_history.json
- `services/restart.py:profile` — фильтрация по profile.filter_names/patterns
- Hypothesis-тесты на cooldown edge cases
- Самая опасная фаза — затрагивает реальные restart commands
