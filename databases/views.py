import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import drivers
from .models import Database, ENGINE_CHOICES, SSL_MODE_CHOICES, SQLITE_DIR


_TEXT_FIELDS = ('nickname', 'host', 'username', 'password',
                'database_name', 'notes')


def _apply_post(db, post):
    for f in _TEXT_FIELDS:
        setattr(db, f, post.get(f, '').strip())
    db.engine = post.get('engine', 'sqlite')
    db.ssl_mode = post.get('ssl_mode', '').strip()
    raw_port = post.get('port', '').strip()
    db.port = int(raw_port) if raw_port.isdigit() else None
    # For SQLite, allow specifying an external file path
    if db.engine == 'sqlite':
        fp = post.get('file_path', '').strip()
        if fp:
            db.file_path = fp


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
    delete_file = request.POST.get('delete_file') == '1'
    if delete_file and db.is_sqlite and db.file_exists:
        try:
            os.remove(db.file_path)
        except OSError:
            pass
    db.delete()
    messages.success(request, f'Removed "{nickname}".')
    return redirect('databases:list')


@login_required
def database_detail(request, slug):
    db = get_object_or_404(Database, slug=slug)
    tables = None
    if db.is_sqlite and db.file_exists:
        try:
            tables = drivers.list_tables(db)
        except Exception:
            pass
    return render(request, 'databases/detail.html', {
        'db': db,
        'tables': tables,
    })


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


@login_required
def table_browse(request, slug, table_name):
    """Browse a table in a SQLite database: columns + rows."""
    db = get_object_or_404(Database, slug=slug)
    if not db.is_sqlite or not db.file_exists:
        messages.error(request, 'Table browsing is only available for SQLite databases.')
        return redirect('databases:detail', slug=slug)

    page = int(request.GET.get('page', 1))
    per_page = 100
    offset = (page - 1) * per_page

    columns = drivers.table_columns(db, table_name)
    col_names, rows = drivers.table_rows(db, table_name, limit=per_page, offset=offset)

    # Get total row count for pagination
    tables = drivers.list_tables(db)
    total_rows = 0
    for t in tables:
        if t['name'] == table_name:
            total_rows = t['row_count']
            break
    total_pages = max(1, (total_rows + per_page - 1) // per_page)

    return render(request, 'databases/table_browse.html', {
        'db': db,
        'table_name': table_name,
        'columns': columns,
        'col_names': col_names,
        'rows': rows,
        'page': page,
        'total_pages': total_pages,
        'total_rows': total_rows,
        'has_prev': page > 1,
        'has_next': page < total_pages,
    })


@login_required
def sql_query(request, slug):
    """Run a read-only SQL query against a SQLite database."""
    db = get_object_or_404(Database, slug=slug)
    if not db.is_sqlite or not db.file_exists:
        messages.error(request, 'SQL shell is only available for SQLite databases.')
        return redirect('databases:detail', slug=slug)

    sql = ''
    col_names = []
    rows = []
    error = ''
    if request.method == 'POST':
        sql = request.POST.get('sql', '').strip()
        if sql:
            try:
                col_names, rows = drivers.run_query(db, sql)
            except Exception as e:
                error = str(e)

    return render(request, 'databases/sql_query.html', {
        'db': db,
        'sql': sql,
        'col_names': col_names,
        'rows': rows,
        'error': error,
    })


@login_required
def download_sqlite(request, slug):
    """Download the SQLite file."""
    db = get_object_or_404(Database, slug=slug)
    if not db.is_sqlite or not db.file_exists:
        messages.error(request, 'No SQLite file to download.')
        return redirect('databases:detail', slug=slug)
    return FileResponse(
        open(db.file_path, 'rb'),
        as_attachment=True,
        filename=f'{db.slug}.sqlite3',
    )
