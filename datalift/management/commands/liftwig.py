"""Lift a Twig template tree into Django templates.

    python manage.py liftwig /path/to/templates \\
        --app myapp \\
        [--out /path/to/project] \\
        [--worklist worklist.md] \\
        [--dry-run]

Twig (Symfony, Drupal 8+, Slim, Craft CMS) is the closest of the
major PHP template languages to Django's syntax — much of the
translation is trivial. See :mod:`datalift.twig_lifter`.
"""

from __future__ import annotations

from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datalift.twig_lifter import apply, parse_theme, render_worklist


class Command(BaseCommand):
    help = 'Lift a Twig template directory into a Django app.'

    def add_arguments(self, parser):
        parser.add_argument('theme', help='Path to the Twig templates directory.')
        parser.add_argument('--app', required=True,
                            help='Django app label that receives the lifted templates.')
        parser.add_argument('--out', default=None,
                            help='Project root (default: settings.BASE_DIR).')
        parser.add_argument('--worklist', default=None)
        parser.add_argument('--dry-run', action='store_true')

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
            else project_root / 'liftwig_worklist.md'
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
            f'{skipped} unhandled Twig fragment(s), '
            f'{unhandled} non-template PHP file(s) flagged'
            f'{" (dry-run)" if opts["dry_run"] else ""}.'
        ))
