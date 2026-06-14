# Decision Log (D1–D36)

Решения рефакторинга unifi-mgr с обоснованиями и триггерами пересмотра.

**Это канонический источник определений D-номеров — на них ссылается код** (напр. `D30` kill-switches ×10 в `restart.py`/`settings.py`/`cli/restart.py`, `D32` SYSID_MAP, `D9` dry-run default). Извлечено из refactor-design спека при консолидации доков (2026-06-14); сам спек как pre-implementation миграционный артефакт удалён, decision log сохранён.

Inline-маркеры: `~~Dn~~ superseded by Dm` — заменено; `DEFER` — отложено с явным триггером.

| # | Решение | Обоснование |
|---|---|---|
| D1 | Полный пакет с тестами и CI (а не точечные правки) | Текущий долг такой, что точечные правки не решают |
| D2 | `BaseClient + LegacyClient + IntegrationClient` (а не единый client с `mode`) | Чистое разделение, легче тестируется, API дают разные endpoints |
| D3 | `pydantic-settings` + `.env` + `config.yaml` | Типизация всего конфига, единая схема, fail-fast при опечатках |
| D4 | Typer для CLI (а не Click/argparse) | Type-hints вместо boilerplate, хорошо сочетается с pydantic |
| D5 | Все три legacy `restart_*.py` → удаляются, заменяются профилем в YAML | Дублирование кода устраняется, новые «профили» — без кода |
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
| D25 | Maintenance mode с max TTL 24 часа | Защита от «забыл снять mute» — авто-разблокировка устройств после суток |
| D26 | EdgeSwitch SSH client — НЕ в этот спек, отдельный follow-up | Принципиально другой протокол (SSH/pexpect, не HTTP/JSON); другая иерархия клиентов; новые зависимости и тестовая инфраструктура |
| D27 | Команда `diag edgeswitch` остаётся в дизайне как REST-через-UniFi-контроллер (не прямой SSH) | Покрывает 80% use cases без введения нового семейства клиентов |
| **D28** | **Phase 7 (post-migration features) полностью отложена** — port errors delta, maintenance mode, controller health check, uplink change logging реализуются по факту инцидентов как отдельные мини-проекты, не упреждающе | External review (2026-05-18) указал что Phase 7 нарушает D23 («не смешивать миграцию и новые фичи»); 4 независимые фичи без подтверждённых use cases — overkill для proactive build |
| **D29** | **`_legacy/` 2 недели после Phase 6** (вместо 4 недель до фикс-даты) | 4 недели = паранойя; 1 неделя = risky если cron switch затянется; 2 недели — middle ground с буфером после observation period |
| **D30** | **`PermissionsSettings` config-уровневые kill-switches** для restart/notify. **Refinement (2026-05-18):** namespace `permissions.cli.*` (CLI/cron entry-points, default permissive=True) vs `permissions.mcp.*` (Phase 4M, default restrictive=False). Backward-compat: отсутствующий `permissions` блок = все cli.* True. | Pattern из sirkirby/unifi-mcp; emergency response без правки crontab. Namespace future-proof для Phase 4M (у LLM нет --apply barrier, поэтому MCP opt-in). |
| **D31** | **Phase 4M (parallel, опциональная)** — FastMCP wrapper поверх `services/`. Не блокирует Phase 5, доступен Claude + локальным моделям как дополнительный интерфейс | `services/` уже без HTTP-зависимостей — идеальный backend для FastMCP. ~200-300 строк. Не конкурирует с sirkirby/unifi-mcp (тот generic, наш specific для конкретного deployment) |
| **D32** | **Extended SYSID_MAP** — seed dict из tnware/unifi-controller-api как **base**, наши 4 entries — **overlay поверх** (перезаписывают при конфликте). **Refinement (2026-05-18):** при попытке lookup отсутствующего sysid — log `sysid_gap` warning + Phase 4R recommendation для пополнения карты по реальности network. | Их словарь покрывает шире, наши 4 — точечные fixes. Зависимости не добавляем, копируем только const. `sysid_gap` warning делает карту самообогащающейся через ops feedback. |
| **D33** | **Report module отдельным спеком** — [`specs/2026-05-18-report-module-design.md`](specs/2026-05-18-report-module-design.md). Phase 4R parallel track. Не блокирует основной рефакторинг. Идеи from FryguyPA (self-contained Jinja2 + inline SVG + 4 темы + recommendations engine + JSON snapshots), кода не берём. | HTML report оказался отдельным аналитическим слоем (`ReportService` + `RecommendationEngine`), не «ещё один формат экспорта». Отдельный спек — чтобы основной не раздувался. |
| **D34** | **`unifi-core` external dependency — DEFER**. Свой sync `BaseUnifiClient` (Phase 1) работает. **Триггер пересмотра:** либо upgrade production сервера до Ubuntu 26.04 LTS (Python 3.13 default), либо конкретный pain с нашим клиентом. | Не менять core dependency без конкретной боли. Наш клиент покрывает все use cases Phase 1-3, retry/timeout/SSL свои. |
| **D35** | **i18n strategy — DEFER до Phase 6 cleanup**. Паттерн двуязычности есть в другом проекте автора, переиспользовать при необходимости. Design docs на русском; English README disclaimer на будущее. Перевод runtime strings — подзадача в Phase 6 если потребуется. | Преждевременный i18n засоряет код gettext-обёртками. Один оператор (русскоговорящий), один deployment — не нужно. |
| **D36** | **Generic UniFi через external MCP (`uvx unifi-network-mcp@latest`)**, НЕ в коде нашего пакета. Если понадобится firewall/DNS/backups/etc. — ставится отдельным процессом рядом с нашим Phase 4M MCP wrapper. Модель видит оба. | Никакого fork/import/coupling. sirkirby/unifi-mcp generic, наш specific для данного deployment — два уровня абстракции работают параллельно. |

---

## Отложенные с триггером (быстрый индекс)

- **D28** — Phase 7 features: по факту инцидентов (см. [ROADMAP.md](ROADMAP.md)).
- **D34** — `unifi-core` dependency: пересмотр при Ubuntu 26.04/Py3.13 или конкретном pain.
- **D35** — i18n: при появлении не-русскоязычного оператора/деплоя.
- **D31/D36** — MCP (свой 4M wrapper + external generic): по потребности.
