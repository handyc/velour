"""SUID/SGID binary audit — Unix-only."""

from security.platform import PlatformInfo, is_unix
from security.runner import run


# Known-safe SUID binaries (common across distros)
KNOWN_SAFE_SUID = {
    '/usr/bin/sudo', '/usr/bin/su', '/usr/bin/passwd', '/usr/bin/chsh',
    '/usr/bin/chfn', '/usr/bin/newgrp', '/usr/bin/gpasswd', '/usr/bin/mount',
    '/usr/bin/umount', '/usr/bin/fusermount', '/usr/bin/fusermount3',
    '/usr/bin/pkexec', '/usr/bin/crontab', '/usr/bin/at',
    '/usr/lib/dbus-1.0/dbus-daemon-launch-helper',
    '/usr/lib/openssh/ssh-keysign',
    '/usr/lib/policykit-1/polkit-agent-helper-1',
    '/usr/sbin/pppd', '/usr/sbin/unix_chkpwd',
    '/bin/su', '/bin/mount', '/bin/umount', '/bin/ping', '/bin/ping6',
    '/usr/bin/ping', '/usr/bin/traceroute6',
    '/sbin/mount.nfs', '/usr/sbin/mount.nfs',
}


def check_suid_sgid(pinfo: PlatformInfo) -> list[dict]:
    if not is_unix(pinfo):
        return []

    findings = []

    # Find SUID binaries (limit search depth and time)
    suid_output = run(
        'find / -perm -4000 -type f '
        '-not -path "/proc/*" -not -path "/sys/*" -not -path "/snap/*" '
        '2>/dev/null | head -50',
        shell=True, timeout=30,
    )

    if suid_output:
        suid_files = [f.strip() for f in suid_output.splitlines() if f.strip()]
        unknown_suid = [f for f in suid_files if f not in KNOWN_SAFE_SUID]

        findings.append({
            'name': f'SUID Binaries: {len(suid_files)} found',
            'status': 'info',
            'detail': '\n'.join(suid_files[:20]) + ('\n...' if len(suid_files) > 20 else ''),
            'severity': 'info', 'fix': None,
        })

        if unknown_suid:
            findings.append({
                'name': f'SUID: {len(unknown_suid)} Non-Standard Binaries',
                'status': 'warn',
                'detail': 'Unexpected SUID binaries:\n' + '\n'.join(unknown_suid[:15]),
                'severity': 'medium',
                'fix': 'Review each binary. Remove SUID bit if not needed: chmod u-s <file>',
            })
    else:
        findings.append({
            'name': 'SUID Scan',
            'status': 'info',
            'detail': 'Could not scan for SUID binaries (may need root).',
            'severity': 'info', 'fix': None,
        })

    # Find SGID binaries
    sgid_output = run(
        'find / -perm -2000 -type f '
        '-not -path "/proc/*" -not -path "/sys/*" -not -path "/snap/*" '
        '2>/dev/null | head -30',
        shell=True, timeout=30,
    )

    if sgid_output:
        sgid_files = [f.strip() for f in sgid_output.splitlines() if f.strip()]
        if sgid_files:
            findings.append({
                'name': f'SGID Binaries: {len(sgid_files)} found',
                'status': 'info',
                'detail': '\n'.join(sgid_files[:15]),
                'severity': 'info', 'fix': None,
            })

    return findings
