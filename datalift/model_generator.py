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

from datalift.dump_parser import (
    iter_create_tables, strip_auto_increment,
    _strip_table_prefix_placeholders,
)


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
    # Reject constraint lines (same shape as ingestdump._COL_DEF_RE).
    # Each keyword requires a trailing KEY/INDEX/paren so a column
    # named ``fulltext`` / ``spatial`` / ``check`` still parses as
    # a column.
    r'^\s*(?!'
      r'CONSTRAINT\s+|'
      r'PRIMARY\s+KEY\b|'
      r'FOREIGN\s+KEY\b|'
      r'UNIQUE\s+(?:KEY\b|\()|'
      r'KEY\s+|'
      r'INDEX\s*(?:\S|\()|'
      r'FULLTEXT\s+(?:KEY|INDEX)\b|'
      r'SPATIAL\s+(?:KEY|INDEX)\b|'
      r'CHECK\s*\('
    r')'
    r'[`"]?(?P<name>[A-Za-z_][A-Za-z0-9_]*)[`"]?\s+(?P<rest>.+?)\s*$',
    re.IGNORECASE,
)


def _normalize_type(raw: str) -> str:
    """Lowercase the type keyword + unsigned/zerofill modifiers, but
    preserve the parenthesised argument list as-written. ENUM('M','F')
    has case-significant values that must round-trip through the
    TextChoices class and back into ingestion unchanged. For numeric
    args (VARCHAR(255), DECIMAL(10,2)) it's a no-op."""
    m = re.match(
        r'^([A-Za-z]+)(\s*\([^)]*\))?(\s+unsigned)?(\s+zerofill)?$',
        raw, re.IGNORECASE,
    )
    if not m:
        return raw.lower()
    kw = m.group(1).lower()
    # Strip whitespace between keyword and "(" so downstream regexes
    # like r'enum\((.+)\)' match whether the source wrote ENUM(...)
    # or ENUM (...) with an intervening space.
    paren = (m.group(2) or '').lstrip()
    rest = ((m.group(3) or '') + (m.group(4) or '')).lower()
    return kw + paren + rest

_CONSTRAINT_RE = re.compile(
    r'^\s*(?:CONSTRAINT\s+[`"]?[^\s`"]+[`"]?\s+)?'
    r'(?P<kind>PRIMARY\s+KEY|UNIQUE\s+KEY|FOREIGN\s+KEY|KEY|INDEX|FULLTEXT|SPATIAL|CHECK)\b',
    re.IGNORECASE,
)
_FK_RE = re.compile(
    r'FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+[`"]?(?P<ref>[^\s`"(]+)[`"]?\s*\(([^)]+)\)'
    r'(?:\s+ON\s+(?:UPDATE|DELETE)\s+(?:RESTRICT|CASCADE|SET\s+NULL|NO\s+ACTION|SET\s+DEFAULT))*'
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
    """Turn ```col1`, `col2`, `col3`` — or the unquoted equivalent —
    into ['col1', 'col2', 'col3']. Handles Laravel (backticked) and
    canonical SQL (unquoted) dumps alike."""
    # Match either `quoted` or bare identifier
    return re.findall(r'[`"]([^`"]+)[`"]|([A-Za-z_][A-Za-z0-9_]*)', s) \
        and [a or b for a, b in re.findall(
            r'[`"]([^`"]+)[`"]|([A-Za-z_][A-Za-z0-9_]*)', s) if a or b]


def parse_create_table(ddl: str) -> Table:
    """Parse a CREATE TABLE DDL block into a structured Table."""
    m = re.search(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"]?([^\s`"(]+)[`"]?\s*\(',
                  ddl, re.IGNORECASE)
    if not m:
        raise ValueError('no CREATE TABLE header')
    # Strip any framework table-prefix placeholder — MediaWiki's
    # `/*_*/table`, WordPress's `$wpdb->table`, generic `{PREFIX}_`.
    name = _strip_table_prefix_placeholders(m.group(1))
    if not name:
        raise ValueError('table name missing after prefix placeholder strip')
    body = ddl[ddl.index('(', m.end() - 1) + 1: ddl.rindex(')')]
    # Strip SQL line comments, then unwrap version-gated comments —
    # /*!50705 ... */ wrap real column definitions (e.g. Sakila's
    # GEOMETRY column for MySQL 5.7.5+). UNWRAP rather than strip so
    # the inner DDL is treated as a regular column, otherwise
    # schema↔data column counts drift.
    body = re.sub(r'--[^\n]*', '', body)
    body = re.sub(r'/\*!\d+\s+', '', body)
    body = re.sub(r'\*/', '', body)
    # Strip plain /* ... */ blocks that aren't version-gated.
    body = re.sub(r'/\*[^*]*\*/', '', body)
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
        # Column-level PRIMARY KEY (Dolibarr: `id smallint PRIMARY KEY`,
        # Chinook: `AlbumId INT NOT NULL … CONSTRAINT PK_Album
        # PRIMARY KEY (AlbumId)`). Only treat as inline when the
        # keyword follows the column's own tail — table-level
        # `PRIMARY KEY (…)` constraints are handled elsewhere.
        if re.search(r'\bPRIMARY\s+KEY\b', tail, re.IGNORECASE):
            if col_name not in t.primary_key:
                t.primary_key.append(col_name)

        default = None
        def_m = re.search(r"\bDEFAULT\s+('(?:[^']|'')*'|\S+)", tail, re.IGNORECASE)
        if def_m:
            default = def_m.group(1)

        t.columns.append(Column(
            name=col_name, raw_type=_normalize_type(raw_type),
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
    """Parse every CREATE TABLE in a dump into Table objects.

    If the same table name appears twice (WordPress defines ``users``
    twice — once for single-site, once for multisite with extra
    spam/deleted columns), the later definition wins. This matches
    the "last write" semantics of running both CREATE TABLE IF NOT
    EXISTS blocks against an empty DB.
    """
    parsed: Dict[str, Table] = {}
    for _, ddl in iter_create_tables(text):
        t = parse_create_table(strip_auto_increment(ddl))
        parsed[t.name] = t
    # Post-pass: attach any ALTER TABLE ADD FOREIGN KEY declarations
    # to their owning table. SQL-Server-origin MySQL ports (Chinook,
    # many hand-authored schemas) declare FKs separately from the
    # CREATE TABLE, so the inline-FK parser misses them.
    _apply_alter_table_fks(text, parsed)
    return list(parsed.values())


# Common ALTER TABLE prelude — handles both mysqldump (single-line,
# no `ONLY`) and pg_dump (multi-line, with `ONLY`, schema-qualified
# names) variants.
_ALTER_TABLE_PRELUDE = (
    r'ALTER\s+TABLE\s+(?:ONLY\s+)?[`"]?(?P<tbl>[^\s`"()]+)[`"]?\s+'
    r'ADD\s+(?:CONSTRAINT\s+[`"]?[^\s`"]+[`"]?\s+)?'
)

# Matches a post-hoc FK constraint declared via ALTER TABLE, e.g.
#   ALTER TABLE `Invoice` ADD CONSTRAINT `FK_InvoiceCustomerId`
#   FOREIGN KEY (`CustomerId`) REFERENCES `Customer` (`CustomerId`)
#   ON DELETE NO ACTION ON UPDATE NO ACTION;
_ALTER_FK_RE = re.compile(
    _ALTER_TABLE_PRELUDE +
    r'FOREIGN\s+KEY\s*\(([^)]+)\)\s+'
    r'REFERENCES\s+[`"]?(?P<ref>[^\s`"()]+)[`"]?\s*\(([^)]+)\)'
    r'(?:\s+ON\s+(?:UPDATE|DELETE)\s+'
    r'(?:RESTRICT|CASCADE|SET\s+NULL|NO\s+ACTION|SET\s+DEFAULT))*'
    r'(?:\s+ON\s+DELETE\s+(?P<ondel>RESTRICT|CASCADE|SET\s+NULL|NO\s+ACTION|SET\s+DEFAULT))?',
    re.IGNORECASE,
)

# Matches a post-hoc PRIMARY KEY declared via ALTER TABLE. Handles
# three shapes:
#   ALTER TABLE t ADD CONSTRAINT cn PRIMARY KEY (cols)     (pg_dump)
#   ALTER TABLE t ADD PRIMARY KEY (cols)                   (plain)
#   ALTER TABLE t ADD PRIMARY KEY cn (cols)                (MySQL-permissive
#                                                           — Dolibarr style)
_ALTER_PK_RE = re.compile(
    _ALTER_TABLE_PRELUDE
    + r'PRIMARY\s+KEY\s*(?:[`"]?[A-Za-z_][\w]*[`"]?\s*)?\(([^)]+)\)',
    re.IGNORECASE,
)

# Matches a post-hoc UNIQUE constraint — same three shapes.
_ALTER_UNIQUE_RE = re.compile(
    _ALTER_TABLE_PRELUDE
    + r'UNIQUE(?:\s+(?:KEY|INDEX))?'
    + r'\s*(?:[`"]?[A-Za-z_][\w]*[`"]?\s*)?\(([^)]+)\)',
    re.IGNORECASE,
)

# A column default of `nextval('…_seq'::regclass)` is pg_dump's way
# of saying "this is a SERIAL / BIGSERIAL auto-increment".
_NEXTVAL_RE = re.compile(
    r"nextval\s*\(\s*'[^']+'(?:::regclass)?\s*\)",
    re.IGNORECASE,
)


def _apply_alter_table_fks(text: str, tables: Dict[str, Table]) -> None:
    """Populate table-level structure from post-hoc ALTER TABLE
    declarations. Covers three shapes emitted by pg_dump (and many
    hand-authored MySQL schemas):

    * ``ALTER TABLE … ADD CONSTRAINT … FOREIGN KEY (…) REFERENCES …``
    * ``ALTER TABLE … ADD CONSTRAINT … PRIMARY KEY (…)``
    * ``ALTER TABLE … ADD CONSTRAINT … UNIQUE (…)``

    Also recognises ``DEFAULT nextval(…)`` on a column as equivalent
    to ``AUTO_INCREMENT``: when ALTER TABLE later declares that
    column as the PK, we upgrade it to a BigAutoField.
    """
    from datalift.dump_parser import _strip_table_prefix_placeholders

    for m in _ALTER_FK_RE.finditer(text):
        tbl_name = _strip_table_prefix_placeholders(m.group('tbl'))
        ref_table = _strip_table_prefix_placeholders(m.group('ref'))
        target = tables.get(tbl_name)
        if target is None:
            continue
        cols = _strip_colnames(m.group(2))
        ref_cols = _strip_colnames(m.group(4))
        ondel = (m.group('ondel') or 'CASCADE').upper().replace(' ', '_')
        if ondel == 'NO_ACTION':
            ondel = 'CASCADE'  # NO ACTION ≈ CASCADE for most app code
        target.foreign_keys.append(ForeignKey(
            columns=cols, ref_table=ref_table,
            ref_columns=ref_cols, on_delete=ondel,
        ))

    for m in _ALTER_PK_RE.finditer(text):
        tbl_name = _strip_table_prefix_placeholders(m.group('tbl'))
        target = tables.get(tbl_name)
        if target is None or target.primary_key:
            continue  # don't overwrite an inline PK
        pk_cols = _strip_colnames(m.group(2))
        target.primary_key = pk_cols
        # Update per-column flags so the emit phase sees them as PK
        for c in target.columns:
            if c.name in pk_cols:
                c.is_primary = True
                # Promote nextval()-defaulted PK columns to AUTO_INCREMENT
                # semantics: when pg_dump says `customer_id integer
                # DEFAULT nextval('customer_customer_id_seq'::regclass)`
                # and later declares it PK, the canonical Django form
                # is a BigAutoField(primary_key=True).
                if c.default and _NEXTVAL_RE.search(c.default):
                    c.is_auto_inc = True

    for m in _ALTER_UNIQUE_RE.finditer(text):
        tbl_name = _strip_table_prefix_placeholders(m.group('tbl'))
        target = tables.get(tbl_name)
        if target is None:
            continue
        u_cols = _strip_colnames(m.group(2))
        if u_cols not in target.uniques:
            target.uniques.append(u_cols)
        if len(u_cols) == 1:
            for c in target.columns:
                if c.name == u_cols[0]:
                    c.is_unique = True


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
    """Best-effort singularize for making a model name from a table.
    Preserves the original case of the preserved prefix — Chinook's
    `InvoiceLine` stays mixed-case so table_to_model_name doesn't
    collapse it to `Invoiceline`."""
    low = name.lower()
    for sing, plur in _IRREGULAR_PLURALS.items():
        if low == plur:
            return sing
    if low.endswith('ies') and len(low) > 3:
        return name[:-3] + ('Y' if name[-3].isupper() else 'y')
    if low.endswith('ses') or low.endswith('xes') or low.endswith('zes'):
        return name[:-2]
    if low.endswith('s') and not low.endswith('ss'):
        return name[:-1]
    return name


def pluralize(name: str) -> str:
    low = name.lower()
    if low in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[low]
    if low.endswith('y') and len(low) > 1 and low[-2] not in 'aeiou':
        return low[:-1] + 'ies'
    if low.endswith(('s', 'x', 'z', 'ch', 'sh')):
        return low + 'es'
    return low + 's'


def _common_table_prefix(tables: Iterable[str]) -> str:
    """Longest ``xxx_`` prefix shared by every table name. Returns
    ``''`` if there's no shared prefix. Used by table_to_model_name
    to strip Dolibarr-style `llx_`, WordPress-style `wp_`, Laravel
    `lab_` etc. automatically — whenever the dump is uniformly
    prefixed, the Python class names drop the overhead."""
    tl = list(tables)
    if not tl:
        return ''
    shortest = min(tl, key=len)
    # Longest common prefix across the set…
    prefix = ''
    for i, ch in enumerate(shortest):
        if all(t[i] == ch for t in tl):
            prefix = shortest[:i + 1]
        else:
            break
    # …truncated at the last `_` so we don't chew partial words.
    last_under = prefix.rfind('_')
    return prefix[:last_under + 1] if last_under >= 0 else ''


def table_to_model_name(table: str, app_label: str = '',
                        all_tables: Optional[Iterable[str]] = None) -> str:
    """Convert a legacy SQL table name to a PascalCase Django model name.

    Strips a shared prefix from the start when every table in the
    dump begins with it. Two cases:

    * ``app_label + '_'`` — Babybase's `lab_user`, `lab_baby` under
      `--app lab`.
    * Framework-conventional literal prefix — Dolibarr's `llx_`,
      WordPress's default `wp_`. Detected automatically via
      `_common_table_prefix` so we don't need a hand-written list.

    Mixed-prefix dumps (PrestaShop under `--app shop` where only
    `shop_*` tables begin with `shop_`) get no strip — the
    `shop_group` table stays `ShopGroup`, avoiding model-name
    collisions with a distinct `group` table.
    """
    stem = table
    if all_tables is not None:
        table_list = list(all_tables)
        # Try app_label first (explicit operator intent)…
        if app_label:
            prefix = app_label + '_'
            if table_list and all(t.startswith(prefix) for t in table_list):
                stem = stem[len(prefix):]
        # …then fall back to an auto-detected shared prefix.
        if stem == table:
            shared = _common_table_prefix(table_list)
            if shared and len(shared) >= 2:  # avoid single-char prefixes
                stem = stem[len(shared):]
    parts = re.split(r'[_\-\s]+', stem)
    parts = [singularize(p) for p in parts if p]

    def _capitalize_part(p: str) -> str:
        # Preserve existing PascalCase or camelCase tokens — Chinook's
        # `InvoiceLine` would become `Invoiceline` under plain
        # `.capitalize()`. If the token already has internal uppercase
        # letters (i.e. it's mixed case), leave the case as-is apart
        # from upper-casing the first character.
        if not p:
            return p
        if any(c.isupper() for c in p[1:]):
            return p[0].upper() + p[1:]
        return p.capitalize()

    return ''.join(_capitalize_part(p) for p in parts) or 'Model'


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


# ═════════════════════════════════════════════════════════════════════
# Type registry — which SQL type keywords map to which Django fields.
#
# When a new SQL dialect shows up with `CITEXT`, `VARCHAR2`, or some
# vendor-specific synonym, the fix is a one-line addition to the
# relevant set here, not a new branch in infer_field. The `raw_type`
# passed to infer_field is always already-normalised (lowercase
# keyword + preserved paren args — see _normalize_type), so the
# lookups are plain set membership.
#
# Order notes:
# * tinyint(1) has to be handled as Boolean BEFORE tinyint falls
#   through to PositiveSmallIntegerField — the raw_type prefix
#   check in infer_field still lives there.
# * Integer map values are (signed_django_field, unsigned_django_field)
#   tuples; when the raw contains " unsigned", we pick the second.
# ═════════════════════════════════════════════════════════════════════

BOOLEAN_TYPE_KEYWORDS = frozenset({'boolean', 'bool'})

INTEGER_TYPE_MAP = {
    'tinyint':   ('PositiveSmallIntegerField', 'PositiveSmallIntegerField'),
    'smallint':  ('SmallIntegerField', 'PositiveSmallIntegerField'),
    'mediumint': ('IntegerField', 'PositiveIntegerField'),
    'int':       ('IntegerField', 'PositiveIntegerField'),
    'integer':   ('IntegerField', 'PositiveIntegerField'),
    'bigint':    ('BigIntegerField', 'PositiveBigIntegerField'),
    'int2':      ('SmallIntegerField', 'PositiveSmallIntegerField'),
    'int4':      ('IntegerField', 'PositiveIntegerField'),
    'int8':      ('BigIntegerField', 'PositiveBigIntegerField'),
    'serial':    ('IntegerField', 'IntegerField'),
    'bigserial': ('BigIntegerField', 'BigIntegerField'),
}

DECIMAL_TYPE_KEYWORDS = frozenset({'decimal', 'numeric', 'dec', 'fixed'})

FLOAT_TYPE_KEYWORDS = frozenset({'float', 'double', 'real', 'float4', 'float8'})

CHAR_TYPE_KEYWORDS = frozenset({'char', 'varchar', 'nchar', 'nvarchar',
                                  'character', 'bpchar', 'varchar2'})

TEXT_TYPE_KEYWORDS = frozenset({'text', 'tinytext', 'mediumtext',
                                  'longtext', 'ntext', 'clob', 'citext'})

DATE_TYPE_KEYWORDS = frozenset({'date'})
TIME_TYPE_KEYWORDS = frozenset({'time', 'timetz'})
DATETIME_TYPE_KEYWORDS = frozenset({'datetime', 'timestamp',
                                     'datetime2', 'smalldatetime',
                                     'timestamptz'})

BLOB_TYPE_KEYWORDS = frozenset({'blob', 'tinyblob', 'mediumblob', 'longblob',
                                 'binary', 'varbinary', 'bytea', 'image',
                                 'raw'})

JSON_TYPE_KEYWORDS = frozenset({'json', 'jsonb'})

UUID_TYPE_KEYWORDS = frozenset({'uuid', 'uniqueidentifier'})


def _type_keyword(raw_type: str) -> str:
    """Return just the type keyword (``'nvarchar'``, ``'decimal'``,
    ``'int'``), stripping any ``(args)`` or ``unsigned`` modifiers."""
    m = re.match(r'([a-z][a-z0-9_]*)', raw_type)
    return m.group(1) if m else ''


def _char_length(raw_type: str) -> Optional[int]:
    """Extract the ``(N)`` length from char-family types."""
    if _type_keyword(raw_type) not in CHAR_TYPE_KEYWORDS:
        return None
    m = re.match(r'[a-z]+\((\d+)\)', raw_type)
    return int(m.group(1)) if m else None


def _decimal_precision(raw_type: str) -> Optional[tuple]:
    """Extract ``(M, D)`` from DECIMAL/NUMERIC. Returns None if not a
    decimal keyword or no parens."""
    if _type_keyword(raw_type) not in DECIMAL_TYPE_KEYWORDS:
        return None
    m = re.match(r'[a-z]+\((\d+),\s*(\d+)\)', raw_type)
    return (int(m.group(1)), int(m.group(2))) if m else None


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


def _render_default(col: Column, kind: str = 'generic') -> str:
    """Render a Django ``, default=<value>`` fragment if the MySQL
    column has an explicit DEFAULT. ``kind`` picks a sensible python
    literal for the field type (``'numeric'``, ``'string'``,
    ``'generic'``). Returns empty string if no applicable default."""
    if col.default is None or col.default.upper() == 'NULL':
        return ''
    raw = col.default
    if raw.upper() in ('CURRENT_TIMESTAMP', 'CURRENT_TIMESTAMP()'):
        return ''  # handled via auto_now / auto_now_add elsewhere
    if raw.startswith("'") and raw.endswith("'"):
        inner = raw[1:-1].replace("'", "\\'")
        if kind == 'numeric':
            # Legacy schemas sometimes quote numeric defaults: '0'
            try:
                return f", default={int(inner)}"
            except ValueError:
                try:
                    return f", default={float(inner)}"
                except ValueError:
                    return ''
        return f", default='{inner}'"
    # Unquoted literal (numeric or keyword)
    if kind == 'string':
        return ''  # don't invent a default for a char field from a bareword
    try:
        int(raw); return f", default={raw}"
    except ValueError:
        try:
            float(raw); return f", default={raw}"
        except ValueError:
            return ''


def _nbd(col: Column, kind: str = 'generic') -> str:
    """null_blank + default combined — the common pattern."""
    return _render_null_blank(col) + _render_default(col, kind)


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

    # ForeignKey — takes precedence over raw-type heuristics.
    # We default to related_name="+" (disables the reverse accessor)
    # to avoid conflicts when a table has multiple FKs to the same
    # target, or when a column name collides with a reverse accessor
    # elsewhere. The operator can promote to a real reverse name in
    # review.
    if fk_target:
        on_delete = 'models.CASCADE'  # overwritten by generate_models_py
        nb = _render_null_blank(col)
        return (f'models.ForeignKey("{fk_target}", '
                f'on_delete={on_delete}, related_name="+"{nb})')

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

    kw = _type_keyword(raw)
    unsigned = 'unsigned' in raw
    nbd_num = _nbd(col, 'numeric')
    nbd_str = _nbd(col, 'string')

    # Boolean — tinyint(1) is MySQL's canonical bool shape, distinct
    # from tinyint(N) which is a small int. The prefix check keeps
    # it routed to BooleanField before the integer map kicks in.
    if raw.startswith('tinyint(1)') or kw in BOOLEAN_TYPE_KEYWORDS:
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

    # Integer family — single lookup in INTEGER_TYPE_MAP.
    if kw in INTEGER_TYPE_MAP:
        signed_field, unsigned_field = INTEGER_TYPE_MAP[kw]
        field = unsigned_field if unsigned else signed_field
        return f'models.{field}({nbd_num.lstrip(", ")})'

    # Decimal / numeric — shares (M,D) precision extraction.
    dp = _decimal_precision(raw)
    if dp is not None:
        return (f'models.DecimalField(max_digits={dp[0]}, '
                f'decimal_places={dp[1]}{nbd_num})')
    if kw in FLOAT_TYPE_KEYWORDS:
        return f'models.FloatField({nbd_num.lstrip(", ")})'

    # Char / varchar — length-based, with column-name heuristics for
    # specialised Django fields (EmailField, URLField, SlugField).
    char_len = _char_length(raw)
    if char_len is not None:
        if _is_email_column(col.name):
            return f'models.EmailField(max_length={char_len}{nbd_str})'
        if _is_url_column(col.name):
            return f'models.URLField(max_length={char_len}{nbd_str})'
        if _is_slug_column(col.name):
            return f'models.SlugField(max_length={char_len}{nbd_str})'
        if _is_ip_column(col.name):
            return f'models.GenericIPAddressField({null_blank.lstrip(", ")})'
        return f'models.CharField(max_length={char_len}{nbd_str})'

    # Text family
    if kw in TEXT_TYPE_KEYWORDS:
        return f'models.TextField({nbd_str.lstrip(", ")})'

    # Dates and times
    if kw in DATE_TYPE_KEYWORDS:
        return f'models.DateField({null_blank.lstrip(", ")})'
    if kw in TIME_TYPE_KEYWORDS:
        return f'models.TimeField({null_blank.lstrip(", ")})'
    if kw in DATETIME_TYPE_KEYWORDS:
        return f'models.DateTimeField({null_blank.lstrip(", ")})'
    if kw == 'year':
        return f'models.PositiveSmallIntegerField({nbd_num.lstrip(", ")})'

    # ENUM — handled at the model level (via TextChoices). Caller sets
    # this up when it detects an enum; this function only returns the
    # CharField reference.
    if kw == 'enum':
        m = re.match(r'enum\((.+)\)', raw)
        if m:
            vals = re.findall(r"'((?:[^']|'')*)'", m.group(1))
            max_len = max((len(v) for v in vals), default=20)
            choices_cls = f'{column_to_field_name(col.name).title()}Choices'
            return (f'models.CharField(max_length={max_len}, '
                    f'choices={choices_cls}.choices{null_blank})')

    # SET — MySQL's comma-separated multi-enum. Django has no native
    # equivalent, but storing as a CharField with the full possible
    # length (all values + separators) keeps the legacy data intact.
    # The operator will typically post-process into a list or M2M.
    if kw == 'set':
        m = re.match(r'set\((.+)\)', raw)
        if m:
            vals = re.findall(r"'((?:[^']|'')*)'", m.group(1))
            max_len = sum(len(v) for v in vals) + max(0, len(vals) - 1) or 255
            allowed = ', '.join(vals)
            return (f'models.CharField(max_length={max_len}{null_blank}, '
                    f'help_text="MySQL SET — stored as comma-separated '
                    f'string. Allowed values: {allowed}.")')

    # JSON
    if kw in JSON_TYPE_KEYWORDS:
        return f'models.JSONField(default=dict{null_blank})'

    # UUID — Django's native UUIDField.
    if kw in UUID_TYPE_KEYWORDS:
        return f'models.UUIDField({null_blank.lstrip(", ")})'

    # Blob / binary
    if kw in BLOB_TYPE_KEYWORDS:
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


_JUNCTION_META_COLS = {
    'id', 'created_at', 'updated_at', 'last_update', 'modified_at',
    'added_at', 'timestamp', 'ts',
}


def _is_junction_table(t: Table) -> bool:
    """Two FK columns plus maybe id/timestamp columns — classic
    pivot-table pattern (e.g. Laravel's baby_language, Sakila's
    film_actor)."""
    fk_cols = {c for fk in t.foreign_keys for c in fk.columns}
    data_cols = [c.name for c in t.columns
                 if c.name not in _JUNCTION_META_COLS and c.name not in fk_cols]
    return len(fk_cols) == 2 and not data_cols


def _find_junction_m2ms(tables: List[Table]) -> Dict[str, List[tuple]]:
    """For each parent table, list the (m2m_field_name, junction_table,
    other_parent_table) tuples we should emit as ManyToManyField.

    A junction qualifies when it has exactly two single-column FKs
    and no data columns beyond id/created_at/updated_at/last_update.
    The M2M is hung off the first FK's target; the other becomes
    the `to=...`. We still keep the junction as its own model
    (ingestdump needs it to load data, and extra fields may exist).
    """
    m2ms: Dict[str, List[tuple]] = {}
    meta_cols = {'id', 'created_at', 'updated_at', 'last_update'}
    for t in tables:
        if not _is_junction_table(t):
            continue
        fks = [fk for fk in t.foreign_keys if len(fk.columns) == 1]
        if len(fks) != 2:
            continue
        # Pick the first FK's parent as "owner" of the M2M; the
        # second's parent is the M2M target.
        owner = fks[0].ref_table
        other = fks[1].ref_table
        # Name the M2M after the junction table's remaining identity —
        # e.g. film_actor on Film → actors, on Actor → films.
        # We default to the pluralised other-parent name.
        field_name = pluralize(singularize(other))
        m2ms.setdefault(owner, []).append((field_name, t.name, other))
    return m2ms


def generate_models_py(tables: List[Table], app_label: str,
                       source: str = '') -> str:
    """Emit a full models.py as a string."""
    _all_table_names = [t.name for t in tables]
    # Map legacy table name → Django model name (for FK targets)
    model_name_for = {t.name: table_to_model_name(t.name, app_label, _all_table_names)
                      for t in tables}
    m2ms = _find_junction_m2ms(tables)

    # Pre-pass: if any FK targets a non-PK column, that column must
    # be declared unique on the referenced table. Django rejects
    # `to_field='x'` without `unique=True` on x (fields.E311).
    # Dolibarr's schema has several such FKs to `code` VARCHARs that
    # aren't formally unique in the CREATE TABLE; flag them here.
    by_name = {t.name: t for t in tables}
    for t in tables:
        for fk in t.foreign_keys:
            ref = by_name.get(fk.ref_table)
            if (ref is None or not fk.ref_columns
                    or len(fk.ref_columns) != 1):
                continue
            ref_col = fk.ref_columns[0]
            if ref_col in ref.primary_key:
                continue
            if [ref_col] in ref.uniques:
                continue
            ref.uniques.append([ref_col])
            for c in ref.columns:
                if c.name == ref_col:
                    c.is_unique = True

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

        # Natural single-column PK (not auto-increment, not an FK) —
        # we'll add `primary_key=True` so Django doesn't silently tack
        # on its own `id` column. Composite PKs stay as
        # UniqueConstraint below; FK-as-PK also stays as constraint,
        # since Django won't let a ForeignKey be the sole PK.
        natural_pk_col = None
        if (len(t.primary_key) == 1
                and not any(c.is_auto_inc and c.name == t.primary_key[0]
                            for c in t.columns)
                and t.primary_key[0] not in fk_by_col):
            natural_pk_col = t.primary_key[0]

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
                    r'on_delete=models\.[A-Z_]+',
                    f'on_delete={on_delete}',
                    field_code,
                )
                # Non-PK target: when the FK references a column
                # other than the target's PK, emit `to_field='col'`
                # so Django matches the legacy data. Dolibarr's
                # `fk_pcg_version → llx_accounting_system(pcg_version)`
                # is the motivating case — stores strings like
                # `'PCG15-PYME-AD'` pointed at a non-PK VARCHAR.
                ref_tbl_obj = next((tt for tt in tables
                                    if tt.name == fk.ref_table), None)
                if (fk.ref_columns and ref_tbl_obj
                        and ref_tbl_obj.primary_key
                        and fk.ref_columns != ref_tbl_obj.primary_key):
                    to_field = fk.ref_columns[0]
                    field_code = re.sub(
                        r'(on_delete=models\.[A-Z_]+)',
                        rf"\1, to_field='{to_field}'",
                        field_code,
                    )
            else:
                py_name = column_to_field_name(col.name)

            # Inject `unique=True` when the column has a single-col
            # UNIQUE constraint. (Multi-col uniques land as Meta
            # UniqueConstraints further down.) For FK columns the
            # positional target string comes first — we insert
            # after it to avoid SyntaxError. For non-FK fields we
            # insert at the head of the kwargs.
            if (col.is_unique and col.name != natural_pk_col
                    and 'primary_key=True' not in field_code
                    and 'unique=True' not in field_code
                    and '(' in field_code):
                if fk:
                    # ForeignKey("Target", … )  → add after "Target",
                    field_code = re.sub(
                        r'(models\.ForeignKey\("[^"]+"),\s*',
                        r'\1, unique=True, ',
                        field_code,
                        count=1,
                    )
                else:
                    paren_open = field_code.index('(')
                    paren_close = field_code.rindex(')')
                    inner = field_code[paren_open + 1:paren_close].strip()
                    sep = ', ' if inner else ''
                    field_code = (field_code[:paren_open + 1]
                                  + 'unique=True' + sep + inner
                                  + field_code[paren_close:])

            # Promote this column to the natural PK if appropriate.
            # Inject `primary_key=True` and strip any null=True /
            # blank=True (PKs are implicitly NOT NULL in MySQL even
            # when the CREATE TABLE forgets to say so).
            if col.name == natural_pk_col and '(' in field_code:
                paren_open = field_code.index('(')
                paren_close = field_code.rindex(')')
                inner = field_code[paren_open + 1:paren_close].strip()
                inner = re.sub(r',?\s*null=True', '', inner)
                inner = re.sub(r',?\s*blank=True', '', inner)
                inner = inner.lstrip(', ').strip()
                sep = ', ' if inner else ''
                field_code = (field_code[:paren_open + 1]
                              + 'primary_key=True' + sep + inner
                              + field_code[paren_close:])

            # Django reserves the Python name `id` for primary keys.
            # When a legacy composite-PK table has an `id` column
            # that's just one part of the composite (Joomla's
            # `associations` table is the motivating case), we must
            # promote `id` to primary_key=True here — the composite
            # UniqueConstraint still enforces the full tuple; Django
            # just needs to know which single column acts as PK.
            if (col.name == 'id'
                    and col.name in t.primary_key
                    and len(t.primary_key) > 1
                    and 'primary_key=True' not in field_code
                    and not (col.is_auto_inc and col.name == 'id')):
                if '(' in field_code:
                    paren_open = field_code.index('(')
                    paren_close = field_code.rindex(')')
                    inner = field_code[paren_open + 1:paren_close].strip()
                    inner = re.sub(r',?\s*null=True', '', inner)
                    inner = re.sub(r',?\s*blank=True', '', inner)
                    inner = inner.lstrip(', ').strip()
                    sep = ', ' if inner else ''
                    field_code = (field_code[:paren_open + 1]
                                  + 'primary_key=True' + sep + inner
                                  + field_code[paren_close:])

            out.append(f'    {py_name} = {field_code}')

        # 2b. M2M fields for junction tables hanging off this model.
        for field_name, junction_table, other_table in m2ms.get(t.name, []):
            other_model = model_name_for.get(other_table, other_table)
            junction_model = model_name_for.get(junction_table, junction_table)
            out.append(
                f'    {field_name} = models.ManyToManyField('
                f'"{other_model}", through="{junction_model}", '
                f'related_name="+")'
            )

        # 3. Meta
        col_names = {c.name for c in t.columns}
        # Pick the real PK name for ordering — legacy tables often
        # don't call it `id`. If the PK column is actually an FK
        # (common in junction tables), the Django field name will
        # have had `_id` stripped; mirror that transform here.
        pk_col = next(
            (c.name for c in t.columns if c.is_auto_inc),
            (t.primary_key[0] if t.primary_key else 'id'),
        )
        pk_field = column_to_field_name(pk_col)
        if pk_col in fk_by_col and pk_field.endswith('_id'):
            pk_field = pk_field[:-3]
        ordering = [pk_field]
        if 'created_at' in col_names:
            ordering = ['-created_at']
        elif 'name' in col_names:
            ordering = ['name']

        out.append('')
        out.append('    class Meta:')
        out.append(f"        db_table = '{t.name}'")
        out.append(f"        ordering = {ordering!r}")
        plural = pluralize(singularize(t.name))
        if plural != model.lower() + 's':
            out.append(f"        verbose_name_plural = '{plural}'")
        # Composite primary keys → UniqueConstraint, so the
        # uniqueness semantic survives even though Django adds its
        # own synthetic PK.
        if len(t.primary_key) > 1:
            pk_fields = []
            for col_name in t.primary_key:
                # If the column is an FK, its Django field name is
                # stripped of the '_id' suffix.
                py_name = column_to_field_name(col_name)
                if col_name in fk_by_col and py_name.endswith('_id'):
                    py_name = py_name[:-3]
                pk_fields.append(py_name)
            constraint_name = f'{t.name}_pk'[:63]
            out.append('        constraints = [')
            out.append(
                f'            models.UniqueConstraint(fields={pk_fields!r}, '
                f"name='{constraint_name}'),"
            )
            out.append('        ]')
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
    # Default skips are Laravel housekeeping tables. We only bake
    # them into the emitted map when they actually appear in the
    # dump — otherwise they're just confusing noise in non-Laravel
    # maps (e.g. an employees or MediaWiki dump).
    laravel_skip = {'migrations', 'password_resets',
                    'personal_access_tokens', 'failed_jobs'}
    table_names = {t.name for t in tables}
    skip_tables = laravel_skip & table_names
    if skip_tables:
        out['skip_tables'] = sorted(skip_tables)

    _all_table_names = [t.name for t in tables]
    for t in tables:
        if t.name in skip_tables:
            continue

        model_name = table_to_model_name(t.name, app_label, _all_table_names)
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
    _all_table_names = [t.name for t in tables]
    model_names = [table_to_model_name(t.name, app_label, _all_table_names) for t in tables
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
        model = table_to_model_name(t.name, app_label, _all_table_names)
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
