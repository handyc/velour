#!/bin/bash
# Diagnose WSL2 mirrored-networking port reachability.
#
# Background: Velour's `.wslconfig` sets `networkingMode=mirrored`, which
# makes WSL share the Windows host's network stack. In that mode, the
# Hyper-V firewall sits in the path even for WSL-internal 127.0.0.1
# traffic, with a `DefaultInboundAction=Block` policy. Ports that need
# to accept connections must be explicitly listed in a
# `New-NetFirewallHyperVRule` entry.
#
# This script tests reachability of a given port from three angles:
#   1. WSL-internal via IPv4 loopback (127.0.0.1:<port>)
#   2. WSL-internal via the eth0 LAN IP
#   3. From Windows host via `localhost:<port>` (PowerShell)
#
# Any time-out on path 1 means the Hyper-V firewall is dropping the
# packet. A "Connection refused" means nothing is listening, which
# means the bind failed. HTTP 200 means the port is fully open.
#
# Usage:
#   ./deploy/diagnose_wsl_ports.sh              # default: 7777-7781
#   ./deploy/diagnose_wsl_ports.sh 7778 7800 8000
set -u

PORTS=( "${@:-7777 7778 7779 7780 7781}" )
WSL_IP=$(hostname -I | awk '{print $1}')

printf '%-6s %-12s %-14s %-14s %s\n' port wsl_127 "wsl_${WSL_IP}" win_localhost note
printf '%-6s %-12s %-14s %-14s %s\n' ---- -------- ---------- ---------- ----

for PORT in ${PORTS[@]}; do
    # If something's already on the port, don't clobber it.
    if ss -tln 2>/dev/null | grep -qE ":$PORT\s"; then
        note="already-bound(probe)"
        RESULT_LOOP=$(curl -s --max-time 3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/" 2>/dev/null)
        RESULT_IP=$(curl -s --max-time 3 -o /dev/null -w '%{http_code}' "http://$WSL_IP:$PORT/" 2>/dev/null)
    else
        note="test-server"
        python3 -m http.server "$PORT" --bind 0.0.0.0 >/tmp/diag_$PORT.log 2>&1 &
        SRV=$!
        sleep 0.6
        if ! kill -0 "$SRV" 2>/dev/null; then
            RESULT_LOOP="bind-fail"
            RESULT_IP="bind-fail"
        else
            RESULT_LOOP=$(curl -s --max-time 3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/" 2>/dev/null)
            RESULT_IP=$(curl -s --max-time 3 -o /dev/null -w '%{http_code}' "http://$WSL_IP:$PORT/" 2>/dev/null)
            kill "$SRV" 2>/dev/null
            wait "$SRV" 2>/dev/null
        fi
    fi

    # Windows-side reach test
    RESULT_WIN=$(powershell.exe -NoProfile -Command \
        "try { (Invoke-WebRequest -Uri 'http://localhost:$PORT/' -UseBasicParsing -TimeoutSec 3).StatusCode } catch { 'timeout' }" \
        2>/dev/null | tr -d '\r\n ')
    [ -z "$RESULT_WIN" ] && RESULT_WIN=noreply

    # Decorate: a 000 curl code becomes "blocked"
    [ "$RESULT_LOOP" = "000" ] && RESULT_LOOP=blocked
    [ "$RESULT_IP" = "000" ] && RESULT_IP=blocked
    [ "$RESULT_WIN" = "timeout" ] && RESULT_WIN=blocked

    printf '%-6s %-12s %-14s %-14s %s\n' "$PORT" "$RESULT_LOOP" "$RESULT_IP" "$RESULT_WIN" "$note"
done

cat <<'EOF'

─── legend ──────────────────────────────────────────────────────────
  200        reachable — Django/http.server returned OK
  blocked    TCP timeout — Hyper-V firewall dropped the SYN
  bind-fail  port was already held by another process
  noreply    PowerShell returned nothing (check powershell.exe access)

If every non-7777 port shows "blocked", the Hyper-V firewall rule
"Velour Dev" exists but isn't actually enforcing its listed ports.
Recreate it from an ELEVATED PowerShell window:

  Remove-NetFirewallHyperVRule -DisplayName 'Velour Dev' -ErrorAction Ignore
  New-NetFirewallHyperVRule -DisplayName 'Velour Dev' `
      -Direction Inbound -Action Allow -VMCreatorId 'Any' `
      -Protocol TCP -LocalPorts 7777,7778,7779,7780,7781,8000,8080,8888

Then `wsl --shutdown` from PowerShell and reopen your WSL terminal.
EOF
