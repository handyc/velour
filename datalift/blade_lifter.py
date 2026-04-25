"""Translate a Laravel Blade template tree into Django templates.

Blade (Laravel's template engine, also widely used outside Laravel via
the standalone package) uses `@directive(...)` syntax instead of
`{% directive %}`. Echoes are `{{ $var }}` (escaped by default) and
`{!! $var !!}` (raw). The translator's main jobs:

* `@if($x)` / `@elseif($x)` / `@else` / `@endif` → Django `{% if %}` chain.
* `@foreach($items as $item)` / `@endforeach` → `{% for ... %}`.
* `@include('view.name')` → `{% include 'view/name.html' %}` (Laravel's
  dotted view names map to filesystem paths).
* `@extends('layout.app')` / `@yield('content')` /
  `@section('content')...@endsection` → Django `{% extends %}` /
  `{% block %}`.
* PHP variable refs: `$var` → `var`, `$obj->prop` → `obj.prop`,
  `$arr['key']` → `arr.key`.
* `{{ $var }}` → `{{ var }}`.
* `{!! $raw !!}` → `{{ raw|safe }}`.
* `{{-- comment --}}` → `{# comment #}`.
* `@csrf` → `{% csrf_token %}`.
* `@auth` / `@guest` → `{% if user.is_authenticated %}` / `{% if not %}`.
* `@php ... @endphp` → porter comment (Django has no inline-Python equiv).

Same deterministic discipline as the rest of the lifter family.
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


# ── PHP variable / expression translation ─────────────────────────

_PHP_VAR = re.compile(r'\$(?P<name>\w+)')


def _translate_var(name: str, rest: str) -> str:
    """Translate `$name` followed by `->prop` / `[index]` chains."""
    out = [name]
    i = 0
    n = len(rest)
    while i < n:
        if rest[i:i + 2] == '->':
            i += 2
            j = i
            while j < n and (rest[j].isalnum() or rest[j] == '_'):
                j += 1
            if j == i:
                break
            out.append('.' + rest[i:j])
            i = j
        elif rest[i] == '.':
            i += 1
            j = i
            while j < n and (rest[j].isalnum() or rest[j] == '_'):
                j += 1
            if j == i:
                break
            out.append('.' + rest[i:j])
            i = j
        elif rest[i] == '[':
            close = rest.find(']', i)
            if close < 0:
                break
            inner = rest[i + 1:close].strip()
            if (inner.startswith("'") and inner.endswith("'")) or \
               (inner.startswith('"') and inner.endswith('"')):
                out.append('.' + inner[1:-1])
            elif inner.isdigit():
                out.append('.' + inner)
            elif inner.startswith('$'):
                # Dynamic index — just use the var name verbatim.
                out.append('.' + inner[1:])
            else:
                out.append('.' + inner)
            i = close + 1
        else:
            break
    return ''.join(out), rest[i:]


def _translate_expr(expr: str) -> str:
    """Translate a Blade/PHP expression to Django-template form.

    Strips dollar-prefixes, converts `->` to `.`, converts `['key']`
    to `.key`. Leaves operators alone. Best-effort — Blade
    expressions can be arbitrary PHP, but the common shapes are
    simple property access.
    """
    # Replace `$word` with `word` keeping any chain.
    def _repl(m: re.Match) -> str:
        name = m.group('name')
        idx = m.end()
        suffix = expr[idx:]
        translated, _ = _translate_var(name, suffix)
        return translated + '\x00' + str(len(translated) - len(name))
    # Two-phase: substitute then strip the marker. Marker carries
    # the consumed-suffix length so we know how much to skip.
    out: list[str] = []
    i = 0
    n = len(expr)
    while i < n:
        m = _PHP_VAR.match(expr, i)
        if m:
            name = m.group('name')
            translated, leftover = _translate_var(name, expr[m.end():])
            out.append(translated)
            i = n - len(leftover)
        else:
            out.append(expr[i])
            i += 1
    s = ''.join(out)
    # `->` outside dollar-context — leave but warn? In practice the only
    # remaining `->` would be in arbitrary expressions, which we leave.
    s = s.replace('!==', '!=').replace('===', '==')
    s = s.replace('&&', ' and ').replace('||', ' or ')
    s = re.sub(r'\bnull\b', 'None', s)
    s = re.sub(r'\btrue\b', 'True', s)
    s = re.sub(r'\bfalse\b', 'False', s)
    return s.strip()


# ── Directive table ───────────────────────────────────────────────

# `@directive(args)` — capture the args. Allow optional whitespace
# between the name and the parens (Blade accepts `@foreach (...)`).
# `@directive` (no parens) for closers / no-arg ones.
_DIRECTIVE_RE = re.compile(
    r'@(?P<name>\w+)\s*(?P<paren>\((?P<args>(?:[^()]|\([^()]*\))*)\))?'
)

# Allowlist: only these directive names are interpreted as Blade.
# Anything else (CSS `@import`, `@media`, `@font-face`, `@page`, etc.,
# JavaScript `@function` / `@param` doc strings, PHP DocBlock `@var`)
# passes through verbatim.
_KNOWN_BLADE_DIRECTIVES = {
    # Control flow
    'if', 'elseif', 'else', 'endif',
    'unless', 'endunless',
    'isset', 'endisset',
    'empty', 'endempty',
    'foreach', 'endforeach',
    'forelse', 'endforelse',
    'for', 'endfor',
    'while', 'endwhile',
    'switch', 'case', 'default', 'break', 'endswitch',
    'continue',
    # Auth / authz
    'auth', 'endauth', 'guest', 'endguest',
    'can', 'endcan', 'cannot', 'endcannot',
    'canany', 'endcanany',
    # Templates
    'extends', 'include', 'includeIf', 'includeWhen', 'includeFirst',
    'yield', 'section', 'endsection', 'show', 'parent',
    'stack', 'push', 'endpush', 'prepend', 'endprepend',
    'component', 'endcomponent', 'slot', 'endslot',
    # Forms
    'csrf', 'method',
    'error', 'enderror',
    'old',
    # Inline PHP
    'php', 'endphp',
    # i18n
    'lang', 'choice',
    # Misc
    'verbatim', 'endverbatim',
    'once', 'endonce',
    'production', 'endproduction',
    'env', 'endenv',
    'json',
    'dd', 'dump',
    'class',
    'props',
}


def _translate_directive(name: str, args: str | None,
                          skipped: list[str]) -> str:
    """Translate a single Blade directive to Django."""
    args = (args or '').strip()
    expr = _translate_expr(args) if args else ''

    # Control flow
    if name == 'if':       return '{% if ' + expr + ' %}'
    if name == 'elseif':   return '{% elif ' + expr + ' %}'
    if name == 'else':     return '{% else %}'
    if name == 'endif':    return '{% endif %}'
    if name == 'unless':   return '{% if not (' + expr + ') %}'
    if name == 'endunless':return '{% endif %}'
    if name == 'isset':    return '{% if ' + expr + ' %}'
    if name == 'endisset': return '{% endif %}'
    if name == 'empty':    return '{% if not (' + expr + ') %}'
    if name == 'endempty': return '{% endif %}'

    if name == 'foreach':
        # `$items as $item` or `$items as $key => $val`
        m = re.match(
            r'^(?P<src>.+?)\s+as\s+(?:(?P<key>\w+)\s*=>\s*)?(?P<item>\w+)\s*$',
            expr,
        )
        if m:
            src, key, item = m.group('src').strip(), m.group('key'), m.group('item')
            if key:
                return ('{% for ' + key + ', ' + item
                        + ' in ' + src + '.items %}')
            return '{% for ' + item + ' in ' + src + ' %}'
        skipped.append(f'@foreach({args})')
        return '{# BLADE-LIFT? @foreach(' + _safe_comment(args) + ') #}'
    if name == 'endforeach': return '{% endfor %}'
    if name == 'forelse':    return '{% for ' + expr + ' %}'  # rare; same shape
    if name == 'empty' or name == 'forelseempty': return '{% empty %}'
    if name == 'endforelse': return '{% endfor %}'

    if name == 'for':
        # @for($i = 0; $i < count($x); $i++) — no clean Django.
        return '{# blade @for(' + _safe_comment(args[:60]) + ') — port to {% for %} or view #}'
    if name == 'endfor':     return '{# /@for #}'
    if name == 'while':      return '{# blade @while(' + _safe_comment(args[:60]) + ') #}'
    if name == 'endwhile':   return '{# /@while #}'

    if name == 'switch':
        return '{# blade @switch(' + _safe_comment(args) + ') #}'
    if name == 'case':       return '{# @case(' + _safe_comment(args) + ') — port to {% if %} #}'
    if name == 'default':    return '{# @default — port to {% else %} #}'
    if name == 'break':      return ''  # implicit in Django for/if
    if name == 'endswitch':  return '{# /@switch #}'

    # Auth helpers
    if name == 'auth':       return '{% if user.is_authenticated %}'
    if name == 'endauth':    return '{% endif %}'
    if name == 'guest':      return '{% if not user.is_authenticated %}'
    if name == 'endguest':   return '{% endif %}'
    if name == 'can':        return '{# blade @can(' + _safe_comment(args) + ') — wire perms in view #}'
    if name == 'endcan':     return '{# /@can #}'
    if name == 'cannot':     return '{# blade @cannot(' + _safe_comment(args) + ') #}'
    if name == 'endcannot':  return '{# /@cannot #}'

    # Templates / inheritance
    if name == 'include':
        return _translate_include(args)
    if name == 'extends':
        return _translate_extends(args)
    if name == 'yield':
        return _translate_yield(args)
    if name == 'section':
        return _translate_section_open(args)
    if name == 'endsection':
        return '{% endblock %}'
    if name == 'show':
        # @show — like @endsection but also yields; treat same.
        return '{% endblock %}'
    if name == 'parent':
        return '{{ block.super }}'
    if name == 'stack':
        return _translate_yield(args)  # @stack('name') ≈ @yield
    if name == 'push':
        return _translate_section_open(args)
    if name == 'endpush':
        return '{% endblock %}'

    # Form / CSRF
    if name == 'csrf':       return '{% csrf_token %}'
    if name == 'method':
        # @method('PUT') → an HTML hidden input. Django doesn't have
        # this concept (PUT is hand-rolled).
        return '{# blade @method(' + _safe_comment(args) + ') — Django uses POST + override or form attr #}'
    if name == 'error':
        return '{% if form.errors %}'
    if name == 'enderror':
        return '{% endif %}'

    # Inline PHP
    if name == 'php':
        return '{# blade @php — port to view; following body is raw PHP #}'
    if name == 'endphp':
        return '{# /@php #}'

    # i18n — `@lang('strings.yes')` → the string literal (no
    # catalog at template-time without {% load i18n %} setup).
    if name == 'lang':
        m = re.match(r"^\s*(['\"])([^'\"]+)\1", args)
        if m:
            return m.group(2)
        return '{# blade @lang(' + _safe_comment(args) + ') #}'
    if name == 'choice':
        return '{# blade @choice(' + _safe_comment(args[:60]) + ') — pluralisation #}'

    # Component / slot — emit a marker; needs Django custom-tag work.
    if name in ('component', 'endcomponent', 'slot', 'endslot',
                 'props', 'class'):
        return ('{# blade @' + name
                + (' ' + _safe_comment(args[:60]) if args else '')
                + ' — port via custom template tag #}')

    # Other includes
    if name in ('includeIf', 'includeWhen', 'includeFirst'):
        return _translate_include(args)

    # JSON encoder
    if name == 'json':
        return '{{ ' + _translate_expr(args) + '|json_script:"data" }}'

    # @old('field') — Laravel form-helper; pass through marker
    if name == 'old':
        return '{# blade @old(' + _safe_comment(args) + ') — Django form needs `value=` from form.field.value #}'

    # Continue / break in loops
    if name == 'continue':
        return '{# blade @continue — Django for-loop has no continue; restructure with {% if %} #}'

    # Push / stack — block-content collection (Django closest: blocks)
    if name == 'push':
        return _translate_section_open(args)
    if name == 'endpush':
        return '{% endblock %}'
    if name == 'prepend':
        return _translate_section_open(args)
    if name == 'endprepend':
        return '{% endblock %}'

    # No-ops / passthrough
    if name in ('verbatim', 'endverbatim'):
        return '{% ' + name + ' %}'  # Django has these too

    if name in ('once', 'endonce', 'production', 'endproduction',
                 'env', 'endenv', 'unless'):
        return '{# blade @' + name + (' ' + _safe_comment(args[:60]) if args else '') + ' #}'

    # Truly unknown.
    skipped.append('@' + name + ('(' + args + ')' if args else ''))
    return ('{# BLADE-LIFT? @' + name
            + ('(' + _safe_comment(args) + ')' if args else '') + ' #}')


def _translate_include(args: str) -> str:
    """`@include('layouts.app')` → `{% include 'layouts/app.html' %}`."""
    m = re.match(r"^\s*(['\"])([^'\"]+)\1", args.strip())
    if not m:
        return '{# blade @include(' + _safe_comment(args) + ') #}'
    name = m.group(2)
    path = name.replace('.', '/') + '.html'
    return "{% include '" + path + "' %}"


def _translate_extends(args: str) -> str:
    m = re.match(r"^\s*(['\"])([^'\"]+)\1", args.strip())
    if not m:
        return '{# blade @extends(' + _safe_comment(args) + ') #}'
    path = m.group(2).replace('.', '/') + '.html'
    return "{% extends '" + path + "' %}"


def _translate_yield(args: str) -> str:
    """`@yield('content')` → `{% block content %}{% endblock %}`.

    `@yield('content', 'default')` → `{% block content %}default{% endblock %}`.
    """
    m = re.match(r"^\s*(['\"])([^'\"]+)\1\s*(?:,\s*(?P<def>.+))?$", args.strip())
    if not m:
        return '{# blade @yield(' + _safe_comment(args) + ') #}'
    name = m.group(2)
    default = m.group('def')
    if default:
        # Default may be a quoted string or an expression.
        d = default.strip()
        if (d.startswith("'") and d.endswith("'")) or (d.startswith('"') and d.endswith('"')):
            return '{% block ' + name + ' %}' + d[1:-1] + '{% endblock %}'
        return ('{% block ' + name + ' %}{{ ' + _translate_expr(d)
                + ' }}{% endblock %}')
    return '{% block ' + name + ' %}{% endblock %}'


def _translate_section_open(args: str) -> str:
    """`@section('content')` → `{% block content %}` (without close;
    the corresponding `@endsection` provides it).

    `@section('title', 'Page title')` (the inline form) →
    `{% block title %}Page title{% endblock %}`.
    """
    m = re.match(r"^\s*(['\"])([^'\"]+)\1\s*(?:,\s*(?P<inline>.+))?$",
                 args.strip())
    if not m:
        return '{# blade @section(' + _safe_comment(args) + ') #}'
    name = m.group(2)
    inline = m.group('inline')
    if inline:
        s = inline.strip()
        if (s.startswith("'") and s.endswith("'")) or \
           (s.startswith('"') and s.endswith('"')):
            return '{% block ' + name + ' %}' + s[1:-1] + '{% endblock %}'
        return ('{% block ' + name + ' %}{{ ' + _translate_expr(s)
                + ' }}{% endblock %}')
    return '{% block ' + name + ' %}'


def _safe_comment(s: str) -> str:
    return s.replace('#}', '#}}')


# ── Echo / comment translation ────────────────────────────────────

def _translate_blade(source: str) -> tuple[str, list[str]]:
    """Walk the source: handle `{{-- comment --}}`, `@directive(args)`,
    `{{ expr }}` (escaped), `{!! expr !!}` (raw), and the
    `@{{ literal }}` escape.
    """
    skipped: list[str] = []
    out: list[str] = []
    i = 0
    n = len(source)
    while i < n:
        # Blade comment {{-- ... --}}
        if source.startswith('{{--', i):
            close = source.find('--}}', i + 4)
            if close < 0:
                break
            inner = source[i + 4:close].strip()
            out.append('{# ' + _safe_comment(inner) + ' #}')
            i = close + 4
            continue
        # Escaped output {{ ... }}
        if source.startswith('{{', i) and not source.startswith('{{{', i):
            # Check for the `@{{ literal }}` escape: a `@` immediately
            # before `{{` means the engine should not interpret it.
            if i > 0 and source[i - 1] == '@':
                # The `@` itself was already emitted; emit the {{ ... }}
                # literally (Blade renders `@{{ x }}` as `{{ x }}`). Replace
                # the trailing `@` we already wrote with nothing, then write
                # the literal.
                if out and out[-1].endswith('@'):
                    out[-1] = out[-1][:-1]
                close = source.find('}}', i + 2)
                if close < 0:
                    break
                # Wrap the literal so Django doesn't try to interpret it.
                out.append('{% verbatim %}'
                           + source[i:close + 2]
                           + '{% endverbatim %}')
                i = close + 2
                continue
            close = source.find('}}', i + 2)
            if close < 0:
                break
            inner = source[i + 2:close].strip()
            out.append('{{ ' + _translate_expr(inner) + ' }}')
            i = close + 2
            continue
        # Raw output {!! ... !!}
        if source.startswith('{!!', i):
            close = source.find('!!}', i + 3)
            if close < 0:
                break
            inner = source[i + 3:close].strip()
            out.append('{{ ' + _translate_expr(inner) + '|safe }}')
            i = close + 3
            continue
        # Directive @name(args) or @name. Blade only interprets known
        # directive names; `@media`, `@import`, `@var` etc. are kept
        # literal so CSS / JS / DocBlock contents pass through.
        if source[i] == '@':
            # `@@name` is the literal-`@name` escape.
            if i + 1 < n and source[i + 1] == '@':
                out.append('@')
                i += 2
                continue
            m = _DIRECTIVE_RE.match(source, i)
            if m and m.group('name') in _KNOWN_BLADE_DIRECTIVES:
                name = m.group('name')
                args = m.group('args')
                out.append(_translate_directive(name, args, skipped))
                i = m.end()
                continue
        out.append(source[i])
        i += 1
    return ''.join(out), skipped


# ── Public translate_template ─────────────────────────────────────

def translate_template(source: str) -> tuple[str, list[str]]:
    """Translate Blade source → (django html, skipped fragments)."""
    return _translate_blade(source)


# ── Theme walker ───────────────────────────────────────────────────

_STATIC_ASSET_EXTS = {
    '.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp',
    '.ico', '.woff', '.woff2', '.ttf', '.otf', '.eot',
}


def parse_theme(theme_dir: Path) -> LiftResult:
    """Walk a Blade view directory and translate every `.blade.php` file."""
    result = LiftResult()
    if not theme_dir.is_dir():
        return result
    for path in sorted(theme_dir.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(theme_dir)
        ext = path.suffix.lower()
        if path.name.endswith('.blade.php'):
            tpl = path.read_text(encoding='utf-8', errors='replace')
            body, skipped = translate_template(tpl)
            target = str(rel)[:-len('.blade.php')] + '.html'
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
        f'# liftblade worklist — {theme_dir.name}',
        '',
        f'Target app: `{app_label}`. Generated by `datalift liftblade`.',
        '',
        '## Translated templates',
        '',
    ]
    if not result.records:
        lines.append('_(none)_')
    for rec in result.records:
        skip = f' — **{len(rec.skipped)} unhandled fragments**' if rec.skipped else ''
        lines.append(f'- `{rec.source}` → `templates/{app_label}/{rec.target_name}`{skip}')
    lines += ['', '## Other PHP files (not Blade views)', '']
    if not result.unhandled_files:
        lines.append('_(none)_')
    for p in result.unhandled_files:
        lines.append(f'- `{p}` (port by hand)')
    lines += ['', '## Static assets passed through', '']
    if not result.static_assets:
        lines.append('_(none)_')
    for p in result.static_assets:
        lines.append(f'- `{p}` → `static/{app_label}/{p}`')
    lines += ['', '## Per-template unhandled Blade fragments', '']
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
