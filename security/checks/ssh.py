"""SSH configuration audit — cross-platform."""

import os
import re

from security.platform import PlatformInfo, is_unix
from security.runner import read_file, run, run_powershell


def check_ssh(pinfo: PlatformInfo) -> list[dict]:
    if pinfo.os_family == 'windows':
        return _check_ssh_windows(pinfo)
    if is_unix(pinfo):
        return _check_ssh_unix(pinfo)
    return [_skip('SSH Config', pinfo)]


# ── Unix (Linux / macOS / BSD) ──────────────────────────────────────

def _check_ssh_unix(pinfo: PlatformInfo) -> list[dict]:
    findings = []
    config_path = '/etc/ssh/sshd_config'
    content = read_file(config_path)

    if content is None:
        # SSH server may not be installed (common on macOS desktops)
        return [{'name': 'SSH Config', 'status': 'info',
                 'detail': f'{config_path} not found — SSH server may not be installed.',
                 'severity': 'info', 'fix': None}]

    # Collect all config including Include directives
    full_config = _resolve_includes(content, os.path.dirname(config_path))

    # PermitRootLogin
    val = _sshd_value(full_config, 'PermitRootLogin', 'prohibit-password')
    if val == 'yes':
        findings.append({
            'name': 'SSH: Root Login Enabled',
            'status': 'fail',
            'detail': f'PermitRootLogin = {val}. Direct root SSH access should be disabled.',
            'severity': 'high',
            'fix': 'Set "PermitRootLogin no" in /etc/ssh/sshd_config and restart sshd.',
        })
    else:
        findings.append({
            'name': 'SSH: Root Login',
            'status': 'pass',
            'detail': f'PermitRootLogin = {val}',
            'severity': 'ok', 'fix': None,
        })

    # PasswordAuthentication
    val = _sshd_value(full_config, 'PasswordAuthentication', 'yes')
    if val == 'yes':
        findings.append({
            'name': 'SSH: Password Authentication',
            'status': 'warn',
            'detail': f'PasswordAuthentication = {val}. Key-based auth is more secure.',
            'severity': 'medium',
            'fix': 'Set "PasswordAuthentication no" in sshd_config (ensure keys are configured first).',
        })
    else:
        findings.append({
            'name': 'SSH: Password Authentication',
            'status': 'pass',
            'detail': f'PasswordAuthentication = {val}',
            'severity': 'ok', 'fix': None,
        })

    # PermitEmptyPasswords
    val = _sshd_value(full_config, 'PermitEmptyPasswords', 'no')
    if val == 'yes':
        findings.append({
            'name': 'SSH: Empty Passwords Allowed',
            'status': 'fail',
            'detail': 'PermitEmptyPasswords = yes. This is extremely dangerous.',
            'severity': 'critical',
            'fix': 'Set "PermitEmptyPasswords no" in sshd_config.',
        })

    # Port
    val = _sshd_value(full_config, 'Port', '22')
    if val == '22':
        findings.append({
            'name': 'SSH: Default Port',
            'status': 'info',
            'detail': 'SSH is on default port 22. Changing it reduces automated scan noise.',
            'severity': 'low',
            'fix': 'Consider changing to a non-standard port in sshd_config.',
        })
    else:
        findings.append({
            'name': 'SSH: Non-Default Port',
            'status': 'pass',
            'detail': f'SSH port = {val}',
            'severity': 'ok', 'fix': None,
        })

    # X11 Forwarding
    val = _sshd_value(full_config, 'X11Forwarding', 'no')
    if val == 'yes':
        findings.append({
            'name': 'SSH: X11 Forwarding',
            'status': 'warn',
            'detail': 'X11Forwarding is enabled. Disable unless needed.',
            'severity': 'low',
            'fix': 'Set "X11Forwarding no" in sshd_config.',
        })

    # MaxAuthTries
    val = _sshd_value(full_config, 'MaxAuthTries', '6')
    try:
        if int(val) > 4:
            findings.append({
                'name': 'SSH: MaxAuthTries',
                'status': 'warn',
                'detail': f'MaxAuthTries = {val}. Recommend 3-4 to limit brute-force window.',
                'severity': 'low',
                'fix': 'Set "MaxAuthTries 3" in sshd_config.',
            })
    except ValueError:
        pass

    # LoginGraceTime
    val = _sshd_value(full_config, 'LoginGraceTime', '120')
    try:
        seconds = _parse_time(val)
        if seconds > 60:
            findings.append({
                'name': 'SSH: LoginGraceTime',
                'status': 'info',
                'detail': f'LoginGraceTime = {val}. Recommend 30-60 seconds.',
                'severity': 'low',
                'fix': 'Set "LoginGraceTime 30" in sshd_config.',
            })
    except ValueError:
        pass

    # ClientAliveInterval (detect idle sessions)
    val = _sshd_value(full_config, 'ClientAliveInterval', '0')
    if val == '0':
        findings.append({
            'name': 'SSH: No Idle Timeout',
            'status': 'info',
            'detail': 'ClientAliveInterval = 0. Idle SSH sessions will never be terminated.',
            'severity': 'low',
            'fix': 'Set "ClientAliveInterval 300" and "ClientAliveCountMax 2" in sshd_config.',
        })

    # Protocol version (legacy check — should not be set to 1)
    val = _sshd_value(full_config, 'Protocol', '')
    if val and '1' in val and '2' not in val:
        findings.append({
            'name': 'SSH: Protocol Version 1',
            'status': 'fail',
            'detail': 'SSH Protocol 1 is insecure and deprecated.',
            'severity': 'critical',
            'fix': 'Remove "Protocol 1" or set "Protocol 2" in sshd_config.',
        })

    # Weak ciphers / MACs / KexAlgorithms
    _check_weak_crypto(full_config, findings)

    return findings


def _check_weak_crypto(config: str, findings: list):
    """Flag weak SSH ciphers, MACs, or key exchange algorithms."""
    weak_ciphers = {'3des-cbc', 'arcfour', 'arcfour128', 'arcfour256',
                    'blowfish-cbc', 'cast128-cbc', 'aes128-cbc', 'aes192-cbc', 'aes256-cbc'}
    weak_macs = {'hmac-md5', 'hmac-md5-96', 'hmac-sha1-96', 'umac-64@openssh.com'}
    weak_kex = {'diffie-hellman-group1-sha1', 'diffie-hellman-group14-sha1',
                'diffie-hellman-group-exchange-sha1'}

    for directive, weak_set, label in [
        ('Ciphers', weak_ciphers, 'Ciphers'),
        ('MACs', weak_macs, 'MACs'),
        ('KexAlgorithms', weak_kex, 'Key Exchange'),
    ]:
        val = _sshd_value(config, directive, '')
        if val:
            configured = {c.strip() for c in val.split(',')}
            bad = configured & weak_set
            if bad:
                findings.append({
                    'name': f'SSH: Weak {label}',
                    'status': 'warn',
                    'detail': f'Weak {label.lower()} configured: {", ".join(sorted(bad))}',
                    'severity': 'medium',
                    'fix': f'Remove weak algorithms from {directive} in sshd_config.',
                })


# ── Windows ─────────────────────────────────────────────────────────

def _check_ssh_windows(pinfo: PlatformInfo) -> list[dict]:
    findings = []
    config_path = r'C:\ProgramData\ssh\sshd_config'
    content = read_file(config_path)

    if content is None:
        # Check if OpenSSH server is installed
        cap = run_powershell(
            'Get-WindowsCapability -Online | Where-Object Name -like "OpenSSH.Server*" '
            '| Select-Object -ExpandProperty State'
        )
        if 'installed' in cap.lower():
            findings.append({
                'name': 'SSH: Config Missing',
                'status': 'warn',
                'detail': 'OpenSSH server installed but sshd_config not found.',
                'severity': 'medium', 'fix': None,
            })
        else:
            findings.append({
                'name': 'SSH Server',
                'status': 'info',
                'detail': 'OpenSSH server is not installed.',
                'severity': 'info', 'fix': None,
            })
        return findings

    # Reuse the same sshd_config parsing
    val = _sshd_value(content, 'PermitRootLogin', 'prohibit-password')
    if val == 'yes':
        findings.append({
            'name': 'SSH: Root Login Enabled',
            'status': 'fail',
            'detail': f'PermitRootLogin = {val}.',
            'severity': 'high',
            'fix': f'Set "PermitRootLogin no" in {config_path}.',
        })

    val = _sshd_value(content, 'PasswordAuthentication', 'yes')
    if val == 'yes':
        findings.append({
            'name': 'SSH: Password Authentication',
            'status': 'warn',
            'detail': f'PasswordAuthentication = {val}.',
            'severity': 'medium',
            'fix': f'Set "PasswordAuthentication no" in {config_path}.',
        })

    return findings or [{'name': 'SSH Config', 'status': 'pass',
                         'detail': 'OpenSSH server configuration looks reasonable.',
                         'severity': 'ok', 'fix': None}]


# ── Helpers ─────────────────────────────────────────────────────────

def _sshd_value(config: str, key: str, default: str) -> str:
    """Extract the first (effective) value for an sshd_config directive."""
    m = re.search(rf'^{key}\s+(.+)', config, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else default


def _resolve_includes(content: str, base_dir: str) -> str:
    """Resolve Include directives in sshd_config (best-effort)."""
    import glob as globmod
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith('include '):
            pattern = stripped.split(None, 1)[1]
            if not os.path.isabs(pattern):
                pattern = os.path.join(base_dir, pattern)
            for inc_path in sorted(globmod.glob(pattern)):
                inc_content = read_file(inc_path)
                if inc_content:
                    lines.append(inc_content)
        else:
            lines.append(line)
    return '\n'.join(lines)


def _parse_time(val: str) -> int:
    """Parse sshd time value (e.g. '2m', '30', '1h') to seconds."""
    val = val.strip().lower()
    if val.endswith('m'):
        return int(val[:-1]) * 60
    elif val.endswith('h'):
        return int(val[:-1]) * 3600
    elif val.endswith('s'):
        return int(val[:-1])
    return int(val)


def _skip(name, pinfo):
    return {'name': name, 'status': 'skip',
            'detail': f'Not applicable on {pinfo.os_family}.',
            'severity': 'info', 'fix': None}
