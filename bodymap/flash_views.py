"""In-browser flasher for bodymap nodes.

Pick a serial device, click Flash, watch the esptool output stream back.
The browser drives `esptool.py` directly against the pre-built binaries
in `bodymap_firmware/.pio/build/esp32-s3-supermini/` — no PlatformIO
compile on click, so flashing a freshly-built binary is a few seconds
rather than half a minute.

Jobs live in-process in `_JOBS` and log to files under /tmp. Process
restart loses the history; that's fine since flashing is an attended
one-shot action and nobody needs to resume a job after a redeploy.
"""

import glob
import shlex
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


FIRMWARE_DIR = (
    settings.BASE_DIR / 'bodymap_firmware' / '.pio' / 'build' / 'esp32-s3-supermini'
)
FIRMWARE_SRC_DIR = settings.BASE_DIR / 'bodymap_firmware'
PIO_PACKAGES = Path.home() / '.platformio' / 'packages'
ESPTOOL_PATH = PIO_PACKAGES / 'tool-esptoolpy' / 'esptool.py'
BOOT_APP0_PATH = (
    PIO_PACKAGES / 'framework-arduinoespressif32' / 'tools' / 'partitions' / 'boot_app0.bin'
)
PYTHON_PATH = settings.BASE_DIR / 'venv' / 'bin' / 'python'
PIO_PATH = settings.BASE_DIR / 'venv' / 'bin' / 'pio'


_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()


def _serial_devices():
    """List /dev/ttyACM* and /dev/ttyUSB* nodes visible to the Django
    process. On WSL2 these only appear after `usbipd attach --wsl` on the
    Windows side, so the template surfaces a hint when the list is empty."""
    ports = sorted(glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*'))
    return [{'path': p} for p in ports]


def _firmware_status():
    bins = {
        'bootloader': FIRMWARE_DIR / 'bootloader.bin',
        'partitions': FIRMWARE_DIR / 'partitions.bin',
        'firmware':   FIRMWARE_DIR / 'firmware.bin',
    }
    status = {}
    newest = 0.0
    ready = True
    for name, p in bins.items():
        exists = p.is_file()
        mtime  = p.stat().st_mtime if exists else 0.0
        size   = p.stat().st_size  if exists else 0
        if not exists:
            ready = False
        newest = max(newest, mtime)
        status[name] = {'exists': exists, 'mtime': mtime, 'size': size}
    return {'bins': status, 'ready': ready, 'newest_mtime': newest}


def _spawn_job(cmd, label):
    """Launch `cmd` with stdout+stderr teed into a per-job log file, and
    stash the Popen handle in `_JOBS` keyed by a short uuid. Returns the
    job id so callers can poll /flash/log/<id>/."""
    job_id = uuid.uuid4().hex[:12]
    log_path = Path(tempfile.gettempdir()) / f'bodymap_flash_{job_id}.log'
    log_file = log_path.open('wb')
    header = f'# {label}\n$ {" ".join(shlex.quote(c) for c in cmd)}\n'
    log_file.write(header.encode())
    log_file.flush()
    proc = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        cwd=str(FIRMWARE_SRC_DIR),
    )
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            'proc':     proc,
            'log_file': log_file,
            'log_path': log_path,
            'label':    label,
            'started':  time.time(),
        }
    return job_id


@login_required
def flash_page(request):
    return render(request, 'bodymap/flash.html', {
        'devices':        _serial_devices(),
        'firmware':       _firmware_status(),
        'firmware_dir':   str(FIRMWARE_DIR),
    })


@login_required
def flash_devices(request):
    return JsonResponse({'devices': _serial_devices()})


@login_required
@csrf_exempt
@require_POST
def flash_run(request):
    port = (request.POST.get('port') or '').strip()
    if not port.startswith('/dev/tty'):
        return JsonResponse({'error': 'invalid port'}, status=400)
    if port not in [d['path'] for d in _serial_devices()]:
        return JsonResponse({'error': 'port not detected'}, status=400)

    fw = _firmware_status()
    if not fw['ready']:
        return JsonResponse(
            {'error': 'firmware not built — click Build first'}, status=400,
        )

    cmd = [
        str(PYTHON_PATH),
        str(ESPTOOL_PATH),
        '--chip', 'esp32s3',
        '--port', port,
        '--baud', '921600',
        '--before', 'default_reset',
        '--after', 'hard_reset',
        'write_flash', '-z',
        '--flash_mode', 'dio',
        '--flash_freq', '80m',
        # The generic ESP32-S3 SuperMini ships with 4 MB flash; 8 MB
        # would match esp32-s3-devkitc-1's default board profile but the
        # ROM refuses to boot when the header claims a size larger than
        # the chip actually has.
        '--flash_size', '4MB',
        '0x0000',  str(FIRMWARE_DIR / 'bootloader.bin'),
        '0x8000',  str(FIRMWARE_DIR / 'partitions.bin'),
        '0xe000',  str(BOOT_APP0_PATH),
        '0x10000', str(FIRMWARE_DIR / 'firmware.bin'),
    ]
    job_id = _spawn_job(cmd, label=f'flash {port}')
    return JsonResponse({'job': job_id})


@login_required
@csrf_exempt
@require_POST
def flash_build(request):
    """Rebuild firmware via pio. Used when the .bin is stale or missing."""
    cmd = [str(PIO_PATH), 'run']
    job_id = _spawn_job(cmd, label='pio build')
    return JsonResponse({'job': job_id})


@login_required
def flash_log(request, job_id):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        raise Http404('unknown job')

    try:
        offset = int(request.GET.get('offset', '0'))
    except ValueError:
        offset = 0

    try:
        data = job['log_path'].read_bytes()
    except FileNotFoundError:
        data = b''

    chunk = data[offset:]
    returncode = job['proc'].poll()
    finished = returncode is not None
    if finished:
        try:
            job['log_file'].close()
        except Exception:
            pass

    return JsonResponse({
        'chunk':      chunk.decode('utf-8', errors='replace'),
        'offset':     len(data),
        'finished':   finished,
        'returncode': returncode,
        'label':      job['label'],
    })
