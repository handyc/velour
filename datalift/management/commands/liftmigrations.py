"""Lift Laravel migrations into Django models.

    python manage.py liftmigrations /path/to/database/migrations \\
        --app myapp \\
        [--out /path/to/project] \\
        [--worklist worklist.md] \\
        [--dry-run]

Most Laravel apps ship their schema as ``database/migrations/*.php``
files (Blueprint API) instead of (or alongside) raw SQL dumps. This
command parses those blueprints and emits Django models — the same
shape ``genmodels`` would produce from a mysqldump.

See :mod:`datalift.laravel_migration_lifter`.
"""

from __future__ import annotations

from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datalift.laravel_migration_lifter import (
    apply, parse_migrations, render_worklist,
)


class Command(BaseCommand):
    help = 'Lift Laravel database migrations into Django models.'

    def add_arguments(self, parser):
        parser.add_argument('source', help='Path to database/migrations/.')
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
        result = parse_migrations(source)
        worklist_path = (
            Path(opts['worklist']).resolve() if opts['worklist']
            else project_root / 'liftmigrations_worklist.md'
        )
        worklist_path.parent.mkdir(parents=True, exist_ok=True)
        worklist_path.write_text(render_worklist(result, app_label, source),
                                 encoding='utf-8')
        self.stdout.write(f'worklist → {worklist_path}')
        log = apply(result, project_root, app_label, dry_run=opts['dry_run'])
        for line in log:
            self.stdout.write('  ' + line)
        n_tables = len(result.tables)
        n_cols = sum(len(t.columns) for t in result.tables)
        self.stdout.write(self.style.SUCCESS(
            f'\n{n_tables} model(s), {n_cols} column(s) translated, '
            f'{len(result.skipped_files)} file(s) skipped'
            f'{" (dry-run)" if opts["dry_run"] else ""}.'
        ))
