"""Lift a WordPress theme into Django templates + views + urls.

    python manage.py liftwp /path/to/theme \\
        --app myapp \\
        [--out /path/to/project] \\
        [--worklist worklist.md] \\
        [--dry-run]

Phase 1: standard theme files only (index/single/page/archive/404 +
header/footer/sidebar partials). The data half is assumed to already
have been datalifted into ``myapp``'s models — `liftwp` writes
``views_wp.py`` and ``urls_wp.py`` that read from them. Wire those
into your project URLs with::

    path('', include('myapp.urls_wp'))

See :mod:`datalift.wp_lifter` for the translation logic.
"""

from __future__ import annotations

from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datalift.wp_lifter import apply, parse_theme, render_worklist


class Command(BaseCommand):
    help = 'Lift a WordPress theme directory into a Django app (Phase 1).'

    def add_arguments(self, parser):
        parser.add_argument('theme', help='Path to the WordPress theme directory.')
        parser.add_argument(
            '--app', required=True,
            help='Django app label that receives the lifted files.',
        )
        parser.add_argument(
            '--out', default=None,
            help='Project root to write into (default: settings.BASE_DIR).',
        )
        parser.add_argument(
            '--worklist', default=None,
            help='Where to write the worklist (default: <project>/liftwp_worklist.md).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Translate and report; write the worklist but no template/view files.',
        )

    def handle(self, *args, **opts):
        theme = Path(opts['theme']).resolve()
        if not theme.is_dir():
            raise CommandError(f'theme is not a directory: {theme}')

        app_label = opts['app']
        try:
            apps.get_app_config(app_label)
        except LookupError:
            raise CommandError(f'unknown app: {app_label}')

        project_root = (
            Path(opts['out']).resolve() if opts['out']
            else Path(settings.BASE_DIR)
        )

        result = parse_theme(theme)

        worklist_text = render_worklist(result, app_label, theme)
        worklist_path = (
            Path(opts['worklist']).resolve()
            if opts['worklist']
            else project_root / 'liftwp_worklist.md'
        )
        worklist_path.parent.mkdir(parents=True, exist_ok=True)
        worklist_path.write_text(worklist_text, encoding='utf-8')
        self.stdout.write(f'worklist → {worklist_path}')

        log = apply(result, project_root, app_label, dry_run=opts['dry_run'])
        for line in log:
            self.stdout.write('  ' + line)

        translated = len(result.records)
        skipped = sum(len(r.skipped) for r in result.records)
        unhandled = len(result.unhandled_files)
        self.stdout.write(self.style.SUCCESS(
            f'\n{translated} template(s) translated, '
            f'{skipped} unhandled fragment(s), '
            f'{unhandled} non-standard PHP file(s) flagged'
            f'{" (dry-run)" if opts["dry_run"] else ""}.'
        ))
