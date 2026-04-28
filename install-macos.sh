#!/bin/bash
# install-macos.sh — first-time install for Velour on macOS.
#
# Single-user dev install. Unlike Linux where adminsetup.sh creates a
# project user and lays out /var/www/webapps/<user>/, on macOS the
# operator's own account owns everything and the app lives next to its
# code in $APP_HOME.
#
# Run from the project root after a fresh git clone:
#
#   bash install-macos.sh                # interactive, no auto-start
#   bash install-macos.sh --launchd      # also writes a LaunchAgent so
#                                        # Velour starts at login
#
# Idempotent. Re-run after pulling new code to update deps + run
# migrations; brew steps short-circuit if the package is already
# installed.

set -e

APP_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_HOME"

WANT_LAUNCHD=0
for arg in "$@"; do
    case "$arg" in
        --launchd) WANT_LAUNCHD=1 ;;
    esac
done

echo "=========================================="
echo "  Velour — install-macos.sh"
echo "  Home: $APP_HOME"
echo "  User: $(whoami)"
echo "=========================================="

# [1/6] Xcode Command Line Tools — needed for cryptography/cffi/etc.
if ! xcode-select -p >/dev/null 2>&1; then
    echo "[1/6] Xcode Command Line Tools missing. Triggering install..."
    xcode-select --install || true
    echo ""
    echo "    A GUI installer should appear. Re-run install-macos.sh"
    echo "    once it finishes."
    exit 1
fi
echo "[1/6] Xcode CLT present."

# [2/6] Homebrew — required for system deps.
if ! command -v brew >/dev/null 2>&1; then
    echo "[2/6] Homebrew not found. Install from https://brew.sh first, then re-run."
    exit 1
fi
# Brew prefix differs between Apple Silicon (/opt/homebrew) and Intel (/usr/local).
BREW_PREFIX="$(brew --prefix)"
echo "[2/6] Homebrew at $BREW_PREFIX."

# [3/6] system deps via brew. Each `brew install` is a no-op when already
# installed, so re-running is cheap.
echo "[3/6] Installing system dependencies via brew..."
BREW_PACKAGES=(
    python@3.12         # interpreter for the venv
    sqlite              # the project DB
    git                 # in case the user installed via download
    espeak-ng           # Lingua TTS fallback
)
for pkg in "${BREW_PACKAGES[@]}"; do
    if brew list --versions "$pkg" >/dev/null 2>&1; then
        echo "  OK   $pkg (already installed)"
    else
        echo "  → installing $pkg..."
        brew install "$pkg"
    fi
done

# [4/6] virtualenv with brew's python (NOT system Python — system Python
# on macOS is locked-down + ages-old).
PYTHON_BIN="$BREW_PREFIX/bin/python3.12"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(brew --prefix python@3.12)/bin/python3.12"
fi
if [ ! -d venv ]; then
    echo "[4/6] Creating virtualenv with $PYTHON_BIN..."
    "$PYTHON_BIN" -m venv venv
else
    echo "[4/6] venv already exists — skipping creation."
fi
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip setuptools wheel >/dev/null

# [5/6] Python deps. Plain pip install -r; if pinned versions don't have
# wheels for arm64, retry per-package without the version pin so the
# operator at least gets a working install.
echo "[5/6] Installing Python dependencies..."
if [ -f requirements.txt ]; then
    if pip install -r requirements.txt >/dev/null 2>&1; then
        echo "  All pinned versions installed."
    else
        echo "  Some pins failed. Retrying per-package..."
        while IFS= read -r line || [ -n "$line" ]; do
            cleaned="$(printf '%s' "$line" | sed -E 's/#.*$//; s/^[[:space:]]+//; s/[[:space:]]+$//')"
            [ -z "$cleaned" ] && continue
            case "$cleaned" in -*) continue ;; esac
            if pip install "$cleaned" >/dev/null 2>&1; then
                echo "  OK   $cleaned"
            else
                pkg="$(printf '%s' "$cleaned" | sed -E 's/[[:space:]]*[<>=!~].*$//')"
                if pip install "$pkg" >/dev/null 2>&1; then
                    echo "  OK   $pkg (fallback from $cleaned)"
                else
                    echo "  WARN could not install $cleaned"
                fi
            fi
        done < requirements.txt
    fi
fi
# Generate SECRET_KEY if the file isn't there yet.
SECRET_FILE="$APP_HOME/secret_key.txt"
if [ ! -s "$SECRET_FILE" ]; then
    python - <<'PY' > "$SECRET_FILE"
import secrets, string
alphabet = string.ascii_letters + string.digits + "!@#%^&*(-_=+)"
print(''.join(secrets.choice(alphabet) for _ in range(64)))
PY
    chmod 600 "$SECRET_FILE"
    echo "  → generated secret_key.txt"
fi

# [6/6] DB setup. makemigrations is intentional so a fresh clone whose
# tree is missing a generated migration self-heals.
echo "[6/6] Migrate + seed_defaults..."
python manage.py makemigrations --noinput
python manage.py migrate --noinput
python manage.py seed_defaults || true   # tolerated: not every clone has data
# If the clone was customized through /apps/create/, apply the bake-in.
if [ -f clone_init.json ]; then
    python manage.py apply_clone_init || true
fi

# Optional: write a LaunchAgent so Velour auto-starts at login.
if [ "$WANT_LAUNCHD" = "1" ]; then
    PLIST_DIR="$HOME/Library/LaunchAgents"
    PLIST_PATH="$PLIST_DIR/com.velour.dev.plist"
    mkdir -p "$PLIST_DIR"
    cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>          <string>com.velour.dev</string>
    <key>ProgramArguments</key>
    <array>
        <string>$APP_HOME/venv/bin/python</string>
        <string>$APP_HOME/manage.py</string>
        <string>runserver</string>
        <string>0.0.0.0:7777</string>
    </array>
    <key>WorkingDirectory</key><string>$APP_HOME</string>
    <key>RunAtLoad</key>      <true/>
    <key>KeepAlive</key>      <true/>
    <key>StandardOutPath</key><string>/tmp/velour_runserver.log</string>
    <key>StandardErrorPath</key><string>/tmp/velour_runserver.log</string>
</dict>
</plist>
EOF
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    launchctl load "$PLIST_PATH"
    echo "  → LaunchAgent loaded: $PLIST_PATH"
    echo "    To stop: launchctl unload $PLIST_PATH"
fi

echo ""
echo "=========================================="
echo "  Install complete."
echo "  Start the dev server:"
echo "    venv/bin/python manage.py runserver 0.0.0.0:7777"
echo "  Then open http://127.0.0.1:7777/ in your browser."
echo "=========================================="
