import hmac
import os
import platform
import subprocess

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from . import health


def _run(cmd, default='N/A'):
    try:
        return subprocess.check_output(cmd, text=True, timeout=5).strip()
    except Exception:
        return default


@login_required
def sysinfo_home(request):
    # Basic
    uname = platform.uname()
    basic = {
        'Hostname': uname.node,
        'OS': f'{uname.system} {uname.release}',
        'Architecture': uname.machine,
        'Kernel': uname.version,
        'Python': platform.python_version(),
        'Current User': os.environ.get('USER', 'unknown'),
        'Home Directory': os.path.expanduser('~'),
        'Uptime': _run(['uptime', '-p']),
    }

    # CPU
    cpu = {}
    try:
        with open('/proc/cpuinfo') as f:
            cpuinfo = f.read()
        model = [l.split(':')[1].strip() for l in cpuinfo.splitlines() if 'model name' in l]
        cpu['Model'] = model[0] if model else 'N/A'
        cpu['Cores'] = str(os.cpu_count())
    except Exception:
        cpu['Cores'] = str(os.cpu_count() or 'N/A')

    load = _run(['cat', '/proc/loadavg'])
    if load != 'N/A':
        parts = load.split()
        cpu['Load (1m / 5m / 15m)'] = f'{parts[0]} / {parts[1]} / {parts[2]}'

    # Memory
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
        memory['Used'] = f'{used_kb // 1024} MB ({100 * used_kb // total_kb}%)'
        swap_total = int(mem.get('SwapTotal', '0').replace(' kB', '').strip())
        swap_free = int(mem.get('SwapFree', '0').replace(' kB', '').strip())
        memory['Swap Total'] = f'{swap_total // 1024} MB'
        memory['Swap Used'] = f'{(swap_total - swap_free) // 1024} MB'
    except Exception:
        memory['Info'] = 'Could not read /proc/meminfo'

    # Disk
    disk_raw = _run(['df', '-h', '--output=target,size,used,avail,pcent'], default='')
    disk_lines = [l for l in disk_raw.splitlines() if l.strip()] if disk_raw else []

    # Network
    net_raw = _run(['ip', '-brief', 'addr'], default='')
    net_lines = [l for l in net_raw.splitlines() if l.strip()] if net_raw else []

    # Processes (top 15 by CPU)
    ps_raw = _run(['ps', 'aux', '--sort=-pcpu'], default='')
    ps_lines = ps_raw.splitlines()[:16] if ps_raw else []  # header + 15

    # Logged-in users
    who_raw = _run(['who'], default='')
    who_lines = [l for l in who_raw.splitlines() if l.strip()] if who_raw else []

    context = {
        'basic': basic,
        'cpu': cpu,
        'memory': memory,
        'disk_lines': disk_lines,
        'net_lines': net_lines,
        'ps_lines': ps_lines,
        'who_lines': who_lines,
    }
    return render(request, 'sysinfo/home.html', context)


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
