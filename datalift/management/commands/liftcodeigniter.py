"""Lift a CodeIgniter application into Django.

    python manage.py liftcodeigniter /path/to/codeigniter/app \\
        --app myapp \\
        [--out /path/to/project] \\
        [--worklist worklist.md] \\
        [--dry-run]

Detects CI3 (`application/`) and CI4 (`app/` or `src/`) layouts.
Reads:

- CI3: `application/config/routes.php`,
  `application/controllers/**/*.php`.
- CI4: `app/Config/Routes.php` (or `src/Config/Routes.php`),
  `app/Controllers/**/*.php` (or `src/Controllers/**/*.php`).

Emits `<app>/urls_codeigniter.py` and `<app>/views_codeigniter.py`.

See :mod:`datalift.codeigniter_lifter`.
"""

from __future__ import annotations

from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datalift.codeigniter_lifter import (
    apply, parse_codeigniter, render_worklist,
)


class Command(BaseCommand):
    help = 'Lift a CodeIgniter application into Django.'

    def add_arguments(self, parser):
        parser.add_argument('source', help='Path to the CodeIgniter app root.')
        parser.add_argument('--app', required=True)
        parser.add_argument('--out', default=None)
        parser.add_argument('--worklist', default=None)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        source = Path(opts['source']).resolve()
        if not source.is_dir():
            raise CommandError(f'source is not a directory: {source}')
        app_label = opts['app']
        try:
            apps.get_app_config(app_label)
        except LookupError:
            raise CommandError(f'unknown app: {app_label}')
        project_root = (
            Path(opts['out']).resolve() if opts['out']
            else Path(settings.BASE_DIR)
        )
        result = parse_codeigniter(source)
        worklist_path = (
            Path(opts['worklist']).resolve() if opts['worklist']
            else project_root / 'liftcodeigniter_worklist.md'
        )
        worklist_path.parent.mkdir(parents=True, exist_ok=True)
        worklist_path.write_text(render_worklist(result, app_label, source),
                                 encoding='utf-8')
        self.stdout.write(f'worklist → {worklist_path}')
        log = apply(result, project_root, app_label, dry_run=opts['dry_run'])
        for line in log:
            self.stdout.write('  ' + line)
        method_count = sum(len(c.methods) for c in result.controllers)
        self.stdout.write(self.style.SUCCESS(
            f'\n{len(result.controllers)} controller(s) with '
            f'{method_count} method(s) translated. '
            f'{len(result.routes)} route(s).'
            f'{" (dry-run)" if opts["dry_run"] else ""}'
        ))
