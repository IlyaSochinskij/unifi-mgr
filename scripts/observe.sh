#!/bin/bash
# Phase 5 observation helper — собирает статус всех cron-job за последние 24ч.
# Запускать раз в день во время observation period.
#
# Usage:
#   bash scripts/observe.sh
#
# Non-destructive — только чтение логов.

set -uo pipefail

LOG_DIR="${LOG_DIR:-/var/log/unifi-mgr}"
LIB_DIR="${LIB_DIR:-/var/lib/unifi-mgr}"
MAIN_LOG="${LOG_DIR}/unifi-mgr.log"
TODAY="$(date +%Y-%m-%d)"

echo "==================================================================="
echo " Phase 5 Observation — ${TODAY}"
echo "==================================================================="

# --- Per-cron last output ---
for job in audit-full audit-critical audit-trends restart-restaurant restart-auto; do
    f="${LOG_DIR}/cron-${job}.log"
    echo
    echo "--- ${job} (last 5 lines) ---"
    if [ -f "$f" ]; then
        tail -5 "$f"
    else
        echo "  (no log yet — cron не срабатывал)"
    fi
done

# --- WARNING/ERROR за сегодня ---
echo
echo "--- WARNING/ERROR в main log за ${TODAY} ---"
if [ -f "$MAIN_LOG" ]; then
    if command -v jq >/dev/null 2>&1; then
        grep "$TODAY" "$MAIN_LOG" 2>/dev/null | \
            jq -rc 'select(.level == "WARNING" or .level == "ERROR") | "\(.level) \(.logger): \(.msg)"' 2>/dev/null | \
            head -30 || echo "  (нет WARNING/ERROR или jq parse fail)"
    else
        grep "$TODAY" "$MAIN_LOG" 2>/dev/null | grep -E '"level":\s*"(WARNING|ERROR)"' | head -30 || echo "  (нет WARNING/ERROR)"
    fi
else
    echo "  (main log не найден: $MAIN_LOG)"
fi

# --- Tracebacks (unhandled exceptions) ---
echo
echo "--- Python tracebacks за сегодня (должно быть 0) ---"
tb_count=$(grep -c "Traceback (most recent call last)" "${LOG_DIR}"/*.log 2>/dev/null | awk -F: '{s+=$2} END {print s+0}')
echo "  tracebacks: ${tb_count}"

# --- restart auto rate (фактические рестарты) ---
echo
echo "--- restart auto: успешных рестартов за сегодня ---"
ra_log="${LOG_DIR}/cron-restart-auto.log"
if [ -f "$ra_log" ]; then
    success=$(grep "$TODAY" "$ra_log" 2>/dev/null | grep -c '"status".*"success"' || echo 0)
    echo "  successful restarts: ${success}"
else
    echo "  (no restart-auto log)"
fi

# --- restart_history.json валидность ---
echo
echo "--- restart_history.json валидность ---"
rh="${LIB_DIR}/restart_history.json"
if [ -f "$rh" ]; then
    if command -v jq >/dev/null 2>&1; then
        if jq . "$rh" >/dev/null 2>&1; then
            entries=$(jq '.entries | length' "$rh" 2>/dev/null || jq 'keys | length' "$rh" 2>/dev/null || echo "?")
            echo "  OK — valid JSON, entries: ${entries}"
        else
            echo "  ⚠️ INVALID JSON — investigate!"
        fi
    else
        echo "  (jq не установлен — skip validation)"
    fi
else
    echo "  (restart_history.json не найден)"
fi

# --- FileLock дубль-запуски ---
echo
echo "--- Дубль-запуски restart auto (FileLock check) ---"
running=$(pgrep -fc 'unifi-mgr restart auto' 2>/dev/null || echo 0)
if [ "$running" -le 1 ]; then
    echo "  OK — ${running} процесс(ов) (норма: 0 или 1)"
else
    echo "  ⚠️ ${running} процессов — FileLock не сработал?!"
fi

echo
echo "==================================================================="
echo " Pass criteria: tracebacks=0, restart_history valid, FileLock OK,"
echo " restart rate в пределах baseline, нет cron failure emails."
echo "==================================================================="
