"""Lift a legacy HTML/JS/CSS site into a Django app's layout.

    python manage.py liftsite /path/to/old/site \\
        --app myapp \\
        [--url-map urls.json] \\
        [--asset-map assets.json] \\
        [--worklist worklist.md] \\
        [--move] [--dry-run]

Phase 1 (this command): HTML + JS + CSS + static assets. PHP files
are inventoried and flagged for Phase 2 but never read or rewritten.

Privacy posture matches ``ingestdump``: the source tree is opened
read-only, no outbound network calls, no LLM usage. Output goes to
``templates/<app>/``, ``static/<app>/``, and a worklist markdown file
inside the target app (or wherever ``--worklist`` points).

See :mod:`datalift.site_lifter` for the rewrite/inventory logic.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datalift.site_lifter import (
    apply_records,
    build_url_map,
    inventory,
    render_worklist,
)


class Command(BaseCommand):
    help = 'Lift a legacy HTML/JS/CSS site into a Django app (Phase 1).'

    def add_arguments(self, parser):
        parser.add_argument('source', help='Path to the legacy site root.')
        parser.add_argument(
            '--app', required=True,
            help='Django app label that receives the lifted files.',
        )
        parser.add_argument(
            '--url-map', default=None,
            help='JSON {legacy-url-or-regex: django-url-name}.',
        )
        parser.add_argument(
            '--asset-map', default=None,
            help='JSON {source-relpath: target-relpath} overrides.',
        )
        parser.add_argument(
            '--worklist', default=None,
            help='Where to write the worklist (default: <app>/liftsite_worklist.md).',
        )
        parser.add_argument(
            '--out', default=None,
            help='Project root to write into (default: settings.BASE_DIR).',
        )
        parser.add_argument(
            '--move', action='store_true',
            help='Move files instead of copying. Source tree is modified.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Scan and write the worklist; do not place any files.',
        )

    def handle(self, *args, **opts):
        source = Path(opts['source']).resolve()
        if not source.is_dir():
            raise CommandError(f'source is not a directory: {source}')

        app_label = opts['app']
        try:
            apps.get_app_config(app_label)
        except LookupError:
            raise CommandError(f'unknown app: {app_label}')

        url_entries: dict[str, str] = {}
        if opts['url_map']:
            try:
                with open(opts['url_map'], 'r', encoding='utf-8') as fh:
                    url_entries = json.load(fh)
            except OSError as e:
                raise CommandError(f'cannot read url-map: {e}')

        asset_map: dict[str, str] = {}
        if opts['asset_map']:
            try:
                with open(opts['asset_map'], 'r', encoding='utf-8') as fh:
                    asset_map = json.load(fh)
            except OSError as e:
                raise CommandError(f'cannot read asset-map: {e}')

        url_rules = build_url_map(url_entries)

        project_root = (
            Path(opts['out']).resolve() if opts['out']
            else Path(settings.BASE_DIR)
        )
        records = inventory(source, app_label, url_rules, asset_map)

        worklist_text = render_worklist(records, app_label, source)
        worklist_path = (
            Path(opts['worklist']).resolve()
            if opts['worklist']
            else project_root / 'liftsite_worklist.md'
        )
        worklist_path.parent.mkdir(parents=True, exist_ok=True)
        worklist_path.write_text(worklist_text, encoding='utf-8')
        self.stdout.write(f'worklist → {worklist_path}')

        log = apply_records(
            records,
            project_root,
            move=opts['move'],
            dry_run=opts['dry_run'],
        )
        for line in log:
            self.stdout.write('  ' + line)

        placed = sum(1 for r in records if r.dst is not None)
        self.stdout.write(self.style.SUCCESS(
            f'\n{placed}/{len(records)} files routed '
            f'({"dry-run" if opts["dry_run"] else ("moved" if opts["move"] else "copied")}).'
        ))
