#!/bin/bash
# Post-install acceptance gate for production deployment.
#
# Must run as root (via sudo): the whole point is to drop to the service user
# and prove the unifi-mgr *cron* runtime (not root) can read config/.env and
# write its state/log dirs. Checking as root would pass while cron still fails.
#
# Usage:
#   sudo bash scripts/verify-deployment.sh

set -uo pipefail

UNIFI_MGR="${UNIFI_MGR:-/opt/unifi-mgr/bin/unifi-mgr}"
CONFIG="${CONFIG:-/etc/unifi-mgr/config.yaml}"
USER_NAME="${USER_NAME:-unifi-mgr}"
RUN=(sudo -u "${USER_NAME}")

if [ "$EUID" -ne 0 ]; then
    echo "Error: run with sudo — runtime checks drop to ${USER_NAME} via 'sudo -u'"
    exit 1
fi

FAIL_COUNT=0

# check NAME CMD [ARGS...]
# Runs CMD with its args directly — no eval, no shell re-parsing of the command.
function check() {
    local name="$1"
    shift
    echo -n "  [${name}] ... "
    if "$@" >/dev/null 2>&1; then
        echo "OK"
    else
        echo "FAIL"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

echo "==> Production deployment verification (runtime user: ${USER_NAME})"
echo

check "Binary present & executable"                   test -x "$UNIFI_MGR"
check "Binary runs as ${USER_NAME}"                   "${RUN[@]}" "$UNIFI_MGR" --version
check "Config readable by ${USER_NAME}"               "${RUN[@]}" test -r "$CONFIG"
check ".env readable by ${USER_NAME}"                 "${RUN[@]}" test -r /etc/unifi-mgr/.env
check "/var/log/unifi-mgr writable by ${USER_NAME}"   "${RUN[@]}" test -w /var/log/unifi-mgr
check "/var/lib/unifi-mgr writable by ${USER_NAME}"   "${RUN[@]}" test -w /var/lib/unifi-mgr
check "Config validates (strict)"                     "${RUN[@]}" "$UNIFI_MGR" --config "$CONFIG" config validate --strict
check "Login test"                                    "${RUN[@]}" "$UNIFI_MGR" --config "$CONFIG" login test

echo
if [ "$FAIL_COUNT" -eq 0 ]; then
    echo "==> All checks PASSED"
    exit 0
else
    echo "==> $FAIL_COUNT check(s) FAILED — fix before proceeding"
    exit 1
fi
