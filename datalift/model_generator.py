"""Smart Django-model generator for Datalift.

Takes a mysqldump (or a schema-only extract from ``dumpschema``) and
emits a runnable ``models.py`` plus a starter ``table_map.json`` that
``ingestdump`` can load. The goal is that the hand-written step in
the Datalift workflow shrinks from "write every model by hand" to
"review and tweak the generated file".

Inference rules, briefly:

  Column types
    * ``varchar(N)`` → ``CharField(max_length=N)`` or a more specific
      subclass if the column name is a known pattern (``EmailField``
      for ``*email*``, ``URLField`` for ``*url*``/``website``,
      ``SlugField`` for ``slug``/``*_slug``, ``GenericIPAddressField``
      for ``ip``/``*_ip_address``).
    * ``text/mediumtext/longtext`` → ``TextField``.
    * ``tinyint(1)`` → ``BooleanField``; ``tinyint`` otherwise →
      ``PositiveSmallIntegerField``.
    * ``int`` unsigned → ``PositiveIntegerField``; signed → ``IntegerField``.
    * ``bigint`` → ``BigIntegerField``; ``smallint`` → ``SmallIntegerField``.
    * ``decimal(M,N)`` → ``DecimalField(max_digits=M, decimal_places=N)``.
    * ``float``/``double`` → ``FloatField``.
    * ``date``/``time``/``datetime``/``timestamp`` → matching field.
    * ``enum(...)`` → generated ``TextChoices`` subclass + CharField.
    * ``json`` → ``JSONField``; ``blob``/``binary`` → ``BinaryField``.

  Relationships
    * ``FOREIGN KEY (col) REFERENCES tbl(col)`` → ``ForeignKey``. The
      field is named after the source column with ``_id`` stripped.
    * A table whose non-meta columns are exactly two FKs (plus
      ``id``/``created_at``/``updated_at``) is flagged as a M2M
      candidate in a comment (left as a regular model so the port is
      non-destructive).

  Laravel conventions
    * ``id`` auto_increment → ``BigAutoField(primary_key=True)``.
    * ``created_at``/``updated_at`` timestamp → ``DateTimeField`` with
      ``auto_now_add``/``auto_now`` respectively (only when the column
      has a CURRENT_TIMESTAMP default, matching Laravel's usage).
    * ``deleted_at`` → nullable DateTimeField + a soft-delete note.
    * ``remember_token`` → dropped from the model and added to the
      map's ``drop_columns`` list.
    * ``password`` → kept as CharField; the map is configured to use
      ``ingestdump``'s Laravel bcrypt rewrite at load time (when we
      add that feature to ingestdump).

  Meta
    * Always emits ``db_table = '<legacy_name>'`` so the Django table
      stays pinned to the legacy name and existing data keeps working.
    * ``ordering`` picks ``['-created_at']`` when that column exists,
      else ``['id']``.
    * Pluralisation edge cases (``baby`` → ``babies`` etc.) are handled.

  __str__
    * First available of ``name``, ``title``, ``label``, ``slug``,
      ``email``, or falls back to ``f'#{self.pk}'``.

The output of this module is authoritative only as a starting point;
the operator is expected to review and refine. Nothing is destructive.
"""

from __future__ import annotations

import json
import keyword
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Iterable

from datalift.dump_parser import iter_create_tables, strip_auto_increment


# ═════════════════════════════════════════════════════════════════════
# Column + table metadata
# ═════════════════════════════════════════════════════════════════════

@dataclass
class Column:
    name: str
    raw_type: str
    not_null: bool
    default: Optional[str] = None
    is_auto_inc: bool = False
    is_primary: bool = False
    is_unique: bool = False
    on_update_current_ts: bool = False


@dataclass
class ForeignKey:
    columns: List[str]
    ref_table: str
    ref_columns: List[str]
    on_delete: str = 'CASCADE'


@dataclass
class Table:
    name: str
    columns: List[Column] = field(default_factory=list)
    primary_key: List[str] = field(default_factory=list)
    uniques: List[List[str]] = field(default_factory=list)
    foreign_keys: List[ForeignKey] = field(default_factory=list)


# ═════════════════════════════════════════════════════════════════════
# DDL parsing
# ═════════════════════════════════════════════════════════════════════

_COL_LINE_RE = re.compile(
    r'^\s*[`"](?P<name>[^`"]+)[`"]\s+(?P<rest>.+?)\s*$'
)
_CONSTRAINT_RE = re.compile(
    r'^\s*(?:CONSTRAINT\s+[`"][^`"]+[`"]\s+)?'
    r'(?P<kind>PRIMARY\s+KEY|UNIQUE\s+KEY|FOREIGN\s+KEY|KEY|INDEX|FULLTEXT|SPATIAL|CHECK)\b',
    re.IGNORECASE,
)
_FK_RE = re.compile(
    r'FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+[`"]?(?P<ref>[^\s`"(]+)[`"]?\s*\(([^)]+)\)'
    r'(?:\s+ON\s+DELETE\s+(?P<ondel>RESTRICT|CASCADE|SET\s+NULL|NO\s+ACTION|SET\s+DEFAULT))?',
    re.IGNORECASE,
)
_PK_RE = re.compile(r'PRIMARY\s+KEY\s*\(([^)]+)\)', re.IGNORECASE)
_UNIQUE_RE = re.compile(
    r'UNIQUE\s+(?:KEY\s+[`"][^`"]+[`"]\s+)?\(([^)]+)\)', re.IGNORECASE
)


def _split_body_lines(body: str) -> List[str]:
    """Split a CREATE TABLE body into logical lines, respecting
    paren depth so enum(a,b,c) doesn't get broken up."""
    out: List[str] = []
    depth = 0
    buf: List[str] = []
    in_s = False
    q = ''
    for ch in body:
        if in_s:
            buf.append(ch)
            if ch == q:
                in_s = False
            continue
        if ch in ("'", '"', '`'):
            in_s = True
            q = ch
            buf.append(ch)
            continue
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            out.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        tail = ''.join(buf).strip()
        if tail:
            out.append(tail)
    return out


def _strip_colnames(s: str) -> List[str]:
    """Turn ```col1`, `col2`, `col3`` into ['col1', 'col2', 'col3']."""
    return [m for m in re.findall(r'[`"]([^`"]+)[`"]', s)]


def parse_create_table(ddl: str) -> Table:
    """Parse a CREATE TABLE DDL block into a structured Table."""
    m = re.search(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"]?([^\s`"(]+)[`"]?\s*\(',
                  ddl, re.IGNORECASE)
    if not m:
        raise ValueError('no CREATE TABLE header')
    name = m.group(1)
    body = ddl[ddl.index('(', m.end() - 1) + 1: ddl.rindex(')')]
    t = Table(name=name)

    for line in _split_body_lines(body):
        if _CONSTRAINT_RE.match(line):
            # Structural constraint, not a column
            fkm = _FK_RE.search(line)
            if fkm:
                ondel = (fkm.group('ondel') or 'CASCADE').upper()
                ondel = ondel.replace(' ', '_')
                t.foreign_keys.append(ForeignKey(
                    columns=_strip_colnames(fkm.group(1)),
                    ref_table=fkm.group('ref'),
                    ref_columns=_strip_colnames(fkm.group(3)),
                    on_delete=ondel,
                ))
                continue
            pkm = _PK_RE.search(line)
            if pkm:
                t.primary_key = _strip_colnames(pkm.group(1))
                continue
            um = _UNIQUE_RE.search(line)
            if um:
                t.uniques.append(_strip_colnames(um.group(1)))
                continue
            continue

        col_m = _COL_LINE_RE.match(line)
        if not col_m:
            continue
        col_name = col_m.group('name')
        rest = col_m.group('rest')

        # Extract raw_type — everything up to the first keyword after it.
        type_m = re.match(
            r'(?P<t>[A-Za-z]+(?:\s*\([^)]*\))?(?:\s+unsigned)?(?:\s+zerofill)?)',
            rest, re.IGNORECASE,
        )
        raw_type = type_m.group('t').strip() if type_m else rest.split()[0]
        tail = rest[len(type_m.group('t')):].strip() if type_m else ''

        not_null = bool(re.search(r'\bNOT\s+NULL\b', tail, re.IGNORECASE))
        auto_inc = bool(re.search(r'\bAUTO_INCREMENT\b', tail, re.IGNORECASE))
        on_update = bool(re.search(
            r'\bON\s+UPDATE\s+CURRENT_TIMESTAMP\b', tail, re.IGNORECASE))

        default = None
        def_m = re.search(r"\bDEFAULT\s+('(?:[^']|'')*'|\S+)", tail, re.IGNORECASE)
        if def_m:
            default = def_m.group(1)

        t.columns.append(Column(
            name=col_name, raw_type=raw_type.lower(),
            not_null=not_null, default=default,
            is_auto_inc=auto_inc, on_update_current_ts=on_update,
        ))

    # Mark PK and unique flags on Column objects
    for col in t.columns:
        if col.name in t.primary_key:
            col.is_primary = True
        for uq in t.uniques:
            if uq == [col.name]:
                col.is_unique = True

    return t


def parse_dump(text: str) -> List[Table]:
    """Parse every CREATE TABLE in a dump into Table objects."""
    return [parse_create_table(strip_auto_increment(ddl))
            for _, ddl in iter_create_tables(text)]


# ═════════════════════════════════════════════════════════════════════
# Naming helpers
# ═════════════════════════════════════════════════════════════════════

_IRREGULAR_PLURALS = {
    'baby': 'babies', 'city': 'cities', 'country': 'countries',
    'story': 'stories', 'category': 'categories', 'company': 'companies',
    'person': 'people', 'child': 'children', 'man': 'men', 'woman': 'women',
    'mouse': 'mice', 'matrix': 'matrices', 'index': 'indices',
}


def singularize(name: str) -> str:
    """Best-effort singularize for making a model name from a table."""
    low = name.lower()
    for sing, plur in _IRREGULAR_PLURALS.items():
        if low == plur:
            return sing
    if low.endswith('ies') and len(low) > 3:
        return low[:-3] + 'y'
    if low.endswith('ses') or low.endswith('xes') or low.endswith('zes'):
        return low[:-2]
    if low.endswith('s') and not low.endswith('ss'):
        return low[:-1]
    return low


def pluralize(name: str) -> str:
    low = name.lower()
    if low in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[low]
    if low.endswith('y') and len(low) > 1 and low[-2] not in 'aeiou':
        return low[:-1] + 'ies'
    if low.endswith(('s', 'x', 'z', 'ch', 'sh')):
        return low + 'es'
    return low + 's'


def table_to_model_name(table: str, app_label: str = '') -> str:
    """``lab_user`` → ``User`` when app_label is ``lab``, otherwise
    ``LabUser``. Also singularizes and handles irregular plurals."""
    stem = table
    if app_label and stem.startswith(app_label + '_'):
        stem = stem[len(app_label) + 1:]
    parts = re.split(r'[_\-\s]+', stem)
    parts = [singularize(p) for p in parts if p]
    return ''.join(p.capitalize() for p in parts) or 'Model'


def column_to_field_name(col_name: str) -> str:
    """Make a column name safe and idiomatic as a Django field name.

    CamelCase legacy names (Laravel's ``isAdmin``) get converted to
    snake_case (``is_admin``) — Django convention.
    """
    # CamelCase → snake_case: insert underscore before each uppercase
    # letter that isn't at the start and isn't preceded by another
    # uppercase letter (keeps runs like ``ID``, ``URL`` intact).
    snake = re.sub(r'(?<=[a-z0-9])([A-Z])', r'_\1', col_name)
    snake = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', snake)
    name = snake.lower().strip()
    name = re.sub(r'[^a-z0-9_]', '_', name)
    if not name or name[0].isdigit():
        name = 'f_' + name
    if keyword.iskeyword(name) or name in {'class', 'self', 'pass'}:
        name = name + '_field'
    return name


# ═════════════════════════════════════════════════════════════════════
# Per-column field inference
# ═════════════════════════════════════════════════════════════════════

LARAVEL_DROP_COLUMNS = {'remember_token'}

# Columns we leave in the model but translate to Django conventions
LARAVEL_TIMESTAMP_COLUMNS = {'created_at', 'updated_at', 'deleted_at'}


def _char_length(raw_type: str) -> Optional[int]:
    m = re.match(r'(?:varchar|char)\((\d+)\)', raw_type)
    return int(m.group(1)) if m else None


def _is_email_column(name: str) -> bool:
    low = name.lower()
    return (low == 'email' or low.endswith('_email')
            or low == 'e_mail' or low == 'email_address')


def _is_url_column(name: str) -> bool:
    low = name.lower()
    return (low in ('url', 'website', 'link', 'homepage')
            or low.endswith('_url'))


def _is_slug_column(name: str) -> bool:
    low = name.lower()
    return low == 'slug' or low.endswith('_slug')


def _is_ip_column(name: str) -> bool:
    low = name.lower()
    return (low in ('ip', 'ip_address', 'ip_addr', 'client_ip',
                    'remote_addr'))


def _render_null_blank(col: Column) -> str:
    return '' if col.not_null else ', null=True, blank=True'


def _render_default(col: Column, python_literal: bool = True) -> str:
    if col.default is None or col.default.upper() == 'NULL':
        return ''
    raw = col.default
    if raw.startswith("'") and raw.endswith("'"):
        return f", default={raw}"
    if raw.upper() in ('CURRENT_TIMESTAMP', 'CURRENT_TIMESTAMP()'):
        return ''  # Handled via auto_now / auto_now_add elsewhere
    if python_literal:
        return f", default={raw}"
    return ''


def infer_field(col: Column, *, fk_target: Optional[str] = None) -> str:
    """Render a Django model field declaration for this column.

    ``fk_target`` is the string model name to point at when this column
    is a ForeignKey — passed in by ``generate_models_py`` which has
    visibility of the whole table graph.
    """
    raw = col.raw_type

    # Primary-key auto-increment → BigAutoField
    if col.is_auto_inc:
        return 'models.BigAutoField(primary_key=True)'

    # ForeignKey — takes precedence over raw-type heuristics
    if fk_target:
        on_delete = {
            'CASCADE':     'models.CASCADE',
            'SET_NULL':    'models.SET_NULL',
            'RESTRICT':    'models.PROTECT',
            'NO_ACTION':   'models.PROTECT',
            'SET_DEFAULT': 'models.SET_DEFAULT',
        }.get('CASCADE', 'models.CASCADE')  # default; overridden below
        nb = _render_null_blank(col)
        return (f'models.ForeignKey("{fk_target}", '
                f'on_delete={on_delete}{nb})')

    null_blank = _render_null_blank(col)

    # Laravel-flavoured timestamp columns
    if col.name == 'created_at' and 'datetime' in raw or 'timestamp' in raw:
        if col.name == 'created_at':
            return 'models.DateTimeField(auto_now_add=True, null=True, blank=True)'
        if col.name == 'updated_at':
            return 'models.DateTimeField(auto_now=True, null=True, blank=True)'
    # A second pass because the above had an `and` precedence issue:
    if col.name in LARAVEL_TIMESTAMP_COLUMNS:
        if col.name == 'created_at':
            return 'models.DateTimeField(auto_now_add=True, null=True, blank=True)'
        if col.name == 'updated_at':
            return 'models.DateTimeField(auto_now=True, null=True, blank=True)'
        if col.name == 'deleted_at':
            return ('models.DateTimeField(null=True, blank=True, '
                    'help_text="Laravel soft-delete column.")')

    # Boolean
    if raw.startswith('tinyint(1)') or raw in ('boolean', 'bool'):
        bits = []
        if col.default is not None:
            raw_default = col.default.strip("'")
            if raw_default in ('1', 'true', 'TRUE'):
                bits.append('default=True')
            elif raw_default in ('0', 'false', 'FALSE'):
                bits.append('default=False')
        elif col.not_null:
            bits.append('default=False')
        if not col.not_null:
            bits.extend(['null=True', 'blank=True'])
        return f'models.BooleanField({", ".join(bits)})'

    # Tinyint / smallint / int / bigint
    if re.match(r'tinyint', raw):
        return f'models.PositiveSmallIntegerField({null_blank.lstrip(", ")})'
    if 'smallint' in raw:
        return f'models.SmallIntegerField({null_blank.lstrip(", ")})'
    if 'bigint' in raw:
        if 'unsigned' in raw:
            return f'models.PositiveBigIntegerField({null_blank.lstrip(", ")})'
        return f'models.BigIntegerField({null_blank.lstrip(", ")})'
    if re.match(r'(mediumint|int)\b', raw):
        if 'unsigned' in raw:
            return f'models.PositiveIntegerField({null_blank.lstrip(", ")})'
        return f'models.IntegerField({null_blank.lstrip(", ")})'

    # Decimal / float / double
    m = re.match(r'decimal\((\d+),(\d+)\)', raw)
    if m:
        return (f'models.DecimalField(max_digits={m.group(1)}, '
                f'decimal_places={m.group(2)}{null_blank})')
    if 'double' in raw or 'float' in raw:
        return f'models.FloatField({null_blank.lstrip(", ")})'

    # Char / varchar — the most inference-heavy branch
    char_len = _char_length(raw)
    if char_len is not None:
        if _is_email_column(col.name):
            return f'models.EmailField(max_length={char_len}{null_blank})'
        if _is_url_column(col.name):
            return f'models.URLField(max_length={char_len}{null_blank})'
        if _is_slug_column(col.name):
            return f'models.SlugField(max_length={char_len}{null_blank})'
        if _is_ip_column(col.name):
            return f'models.GenericIPAddressField({null_blank.lstrip(", ")})'
        return f'models.CharField(max_length={char_len}{null_blank})'

    # Text family
    if raw in ('text', 'tinytext', 'mediumtext', 'longtext'):
        return f'models.TextField({null_blank.lstrip(", ")})'

    # Dates and times
    if raw == 'date':
        return f'models.DateField({null_blank.lstrip(", ")})'
    if raw == 'time':
        return f'models.TimeField({null_blank.lstrip(", ")})'
    if 'datetime' in raw or 'timestamp' in raw:
        return f'models.DateTimeField({null_blank.lstrip(", ")})'
    if raw == 'year':
        return f'models.PositiveSmallIntegerField({null_blank.lstrip(", ")})'

    # ENUM — handled at the model level (via TextChoices). Caller sets
    # this up when it detects an enum; this function only returns the
    # CharField reference.
    m = re.match(r'enum\((.+)\)', raw)
    if m:
        vals = re.findall(r"'((?:[^']|'')*)'", m.group(1))
        max_len = max((len(v) for v in vals), default=20)
        # Emit reference; model generator inserts a Choices class.
        choices_cls = f'{column_to_field_name(col.name).title()}Choices'
        return (f'models.CharField(max_length={max_len}, '
                f'choices={choices_cls}.choices{null_blank})')

    # JSON
    if raw == 'json':
        return f'models.JSONField(default=dict{null_blank})'

    # Blob / binary
    if 'blob' in raw or 'binary' in raw:
        return f'models.BinaryField({null_blank.lstrip(", ")})'

    return f'models.TextField({null_blank.lstrip(", ")})  # unmapped: {raw}'


# ═════════════════════════════════════════════════════════════════════
# Model-file generation
# ═════════════════════════════════════════════════════════════════════

def _choose_str_field(col_names: Iterable[str]) -> Optional[str]:
    """Best-available field for a generated __str__."""
    pool = list(col_names)
    for candidate in ('name', 'title', 'label', 'slug', 'email', 'code'):
        if candidate in pool:
            return candidate
    return None


def _is_junction_table(t: Table) -> bool:
    """Two FK columns plus maybe id/created_at/updated_at — classic
    Laravel pivot table pattern (e.g. baby_language)."""
    meta = {'id', 'created_at', 'updated_at'}
    fk_cols = {c for fk in t.foreign_keys for c in fk.columns}
    data_cols = [c.name for c in t.columns
                 if c.name not in meta and c.name not in fk_cols]
    return len(fk_cols) == 2 and not data_cols


def generate_models_py(tables: List[Table], app_label: str,
                       source: str = '') -> str:
    """Emit a full models.py as a string."""
    # Map legacy table name → Django model name (for FK targets)
    model_name_for = {t.name: table_to_model_name(t.name, app_label)
                      for t in tables}

    out: List[str] = [
        '"""Auto-generated by datalift genmodels.',
        '',
        f'Source: {source or "mysqldump"}',
        '',
        'Review every model before migrating — Datalift makes best-',
        'effort inferences (field types, FK targets, Laravel timestamp',
        'conventions, ENUM → TextChoices, soft-delete hints). Rename',
        'fields, split tables, promote junction tables to M2M, etc.',
        '"""',
        '',
        'from django.db import models',
        '',
        '',
    ]

    for t in tables:
        # Skip Laravel internal tables that rarely want Django models
        if t.name in {'migrations', 'password_resets',
                      'personal_access_tokens', 'failed_jobs'}:
            out.append(f'# skipped legacy table: {t.name} '
                       '(Laravel internal; not a domain model)')
            out.append('')
            continue

        model = model_name_for[t.name]
        out.append(f'class {model}(models.Model):')
        header_bits = [f'Generated from legacy table `{t.name}`.']
        if _is_junction_table(t):
            header_bits.append('CANDIDATE for promotion to '
                               'ManyToManyField on the parent side — '
                               'two FKs, no other data columns.')
        out.append(f'    """{" ".join(header_bits)}"""')
        out.append('')

        # 1. Generate TextChoices classes for every ENUM column first.
        enum_classes: Dict[str, List[str]] = {}
        for col in t.columns:
            m = re.match(r'enum\((.+)\)', col.raw_type)
            if m:
                vals = re.findall(r"'((?:[^']|'')*)'", m.group(1))
                enum_classes[col.name] = vals

        for col_name, vals in enum_classes.items():
            cls_name = f'{column_to_field_name(col_name).title()}Choices'
            out.append(f'    class {cls_name}(models.TextChoices):')
            for v in vals:
                # Sanitize: VALUE = 'value', 'Display'
                const = re.sub(r'[^A-Za-z0-9]+', '_', v).upper().strip('_')
                if not const or const[0].isdigit():
                    const = 'V_' + const
                out.append(f"        {const} = '{v}', '{v.capitalize()}'")
            out.append('')

        # 2. Generate columns.
        fk_by_col = {fk.columns[0]: fk for fk in t.foreign_keys
                     if len(fk.columns) == 1}

        for col in t.columns:
            # Skip PK if it's the default auto-id (Django emits one)
            if col.is_auto_inc and col.name == 'id':
                # Emit explicitly so db_table-pinned tables round-trip
                # cleanly; Django otherwise uses its own id field.
                out.append('    id = models.BigAutoField(primary_key=True)')
                continue
            if col.name in LARAVEL_DROP_COLUMNS:
                out.append(f'    # dropped Laravel column: {col.name} '
                           '(Django\'s auth handles session tokens)')
                continue

            fk = fk_by_col.get(col.name)
            field_target = model_name_for.get(fk.ref_table) if fk else None
            field_code = infer_field(col, fk_target=field_target)

            if fk:
                # Strip trailing _id from the field name per Django idiom
                py_name = column_to_field_name(col.name)
                if py_name.endswith('_id'):
                    py_name = py_name[:-3]
                # Replace the on_delete default with the right one for this FK
                on_delete = {
                    'CASCADE':     'models.CASCADE',
                    'SET_NULL':    'models.SET_NULL',
                    'RESTRICT':    'models.PROTECT',
                    'NO_ACTION':   'models.PROTECT',
                    'SET_DEFAULT': 'models.SET_DEFAULT',
                }.get(fk.on_delete, 'models.CASCADE')
                field_code = re.sub(
                    r'on_delete=[^,)]+',
                    f'on_delete={on_delete}',
                    field_code,
                )
            else:
                py_name = column_to_field_name(col.name)

            out.append(f'    {py_name} = {field_code}')

        # 3. Meta
        col_names = {c.name for c in t.columns}
        ordering = ['id']
        if 'created_at' in col_names:
            ordering = ["-created_at"]
        elif 'name' in col_names:
            ordering = ['name']

        out.append('')
        out.append('    class Meta:')
        out.append(f"        db_table = '{t.name}'")
        out.append(f"        ordering = {ordering!r}")
        plural = pluralize(singularize(t.name))
        if plural != model.lower() + 's':
            out.append(f"        verbose_name_plural = '{plural}'")
        out.append('')

        # 4. __str__
        str_field = _choose_str_field(col_names)
        if str_field:
            out.append('    def __str__(self):')
            py_name = column_to_field_name(str_field)
            out.append(f'        return str(self.{py_name} or self.pk)')
            out.append('')

        out.append('')

    return '\n'.join(out).rstrip() + '\n'


# ═════════════════════════════════════════════════════════════════════
# Starter table_map.json
# ═════════════════════════════════════════════════════════════════════

def generate_table_map(tables: List[Table], app_label: str,
                       source_database: str = '') -> dict:
    """Emit a starter map that ``ingestdump`` can consume.

    Encodes everything Datalift already inferred (drop_columns,
    value_maps scaffolds for ENUMs, synthesize for users-without-
    username tables) so the operator only has to tune values, not
    the structure.
    """
    out = {
        '_meta': {
            'source_database': source_database or '',
            'generated_by': 'datalift.genmodels',
            'note': 'Starter table_map — review before running ingestdump.',
        },
        'tables': {},
    }
    skip_tables = {'migrations', 'password_resets',
                   'personal_access_tokens', 'failed_jobs'}
    out['skip_tables'] = sorted(skip_tables)

    for t in tables:
        if t.name in skip_tables:
            continue

        model_name = table_to_model_name(t.name, app_label)
        spec: Dict = {
            'model': f'{app_label}.{model_name}',
        }

        # Drop columns (Laravel convenience)
        drops = [c.name for c in t.columns if c.name in LARAVEL_DROP_COLUMNS]
        if drops:
            spec['drop_columns'] = drops

        # value_maps scaffold for ENUMs (operator fills in if the
        # target Django model uses different choice keys)
        value_maps = {}
        for col in t.columns:
            m = re.match(r'enum\((.+)\)', col.raw_type)
            if m:
                vals = re.findall(r"'((?:[^']|'')*)'", m.group(1))
                # Identity map as a starter; edit when targets differ.
                value_maps[col.name] = {v: v for v in vals}
        if value_maps:
            spec['value_maps'] = value_maps

        # synthesize username from email for users-like tables
        col_names = {c.name for c in t.columns}
        is_user_table = any(k in t.name.lower()
                            for k in ('user', 'account'))
        if ('username' not in col_names and 'email' in col_names
                and is_user_table):
            spec['synthesize'] = {'username': 'email'}
            spec['dedupe_by'] = 'username'

        # Laravel $2y$ bcrypt → Django bcrypt$$2b$ at load time
        if is_user_table and 'password' in col_names:
            spec['rewrite_laravel_passwords'] = 'password'

        out['tables'][t.name] = spec

    return out


# ═════════════════════════════════════════════════════════════════════
# Admin-file generation
# ═════════════════════════════════════════════════════════════════════

# Column-name heuristics for what an admin would want to surface.
_SEARCH_NAMES = {'name', 'title', 'label', 'slug', 'email', 'username',
                 'code', 'headline', 'subject'}
_LIST_FILTER_PATTERNS = ('status', 'active', 'approved', 'published',
                         'state', 'role', 'kind', 'type', 'level')


def _guess_list_display(t: Table) -> List[str]:
    """Pick up to 6 columns worth showing in the admin list view."""
    picks: List[str] = []
    col_names = [c.name for c in t.columns]

    # 'id' always if present (or django handles the PK link anyway)
    if 'id' in col_names:
        picks.append('id')

    # Prioritised identifier columns
    for candidate in ('name', 'title', 'slug', 'email', 'username',
                      'code', 'label'):
        if candidate in col_names and candidate not in picks:
            picks.append(candidate)
        if len(picks) >= 4:
            break

    # Append useful metadata columns
    for candidate in ('status', 'active', 'approved', 'role', 'kind',
                      'type', 'level', 'created_at', 'updated_at',
                      'published_at'):
        if candidate in col_names and candidate not in picks:
            picks.append(candidate)
        if len(picks) >= 6:
            break

    # Include first FK (as a useful join column) if we still have room
    fk_cols = {fk.columns[0] for fk in t.foreign_keys if len(fk.columns) == 1}
    for col in col_names:
        if col in fk_cols and col not in picks and len(picks) < 6:
            # FK fields are named without _id on the Django side
            py_name = column_to_field_name(col)
            if py_name.endswith('_id'):
                py_name = py_name[:-3]
            picks.append(py_name)

    return picks


def _guess_search_fields(t: Table) -> List[str]:
    """Text-ish columns an operator is likely to search on."""
    col_names = {c.name: c for c in t.columns}
    picks = []
    for c in t.columns:
        low = c.name.lower()
        if low in _SEARCH_NAMES or low.endswith('_name') or low.endswith('_title'):
            # Only include if column is textual
            raw = c.raw_type
            if raw.startswith(('varchar', 'char')) or raw in (
                    'text', 'tinytext', 'mediumtext', 'longtext'):
                picks.append(column_to_field_name(c.name))
    return picks[:4]


def _guess_list_filter(t: Table) -> List[str]:
    """Columns whose admin filter-panel would be useful — booleans,
    choices, low-cardinality FKs, date columns."""
    picks = []
    fk_cols = {fk.columns[0] for fk in t.foreign_keys if len(fk.columns) == 1}
    for c in t.columns:
        low = c.name.lower()
        raw = c.raw_type
        if raw.startswith('tinyint(1)') or raw in ('boolean', 'bool'):
            picks.append(column_to_field_name(c.name))
        elif raw.startswith('enum('):
            picks.append(column_to_field_name(c.name))
        elif any(pat in low for pat in _LIST_FILTER_PATTERNS):
            picks.append(column_to_field_name(c.name))
        elif c.name in fk_cols and c.name != 'user_id':
            # FKs can be useful filters — strip _id for the Django field
            py_name = column_to_field_name(c.name)
            if py_name.endswith('_id'):
                py_name = py_name[:-3]
            picks.append(py_name)
    # Dedupe preserving order
    seen = set()
    out = []
    for p in picks:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out[:5]


def _guess_date_hierarchy(t: Table) -> Optional[str]:
    """If there's a prominent date column, Django's admin gets a nicer
    top-bar navigation from it."""
    for candidate in ('created_at', 'published_at', 'date', 'dob',
                      'application_date'):
        if any(c.name == candidate for c in t.columns):
            return candidate
    return None


def _guess_raw_id_fields(t: Table) -> List[str]:
    """FKs that could explode a <select> widget — use raw id input
    instead. Heuristic: FK to a table named users or babies or anything
    likely to have many rows."""
    HIGH_CARDINALITY = {'users', 'babies', 'posts', 'orders',
                        'products', 'items', 'events'}
    picks = []
    for fk in t.foreign_keys:
        if len(fk.columns) != 1:
            continue
        if fk.ref_table in HIGH_CARDINALITY:
            py_name = column_to_field_name(fk.columns[0])
            if py_name.endswith('_id'):
                py_name = py_name[:-3]
            picks.append(py_name)
    return picks


def generate_admin_py(tables: List[Table], app_label: str,
                     source: str = '') -> str:
    """Emit a full admin.py as a string — one ModelAdmin per non-
    skipped table with inferred list_display, search_fields,
    list_filter, date_hierarchy, raw_id_fields."""
    model_names = [table_to_model_name(t.name, app_label) for t in tables
                   if t.name not in {'migrations', 'password_resets',
                                     'personal_access_tokens', 'failed_jobs'}]
    if not model_names:
        return ('# Auto-generated by datalift genmodels.\n'
                '# No models to register.\n')

    out: List[str] = [
        '"""Auto-generated by datalift genmodels.',
        '',
        f'Source: {source or "mysqldump"}',
        '',
        'One ModelAdmin per generated model. Inferred defaults for',
        'list_display / search_fields / list_filter / date_hierarchy /',
        'raw_id_fields — tune as needed.',
        '"""',
        '',
        'from django.contrib import admin',
        '',
        'from .models import (',
    ]
    for n in sorted(model_names):
        out.append(f'    {n},')
    out.append(')')
    out.append('')
    out.append('')

    for t in tables:
        if t.name in {'migrations', 'password_resets',
                      'personal_access_tokens', 'failed_jobs'}:
            continue
        model = table_to_model_name(t.name, app_label)
        list_display = _guess_list_display(t)
        search_fields = _guess_search_fields(t)
        list_filter = _guess_list_filter(t)
        date_h = _guess_date_hierarchy(t)
        raw_id = _guess_raw_id_fields(t)

        out.append(f'@admin.register({model})')
        out.append(f'class {model}Admin(admin.ModelAdmin):')
        if list_display:
            out.append(f'    list_display = {tuple(list_display)!r}')
        if search_fields:
            out.append(f'    search_fields = {tuple(search_fields)!r}')
        if list_filter:
            out.append(f'    list_filter = {tuple(list_filter)!r}')
        if date_h:
            out.append(f'    date_hierarchy = {date_h!r}')
        if raw_id:
            out.append(f'    raw_id_fields = {tuple(raw_id)!r}')
        if not (list_display or search_fields or list_filter
                or date_h or raw_id):
            out.append('    pass')
        out.append('')

    return '\n'.join(out).rstrip() + '\n'


# Convenience wrapper
def generate_all(dump_text: str, app_label: str,
                 source_database: str = ''
                 ) -> tuple[str, str, dict]:
    """One-shot: parse dump, return
    (models_py_source, admin_py_source, table_map_dict)."""
    tables = parse_dump(dump_text)
    models_src = generate_models_py(tables, app_label=app_label,
                                    source=source_database or 'dump')
    admin_src = generate_admin_py(tables, app_label=app_label,
                                  source=source_database or 'dump')
    tmap = generate_table_map(tables, app_label=app_label,
                              source_database=source_database)
    return models_src, admin_src, tmap
