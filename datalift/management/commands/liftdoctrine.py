"""Lift Doctrine entity classes into Django models.

    python manage.py liftdoctrine /path/to/symfony/app \\
        --app myapp \\
        [--out /path/to/project] \\
        [--worklist worklist.md] \\
        [--dry-run]

Reads ``<app>/src/Entity/**/*.php`` (and ``Entities/`` / ``Domain/``)
and emits ``<app>/models_doctrine.py`` from each `#[ORM\\Entity]`
class. Useful when the source ships with Doctrine entities but no
SQL dump.

See :mod:`datalift.doctrine_lifter`.
"""

from __future__ import annotations

from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datalift.doctrine_lifter import apply, parse_doctrine, render_worklist


class Command(BaseCommand):
    help = 'Lift Doctrine entities into Django models.'

    def add_arguments(self, parser):
        parser.add_argument('source', help='Path to the Symfony app root.')
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
        result = parse_doctrine(source)
        worklist_path = (
            Path(opts['worklist']).resolve() if opts['worklist']
            else project_root / 'liftdoctrine_worklist.md'
        )
        worklist_path.parent.mkdir(parents=True, exist_ok=True)
        worklist_path.write_text(render_worklist(result, app_label, source),
                                 encoding='utf-8')
        self.stdout.write(f'worklist → {worklist_path}')
        log = apply(result, project_root, app_label, dry_run=opts['dry_run'])
        for line in log:
            self.stdout.write('  ' + line)
        self.stdout.write(self.style.SUCCESS(
            f'\n{len(result.entities)} entity(ies) translated, '
            f'{sum(len(e.columns) for e in result.entities)} column(s).'
            f'{" (dry-run)" if opts["dry_run"] else ""}'
        ))
