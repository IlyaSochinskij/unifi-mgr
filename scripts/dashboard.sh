#!/bin/bash
# UniFi Management Dashboard — new CLI version
# Заменяет _legacy/dashboard.sh

UNIFI_MGR="${UNIFI_MGR:-/opt/unifi-mgr/bin/unifi-mgr}"
LOG_DIR="${LOG_DIR:-/var/log/unifi-mgr}"

function check_status() {
    if [ -x "$UNIFI_MGR" ]; then
        VERSION=$("$UNIFI_MGR" --version 2>/dev/null | awk '{print $2}')
        echo "unifi-mgr $VERSION | logs: $LOG_DIR"
    else
        echo "unifi-mgr NOT FOUND at $UNIFI_MGR — set UNIFI_MGR env var"
    fi
}

while true; do
    STATUS=$(check_status)
    CHOICE=$(whiptail --title "UniFi Network Dashboard" \
        --backtitle "$STATUS" \
        --menu "\nВыберите действие:" 20 70 12 \
        "1" "Быстрая проверка критических проблем (audit critical)" \
        "2" "Полный аудит (audit full)" \
        "3" "Анализ трендов (audit trends)" \
        "4" "MAC analysis (audit light)" \
        "5" "Авто-рестарт (restart auto --dry-run)" \
        "6" "Профиль рестарта restaurant (DRY-RUN by default)" \
        "7" "Логи (less /var/log/unifi-mgr/unifi-mgr.log)" \
        "8" "Экспорт клиентов в CSV" \
        "9" "Настройки (config show)" \
        "10" "Валидация config" \
        "0" "Выход" 3>&1 1>&2 2>&3)

    exitstatus=$?
    if [ $exitstatus != 0 ]; then
        clear
        echo "Выход..."
        break
    fi

    clear
    case $CHOICE in
        1) "$UNIFI_MGR" audit critical; read -p "Enter to continue..." ;;
        2) "$UNIFI_MGR" audit full; read -p "Enter to continue..." ;;
        3) "$UNIFI_MGR" audit trends; read -p "Enter to continue..." ;;
        4) "$UNIFI_MGR" audit light; read -p "Enter to continue..." ;;
        5) "$UNIFI_MGR" restart auto --dry-run; read -p "Enter to continue..." ;;
        6) "$UNIFI_MGR" restart profile restaurant; read -p "Enter to continue..." ;;
        7)
            if [ -f "$LOG_DIR/unifi-mgr.log" ]; then
                less "$LOG_DIR/unifi-mgr.log"
            else
                echo "Лог не найден: $LOG_DIR/unifi-mgr.log"
                read -p "Enter to continue..."
            fi
            ;;
        8) "$UNIFI_MGR" export clients --format csv --out /tmp/unifi-clients.csv && \
           echo "Сохранено в /tmp/unifi-clients.csv"; read -p "Enter to continue..." ;;
        9) "$UNIFI_MGR" config show; read -p "Enter to continue..." ;;
        10) "$UNIFI_MGR" config validate; read -p "Enter to continue..." ;;
        0) break ;;
    esac
done

clear
echo "Сеанс завершён."
