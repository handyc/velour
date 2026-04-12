#!/bin/bash
# Velour WSL auto-start — source this from ~/.bashrc.
#
# Starts supervisord (user-mode) if it's not already running.
# Only acts on interactive shells so scripts/cron/background jobs
# don't trigger it. Idempotent — safe to source multiple times.
#
# Add to the END of ~/.bashrc:
#   source /home/handyc/claubsh/velour-dev/deploy/velour-wsl-autostart.sh

VELOUR_SUPERVISOR_CONF="/home/handyc/claubsh/velour-dev/deploy/supervisord-wsl.ini"
VELOUR_SUPERVISOR_PID="/tmp/velour_supervisord.pid"

# Only run in interactive shells.
[[ $- != *i* ]] && return

# Only run if supervisord is installed.
command -v supervisord &>/dev/null || return

# Check if supervisord is already running.
if [ -f "$VELOUR_SUPERVISOR_PID" ]; then
    pid=$(cat "$VELOUR_SUPERVISOR_PID" 2>/dev/null)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        # Already running — nothing to do.
        return
    fi
    # Stale pidfile from a crash/freeze — clean it up.
    rm -f "$VELOUR_SUPERVISOR_PID"
fi

# Start supervisord in user mode.
echo "[velour] Starting Velour services via supervisor..."
supervisord -c "$VELOUR_SUPERVISOR_CONF"
echo "[velour] Velour is up. Use 'supervisorctl -c $VELOUR_SUPERVISOR_CONF status' to check."
