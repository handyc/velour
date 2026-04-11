"""Intrusion prevention audit — cross-platform (replaces fail2ban-only check)."""

import re

from security.platform import PlatformInfo, is_debian_family, is_rhel_family
from security.runner import run, run_powershell, command_exists


def check_intrusion_prevention(pinfo: PlatformInfo) -> list[dict]:
    if pinfo.os_family == 'linux':
        return _check_intrusion_linux(pinfo)
    elif pinfo.os_family == 'darwin':
        return _check_intrusion_macos(pinfo)
    elif pinfo.os_family == 'windows':
        return _check_intrusion_windows(pinfo)
    elif pinfo.os_family in ('freebsd', 'openbsd', 'netbsd'):
        return _check_intrusion_bsd(pinfo)
    return []


# ── Linux ───────────────────────────────────────────────────────────

def _check_intrusion_linux(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # fail2ban
    status = run(['fail2ban-client', 'status'])
    if status and 'number of jail' in status.lower():
        jails = re.search(r'Jail list:\s*(.+)', status)
        jail_list = jails.group(1).strip() if jails else 'unknown'
        findings.append({
            'name': 'Fail2ban: Active',
            'status': 'pass',
            'detail': f'Jails: {jail_list}',
            'severity': 'ok', 'fix': None,
        })

        # Check specific jail stats
        for jail_name in [j.strip() for j in jail_list.split(',')] if jail_list != 'unknown' else []:
            jail_status = run(['fail2ban-client', 'status', jail_name])
            if jail_status:
                banned = re.search(r'Currently banned:\s*(\d+)', jail_status)
                total = re.search(r'Total banned:\s*(\d+)', jail_status)
                if banned and total:
                    b, t = banned.group(1), total.group(1)
                    if int(b) > 0:
                        findings.append({
                            'name': f'Fail2ban Jail "{jail_name}"',
                            'status': 'info',
                            'detail': f'Currently banned: {b}, Total banned: {t}',
                            'severity': 'info', 'fix': None,
                        })
    elif command_exists('fail2ban-client'):
        findings.append({
            'name': 'Fail2ban: Installed but Not Running',
            'status': 'warn',
            'detail': 'Fail2ban is installed but does not appear active.',
            'severity': 'medium',
            'fix': 'sudo systemctl enable --now fail2ban',
        })
    else:
        pkg_cmd = 'sudo apt install fail2ban' if is_debian_family(pinfo) \
            else 'sudo dnf install fail2ban' if pinfo.pkg_manager == 'dnf' \
            else 'sudo yum install fail2ban' if pinfo.pkg_manager == 'yum' \
            else 'Install fail2ban for your distribution'
        findings.append({
            'name': 'Fail2ban: Not Installed',
            'status': 'fail',
            'detail': 'Fail2ban protects against brute-force attacks. Not installed.',
            'severity': 'medium',
            'fix': f'{pkg_cmd} && sudo systemctl enable --now fail2ban',
        })

    # CrowdSec
    if command_exists('cscli'):
        cs_metrics = run(['cscli', 'metrics'])
        if cs_metrics:
            findings.append({
                'name': 'CrowdSec: Active',
                'status': 'pass',
                'detail': 'CrowdSec intrusion detection is running.',
                'severity': 'ok', 'fix': None,
            })

    return findings


# ── macOS ───────────────────────────────────────────────────────────

def _check_intrusion_macos(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # Check XProtect (built-in malware detection)
    xprotect = run(['system_profiler', 'SPInstallHistoryDataType'])
    xp_version = ''
    if xprotect:
        # Look for XProtect updates
        lines = xprotect.splitlines()
        for i, line in enumerate(lines):
            if 'xprotect' in line.lower():
                xp_version = line.strip()
                break

    if xp_version:
        findings.append({
            'name': 'XProtect (Malware Detection)',
            'status': 'pass',
            'detail': f'XProtect is present: {xp_version}',
            'severity': 'ok', 'fix': None,
        })
    else:
        findings.append({
            'name': 'XProtect (Malware Detection)',
            'status': 'info',
            'detail': 'XProtect status could not be determined. It is typically active on all macOS systems.',
            'severity': 'info', 'fix': None,
        })

    # MRT (Malware Removal Tool)
    if run(['which', 'MRT']):
        findings.append({
            'name': 'Malware Removal Tool (MRT)',
            'status': 'pass',
            'detail': 'MRT is present.',
            'severity': 'ok', 'fix': None,
        })

    # Check if fail2ban is installed via Homebrew
    if command_exists('fail2ban-client'):
        status = run(['fail2ban-client', 'status'])
        if status and 'number of jail' in status.lower():
            findings.append({
                'name': 'Fail2ban: Active',
                'status': 'pass',
                'detail': 'Fail2ban is running.',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'Fail2ban: Installed but Not Running',
                'status': 'warn',
                'detail': 'Fail2ban is installed but not active.',
                'severity': 'low',
                'fix': 'brew services start fail2ban',
            })
    else:
        findings.append({
            'name': 'Brute-Force Protection',
            'status': 'info',
            'detail': 'No dedicated brute-force protection (fail2ban) installed. '
                      'macOS has built-in rate limiting for SSH via launchd.',
            'severity': 'low',
            'fix': 'Consider: brew install fail2ban',
        })

    return findings


# ── Windows ─────────────────────────────────────────────────────────

def _check_intrusion_windows(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # Windows Defender status
    defender = run_powershell(
        'Get-MpComputerStatus | Select-Object AntivirusEnabled, '
        'RealTimeProtectionEnabled, AntivirusSignatureLastUpdated | Format-List'
    )
    if defender:
        if 'true' in defender.lower():
            findings.append({
                'name': 'Windows Defender: Active',
                'status': 'pass',
                'detail': defender.strip(),
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'Windows Defender: Disabled',
                'status': 'fail',
                'detail': 'Windows Defender real-time protection is not active.',
                'severity': 'critical',
                'fix': 'Enable via: Set-MpPreference -DisableRealtimeMonitoring $false',
            })
    else:
        findings.append({
            'name': 'Windows Defender',
            'status': 'unknown',
            'detail': 'Could not query Windows Defender status.',
            'severity': 'info', 'fix': None,
        })

    # Account lockout policy
    net_accounts = run(['net', 'accounts'])
    if net_accounts:
        for line in net_accounts.splitlines():
            if 'lockout threshold' in line.lower():
                val = line.split(':')[-1].strip()
                if val.lower() == 'never' or val == '0':
                    findings.append({
                        'name': 'Account Lockout: Not Configured',
                        'status': 'warn',
                        'detail': 'No lockout threshold. Brute-force attacks are unlimited.',
                        'severity': 'medium',
                        'fix': 'net accounts /lockoutthreshold:5',
                    })
                else:
                    findings.append({
                        'name': f'Account Lockout Threshold: {val}',
                        'status': 'pass',
                        'detail': f'Lockout after {val} failed attempts.',
                        'severity': 'ok', 'fix': None,
                    })

    return findings


# ── BSD ─────────────────────────────────────────────────────────────

def _check_intrusion_bsd(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # Check for fail2ban or sshguard
    if command_exists('fail2ban-client'):
        status = run(['fail2ban-client', 'status'])
        if status and 'number of jail' in status.lower():
            findings.append({
                'name': 'Fail2ban: Active',
                'status': 'pass',
                'detail': 'Fail2ban is running.',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'Fail2ban: Not Running',
                'status': 'warn',
                'detail': 'Fail2ban is installed but not active.',
                'severity': 'medium', 'fix': None,
            })
    elif command_exists('sshguard'):
        findings.append({
            'name': 'SSHGuard: Installed',
            'status': 'pass',
            'detail': 'SSHGuard brute-force protection is available.',
            'severity': 'ok', 'fix': None,
        })
    else:
        findings.append({
            'name': 'Brute-Force Protection: None',
            'status': 'warn',
            'detail': 'No fail2ban or sshguard installed.',
            'severity': 'medium',
            'fix': 'pkg install fail2ban' if pinfo.os_family == 'freebsd' else 'Install fail2ban or sshguard.',
        })

    return findings
