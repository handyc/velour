"""User account audit — cross-platform."""

import os
import re

from security.platform import PlatformInfo, is_unix
from security.runner import run, run_powershell, read_lines, read_file


def check_users(pinfo: PlatformInfo) -> list[dict]:
    if pinfo.os_family == 'linux':
        return _check_users_unix(pinfo)
    elif pinfo.os_family == 'darwin':
        return _check_users_macos(pinfo)
    elif pinfo.os_family == 'windows':
        return _check_users_windows(pinfo)
    elif pinfo.os_family in ('freebsd', 'openbsd', 'netbsd'):
        return _check_users_unix(pinfo)
    return [{'name': 'User Audit', 'status': 'skip',
             'detail': f'Not implemented for {pinfo.os_family}.',
             'severity': 'info', 'fix': None}]


# ── Unix (Linux / BSD) ──────────────────────────────────────────────

def _check_users_unix(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    passwd = read_lines('/etc/passwd')
    if not passwd:
        return [{'name': 'User Audit', 'status': 'unknown',
                 'detail': 'Cannot read /etc/passwd.',
                 'severity': 'info', 'fix': None}]

    # Parse into fields
    users = []
    for line in passwd:
        fields = line.split(':')
        if len(fields) >= 7:
            users.append({
                'name': fields[0],
                'uid': fields[2],
                'gid': fields[3],
                'home': fields[5],
                'shell': fields[6],
            })

    # UID 0 accounts (root equivalents)
    root_users = [u['name'] for u in users if u['uid'] == '0']
    if len(root_users) > 1:
        findings.append({
            'name': 'Multiple UID 0 Accounts',
            'status': 'fail',
            'detail': f'Users with UID 0: {", ".join(root_users)}. Only root should have UID 0.',
            'severity': 'high',
            'fix': 'Remove or change UID of extra UID-0 accounts.',
        })
    else:
        findings.append({
            'name': 'UID 0 Accounts',
            'status': 'pass',
            'detail': 'Only root has UID 0.',
            'severity': 'ok', 'fix': None,
        })

    # Users with login shells
    login_shells = ('/bash', '/sh', '/zsh', '/fish', '/csh', '/tcsh', '/ksh')
    login_users = [u['name'] for u in users
                   if u['shell'].endswith(login_shells)
                   and _safe_int(u['uid'], 0) >= 1000]
    findings.append({
        'name': f'Login-Capable Users: {len(login_users)}',
        'status': 'info',
        'detail': ', '.join(login_users) if login_users else 'None',
        'severity': 'info', 'fix': None,
    })

    # System accounts with login shells (UID < 1000, not root)
    sys_login = [u['name'] for u in users
                 if u['shell'].endswith(login_shells)
                 and 0 < _safe_int(u['uid'], 0) < 1000]
    if sys_login:
        findings.append({
            'name': 'System Accounts with Login Shell',
            'status': 'warn',
            'detail': f'System accounts that can log in: {", ".join(sys_login)}',
            'severity': 'medium',
            'fix': 'Set shell to /usr/sbin/nologin for service accounts that do not need interactive access.',
        })

    # Empty passwords in shadow
    shadow_path = '/etc/shadow'
    if pinfo.os_family in ('freebsd', 'openbsd', 'netbsd'):
        shadow_path = '/etc/master.passwd'

    shadow_lines = read_lines(shadow_path, skip_comments=True)
    if shadow_lines:
        empty_pw = []
        for line in shadow_lines:
            parts = line.split(':')
            if len(parts) >= 2 and parts[1] == '':
                empty_pw.append(parts[0])
        if empty_pw:
            findings.append({
                'name': 'Empty Passwords',
                'status': 'fail',
                'detail': f'Users with empty passwords: {", ".join(empty_pw)}',
                'severity': 'critical',
                'fix': 'Set passwords: sudo passwd <username>',
            })
        else:
            findings.append({
                'name': 'Password Check',
                'status': 'pass',
                'detail': 'No users with empty passwords found.',
                'severity': 'ok', 'fix': None,
            })

        # Accounts with no password aging
        no_aging = []
        for line in shadow_lines:
            parts = line.split(':')
            if len(parts) >= 5:
                username = parts[0]
                max_days = parts[4] if parts[4] else ''
                pw_hash = parts[1] if len(parts) > 1 else ''
                # Skip locked/disabled accounts
                if pw_hash.startswith(('!', '*', '!!')):
                    continue
                if max_days in ('', '99999'):
                    no_aging.append(username)
        if no_aging and len(no_aging) <= 20:
            findings.append({
                'name': 'Password Aging: Not Configured',
                'status': 'info',
                'detail': f'Accounts without password expiry: {", ".join(no_aging[:10])}'
                          + (f' (+{len(no_aging)-10} more)' if len(no_aging) > 10 else ''),
                'severity': 'low',
                'fix': 'Consider: chage -M 90 <username>',
            })
    else:
        findings.append({
            'name': 'Shadow File',
            'status': 'info',
            'detail': f'Cannot read {shadow_path} (normal for non-root). Run audit as root for full check.',
            'severity': 'info', 'fix': None,
        })

    # Sudoers
    sudoers_d = '/etc/sudoers.d'
    if os.path.isdir(sudoers_d):
        try:
            files = os.listdir(sudoers_d)
            findings.append({
                'name': f'Sudoers.d: {len(files)} files',
                'status': 'info',
                'detail': ', '.join(files) if files else 'Empty',
                'severity': 'info', 'fix': None,
            })
        except PermissionError:
            pass

    # Check for users with NOPASSWD sudo
    sudoers_content = read_file('/etc/sudoers')
    if sudoers_content:
        nopasswd = re.findall(r'^(\S+)\s+.*NOPASSWD', sudoers_content, re.MULTILINE)
        if nopasswd:
            findings.append({
                'name': 'NOPASSWD Sudo Entries',
                'status': 'warn',
                'detail': f'Users/groups with passwordless sudo: {", ".join(nopasswd)}',
                'severity': 'medium',
                'fix': 'Remove NOPASSWD from /etc/sudoers entries where not required.',
            })

    return findings


# ── macOS ───────────────────────────────────────────────────────────

def _check_users_macos(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # List all users
    user_list = run(['dscl', '.', '-list', '/Users'])
    if not user_list:
        return [{'name': 'User Audit', 'status': 'unknown',
                 'detail': 'Cannot query user directory.',
                 'severity': 'info', 'fix': None}]

    users = [u for u in user_list.splitlines() if not u.startswith('_')]

    findings.append({
        'name': f'User Accounts: {len(users)}',
        'status': 'info',
        'detail': ', '.join(users),
        'severity': 'info', 'fix': None,
    })

    # Check admin group
    admin_group = run(['dscl', '.', '-read', '/Groups/admin', 'GroupMembership'])
    if admin_group:
        members = admin_group.split(':', 1)[1].strip() if ':' in admin_group else admin_group
        admin_users = members.split()
        if len(admin_users) > 2:
            findings.append({
                'name': f'Admin Users: {len(admin_users)}',
                'status': 'warn',
                'detail': f'Admin group members: {", ".join(admin_users)}. Consider limiting admin access.',
                'severity': 'medium',
                'fix': 'Remove unnecessary users from the admin group via System Settings → Users & Groups.',
            })
        else:
            findings.append({
                'name': f'Admin Users: {len(admin_users)}',
                'status': 'pass',
                'detail': f'Admin group: {", ".join(admin_users)}',
                'severity': 'ok', 'fix': None,
            })

    # Guest account
    guest = run(['dscl', '.', '-read', '/Users/Guest'])
    if guest and 'does not exist' not in guest.lower():
        findings.append({
            'name': 'Guest Account: Exists',
            'status': 'info',
            'detail': 'The Guest account exists. Consider disabling if not needed.',
            'severity': 'low',
            'fix': 'System Settings → Users & Groups → Guest User → Turn off.',
        })

    # Root account status
    root_pw = run(['dscl', '.', '-read', '/Users/root', 'AuthenticationAuthority'])
    if root_pw and 'disabled' not in root_pw.lower():
        findings.append({
            'name': 'macOS Root Account: Enabled',
            'status': 'warn',
            'detail': 'The root account is enabled. macOS recommends keeping it disabled.',
            'severity': 'medium',
            'fix': 'Disable: dsenableroot -d',
        })

    return findings


# ── Windows ─────────────────────────────────────────────────────────

def _check_users_windows(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # List local users
    users_output = run_powershell(
        'Get-LocalUser | Select-Object Name, Enabled, PasswordRequired, '
        'PasswordLastSet, LastLogon | Format-List'
    )
    if not users_output:
        return [{'name': 'User Audit', 'status': 'unknown',
                 'detail': 'Cannot query local users.',
                 'severity': 'info', 'fix': None}]

    # Parse user blocks
    enabled_users = []
    no_pw_required = []
    current_user = {}
    for line in users_output.splitlines():
        line = line.strip()
        if line.startswith('Name'):
            if current_user:
                _process_win_user(current_user, enabled_users, no_pw_required)
            current_user = {'Name': line.split(':', 1)[1].strip()}
        elif ':' in line:
            key, _, val = line.partition(':')
            current_user[key.strip()] = val.strip()
    if current_user:
        _process_win_user(current_user, enabled_users, no_pw_required)

    findings.append({
        'name': f'Enabled Local Users: {len(enabled_users)}',
        'status': 'info',
        'detail': ', '.join(enabled_users),
        'severity': 'info', 'fix': None,
    })

    if no_pw_required:
        findings.append({
            'name': 'Users Without Password Requirement',
            'status': 'fail',
            'detail': f'Accounts that don\'t require a password: {", ".join(no_pw_required)}',
            'severity': 'high',
            'fix': 'Set-LocalUser -Name "<user>" -PasswordNeverExpires $false',
        })

    # Check built-in Administrator account
    admin_status = run_powershell(
        'Get-LocalUser -Name "Administrator" | Select-Object -ExpandProperty Enabled'
    )
    if admin_status and 'true' in admin_status.lower():
        findings.append({
            'name': 'Built-in Administrator: Enabled',
            'status': 'warn',
            'detail': 'The built-in Administrator account is enabled. Consider disabling it.',
            'severity': 'medium',
            'fix': 'Disable-LocalUser -Name "Administrator"',
        })

    # Check account lockout policy
    net_accounts = run(['net', 'accounts'])
    if net_accounts:
        for line in net_accounts.splitlines():
            if 'lockout threshold' in line.lower():
                val = line.split(':')[-1].strip()
                if val.lower() == 'never' or val == '0':
                    findings.append({
                        'name': 'Account Lockout: Not Configured',
                        'status': 'warn',
                        'detail': 'No account lockout threshold. Brute-force attacks are not limited.',
                        'severity': 'medium',
                        'fix': 'net accounts /lockoutthreshold:5',
                    })

    return findings


def _process_win_user(user, enabled_list, no_pw_list):
    if user.get('Enabled', '').lower() == 'true':
        enabled_list.append(user.get('Name', ''))
        if user.get('PasswordRequired', '').lower() == 'false':
            no_pw_list.append(user.get('Name', ''))


def _safe_int(s, default=0):
    try:
        return int(s)
    except (ValueError, TypeError):
        return default
