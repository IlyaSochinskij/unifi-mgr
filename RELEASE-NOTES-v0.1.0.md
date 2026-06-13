## unifi-mgr v0.1.0

Полный рефакторинг legacy UniFi-скриптов в production-grade Python пакет.
Заменяет 15+ разрозненных скриптов единым типизированным CLI с тестами и CI.

### Что нового

- **Единый CLI** `unifi-mgr` (Typer) — `audit` / `restart` / `export` / `diag` / `notify` / `zabbix` / `config` / `login` / `legacy`
- **5-слойная архитектура:** `clients` / `domain` / `services` / `integrations` / `cli`
- **Два UniFi API:** Legacy (session + CSRF) и Integration (X-API-KEY)
- **audit:** critical (exit-code-friendly) / status / full (оба API) / light (MAC dup + spoofing) / trends
- **restart:** auto (cooldown + priority + max-per-run + history) / profile (заменяет 3 legacy restart_restaurant_*.py YAML-профилем) / device (точечный)
- **export:** CSV / JSON для клиентов и устройств (с `real_model` через SYSID_MAP)
- **integrations:** Telegram (dedup + rate-limit) + Zabbix LLD
- **pydantic-settings** конфиг (config.yaml + .env), `SecretStr` для секретов, `SecretsFilter` в логах
- **D30 permissions kill-switch:** `permissions.cli.restart.execute: false` — emergency stop без правки cron
- **FileLock** (fasteners) — cron-safety против параллельных запусков

### Bug fixes (из аудита legacy кода)

- **Timezone bug** (UTC vs naive `datetime.now()`) → `utils/time` с tz-aware helpers + Hypothesis property-тесты
- **TOCTOU race** в bash lock-файле → атомарный `FileLock`
- **ZeroDivisionError** в PoE-расчёте, bare `except:`, `login()` без проверки статуса

### Качество

- **267 unit-тестов**, 90%+ coverage
- **mypy --strict** для 24 core модулей
- ruff + pre-commit + GitHub Actions CI

### Развёртывание

См. `DEPLOY.md` в bundle + `docs/runbooks/phase-5-compressed-timeline.md`.

**Артефакты:**
- `unifi-mgr-0.1.0-deploy.tar.gz` — deployment bundle (Linux server)
- `unifi-mgr-0.1.0-deploy.zip` — deployment bundle (Windows/zip)
- Pre-built wheel внутри bundle

### Статус

Phase 0-4 complete + Phase 5 prep. Production cron switch (Phase 5) и cleanup (Phase 6) — в процессе по operator runbook.

### Известные ограничения

- **Telegram отключён по умолчанию** (заблокирован в РФ) — код рабочий, включается в config если доступен `api.telegram.org`
- **Matrix-канал** (self-hosted) — в планах
- **Phase 7 features** (maintenance mode, controller health check) — отложены

### Лицензия

MIT © 2026 Ilya Sochinskij
