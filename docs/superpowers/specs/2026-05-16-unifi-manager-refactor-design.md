# UniFi Manager — Полный рефакторинг (дизайн)

**Дата:** 2026-05-16
**Статус:** Approved (брейнсторминг между пользователем, Claude и Gemini)
**Целевая ветка работы:** `refactor/v2`
**Целевая дата завершения:** ~2026-06-13 (4 недели включая cron switch и наблюдение)

---

## Контекст

### Что есть сейчас

`D:\project\unifi_manager` — набор Python-скриптов (~15 файлов), плюс bash-обвязка, развёрнутый на хосте контроллера UniFi (`192.0.2.1`, `/home/operator/unifi_manager/`) и управляющий ~271 устройством в production network. По cron работают:
- `run_audit.sh` (ежедневный полный аудит)
- `check_critical.py` (раз в 15 минут)
- `auto_restart_cron.sh` (раз в 30 минут — авто-рестарт проблемных AP)
- `restart_restaurant_aps_v2.py` (раз в день в 7:00)

Проект является частью более крупной инфраструктурной репы `D:\project\infra`, где есть документация (`docs/network/unifi-framework.md`, `docs/network/unifi-inventory.md`) и зеркало кода в `external_repos/unifi_manager/` (рассинхронизировано: в зеркале есть `diagnostics/*` и одноразовые investigation-скрипты, которых нет в основной репе; критично — там же живёт `SYSID_MAP`, маппинг "реальная модель AP по sysid").

### Найденные проблемы (по результатам аудита 2026-05-16)

**Архитектура:**
- Три почти идентичных файла `restart_restaurant_*.py` (v1, v2, и compact-v2) — эволюционные черновики одной идеи
- 4 разных паттерна работы с UniFi API в одном проекте (общий клиент / `load_config()` + ручная сессия / полностью inline / Integration API ключом)
- Параметры подключения и API-ключ Integration API захардкожены в нескольких .py файлах как fallback'и
- Логирование непоследовательно: половина скриптов через `setup_logger()`, половина просто `print()`
- Нет `requirements.txt`, плоская структура

**Баги (high impact):**
- Timezone-баг в фильтрации событий (`restart_restaurant_aps.py:114`, `restart_restaurant_aps_v2.py:90`): UniFi отдаёт UTC, скрипт сравнивает с naive `datetime.now()`. Для production deployment в non-UTC timezone (например UTC+3) — окно сдвинуто на соответствующее количество часов.
- TOCTOU race в lock-файле `auto_restart_cron.sh:9-18` — два cron-процесса могут одновременно пройти проверку и начать массовый рестарт.
- `restart_restaurant_*.py` не имеют ни lock-файла, ни `max_restarts_per_run` — потенциал шторма рестартов.
- `ZeroDivisionError` в `full_audit_unifi.py:382` при отсутствии PoE budget.
- `login()` в нескольких файлах не проверяет статус — при неверном пароле скрипт молча "не находит AP".
- Bare `except:` в трёх местах проглатывает реальные ошибки парсинга.

**Безопасность (для проекта не критично — credentials специально под AI-агентов):**
- Hard-coded password/API-key в репо. Решено: всё равно перенести в `.env` ради чистоты архитектуры.
- `verify=False` для SSL везде. Решено: оставить `False` по умолчанию (UniFi self-signed), но дать возможность указать путь к pem.

### Зачем рефакторим

- Сейчас изменения требуют редактирования 3-7 похожих файлов с одинаковым кодом.
- Любая регрессия в timezone-логике или cooldown проявляется только в проде через 24 часа.
- Невозможно протестировать `restart` логику без реального запуска против контроллера.
- Невозможно добавить новый "профиль рестарта" (например, для офиса или лобби) иначе как через copy-paste ещё одного `restart_*.py`.
- Любой новый человек / новый AI-агент в проекте тратит часы на понимание "какой из похожих скриптов использовать".

---

## Цели и не-цели

**Цели:**
1. Один установленный пакет (`unifi-mgr`), все операции через единый CLI.
2. Тестируемость каждого слоя в изоляции (unit-тесты с моками HTTP).
3. Сохранение всей текущей функциональности (audit, restart, export, notify, zabbix, dashboard).
4. Сохранение поддержки **обоих** API UniFi: Legacy (session+CSRF) и Integration (X-API-KEY).
5. Конфигурация через типизированный pydantic-settings.
6. Безопасная инкрементальная миграция с возможностью rollback в течение 4 недель.
7. Включение в основной кодбейз диагностических скриптов, которые сейчас живут в зеркале `infra/external_repos/`.
8. **Фаза 7 (после стабилизации миграции):** наблюдаемость (port errors delta, topology drift) и защита от ложных алертов (controller health check, maintenance mode). Архитектура учитывает эти фичи сразу, имплементация — после фазы 6.

**Не-цели:**
1. Поддержка других вендоров (MikroTik, Cisco). Структура слоёв оставляет дверь открытой, но в дизайн не закладывается.
2. Миграция cron → systemd timers. Отдельная мини-фаза в будущем.
3. Docker / Kubernetes. Пакет ставится на bare metal, как сейчас.
4. Web UI. CLI + TUI (`dashboard.sh`) достаточно.
5. Публикация в PyPI. Внутренний инструмент.

---

## Глоссарий

- **Legacy API** — старый UniFi Network API: авторизация через `POST /api/auth/login`, CSRF токен в заголовках, endpoints вида `/proxy/network/api/s/<site>/...`. Используется большинством текущих скриптов.
- **Integration API** — новый UniFi Network Integration API: авторизация через `X-API-KEY` заголовок, endpoints вида `/proxy/network/integration/v1/sites/<uuid>/...`. UUID сайта отличается от short slug, используемого Legacy API. Используется в `audit_unifi.py`, `check_unifi.py`, `export_all_clients.py`.
- **SYSID_MAP** — словарь маппинга `sysid` → реальное имя модели AP. UniFi для некоторых старых моделей возвращает в поле `model` неправильное короткое имя (например `U7IW` вместо `UAP-AC-IW`). Текущие значения: `{58759: 'UAP-AC-IW', 58679: 'UAP-AC-Pro', 58727: 'UAP-AC-M', 58711: 'UAP-AC-M-Pro'}`. Сейчас живёт только в `infra/external_repos/.../diagnostics/infra_deep_v2.py:10`.
- **Профиль рестарта** — именованный набор фильтров AP + порогов в `config.yaml`, под которым работает `unifi-mgr restart profile <name>`. Заменяет три `restart_restaurant_*.py`.
- **`_legacy/`** — папка в репе со старыми скриптами на период миграции (4 недели), с явным DeprecationWarning и датой удаления.
- **Maintenance Mode (mute)** — состояние, при котором `RestartService` игнорирует выбранные устройства или весь site на заданный срок. Хранится в `/var/lib/unifi-mgr/mute_state.json` (фаза 7). Use case: оператор обновляет свитч → mute свитча на 30 минут, чтобы автоматика не дёргала падающие из-за апдейта AP.
  - **Precedence:** site mute и device mute работают по OR — если что-либо в mute, restart blocked. Override device → site не предусмотрен (YAGNI; явный unmute доступен в обе стороны).
  - **TTL и safety:** каждая запись имеет `expires_at`. После истечения — авто-разблокировка при следующем `RestartService.can_restart()`. Максимальный TTL — 24 часа (`MaintenanceSettings.max_mute_duration_hours`), защита от "забыл снять mute".
  - **Логирование:** каждый skip из-за mute → `logger.info("Skipped: muted", extra={"mac": ..., "reason": ..., "expires_at": ..., "scope": "device|site"})` + запись в `restart_history.json` со статусом `SKIPPED_MUTED`.
- **Audit Baseline** — снапшот предыдущего прогона `audit critical`, хранит счётчики port errors и текущую топологию (`uplink_mac` для каждого устройства). Используется для дельта-сравнений (фаза 7). Файл: `/var/lib/unifi-mgr/audit_baseline.json`.
- **Controller Health Check** — pre-check самого контроллера перед audit: DNS resolve + HTTP ping настраиваемых эндпоинтов. Если контроллер сам "офлайн" (нет сети/DNS) — шлём один алерт "controller unreachable" вместо 270 алертов "device offline". Реализуется в фазе 7.
  - **Exit codes** для `audit critical`: `0` = OK, `1` = есть критические проблемы на устройствах, `2` = controller сам недоступен (health-check fail). Это позволяет cron/Zabbix различать "проблема с production network" и "проблема с самой системой мониторинга".

---

## 1. Структура пакета и слои

```
unifi_manager/                       # корень репы (D:\project\unifi_manager)
├── pyproject.toml                   # сборка, метаданные, [project.scripts] для CLI, ruff/mypy/pytest конфиги
├── requirements.txt                 # совместимость со старым pip-стилем (auto-generated из pyproject)
├── .env.example                     # шаблон секретов (в git), `.env` в `.gitignore`
├── config.yaml                      # публичный конфиг (пороги, фильтры, профили, пути)
├── .gitignore                       # config.json (legacy), .env, __pycache__, *.csv/*.json exports, logs
├── README.md
├── .pre-commit-config.yaml
├── .github/workflows/ci.yml
│
├── src/unifi_manager/
│   ├── __init__.py                  # __version__
│   ├── settings.py                  # Settings(BaseSettings) — все pydantic-модели конфига
│   ├── logging_config.py            # setup_logging(settings, verbose, quiet) + SecretsFilter
│   │
│   ├── clients/                     # СЛОЙ 1: HTTP API клиенты (не знают про бизнес-логику)
│   │   ├── __init__.py
│   │   ├── base.py                  # BaseUnifiClient: session, retry, timeout, SSL, exceptions
│   │   ├── legacy.py                # LegacyClient(BaseUnifiClient): login+CSRF, /proxy/network/api/...
│   │   ├── integration.py           # IntegrationClient(BaseUnifiClient): X-API-KEY, /proxy/network/integration/...
│   │   └── exceptions.py            # UnifiAuthError, UnifiAPIError, UnifiTimeoutError
│   │
│   ├── domain/                      # СЛОЙ 2: типизированные модели данных
│   │   ├── __init__.py
│   │   ├── device.py                # Device, AccessPoint (с SYSID_MAP + computed_field real_model), Switch
│   │   ├── event.py                 # ApEvent, EventKey enum (EVT_AP_Lost_Contact, EVT_AP_Disconnected, ...)
│   │   └── client.py                # WirelessClient
│   │
│   ├── services/                    # СЛОЙ 3: бизнес-логика (не знает про HTTP)
│   │   ├── __init__.py
│   │   ├── audit.py                 # AuditService: critical, status, full, light, trends
│   │   ├── restart.py               # RestartService: auto / profile / device, cooldown, history, priority
│   │   ├── export.py                # ExportService: CSV/JSON/XLSX для clients и devices
│   │   ├── notify.py                # NotifyService + AlertHistory (дедупликация critical алертов)
│   │   └── lock.py                  # FileLock через `fasteners` — общее атомарное решение
│   │
│   ├── diagnostics/                 # СЛОЙ 3.5: одноразовые/специальные инструменты (из infra/external_repos/)
│   │   ├── __init__.py
│   │   ├── deep_scan.py             # бывший infra_deep_v2.py
│   │   ├── models.py                # бывший probe_models.py
│   │   ├── edgeswitch.py            # консолидация edgeswitch_probe_v1/v2/v3
│   │   ├── channels.py              # consolidation migrate_channels_legacy + migrate_channels_bld4
│   │   ├── building.py              # обобщение bld4_deep_dive + bld9_switch_audit (--building N)
│   │   ├── port_trace.py            # обобщение port12_investigation (--switch MAC --port N)
│   │   └── switch_trace.py          # НОВОЕ: рекурсивный трассировщик uplink → root
│   │
│   ├── integrations/                # СЛОЙ 4: внешние системы
│   │   ├── __init__.py
│   │   ├── telegram.py              # send_message + escape_markdown_v2 + TelegramRateLimiter
│   │   └── zabbix.py                # форматирование stats в JSON для Zabbix LLD / external check
│   │
│   ├── cli/                         # СЛОЙ 5: Typer entrypoints
│   │   ├── __init__.py              # точка входа `unifi-mgr` (root app)
│   │   ├── audit.py                 # подкоманды audit
│   │   ├── restart.py               # подкоманды restart
│   │   ├── export.py                # подкоманды export
│   │   ├── diag.py                  # подкоманды diag
│   │   ├── notify.py                # подкоманды notify
│   │   ├── zabbix.py                # подкоманды zabbix
│   │   ├── config.py                # подкоманды config (validate, show)
│   │   ├── login.py                 # подкоманды login (test)
│   │   └── legacy.py                # legacy run wrapper (DeprecationWarning)
│   │
│   └── utils/
│       ├── __init__.py
│       ├── time.py                  # UTC parsing, is_within_window, freeze-safe (фикс timezone bug)
│       └── formatting.py            # rich tables, человекочитаемый вывод
│
├── tests/                           # см. Раздел 4
│
├── scripts/                         # shell-обвязка
│   ├── deploy.sh                    # atomic release switch
│   └── (dashboard.sh — переписан на новый CLI, см. ниже)
│
├── _legacy/                         # ВРЕМЕННО (удалить 2026-06-13)
│   ├── README.md                    # дата удаления, mapping old → new
│   ├── config.json                  # старый формат, для legacy-скриптов
│   ├── audit_unifi.py
│   ├── full_audit_unifi.py
│   ├── check_critical.py
│   ├── check_unifi.py
│   ├── auto_restart_problem_aps.py
│   ├── restart_restaurant_aps.py
│   ├── restart_restaurant_aps_v2.py
│   ├── restart_restaurant_v2.py
│   ├── export_all_clients.py
│   ├── unifi_trends.py
│   ├── zabbix_unifi_stats.py
│   ├── telegram_notify.py
│   ├── unifi_client.py
│   ├── run_audit.sh
│   ├── auto_restart_cron.sh
│   └── from_infra/                  # перенесено из infra/external_repos/.../diagnostics/
│       ├── infra_deep_v2.py
│       ├── probe_models.py
│       ├── edgeswitch_probe_v1.py
│       ├── edgeswitch_probe_v2.py
│       ├── edgeswitch_probe_v3.py
│       ├── edgeswitch_fix.py
│       ├── migrate_channels_legacy.py
│       ├── migrate_channels_bld4.py
│       ├── bld9_switch_audit.py
│       ├── bld4_deep_dive.py
│       └── port12_investigation.py
│
└── docs/
    ├── superpowers/specs/2026-05-16-unifi-manager-refactor-design.md   # этот документ
    └── (другая документация)
```

### Принципы слоёв

**5 слоёв с однонаправленной зависимостью:** `cli → services → clients → http`. `domain/` и `utils/` могут использоваться всеми, но сами не зависят ни от кого.

- **`clients/`** ничего не знает про бизнес-логику. `LegacyClient.list_devices()` возвращает список (или `Device` объектов из `domain/`), но никакого "решить, надо ли рестартить".
- **`services/`** ничего не знает про HTTP. В тестах сервисов мокаем клиенты (объекты `BaseUnifiClient`), не HTTP. В тестах клиентов мокаем HTTP через `responses`.
- **`domain/`** — чистые Pydantic-модели с валидацией. Никакого I/O.
- **`cli/`** — тонкий слой: парсит флаги, читает settings, создаёт нужный client, передаёт в service, печатает результат.
- **`diagnostics/`** — параллелен `services/`: использует клиенты, но это одноразовые/специальные операции, не основной flow.

**Layout `src/`** — стандарт современных Python-пакетов: предотвращает случайные импорты "из текущей директории" и заставляет ставить пакет (`pip install -e .`) перед запуском тестов.

### Ключевые решения по domain слою

**`SYSID_MAP` в `domain/device.py`** как константа модуля + `computed_field`:

```python
SYSID_MAP: Final[dict[int, str]] = {
    58759: 'UAP-AC-IW',
    58679: 'UAP-AC-Pro',
    58727: 'UAP-AC-M',
    58711: 'UAP-AC-M-Pro',
}

class AccessPoint(BaseModel):
    model_config = ConfigDict(extra='allow', populate_by_name=True)
    
    mac: str
    sysid: int | None = None
    reported_model: str = Field(alias='model')
    name: str | None = None
    state: int = 0
    # ... другие поля из UniFi API
    
    @computed_field
    @property
    def real_model(self) -> str:
        if self.sysid and self.sysid in SYSID_MAP:
            return SYSID_MAP[self.sysid]
        return self.reported_model
```

**`extra='allow'`** означает: лишние поля (которых UniFi может добавить в новых версиях контроллера) сохраняются в `model_extra` без потерь. Это страховка вместо явного поля `raw_data: dict` — экономит память на сотнях устройств × сотнях клиентов в одном прогоне.

**Fallback при `ValidationError`** — DEBUG-лог сырого JSON, WARN при первом разе для данного типа объекта:
```python
try:
    device = AccessPoint.model_validate(raw)
except ValidationError as e:
    logger.debug("Raw payload that failed validation", extra={"raw": raw})
    logger.warning(f"Failed to parse AccessPoint: {e}", extra={"errors": e.errors()})
    continue
```

---

## 2. CLI поверхность

Единая точка входа `unifi-mgr` через Typer. Все команды поддерживают `--help`.

```
unifi-mgr [--config PATH] [-v|-vv|-q] [--json] [--version]

├── audit
│   ├── critical  [--telegram] [--telegram-cooldown 60m]   [exit 1 если есть критические]
│   ├── status                                              [человекочитаемый снимок]
│   ├── full      [--api legacy|integration|both]          [глубокий, оба API параллельно]
│   ├── light                                               [MAC dup, spoof, перекосы]
│   └── trends    [--days 7]                                [исторические отчёты]
│
├── restart
│   ├── auto      [--dry-run] [--max N]                    [РЕАЛЬНЫЙ запуск по умолчанию — для cron]
│   ├── profile NAME [--apply]                             [DRY-RUN по умолчанию, --apply реальный]
│   └── device --mac MAC [--method restart|poe-cycle] [--apply]   [точечный, dry-run default]
│
├── export
│   ├── clients   [--format csv|json] [--out PATH]
│   └── devices   [--format csv|json|xlsx] [--out PATH]
│
├── diag
│   ├── deep
│   ├── models
│   ├── edgeswitch    [--target MAC]
│   ├── channels      [--building N] [--apply]
│   ├── building      --building N
│   ├── port          --switch MAC --port N
│   └── switch-trace  --mac MAC                            [трассировка uplink → root]
│
├── notify
│   ├── test
│   └── send "text"   [--level info|warn|crit]
│
├── device                                                 [фаза 7]
│   ├── mute     --mac MAC --duration 30m [--reason TEXT]  [maintenance mode на устройство]
│   ├── unmute   --mac MAC                                 [снять mute с устройства]
│   └── list-muted                                         [список замьюченных устройств с TTL]
│
├── site                                                   [фаза 7]
│   ├── mute     --duration 1h [--reason TEXT]             [mute всего site (для апдейтов контроллера)]
│   ├── unmute                                             [снять mute с site]
│   └── status                                             [сводка по site: muted? auto-restart активен?]
│
├── zabbix
│   └── stats                                              [JSON для Zabbix external check]
│
├── config
│   ├── validate                                           [проверка YAML + типов]
│   └── show          [--secrets]                          [рассчитанный config; --secrets требует TTY]
│
├── login
│   └── test          [--api legacy|integration|both]      [не протух ли unifi_user / API key]
│
└── legacy
    └── run <script_name> [-y|--no-confirm] [--list]       [deprecated wrapper до 2026-06-13]
```

### Глобальные флаги

- `--config PATH` — путь к `config.yaml` (порядок поиска: CLI > `./config.yaml` > `~/.config/unifi-mgr/config.yaml` > `/etc/unifi-mgr/config.yaml`)
- `--dry-run` — для всех команд, изменяющих состояние сети
- `--json` — машинный вывод для cron-обвязок и Zabbix
- `-v` / `-vv` — console уровень до DEBUG (на file-log не влияет, там всегда DEBUG)
- `-q` — console уровень до WARNING
- `--api {legacy|integration|auto}` — выбор API там, где применимо
- `--site SITE` — переопределить site из конфига
- `--version`

### Принципиальные решения по CLI

**`restart profile` дефолтом `--dry-run`, реальный запуск только через `--apply`.** Это "защита от дурака" для оператора в консоли. В cron — пишется один раз с `--apply` и забывается. Для `restart auto` (cron-команда) — наоборот, по умолчанию реальный запуск, защита уже встроена внутри (cooldown, max_per_run, history). Для `restart device` — дефолтом `--dry-run`, точечная операция требует осознанного `--apply`.

**`audit critical --telegram` с дедупликацией.** Хэш `(mac, error_type)` сохраняется в `~/.cache/unifi-mgr/last_alert.json`. Telegram-уведомление шлётся только если набор проблем изменился относительно прошлого запуска. `--telegram-cooldown 60m` — даже если состав тот же, разрешить повтор каждый час.

**Профили рестарта в `config.yaml` вместо отдельных скриптов:**
```yaml
restart_profiles:
  restaurant:
    filter_names: [Restoran, "Restoran WIFI", "Rest Bar"]
    exclude_names: ["Spasatel vagon"]
    lost_contact_threshold: 3
  office:
    filter_patterns: ["^office.*"]
    lost_contact_threshold: 5
```
Любой профиль вызывается как `unifi-mgr restart profile <name>`. Добавить новый — блок в YAML, без правки кода.

**`legacy run <script>`** с обязательным интерактивным подтверждением (если не передан `-y`):
```
$ unifi-mgr legacy run restart_restaurant_v2.py
⚠️  LEGACY MODE — running _legacy/restart_restaurant_v2.py
⚠️  This script will be REMOVED on 2026-06-13. Use `unifi-mgr restart profile restaurant` instead.
Continue? [y/N]
```

---

## 3. Configuration & Logging

### 3.1 Configuration

**Источники (от низкого приоритета к высокому):**
```
defaults в коде → config.yaml → .env → переменные окружения → CLI флаги
```

**Schema** (`src/unifi_manager/settings.py`):

```python
class UnifiAuthSettings(BaseModel):
    host: str
    port: int = 11443
    site: str                          # short slug ("site-1") для Legacy API
    site_id_uuid: str | None = None    # UUID для Integration API
    username: SecretStr | None = None
    password: SecretStr | None = None
    api_key: SecretStr | None = None
    verify_ssl: bool | Path = False    # False / путь к CA pem

class TelegramSettings(BaseModel):
    bot_token: SecretStr | None = None
    chat_id: str | None = None
    enabled: bool = True
    parse_mode: Literal["MarkdownV2", "HTML", "None"] = "MarkdownV2"
    rate_limit_per_hash_seconds: int = 30
    rate_limit_total_per_minute: int = 5

class RestartProfile(BaseModel):
    filter_names: list[str] = []
    filter_patterns: list[str] = []
    exclude_names: list[str] = []
    exclude_patterns: list[str] = []
    # Триггер: количество EVT_AP_Lost_Contact за window_hours СТРОГО БОЛЬШЕ threshold
    # (сохраняет совместимость с поведением restart_restaurant_*.py: `if count > threshold`)
    lost_contact_threshold: int = 3
    window_hours: int = 24
    max_restarts: int = 5      # макс. рестартов за один запуск этого профиля
    cooldown_minutes: int = 60

class AutoRestartSettings(BaseModel):
    max_restarts_per_run: int = 5
    cooldown_minutes: int = 60
    offline_threshold_min: int = 15
    exclude_patterns: list[str] = []
    statefile: Path = Path("/var/lib/unifi-mgr/restart_history.json")

class ThresholdsSettings(BaseModel):
    critical_temp_c: int = 70
    critical_poe_percent: int = 90
    high_cu_percent: int = 50
    # Фаза 7: триггер WARNING если на любом порту свитча счётчик ошибок
    # вырос больше чем на N между двумя прогонами audit critical.
    # Сравнение через audit_baseline.json. 0 = отключено.
    port_error_delta_threshold: int = 50

class AuditHealthCheckSettings(BaseModel):
    """Фаза 7: pre-check контроллера перед audit critical.
    Если health-check fail — audit critical шлёт ОДИН алерт
    "Controller unreachable" вместо 270 алертов "Device offline" (exit code 2).
    """
    enabled: bool = True
    dns_servers: list[str] = ["8.8.8.8", "1.1.1.1"]
    http_endpoints: list[str] = ["https://www.cloudflare.com", "https://www.google.com"]
    timeout_seconds: int = 5

class MaintenanceSettings(BaseModel):
    """Фаза 7: maintenance mode для защиты от ложных рестартов при работах.
    RestartService проверяет этот state-файл перед любым действием
    и пропускает muted устройства / весь site.
    """
    mute_state_file: Path = Path("/var/lib/unifi-mgr/mute_state.json")
    audit_baseline_file: Path = Path("/var/lib/unifi-mgr/audit_baseline.json")
    default_mute_duration_minutes: int = 30
    max_mute_duration_hours: int = 24    # защита от "забыл снять mute"

class _PermRestart(BaseModel):
    execute: bool = True            # глобальный kill для всей restart категории
    profile_apply: bool = True      # отключает только `restart profile *`
    device_apply: bool = True       # отключает только `restart device --apply`


class _PermNotify(BaseModel):
    telegram_send: bool = True      # доп. kill поверх telegram.enabled


class _CliPermissions(BaseModel):
    """D30 refinement (2026-05-18): cli namespace.

    Default permissive (True) — backward compat для existing cron-задач.
    Если в config.yaml блок `permissions:` отсутствует, ничего не ломается.
    """
    restart: _PermRestart = _PermRestart()
    notify: _PermNotify = _PermNotify()


class _McpPermissions(BaseModel):
    """D30 refinement: mcp namespace (Phase 4M).

    Default RESTRICTIVE (False) — opt-in оператором.
    У LLM нет `--apply` barrier, поэтому MCP-вызовы должны быть явно разрешены.
    """
    restart_execute: bool = False
    notify_send: bool = False


class PermissionsSettings(BaseModel):
    """D30: config-level kill-switches.

    Refinement (2026-05-18): split на `cli` (default True) и `mcp` (default False)
    namespaces для подготовки к Phase 4M (MCP wrapper) без поломки config schema.

    Пример: чтобы экстренно отключить весь автоматический рестарт из cron,
    оператор ставит `permissions.cli.restart.execute: false` в config.yaml
    — cron-job'ы продолжают вызываться, но не доходят до API.
    """
    cli: _CliPermissions = _CliPermissions()
    mcp: _McpPermissions = _McpPermissions()

class LoggingSettings(BaseModel):
    log_dir: Path = Path("/var/log/unifi-mgr")
    console_format: Literal["human", "json"] = "human"
    file_format: Literal["json"] = "json"      # файлы всегда JSON
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    max_bytes: int = 10_000_000
    backup_count: int = 5

class PathsSettings(BaseModel):
    reports_dir: Path = Path("/var/lib/unifi-mgr/reports")
    export_dir: Path = Path("/var/lib/unifi-mgr/exports")
    cache_dir: Path = Path.home() / ".cache/unifi-mgr"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="UNIFI_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="forbid",
    )
    unifi: UnifiAuthSettings
    telegram: TelegramSettings = TelegramSettings()
    auto_restart: AutoRestartSettings = AutoRestartSettings()
    restart_profiles: dict[str, RestartProfile] = {}
    thresholds: ThresholdsSettings = ThresholdsSettings()
    logging: LoggingSettings = LoggingSettings()
    paths: PathsSettings = PathsSettings()
    # D30 (Phase 3): permission kill-switches (config-level emergency override).
    permissions: PermissionsSettings = PermissionsSettings()
    # Фаза 7 (DEFERRED, см. D28): новые блоки. Оставлены в schema для совместимости
    # с уже написанным config.yaml.example, но services к ним не обращаются.
    audit_health_check: AuditHealthCheckSettings = AuditHealthCheckSettings()
    maintenance: MaintenanceSettings = MaintenanceSettings()
```

**`extra="forbid"`** — неизвестные ключи дают ошибку валидации при `config validate`. Защита от опечаток в YAML.

**Пример `config.yaml`** (коммитится):
```yaml
unifi:
  host: 192.0.2.1
  port: 11443
  site: site-1
  site_id_uuid: bbffb94c-xxxx-xxxx-xxxx-xxxxxxxxxxxx
  verify_ssl: false

telegram:
  chat_id: "123456789"
  enabled: true

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

thresholds:
  critical_temp_c: 70
  critical_poe_percent: 90

logging:
  log_dir: /var/log/unifi-mgr
  level: INFO
```

**`.env`** (.gitignore, рядом — `.env.example` в git):
```bash
UNIFI_UNIFI__USERNAME=unifi_user
UNIFI_UNIFI__PASSWORD=your-unifi-password
UNIFI_UNIFI__API_KEY=your-integration-api-key
UNIFI_TELEGRAM__BOT_TOKEN=123456789:ABCdef...
```

### 3.2 Logging

**Единый `dictConfig` в `logging_config.py`**, вызывается первым делом из любой CLI команды.

| Handler | Куда | Формат | Уровень |
|---|---|---|---|
| `console` | stderr | human (через `rich.logging.RichHandler`) | INFO дефолт, изменяется `-v`/`-q` |
| `file_rotating` | `/var/log/unifi-mgr/unifi-mgr.log` | JSON | DEBUG всегда |
| `telegram` | TG-чат | MarkdownV2 (escaped) | WARNING+, только если `telegram.enabled` |

**Формат JSON-записи в файле:**
```json
{"ts":"2026-05-16T14:23:01.123Z","level":"WARNING","logger":"unifi_manager.services.restart",
 "msg":"Cooldown active for AP","ap_mac":"aa:bb:cc:dd:ee:ff","ap_name":"Restoran",
 "cooldown_remaining_sec":1830,"cmd":"restart auto","run_id":"f0a3..."}
```

Любые kwargs из `logger.warning("text", extra={...})` сериализуются как поля JSON. Это даёт грепабельность через `jq`:
```bash
jq 'select(.cmd == "restart auto" and .level == "WARNING")' /var/log/unifi-mgr/unifi-mgr.log
```

**`SecretsFilter`** — `logging.Filter`, регистрируется на root logger. Сканирует `record.msg` и `record.args` на наличие значений зарегистрированных `SecretStr` (password, api_key, bot_token) и заменяет на `***REDACTED***`. Страховка на случай `logger.exception()` с request body.

**`TelegramRateLimiter`** (`integrations/telegram.py`):
- State в файле `paths.cache_dir / "telegram_throttle.json"`
- Лимиты из `TelegramSettings`:
  - `rate_limit_per_hash_seconds: 30` — для одинаковых `(mac, error_type)` не чаще 1 раз в 30 сек
  - `rate_limit_total_per_minute: 5` — суммарно не более 5 разных сообщений в минуту
- При превышении — `logger.debug("Telegram rate-limit blocked", extra={...})`, не отправляется

**Чего НЕ делаем:**
- Не используем `structlog` — стандартного `logging` + JSON-formatter достаточно.
- Не используем `loguru` — плохая интеграция с Sentry/OpenTelemetry/journalctl.
- Не пишем per-command файлы (`auto_restart_YYYYMMDD_HHMM.log` как в текущем коде) — JSON-фильтрация по `cmd` и `run_id` даёт то же самое, но без захламления диска.

---

## 4. Tests & CI

### 4.1 Стек

| Инструмент | Назначение |
|---|---|
| pytest, pytest-cov, pytest-mock, pytest-xdist | runner, coverage, моки, параллель |
| responses | mock HTTP для `requests` |
| freezegun | заморозка времени для timezone и cooldown тестов |
| **hypothesis** | property-based тесты для `utils/time.py` (обязательно) |
| ruff | lint + format (заменяет black + isort + flake8 + pyupgrade) |
| mypy | type checking (`--strict` для core, обычный для cli/utils) |
| pre-commit | git hooks |

**Python:** 3.12 only (Ubuntu 24.04 LTS на проде). Никакой matrix.

### 4.2 Структура `tests/`

```
tests/
├── conftest.py
├── fixtures/                                    # JSON snapshots реальных ответов (anonymized)
│   ├── stat_device_response.json
│   ├── stat_event_response.json
│   ├── integration_devices.json
│   ├── settings_minimal.yaml
│   └── settings_full.yaml
│
├── unit/
│   ├── test_clients/
│   │   ├── test_base.py                         # retry, timeout, SSL, exceptions
│   │   ├── test_legacy.py                       # CSRF token, login flow
│   │   └── test_integration.py                  # X-API-KEY header
│   │
│   ├── test_domain/
│   │   ├── test_device.py                       # Pydantic parsing, SYSID_MAP → real_model
│   │   ├── test_event.py
│   │   └── test_validation_fallback.py          # ValidationError → DEBUG лог
│   │
│   ├── test_services/
│   │   ├── test_restart_auto.py                 # cooldown, max_per_run, priority, history
│   │   ├── test_restart_profile.py              # filter_names/patterns, dry-run default
│   │   ├── test_audit.py                        # exit codes, --telegram dedup
│   │   ├── test_export.py                       # CSV/JSON/XLSX
│   │   ├── test_notify.py                       # AlertHistory dedup
│   │   └── test_lock.py                         # FileLock параллельный запуск
│   │
│   ├── test_integrations/
│   │   ├── test_telegram.py                     # MarkdownV2 escape, rate-limit
│   │   └── test_zabbix.py                       # LLD JSON формат
│   │
│   ├── test_cli/
│   │   ├── test_audit.py                        # CliRunner: exit codes
│   │   ├── test_restart.py                      # --dry-run default, --apply
│   │   ├── test_config.py                       # validate, show --secrets защита
│   │   └── test_legacy.py                       # DeprecationWarning, --list
│   │
│   ├── test_utils/
│   │   ├── test_time.py                         # КРИТИЧНЫЙ: timezone + Hypothesis
│   │   └── test_formatting.py
│   │
│   └── test_settings.py                         # приоритеты источников, validation
```

Папка `tests/integration/` не создаётся — решено не делать integration-тесты против прода (нет выделенного тестового контроллера, риск ложных алертов в TG).

### 4.3 Coverage targets

| Слой | Цель |
|---|---|
| `utils/time.py` | **100%** (источник одного из багов аудита) |
| `services/` | 90%+ |
| `clients/` | 85%+ |
| `domain/` | 90%+ |
| `cli/` | 70%+ |
| `integrations/` | 85%+ |
| **Overall** | **80%+** (`--cov-fail-under=80` ломает CI) |

### 4.4 CI: GitHub Actions

`.github/workflows/ci.yml`:
```yaml
name: CI
on: [push, pull_request]

jobs:
  lint-type:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12", cache: pip}
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: ruff format --check .
      # strict для core (бизнес-логика и инфраструктура): clients, domain, services,
      # integrations, diagnostics, settings.py, logging_config.py
      - run: mypy --strict src/unifi_manager/clients src/unifi_manager/domain src/unifi_manager/services src/unifi_manager/integrations src/unifi_manager/diagnostics src/unifi_manager/settings.py src/unifi_manager/logging_config.py
      # обычный mypy для слоёв с фреймворк-магией (Typer декораторы, Rich форматирование)
      - run: mypy src/unifi_manager/cli src/unifi_manager/utils

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12", cache: pip}
      - run: pip install -e ".[dev]"
      - run: pytest --cov --cov-fail-under=80

  build:
    needs: [lint-type, test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install build
      - run: python -m build
      - uses: actions/upload-artifact@v4
        with:
          name: wheel
          path: dist/*.whl
```

Никакой публикации в PyPI, никакого Codecov (приватная репа), никакого Docker.

### 4.5 Pre-commit

`.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
        additional_dependencies: [pydantic, types-requests]
  - repo: local
    hooks:
      - id: pytest-fast
        name: pytest-fast
        entry: pytest -m fast --no-cov
        language: system
        pass_filenames: false
```

Маркер `@pytest.mark.fast` ставится на быстрые юниты, чтобы pre-commit не висел.

---

## 5. Migration & Cron

### 5.1 Стратегия: incremental, не big-bang

Cron-задачи переключаются по одной, начиная с read-only (`audit`). Между переключениями — минимум 24 часа наблюдения. `_legacy/` держится 4 недели — мгновенный rollback одной строкой crontab.

### 5.2 Фазы

| # | Фаза | Длит. | Гейт готовности |
|---|---|---|---|
| 0 | Foundation: pyproject, dev зависимости, ruff/mypy/pytest, CI, скелет `src/unifi_manager/`, `settings.py` | 1-2 дня | CI зелёный на пустом проекте, `unifi-mgr --version` работает |
| 1 | Core: `clients/`, `domain/` с SYSID_MAP, `utils/time.py` с hypothesis | 2-3 дня | mypy --strict зелёный для core, coverage 90%+ |
| 2 | Services + integrations: `services/{audit,export,lock,notify}`, `integrations/{telegram,zabbix}` с rate-limit | 2-3 дня | unit-тесты всех сервисов зелёные |
| 3 | Restart: `services/restart.py` (auto + profile), миграция формата `restart_history.json` | 2-3 дня | Cooldown/dry-run/max edge-cases покрыты; `--dry-run` против прода даёт ожидаемый вывод |
| 4 | CLI: все Typer-команды, `dashboard.sh` переписан под новый CLI | 2-3 дня | CliRunner smoke-тесты проходят, все `--help` работают |
| **4M** | **(parallel track, опциональная)** MCP server wrapper поверх `services/` для Claude / локальных LLM | 1-2 дня | `unifi-mgr-mcp` запускается, tools видны через `mcp inspect`, 5+ tools покрывают audit/export/restart-dry-run; не блокирует Phase 5 |
| 5 | Cron switch (на проде, постепенно): см. таблицу ниже | ~1 неделя | Все cron-job'ы на новом CLI, 7 дней без регрессий |
| 6 | Cleanup: удаление `_legacy/`, обновление `infra/docs/network/unifi-framework.md`, sync infra-зеркала | 1 день | `_legacy/` пуст, infra документация актуальна |
| ~~7~~ | ~~Post-migration features~~ — **DEFERRED** (см. D28). Делается по факту инцидентов как отдельные мини-проекты, не в рамках этого refactor | — | — |
| **4R** | **(parallel track)** Report module — HTML/JSON отчёт через `ReportService` + `RecommendationEngine`. Отдельный спек: [`2026-05-18-unifi-manager-report-module-design.md`](2026-05-18-unifi-manager-report-module-design.md). Зависит от Phase 4 (CLI скелет) (см. D33) | 2-3 дня | `unifi-mgr report generate` выдаёт self-contained HTML + JSON snapshot |

**Итого:** ~3 недели работы + 2 недели наблюдения после Cron switch = ~5 недель до cleanup. Phase 4M добавляет 1-2 дня (опционально).

**Гейт завершения refactor:** Phase 6 done + `_legacy/` удалён + 7 дней prod-наблюдения без регрессий. Phase 7 фичи больше не часть этого спека (см. D28).

### 5.3 Контракт `_legacy/`

- `_legacy/README.md` содержит явную дату удаления (**2 недели после tag `phase-6-complete`**, см. D29) и mapping старых скриптов на новые команды.
- Запуск через `unifi-mgr legacy run <script>` — с интерактивным подтверждением (или `-y` для cron).
- Прямой запуск `python3 _legacy/<script>.py` остаётся работоспособным.
- `_legacy/config.json` — старый формат, используется только legacy-скриптами.
- `_legacy/from_infra/` — диагностические скрипты, перенесённые из `infra/external_repos/.../diagnostics/`. После Cleanup-фазы эти инструменты живут в `src/unifi_manager/diagnostics/`, а исходники удаляются.

### 5.4 Cron migration table

Переключаем строго по порядку, между шагами 24+ часа наблюдения. Между шагами 4 и 5 — 3-4 дня.

| # | Старое | Новое | Риск |
|---|---|---|---|
| 1 | `0 9 * * * /home/operator/unifi_manager/run_audit.sh` | `0 9 * * * /opt/unifi-mgr/bin/unifi-mgr audit full --json >> /var/log/unifi-mgr/cron-audit.log 2>&1` | низкий |
| 2 | `*/15 * * * * /home/operator/unifi_manager/check_critical.py >> ...` | `*/15 * * * * /opt/unifi-mgr/bin/unifi-mgr audit critical --telegram --json` | низкий |
| 3 | (новое) | `0 6 * * * /opt/unifi-mgr/bin/unifi-mgr audit trends --json >> ...` | нулевой |
| 4 | `0 7 * * * .../restart_restaurant_aps_v2.py` | `0 7 * * * /opt/unifi-mgr/bin/unifi-mgr restart profile restaurant --apply` | средний |
| 5 | `*/30 * * * * .../auto_restart_cron.sh` | `*/30 * * * * /opt/unifi-mgr/bin/unifi-mgr restart auto` | высокий |

Lockfile `auto_restart_cron.sh` больше не нужен — `services/lock.py` через `fasteners` делает атомарную блокировку внутри Python-процесса. Фикс TOCTOU из аудита.

### 5.5 Deployment layout

```
/opt/unifi-mgr/                                # установка (Enterprise standard)
├── current -> releases/2026-05-20-abc1234/   # symlink на актуальный релиз
├── releases/
│   ├── 2026-05-16-aaa1111/                   # предыдущий для rollback
│   │   ├── .venv/
│   │   └── src/unifi_manager/
│   └── 2026-05-20-abc1234/
└── bin/unifi-mgr                              # symlink → current/.venv/bin/unifi-mgr

/etc/unifi-mgr/
├── config.yaml                                # 640 root:unifi-mgr
└── .env                                       # 600 root:root (секреты)

/var/log/unifi-mgr/                            # 755 unifi-mgr:unifi-mgr
└── unifi-mgr.log                              # JSON, rotating 10MB × 5

/var/lib/unifi-mgr/                            # 750 unifi-mgr:unifi-mgr
├── restart_history.json
├── telegram_throttle.json
├── reports/
└── exports/
```

**Deploy скрипт** (`scripts/deploy.sh`):
```bash
#!/usr/bin/env bash
set -euo pipefail
RELEASE_ID="$(date +%Y-%m-%d)-$(git rev-parse --short HEAD)"
RELEASE_DIR="/opt/unifi-mgr/releases/$RELEASE_ID"
mkdir -p "$RELEASE_DIR"
git archive HEAD | tar -x -C "$RELEASE_DIR"
python3.12 -m venv "$RELEASE_DIR/.venv"
"$RELEASE_DIR/.venv/bin/pip" install -e "$RELEASE_DIR"
ln -sfn "$RELEASE_DIR" /opt/unifi-mgr/current.new
mv -Tf /opt/unifi-mgr/current.new /opt/unifi-mgr/current
echo "Deployed $RELEASE_ID"
```

Cron не перезапускается — он использует стабильный путь `/opt/unifi-mgr/bin/unifi-mgr`, который не меняется. Меняется только цель симлинка `current`.

**Rollback:**
```bash
ln -sfn /opt/unifi-mgr/releases/2026-05-16-aaa1111 /opt/unifi-mgr/current
```

### 5.6 Sync с infra-репой

**Решение:** простой rsync-скрипт, не git submodule.

`infra/scripts/sync_unifi_manager.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
rsync -av --delete \
  --exclude=.git --exclude=.venv --exclude=__pycache__ \
  --exclude='*.csv' --exclude='*.log' --exclude='.env' \
  "$HOME/project/unifi_manager/" external_repos/unifi_manager/
echo "Synced unifi_manager → external_repos/unifi_manager/"
```

После завершения рефакторинга `infra/docs/network/unifi-framework.md` переписывается под новую архитектуру (вместо описания старых .py-файлов — описание Typer-команд, слоёв, конфига).

### 5.7 `dashboard.sh` wrapper

Сохраняется как TUI для оператора. Меняются только тела `case`-веток:

```bash
# Старое: python3 "$DIR/check_critical.py"
# Новое:  unifi-mgr audit critical

# Старое: python3 "$DIR/full_audit_unifi.py"
# Новое:  unifi-mgr audit full

# Старое: python3 "$DIR/unifi_trends.py"
# Новое:  unifi-mgr audit trends

# Старое: python3 "$DIR/auto_restart_problem_aps.py"
# Новое:  unifi-mgr restart auto --dry-run        # из TUI ВСЕГДА с --dry-run, потому что
                                                  # TUI = операторский интерфейс (защита от опечатки),
                                                  # cron вызывает ту же команду БЕЗ --dry-run (реальный запуск).
                                                  # Для реального запуска из TUI оператор подтверждает
                                                  # отдельным пунктом меню "Запустить (реально)".

# Старое: nano "$CONFIG"
# Новое:  ${EDITOR:-nano} /etc/unifi-mgr/config.yaml
```

### 5.8 Risk register

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| Новый `restart auto` рестартит лишнее | Низкая | Высокое | `--dry-run` 3-4 ручных прогона до cron switch, сравнение со старым выводом |
| Несовместимый формат `restart_history.json` | Низкая | Среднее | Тест `test_loads_legacy_history` в фазе 3 |
| Cron путь неверный (`/opt/unifi-mgr/bin/unifi-mgr` не найден) | Средняя | Высокое | Smoke-тест после каждого deploy: `/opt/unifi-mgr/bin/unifi-mgr --version` |
| `.env` потерян / права 644 | Средняя | Критическое | `systemd-tmpfiles` + `chmod 600`; `unifi-mgr login test` в health-check |
| Telegram-шторм при инциденте | Средняя | Среднее | Rate-limit реализован и покрыт тестами |
| Регрессия в timezone | Низкая | Высокое | Hypothesis для `utils/time.py`, ручной тест в день переключения cron |

**Rollback процедуры (по убыванию инвазивности):**
1. Одна cron-job сломала прод → откатить одну строку crontab на старый `_legacy/<script>.py`. < 1 мин.
2. Весь пакет проблемный → `ln -sfn /opt/unifi-mgr/releases/<previous> /opt/unifi-mgr/current`. < 1 мин.
3. State в `restart_history.json` испорчен → `cp _legacy/ap_restart_history.json /var/lib/unifi-mgr/restart_history.json`. Формат совместим в обе стороны.

---

## Принятые решения (decision log)

| # | Решение | Обоснование |
|---|---|---|
| D1 | Полный пакет с тестами и CI (а не точечные правки) | Текущий долг такой, что точечные правки не решают |
| D2 | `BaseClient + LegacyClient + IntegrationClient` (а не единый client с `mode`) | Чистое разделение, легче тестируется, API дают разные endpoints |
| D3 | `pydantic-settings` + `.env` + `config.yaml` | Типизация всего конфига, единая схема, fail-fast при опечатках |
| D4 | Typer для CLI (а не Click/argparse) | Type-hints вместо boilerplate, хорошо сочетается с pydantic |
| D5 | Все три `restart_restaurant_*.py` → удаляются, заменяются профилем в YAML | Дублирование кода устраняется, новые "профили" — без кода |
| D6 | SYSID_MAP в `domain/device.py` как `Final[dict[int, str]]` + `computed_field` | Сейчас живёт только в infra-зеркале, должен быть в основной репе |
| D7 | `raw_data` через `ConfigDict(extra='allow')`, не отдельное поле | Экономия памяти на сотнях устройств × клиентов |
| D8 | ~~`_legacy/` папка на 4 недели до 2026-06-13~~ — **superseded by D29** | (см. D29) |
| D9 | `restart profile` дефолтом `--dry-run`, реальный через `--apply` | Защита от опечатки в стрессовой ситуации |
| D10 | `audit critical --telegram` с дедупликацией по `(mac, error_type)` | Защита от шторма алертов |
| D11 | `/var/log/unifi-mgr` и `/var/lib/unifi-mgr` (Enterprise layout) | Жёсткие права на секреты, не в home |
| D12 | `rich.logging.RichHandler` для console | Читаемые таблицы и логи окупают +7 MB зависимости |
| D13 | Telegram rate-limit: 1/30s per hash, 5/min суммарно | Защита от шторма в реальном инциденте |
| D14 | Python 3.12 only в CI | Ubuntu 24.04 LTS на проде, упрощает CI |
| D15 | Только unit-тесты, без integration против прода | Нет тестового контроллера, риск ложных алертов |
| D16 | mypy `--strict` для `clients/`, `domain/`, `services/`; обычный для `cli/`, `utils/` | Ядро должно быть безупречно, не воевать с декораторами Typer |
| D17 | Без Codecov, `--cov-fail-under=80` в GH Actions | Приватная репа, лимиты не нужны |
| D18 | Hypothesis обязателен для `utils/time.py` | Timezone-bug коварен, нужна property-based проверка |
| D19 | Rsync-скрипт для sync с infra-зеркалом (не submodule) | Submodule создаёт detached HEAD проблемы при срочных правках |
| D20 | `/opt/unifi-mgr/` (не `/home/operator/`) | Enterprise standard, жёсткие права 600 на .env |
| D21 | Cron остаётся (не migrate на systemd timers) | Слишком много меняется одновременно, systemd — отдельная мини-фаза в будущем |
| D22 | `legacy run` команда с DeprecationWarning и интерактивным подтверждением | UX единой точки входа без маскировки факта legacy |
| D23 | Post-migration features (port errors delta, maintenance mode, controller health check, uplink logging) — в отдельной фазе 7 | Не смешивать миграцию и новые фичи; отдельный rollback; архитектура готова сразу, имплементация после стабилизации |
| D24 | Controller health check — настраиваемые DNS-серверы и HTTP-эндпоинты, не хардкод `google.com` | В закрытых/изолированных production сетях google может быть заблокирован; внутренние резолверы и эндпоинты — гибкость |
| D25 | Maintenance mode с max TTL 24 часа | Защита от "забыл снять mute" — авто-разблокировка устройств после суток |
| D26 | EdgeSwitch SSH client — НЕ в этот спек, отдельный follow-up | Принципиально другой протокол (SSH/pexpect, не HTTP/JSON); другая иерархия клиентов; новые зависимости и тестовая инфраструктура |
| D27 | Команда `diag edgeswitch` остаётся в дизайне как REST-через-UniFi-контроллер (не прямой SSH) | Покрывает 80% use cases без введения нового семейства клиентов |
| **D28** | **Phase 7 (post-migration features) полностью отложена** — port errors delta, maintenance mode, controller health check, uplink change logging реализуются по факту инцидентов как отдельные мини-проекты, не упреждающе | External review (2026-05-18) указал что Phase 7 нарушает D23 ("не смешивать миграцию и новые фичи"); 4 независимые фичи без подтверждённых use cases — overkill для proactive build |
| **D29** | **`_legacy/` 2 недели после Phase 6** (вместо 4 недель до фикс-даты) | 4 недели = паранойя; 1 неделя = risky если cron switch затянется; 2 недели — middle ground с буфером после observation period |
| **D30** | **`PermissionsSettings` config-уровневые kill-switches** для restart/notify. **Refinement (2026-05-18):** namespace `permissions.cli.*` (CLI/cron entry-points, default permissive=True) vs `permissions.mcp.*` (Phase 4M, default restrictive=False). Backward-compat: отсутствующий `permissions` блок = все cli.* True. | Pattern из sirkirby/unifi-mcp; emergency response без правки crontab. Namespace future-proof для Phase 4M (у LLM нет --apply barrier, поэтому MCP opt-in). |
| **D31** | **Phase 4M (parallel, опциональная)** — FastMCP wrapper поверх `services/`. Не блокирует Phase 5, доступен Claude + локальным моделям как дополнительный интерфейс | `services/` уже без HTTP-зависимостей — идеальный backend для FastMCP. ~200-300 строк. Не конкурирует с sirkirby/unifi-mcp (тот generic, наш specific для конкретного production deployment) |
| **D32** | **Extended SYSID_MAP** — seed dict из tnware/unifi-controller-api как **base**, наши 4 entries — **overlay поверх** (перезаписывают при конфликте). **Refinement (2026-05-18):** при попытке lookup отсутствующего sysid — log `sysid_gap` warning + Phase 4R recommendation для пополнения карты по реальности production network. | Их словарь покрывает шире, наши 4 — точечные fixes. Зависимости не добавляем, копируем только const. `sysid_gap` warning делает карту самообогащающейся через ops feedback. |
| **D33** | **Report module отдельным спеком** — `2026-05-18-unifi-manager-report-module-design.md`. Phase 4R parallel track. Не блокирует основной рефакторинг. Идеи from FryguyPA (self-contained Jinja2 + inline SVG + 4 темы + recommendations engine + JSON snapshots), кода не берём. | HTML report оказался отдельным аналитическим слоем (`ReportService` + `RecommendationEngine`), не "ещё один формат экспорта". Отдельный спек — чтобы основной не раздувался. |
| **D34** | **`unifi-core` external dependency — DEFER**. Свой sync `BaseUnifiClient` (Phase 1) работает. Триггер для пересмотра: либо upgrade production сервера до Ubuntu 26.04 LTS (Python 3.13 default), либо конкретный pain с нашим клиентом. | Не менять core dependency без конкретной боли. Наш клиент покрывает все use cases Phase 1-3, retry/timeout/SSL свои. |
| **D35** | **i18n strategy — DEFER до Phase 6 cleanup**. Паттерн уже есть в проекте `fuckrkn` (двуязычность реализована), переиспользовать оттуда при необходимости. Design docs остаются на русском в `docs/superpowers/specs/` (disclaimer в English README на будущее). Перевод runtime strings — подзадача в Phase 6 если потребуется. | Преждевременный i18n засоряет код gettext-обёртками. Один оператор (русскоговорящий), один deployment — не нужно. |
| **D36** | **Generic UniFi через external MCP (`uvx unifi-network-mcp@latest`)**, НЕ в коде нашего пакета. Если понадобится firewall/DNS/backups/etc. — ставится отдельным процессом рядом с нашим Phase 4M MCP wrapper. Модель видит оба. | Никакого fork/import/coupling. sirkirby/unifi-mcp generic, наш specific для данного production deployment — два уровня абстракции работают параллельно. |

---

## Что не входит в этот спек (defer)

- **Phase 7 — port errors delta, maintenance mode, controller health check, uplink change logging** (см. D28). Реализуются по факту инцидентов как отдельные мини-проекты. Architecture-hooks (PermissionsSettings, audit baseline state-файл) могут быть подготовлены раньше, но features — только по реальной потребности.
- **Прямое управление EdgeSwitch через SSH** (`EdgeSwitchClient` через pexpect/paramiko/netmiko). Отдельный спек после стабилизации основного рефакторинга. Команда `diag edgeswitch` в этом спеке работает через REST API UniFi контроллера.
- **Security benchmarks** (audit security command, 16 проверок в стиле sirkirby/unifi-mcp). Полезный extension, добавим если решим открывать SOC-направление.
- ~~HTML report format в ExportService~~ — **superseded by D33**: report — отдельный модуль `ReportService`, спек `2026-05-18-unifi-manager-report-module-design.md`. Phase 4R parallel track.
- **`unifi-core` external dependency** (см. D34) — defer до конкретного pain или Ubuntu 26.04 upgrade.
- **i18n / runtime translation** (см. D35) — defer до Phase 6 cleanup; pattern reuse из `fuckrkn` если потребуется.
- **Generic UniFi tools в нашем коде** (см. D36) — defer навсегда; используется external `uvx unifi-network-mcp` процесс.
- Поддержка MikroTik / Cisco. Структура `clients/` позволяет добавить, но не делаем.
- Миграция cron → systemd timers (отдельная мини-фаза).
- Docker / Kubernetes / Helm.
- Web UI / REST API.
- Публикация в PyPI или внутренний devpi.
- Метрики в Prometheus / OpenTelemetry. Можно добавить позже, когда понадобится.

---

## Следующий шаг

После одобрения этого дизайн-документа — переход к `superpowers:writing-plans` для детального implementation plan, разбитого по фазам 0-6 из раздела 5.2.
