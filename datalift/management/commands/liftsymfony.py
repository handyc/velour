"""Lift a Symfony application's controllers + routes into Django.

    python manage.py liftsymfony /path/to/symfony/app \\
        --app myapp \\
        [--out /path/to/project] \\
        [--worklist worklist.md] \\
        [--dry-run]

Reads:

* ``<symfony>/src/Controller/*.php`` — emits ``<app>/views_symfony.py``.
* ``<symfony>/config/routes/*.yaml`` and ``config/*.yaml`` — adds
  to the URL surface.
* PHP attribute routes (``#[Route(...)]``) and docblock annotation
  routes (``@Route(...)``) on each controller method.

For Twig templates, run :command:`liftwig` separately. For the
schema, run :command:`genmodels` against a SQL dump (Doctrine
entity translation is out of scope for this lifter).

See :mod:`datalift.symfony_lifter`.
"""

from __future__ import annotations

from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datalift.symfony_lifter import (
    apply, parse_symfony, render_worklist,
)


class Command(BaseCommand):
    help = 'Lift a Symfony application controllers + routes into Django.'

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

        result = parse_symfony(source)

        worklist_path = (
            Path(opts['worklist']).resolve() if opts['worklist']
            else project_root / 'liftsymfony_worklist.md'
        )
        worklist_path.parent.mkdir(parents=True, exist_ok=True)
        worklist_path.write_text(render_worklist(result, app_label, source),
                                 encoding='utf-8')
        self.stdout.write(f'worklist → {worklist_path}')

        log = apply(result, project_root, app_label, dry_run=opts['dry_run'])
        for line in log:
            self.stdout.write('  ' + line)

        n_yaml = len(result.yaml_routes)
        n_ctrls = len(result.controllers)
        n_methods = sum(len(c.methods) for c in result.controllers)
        n_attr_routes = sum(len(m.routes) for c in result.controllers
                             for m in c.methods)
        self.stdout.write(self.style.SUCCESS(
            f'\n{n_ctrls} controller(s) with {n_methods} method(s) translated. '
            f'{n_attr_routes} attribute/annotation route(s), '
            f'{n_yaml} YAML route(s).'
            f'{" (dry-run)" if opts["dry_run"] else ""}'
        ))
