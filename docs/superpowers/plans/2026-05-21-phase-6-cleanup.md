# Phase 6 — Cleanup Implementation Plan

> **For agentic workers:** Mixed plan — REPO tasks (T3, T4, T6) subagent-able; PRODUCTION tasks (T1, T2) — operator manual на сервере. Steps used checkbox (`- [ ]`) syntax.

**Goal:** Финальная зачистка после успешного Phase 5 cron switch — удаление legacy с production, sync infra-зеркала, обновление infra-документации, финальные теги.

**Architecture:** Workstation master уже очищен от legacy (сделано при merge). Phase 6 завершает: production-side legacy removal, infra repo sync, docs.

**Tech Stack:** git, rsync, Linux ops.

**Гейт:** `_legacy` нигде нет, infra-зеркало синхронизировано, infra docs актуальны, теги phase-5/6-complete стоят.

**Предусловие:** Phase 5 завершён — все 5 cron на новом CLI, 2-day observation passed (compressed timeline).

**Связанный спек:** [refactor-design.md](../specs/2026-05-16-unifi-manager-refactor-design.md) раздел 5.6.

**Deadline:** часть недельного дедлайна (2026-05-21+). Phase 6 ~2-3 часа работы.

---

## Task 1: Phase 5 completion tag (operator confirms → subagent tags)

**Когда:** после 2-day observation passed.

- [ ] **Step 1.1** (operator): подтвердить observation clean — `bash scripts/observe.sh` 2 дня подряд без issues.

- [ ] **Step 1.2** (workstation): tag phase-5-complete

```bash
cd D:/project/unifi_manager
git tag -a phase-5-complete -m "Phase 5 (Cron switch) complete: все 5 cron на новом CLI, compressed observation passed (Telegram excluded — РФ block)"
git push origin phase-5-complete
```

---

## Task 2: Production legacy removal (operator manual на сервере)

**Когда:** после phase-5-complete. Cron уже на новом CLI, legacy скрипты больше не вызываются.

- [ ] **Step 2.1: Финальная проверка что cron НЕ ссылается на legacy**

```bash
sudo crontab -l | grep -v '^#' | grep -i 'unifi_manager/.*\.py\|unifi_manager/.*\.sh'
```
Expected: пусто (никаких ссылок на /home/operator/unifi_manager/*.py или *.sh legacy). Только `/opt/unifi-mgr/bin/unifi-mgr ...`.

Если что-то ссылается — STOP, доделать Phase 5.

- [ ] **Step 2.2: Архивировать legacy (на всякий случай) и удалить**

```bash
# Архив на случай если что-то понадобится (хранить месяц)
cd /home/operator
tar czf ~/unifi_manager_legacy_backup_$(date +%Y%m%d).tar.gz unifi_manager/

# Удалить legacy скрипты (но НЕ logs которые могут быть полезны)
cd /home/operator/unifi_manager
rm -f audit_unifi.py auto_restart_cron.sh auto_restart_problem_aps.py \
      check_critical.py check_unifi.py dashboard.sh export_all_clients.py \
      full_audit_unifi.py restart_restaurant_aps.py restart_restaurant_aps_v2.py \
      restart_restaurant_v2.py run_audit.sh telegram_notify.py unifi_client.py \
      unifi_trends.py zabbix_unifi_stats.py config.json
```

- [ ] **Step 2.3: Удалить crontab backup files (Phase 5 artifacts)**

```bash
rm -f ~/crontab-before-stage*.txt
# Оставить ~/crontab-pre-phase5-backup.txt ещё на пару недель на всякий случай
```

- [ ] **Step 2.4: Verify production по-прежнему работает**

```bash
/opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml audit status
bash /opt/unifi-mgr/current/scripts/verify-deployment.sh 2>/dev/null || \
  /opt/unifi-mgr/bin/unifi-mgr --version
```
Expected: работает без legacy.

---

## Task 3: Infra mirror sync (workstation, subagent-able)

**Контекст (D19):** `D:\project\infra\external_repos\unifi_manager\` — рассинхронизированное зеркало. Заменить на актуальную копию через rsync.

- [ ] **Step 3.1: Проверить infra repo существует**

```bash
ls "D:/project/infra/external_repos/unifi_manager" 2>&1 | head -5
```

- [ ] **Step 3.2: Sync через rsync (исключая .git, .venv, build artifacts)**

```bash
rsync -av --delete \
  --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
  --exclude='dist' --exclude='build' --exclude='*.egg-info' \
  --exclude='.pytest_cache' --exclude='.mypy_cache' --exclude='.ruff_cache' \
  --exclude='.claude' --exclude='.clone' \
  "D:/project/unifi_manager/" \
  "D:/project/infra/external_repos/unifi_manager/"
```

(На Windows rsync может не быть — альтернатива: `robocopy` или manual copy. Если нет rsync — `robocopy "D:\project\unifi_manager" "D:\project\infra\external_repos\unifi_manager" /MIR /XD .git .venv __pycache__ dist build .claude .clone /XF *.pyc`)

- [ ] **Step 3.3: Commit в infra repo**

```bash
cd "D:/project/infra"
git add external_repos/unifi_manager/
git commit -m "chore: sync unifi_manager mirror to refactored v0.1.0 (post Phase 5)"
```

---

## Task 4: Update infra docs (workstation, subagent-able)

**Файл:** `D:\project\infra\docs\network\unifi-framework.md` — описывает СТАРУЮ архитектуру (legacy скрипты). Переписать под новый пакет.

- [ ] **Step 4.1: Прочитать текущий unifi-framework.md** чтобы понять structure.

- [ ] **Step 4.2: Переписать** — заменить описание legacy скриптов на:
  - Новый пакет `unifi-mgr` (CLI, 5 слоёв)
  - Команды (audit/restart/export/diag/notify/zabbix)
  - Deployment в `/opt/unifi-mgr/`
  - Ссылка на main repo (Forgejo) + runbooks
  - Отметить что SYSID_MAP теперь в `domain/device.py` (был в зеркале)

- [ ] **Step 4.3: Commit в infra repo**

```bash
cd "D:/project/infra"
git add docs/network/unifi-framework.md
git commit -m "docs: update unifi-framework.md под refactored unifi-mgr architecture"
```

---

## Task 5: Workstation final cleanup verification (subagent-able)

- [ ] **Step 5.1: Verify нет legacy artifacts на workstation main**

```bash
cd "D:/project/unifi_manager"
ls -1 | grep -v '^\.' | grep -v '^src$\|^tests$\|^scripts$\|^docs$\|^dist$\|^build$'
```
Expected: только `README.md`, `LICENSE`, `config.yaml.example`, `pyproject.toml`. Никаких legacy .py.

- [ ] **Step 5.2: Tests + smoke**

```bash
.venv/Scripts/pytest --no-cov          # 267+ PASS
.venv/Scripts/unifi-mgr --version       # 0.1.0
```

---

## Task 6: phase-6-complete tag + final status (workstation, subagent-able)

- [ ] **Step 6.1: Update docs/refactor-status.md** — отметить phases 5, 6 complete:

```markdown
- [x] Фаза 5: Cron switch (production) — completed YYYY-MM-DD
- [x] Фаза 6: Cleanup — completed YYYY-MM-DD
- [ ] Фаза 7: Post-migration features (deferred per D28)
```

Plus note: Telegram excluded (РФ block), Matrix — future backlog.

- [ ] **Step 6.2: Update README.md статус** аналогично.

- [ ] **Step 6.3: Commit + push + tag**

```bash
cd "D:/project/unifi_manager" && export PATH="$PWD/.venv/Scripts:$PATH"
git add docs/refactor-status.md README.md
git commit -m "phase6: cleanup complete — legacy removed, infra synced, docs updated"
git tag -a phase-6-complete -m "Phase 6 (Cleanup) complete: production legacy removed, infra mirror synced, framework docs updated. Refactor project closed."
git push origin main
git push origin phase-6-complete
```

---

## Definition of Done — Phase 6 (= Project Complete)

| Check | Expected |
|---|---|
| Production cron | только `/opt/unifi-mgr/bin/unifi-mgr ...`, никаких legacy |
| Production legacy скрипты | удалены (архив сохранён) |
| Workstation main | только refactor код |
| Infra mirror | синхронизирован с main repo |
| Infra unifi-framework.md | описывает новую архитектуру |
| Tags | phase-5-complete + phase-6-complete |
| Tests | 267+ PASS |
| **ПРОЕКТ** | **ЗАКРЫТ** ✅ |

---

## После Phase 6 (backlog, не в дедлайн)

- **Matrix integration** — `integrations/matrix.py` (friend's server), замена/дополнение Telegram. См. memory `telegram_matrix_notifications.md`.
- **Phase 7 features** (deferred per D28) — maintenance mode, controller health check, port errors delta — по факту инцидентов.
- **Phase 4R** (Report module) — HTML отчёты, parallel track (D33).
- **Phase 4M** (MCP wrapper) — exposing services через FastMCP (D31/D36).
