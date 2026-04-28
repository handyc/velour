#!/bin/bash
# hotswap.sh — in-place code update for an already-provisioned velour app.
#
# Unlike adminsetup.sh, this script does NOT create users, lay out
# /var/www/webapps/<user>/, install system packages, or re-wire nginx +
# supervisor. It assumes the target deployment is already provisioned and
# just:
#
#   1. Syncs new source into /home/<user>/ (preserving venv, db, secret_key.txt).
#   2. Hands off to setup.sh as the project user (pip, makemigrations, migrate,
#      collectstatic).
#   3. Restarts the supervisor program so gunicorn picks up the new code.
#
# Run this from a regular sudoer account on the target server, pointed at a
# staging directory containing the new source. The target deploy user
# defaults to "{{ deploy_user }}" (baked in at generation time) but can be
# overridden at runtime so a single hotswap.sh can update any pre-provisioned
# app on the host.
#
# Usage:
#   bash hotswap.sh                   # defaults to {{ deploy_user }}
#   bash hotswap.sh swibliq           # explicit target user
#   DEPLOY_USER=swibliq bash hotswap.sh

set -e

STAGING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_USER="${1:-${DEPLOY_USER:-{{ deploy_user }}}}"
APP_HOME="/home/${DEPLOY_USER}"

echo "=========================================="
echo "  {{ app_label }} — hotswap.sh"
echo "  Staging: $STAGING_DIR"
echo "  Target : $APP_HOME"
echo "  User   : $DEPLOY_USER"
echo "=========================================="

if [ "$(id -u)" = "0" ]; then
    echo "ERROR: run hotswap.sh as a regular sudoer, not as root directly." >&2
    exit 1
fi

if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
    echo "ERROR: user $DEPLOY_USER does not exist on this host." >&2
    echo "       Run adminsetup.sh for a first-time provision instead." >&2
    exit 1
fi

if [ ! -d "$APP_HOME" ]; then
    echo "ERROR: $APP_HOME does not exist. Is this app provisioned yet?" >&2
    echo "       Run adminsetup.sh for a first-time provision instead." >&2
    exit 1
fi

if ! sudo -n true 2>/dev/null; then
    echo "This script will use sudo; you may be prompted for your password."
fi

# [1/3] sync new source, preserving runtime state that belongs to the server
# (venv, SQLite DB + sidecars, generated secret, editor files) and local
# artifacts that should never leak to prod (.git, .claude, memory, .env*).
# rsync exit 24 (vanished files) is downgraded to a warning.
echo ""
echo "[1/3] Syncing new source into $APP_HOME..."
set +e
# CRITICAL: deploy/ is excluded. The server's /home/<user>/deploy/*.conf files
# have paths, program names, and server_name directives baked in for THIS
# deployment's user, and they are symlinked from /etc/{nginx,supervisor} so
# any changes to them are live. A hot swap uploads code generated against
# some OTHER user (usually the local dev's default), so overwriting the
# server's deploy configs would point supervisor at /home/<wrong-user>/ and
# spawn-fail the app. Regenerate those files with `manage.py generate_deploy`
# on the server if you need to update them; never hot-swap them.
#
# adminsetup.sh is excluded for the same reason: its baked-in user values
# don't match the target, and it should never be re-run for a hot swap.
sudo rsync -a --delete \
    --exclude='venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='staticfiles/' \
    --exclude='db.sqlite3' \
    --exclude='db.sqlite3-*' \
    --exclude='secret_key.txt' \
    --exclude='health_token.txt' \
    --exclude='mail_relay_token.txt' \
    --exclude='provisioning_secret.txt' \
    --exclude='*.token' \
    --exclude='llm_*.key' \
    --exclude='*_api_key.txt' \
    --exclude='deploy/' \
    --exclude='adminsetup.sh' \
    --exclude='.env' \
    --exclude='.env.*' \
    --exclude='.git/' \
    --exclude='.claude/' \
    --exclude='memory/' \
    --exclude='*.swp' \
    --exclude='.*.swo' \
    --exclude='.DS_Store' \
    "$STAGING_DIR/" "$APP_HOME/"
rsync_status=$?
set -e
if [ "$rsync_status" -ne 0 ] && [ "$rsync_status" -ne 24 ]; then
    echo "ERROR: rsync failed with exit code $rsync_status" >&2
    exit "$rsync_status"
fi
if [ "$rsync_status" -eq 24 ]; then
    echo "  (rsync reported vanished files — ignored; transient caches)"
fi
sudo chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_HOME"

# [2/3] setup.sh runs as the project user and handles everything code-level:
# pip install (idempotent), existing secret_key.txt kept, makemigrations,
# migrate, collectstatic → /var/www/webapps/<user>/static/.
echo ""
echo "[2/3] Running setup.sh as $DEPLOY_USER..."
sudo -u "$DEPLOY_USER" -H bash "$APP_HOME/setup.sh"

# [3/3] restart supervisor program so gunicorn re-execs with the new code.
# nginx config has not changed (same socket, same server_name), so no nginx
# reload is required.
echo ""
echo "[3/3] Restarting $DEPLOY_USER via supervisor..."
sudo supervisorctl restart "$DEPLOY_USER"

echo ""
echo "=========================================="
echo "  Hot swap complete for $DEPLOY_USER."
echo "=========================================="
