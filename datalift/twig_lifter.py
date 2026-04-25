"""Translate a Twig template tree into Django templates.

Twig (Symfony, Drupal 8+, Slim, Craft CMS, etc.) is the closest of
the major PHP template languages to Django's own template syntax —
many constructs already line up. The translator's job is mostly:

* Path remapping (``.html.twig`` → ``.html`` in includes/extends).
* Filter-argument syntax: ``|date('Y-m-d')`` → ``|date:'Y-m-d'``.
* The handful of constructs Twig has that Django doesn't (``{% set %}``,
  ``{% macro %}``, ``{% embed %}``, the ternary expression
  ``x ? 'a' : 'b'``).

Same deterministic discipline as liftwp / liftsmarty: pure Python,
no LLM, no network. The management command
:mod:`datalift.management.commands.liftwig` wraps this for the
file-writing side.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


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


# ── Tag regexes ────────────────────────────────────────────────────

_TAG_BLOCK = re.compile(r'\{%-?\s*(?P<body>.*?)\s*-?%\}', re.DOTALL)
_TAG_OUT   = re.compile(r'\{\{-?\s*(?P<body>.*?)\s*-?\}\}', re.DOTALL)

# Twig path-remap targets: any string literal in an include/extends/embed.
_TWIG_EXT_RE = re.compile(r"(['\"])([^'\"]+?)\.html\.twig\1")
_TWIG_EXT_BARE_RE = re.compile(r"(['\"])([^'\"]+?)\.twig\1")

# Filter call syntax — Twig: |name('arg', 'arg2')
# Django:                   |name:'arg'
# Two patterns: with parens / without.
_FILTER_PARENS_RE = re.compile(
    r"\|\s*(\w+)\s*\(\s*([^)]*?)\s*\)"
)


def _remap_template_paths(text: str) -> str:
    """Rewrite quoted Twig template paths to Django-style .html paths."""
    text = _TWIG_EXT_RE.sub(r'\1\2.html\1', text)
    text = _TWIG_EXT_BARE_RE.sub(r'\1\2.html\1', text)
    return text


def _convert_filter_args(text: str) -> str:
    """``|date('Y-m-d')`` → ``|date:'Y-m-d'``.

    Twig's parenthesised filter args become Django's colon-separated
    form. Multi-arg cases (``|replace({'a': 'b'})``) collapse to the
    first arg only — Django filters don't take dicts. Anything we
    can't safely convert, we leave in place; Django will throw
    `Invalid filter` and the porter sees exactly where.
    """
    def _swap(m: re.Match) -> str:
        name = m.group(1)
        arg = m.group(2).strip()
        if not arg:
            return f'|{name}'
        # If multiple positional args, take just the first.
        # Detect by top-level comma.
        depth = 0
        in_str: str | None = None
        first = arg
        for i, ch in enumerate(arg):
            if in_str:
                if ch == in_str:
                    in_str = None
                continue
            if ch in "'\"":
                in_str = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == ',' and depth == 0:
                first = arg[:i]
                break
        return f'|{name}:{first.strip()}'
    return _FILTER_PARENS_RE.sub(_swap, text)


# ── Block-tag transforms ───────────────────────────────────────────

def _translate_block_body(body: str, skipped: list[str]) -> str:
    """Translate the body of a `{% ... %}` block tag."""
    s = body.strip()
    if not s:
        return ''
    head = s.split(None, 1)[0]
    rest = s[len(head):].strip()

    # Direct passthroughs — Django has these tags with the same names.
    if head in ('if', 'elseif', 'else', 'endif',
                'for', 'endfor',
                'block', 'endblock',
                'extends', 'include', 'spaceless', 'endspaceless',
                'autoescape', 'endautoescape',
                'with', 'endwith', 'comment', 'endcomment',
                'verbatim', 'endverbatim'):
        if head == 'elseif':
            return '{% elif ' + _convert_expr(rest) + ' %}'
        if head == 'extends' or head == 'include':
            rest = _remap_template_paths(rest)
            return '{% ' + head + ' ' + _convert_expr(rest) + ' %}'
        if head == 'for':
            # Twig's ``for k, v in items`` and ``for v in items``
            # match Django's syntax exactly.
            return '{% for ' + _convert_expr(rest) + ' %}'
        if head == 'if':
            return '{% if ' + _convert_expr(rest) + ' %}'
        if head == 'block':
            # ``{% block name %}body{% endblock %}`` (Django shape) but Twig
            # also allows the inline form ``{% block name body %}``. We don't
            # convert the inline form; flag it.
            parts = rest.split(None, 1)
            if len(parts) > 1 and not rest.endswith(' '):
                # Inline form like `{% block title page_title|trans %}`.
                # We'll emit the block opener with just the name, and then
                # let the porter wire the body.
                skipped.append('inline {% block ' + rest + ' %}')
                return ('{% block ' + parts[0] + ' %}'
                        + '{# inline block body: '
                        + _safe_comment(parts[1][:60]) + ' #}')
            return '{% ' + head + ' ' + rest + ' %}'
        if head == 'with':
            return '{% with ' + _convert_expr(rest) + ' %}'
        return '{% ' + head + (' ' + rest if rest else '') + ' %}'

    # Twig-specific: `{% set x = y %}` (statement form) and
    # `{% set x %}body{% endset %}` (block form).
    if head == 'set':
        return '{# twig set ' + _safe_comment(rest[:80]) + ' — wire in view #}'
    if head == 'endset':
        return '{# /twig set #}'

    # Embedding: `{% embed 'X.html.twig' %}{% endembed %}` ≈ Django's
    # `{% include %}` with parameters.
    if head == 'embed':
        return ('{% include ' + _convert_expr(_remap_template_paths(rest)) + ' %}'
                '{# twig embed — block overrides need a porter #}')
    if head == 'endembed':
        return ''

    # Macros: Django has no exact equivalent; emit a porter marker.
    if head == 'macro':
        return '{# twig macro ' + _safe_comment(rest[:80]) + ' #}'
    if head == 'endmacro':
        return ''
    if head == 'import' or head == 'from':
        return '{# twig ' + head + ' ' + _safe_comment(rest[:80]) + ' #}'

    # `do` is the silent-side-effect tag.
    if head == 'do':
        return '{# twig do ' + _safe_comment(rest[:80]) + ' #}'

    # `flush`, `use`, `sandbox`, `verbatim` — silent or porter-comment.
    if head in ('flush', 'use', 'sandbox', 'endsandbox',
                'apply', 'endapply', 'cache', 'endcache',
                'trans_default_domain'):
        return '{# twig ' + head + (' ' + _safe_comment(rest[:60]) if rest else '') + ' #}'

    # Twig i18n block: {% trans %}sing{% plural %}plur{% endtrans %}
    # Maps to Django blocktranslate. Pluralisation logic is the porter's
    # job because the count expression (e.g. `count not_found|length`)
    # needs Django context.
    if head == 'trans':
        return '{% blocktranslate %}'
    if head == 'plural':
        return '{% plural %}'
    if head == 'endtrans':
        return '{% endblocktranslate %}'

    # Truly unknown.
    skipped.append(s)
    return '{# TWIG-LIFT? ' + _safe_comment(s) + ' #}'


def _convert_expr(expr: str) -> str:
    """Adjust a Twig expression to Django-template syntax.

    The two transforms that matter:

    * Filter arguments: ``|date('Y-m-d')`` → ``|date:'Y-m-d'``.
    * Path remap: any quoted ``.html.twig`` → ``.html``.

    Twig's ``not`` / ``and`` / ``or`` already match Django. Twig's
    function calls (``path('x')``, ``asset('x')``) are kept as-is —
    Django will fail to resolve them and the porter sees the trace.
    """
    expr = _remap_template_paths(expr)
    expr = _convert_filter_args(expr)
    return expr


def _convert_output_body(body: str, skipped: list[str]) -> str:
    """Translate the body of a `{{ ... }}` output expression."""
    inner = body.strip()
    if not inner:
        return ''
    inner = _convert_expr(inner)
    # Twig ternary `x ? 'a' : 'b'` — try to detect and translate when
    # both branches are string literals; otherwise pass through.
    m = _TERNARY_RE.match(inner)
    if m:
        cond, a, b = m.group('cond'), m.group('a'), m.group('b')
        return ('{% if ' + cond.strip() + ' %}'
                + a + '{% else %}' + b + '{% endif %}')
    # Twig `x ?? 'fallback'` (null-coalesce) → `x|default:'fallback'`
    m = _COALESCE_RE.match(inner)
    if m:
        return '{{ ' + m.group('lhs').strip() + '|default:' + m.group('rhs').strip() + ' }}'
    return '{{ ' + inner + ' }}'


_TERNARY_RE = re.compile(
    r"^(?P<cond>[^?]+?)\?\s*"
    r"(?P<a>'[^']*'|\"[^\"]*\")\s*:\s*"
    r"(?P<b>'[^']*'|\"[^\"]*\")\s*$"
)

_COALESCE_RE = re.compile(
    r"^(?P<lhs>.+?)\?\?(?P<rhs>.+)$"
)


def _safe_comment(s: str) -> str:
    return s.replace('#}', '#}}')


# ── Top-level translation ──────────────────────────────────────────

def translate_template(source: str) -> tuple[str, list[str]]:
    """Translate Twig source → (django html, skipped statements)."""
    skipped: list[str] = []
    out: list[str] = []
    i = 0
    n = len(source)
    while i < n:
        # Comment {# ... #} — already valid Django syntax, but Twig may
        # have multiline comments; pass through.
        if source.startswith('{#', i):
            close = source.find('#}', i + 2)
            if close < 0:
                out.append(source[i:])
                break
            out.append(source[i:close + 2])
            i = close + 2
            continue
        # Verbatim escape: Twig has `{% verbatim %}{% endverbatim %}`
        # which is also Django syntax; pass through (already handled
        # by the block tag matcher).
        m_block = _TAG_BLOCK.search(source, i)
        m_out   = _TAG_OUT.search(source, i)
        # Choose whichever comes first.
        candidates = [m for m in (m_block, m_out) if m]
        if not candidates:
            out.append(source[i:])
            break
        m_first = min(candidates, key=lambda mm: mm.start())
        out.append(source[i:m_first.start()])
        if m_first is m_block:
            out.append(_translate_block_body(m_first.group('body'), skipped))
        else:
            out.append(_convert_output_body(m_first.group('body'), skipped))
        i = m_first.end()
    return ''.join(out), skipped


# ── Theme walker ───────────────────────────────────────────────────

_STATIC_ASSET_EXTS = {
    '.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp',
    '.ico', '.woff', '.woff2', '.ttf', '.otf', '.eot',
}


def parse_theme(theme_dir: Path) -> LiftResult:
    """Walk a Twig template directory and translate every `.twig` file.

    Twig files canonically end ``.html.twig``, but ``.twig`` and
    ``.txt.twig`` / ``.xml.twig`` etc. all get translated; the
    output extension drops the trailing ``.twig`` and leaves the
    media-type extension in place.
    """
    result = LiftResult()
    if not theme_dir.is_dir():
        return result
    for path in sorted(theme_dir.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(theme_dir)
        ext = path.suffix.lower()
        # `.twig` only counts as a Twig template if the file *ends*
        # with .twig — we drop the trailing .twig in the output.
        if path.name.endswith('.twig'):
            tpl = path.read_text(encoding='utf-8', errors='replace')
            body, skipped = translate_template(tpl)
            target = str(rel)[:-len('.twig')]
            if not target.endswith(('.html', '.txt', '.xml', '.json')):
                target += '.html'
            result.records.append(TemplateRecord(
                source=rel, target_name=target, body=body, skipped=skipped,
            ))
        elif ext in _STATIC_ASSET_EXTS:
            result.static_assets.append(rel)
        elif ext in {'.php', '.phtml', '.inc'}:
            result.unhandled_files.append(rel)
    return result


# ── Worklist + apply ───────────────────────────────────────────────

def render_worklist(result: LiftResult, app_label: str, theme_dir: Path) -> str:
    lines = [
        f'# liftwig worklist — {theme_dir.name}',
        '',
        f'Target app: `{app_label}`. Generated by `datalift liftwig`.',
        '',
        '## Translated templates',
        '',
    ]
    if not result.records:
        lines.append('_(none)_')
    for rec in result.records:
        skip = f' — **{len(rec.skipped)} unhandled fragments**' if rec.skipped else ''
        lines.append(f'- `{rec.source}` → `templates/{app_label}/{rec.target_name}`{skip}')
    lines += ['', '## Theme files we did not translate', '']
    if not result.unhandled_files:
        lines.append('_(none)_')
    for p in result.unhandled_files:
        lines.append(f'- `{p}` (PHP code; port by hand)')
    lines += ['', '## Static assets passed through', '']
    if not result.static_assets:
        lines.append('_(none)_')
    for p in result.static_assets:
        lines.append(f'- `{p}` → `static/{app_label}/{p}`')
    lines += ['', '## Per-template unhandled Twig fragments', '']
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
