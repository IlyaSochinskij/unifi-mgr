## unifi-mgr v0.1.5 — CLI Contract Hardening

Патч поверх 0.1.4. Закрывает находки аудита CLI-контрактов и надёжности доставки алертов. Также несёт всю deploy-гигиену 0.1.4 (нормализованные права бандла, root-owned `/opt`, verify от runtime-юзера, strict + `site_id_uuid`, `/etc/cron.d` runbook'и) — она не выпускалась отдельным тегом.

### CLI-контракты

- **`restart device --method` — StrEnum (P1).** Раньше `str`: любое значение кроме `poe-cycle` молча превращалось в `restart`, поэтому опечатка с `--apply` выполняла **реальный рестарт** вместо отказа. Теперь typer отвергает неизвестные значения (exit 2) до запуска команды.
- **`--api` — StrEnum для `login test` и `audit full` (P2).** Раньше `login test --api typo` не попадал ни в одну ветку и выходил `0` без единой проверки; `audit full --api typo` молча игнорировался. Общий `ApiChoice {legacy, integration, both}` — typer отвергает прочее.
- **`audit full --api integration` работает integration-only (P2).** Раньше `full()` безусловно дёргал Legacy inventory, поэтому на integration-only стенде команда падала на legacy-логине. Теперь `full()` использует те API, чьи клиенты переданы (legacy-only / integration-only / merge), а CLI строит только нужные клиенты.

### Надёжность алертов

- **Telegram MarkdownV2 escaping (P2).** `parse_mode` по умолчанию `MarkdownV2`, но `send_message` слал сырой текст, не вызывая существующий `escape_markdown_v2`. Обычное имя устройства с `_ ( ) - .` (напр. `Restoran (WIFI) ap_offline`) давало Telegram 400, и алерт **терялся навсегда** (retry падал так же). Теперь текст экранируется при `MarkdownV2`.

### Точность preview

- **`restart profile` dry-run соблюдает `max_restarts` (P3).** Dry-run добавлял действия без cap'а, который есть в apply-path, поэтому preview мог показать больше действий, чем выполнит `--apply`. Cap теперь применяется и в dry-run.

### Развёртывание

Артефакты: `unifi-mgr-0.1.5-deploy.tar.gz` / `.zip`. Включает всю обвязку 0.1.4 (deploy hygiene) + перечисленные CLI-контрактные фиксы. 336 тестов, coverage ≥90%, ruff + mypy чисто, бандл LF-clean с perms/CRLF/notes build-gate.

### Лицензия

MIT © 2026 Ilya Sochinskij
