# Phase 5 — Cron Switch (Production) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development для REPO prep tasks (Tasks 1, 2, 3, 10). **Tasks 4-9 — manual operator runbook** на production сервере (Ubuntu 24.04 LTS, host `192.0.2.1`). Steps used checkbox (`- [ ]`) syntax — операторские шаги отмечает оператор сам после выполнения, dispatcher subagent НЕ для них.

**Goal:** Перенести production cron'ы с legacy скриптов (`_legacy/`) на новый `unifi-mgr` CLI, по одной строке за раз с 24+ часов наблюдения между. 7-дневный observation period перед `phase-5-complete` tag.

**Architecture:** Incremental cron switch — 5 stages в порядке возрастания риска. На каждом этапе: editor cron → монитор 24 часа → если регрессий нет, следующий этап. Legacy скрипты остаются в `_legacy/` рабочими (rollback = одна строка crontab).

**Tech Stack:** Linux Ubuntu 24.04 LTS, systemd, cron, Python 3.12, существующий `unifi-mgr` пакет (Phase 4).

**Гейт готовности:** Все 5 cron-job на новом CLI, 7 дней без регрессий, нет false-positive Telegram алертов, restart_history совместим с legacy форматом.

**Ветка работы:** `worktree-refactor+v2` (продолжение с Phase 4 для subagent-prep tasks). Production деплой — отдельный server.

**Связанный спек:** [docs/superpowers/specs/2026-05-16-unifi-manager-refactor-design.md](../specs/2026-05-16-unifi-manager-refactor-design.md), Разделы 5.4 (cron migration table), 5.5 (deployment layout).

**Предыдущая фаза:** [phase-4-cli-complete.md](2026-05-18-phase-4-cli-complete.md) — CLI complete, tag `phase-4-complete`.

**Production server:** `192.0.2.1` (UniFi controller хост, `/home/operator/`). SSH access от operator.

**Operator notes:** Все Tasks 2-9 выполняются на production server через SSH. Repo (Windows workstation) синхронизируется отдельно — wheel/runbook доставляются на сервер через scp или git pull.

---

## Phase 5 critical safety notes

1. **`_legacy/` НЕ удаляется** в этой фазе — это Phase 6. Legacy скрипты остаются работоспособными на сервере для rollback.
2. **`restart_history.json` migration** — новый код Phase 3 читает legacy format (Task 1 Phase 3). Первый запуск нового `restart auto` continues prior history без data loss.
3. **Между stages 4 и 5 — 3-4 дня** (per spec), не 24 часа. `restart auto` — самая опасная команда (массовый рестарт).
4. **Telegram алерт-шторм risk:** AlertHistory dedup активен из Phase 2. При первой неделе наблюдения — повышенная чувствительность к необычному количеству алертов.
5. **Rollback процедура** — одна строка crontab. Documented в каждом stage.

---

## File Structure

### Создаются (subagent prep — Tasks 1-3):

```
scripts/
├── install-production.sh   # one-time setup для /opt/unifi-mgr/, /etc/, /var/
├── deploy.sh                # release rotation через symlinks
└── verify-deployment.sh    # post-install smoke checks

docs/
└── runbooks/
    └── phase-5-cron-migration.md   # operator runbook для Tasks 4-9
```

### НЕ трогаются:

- `src/unifi_manager/` — Phase 4 done, никакого кода в Phase 5
- `_legacy/` — остаётся для rollback
- `pyproject.toml` (кроме возможной правки version если нужно)

### На production server (operator):

```
/opt/unifi-mgr/
├── current -> releases/2026-05-21-a42b2dd/
├── releases/
│   └── 2026-05-21-a42b2dd/.venv/...
└── bin/unifi-mgr -> current/.venv/bin/unifi-mgr

/etc/unifi-mgr/
├── config.yaml          # 640 root:unifi-mgr
└── .env                 # 600 root:root (secrets)

/var/log/unifi-mgr/      # 755 unifi-mgr:unifi-mgr
/var/lib/unifi-mgr/      # 750 unifi-mgr:unifi-mgr
```

---

## Pre-flight Checklist (operator на server, before Task 1)

Эти проверки **обязательны** перед стартом Phase 5 — без них stages могут упасть тихо.

- [ ] SSH доступ к `192.0.2.1` работает: `ssh operator@192.0.2.1`
- [ ] Python 3.12 доступен: `python3.12 --version` → `Python 3.12.x`
- [ ] Sudo доступ для создания `/opt/unifi-mgr/`, `/etc/unifi-mgr/`, `/var/log/unifi-mgr/`
- [ ] Текущий crontab задокументирован: `sudo crontab -l > ~/crontab-pre-phase5-backup.txt`
- [ ] Legacy скрипты работают: проверка `python3 /home/operator/unifi_manager/check_critical.py` отрабатывает
- [ ] UniFi controller доступен с сервера (он же на нём и крутится — должно быть OK)
- [ ] Telegram bot токен функционирует (legacy `telegram_notify.py` отрабатывает)
- [ ] Достаточно места на диске для `/opt/unifi-mgr/releases/` (`df -h /opt`) — нужно ~200MB для wheel + venv
- [ ] Email уведомления оператору при cron failure настроены (MAILTO в crontab)

Если хоть что-то не выполнено — fix первым делом или **stop the phase**.

---

## Task 1: Build deployment artifacts (subagent)

**Files:**
- Create: `scripts/install-production.sh`
- Create: `scripts/deploy.sh`
- Create: `scripts/verify-deployment.sh`

**Goal:** Создать install и deploy скрипты которые operator использует на production. Это repo-side работа, можно делегировать subagent.

- [ ] **Step 1.1: Create `scripts/install-production.sh`**

```bash
#!/bin/bash
# One-time production setup для unifi-mgr.
# Запускается с sudo на production server.
#
# Usage:
#   sudo bash scripts/install-production.sh
#
# Создаёт:
#   - User/group unifi-mgr (system account)
#   - /opt/unifi-mgr/{releases,bin}/ (755 unifi-mgr:unifi-mgr)
#   - /etc/unifi-mgr/ (755 root:unifi-mgr)
#   - /var/log/unifi-mgr/ (755 unifi-mgr:unifi-mgr)
#   - /var/lib/unifi-mgr/ (750 unifi-mgr:unifi-mgr)

set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "Error: must run with sudo"
    exit 1
fi

USER_NAME="unifi-mgr"
GROUP_NAME="unifi-mgr"

echo "==> Creating system user/group ${USER_NAME}..."
if ! id -u "$USER_NAME" &>/dev/null; then
    useradd --system --user-group --shell /usr/sbin/nologin \
            --home-dir /var/lib/unifi-mgr --no-create-home "$USER_NAME"
fi

echo "==> Creating directories..."
install -d -m 755 -o "$USER_NAME" -g "$GROUP_NAME" /opt/unifi-mgr
install -d -m 755 -o "$USER_NAME" -g "$GROUP_NAME" /opt/unifi-mgr/releases
install -d -m 755 -o "$USER_NAME" -g "$GROUP_NAME" /opt/unifi-mgr/bin
install -d -m 755 -o root -g "$GROUP_NAME" /etc/unifi-mgr
install -d -m 755 -o "$USER_NAME" -g "$GROUP_NAME" /var/log/unifi-mgr
install -d -m 750 -o "$USER_NAME" -g "$GROUP_NAME" /var/lib/unifi-mgr

echo "==> Setup complete. Next:"
echo "  1. Copy config.yaml to /etc/unifi-mgr/config.yaml (chmod 640)"
echo "  2. Copy .env to /etc/unifi-mgr/.env (chmod 600, root:root)"
echo "  3. Run scripts/deploy.sh to install first release"
```

- [ ] **Step 1.2: Create `scripts/deploy.sh`**

```bash
#!/bin/bash
# Deploy a new unifi-mgr release.
# Запускается с sudo. Argument: wheel file (e.g. unifi_mgr-0.1.0-py3-none-any.whl).
#
# Usage:
#   sudo bash scripts/deploy.sh /path/to/unifi_mgr-0.1.0-py3-none-any.whl
#
# Эффект:
#   - Создаёт /opt/unifi-mgr/releases/<DATE>-<SHORT_SHA>/.venv
#   - Устанавливает wheel в этот venv
#   - Атомарно переключает /opt/unifi-mgr/current symlink на новый release
#   - Обновляет /opt/unifi-mgr/bin/unifi-mgr symlink

set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "Error: must run with sudo"
    exit 1
fi

if [ $# -lt 1 ]; then
    echo "Usage: sudo bash $0 <wheel-file>"
    exit 1
fi

WHEEL="$1"
if [ ! -f "$WHEEL" ]; then
    echo "Error: wheel file not found: $WHEEL"
    exit 1
fi

USER_NAME="unifi-mgr"
RELEASE_ID="$(date +%Y-%m-%d)-$(basename "$WHEEL" | grep -oP '\d+\.\d+\.\d+' | head -1)"
RELEASE_DIR="/opt/unifi-mgr/releases/${RELEASE_ID}"

if [ -d "$RELEASE_DIR" ]; then
    echo "==> Release dir already exists, appending suffix"
    RELEASE_ID="${RELEASE_ID}-$(date +%H%M%S)"
    RELEASE_DIR="/opt/unifi-mgr/releases/${RELEASE_ID}"
fi

echo "==> Creating release at ${RELEASE_DIR}..."
install -d -m 755 -o "$USER_NAME" -g "$USER_NAME" "$RELEASE_DIR"

echo "==> Creating virtualenv (Python 3.12)..."
sudo -u "$USER_NAME" python3.12 -m venv "${RELEASE_DIR}/.venv"

echo "==> Installing wheel..."
sudo -u "$USER_NAME" "${RELEASE_DIR}/.venv/bin/pip" install --upgrade pip
sudo -u "$USER_NAME" "${RELEASE_DIR}/.venv/bin/pip" install "$WHEEL"

echo "==> Atomic symlink switch..."
ln -sfn "$RELEASE_DIR" /opt/unifi-mgr/current.new
mv -Tf /opt/unifi-mgr/current.new /opt/unifi-mgr/current

ln -sfn /opt/unifi-mgr/current/.venv/bin/unifi-mgr /opt/unifi-mgr/bin/unifi-mgr

echo "==> Verify version..."
/opt/unifi-mgr/bin/unifi-mgr --version

echo "==> Deployed: $RELEASE_ID"
echo "==> To rollback: ln -sfn /opt/unifi-mgr/releases/<previous> /opt/unifi-mgr/current"
```

- [ ] **Step 1.3: Create `scripts/verify-deployment.sh`**

```bash
#!/bin/bash
# Post-install smoke checks для production deployment.
# Можно запускать с любого user'а — non-destructive.
#
# Usage:
#   bash scripts/verify-deployment.sh

set -uo pipefail

UNIFI_MGR="${UNIFI_MGR:-/opt/unifi-mgr/bin/unifi-mgr}"
CONFIG="${CONFIG:-/etc/unifi-mgr/config.yaml}"

FAIL_COUNT=0

function check() {
    local name="$1"
    local cmd="$2"
    echo -n "  [${name}] ... "
    if eval "$cmd" >/dev/null 2>&1; then
        echo "OK"
    else
        echo "FAIL"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

echo "==> Production deployment verification"
echo

check "Binary exists" "[ -x $UNIFI_MGR ]"
check "Binary runs" "$UNIFI_MGR --version"
check "Config file readable" "[ -r $CONFIG ]"
check ".env file exists" "[ -r /etc/unifi-mgr/.env ]"
check "/var/log/unifi-mgr writable" "[ -w /var/log/unifi-mgr ]"
check "/var/lib/unifi-mgr writable" "[ -w /var/lib/unifi-mgr ]"
check "Config validates" "$UNIFI_MGR --config $CONFIG config validate"

echo
if [ "$FAIL_COUNT" -eq 0 ]; then
    echo "==> All checks PASSED"
    exit 0
else
    echo "==> $FAIL_COUNT check(s) FAILED — fix before proceeding"
    exit 1
fi
```

- [ ] **Step 1.4: Make all scripts executable**

```bash
chmod +x scripts/install-production.sh scripts/deploy.sh scripts/verify-deployment.sh
bash -n scripts/install-production.sh
bash -n scripts/deploy.sh
bash -n scripts/verify-deployment.sh
```
Expected: all 3 syntax-OK.

- [ ] **Step 1.5: Commit**

```bash
git add scripts/install-production.sh scripts/deploy.sh scripts/verify-deployment.sh
git commit -m "phase5: production deployment scripts (install, deploy, verify)"
```

---

## Task 2: Build wheel artifact (subagent)

**Files:**
- Build artifact: `dist/unifi_mgr-0.1.0-py3-none-any.whl`

**Goal:** Build wheel для deployment.

- [ ] **Step 2.1: Build wheel**

```bash
.venv/Scripts/python -m pip install --upgrade build
.venv/Scripts/python -m build --wheel
ls dist/
```
Expected: `dist/unifi_mgr-0.1.0-py3-none-any.whl` created.

- [ ] **Step 2.2: Verify wheel contains py.typed**

```bash
.venv/Scripts/python -m zipfile -l dist/unifi_mgr-0.1.0-py3-none-any.whl | grep py.typed
```
Expected: line containing `unifi_manager/py.typed`.

- [ ] **Step 2.3: Verify CLI запускается из freshly installed wheel**

```bash
rm -rf .venv-prod-test
py -3.12 -m venv .venv-prod-test
.venv-prod-test/Scripts/pip install dist/unifi_mgr-0.1.0-py3-none-any.whl
.venv-prod-test/Scripts/unifi-mgr --version
```
Expected: `unifi-mgr 0.1.0`.

```bash
.venv-prod-test/Scripts/unifi-mgr --help
```
Expected: 9 subcommand groups (audit/restart/export/diag/notify/zabbix/config/login/legacy).

- [ ] **Step 2.4: Cleanup test venv**

```bash
rm -rf .venv-prod-test
```

- [ ] **Step 2.5: Note artifact location (для operator scp)**

Wheel в `dist/unifi_mgr-0.1.0-py3-none-any.whl` (gitignored). Operator копирует через scp:

```bash
# (operator на workstation)
scp dist/unifi_mgr-0.1.0-py3-none-any.whl operator@192.0.2.1:/tmp/
```

(Не commit'ить — dist/ в `.gitignore`.)

---

## Task 3: Operator runbook (subagent)

**Files:**
- Create: `docs/runbooks/phase-5-cron-migration.md`

**Goal:** Создать step-by-step runbook для operator. Это **единственная документация** которой operator пользуется в Tasks 4-9.

- [ ] **Step 3.1: Create `docs/runbooks/` directory**

```bash
mkdir -p docs/runbooks
```

- [ ] **Step 3.2: Write `docs/runbooks/phase-5-cron-migration.md`**

```markdown
# Phase 5 — Cron Migration Runbook

**Производственный сервер:** `192.0.2.1` (UniFi controller хост)
**Linux:** Ubuntu 24.04 LTS
**Дата старта:** заполнить при начале
**Оператор:** заполнить

---

## Подготовка (one-time, до первого cron stage)

### Pre-flight checklist

Перед началом — пробежать checklist из плана `phase-5-cron-switch.md`.

### Initial production setup

1. **SCP wheel + scripts на сервер:**

   ```bash
   # На workstation
   scp dist/unifi_mgr-0.1.0-py3-none-any.whl operator@192.0.2.1:/tmp/
   scp scripts/install-production.sh operator@192.0.2.1:/tmp/
   scp scripts/deploy.sh operator@192.0.2.1:/tmp/
   scp scripts/verify-deployment.sh operator@192.0.2.1:/tmp/
   scp config.yaml.example operator@192.0.2.1:/tmp/
   scp .env.example operator@192.0.2.1:/tmp/
   ```

2. **SSH на сервер:**

   ```bash
   ssh operator@192.0.2.1
   ```

3. **Run install:**

   ```bash
   sudo bash /tmp/install-production.sh
   ```

   Expected: создаются user/group `unifi-mgr`, директории `/opt/unifi-mgr/`, `/etc/unifi-mgr/`, `/var/log/unifi-mgr/`, `/var/lib/unifi-mgr/`.

4. **Configure:**

   ```bash
   sudo cp /tmp/config.yaml.example /etc/unifi-mgr/config.yaml
   sudo nano /etc/unifi-mgr/config.yaml
   # ВАЖНО: проставить:
   #   - unifi.host: 192.0.2.1
   #   - unifi.port: 11443
   #   - unifi.site: site-1 (или актуальный slug)
   #   - unifi.site_id_uuid: <UUID для Integration API>
   #   - telegram.chat_id: "<ваш chat_id>"
   #   - restart_profiles.restaurant: filter_names как было в legacy
   #   - logging.log_dir: /var/log/unifi-mgr
   #   - paths.reports_dir: /var/lib/unifi-mgr/reports
   sudo chmod 640 /etc/unifi-mgr/config.yaml
   sudo chown root:unifi-mgr /etc/unifi-mgr/config.yaml
   ```

   ```bash
   sudo cp /tmp/.env.example /etc/unifi-mgr/.env
   sudo nano /etc/unifi-mgr/.env
   # Прописать:
   #   UNIFI_UNIFI__USERNAME=unifi_user
   #   UNIFI_UNIFI__PASSWORD=<актуальный пароль из старого config.json>
   #   UNIFI_UNIFI__API_KEY=<Integration API key>
   #   UNIFI_TELEGRAM__BOT_TOKEN=<токен бота>
   sudo chmod 600 /etc/unifi-mgr/.env
   sudo chown root:root /etc/unifi-mgr/.env
   ```

5. **Migrate legacy restart_history:**

   ```bash
   # Скопировать legacy restart history в новую локацию
   sudo -u unifi-mgr cp /home/operator/logs/ap_restart_history.json \
                       /var/lib/unifi-mgr/restart_history.json
   ```

   Новый код Phase 3 читает legacy format автоматически.

6. **Deploy первый release:**

   ```bash
   sudo bash /tmp/deploy.sh /tmp/unifi_mgr-0.1.0-py3-none-any.whl
   ```

   Expected: `==> Deployed: 2026-05-21-0.1.0` + `unifi-mgr 0.1.0`.

7. **Verify deployment:**

   ```bash
   bash /tmp/verify-deployment.sh
   ```

   Expected: `==> All checks PASSED`. Если что-то FAIL — fix первым делом.

8. **Smoke test live:**

   ```bash
   /opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml login test
   ```

   Expected:
   ```
   ✓ Legacy API login OK
   ✓ Integration API access OK
   ```

   ```bash
   /opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml audit status
   ```

   Expected: `Total: 271` (или актуальное число устройств), `Online: <N>`, `By type: ...`.

   ```bash
   /opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml audit critical
   ```

   Expected: либо `✓ No critical issues found`, либо список реальных проблем (соответствующих текущему состоянию сети).

9. **Backup текущий crontab:**

   ```bash
   sudo crontab -l > ~/crontab-pre-phase5-backup.txt
   cat ~/crontab-pre-phase5-backup.txt
   ```

   Сохранить файл — это rollback baseline.

---

## Stage 1: Switch `audit full` cron (LOW RISK)

**Старая строка:**
```
0 9 * * * /home/operator/unifi_manager/run_audit.sh
```

**Новая строка:**
```
0 9 * * * /opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml audit full --json >> /var/log/unifi-mgr/cron-audit-full.log 2>&1
```

### Steps

1. **Backup crontab перед изменением:**

   ```bash
   sudo crontab -l > ~/crontab-before-stage1.txt
   ```

2. **Edit crontab:**

   ```bash
   sudo crontab -e
   ```

   Закомментировать (НЕ удалять) старую строку, добавить новую:
   ```
   # 0 9 * * * /home/operator/unifi_manager/run_audit.sh
   0 9 * * * /opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml audit full --json >> /var/log/unifi-mgr/cron-audit-full.log 2>&1
   ```

3. **Ждать следующего планового запуска (09:00 на следующий день).**

   До этого момента — не trogат остальные cron'ы.

4. **На следующий день после 09:00 — проверить:**

   ```bash
   # Проверить что cron отработал
   tail -50 /var/log/unifi-mgr/cron-audit-full.log

   # Проверить main JSON log
   tail -100 /var/log/unifi-mgr/unifi-mgr.log | jq -c 'select(.cmd == "audit full" or .logger | startswith("unifi_manager"))'
   ```

   **Expected:**
   - cron-audit-full.log содержит валидный JSON с `"devices": [...]` массивом
   - unifi-mgr.log содержит logged structured records от выполнения
   - exit code был 0 (cron не отправил email об ошибке)

5. **Если всё ОК — переходим к Stage 2.**

### Rollback Stage 1

Если cron упал или output broken:

```bash
sudo crontab -e
# Удалить новую строку, раскомментировать старую:
# 0 9 * * * /home/operator/unifi_manager/run_audit.sh
```

Backup для верификации: `cat ~/crontab-before-stage1.txt`.

---

## Stage 2: Switch `audit critical` cron (LOW RISK)

**Старая строка:**
```
*/15 * * * * /home/operator/unifi_manager/check_critical.py >> /home/operator/logs/critical_check.log 2>&1
```

**Новая строка:**
```
*/15 * * * * /opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml audit critical --telegram --json >> /var/log/unifi-mgr/cron-audit-critical.log 2>&1
```

### Steps

1. **Backup:**
   ```bash
   sudo crontab -l > ~/crontab-before-stage2.txt
   ```

2. **Edit crontab:**
   ```bash
   sudo crontab -e
   ```
   Закомментировать старую строку, добавить новую.

3. **15-минутный observation:**

   После следующего срабатывания (≤15 минут):
   ```bash
   tail -50 /var/log/unifi-mgr/cron-audit-critical.log
   ```
   Expected: JSON array (пустой если no issues, либо со списком issues).

   **Проверка дедупликации Telegram:**
   - Если на момент перехода были active issues — оператор должен получить **один** Telegram per (mac, error_type), не каждые 15 минут.
   - В течение часа после первого срабатывания НЕ должно быть повторов того же hash_key.

4. **24-часовое наблюдение:**

   ```bash
   # Через 24 часа после переключения
   grep -c "send_message" /var/log/unifi-mgr/unifi-mgr.log
   # Сколько раз Telegram реально вызывался — ожидаемо: только при изменении состава issues
   ```

   Также — нет ли необычного количества алертов в TG чате (по сравнению с обычным днём с legacy кодом).

5. **Если всё ОК — Stage 3.**

### Rollback Stage 2

```bash
sudo crontab -e
# Удалить новую строку, раскомментировать старую
```

---

## Stage 3: Add `audit trends` cron (ZERO RISK)

**Это новый cron** — не заменяет ничего legacy, просто добавляется. Поэтому zero risk.

**Новая строка:**
```
0 6 * * * /opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml audit trends --json >> /var/log/unifi-mgr/cron-audit-trends.log 2>&1
```

### Steps

1. **Edit crontab:**
   ```bash
   sudo crontab -e
   ```
   Добавить новую строку (no removal).

2. **Подождать следующего 06:00.**

3. **Проверить:**
   ```bash
   tail -30 /var/log/unifi-mgr/cron-audit-trends.log
   ```
   Expected: JSON `{"data_points": [...]}` со списком исторических отчётов из `paths.reports_dir`.

   Если `paths.reports_dir` пуст — это OK, `data_points` будет `[]`.

4. **Если ОК — Stage 4.**

### Rollback Stage 3

```bash
sudo crontab -e
# Удалить добавленную строку
```

---

## Stage 4: Switch `restart profile restaurant` cron (MEDIUM RISK)

**Старая строка:**
```
0 7 * * * /home/operator/unifi_manager/restart_restaurant_aps_v2.py >> /home/operator/logs/restaurant_restart.log 2>&1
```

**Новая строка:**
```
0 7 * * * /opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml restart profile restaurant --apply --json >> /var/log/unifi-mgr/cron-restart-restaurant.log 2>&1
```

### Pre-stage validation (КРИТИЧНО — это первая реально-меняющая команда)

1. **Dry-run новой команды вручную:**

   ```bash
   /opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml restart profile restaurant
   ```

   (Без `--apply` — default dry-run.)

   **Expected output:**
   - `[DRY-RUN] Status: completed, Actions: N`
   - Список AP которые **будут** рестартованы при `--apply`
   - Должно быть только ресторанные AP (Restoran, Restoran WIFI, Rest Bar). НЕ Spasatel vagon, НЕ офисные.

2. **Сравнение с legacy выводом:**

   ```bash
   # Legacy script — также dry-run манерой (если есть способ) или просто visual compare names
   python3 /home/operator/unifi_manager/restart_restaurant_aps_v2.py
   ```

   Names AP в обоих списках должны совпадать (плюс-минус — legacy threshold может быть другой).

3. **Если списки расходятся существенно — STOP.** Не переходить к real cron switch. Investigate restart_profiles config.

### Steps

1. **Backup:**
   ```bash
   sudo crontab -l > ~/crontab-before-stage4.txt
   ```

2. **Edit crontab:**
   ```bash
   sudo crontab -e
   ```
   Закомментировать старую, добавить новую (с `--apply`!).

3. **Подождать 07:00 следующего дня.**

4. **На следующий день после 07:00 — проверить:**

   ```bash
   tail -50 /var/log/unifi-mgr/cron-restart-restaurant.log
   ```

   Expected: JSON со `"status": "completed"`, `"dry_run": false`, `"actions": [...]`.

   ```bash
   # Проверить restart_history обновился
   cat /var/lib/unifi-mgr/restart_history.json | jq 'keys | length'
   ```

   Должно быть >0.

   ```bash
   # UI verification — оператор смотрит в UniFi controller
   # Проверить статусы AP в ресторане
   ```

5. **3-4 ДНЯ наблюдения** перед переходом к Stage 5:
   - Сравнить количество incident'ов в ресторане до/после
   - Нет ли необычных перезагрузок
   - Telegram не штормит false-positive

6. **Если 3+ дня всё стабильно — Stage 5.**

### Rollback Stage 4

```bash
sudo crontab -e
# Удалить новую строку, раскомментировать старую
```

Если был неправильный массовый рестарт — restart_history.json удалить чтобы legacy не получил битый формат:

```bash
sudo rm /var/lib/unifi-mgr/restart_history.json
sudo -u unifi-mgr cp /home/operator/logs/ap_restart_history.json \
                    /var/lib/unifi-mgr/restart_history.json
```

---

## Stage 5: Switch `restart auto` cron (HIGH RISK)

**САМЫЙ ОПАСНЫЙ STAGE.** Затрагивает любые проблемные AP (не только ресторан), запускается каждые 30 минут.

**Старая строка:**
```
*/30 * * * * /home/operator/unifi_manager/auto_restart_cron.sh
```

**Новая строка:**
```
*/30 * * * * /opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml restart auto --json >> /var/log/unifi-mgr/cron-restart-auto.log 2>&1
```

### Pre-stage validation (ОБЯЗАТЕЛЬНО — несколько ручных прогонов)

1. **Dry-run несколько раз в течение дня:**

   ```bash
   for i in 1 2 3 4; do
       echo "=== Dry-run $i ==="
       /opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml restart auto --dry-run
       sleep 600  # 10 min
   done
   ```

   **Sanity checks:**
   - Список actions reasonable (не больше `max_restarts_per_run: 5`)
   - exclude_patterns (Spasatel, test) работают — эти AP не в списке
   - cooldown работает — AP который "рестартился" 5 минут назад в state cooldown_skip

2. **Сравнение с legacy auto_restart_problem_aps.py:**

   ```bash
   python3 /home/operator/unifi_manager/auto_restart_problem_aps.py
   # Visual compare — должна быть та же логика выбора priority + cooldown
   ```

3. **Если списки расходятся существенно — STOP.**

### Permissions kill-switch на руки

**Перед Stage 5 — verify kill-switch работает:**

```bash
# Включить kill-switch
sudo nano /etc/unifi-mgr/config.yaml
# Добавить (если ещё нет):
# permissions:
#   cli:
#     restart:
#       execute: false

# Test
/opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml restart auto
# Expected: "Status: skipped_permissions" + log warning

# ВЕРНУТЬ обратно (иначе cron не будет ничего делать!)
sudo nano /etc/unifi-mgr/config.yaml
# Изменить execute: false → execute: true (или удалить блок — default True)
```

Это страховка: если в любой момент после Stage 5 нужно экстренно остановить auto-restart, оператор знает как это сделать в одну строку.

### Steps

1. **Backup:**
   ```bash
   sudo crontab -l > ~/crontab-before-stage5.txt
   ```

2. **Edit crontab:**
   ```bash
   sudo crontab -e
   ```
   Закомментировать старую, добавить новую.

3. **Очень внимательно наблюдать первый час** — каждые 30 минут будет срабатывание:

   ```bash
   # Через 30 минут после переключения
   tail -100 /var/log/unifi-mgr/cron-restart-auto.log
   ```

   Expected: JSON, `"status": "completed"`, `"actions": [...]` (часто пустой если нет проблем).

   ```bash
   # Проверить что нет дубль-запусков (FileLock работает)
   pgrep -f 'unifi-mgr restart auto' | wc -l
   ```

   Должно быть 0 или 1 (никогда не 2+).

4. **3-4 дня наблюдения:**

   ```bash
   # Сколько рестартов в сутки
   grep -c "status.*success" /var/log/unifi-mgr/cron-restart-auto.log
   ```

   Сравнить с baseline до Phase 5 (sudo journalctl + legacy auto_restart_cron.log).

5. **Если стабильно — переходим к 7-дневному observation.**

### Rollback Stage 5

```bash
sudo crontab -e
# Удалить новую строку, раскомментировать старую
```

Если был массовый ложный рестарт — поднять kill-switch:
```yaml
permissions:
  cli:
    restart:
      execute: false
```
И investigate logs прежде чем включить обратно.

---

## 7-day Observation Period

**Старт:** сразу после Stage 5 завершения с успехом.

### Daily checklist (на каждый из 7 дней)

```bash
# Текущее состояние всех cron'ов за последние 24 часа
echo "=== audit full ===" && tail -5 /var/log/unifi-mgr/cron-audit-full.log
echo "=== audit critical ===" && tail -10 /var/log/unifi-mgr/cron-audit-critical.log
echo "=== audit trends ===" && tail -5 /var/log/unifi-mgr/cron-audit-trends.log
echo "=== restart profile restaurant ===" && tail -10 /var/log/unifi-mgr/cron-restart-restaurant.log
echo "=== restart auto ===" && tail -20 /var/log/unifi-mgr/cron-restart-auto.log

# Sumamry за 24 часа
grep "$(date -d yesterday +%Y-%m-%d)" /var/log/unifi-mgr/unifi-mgr.log | \
    jq -c 'select(.level == "WARNING" or .level == "ERROR")' | \
    head -50

# Telegram алерты — сколько отправилось
grep "TelegramNotifier" /var/log/unifi-mgr/unifi-mgr.log | grep "$(date +%Y-%m-%d)" | wc -l
```

### Pass criteria (на 7-й день)

| Criterion | Threshold |
|---|---|
| Cron upset count | 0 (нет email от cron о failed jobs) |
| Stack tracebacks в logs | 0 (никаких unhandled exceptions) |
| Telegram алертов в сутки | ≤ обычного daily baseline (legacy) |
| `restart auto` фактических рестартов | в пределах legacy baseline |
| `restart_history.json` валиден | `jq . /var/lib/unifi-mgr/restart_history.json` не падает |
| User network complaints | 0 непривычных от user (ресторан, гости) |

### Если pass criteria выполнены — Task 10.

### Если что-то failed — investigate, rollback affected stage, fix, restart observation window.

---

## После 7-day observation

Operator informs developer (через ticket / message): "Phase 5 observation complete, all stable. Ready for tag."

Developer:

1. Создаёт tag (Task 10).
2. Planning Phase 6 (cleanup, удаление `_legacy/`).

Operator на сервере:

- НЕ удалять `_legacy/` ещё — это Phase 6.
- НЕ удалять legacy crontab backup files — храним до конца Phase 6.

---

## Emergency rollback (полный возврат к legacy)

Если что-то пошло не так глобально:

```bash
# Восстановить полный crontab от Phase 4 baseline
sudo crontab ~/crontab-pre-phase5-backup.txt
sudo crontab -l   # verify

# Проверить что legacy cron работает (через час-два)
ls -la /home/operator/logs/  # должны появиться новые logs
```

`/opt/unifi-mgr/` оставить — он не вредит ничему. Просто cron его не использует.

`_legacy/` скрипты продолжают работать как и до Phase 5.
```

- [ ] **Step 3.3: Verify markdown renders**

```bash
# (cwd should be worktree root)
ls docs/runbooks/phase-5-cron-migration.md
wc -l docs/runbooks/phase-5-cron-migration.md
```
Expected: file exists, ~400+ lines.

- [ ] **Step 3.4: Commit**

```bash
git add docs/runbooks/phase-5-cron-migration.md
git commit -m "phase5: docs/runbooks/phase-5-cron-migration.md — operator runbook"
```

---

## Task 4-9: Operator cron migration (manual на сервере)

**Эти tasks выполняет operator (user) на production server согласно runbook.** Subagents НЕ для этих tasks.

Operator работает по `docs/runbooks/phase-5-cron-migration.md`:

- [ ] **Task 4**: Initial production setup (Pre-flight + setup из runbook)
- [ ] **Task 5**: Stage 1 — `audit full` cron + 24h observation
- [ ] **Task 6**: Stage 2 — `audit critical --telegram` + 24h observation
- [ ] **Task 7**: Stage 3 — `audit trends` (zero risk) + 24h observation
- [ ] **Task 8**: Stage 4 — `restart profile restaurant --apply` + **3-4 days** observation
- [ ] **Task 9**: Stage 5 — `restart auto` + 7-day full observation

### Operator reporting back

После каждого stage operator пишет в chat developer'у:
- "Stage N complete, no regressions in 24h, ready for Stage N+1"
- ИЛИ "Stage N failed, rolled back, investigating issue X"

Developer (subagent) сам не runs Tasks 4-9 — только пишет/правит runbook если operator находит баг.

---

## Task 10: phase-5-complete tag (subagent после operator confirmation)

**Когда operator сообщает "7-day observation complete, all stable":**

- [ ] **Step 10.1: Quick repo verification**

```bash
# Full test suite still passes (ничего не должно было сломаться, но verify)
.venv/Scripts/pytest --no-cov
```
Expected: 267+ tests PASS.

- [ ] **Step 10.2: Create tag**

```bash
git tag -d phase-5-complete 2>/dev/null || true
git tag -a phase-5-complete -m "Phase 5 (Cron switch на проде) complete: все 5 cron stages migrated, 7-day observation passed без регрессий"
git describe --tags
```

- [ ] **Step 10.3: Update docs/refactor-status.md**

Edit `docs/refactor-status.md`. Find:
```markdown
- [x] Фаза 0: Foundation (этот план)
- [ ] Фаза 1: Core layers (clients, domain, utils)
...
- [ ] Фаза 5: Cron switch (production)
```

Update all completed phases:
```markdown
- [x] Фаза 0: Foundation
- [x] Фаза 1: Core layers (clients, domain, utils)
- [x] Фаза 2: Services + integrations
- [x] Фаза 3: Restart logic
- [x] Фаза 4: CLI complete
- [x] Фаза 5: Cron switch (production) — completed YYYY-MM-DD
- [ ] Фаза 6: Cleanup (удаление _legacy/)
- [ ] Фаза 7: Post-migration features (deferred per D28)
```

Where `YYYY-MM-DD` — фактическая дата завершения observation.

- [ ] **Step 10.4: Commit**

```bash
git add docs/refactor-status.md
git commit -m "phase5: mark phases 1-5 complete in refactor-status.md"
```

---

## Definition of Done — Phase 5

| Check | Expected |
|---|---|
| Все 5 cron-job на новом CLI | crontab показывает only new commands |
| Legacy cron строки закомментированы | старые комментарии в crontab остались (не удалены) |
| `/opt/unifi-mgr/` deployed | `bin/unifi-mgr --version` → `0.1.0` |
| Production config | `/etc/unifi-mgr/{config.yaml,.env}` exist с правильными правами |
| restart_history migrated | `/var/lib/unifi-mgr/restart_history.json` существует, читается обоими (legacy и новым) |
| 7 дней без регрессий | journalctl + cron logs чистые |
| Telegram baseline | алертов не больше чем при legacy (no false-positive spam) |
| Kill-switch tested | `permissions.cli.restart.execute: false` останавливает все restart cron'ы |
| Tag created | `git tag -l phase-5-complete` exists |
| Runbook archived | `docs/runbooks/phase-5-cron-migration.md` committed |

**Not in this phase:**
- ❌ Удаление `_legacy/` — **Phase 6** (после 7-day stable observation)
- ❌ Перезапись `docs/network/unifi-framework.md` в infra repo — Phase 6
- ❌ Удаление legacy crontab backup files — храним до Phase 6

---

## After Phase 5

`superpowers:writing-plans` для **Phase 6 (Cleanup)**:
- Удаление `_legacy/` directory из репы (после `LEGACY_REMOVAL_DATE` или раньше если всё стабильно)
- Удаление legacy crontab backup files на сервере
- Sync infra-зеркала `D:\project\infra\external_repos\unifi_manager\` (rsync per D19)
- Перепись `infra/docs/network/unifi-framework.md` под новую архитектуру
- Final merge `refactor/v2` → `master`
