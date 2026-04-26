"""Lift a WordPress block theme (Twenty Twenty-Two and friends)
into Django templates.

    python manage.py liftwpblock /path/to/wp/block/theme \\
        --app myapp \\
        [--out /path/to/project] \\
        [--worklist worklist.md] \\
        [--dry-run]

Reads `<theme>/templates/*.html` and `<theme>/parts/*.html`,
parses the WordPress block-comment markup, emits Django templates
under `<project>/templates/<app>/`. Also extracts `theme.json`
to `<app>/wp_theme.json` for the porter to wire into Django
settings or a context processor.

See :mod:`datalift.wp_block_lifter`.
"""

from __future__ import annotations

from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datalift.wp_block_lifter import apply, parse_block_theme, render_worklist


class Command(BaseCommand):
    help = 'Lift a WordPress block theme into Django templates.'

    def add_arguments(self, parser):
        parser.add_argument('source',
                            help='Path to the WP block theme directory.')
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
        result = parse_block_theme(source, app_label=app_label)
        worklist_path = (
            Path(opts['worklist']).resolve() if opts['worklist']
            else project_root / 'liftwpblock_worklist.md'
        )
        worklist_path.parent.mkdir(parents=True, exist_ok=True)
        worklist_path.write_text(render_worklist(result, app_label),
                                 encoding='utf-8')
        self.stdout.write(f'worklist → {worklist_path}')
        log = apply(result, project_root, app_label, dry_run=opts['dry_run'])
        for line in log:
            self.stdout.write('  ' + line)
        n_blocks = sum(len(t.blocks_seen)
                        for t in result.templates + result.parts)
        n_porter = sum(t.porter_markers
                        for t in result.templates + result.parts)
        self.stdout.write(self.style.SUCCESS(
            f'\n{len(result.templates)} template(s), '
            f'{len(result.parts)} part(s) translated. '
            f'{n_blocks} block(s) seen, {n_porter} porter marker(s).'
            f'{" (dry-run)" if opts["dry_run"] else ""}'
        ))
