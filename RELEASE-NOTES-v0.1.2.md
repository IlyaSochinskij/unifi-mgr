## unifi-mgr v0.1.2 — Deployment-Contract Hardening

Патч-релиз: закрытие 7 находок боевого развёртывания v0.1.1 (271 устройство, обе API OK). Делает инструмент cron-ready для Phase 5 — после него `sudo -u unifi-mgr unifi-mgr --config /etc/unifi-mgr/config.yaml audit status` работает без `cd`, без воркэраундов, без root-магии и с чистым stdout.

### 🔴 Security

- **`export devices` больше не льёт секреты.** Раньше выгружал сырой payload UniFi с полями `x_adopt_password` / `x_authkey` / `x_vwirekey` / `x_aes_gcm` / `x_ssh_hostkey_fingerprint`. Теперь по умолчанию — allow-list безопасных колонок + deny-pattern вторым слоем (defense-in-depth); фильтрация покрывает и устройства неизвестного типа. Сырой дамп — только явный `--raw` с предупреждением в stderr.

### 🟠 Deploy-contract

- **`.env` находится вне CWD.** Цепочка поиска: `--env-file` → `UNIFI_ENV_FILE` → рядом с `config.yaml` → `/etc/unifi-mgr/.env`. Раньше искался только `./.env` — cron не находил креды.
- **Глобальный `--config` / `--env-file`** на верхнем уровне CLI: `unifi-mgr --config X audit status` теперь работает (раньше — `No such option: --config`). Per-subcommand `--config` сохранён как override.
- **`config validate --strict`** — проверяет, что креды реально подгрузились (а не только что YAML валиден).
- **Логи → stderr.** `export` / `--json` отдают чистый stdout (пайпы и редиректы парсятся).
- **Least-privilege runtime.** `config.yaml` и `.env` → `640 root:unifi-mgr`; cron и smoke-проверки от `unifi-mgr`. `verify-deployment.sh` гоняет проверки уже от сервис-юзера.
- **`deploy.sh`** стейджит wheel в release-dir перед install (фикс `Errno 13` когда wheel в домашке деплоящего).
- **LF в shell-скриптах** — `.gitattributes` (`eol=lf`) + CI-страж против CRLF. Bundle больше не приедет с виндовыми переводами строк.

### Качество

- TDD на все новые safety-ветки; full suite зелёный, coverage ≥90% (gate 90%); mypy --strict чистый; ruff clean.
- Исполнено subagent-driven: каждая задача с независимым ревью; security-фикс (#7) прошёл отдельный аудит с leak-probe.

### Развёртывание

См. `DEPLOY.md` в bundle (обновлён под least-privilege + global `--config`) и `docs/runbooks/phase-5-compressed-timeline.md`. Артефакты: `unifi-mgr-0.1.2-deploy.tar.gz` / `.zip`.

### Лицензия

MIT © 2026 Ilya Sochinskij
