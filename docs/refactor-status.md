# UniFi Manager — Refactor Status

**Текущее состояние:** в процессе миграции (Фаза 0).
**Целевая дата завершения:** ~2026-06-13.
**Спек:** [refactor design](superpowers/specs/2026-05-16-unifi-manager-refactor-design.md)
**Текущий план фазы:** [phase-0-foundation](superpowers/plans/2026-05-16-phase-0-foundation.md)

## Где что находится

| Что | Где | Статус |
|---|---|---|
| Старые скрипты (продакшен) | корень репы (`audit_unifi.py`, etc.) | работают через cron, не трогаем до фазы 5 |
| Новый код (в разработке) | `src/unifi_manager/` | растёт по фазам |
| Старый конфиг | `config.json` | для legacy-скриптов |
| Новый конфиг | `config.yaml` + `.env` | для нового пакета |
| Документация рефакторинга | `docs/superpowers/` | дизайн + планы |

## Прогресс по фазам

- [x] Фаза 0: Foundation (этот план)
- [x] Фаза 1: Core layers (clients, domain, utils)
- [ ] Фаза 2: Services + integrations
- [ ] Фаза 3: Restart logic
- [ ] Фаза 4: CLI complete
- [ ] Фаза 5: Cron switch (production)
- [ ] Фаза 6: Cleanup (удаление _legacy/)
- [ ] Фаза 7: Post-migration features

## Как запустить новый код локально

```bash
# В разработке используется worktree-derived имя ветки.
# Перед merge в master ветка будет переименована в refactor/v2.
git checkout worktree-refactor+v2  # или refactor/v2 после переименования
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
unifi-mgr --version
pytest
```
