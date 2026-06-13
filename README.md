# unifi-mgr

Production-grade Python toolkit для управления UniFi сетью (~270+ устройств, production network deployment, 192.0.2.1).

Заменяет 15+ legacy скриптов единым типизированным пакетом с CLI, тестами и CI.

## Возможности

- **Audit** — критические проблемы, inventory snapshot, deep (оба API), MAC duplicates / spoofing, исторические тренды
- **Auto-restart** проблемных AP с cooldown, priority sort, max-per-run, history persistence
- **Profile-based restart** — заменяет 3 legacy `restart_restaurant_*.py` одним YAML-профилем
- **Targeted device restart** (single MAC, `restart` или `poe-cycle`)
- **Telegram alerts** с dedup через `AlertHistory` + rate-limit (per-hash + per-minute)
- **Zabbix LLD integration** для external check
- **CSV/JSON export** клиентов и устройств
- **Config validation** + login test + legacy script wrapper

## Установка

### Development (из исходников)

```bash
git clone <repo> && cd unifi_manager
python -m venv .venv          # Python 3.12+
.venv/bin/pip install -e ".[dev]"
unifi-mgr --version            # → unifi-mgr 0.1.7
pytest                         # 354 tests
```

### Production (Linux server)

См. operator runbook: [`docs/runbooks/phase-5-cron-migration.md`](docs/runbooks/phase-5-cron-migration.md)

Сборка wheel + production setup:
```bash
python -m build --wheel        # → dist/unifi_mgr-*.whl
# На сервере:
sudo bash scripts/install-production.sh     # one-time
sudo bash scripts/deploy.sh dist/unifi_mgr-*.whl
bash scripts/verify-deployment.sh
```

## Конфигурация

Двухуровневая:

- **`config.yaml`** — публичные настройки (пороги, профили рестарта, пути, logging level)
- **`.env`** — секреты (UniFi пароль, Integration API key, Telegram bot token)

Шаблоны: [`config.yaml.example`](config.yaml.example), [`.env.example`](.env.example).

Места поиска `config.yaml`:
1. `--config PATH` (CLI флаг)
2. `./config.yaml`
3. `~/.config/unifi-mgr/config.yaml`
4. `/etc/unifi-mgr/config.yaml`

## Использование

### Audit
```bash
unifi-mgr audit critical                    # exit 1 если критические проблемы
unifi-mgr audit critical --telegram         # + send alert с dedup
unifi-mgr audit status                      # inventory: total/online/offline/by type
unifi-mgr audit full --api both             # deep audit, оба API параллельно
unifi-mgr audit light                       # MAC duplicates + spoofing
unifi-mgr audit trends --days 7             # исторические отчёты
```

### Restart (D9 dry-run defaults)
```bash
unifi-mgr restart auto                      # REAL execution (cron-friendly)
unifi-mgr restart auto --dry-run            # preview
unifi-mgr restart profile restaurant        # DRY-RUN (default)
unifi-mgr restart profile restaurant --apply  # REAL
unifi-mgr restart device --mac aa:bb:cc:dd:ee:ff --method poe-cycle --apply
```

### Export / Notify / Zabbix
```bash
unifi-mgr export clients --format csv --out clients.csv
unifi-mgr export devices --format json
unifi-mgr notify test
unifi-mgr notify send "manual alert" --level warn
unifi-mgr zabbix stats                      # LLD JSON для external check
```

### Utility
```bash
unifi-mgr config validate                   # check config.yaml + .env
unifi-mgr config show --secrets             # full config (--secrets требует TTY)
unifi-mgr login test --api both             # verify credentials к UniFi
unifi-mgr legacy run <script_name>          # wrapper для старых скриптов (deprecated)
```

## Архитектура

5-слойный пакет (`src/unifi_manager/`):

| Слой | Назначение |
|---|---|
| `clients/` | HTTP с retry/timeout (Legacy session+CSRF, Integration X-API-KEY) |
| `domain/` | Pydantic models (Device/AccessPoint/Switch + SYSID_MAP, ApEvent, WirelessClient, RestartHistory) |
| `services/` | Бизнес-логика (audit, restart, export, notify, lock) |
| `integrations/` | Outbound (Telegram с rate-limit, Zabbix LLD formatter) |
| `cli/` | Typer commands (audit/restart/export/notify/zabbix/config/login/legacy) |

Зависимости: `clients → domain ← services ← cli`. Тесты с моками HTTP (`responses`) и временем (`freezegun`).

Полный дизайн: [`docs/superpowers/specs/2026-05-16-unifi-manager-refactor-design.md`](docs/superpowers/specs/2026-05-16-unifi-manager-refactor-design.md)

## Безопасность

- Все секреты через `pydantic.SecretStr` — masked в `repr()`, не утекают в logs
- `SecretsFilter` в logging автоматически redact'ит зарегистрированные значения
- D30 permissions kill-switch: `permissions.cli.restart.execute: false` в config.yaml — emergency stop без правки cron
- Telegram rate-limit (per-hash 30s + total 5/min) защищает от шторма алертов

## Development

```bash
pytest --cov=unifi_manager --cov-fail-under=90
mypy --strict \
  src/unifi_manager/settings.py \
  src/unifi_manager/logging_config.py \
  src/unifi_manager/clients \
  src/unifi_manager/domain \
  src/unifi_manager/utils \
  src/unifi_manager/services \
  src/unifi_manager/integrations
ruff check . && ruff format --check .
pre-commit install && pre-commit run --all-files
```

CI (`.github/workflows/ci.yml`): lint + type + test + build.

## Статус рефакторинга

- [x] Phase 0 — Foundation (pyproject, scaffold, CI)
- [x] Phase 1 — Core layers (clients, domain с SYSID_MAP, utils/time)
- [x] Phase 2 — Services + integrations (audit, export, lock, notify, telegram, zabbix)
- [x] Phase 3 — RestartService (auto + profile + device, D30 permissions)
- [x] Phase 4 — CLI complete (все Typer commands wired)
- [x] Phase 5 prep — deployment scripts + operator runbook
- [ ] Phase 5 production — cron switch на сервере (см. runbook)
- [ ] Phase 6 — Cleanup `_legacy/`, sync infra-зеркала
- [ ] Phase 7 — Post-migration features (maintenance mode, controller health check) — deferred per D28

## Tags

```bash
git tag -l 'phase-*'
# phase-0-complete  phase-1-complete  phase-2-complete  phase-3-complete  phase-4-complete
```

## Лицензия

[MIT](LICENSE) © 2026 Ilya Sochinskij
