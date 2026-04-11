#!/bin/bash
# setup.sh — unprivileged setup for {{ app_label }}
#
# Runs as the project user ({{ deploy_user }}). No sudo, no system changes.
# Re-run this after pulling new code to update deps, run migrations, and
# refresh collected static files. Safe to run repeatedly.
#
# On a fresh provisioning, adminsetup.sh invokes this via `sudo -u {{ deploy_user }}`
# after creating the user, /var tree, and installing system packages.

set -e

APP_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_HOME"

echo "=========================================="
echo "  {{ app_label }} — setup.sh"
echo "  Home: $APP_HOME"
echo "  User: $(whoami)"
echo "=========================================="

# install_with_fallback: try a requirements.txt line verbatim (respects version
# pins), and if the pinned version is unavailable, retry with the package name
# alone so pip resolves to the closest version it CAN install. Lines that are
# pip directives (-r, -e, --index-url, …) are skipped. Returns non-zero only
# when even the unpinned fallback fails, so the caller can count warnings.
install_with_fallback() {
    local raw="$1"
    local line
    line="$(printf '%s' "$raw" | sed -E 's/#.*$//; s/^[[:space:]]+//; s/[[:space:]]+$//')"
    [ -z "$line" ] && return 0
    case "$line" in
        -*) return 0 ;;
    esac

    if pip install "$line" >/dev/null 2>&1; then
        echo "  OK   $line"
        return 0
    fi

    local pkg
    pkg="$(printf '%s' "$line" | sed -E 's/[[:space:]]*[<>=!~].*$//')"
    if [ -n "$pkg" ] && [ "$pkg" != "$line" ]; then
        if pip install "$pkg" >/dev/null 2>&1; then
            echo "  OK   $pkg (fallback from $line)"
            return 0
        fi
    fi

    echo "  WARN could not install $line"
    return 1
}

# [1/5] virtualenv
if [ ! -d venv ]; then
    echo "[1/5] Creating virtualenv..."
    python3 -m venv venv
else
    echo "[1/5] venv already exists — skipping creation."
fi
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip setuptools wheel >/dev/null

# [2/5] dependencies — fast path first, fall back to per-package with version fallback
echo "[2/5] Installing dependencies..."
if [ -f requirements.txt ]; then
    if pip install -r requirements.txt >/dev/null 2>&1; then
        echo "  All pinned versions installed successfully."
    else
        echo "  Some pinned versions failed. Installing per-package with fallback..."
        while IFS= read -r line || [ -n "$line" ]; do
            install_with_fallback "$line" || true
        done < requirements.txt
    fi
else
    echo "  No requirements.txt — skipping."
fi
# Gunicorn is required by supervisor/gunicorn.conf.py whether or not it is
# listed in requirements.txt; make sure it is present either way.
if ! pip show gunicorn >/dev/null 2>&1; then
    install_with_fallback "gunicorn" || true
fi

# [3/5] Django SECRET_KEY
SECRET_FILE="$APP_HOME/secret_key.txt"
if [ ! -s "$SECRET_FILE" ]; then
    echo "[3/5] Generating Django SECRET_KEY..."
    python - <<'PY' > "$SECRET_FILE"
import secrets, string
alphabet = string.ascii_letters + string.digits + "!@#%^&*(-_=+)"
print(''.join(secrets.choice(alphabet) for _ in range(64)))
PY
    chmod 600 "$SECRET_FILE"
else
    echo "[3/5] secret_key.txt already present — keeping existing key."
fi

# [4/5] migrations — regenerate any missing migration files first, then apply.
# makemigrations on deploy is intentional: it guarantees a self-contained
# provisioning even if the source tree is missing a generated migration.
echo "[4/5] Running makemigrations + migrate..."
python manage.py makemigrations --noinput
python manage.py migrate --noinput

# [5/5] static files — last step before adminsetup.sh brings the app online
echo "[5/5] Collecting static files..."
python manage.py collectstatic --noinput

echo ""
echo "Setup complete."
