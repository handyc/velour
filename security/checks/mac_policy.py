"""Mandatory Access Control (SELinux / AppArmor / etc.) audit — cross-platform."""

import os

from security.platform import PlatformInfo, is_debian_family, is_rhel_family
from security.runner import run, run_powershell, read_file, command_exists


def check_mac_policy(pinfo: PlatformInfo) -> list[dict]:
    if pinfo.os_family == 'linux':
        return _check_mac_linux(pinfo)
    elif pinfo.os_family == 'darwin':
        return _check_mac_macos(pinfo)
    elif pinfo.os_family == 'windows':
        return _check_mac_windows(pinfo)
    return []


def _check_mac_linux(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # SELinux (RHEL/Fedora/CentOS family)
    if command_exists('getenforce') or os.path.isfile('/etc/selinux/config'):
        getenforce = run(['getenforce'])
        if getenforce:
            mode = getenforce.strip()
            if mode == 'Enforcing':
                findings.append({
                    'name': 'SELinux: Enforcing',
                    'status': 'pass',
                    'detail': 'SELinux is in enforcing mode.',
                    'severity': 'ok', 'fix': None,
                })
            elif mode == 'Permissive':
                findings.append({
                    'name': 'SELinux: Permissive',
                    'status': 'warn',
                    'detail': 'SELinux is in permissive mode (logging only, not enforcing).',
                    'severity': 'medium',
                    'fix': 'Set SELINUX=enforcing in /etc/selinux/config and run: setenforce 1',
                })
            elif mode == 'Disabled':
                findings.append({
                    'name': 'SELinux: Disabled',
                    'status': 'fail',
                    'detail': 'SELinux is disabled. Mandatory access control is not active.',
                    'severity': 'high',
                    'fix': 'Set SELINUX=enforcing in /etc/selinux/config and reboot.',
                })

            # Check for policy denials
            if mode in ('Enforcing', 'Permissive'):
                denials = run(['ausearch', '-m', 'avc', '-ts', 'recent'], timeout=10)
                if denials and 'denied' in denials.lower():
                    denial_count = denials.lower().count('denied')
                    findings.append({
                        'name': f'SELinux: {denial_count} Recent Denials',
                        'status': 'info',
                        'detail': f'{denial_count} AVC denials found. Review for legitimate issues.',
                        'severity': 'info',
                        'fix': 'Use "sealert -a /var/log/audit/audit.log" to analyze denials.',
                    })

        return findings

    # AppArmor (Debian/Ubuntu family)
    if command_exists('aa-status') or os.path.isdir('/etc/apparmor.d'):
        aa_status = run(['aa-status'])
        if aa_status:
            if 'profiles are loaded' in aa_status:
                findings.append({
                    'name': 'AppArmor: Active',
                    'status': 'pass',
                    'detail': aa_status.split('\n')[0] if aa_status else 'AppArmor is loaded.',
                    'severity': 'ok', 'fix': None,
                })

                # Check for profiles in complain mode
                if 'complain' in aa_status:
                    import re
                    complain = re.search(r'(\d+)\s+profiles are in complain mode', aa_status)
                    if complain and int(complain.group(1)) > 0:
                        findings.append({
                            'name': f'AppArmor: {complain.group(1)} Profiles in Complain Mode',
                            'status': 'info',
                            'detail': 'Some profiles are in complain (log-only) mode.',
                            'severity': 'low',
                            'fix': 'Move profiles to enforce mode when ready: aa-enforce /etc/apparmor.d/<profile>',
                        })
            else:
                findings.append({
                    'name': 'AppArmor: Not Active',
                    'status': 'warn',
                    'detail': 'AppArmor does not appear to be loaded.',
                    'severity': 'medium',
                    'fix': 'sudo systemctl enable --now apparmor',
                })
        elif os.path.isdir('/etc/apparmor.d'):
            findings.append({
                'name': 'AppArmor: Installed but Status Unknown',
                'status': 'info',
                'detail': 'AppArmor config directory exists but cannot query status.',
                'severity': 'info', 'fix': None,
            })
        return findings

    # Neither found
    findings.append({
        'name': 'Mandatory Access Control: None',
        'status': 'warn',
        'detail': 'Neither SELinux nor AppArmor is active. No mandatory access control.',
        'severity': 'medium',
        'fix': 'Install and enable AppArmor (Debian/Ubuntu) or SELinux (RHEL/Fedora).',
    })
    return findings


def _check_mac_macos(pinfo: PlatformInfo) -> list[dict]:
    # SIP is macOS's primary MAC — covered in filesystem/kernel checks
    # We add a note here for completeness
    findings = []
    sip = run(['csrutil', 'status'])
    if sip and 'enabled' in sip.lower():
        findings.append({
            'name': 'macOS SIP (MAC equivalent)',
            'status': 'pass',
            'detail': 'System Integrity Protection provides mandatory access control.',
            'severity': 'ok', 'fix': None,
        })
    elif sip:
        findings.append({
            'name': 'macOS SIP: Disabled',
            'status': 'fail',
            'detail': 'SIP is disabled — the primary MAC mechanism on macOS.',
            'severity': 'critical',
            'fix': 'Reboot to Recovery Mode and run: csrutil enable',
        })
    return findings


def _check_mac_windows(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # AppLocker
    applocker = run_powershell(
        'Get-AppLockerPolicy -Effective -ErrorAction SilentlyContinue | '
        'Select-Object -ExpandProperty RuleCollections | Measure-Object | '
        'Select-Object -ExpandProperty Count'
    )
    if applocker:
        try:
            count = int(applocker.strip())
            if count > 0:
                findings.append({
                    'name': f'AppLocker: {count} Rule Collections',
                    'status': 'pass',
                    'detail': f'AppLocker has {count} active rule collections.',
                    'severity': 'ok', 'fix': None,
                })
            else:
                findings.append({
                    'name': 'AppLocker: No Rules',
                    'status': 'info',
                    'detail': 'AppLocker has no active rules.',
                    'severity': 'low', 'fix': None,
                })
        except ValueError:
            pass

    # Windows Defender Application Control (WDAC)
    wdac = run_powershell(
        'Get-CimInstance -Namespace root\\Microsoft\\Windows\\CI '
        '-ClassName MSFT_WDACConfig -ErrorAction SilentlyContinue | '
        'Select-Object -ExpandProperty PolicyStatus'
    )
    if wdac:
        findings.append({
            'name': 'WDAC: Active',
            'status': 'pass',
            'detail': 'Windows Defender Application Control policy is active.',
            'severity': 'ok', 'fix': None,
        })

    if not findings:
        findings.append({
            'name': 'Application Control',
            'status': 'info',
            'detail': 'No AppLocker or WDAC policies detected.',
            'severity': 'low',
            'fix': 'Consider enabling AppLocker or WDAC for application whitelisting.',
        })

    return findings
