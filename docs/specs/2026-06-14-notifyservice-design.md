# NotifyService + Notifier-протокол (дизайн)

**Дата:** 2026-06-14
**Статус:** Approved (брейнсторминг: пользователь, Claude, GPT)
**Track:** Track 3 — архитектурный рефактор, под-проект 1 из 4 (самодостаточный, не трогает domain-нормализацию)
**Закрывает:** SEC4 (kill-switch обходят `notify test`/`send`), T5 (`--level` как plain `str`); попутно T4 (переусложнённый dedup-тест переезжает на уровень сервиса).

---

## Контекст

### Что есть сейчас

Оркестрация уведомлений размазана по CLI, политика permission продублирована «руками»:

- `cli/notify.py` (`notify test`, `notify send`) строит `TelegramNotifier` напрямую и **не проверяет** `permissions.cli.notify.telegram_send` — kill-switch обходится (SEC4).
- `cli/audit.py` (`audit critical --telegram`) проверяет permission *перед* конструированием нотифаера, отдельно руками делает per-issue dedup через `AlertHistory`, сам форматирует сообщения.
- `--level` в `notify send` — это `str` с `{...}.get(level, "")`: мусорное значение молча проходит (T5).
- `notify send` кладёт `hash_key=f"cli-send:{level}:{text[:32]}"` — кусок текста алерта уезжает в throttle-state, плюс коллизии по префиксу.

### Зачем

Вынести оркестрацию в сервис между `cli/` и `integrations/`; сделать **единственный** источник правды по permission/status; ввести seam для каналов (готовность к Matrix без его реализации сейчас). Сервисный слой повторяет уже принятый в проекте паттерн `RestartService` → `RestartReport`.

---

## Цели и не-цели

**Цели:**

- `NotifyService` — единственный authority по permission/status политике уведомлений.
- `Notifier`-протокол как seam: текущий `TelegramNotifier` уже соответствует; будущий `MatrixNotifier` реализует тот же интерфейс.
- `notify test/send` и `audit critical --telegram` ужимаются до «load settings → build_notify_service → один вызов».
- `--level` через `AlertLevel(StrEnum)` (Typer отвергает мусор → exit 2).
- Закрыть SEC4 одной точкой проверки kill-switch.

**Не-цели (явно):**

- **MatrixNotifier** — делаем только seam, реализация канала отложена.
- **Summary/cap-режим.** Сохраняем текущую per-issue семантику (N issues → N сообщений). Агрегированное «N устройств оффлайн» одним сообщением + cap — отдельный future improvement. `NotifyService` — правильный дом под него, но не в этом цикле.
- **FileLock / concurrency hardening для notify.** Atomic save (см. ниже) чинит torn write, но НЕ решает read-modify-write гонку двух пересекающихся cron-ранов по `alert_history.json` (оба прочли `{}`, оба шлют, последний пишет). Двойной алерт под параллельным cron остаётся — ограничен сверху throttle-лимитом 5/мин. Это принятая поза цикла, atomic save её на бумаге не «закрывает».
- **Статус `rate_limited`.** `TelegramNotifier.send_message()` возвращает голый `bool` и не различает {disabled, rate-limited, HTTP-error}. Сервис физически не отличит throttle от ошибки — значению статуса нечем наполниться, в енум его не вводим.
- **Обобщение permission** за пределы `telegram_send` — пока канал один, обобщим, когда придёт Matrix.

---

## 1. Компоненты

### 1.1 `Notifier` (Protocol) — `services/notify.py`

```python
class Notifier(Protocol):
    def send_message(self, text: str, *, hash_key: str) -> bool: ...
```

`TelegramNotifier` уже соответствует. Это и есть seam.

### 1.2 `AlertLevel(StrEnum)` — `services/notify.py`

```python
class AlertLevel(StrEnum):
    info = "info"
    warn = "warn"
    crit = "crit"
```

Typer отвергает прочее (exit 2) — как уже сделано для `--api`/`--method`. Закрывает T5.

### 1.3 Разведение internal channel-state и public report-status

`enabled` — это внутреннее состояние канала, а НЕ исход в отчёте. Два разных енума, чтобы тип `status` не распухал значением, которого в отчёте быть не может:

```python
class _ChannelState(StrEnum):          # internal
    enabled = "enabled"
    skipped_permissions = "skipped_permissions"
    skipped_disabled = "skipped_disabled"


class NotifyStatus(StrEnum):           # public — в NotifyReport
    sent = "sent"
    completed = "completed"
    partial = "partial"
    failed = "failed"
    channel_unavailable = "channel_unavailable"
    skipped_permissions = "skipped_permissions"
    skipped_disabled = "skipped_disabled"
    no_issues = "no_issues"
```

`enabled` НЕ входит в `NotifyStatus`.

### 1.4 `NotifyReport` (frozen dataclass)

По стилю `RestartReport` — статус + счётчики, а не голый `int`/`bool`:

```python
@dataclass(frozen=True)
class NotifyReport:
    status: NotifyStatus
    sent: int = 0
    skipped_dedup: int = 0
    failed: int = 0
```

### 1.5 `NotifyService` — `services/notify.py`

Держит `settings` + инжектированную lazy-фабрику нотифаера + `AlertHistory`.

```python
class NotifyService:
    def __init__(
        self,
        *,
        settings: Settings,
        history: AlertHistory,
        notifier_factory: Callable[[], Notifier],
    ) -> None: ...

    def notify_audit_issues(self, issues: Sequence[AuditIssue]) -> NotifyReport: ...
    def send(self, text: str, *, level: AlertLevel) -> NotifyReport: ...
    def test(self) -> NotifyReport: ...
```

`notify_audit_issues` принимает `AuditIssue` напрямую (не generic `notify_issues`): это форматирование `AuditIssue` (`issue_type`, `device_mac`, `device_name`, `severity`). Связь `services.notify → services.audit` однонаправленная (audit нотифаер не зовёт), циклов нет — `AuditIssueLike`-протокол тут YAGNI.

### 1.6 `build_notify_service(settings)` — `cli/_common.py`

Фабрика **не ветвится на permissions** — отдаёт сервису ленивый constructor:

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

`AlertHistory` строится сразу (дёшево, без сети, без `ValueError`). `TelegramNotifier` НЕ строится здесь — только лениво внутри сервиса и только после прохождения channel-state.

---

## 2. Инвариант permission gate (двухчастный)

`NotifyService` — единственный authority. Никакого второго gate в фабрике (это был бы ровно policy-в-двух-местах: один источник считает allowed, другой — slightly differently).

**Часть 1.** `telegram_send=false` → нотифаер **никогда не конструируется**, валидные креды не требуются.

**Часть 2.** `telegram_send=true && enabled=true && нет bot_token/chat_id` → `TelegramNotifier.__init__` кидает `ValueError`; сервис ловит и возвращает контролируемый `channel_unavailable`, **`ValueError` наружу не пробрасывается**.

Реализуется через **safe-lazy + memoized** `_get_notifier` (мемоизируем и успех, и провал — чтобы кривой конфиг не превращался в N одинаковых попыток):

```python
def _channel_state(self) -> _ChannelState:
    if not self.settings.permissions.cli.notify.telegram_send:
        return _ChannelState.skipped_permissions
    if not self.settings.telegram.enabled:
        return _ChannelState.skipped_disabled
    return _ChannelState.enabled

def _get_notifier(self) -> Notifier | None:
    if self._notifier_attempted:
        return self._notifier
    self._notifier_attempted = True
    try:
        self._notifier = self._notifier_factory()
    except ValueError as e:
        self._channel_error = str(e)
        self._notifier = None
    return self._notifier
```

`_get_notifier()` вызывается **один раз** на инстанс сервиса и только когда `_channel_state() == enabled`. Контракт «build once, reuse»: per-issue конструирование пересоздавало бы `TelegramRateLimiter` и перечитывало throttle-state с диска — total-лимит 5/мин держался бы тогда только «по случайности» и сломался бы при любом батч-сейве.

---

## 3. Деривация `NotifyReport.status`

Это **часть контракта**, не имплементационная деталь: без явной таблицы два нормальных имплементатора напишут разное поведение.

### 3.1 `notify_audit_issues(issues)` — strict precedence, first match wins

```text
1. issues пусто                              → no_issues
2. permissions.cli.notify.telegram_send=false → skipped_permissions
3. settings.telegram.enabled=false            → skipped_disabled
4. notifier construction failed               → channel_unavailable
5. channel ok, issues есть:
     sent > 0,  failed == 0                   → sent
     sent > 0,  failed > 0                    → partial
     sent == 0, failed > 0                    → failed
     sent == 0, failed == 0                   → completed   # все issues задедуплены через AlertHistory
```

Гейты (1–4) идут до счётчиков (5), поэтому `channel_unavailable` (канал не построился) и `failed` (построился, но `send_message` вернул False) — два разных значения, не «или».

При `channel_unavailable` счётчик `failed` — **don't-care** (может быть `len(sendable issues)` или `0`); консьюмер обязан ветвиться по `status`, не по счётчику.

### 3.2 `notify send` / `notify test` — вырожденная однострочная проекция той же функции

```text
permission off        → skipped_permissions
telegram.enabled off  → skipped_disabled
construction failed   → channel_unavailable
send True             → sent
send False            → failed
```

Никакого `completed` для manual send/test (нет dedup-suppression концепта для одиночной ручной отправки).

---

## 4. Per-issue петля и порядок записи

```text
state = _channel_state()
если state != enabled  → ранний возврат (skipped_permissions / skipped_disabled)
notifier = _get_notifier()
если notifier is None  → channel_unavailable

for issue in issues:
    hash_key = f"{issue.issue_type}:{issue.device_mac}"      # текущая human-readable семантика — сохраняем
    if history.is_new_alert(hash_key=hash_key):
        if notifier.send_message(format(issue), hash_key=hash_key):
            sent += 1
            history.record_alert(hash_key=hash_key)           # record ТОЛЬКО после успешного send
        else:
            failed += 1
    else:
        skipped_dedup += 1

history.save()                                                # один раз в конце, не incremental
```

`save()` once-at-end (не incremental как у `RestartService`): для алертов пересыл нескольких при краше безобиден (throttle бэкстопит), incremental тут — только лишние записи.

Для manual `notify send` hash через digest (не `text[:32]` — не хранить куски ручного сообщения в state, не ловить коллизии):

```python
digest = sha256(f"{level.value}\0{text}".encode()).hexdigest()[:16]
hash_key = f"cli-send:{level.value}:{digest}"
```

---

## 5. CLI-правила и exit-коды

**`audit critical`** — exit-код по audit issues, не по notify:

```text
exit 1  если critical issues есть
exit 0  если issues нет
notify result НЕ меняет audit exit code
broken Telegram config НЕ маскирует и не отменяет найденные critical issues
```

(Сохраняет текущее поведение, где `audit critical` ловит `ValueError` вокруг `TelegramNotifier` и выходит по issues — только теперь без исключения наружу.)

**`notify send` / `notify test`** — отправка это основная операция:

```text
exit 0  только если sent
exit 1  при skipped_permissions / skipped_disabled / channel_unavailable / failed (вкл. rate-limit)
```

---

## 6. State persistence

**Имена файлов не менять** (смена пути после деплоя = повторный шторм уже известных алертов):

```text
cache_dir / "alert_history.json"
cache_dir / "telegram_throttle.json"
```

**Atomic save — обоим файлам** (этот цикл, low-risk). Сейчас и `AlertHistory.save()`, и `TelegramRateLimiter._save()` пишут напрямую через `write_text`:

```text
Atomic JSON save helper:
- write tmp рядом с target;
- json.dumps(..., ensure_ascii=False);   # hash_key содержит кириллические имена устройств
- os.replace(tmp, target);
- cleanup tmp при OSError.
```

`telegram_throttle.json` атомарность нужнее, чем `alert_history.json` — он и есть антишторм-бэкстоп (total 5/мин).

**`AlertHistory` corrupt/unreadable → fail-OPEN** (считать alerts новыми), **НЕ** fail-closed. Это НЕ механический перенос с `RestartHistory`: для рестарта «ничего не делать» безопасно, для алертов fail-closed скрыл бы аварию (молчание хуже шума). Шторм при сбросе дедупа ограничен сверху throttle-лимитером.

**Corrupt-policy / FileLock для notify — отдельное решение, не этот цикл** (см. не-цели).

---

## 7. Acceptance criteria

```text
1.  NotifyService — единственный authority по notify permission/status политике.
2.  build_notify_service не ветвится на permissions; отдаёт lazy notifier_factory.
3.  TelegramNotifier строится лениво, только после channel state == enabled.
4.  telegram_send=false никогда не строит TelegramNotifier и не требует валидных кред.
5.  telegram_send=true + telegram.enabled=false → skipped_disabled.
6.  telegram_send=true + telegram.enabled=true + нет bot_token/chat_id
    → channel_unavailable, без утечки ValueError в CLI.
7.  _get_notifier мемоизирует и успешное построение, и провал — once per NotifyService instance.
8.  audit critical exit-код по audit issues, не по notify success/failure.
9.  notify send/test → exit 1 при skipped_permissions / skipped_disabled /
    channel_unavailable / rate-limit / failure.
10. Возвращается NotifyReport, не int/bool.
11. Internal _ChannelState отделён от public NotifyReport.status (enabled не входит в status).
12. notify_audit_issues принимает AuditIssue, сохраняет текущую per-issue dedup-семантику.
13. Per-issue notification — текущее поведение; summary/cap — explicit non-goal.
14. AlertLevel — StrEnum: info | warn | crit.
15. manual notify send hash через digest, не text[:32].
16. Имена state-файлов: alert_history.json, telegram_throttle.json.
17. AlertHistory и TelegramRateLimiter state saves атомарны.
18. AlertHistory corrupt/unreadable остаётся fail-open, не fail-closed.
19. NotifyReport.status считается строго по precedence-таблице (§3.1 / §3.2).
20. AlertHistory.save() вызывается один раз в конце notify_audit_issues, после всех issues.
21. Статус rate_limited не вводится (send_message → bool, не различает throttle/disabled/http).
22. Atomic save заявляется только против torn write, НЕ против RMW-гонки cron-ранов.
```

---

## 8. Обязательные тесты

`test_services/test_notify.py` — `NotifyService` с fake-`Notifier`; чинит T4 (реальный `AlertHistory` + fake `Notifier` на уровне сервиса). `test_cli/test_notify.py` — негативный `--level` (exit 2) + уважение kill-switch.

```text
1.  telegram_send=false + enabled=true + нет token/chat_id
    → TelegramNotifier НЕ конструируется, report skipped_permissions, без ValueError.
2.  telegram_send=true + enabled=true + нет token/chat_id
    → construction attempted once, report channel_unavailable, без ValueError.
3.  audit critical с issues + broken Telegram config
    → команда выходит 1 ПОТОМУ ЧТО issues есть, а не потому что notify упал.
4.  notify send/test + broken Telegram config
    → exit 1 controlled, stderr читаемый.
5.  несколько audit issues
    → notifier_factory вызвана ровно один раз.
6.  issues непусто, sent==0, failed==0, skipped_dedup>0 (всё задедуплено)
    → status == completed.
7.  channel ok, send_message → False на каждый новый issue (sent==0, failed>0)
    → status == failed.
8.  channel unavailable: notifier_factory кидает ValueError
    → status == channel_unavailable; failed может быть len(sendable) ИЛИ 0, но status != failed.
9.  успешный send → record_alert ТОЛЬКО после send_message == True; failed/rate-limited → нет record_alert.
10. atomic save пишет читаемый JSON и сохраняет ensure_ascii=False (кириллица не экранирована).
```

---

## Следующий шаг

Spec заморожена (5 раундов брейнсторминга закрыты, асимметрий не осталось). Дальше — `writing-plans`: план реализации по этому контракту, затем код.
