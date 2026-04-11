import os
import re
import subprocess

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


def _run(cmd, default=''):
    try:
        return subprocess.check_output(cmd, text=True, timeout=5, stderr=subprocess.STDOUT).strip()
    except Exception:
        return default


def _get_nginx_sites():
    """Read Nginx enabled sites from config directories (no sudo needed)."""
    sites = []
    search_dirs = [
        '/etc/nginx/sites-enabled',
        '/etc/nginx/conf.d',
    ]

    for conf_dir in search_dirs:
        if not os.path.isdir(conf_dir):
            continue
        for fname in sorted(os.listdir(conf_dir)):
            fpath = os.path.join(conf_dir, fname)
            if os.path.isfile(fpath) or os.path.islink(fpath):
                try:
                    with open(fpath) as f:
                        content = f.read()
                except PermissionError:
                    content = '(permission denied)'

                # Parse useful info
                server_names = re.findall(r'server_name\s+([^;]+);', content)
                listens = re.findall(r'listen\s+([^;]+);', content)
                proxy_passes = re.findall(r'proxy_pass\s+([^;]+);', content)
                roots = re.findall(r'root\s+([^;]+);', content)
                aliases = re.findall(r'alias\s+([^;]+);', content)

                # Check if the target link exists (for symlinks)
                real_path = os.path.realpath(fpath) if os.path.islink(fpath) else fpath
                is_symlink = os.path.islink(fpath)

                sites.append({
                    'name': fname,
                    'path': fpath,
                    'real_path': real_path,
                    'is_symlink': is_symlink,
                    'source_dir': conf_dir,
                    'server_names': [s.strip() for s in server_names],
                    'listens': [l.strip() for l in listens],
                    'proxy_passes': [p.strip() for p in proxy_passes],
                    'roots': [r.strip() for r in roots],
                    'aliases': [a.strip() for a in aliases],
                    'content': content,
                })

    # Check if nginx is running
    nginx_running = bool(_run(['pgrep', '-x', 'nginx']))
    nginx_version = _run(['nginx', '-v'])

    return sites, nginx_running, nginx_version


def _get_supervisor_programs():
    """Read Supervisor programs from config and check status."""
    programs = []
    search_dirs = [
        '/etc/supervisor/conf.d',
        '/etc/supervisord.d',
    ]

    for conf_dir in search_dirs:
        if not os.path.isdir(conf_dir):
            continue
        for fname in sorted(os.listdir(conf_dir)):
            if not (fname.endswith('.conf') or fname.endswith('.ini')):
                continue
            fpath = os.path.join(conf_dir, fname)
            try:
                with open(fpath) as f:
                    content = f.read()
            except PermissionError:
                content = '(permission denied)'

            # Parse program sections
            for match in re.finditer(
                r'\[program:([^\]]+)\](.*?)(?=\[|$)', content, re.DOTALL
            ):
                name = match.group(1)
                block = match.group(2)

                command = _extract_conf(block, 'command')
                directory = _extract_conf(block, 'directory')
                user = _extract_conf(block, 'user')
                autostart = _extract_conf(block, 'autostart')
                autorestart = _extract_conf(block, 'autorestart')
                stdout_log = _extract_conf(block, 'stdout_logfile')

                programs.append({
                    'name': name,
                    'config_file': fpath,
                    'command': command,
                    'directory': directory,
                    'user': user,
                    'autostart': autostart,
                    'autorestart': autorestart,
                    'stdout_logfile': stdout_log,
                    'content': f'[program:{name}]{block}',
                })

    # Try to get status from supervisorctl (may fail without sudo)
    status_map = {}
    raw = _run(['supervisorctl', 'status'])
    if raw and 'error' not in raw.lower() and 'refused' not in raw.lower():
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                status_map[parts[0]] = {
                    'state': parts[1],
                    'detail': ' '.join(parts[2:]),
                }

    for prog in programs:
        status = status_map.get(prog['name'], {})
        prog['state'] = status.get('state', 'UNKNOWN')
        prog['detail'] = status.get('detail', 'Could not query supervisorctl')

    # Also look for programs found in supervisorctl but not in config files
    config_names = {p['name'] for p in programs}
    for name, status in status_map.items():
        if name not in config_names:
            programs.append({
                'name': name,
                'config_file': '(discovered via supervisorctl)',
                'command': '',
                'directory': '',
                'user': '',
                'autostart': '',
                'autorestart': '',
                'stdout_logfile': '',
                'content': '',
                'state': status['state'],
                'detail': status['detail'],
            })

    # Check if supervisord is running
    supervisor_running = bool(_run(['pgrep', '-x', 'supervisord']))

    return programs, supervisor_running


def _extract_conf(block, key):
    match = re.search(rf'^{key}\s*=\s*(.+)$', block, re.MULTILINE)
    return match.group(1).strip() if match else ''


def _get_running_gunicorn():
    """Find running gunicorn processes (visible without sudo)."""
    instances = []
    raw = _run(['ps', 'aux'])
    if not raw:
        return instances

    for line in raw.splitlines():
        if 'gunicorn' in line and 'master' in line.lower():
            parts = line.split(None, 10)
            if len(parts) >= 11:
                instances.append({
                    'user': parts[0],
                    'pid': parts[1],
                    'cpu': parts[2],
                    'mem': parts[3],
                    'command': parts[10],
                })
    return instances


@login_required
def services_home(request):
    nginx_sites, nginx_running, nginx_version = _get_nginx_sites()
    supervisor_programs, supervisor_running = _get_supervisor_programs()
    gunicorn_instances = _get_running_gunicorn()

    return render(request, 'services/home.html', {
        'nginx_sites': nginx_sites,
        'nginx_running': nginx_running,
        'nginx_version': nginx_version,
        'supervisor_programs': supervisor_programs,
        'supervisor_running': supervisor_running,
        'gunicorn_instances': gunicorn_instances,
    })
