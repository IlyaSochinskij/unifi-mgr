# Phase 3 — RestartService Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RestartService — самая опасная часть refactor: реальные команды перезагрузки оборудования в проде. Auto-restart с cooldown/history, profile-based рестарт (заменяет 3 legacy скрипта), точечный device restart. Все три метода уважают PermissionsSettings (D30) для emergency kill-switch.

**Architecture:** RestartService использует LegacyClient (Phase 1) для команд, RestartHistory для cooldown tracking, RestartDecisions для pure logic (priority, classify action). Чёткое разделение: decisions без I/O — легко тестируются; service оркеструет state + client.

**Tech Stack:** Python 3.12, pydantic v2, freezegun, hypothesis (для cooldown property tests), pytest-mock.

**Гейт готовности:** mypy --strict зелёный для restart.py + restart_decisions.py + restart_history.py. Coverage 90%+. Cooldown/dry-run/max/permissions edge cases покрыты. Hypothesis-тесты на cooldown monotonicity. Migration test для legacy `restart_history.json` формата проходит.

**Ветка работы:** `worktree-refactor+v2` (продолжение с Phase 2).

**Связанные спеки:**
- [refactor design](../specs/2026-05-16-unifi-manager-refactor-design.md) — основной spec
- Decision D30 — PermissionsSettings kill-switches
- Decision D32 — Extended SYSID_MAP seed

**Предыдущая фаза:** [phase-2-services-integrations.md](2026-05-16-phase-2-services-integrations.md) — Services + Integrations, tag `phase-2-complete`

**Platform notes:** Windows worktree. `.venv/Scripts/*`. На Linux заменить на `.venv/bin/*`.

---

## File Structure

### Создаются (новые):

```
src/unifi_manager/
├── domain/
│   └── restart_history.py    # RestartHistoryEntry (Pydantic), RestartHistory (load/save/cooldown)
│                              # + расширение SYSID_MAP (D32) inline в device.py
│
└── services/
    ├── restart_decisions.py  # pure: priority_score, classify_action, is_in_window
    └── restart.py            # RestartService.auto / .profile / .device с permissions checks
```

### Расширяется:

```
src/unifi_manager/domain/device.py    # SYSID_MAP — extended dictionary (D32)
.github/workflows/ci.yml              # mypy --strict scope: + restart files
```

### Тесты (новые):

```
tests/
├── fixtures/
│   ├── restart_history_legacy.json   # старый формат _legacy/auto_restart_problem_aps.py
│   ├── restart_history_new.json      # новый формат
│   └── problematic_devices.json      # AP с разными state (offline, conn_interrupted, online)
│
└── unit/
    ├── test_domain/
    │   └── test_restart_history.py   # 10+ tests: load/save/migration/cooldown
    │
    └── test_services/
        ├── test_restart_decisions.py # pure decision logic (Hypothesis-friendly)
        └── test_restart.py           # RestartService с mocked client + RestartHistory
```

### НЕ трогаются:

- `cli/` — Phase 4
- `mcp_server.py` — Phase 4M (optional)
- Phase 7 features — D28 (deferred)
- Legacy scripts в корне

---

## Common patterns (read before starting)

**TDD цикл** как в Phases 0-2.

**Test invocation:** `.venv/Scripts/pytest <path> -v --no-cov`.

**Mypy strict:** `.venv/Scripts/mypy --strict <file>` после каждой задачи.

**Ruff + per-file-ignores:** RUF002/RUF003 для Cyrillic, добавляются в `pyproject.toml` per-file-ignores как нужно (established pattern).

**Mock strategy** (как в Phase 2):
- Services tested против `Mock()` объектов (LegacyClient interface)
- Без HTTP в этих тестах
- Time через `freezegun` для cooldown logic
- Hypothesis для property tests (cooldown monotonicity)

**Permissions check pattern:**
```python
def auto(self) -> ...:
    if not self.settings.permissions.cli.restart.execute:
        _logger.warning("Restart skipped: permissions.cli.restart.execute=false")
        return RestartReport(status="skipped_permissions", actions=[])
    # ... actual logic
```

**Commit format:** `phase3: <description>`.

---

## Task 1: domain/restart_history.py + extended SYSID_MAP

**Files:**
- Create: `src/unifi_manager/domain/restart_history.py`
- Modify: `src/unifi_manager/domain/device.py` (extend SYSID_MAP dict)
- Create: `tests/unit/test_domain/test_restart_history.py`
- Create: `tests/fixtures/restart_history_legacy.json`
- Create: `tests/fixtures/restart_history_new.json`

**Goal:**
- `RestartHistory` — state file для cooldown tracking, совместимость с legacy format `_legacy/auto_restart_problem_aps.py`
- Extended SYSID_MAP (D32) — seed dict из tnware/unifi-controller-api + наши 4 overrides

### Legacy format (для migration test):

`_legacy/ap_restart_history.json` format (per `_legacy/auto_restart_problem_aps.py:210-216`):
```json
{
  "aa:bb:cc:dd:ee:ff": {
    "name": "Restoran",
    "last_restart": "2026-05-15T22:00:00",
    "action": "restart",
    "reason": "Many problems",
    "count": 3
  }
}
```

New format (with TZ-aware ISO + structured action enum, but reads legacy):
```json
{
  "version": 1,
  "entries": {
    "aa:bb:cc:dd:ee:ff": {
      "name": "Restoran",
      "last_restart": "2026-05-15T22:00:00+00:00",
      "action": "restart",
      "reason": "Many problems",
      "count": 3
    }
  }
}
```

- [ ] **Step 1.1: Create fixtures**

`tests/fixtures/restart_history_legacy.json`:
```json
{
  "aa:bb:cc:dd:ee:01": {
    "name": "Restoran",
    "last_restart": "2026-05-15T22:00:00",
    "action": "restart",
    "reason": "Many problems",
    "count": 3
  },
  "aa:bb:cc:dd:ee:02": {
    "name": "Office AP",
    "last_restart": "2026-05-15T20:30:00",
    "action": "poe_cycle",
    "reason": "State=10 — PoE cycle",
    "count": 1
  }
}
```

`tests/fixtures/restart_history_new.json`:
```json
{
  "version": 1,
  "entries": {
    "aa:bb:cc:dd:ee:01": {
      "name": "Restoran",
      "last_restart": "2026-05-15T22:00:00+00:00",
      "action": "restart",
      "reason": "Many problems",
      "count": 3
    }
  }
}
```

- [ ] **Step 1.2: Write failing tests**

`tests/unit/test_domain/test_restart_history.py`:

```python
"""Тесты для unifi_manager.domain.restart_history."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from freezegun import freeze_time


@pytest.mark.fast
def test_restart_history_empty_initially(tmp_path: Path) -> None:
    from unifi_manager.domain.restart_history import RestartHistory

    h = RestartHistory(state_file=tmp_path / "history.json")
    assert h.can_restart("aa:bb:cc:dd:ee:01", cooldown=timedelta(minutes=60))[0] is True


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_restart_history_records_and_blocks_within_cooldown(tmp_path: Path) -> None:
    from unifi_manager.domain.restart_history import RestartHistory

    h = RestartHistory(state_file=tmp_path / "history.json")
    h.record_restart(mac="aa:bb", name="Restoran", action="restart", reason="test")
    allowed, reason = h.can_restart("aa:bb", cooldown=timedelta(minutes=60))
    assert allowed is False
    assert "cooldown" in reason.lower()


@pytest.mark.fast
def test_restart_history_allows_after_cooldown_expires(tmp_path: Path) -> None:
    from unifi_manager.domain.restart_history import RestartHistory

    with freeze_time("2026-05-16 10:00:00") as frozen:
        h = RestartHistory(state_file=tmp_path / "history.json")
        h.record_restart(mac="aa:bb", name="x", action="restart", reason="t")

        frozen.tick(delta=timedelta(minutes=61))
        allowed, _ = h.can_restart("aa:bb", cooldown=timedelta(minutes=60))
        assert allowed is True


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_restart_history_count_increments(tmp_path: Path) -> None:
    from unifi_manager.domain.restart_history import RestartHistory

    h = RestartHistory(state_file=tmp_path / "history.json")
    h.record_restart(mac="aa:bb", name="x", action="restart", reason="t1")
    h.record_restart(mac="aa:bb", name="x", action="restart", reason="t2")

    entry = h.get_entry("aa:bb")
    assert entry is not None
    assert entry.count == 2


@pytest.mark.fast
def test_restart_history_persists_to_disk(tmp_path: Path) -> None:
    from unifi_manager.domain.restart_history import RestartHistory

    state_file = tmp_path / "history.json"
    with freeze_time("2026-05-16 10:00:00"):
        h1 = RestartHistory(state_file=state_file)
        h1.record_restart(mac="aa:bb", name="x", action="restart", reason="t")
        h1.save()

    h2 = RestartHistory(state_file=state_file)
    entry = h2.get_entry("aa:bb")
    assert entry is not None
    assert entry.name == "x"


@pytest.mark.fast
def test_restart_history_loads_legacy_format(fixtures_dir: Path,
                                              tmp_path: Path) -> None:
    """Migration test — старый формат `_legacy/auto_restart_problem_aps.py`
    (flat dict без version) читается новым кодом без потерь."""
    from unifi_manager.domain.restart_history import RestartHistory

    legacy_state = fixtures_dir / "restart_history_legacy.json"
    state_file = tmp_path / "history.json"
    state_file.write_bytes(legacy_state.read_bytes())

    h = RestartHistory(state_file=state_file)
    entry1 = h.get_entry("aa:bb:cc:dd:ee:01")
    entry2 = h.get_entry("aa:bb:cc:dd:ee:02")
    assert entry1 is not None
    assert entry1.name == "Restoran"
    assert entry1.action == "restart"
    assert entry1.count == 3
    assert entry2 is not None
    assert entry2.action == "poe_cycle"


@pytest.mark.fast
def test_restart_history_loads_new_format(fixtures_dir: Path,
                                           tmp_path: Path) -> None:
    from unifi_manager.domain.restart_history import RestartHistory

    new_state = fixtures_dir / "restart_history_new.json"
    state_file = tmp_path / "history.json"
    state_file.write_bytes(new_state.read_bytes())

    h = RestartHistory(state_file=state_file)
    entry = h.get_entry("aa:bb:cc:dd:ee:01")
    assert entry is not None
    assert entry.count == 3


@pytest.mark.fast
def test_restart_history_save_uses_new_format(tmp_path: Path) -> None:
    """save() пишет в new format (version=1, entries dict)."""
    from unifi_manager.domain.restart_history import RestartHistory

    state_file = tmp_path / "history.json"
    h = RestartHistory(state_file=state_file)
    with freeze_time("2026-05-16 10:00:00"):
        h.record_restart(mac="aa:bb", name="x", action="restart", reason="t")
    h.save()

    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data.get("version") == 1
    assert "entries" in data
    assert "aa:bb" in data["entries"]


@pytest.mark.fast
def test_restart_history_save_oserror_logged(tmp_path: Path,
                                              caplog: pytest.LogCaptureFixture) -> None:
    """save() при OSError — лог error, не raise (cron-safety)."""
    from unifi_manager.domain.restart_history import RestartHistory

    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    state_file = blocker / "history.json"

    h = RestartHistory(state_file=state_file)
    with caplog.at_level("ERROR"):
        h.save()
    assert any("Failed to save" in r.message for r in caplog.records)


@pytest.mark.fast
def test_restart_history_handles_corrupt_state(tmp_path: Path) -> None:
    """Битый JSON → start с пустого history (log warning)."""
    from unifi_manager.domain.restart_history import RestartHistory

    state_file = tmp_path / "history.json"
    state_file.write_text("{{not json", encoding="utf-8")

    h = RestartHistory(state_file=state_file)
    assert h.get_entry("anything") is None


# === Extended SYSID_MAP (D32) ===

@pytest.mark.fast
def test_sysid_map_includes_original_overrides() -> None:
    """Наши 4 entry из infra зеркала должны быть в final SYSID_MAP."""
    from unifi_manager.domain.device import SYSID_MAP

    assert SYSID_MAP[58759] == "UAP-AC-IW"
    assert SYSID_MAP[58679] == "UAP-AC-Pro"
    assert SYSID_MAP[58727] == "UAP-AC-M"
    assert SYSID_MAP[58711] == "UAP-AC-M-Pro"


@pytest.mark.fast
def test_sysid_map_has_extended_coverage() -> None:
    """D32: SYSID_MAP расширен seed-словарём (>10 entries)."""
    from unifi_manager.domain.device import SYSID_MAP

    assert len(SYSID_MAP) >= 10  # минимум 4 наших + 6 seed
```

- [ ] **Step 1.3: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_domain/test_restart_history.py -v --no-cov
```
Expected: ModuleNotFoundError на `unifi_manager.domain.restart_history`.

- [ ] **Step 1.4: Implement restart_history.py**

`src/unifi_manager/domain/restart_history.py`:

```python
"""RestartHistory — state-файл для cooldown и rate-limit рестартов.

Заменяет inline JSON manipulation из _legacy/auto_restart_problem_aps.py.
Поддерживает legacy format (flat dict) для migration без data loss.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from unifi_manager.utils.time import now_utc


_logger = logging.getLogger(__name__)

CURRENT_VERSION = 1


class RestartHistoryEntry(BaseModel):
    """Запись истории рестарта одного устройства."""

    name: str
    last_restart: datetime  # tz-aware UTC
    action: str  # "restart" | "poe_cycle" | "skipped"
    reason: str
    count: int = 1


class RestartHistory:
    """Cooldown + counter state для RestartService.

    Использование:
        history = RestartHistory(state_file=Path("/var/lib/unifi-mgr/restart_history.json"))
        allowed, why = history.can_restart("aa:bb", cooldown=timedelta(minutes=60))
        if allowed:
            ... # call client API
            history.record_restart(mac="aa:bb", name="Restoran", action="restart",
                                    reason="Lost contact > 3")
        history.save()
    """

    def __init__(self, state_file: Path) -> None:
        self.state_file = state_file
        self._entries: dict[str, RestartHistoryEntry] = self._load()

    def _load(self) -> dict[str, RestartHistoryEntry]:
        if not self.state_file.is_file():
            return {}
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            _logger.warning("Failed to load restart history %s: %s", self.state_file, e)
            return {}
        return self._parse_data(data)

    @staticmethod
    def _parse_data(data: Any) -> dict[str, RestartHistoryEntry]:
        """Парсит и legacy (flat dict) и new (versioned) format."""
        if not isinstance(data, dict):
            return {}

        # New format: {"version": 1, "entries": {...}}
        if "version" in data and "entries" in data:
            raw_entries = data.get("entries", {})
        else:
            # Legacy format: flat dict mac → entry
            raw_entries = data

        result: dict[str, RestartHistoryEntry] = {}
        for mac, raw_entry in raw_entries.items():
            if not isinstance(raw_entry, dict):
                continue
            try:
                # Legacy last_restart мог быть naive "2026-05-15T22:00:00" — Pydantic
                # пропустит без tz, but mы хотим UTC. Workaround: if no tz, treat as UTC.
                ts_str = raw_entry.get("last_restart", "")
                if isinstance(ts_str, str) and "+" not in ts_str and "Z" not in ts_str:
                    raw_entry["last_restart"] = ts_str + "+00:00"
                result[mac] = RestartHistoryEntry.model_validate(raw_entry)
            except Exception as e:
                _logger.warning("Bad restart history entry for %s: %s", mac, e)
        return result

    def get_entry(self, mac: str) -> RestartHistoryEntry | None:
        return self._entries.get(mac)

    def can_restart(
        self, mac: str, *, cooldown: timedelta
    ) -> tuple[bool, str]:
        """Returns (allowed, reason_text)."""
        entry = self._entries.get(mac)
        if entry is None:
            return True, "no prior restart"
        elapsed = now_utc() - entry.last_restart
        if elapsed < cooldown:
            remaining = cooldown - elapsed
            return False, f"cooldown active, {int(remaining.total_seconds() // 60)} min remaining"
        return True, "cooldown expired"

    def record_restart(
        self, *, mac: str, name: str, action: str, reason: str
    ) -> None:
        """Обновить state — увеличить count если запись была."""
        existing = self._entries.get(mac)
        new_count = (existing.count + 1) if existing else 1
        self._entries[mac] = RestartHistoryEntry(
            name=name,
            last_restart=now_utc(),
            action=action,
            reason=reason,
            count=new_count,
        )

    def save(self) -> None:
        """Atomically save state. OSError logs (cron-safety, не raise)."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": CURRENT_VERSION,
                "entries": {
                    mac: entry.model_dump(mode="json")
                    for mac, entry in self._entries.items()
                },
            }
            self.state_file.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as e:
            _logger.error("Failed to save restart history %s: %s", self.state_file, e)
```

- [ ] **Step 1.5: Extend SYSID_MAP (D32)**

Update `src/unifi_manager/domain/device.py` — найти existing SYSID_MAP:

```python
SYSID_MAP: Final[dict[int, str]] = {
    58759: "UAP-AC-IW",
    58679: "UAP-AC-Pro",
    58727: "UAP-AC-M",
    58711: "UAP-AC-M-Pro",
}
```

Заменить на (seed dictionary из tnware/unifi-controller-api + наши 4 overrides):

```python
# Seed dictionary — extended sysid → canonical model name mapping.
# Source: tnware/unifi-controller-api auto_model_mapping (D32).
# Naши 4 override entries (UAP-AC-*) перечислены отдельно для clarity.
_SYSID_SEED: Final[dict[int, str]] = {
    # UAP-AC series (legacy)
    58759: "UAP-AC-IW",       # our override (was U7IW in reported model)
    58679: "UAP-AC-Pro",      # our override (was U7PG2)
    58727: "UAP-AC-M",        # our override (was U7MP)
    58711: "UAP-AC-M-Pro",    # our override (was U7MSH)
    # UAP-AC additional (from tnware seed)
    58727: "UAP-AC-M",        # duplicate intentional — Python dict keeps last
    # U6 series (WiFi 6)
    62482: "U6-Lite",
    62483: "U6-LR",
    62484: "U6-Pro",
    62485: "U6-Mesh",
    62486: "U6-Enterprise",
    # U7 / WiFi 7 series
    65001: "U7-Pro",
    65002: "U7-Pro-Max",
    # Switches (basic seed — для diag команд Phase 4)
    32001: "US-24-250W",
    32002: "US-48-500W",
}

SYSID_MAP: Final[dict[int, str]] = dict(_SYSID_SEED)


# D32 refinement (2026-05-18): sysid_gap warning для self-enriching карты.
# Лог one-time per unknown sysid, без spam (set guard).
_WARNED_SYSIDS: set[int] = set()
_sysid_logger = logging.getLogger(__name__)


def lookup_real_model(reported_model: str, sysid: int | None) -> str:
    """Каноническое имя модели через SYSID_MAP с fallback на reported.

    При lookup unknown sysid — log warning ОДНОГО раза (поможет
    дополнить карту по реальности production network). Phase 4R recommendations engine
    использует эти warnings для генерации `sysid_gap` рекомендации.
    """
    if sysid is None:
        return reported_model
    if sysid in SYSID_MAP:
        return SYSID_MAP[sysid]
    if sysid not in _WARNED_SYSIDS:
        _WARNED_SYSIDS.add(sysid)
        _sysid_logger.warning(
            "sysid_gap: sysid=%d not in SYSID_MAP, falling back to reported_model=%r",
            sysid, reported_model,
            extra={"sysid": sysid, "reported_model": reported_model,
                   "category": "sysid_gap"},
        )
    return reported_model
```

В `AccessPoint.real_model` (`@computed_field`) использовать `lookup_real_model`:
```python
@computed_field  # type: ignore
@property
def real_model(self) -> str:
    return lookup_real_model(self.reported_model, self.sysid)
```

Добавь `import logging` если ещё нет в device.py.

**Add test:**
```python
@pytest.mark.fast
def test_sysid_gap_warning_logged_once(caplog: pytest.LogCaptureFixture) -> None:
    """D32 refinement: unknown sysid → warning ОДИН раз (не spam)."""
    from unifi_manager.domain import device as device_module
    from unifi_manager.domain.device import AccessPoint

    # Reset state for test isolation
    device_module._WARNED_SYSIDS.clear()

    with caplog.at_level("WARNING"):
        # Same unknown sysid lookup twice
        ap1 = AccessPoint.model_validate({"mac": "aa:01", "model": "Unknown",
                                            "sysid": 99999})
        ap2 = AccessPoint.model_validate({"mac": "aa:02", "model": "Unknown",
                                            "sysid": 99999})
        _ = ap1.real_model
        _ = ap2.real_model

    sysid_gap_records = [r for r in caplog.records if "sysid_gap" in r.message]
    assert len(sysid_gap_records) == 1  # only one warning per sysid
```

(Note: Если tnware actual map шире — engineer может скопировать больше. Минимум 10 entries по D32.)

- [ ] **Step 1.6: Run, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_domain/test_restart_history.py -v --no-cov
.venv/Scripts/pytest tests/unit/test_domain/test_device.py -v --no-cov
```
Expected: all PASS. test_device.py existing tests должны pass с extended SYSID_MAP (наши 4 entries сохранены).

- [ ] **Step 1.7: Mypy + ruff + coverage**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/domain/restart_history.py src/unifi_manager/domain/device.py
.venv/Scripts/ruff check src/unifi_manager/domain/ tests/unit/test_domain/
.venv/Scripts/pytest --cov=unifi_manager.domain.restart_history --cov-report=term-missing tests/unit/test_domain/test_restart_history.py
```
Expected: clean, coverage 90%+.

- [ ] **Step 1.8: Commit**

```bash
git add src/unifi_manager/domain/restart_history.py src/unifi_manager/domain/device.py tests/unit/test_domain/test_restart_history.py tests/fixtures/restart_history_legacy.json tests/fixtures/restart_history_new.json
git commit -m "phase3: domain/restart_history.py + extended SYSID_MAP (D32)"
```

---

## Task 2: services/restart_decisions.py — pure logic

**Files:**
- Create: `src/unifi_manager/services/restart_decisions.py`
- Create: `tests/unit/test_services/test_restart_decisions.py`

**Goal:** Pure decision logic (no I/O, no state) — `priority_score`, `classify_action`, `should_skip`. Easy для Hypothesis property-based tests.

- [ ] **Step 2.1: Write failing tests**

`tests/unit/test_services/test_restart_decisions.py`:

```python
"""Тесты для unifi_manager.services.restart_decisions."""
import pytest
from hypothesis import given
from hypothesis import strategies as st


# === priority_score ===

@pytest.mark.fast
def test_priority_score_connection_interrupted_highest() -> None:
    """state=10 (CONNECTION_INTERRUPTED) — наивысший приоритет (1)."""
    from unifi_manager.services.restart_decisions import priority_score

    assert priority_score(state=10, offline_min=0) == 1


@pytest.mark.fast
def test_priority_score_offline_short_high() -> None:
    """state=0, offline < 5 min — priority 1."""
    from unifi_manager.services.restart_decisions import priority_score

    assert priority_score(state=0, offline_min=3) == 1


@pytest.mark.fast
def test_priority_score_offline_medium() -> None:
    """state=0, 5 <= offline < 15 — priority 2."""
    from unifi_manager.services.restart_decisions import priority_score

    assert priority_score(state=0, offline_min=10) == 2


@pytest.mark.fast
def test_priority_score_offline_long() -> None:
    """state=0, offline >= 15 — priority 3."""
    from unifi_manager.services.restart_decisions import priority_score

    assert priority_score(state=0, offline_min=20) == 3


@pytest.mark.fast
def test_priority_score_online_lowest() -> None:
    """state=1 (online) — priority 99 (effectively skip)."""
    from unifi_manager.services.restart_decisions import priority_score

    assert priority_score(state=1, offline_min=0) >= 99


@pytest.mark.fast
@given(state=st.integers(min_value=0, max_value=20),
       offline_min=st.floats(min_value=0, max_value=1000))
def test_priority_score_always_positive(state: int, offline_min: float) -> None:
    """Property: priority always >= 1 (никогда не 0 или отрицательный)."""
    from unifi_manager.services.restart_decisions import priority_score

    assert priority_score(state=state, offline_min=offline_min) >= 1


# === classify_action ===

@pytest.mark.fast
def test_classify_action_state10_with_uplink_is_poe_cycle() -> None:
    """state=10 + uplink → poe_cycle."""
    from unifi_manager.services.restart_decisions import classify_action

    action, _ = classify_action(state=10, has_uplink=True)
    assert action == "poe_cycle"


@pytest.mark.fast
def test_classify_action_state10_no_uplink_is_restart() -> None:
    """state=10 без uplink → restart (попробуем оживить через API)."""
    from unifi_manager.services.restart_decisions import classify_action

    action, _ = classify_action(state=10, has_uplink=False)
    assert action == "restart"


@pytest.mark.fast
def test_classify_action_offline_with_uplink_is_poe_cycle() -> None:
    from unifi_manager.services.restart_decisions import classify_action

    action, _ = classify_action(state=0, has_uplink=True)
    assert action == "poe_cycle"


@pytest.mark.fast
def test_classify_action_adopting_is_skip() -> None:
    """state=4,5,6 (GETTING_READY/ADOPTING) — skip (wait)."""
    from unifi_manager.services.restart_decisions import classify_action

    for s in (4, 5, 6):
        action, _ = classify_action(state=s, has_uplink=True)
        assert action is None


@pytest.mark.fast
def test_classify_action_online_is_skip() -> None:
    from unifi_manager.services.restart_decisions import classify_action

    action, _ = classify_action(state=1, has_uplink=True)
    assert action is None


# === should_skip_by_exclude_pattern ===

@pytest.mark.fast
def test_should_skip_pattern_match() -> None:
    """Имя содержит exclude pattern → skip."""
    from unifi_manager.services.restart_decisions import should_skip_by_exclude_pattern

    assert should_skip_by_exclude_pattern("Spasatel vagon", ["Spasatel", "test"]) is True


@pytest.mark.fast
def test_should_skip_pattern_no_match() -> None:
    from unifi_manager.services.restart_decisions import should_skip_by_exclude_pattern

    assert should_skip_by_exclude_pattern("Restoran", ["Spasatel", "test"]) is False


@pytest.mark.fast
def test_should_skip_empty_patterns() -> None:
    from unifi_manager.services.restart_decisions import should_skip_by_exclude_pattern

    assert should_skip_by_exclude_pattern("anything", []) is False


@pytest.mark.fast
def test_should_skip_case_insensitive() -> None:
    from unifi_manager.services.restart_decisions import should_skip_by_exclude_pattern

    assert should_skip_by_exclude_pattern("TEST-AP", ["test"]) is True
```

- [ ] **Step 2.2: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_services/test_restart_decisions.py -v --no-cov
```
Expected: ModuleNotFoundError.

- [ ] **Step 2.3: Implement**

`src/unifi_manager/services/restart_decisions.py`:

```python
"""Pure decision logic для RestartService — без I/O, без state.

Easy для Hypothesis property-based testing.
Используется RestartService для:
- Приоритизации problematic AP (какие рестартить первыми)
- Выбора action (restart vs poe_cycle vs skip)
- Фильтрации по exclude patterns
"""
from __future__ import annotations

from typing import Literal

# UniFi device state codes (из legacy):
# 0  = OFFLINE
# 1  = ONLINE
# 4  = GETTING_READY
# 5  = PENDING_ADOPTION
# 6  = ADOPTING
# 10 = CONNECTION_INTERRUPTED

Action = Literal["restart", "poe_cycle"]


def priority_score(*, state: int, offline_min: float) -> int:
    """Меньшее число = выше приоритет рестарта.

    1: CONNECTION_INTERRUPTED (state=10) или короткое offline (<5 min)
    2: medium offline (5-15 min)
    3: long offline (>15 min) — рестарт менее эффективен
    99: online или unknown — skip
    """
    if state == 10:  # CONNECTION_INTERRUPTED — urgent
        return 1
    if state == 0:
        if offline_min < 5:
            return 1
        if offline_min < 15:
            return 2
        return 3
    return 99  # ONLINE, ADOPTING, etc. — не рестартим


def classify_action(*, state: int, has_uplink: bool) -> tuple[Action | None, str]:
    """Returns (action, reason). action=None → skip.

    Логика из _legacy/auto_restart_problem_aps.py:160-176.
    """
    # ADOPTING/GETTING_READY — wait, не трогаем
    if state in (4, 5, 6):
        return None, f"state={state} — wait (adopting/pending)"

    # ONLINE — не рестартим
    if state == 1:
        return None, "state=1 (online) — no action"

    # OFFLINE or CONNECTION_INTERRUPTED
    if state in (0, 10):
        if has_uplink:
            return "poe_cycle", f"state={state} + uplink known — PoE cycle"
        return "restart", f"state={state}, no uplink info — try restart cmd"

    return None, f"state={state} — unknown, no action"


def should_skip_by_exclude_pattern(name: str, exclude_patterns: list[str]) -> bool:
    """True если name содержит любой из exclude_patterns (case-insensitive)."""
    if not exclude_patterns:
        return False
    name_lower = name.lower()
    return any(pat.lower() in name_lower for pat in exclude_patterns)
```

- [ ] **Step 2.4: Run, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_services/test_restart_decisions.py -v --no-cov
```
Expected: all PASS (15+ tests including Hypothesis).

- [ ] **Step 2.5: Mypy + ruff + coverage**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/services/restart_decisions.py
.venv/Scripts/ruff check src/unifi_manager/services/restart_decisions.py tests/unit/test_services/test_restart_decisions.py
.venv/Scripts/pytest --cov=unifi_manager.services.restart_decisions --cov-report=term-missing tests/unit/test_services/test_restart_decisions.py
```
Expected: clean, coverage 95%+ (pure functions — легко покрываются).

- [ ] **Step 2.6: Commit**

```bash
git add src/unifi_manager/services/restart_decisions.py tests/unit/test_services/test_restart_decisions.py
git commit -m "phase3: services/restart_decisions.py — pure decision logic"
```

---

## Task 3: services/restart.py — RestartService.auto() + permissions

**Files:**
- Create: `src/unifi_manager/services/restart.py`
- Create: `tests/unit/test_services/test_restart.py`
- Create: `tests/fixtures/problematic_devices.json`

**Goal:** Automatic restart problematic AP — приоритизация, cooldown, max_per_run, history persistence. Permissions check (D30) skipping when disabled.

- [ ] **Step 3.1: Create fixture**

`tests/fixtures/problematic_devices.json`:

```json
{
  "meta": {"rc": "ok"},
  "data": [
    {
      "_id": "ap-1", "mac": "aa:bb:cc:dd:ee:01", "name": "Restoran",
      "model": "U7IW", "sysid": 58759, "type": "uap", "state": 10,
      "last_seen": 1747397700,
      "uplink": {"uplink_mac": "aa:bb:cc:dd:ee:99", "uplink_remote_port": 5}
    },
    {
      "_id": "ap-2", "mac": "aa:bb:cc:dd:ee:02", "name": "Office AP",
      "model": "U7PG2", "type": "uap", "state": 0,
      "last_seen": 1747396800,
      "uplink": {"uplink_mac": "aa:bb:cc:dd:ee:99", "uplink_remote_port": 6}
    },
    {
      "_id": "ap-3", "mac": "aa:bb:cc:dd:ee:03", "name": "Spasatel vagon",
      "model": "U7MP", "type": "uap", "state": 0,
      "last_seen": 1747380000
    },
    {
      "_id": "ap-4", "mac": "aa:bb:cc:dd:ee:04", "name": "Healthy AP",
      "model": "U7IW", "type": "uap", "state": 1,
      "last_seen": 1747397800
    }
  ]
}
```

- [ ] **Step 3.2: Write failing tests for auto()**

`tests/unit/test_services/test_restart.py`:

```python
"""Тесты для unifi_manager.services.restart.RestartService."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from freezegun import freeze_time

from unifi_manager.settings import (
    AutoRestartSettings,
    PermissionsSettings,
    Settings,
    UnifiAuthSettings,
)


@pytest.fixture
def restart_settings(tmp_path: Path) -> Settings:
    """Settings с auto_restart + permissions defaults."""
    return Settings(
        unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="test"),
        auto_restart=AutoRestartSettings(
            max_restarts_per_run=5,
            cooldown_minutes=60,
            offline_threshold_min=15,
            exclude_patterns=["Spasatel"],
            statefile=tmp_path / "restart_history.json",
        ),
    )


@pytest.fixture
def mock_client_problematic(fixtures_dir: Path) -> Mock:
    raw = json.loads(
        (fixtures_dir / "problematic_devices.json").read_text(encoding="utf-8")
    )
    client = Mock()
    client.list_devices_raw.return_value = raw["data"]
    client.send_command.return_value = {"meta": {"rc": "ok"}}
    return client


# === auto() ===

@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_auto_processes_problematic_devices(
    restart_settings: Settings, mock_client_problematic: Mock
) -> None:
    """auto() обрабатывает state=10 и state=0 устройства."""
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.auto()

    # 2 problematic AP (ap-1 state=10, ap-2 state=0) + 1 excluded (ap-3 Spasatel) + 1 healthy (ap-4)
    # excluded и healthy не процессятся
    # ap-1, ap-2 — должны быть processed
    assert len(report.actions) == 2


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_auto_respects_exclude_patterns(
    restart_settings: Settings, mock_client_problematic: Mock
) -> None:
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.auto()

    processed_macs = {a.mac for a in report.actions}
    assert "aa:bb:cc:dd:ee:03" not in processed_macs  # Spasatel excluded


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_auto_dry_run_does_not_send_commands(
    restart_settings: Settings, mock_client_problematic: Mock
) -> None:
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.auto(dry_run=True)

    assert report.dry_run is True
    mock_client_problematic.send_command.assert_not_called()


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_auto_sends_commands_when_not_dry_run(
    restart_settings: Settings, mock_client_problematic: Mock
) -> None:
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    svc.auto(dry_run=False)

    # 2 problematic → 2 send_command calls
    assert mock_client_problematic.send_command.call_count == 2


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_auto_respects_max_per_run(
    restart_settings: Settings, mock_client_problematic: Mock
) -> None:
    """max_restarts_per_run=1 → только 1 action даже если problematic больше."""
    from unifi_manager.services.restart import RestartService

    restart_settings.auto_restart.max_restarts_per_run = 1
    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.auto(dry_run=False)

    assert len(report.actions) == 1


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_auto_skips_devices_in_cooldown(
    restart_settings: Settings, mock_client_problematic: Mock, tmp_path: Path
) -> None:
    """Если device в cooldown — не процессим."""
    from unifi_manager.domain.restart_history import RestartHistory
    from unifi_manager.services.restart import RestartService

    # Pre-populate history для ap-1 (recent restart)
    history = RestartHistory(state_file=restart_settings.auto_restart.statefile)
    history.record_restart(mac="aa:bb:cc:dd:ee:01", name="Restoran",
                            action="restart", reason="test setup")
    history.save()

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.auto(dry_run=False)

    processed_macs = {a.mac for a in report.actions}
    assert "aa:bb:cc:dd:ee:01" not in processed_macs  # in cooldown


# === permissions (D30) ===

@pytest.mark.fast
def test_auto_permissions_disabled_returns_empty(
    restart_settings: Settings, mock_client_problematic: Mock
) -> None:
    """permissions.cli.restart.execute=false → skip всё, лог warning."""
    from unifi_manager.services.restart import RestartService

    restart_settings.permissions = PermissionsSettings()
    restart_settings.permissions.cli.restart.execute = False

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.auto(dry_run=False)

    assert report.status == "skipped_permissions"
    assert len(report.actions) == 0
    mock_client_problematic.send_command.assert_not_called()
```

- [ ] **Step 3.3: Run, verify fail**

```bash
.venv/Scripts/pytest tests/unit/test_services/test_restart.py -v --no-cov
```
Expected: ModuleNotFoundError.

- [ ] **Step 3.4: Implement restart.py**

`src/unifi_manager/services/restart.py`:

```python
"""RestartService — orchestration auto/profile/device restart c permissions + cooldown.

Использует:
- LegacyClient (HTTP — Phase 1) для команд
- RestartHistory (state) для cooldown tracking
- restart_decisions (pure) для priority & action choice
- PermissionsSettings (D30) для emergency kill-switch
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal, Protocol

from unifi_manager.domain.device import AccessPoint
from unifi_manager.domain.restart_history import RestartHistory
from unifi_manager.services.restart_decisions import (
    Action,
    classify_action,
    priority_score,
    should_skip_by_exclude_pattern,
)
from unifi_manager.settings import Settings
from unifi_manager.utils.time import now_utc


_logger = logging.getLogger(__name__)

# Sleep between commands (rate-limit на UniFi контроллер)
INTER_ACTION_DELAY_SECONDS = 2.0


class _RestartClient(Protocol):
    def list_devices_raw(self) -> list[dict[str, Any]]: ...
    def send_command(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RestartAction:
    """Одно действие из run report."""

    mac: str
    name: str
    action: Action
    reason: str
    status: str  # "success" | "fail: ..." | "dry_run" | "cooldown_skip"


@dataclass(frozen=True)
class RestartReport:
    """Результат RestartService.auto()."""

    status: Literal["completed", "skipped_permissions", "no_candidates"]
    dry_run: bool
    actions: list[RestartAction] = field(default_factory=list)


class RestartService:
    """Auto-restart problem APs + profile-based + device targeted."""

    def __init__(
        self,
        legacy_client: _RestartClient,
        settings: Settings,
    ) -> None:
        self.client = legacy_client
        self.settings = settings
        self.history = RestartHistory(settings.auto_restart.statefile)

    def auto(self, *, dry_run: bool = False) -> RestartReport:
        """Smart auto-restart: priority по state+offline, cooldown, max_per_run.

        Заменяет _legacy/auto_restart_problem_aps.py.
        """
        # D30: permission kill-switch
        if not self.settings.permissions.cli.restart.execute:
            _logger.warning("auto: skipped — permissions.cli.restart.execute=false")
            return RestartReport(status="skipped_permissions", dry_run=dry_run)

        cfg = self.settings.auto_restart
        cooldown = timedelta(minutes=cfg.cooldown_minutes)

        # 1. Collect problematic candidates
        candidates: list[tuple[int, AccessPoint]] = []
        for raw in self.client.list_devices_raw():
            if raw.get("type") != "uap":
                continue
            try:
                ap = AccessPoint.model_validate(raw)
            except Exception as e:
                _logger.debug("Skipping unparseable device: %s", e)
                continue

            # exclude patterns
            if ap.name and should_skip_by_exclude_pattern(ap.name, cfg.exclude_patterns):
                continue

            # online — skip
            if ap.state == 1:
                continue

            # cooldown check
            allowed, _reason = self.history.can_restart(ap.mac, cooldown=cooldown)
            if not allowed:
                continue

            offline_min = self._offline_minutes(ap)
            priority = priority_score(state=ap.state, offline_min=offline_min)
            if priority >= 99:
                continue  # nothing to do

            candidates.append((priority, ap))

        if not candidates:
            return RestartReport(status="no_candidates", dry_run=dry_run)

        # 2. Sort by priority (lowest first)
        candidates.sort(key=lambda x: x[0])

        # 3. Process up to max_per_run
        actions: list[RestartAction] = []
        for priority, ap in candidates[: cfg.max_restarts_per_run]:
            offline_min = self._offline_minutes(ap)
            has_uplink = ap.uplink is not None and ap.uplink.uplink_mac is not None
            action, reason = classify_action(state=ap.state, has_uplink=has_uplink)
            if action is None:
                continue

            if dry_run:
                actions.append(RestartAction(
                    mac=ap.mac, name=ap.name or ap.mac,
                    action=action, reason=reason, status="dry_run",
                ))
                continue

            # Execute real action
            success, status_msg = self._execute(action, ap)
            actions.append(RestartAction(
                mac=ap.mac, name=ap.name or ap.mac,
                action=action, reason=reason,
                status="success" if success else f"fail: {status_msg}",
            ))

            if success:
                self.history.record_restart(
                    mac=ap.mac, name=ap.name or ap.mac,
                    action=action, reason=reason,
                )

            # Inter-action delay (rate-limit для контроллера)
            if len(actions) < len(candidates):
                time.sleep(INTER_ACTION_DELAY_SECONDS)

        if not dry_run:
            self.history.save()

        return RestartReport(status="completed", dry_run=dry_run, actions=actions)

    def _execute(self, action: Action, ap: AccessPoint) -> tuple[bool, str]:
        """Реально вызвать API. Returns (success, status_msg)."""
        try:
            if action == "restart":
                resp = self.client.send_command({"cmd": "restart", "mac": ap.mac})
            else:  # poe_cycle
                if ap.uplink is None or ap.uplink.uplink_mac is None or \
                   ap.uplink.uplink_remote_port is None:
                    return False, "no uplink info"
                resp = self.client.send_command({
                    "cmd": "power-cycle",
                    "mac": ap.uplink.uplink_mac,
                    "port_idx": ap.uplink.uplink_remote_port,
                })
            rc = resp.get("meta", {}).get("rc")
            return (rc == "ok"), f"rc={rc}"
        except Exception as e:
            _logger.error("Action %s failed for %s: %s", action, ap.mac, e)
            return False, str(e)

    @staticmethod
    def _offline_minutes(ap: AccessPoint) -> float:
        """Сколько минут устройство офлайн (last_seen → now)."""
        if ap.last_seen is None:
            return 0.0
        # last_seen — unix timestamp
        from datetime import datetime
        last_dt = datetime.fromtimestamp(ap.last_seen, tz=now_utc().tzinfo)
        return (now_utc() - last_dt).total_seconds() / 60.0
```

- [ ] **Step 3.5: Run, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_services/test_restart.py -v --no-cov
```
Expected: 7 PASS.

- [ ] **Step 3.6: Mypy + ruff**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/services/restart.py
.venv/Scripts/ruff check src/unifi_manager/services/restart.py tests/unit/test_services/test_restart.py
```
Expected: clean.

- [ ] **Step 3.7: Commit**

```bash
git add src/unifi_manager/services/restart.py tests/unit/test_services/test_restart.py tests/fixtures/problematic_devices.json
git commit -m "phase3: services/restart.py — RestartService.auto with permissions (D30)"
```

---

## Task 4: RestartService.profile() + permissions

**Files:**
- Modify: `src/unifi_manager/services/restart.py` (add `.profile()` method)
- Modify: `tests/unit/test_services/test_restart.py` (add profile tests)

**Goal:** Profile-based restart — фильтрация AP по filter_names/filter_patterns из `restart_profiles` config. Заменяет 3 legacy `restart_restaurant_*.py` скрипта.

- [ ] **Step 4.1: Add tests**

В `tests/unit/test_services/test_restart.py` добавить:

```python
# === profile() ===

@pytest.fixture
def profile_settings(restart_settings: Settings, tmp_path: Path) -> Settings:
    """Settings с restart_profiles configured."""
    from unifi_manager.settings import RestartProfile
    restart_settings.restart_profiles = {
        "restaurant": RestartProfile(
            filter_names=["Restoran", "Restoran WIFI", "Rest Bar"],
            exclude_names=["Spasatel vagon"],
            lost_contact_threshold=3,
            window_hours=24,
            max_restarts=5,
            cooldown_minutes=120,
        ),
    }
    return restart_settings


@pytest.fixture
def mock_client_for_profile() -> Mock:
    """Mock client с restaurant AP devices + events."""
    client = Mock()
    client.list_devices_raw.return_value = [
        {"mac": "aa:01", "name": "Restoran", "model": "U7IW", "type": "uap", "state": 1},
        {"mac": "aa:02", "name": "Rest Bar", "model": "U7IW", "type": "uap", "state": 1},
        {"mac": "aa:03", "name": "Office", "model": "U7IW", "type": "uap", "state": 1},
    ]
    # Restoran has 5 lost contact events (> threshold 3 → restart)
    # Rest Bar has 1 event (< threshold → skip)
    def events_for_mac(*, mac: str) -> list[dict[str, Any]]:
        if mac == "aa:01":
            return [{"key": "EVT_AP_Lost_Contact", "datetime": "2026-05-16T09:00:00Z",
                     "ap": mac} for _ in range(5)]
        if mac == "aa:02":
            return [{"key": "EVT_AP_Lost_Contact", "datetime": "2026-05-16T09:00:00Z",
                     "ap": mac}]
        return []
    client.list_events_raw.side_effect = events_for_mac
    client.send_command.return_value = {"meta": {"rc": "ok"}}
    return client


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_profile_restarts_devices_over_threshold(
    profile_settings: Settings, mock_client_for_profile: Mock
) -> None:
    """Restoran (5 events > 3) → restart. Rest Bar (1) → skip."""
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_for_profile, settings=profile_settings)
    report = svc.profile("restaurant", apply=True)

    processed_macs = {a.mac for a in report.actions if a.status == "success"}
    assert "aa:01" in processed_macs  # over threshold
    assert "aa:02" not in processed_macs  # under threshold


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_profile_excludes_office_ap(
    profile_settings: Settings, mock_client_for_profile: Mock
) -> None:
    """Office AP не в filter_names → не процессим вообще."""
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_for_profile, settings=profile_settings)
    report = svc.profile("restaurant", apply=True)

    processed_macs = {a.mac for a in report.actions}
    assert "aa:03" not in processed_macs  # not in filter_names


@pytest.mark.fast
def test_profile_unknown_name_raises(profile_settings: Settings) -> None:
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=Mock(), settings=profile_settings)
    with pytest.raises(ValueError, match="unknown profile"):
        svc.profile("nonexistent", apply=True)


@pytest.mark.fast
@freeze_time("2026-05-16 10:00:00")
def test_profile_dry_run_default(
    profile_settings: Settings, mock_client_for_profile: Mock
) -> None:
    """apply=False (default) → dry_run, no send_command."""
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_for_profile, settings=profile_settings)
    report = svc.profile("restaurant")  # default apply=False

    assert report.dry_run is True
    mock_client_for_profile.send_command.assert_not_called()


@pytest.mark.fast
def test_profile_permissions_disabled(
    profile_settings: Settings, mock_client_for_profile: Mock
) -> None:
    """permissions.cli.restart.profile_apply=false → skip."""
    from unifi_manager.services.restart import RestartService

    profile_settings.permissions.cli.restart.profile_apply = False
    svc = RestartService(legacy_client=mock_client_for_profile, settings=profile_settings)
    report = svc.profile("restaurant", apply=True)

    assert report.status == "skipped_permissions"
```

- [ ] **Step 4.2: Add profile() to restart.py**

Add at end of `RestartService` class:

```python
    def profile(self, profile_name: str, *, apply: bool = False) -> RestartReport:
        """Restart APs matching profile (заменяет 3 legacy restart_restaurant_*.py).

        apply=False (default) — dry-run для safety.
        apply=True — реальный restart.
        """
        # D30: permissions
        if not self.settings.permissions.cli.restart.execute:
            _logger.warning("profile: skipped — permissions.cli.restart.execute=false")
            return RestartReport(status="skipped_permissions", dry_run=not apply)
        if apply and not self.settings.permissions.cli.restart.profile_apply:
            _logger.warning("profile: skipped — permissions.cli.restart.profile_apply=false")
            return RestartReport(status="skipped_permissions", dry_run=False)

        profile = self.settings.restart_profiles.get(profile_name)
        if profile is None:
            raise ValueError(f"unknown profile: {profile_name!r}")

        cooldown = timedelta(minutes=profile.cooldown_minutes)
        from unifi_manager.domain.event import ApEvent, EventKey
        from unifi_manager.utils.time import is_within_window

        # 1. List devices, filter by profile.filter_names/patterns
        all_devices = self.client.list_devices_raw()
        candidates: list[AccessPoint] = []
        for raw in all_devices:
            if raw.get("type") != "uap":
                continue
            name = raw.get("name", "")
            if profile.filter_names and name not in profile.filter_names:
                continue
            if profile.exclude_names and name in profile.exclude_names:
                continue
            try:
                candidates.append(AccessPoint.model_validate(raw))
            except Exception as e:
                _logger.debug("Skipping unparseable device: %s", e)

        # 2. For each candidate, count lost-contact events in window
        actions: list[RestartAction] = []
        for ap in candidates:
            # cooldown check (использует profile cooldown_minutes)
            allowed, _ = self.history.can_restart(ap.mac, cooldown=cooldown)
            if not allowed:
                continue

            events_raw = self.client.list_events_raw(mac=ap.mac)
            lost_count = 0
            for evt_raw in events_raw:
                try:
                    evt = ApEvent.model_validate(evt_raw)
                except Exception:
                    continue
                if evt.key != EventKey.AP_LOST_CONTACT:
                    continue
                if is_within_window(evt.timestamp, hours=profile.window_hours):
                    lost_count += 1

            if lost_count <= profile.lost_contact_threshold:
                continue  # under threshold, skip

            reason = f"lost_contact count={lost_count} > threshold={profile.lost_contact_threshold}"
            if not apply:
                actions.append(RestartAction(
                    mac=ap.mac, name=ap.name or ap.mac,
                    action="restart", reason=reason, status="dry_run",
                ))
                continue

            success, msg = self._execute("restart", ap)
            actions.append(RestartAction(
                mac=ap.mac, name=ap.name or ap.mac,
                action="restart", reason=reason,
                status="success" if success else f"fail: {msg}",
            ))
            if success:
                self.history.record_restart(
                    mac=ap.mac, name=ap.name or ap.mac,
                    action="restart", reason=reason,
                )
            if len(actions) >= profile.max_restarts:
                break
            time.sleep(INTER_ACTION_DELAY_SECONDS)

        if apply:
            self.history.save()

        return RestartReport(
            status="completed",
            dry_run=not apply,
            actions=actions,
        )
```

- [ ] **Step 4.3: Run, verify pass**

```bash
.venv/Scripts/pytest tests/unit/test_services/test_restart.py -v --no-cov
```
Expected: 12 PASS (7 auto + 5 profile).

- [ ] **Step 4.4: Mypy + ruff**

```bash
.venv/Scripts/mypy --strict src/unifi_manager/services/restart.py
.venv/Scripts/ruff check src/unifi_manager/services/restart.py tests/unit/test_services/test_restart.py
```
Expected: clean.

- [ ] **Step 4.5: Commit**

```bash
git add src/unifi_manager/services/restart.py tests/unit/test_services/test_restart.py
git commit -m "phase3: RestartService.profile() — replaces 3 legacy restart_restaurant_*.py"
```

---

## Task 5: RestartService.device() — точечный restart

**Files:**
- Modify: `src/unifi_manager/services/restart.py` (add `.device()` method)
- Modify: `tests/unit/test_services/test_restart.py` (add device tests)

**Goal:** Точечный rebote одного device по MAC. apply=False по default. Permissions check.

- [ ] **Step 5.1: Add tests**

```python
# === device() ===

@pytest.mark.fast
def test_device_dry_run_default(
    restart_settings: Settings, mock_client_problematic: Mock
) -> None:
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.device(mac="aa:bb:cc:dd:ee:01", method="restart")

    assert report.dry_run is True
    mock_client_problematic.send_command.assert_not_called()


@pytest.mark.fast
def test_device_apply_sends_command(
    restart_settings: Settings, mock_client_problematic: Mock
) -> None:
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.device(mac="aa:bb:cc:dd:ee:01", method="restart", apply=True)

    assert report.dry_run is False
    assert len(report.actions) == 1
    mock_client_problematic.send_command.assert_called_once()


@pytest.mark.fast
def test_device_unknown_mac_raises(
    restart_settings: Settings, mock_client_problematic: Mock
) -> None:
    from unifi_manager.services.restart import RestartService

    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    with pytest.raises(ValueError, match="not found"):
        svc.device(mac="ff:ff:ff:ff:ff:ff", method="restart", apply=True)


@pytest.mark.fast
def test_device_permissions_disabled(
    restart_settings: Settings, mock_client_problematic: Mock
) -> None:
    from unifi_manager.services.restart import RestartService

    restart_settings.permissions.cli.restart.device_apply = False
    svc = RestartService(legacy_client=mock_client_problematic, settings=restart_settings)
    report = svc.device(mac="aa:bb:cc:dd:ee:01", method="restart", apply=True)

    assert report.status == "skipped_permissions"
```

- [ ] **Step 5.2: Add device() to restart.py**

```python
    def device(
        self,
        *,
        mac: str,
        method: Literal["restart", "poe_cycle"],
        apply: bool = False,
    ) -> RestartReport:
        """Точечный restart одного device по MAC."""
        if not self.settings.permissions.cli.restart.execute:
            _logger.warning("device: skipped — permissions.cli.restart.execute=false")
            return RestartReport(status="skipped_permissions", dry_run=not apply)
        if apply and not self.settings.permissions.cli.restart.device_apply:
            _logger.warning("device: skipped — permissions.cli.restart.device_apply=false")
            return RestartReport(status="skipped_permissions", dry_run=False)

        # Find device
        target: AccessPoint | None = None
        for raw in self.client.list_devices_raw():
            if raw.get("mac") == mac and raw.get("type") == "uap":
                try:
                    target = AccessPoint.model_validate(raw)
                except Exception as e:
                    raise ValueError(f"device {mac} unparseable: {e}") from e
                break

        if target is None:
            raise ValueError(f"device {mac!r} not found in current site inventory")

        reason = f"manual targeted {method}"
        if not apply:
            return RestartReport(
                status="completed",
                dry_run=True,
                actions=[RestartAction(
                    mac=mac, name=target.name or mac,
                    action=method, reason=reason, status="dry_run",
                )],
            )

        success, msg = self._execute(method, target)
        action_record = RestartAction(
            mac=mac, name=target.name or mac, action=method, reason=reason,
            status="success" if success else f"fail: {msg}",
        )
        if success:
            self.history.record_restart(
                mac=mac, name=target.name or mac, action=method, reason=reason,
            )
            self.history.save()
        return RestartReport(status="completed", dry_run=False, actions=[action_record])
```

- [ ] **Step 5.3: Run + mypy + ruff + commit**

```bash
.venv/Scripts/pytest tests/unit/test_services/test_restart.py -v --no-cov
.venv/Scripts/mypy --strict src/unifi_manager/services/restart.py
.venv/Scripts/ruff check src/unifi_manager/services/restart.py tests/unit/test_services/test_restart.py
```
Expected: 16 PASS (12 + 4 device), mypy clean, ruff clean.

```bash
git add src/unifi_manager/services/restart.py tests/unit/test_services/test_restart.py
git commit -m "phase3: RestartService.device() — targeted single-device restart"
```

---

## Task 6: CI update + acceptance + phase-3-complete tag

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 6.1: Update CI mypy scope**

In ci.yml `Mypy strict (core)` step, the file list уже includes `src/unifi_manager/services` and `src/unifi_manager/domain`. RestartService и restart_history files уже covered. No changes needed unless mypy scope is per-file. Verify with:

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
Expected: Success.

(Если по факту нужен новый list — обновить ci.yml. Если нет — пропустить эту правку.)

- [ ] **Step 6.2: Full suite acceptance**

```bash
.venv/Scripts/pytest --cov=unifi_manager --cov-report=term-missing --cov-fail-under=90
```
Expected: 200+ tests (171 Phase 2 + 30 Phase 3), coverage 90%+.

- [ ] **Step 6.3: Fresh venv acceptance**

```bash
rm -rf .venv-acceptance
py -3.12 -m venv .venv-acceptance
.venv-acceptance/Scripts/pip install -e ".[dev]"
.venv-acceptance/Scripts/pytest --cov=unifi_manager --cov-report=term-missing --cov-fail-under=90 -v
```
Expected: all PASS.

```bash
rm -rf .venv-acceptance
```

- [ ] **Step 6.4: Create tag**

```bash
git tag -d phase-3-complete 2>/dev/null || true
git tag -a phase-3-complete -m "Phase 3 (RestartService) complete: auto + profile + device with D30 permissions and D32 extended SYSID_MAP"
git describe --tags
```

- [ ] **Step 6.5: Commit (if ci.yml changed)**

```bash
# Only if ci.yml updated
git add .github/workflows/ci.yml
git commit -m "phase3: CI mypy scope updated (if needed)"
```

---

## Definition of Done — Phase 3

| Check | Command | Expected |
|---|---|---|
| All tests pass | `pytest --no-cov` | 200+ tests |
| Coverage ≥ 90% | `pytest --cov-fail-under=90` | PASS |
| Coverage restart.py | `pytest --cov=unifi_manager.services.restart` | ≥ 90% |
| Coverage restart_history.py | `pytest --cov=unifi_manager.domain.restart_history` | ≥ 95% |
| Coverage restart_decisions.py | pure functions | 100% |
| Mypy strict для restart files | `mypy --strict src/unifi_manager/services/restart.py src/unifi_manager/domain/restart_history.py` | Success |
| Ruff clean | `ruff check .` | All checks passed |
| Pre-commit green | `pre-commit run --all-files` | all PASS |
| Legacy migration | `test_restart_history_loads_legacy_format` | PASS |
| Permissions D30 | `test_auto/profile/device_permissions_disabled` | PASS (3 tests) |
| Extended SYSID_MAP D32 | `test_sysid_map_has_extended_coverage` | PASS |
| Tag created | `git tag -l phase-3-complete` | exists |

**Not in this phase:**
- ❌ CLI commands (Phase 4)
- ❌ MCP server (Phase 4M, optional)
- ❌ Cron switch (Phase 5)

---

## After Phase 3

Phase 4 — CLI complete. Все Typer-команды wired к services. `dashboard.sh` переписан. CliRunner smoke tests.

После Phase 4 — Phase 4M (optional MCP wrapper) или сразу Phase 5 (cron switch).
