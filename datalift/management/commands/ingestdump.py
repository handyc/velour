"""Ingest a mysqldump's data rows into a Django app's SQLite.

    python manage.py ingestdump path/to/full_dump.sql \\
        --app myapp [--map table_map.json] [--truncate] \\
        [--chunk 500] [--dry-run] [--no-fk-sweep]

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
* Pass ``--map table_map.json`` with entries in one of two forms:

      {
        "users":    "myapp.User",
        "studies": {
          "model":         "myapp.Study",
          "drop_columns":  ["internal_flag"],
          "value_maps":    {"study_type": {"Linguistics": "linguistics"}},
          "synthesize":    {"username": "email"},
          "dedupe_by":     "username"
        }
      }

* Tables without a mapping are skipped with a warning.

Column resolution: the INSERT's own column list is preferred. If the
INSERT has no columns, the command reads them from the CREATE TABLE
block in the same dump. Unknown columns on the model are dropped with
a warning.

The rich per-table spec supports five legacy-data knobs that come up
on almost every port of a custom framework to Django:

* ``drop_columns``: legacy columns to NOT send to the model (e.g.
  Laravel ``remember_token`` when your Django model doesn't have one).
* ``value_maps``: per-column enum translation, e.g. legacy
  ``"Male"/"Female"`` to your model's choice keys ``"M"/"F"``. Use
  the sentinel ``"__default__"`` to catch unknown values.
* ``synthesize``: compute a Django field's value from another legacy
  column on the same row, e.g. ``{"username": "email"}``. Falls back
  to ``<fieldname>_<id>`` when the source column is null/empty.
* ``dedupe_by``: after all row transforms but before bulk_create,
  collapse rows that collide on this field — classic fix for legacy
  tables where two rows share an email but Django needs a unique
  username. The row with the highest legacy ``id`` wins.
* ``rewrite_laravel_passwords``: the name of a column that holds
  Laravel bcrypt (``$2y$``) hashes. At load time they're rewritten to
  Django's ``bcrypt$$2b$`` prefix so existing passwords keep working.
* ``model``: the usual "app.Model" target; only required in the rich
  form (the string form IS the model).

After every table is loaded, the ingest runs a SQLite
``PRAGMA foreign_key_check`` sweep and drops child rows whose parent
is missing — catches orphan appointments/junction rows from hard
deletes in the legacy system. Disable with ``--no-fk-sweep``.
"""

from __future__ import annotations

import json
import re

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from datalift.dump_parser import iter_create_tables, iter_inserts


_COL_DEF_RE = re.compile(
    # Reject lines that START a constraint/index declaration. The
    # keyword match requires an accompanying KEY/INDEX/paren so we
    # don't mistake a column named ``fulltext`` / ``spatial`` /
    # ``check`` (Pagila has ``fulltext tsvector``) for a constraint.
    r"^\s*(?!"
      r"CONSTRAINT\s+|"
      r"PRIMARY\s+KEY\b|"
      r"FOREIGN\s+KEY\b|"
      r"UNIQUE\s+(?:KEY\b|\()|"
      r"KEY\s+|"
      r"INDEX\s*(?:\S|\()|"
      r"FULLTEXT\s+(?:KEY|INDEX)\b|"
      r"SPATIAL\s+(?:KEY|INDEX)\b|"
      r"CHECK\s*\("
    r")"
    r"[`\"]?(?P<name>[A-Za-z_][A-Za-z0-9_]*)[`\"]?\s+",
    re.IGNORECASE,
)


def _extract_column_order(ddl: str) -> list[str]:
    """Pull the column names out of a CREATE TABLE DDL block, in order."""
    body = ddl[ddl.index('(') + 1 : ddl.rindex(')')]
    # Unwrap version-gated comments so the column definitions inside
    # are parsed as regular lines (see model_generator for the matching
    # rationale). Strip SQL line comments too.
    body = re.sub(r'--[^\n]*', '', body)
    body = re.sub(r'/\*!\d+\s+', '', body)
    body = re.sub(r'\*/', '', body)
    body = re.sub(r'/\*[^*]*\*/', '', body)
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
    stem = table
    prefix = app_label + '_'
    if stem.startswith(prefix):
        stem = stem[len(prefix):]
    return ''.join(part.capitalize() for part in stem.split('_') if part)


def _apply_value_map(value, vmap):
    """Translate a cell value through a per-column value_maps dict.

    Recognises the sentinel ``"__default__"`` as the fallback for
    unknown values. ``None`` passes through unchanged.
    """
    if value is None:
        return None
    if value in vmap:
        return vmap[value]
    if "__default__" in vmap:
        return vmap["__default__"]
    return value


# Date formats we try in order when a legacy dump emits something
# Django's Date/DateTimeField to_python won't parse on its own.
# Chinook uses YYYY/M/D; some European exports use DD-MM-YYYY etc.
_DATE_FORMATS = (
    '%Y/%m/%d',
    '%Y/%m/%d %H:%M:%S',
    '%d-%m-%Y',
    '%d-%m-%Y %H:%M:%S',
    '%d/%m/%Y',
    '%d.%m.%Y',
    '%Y%m%d',
)


def _coerce_binary_value(val):
    """Turn a string-shaped bytea value into actual bytes.

    * ``'\\x89504e47…'`` → ``b'\\x89\\x50\\x4e\\x47…'`` (pg_dump
      emits bytea values in this hex-escape form inside quoted
      strings; the backslash is preserved by the string parser).
    * ``'plain text'`` → UTF-8 bytes (some schemas still stuff text
      into a BLOB column).
    * ``bytes`` → passed through.
    * ``None`` → passed through.
    """
    if val is None or isinstance(val, (bytes, bytearray, memoryview)):
        return val
    if isinstance(val, str):
        if val.startswith('\\x'):
            hex_part = val[2:]
            try:
                return bytes.fromhex(hex_part)
            except ValueError:
                pass
        return val.encode('utf-8', 'replace')
    return val


def _coerce_date_string(val):
    """Best-effort normalise a date string into Django's preferred
    ``YYYY-MM-DD[ HH:MM:SS]`` form. Non-string values pass through
    untouched. Unparseable strings also pass through so Django still
    raises a clear ValidationError with the original value."""
    if not isinstance(val, str):
        return val
    from datetime import datetime
    # Already ISO-like?
    if re.match(r'^\d{4}-\d{2}-\d{2}', val):
        return val
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(val, fmt)
            return dt.isoformat(sep=' ')
        except ValueError:
            continue
    return val


def _dedupe_rows(objs, key_field, report):
    """Collapse rows that share a value on ``key_field``. Keeps the row
    with the highest ``id`` (most recent in legacy systems that use
    autoincrement). Returns (kept_objs, n_dropped).
    """
    by_key = {}
    dropped = []
    for obj in objs:
        k = getattr(obj, key_field, None)
        if k is None:
            by_key[id(obj)] = obj  # unique by python id; will keep all
            continue
        prev = by_key.get(k)
        if prev is None:
            by_key[k] = obj
            continue
        win, los = ((obj, prev)
                    if (getattr(obj, 'id', 0) or 0) > (getattr(prev, 'id', 0) or 0)
                    else (prev, obj))
        by_key[k] = win
        dropped.append((getattr(los, 'id', None), k, getattr(win, 'id', None)))
    if dropped:
        report(f"  deduped {len(dropped)} row(s) on {key_field}:")
        for loser_id, k, winner_id in dropped[:20]:
            report(f"    legacy id {loser_id} ({k!r}) → superseded by id {winner_id}")
        if len(dropped) > 20:
            report(f"    … and {len(dropped) - 20} more")
    return list(by_key.values()), len(dropped)


def _fk_orphan_sweep(report):
    """Drop child rows whose FK parent is missing (SQLite only).

    Loops until `PRAGMA foreign_key_check` reports nothing — deleting
    a child can't create a new orphan since we never touch parents,
    but the loop is cheap insurance. Returns {table: count_dropped}.
    """
    dropped = {}
    with connection.cursor() as c:
        for _ in range(5):
            c.execute("PRAGMA foreign_key_check")
            violations = c.fetchall()
            if not violations:
                break
            by_tbl = {}
            for row in violations:
                tbl, rowid = row[0], row[1]
                by_tbl.setdefault(tbl, set()).add(rowid)
            for tbl, rowids in by_tbl.items():
                ids = sorted(rowids)
                ph = ",".join(["%s"] * len(ids))
                c.execute(
                    f'DELETE FROM "{tbl}" WHERE rowid IN ({ph})', ids
                )
                dropped[tbl] = dropped.get(tbl, 0) + len(ids)
    for tbl, n in dropped.items():
        report(f"  dropped {n} orphan row(s) from {tbl} "
               "(missing parent in legacy data)")
    return dropped


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
            help='JSON file mapping source-table-name → "app.Model" '
                 'or a rich spec dict (see module docstring).',
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
        parser.add_argument(
            '--no-fk-sweep', action='store_true',
            help='Skip the post-load PRAGMA foreign_key_check pass that '
                 'drops child rows whose FK parent is missing.',
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

        table_columns: dict[str, list[str]] = {}
        for name, ddl in iter_create_tables(text):
            table_columns[name] = _extract_column_order(ddl)

        raw_map: dict = {}
        if opts['map']:
            try:
                with open(opts['map'], 'r', encoding='utf-8') as fh:
                    raw_map = json.load(fh)
            except OSError as e:
                raise CommandError(f'cannot read map {opts["map"]}: {e}')

        # Maps come in two shapes. Both are supported for backwards-
        # compatibility with the pre-genmodels hand-written form:
        #   flat:     {"tablename": "app.Model", "other": {...}, ...}
        #   nested:   {"_meta": ..., "tables": {"tablename": ...},
        #              "skip_tables": [...]}
        table_entries = raw_map.get('tables') if isinstance(
            raw_map.get('tables'), dict) else raw_map
        skip_tables = set(raw_map.get('skip_tables') or [])

        def resolve_spec(table: str):
            """Return (model, spec) or (None, None) for this table.

            Spec is a normalized dict with keys drop_columns,
            value_maps, synthesize, dedupe_by. The table map may give
            either a plain "app.Model" string or a full dict.
            """
            if table in skip_tables:
                return None, None
            entry = table_entries.get(table)
            spec = {
                "drop_columns": [],
                "value_maps": {},
                "synthesize": {},
                "dedupe_by": None,
                "rewrite_laravel_passwords": None,
            }
            if isinstance(entry, dict):
                dotted = entry.get("model") or f"{app_label}.{_default_model_name(app_label, table)}"
                spec["drop_columns"] = list(entry.get("drop_columns", []))
                spec["value_maps"] = dict(entry.get("value_maps", {}))
                spec["synthesize"] = dict(entry.get("synthesize", {}))
                spec["dedupe_by"] = entry.get("dedupe_by")
                spec["rewrite_laravel_passwords"] = entry.get(
                    "rewrite_laravel_passwords")
            elif isinstance(entry, str):
                dotted = entry
            else:
                dotted = f"{app_label}.{_default_model_name(app_label, table)}"
            try:
                app, model = dotted.split('.', 1)
                return apps.get_model(app, model), spec
            except (LookupError, ValueError):
                return None, None

        if opts['truncate'] and not opts['dry_run']:
            seen_models = set()
            for table, _, _ in iter_inserts(text):
                model, _ = resolve_spec(table)
                if model and model not in seen_models:
                    model.objects.all().delete()
                    seen_models.add(model)
                    self.stdout.write(f'  truncated {model.__name__}')

        total_in = 0
        total_out = 0
        skipped_tables: list[str] = []

        # We accumulate all writes in one transaction so the FK-orphan
        # sweep at the end sees a consistent graph.
        with transaction.atomic():
            for table, cols, rows in iter_inserts(text):
                total_in += len(rows)
                model, spec = resolve_spec(table)
                if model is None:
                    skipped_tables.append(table)
                    continue
                column_names = cols or table_columns.get(table)
                if not column_names:
                    self.stderr.write(
                        f'  ! {table}: no column list; skipping '
                        f'{len(rows)} row(s)')
                    continue
                if len(column_names) != len(rows[0]):
                    self.stderr.write(
                        f'  ! {table}: column count mismatch '
                        f'({len(column_names)} cols, {len(rows[0])} values); '
                        'skipping')
                    continue

                field_names = {f.column for f in model._meta.get_fields()
                               if hasattr(f, 'column')}
                field_names |= {f.name for f in model._meta.get_fields()
                                if hasattr(f, 'name')}

                # Map FK Python-name and column-name → attname. When
                # the legacy dump has a column `emp_no` that we've
                # promoted to a ForeignKey(Employee), the constructor
                # won't accept `model(emp_no=10001)` (needs an instance);
                # we have to route to the raw-PK attribute `emp_no_id`.
                fk_attname = {}
                for f in model._meta.get_fields():
                    if getattr(f, 'many_to_one', False):
                        fk_attname[f.name] = f.attname
                        if hasattr(f, 'column'):
                            fk_attname[f.column] = f.attname

                # Fields expecting a date/datetime — for these we'll
                # coerce unusual string formats (Chinook stores
                # `YYYY/M/D`, some dumps use `DD-MM-YYYY`) before
                # Django's field.to_python() trips over them.
                # Similarly for BinaryField — pg_dump emits bytea
                # values as `'\x<hex>'` text literals, which our
                # parser returns as a str; we need bytes for Django.
                date_fields = set()
                binary_fields = set()
                for f in model._meta.get_fields():
                    cls = f.__class__.__name__
                    if cls in ('DateField', 'DateTimeField'):
                        date_fields.add(f.name)
                        if hasattr(f, 'attname'):
                            date_fields.add(f.attname)
                    elif cls == 'BinaryField':
                        binary_fields.add(f.name)
                        if hasattr(f, 'attname'):
                            binary_fields.add(f.attname)

                drop_set = set(spec["drop_columns"])

                # Case-normalised alias map: Chinook's INSERT lists
                # columns as PascalCase (`GenreId`, `Name`) while our
                # generated Django fields are snake_case (`genre_id`,
                # `name`). Any INSERT column that doesn't match a field
                # directly gets snake_cased + lower-cased; if that hits
                # a field name, we alias through.
                def _snakeify(s: str) -> str:
                    # Lightweight CamelCase → snake_case that mirrors
                    # model_generator.column_to_field_name. Doesn't
                    # import it to keep the command self-contained.
                    s1 = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s)
                    s2 = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', s1)
                    return s2.lower()
                col_alias = {}
                for c in column_names:
                    if c in field_names or c in drop_set:
                        continue
                    sn = _snakeify(c)
                    if sn in field_names or sn in fk_attname:
                        col_alias[c] = sn
                        continue
                    # FK field: strip trailing _id
                    if sn.endswith('_id') and sn[:-3] in fk_attname:
                        col_alias[c] = sn[:-3]
                        continue
                    # Lowercase exact match (e.g. ALL CAPS column)
                    if c.lower() in field_names:
                        col_alias[c] = c.lower()

                unknown = [c for c in column_names
                           if c not in field_names
                           and c not in drop_set
                           and c not in col_alias]
                if unknown:
                    self.stderr.write(
                        f'  - {table}: dropping {len(unknown)} unknown column(s): '
                        f'{unknown}'
                    )

                vmaps = spec["value_maps"]
                synth = spec["synthesize"]
                pw_col = spec.get("rewrite_laravel_passwords")
                n_pw_rewritten = 0

                objs = []
                for row in rows:
                    row_dict = dict(zip(column_names, row))
                    kwargs = {}
                    for col, val in row_dict.items():
                        if col in drop_set:
                            continue
                        # Translate case-mismatched INSERT columns
                        # into their Django field name (e.g. Chinook's
                        # `GenreId` → `genre_id`).
                        if col in col_alias:
                            col = col_alias[col]
                        if col not in field_names:
                            continue
                        if col in vmaps:
                            val = _apply_value_map(val, vmaps[col])
                        if (col == pw_col and isinstance(val, str)
                                and val.startswith('$2y$')):
                            val = 'bcrypt$' + val.replace(
                                '$2y$', '$2b$', 1)
                            n_pw_rewritten += 1
                        # FK fields: route to the attname (e.g. emp_no
                        # → emp_no_id) so the constructor accepts a
                        # raw PK without having to fetch the target.
                        target_field = fk_attname.get(col, col)
                        if target_field in date_fields:
                            val = _coerce_date_string(val)
                        elif target_field in binary_fields:
                            val = _coerce_binary_value(val)
                        kwargs[target_field] = val
                    for dest, src in synth.items():
                        kwargs[dest] = (row_dict.get(src)
                                        or f"{dest}_{row_dict.get('id')}")
                    objs.append(model(**kwargs))

                if n_pw_rewritten:
                    self.stdout.write(
                        f'  rewrote {n_pw_rewritten} Laravel $2y$ password '
                        f'hash(es) → Django bcrypt$$2b$ format')

                if spec["dedupe_by"]:
                    objs, _ = _dedupe_rows(
                        objs, spec["dedupe_by"], self.stdout.write
                    )

                if opts['dry_run']:
                    self.stdout.write(
                        f'  [dry] {table} → {model.__name__}: '
                        f'{len(objs)} row(s) would be loaded')
                    total_out += len(objs)
                    continue

                model.objects.bulk_create(objs, batch_size=opts['chunk'])
                self.stdout.write(
                    f'  ✓ {table} → {model.__name__}: {len(objs)} row(s)')
                total_out += len(objs)

            # Sweep orphans inside the same atomic block so a violation
            # leaves the DB unchanged.
            if (not opts['dry_run']
                    and not opts['no_fk_sweep']
                    and connection.vendor == 'sqlite'):
                _fk_orphan_sweep(self.stdout.write)

        if skipped_tables:
            self.stderr.write(
                f'Skipped tables with no model: {sorted(set(skipped_tables))}')
        self.stdout.write(
            self.style.SUCCESS(
                f'\n{total_out}/{total_in} rows ingested '
                f'({"dry-run" if opts["dry_run"] else "committed"}).'
            )
        )
