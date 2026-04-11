"""Sysinfo contribution — current host snapshot.

The sysinfo app doesn't store historical data (the graphs app does
that). Until graphs is integrated as a contributor too, this section
just reports the live load + uptime + memory + disk at the moment of
report generation.
"""

from . import SectionContribution


def contribute(start_dt, end_dt, **opts):
    body_lines = ['## Host snapshot at report time']

    # Load
    try:
        with open('/proc/loadavg') as f:
            parts = f.read().split()
        body_lines.append('')
        body_lines.append(f'Load average: **{parts[0]}** (1m), **{parts[1]}** (5m), **{parts[2]}** (15m).')
    except Exception:
        pass

    # Memory
    try:
        with open('/proc/meminfo') as f:
            mem = {}
            for line in f:
                if ':' in line:
                    k, v = line.split(':', 1)
                    mem[k.strip()] = int(v.strip().split()[0])
        total_gb = mem.get('MemTotal', 0) / 1024 / 1024
        avail_gb = mem.get('MemAvailable', 0) / 1024 / 1024
        used_pct = (1 - (mem.get('MemAvailable', 0) / mem.get('MemTotal', 1))) * 100
        body_lines.append('')
        body_lines.append(f'Memory: **{used_pct:.0f}%** used of {total_gb:.1f} GB total ({avail_gb:.1f} GB available).')
    except Exception:
        pass

    # Disk
    try:
        import shutil
        usage = shutil.disk_usage('/')
        used_pct = usage.used / usage.total * 100
        body_lines.append('')
        body_lines.append(f'Disk: **{used_pct:.0f}%** used of {usage.total / 1024**3:.0f} GB total ({usage.free / 1024**3:.0f} GB free).')
    except Exception:
        pass

    # Uptime
    try:
        with open('/proc/uptime') as f:
            secs = float(f.read().split()[0])
        days = secs / 86400
        body_lines.append('')
        body_lines.append(f'Uptime: **{days:.1f} days**.')
    except Exception:
        pass

    if len(body_lines) <= 1:
        return []

    return [SectionContribution(
        title='System',
        body='\n'.join(body_lines),
        sidenotes='Sysinfo currently reports a snapshot only. The graphs app holds the historical series; integrating graphs as a contributor is the next step.',
    )]
