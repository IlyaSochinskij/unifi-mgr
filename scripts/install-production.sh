#!/bin/bash
# One-time production setup для unifi-mgr.
# Запускается с sudo на production server.
#
# Usage:
#   sudo bash scripts/install-production.sh
#
# Создаёт (least-privilege: root владеет кодом, сервисный user — только рантайм):
#   - User/group unifi-mgr (system account)
#   - /opt/unifi-mgr/{,releases,bin} (755 root:root — install/upgrade = root)
#   - /etc/unifi-mgr/ (750 root:unifi-mgr — секреты 640 внутри)
#   - /var/log/unifi-mgr/ (750 unifi-mgr:unifi-mgr — runtime пишет логи)
#   - /var/lib/unifi-mgr/ (750 unifi-mgr:unifi-mgr — runtime state/lock/history)

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
# Code tree — root-owned. The runtime user must NOT be able to rewrite its own
# executable (venv/symlinks); 755 gives it read+exec only. install/upgrade = root.
install -d -m 755 -o root -g root /opt/unifi-mgr
install -d -m 755 -o root -g root /opt/unifi-mgr/releases
install -d -m 755 -o root -g root /opt/unifi-mgr/bin
# Config — root-owned, service group reads (secrets are 640 inside); 750 hides
# the listing from other users.
install -d -m 750 -o root -g "$GROUP_NAME" /etc/unifi-mgr
# Runtime-writable state — owned by the service user, no world access.
install -d -m 750 -o "$USER_NAME" -g "$GROUP_NAME" /var/log/unifi-mgr
install -d -m 750 -o "$USER_NAME" -g "$GROUP_NAME" /var/lib/unifi-mgr
# Re-runs / upgrades: reclaim any pre-existing contents for the service user.
# (e.g. a root-owned unifi-mgr.log left by an earlier root-run smoke test would
# otherwise block the service user from writing its own log.) Idempotent.
chown -R "$USER_NAME:$GROUP_NAME" /var/log/unifi-mgr /var/lib/unifi-mgr

echo "==> Setup complete. Next:"
echo "  1. install -m 640 -o root -g ${GROUP_NAME} config.yaml /etc/unifi-mgr/config.yaml"
echo "  2. install -m 640 -o root -g ${GROUP_NAME} .env        /etc/unifi-mgr/.env"
echo "     (640 root:${GROUP_NAME} — root owns, service user ${GROUP_NAME} reads; cron runs as ${GROUP_NAME})"
echo "  3. Run scripts/deploy.sh to install first release"
