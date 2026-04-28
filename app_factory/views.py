import io
import os
import shutil
import signal
import socket
import stat
import subprocess
from datetime import datetime

import paramiko

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .management.commands.generate_deploy import render_deploy_artifacts
from .models import GeneratedApp


# Files and directories at BASE_DIR that must NEVER end up in a clone.
# Mirrors .gitignore — anything excluded from the public repo should
# also be excluded from a clone tree, since the clone is a fresh install
# with its own secrets, its own DB, and its own per-machine state.
#
# THE SECRET FILES ARE THE LOAD-BEARING ENTRIES. A clone that inherits
# the originating install's secret_key.txt or token files means
# compromise of one → compromise of both.
CLONE_SKIP_TOPLEVEL = {
    # Secret-file protocol — never copy
    'secret_key.txt',
    'health_token.txt',
    'mail_relay_token.txt',
    'provisioning_secret.txt',
    # Source-level git state — clone gets its own .git via `git init`
    '.git',
    # Build / runtime
    'venv',
    'staticfiles',
    'db.sqlite3',
    'db.sqlite3-journal',
    '__pycache__',
    # Per-machine runtime state
    'velour_port.txt',
    # Generated outputs (per /outputs/<app>/ convention)
    'outputs',
    'media',
    # Claude harness machine-local state
    '.claude',
    'memory',
    # Editor / OS
    '.vscode',
    '.idea',
    '.DS_Store',
}

# Recursive glob patterns to skip inside subdirectories.
CLONE_SKIP_PATTERNS = (
    '__pycache__', '*.pyc', '*.pyo',
    # Any file ending in .token treated as a secret
    '*.token',
    # Per-provider LLM API keys + generic API key files
    'llm_*.key', '*_api_key.txt',
    # PlatformIO per-device secrets
    'secrets.ini',
    # Editor / OS
    '*.swp', '*.swo', '*~', '.DS_Store',
    # Large auto-downloaded data; clone re-downloads on first use
    '*.bsp',                  # skyfield ephemeris (~17MB each)
    '*.onnx', '*.onnx.json',  # piper TTS voice models (~60MB each)
)


def _find_open_port(start=8001, end=9000):
    """Find an available port in the given range."""
    # Also avoid ports already claimed by other deployed apps
    used_ports = set(
        GeneratedApp.objects.filter(dev_port__isnull=False)
        .values_list('dev_port', flat=True)
    )
    for port in range(start, end):
        if port in used_ports:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return None


def _is_pid_running(pid):
    """Check if a process with the given PID is still alive."""
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _make_dir_name(name):
    """Generate a datetime-stamped directory name like vXXXXXXXX_DDmmmYYYY."""
    import random
    import string

    now = datetime.now()
    tag = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    date_str = now.strftime('%d%b%Y').lower()
    return f'v{tag}_{date_str}'


@login_required
def app_list(request):
    apps = GeneratedApp.objects.all()
    return render(request, 'app_factory/list.html', {'apps': apps})


def _identity_defaults():
    """Read the originating install's Identity values to pre-fill the
    create-app form. Falls back to safe placeholders if Identity isn't
    available (e.g. fresh checkout, pre-migrate)."""
    try:
        from identity.models import Identity
        i = Identity.get_self()
        return {
            'hostname': (i.hostname or 'example.com').strip(),
            'admin_email': (i.admin_email or '').strip(),
        }
    except Exception:
        return {'hostname': 'example.com', 'admin_email': ''}


def _write_clone_init(target_dir, instance_label, hostname, admin_email):
    """Drop a clone_init.json at the cloned tree's root. The new install
    consumes this on first boot via `manage.py apply_clone_init` so its
    Identity singleton starts with operator-chosen values rather than
    inheriting the originating instance's name/hostname/email."""
    import json
    payload = {
        'instance_label': instance_label,
        'hostname': hostname,
        'admin_email': admin_email,
    }
    out = os.path.join(target_dir, 'clone_init.json')
    with open(out, 'w') as f:
        json.dump(payload, f, indent=2)


@login_required
def app_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        app_type = request.POST.get('app_type', 'blank')
        deploy_user = request.POST.get('deploy_user', '').strip()
        server_name = request.POST.get('server_name', '').strip()
        hostname = request.POST.get('hostname', '').strip()
        admin_email = request.POST.get('admin_email', '').strip()
        maintenance_root = request.POST.get('maintenance_root', '').strip()
        instance_label = request.POST.get('instance_label', '').strip()

        if not name:
            messages.error(request, 'App name is required.')
            return render(request, 'app_factory/create.html', {
                'defaults': _identity_defaults(),
            })

        dir_name = _make_dir_name(name)
        output_dir = os.path.join(settings.APP_OUTPUT_DIR, dir_name)
        os.makedirs(output_dir, exist_ok=True)

        if app_type == 'clone':
            base = str(settings.BASE_DIR)
            for item in os.listdir(base):
                if item in CLONE_SKIP_TOPLEVEL:
                    continue
                src = os.path.join(base, item)
                dst = os.path.join(output_dir, item)
                if os.path.isdir(src):
                    shutil.copytree(
                        src, dst,
                        ignore=shutil.ignore_patterns(*CLONE_SKIP_PATTERNS),
                    )
                else:
                    shutil.copy2(src, dst)

            # Bake the operator's choices into the new tree. apply_clone_init
            # picks this up on first boot.
            _write_clone_init(
                output_dir,
                instance_label=instance_label or name,
                hostname=hostname,
                admin_email=admin_email,
            )

            subprocess.run(
                ['python3', '-m', 'venv', os.path.join(output_dir, 'venv')],
                check=True,
            )
            req_file = os.path.join(base, 'requirements.txt')
            if os.path.exists(req_file):
                subprocess.run(
                    [os.path.join(output_dir, 'venv', 'bin', 'pip'),
                     'install', '-r', req_file],
                    capture_output=True,
                )
        else:
            subprocess.run(
                ['python3', '-m', 'venv', os.path.join(output_dir, 'venv')],
                check=True,
            )
            pip = os.path.join(output_dir, 'venv', 'bin', 'pip')
            subprocess.run([pip, 'install', 'django', 'gunicorn'], capture_output=True)
            django_admin = os.path.join(output_dir, 'venv', 'bin', 'django-admin')
            subprocess.run(
                [django_admin, 'startproject', name, output_dir],
                capture_output=True,
            )

        app = GeneratedApp.objects.create(
            name=name,
            description=description,
            directory=output_dir,
            app_type=app_type,
            created_by=request.user,
            deploy_user=deploy_user or name.lower().replace(' ', ''),
            server_name=server_name,
            hostname=hostname,
            admin_email=admin_email,
            maintenance_root=maintenance_root,
            instance_label=instance_label,
        )

        _generate_deploy_artifacts(app)

        messages.success(request, f'App "{name}" created at {output_dir}')
        return redirect('app_factory:list')

    return render(request, 'app_factory/create.html', {
        'defaults': _identity_defaults(),
    })


def _generate_deploy_artifacts(app):
    """Render the five deploy artifacts (gunicorn/supervisor/nginx/setup.sh/adminsetup.sh)
    into the app's project directory, using the shared templates under
    app_factory/templates/deploy/.

    Layout on the target server:
      - App code:     /home/{deploy_user}/
      - Socket:       /var/www/webapps/{deploy_user}/run/{deploy_user}.sock
      - Static files: /var/www/webapps/{deploy_user}/static/
      - Logs:         /var/www/webapps/{deploy_user}/log/

    The deploy_user is the single identifier driving every path, nginx/supervisor
    symlink name, and ownership assignment.

    project_name is the Python package name that holds wsgi.py + settings.py.
    For clones, that's always the running velour's package (derived from
    settings.WSGI_APPLICATION) because cloning copies the velour/ directory
    as-is without renaming it. For blank apps scaffolded via django-admin
    startproject, the package is named after the app itself.
    """
    display_slug = app.name.lower().replace(' ', '_')
    deploy_user = app.deploy_user or display_slug
    if app.app_type == 'clone':
        project_name = settings.WSGI_APPLICATION.split('.')[0]
    else:
        project_name = display_slug
    render_deploy_artifacts(
        target_dir=app.directory,
        project_name=project_name,
        deploy_user=deploy_user,
        app_label=app.name,
        server_name=app.server_name or None,
        maintenance_root=app.maintenance_root or None,
    )


def _get_app_runtime_info(app):
    """Get memory usage and process info for a deployed app."""
    info = {'running': False, 'pid': None, 'memory_mb': None, 'cpu_percent': None, 'processes': []}
    project_name = app.name.lower().replace(' ', '_')

    try:
        result = subprocess.run(
            ['pgrep', '-f', f'gunicorn.*{project_name}'],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().split('\n')
        pids = [p for p in pids if p]
        if pids:
            info['running'] = True
            info['pid'] = pids[0]
            total_mem = 0
            total_cpu = 0
            for pid in pids:
                ps_result = subprocess.run(
                    ['ps', '-p', pid, '-o', 'pid,rss,pcpu,etime,comm', '--no-headers'],
                    capture_output=True, text=True, timeout=5,
                )
                line = ps_result.stdout.strip()
                if line:
                    parts = line.split()
                    if len(parts) >= 5:
                        rss_kb = int(parts[1])
                        cpu = float(parts[2])
                        total_mem += rss_kb
                        total_cpu += cpu
                        info['processes'].append({
                            'pid': parts[0],
                            'memory_kb': rss_kb,
                            'cpu_percent': cpu,
                            'elapsed': parts[3],
                            'command': parts[4],
                        })
            info['memory_mb'] = round(total_mem / 1024, 1)
            info['cpu_percent'] = round(total_cpu, 1)
    except Exception:
        pass

    # Check disk usage of the app directory
    try:
        result = subprocess.run(
            ['du', '-sh', app.directory],
            capture_output=True, text=True, timeout=5,
        )
        info['disk_usage'] = result.stdout.strip().split('\t')[0] if result.stdout else 'N/A'
    except Exception:
        info['disk_usage'] = 'N/A'

    # Check log file sizes
    log_dir = os.path.join(app.directory, 'logs')
    info['logs'] = {}
    if os.path.isdir(log_dir):
        for fname in os.listdir(log_dir):
            fpath = os.path.join(log_dir, fname)
            try:
                size = os.path.getsize(fpath)
                info['logs'][fname] = f'{size / 1024:.1f} KB'
            except OSError:
                pass

    return info


@login_required
def app_detail(request, pk):
    app = get_object_or_404(GeneratedApp, pk=pk)
    configs = {}
    conf_dir = os.path.join(app.directory, 'deploy')
    for fname in ('gunicorn.conf.py', 'supervisor.conf', 'nginx.conf'):
        fpath = os.path.join(conf_dir, fname)
        if os.path.exists(fpath):
            with open(fpath) as f:
                configs[fname] = f.read()

    runtime_info = None
    dev_server_running = False
    if app.status == 'deployed':
        runtime_info = _get_app_runtime_info(app)
        dev_server_running = _is_pid_running(app.dev_pid)

    return render(request, 'app_factory/detail.html', {
        'app': app,
        'configs': configs,
        'runtime': runtime_info,
        'dev_server_running': dev_server_running,
    })


@login_required
def app_approve(request, pk):
    app = get_object_or_404(GeneratedApp, pk=pk)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'approve':
            app.status = 'approved'
            app.save()
            messages.success(request, f'App "{app.name}" approved.')
        elif action == 'reject':
            app.status = 'rejected'
            app.save()
            messages.info(request, f'App "{app.name}" rejected.')
        elif action == 'unreject':
            app.status = 'pending'
            app.save()
            messages.success(request, f'App "{app.name}" restored to pending.')
    return redirect('app_factory:detail', pk=pk)


@login_required
def app_rename(request, pk):
    app = get_object_or_404(GeneratedApp, pk=pk)
    if request.method == 'POST':
        new_name = request.POST.get('name', '').strip()
        if new_name:
            old_name = app.name
            app.name = new_name
            app.save()
            messages.success(request, f'App renamed from "{old_name}" to "{new_name}".')
        else:
            messages.error(request, 'Name cannot be empty.')
    return redirect('app_factory:detail', pk=pk)


@login_required
def app_delete(request, pk):
    app = get_object_or_404(GeneratedApp, pk=pk)
    if request.method == 'POST':
        name = app.name
        directory = app.directory
        # Remove files from disk if directory exists
        if os.path.isdir(directory):
            shutil.rmtree(directory)
        app.delete()
        messages.success(request, f'App "{name}" and its files have been deleted.')
    return redirect('app_factory:list')


@login_required
def app_deploy(request, pk):
    """Deploy an approved app by spawning a local dev server on an open port."""
    app = get_object_or_404(GeneratedApp, pk=pk)
    if request.method == 'POST' and app.status in ('approved', 'deployed'):
        venv_python = os.path.join(app.directory, 'venv', 'bin', 'python')
        manage_py = os.path.join(app.directory, 'manage.py')

        if not os.path.exists(manage_py):
            messages.error(request, f'No manage.py found in {app.directory}')
            return redirect('app_factory:detail', pk=pk)

        # Stop existing dev server if running
        if app.dev_pid and _is_pid_running(app.dev_pid):
            try:
                os.kill(app.dev_pid, signal.SIGTERM)
            except OSError:
                pass

        # Build a clean env so the child uses its own manage.py defaults
        # instead of inheriting velour's DJANGO_SETTINGS_MODULE
        child_env = os.environ.copy()
        child_env.pop('DJANGO_SETTINGS_MODULE', None)

        # Run migrations and collect static
        subprocess.run(
            [venv_python, manage_py, 'migrate', '--noinput'],
            capture_output=True, cwd=app.directory, env=child_env,
        )
        subprocess.run(
            [venv_python, manage_py, 'collectstatic', '--noinput'],
            capture_output=True, cwd=app.directory, env=child_env,
        )

        # Find an open port
        port = _find_open_port()
        if port is None:
            messages.error(request, 'No open ports available in range 8001-9000.')
            return redirect('app_factory:detail', pk=pk)

        # Spawn the dev server as a background process
        log_dir = os.path.join(app.directory, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = open(os.path.join(log_dir, 'devserver.log'), 'w')

        proc = subprocess.Popen(
            [venv_python, manage_py, 'runserver', f'0.0.0.0:{port}'],
            cwd=app.directory,
            stdout=log_file,
            stderr=log_file,
            env=child_env,
            start_new_session=True,
        )

        app.status = 'deployed'
        app.dev_port = port
        app.dev_pid = proc.pid
        app.save()

        messages.success(
            request,
            f'App "{app.name}" is now running at http://localhost:{port}/'
        )
    return redirect('app_factory:detail', pk=pk)


@login_required
def app_stop(request, pk):
    """Stop a running local dev server."""
    app = get_object_or_404(GeneratedApp, pk=pk)
    if request.method == 'POST' and app.dev_pid:
        if _is_pid_running(app.dev_pid):
            try:
                os.kill(app.dev_pid, signal.SIGTERM)
                messages.success(request, f'Dev server for "{app.name}" stopped.')
            except OSError as e:
                messages.error(request, f'Could not stop server: {e}')
        else:
            messages.info(request, 'Server was not running.')
        app.dev_pid = None
        app.dev_port = None
        app.save()
    return redirect('app_factory:detail', pk=pk)


@login_required
def app_cloud_deploy(request, pk):
    """Show the cloud deploy form for an app."""
    app = get_object_or_404(GeneratedApp, pk=pk)
    return render(request, 'app_factory/cloud_deploy.html', {'app': app})


@login_required
@require_POST
def app_cloud_deploy_run(request, pk):
    """Connect via SSH and upload the app source to a staging directory on the
    remote server. The admin user (the SSH account) then runs adminsetup.sh
    from the staging dir to provision the project user, /var/www tree, system
    packages, nginx/supervisor wiring, and finally invokes setup.sh as the
    project user.

    Files are uploaded to /home/{ssh_username}/velour-staging/{deploy_user}/
    because the project user ({deploy_user}) doesn't exist yet on first run —
    only adminsetup.sh creates it.
    """
    app = get_object_or_404(GeneratedApp, pk=pk)

    hostname = request.POST.get('hostname', '').strip()
    port = int(request.POST.get('port', 22))
    username = request.POST.get('username', '').strip()
    password = request.POST.get('password', '').strip()
    key_path = request.POST.get('key_path', '').strip()
    remote_dir = request.POST.get('remote_dir', '').strip()

    if not hostname or not username:
        messages.error(request, 'Hostname and username are required.')
        return redirect('app_factory:cloud_deploy', pk=pk)

    deploy_user = app.deploy_user or app.name.lower().replace(' ', '_')
    if not remote_dir:
        # Staging under the SSH admin user's home — the project user doesn't
        # exist yet, so we cannot land files in /home/{deploy_user} directly.
        remote_dir = f'/home/{username}/velour-staging/{deploy_user}'

    # Regenerate deploy artifacts against the current templates so any edits
    # to app_factory/templates/deploy/ are picked up on every redeploy without
    # having to recreate the app.
    _generate_deploy_artifacts(app)

    skip = {'venv', '__pycache__', 'db.sqlite3', 'staticfiles', '.pyc'}
    log = []

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            'hostname': hostname,
            'port': port,
            'username': username,
            'timeout': 15,
        }
        if key_path and os.path.isfile(key_path):
            connect_kwargs['key_filename'] = key_path
        elif password:
            connect_kwargs['password'] = password
        else:
            for default_key in ['~/.ssh/id_rsa', '~/.ssh/id_ed25519']:
                expanded = os.path.expanduser(default_key)
                if os.path.isfile(expanded):
                    connect_kwargs['key_filename'] = expanded
                    break

        log.append(f'Connecting to {username}@{hostname}:{port}...')
        ssh.connect(**connect_kwargs)
        log.append('Connected.')

        sftp = ssh.open_sftp()

        log.append(f'Creating staging directory: {remote_dir}')
        _sftp_makedirs(sftp, remote_dir)

        local_root = app.directory
        file_count = 0
        for dirpath, dirnames, filenames in os.walk(local_root):
            dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith('.')]

            rel_dir = os.path.relpath(dirpath, local_root)
            remote_subdir = os.path.join(remote_dir, rel_dir).replace('\\', '/')
            if rel_dir != '.':
                _sftp_makedirs(sftp, remote_subdir)

            for fname in filenames:
                if fname.endswith('.pyc'):
                    continue
                local_file = os.path.join(dirpath, fname)
                remote_file = os.path.join(remote_subdir, fname).replace('\\', '/')
                try:
                    sftp.put(local_file, remote_file)
                    # Preserve executable bit on the setup scripts.
                    if fname in ('setup.sh', 'adminsetup.sh'):
                        sftp.chmod(remote_file, 0o755)
                    file_count += 1
                except Exception as e:
                    log.append(f'  SKIP {remote_file}: {e}')

        log.append(f'Uploaded {file_count} files.')

        # If the generated app doesn't carry its own requirements.txt, ship the
        # master velour requirements so setup.sh has something to install.
        req_local = os.path.join(local_root, 'requirements.txt')
        if not os.path.exists(req_local):
            master_req = os.path.join(str(settings.BASE_DIR), 'requirements.txt')
            if os.path.exists(master_req):
                req_remote = os.path.join(remote_dir, 'requirements.txt').replace('\\', '/')
                sftp.put(master_req, req_remote)
                log.append('Uploaded requirements.txt from master project.')

        sftp.close()
        ssh.close()
        log.append('Disconnected. Upload complete.')
        log.append('')
        log.append('Next steps on the server (run as the SSH user):')
        log.append(f'  ssh {username}@{hostname}')
        log.append(f'  cd {remote_dir}')
        log.append('  bash adminsetup.sh')
        log.append('')
        log.append('adminsetup.sh will install packages, create the')
        log.append(f'{deploy_user} user, lay out /var/www/webapps/{deploy_user}/,')
        log.append(f'sync source into /home/{deploy_user}/, wire nginx + supervisor,')
        log.append('and hand off to setup.sh as the project user.')

        messages.success(request, f'App "{app.name}" uploaded to {hostname}:{remote_dir}')

    except paramiko.AuthenticationException:
        log.append('ERROR: Authentication failed. Check username/password/key.')
        messages.error(request, 'SSH authentication failed.')
    except paramiko.SSHException as e:
        log.append(f'ERROR: SSH error: {e}')
        messages.error(request, f'SSH error: {e}')
    except Exception as e:
        log.append(f'ERROR: {e}')
        messages.error(request, f'Deploy failed: {e}')

    return render(request, 'app_factory/cloud_deploy_result.html', {
        'app': app, 'log': log,
        'hostname': hostname, 'username': username, 'remote_dir': remote_dir,
        'unique_name': deploy_user,
    })


def _sftp_makedirs(sftp, remote_dir):
    """Recursively create remote directories via SFTP."""
    dirs_to_make = []
    current = remote_dir
    while current and current != '/':
        try:
            sftp.stat(current)
            break
        except FileNotFoundError:
            dirs_to_make.append(current)
            current = os.path.dirname(current)
    for d in reversed(dirs_to_make):
        try:
            sftp.mkdir(d)
        except Exception:
            pass
