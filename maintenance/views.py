import os
import subprocess
import tarfile
from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Backup


BACKUP_DIR = os.path.join(str(settings.BASE_DIR), 'backups')


def _get_home_users():
    """List users that have a /home directory."""
    users = []
    home = '/home'
    if os.path.isdir(home):
        for name in sorted(os.listdir(home)):
            path = os.path.join(home, name)
            if os.path.isdir(path):
                try:
                    size = subprocess.check_output(
                        ['du', '-sh', path], text=True, timeout=10,
                        stderr=subprocess.DEVNULL,
                    ).split('\t')[0]
                except Exception:
                    size = '?'
                users.append({'name': name, 'path': path, 'size': size})
    return users


def _make_filename(username):
    """Generate datetime-stamped filename like username_9apr2026.tar"""
    now = datetime.now()
    day = now.strftime('%-d').lstrip('0') if os.name != 'nt' else str(now.day)
    month = now.strftime('%b').lower()
    year = now.strftime('%Y')
    return f'{username}_{day}{month}{year}.tar'


@login_required
def maintenance_home(request):
    users = _get_home_users()
    backups = Backup.objects.all()[:30]
    os.makedirs(BACKUP_DIR, exist_ok=True)
    return render(request, 'maintenance/home.html', {
        'users': users,
        'backups': backups,
        'backup_dir': BACKUP_DIR,
    })


@login_required
@require_POST
def backup_create(request):
    """Create a tarball backup of a user's home directory."""
    username = request.POST.get('username', '').strip()
    if not username:
        messages.error(request, 'No username specified.')
        return redirect('maintenance:home')

    home_path = f'/home/{username}'
    if not os.path.isdir(home_path):
        messages.error(request, f'Directory {home_path} does not exist.')
        return redirect('maintenance:home')

    os.makedirs(BACKUP_DIR, exist_ok=True)
    filename = _make_filename(username)
    filepath = os.path.join(BACKUP_DIR, filename)

    # If file already exists, add a counter
    counter = 1
    base, ext = os.path.splitext(filename)
    while os.path.exists(filepath):
        filename = f'{base}_{counter}{ext}'
        filepath = os.path.join(BACKUP_DIR, filename)
        counter += 1

    try:
        with tarfile.open(filepath, 'w') as tar:
            tar.add(home_path, arcname=username)

        size = os.path.getsize(filepath)
        backup = Backup.objects.create(
            username=username,
            filename=filename,
            filepath=filepath,
            size_bytes=size,
            created_by=request.user,
            notes=request.POST.get('notes', '').strip(),
        )
        messages.success(request, f'Backup created: {filename} ({backup.size_display})')
    except PermissionError:
        messages.error(request, f'Permission denied reading {home_path}. Run as the user or with appropriate permissions.')
    except Exception as e:
        messages.error(request, f'Backup failed: {e}')

    return redirect('maintenance:home')


@login_required
@require_POST
def backup_restore(request, pk):
    """Restore a tarball backup to /home."""
    backup = get_object_or_404(Backup, pk=pk)

    if not os.path.isfile(backup.filepath):
        messages.error(request, f'Backup file not found: {backup.filepath}')
        return redirect('maintenance:home')

    target = '/home'
    try:
        with tarfile.open(backup.filepath, 'r') as tar:
            # Security: verify all paths extract under /home/username
            for member in tar.getmembers():
                if member.name.startswith('/') or '..' in member.name:
                    messages.error(request, f'Unsafe path in archive: {member.name}')
                    return redirect('maintenance:home')
            tar.extractall(path=target)
        messages.success(request, f'Restored {backup.filename} to {target}/{backup.username}/')
    except PermissionError:
        messages.error(request, f'Permission denied writing to {target}/{backup.username}/.')
    except Exception as e:
        messages.error(request, f'Restore failed: {e}')

    return redirect('maintenance:home')


@login_required
def backup_download(request, pk):
    """Download a backup tarball."""
    backup = get_object_or_404(Backup, pk=pk)
    if not os.path.isfile(backup.filepath):
        messages.error(request, 'Backup file not found.')
        return redirect('maintenance:home')
    return FileResponse(
        open(backup.filepath, 'rb'),
        as_attachment=True,
        filename=backup.filename,
    )


@login_required
@require_POST
def backup_delete(request, pk):
    """Delete a backup tarball from disk and database."""
    backup = get_object_or_404(Backup, pk=pk)
    if os.path.isfile(backup.filepath):
        os.remove(backup.filepath)
    name = backup.filename
    backup.delete()
    messages.success(request, f'Deleted backup: {name}')
    return redirect('maintenance:home')
