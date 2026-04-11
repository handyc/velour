"""Package update status audit — cross-platform."""

import os

from security.platform import PlatformInfo, is_debian_family, is_rhel_family
from security.runner import run, run_powershell, read_file


def check_updates(pinfo: PlatformInfo) -> list[dict]:
    if pinfo.os_family == 'linux':
        return _check_updates_linux(pinfo)
    elif pinfo.os_family == 'darwin':
        return _check_updates_macos(pinfo)
    elif pinfo.os_family == 'windows':
        return _check_updates_windows(pinfo)
    elif pinfo.os_family in ('freebsd',):
        return _check_updates_freebsd(pinfo)
    return [{'name': 'System Updates', 'status': 'skip',
             'detail': f'Update check not implemented for {pinfo.os_family}.',
             'severity': 'info', 'fix': None}]


# ── Linux ───────────────────────────────────────────────────────────

def _check_updates_linux(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    if is_debian_family(pinfo):
        _check_apt(findings)
    elif is_rhel_family(pinfo):
        _check_yum_dnf(pinfo, findings)
    elif pinfo.pkg_manager == 'pacman':
        _check_pacman(findings)
    elif pinfo.pkg_manager == 'apk':
        _check_apk(findings)
    elif pinfo.pkg_manager == 'zypper':
        _check_zypper(findings)
    else:
        findings.append({
            'name': 'System Updates',
            'status': 'info',
            'detail': f'Package manager "{pinfo.pkg_manager}" not yet supported for update checks.',
            'severity': 'info', 'fix': None,
        })

    return findings


def _check_apt(findings):
    """Debian/Ubuntu apt-based update check."""
    # Try apt-check first
    apt_check = run(['/usr/lib/update-notifier/apt-check', '--human-readable'])
    if apt_check:
        findings.append({
            'name': 'Pending Updates',
            'status': 'info',
            'detail': apt_check,
            'severity': 'medium' if 'security' in apt_check.lower() else 'low',
            'fix': 'sudo apt update && sudo apt upgrade -y',
        })
    else:
        apt_list = run(['apt', 'list', '--upgradable'], timeout=15)
        if apt_list:
            lines = [l for l in apt_list.splitlines() if '/' in l]
            if lines:
                findings.append({
                    'name': f'Pending Updates: {len(lines)} packages',
                    'status': 'warn',
                    'detail': '\n'.join(lines[:10]) + ('\n...' if len(lines) > 10 else ''),
                    'severity': 'medium',
                    'fix': 'sudo apt update && sudo apt upgrade -y',
                })
            else:
                findings.append({
                    'name': 'System Up-to-Date',
                    'status': 'pass',
                    'detail': 'No pending package updates.',
                    'severity': 'ok', 'fix': None,
                })

    # Check unattended-upgrades
    auto_upgrades = '/etc/apt/apt.conf.d/20auto-upgrades'
    if os.path.isfile(auto_upgrades):
        content = read_file(auto_upgrades, '')
        if 'Unattended-Upgrade "1"' in content:
            findings.append({
                'name': 'Unattended Upgrades: Enabled',
                'status': 'pass',
                'detail': 'Automatic security updates are configured.',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'Unattended Upgrades: Disabled',
                'status': 'warn',
                'detail': 'Automatic security updates are not enabled.',
                'severity': 'medium',
                'fix': 'sudo apt install unattended-upgrades && sudo dpkg-reconfigure -plow unattended-upgrades',
            })
    else:
        findings.append({
            'name': 'Unattended Upgrades: Not Installed',
            'status': 'warn',
            'detail': 'Automatic security updates package not found.',
            'severity': 'medium',
            'fix': 'sudo apt install unattended-upgrades && sudo dpkg-reconfigure -plow unattended-upgrades',
        })


def _check_yum_dnf(pinfo, findings):
    """RHEL/CentOS/Fedora update check."""
    cmd = 'dnf' if pinfo.pkg_manager == 'dnf' else 'yum'
    # check-update returns exit code 100 if updates available, 0 if none
    result = run([cmd, 'check-update', '-q'], timeout=30)
    if result:
        lines = [l for l in result.splitlines() if l.strip() and not l.startswith('Last')]
        if lines:
            findings.append({
                'name': f'Pending Updates: {len(lines)} packages',
                'status': 'warn',
                'detail': '\n'.join(lines[:10]) + ('\n...' if len(lines) > 10 else ''),
                'severity': 'medium',
                'fix': f'sudo {cmd} update -y',
            })
        else:
            findings.append({
                'name': 'System Up-to-Date',
                'status': 'pass',
                'detail': 'No pending package updates.',
                'severity': 'ok', 'fix': None,
            })
    else:
        findings.append({
            'name': 'System Up-to-Date',
            'status': 'pass',
            'detail': 'No pending package updates.',
            'severity': 'ok', 'fix': None,
        })

    # Check if automatic updates are configured
    if os.path.isfile('/etc/dnf/automatic.conf') or os.path.isfile('/etc/yum/yum-cron.conf'):
        svc = 'dnf-automatic.timer' if cmd == 'dnf' else 'yum-cron'
        status = run(['systemctl', 'is-active', svc])
        if status and 'active' in status:
            findings.append({
                'name': 'Automatic Updates: Enabled',
                'status': 'pass',
                'detail': f'{svc} is active.',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'Automatic Updates: Not Active',
                'status': 'warn',
                'detail': f'{svc} is not running.',
                'severity': 'medium',
                'fix': f'sudo systemctl enable --now {svc}',
            })


def _check_pacman(findings):
    """Arch Linux update check."""
    result = run(['checkupdates'], timeout=30)
    if not result:
        result = run(['pacman', '-Qu'], timeout=15)

    if result and result.strip():
        lines = result.strip().splitlines()
        findings.append({
            'name': f'Pending Updates: {len(lines)} packages',
            'status': 'warn',
            'detail': '\n'.join(lines[:10]) + ('\n...' if len(lines) > 10 else ''),
            'severity': 'medium',
            'fix': 'sudo pacman -Syu',
        })
    else:
        findings.append({
            'name': 'System Up-to-Date',
            'status': 'pass',
            'detail': 'No pending package updates.',
            'severity': 'ok', 'fix': None,
        })


def _check_apk(findings):
    """Alpine Linux update check."""
    result = run(['apk', 'version', '-v', '-l', '<'], timeout=15)
    if result and result.strip():
        lines = result.strip().splitlines()
        findings.append({
            'name': f'Pending Updates: {len(lines)} packages',
            'status': 'warn',
            'detail': '\n'.join(lines[:10]) + ('\n...' if len(lines) > 10 else ''),
            'severity': 'medium',
            'fix': 'apk update && apk upgrade',
        })
    else:
        findings.append({
            'name': 'System Up-to-Date',
            'status': 'pass',
            'detail': 'No pending package updates.',
            'severity': 'ok', 'fix': None,
        })


def _check_zypper(findings):
    """openSUSE/SLES update check."""
    result = run(['zypper', 'list-updates'], timeout=30)
    if result:
        lines = [l for l in result.splitlines() if '|' in l and 'v |' not in l.lower()]
        # Skip header lines
        data_lines = [l for l in lines if not l.startswith('+') and not l.startswith('S ')]
        if data_lines:
            findings.append({
                'name': f'Pending Updates: {len(data_lines)} packages',
                'status': 'warn',
                'detail': '\n'.join(data_lines[:10]),
                'severity': 'medium',
                'fix': 'sudo zypper update',
            })
            return
    findings.append({
        'name': 'System Up-to-Date',
        'status': 'pass',
        'detail': 'No pending package updates.',
        'severity': 'ok', 'fix': None,
    })


# ── macOS ───────────────────────────────────────────────────────────

def _check_updates_macos(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # System software updates
    sw_update = run(['softwareupdate', '-l'], timeout=30)
    if sw_update:
        if 'no new software available' in sw_update.lower():
            findings.append({
                'name': 'macOS System Updates',
                'status': 'pass',
                'detail': 'No pending system updates.',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'macOS System Updates Available',
                'status': 'warn',
                'detail': sw_update[:300],
                'severity': 'medium',
                'fix': 'softwareupdate --install --all',
            })
    else:
        findings.append({
            'name': 'macOS System Updates',
            'status': 'unknown',
            'detail': 'Could not check for system updates.',
            'severity': 'info', 'fix': None,
        })

    # Check automatic updates setting
    auto = run(['defaults', 'read', '/Library/Preferences/com.apple.SoftwareUpdate',
                'AutomaticCheckEnabled'])
    if auto and auto.strip() == '0':
        findings.append({
            'name': 'macOS Auto-Update Check: Disabled',
            'status': 'warn',
            'detail': 'Automatic update checking is turned off.',
            'severity': 'medium',
            'fix': 'System Settings → General → Software Update → Automatic Updates',
        })

    # Homebrew updates (if installed)
    if pinfo.pkg_manager == 'brew':
        brew_out = run(['brew', 'outdated'], timeout=30)
        if brew_out and brew_out.strip():
            lines = brew_out.strip().splitlines()
            findings.append({
                'name': f'Homebrew: {len(lines)} Outdated Packages',
                'status': 'info',
                'detail': '\n'.join(lines[:10]) + ('\n...' if len(lines) > 10 else ''),
                'severity': 'low',
                'fix': 'brew update && brew upgrade',
            })

    return findings


# ── Windows ─────────────────────────────────────────────────────────

def _check_updates_windows(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # Check Windows Update via COM
    result = run_powershell(
        '$s = New-Object -ComObject Microsoft.Update.Session; '
        '$u = $s.CreateUpdateSearcher(); '
        '$r = $u.Search("IsInstalled=0"); '
        '$r.Updates | Select-Object -First 10 Title | Format-List',
        timeout=30,
    )
    if result:
        lines = [l for l in result.splitlines() if l.strip() and ':' in l]
        if lines:
            findings.append({
                'name': f'Windows Updates: {len(lines)} Pending',
                'status': 'warn',
                'detail': '\n'.join(l.split(':', 1)[1].strip() for l in lines[:10]),
                'severity': 'medium',
                'fix': 'Settings → Windows Update → Check for updates',
            })
        else:
            findings.append({
                'name': 'Windows Updates',
                'status': 'pass',
                'detail': 'No pending updates found.',
                'severity': 'ok', 'fix': None,
            })
    else:
        findings.append({
            'name': 'Windows Updates',
            'status': 'unknown',
            'detail': 'Could not query Windows Update status.',
            'severity': 'info', 'fix': None,
        })

    return findings


# ── FreeBSD ─────────────────────────────────────────────────────────

def _check_updates_freebsd(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # pkg audit for known vulnerabilities
    audit = run(['pkg', 'audit', '-F'], timeout=30)
    if audit:
        if 'is affected by' in audit.lower() or 'problem(s)' in audit.lower():
            findings.append({
                'name': 'FreeBSD Package Vulnerabilities',
                'status': 'fail',
                'detail': audit[:300],
                'severity': 'high',
                'fix': 'pkg upgrade to update affected packages.',
            })
        elif '0 problem' in audit:
            findings.append({
                'name': 'FreeBSD Package Audit',
                'status': 'pass',
                'detail': 'No known vulnerabilities in installed packages.',
                'severity': 'ok', 'fix': None,
            })

    # freebsd-update
    fb_update = run(['freebsd-update', 'fetch'], timeout=60)
    if fb_update and 'no updates' not in fb_update.lower():
        findings.append({
            'name': 'FreeBSD System Updates Available',
            'status': 'warn',
            'detail': 'System updates are available.',
            'severity': 'medium',
            'fix': 'freebsd-update install',
        })

    return findings or [{'name': 'System Updates', 'status': 'pass',
                         'detail': 'System appears up to date.',
                         'severity': 'ok', 'fix': None}]
