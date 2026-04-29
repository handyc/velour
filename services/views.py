import glob
import os
import re
import shutil
import subprocess

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import local_nginx as ln


def _run(cmd, default=''):
    try:
        return subprocess.check_output(
            cmd, text=True, timeout=5, stderr=subprocess.STDOUT,
        ).strip()
    except Exception:
        return default


def _extract_conf(block, key):
    m = re.search(rf'^{key}\s*=\s*(.+)$', block, re.MULTILINE)
    return m.group(1).strip() if m else ''


# ---- Nginx ----------------------------------------------------------------

def _get_nginx_sites():
    sites = []
    for conf_dir in ('/etc/nginx/sites-enabled', '/etc/nginx/conf.d'):
        if not os.path.isdir(conf_dir):
            continue
        for fname in sorted(os.listdir(conf_dir)):
            fpath = os.path.join(conf_dir, fname)
            if not (os.path.isfile(fpath) or os.path.islink(fpath)):
                continue
            try:
                with open(fpath) as f:
                    content = f.read()
            except PermissionError:
                content = '(permission denied)'
            sites.append({
                'name':         fname,
                'path':         fpath,
                'real_path':    os.path.realpath(fpath) if os.path.islink(fpath) else fpath,
                'is_symlink':   os.path.islink(fpath),
                'source_dir':   conf_dir,
                'server_names': [s.strip() for s in re.findall(r'server_name\s+([^;]+);', content)],
                'listens':      [l.strip() for l in re.findall(r'listen\s+([^;]+);', content)],
                'proxy_passes': [p.strip() for p in re.findall(r'proxy_pass\s+([^;]+);', content)],
                'roots':        [r.strip() for r in re.findall(r'root\s+([^;]+);', content)],
                'aliases':      [a.strip() for a in re.findall(r'alias\s+([^;]+);', content)],
                'content':      content,
            })
    return sites, bool(_run(['pgrep', '-x', 'nginx'])), _run(['nginx', '-v'])


# ---- Supervisor (multi-instance) ------------------------------------------

def _supervisord_instances():
    """Every running supervisord process on the host. Walk /proc and
    match on /proc/<pid>/comm rather than `pgrep -af supervisord`,
    which false-positives on any shell command that contains the word
    (e.g. our own Django shell calls)."""
    out = []
    try:
        pids = os.listdir('/proc')
    except OSError:
        return out
    for pid in pids:
        if not pid.isdigit():
            continue
        try:
            with open(f'/proc/{pid}/comm') as f:
                if f.read().strip() != 'supervisord':
                    continue
            with open(f'/proc/{pid}/cmdline') as f:
                cmd = f.read().replace('\0', ' ').strip()
        except OSError:
            continue
        m = re.search(r'-c\s+(\S+)', cmd)
        out.append({'pid': pid, 'cmd': cmd,
                    'conf_path': m.group(1) if m else ''})
    return out


def _supervisor_socket_for(conf_path):
    try:
        with open(conf_path) as f:
            content = f.read()
    except (OSError, PermissionError):
        return ''
    m = re.search(r'\[unix_http_server\][^\[]*?file\s*=\s*(\S+)',
                  content, re.DOTALL)
    return m.group(1).strip() if m else ''


def _parse_supervisor_programs(conf_path):
    """Walk a supervisord.conf file, follow [include] files = ..., and
    collect every [program:NAME] block found."""
    if not conf_path or not os.path.isfile(conf_path):
        return []
    programs, seen = [], set()

    def parse(p):
        if p in seen:
            return
        seen.add(p)
        try:
            with open(p) as f:
                content = f.read()
        except (OSError, PermissionError):
            return
        for m in re.finditer(
            r'\[program:([^\]]+)\](.*?)(?=^\[|\Z)',
            content, re.DOTALL | re.MULTILINE,
        ):
            name, block = m.group(1), m.group(2)
            programs.append({
                'name':           name,
                'config_file':    p,
                'command':        _extract_conf(block, 'command'),
                'directory':      _extract_conf(block, 'directory'),
                'user':           _extract_conf(block, 'user'),
                'autostart':      _extract_conf(block, 'autostart'),
                'autorestart':    _extract_conf(block, 'autorestart'),
                'stdout_logfile': _extract_conf(block, 'stdout_logfile'),
                'content':        f'[program:{name}]{block}'.rstrip(),
            })
        inc = re.search(
            r'\[include\][^\[]*?files\s*=\s*([^\n]+)',
            content, re.DOTALL,
        )
        if inc:
            base = os.path.dirname(p)
            for token in inc.group(1).split():
                pat = token if os.path.isabs(token) else os.path.join(base, token)
                for sub in sorted(glob.glob(pat)):
                    parse(sub)
    parse(conf_path)
    return programs


def _supervisor_status(conf_path):
    args = ['supervisorctl']
    if conf_path:
        args += ['-c', conf_path]
    raw = _run(args + ['status'])
    out = {}
    if raw and 'error' not in raw.lower() and 'refused' not in raw.lower():
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                out[parts[0]] = {'state': parts[1],
                                 'detail': ' '.join(parts[2:])}
    return out


def _supervisor_label(conf_path):
    if conf_path == '/etc/supervisor/supervisord.conf':
        return 'system'
    # user-mode supervisor — name it after the project dir it lives in
    return os.path.basename(os.path.dirname(os.path.dirname(conf_path))) or 'user'


def _get_supervisors():
    out = []
    for inst in _supervisord_instances():
        conf = inst['conf_path'] or '/etc/supervisor/supervisord.conf'
        sock = _supervisor_socket_for(conf)
        programs = _parse_supervisor_programs(conf)
        status = _supervisor_status(conf)
        for p in programs:
            s = status.get(p['name'], {})
            p['state'] = s.get('state', 'UNKNOWN')
            p['detail'] = s.get('detail', '')
        cfg_names = {p['name'] for p in programs}
        for name, s in status.items():
            if name not in cfg_names:
                programs.append({
                    'name': name, 'config_file': '(via supervisorctl)',
                    'command': '', 'directory': '', 'user': '',
                    'autostart': '', 'autorestart': '', 'stdout_logfile': '',
                    'content': '', 'state': s['state'], 'detail': s['detail'],
                })
        programs.sort(key=lambda p: p['name'])
        out.append({
            'pid':       inst['pid'],
            'conf_path': conf,
            'socket':    sock,
            'label':     _supervisor_label(conf),
            'programs':  programs,
        })
    out.sort(key=lambda s: s['label'])
    return out


# ---- systemd --------------------------------------------------------------

# Internal/transport units that aren't useful in a "services" panel.
_SYSTEMD_HIDE_RE = re.compile(
    r'^(systemd-|getty|console-|user@|wsl-|init-|networkd-)'
)


def _get_systemd_units():
    """Active + failed systemd services (the actionable subset). Returns
    (units, available, inactive_count)."""
    raw = _run([
        'systemctl', 'list-units', '--type=service', '--all',
        '--no-pager', '--no-legend', '--plain',
    ])
    if not raw:
        return [], False, 0
    units, inactive = [], 0
    for line in raw.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        unit, load, active, sub = parts[:4]
        desc = parts[4] if len(parts) >= 5 else ''
        if load != 'loaded':
            continue
        if _SYSTEMD_HIDE_RE.match(unit):
            continue
        if active == 'inactive':
            inactive += 1
            continue
        units.append({
            'unit':        unit,
            'name':        unit.replace('.service', ''),
            'active':      active,
            'sub':         sub,
            'description': desc,
        })
    units.sort(key=lambda u: (
        0 if u['active'] == 'failed' else 1,
        u['name'],
    ))
    return units, True, inactive


# ---- Listening ports ------------------------------------------------------

_USERS_RE = re.compile(r'\("([^"]+)",pid=(\d+),fd=\d+\)')


def _get_listening_ports():
    raw = _run(['ss', '-tlnpH']) or _run(['ss', '-tlnH'])
    rows = []
    for line in (raw or '').splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[3]
        host, _, port = local.rpartition(':')
        if not port.isdigit():
            continue
        users_field = ' '.join(parts[5:]) if len(parts) > 5 else ''
        owner, pid = '', ''
        m = _USERS_RE.search(users_field)
        if m:
            owner, pid = m.group(1), m.group(2)
        cmdline = ''
        if pid:
            try:
                with open(f'/proc/{pid}/cmdline') as f:
                    cmdline = f.read().replace('\0', ' ').strip()
            except OSError:
                pass
        rows.append({
            'host':    host or '*',
            'port':    int(port),
            'pid':     pid,
            'owner':   owner,
            'cmdline': cmdline,
        })
    rows.sort(key=lambda r: (r['port'], r['host']))
    return rows


# ---- Backend service probes ----------------------------------------------

# Each probe declares a binary, the version flag, and the process name(s)
# that mean "this is running." Liveness is checked with pgrep -x, so the
# names must be exact (no shell-script wrappers). Optional `extra(probe)`
# returns a dict with richer info when the service is up.

def _apache_extra(probe):
    """Vhosts from sites-enabled — same shape as nginx parsing."""
    sites = []
    for d in ('/etc/apache2/sites-enabled', '/etc/httpd/conf.d'):
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            fp = os.path.join(d, fn)
            if not (os.path.isfile(fp) or os.path.islink(fp)):
                continue
            try:
                content = open(fp).read()
            except (OSError, PermissionError):
                continue
            names = re.findall(r'ServerName\s+(\S+)', content, re.IGNORECASE)
            sites.append({'name': fn, 'server_names': names, 'path': fp})
    return {'sites': sites}


def _docker_extra(probe):
    """Container count + a slice of running containers."""
    raw = _run(['docker', 'ps', '--format', '{{.Names}}\t{{.Image}}\t{{.Status}}'])
    if not raw:
        # Daemon unreachable (no group access, daemon stopped, etc.)
        return {'containers': [], 'unreachable': True}
    rows = []
    for line in raw.splitlines():
        parts = line.split('\t')
        if len(parts) >= 3:
            rows.append({'name': parts[0], 'image': parts[1], 'status': parts[2]})
    return {'containers': rows, 'unreachable': False}


def _redis_extra(probe):
    """Server version + database count from redis-cli INFO."""
    server = _run(['redis-cli', 'INFO', 'server'])
    keyspace = _run(['redis-cli', 'INFO', 'keyspace'])
    version = ''
    for line in (server or '').splitlines():
        if line.startswith('redis_version:'):
            version = line.split(':', 1)[1].strip()
            break
    dbs = []
    for line in (keyspace or '').splitlines():
        if line.startswith('db'):
            # "db0:keys=42,expires=0,avg_ttl=0"
            name, _, rest = line.partition(':')
            keys_m = re.search(r'keys=(\d+)', rest)
            dbs.append({'name': name, 'keys': int(keys_m.group(1)) if keys_m else 0})
    return {'redis_version': version, 'dbs': dbs}


_BACKEND_PROBES = [
    {'label': 'Apache',    'bin': 'apache2',     'version_args': ['-v'],
     'proc_names': ['apache2', 'httpd'],         'extra': _apache_extra},
    {'label': 'Docker',    'bin': 'docker',      'version_args': ['version', '--format', '{{.Server.Version}}'],
     'proc_names': ['dockerd'],                  'extra': _docker_extra},
    {'label': 'MySQL/MariaDB', 'bin': 'mysql',   'version_args': ['--version'],
     'proc_names': ['mysqld', 'mariadbd'],       'extra': None},
    {'label': 'PostgreSQL','bin': 'psql',        'version_args': ['--version'],
     'proc_names': ['postgres'],                 'extra': None},
    {'label': 'Redis',     'bin': 'redis-cli',   'version_args': ['--version'],
     'proc_names': ['redis-server'],             'extra': _redis_extra},
    {'label': 'Memcached', 'bin': 'memcached',   'version_args': ['-V'],
     'proc_names': ['memcached'],                'extra': None},
    {'label': 'RabbitMQ',  'bin': 'rabbitmqctl', 'version_args': ['version'],
     'proc_names': ['beam.smp'],                 'extra': None},
    {'label': 'MongoDB',   'bin': 'mongod',      'version_args': ['--version'],
     'proc_names': ['mongod'],                   'extra': None},
]


def _backend_status(probe):
    bin_path = shutil.which(probe['bin'])
    if not bin_path:
        return {
            'label':   probe['label'],
            'bin':     probe['bin'],
            'installed': False,
            'running': False,
            'version': '',
            'extra':   {},
        }
    version = _run([bin_path] + probe['version_args'], default='')
    version_line = (version or '').split('\n')[0].strip()
    running = any(bool(_run(['pgrep', '-x', n])) for n in probe['proc_names'])
    extra = {}
    if running and probe.get('extra'):
        try:
            extra = probe['extra'](probe) or {}
        except Exception:
            extra = {}
    return {
        'label':     probe['label'],
        'bin':       bin_path,
        'installed': True,
        'running':   running,
        'version':   version_line,
        'extra':     extra,
    }


def _get_backend_services():
    return [_backend_status(p) for p in _BACKEND_PROBES]


# ---- Gunicorn -------------------------------------------------------------

def _get_running_gunicorn():
    instances = []
    raw = _run(['ps', 'aux'])
    if not raw:
        return instances
    for line in raw.splitlines():
        if 'gunicorn' in line and 'master' in line.lower():
            parts = line.split(None, 10)
            if len(parts) >= 11:
                instances.append({
                    'user':    parts[0],
                    'pid':     parts[1],
                    'cpu':     parts[2],
                    'mem':     parts[3],
                    'command': parts[10],
                })
    return instances


@login_required
def services_home(request):
    nginx_sites, nginx_running, nginx_version = _get_nginx_sites()
    supervisors = _get_supervisors()
    systemd_units, systemd_available, systemd_inactive = _get_systemd_units()
    listening = _get_listening_ports()
    gunicorn_instances = _get_running_gunicorn()
    local_nginx_status = ln.status()
    backends = _get_backend_services()

    return render(request, 'services/home.html', {
        'nginx_sites':        nginx_sites,
        'nginx_running':      nginx_running,
        'nginx_version':      nginx_version,
        'supervisors':        supervisors,
        'systemd_units':      systemd_units,
        'systemd_available':  systemd_available,
        'systemd_inactive':   systemd_inactive,
        'listening':          listening,
        'gunicorn_instances': gunicorn_instances,
        'local_nginx':        local_nginx_status,
        'backends':           backends,
    })


@login_required
@require_POST
def local_nginx_toggle(request):
    action = request.POST.get('action', '')
    if action == 'start':
        ok, msg = ln.start()
    elif action == 'stop':
        ok, msg = ln.stop()
    elif action == 'regenerate':
        ln.regenerate()
        ok, msg = True, f'config rewritten at {ln.CONFFILE}'
    else:
        ok, msg = False, f'unknown action: {action!r}'
    (messages.success if ok else messages.error)(request, f'local-nginx: {msg}')
    return redirect('services:home')
