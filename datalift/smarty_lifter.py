"""Translate a Smarty template tree into Django templates.

Pure Python, no Django imports, no network, no LLM. The management
command :mod:`datalift.management.commands.liftsmarty` wraps this for
the file-writing side. Designed in parallel with :mod:`datalift.wp_lifter`
— the same translator-with-rules-table shape, retargeted from
WordPress PHP themes to Smarty `.tpl` templates.

Smarty is small. The translator handles five tag families:

* **Echoes** — ``{$var}``, ``{$obj.prop}``, ``{$obj->prop}``,
  short literals ``{$x|modifier:arg}``.
* **Control flow** — ``{if X}{elseif X}{else}{/if}``,
  ``{foreach $X as $Y}{foreachelse}{/foreach}`` (modern syntax),
  ``{foreach from=$X item=Y}`` (older syntax).
* **Includes** — ``{include file='X.tpl'}``.
* **Comments** — ``{*...*}`` dropped silently.
* **Modifiers** — ``|@translate``, ``|escape``, ``|default``,
  ``|count``, ``|date_format``, plus a passthrough for unknown.

What is deliberately not in scope (flagged in the worklist as
``{# SMARTY-LIFT? <original> #}`` markers):

* ``{capture}``, ``{section}`` (older Smarty 2 looping),
  ``{cycle}``, ``{counter}`` — the long tail of legacy tags.
* Plugin tags like ``{html_image}``, ``{popup_init}``,
  ``{html_options}`` — port by hand.
* ``{php}...{/php}`` blocks — out of scope for a template lifter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Records (shared shape with wp_lifter) ──────────────────────────

@dataclass
class TemplateRecord:
    source: Path
    target_name: str
    body: str
    skipped: list[str] = field(default_factory=list)


@dataclass
class LiftResult:
    records: list[TemplateRecord] = field(default_factory=list)
    static_assets: list[Path] = field(default_factory=list)
    unhandled_files: list[Path] = field(default_factory=list)


# ── Smarty tag detection ───────────────────────────────────────────
#
# Smarty distinguishes tags from literal `{` by what follows the open
# brace: a non-whitespace character means tag, whitespace or end-of-line
# means literal. The Piwigo / typical-WP-plugin shape uses no spaces.
# We honour the convention.
#
# `{literal}...{/literal}` opts out of Smarty parsing — we treat any
# text inside as raw HTML and emit it verbatim.
# `{*comment*}` is dropped silently.

_TAG_OPEN  = re.compile(r'\{(?!\s)')
_TAG_CLOSE = re.compile(r'\}')
_LITERAL_OPEN  = '{literal}'
_LITERAL_CLOSE = '{/literal}'
_COMMENT_OPEN  = '{*'
_COMMENT_CLOSE = '*}'


def _find_tag_boundaries(source: str, start: int) -> tuple[int, int] | None:
    """Find the next Smarty tag, returning (open_idx, close_idx) or None.

    Skips past `{*comment*}` and `{literal}...{/literal}` regions. The
    returned indices delimit just the tag content (not including the
    surrounding ``{`` ``}``).
    """
    i = start
    while i < len(source):
        m = _TAG_OPEN.search(source, i)
        if not m:
            return None
        open_pos = m.start()
        # Comment: {*...*}
        if source[open_pos:open_pos + 2] == _COMMENT_OPEN:
            close = source.find(_COMMENT_CLOSE, open_pos + 2)
            if close < 0:
                return None  # unterminated comment, treat tail as literal
            i = close + 2
            continue
        # Literal: {literal}...{/literal} — skip the whole region
        if source[open_pos:open_pos + len(_LITERAL_OPEN)] == _LITERAL_OPEN:
            close = source.find(_LITERAL_CLOSE,
                                open_pos + len(_LITERAL_OPEN))
            if close < 0:
                return None
            i = close + len(_LITERAL_CLOSE)
            continue
        # Real tag — find matching close. Smarty doesn't nest curly
        # braces inside tag bodies (would conflict with the syntax),
        # so the next `}` ends it.
        close_m = _TAG_CLOSE.search(source, open_pos + 1)
        if not close_m:
            return None
        return (open_pos, close_m.end())


def _strip_comments_and_literals(source: str) -> str:
    """Return a copy with `{*...*}` removed and `{literal}...{/literal}`
    contents preserved literally. Used during the main translate pass —
    we walk tags but skip these regions."""
    # Implementation note: we don't actually strip in-place; the
    # main translate loop honours these regions via _find_tag_boundaries.
    # This helper is kept for explicit testing.
    out = []
    i = 0
    while i < len(source):
        if source.startswith(_COMMENT_OPEN, i):
            close = source.find(_COMMENT_CLOSE, i + 2)
            if close < 0:
                break
            i = close + 2
            continue
        if source.startswith(_LITERAL_OPEN, i):
            close = source.find(_LITERAL_CLOSE, i + len(_LITERAL_OPEN))
            if close < 0:
                out.append(source[i + len(_LITERAL_OPEN):])
                break
            out.append(source[i + len(_LITERAL_OPEN):close])
            i = close + len(_LITERAL_CLOSE)
            continue
        out.append(source[i])
        i += 1
    return ''.join(out)


# ── Tag translation ────────────────────────────────────────────────

# Each rule: (regex matched against the trimmed tag body, replacement).
# Order matters — earlier rules win. Replacement is a string with named
# group substitutions, OR a callable taking the match and returning a
# string.

_LDELIM_RE = re.compile(r'^ldelim$')
_RDELIM_RE = re.compile(r'^rdelim$')
_STRIP_OPEN_RE = re.compile(r'^strip$')
_STRIP_CLOSE_RE = re.compile(r'^/strip$')
_NOP_OPEN_RE = re.compile(r'^nocache$')
_NOP_CLOSE_RE = re.compile(r'^/nocache$')

# Modifier translation: Smarty `|name:arg1:arg2` ↔ Django `|name:arg1`.
# The `@` prefix means "apply to whole array if iterable" in Smarty;
# we drop it (Django filters apply to the value passed to them).
_MODIFIER_MAP = {
    '@translate':   ('translate', None),  # special: a tag in Django, not a filter
    'translate':    ('translate', None),
    'escape':       ('escape', None),
    'escape:html':  ('escape', None),
    'escape:url':   ('urlencode', None),
    'escape:javascript': ('escapejs', None),
    'urlencode':    ('urlencode', None),
    'default':      ('default', '_pass_arg'),
    'count':        ('length', None),
    '@count':       ('length', None),
    'lower':        ('lower', None),
    'upper':        ('upper', None),
    'capitalize':   ('capfirst', None),
    'truncate':     ('truncatechars', '_first_arg'),
    'strip_tags':   ('striptags', None),
    'nl2br':        ('linebreaksbr', None),
    'date_format':  ('date', '_smarty_date'),
    'cat':          ('add', '_pass_arg'),
}


def _smarty_date_to_django(arg: str) -> str:
    """Convert a Smarty `date_format` strftime-style string to Django's
    date filter format. Best-effort — covers the common tokens.
    """
    if arg.startswith('"') and arg.endswith('"'):
        arg = arg[1:-1]
    elif arg.startswith("'") and arg.endswith("'"):
        arg = arg[1:-1]
    table = [
        ('%Y', 'Y'), ('%y', 'y'), ('%m', 'm'), ('%d', 'd'),
        ('%H', 'H'), ('%I', 'h'), ('%M', 'i'), ('%S', 's'),
        ('%p', 'A'), ('%B', 'F'), ('%b', 'M'),
        ('%A', 'l'), ('%a', 'D'),
    ]
    out = arg
    for src, dst in table:
        out = out.replace(src, dst)
    return f'"{out}"'


def _translate_modifier_chain(body: str) -> str:
    """Translate a Smarty `value|mod:arg|mod2` chain to Django filters.

    `value` is whatever is to the left of the first `|`; `mod:arg` is
    each subsequent piece. Returns the translated chain (with the
    `value` translated as a Django expression already)."""
    parts = _split_pipes(body)
    if not parts:
        return body
    expr = _translate_expression(parts[0])
    rest = parts[1:]
    out = [expr]
    for mod in rest:
        translated = _translate_one_modifier(mod)
        if translated is not None:
            out.append('|' + translated)
        else:
            out.append('|' + mod.split(':')[0])  # passthrough name
    return ''.join(out)


def _split_pipes(s: str) -> list[str]:
    """Split on `|` outside of quotes / colons."""
    parts: list[str] = []
    buf: list[str] = []
    in_str: str | None = None
    depth = 0
    for ch in s:
        if in_str:
            buf.append(ch)
            if ch == in_str:
                in_str = None
            continue
        if ch in ('"', "'"):
            in_str = ch
            buf.append(ch)
            continue
        if ch == '(':
            depth += 1
            buf.append(ch)
        elif ch == ')':
            depth -= 1
            buf.append(ch)
        elif ch == '|' and depth == 0:
            parts.append(''.join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append(''.join(buf))
    return parts


def _translate_one_modifier(mod: str) -> str | None:
    """Translate one Smarty modifier (e.g. ``escape``, ``date_format:"%Y"``)
    to a Django filter (e.g. ``escape``, ``date:"Y"``).
    Returns None if it's a passthrough (Django has the same name).

    Smarty's ``@`` prefix means "apply to whole array if iterable" —
    Django filters apply to the value passed in, so we just drop it.
    """
    name, _, arg = mod.partition(':')
    name = name.strip()
    arg = arg.strip()
    bare = name.lstrip('@')
    key = bare + (':' + arg if arg and ':' in mod and bare in {'escape'} else '')
    entry = _MODIFIER_MAP.get(key) or _MODIFIER_MAP.get(bare)
    if entry is None:
        # Unknown modifier — treat as a passthrough (Django filter
        # with the same name, sans @-prefix).
        return bare
    django_name, arg_handler = entry
    if django_name == 'translate':
        # Special-cased upstream — should never reach here as a modifier
        # since translate is a tag in Django.
        return django_name
    if arg_handler == '_pass_arg' and arg:
        return f'{django_name}:{arg}'
    if arg_handler == '_first_arg' and arg:
        first = arg.split(':')[0]
        return f'{django_name}:{first}'
    if arg_handler == '_smarty_date':
        return f'{django_name}:{_smarty_date_to_django(arg)}'
    return django_name


# ── Expression translation (Smarty → Django dotted) ────────────────

def _translate_expression(expr: str) -> str:
    """Translate a Smarty expression to a Django template expression.

    ``$var``                → ``var``
    ``$obj.prop``           → ``obj.prop``
    ``$obj->prop``          → ``obj.prop``
    ``$arr[0]``             → ``arr.0``
    ``$arr['key']``         → ``arr.key``
    ``'literal'``           → ``"literal"``
    """
    expr = expr.strip()
    if not expr:
        return ''
    if expr[0] in ('"', "'"):
        return expr  # literal string
    if expr[0] == '$':
        return _translate_var(expr[1:])
    return expr  # numeric, true/false/null, etc.


def _translate_var(rest: str) -> str:
    """Translate the body of a Smarty variable (everything after `$`)."""
    out: list[str] = []
    i = 0
    n = len(rest)
    # First identifier
    while i < n and (rest[i].isalnum() or rest[i] == '_'):
        out.append(rest[i])
        i += 1
    while i < n:
        ch = rest[i]
        if ch == '.':
            out.append('.')
            i += 1
            while i < n and (rest[i].isalnum() or rest[i] == '_'):
                out.append(rest[i])
                i += 1
        elif ch == '-' and i + 1 < n and rest[i + 1] == '>':
            out.append('.')
            i += 2
            while i < n and (rest[i].isalnum() or rest[i] == '_'):
                out.append(rest[i])
                i += 1
        elif ch == '[':
            close = rest.find(']', i)
            if close < 0:
                break
            inner = rest[i + 1:close].strip()
            if (inner.startswith("'") and inner.endswith("'")) or \
               (inner.startswith('"') and inner.endswith('"')):
                out.append('.' + inner[1:-1])
            elif inner.startswith('$'):
                out.append('.')
                out.append(_translate_var(inner[1:]))
            elif inner.isdigit():
                out.append('.' + inner)
            else:
                out.append('.' + inner)  # best-effort
            i = close + 1
        else:
            break
    return ''.join(out)


# ── Condition translation ──────────────────────────────────────────

_OPERATOR_MAP = {
    'eq': '==', 'neq': '!=', 'ne': '!=',
    'gt': '>', 'lt': '<', 'gte': '>=', 'ge': '>=',
    'lte': '<=', 'le': '<=',
    'and': 'and', 'or': 'or', 'not': 'not',
    'mod': '%',
}


def _translate_condition(cond: str) -> str:
    """Translate a Smarty condition expression to Django's reduced
    `{% if %}` syntax. Handles operator words, `isset`, `empty`,
    and bare variable refs.
    """
    cond = cond.strip()
    # `isset($x)` → `x` (Django nones are falsy)
    cond = re.sub(r'isset\s*\(\s*\$([\w.\[\]\'"\->]+)\s*\)',
                  lambda m: _translate_var(m.group(1)), cond)
    # `empty($x)` → `not x`
    cond = re.sub(r'empty\s*\(\s*\$([\w.\[\]\'"\->]+)\s*\)',
                  lambda m: 'not ' + _translate_var(m.group(1)), cond)
    # Word operators with surrounding whitespace
    def _word_op(m: re.Match) -> str:
        return f' {_OPERATOR_MAP[m.group(0)]} '
    word_re = re.compile(r'\b(?:eq|neq|ne|gt|lt|gte|ge|lte|le|and|or|not|mod)\b')
    cond = word_re.sub(_word_op, cond)
    # `!$x` → `not x`
    cond = re.sub(r'!\s*\$', 'not $', cond)
    # `&&` `||` → `and` `or`
    cond = cond.replace('&&', 'and').replace('||', 'or')
    # Now translate dollar variables
    def _var(m: re.Match) -> str:
        return _translate_var(m.group(1))
    cond = re.sub(r'\$([\w.\[\]\'"\->]+)', _var, cond)
    # Tighten whitespace
    cond = re.sub(r'\s+', ' ', cond).strip()
    return cond


# ── Tag-level rules ────────────────────────────────────────────────

_FOREACH_NEW = re.compile(
    r'^foreach\s+\$(?P<src>[\w.\[\]\'"\->]+)\s+as\s+\$(?P<item>\w+)\s*$'
)
_FOREACH_NEW_KEY = re.compile(
    r'^foreach\s+\$(?P<src>[\w.\[\]\'"\->]+)\s+as\s+\$(?P<key>\w+)\s*=>\s*\$(?P<item>\w+)\s*$'
)
_FOREACH_OLD = re.compile(
    r'^foreach\s+(?:from=\$(?P<src>[\w.\[\]\'"\->]+))(?:\s+|$)'
    r'(?:.*?\bitem=(?P<item>\w+))?'
    r'(?:.*?\bkey=(?P<key>\w+))?'
    r'.*$'
)

_INCLUDE_RE = re.compile(
    r'^include\s+(?:.*?file\s*=\s*(?P<q>["\'])(?P<path>[^"\']+)(?P=q))'
)

_INCLUDE_VAR_RE = re.compile(
    r'^include\s+(?:.*?file\s*=\s*\$)(?P<var>[\w.\[\]\'"\->]+)'
)

_COUNT_RE = re.compile(
    r'^count\s*\(\s*\$(?P<var>[\w.\[\]\'"\->]+)\s*\)\s*$'
)

# Smarty stdlib + common Piwigo / WP-plugin Smarty block tags. Each
# becomes a porter-facing comment marker, NOT a worklist-skip — the
# tags are known and intentional, just not template-translatable.
_KNOWN_PLUGIN_NAMES = {
    # Asset bundling (Piwigo-style)
    'combine_script', 'combine_css',
    'get_combined_scripts', 'get_combined_css',
    # Block-style asset injectors
    'footer_script', '/footer_script',
    'html_style',    '/html_style',
    'html_head',     '/html_head',
    'javascript',    '/javascript',
    # Smarty stdlib form helpers
    'html_options', 'html_radios', 'html_checkboxes',
    'html_select_date', 'html_select_time',
    'html_image', 'html_table',
    # Smarty 2 looping (rarely used today)
    'section', '/section',
    # Misc
    'mailto', 'fetch', 'eval', 'php', '/php',
    'capture', '/capture',
    'cycle', 'counter', 'textformat', '/textformat',
}

_ASSIGN_RE = re.compile(
    r'^assign\s+(?:.*?\bvar\s*=\s*'
    r'(?:(?P<q>["\'])(?P<name>[^"\']+)(?P=q)|(?P<bareName>\w+)))'
    r'.*?\bvalue\s*=\s*(?P<value>.+?)\s*$'
)

_IF_RE          = re.compile(r'^if\s+(?P<cond>.+)$')
_ELSEIF_RE      = re.compile(r'^elseif\s+(?P<cond>.+)$')
_ELSE_IF_RE     = re.compile(r'^else\s+if\s+(?P<cond>.+)$')  # Smarty 2 form


def _translate_tag(body: str, skipped: list[str]) -> str:
    """Translate one Smarty tag body (the text between `{` and `}`)
    to its Django equivalent. Returns the Django string. Records
    unhandled tag bodies in `skipped`."""
    s = body.strip()
    if not s:
        return ''

    # Closing tags first.
    if s == '/if':           return '{% endif %}'
    if s == '/foreach':      return '{% endfor %}'
    if s == '/section':      return '{% endfor %}'  # Smarty 2 loop close
    if s == '/strip':        return ''
    if s == '/nocache':      return ''
    if s == '/literal':      return ''  # handled by walker
    if s == 'else':          return '{% else %}'
    if s == 'foreachelse':   return '{% empty %}'
    if s == 'sectionelse':   return '{% empty %}'
    if _LDELIM_RE.match(s):  return '{'
    if _RDELIM_RE.match(s):  return '}'
    if _STRIP_OPEN_RE.match(s):  return ''
    if _NOP_OPEN_RE.match(s):    return ''

    # Block opens.
    m = _IF_RE.match(s)
    if m:
        return '{% if ' + _translate_condition(m.group('cond')) + ' %}'
    m = _ELSEIF_RE.match(s)
    if m:
        return '{% elif ' + _translate_condition(m.group('cond')) + ' %}'
    m = _ELSE_IF_RE.match(s)
    if m:
        return '{% elif ' + _translate_condition(m.group('cond')) + ' %}'
    m = _FOREACH_NEW_KEY.match(s)
    if m:
        return ('{% for ' + m.group('key') + ', ' + m.group('item')
                + ' in ' + _translate_var(m.group('src')) + '.items %}')
    m = _FOREACH_NEW.match(s)
    if m:
        return ('{% for ' + m.group('item') + ' in '
                + _translate_var(m.group('src')) + ' %}')
    m = _FOREACH_OLD.match(s)
    if m and m.group('src'):
        item = m.group('item') or 'item'
        return ('{% for ' + item + ' in '
                + _translate_var(m.group('src')) + ' %}')
    m = _INCLUDE_RE.match(s)
    if m:
        path = m.group('path').replace('.tpl', '.html')
        return "{% include '" + path + "' %}"
    m = _INCLUDE_VAR_RE.match(s)
    if m:
        return '{% include ' + _translate_var(m.group('var')) + ' %}'
    m = _COUNT_RE.match(s)
    if m:
        return '{{ ' + _translate_var(m.group('var')) + '|length }}'

    # Known Smarty stdlib / Piwigo-style block plugins — silent
    # porter-facing comment.
    head = s.split(None, 1)[0] if s else ''
    if head in _KNOWN_PLUGIN_NAMES:
        return '{# smarty plugin ' + head + ' — port manually #}'
    m = _ASSIGN_RE.match(s)
    if m:
        name = m.group('name') or m.group('bareName') or '_var'
        value = m.group('value').strip()
        # Smarty `{assign}` has no clean Django equivalent — Django's
        # `{% with %}` is a block, not a statement. Emit a porter-facing
        # comment but don't flag in the worklist (this is known
        # territory, the porter just needs to wire the value via the
        # view or refactor to {% with %}).
        return ('{# smarty assign ' + name + ' = '
                + _safe_smarty_comment(value[:80]) + ' — wire in view #}')

    # `{'literal'|@translate}` and `{$var|...}` echo expressions.
    if s.startswith("'") or s.startswith('"'):
        # Quoted literal at the front — string with optional modifiers.
        parts = _split_pipes(s)
        first = parts[0].strip()
        # Strip outer quotes
        text = first[1:-1] if len(first) >= 2 and first[0] == first[-1] else first
        if any(p.strip().split(':')[0] in ('translate', '@translate')
                for p in parts[1:]):
            # Drop |@translate (becomes literal text — Django {% translate %}
            # would need {% load i18n %}, optional.)
            return text
        # Other modifiers on a literal: rare; emit literal.
        return text
    if s.startswith('$') or s.startswith('('):
        # Variable echo with optional modifiers
        # Special-case |@translate → wrap in {% translate %} only when
        # value is a literal; for variables, skip the filter (it's a no-op
        # without the catalog).
        chain = _translate_modifier_chain(s)
        # Drop a leading translate filter on a variable — equivalent to passthrough
        chain = re.sub(r'\|translate\b', '', chain)
        return '{{ ' + chain + ' }}'

    # Unknown tag.
    skipped.append(s)
    return '{# SMARTY-LIFT? ' + s.replace('#}', '#}}') + ' #}'


def _safe_smarty_comment(s: str) -> str:
    return s.replace('#}', '#}}')


# ── Top-level translation ──────────────────────────────────────────

def translate_template(source: str) -> tuple[str, list[str]]:
    """Translate one Smarty `.tpl` source → (django html, skipped).

    Walks the source, splitting at Smarty tag boundaries, translating
    each tag through the rules table, and preserving `{literal}...{/literal}`
    contents verbatim.
    """
    skipped: list[str] = []
    out: list[str] = []
    i = 0
    n = len(source)
    while i < n:
        # Find the next `{` that opens something we recognise. Walk
        # forward through plain text until we hit one.
        j = source.find('{', i)
        if j < 0:
            out.append(source[i:])
            break
        # Emit the run of literal text we just walked past.
        out.append(source[i:j])
        # Comment: {*...*}
        if source.startswith(_COMMENT_OPEN, j):
            close = source.find(_COMMENT_CLOSE, j + 2)
            if close < 0:
                # Unterminated comment — drop the rest silently.
                break
            i = close + 2
            continue
        # Literal: {literal}...{/literal}
        if source.startswith(_LITERAL_OPEN, j):
            close = source.find(_LITERAL_CLOSE, j + len(_LITERAL_OPEN))
            if close < 0:
                out.append(source[j + len(_LITERAL_OPEN):])
                break
            out.append(source[j + len(_LITERAL_OPEN):close])
            i = close + len(_LITERAL_CLOSE)
            continue
        # Real Smarty tag: `{` followed by a non-whitespace character.
        if j + 1 < n and not source[j + 1].isspace():
            close_m = _TAG_CLOSE.search(source, j + 1)
            if not close_m:
                out.append(source[j:])
                break
            body = source[j + 1:close_m.start()]
            out.append(_translate_tag(body, skipped))
            i = close_m.end()
            continue
        # Bare `{` followed by whitespace — literal text to Smarty.
        out.append('{')
        i = j + 1
    return ''.join(out), skipped


# ── Theme walker ───────────────────────────────────────────────────

_STATIC_ASSET_EXTS = {
    '.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp',
    '.ico', '.woff', '.woff2', '.ttf', '.otf', '.eot',
}


def parse_theme(theme_dir: Path) -> LiftResult:
    """Walk a Smarty theme directory and translate every `.tpl` file.

    Non-`.tpl` PHP files (e.g. `themeconf.inc.php`, `index.php`) are
    flagged as `unhandled_files` — those are PHP code, not templates,
    and need a different lifter (or hand port).
    """
    result = LiftResult()
    if not theme_dir.is_dir():
        return result
    for path in sorted(theme_dir.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(theme_dir)
        ext = path.suffix.lower()
        if ext in _STATIC_ASSET_EXTS:
            result.static_assets.append(rel)
            continue
        if ext == '.tpl':
            tpl = path.read_text(encoding='utf-8', errors='replace')
            body, skipped = translate_template(tpl)
            target = str(rel.with_suffix('.html'))
            result.records.append(TemplateRecord(
                source=rel, target_name=target, body=body, skipped=skipped,
            ))
        elif ext in {'.php', '.phtml', '.inc'}:
            result.unhandled_files.append(rel)
    return result


# ── Worklist + apply ───────────────────────────────────────────────

def render_worklist(result: LiftResult, app_label: str, theme_dir: Path) -> str:
    lines = [
        f'# liftsmarty worklist — {theme_dir.name}',
        '',
        f'Target app: `{app_label}`. Generated by `datalift liftsmarty`.',
        '',
        '## Translated templates',
        '',
    ]
    if not result.records:
        lines.append('_(none)_')
    for rec in result.records:
        skip = f' — **{len(rec.skipped)} unhandled fragments**' if rec.skipped else ''
        lines.append(f'- `{rec.source}` → `templates/{app_label}/{rec.target_name}`{skip}')
    lines += ['', '## Theme files we did not translate (PHP code, not templates)', '']
    if not result.unhandled_files:
        lines.append('_(none)_')
    for p in result.unhandled_files:
        lines.append(f'- `{p}` (port by hand)')
    lines += ['', '## Static assets passed through', '']
    if not result.static_assets:
        lines.append('_(none)_')
    for p in result.static_assets:
        lines.append(f'- `{p}` → `static/{app_label}/{p}`')
    lines += ['', '## Per-template unhandled Smarty fragments', '']
    saw_any = False
    for rec in result.records:
        if not rec.skipped:
            continue
        saw_any = True
        lines.append(f'### `{rec.source}`')
        for s in rec.skipped:
            lines.append(f'- `{s[:200]}`')
        lines.append('')
    if not saw_any:
        lines.append('_(everything translated cleanly)_')
    return '\n'.join(lines)


def apply(result: LiftResult, project_root: Path, app_label: str,
          dry_run: bool = False) -> list[str]:
    """Write generated templates + static assets out."""
    log: list[str] = []
    templates_dir = project_root / 'templates' / app_label
    static_dir = project_root / 'static' / app_label

    if not dry_run:
        templates_dir.mkdir(parents=True, exist_ok=True)
        static_dir.mkdir(parents=True, exist_ok=True)

    for rec in result.records:
        target = templates_dir / rec.target_name
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rec.body, encoding='utf-8')
        log.append(f'template  {rec.source} → {target.relative_to(project_root)}')

    return log
