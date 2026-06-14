# unifi-mgr

Production-grade Python toolkit для управления UniFi-сетью через Legacy и Integration API.

Заменяет 15+ legacy скриптов единым типизированным пакетом с CLI, тестами и CI.

## Возможности

- **Audit** — критические проблемы, inventory snapshot, deep (оба API), MAC duplicates / spoofing, исторические тренды
- **Auto-restart** проблемных AP с cooldown, priority sort, max-per-run, history persistence
- **Profile-based restart** — именованные YAML-профили (`restart profile <name>`)
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

Полный step-by-step (чистый сервер, least-privilege, scheduling): [`docs/INSTALL.md`](docs/INSTALL.md).

Кратко — сборка wheel + production setup:
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
unifi-mgr restart profile office            # DRY-RUN (default)
unifi-mgr restart profile office --apply    # REAL
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

Архитектура: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · Дорожная карта: [`docs/ROADMAP.md`](docs/ROADMAP.md)

## Безопасность

- Все секреты через `pydantic.SecretStr` — masked в `repr()`, не утекают в logs
- `SecretsFilter` в logging автоматически redact'ит зарегистрированные значения
- D30 permissions kill-switch: `permissions.cli.restart.execute: false` в config.yaml — emergency stop без правки cron
- Telegram rate-limit (per-hash 30s + total 5/min) защищает от шторма алертов

## Development

```bash
pytest --cov=unifi_manager --cov-fail-under=80
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

## Статус

Production-ready (v0.1.7): dual-API (Legacy + Integration), 354 теста, CI (lint + type + test + build).
Релизы и deploy-архивы — в [GitHub Releases](../../releases).

## Лицензия

[MIT](LICENSE) © 2026 Ilya Sochinskij
