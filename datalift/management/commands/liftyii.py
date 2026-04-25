"""Lift a Yii 2 application into Django.

    python manage.py liftyii /path/to/yii2/app \\
        --app myapp \\
        [--out /path/to/project] \\
        [--worklist worklist.md] \\
        [--dry-run]

Reads `<app>/controllers/**/*Controller.php` and (if present)
`<app>/config/web.php` for custom `urlManager.rules`. Emits
`<app>/urls_yii.py` + `<app>/views_yii.py`.

See :mod:`datalift.yii_lifter`.
"""

from __future__ import annotations

from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datalift.yii_lifter import apply, parse_yii, render_worklist


class Command(BaseCommand):
    help = 'Lift a Yii 2 application into Django.'

    def add_arguments(self, parser):
        parser.add_argument('source', help='Path to the Yii 2 app root.')
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
        result = parse_yii(source)
        worklist_path = (
            Path(opts['worklist']).resolve() if opts['worklist']
            else project_root / 'liftyii_worklist.md'
        )
        worklist_path.parent.mkdir(parents=True, exist_ok=True)
        worklist_path.write_text(render_worklist(result, app_label, source),
                                 encoding='utf-8')
        self.stdout.write(f'worklist → {worklist_path}')
        log = apply(result, project_root, app_label, dry_run=opts['dry_run'])
        for line in log:
            self.stdout.write('  ' + line)
        action_count = sum(len(c.actions) for c in result.controllers)
        self.stdout.write(self.style.SUCCESS(
            f'\n{len(result.controllers)} controller(s) with '
            f'{action_count} action(s) translated. '
            f'{len(result.routes)} route(s).'
            f'{" (dry-run)" if opts["dry_run"] else ""}'
        ))
