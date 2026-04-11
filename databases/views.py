from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import drivers
from .models import Database, ENGINE_CHOICES, SSL_MODE_CHOICES


_TEXT_FIELDS = ('nickname', 'host', 'username', 'password',
                'database_name', 'notes')


def _apply_post(db, post):
    for f in _TEXT_FIELDS:
        setattr(db, f, post.get(f, '').strip())
    db.engine = post.get('engine', 'postgresql')
    db.ssl_mode = post.get('ssl_mode', '').strip()
    raw_port = post.get('port', '').strip()
    db.port = int(raw_port) if raw_port.isdigit() else None


@login_required
def database_list(request):
    qs = Database.objects.all()
    return render(request, 'databases/list.html', {
        'databases': qs,
        'engines': dict(ENGINE_CHOICES),
    })


@login_required
def database_add(request):
    db = Database()
    if request.method == 'POST':
        _apply_post(db, request.POST)
        if not db.nickname:
            messages.error(request, 'Nickname is required.')
        else:
            try:
                db.save()
                messages.success(request, f'Added "{db.nickname}".')
                return redirect('databases:detail', slug=db.slug)
            except Exception as e:
                messages.error(request, f'Could not save: {e}')
    return render(request, 'databases/form.html', {
        'db': db,
        'action': 'Add',
        'engine_choices': ENGINE_CHOICES,
        'ssl_mode_choices': SSL_MODE_CHOICES,
    })


@login_required
def database_edit(request, slug):
    db = get_object_or_404(Database, slug=slug)
    if request.method == 'POST':
        _apply_post(db, request.POST)
        if not db.nickname:
            messages.error(request, 'Nickname is required.')
        else:
            try:
                db.save()
                messages.success(request, f'Updated "{db.nickname}".')
                return redirect('databases:detail', slug=db.slug)
            except Exception as e:
                messages.error(request, f'Could not save: {e}')
    return render(request, 'databases/form.html', {
        'db': db,
        'action': 'Edit',
        'engine_choices': ENGINE_CHOICES,
        'ssl_mode_choices': SSL_MODE_CHOICES,
    })


@login_required
@require_POST
def database_delete(request, slug):
    db = get_object_or_404(Database, slug=slug)
    nickname = db.nickname
    db.delete()
    messages.success(request, f'Removed "{nickname}".')
    return redirect('databases:list')


@login_required
def database_detail(request, slug):
    db = get_object_or_404(Database, slug=slug)
    return render(request, 'databases/detail.html', {'db': db})


@login_required
@require_POST
def database_test(request, slug):
    """Run a SELECT 1 / SELECT version() against this database and store
    the result on the record so the list view can show status dots."""
    db = get_object_or_404(Database, slug=slug)
    db.last_tested_at = timezone.now()
    try:
        version = drivers.test_connection(db)
        db.last_test_status = 'ok'
        db.last_test_error = ''
        db.last_test_server_version = version
        messages.success(request, f'Connected to "{db.nickname}": {version}')
    except Exception as e:
        db.last_test_status = 'failed'
        db.last_test_error = str(e)[:2000]
        db.last_test_server_version = ''
        messages.error(request, f'Connection to "{db.nickname}" failed: {e}')
    db.save(update_fields=[
        'last_tested_at', 'last_test_status',
        'last_test_error', 'last_test_server_version',
    ])
    return redirect('databases:detail', slug=db.slug)
