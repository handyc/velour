#!/bin/bash
# adminsetup.sh — privileged provisioning for Velour
#
# Run this ONCE after uploading the app source to a staging directory.
# Must be run as a regular sudoer account (not root directly). It will:
#
#   1. Install system packages (python3-venv, nginx, supervisor, rsync).
#   2. Create the project user (velour) if missing, lock down $HOME.
#   3. Create /var/www/webapps/velour/{run,static,log} with correct
#      ownership.
#   4. Rsync the staging tree into /home/velour/ and chown it.
#   5. Symlink deploy/nginx.conf and deploy/supervisor.conf into /etc.
#   6. Validate + reload nginx.
#   7. Invoke setup.sh as the project user (venv, pip, secret, migrate,
#      collectstatic).
#   8. Reread supervisor and start the app.
#
# Idempotent: re-running it on a provisioned server is safe — it will just
# re-sync files and restart the service.

set -e

STAGING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_USER="velour"
PROJECT_NAME="velour"
APP_HOME="/home/${DEPLOY_USER}"
VAR_DIR="/var/www/webapps/${DEPLOY_USER}"

echo "=========================================="
echo "  Velour — adminsetup.sh"
echo "  Staging: $STAGING_DIR"
echo "  Target : $APP_HOME"
echo "  Var    : $VAR_DIR"
echo "=========================================="

if [ "$(id -u)" = "0" ]; then
    echo "ERROR: run adminsetup.sh as a regular sudoer, not as root directly." >&2
    exit 1
fi

if ! sudo -n true 2>/dev/null; then
    echo "This script will use sudo; you may be prompted for your password."
fi

# [1/8] system packages
echo ""
echo "[1/8] Installing system packages..."
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3-venv python3-pip rsync nginx supervisor

# [2/8] project user
echo ""
if id "$DEPLOY_USER" >/dev/null 2>&1; then
    echo "[2/8] User $DEPLOY_USER already exists — skipping useradd."
else
    echo "[2/8] Creating user $DEPLOY_USER..."
    sudo useradd -m -s /bin/bash "$DEPLOY_USER"
fi
sudo chmod 700 "$APP_HOME"
sudo chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_HOME"

# [3/8] /var/www tree
echo ""
echo "[3/8] Creating $VAR_DIR/{run,static,log,apps} + host-wide maintenance page..."
# apps/ is where the velour app factory writes newly generated projects. It
# sits alongside run/static/log and is owned by the project user so velour
# can create subdirectories there without needing root.
sudo mkdir -p "$VAR_DIR/run" "$VAR_DIR/static" "$VAR_DIR/log" "$VAR_DIR/apps"
sudo chown -R "$DEPLOY_USER:$DEPLOY_USER" "$VAR_DIR"
sudo chmod 755 "$VAR_DIR"

# Host-wide maintenance page: nginx falls back to this when the upstream
# gunicorn socket is unreachable (app stopped, supervisor stopped, etc.).
# Shared across every app on this host, owned by root, readable by nginx.
# Only writes a default index.html if the file doesn't already exist, so
# a hand-edited maintenance page survives subsequent adminsetup.sh runs.
MAINTENANCE_DIR="/var/www/maintenance"
if [ ! -d "$MAINTENANCE_DIR" ]; then
    echo "  Creating $MAINTENANCE_DIR..."
    sudo mkdir -p "$MAINTENANCE_DIR"
    sudo chmod 755 "$MAINTENANCE_DIR"
fi
if [ ! -s "$MAINTENANCE_DIR/index.html" ]; then
    echo "  Writing default $MAINTENANCE_DIR/index.html..."
    sudo tee "$MAINTENANCE_DIR/index.html" >/dev/null <<'MAINTENANCE_HTML'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Service Unavailable</title>
    <style>
        html, body { height: 100%; margin: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #0d1117;
            color: #c9d1d9;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .card {
            max-width: 480px;
            padding: 2.5rem 3rem;
            text-align: center;
        }
        h1 { font-size: 1.75rem; margin: 0 0 0.75rem; color: #58a6ff; font-weight: 600; }
        p  { font-size: 0.95rem; line-height: 1.5; color: #8b949e; margin: 0.5rem 0; }
        .small { margin-top: 1.5rem; font-size: 0.8rem; color: #6e7681; }
    </style>
</head>
<body>
    <div class="card">
        <h1>Service temporarily unavailable</h1>
        <p>The application you're trying to reach isn't running right now.</p>
        <p>Please try again shortly.</p>
        <p class="small">If you're the operator, check supervisor status on the host.</p>
    </div>
</body>
</html>
MAINTENANCE_HTML
    sudo chmod 644 "$MAINTENANCE_DIR/index.html"
fi

# [4/8] sync source into $APP_HOME
# Excludes cover: generated caches (venv, __pycache__, *.pyc, staticfiles),
# the primary SQLite DB and its WAL/SHM/journal sidecars that would vanish
# mid-rsync if anything was touching the DB, and common editor swap files.
#
# rsync exit 24 ("some files vanished before they could be transferred") is
# downgraded to a warning here: any file we failed to grab because it
# disappeared is, by definition, a transient file we didn't want anyway.
# All other non-zero exits still abort the script.
echo ""
echo "[4/8] Syncing source from staging to $APP_HOME..."
set +e
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
    echo "  (rsync reported vanished files — ignored; likely transient cache/DB sidecars)"
fi
sudo chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_HOME"

# [5/8] nginx + supervisor config symlinks (validate only, no reload yet)
echo ""
echo "[5/8] Linking nginx + supervisor configs..."
sudo ln -sfn "$APP_HOME/deploy/nginx.conf" "/etc/nginx/sites-enabled/${DEPLOY_USER}"
sudo ln -sfn "$APP_HOME/deploy/supervisor.conf" "/etc/supervisor/conf.d/${DEPLOY_USER}.conf"
echo "  Validating nginx config..."
sudo nginx -t

# [6/8] hand off to setup.sh as the project user — this is where venv, pip,
# secret_key.txt, migrate, and collectstatic happen. collectstatic is the
# last step inside setup.sh, so by the time control returns here, every
# file the app needs is on disk in the right place.
echo ""
echo "[6/8] Running setup.sh as $DEPLOY_USER..."
sudo -u "$DEPLOY_USER" -H bash "$APP_HOME/setup.sh"

# [7/8] reload nginx now that /var/www/webapps/$DEPLOY_USER/static/ is populated
echo ""
echo "[7/8] Reloading nginx..."
sudo systemctl reload nginx

# [8/8] reload supervisor and (re)start the app — this is the step that
# actually brings the app online.
echo ""
echo "[8/8] Reloading supervisor and starting $DEPLOY_USER..."
sudo supervisorctl reread
sudo supervisorctl update
if sudo supervisorctl status "$DEPLOY_USER" >/dev/null 2>&1; then
    sudo supervisorctl restart "$DEPLOY_USER"
else
    sudo supervisorctl start "$DEPLOY_USER"
fi

echo ""
echo "=========================================="
echo "  Provisioning complete for $PROJECT_NAME."
echo "=========================================="
