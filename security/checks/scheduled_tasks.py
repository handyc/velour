"""Scheduled tasks / cron audit — cross-platform."""

import os
import stat

from security.platform import PlatformInfo, is_unix
from security.runner import run, run_powershell, read_file, read_lines


def check_scheduled_tasks(pinfo: PlatformInfo) -> list[dict]:
    if pinfo.os_family == 'linux':
        return _check_cron_linux(pinfo)
    elif pinfo.os_family == 'darwin':
        return _check_scheduled_macos(pinfo)
    elif pinfo.os_family == 'windows':
        return _check_scheduled_windows(pinfo)
    elif pinfo.os_family in ('freebsd', 'openbsd', 'netbsd'):
        return _check_cron_linux(pinfo)  # Same cron structure
    return []


def _check_cron_linux(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # System crontab
    crontab = read_file('/etc/crontab')
    if crontab:
        jobs = [l for l in crontab.splitlines()
                if l.strip() and not l.startswith('#') and not l.startswith('SHELL')
                and not l.startswith('PATH') and not l.startswith('MAILTO')]
        findings.append({
            'name': f'System Crontab: {len(jobs)} entries',
            'status': 'info',
            'detail': '\n'.join(jobs[:10]) if jobs else 'Empty',
            'severity': 'info', 'fix': None,
        })

    # /etc/cron.d
    cron_d = '/etc/cron.d'
    if os.path.isdir(cron_d):
        try:
            files = os.listdir(cron_d)
            findings.append({
                'name': f'Cron.d: {len(files)} files',
                'status': 'info',
                'detail': ', '.join(files[:15]) if files else 'Empty',
                'severity': 'info', 'fix': None,
            })
        except PermissionError:
            pass

    # Check crontab permissions
    for path in ['/etc/crontab', '/etc/cron.d']:
        if os.path.exists(path):
            try:
                mode = os.stat(path).st_mode
                if mode & stat.S_IWOTH:
                    findings.append({
                        'name': f'Cron: World-Writable {path}',
                        'status': 'fail',
                        'detail': f'{path} is world-writable. Anyone can add scheduled tasks.',
                        'severity': 'critical',
                        'fix': f'chmod o-w {path}',
                    })
            except PermissionError:
                pass

    # Check for cron jobs running world-writable scripts
    _check_cron_script_perms('/etc/crontab', findings)

    # User crontabs
    cron_spool = '/var/spool/cron/crontabs'
    if not os.path.isdir(cron_spool):
        cron_spool = '/var/spool/cron'  # RHEL/CentOS location
    if os.path.isdir(cron_spool):
        try:
            user_crons = os.listdir(cron_spool)
            if user_crons:
                findings.append({
                    'name': f'User Crontabs: {len(user_crons)}',
                    'status': 'info',
                    'detail': f'Users with crontabs: {", ".join(user_crons)}',
                    'severity': 'info', 'fix': None,
                })
        except PermissionError:
            pass

    # at jobs
    at_spool = '/var/spool/at'
    if os.path.isdir(at_spool):
        try:
            at_jobs = [f for f in os.listdir(at_spool) if f.startswith('a')]
            if at_jobs:
                findings.append({
                    'name': f'At Jobs: {len(at_jobs)} pending',
                    'status': 'info',
                    'detail': f'{len(at_jobs)} pending at(1) jobs.',
                    'severity': 'info', 'fix': None,
                })
        except PermissionError:
            pass

    # Cron access control
    for access_file, expected in [('/etc/cron.allow', True), ('/etc/cron.deny', False)]:
        if os.path.isfile(access_file):
            findings.append({
                'name': f'Cron Access: {os.path.basename(access_file)} exists',
                'status': 'info',
                'detail': f'{access_file} is present, controlling cron access.',
                'severity': 'info', 'fix': None,
            })

    return findings


def _check_cron_script_perms(crontab_path, findings):
    """Check if any cron jobs reference world-writable scripts."""
    content = read_file(crontab_path)
    if not content:
        return
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) >= 6:
            # The command starts at field index 5 (or 6 if user field present)
            cmd_start = 6 if len(parts) > 6 else 5
            for part in parts[cmd_start:]:
                if part.startswith('/') and os.path.isfile(part):
                    try:
                        mode = os.stat(part).st_mode
                        if mode & stat.S_IWOTH:
                            findings.append({
                                'name': f'Cron: World-Writable Script',
                                'status': 'fail',
                                'detail': f'Cron job executes world-writable file: {part}',
                                'severity': 'critical',
                                'fix': f'chmod o-w {part}',
                            })
                    except (PermissionError, OSError):
                        pass
                    break


def _check_scheduled_macos(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # LaunchDaemons (system-level)
    daemon_dirs = ['/Library/LaunchDaemons', '/System/Library/LaunchDaemons']
    for d in daemon_dirs:
        if os.path.isdir(d):
            try:
                plists = [f for f in os.listdir(d) if f.endswith('.plist')]
                non_apple = [f for f in plists if not f.startswith('com.apple.')]
                if non_apple:
                    findings.append({
                        'name': f'LaunchDaemons ({os.path.basename(os.path.dirname(d))}): {len(non_apple)} third-party',
                        'status': 'info',
                        'detail': ', '.join(non_apple[:10]),
                        'severity': 'info', 'fix': None,
                    })
            except PermissionError:
                pass

    # LaunchAgents (user-level)
    agent_dirs = ['/Library/LaunchAgents']
    home = os.path.expanduser('~')
    user_agents = os.path.join(home, 'Library', 'LaunchAgents')
    if os.path.isdir(user_agents):
        agent_dirs.append(user_agents)

    for d in agent_dirs:
        if os.path.isdir(d):
            try:
                plists = [f for f in os.listdir(d) if f.endswith('.plist')]
                non_apple = [f for f in plists if not f.startswith('com.apple.')]
                if non_apple:
                    findings.append({
                        'name': f'LaunchAgents ({d}): {len(non_apple)} third-party',
                        'status': 'info',
                        'detail': ', '.join(non_apple[:10]),
                        'severity': 'info', 'fix': None,
                    })
            except PermissionError:
                pass

    # User crontab
    user_cron = run(['crontab', '-l'])
    if user_cron and 'no crontab' not in user_cron.lower():
        lines = [l for l in user_cron.splitlines() if l.strip() and not l.startswith('#')]
        if lines:
            findings.append({
                'name': f'User Crontab: {len(lines)} entries',
                'status': 'info',
                'detail': '\n'.join(lines[:5]),
                'severity': 'info', 'fix': None,
            })

    return findings


def _check_scheduled_windows(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    result = run_powershell(
        'Get-ScheduledTask | Where-Object {$_.State -ne "Disabled"} | '
        'Select-Object TaskName, TaskPath, State | Format-Table -AutoSize',
        timeout=15,
    )
    if result:
        lines = [l for l in result.splitlines() if l.strip() and not l.startswith('-')]
        # Filter out header
        data_lines = lines[1:] if lines else []
        findings.append({
            'name': f'Active Scheduled Tasks: {len(data_lines)}',
            'status': 'info',
            'detail': '\n'.join(data_lines[:15]) + ('\n...' if len(data_lines) > 15 else ''),
            'severity': 'info', 'fix': None,
        })

        # Check for tasks running as SYSTEM that are non-Microsoft
        system_tasks = run_powershell(
            'Get-ScheduledTask | Where-Object {$_.State -ne "Disabled"} | '
            'ForEach-Object { $info = $_ | Get-ScheduledTaskInfo -ErrorAction SilentlyContinue; '
            '$action = ($_.Actions | Select-Object -First 1).Execute; '
            'if ($action -and $action -notlike "*Microsoft*" -and $action -notlike "*Windows*") '
            '{ "$($_.TaskName)|$action" } } | Select-Object -First 10',
            timeout=20,
        )
        if system_tasks:
            findings.append({
                'name': 'Non-Microsoft Scheduled Tasks',
                'status': 'info',
                'detail': system_tasks[:300],
                'severity': 'low', 'fix': None,
            })

    return findings
