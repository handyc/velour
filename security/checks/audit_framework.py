"""Audit framework (auditd / OpenBSM / Windows Audit) — cross-platform."""

import os

from security.platform import PlatformInfo
from security.runner import run, run_powershell, command_exists


def check_audit_framework(pinfo: PlatformInfo) -> list[dict]:
    if pinfo.os_family == 'linux':
        return _check_auditd(pinfo)
    elif pinfo.os_family == 'darwin':
        return _check_openbsm(pinfo)
    elif pinfo.os_family == 'windows':
        return _check_windows_audit(pinfo)
    elif pinfo.os_family in ('freebsd', 'openbsd'):
        return _check_openbsm(pinfo)
    return []


def _check_auditd(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # Check if auditd is running
    status = run(['auditctl', '-s'])
    if status and 'enabled' in status.lower():
        findings.append({
            'name': 'Audit Daemon: Active',
            'status': 'pass',
            'detail': 'auditd is running and enabled.',
            'severity': 'ok', 'fix': None,
        })

        # Check number of rules
        rules = run(['auditctl', '-l'])
        if rules:
            rule_lines = [l for l in rules.splitlines() if l.strip() and 'No rules' not in l]
            if rule_lines:
                findings.append({
                    'name': f'Audit Rules: {len(rule_lines)} loaded',
                    'status': 'pass',
                    'detail': '\n'.join(rule_lines[:10]) + ('\n...' if len(rule_lines) > 10 else ''),
                    'severity': 'ok', 'fix': None,
                })
            else:
                findings.append({
                    'name': 'Audit Rules: None',
                    'status': 'warn',
                    'detail': 'auditd is running but has no rules loaded.',
                    'severity': 'medium',
                    'fix': 'Add audit rules in /etc/audit/rules.d/ — consider CIS benchmark rules.',
                })

        # Check log rotation
        audit_conf = '/etc/audit/auditd.conf'
        if os.path.isfile(audit_conf):
            try:
                with open(audit_conf) as f:
                    conf = f.read()
                if 'max_log_file_action' in conf.lower():
                    findings.append({
                        'name': 'Audit Log Rotation: Configured',
                        'status': 'pass',
                        'detail': 'Audit log rotation is configured.',
                        'severity': 'ok', 'fix': None,
                    })
            except PermissionError:
                pass

    elif command_exists('auditd') or command_exists('auditctl'):
        findings.append({
            'name': 'Audit Daemon: Not Running',
            'status': 'fail',
            'detail': 'auditd is installed but not running.',
            'severity': 'high',
            'fix': 'sudo systemctl enable --now auditd',
        })
    else:
        findings.append({
            'name': 'Audit Daemon: Not Installed',
            'status': 'warn',
            'detail': 'auditd is not installed. System call auditing is not available.',
            'severity': 'medium',
            'fix': 'Install auditd for your distribution.',
        })

    return findings


def _check_openbsm(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    audit_control = '/etc/security/audit_control'
    if os.path.isfile(audit_control):
        try:
            with open(audit_control) as f:
                content = f.read()
            findings.append({
                'name': 'OpenBSM Audit: Configured',
                'status': 'pass',
                'detail': 'Audit control file exists at /etc/security/audit_control.',
                'severity': 'ok', 'fix': None,
            })

            # Check flags
            if 'flags:' in content:
                for line in content.splitlines():
                    if line.startswith('flags:'):
                        flags = line.split(':', 1)[1].strip()
                        if 'lo' in flags:
                            findings.append({
                                'name': 'Audit: Login/Logout Events',
                                'status': 'pass',
                                'detail': f'Audit flags include login events: {flags}',
                                'severity': 'ok', 'fix': None,
                            })
        except PermissionError:
            findings.append({
                'name': 'Audit Configuration',
                'status': 'info',
                'detail': 'Cannot read audit_control (permission denied).',
                'severity': 'info', 'fix': None,
            })
    else:
        if pinfo.os_family == 'darwin':
            findings.append({
                'name': 'macOS Audit',
                'status': 'info',
                'detail': 'OpenBSM audit_control not found. macOS uses Unified Logging by default.',
                'severity': 'info', 'fix': None,
            })

    return findings


def _check_windows_audit(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    result = run_powershell('auditpol /get /category:* 2>$null')
    if result:
        lines = result.splitlines()
        no_auditing = [l for l in lines if 'No Auditing' in l]
        total = len([l for l in lines if l.strip() and 'Subcategory' not in l
                     and '---' not in l and 'Category' not in l])

        if no_auditing and len(no_auditing) > total * 0.5:
            findings.append({
                'name': 'Windows Audit Policy: Mostly Disabled',
                'status': 'fail',
                'detail': f'{len(no_auditing)}/{total} audit subcategories have no auditing.',
                'severity': 'high',
                'fix': 'Enable recommended audit policies via Group Policy or: '
                       'auditpol /set /subcategory:"Logon" /success:enable /failure:enable',
            })
        else:
            findings.append({
                'name': 'Windows Audit Policy: Configured',
                'status': 'pass',
                'detail': f'{total - len(no_auditing)}/{total} audit subcategories are active.',
                'severity': 'ok', 'fix': None,
            })

        # Key subcategories that should always be audited
        important = ['Logon', 'Account Lockout', 'Special Logon',
                      'Audit Policy Change', 'Security Group Management']
        for subcat in important:
            for l in lines:
                if subcat in l and 'No Auditing' in l:
                    findings.append({
                        'name': f'Audit: {subcat} Not Audited',
                        'status': 'warn',
                        'detail': f'{subcat} events are not being audited.',
                        'severity': 'medium',
                        'fix': f'auditpol /set /subcategory:"{subcat}" /success:enable /failure:enable',
                    })
    else:
        findings.append({
            'name': 'Windows Audit Policy',
            'status': 'unknown',
            'detail': 'Could not query audit policy. Requires elevated privileges.',
            'severity': 'info', 'fix': None,
        })

    return findings
