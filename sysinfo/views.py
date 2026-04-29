import hmac
import os
import platform
import pwd
import subprocess
import time

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from . import health


_PAGESIZE = os.sysconf('SC_PAGESIZE') if hasattr(os, 'sysconf') else 4096
# Cache username lookups — /etc/passwd doesn't change between two
# /proc reads 100ms apart.
_USER_CACHE = {}


def _run(cmd, default='N/A'):
    try:
        return subprocess.check_output(cmd, text=True, timeout=5).strip()
    except Exception:
        return default


def _basic_block():
    """Static info — only collected on initial render, not on poll."""
    uname = platform.uname()
    # Kernel `uname.version` is the noisy build banner ("#1 SMP …").
    # Trim to just the timestamp suffix; the release line carries the
    # version number people actually want.
    kernel = uname.version
    if len(kernel) > 60:
        kernel = kernel[:57] + '…'
    return {
        'Hostname': uname.node,
        'OS': f'{uname.system} {uname.release}',
        'Architecture': uname.machine,
        'Kernel': kernel,
        'Python': platform.python_version(),
        'Current User': os.environ.get('USER', 'unknown'),
        'Home Directory': os.path.expanduser('~'),
        'Uptime': _run(['uptime', '-p']),
    }


def _cpu_block():
    cpu = {}
    try:
        with open('/proc/cpuinfo') as f:
            cpuinfo = f.read()
        model = [l.split(':')[1].strip() for l in cpuinfo.splitlines() if 'model name' in l]
        cpu['Model'] = model[0] if model else 'N/A'
        cpu['Cores'] = str(os.cpu_count())
    except Exception:
        cpu['Cores'] = str(os.cpu_count() or 'N/A')
    try:
        with open('/proc/loadavg') as f:
            parts = f.read().strip().split()
        cores = max(1, os.cpu_count() or 1)
        # Show ratio so the reader can tell at a glance whether load is
        # actually a problem on this box (load 4 on 8 cores ≠ load 4 on 2).
        cpu['Load (1m / 5m / 15m)'] = (
            f'{parts[0]} / {parts[1]} / {parts[2]}  '
            f'({float(parts[0]) / cores:.0%} of {cores} cores)'
        )
    except Exception:
        pass
    return cpu


def _memory_block():
    memory = {}
    try:
        with open('/proc/meminfo') as f:
            meminfo = f.read()
        mem = {}
        for line in meminfo.splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                mem[k.strip()] = v.strip()
        total_kb = int(mem.get('MemTotal', '0').replace(' kB', '').strip())
        avail_kb = int(mem.get('MemAvailable', '0').replace(' kB', '').strip())
        used_kb = total_kb - avail_kb
        memory['Total'] = f'{total_kb // 1024} MB'
        memory['Available'] = f'{avail_kb // 1024} MB'
        memory['Used'] = f'{used_kb // 1024} MB ({100 * used_kb // total_kb}%)' if total_kb else '0'
        swap_total = int(mem.get('SwapTotal', '0').replace(' kB', '').strip())
        swap_free = int(mem.get('SwapFree', '0').replace(' kB', '').strip())
        memory['Swap Total'] = f'{swap_total // 1024} MB'
        memory['Swap Used'] = f'{(swap_total - swap_free) // 1024} MB'
    except Exception:
        memory['Info'] = 'Could not read /proc/meminfo'
    return memory


def _disk_lines():
    raw = _run(['df', '-h', '--output=target,size,used,avail,pcent'], default='')
    return [l for l in raw.splitlines() if l.strip()]


def _net_lines():
    raw = _run(['ip', '-brief', 'addr'], default='')
    return [l for l in raw.splitlines() if l.strip()]


def _ps_lines():
    raw = _run(['ps', 'aux', '--sort=-pcpu'], default='')
    return raw.splitlines()[:16] if raw else []  # header + 15


def _read_pid_stat(pid):
    """Parse /proc/<pid>/stat → (pid, comm, utime+stime, rss_pages).

    Returns None if the process disappeared mid-read (PIDs vanish
    between scandir and open all the time on a busy system).

    The comm field can contain spaces and parentheses ("(my (program))"),
    so we anchor on the LAST ')' rather than splitting on whitespace.
    """
    try:
        with open(f'/proc/{pid}/stat') as f:
            data = f.read()
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    end = data.rfind(')')
    start = data.find('(')
    if start < 0 or end < start:
        return None
    comm = data[start + 1:end]
    rest = data[end + 2:].split()
    # /proc/[pid]/stat field 14 is utime, 15 is stime, 24 is rss (pages).
    # rest[0] is field 3 (state), so utime=rest[11], stime=rest[12], rss=rest[21].
    try:
        utime = int(rest[11])
        stime = int(rest[12])
        rss   = int(rest[21])
    except (IndexError, ValueError):
        return None
    return pid, comm, utime + stime, rss


def _read_proc_stat_total():
    """Aggregated CPU jiffies across all CPUs from /proc/stat first line."""
    try:
        with open('/proc/stat') as f:
            parts = [int(v) for v in f.readline().split()[1:]]
        return sum(parts)
    except Exception:
        return 0


def _username_for_pid(pid):
    """Lookup the effective UID of a process and resolve to a name."""
    try:
        with open(f'/proc/{pid}/status') as f:
            for line in f:
                if line.startswith('Uid:'):
                    uid = int(line.split()[2])  # effective uid
                    if uid in _USER_CACHE:
                        return _USER_CACHE[uid]
                    try:
                        name = pwd.getpwuid(uid).pw_name
                    except KeyError:
                        name = str(uid)
                    _USER_CACHE[uid] = name
                    return name
    except Exception:
        pass
    return '?'


def _ps_table(top_n=20, sample_window_s=0.1):
    """Top processes ranked by *current* %CPU (Irix mode — % of one core).

    Walks /proc twice, ~100 ms apart, and computes Δticks(pid) /
    (Δticks(total) / ncpus) × 100. That's what `top` displays — a
    process pegging one core shows ~100%, on multi-threaded processes
    you can exceed 100%. Replaces the lifetime-averaged %CPU that
    `ps aux` shows (which is mostly 0.0 on modern systems).
    """
    ncpus = max(1, os.cpu_count() or 1)

    def _snapshot():
        # Returns ({pid: (utime+stime, rss_pages, comm)}, total_jiffies)
        out = {}
        try:
            entries = os.listdir('/proc')
        except OSError:
            return out, 0
        for name in entries:
            if not name.isdigit():
                continue
            stat = _read_pid_stat(name)
            if stat is None:
                continue
            pid, comm, ticks, rss = stat
            out[pid] = (ticks, rss, comm)
        return out, _read_proc_stat_total()

    s1, t1 = _snapshot()
    if not s1:
        return []
    time.sleep(sample_window_s)
    s2, t2 = _snapshot()

    dtotal = max(1, t2 - t1)
    # Irix mode: divide by per-cpu jiffies so a single fully-loaded core
    # reads as 100%.
    per_cpu_total = dtotal / ncpus

    # Read mem total once for %MEM denominator.
    mem_total_kb = 0
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    mem_total_kb = int(line.split()[1])
                    break
    except Exception:
        pass
    mem_total_kb = mem_total_kb or 1

    rows = []
    for pid, (ticks2, rss_pages, comm) in s2.items():
        if pid not in s1:
            continue  # newly-spawned process — no delta available
        ticks1 = s1[pid][0]
        d_ticks = max(0, ticks2 - ticks1)
        pcpu = (d_ticks / per_cpu_total * 100) if per_cpu_total else 0.0
        rss_kb = rss_pages * _PAGESIZE // 1024
        pmem = (rss_kb / mem_total_kb * 100) if mem_total_kb else 0.0
        rows.append({
            'pid':    int(pid),
            'user':   _username_for_pid(pid),
            'pcpu':   round(pcpu, 1),
            'pmem':   round(pmem, 1),
            'rss_kb': rss_kb,
            'comm':   comm,
        })

    rows.sort(key=lambda r: r['pcpu'], reverse=True)
    return rows[:top_n]


def _who_lines():
    raw = _run(['who'], default='')
    return [l for l in raw.splitlines() if l.strip()]


def _live_snapshot():
    """The live-changeable bits — what /sysinfo/snapshot/ returns and
    what the JS poller swaps into the page."""
    return {
        'cpu': _cpu_block(),
        'memory': _memory_block(),
        'disk_lines': _disk_lines(),
        'net_lines': _net_lines(),
        'ps_rows': _ps_table(),
        'who_lines': _who_lines(),
    }


@login_required
def sysinfo_home(request):
    context = _live_snapshot()
    context['basic'] = _basic_block()
    return render(request, 'sysinfo/home.html', context)


@login_required
@require_GET
def sysinfo_snapshot(request):
    """JSON of the live-changeable blocks. JS polls this every few
    seconds and replaces the rendered tables in place."""
    return JsonResponse(_live_snapshot())


def _read_health_token():
    """Return the contents of BASE_DIR/health_token.txt, or None if missing.
    The file is the only source of truth; no env-var fallback, no default."""
    token_file = settings.BASE_DIR / 'health_token.txt'
    if not token_file.is_file():
        return None
    try:
        token = token_file.read_text().strip()
        return token or None
    except OSError:
        return None


def _extract_bearer_token(request):
    """Pull a token out of an Authorization: Bearer <token> header, or from
    a ?token= query parameter as a fallback for quick curl/browser testing."""
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if auth.startswith('Bearer '):
        return auth[len('Bearer '):].strip()
    return request.GET.get('token', '').strip() or None


@csrf_exempt
@require_GET
def health_json(request):
    """Cross-host health snapshot. Returns JSON suitable for a Remote Hosts
    dashboard to poll.

    Auth model:
      - If BASE_DIR/health_token.txt does not exist, pretend the endpoint
        doesn't exist at all (404). This keeps a stock / local-dev install
        from accidentally exposing host data.
      - If the file exists but the presented bearer token doesn't match,
        return 401 without revealing anything about the snapshot.
      - Matching token → 200 with the full snapshot payload.
    """
    server_token = _read_health_token()
    if server_token is None:
        raise Http404('health endpoint not configured')

    client_token = _extract_bearer_token(request)
    if not client_token or not hmac.compare_digest(server_token, client_token):
        return JsonResponse({'error': 'unauthorized'}, status=401)

    snapshot = health.collect()
    status, reasons = health.classify(snapshot)
    snapshot['status'] = status
    snapshot['status_reasons'] = reasons
    return JsonResponse(snapshot)
