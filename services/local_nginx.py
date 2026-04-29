"""User-mode local Nginx — opt-in prod-parity proxy in front of runserver.

Lives outside the management command so the Services view can call
into the same status/start/stop functions for its toggle buttons.
"""
import io
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from django.conf import settings
from django.core.management import call_command


WORKDIR = Path('/tmp/velour-nginx-local')
PIDFILE = WORKDIR / 'nginx.pid'
CONFFILE = WORKDIR / 'nginx.conf'
TEMPLATE = settings.BASE_DIR / 'deploy' / 'nginx-local.conf.template'

LISTEN_PORT = 8080
UPSTREAM_PORT = 7777


def static_root():
    """Where collectstatic should place files."""
    return Path(getattr(settings, 'STATIC_ROOT', None)
                or settings.BASE_DIR / 'staticfiles')


def nginx_installed():
    return shutil.which('nginx') is not None


def regenerate():
    """Write the local nginx config + ensure the workdir exists."""
    WORKDIR.mkdir(exist_ok=True)
    for sub in ('client_body', 'proxy', 'fastcgi', 'uwsgi', 'scgi'):
        (WORKDIR / sub).mkdir(exist_ok=True)
    template = TEMPLATE.read_text()
    rendered = template.format(
        workdir=str(WORKDIR),
        listen_port=LISTEN_PORT,
        upstream_port=UPSTREAM_PORT,
        static_root=str(static_root()),
    )
    CONFFILE.write_text(rendered)
    return CONFFILE


def status():
    """Return a dict describing the local nginx state.

    Keys: installed, running, pid, listen_port, upstream_port,
    static_root, conf_path, conf_exists, last_collectstatic.
    """
    info = {
        'installed':     nginx_installed(),
        'running':       False,
        'pid':           None,
        'listen_port':   LISTEN_PORT,
        'upstream_port': UPSTREAM_PORT,
        'static_root':   str(static_root()),
        'conf_path':     str(CONFFILE),
        'conf_exists':   CONFFILE.is_file(),
        'last_collectstatic': None,
    }
    if PIDFILE.is_file():
        try:
            pid = int(PIDFILE.read_text().strip())
            os.kill(pid, 0)  # signal 0 = liveness probe
            info['running'] = True
            info['pid'] = pid
        except (OSError, ValueError):
            pass
    sr = static_root()
    if sr.is_dir():
        try:
            info['last_collectstatic'] = sr.stat().st_mtime
        except OSError:
            pass
    return info


def collectstatic():
    """Run Django's collectstatic into STATIC_ROOT in-process. Returns
    (ok, message). Uses --link so reruns are fast and atomic."""
    sr = static_root()
    sr.mkdir(parents=True, exist_ok=True)
    sink = io.StringIO()
    try:
        call_command('collectstatic', interactive=False, clear=True,
                     link=True, verbosity=0, stdout=sink, stderr=sink)
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'
    return True, sink.getvalue().strip()


def start():
    """Start nginx. Returns (ok, message)."""
    if not nginx_installed():
        return False, 'nginx not installed (sudo apt install nginx)'
    if status()['running']:
        return True, f'already running (pid {status()["pid"]})'
    regenerate()
    cs_ok, cs_msg = collectstatic()
    if not cs_ok:
        return False, f'collectstatic failed: {cs_msg[:200]}'
    proc = subprocess.run(
        ['nginx', '-p', str(WORKDIR) + '/', '-c', str(CONFFILE)],
        capture_output=True, text=True, timeout=10,
    )
    if proc.returncode != 0:
        return False, f'nginx failed: {proc.stderr.strip() or proc.stdout.strip()}'
    # nginx forks; give it a moment to write the pid
    for _ in range(10):
        if PIDFILE.is_file():
            break
        time.sleep(0.1)
    s = status()
    if s['running']:
        return True, f'started on http://127.0.0.1:{LISTEN_PORT}/ (pid {s["pid"]})'
    return False, 'nginx exited without writing a pid; check error.log'


def stop():
    """Stop nginx. Returns (ok, message)."""
    s = status()
    if not s['running']:
        return True, 'not running'
    try:
        os.kill(s['pid'], signal.SIGTERM)
    except OSError as e:
        return False, f'kill failed: {e}'
    for _ in range(20):
        if not PIDFILE.is_file() or not status()['running']:
            return True, 'stopped'
        time.sleep(0.1)
    return False, 'nginx still running after SIGTERM'
