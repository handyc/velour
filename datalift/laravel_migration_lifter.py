"""Translate Laravel migration files into Django models.

Most Laravel apps ship their schema as ``database/migrations/*.php``
files containing ``Schema::create('users', function (Blueprint $table) {
$table->id(); $table->string('email')->unique(); ... });`` blueprints
rather than as raw SQL dumps. This lifter parses those blueprints and
emits an equivalent Django ``models.py``.

Why this matters: a Laravel project handed to a porter often comes
without a populated database — just the source tree + migrations.
This module lets `genmodels`-style output flow from the migrations
directly, no `mysqldump` required.

Same deterministic discipline as the other lifters: pure Python,
no LLM, no network. Used by `manage.py liftmigrations` (Laravel
side) and is also wired into ``liftall`` for the pure-source case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Records ────────────────────────────────────────────────────────

@dataclass
class ColumnRecord:
    name: str
    django_type: str
    kwargs: dict[str, object] = field(default_factory=dict)
    raw: str = ''


@dataclass
class TableRecord:
    name: str               # legacy table name (e.g. 'users')
    model_name: str = ''    # PascalCase ('User')
    columns: list[ColumnRecord] = field(default_factory=list)
    indexes: list[str] = field(default_factory=list)
    unique: list[list[str]] = field(default_factory=list)
    foreign_keys: list[tuple[str, str, str]] = field(default_factory=list)
    raw: str = ''
    skipped: list[str] = field(default_factory=list)


@dataclass
class MigrationLiftResult:
    tables: list[TableRecord] = field(default_factory=list)
    skipped_files: list[Path] = field(default_factory=list)


# ── Schema::create / Schema::table parsing ────────────────────────

_SCHEMA_CREATE_RE = re.compile(
    r"Schema::create\s*\(\s*"
    r"(?P<q>['\"])(?P<table>[^'\"]+)(?P=q)\s*,\s*"
    r"function\s*\([^)]*\)\s*\{",
)
_SCHEMA_TABLE_RE = re.compile(
    r"Schema::table\s*\(\s*"
    r"(?P<q>['\"])(?P<table>[^'\"]+)(?P=q)\s*,\s*"
    r"function\s*\([^)]*\)\s*\{",
)


def _extract_brace_block(src: str, start: int) -> tuple[str, int]:
    """Given a `{` at index `start`, return (body, end_index_after_})."""
    depth = 1
    in_str: str | None = None
    i = start + 1
    n = len(src)
    while i < n:
        ch = src[i]
        if in_str:
            if ch == '\\' and i + 1 < n:
                i += 2; continue
            if ch == in_str:
                in_str = None
            i += 1; continue
        if ch in ('"', "'"):
            in_str = ch
            i += 1; continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return src[start + 1:i], i + 1
        i += 1
    return src[start + 1:], n


# ── Column statement translation ─────────────────────────────────
#
# Each Blueprint column statement looks like:
#   $table->string('email', 100)->unique()->nullable();
# We parse: column kind (`string`), args (`'email', 100`), modifier
# chain (`unique()`, `nullable()`), and emit a Django field.

_COLUMN_STMT_RE = re.compile(
    r"\$table->(?P<kind>\w+)\s*\((?P<args>(?:[^()]|\([^()]*\))*)\)"
    r"(?P<chain>(?:->\w+\s*\((?:[^()]|\([^()]*\))*\))*)\s*;"
)
_CHAIN_CALL_RE2 = re.compile(
    r"->(?P<m>\w+)\s*\((?P<a>(?:[^()]|\([^()]*\))*)\)"
)


# Map Blueprint column-kind → Django field type.
# Some kinds emit fixed kwargs (e.g. timestamps()).
_KIND_TO_DJANGO: dict[str, tuple[str, dict]] = {
    'id':              ('BigAutoField',         {'primary_key': True}),
    'increments':      ('AutoField',            {'primary_key': True}),
    'bigIncrements':   ('BigAutoField',         {'primary_key': True}),
    'smallIncrements': ('SmallAutoField',       {'primary_key': True}),
    'mediumIncrements':('AutoField',            {'primary_key': True}),
    'tinyIncrements':  ('SmallAutoField',       {'primary_key': True}),

    'string':          ('CharField',            {'max_length': 255}),
    'char':            ('CharField',            {'max_length': 255}),
    'text':            ('TextField',            {}),
    'mediumText':      ('TextField',            {}),
    'longText':        ('TextField',            {}),
    'tinyText':        ('CharField',            {'max_length': 255}),

    'integer':         ('IntegerField',         {}),
    'bigInteger':      ('BigIntegerField',      {}),
    'smallInteger':    ('SmallIntegerField',    {}),
    'tinyInteger':     ('SmallIntegerField',    {}),
    'mediumInteger':   ('IntegerField',         {}),
    'unsignedInteger':       ('PositiveIntegerField',      {}),
    'unsignedBigInteger':    ('PositiveBigIntegerField',   {}),
    'unsignedSmallInteger':  ('PositiveSmallIntegerField', {}),
    'unsignedTinyInteger':   ('PositiveSmallIntegerField', {}),
    'unsignedMediumInteger': ('PositiveIntegerField',      {}),

    'decimal':         ('DecimalField',         {'max_digits': 8, 'decimal_places': 2}),
    'double':          ('FloatField',           {}),
    'float':           ('FloatField',           {}),

    'boolean':         ('BooleanField',         {}),
    'date':            ('DateField',            {}),
    'dateTime':        ('DateTimeField',        {}),
    'dateTimeTz':      ('DateTimeField',        {}),
    'time':            ('TimeField',            {}),
    'timeTz':          ('TimeField',            {}),
    'timestamp':       ('DateTimeField',        {}),
    'timestampTz':     ('DateTimeField',        {}),
    'year':            ('SmallIntegerField',    {}),

    'binary':          ('BinaryField',          {}),
    'json':            ('JSONField',            {}),
    'jsonb':           ('JSONField',            {}),
    'uuid':            ('UUIDField',            {}),
    'ipAddress':       ('GenericIPAddressField',{}),
    'macAddress':      ('CharField',            {'max_length': 17}),

    # Sugar / aliases
    'rememberToken':   ('CharField',            {'max_length': 100,
                                                  'null': True, 'blank': True}),
    'softDeletes':     ('DateTimeField',        {'null': True, 'blank': True}),
    'softDeletesTz':   ('DateTimeField',        {'null': True, 'blank': True}),

    # ENUM / SET need special handling because they take an array of choices.
    'enum':            ('CharField',            {'max_length': 32}),
    'set':             ('CharField',            {'max_length': 255}),

    # foreignId / foreign — translated specially below
    'foreignId':       ('ForeignKey',           {}),
    'foreignUuid':     ('ForeignKey',           {}),
}


def _split_args(s: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    in_str: str | None = None
    for ch in s:
        if in_str:
            buf.append(ch)
            if ch == in_str:
                in_str = None
            continue
        if ch in ('"', "'"):
            in_str = ch; buf.append(ch); continue
        if ch in '([{':
            depth += 1; buf.append(ch)
        elif ch in ')]}':
            depth -= 1; buf.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(buf)); buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append(''.join(buf))
    return [p.strip() for p in parts]


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _php_value_to_python(s: str) -> object:
    """Best-effort PHP literal → Python value."""
    s = s.strip()
    if not s:
        return None
    if s.lower() == 'null':
        return None
    if s.lower() == 'true':
        return True
    if s.lower() == 'false':
        return False
    if (s.startswith("'") and s.endswith("'")) or \
       (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s  # leave as raw expression


def _translate_blueprint_column(stmt: str) -> ColumnRecord | None:
    """Translate one ``$table->kind(args)->mod()->mod();`` to a ColumnRecord."""
    m = _COLUMN_STMT_RE.search(stmt)
    if not m:
        return None
    kind = m.group('kind')
    args_s = m.group('args')
    chain_s = m.group('chain')

    args = _split_args(args_s)

    # Special-cased kinds first.
    if kind == 'timestamps':
        # Two columns: created_at / updated_at. The caller handles
        # this by special-recognising 'timestamps' before us.
        return None
    if kind == 'timestampsTz':
        return None
    if kind in ('foreign', 'foreignId', 'foreignUuid'):
        # `foreign('user_id')->references('id')->on('users')` is
        # split across the chain — handled in the parent loop.
        col_name = _strip_quotes(args[0]) if args else 'fk'
        rec = ColumnRecord(
            name=col_name,
            django_type='ForeignKey',
            kwargs={
                'to': "'__SAME_APP__.Unknown'",  # filled in by parent
                'on_delete': 'models.DO_NOTHING',
            },
            raw=stmt,
        )
        return rec

    if kind not in _KIND_TO_DJANGO:
        return None

    django_type, base_kwargs = _KIND_TO_DJANGO[kind]
    kwargs = dict(base_kwargs)

    # Args[0] is normally the column name.
    if not args:
        # Sugar like ->rememberToken() or ->softDeletes() with no name.
        if kind == 'rememberToken':
            col_name = 'remember_token'
        elif kind in ('softDeletes', 'softDeletesTz'):
            col_name = 'deleted_at'
        else:
            col_name = '_unnamed_' + kind
    else:
        col_name = _strip_quotes(args[0])

    # CharField max_length from arg[1] if given.
    if django_type == 'CharField' and len(args) >= 2:
        try:
            kwargs['max_length'] = int(args[1].strip())
        except ValueError:
            pass

    # DecimalField max_digits / decimal_places from args.
    if django_type == 'DecimalField':
        if len(args) >= 2:
            try:
                kwargs['max_digits'] = int(args[1].strip())
            except ValueError:
                pass
        if len(args) >= 3:
            try:
                kwargs['decimal_places'] = int(args[2].strip())
            except ValueError:
                pass

    # ENUM choices from args[1] (array literal).
    if kind == 'enum' and len(args) >= 2:
        # args[1] is something like `['draft', 'published']`. Extract.
        choices_src = args[1].strip().lstrip('[').rstrip(']')
        choices = [_strip_quotes(c) for c in _split_args(choices_src)]
        if choices:
            kwargs['max_length'] = max(len(c) for c in choices)
            kwargs['choices'] = choices

    # Process the chain modifiers.
    for cm in _CHAIN_CALL_RE2.finditer(chain_s):
        mod = cm.group('m')
        a = cm.group('a').strip()
        if mod == 'nullable':
            kwargs['null'] = True
            kwargs['blank'] = True
        elif mod == 'unique':
            kwargs['unique'] = True
        elif mod == 'default':
            kwargs['default'] = _php_value_to_python(a)
        elif mod == 'unsigned':
            # Django doesn't have unsigned generic; try to upgrade type.
            if django_type == 'IntegerField':
                django_type = 'PositiveIntegerField'
            elif django_type == 'BigIntegerField':
                django_type = 'PositiveBigIntegerField'
            elif django_type == 'SmallIntegerField':
                django_type = 'PositiveSmallIntegerField'
        elif mod == 'comment':
            kwargs['help_text'] = _strip_quotes(a)
        elif mod == 'index':
            kwargs['db_index'] = True
        elif mod == 'primary':
            kwargs['primary_key'] = True
        elif mod in ('useCurrent', 'useCurrentOnUpdate'):
            kwargs['auto_now_add'] = True
        elif mod == 'autoIncrement':
            # Already handled by AutoField.
            pass
        elif mod == 'after':
            pass  # column ordering — Django doesn't care
        elif mod == 'change':
            pass  # this is `Schema::table` modifying an existing column
        # `references('id')->on('users')` chains are gathered later
        # by the parent if this is a foreignId.

    return ColumnRecord(
        name=col_name, django_type=django_type, kwargs=kwargs, raw=stmt,
    )


# ── ForeignKey chain translation ──────────────────────────────────

_FK_CHAIN_RE = re.compile(
    r"\$table->(?P<kind>foreign|foreignId|foreignUuid)\s*\("
    r"(?P<args>(?:[^()]|\([^()]*\))*)\)"
    r"(?P<chain>(?:->\w+\s*\((?:[^()]|\([^()]*\))*\))*)\s*;"
)


def _resolve_foreign_keys(table: TableRecord, body: str) -> None:
    """Walk the body and rewire ForeignKey columns with their
    references / on / onDelete data."""
    for m in _FK_CHAIN_RE.finditer(body):
        col_name = _strip_quotes(_split_args(m.group('args'))[0])
        chain = m.group('chain')
        ref_col = 'id'
        ref_table = ''
        on_delete = 'models.DO_NOTHING'
        for cm in _CHAIN_CALL_RE2.finditer(chain):
            mod = cm.group('m'); a = cm.group('a').strip()
            if mod == 'references':
                ref_col = _strip_quotes(_split_args(a)[0]) if a else 'id'
            elif mod == 'on':
                ref_table = _strip_quotes(_split_args(a)[0]) if a else ''
            elif mod == 'constrained':
                # `constrained('users')` shorthand for ->references('id')->on('users')
                if a:
                    ref_table = _strip_quotes(_split_args(a)[0])
                else:
                    # Default: column name minus '_id'.
                    if col_name.endswith('_id'):
                        ref_table = col_name[:-3] + 's'
                    else:
                        ref_table = col_name + 's'
            elif mod == 'onDelete':
                policy = _strip_quotes(a).lower()
                on_delete = {
                    'cascade':    'models.CASCADE',
                    'set null':   'models.SET_NULL',
                    'restrict':   'models.PROTECT',
                    'no action':  'models.DO_NOTHING',
                }.get(policy, 'models.DO_NOTHING')
            elif mod == 'cascadeOnDelete':
                on_delete = 'models.CASCADE'
            elif mod == 'restrictOnDelete':
                on_delete = 'models.PROTECT'
            elif mod == 'nullOnDelete':
                on_delete = 'models.SET_NULL'
        # Find the matching ColumnRecord and update / inject.
        col = next((c for c in table.columns if c.name == col_name), None)
        if col is None:
            col = ColumnRecord(name=col_name, django_type='ForeignKey',
                                kwargs={}, raw=m.group(0))
            table.columns.append(col)
        col.django_type = 'ForeignKey'
        col.kwargs.setdefault('to', f"'__SAME_APP__.{_pascal(ref_table)}'")
        if ref_table:
            col.kwargs['to'] = f"'__SAME_APP__.{_pascal(ref_table)}'"
        col.kwargs['on_delete'] = on_delete
        # ForeignKey doesn't take max_length etc.; clean up.
        col.kwargs.pop('max_length', None)


# ── Index / unique parsing ────────────────────────────────────────

_INDEX_RE = re.compile(
    r"\$table->(?P<kind>index|unique|primary)\s*\((?P<args>(?:[^()]|\([^()]*\))*)\)\s*;"
)


def _collect_indexes(table: TableRecord, body: str) -> None:
    for m in _INDEX_RE.finditer(body):
        kind = m.group('kind')
        a = m.group('args').strip()
        # arg may be a string or an array.
        if a.startswith('['):
            cols = [_strip_quotes(c) for c in _split_args(a.lstrip('[').rstrip(']'))]
        else:
            cols = [_strip_quotes(c) for c in _split_args(a)]
        if not cols:
            continue
        if kind == 'index':
            table.indexes.extend(cols)
        elif kind == 'unique':
            table.unique.append(cols)
        elif kind == 'primary' and len(cols) == 1:
            # Mark the column as primary_key.
            col = next((c for c in table.columns if c.name == cols[0]), None)
            if col:
                col.kwargs['primary_key'] = True


# ── PascalCase + parsing entry point ──────────────────────────────

def _pascal(name: str) -> str:
    parts = re.split(r'[_\W]+', name)
    return ''.join(p[:1].upper() + p[1:].lower() for p in parts if p)


def parse_blueprint(body: str) -> list[ColumnRecord]:
    """Parse a Schema::create body and return its columns."""
    columns: list[ColumnRecord] = []

    # Strip comments first.
    body = re.sub(r'/\*.*?\*/', '', body, flags=re.DOTALL)
    body = re.sub(r'(?m)//.*?$', '', body)

    # Handle `$table->timestamps()` — expands to created_at + updated_at.
    if re.search(r"\$table->timestamps\s*\(\s*\)", body):
        columns.append(ColumnRecord(
            name='created_at', django_type='DateTimeField',
            kwargs={'auto_now_add': True}, raw='$table->timestamps()',
        ))
        columns.append(ColumnRecord(
            name='updated_at', django_type='DateTimeField',
            kwargs={'auto_now': True}, raw='$table->timestamps()',
        ))

    if re.search(r"\$table->softDeletes\s*\(\s*\)", body):
        columns.append(ColumnRecord(
            name='deleted_at', django_type='DateTimeField',
            kwargs={'null': True, 'blank': True}, raw='$table->softDeletes()',
        ))

    for m in _COLUMN_STMT_RE.finditer(body):
        # Skip the ones already handled above.
        if m.group('kind') in ('timestamps', 'timestampsTz', 'softDeletes',
                                 'softDeletesTz', 'index', 'unique',
                                 'primary'):
            continue
        col = _translate_blueprint_column(m.group(0))
        if col is not None:
            columns.append(col)

    return columns


def parse_migration_file(path: Path) -> list[TableRecord]:
    """Parse a single Laravel migration file. Returns a list of
    TableRecord — one per ``Schema::create`` block."""
    text = path.read_text(encoding='utf-8', errors='replace')
    out: list[TableRecord] = []
    for m in _SCHEMA_CREATE_RE.finditer(text):
        body, _ = _extract_brace_block(text, m.end() - 1)
        table_name = m.group('table')
        cols = parse_blueprint(body)
        rec = TableRecord(
            name=table_name,
            model_name=_pascal(table_name).rstrip('s') or _pascal(table_name),
            columns=cols,
            raw=text[m.start():m.start() + 200],
        )
        _resolve_foreign_keys(rec, body)
        _collect_indexes(rec, body)
        out.append(rec)
    return out


# ── Theme-style walker ────────────────────────────────────────────

def parse_migrations(migrations_dir: Path) -> MigrationLiftResult:
    """Walk a ``database/migrations`` directory and parse every PHP file."""
    result = MigrationLiftResult()
    if not migrations_dir.is_dir():
        return result
    for path in sorted(migrations_dir.glob('*.php')):
        try:
            tables = parse_migration_file(path)
        except OSError:
            result.skipped_files.append(path.name)
            continue
        result.tables.extend(tables)
    return result


# ── models.py renderer ────────────────────────────────────────────

def render_models(result: MigrationLiftResult, app_label: str) -> str:
    out = [
        '"""Auto-generated by datalift liftmigrations.',
        '',
        'Translated from Laravel database/migrations Schema::create',
        'blueprints. Review every model before migrating: max_length,',
        'choices, foreign-key targets, and on_delete policy are all',
        'best-effort inferences.',
        '"""',
        'from django.db import models',
        '',
        '',
    ]
    for tbl in result.tables:
        if not tbl.columns:
            continue  # likely a Schema::table modification, skip
        out.append(f'class {tbl.model_name}(models.Model):')
        out.append(f'    """Generated from Laravel migration `{tbl.name}`."""')
        out.append('')
        # Emit each column.
        for col in tbl.columns:
            kwargs_src = ', '.join(
                f'{k}={_kwarg_repr(v, app_label)}'
                for k, v in col.kwargs.items()
            )
            out.append(f'    {col.name} = models.{col.django_type}('
                       f'{kwargs_src})')
        # Meta block
        out.append('')
        out.append('    class Meta:')
        out.append(f"        db_table = {tbl.name!r}")
        if tbl.unique:
            for u in tbl.unique:
                out.append(f"        # unique together: {u!r}")
        out.append('')
    return '\n'.join(out)


def _kwarg_repr(v: object, app_label: str) -> str:
    if isinstance(v, str):
        if v.startswith('models.') or v.startswith("'__SAME_APP__"):
            return v.replace('__SAME_APP__', app_label)
        return repr(v)
    if isinstance(v, list):
        return '[' + ', '.join(repr(x) for x in v) + ']'
    return repr(v)


# ── Worklist + apply ──────────────────────────────────────────────

def render_worklist(result: MigrationLiftResult, app_label: str,
                    migrations_dir: Path) -> str:
    lines = [
        f'# liftmigrations worklist — {migrations_dir.name}',
        '',
        f'Target app: `{app_label}`. Generated by `datalift liftmigrations`.',
        '',
        '## Tables found',
        '',
    ]
    if not result.tables:
        lines.append('_(none — no `Schema::create(...)` calls found)_')
    for tbl in result.tables:
        lines.append(f'- `{tbl.name}` → `{tbl.model_name}` '
                     f'({len(tbl.columns)} column(s))')
    lines += ['', '## Skipped files', '']
    if not result.skipped_files:
        lines.append('_(none)_')
    for f in result.skipped_files:
        lines.append(f'- `{f}`')
    return '\n'.join(lines)


def apply(result: MigrationLiftResult, project_root: Path,
          app_label: str, dry_run: bool = False) -> list[str]:
    log: list[str] = []
    if not result.tables:
        return log
    app_dir = project_root / app_label
    if not dry_run:
        app_dir.mkdir(parents=True, exist_ok=True)
    target = app_dir / 'models_migrations.py'
    text = render_models(result, app_label)
    if not dry_run:
        target.write_text(text, encoding='utf-8')
    log.append(f'models    → {target.relative_to(project_root)} '
               f'({len(result.tables)} model(s))')
    return log
