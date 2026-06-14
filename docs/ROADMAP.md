# Roadmap

Что сделано, что в работе, что отложено. Заменяет старые phase-планы (отработанный
process-выхлоп удалён; здесь — только живая дорожная карта).

## Сделано (v0.1.7)

- **Phase 0-4** — рефакторинг 15+ legacy-скриптов в типизированный пакет (clients/domain/services/integrations/cli), dual-API, Typer CLI, тесты, CI. Завершено.
- **0.1.7 safety** — закрыты блокеры аудита 2026-06-11: `audit full --json` redacted by default, per-item guard в audit, перечитка restart-history под локом, нет ретраев command-POST, Telegram budget-after-success + token-не-в-логах, deps caps + constraints.
- **Product/deployment split** — деплой-специфика (config, cron, runbooks) вынесена в приватный репо; публичный продукт generic. Публичные доки переработаны под реальность.

## В работе — Track 3 (архитектурный рефактор)

Под-проекты, каждый своим циклом (spec → plan → impl):

1. **NotifyService + Notifier-протокол** — оркестрация уведомлений из CLI в сервис, единая точка kill-switch (SEC4), seam под Matrix. Spec approved: [specs/2026-06-14-notifyservice-design.md](specs/2026-06-14-notifyservice-design.md). ← следующий.
2. **Domain-нормализация** — канонич. модель устройства, в которую маппятся оба API; секреты не входят by construction (структурно закрывает корень утечки, которую 0.1.7 закрыл band-aid'ом). Разблокирует Integration-expansion.
3. **Config-seam** — заменить мутацию `os.environ` явной передачей пути конфига; предусловие для MCP-режима (Phase 4M).
4. **Quick-wins** — exit-коды для cron-мониторинга, state-классификатор (4/5/6/10 ≠ один «critical offline»), валидатор пустого include-фильтра профиля.

## Остаток Phase 6 (cleanup)

Workstation-часть сделана (legacy в коде нет, ruff-exclude вычищен в product/deployment split). Осталось:

- **Server-side legacy removal** (оператор) — удалить старые `*.py`/`*.sh` с прод-сервера после полной cron-миграции; архив на месяц.
- **Infra-mirror sync** — `D:\project\infra\external_repos\unifi_manager` рассинхронизирован; обновить (rsync/robocopy, исключая артефакты).
- **Infra docs** — переписать `infra/docs/network/unifi-framework.md` под новую архитектуру.
- **Legacy CLI-wrapper** — `unifi-mgr legacy run` + связанный shim удалить (срок removal истёк).

## Отложено — Phase 7 (features, архитектура готова)

Делается по факту инцидентов как отдельные мини-проекты (D28). Хуки уже в schema (см. [ARCHITECTURE.md](ARCHITECTURE.md)):

- **Controller health check** — pre-check контроллера (DNS + HTTP) перед `audit critical`; один алерт «controller unreachable» вместо N «device offline» (exit 2). Настраиваемые DNS/эндпоинты (D24).
- **Maintenance mode (mute)** — `device/site mute --duration` на время работ; max TTL 24ч (D25). State в `/var/lib/unifi-mgr/mute_state.json`.
- **Audit baseline** — снапшот port-errors + топологии для дельта-сравнений (port-errors delta, topology/uplink drift).

## Параллельные треки

- **Phase 4R — Report module** — HTML-отчёты. Детальный design: [specs/2026-05-18-report-module-design.md](specs/2026-05-18-report-module-design.md). Ждёт `NotifyService.get_alert_stats()` (появится после под-проекта 1).
- **Phase 4M — MCP wrapper** — экспонировать сервисы через FastMCP. Предусловие: config-seam (под-проект 3) — текущая мутация `os.environ` не thread-safe для long-running режима.
- **Matrix integration** — `integrations/matrix.py` (Telegram заблокирован в РФ). Подключается в `Notifier`-протокол после под-проекта 1; альтернатива/дополнение Telegram.
