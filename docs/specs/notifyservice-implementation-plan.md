# NotifyService — план реализации

**Спек (заморожен):** `docs/specs/2026-06-14-notifyservice-design.md` — single source of truth. План его не меняет; при расхождении план неправ.
**Track:** Track 3, под-проект 1/4.
**Калибровка:** known-design implementation → direct Code (не Ultracode).
**Формат:** рабочий вход, не репо-док (process-выхлоп в репо не коммитим — ROADMAP остаётся живой картой).

## Три заметки реализации (подтверждены фактически, зашиты в план)

1. **`cache_dir` тест-изоляция.** Autouse в `tests/unit/test_cli/conftest.py` изолирует `LOG_DIR`/`REPORTS_DIR`/`EXPORT_DIR`, но **не `CACHE_DIR`**. NotifyService пишет `alert_history.json` + `telegram_throttle.json` в `paths.cache_dir` (дефолт `~/.cache`) → без фикса тесты гадят в живой `~/.cache`. → **Task 0**.
2. **Общий atomic-save helper**, не третья копия. `RestartHistory.save` уже атомарный (tmp + `os.replace` + cleanup) — извлечь паттерн в `utils/`. → **Task 1**.
3. **Сохранить формат сообщения issue + видимость suppressed.** Текущий формат `⚠ {severity}: {device_name} — {issue_type}`, hash_key `{issue_type}:{device_mac}` — не менять. CLI `audit critical` логирует `report.status` (видно, что задедуплено). → **Task 3 + Task 6**.

## Порядок (зависимости-первыми, TDD)

```
Task 0  conftest cache_dir            (unblocks все notify-тесты)
Task 1  utils/atomic.py + рефактор 3 savers   (нет зависимостей)
Task 2  типы в services/notify.py     (нет зависимостей)
Task 3  NotifyService core + сервис-тесты   (← 1,2)   ← основная масса
Task 4  build_notify_service           (← 3)
Task 5  CLI notify test/send + тесты   (← 3,4)
Task 6  CLI audit critical + тесты     (← 3,4)
Task 7  финальный гейт                 (§7 ×22 + §8 ×10)
```

Каждый Task: ruff + mypy(core) + pytest зелёные перед переходом к следующему.

---

## Task 0 — Тест-изоляция cache_dir

Файл: `tests/unit/test_cli/conftest.py` (autouse-фикстура, что ставит `LOG_DIR`/`REPORTS_DIR`/`EXPORT_DIR`).

- [ ] **0.1** Добавить в ту же autouse-фикстуру:
  ```python
  monkeypatch.setenv("UNIFI_PATHS__CACHE_DIR", str(tmp_path / "cache"))
  ```
  Env-имя подтверждено эмпирически: `UNIFI_PATHS__CACHE_DIR=X` → `settings.paths.cache_dir == X`.
  **Важно:** промах изоляции cache_dir CI НЕ поймает (в отличие от log_dir → `/var/log` PermissionError) — `~/.cache` на раннере writable, тесты не упадут, просто загадят home + перекрёстно заразятся. Поэтому проверять надо эмпирикой (этот redirect-чек), а не «суйта зелёная».
- [ ] **0.2** Проверить, нет ли существующих `audit critical --telegram` тестов, которые уже пишут в реальный `~/.cache` (если `telegram_send=false` — не пишут; если есть путь с записью — теперь изолированы).
- [ ] **0.3** `pytest tests/unit/test_cli` зелёный.

---

## Task 1 — Atomic JSON save helper

Новый файл: `src/unifi_manager/utils/atomic.py`.

- [ ] **1.1 (тест-первый)** `tests/unit/test_utils/test_atomic.py`:
  - пишет читаемый JSON, round-trip; **`ensure_ascii=False`** (кириллица не экранирована в файле) — *спек тест #10*;
  - `os.replace` поверх существующего (перезапись);
  - на `OSError` (напр. unwritable dir) — tmp подчищен, не падает (logged).
- [ ] **1.2** Реализовать (паттерн из `RestartHistory.save`):
  ```python
  def atomic_write_json(path: Path, data: object) -> None:
      """tmp + os.replace; ensure_ascii=False; OSError → log + cleanup tmp, не raise."""
      tmp = path.with_name(path.name + ".tmp")
      try:
          path.parent.mkdir(parents=True, exist_ok=True)
          tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
          os.replace(tmp, path)
      except OSError as e:
          _logger.error("Failed to save %s: %s", path, e)
          with contextlib.suppress(OSError):
              tmp.unlink(missing_ok=True)
  ```
- [ ] **1.3** Перевести три savers на helper:
  - `RestartHistory.save` — **сохранить** `if self._corrupt: return` guard ДО вызова helper (fail-closed остаётся); тело payload без изменений.
  - `AlertHistory.save` — заменить прямой `write_text` на `atomic_write_json(self.state_file, self._state)`.
  - `TelegramRateLimiter._save` — заменить на `atomic_write_json(self.state_file, {"hashes": ..., "total": list(...)})` (попутно добавляет `ensure_ascii=False`, которого там не было).
- [ ] **1.4** Существующие тесты (`test_restart_history`, `test_telegram`, `test_notify`) зелёные — атомарность RestartHistory уже покрыта, не должна сломаться.

*Спек:* критерии 17 (atomic both), 22 (atomic ≠ concurrency — в коде не заявлять обратного).

---

## Task 2 — Типы в `services/notify.py`

Файл: `src/unifi_manager/services/notify.py` (рядом с существующим `AlertHistory`).

- [ ] **2.1** `class AlertLevel(StrEnum): info / warn / crit` — *спек §1.2, критерий 14, T5*.
- [ ] **2.2** `class Notifier(Protocol): def send_message(self, text: str, *, hash_key: str) -> bool: ...` — *§1.1, seam*.
- [ ] **2.3** `class _ChannelState(StrEnum): enabled / skipped_permissions / skipped_disabled` — internal.
- [ ] **2.4** `class NotifyStatus(StrEnum)`: `sent, completed, partial, failed, channel_unavailable, skipped_permissions, skipped_disabled, no_issues` — **без `enabled`** — *§1.3, критерий 11*.
- [ ] **2.5** `@dataclass(frozen=True) class NotifyReport`: `status: NotifyStatus`, `sent: int = 0`, `skipped_dedup: int = 0`, `failed: int = 0` — *§1.4, критерий 10*.

(Типы тестируются через Task 3.)

---

## Task 3 — NotifyService core

Файл: `src/unifi_manager/services/notify.py`.

- [ ] **3.1 (тест-первый)** `tests/unit/test_services/test_notify.py` с fake-`Notifier` (см. Appendix B). Покрыть §8:
  - #1 `telegram_send=false` + `enabled=true` + нет токена → нотифаер НЕ строится, `status=skipped_permissions`, без `ValueError`;
  - #2 `telegram_send=true` + `enabled=true` + нет токена → factory дёрнут один раз, `status=channel_unavailable`, без `ValueError`;
  - #5 несколько issues → `notifier_factory` вызвана **ровно один раз** (memoization);
  - #6 всё задедуплено (issues непусто, sent=0, failed=0, skipped_dedup>0) → `status=completed`;
  - #7 send→False на каждый новый issue (sent=0, failed>0) → `status=failed`;
  - #8 factory кидает `ValueError` → `status=channel_unavailable`; `failed` может быть 0 или len — **status не failed**;
  - #9 `record_alert` ТОЛЬКО после `send_message()==True`; на False/throttle — нет `record_alert`;
  - backward-compat dedup: pre-populated old `alert_history.json` подавляет известный alert (это и есть T4-чистка — реальный `AlertHistory` + fake `Notifier` на уровне сервиса).
- [ ] **3.2** `__init__(self, *, settings, history: AlertHistory, notifier_factory: Callable[[], Notifier])`; поля мемоизации: `self._notifier_attempted = False`, `self._notifier: Notifier | None = None`, `self._channel_error: str | None = None`.
- [ ] **3.3** `_channel_state() -> _ChannelState` — *§2*:
  ```python
  if not settings.permissions.cli.notify.telegram_send: return skipped_permissions
  if not settings.telegram.enabled:                     return skipped_disabled
  return enabled
  ```
- [ ] **3.4** `_get_notifier() -> Notifier | None` — **safe-lazy + memoize успех И провал** (*§2, критерий 7*):
  ```python
  if self._notifier_attempted: return self._notifier
  self._notifier_attempted = True
  try:    self._notifier = self._notifier_factory()
  except ValueError as e:
          self._channel_error = str(e); self._notifier = None
  return self._notifier
  ```
- [ ] **3.5** `notify_audit_issues(self, issues: Sequence[AuditIssue]) -> NotifyReport` — деривация строго по precedence (Appendix A / §3.1):
  - issues пусто → `no_issues`;
  - `_channel_state()` != enabled → `skipped_permissions` / `skipped_disabled` (ранний возврат, нотифаер не трогаем);
  - `_get_notifier() is None` → `channel_unavailable` (ранний возврат, петли нет → `failed=0`);
  - иначе петля (Appendix C): hash_key `{issue_type}:{device_mac}`, формат `⚠ {severity}: {device_name} — {issue_type}` (**не менять** — заметка 3); `record_alert` после True; `save()` **один раз в конце** (критерий 20);
  - финальный статус по (sent, failed): см. таблицу.
  - импорт `AuditIssue` из `services.audit` — связь однонаправленная, OK (*§1.5, без `AuditIssueLike`*).
- [ ] **3.6** `send(self, text: str, *, level: AlertLevel) -> NotifyReport` — §3.2: front-gate (skipped_*/channel_unavailable) → формат `{icon} {text}` (`{info:ℹ, warn:⚠, crit:🚨}`) → digest hash (Appendix D) → `send True → sent / False → failed`. Без `completed`.
- [ ] **3.7** `test(self) -> NotifyReport` — тот же front-gate → сообщение `✓ unifi-mgr test message`, hash_key `cli-test` → sent/failed.

---

## Task 4 — `build_notify_service`

Файл: `src/unifi_manager/cli/_common.py`.

- [ ] **4.1** **Не ветвить на permissions** (*критерий 2*). `AlertHistory` строится сразу (дёшево, без сети/ValueError); `notifier_factory` ленивый:
  ```python
  def build_notify_service(settings: Settings) -> NotifyService:
      return NotifyService(
          settings=settings,
          history=AlertHistory(settings.paths.cache_dir / "alert_history.json"),
          notifier_factory=lambda: TelegramNotifier(
              settings=settings.telegram,
              rate_limit_state=settings.paths.cache_dir / "telegram_throttle.json",
          ),
      )
  ```
- [ ] **4.2** Имена state-файлов **не менять** (*критерий 16*) — `alert_history.json`, `telegram_throttle.json`.

---

## Task 5 — CLI: `notify test` / `notify send`

Файл: `src/unifi_manager/cli/notify.py`.

- [ ] **5.1 (тест-первый)** `tests/unit/test_cli/test_notify.py`:
  - `--level garbage` → Typer exit 2 (Enum) — *T5*;
  - `telegram_send=false` → не шлёт, exit 1 (`skipped_permissions`);
  - broken Telegram config (enabled + нет токена) → exit 1, stderr читаемый, без traceback — *спек тест #4*;
  - успешный путь (fake/responses) → exit 0.
- [ ] **5.2** `notify test` и `notify send` → `load_settings` → `build_notify_service` → `.test()` / `.send(text, level=...)`.
- [ ] **5.3** `--level: Annotated[AlertLevel, typer.Option("--level")] = AlertLevel.info`.
- [ ] **5.4** Exit-mapping (*§5, критерий 9*): `raise typer.Exit(code=0 if report.status is NotifyStatus.sent else 1)`. Убрать прямое создание `TelegramNotifier` и `text[:32]`-hash из CLI.

---

## Task 6 — CLI: `audit critical --telegram`

Файл: `src/unifi_manager/cli/audit.py` (заменяет текущий блок Telegram + ручной dedup, ~стр. 63–83).

- [ ] **6.1 (тест-первый)** `tests/unit/test_cli/test_audit.py`:
  - issues есть + broken Telegram config → команда **exit 1 потому что issues**, не из-за notify-краха — *спек тест #3, критерий 8*;
  - обновить существующий `telegram_send=false` тест (логика dedup переехала на сервис-уровень — T4).
- [ ] **6.2** Заменить блок на:
  ```python
  if telegram and issues:
      report = build_notify_service(settings).notify_audit_issues(issues)
      _logger.info("notify: %s (sent=%d dedup=%d failed=%d)", report.status, report.sent, report.skipped_dedup, report.failed)  # видимость suppressed — заметка 3
  raise typer.Exit(code=1 if issues else 0)   # exit по issues — НЕ по notify
  ```
- [ ] **6.3** Подтвердить: `ValueError` наружу не уходит (ловится в `_get_notifier`), exit-код только по issues.

---

## Task 7 — Финальный гейт

- [ ] **7.1** `ruff check src tests` + `mypy src` (--strict core) + `pytest` — всё зелёное.
- [ ] **7.2** Сверить acceptance §7 (22 критерия) поштучно.
- [ ] **7.3** Сверить §8 (10 тестов) — каждый существует и проходит.
- [ ] **7.4** Smoke: `unifi-mgr notify test` с `telegram_send=false` → controlled (exit 1, без traceback); `audit critical --telegram` с broken config → exit по issues.
- [ ] **7.5** Подтвердить нон-голы не заехали: нет summary/cap, нет FileLock для notify, нет статуса `rate_limited`, нет MatrixNotifier (только seam).

---

## Appendix A — Деривация `NotifyReport.status` (из §3, для удобства)

`notify_audit_issues`, first match wins:
```
1. issues пусто                 → no_issues
2. telegram_send=false          → skipped_permissions
3. telegram.enabled=false       → skipped_disabled
4. notifier construction failed → channel_unavailable
5. channel ok:  sent>0, failed==0 → sent
                sent>0, failed>0  → partial
                sent==0,failed>0  → failed
                sent==0,failed==0 → completed   (всё задедуплено)
```
`send`/`test`: `permission off→skipped_permissions / enabled off→skipped_disabled / construction failed→channel_unavailable / send True→sent / send False→failed`. Без `completed`.

## Appendix B — fake Notifier для сервис-тестов

```python
class _FakeNotifier:
    def __init__(self, returns: bool = True) -> None:
        self.returns = returns
        self.calls: list[tuple[str, str]] = []  # (text, hash_key)
    def send_message(self, text: str, *, hash_key: str) -> bool:
        self.calls.append((text, hash_key))
        return self.returns
```
`channel_unavailable`-кейс: `notifier_factory=lambda: (_ for _ in ()).throw(ValueError("no token"))` или фабрика, поднимающая `ValueError`. Для memoization-теста (#5): счётчик вызовов фабрики.

## Appendix C — петля `notify_audit_issues` (контракт записи)

```
state = _channel_state();  if state != enabled → ранний возврат
notifier = _get_notifier(); if notifier is None → NotifyReport(channel_unavailable)   # петли нет
sent = failed = skipped_dedup = 0
for issue in issues:
    hk = f"{issue.issue_type}:{issue.device_mac}"
    if history.is_new_alert(hash_key=hk):
        if notifier.send_message(f"⚠ {issue.severity}: {issue.device_name} — {issue.issue_type}", hash_key=hk):
            sent += 1; history.record_alert(hash_key=hk)      # record ТОЛЬКО после True
        else: failed += 1
    else: skipped_dedup += 1
history.save()                                                # ОДИН раз в конце (критерий 20)
return NotifyReport(status=<по таблице A>, sent=sent, skipped_dedup=skipped_dedup, failed=failed)
```

## Appendix D — digest hash для manual send (§4, критерий 15)

```python
from hashlib import sha256
digest = sha256(f"{level.value}\0{text}".encode()).hexdigest()[:16]
hash_key = f"cli-send:{level.value}:{digest}"
```

---

## Definition of Done

Все 7 Task'ов закрыты; §7 (22) и §8 (10) зелёные; ruff/mypy/pytest чистые; SEC4 закрыт (единая точка kill-switch), T5 закрыт (Enum), T4 закрыт (сервис-уровневый dedup-тест); нон-голы не заехали. Затем — следующий под-проект Track 3 своим циклом.
