# Rebuild Velour's WSL port-opening stack with ONE rule per port.
#
# Why this exists, separate from fix_wsl_firewall.ps1:
#
# fix_wsl_firewall.ps1 creates a single Hyper-V firewall rule whose
# LocalPorts list holds every Velour port. On current Windows builds
# that rule frequently enforces only the FIRST port in the list -- so
# 7777 is reachable but 7778-8888 silently drop SYNs even though the
# rule is Enabled and lists them. The "Known quirk" comment in
# fix_wsl_firewall.ps1 documents this; in practice re-running that
# script does not always restore enforcement for the trailing ports.
#
# This script avoids the quirk by giving each port its own Hyper-V
# firewall rule, named "Velour Dev :<port>". With a single LocalPort
# per rule, there is no "first wins" ambiguity to trip over.
#
# Other layers stay one-rule-fits-all because they don't have the bug:
#   * netsh portproxy        -- per-port entries (already)
#   * Defender NetFirewall   -- one rule, all ports (works fine)
#
# Usage (elevated PowerShell):
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File rebuild_wsl_firewall.ps1
#
# After running: `wsl --shutdown` from a non-elevated PowerShell so the
# Hyper-V firewall rule cache refreshes on next WSL boot.

#Requires -RunAsAdministrator

$Ports = @(7777, 7778, 7779, 7780, 7781, 8000, 8080, 8888)
$WslCreatorId = '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'

$WslIp = (& wsl.exe hostname -I).Trim().Split(' ')[0]
if (-not $WslIp) {
    Write-Host "Could not determine WSL IP -- aborting." -ForegroundColor Red
    exit 1
}
Write-Host "Discovered WSL IP: $WslIp" -ForegroundColor Cyan

# --- 1. netsh portproxy -----------------------------------------------
Write-Host ""
Write-Host "[1/3] Refreshing netsh portproxy entries..." -ForegroundColor Cyan
foreach ($p in $Ports) {
    & netsh interface portproxy delete v4tov4 listenport=$p listenaddress=0.0.0.0 2>$null | Out-Null
    & netsh interface portproxy add v4tov4 listenport=$p listenaddress=0.0.0.0 connectport=$p connectaddress=$WslIp | Out-Null
}
Write-Host "portproxy now shows:" -ForegroundColor Green
& netsh interface portproxy show all

# --- 2. Windows Defender Firewall rule (one, all ports) ---------------
Write-Host ""
Write-Host "[2/3] Updating Windows Defender Firewall rule 'Velour Dev'..." -ForegroundColor Cyan
Get-NetFirewallRule -DisplayName 'Velour Dev*' -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction SilentlyContinue
New-NetFirewallRule `
    -DisplayName 'Velour Dev' `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $Ports | Out-Null
Write-Host "Defender rule now covers: $($Ports -join ', ')" -ForegroundColor Green

# --- 3. Hyper-V firewall rules: one per port --------------------------
Write-Host ""
Write-Host "[3/3] Recreating Hyper-V firewall rules (one per port)..." -ForegroundColor Cyan

# Sweep ALL existing Velour-Dev-named Hyper-V rules, including the
# Any-scoped one that Defender auto-mirrors and the legacy single
# multi-port rule from fix_wsl_firewall.ps1.
Get-NetFirewallHyperVRule -DisplayName 'Velour Dev*' -ErrorAction SilentlyContinue |
    ForEach-Object {
        try { Remove-NetFirewallHyperVRule -Name $_.Name -ErrorAction Stop }
        catch { Write-Host ("  could not remove " + $_.Name + ": " + $_.Exception.Message) -ForegroundColor Yellow }
    }

foreach ($p in $Ports) {
    New-NetFirewallHyperVRule `
        -DisplayName "Velour Dev :$p" `
        -Direction Inbound `
        -Action Allow `
        -VMCreatorId $WslCreatorId `
        -Protocol TCP `
        -LocalPorts $p | Out-Null
}
Write-Host "Created one Hyper-V rule per port: $($Ports -join ', ')" -ForegroundColor Green

# --- Verify -----------------------------------------------------------
Write-Host ""
Write-Host "Final Hyper-V rules:" -ForegroundColor Green
Get-NetFirewallHyperVRule -DisplayName 'Velour Dev*' |
    Sort-Object DisplayName |
    Format-Table DisplayName, Enabled, Action, Protocol, LocalPorts, VMCreatorId -AutoSize

Write-Host ""
Write-Host "Next step: run 'wsl --shutdown' from a non-elevated PowerShell," -ForegroundColor Yellow
Write-Host "then reopen your WSL terminal and run deploy/diagnose_wsl_ports.sh." -ForegroundColor Yellow
Write-Host ""
Write-Host "Press any key to close..."
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
