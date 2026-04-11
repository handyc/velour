"""NTP / time synchronization audit — cross-platform."""

from security.platform import PlatformInfo
from security.runner import run, run_powershell, command_exists


def check_ntp(pinfo: PlatformInfo) -> list[dict]:
    if pinfo.os_family == 'linux':
        return _check_ntp_linux(pinfo)
    elif pinfo.os_family == 'darwin':
        return _check_ntp_macos(pinfo)
    elif pinfo.os_family == 'windows':
        return _check_ntp_windows(pinfo)
    elif pinfo.os_family in ('freebsd', 'openbsd', 'netbsd'):
        return _check_ntp_bsd(pinfo)
    return []


def _check_ntp_linux(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # systemd-timesyncd / timedatectl
    if pinfo.init_system == 'systemd':
        td = run(['timedatectl', 'status'])
        if td:
            if 'synchronized: yes' in td.lower() or 'ntp synchronized: yes' in td.lower():
                findings.append({
                    'name': 'Time Sync: Active',
                    'status': 'pass',
                    'detail': 'System clock is synchronized via NTP.',
                    'severity': 'ok', 'fix': None,
                })
            elif 'synchronized: no' in td.lower() or 'ntp synchronized: no' in td.lower():
                findings.append({
                    'name': 'Time Sync: Not Synchronized',
                    'status': 'warn',
                    'detail': 'System clock is NOT synchronized. This can affect TLS, logging, and Kerberos.',
                    'severity': 'medium',
                    'fix': 'sudo timedatectl set-ntp true',
                })

            if 'ntp service: active' in td.lower() or 'systemd-timesyncd' in td.lower():
                findings.append({
                    'name': 'NTP Service: Running',
                    'status': 'pass',
                    'detail': 'NTP service is active.',
                    'severity': 'ok', 'fix': None,
                })

            return findings

    # Check chronyd
    if command_exists('chronyc'):
        tracking = run(['chronyc', 'tracking'])
        if tracking and 'reference id' in tracking.lower():
            findings.append({
                'name': 'Time Sync (chronyd): Active',
                'status': 'pass',
                'detail': tracking.split('\n')[0] if tracking else 'chronyd is tracking.',
                'severity': 'ok', 'fix': None,
            })
            return findings

    # Check ntpd
    if command_exists('ntpq'):
        peers = run(['ntpq', '-p'])
        if peers and '*' in peers:  # * marks the active peer
            findings.append({
                'name': 'Time Sync (ntpd): Active',
                'status': 'pass',
                'detail': 'ntpd has an active time source.',
                'severity': 'ok', 'fix': None,
            })
            return findings

    findings.append({
        'name': 'Time Sync: Not Detected',
        'status': 'warn',
        'detail': 'No NTP synchronization detected. Accurate time is critical for security.',
        'severity': 'medium',
        'fix': 'Install and enable chronyd or systemd-timesyncd.',
    })
    return findings


def _check_ntp_macos(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    ntp = run(['systemsetup', '-getusingnetworktime'])
    if ntp:
        if 'on' in ntp.lower():
            findings.append({
                'name': 'Network Time: Enabled',
                'status': 'pass',
                'detail': 'macOS network time synchronization is enabled.',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'Network Time: Disabled',
                'status': 'warn',
                'detail': 'Network time is not enabled.',
                'severity': 'medium',
                'fix': 'sudo systemsetup -setusingnetworktime on',
            })

    server = run(['systemsetup', '-getnetworktimeserver'])
    if server:
        findings.append({
            'name': f'NTP Server: {server.split(":")[-1].strip() if ":" in server else server}',
            'status': 'info',
            'detail': server.strip(),
            'severity': 'info', 'fix': None,
        })

    return findings


def _check_ntp_windows(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    w32tm = run(['w32tm', '/query', '/status'])
    if w32tm:
        if 'last successful sync' in w32tm.lower():
            findings.append({
                'name': 'Time Sync: Active',
                'status': 'pass',
                'detail': w32tm[:200],
                'severity': 'ok', 'fix': None,
            })
        elif 'the service has not been started' in w32tm.lower():
            findings.append({
                'name': 'Time Sync: Service Not Running',
                'status': 'warn',
                'detail': 'Windows Time service is not running.',
                'severity': 'medium',
                'fix': 'net start w32time && w32tm /resync',
            })
    else:
        findings.append({
            'name': 'Time Sync',
            'status': 'unknown',
            'detail': 'Could not query Windows Time service.',
            'severity': 'info', 'fix': None,
        })

    return findings


def _check_ntp_bsd(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    if command_exists('ntpq'):
        peers = run(['ntpq', '-p'])
        if peers and '*' in peers:
            findings.append({
                'name': 'Time Sync (ntpd): Active',
                'status': 'pass',
                'detail': 'ntpd has an active peer.',
                'severity': 'ok', 'fix': None,
            })
            return findings

    if command_exists('ntpctl'):  # OpenBSD
        status = run(['ntpctl', '-s', 'status'])
        if status:
            findings.append({
                'name': 'Time Sync (ntpd): Active',
                'status': 'pass',
                'detail': status.split('\n')[0],
                'severity': 'ok', 'fix': None,
            })
            return findings

    findings.append({
        'name': 'Time Sync: Not Detected',
        'status': 'warn',
        'detail': 'No NTP synchronization detected.',
        'severity': 'medium',
        'fix': 'Enable ntpd in /etc/rc.conf.',
    })
    return findings
