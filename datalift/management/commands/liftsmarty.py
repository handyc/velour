"""Lift a Smarty theme directory into Django templates.

    python manage.py liftsmarty /path/to/themes/default \\
        --app myapp \\
        [--out /path/to/project] \\
        [--worklist worklist.md] \\
        [--dry-run]

Where `liftwp` targets WordPress PHP themes, `liftsmarty` targets
Smarty templates (`.tpl` files with `{$var}`, `{foreach}`,
`{include file=...}` syntax). Used in the Piwigo case study to
close the gap that liftwp couldn't bridge.

See :mod:`datalift.smarty_lifter` for the translation logic.
"""

from __future__ import annotations

from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datalift.smarty_lifter import apply, parse_theme, render_worklist


class Command(BaseCommand):
    help = 'Lift a Smarty theme directory into a Django app.'

    def add_arguments(self, parser):
        parser.add_argument('theme', help='Path to the Smarty theme directory.')
        parser.add_argument(
            '--app', required=True,
            help='Django app label that receives the lifted templates.',
        )
        parser.add_argument(
            '--out', default=None,
            help='Project root to write into (default: settings.BASE_DIR).',
        )
        parser.add_argument(
            '--worklist', default=None,
            help='Where to write the worklist (default: <project>/liftsmarty_worklist.md).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Translate and report; write the worklist but no template files.',
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
            else project_root / 'liftsmarty_worklist.md'
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
            f'{skipped} unhandled Smarty fragment(s), '
            f'{unhandled} non-template PHP file(s) flagged'
            f'{" (dry-run)" if opts["dry_run"] else ""}.'
        ))
