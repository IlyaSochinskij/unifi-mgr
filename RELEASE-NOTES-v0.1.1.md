## unifi-mgr v0.1.1 — Security Hardening

Патч-релиз: закрытие blast-radius уязвимостей, найденных независимым код-ревью перед production-развёртыванием. **Это версия для прода** — `v0.1.0` содержит перечисленные ниже дыры, разворачивать её не следует.

### 🔴 Critical fixes (blast-radius)

- **FileLock подключён в рантайм.** `FileLock` был написан и протестирован (Phase 2), но НЕ вызывался в restart-flow — cron `*/30 restart auto` мог запустить параллельные инстансы и удвоить batch рестартов. Теперь `auto`/`profile`/`device` исполняются под `FileLock` (timeout=0 → skip если занято, статус `skipped_locked`). Dry-run не требует lock.
- **Cap ограничен и неообходим.** `max_restarts_per_run` теперь `Field(ge=1, le=20)` + `validate_assignment=True`; CLI `--max` с диапазоном `1-20`. Раньше `--max -1` давал срез `[:-1]` = рестарт всех точек кроме одной.
- **История рестартов атомарна + fail-closed.** `save()` пишет через temp-файл + `os.replace` (атомарно); битый state-файл теперь **блокирует** все рестарты (`can_restart` → False) вместо сброса cooldown и массового рестарта; инкрементальный save после каждого действия (crash-safety). При corrupt — файл не перезаписывается (сохраняется для разбора).

### 🟡 Hardening

- **`verify_ssl` по умолчанию `True`** (secure by default). UniFi self-signed → явный `verify_ssl: false` в config. *(Бонус: починен pre-existing баг — `str(True)` отдавал строку-путь `'True'` как CA-bundle, что ломало verify=True.)*
- **`legacy run` — защита от path traversal.** `script_name` санитизируется (`Path(name).name` + containment-check) — `../` и абсолютные пути отвергаются.

### Качество

- +30 тестов на новые safety-ветки, coverage **93%** (gate 90%)
- mypy --strict зелёный (24 core модуля), ruff clean
- Бонусом найдены и починены 2 pre-existing бага (lock.py freezegun + base.py str-coercion)

### Развёртывание

См. `DEPLOY.md` в bundle + `docs/runbooks/phase-5-compressed-timeline.md`. Артефакты: `unifi-mgr-0.1.1-deploy.tar.gz` / `.zip`.

### Лицензия

MIT © 2026 Ilya Sochinskij
