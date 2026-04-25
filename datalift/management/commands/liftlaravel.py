"""Lift a Laravel application's routes + controllers into Django.

    python manage.py liftlaravel /path/to/laravel/app \\
        --app myapp \\
        [--out /path/to/project] \\
        [--worklist worklist.md] \\
        [--dry-run]

The first PHP business-logic lifter. Reads:

* ``<laravel>/routes/*.php`` — emits ``<app>/urls_laravel.py``.
* ``<laravel>/app/Http/Controllers/*.php`` — emits ``<app>/views_laravel.py``.

For Eloquent models, run :command:`liftblade` for the Blade templates
and rely on :command:`genmodels` for the database side — the schema
is the canonical source there.

See :mod:`datalift.laravel_lifter`.
"""

from __future__ import annotations

from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datalift.laravel_lifter import apply, parse_laravel, render_worklist


class Command(BaseCommand):
    help = 'Lift a Laravel application routes + controllers into Django.'

    def add_arguments(self, parser):
        parser.add_argument('source', help='Path to the Laravel application root.')
        parser.add_argument('--app', required=True,
                            help='Django app label that receives the lifted views.')
        parser.add_argument('--out', default=None,
                            help='Project root (default: settings.BASE_DIR).')
        parser.add_argument('--worklist', default=None,
                            help='Where to write the worklist.')
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

        result = parse_laravel(source)

        worklist_text = render_worklist(result, app_label, source)
        worklist_path = (
            Path(opts['worklist']).resolve()
            if opts['worklist']
            else project_root / 'liftlaravel_worklist.md'
        )
        worklist_path.parent.mkdir(parents=True, exist_ok=True)
        worklist_path.write_text(worklist_text, encoding='utf-8')
        self.stdout.write(f'worklist → {worklist_path}')

        log = apply(result, project_root, app_label, dry_run=opts['dry_run'])
        for line in log:
            self.stdout.write('  ' + line)

        n_routes = len(result.routes)
        n_ctrls = len(result.controllers)
        n_methods = sum(len(c.methods) for c in result.controllers)
        n_skipped_routes = len(result.skipped_routes)
        n_skipped_methods = sum(len(c.skipped) for c in result.controllers)
        self.stdout.write(self.style.SUCCESS(
            f'\n{n_routes} route(s), {n_ctrls} controller(s) '
            f'with {n_methods} method(s) translated. '
            f'{n_skipped_routes} unhandled route fragment(s), '
            f'{n_skipped_methods} controller-method skips'
            f'{" (dry-run)" if opts["dry_run"] else ""}.'
        ))
