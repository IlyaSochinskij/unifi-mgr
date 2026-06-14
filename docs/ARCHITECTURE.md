# Архитектура unifi-mgr

Текущее состояние (v0.1.7). Описывает реальную структуру кода, не план миграции.

## Слои

`src/unifi_manager/` — src-layout пакет, строго однонаправленные зависимости:

```
cli  →  services  →  domain
                 ↘   clients (через Protocol)
                 ↘   integrations
        utils ← (все)
```

| Слой | Назначение |
|---|---|
| `clients/` | HTTP-фундамент: `BaseUnifiClient` (session, retry на 5xx, timeout, TLS) + `LegacyClient` (session + CSRF) + `IntegrationClient` (X-API-KEY) + `exceptions` |
| `domain/` | Pydantic-модели: `Device`/`AccessPoint`/`Switch` (+ `SYSID_MAP`), `WirelessClient`, `ApEvent`, `RestartHistory` |
| `services/` | Бизнес-логика: `AuditService`, `RestartService` (+ pure `restart_decisions`), `ExportService`, `notify` (`AlertHistory`), `lock` (`FileLock`) |
| `integrations/` | Outbound: `TelegramNotifier` (rate-limit), `zabbix` (LLD formatter) |
| `cli/` | Typer-команды (audit/restart/export/notify/zabbix/config/login/legacy) + `_common` (builders, settings, logging) |
| `utils/` | `time`, `redact` (рекурсивный санитайзер секретов) |

## Ключевые швы (seams)

- **Protocol-инъекция клиентов в сервисы.** Сервисы не импортируют `clients/` напрямую — принимают структурный `Protocol` (`_DeviceClient`, `_RestartClient`). Это тест-шов (mock через `responses`) и развязка слоёв.
- **Pure decision-модуль.** `services/restart_decisions.py` — чистые функции (priority, classify_action) без I/O; тестируются изолированно.
- **`Notifier`-протокол** (Track 3, под-проект 1) — seam для каналов уведомлений; `TelegramNotifier` соответствует, будущий `MatrixNotifier` реализует тот же интерфейс. См. [specs/2026-06-14-notifyservice-design.md](specs/2026-06-14-notifyservice-design.md).

## Dual-API (обязательное требование)

Поддерживаются **оба** API UniFi одновременно — это hard-требование, не дублирование:

- **Legacy API** (`/proxy/network/api/s/<site>/...`): session-cookie + `X-Csrf-Token`. Основной источник инвентаря/событий/команд.
- **Integration API** (`/proxy/network/integration/...`): `X-API-KEY` + `site_id_uuid`. Используется в `audit full --api both|integration` и `login test`.

Общий транспорт — в `BaseUnifiClient`; различаются только auth и пути (тонкие подклассы).

## State и персистентность

- **`RestartHistory`** (`domain/`) — cooldown-история рестартов. Atomic save (`os.replace`), **fail-closed** при повреждении (рестарты блокируются — безопасно). Перечитывается под `FileLock` (защита от lost-update между cron-ранами).
- **`AlertHistory`** (`services/notify`) — dedup алертов. **fail-open** при повреждении (алерты считаются новыми — «молчание хуже шума»), сверху ограничено throttle-лимитом.
- **`FileLock`** (`services/lock`, fasteners) — non-blocking; cron `*/30` не запускает параллельные restart-инстансы.

## Конфигурация

- `pydantic-settings`: `config.yaml` (публичное) + `.env` (секреты). Источники: `--config` → `./config.yaml` → `~/.config` → `/etc/unifi-mgr`. Деплой-специфика (host/site/профили) живёт в приватном конфиге, не в репозитории.
- Аварийный kill-switch: `permissions.cli.restart.execute` / `notify.telegram_send`.

## Безопасность

- Все секреты — `pydantic.SecretStr`; `SecretsFilter` redact'ит зарегистрированные значения в логах.
- `utils/redact.redact_secrets` — рекурсивная вырезка секретных ключей (`x_authkey`, …) на путях, отдающих сырые dict наружу (`audit full --json` redacted by default, `export devices`).
- Least-privilege деплой: код root-owned (`/opt`), runtime от сервис-юзера.

## Заложенные, но отложенные хуки (Phase 7, DEFERRED)

Архитектура готова, реализация — по факту необходимости (см. [ROADMAP.md](ROADMAP.md)):

- `permissions` namespace (kill-switches) — уже активен.
- `audit_health_check`, `maintenance` (mute) секции в settings — инертны в текущих фазах, имеют дефолты.
- `SwitchPort` метрики ошибок (port-errors delta) — модель готова, триггеры отложены.

## Тестирование

`pytest` + `responses` (HTTP-моки) + `freezegun` (время) + `hypothesis` (property). 354 теста, CI: ruff + mypy --strict (core) + pytest + build.
