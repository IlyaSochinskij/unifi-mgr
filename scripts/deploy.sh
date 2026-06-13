#!/bin/bash
# Deploy a new unifi-mgr release.
# Запускается с sudo. Argument: wheel file (e.g. unifi_mgr-0.1.7-py3-none-any.whl).
#
# Usage:
#   sudo bash scripts/deploy.sh /path/to/unifi_mgr-0.1.7-py3-none-any.whl
#
# Эффект (least-privilege: всё дерево релиза root-owned, runtime user — read/exec):
#   - Создаёт /opt/unifi-mgr/releases/<DATE>-<VERSION>/.venv (root:root)
#   - Устанавливает wheel в этот venv (от root)
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

# constraints.txt пинит версии runtime-зависимостей (D1/DP1). Лежит рядом с wheel
# в бандле (git archive включает его автоматически). Если нет — деплой не падает,
# но предупреждает (deps резолвятся из PyPI floor-only).
WHEEL_DIR="$(cd "$(dirname "$WHEEL")" && pwd)"
CONSTRAINTS="${WHEEL_DIR}/constraints.txt"

USER_NAME="unifi-mgr"
RELEASE_ID="$(date +%Y-%m-%d)-$(basename "$WHEEL" | grep -oP '\d+\.\d+\.\d+' | head -1)"
RELEASE_DIR="/opt/unifi-mgr/releases/${RELEASE_ID}"

if [ -d "$RELEASE_DIR" ]; then
    echo "==> Release dir already exists, appending suffix"
    RELEASE_ID="${RELEASE_ID}-$(date +%H%M%S)"
    RELEASE_DIR="/opt/unifi-mgr/releases/${RELEASE_ID}"
fi

echo "==> Creating release at ${RELEASE_DIR} (root-owned)..."
install -d -m 755 -o root -g root "$RELEASE_DIR"

echo "==> Creating virtualenv (Python 3.12, root-owned)..."
python3.12 -m venv "${RELEASE_DIR}/.venv"

echo "==> Staging wheel into release dir..."
STAGED_WHEEL="${RELEASE_DIR}/$(basename "$WHEEL")"
install -m 0644 -o root -g root "$WHEEL" "$STAGED_WHEEL"

echo "==> Installing wheel (as root, into root-owned venv)..."
"${RELEASE_DIR}/.venv/bin/pip" install --upgrade pip
if [ -f "$CONSTRAINTS" ]; then
    echo "    using pinned constraints: $CONSTRAINTS"
    "${RELEASE_DIR}/.venv/bin/pip" install -c "$CONSTRAINTS" "$STAGED_WHEEL"
else
    echo "    WARNING: constraints.txt not found — deps resolved unpinned from PyPI"
    "${RELEASE_DIR}/.venv/bin/pip" install "$STAGED_WHEEL"
fi

echo "==> Atomic symlink switch..."
ln -sfn "$RELEASE_DIR" /opt/unifi-mgr/current.new
mv -Tf /opt/unifi-mgr/current.new /opt/unifi-mgr/current

ln -sfn /opt/unifi-mgr/current/.venv/bin/unifi-mgr /opt/unifi-mgr/bin/unifi-mgr

echo "==> Verify version (as ${USER_NAME} — proves the runtime user can execute it)..."
sudo -u "$USER_NAME" /opt/unifi-mgr/bin/unifi-mgr --version

echo "==> Deployed: $RELEASE_ID"
echo "==> To rollback: ln -sfn /opt/unifi-mgr/releases/<previous> /opt/unifi-mgr/current"
