"""Take screenshots of Velour pages via headless Chromium.

Used to refresh the README image, capture Codex manual figures of live
UI, and generally produce reference images of any page in the project
without manual screenshot wrangling.

Usage:

    # Take a single named preset:
    python manage.py snapshot dashboard

    # Take several at once:
    python manage.py snapshot dashboard codex chronos databases

    # Take a custom path (slugified from the path itself):
    python manage.py snapshot /security/

    # Override viewport, output dir, or which superuser session to use:
    python manage.py snapshot dashboard --width 1600 --height 1000
    python manage.py snapshot dashboard --out-dir /tmp
    python manage.py snapshot dashboard --user alice

The command requires the Velour dev server to be running (default
port 7777) so that headless Chromium can hit it. It manufactures a
session for an existing superuser via Django's session backend, so no
password is needed.

Playwright + Chromium must be installed:

    pip install playwright
    playwright install chromium
    sudo playwright install-deps chromium   # one-time system libs
"""

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.core.management.base import BaseCommand, CommandError


# Known shortcuts: name -> URL path on the dev server.
PRESETS = {
    'dashboard':  '/dashboard/',
    'codex':      '/codex/',
    'chronos':    '/chronos/',
    'databases':  '/databases/',
    'sysinfo':    '/sysinfo/',
    'security':   '/security/',
    'logs':       '/logs/',
    'graphs':     '/graphs/',
    'services':   '/services/',
    'identity':   '/identity/',
    'nodes':      '/nodes/',
    'experiments':'/experiments/',
    'mailboxes':  '/mailboxes/',
    'mailroom':   '/mailroom/',
    'maintenance':'/maintenance/',
    'winctl':     '/windows/',
}


class Command(BaseCommand):
    help = (
        'Snapshot one or more Velour pages to PNG via headless Chromium. '
        'Pass preset names (dashboard, codex, chronos, ...) or URL paths.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'targets', nargs='+',
            help='Preset names or URL paths to screenshot.',
        )
        parser.add_argument(
            '--port', type=int, default=7777,
            help='Port the dev server is listening on (default 7777).',
        )
        parser.add_argument(
            '--host', default='127.0.0.1',
            help='Host the dev server is listening on (default 127.0.0.1).',
        )
        parser.add_argument(
            '--width', type=int, default=1400,
            help='Viewport width in CSS pixels (default 1400).',
        )
        parser.add_argument(
            '--height', type=int, default=900,
            help='Viewport height in CSS pixels (default 900).',
        )
        parser.add_argument(
            '--scale', type=int, default=2,
            help='Device pixel ratio. 2 = retina-quality (default 2).',
        )
        parser.add_argument(
            '--out-dir', default='docs/screenshots',
            help='Directory to write PNGs to (default docs/screenshots/).',
        )
        parser.add_argument(
            '--user', default=None,
            help='Username to log in as (default: first superuser found).',
        )
        parser.add_argument(
            '--no-full-page', action='store_true',
            help='Capture only the viewport instead of the full scrollable page.',
        )

    def handle(self, *args, **opts):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise CommandError(
                'playwright is not installed. Run: pip install playwright '
                '&& playwright install chromium'
            ) from e

        # Pick a user.
        User = get_user_model()
        if opts['user']:
            try:
                user = User.objects.get(username=opts['user'])
            except User.DoesNotExist:
                raise CommandError(f'No such user: {opts["user"]}')
        else:
            user = User.objects.filter(is_superuser=True).first()
            if not user:
                raise CommandError(
                    'No superuser found. Create one with '
                    '`python manage.py createsuperuser` or pass --user.'
                )

        # Manufacture a session so headless Chromium can browse as `user`
        # without ever knowing the password.
        session = SessionStore()
        session['_auth_user_id'] = str(user.pk)
        session['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
        session['_auth_user_hash'] = user.get_session_auth_hash()
        session.save()
        session_key = session.session_key

        out_dir = Path(opts['out_dir'])
        if not out_dir.is_absolute():
            out_dir = Path(settings.BASE_DIR) / out_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        host = opts['host']
        port = opts['port']
        full_page = not opts['no_full_page']

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                context = browser.new_context(
                    viewport={'width': opts['width'], 'height': opts['height']},
                    device_scale_factor=opts['scale'],
                )
                context.add_cookies([{
                    'name': 'sessionid',
                    'value': session_key,
                    'domain': host,
                    'path': '/',
                }])

                for target in opts['targets']:
                    if target in PRESETS:
                        path = PRESETS[target]
                        out_name = f'{target}.png'
                    elif target.startswith('/'):
                        path = target
                        slug = target.strip('/').replace('/', '-') or 'root'
                        out_name = f'{slug}.png'
                    else:
                        self.stderr.write(self.style.WARNING(
                            f'Skipping "{target}" — not a known preset and '
                            f'not a URL path (must start with /).'
                        ))
                        continue

                    url = f'http://{host}:{port}{path}'
                    out_path = out_dir / out_name

                    page = context.new_page()
                    try:
                        page.goto(url, wait_until='networkidle', timeout=15000)
                        page.screenshot(path=str(out_path), full_page=full_page)
                        size = out_path.stat().st_size
                        self.stdout.write(self.style.SUCCESS(
                            f'  ✓ {target}: {url} → {out_path.relative_to(settings.BASE_DIR)} ({size:,} bytes)'
                        ))
                    except Exception as e:
                        self.stderr.write(self.style.ERROR(
                            f'  ✗ {target}: {e}'
                        ))
                    finally:
                        page.close()
            finally:
                browser.close()
