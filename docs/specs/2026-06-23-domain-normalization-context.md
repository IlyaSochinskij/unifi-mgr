# Domain Normalization — контекст для следующей сессии

**Track 3, под-проект 2/4.** Keystone-рефактор. Это **контекст/бриф**, не финальный спек: следующая сессия запускает `superpowers:brainstorming` → spec → plan → impl поверх этого.

**Статус:** не начат. Самый большой и рисковый под-проект Track 3 (рябь по clients + domain + services + тестам).

---

## Зачем (что закрывает)

- **A4** — domain-модели сейчас только Legacy-shape; Integration-данные обходят domain целиком.
- **S1 (корень)** — `audit full --json` сливал секреты устройств; 0.1.7 закрыл **band-aid'ом** (`utils/redact.redact_secrets`). Нормализация делает это **структурно**: канонич. модель объявляет только безопасные поля → `x_authkey` физически не входит → redact становится defense-in-depth, а не единственным барьером.
- **CC1** (смежно) — Integration API пагинацию игнорит (тихое усечение). Нормализатор — естественное место добить, ЛИБО оставить отдельным под-проектом (решить в brainstorm).
- **SC6** (частично) — MAC-нормализация уже пропатчена в `_merge_devices` (mac.lower() ключ); каноничная модель сделает это by construction.

## Корень проблемы

Нет **нормализующего шва** между сырым API-dict и domain-моделью. Legacy-dict → модель работает (модели Legacy-shaped). Integration-dict **не проходит** `model_validate` (`macAddress` vs `mac`, `state:"ONLINE"` vs `state:int`). Поэтому `audit full` мёржит **сырые dict'ы**, секреты текут (band-aid), Integration-данные никогда не типизируются.

## Текущее состояние кода (file:line)

- **`domain/device.py`** — `Device` (base): `mac`, `name`, `reported_model = Field(alias="model")`, `sysid: int|None`, `state: int = 0` (1=online, 0/10=offline — **Legacy int-коды**), `type`, `last_seen`, `device_id`. `model_config = extra="allow", populate_by_name=True`. `AccessPoint(Device)`: `uplink: UplinkInfo|None`, `radio_table`, `real_model` computed_field (SYSID_MAP). `Switch(Device)`: `general_temperature`, `port_table`. **Всё привязано к Legacy именам/типам.**
- **`clients/legacy.py:76 list_devices_raw`** → `/stat/device` → Legacy raw dicts (`mac`, int `state`, `x_authkey`/`x_aes_gcm`/… секреты top-level).
- **`clients/integration.py:45 list_devices_raw`** → `/integration/v1/sites/<uuid>/devices` → Integration dicts (`macAddress`, `state:"ONLINE"`, `ipAddress`, …). `_extract_data` (line 56) знает про envelope `{data,offset,limit,count,totalCount}`, но **пагинацию не реализует** (CC1).
- **`services/audit.py:_merge_devices`** (после SC6-патча) — ключ дедупа `mac.lower()`, руками `macAddress or mac`, мёрж key-by-key. `FullAuditReport.devices = list[dict[str, Any]]` — **обходит domain**.
- **`cli/audit.py:audit_full`** — `redact_secrets` band-aid (0.1.7) на сырых dict'ах перед `--json`. **Это и есть band-aid, который структурный фикс заменяет.**

**Консьюмеры device-моделей/dict'ов** (всё парсит сейчас LEGACY-dict через Legacy-shaped модели): `AuditService` (critical/status/light/full), `ExportService.export_devices` (через `AccessPoint/Switch.model_validate`), `RestartService` (`AccessPoint.model_validate`), `integrations/zabbix` (Device-модели). Только `audit full --api both|integration` и `login test` сейчас трогают Integration-клиент.

## Варианты дизайна (для brainstorm — 2-3 проработать)

1. **Adapter/normalizer per client** — клиент отдаёт dict'ы, уже отображённые в каноничные имена (Legacy почти каноничен; Integration нормализуется в клиенте). Сервисы/модели единообразны. *Минус:* размазывает знание о shape по клиентам.
2. **`from_legacy()` / `from_integration()` конструкторы** на domain-моделях — явный per-source парсинг в каноничную модель. *Плюс:* знание о shape в одном месте (domain). *Минус:* два пути парсинга.
3. **`validation_alias` / `AliasChoices`** на полях модели — модель принимает и `mac`, и `macAddress`, и int, и string state (через validator). *Плюс:* одна модель. *Минус:* state-нормализация (int↔string) через валидатор, может запутать.
4. **Отдельный слой `domain/normalize.py`** — чистые функции `(raw_dict, source) → canonical model`. *Плюс:* тестируется изолированно, не раздувает модели/клиенты.

**Ключевые вопросы дизайна:**
- Где происходит **исключение секретов**? Каноничная модель должна объявлять ТОЛЬКО безопасные поля (тогда `x_authkey` не войдёт). Но `Device` сейчас `extra="allow"` (D7 — экономия памяти) — для каноничной модели, возможно, нужен `extra="ignore"` или explicit-only.
- **State-коды:** Legacy int (1/0/10) vs Integration `"ONLINE"`. Нормализовать в единый enum/int. Взаимодействует с A1 (state-классификатор из quick-wins).
- **CC1 пагинация** — добивать здесь (loop offset/totalCount) или отдельно?
- Сохранить `real_model`/SYSID_MAP-обогащение (D6/D32) и `uplink` для restart poe_cycle.

## Жёсткие ограничения

- **Dual-API — hard requirement (D2).** НЕ схлопывать клиенты. Каноничная модель — слой ПОВЕРХ двух клиентов, не вместо.
- **Не сломать** audit/export/restart/zabbix/CLI — все потребляют device-модели/dict'ы сегодня. Нужны регрессии на каждом потребителе.
- **Секреты by construction** — каноничная модель без секретных полей; `audit full --json` отдаёт каноничные объекты (redact остаётся defense-in-depth).
- Связанные решения: **D2** (BaseClient+Legacy+Integration), **D6/D32** (SYSID_MAP base+overlay, sysid_gap warning), **D7** (raw_data extra=allow — пересмотреть для каноничной модели). См. [`../DECISIONS.md`](../DECISIONS.md).

## Blast radius (почему «большой/рисковый»)

clients (оба) + domain (модели + новый нормализатор) + services (`audit._merge_devices`, export, возможно restart/zabbix) + тесты + удаление/ослабление redact band-aid в `audit full`. Это причина, почему его держали «под отдельную сессию».

## Тест-стратегия (заготовки уже есть)

- `tests/fixtures/integration_devices.json` — Integration shape (`macAddress`, string state, `totalCount`).
- `tests/fixtures/stat_device_response.json` — Legacy shape.
- Тест нормализатора: оба shape → одна каноничная модель (round-trip), секретные поля НЕ попадают, state унифицирован, `real_model` сохранён.
- Регрессии на каждом потребителе (audit full both/integration, export, restart, zabbix).

## Точка входа для следующей сессии

1. `superpowers:brainstorming` — проработать варианты 1-4 выше, выбрать (рекомендация будет зависеть от того, добиваем ли CC1 здесь).
2. Spec → `docs/specs/<date>-domain-normalization-design.md` (как notifyservice-design).
3. Plan → gitignored рабочий док (`*-implementation-plan.md` в .gitignore).
4. Impl → TDD, по коммиту на таску, ветка `github-main` + cherry-pick `phase-4.6.2-deploy-hygiene`, CI green per task. Workflow тот же, что у NotifyService.

## Долги из под-проекта 1 (NotifyService) — отдельно, в бэклог

- **#3 RMW-гонка** двух cron `audit critical` по `alert_history.json` (явный нон-гол; throttle-капнут) → возможный FileLock-для-notify.
- **#4** `skipped_disabled → exit 1` — UX-решение спека, пересмотреть при желании.
- **#5** мемоизация провала `_get_notifier` залипает в long-running MCP-режиме (4M) — инвалидация когда дойдём до Phase 4M.
- **#6/#7** atomic blast-radius (restart/throttle persistence) + cache_dir-греп — дёшево, покрыто тестами, низкий приоритет.
