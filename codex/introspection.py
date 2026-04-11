"""Introspection helpers for the Complete Reference manual.

These functions walk the live Django project (settings, URLs, models,
management commands) and return markdown strings that the seed_manuals
command embeds into Section.body.

Re-running the seeder picks up any code changes — so the auto-generated
parts of the Complete Reference stay in sync with the codebase
automatically.
"""

import inspect
import re
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management import get_commands, load_command_class
from django.urls import get_resolver
from django.utils.module_loading import import_string


_FIELD_DESCRIPTIONS = {
    'AutoField': 'auto integer',
    'BigAutoField': 'big auto integer',
    'BooleanField': 'boolean',
    'CharField': 'string',
    'DateField': 'date',
    'DateTimeField': 'datetime',
    'DecimalField': 'decimal',
    'EmailField': 'email',
    'FileField': 'file',
    'FloatField': 'float',
    'ForeignKey': 'fk →',
    'GenericIPAddressField': 'ip',
    'ImageField': 'image',
    'IntegerField': 'integer',
    'JSONField': 'json',
    'ManyToManyField': 'm2m →',
    'OneToOneField': 'one2one →',
    'PositiveIntegerField': 'positive integer',
    'SlugField': 'slug',
    'TextField': 'text',
    'URLField': 'url',
    'UUIDField': 'uuid',
}


def _esc(text):
    """Escape pipe characters so they don't break markdown tables."""
    if text is None:
        return ''
    return str(text).replace('|', '\\|').replace('\n', ' ')


def _truncate(text, n=80):
    if not text:
        return ''
    text = text.replace('\n', ' ').strip()
    if len(text) <= n:
        return text
    return text[:n - 1] + '…'


# --- settings ------------------------------------------------------------

_INTERESTING_SETTINGS = [
    ('DEBUG',               'Whether Django runs in debug mode.'),
    ('ALLOWED_HOSTS',       'Hosts the server will respond to.'),
    ('INSTALLED_APPS',      'The full list of Django apps.'),
    ('TIME_ZONE',           'Server-side timezone (chronos overrides for display).'),
    ('USE_TZ',              'If True, datetimes are stored timezone-aware.'),
    ('LANGUAGE_CODE',       'Default Django language code.'),
    ('STATIC_URL',          'URL prefix for static files.'),
    ('STATIC_ROOT',         'Filesystem location of collected static files.'),
    ('MEDIA_URL',           'URL prefix for user-uploaded media.'),
    ('MEDIA_ROOT',          'Filesystem location of uploaded media.'),
    ('EMAIL_BACKEND',       'Email backend (mailboxes app overrides at runtime).'),
    ('DEFAULT_FROM_EMAIL',  'Fallback From: address.'),
    ('LOGIN_URL',           'Where @login_required redirects.'),
    ('LOGIN_REDIRECT_URL',  'Where login redirects on success.'),
    ('LOGOUT_REDIRECT_URL', 'Where logout redirects on success.'),
    ('ASGI_APPLICATION',    'Channels ASGI application path.'),
    ('WSGI_APPLICATION',    'WSGI application path.'),
    ('APP_OUTPUT_DIR',      'Where app_factory writes generated projects.'),
    ('CODEX_KROKI_URL',     'Mermaid renderer endpoint (Kroki by default).'),
]


def settings_section():
    rows = ['| Setting | Value | Notes |', '|---|---|---|']
    for name, note in _INTERESTING_SETTINGS:
        if not hasattr(settings, name):
            continue
        val = getattr(settings, name)
        val_str = _truncate(_esc(repr(val)), n=60)
        rows.append(f'| `{name}` | `{val_str}` | {_esc(note)} |')
    return '\n'.join(rows)


# --- urls ----------------------------------------------------------------

def _walk_urlpatterns(patterns, prefix=''):
    out = []
    for p in patterns:
        try:
            pattern_str = str(p.pattern)
        except Exception:
            pattern_str = '?'
        if hasattr(p, 'url_patterns'):
            out.extend(_walk_urlpatterns(p.url_patterns, prefix + pattern_str))
        else:
            full = prefix + pattern_str
            name = getattr(p, 'name', '') or ''
            cb = getattr(p, 'callback', None)
            view_path = ''
            if cb is not None:
                mod = getattr(cb, '__module__', '')
                qname = getattr(cb, '__qualname__', getattr(cb, '__name__', ''))
                view_path = f'{mod}.{qname}'
            out.append((full, name, view_path))
    return out


_SKIP_URL_VIEWS = (
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.staticfiles',
    'django.views.generic',
    'django.views.static',
)


def urls_section():
    resolver = get_resolver()
    urls = _walk_urlpatterns(resolver.url_patterns)
    urls.sort(key=lambda r: r[0])

    rows = ['| Pattern | Name | View |', '|---|---|---|']
    for pattern, name, view in urls:
        # Skip framework-internal routes that aren't useful in a reference.
        if any(view.startswith(prefix) for prefix in _SKIP_URL_VIEWS):
            continue
        if pattern.startswith('admin/'):
            continue
        rows.append(
            f'| `{_truncate(_esc(pattern), 50)}` '
            f'| `{_truncate(_esc(name), 30)}` '
            f'| `{_truncate(_esc(view), 60)}` |'
        )
    return '\n'.join(rows)


# --- models --------------------------------------------------------------

def _field_summary(f):
    type_name = type(f).__name__
    short = _FIELD_DESCRIPTIONS.get(type_name, type_name.lower())
    if hasattr(f, 'related_model') and f.related_model:
        short += f' {f.related_model.__name__}'
    return short


def _model_block(model):
    out = []
    out.append(f'### `{model._meta.app_label}.{model.__name__}`')
    out.append('')
    doc = inspect.getdoc(model) or ''
    if doc:
        out.append(_truncate(doc, 200))
        out.append('')

    # Field table
    out.append('| Field | Type | Null | Blank | Help |')
    out.append('|---|---|---|---|---|')
    for f in model._meta.get_fields():
        if f.is_relation and f.auto_created and not f.concrete:
            continue  # skip reverse relations
        try:
            help_text = getattr(f, 'help_text', '') or ''
            null_v = 'Y' if getattr(f, 'null', False) else ''
            blank_v = 'Y' if getattr(f, 'blank', False) else ''
            out.append(
                f'| `{f.name}` '
                f'| {_field_summary(f)} '
                f'| {null_v} '
                f'| {blank_v} '
                f'| {_truncate(_esc(help_text), 50)} |'
            )
        except Exception:
            continue

    # Meta info
    meta = model._meta
    if meta.ordering:
        out.append('')
        out.append(f'**Ordering**: `{meta.ordering}`')
    if meta.indexes:
        idxs = ', '.join([f'`{i.name or "(auto)"}`' for i in meta.indexes])
        out.append(f'**Indexes**: {idxs}')
    out.append('')
    return '\n'.join(out)


def models_section():
    out = []
    for app in apps.get_app_configs():
        if app.name.startswith('django.') or app.name == 'channels':
            continue
        models = list(app.get_models())
        if not models:
            continue
        out.append(f'## {app.verbose_name}')
        out.append('')
        for model in models:
            out.append(_model_block(model))
    return '\n'.join(out)


def models_for_app(app_label):
    """Return the model reference for a single app, used inside per-app
    chapters in Part II. Returns an empty string if the app has no
    models or doesn't exist."""
    try:
        app = apps.get_app_config(app_label)
    except LookupError:
        return ''
    models = list(app.get_models())
    if not models:
        return ''
    out = ['## Models', '']
    for model in models:
        out.append(_model_block(model))
    return '\n'.join(out)


def urls_for_app(app_label):
    """Return the URL routes that are defined inside the given app
    (matched by view module name)."""
    resolver = get_resolver()
    urls = _walk_urlpatterns(resolver.url_patterns)
    rows = ['## URL routes', '', '| Pattern | Name | View |', '|---|---|---|']
    found = False
    for pattern, name, view in urls:
        if not view.startswith(app_label + '.'):
            continue
        found = True
        rows.append(
            f'| `{_truncate(_esc(pattern), 50)}` '
            f'| `{_truncate(_esc(name), 30)}` '
            f'| `{_truncate(_esc(view), 60)}` |'
        )
    if not found:
        return ''
    return '\n'.join(rows)


def commands_for_app(app_label):
    """Return the management commands defined by the given app."""
    cmds = get_commands()
    rows = ['## Management commands', '', '| Command | Help |', '|---|---|']
    found = False
    for name, owning_app in sorted(cmds.items()):
        if owning_app != app_label:
            continue
        try:
            cmd = load_command_class(owning_app, name)
            help_text = (cmd.help or '').strip()
        except Exception:
            help_text = ''
        rows.append(f'| `{_esc(name)}` | {_truncate(_esc(help_text), 80)} |')
        found = True
    if not found:
        return ''
    return '\n'.join(rows)


# --- management commands -------------------------------------------------

def commands_section():
    cmds = get_commands()
    rows = ['| Command | App | Help |', '|---|---|---|']
    for name, app_name in sorted(cmds.items()):
        if app_name.startswith('django.'):
            continue
        try:
            cmd = load_command_class(app_name, name)
            help_text = (cmd.help or '').strip()
        except Exception:
            help_text = ''
        rows.append(
            f'| `{_esc(name)}` '
            f'| `{_esc(app_name)}` '
            f'| {_truncate(_esc(help_text), 70)} |'
        )
    return '\n'.join(rows)


# --- env vars ------------------------------------------------------------

_ENV_RE = re.compile(r"os\.environ\.get\(\s*['\"]([A-Z_][A-Z0-9_]*)['\"]")


def env_section():
    """Grep settings.py for os.environ.get('NAME', ...) patterns."""
    settings_path = Path(settings.BASE_DIR) / 'velour' / 'settings.py'
    out = ['| Variable | Default | Notes |', '|---|---|---|']
    if not settings_path.exists():
        return '\n'.join(out)
    text = settings_path.read_text()
    seen = set()
    for m in _ENV_RE.finditer(text):
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        # Try to grab the rest of the call to extract the default.
        snippet = text[m.start():m.start() + 200]
        snippet = snippet.replace('\n', ' ')
        snippet = snippet[:120]
        out.append(f'| `{name}` | _see settings.py_ | {_esc(snippet)} |')
    return '\n'.join(out)
