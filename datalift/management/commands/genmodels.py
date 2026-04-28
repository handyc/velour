"""Generate a Django ``models.py`` and a starter ``table_map.json``
from a mysqldump. One-shot replacement for hand-writing models after
``dumpschema``.

    python manage.py genmodels path/to/dump.sql \\
        --app myapp \\
        [--out myapp/models.py] \\
        [--map-out myapp/ingest/table_map.json] \\
        [--source-database legacy_app_db]

The output is never authoritative — Datalift makes best-effort
inferences (EmailField / SlugField / URLField / TextChoices for
ENUMs / FK resolution / Laravel soft-delete hints / junction-table
flags). Review the generated file before migrating.

Workflow:

  1. ``manage.py dumpschema dump.sql --out schema.sql``  (optional)
  2. ``manage.py genmodels dump.sql --app myapp``
     → writes myapp/models.py + myapp/ingest/table_map.json
  3. Edit both to taste, then ``makemigrations`` + ``migrate``.
  4. ``manage.py ingestdump dump.sql --app myapp
        --map myapp/ingest/table_map.json --truncate``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

from datalift.model_generator import generate_all


class Command(BaseCommand):
    help = ('Generate models.py + table_map.json from a mysqldump, '
            'using semantic field inference and FK detection.')

    def add_arguments(self, parser):
        parser.add_argument('input', help='Path to the mysqldump .sql file.')
        parser.add_argument('--app', required=True,
            help='Django app label that will receive the models.')
        parser.add_argument('--app-dir', default=None,
            help='Target app filesystem directory. Required when --app '
                 'is not installed in the running Django project; '
                 'optional (and auto-inferred) when it is.')
        parser.add_argument('--out', default=None,
            help='Where to write models.py. Default: <app-dir>/models.py. '
                 'Use "-" for stdout.')
        parser.add_argument('--admin-out', default=None,
            help='Where to write admin.py. Default: <app-dir>/admin.py. '
                 'Use "" to skip.')
        parser.add_argument('--map-out', default=None,
            help='Where to write the starter table_map.json. Default: '
                 '<app-dir>/ingest/table_map.json. Use "" to skip writing.')
        parser.add_argument('--source-database', default='',
            help='Label to record in the map _meta and header comment.')
        parser.add_argument('--force', action='store_true',
            help='Overwrite an existing models.py / admin.py.')

    def handle(self, *args, **opts):
        path = Path(opts['input'])
        if not path.exists():
            raise CommandError(f'cannot read {path}')
        text = path.read_text(encoding='utf-8', errors='replace')

        app_label = opts['app']
        # If the app is installed in the current Django project, auto-
        # infer the output paths from its filesystem location. If it's
        # not installed (the dump-and-go case — running from Datalift,
        # writing into an unrelated project), the user must supply
        # --out / --admin-out / --map-out (or --app-dir) explicitly.
        app_dir = None
        try:
            app_config = apps.get_app_config(app_label)
            app_dir = Path(app_config.path)
        except LookupError:
            if opts.get('app_dir'):
                app_dir = Path(opts['app_dir']).resolve()
            elif not (opts['out'] or opts['admin_out'] or opts['map_out']):
                raise CommandError(
                    f'app `{app_label}` is not installed in this project. '
                    f'Either register it first (manage.py startapp '
                    f'{app_label}) or pass --app-dir /path/to/<app>/ so '
                    f'outputs go to the right place. You can also pass '
                    f'--out/--admin-out/--map-out individually.'
                )

        def _default(path_component: str) -> Path | None:
            if app_dir is None:
                return None
            return app_dir / path_component

        models_path_opt = opts['out']
        if models_path_opt is None:
            models_path = _default('models.py')
        elif models_path_opt == '-':
            models_path = None
        else:
            models_path = Path(models_path_opt)

        admin_path_opt = opts['admin_out']
        if admin_path_opt is None:
            admin_path = _default('admin.py')
        elif admin_path_opt == '':
            admin_path = None
        else:
            admin_path = Path(admin_path_opt)

        map_path_opt = opts['map_out']
        if map_path_opt is None:
            map_path = _default('ingest') / 'table_map.json' if app_dir else None
        elif map_path_opt == '':
            map_path = None
        else:
            map_path = Path(map_path_opt)

        if models_path is None and not any(
                [opts['out'] == '-',  # explicit stdout
                 opts['admin_out'], opts['map_out']]):
            raise CommandError(
                'no output path resolved — supply --out (or --app-dir '
                'to infer all three).'
            )

        models_src, admin_src, tmap = generate_all(
            text, app_label=app_label,
            source_database=opts['source_database'],
        )

        n_tables = len(tmap.get('tables') or {})

        def _safe_write(target: Path, content: str, label: str):
            if target.exists() and not opts['force']:
                existing = target.read_text(encoding='utf-8')
                if 'Auto-generated by datalift genmodels' not in existing:
                    raise CommandError(
                        f'{target} exists and is not a prior datalift '
                        f'genmodels file. Pass --force to overwrite.'
                    )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
            self.stdout.write(f'→ {target} ({label})')

        # Write models.py
        if models_path is None:
            sys.stdout.write(models_src)
        else:
            _safe_write(models_path, models_src, f'{n_tables} model(s)')

        # Write admin.py
        if admin_path is not None:
            _safe_write(admin_path, admin_src, 'ModelAdmin registrations')

        # Write table_map.json
        if map_path is not None:
            map_path.parent.mkdir(parents=True, exist_ok=True)
            map_path.write_text(
                json.dumps(tmap, indent=2, ensure_ascii=False) + '\n',
                encoding='utf-8',
            )
            self.stdout.write(f'→ {map_path} (ingestdump map)')

        self.stdout.write(self.style.SUCCESS(
            f'Generated {n_tables} model(s) + admin. Review, then '
            f'`manage.py makemigrations {app_label} && migrate`, then '
            f'`manage.py ingestdump {path} --app {app_label} '
            f'--map {map_path or "<mapfile>"} --truncate`.'
        ))
