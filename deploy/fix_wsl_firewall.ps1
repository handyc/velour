# Recreate the full "Velour Dev" port-opening stack on Windows.
#
# When we first set up Velour (NAT-bridge era), we opened 7777 end-to-end
# by layering THREE things on the Windows side:
#
#   1. netsh interface portproxy       -- Windows listens on 0.0.0.0:<port>
#                                        and forwards to the WSL IP
#   2. Windows Defender Firewall rule  -- inbound allow on <ports>
#   3. Hyper-V firewall rule           -- needed once we moved to mirrored
#                                        networking mode (VMCreatorId=WSL)
#
# Layers 1 and 2 were the original 7777 pattern. Layer 3 became
# necessary after we switched to mirrored mode (.wslconfig:
# networkingMode=mirrored), because in that mode Hyper-V firewall sits
# in the path even for WSL-internal 127.0.0.1 traffic with a default
# inbound Block policy. Layer 2 auto-mirrors into the Hyper-V firewall
# as a VMCreatorId=Any rule; layer 3 is an additional, WSL-scoped rule.
#
# This script normalizes all three layers for one consistent port list,
# so adding a new Velour port only requires editing $Ports below.
#
# Known quirk: Hyper-V firewall rules with multi-port LocalPorts
# occasionally enforce only the first port. Remove+recreate restores
# full enforcement. If symptoms recur, re-run this script.
#
# Usage (elevated PowerShell):
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File fix_wsl_firewall.ps1
#
# After running: `wsl --shutdown` from a non-elevated PowerShell so the
# Hyper-V firewall rule cache refreshes on next WSL boot.

#Requires -RunAsAdministrator

$Ports = @(7777, 7778, 7779, 7780, 7781, 8000, 8080, 8888)

# WSL's registered VMCreatorId. Do NOT use 'Any' here -- older rules may
# display VMCreatorId='Any' (Defender sync) but New-NetFirewallHyperVRule
# on current builds rejects that string with "Unable to parse the GUID".
$WslCreatorId = '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'

# Discover current WSL eth0 IP. In mirrored-networking mode this equals
# the Windows host's LAN IP, but we still honour the portproxy pattern
# from the original setup -- listen on 0.0.0.0, forward to the WSL-visible
# IP -- so the behaviour is symmetric across networking modes.
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

# --- 2. Windows Defender Firewall rule --------------------------------
Write-Host ""
Write-Host "[2/3] Updating Windows Defender Firewall rule 'Velour Dev'..." -ForegroundColor Cyan
Get-NetFirewallRule -DisplayName 'Velour Dev' -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction SilentlyContinue
New-NetFirewallRule `
    -DisplayName 'Velour Dev' `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $Ports | Out-Null
Write-Host "Defender rule now covers: $($Ports -join ', ')" -ForegroundColor Green

# --- 3. Hyper-V firewall rule -----------------------------------------
Write-Host ""
Write-Host "[3/3] Recreating Hyper-V firewall rule 'Velour Dev'..." -ForegroundColor Cyan
Get-NetFirewallHyperVRule -DisplayName 'Velour Dev' -ErrorAction SilentlyContinue |
    ForEach-Object {
        try { Remove-NetFirewallHyperVRule -Name $_.Name -ErrorAction Stop }
        catch { Write-Host ("  could not remove " + $_.Name + ": " + $_.Exception.Message) -ForegroundColor Yellow }
    }
New-NetFirewallHyperVRule `
    -DisplayName 'Velour Dev' `
    -Direction Inbound `
    -Action Allow `
    -VMCreatorId $WslCreatorId `
    -Protocol TCP `
    -LocalPorts $Ports | Out-Null
Write-Host "Hyper-V rule now covers: $($Ports -join ', ')" -ForegroundColor Green

# --- Verify -----------------------------------------------------------
Write-Host ""
Write-Host "Final state:" -ForegroundColor Green
Get-NetFirewallHyperVRule -DisplayName 'Velour Dev' |
    Format-List DisplayName, Enabled, Direction, Action, Protocol, LocalPorts, VMCreatorId

Write-Host ""
Write-Host "Next step: run 'wsl --shutdown' from a non-elevated PowerShell," -ForegroundColor Yellow
Write-Host "then reopen your WSL terminal and run deploy/diagnose_wsl_ports.sh." -ForegroundColor Yellow
Write-Host ""
Write-Host "Press any key to close..."
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
