"""Translate Doctrine entity classes into Django models.

Doctrine is Symfony's default ORM. Entities are PHP classes
decorated with PHP 8 attributes (modern) or annotations (legacy):

    #[ORM\\Entity(repositoryClass: PostRepository::class)]
    #[ORM\\Table(name: 'posts')]
    class Post
    {
        #[ORM\\Id]
        #[ORM\\GeneratedValue]
        #[ORM\\Column(type: 'integer')]
        private int $id;

        #[ORM\\Column(type: 'string', length: 255)]
        private string $title;

        #[ORM\\ManyToOne(targetEntity: User::class)]
        #[ORM\\JoinColumn(nullable: false)]
        private User $author;
    }

This module parses each entity class and emits a Django model — the
same shape genmodels would produce from a SQL dump, but driven from
the PHP source instead. Useful when the Symfony app ships entities
but no schema dump.

Pure Python, no LLM, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Records ────────────────────────────────────────────────────────

@dataclass
class DoctrineColumn:
    name: str               # PHP property name (camelCase)
    db_name: str            # underscored snake_case for db_column
    django_type: str
    kwargs: dict[str, object] = field(default_factory=dict)
    raw: str = ''


@dataclass
class DoctrineEntity:
    source: Path
    class_name: str
    db_table: str
    columns: list[DoctrineColumn] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


@dataclass
class DoctrineLiftResult:
    entities: list[DoctrineEntity] = field(default_factory=list)
    skipped_files: list[Path] = field(default_factory=list)


# ── PHP source utilities ──────────────────────────────────────────

def _strip_php_comments(src: str) -> str:
    src = re.sub(r'(?m)//.*?$', '', src)
    src = re.sub(r'(?m)#(?!\[).*?$', '', src)  # `#` but not `#[`
    return src


def _camel_to_snake(name: str) -> str:
    s = re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
    return s


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _split_top_level_commas(s: str) -> list[str]:
    parts: list[str] = []; buf: list[str] = []
    depth = 0; in_str: str | None = None
    for ch in s:
        if in_str:
            buf.append(ch)
            if ch == in_str: in_str = None
            continue
        if ch in ('"', "'"): in_str = ch; buf.append(ch); continue
        if ch in '([{': depth += 1; buf.append(ch)
        elif ch in ')]}': depth -= 1; buf.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(buf)); buf = []
        else:
            buf.append(ch)
    if buf: parts.append(''.join(buf))
    return parts


def _php_value_to_python(s: str) -> object:
    s = s.strip()
    if not s: return None
    if (s.startswith("'") and s.endswith("'")) or \
       (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    if s.lower() in ('true', 'false'):
        return s.lower() == 'true'
    if s.lower() == 'null':
        return None
    try: return int(s)
    except ValueError: pass
    try: return float(s)
    except ValueError: pass
    return s


def _parse_attr_args(args: str) -> dict[str, object]:
    """Parse attribute arguments into a dict.

    Handles named args (`name: 'foo'`, `length: 255`, `type: 'string'`)
    AND positional first arg (treated as the primary value).
    """
    out: dict[str, object] = {}
    parts = _split_top_level_commas(args)
    for i, p in enumerate(parts):
        p = p.strip()
        if not p:
            continue
        if ':' in p and not p.startswith(("'", '"')):
            key, _, val = p.partition(':')
            out[key.strip()] = _php_value_to_python(val.strip())
        else:
            out.setdefault('_positional', []).append(_php_value_to_python(p))
    return out


# Doctrine `Types::*` class constants — common shorthand in modern
# Symfony. Resolve to lowercase string types before mapping.
_TYPES_CONST_MAP = {
    'INTEGER':            'integer',
    'BIGINT':             'bigint',
    'SMALLINT':           'smallint',
    'STRING':             'string',
    'TEXT':               'text',
    'BOOLEAN':            'boolean',
    'FLOAT':              'float',
    'DECIMAL':            'decimal',
    'DATE_MUTABLE':       'date',
    'DATE_IMMUTABLE':     'date_immutable',
    'DATETIME_MUTABLE':   'datetime',
    'DATETIME_IMMUTABLE': 'datetime_immutable',
    'DATETIMETZ_MUTABLE': 'datetimetz',
    'DATETIMETZ_IMMUTABLE':'datetimetz',
    'TIME_MUTABLE':       'time',
    'TIME_IMMUTABLE':     'time_immutable',
    'JSON':               'json',
    'ARRAY':              'array',
    'SIMPLE_ARRAY':       'simple_array',
    'BINARY':             'binary',
    'BLOB':               'blob',
    'OBJECT':             'object',
    'GUID':               'guid',
    'ASCII_STRING':       'ascii_string',
}


def _resolve_doctrine_type(t: object) -> str:
    """Doctrine type can be a literal ('string') or a class constant
    (Types::DATETIME_MUTABLE). Normalise to the lowercase literal."""
    if not isinstance(t, str):
        return 'string'
    if '::' in t:
        const_name = t.split('::', 1)[1]
        return _TYPES_CONST_MAP.get(const_name, t.lower())
    return t


# When `#[ORM\Column]` has no explicit `type:`, Doctrine infers the
# type from the PHP property type hint. Mirror that here.
_PHP_TYPE_TO_DOCTRINE = {
    'string':              'string',
    'int':                 'integer',
    'bool':                'boolean',
    'float':               'float',
    'array':               'json',
    'datetime':            'datetime',
    'datetimeimmutable':   'datetime_immutable',
    'datetimeinterface':   'datetime',
    'dateinterval':        'string',
    'datetimezone':        'string',
}


def _infer_type_from_hint(hint: str | None) -> str | None:
    """Return a Doctrine type name from a PHP type hint, or None."""
    if not hint:
        return None
    name = hint.lstrip('?').lstrip('\\').lower()
    return _PHP_TYPE_TO_DOCTRINE.get(name)


# ── Doctrine type → Django field mapping ──────────────────────────

_TYPE_TO_DJANGO: dict[str, tuple[str, dict]] = {
    'integer':       ('IntegerField',         {}),
    'smallint':      ('SmallIntegerField',    {}),
    'bigint':        ('BigIntegerField',      {}),
    'string':        ('CharField',            {'max_length': 255}),
    'text':          ('TextField',            {}),
    'guid':          ('UUIDField',            {}),
    'uuid':          ('UUIDField',            {}),
    'boolean':       ('BooleanField',         {}),
    'float':         ('FloatField',           {}),
    'decimal':       ('DecimalField',         {'max_digits': 10, 'decimal_places': 2}),
    'date':          ('DateField',            {}),
    'date_immutable':('DateField',            {}),
    'datetime':      ('DateTimeField',        {}),
    'datetime_immutable': ('DateTimeField',   {}),
    'datetimetz':    ('DateTimeField',        {}),
    'time':          ('TimeField',            {}),
    'time_immutable':('TimeField',            {}),
    'json':          ('JSONField',            {}),
    'array':         ('JSONField',            {}),
    'simple_array':  ('JSONField',            {}),
    'binary':        ('BinaryField',          {}),
    'blob':          ('BinaryField',          {}),
    'object':        ('TextField',            {}),
    'ascii_string':  ('CharField',            {'max_length': 255}),
}


# ── Class + property parsing ──────────────────────────────────────

_ENTITY_HEADER = re.compile(
    r'class\s+(?P<name>\w+)\s*'
)
_PROPERTY_HEADER = re.compile(
    r'(?P<vis>public|protected|private)\s+'
    r'(?:readonly\s+)?'
    r'(?:(?P<type>\??[\\\w]+)\s+)?'
    r'\$(?P<name>\w+)'
    r'(?:\s*=\s*[^;]+)?\s*;'
)
_ATTR_RE = re.compile(
    r'#\[\s*(?:ORM\\)?(?P<name>\w+)\s*'
    r'(?:\((?P<args>(?:[^\[\]()]|\[[^\[\]]*\]|\([^()]*\))*)\))?'
    r'\s*\]',
    re.DOTALL,
)
_ENTITY_ATTR_RE = re.compile(r'#\[\s*(?:ORM\\)?Entity\b')
_TABLE_ATTR_RE = re.compile(
    r'#\[\s*(?:ORM\\)?Table\s*\((?P<args>(?:[^()]|\([^()]*\))*)\)\s*\]'
)


def parse_entity(php: str, source: Path | None = None) -> DoctrineEntity | None:
    """Parse a Doctrine entity class out of PHP source.

    Returns None if the file doesn't contain an `#[ORM\\Entity]`
    annotation (or its annotation form `@ORM\\Entity`).
    """
    src = _strip_php_comments(php)
    if not _ENTITY_ATTR_RE.search(src) and '@ORM\\Entity' not in src:
        return None

    cm = _ENTITY_HEADER.search(src)
    if not cm:
        return None

    rec = DoctrineEntity(
        source=source or Path('entity.php'),
        class_name=cm.group('name'),
        db_table='',
    )

    # Table name: prefer #[ORM\Table(name: 'foo')]; fall back to
    # snake_case of the class name.
    tm = _TABLE_ATTR_RE.search(src)
    if tm:
        targs = _parse_attr_args(tm.group('args'))
        if 'name' in targs:
            rec.db_table = str(targs['name'])
    if not rec.db_table:
        rec.db_table = _camel_to_snake(rec.class_name) + 's'

    # Walk each property: gather attributes that immediately precede it.
    last_end = src.find('{', cm.end())
    if last_end < 0:
        return rec
    last_end += 1

    for pm in _PROPERTY_HEADER.finditer(src, last_end):
        pre_region = src[last_end:pm.start()]
        attrs: list[tuple[str, dict[str, object]]] = []
        for am in _ATTR_RE.finditer(pre_region):
            args = am.group('args') or ''
            attrs.append((am.group('name'), _parse_attr_args(args)))

        # Build the column from the gathered attributes.
        col = _build_column(pm.group('name'), pm.group('type'), attrs)
        if col is not None:
            rec.columns.append(col)
        last_end = pm.end()

    return rec


def _build_column(prop_name: str, type_hint: str | None,
                   attrs: list[tuple[str, dict[str, object]]]) -> DoctrineColumn | None:
    """Translate one Doctrine property + its preceding attributes into
    a DoctrineColumn. Returns None if the property has no @Column
    or relationship attribute (likely a non-persisted property)."""
    snake = _camel_to_snake(prop_name)
    is_id = any(name == 'Id' for name, _ in attrs)
    is_generated = any(name == 'GeneratedValue' for name, _ in attrs)
    is_nullable = False  # Set by JoinColumn or Column kwargs
    column_attr = next(((n, a) for n, a in attrs if n == 'Column'), None)
    onetoone   = next(((n, a) for n, a in attrs if n == 'OneToOne'), None)
    onetomany  = next(((n, a) for n, a in attrs if n == 'OneToMany'), None)
    manytoone  = next(((n, a) for n, a in attrs if n == 'ManyToOne'), None)
    manytomany = next(((n, a) for n, a in attrs if n == 'ManyToMany'), None)
    join_col   = next(((n, a) for n, a in attrs if n == 'JoinColumn'), None)

    # Relationship cases
    if manytoone:
        target = _resolve_target(manytoone[1])
        on_delete = 'models.DO_NOTHING'
        kwargs: dict[str, object] = {'to': repr(target),
                                      'on_delete': 'models.DO_NOTHING'}
        if join_col and join_col[1].get('nullable') is True:
            kwargs['null'] = True
            kwargs['blank'] = True
        if join_col and join_col[1].get('onDelete'):
            policy = str(join_col[1]['onDelete']).upper()
            kwargs['on_delete'] = {
                'CASCADE':  'models.CASCADE',
                'SET NULL': 'models.SET_NULL',
                'RESTRICT': 'models.PROTECT',
            }.get(policy, 'models.DO_NOTHING')
        return DoctrineColumn(
            name=snake, db_name=snake + '_id',
            django_type='ForeignKey', kwargs=kwargs,
            raw=str(manytoone),
        )
    if onetoone:
        target = _resolve_target(onetoone[1])
        return DoctrineColumn(
            name=snake, db_name=snake + '_id',
            django_type='OneToOneField',
            kwargs={'to': repr(target),
                    'on_delete': 'models.DO_NOTHING'},
            raw=str(onetoone),
        )
    if manytomany:
        target = _resolve_target(manytomany[1])
        return DoctrineColumn(
            name=snake, db_name=snake,
            django_type='ManyToManyField',
            kwargs={'to': repr(target)},
            raw=str(manytomany),
        )
    if onetomany:
        # OneToMany → handled by the inverse side in Django (related_name).
        # Nothing to emit here.
        return None

    if column_attr is None:
        # No @Column and no relationship — not a persisted property.
        return None

    args = column_attr[1]
    if 'type' in args:
        type_name = _resolve_doctrine_type(args['type'])
    else:
        type_name = _infer_type_from_hint(type_hint) or 'string'
    if type_name in _TYPE_TO_DJANGO:
        django_type, base_kwargs = _TYPE_TO_DJANGO[type_name]
    else:
        django_type, base_kwargs = ('CharField', {'max_length': 255})
    kwargs = dict(base_kwargs)

    if django_type == 'CharField' and 'length' in args:
        try: kwargs['max_length'] = int(args['length'])
        except (ValueError, TypeError): pass
    if 'nullable' in args and args['nullable'] is True:
        kwargs['null'] = True
        kwargs['blank'] = True
    if 'unique' in args and args['unique'] is True:
        kwargs['unique'] = True
    if 'precision' in args:
        try: kwargs['max_digits'] = int(args['precision'])
        except (ValueError, TypeError): pass
    if 'scale' in args:
        try: kwargs['decimal_places'] = int(args['scale'])
        except (ValueError, TypeError): pass
    if 'options' in args and isinstance(args['options'], dict):
        opts = args['options']
        if 'default' in opts:
            kwargs['default'] = opts['default']

    if is_id:
        if is_generated:
            if django_type == 'BigIntegerField':
                django_type = 'BigAutoField'
            else:
                django_type = 'AutoField'
            kwargs.pop('max_length', None)
        kwargs['primary_key'] = True

    return DoctrineColumn(
        name=snake, db_name=snake,
        django_type=django_type, kwargs=kwargs,
        raw=str(column_attr),
    )


def _resolve_target(args: dict[str, object]) -> str:
    """Get a relationship target's class name from a Doctrine attribute."""
    if 'targetEntity' in args:
        t = args['targetEntity']
        if isinstance(t, str):
            # Strip `::class` suffix (already stripped by _php_value_to_python
            # in most cases, but be defensive) and namespace prefix.
            t = t.replace('::class', '').strip()
            return t.replace('\\\\', '\\').rsplit('\\', 1)[-1]
    pos = args.get('_positional') or []
    if pos:
        first = str(pos[0]).replace('::class', '').strip()
        return first.replace('\\\\', '\\').rsplit('\\', 1)[-1]
    return 'Unknown'


# ── Walker ────────────────────────────────────────────────────────

def parse_doctrine(app_dir: Path) -> DoctrineLiftResult:
    """Walk a Symfony / Doctrine project's entity directory."""
    result = DoctrineLiftResult()
    if not app_dir.is_dir():
        return result
    for sub in ('src/Entity', 'src/Entities', 'src/Domain'):
        d = app_dir / sub
        if not d.is_dir():
            continue
        for php_file in sorted(d.rglob('*.php')):
            try:
                php = php_file.read_text(encoding='utf-8', errors='replace')
            except OSError:
                result.skipped_files.append(php_file.relative_to(app_dir))
                continue
            ent = parse_entity(php, source=php_file.relative_to(app_dir))
            if ent is not None:
                result.entities.append(ent)
    return result


# ── Models renderer ───────────────────────────────────────────────

def render_models(result: DoctrineLiftResult) -> str:
    out = [
        '"""Auto-generated by datalift liftdoctrine.',
        '',
        'Translated from Symfony / Doctrine entity classes',
        '(`#[ORM\\\\Entity]` annotations / PHP 8 attributes). Review',
        'every model before migrating: max_length, on_delete policy,',
        'and forward-reference targets are best-effort inferences.',
        '"""',
        'from django.db import models',
        '',
        '',
    ]
    for ent in result.entities:
        out.append(f'class {ent.class_name}(models.Model):')
        out.append(f'    """Generated from Doctrine entity `{ent.class_name}`."""')
        out.append('')
        for col in ent.columns:
            kwargs_src = ', '.join(
                f'{k}={_kwarg_repr(v)}' for k, v in col.kwargs.items()
            )
            out.append(f'    {col.name} = models.{col.django_type}'
                       f'({kwargs_src})')
        out.append('')
        out.append('    class Meta:')
        out.append(f"        db_table = {ent.db_table!r}")
        out.append('')
    return '\n'.join(out)


def _kwarg_repr(v: object) -> str:
    if isinstance(v, str):
        if v.startswith('models.') or v.startswith("'") or v.startswith('"'):
            return v
        return repr(v)
    return repr(v)


# ── Worklist + apply ──────────────────────────────────────────────

def render_worklist(result: DoctrineLiftResult, app_label: str,
                    app_dir: Path) -> str:
    lines = [
        f'# liftdoctrine worklist — {app_dir.name}',
        '',
        f'Target app: `{app_label}`. Generated by `datalift liftdoctrine`.',
        '',
        f'## Entities ({len(result.entities)})',
        '',
    ]
    if not result.entities:
        lines.append('_(none — no `#[ORM\\Entity]` classes found)_')
    for ent in result.entities:
        lines.append(f'- `{ent.source}` — `{ent.class_name}` '
                     f'→ `{ent.db_table}` ({len(ent.columns)} field(s))')
    return '\n'.join(lines)


def apply(result: DoctrineLiftResult, project_root: Path,
          app_label: str, dry_run: bool = False) -> list[str]:
    log: list[str] = []
    if not result.entities:
        return log
    app_dir = project_root / app_label
    if not dry_run:
        app_dir.mkdir(parents=True, exist_ok=True)
    target = app_dir / 'models_doctrine.py'
    text = render_models(result)
    if not dry_run:
        target.write_text(text, encoding='utf-8')
    log.append(f'models    → {target.relative_to(project_root)} '
               f'({len(result.entities)} entity(ies))')
    return log
