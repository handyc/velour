"""User-mode local Nginx — opt-in prod-parity proxy in front of runserver.

Lives outside the management command so the Services view can call
into the same status/start/stop functions for its toggle buttons.
"""
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from django.conf import settings


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
    """Run Django's collectstatic into static_root (silent, --noinput)."""
    sr = static_root()
    sr.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        ['python', 'manage.py', 'collectstatic', '--noinput',
         f'--clear', f'--link', '-v', '0'],
        cwd=str(settings.BASE_DIR),
        capture_output=True, text=True, timeout=60,
        env={**os.environ, 'STATIC_ROOT': str(sr)},
    )


def start():
    """Start nginx. Returns (ok, message)."""
    if not nginx_installed():
        return False, 'nginx not installed (sudo apt install nginx)'
    if status()['running']:
        return True, f'already running (pid {status()["pid"]})'
    regenerate()
    # Ensure STATIC_ROOT is populated. Use --link for fast rebuild.
    cs = collectstatic()
    if cs.returncode != 0:
        return False, f'collectstatic failed: {cs.stderr.strip()[:200]}'
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
