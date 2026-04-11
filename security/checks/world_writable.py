"""World-writable file/directory audit — Unix-only."""

from security.platform import PlatformInfo, is_unix
from security.runner import run


def check_world_writable(pinfo: PlatformInfo) -> list[dict]:
    if not is_unix(pinfo):
        return []

    findings = []

    # World-writable files in sensitive directories
    ww_output = run(
        'find /etc /usr /var/log -xdev -type f -perm -0002 '
        '-not -path "/proc/*" -not -path "/sys/*" '
        '2>/dev/null | head -25',
        shell=True, timeout=20,
    )

    if ww_output:
        ww_files = [f.strip() for f in ww_output.splitlines() if f.strip()]
        if ww_files:
            findings.append({
                'name': f'World-Writable Files: {len(ww_files)} in sensitive dirs',
                'status': 'fail',
                'detail': 'World-writable files in /etc, /usr, or /var/log:\n'
                          + '\n'.join(ww_files[:15]),
                'severity': 'high',
                'fix': 'Remove world-write permission: chmod o-w <file>',
            })
        else:
            findings.append({
                'name': 'World-Writable Files',
                'status': 'pass',
                'detail': 'No world-writable files found in sensitive directories.',
                'severity': 'ok', 'fix': None,
            })
    else:
        findings.append({
            'name': 'World-Writable Files',
            'status': 'pass',
            'detail': 'No world-writable files found in /etc, /usr, /var/log.',
            'severity': 'ok', 'fix': None,
        })

    # World-writable directories without sticky bit (beyond /tmp)
    ww_dirs = run(
        'find / -maxdepth 3 -xdev -type d -perm -0002 ! -perm -1000 '
        '-not -path "/proc/*" -not -path "/sys/*" -not -path "/dev/*" '
        '2>/dev/null | head -15',
        shell=True, timeout=15,
    )

    if ww_dirs:
        dirs = [d.strip() for d in ww_dirs.splitlines() if d.strip()]
        if dirs:
            findings.append({
                'name': f'Unsafe World-Writable Directories: {len(dirs)}',
                'status': 'fail',
                'detail': 'World-writable directories missing sticky bit:\n' + '\n'.join(dirs),
                'severity': 'high',
                'fix': 'Add sticky bit: chmod +t <directory>',
            })

    return findings
