"""Ingest a mysqldump's data rows into a Django app's SQLite.

    python manage.py ingestdump path/to/full_dump.sql \\
        --app myapp [--map table_map.json] [--truncate] \\
        [--chunk 500] [--dry-run]

This runs on the machine that holds the original data. Nothing it
reads or writes needs to leave the local environment.

Workflow:

1. Claude looks at ``schema.sql`` (from ``dumpschema``) and hand-writes
   ``myapp/models.py``. You run ``manage.py makemigrations myapp``
   and ``migrate`` to create empty tables.
2. You run ``manage.py ingestdump dump.sql --app myapp`` to populate
   those tables from the original dump's INSERT statements.

Table-to-model resolution:

* By default, MySQL table ``foo_bar`` maps to Django model
  ``<app>.FooBar`` (i.e. Django's default ``<app>_<modellower>``
  table name, reversed — we strip the ``<app>_`` prefix if present
  and PascalCase what's left).
* Pass ``--map table_map.json`` with ``{"src_table": "app.Model",
  …}`` to override.
* Tables without a mapping are skipped with a warning.

Column resolution: the INSERT's own column list is preferred. If the
INSERT has no columns, the command reads them from the CREATE TABLE
block in the same dump. Unknown columns on the model are dropped with
a warning.
"""

from __future__ import annotations

import json
import re

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from datalift.dump_parser import iter_create_tables, iter_inserts


_COL_DEF_RE = re.compile(
    r"^\s*[`\"]?(?P<name>[A-Za-z_][A-Za-z0-9_]*)[`\"]?\s+(?!KEY|UNIQUE|PRIMARY|"
    r"FOREIGN|CONSTRAINT|INDEX|FULLTEXT|SPATIAL|CHECK)",
    re.IGNORECASE,
)


def _extract_column_order(ddl: str) -> list[str]:
    """Pull the column names out of a CREATE TABLE DDL block, in order."""
    # Strip outer CREATE TABLE … ( … ) ENGINE=… ;
    body = ddl[ddl.index('(') + 1 : ddl.rindex(')')]
    cols: list[str] = []
    depth = 0
    buf: list[str] = []
    in_s = False
    quote_ch = ''
    for ch in body:
        if in_s:
            buf.append(ch)
            if ch == quote_ch:
                in_s = False
            continue
        if ch in ("'", '"'):
            in_s = True
            quote_ch = ch
            buf.append(ch)
            continue
        if ch == '(':
            depth += 1
            buf.append(ch)
            continue
        if ch == ')':
            depth -= 1
            buf.append(ch)
            continue
        if ch == ',' and depth == 0:
            line = ''.join(buf)
            m = _COL_DEF_RE.match(line)
            if m:
                cols.append(m.group('name'))
            buf = []
            continue
        buf.append(ch)
    if buf:
        line = ''.join(buf)
        m = _COL_DEF_RE.match(line)
        if m:
            cols.append(m.group('name'))
    return cols


def _default_model_name(app_label: str, table: str) -> str:
    """Guess a model name from a MySQL table name.

    Strips the conventional ``<app>_`` prefix (Django's default table
    naming), then PascalCases the remainder.
    """
    stem = table
    prefix = app_label + '_'
    if stem.startswith(prefix):
        stem = stem[len(prefix):]
    return ''.join(part.capitalize() for part in stem.split('_') if part)


class Command(BaseCommand):
    help = 'Load INSERTs from a mysqldump into a Django app\'s models.'

    def add_arguments(self, parser):
        parser.add_argument('input', help='Path to the mysqldump .sql file.')
        parser.add_argument(
            '--app', required=True,
            help='Django app label that receives the data.',
        )
        parser.add_argument(
            '--map', default=None,
            help='JSON file mapping source-table-name → "app.Model".',
        )
        parser.add_argument(
            '--truncate', action='store_true',
            help='DELETE every row from each target model before ingesting.',
        )
        parser.add_argument(
            '--chunk', type=int, default=500,
            help='bulk_create chunk size (default 500).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Parse and resolve; do not write to the database.',
        )

    def handle(self, *args, **opts):
        path = opts['input']
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                text = fh.read()
        except OSError as e:
            raise CommandError(f'cannot read {path}: {e}')

        app_label = opts['app']
        try:
            apps.get_app_config(app_label)
        except LookupError:
            raise CommandError(f'unknown app: {app_label}')

        # Table → (columns, model) resolution.
        table_columns: dict[str, list[str]] = {}
        for name, ddl in iter_create_tables(text):
            table_columns[name] = _extract_column_order(ddl)

        table_map: dict[str, str] = {}
        if opts['map']:
            try:
                with open(opts['map'], 'r', encoding='utf-8') as fh:
                    table_map = json.load(fh)
            except OSError as e:
                raise CommandError(f'cannot read map {opts["map"]}: {e}')

        def resolve_model(table: str):
            dotted = table_map.get(table)
            if dotted:
                app, model = dotted.split('.', 1)
            else:
                app = app_label
                model = _default_model_name(app_label, table)
            try:
                return apps.get_model(app, model)
            except LookupError:
                return None

        if opts['truncate'] and not opts['dry_run']:
            seen_models = set()
            for table, _, _ in iter_inserts(text):
                model = resolve_model(table)
                if model and model not in seen_models:
                    model.objects.all().delete()
                    seen_models.add(model)
                    self.stdout.write(f'  truncated {model.__name__}')

        total_in = 0
        total_out = 0
        skipped_tables: list[str] = []

        for table, cols, rows in iter_inserts(text):
            total_in += len(rows)
            model = resolve_model(table)
            if model is None:
                skipped_tables.append(table)
                continue
            column_names = cols or table_columns.get(table)
            if not column_names:
                self.stderr.write(
                    f'  ! {table}: no column list; skipping {len(rows)} row(s)')
                continue
            if len(column_names) != len(rows[0]):
                self.stderr.write(
                    f'  ! {table}: column count mismatch '
                    f'({len(column_names)} cols, {len(rows[0])} values); skipping'
                )
                continue

            field_names = {f.column for f in model._meta.get_fields()
                           if hasattr(f, 'column')}
            field_names |= {f.name for f in model._meta.get_fields()
                            if hasattr(f, 'name')}

            unknown = [c for c in column_names if c not in field_names]
            if unknown:
                self.stderr.write(
                    f'  - {table}: dropping {len(unknown)} unknown column(s): '
                    f'{unknown}'
                )

            objs = []
            for row in rows:
                kwargs = {}
                for col, val in zip(column_names, row):
                    if col in field_names:
                        kwargs[col] = val
                objs.append(model(**kwargs))

            if opts['dry_run']:
                self.stdout.write(
                    f'  [dry] {table} → {model.__name__}: '
                    f'{len(objs)} row(s) would be loaded')
                total_out += len(objs)
                continue

            chunk = opts['chunk']
            with transaction.atomic():
                model.objects.bulk_create(objs, batch_size=chunk)
            self.stdout.write(
                f'  ✓ {table} → {model.__name__}: {len(objs)} row(s)')
            total_out += len(objs)

        if skipped_tables:
            self.stderr.write(
                f'Skipped tables with no model: {sorted(set(skipped_tables))}')
        self.stdout.write(
            self.style.SUCCESS(
                f'\n{total_out}/{total_in} rows ingested '
                f'({"dry-run" if opts["dry_run"] else "committed"}).'
            )
        )
