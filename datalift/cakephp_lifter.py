"""Translate a CakePHP application's routes + controllers into Django.

CakePHP 4 / 5 routes live in `config/routes.php` and use a closure
that receives a `RouteBuilder`:

    return function (RouteBuilder $routes): void {
        $routes->scope('/', function (RouteBuilder $builder): void {
            $builder->connect('/', ['controller' => 'Pages',
                                     'action' => 'display', 'home']);
            $builder->connect('/pages/*', 'Pages::display');
            $builder->connect('/articles/{id}',
                ['controller' => 'Articles', 'action' => 'view']);
            $builder->fallbacks();
        });
        $routes->scope('/api', function (RouteBuilder $builder): void {
            $builder->resources('Articles');
        });
        $routes->prefix('Admin', function (RouteBuilder $builder): void {
            $builder->connect('/dashboard',
                ['controller' => 'Dashboard', 'action' => 'index']);
        });
    };

Controllers live in `src/Controller/*Controller.php` and extend
`AppController`. Every public method is an action, dispatched at
`/<controller>/<action>/<args>` by default.

Pure Python, no LLM, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Records ────────────────────────────────────────────────────────

@dataclass
class CakeRoute:
    http_method: str        # 'GET' / 'POST' / ... or 'ANY'
    path: str               # Django path, e.g. 'articles/<int:id>/'
    controller: str         # bare controller class name (no Controller suffix)
    action: str             # PHP action method name


@dataclass
class CakeAction:
    name: str
    args: list[str]
    body: str
    raw_body: str


@dataclass
class CakeController:
    source: Path
    class_name: str         # e.g. 'ArticlesController'
    qualified_name: str     # e.g. 'Admin_ArticlesController' (with prefix)
    actions: list[CakeAction] = field(default_factory=list)


@dataclass
class CakeLiftResult:
    routes: list[CakeRoute] = field(default_factory=list)
    controllers: list[CakeController] = field(default_factory=list)
    fallbacks_used: bool = False
    skipped_files: list[Path] = field(default_factory=list)


# ── PHP utilities ─────────────────────────────────────────────────

def _strip_php_comments(src: str) -> str:
    """String-aware PHP comment stripper. Delegates to shared helper."""
    from datalift._php import strip_php_comments
    return strip_php_comments(src)


def _php_str(s: str) -> str | None:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return None


def _balanced_block(src: str, open_idx: int) -> tuple[int, int] | None:
    depth = 0
    in_str: str | None = None
    i = open_idx
    while i < len(src):
        ch = src[i]
        if in_str:
            if ch == '\\':
                i += 2; continue
            if ch == in_str:
                in_str = None
            i += 1; continue
        if ch in ('"', "'"):
            in_str = ch; i += 1; continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return open_idx + 1, i
        i += 1
    return None


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
            parts.append(''.join(buf).strip()); buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append(''.join(buf).strip())
    return parts


# ── URL placeholder conversion ────────────────────────────────────

_PARAM_RE = re.compile(r'\{(\w+)\}')


def _convert_path(cake_path: str, regex_hints: dict[str, str] | None = None
                  ) -> tuple[str, list[str]]:
    """`/articles/{id}` → `articles/<int:id>/` (using regex hint)."""
    p = cake_path.strip().lstrip('/').rstrip('/')
    args: list[str] = []
    hints = regex_hints or {}

    def _sub(m: re.Match[str]) -> str:
        name = m.group(1)
        args.append(name)
        hint = hints.get(name, '')
        if hint and re.match(r'\\d', hint):
            return f'<int:{name}>'
        if hint and re.match(r'[a-zA-Z]', hint):
            return f'<slug:{name}>'
        # Common Cake convention: `id` is numeric.
        if name == 'id':
            return f'<int:{name}>'
        return f'<str:{name}>'

    out = _PARAM_RE.sub(_sub, p)
    # CakePHP `*` matches any trailing path segments (greedy).
    out = out.replace('*', '<path:tail>')
    if 'tail' in out and 'tail' not in args:
        args.append('tail')
    if out and not out.endswith('/'):
        out += '/'
    return out, args


# ── Action body translation ───────────────────────────────────────

_BODY_RULES: list[tuple[re.Pattern[str], str]] = [
    # render — `$this->render('path/to/template')` (positional)
    (re.compile(r"\$this->render\(\s*'([^']+)'\s*\)"),
     r"return render(request, '\1.html')"),
    (re.compile(r"\$this->render\(\s*'([^']+)'\s*,\s*\$([a-zA-Z_]\w*)\s*\)"),
     r"return render(request, '\1.html', \2)"),

    # set / compact — `$this->set(compact('articles'))` is "pass var to view"
    (re.compile(r"\$this->set\(\s*compact\(\s*'([^']+)'\s*\)\s*\);?"),
     r"# PORTER: $this->set(compact('\1')) — pass to render() context dict"),
    (re.compile(r"\$this->set\(\s*'([^']+)'\s*,\s*\$([^)]+)\)\s*;?"),
     r"# PORTER: $this->set('\1', \2) — pass to render() context dict"),

    # Redirects — same pattern as liftcodeigniter (consume any 'return ').
    (re.compile(r"(?:return\s+)?\$this->redirect\(\s*'([^']+)'\s*\)"),
     r"return redirect('\1')"),
    (re.compile(r"(?:return\s+)?\$this->redirect\(\s*\[\s*'controller'\s*=>\s*"
                r"'([^']+)'\s*,\s*'action'\s*=>\s*'([^']+)'\s*\]\s*\)"),
     r"return redirect('\1_\2')"),

    # Request data
    (re.compile(r"\$this->request->getData\(\s*'([^']+)'\s*\)"),
     r"request.POST.get('\1')"),
    (re.compile(r"\$this->request->getData\(\s*\)"),
     r"request.POST"),
    (re.compile(r"\$this->request->getQuery\(\s*'([^']+)'\s*\)"),
     r"request.GET.get('\1')"),
    (re.compile(r"\$this->request->getParam\(\s*'([^']+)'\s*\)"),
     r"kwargs.get('\1')"),

    # Session
    (re.compile(r"\$this->getRequest\(\)->getSession\(\)->read\(\s*'([^']+)'\s*\)"),
     r"request.session.get('\1')"),
    (re.compile(r"\$this->getRequest\(\)->getSession\(\)->write\(\s*'([^']+)'\s*,\s*([^)]+)\)"),
     r"request.session['\1'] = \2"),

    # Tables: $this->Articles->find('all') → porter marker
    (re.compile(r"\$this->([A-Z]\w*)->find\(\s*'all'\s*\)"),
     r"# PORTER: $this->\1->find('all') → \1.objects.all()"),
    (re.compile(r"\$this->([A-Z]\w*)->get\(\s*\$([a-zA-Z_]\w*)\s*\)"),
     r"# PORTER: $this->\1->get(\2) → \1.objects.get(pk=\2)"),
    (re.compile(r"\$this->([A-Z]\w*)->newEmptyEntity\(\s*\)"),
     r"# PORTER: $this->\1->newEmptyEntity() → \1()"),
    (re.compile(r"\$this->([A-Z]\w*)->save\(\s*\$([a-zA-Z_]\w*)\s*\)"),
     r"# PORTER: $this->\1->save(\2) → \2.save()"),
    (re.compile(r"\$this->([A-Z]\w*)->delete\(\s*\$([a-zA-Z_]\w*)\s*\)"),
     r"# PORTER: $this->\1->delete(\2) → \2.delete()"),

    # Flash messages
    (re.compile(r"\$this->Flash->success\(\s*([^)]+)\)\s*;?"),
     r"# PORTER: $this->Flash->success(\1) → messages.success(request, \1)"),
    (re.compile(r"\$this->Flash->error\(\s*([^)]+)\)\s*;?"),
     r"# PORTER: $this->Flash->error(\1) → messages.error(request, \1)"),

    # Exceptions
    (re.compile(r"throw\s+new\s+NotFoundException\(\s*\)\s*;?"),
     r"raise Http404"),
    (re.compile(r"throw\s+new\s+ForbiddenException\(\s*\)\s*;?"),
     r"raise PermissionDenied"),

    # `$var = ` cleanup
    (re.compile(r"\$([a-zA-Z_]\w*)"), r"\1"),
]


def _translate_body(php_body: str) -> str:
    """Two-stage: CakePHP-specific rules first (`$this->render`,
    `$this->redirect`, `$this->Articles->find`...), then delegate to
    `php_code_lifter._translate_block` for control flow + array
    literals + casts + everything else generic. Without stage 2 the
    output had untranslated `$this->`, `array(...)`, `::`, PHP
    `if (...)` braces, etc. — Python-shaped but not Python-correct."""
    body = php_body
    for pat, repl in _BODY_RULES:
        body = pat.sub(repl, body)
    from datalift.php_code_lifter import _translate_block
    return _translate_block(body, indent=0)


# ── Controller parsing ────────────────────────────────────────────

_NAMESPACE_RE = re.compile(r'^\s*namespace\s+([\w\\]+)\s*;', re.MULTILINE)
_CLASS_RE = re.compile(
    r'(?m)^\s*(?:abstract\s+|final\s+)?class\s+(?P<name>\w+)'
    r'(?:\s+extends\s+(?P<parent>[\w\\]+))?'
)
_METHOD_RE = re.compile(
    r'(?m)^\s*public\s+function\s+(?P<name>\w+)\s*\((?P<args>[^)]*)\)'
    r'(?:\s*:\s*\??[\w\\|]+)?\s*\{'
)
_PHP_PARAM_RE = re.compile(
    r'(?:\??[\w\\.]+\s+)?\$(?P<name>\w+)(?:\s*=\s*[^,]+)?'
)


def parse_controller(php: str, source: Path | None = None,
                     prefix: str = '') -> CakeController | None:
    src = _strip_php_comments(php)
    cm = _CLASS_RE.search(src)
    if not cm:
        return None
    parent = cm.group('parent') or ''
    name = cm.group('name')
    if not name.endswith('Controller'):
        return None
    if parent and 'Controller' not in parent:
        return None
    qualified = f'{prefix}_{name}' if prefix else name
    rec = CakeController(
        source=source or Path('Controller.php'),
        class_name=name,
        qualified_name=qualified,
    )
    body_open = src.find('{', cm.end())
    if body_open < 0:
        return rec
    span = _balanced_block(src, body_open)
    if span is None:
        return rec
    body = src[span[0]:span[1]]
    for mm in _METHOD_RE.finditer(body):
        action_name = mm.group('name')
        if action_name in ('initialize', 'beforeFilter', 'beforeRender',
                           'afterFilter', 'beforeRedirect'):
            continue
        if action_name.startswith('_'):
            continue
        body_open_i = mm.end() - 1
        body_span = _balanced_block(body, body_open_i)
        if body_span is None:
            continue
        php_body = body[body_span[0]:body_span[1]]
        translated = _translate_body(php_body)
        args = [pm.group('name') for pm in _PHP_PARAM_RE.finditer(mm.group('args').strip())]
        rec.actions.append(CakeAction(
            name=action_name, args=args, body=translated, raw_body=php_body,
        ))
    return rec


# ── Routes parsing ────────────────────────────────────────────────

# `$builder->connect('/path', ...)` or `$routes->connect(...)`
_CONNECT_RE = re.compile(
    r"\$\w+->connect\(\s*"
    r"(?P<args>(?:[^()]|\([^()]*\))*?)"
    r"\)\s*;",
    re.DOTALL,
)
_RESOURCES_RE = re.compile(
    r"\$\w+->resources\(\s*'(?P<name>\w+)'\s*"
    r"(?:,\s*\[[^\]]*\])?"
    r"\s*\)\s*;",
    re.DOTALL,
)
_FALLBACKS_RE = re.compile(r"\$\w+->fallbacks\(\s*\)\s*;")
_SCOPE_RE = re.compile(
    r"\$\w+->scope\(\s*"
    r"'(?P<scope>[^']*)'\s*,"
    r"\s*function\s*\([^)]*\)(?:\s*:\s*[\w\\|]+)?\s*\{"
)
_PREFIX_RE = re.compile(
    r"\$\w+->prefix\(\s*"
    r"'(?P<prefix>[^']+)'\s*,"
    r"\s*function\s*\([^)]*\)(?:\s*:\s*[\w\\|]+)?\s*\{"
)


def parse_routes(php: str) -> tuple[list[CakeRoute], bool]:
    """Parse a CakePHP `routes.php` file. Returns (routes,
    fallbacks_used)."""
    src = _strip_php_comments(php)
    routes: list[CakeRoute] = []
    fallbacks_used = [False]
    _parse_block(src, '', '', routes, fallbacks_used)
    return routes, fallbacks_used[0]


def _parse_block(src: str, scope: str, prefix: str,
                 out: list[CakeRoute], fb: list[bool]) -> None:
    i = 0
    while i < len(src):
        sm = _SCOPE_RE.search(src, i)
        pm = _PREFIX_RE.search(src, i)
        cm = _CONNECT_RE.search(src, i)
        rm = _RESOURCES_RE.search(src, i)
        fm = _FALLBACKS_RE.search(src, i)
        candidates = [(m.start(), m, kind) for m, kind in
                      ((sm, 'scope'), (pm, 'prefix'),
                       (cm, 'connect'), (rm, 'resource'),
                       (fm, 'fallback'))
                      if m is not None]
        if not candidates:
            break
        candidates.sort(key=lambda t: t[0])
        _, m, kind = candidates[0]

        if kind == 'scope':
            new_scope = (scope.rstrip('/') + '/' + m.group('scope').strip('/')
                         if scope else m.group('scope').strip('/'))
            new_scope = new_scope.strip('/')
            body_open = m.end() - 1
            span = _balanced_block(src, body_open)
            if span is None:
                i = m.end(); continue
            _parse_block(src[span[0]:span[1]], new_scope, prefix, out, fb)
            i = span[1] + 1; continue

        if kind == 'prefix':
            new_prefix = m.group('prefix')
            body_open = m.end() - 1
            span = _balanced_block(src, body_open)
            if span is None:
                i = m.end(); continue
            _parse_block(src[span[0]:span[1]], scope, new_prefix, out, fb)
            i = span[1] + 1; continue

        if kind == 'connect':
            args = _split_args(m.group('args'))
            if not args:
                i = m.end(); continue
            raw_path = _php_str(args[0]) or ''
            full_path = (scope.rstrip('/') + '/' + raw_path.lstrip('/')
                         if scope else raw_path).strip('/')
            controller = ''
            action = ''
            if len(args) >= 2:
                target = args[1]
                tstr = _php_str(target)
                if tstr and '::' in tstr:
                    controller, _, action = tstr.partition('::')
                elif target.startswith('['):
                    # array form: ['controller' => 'X', 'action' => 'y']
                    cm2 = re.search(r"'controller'\s*=>\s*'([^']+)'", target)
                    am2 = re.search(r"'action'\s*=>\s*'([^']+)'", target)
                    if cm2:
                        controller = cm2.group(1)
                    if am2:
                        action = am2.group(1)
            # regex hints in 3rd arg: ['id' => '\d+']
            hints: dict[str, str] = {}
            if len(args) >= 3 and args[2].startswith('['):
                for hm in re.finditer(r"'(\w+)'\s*=>\s*'([^']+)'", args[2]):
                    hints[hm.group(1)] = hm.group(2)
            path_, _ = _convert_path(full_path, hints)
            if controller:
                qual = (f'{prefix}_{controller}Controller'
                        if prefix else f'{controller}Controller')
                out.append(CakeRoute(
                    http_method='ANY', path=path_,
                    controller=qual, action=action or 'index',
                ))
            i = m.end(); continue

        if kind == 'resource':
            name = m.group('name')
            base = (scope.rstrip('/') + '/' + name.lower()
                    if scope else name.lower()).strip('/')
            qual = (f'{prefix}_{name}Controller'
                    if prefix else f'{name}Controller')
            rest = [
                ('GET',    base,                'index'),
                ('GET',    base + '/add',       'add'),
                ('POST',   base,                'add'),
                ('GET',    base + '/{id}',      'view'),
                ('GET',    base + '/{id}/edit', 'edit'),
                ('PUT',    base + '/{id}',      'edit'),
                ('DELETE', base + '/{id}',      'delete'),
            ]
            for verb, raw_path, act in rest:
                path_, _ = _convert_path(raw_path)
                out.append(CakeRoute(
                    http_method=verb, path=path_,
                    controller=qual, action=act,
                ))
            i = m.end(); continue

        if kind == 'fallback':
            fb[0] = True
            i = m.end(); continue


# ── Walker ────────────────────────────────────────────────────────

def parse_cakephp(app_dir: Path) -> CakeLiftResult:
    result = CakeLiftResult()
    if not app_dir.is_dir():
        return result
    routes_file = app_dir / 'config' / 'routes.php'
    if routes_file.is_file():
        text = _safe_read(routes_file)
        rs, fb = parse_routes(text)
        result.routes.extend(rs)
        result.fallbacks_used = fb
    ctl_dir = app_dir / 'src' / 'Controller'
    if ctl_dir.is_dir():
        # Top-level controllers
        for php_file in sorted(ctl_dir.glob('*.php')):
            _maybe_add_controller(result, php_file, app_dir, prefix='')
        # Prefixed controllers (e.g. `src/Controller/Admin/...`)
        for sub in sorted(p for p in ctl_dir.iterdir() if p.is_dir()):
            prefix_name = sub.name
            for php_file in sorted(sub.rglob('*.php')):
                _maybe_add_controller(result, php_file, app_dir,
                                      prefix=prefix_name)
    return result


def _maybe_add_controller(result: CakeLiftResult, php_file: Path,
                          app_dir: Path, prefix: str) -> None:
    text = _safe_read(php_file)
    if not text.strip():
        result.skipped_files.append(php_file.relative_to(app_dir))
        return
    ctl = parse_controller(text, source=php_file.relative_to(app_dir),
                            prefix=prefix)
    if ctl is None:
        return
    if ctl.class_name in ('AppController', 'ErrorController'):
        # Base classes — not URL-routed. Skip silently.
        return
    if ctl.actions:
        result.controllers.append(ctl)


def _safe_read(p: Path) -> str:
    try:
        return p.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


# ── Renderers ─────────────────────────────────────────────────────

def render_urls(result: CakeLiftResult, app_label: str) -> str:
    out = [
        '"""Auto-generated by datalift liftcakephp.',
        '',
        'CakePHP routes translated into Django URL patterns.',
        '"""',
        'from django.urls import path',
        'from . import views_cakephp as views',
        '',
        '',
    ]
    by_path: dict[str, list[CakeRoute]] = {}
    for r in result.routes:
        by_path.setdefault(r.path, []).append(r)
    out.append('urlpatterns = [')
    for path_, rs in by_path.items():
        if len(rs) == 1:
            r = rs[0]
            out.append(f"    path('{path_}', "
                       f"views.{r.controller}_{r.action}),")
        else:
            disp = '_dispatch_' + re.sub(r'[^a-zA-Z0-9]+', '_', path_).strip('_')
            disp = disp or '_dispatch_root'
            out.append(f"    path('{path_}', views.{disp}),")
    out.append(']')
    if result.fallbacks_used:
        out.append('')
        out.append('# PORTER: routes.php called $builder->fallbacks() — '
                   'CakePHP\'s default '
                   '/{controller}/{action}/* dispatch is not auto-translated. '
                   'Add explicit Django paths for any controller that needs '
                   'the fallback behaviour.')
    out.append('')
    for path_, rs in by_path.items():
        if len(rs) == 1:
            continue
        disp = '_dispatch_' + re.sub(r'[^a-zA-Z0-9]+', '_', path_).strip('_')
        disp = disp or '_dispatch_root'
        out.append('')
        out.append(f'def {disp}(request, *args, **kwargs):')
        out.append('    method = request.method')
        for r in rs:
            view = f'views.{r.controller}_{r.action}'
            verb = r.http_method if r.http_method != 'ANY' else None
            if verb is None:
                out.append(f'    return {view}(request, *args, **kwargs)')
                break
            out.append(f"    if method == '{verb}':")
            out.append(f'        return {view}(request, *args, **kwargs)')
        out.append("    from django.http import HttpResponseNotAllowed")
        verbs = sorted({r.http_method for r in rs if r.http_method != 'ANY'})
        out.append(f"    return HttpResponseNotAllowed({verbs!r})")
    return '\n'.join(out)


def render_views(result: CakeLiftResult) -> str:
    out = [
        '"""Auto-generated by datalift liftcakephp.',
        '',
        'CakePHP controller actions translated into Django view',
        'functions. `$this->Tablename->find/get/save` and',
        '`$this->set(compact(...))` emit porter markers; the porter',
        'rewires those into Django ORM + render() context dicts.',
        '"""',
        'from django.core.exceptions import PermissionDenied',
        'from django.http import Http404, HttpResponse, JsonResponse',
        'from django.shortcuts import redirect, render',
        '',
        '',
    ]
    for ctl in result.controllers:
        for a in ctl.actions:
            arg_list = ['request'] + a.args
            out.append(f'def {ctl.qualified_name}_{a.name}'
                       f'({", ".join(arg_list)}):')
            body = a.body or 'pass'
            for line in body.splitlines() or ['pass']:
                if not line.strip():
                    out.append('')
                else:
                    out.append('    ' + line)
            out.append('')
    return '\n'.join(out)


def render_worklist(result: CakeLiftResult, app_label: str,
                    app_dir: Path) -> str:
    lines = [
        f'# liftcakephp worklist — {app_dir.name}',
        '',
        f'Target app: `{app_label}`. Generated by `datalift liftcakephp`.',
        '',
        f'## Routes ({len(result.routes)})',
        '',
    ]
    for r in result.routes:
        lines.append(f'- `{r.http_method:>6} {r.path}` → '
                     f'`{r.controller}::{r.action}`')
    if result.fallbacks_used:
        lines.append('')
        lines.append('_Note: `$builder->fallbacks()` was called. '
                     'CakePHP\'s automatic /{controller}/{action}/* '
                     'dispatch is NOT auto-translated; the porter must '
                     'add explicit Django paths for each fallback-routed '
                     'controller._')
    lines.append('')
    lines.append(f'## Controllers ({len(result.controllers)})')
    lines.append('')
    for c in result.controllers:
        lines.append(f'- `{c.source}` — `{c.class_name}` '
                     f'({len(c.actions)} action(s))')
    return '\n'.join(lines)


def apply(result: CakeLiftResult, project_root: Path,
          app_label: str, dry_run: bool = False) -> list[str]:
    log: list[str] = []
    if not result.routes and not result.controllers:
        return log
    app_dir = project_root / app_label
    if not dry_run:
        app_dir.mkdir(parents=True, exist_ok=True)
    if result.routes:
        target = app_dir / 'urls_cakephp.py'
        if not dry_run:
            target.write_text(render_urls(result, app_label), encoding='utf-8')
        log.append(f'urls      → {target.relative_to(project_root)} '
                   f'({len(result.routes)} route(s))')
    if result.controllers:
        target = app_dir / 'views_cakephp.py'
        if not dry_run:
            target.write_text(render_views(result), encoding='utf-8')
        action_count = sum(len(c.actions) for c in result.controllers)
        log.append(f'views     → {target.relative_to(project_root)} '
                   f'({len(result.controllers)} controller(s), '
                   f'{action_count} action(s))')
    return log
