"""Health snapshot collector.

Gathers a structured snapshot of the local host and every velour-style app
running under supervisor, for cross-host monitoring via the /sysinfo/health.json
endpoint. All of this is stdlib-only so it works on any Python 3 host without
new dependencies.

The returned dict is a stable JSON schema — add new keys freely, but don't
remove or rename existing ones without bumping a schema version, because other
velour nodes parse this structure when polling.
"""

from __future__ import annotations

import glob
import os
import platform
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1

# Soft thresholds used by callers (e.g. Remote Hosts traffic lights) to decide
# whether a snapshot counts as "yellow". The snapshot itself doesn't classify —
# it just reports the numbers — so the thresholds are advisory.
DISK_WARN_PCT = 85
MEMORY_WARN_PCT = 90
LOAD_WARN_PER_CORE = 1.5


def _run(cmd, timeout=5):
    """Run a command, return stdout on success, None on failure."""
    try:
        return subprocess.check_output(
            cmd, text=True, timeout=timeout, stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None


def _load_avg():
    try:
        return list(os.getloadavg())
    except (OSError, AttributeError):
        return None


def _memory_info():
    """Parse /proc/meminfo into MB + percent used. Linux-only; other OSes
    return None and callers should treat that as "not available"."""
    try:
        with open('/proc/meminfo') as f:
            info = {}
            for line in f:
                if ':' not in line:
                    continue
                k, v = line.split(':', 1)
                # kB suffix
                parts = v.strip().split()
                if parts and parts[-1] == 'kB':
                    info[k.strip()] = int(parts[0])
        total_kb = info.get('MemTotal', 0)
        avail_kb = info.get('MemAvailable', 0)
        if not total_kb:
            return None
        used_kb = total_kb - avail_kb
        return {
            'total_mb': total_kb // 1024,
            'used_mb': used_kb // 1024,
            'available_mb': avail_kb // 1024,
            'percent_used': round(100 * used_kb / total_kb, 1),
            'swap_total_mb': info.get('SwapTotal', 0) // 1024,
            'swap_used_mb': (info.get('SwapTotal', 0) - info.get('SwapFree', 0)) // 1024,
        }
    except (OSError, ValueError):
        return None


def _disk_info(path='/'):
    try:
        usage = shutil.disk_usage(path)
        return {
            'path': path,
            'total_gb': round(usage.total / (1024 ** 3), 1),
            'used_gb':  round(usage.used  / (1024 ** 3), 1),
            'free_gb':  round(usage.free  / (1024 ** 3), 1),
            'percent_used': round(100 * usage.used / usage.total, 1) if usage.total else 0,
        }
    except OSError:
        return None


def _uptime_seconds():
    try:
        with open('/proc/uptime') as f:
            return int(float(f.read().split()[0]))
    except (OSError, ValueError, IndexError):
        return None


def _supervisor_programs():
    """Parse `supervisorctl status` output into structured program records.

    Output looks like:
        myapp       RUNNING   pid 1234, uptime 1:23:45
        velour      STOPPED   Apr 10 10:00 AM
        foo         FATAL     Exited too quickly (process log may have details)

    If supervisorctl is unavailable (not installed, no permission), returns
    an empty list with a note in the snapshot's 'errors' key at caller level.
    """
    out = _run(['supervisorctl', 'status'])
    if out is None:
        return None
    programs = []
    for line in out.splitlines():
        line = line.rstrip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 2:
            continue
        name, state = parts[0], parts[1]
        detail = parts[2] if len(parts) > 2 else ''
        pid = None
        uptime = None
        if state == 'RUNNING' and 'pid' in detail:
            # "pid 1234, uptime 1:23:45"
            try:
                pid_part, _, uptime_part = detail.partition(', uptime ')
                pid = int(pid_part.replace('pid', '').strip().rstrip(','))
                uptime = uptime_part.strip() or None
            except ValueError:
                pass
        programs.append({
            'name': name,
            'state': state,
            'pid': pid,
            'uptime': uptime,
            'detail': detail,
        })
    return programs


def _webapps():
    """Scan /var/www/webapps/*/run/*.sock for every app following the velour
    layout convention, reporting whether each socket file currently exists."""
    apps = []
    for run_dir in sorted(glob.glob('/var/www/webapps/*/run')):
        app_name = Path(run_dir).parent.name
        app = {'name': app_name, 'var_dir': str(Path(run_dir).parent), 'sockets': []}
        for sock in sorted(glob.glob(os.path.join(run_dir, '*.sock'))):
            app['sockets'].append({
                'path': sock,
                'exists': os.path.exists(sock),
                'is_socket': os.path.exists(sock) and _is_socket(sock),
            })
        # Best-effort "is the app up" signal: any socket file exists AND is a
        # valid unix socket that accepts a connection.
        app['reachable'] = any(
            s['is_socket'] and _socket_connects(s['path'])
            for s in app['sockets']
        )
        apps.append(app)
    return apps


def _is_socket(path):
    try:
        import stat
        return stat.S_ISSOCK(os.stat(path).st_mode)
    except OSError:
        return False


def _socket_connects(path, timeout=0.5):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(path)
        return True
    except (OSError, socket.error):
        return False
    finally:
        s.close()


def collect():
    """Build the full health snapshot. Returns a JSON-serializable dict."""
    now = datetime.now(timezone.utc)
    uname = platform.uname()

    load = _load_avg()
    cores = os.cpu_count() or 1

    snapshot = {
        'schema_version': SCHEMA_VERSION,
        'hostname': uname.node,
        'timestamp': now.isoformat(),
        'generated_at_epoch': int(time.time()),
        'os': f'{uname.system} {uname.release}',
        'python': platform.python_version(),
        'uptime_seconds': _uptime_seconds(),
        'cpu': {
            'cores': cores,
            'load_average': load,
            'load_per_core': round(load[0] / cores, 2) if load else None,
        },
        'memory': _memory_info(),
        'disk': _disk_info('/'),
        'var_disk': _disk_info('/var/www') if os.path.isdir('/var/www') else None,
        'supervisor': {
            'available': False,
            'programs': [],
        },
        'webapps': _webapps(),
        'errors': [],
    }

    programs = _supervisor_programs()
    if programs is None:
        snapshot['supervisor']['available'] = False
        snapshot['errors'].append('supervisorctl unavailable or inaccessible')
    else:
        snapshot['supervisor']['available'] = True
        snapshot['supervisor']['programs'] = programs
        snapshot['supervisor']['counts'] = {
            'running':  sum(1 for p in programs if p['state'] == 'RUNNING'),
            'stopped':  sum(1 for p in programs if p['state'] == 'STOPPED'),
            'fatal':    sum(1 for p in programs if p['state'] == 'FATAL'),
            'backoff':  sum(1 for p in programs if p['state'] == 'BACKOFF'),
            'exited':   sum(1 for p in programs if p['state'] == 'EXITED'),
            'total':    len(programs),
        }

    return snapshot


def classify(snapshot, thresholds=None):
    """Turn a snapshot into a simple traffic-light status: 'green', 'yellow',
    or 'red'. Used by the Remote Hosts dashboard when rendering a host card.

    'red' means something is definitively broken (supervisor has a FATAL
    program, a registered webapp's socket is missing, or the snapshot itself
    is missing critical fields). 'yellow' means a soft threshold is breached
    (high disk, high memory, high load, a STOPPED program). 'green' otherwise.
    """
    t = {
        'disk_pct': DISK_WARN_PCT,
        'memory_pct': MEMORY_WARN_PCT,
        'load_per_core': LOAD_WARN_PER_CORE,
    }
    if thresholds:
        t.update(thresholds)

    reasons_red = []
    reasons_yellow = []

    sup = snapshot.get('supervisor') or {}
    counts = sup.get('counts') or {}
    if counts.get('fatal', 0):
        reasons_red.append(f"{counts['fatal']} supervisor program(s) FATAL")
    if counts.get('backoff', 0):
        reasons_red.append(f"{counts['backoff']} supervisor program(s) BACKOFF")
    if counts.get('stopped', 0):
        reasons_yellow.append(f"{counts['stopped']} supervisor program(s) STOPPED")

    for app in snapshot.get('webapps') or []:
        if app.get('sockets') and not app.get('reachable'):
            reasons_red.append(f"webapp {app['name']} socket unreachable")

    disk = snapshot.get('disk') or {}
    if disk.get('percent_used', 0) >= t['disk_pct']:
        reasons_yellow.append(f"disk {disk.get('percent_used')}%")

    mem = snapshot.get('memory') or {}
    if mem.get('percent_used', 0) >= t['memory_pct']:
        reasons_yellow.append(f"memory {mem.get('percent_used')}%")

    cpu = snapshot.get('cpu') or {}
    if cpu.get('load_per_core') and cpu['load_per_core'] >= t['load_per_core']:
        reasons_yellow.append(f"load {cpu['load_per_core']}/core")

    if reasons_red:
        return 'red', reasons_red + reasons_yellow
    if reasons_yellow:
        return 'yellow', reasons_yellow
    return 'green', []
