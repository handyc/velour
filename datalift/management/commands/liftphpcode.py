"""Translate arbitrary PHP source into Python.

    python manage.py liftphpcode /path/to/php/tree \\
        --app myapp \\
        [--out /path/to/project] \\
        [--worklist worklist.md] \\
        [--dry-run]

The catch-all complement to the framework-specific lifters
(liftlaravel, liftsymfony, liftcakephp, liftyii, liftcodeigniter).
Walks every `.php` file under the source tree (skipping
`vendor/`, `node_modules/`, and `tests/`) and emits a
`<app>/php_lifted/<mirrored-path>.py` file for each — best-effort
PHP → Python translation with `# PORTER:` markers on lines that
need human review.

See :mod:`datalift.php_code_lifter`.
"""

from __future__ import annotations

from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datalift.php_code_lifter import apply, parse_php_code, render_worklist


class Command(BaseCommand):
    help = 'Translate arbitrary PHP source into Python (catch-all lifter).'

    def add_arguments(self, parser):
        parser.add_argument('source', help='Path to the PHP source tree.')
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
        result = parse_php_code(source)
        worklist_path = (
            Path(opts['worklist']).resolve() if opts['worklist']
            else project_root / 'liftphpcode_worklist.md'
        )
        worklist_path.parent.mkdir(parents=True, exist_ok=True)
        worklist_path.write_text(render_worklist(result, app_label, source),
                                 encoding='utf-8')
        self.stdout.write(f'worklist → {worklist_path}')
        log = apply(result, project_root, app_label,
                    dry_run=opts['dry_run'], source_root=source)
        for line in log:
            self.stdout.write('  ' + line)
        total_funcs = sum(len(f.functions) for f in result.files)
        total_classes = sum(len(f.classes) for f in result.files)
        total_methods = sum(len(c.methods) for f in result.files
                             for c in f.classes)
        total_porter = sum(f.porter_markers for f in result.files)
        self.stdout.write(self.style.SUCCESS(
            f'\n{len(result.files)} file(s) translated. '
            f'{total_funcs} fn(s), {total_classes} class(es), '
            f'{total_methods} method(s). '
            f'{total_porter} # PORTER: marker(s).'
            f'{" (dry-run)" if opts["dry_run"] else ""}'
        ))
