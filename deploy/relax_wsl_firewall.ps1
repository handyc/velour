# Relax Velour's WSL Hyper-V firewall -- DefaultInboundAction = Allow.
#
# Why this exists: on current WSL builds with networkingMode=mirrored,
# per-port Hyper-V firewall rules are INERT for listeners that bind
# dynamically after VM boot -- only listeners present at WSL boot
# (e.g. supervisor-started Velour on 7777) are actually reachable.
# This was verified 2026-04-24:
#
#   * 7777 (bound by supervisor at WSL boot)  -> reachable
#   * 7778, 8080 (fresh http.server listeners)  -> blocked, identical
#     result to port 7782 which had NO firewall rule at all
#
# So the per-port rules from rebuild_wsl_firewall.ps1 don't actually
# help ad-hoc dev servers. For a dev box the simplest fix is to flip
# the WSL VM's Hyper-V firewall default action from Block to Allow,
# which matches the trust level you already place in your own WSL VM.
#
# This script:
#   1. Re-enables the Defender 'Velour Dev' rule (rollback of the
#      test_shadow_hypothesis.ps1 mid-test state).
#   2. Sets DefaultInboundAction = Allow for the WSL VM's Hyper-V
#      firewall.
#   3. Prints the resulting state.
#
# The per-port "Velour Dev :<port>" rules are left in place -- harmless
# and self-documenting. If you ever want to tighten back up, flip
# DefaultInboundAction back to Block.
#
# Usage (elevated PowerShell):
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File relax_wsl_firewall.ps1
#
# No wsl --shutdown is required -- VM-setting changes apply live.

#Requires -RunAsAdministrator

$WslCreatorId = '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'

Write-Host "Before:" -ForegroundColor Cyan
Get-NetFirewallRule -DisplayName 'Velour Dev' |
    Format-Table DisplayName, Enabled, Direction, Action -AutoSize
Get-NetFirewallHyperVVMSetting -Name $WslCreatorId -PolicyStore ActiveStore |
    Format-Table Name, DefaultInboundAction, DefaultOutboundAction, LoopbackEnabled -AutoSize

Write-Host "Re-enabling Defender 'Velour Dev' rule..." -ForegroundColor Yellow
Enable-NetFirewallRule -DisplayName 'Velour Dev'

Write-Host "Setting WSL VM DefaultInboundAction = Allow..." -ForegroundColor Yellow
Set-NetFirewallHyperVVMSetting -Name $WslCreatorId -DefaultInboundAction Allow

Start-Sleep -Seconds 1

Write-Host ""
Write-Host "After:" -ForegroundColor Cyan
Get-NetFirewallRule -DisplayName 'Velour Dev' |
    Format-Table DisplayName, Enabled, Direction, Action -AutoSize
Get-NetFirewallHyperVVMSetting -Name $WslCreatorId -PolicyStore ActiveStore |
    Format-Table Name, DefaultInboundAction, DefaultOutboundAction, LoopbackEnabled -AutoSize

Write-Host ""
Write-Host "Now, from your WSL terminal, run:" -ForegroundColor Green
Write-Host "  bash deploy/diagnose_wsl_ports.sh" -ForegroundColor Green
Write-Host ""
Write-Host "To tighten back up later (elevated):" -ForegroundColor Yellow
Write-Host "  Set-NetFirewallHyperVVMSetting -Name '$WslCreatorId' -DefaultInboundAction Block" -ForegroundColor Yellow
Write-Host ""
Write-Host "Press any key to close..."
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
