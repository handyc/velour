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
#   3. From Windows host via `127.0.0.1:<port>` (PowerShell)
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

    # Windows-side reach test. We probe 127.0.0.1 (not "localhost") on
    # purpose: PowerShell resolves "localhost" to ::1 first, and our WSL
    # servers bind only to 0.0.0.0 — so a localhost probe times out even
    # though the firewall is wide open. 127.0.0.1 surfaces the real state.
    RESULT_WIN=$(powershell.exe -NoProfile -Command \
        "try { (Invoke-WebRequest -Uri 'http://127.0.0.1:$PORT/' -UseBasicParsing -TimeoutSec 3).StatusCode } catch { 'timeout' }" \
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

If every non-7777 port shows "blocked", check ufw FIRST:

    sudo ufw status
    sudo ufw allow <port>/tcp     # or 7778:7782/tcp for a range

ufw runs inside WSL, and mirrored-networking routes 127.0.0.1 through
netfilter too, so it can drop even "loopback" probes. We burned a
full session chasing Windows-side firewall theories (below) before
`sudo ufw allow 7778:7782/tcp` fixed every path in one command.

Only if ufw is off or the port is allowed should you touch the
Windows side. For LAN/external ingress you'll want the canonical
3-layer stack via `deploy/fix_wsl_firewall.ps1` from an ELEVATED
PowerShell, then `wsl --shutdown` to refresh the rule cache.

Manual equivalent (elevated PowerShell):
  Get-NetFirewallHyperVRule -DisplayName 'Velour Dev' |
      ForEach-Object { Remove-NetFirewallHyperVRule -Name $_.Name }
  New-NetFirewallHyperVRule -DisplayName 'Velour Dev' `
      -Direction Inbound -Action Allow `
      -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' `
      -Protocol TCP -LocalPorts 7777,7778,7779,7780,7781,8000,8080,8888

Note: -VMCreatorId 'Any' is rejected by New-NetFirewallHyperVRule
on current builds ("Unable to parse the GUID") even though older
rules display VMCreatorId='Any'. Use the WSL GUID above.
Then `wsl --shutdown` from PowerShell and reopen your WSL terminal.
EOF
