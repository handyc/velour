"""Authentication log analysis — cross-platform."""

import os
import re
from collections import Counter

from security.platform import PlatformInfo
from security.runner import run, run_powershell, read_file


def check_auth_logs(pinfo: PlatformInfo) -> list[dict]:
    if pinfo.os_family == 'linux':
        return _check_auth_logs_linux(pinfo)
    elif pinfo.os_family == 'darwin':
        return _check_auth_logs_macos(pinfo)
    elif pinfo.os_family == 'windows':
        return _check_auth_logs_windows(pinfo)
    elif pinfo.os_family in ('freebsd', 'openbsd', 'netbsd'):
        return _check_auth_logs_bsd(pinfo)
    return []


# ── Linux ───────────────────────────────────────────────────────────

def _check_auth_logs_linux(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # Try log files first
    log_paths = ['/var/log/auth.log', '/var/log/secure']
    content = None
    for path in log_paths:
        if os.path.isfile(path):
            try:
                with open(path) as f:
                    content = f.readlines()[-2000:]
                break
            except PermissionError:
                continue

    # Fall back to journalctl on systemd systems
    if content is None and pinfo.init_system == 'systemd':
        journal = run(['journalctl', '-u', 'sshd', '--since', '24 hours ago',
                       '--no-pager', '-q'], timeout=15)
        if not journal:
            journal = run(['journalctl', '-u', 'ssh', '--since', '24 hours ago',
                           '--no-pager', '-q'], timeout=15)
        if journal:
            content = journal.splitlines()

    if content is None:
        findings.append({
            'name': 'Auth Logs',
            'status': 'info',
            'detail': 'Cannot read authentication logs. Run as root for full analysis.',
            'severity': 'info', 'fix': None,
        })
        return findings

    _analyze_auth_lines(content, findings)
    return findings


# ── macOS ───────────────────────────────────────────────────────────

def _check_auth_logs_macos(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # macOS unified logging
    result = run([
        'log', 'show', '--predicate',
        'eventMessage contains "failed" OR eventMessage contains "invalid user"',
        '--style', 'syslog', '--last', '1h',
    ], timeout=30)

    if result:
        lines = result.splitlines()
        failed = [l for l in lines if 'failed' in l.lower() or 'invalid user' in l.lower()]
        if len(failed) > 20:
            findings.append({
                'name': f'Failed Auth Events (last 1h): {len(failed)}',
                'status': 'warn',
                'detail': 'High number of failed authentication events in the last hour.',
                'severity': 'medium',
                'fix': 'Review login attempts. Consider enabling the macOS firewall and limiting SSH access.',
            })
            _extract_ips(failed, findings)
        elif failed:
            findings.append({
                'name': f'Failed Auth Events (last 1h): {len(failed)}',
                'status': 'info',
                'detail': 'Normal level of failed authentication events.',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'Auth Logs (last 1h)',
                'status': 'pass',
                'detail': 'No failed authentication events in the last hour.',
                'severity': 'ok', 'fix': None,
            })
    else:
        findings.append({
            'name': 'Auth Logs',
            'status': 'info',
            'detail': 'Could not query unified log. May require elevated privileges.',
            'severity': 'info', 'fix': None,
        })

    return findings


# ── Windows ─────────────────────────────────────────────────────────

def _check_auth_logs_windows(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # Event ID 4625 = failed logon
    result = run_powershell(
        'Get-WinEvent -FilterHashtable @{LogName="Security"; Id=4625} '
        '-MaxEvents 200 -ErrorAction SilentlyContinue | '
        'Select-Object TimeCreated, Message | Format-List',
        timeout=20,
    )

    if result:
        # Count events
        events = result.count('TimeCreated')
        if events > 50:
            findings.append({
                'name': f'Failed Logons: {events} (recent)',
                'status': 'warn',
                'detail': 'High number of failed Windows logon attempts.',
                'severity': 'medium',
                'fix': 'Review failed logon events. Consider account lockout policies.',
            })
            # Extract source IPs if present
            ips = re.findall(r'Source Network Address:\s*(\d+\.\d+\.\d+\.\d+)', result)
            if ips:
                top = Counter(ips).most_common(5)
                detail = ', '.join(f'{ip} ({c}x)' for ip, c in top)
                findings.append({
                    'name': 'Top Failed Logon Sources',
                    'status': 'info',
                    'detail': detail,
                    'severity': 'info',
                    'fix': 'Consider blocking these IPs in Windows Firewall.',
                })
        elif events > 0:
            findings.append({
                'name': f'Failed Logons: {events}',
                'status': 'info',
                'detail': 'Normal level of failed logon attempts.',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'Failed Logons',
                'status': 'pass',
                'detail': 'No recent failed logon events found.',
                'severity': 'ok', 'fix': None,
            })
    else:
        # Check if audit logging is even enabled
        audit = run_powershell(
            'auditpol /get /subcategory:"Logon" 2>$null'
        )
        if audit and 'no auditing' in audit.lower():
            findings.append({
                'name': 'Logon Auditing: Disabled',
                'status': 'fail',
                'detail': 'Logon auditing is not enabled. Failed login attempts are not being recorded.',
                'severity': 'high',
                'fix': 'auditpol /set /subcategory:"Logon" /failure:enable',
            })
        else:
            findings.append({
                'name': 'Auth Logs',
                'status': 'info',
                'detail': 'Could not query Security event log. May require elevated privileges.',
                'severity': 'info', 'fix': None,
            })

    return findings


# ── BSD ─────────────────────────────────────────────────────────────

def _check_auth_logs_bsd(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    log_paths = ['/var/log/authlog', '/var/log/auth.log', '/var/log/secure']
    for path in log_paths:
        if os.path.isfile(path):
            try:
                with open(path) as f:
                    content = f.readlines()[-2000:]
                _analyze_auth_lines(content, findings)
                return findings
            except PermissionError:
                continue

    findings.append({
        'name': 'Auth Logs',
        'status': 'info',
        'detail': 'Cannot read authentication logs.',
        'severity': 'info', 'fix': None,
    })
    return findings


# ── Shared helpers ──────────────────────────────────────────────────

def _analyze_auth_lines(lines, findings):
    """Analyze auth log lines for failed login patterns."""
    if isinstance(lines, str):
        lines = lines.splitlines()

    failed = [l for l in lines
              if isinstance(l, str) and ('failed' in l.lower() or 'invalid user' in l.lower())]

    if len(failed) > 50:
        findings.append({
            'name': f'Failed Logins: {len(failed)} (last 2000 log lines)',
            'status': 'warn',
            'detail': 'High number of failed login attempts detected.',
            'severity': 'medium',
            'fix': 'Review auth logs. Consider fail2ban and key-only SSH auth.',
        })
        _extract_ips(failed[-200:], findings)
    elif failed:
        findings.append({
            'name': f'Failed Logins: {len(failed)}',
            'status': 'info',
            'detail': 'Normal level of failed login attempts.',
            'severity': 'ok', 'fix': None,
        })
    else:
        findings.append({
            'name': 'Failed Logins',
            'status': 'pass',
            'detail': 'No failed login attempts found in recent logs.',
            'severity': 'ok', 'fix': None,
        })


def _extract_ips(lines, findings):
    """Extract and report top attacking IPs from log lines."""
    text = '\n'.join(l if isinstance(l, str) else str(l) for l in lines)
    ips = re.findall(r'from (\d+\.\d+\.\d+\.\d+)', text)
    if ips:
        top = Counter(ips).most_common(5)
        detail = ', '.join(f'{ip} ({c}x)' for ip, c in top)
        findings.append({
            'name': 'Top Offending IPs',
            'status': 'info',
            'detail': detail,
            'severity': 'info',
            'fix': 'Consider blocking these IPs with your firewall.',
        })
