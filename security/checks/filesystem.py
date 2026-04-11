"""Filesystem permissions audit — cross-platform."""

import os
import stat

from security.platform import PlatformInfo, is_unix
from security.runner import run, run_powershell


def check_filesystem(pinfo: PlatformInfo) -> list[dict]:
    if pinfo.os_family == 'linux':
        return _check_filesystem_linux(pinfo)
    elif pinfo.os_family == 'darwin':
        return _check_filesystem_macos(pinfo)
    elif pinfo.os_family == 'windows':
        return _check_filesystem_windows(pinfo)
    elif pinfo.os_family in ('freebsd', 'openbsd', 'netbsd'):
        return _check_filesystem_bsd(pinfo)
    return []


# ── Linux ───────────────────────────────────────────────────────────

def _check_filesystem_linux(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    sensitive_files = {
        '/etc/shadow': '0640',
        '/etc/gshadow': '0640',
        '/etc/passwd': '0644',
        '/etc/group': '0644',
        '/etc/ssh/sshd_config': '0600',
        '/root/.ssh/authorized_keys': '0600',
        '/etc/crontab': '0600',
        '/etc/sudoers': '0440',
        '/boot/grub/grub.cfg': '0600',
    }
    _check_file_perms(sensitive_files, findings)

    # Sticky bit on world-writable dirs
    for d in ['/tmp', '/var/tmp']:
        _check_sticky_bit(d, findings)

    # /home directory permissions
    if os.path.isdir('/home'):
        try:
            for entry in os.listdir('/home'):
                home_dir = os.path.join('/home', entry)
                if os.path.isdir(home_dir):
                    mode = os.stat(home_dir).st_mode
                    if mode & stat.S_IROTH or mode & stat.S_IWOTH:
                        findings.append({
                            'name': f'Home Directory: {home_dir}',
                            'status': 'warn',
                            'detail': f'{home_dir} is world-readable or world-writable (mode: {oct(mode)[-4:]}).',
                            'severity': 'medium',
                            'fix': f'chmod 750 {home_dir}',
                        })
        except PermissionError:
            pass

    return findings


# ── macOS ───────────────────────────────────────────────────────────

def _check_filesystem_macos(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # SIP (System Integrity Protection)
    sip = run(['csrutil', 'status'])
    if sip:
        if 'enabled' in sip.lower():
            findings.append({
                'name': 'System Integrity Protection (SIP)',
                'status': 'pass',
                'detail': 'SIP is enabled.',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'System Integrity Protection (SIP): Disabled',
                'status': 'fail',
                'detail': 'SIP is disabled. This removes critical OS protections.',
                'severity': 'critical',
                'fix': 'Reboot to Recovery Mode (Cmd+R) and run: csrutil enable',
            })

    # Gatekeeper
    gk = run(['spctl', '--status'])
    if gk:
        if 'enabled' in gk.lower():
            findings.append({
                'name': 'Gatekeeper: Enabled',
                'status': 'pass',
                'detail': 'Gatekeeper code signing enforcement is active.',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'Gatekeeper: Disabled',
                'status': 'fail',
                'detail': 'Gatekeeper is disabled. Unsigned apps can run without warning.',
                'severity': 'high',
                'fix': 'sudo spctl --master-enable',
            })

    # Check key file permissions
    sensitive_files = {
        '/etc/sudoers': '0440',
        '/etc/ssh/sshd_config': '0644',
    }
    _check_file_perms(sensitive_files, findings)

    # Check /Users directory permissions
    if os.path.isdir('/Users'):
        try:
            for entry in os.listdir('/Users'):
                if entry.startswith('.') or entry in ('Shared', 'Guest'):
                    continue
                user_dir = os.path.join('/Users', entry)
                if os.path.isdir(user_dir):
                    mode = os.stat(user_dir).st_mode
                    if mode & stat.S_IROTH or mode & stat.S_IWOTH:
                        findings.append({
                            'name': f'Home Directory: {user_dir}',
                            'status': 'warn',
                            'detail': f'{user_dir} is world-readable or writable.',
                            'severity': 'medium',
                            'fix': f'chmod 750 {user_dir}',
                        })
        except PermissionError:
            pass

    return findings


# ── Windows ─────────────────────────────────────────────────────────

def _check_filesystem_windows(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # Check key directories have proper ACLs
    critical_paths = [
        (r'C:\Windows\System32\config', 'SAM/SECURITY registry hives'),
        (r'C:\Windows\System32\drivers\etc\hosts', 'Hosts file'),
    ]

    for path, desc in critical_paths:
        if os.path.exists(path):
            acl = run_powershell(f'(Get-Acl "{path}").Access | Format-Table -AutoSize')
            if acl:
                if 'everyone' in acl.lower() and 'fullcontrol' in acl.lower():
                    findings.append({
                        'name': f'ACL: {desc}',
                        'status': 'fail',
                        'detail': f'Everyone has FullControl on {path}.',
                        'severity': 'high',
                        'fix': f'Review and restrict ACLs on {path}.',
                    })
                else:
                    findings.append({
                        'name': f'ACL: {desc}',
                        'status': 'pass',
                        'detail': f'ACLs on {path} appear reasonable.',
                        'severity': 'ok', 'fix': None,
                    })

    # Check if UAC is enabled
    uac = run_powershell(
        '(Get-ItemProperty HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System).EnableLUA'
    )
    if uac is not None:
        if uac.strip() == '1':
            findings.append({
                'name': 'User Account Control (UAC)',
                'status': 'pass',
                'detail': 'UAC is enabled.',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'User Account Control (UAC): Disabled',
                'status': 'fail',
                'detail': 'UAC is disabled. This is a significant security risk.',
                'severity': 'critical',
                'fix': 'Enable UAC in Control Panel → User Accounts → Change User Account Control settings.',
            })

    return findings


# ── BSD ─────────────────────────────────────────────────────────────

def _check_filesystem_bsd(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    sensitive_files = {
        '/etc/master.passwd': '0600',
        '/etc/passwd': '0644',
        '/etc/ssh/sshd_config': '0600',
    }
    _check_file_perms(sensitive_files, findings)

    for d in ['/tmp', '/var/tmp']:
        _check_sticky_bit(d, findings)

    # securelevel
    sl = run(['sysctl', '-n', 'kern.securelevel'])
    if sl:
        try:
            level = int(sl.strip())
            if level < 1:
                findings.append({
                    'name': 'Kernel Securelevel',
                    'status': 'warn',
                    'detail': f'kern.securelevel = {level}. Consider raising to 1 or 2.',
                    'severity': 'medium',
                    'fix': 'Set kern.securelevel=1 in /etc/sysctl.conf.',
                })
        except ValueError:
            pass

    return findings


# ── Shared helpers ──────────────────────────────────────────────────

def _check_file_perms(file_map: dict, findings: list):
    """Check file permissions against expected values."""
    for fpath, expected in file_map.items():
        if not os.path.exists(fpath):
            continue
        try:
            mode = oct(os.stat(fpath).st_mode)[-4:]
            if int(mode, 8) > int(expected, 8):
                findings.append({
                    'name': f'Permissions: {fpath}',
                    'status': 'warn',
                    'detail': f'Current: {mode}, Recommended: {expected}',
                    'severity': 'medium',
                    'fix': f'chmod {expected} {fpath}',
                })
            else:
                findings.append({
                    'name': f'Permissions: {fpath}',
                    'status': 'pass',
                    'detail': f'Mode: {mode} (OK)',
                    'severity': 'ok', 'fix': None,
                })
        except PermissionError:
            pass


def _check_sticky_bit(directory: str, findings: list):
    """Check that a world-writable directory has the sticky bit set."""
    if os.path.isdir(directory):
        try:
            st = os.stat(directory)
            if not (st.st_mode & stat.S_ISVTX):
                findings.append({
                    'name': f'Sticky Bit: {directory}',
                    'status': 'fail',
                    'detail': f'{directory} is world-writable without sticky bit.',
                    'severity': 'high',
                    'fix': f'chmod +t {directory}',
                })
        except PermissionError:
            pass
