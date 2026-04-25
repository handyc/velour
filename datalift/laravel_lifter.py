"""Translate a Laravel application's business logic into Django.

The first PHP business-logic lifter in the Datalift family. Targets:

* ``routes/web.php`` and ``routes/api.php`` → ``urls.py``.
* ``app/Http/Controllers/*.php`` → Django function-based views.
* Eloquent query patterns → Django ORM equivalents.

The translator handles the conventional Laravel idioms:

  Route::get('/path', [Controller::class, 'method'])
      → path('path/', Controller_method, name=...)
  Route::resource('items', ItemController::class)
      → standard 7-route resource expansion
  $users = User::all()                     → User.objects.all()
  $user = User::find($id)                  → User.objects.filter(id=id).first()
  $user = User::findOrFail($id)            → get_object_or_404(User, id=id)
  User::where('age', '>', 18)->get()       → User.objects.filter(age__gt=18)
  return view('foo.bar', $data)            → render(request, 'foo/bar.html', data)
  return redirect()->route('x')            → redirect('x')
  return response()->json($data)           → JsonResponse(data)
  Auth::user() / auth()->user()            → request.user
  request()->input('k') / request('k')     → request.POST.get('k') or .GET

What it does NOT translate (worklist markers):

* Custom service classes / facades (``ServiceProvider``, ``Mail::``,
  ``Queue::``, etc.).
* Form Request validators (a Laravel-specific pattern).
* Closures inside route definitions or middleware.
* Eloquent relationships (``hasMany``, ``belongsTo``) — those overlap
  with what genmodels infers from the SQL schema, so they're better
  reconciled via the ``port`` pipeline than re-derived from PHP.

Same deterministic discipline as the rest of the lifter family: pure
Python, no LLM, no network. The walker reads PHP source, the parser
extracts the conventional shapes, the rule table emits Python.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Records ────────────────────────────────────────────────────────

@dataclass
class RouteRecord:
    method: str             # 'get', 'post', 'put', 'patch', 'delete', 'any'
    path: str               # URL path pattern (Laravel-style: /users/{id})
    controller: str         # 'UserController' or '' for closure routes
    action: str             # 'index' or '' for closure
    name: str | None = None
    middleware: list[str] = field(default_factory=list)
    raw: str = ''           # original line, for skipped-list


@dataclass
class ControllerRecord:
    source: Path
    class_name: str
    base_class: str = ''           # 'Controller' typically
    methods: list['ControllerMethod'] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


@dataclass
class ControllerMethod:
    name: str
    visibility: str                # 'public', 'protected', 'private'
    args: list[str]                # original PHP arg names (without $)
    body_php: str
    body_django: str
    skipped: list[str] = field(default_factory=list)


@dataclass
class LiftResult:
    routes: list[RouteRecord] = field(default_factory=list)
    controllers: list[ControllerRecord] = field(default_factory=list)
    unhandled_files: list[Path] = field(default_factory=list)
    skipped_routes: list[str] = field(default_factory=list)


# ── Route translation ─────────────────────────────────────────────

# Match `Route::method('path', [Controller::class, 'action'])` form
# Controller class allows namespaces (Admin\BaseController) and a
# leading backslash (\App\Http\Controllers\Foo).
_ROUTE_BRACKET = re.compile(
    r"Route::(?P<method>get|post|put|patch|delete|options|any|match)"
    r"\(\s*"
    r"(?P<q1>['\"])(?P<path>[^'\"]+)(?P=q1)"
    r"\s*,\s*"
    r"\[\s*(?P<ctrl>[\\\w]+)::class\s*,\s*"
    r"(?P<q2>['\"])(?P<action>\w+)(?P=q2)\s*\]",
)

# Match `Route::method('path', 'Controller@action')` form
_ROUTE_AT = re.compile(
    r"Route::(?P<method>get|post|put|patch|delete|options|any|match)"
    r"\(\s*"
    r"(?P<q1>['\"])(?P<path>[^'\"]+)(?P=q1)"
    r"\s*,\s*"
    r"(?P<q2>['\"])(?P<ctrl>[\\\w]+)@(?P<action>\w+)(?P=q2)",
)

# Match `Route::resource('items', ItemController::class)` form
_ROUTE_RESOURCE = re.compile(
    r"Route::(?P<kind>resource|apiResource)"
    r"\(\s*"
    r"(?P<q1>['\"])(?P<name>[^'\"]+)(?P=q1)"
    r"\s*,\s*"
    r"(?P<ctrl>[\\\w]+)::class",
)

# Match invokable single-action controller form:
#   Route::get('/path', Controller::class)
# Laravel runs Controller::__invoke() for these.
_ROUTE_INVOKABLE = re.compile(
    r"Route::(?P<method>get|post|put|patch|delete|options|any|match)"
    r"\(\s*"
    r"(?P<q1>['\"])(?P<path>[^'\"]+)(?P=q1)"
    r"\s*,\s*"
    r"(?P<ctrl>[\\\w]+)::class\s*\)",
)

# Laravel's `Route::fallback(...)` — catch-all 404 handler.
_ROUTE_FALLBACK = re.compile(
    r"Route::fallback\(\s*\[\s*(?P<ctrl>[\\\w]+)::class\s*,\s*"
    r"(?P<q>['\"])(?P<action>\w+)(?P=q)\s*\]"
)

# `Route::group([...], function () { ... });` and chained builders
# (`Route::prefix(...)->middleware(...)->group(function() { ... })`)
# are *containers* — the actual routes inside still match the
# patterns above. We recognise the container opener so it doesn't
# show up as an unhandled fragment.
_ROUTE_GROUP_OPENER = re.compile(
    r"Route::(?:group|prefix|middleware|namespace|name|domain|where)\s*\("
)

# Match `Route::view('path', 'view.name')` form
_ROUTE_VIEW = re.compile(
    r"Route::view"
    r"\(\s*"
    r"(?P<q1>['\"])(?P<path>[^'\"]+)(?P=q1)"
    r"\s*,\s*"
    r"(?P<q2>['\"])(?P<view>[^'\"]+)(?P=q2)",
)

# Trailing modifiers on a chained route: ->name('foo'), ->middleware('x')
_NAME_RE = re.compile(r"->name\(\s*(['\"])([^'\"]+)\1\s*\)")
_MIDDLEWARE_RE = re.compile(
    r"->middleware\(\s*(?:\[?\s*((?:['\"][^'\"]+['\"]\s*,?\s*)+)\]?)\s*\)"
)


def _resource_routes(prefix: str, controller: str) -> list[RouteRecord]:
    """Expand ``Route::resource('items', ItemController::class)`` to the
    seven conventional REST routes."""
    base = prefix.strip('/')
    routes = [
        ('get',    f'/{base}',                'index'),
        ('get',    f'/{base}/create',         'create'),
        ('post',   f'/{base}',                'store'),
        ('get',    f'/{base}/{{id}}',         'show'),
        ('get',    f'/{base}/{{id}}/edit',    'edit'),
        ('put',    f'/{base}/{{id}}',         'update'),
        ('delete', f'/{base}/{{id}}',         'destroy'),
    ]
    return [
        RouteRecord(
            method=m, path=p, controller=controller, action=a,
            name=f'{base}.{a}', raw=f'Route::resource({base!r})',
        )
        for m, p, a in routes
    ]


def _api_resource_routes(prefix: str, controller: str) -> list[RouteRecord]:
    """``apiResource`` is ``resource`` minus the create/edit forms."""
    base = prefix.strip('/')
    routes = [
        ('get',    f'/{base}',         'index'),
        ('post',   f'/{base}',         'store'),
        ('get',    f'/{base}/{{id}}',  'show'),
        ('put',    f'/{base}/{{id}}',  'update'),
        ('delete', f'/{base}/{{id}}',  'destroy'),
    ]
    return [
        RouteRecord(
            method=m, path=p, controller=controller, action=a,
            name=f'{base}.{a}', raw=f'Route::apiResource({base!r})',
        )
        for m, p, a in routes
    ]


def _strip_php_comments(php: str) -> str:
    """Remove `// ...`, `# ...`, and `/* ... */` comments from PHP."""
    php = re.sub(r'/\*.*?\*/', '', php, flags=re.DOTALL)
    php = re.sub(r'(?m)//.*?$', '', php)
    php = re.sub(r'(?m)#.*?$', '', php)
    return php


def parse_routes(php: str) -> tuple[list[RouteRecord], list[str]]:
    """Parse a Laravel routes file. Returns (routes, unhandled-fragments)."""
    php = _strip_php_comments(php)
    routes: list[RouteRecord] = []
    skipped: list[str] = []

    # Track lines we've consumed so we can flag the rest.
    seen_spans: list[tuple[int, int]] = []

    # 1. Resource and apiResource (each expands to multiple routes).
    for m in _ROUTE_RESOURCE.finditer(php):
        seen_spans.append((m.start(), m.end()))
        kind = m.group('kind')
        name = m.group('name')
        ctrl = m.group('ctrl')
        # Look at the trailing modifiers (e.g. `->only(['index', 'show'])`)
        # in the same statement; we don't translate them yet, just
        # record the full set.
        if kind == 'resource':
            routes.extend(_resource_routes(name, ctrl))
        else:
            routes.extend(_api_resource_routes(name, ctrl))

    # 2. Route::view (no controller) — emit a TemplateView-like marker.
    for m in _ROUTE_VIEW.finditer(php):
        seen_spans.append((m.start(), m.end()))
        path = m.group('path')
        view_name = m.group('view').replace('.', '/') + '.html'
        routes.append(RouteRecord(
            method='get', path=path, controller='', action='_view_only',
            name=None, raw=f'Route::view({path!r}, {view_name!r})',
        ))

    # 3. Bracket form: Route::method('path', [Ctrl::class, 'action'])
    for m in _ROUTE_BRACKET.finditer(php):
        seen_spans.append((m.start(), m.end()))
        # Look ahead for chained ->name() / ->middleware() up to the
        # next semicolon at brace depth 0. Cheap heuristic: scan to
        # the next semicolon.
        end_idx = php.find(';', m.end())
        chain = php[m.end():end_idx if end_idx > 0 else m.end()]
        name_m = _NAME_RE.search(chain)
        mw_m = _MIDDLEWARE_RE.search(chain)
        middleware: list[str] = []
        if mw_m:
            middleware = [
                s.strip().strip("'\"")
                for s in mw_m.group(1).split(',')
                if s.strip()
            ]
        routes.append(RouteRecord(
            method=m.group('method').lower(),
            path=m.group('path'),
            controller=m.group('ctrl'),
            action=m.group('action'),
            name=name_m.group(2) if name_m else None,
            middleware=middleware,
            raw=php[m.start():end_idx if end_idx > 0 else m.end()],
        ))

    # 4a. Invokable form: Route::method('path', Ctrl::class)
    for m in _ROUTE_INVOKABLE.finditer(php):
        if any(s <= m.start() < e for s, e in seen_spans):
            continue
        seen_spans.append((m.start(), m.end()))
        end_idx = php.find(';', m.end())
        chain = php[m.end():end_idx if end_idx > 0 else m.end()]
        name_m = _NAME_RE.search(chain)
        mw_m = _MIDDLEWARE_RE.search(chain)
        middleware = []
        if mw_m:
            middleware = [
                s.strip().strip("'\"")
                for s in mw_m.group(1).split(',') if s.strip()
            ]
        routes.append(RouteRecord(
            method=m.group('method').lower(),
            path=m.group('path'),
            controller=m.group('ctrl'),
            action='__invoke',
            name=name_m.group(2) if name_m else None,
            middleware=middleware,
            raw=php[m.start():end_idx if end_idx > 0 else m.end()],
        ))

    # 4b. Fallback: Route::fallback([Ctrl::class, 'method'])
    for m in _ROUTE_FALLBACK.finditer(php):
        if any(s <= m.start() < e for s, e in seen_spans):
            continue
        seen_spans.append((m.start(), m.end()))
        routes.append(RouteRecord(
            method='get', path='/<fallback>',
            controller=m.group('ctrl'),
            action=m.group('action'),
            name='_fallback',
            raw=php[m.start():m.end()],
        ))

    # 4. At-form: Route::method('path', 'Ctrl@action')
    for m in _ROUTE_AT.finditer(php):
        # Skip if already covered by the bracket form.
        if any(s <= m.start() < e for s, e in seen_spans):
            continue
        seen_spans.append((m.start(), m.end()))
        end_idx = php.find(';', m.end())
        chain = php[m.end():end_idx if end_idx > 0 else m.end()]
        name_m = _NAME_RE.search(chain)
        mw_m = _MIDDLEWARE_RE.search(chain)
        middleware = []
        if mw_m:
            middleware = [
                s.strip().strip("'\"")
                for s in mw_m.group(1).split(',')
                if s.strip()
            ]
        routes.append(RouteRecord(
            method=m.group('method').lower(),
            path=m.group('path'),
            controller=m.group('ctrl'),
            action=m.group('action'),
            name=name_m.group(2) if name_m else None,
            middleware=middleware,
            raw=php[m.start():end_idx if end_idx > 0 else m.end()],
        ))

    # 5. Recognise group / prefix / middleware / namespace / name /
    # domain / where chain openers — these are containers; the real
    # routes inside them already matched in steps 1-4. Mark their
    # spans so they don't end up in `skipped`.
    for m in _ROUTE_GROUP_OPENER.finditer(php):
        # The `->where('id', '[0-9]+')` route-pattern modifier comes
        # *after* a route call, so it's already inside a seen_span.
        if any(s <= m.start() < e for s, e in seen_spans):
            continue
        seen_spans.append((m.start(), m.end()))

    # 6. Flag remaining Route::* calls that didn't match a known
    # shape AND aren't already inside a recognised span.
    for m in re.finditer(r'Route::\w+\s*\(', php):
        if any(s <= m.start() < e for s, e in seen_spans):
            continue
        end_idx = php.find(';', m.end())
        snippet = php[m.start():end_idx if end_idx > 0 else m.start() + 100]
        skipped.append(snippet.strip()[:200])

    return routes, skipped


# ── Path translation ──────────────────────────────────────────────

# Laravel `{id}` → Django `<int:id>` if the param looks numeric;
# `<slug:slug>` if it looks slug-like; `<str:...>` otherwise.
# Also handles Laravel's `{Model:column}` route-model-binding shorthand
# (e.g. `{user:id}`, `{post:slug}`) by treating the column as the param.
_LARAVEL_PARAM_RE = re.compile(r'\{(\w+)(?::(\w+))?(\?)?\}')
_NUMERIC_PARAM_NAMES = {'id', 'pk', 'page', 'count', 'limit', 'offset',
                        'year', 'month', 'day', 'number', 'num'}


def laravel_path_to_django(path: str) -> str:
    """``/users/{id}`` → ``users/<int:id>/``.

    Also supports Laravel's `{Model:column}` route-binding form:
    ``{user:id}`` → ``<int:user_id>``;
    ``{post:slug}`` → ``<slug:post_slug>``.

    Leading slash dropped (Django patterns are relative); trailing
    slash added unless path is empty.
    """
    def _replace(m: re.Match) -> str:
        name = m.group(1)
        column = m.group(2)
        if column:
            # Combine model + column for a unique kwarg name.
            param = f'{name}_{column}'
            if column in _NUMERIC_PARAM_NAMES or column.endswith('_id') or column == 'id':
                return f'<int:{param}>'
            if column == 'slug' or column.endswith('_slug'):
                return f'<slug:{param}>'
            return f'<str:{param}>'
        if name in _NUMERIC_PARAM_NAMES or name.endswith('_id'):
            return f'<int:{name}>'
        if name == 'slug' or name.endswith('_slug'):
            return f'<slug:{name}>'
        return f'<str:{name}>'
    p = _LARAVEL_PARAM_RE.sub(_replace, path)
    p = p.lstrip('/')
    if p and not p.endswith('/'):
        p += '/'
    return p


def _short_controller_name(name: str) -> str:
    """Strip the namespace prefix off a Laravel controller class.

    ``Admin\\BaseController`` → ``BaseController``;
    ``\\App\\Http\\Controllers\\PostController`` → ``PostController``.
    The view name is the short name with `_<action>` suffix.
    """
    return name.replace('\\\\', '\\').rstrip('\\').rsplit('\\', 1)[-1]


def render_urls(routes: list[RouteRecord], app_label: str = 'app') -> str:
    """Render a Django ``urls.py`` from a list of routes."""
    seen_views: set[str] = set()
    paths: list[str] = []
    needs_views_import = False

    for r in routes:
        if not r.controller:
            # Route::view or closure — emit a TemplateView marker
            paths.append(
                f"    # path({laravel_path_to_django(r.path)!r}, "
                f"TemplateView.as_view(template_name='...')),"
            )
            continue
        ctrl_short = _short_controller_name(r.controller)
        view_name = f'{ctrl_short}_{r.action}'
        seen_views.add(view_name)
        django_path = laravel_path_to_django(r.path)
        line = (
            f"    path({django_path!r}, views.{view_name}"
            + (f", name={r.name!r}" if r.name else '')
            + "),  # "
            + r.method.upper()
        )
        if r.middleware:
            line += f' [middleware: {", ".join(r.middleware)}]'
        paths.append(line)
        needs_views_import = True

    out = ['"""Auto-generated by datalift liftlaravel."""',
           'from django.urls import path',
           '']
    if needs_views_import:
        out.append('from . import views')
        out.append('')
    out.append('urlpatterns = [')
    out.extend(paths)
    out.append(']')
    return '\n'.join(out) + '\n'


# ── Controller body translation ───────────────────────────────────

# Order matters in this rule list — earlier rules win.
# Each rule: (pattern, replacement). Replacement may use named groups.

_BODY_RULES: list[tuple[re.Pattern[str], str | object]] = [
    # `view('foo.bar', $data)` → `render(request, 'foo/bar.html', data)`
    (re.compile(
        r"view\(\s*(['\"])(?P<view>[^'\"]+)\1"
        r"(?:\s*,\s*(?P<data>[^)]+))?\)"
    ),
     lambda m: ("render(request, '"
                + m.group('view').replace('.', '/') + ".html'"
                + (', ' + _translate_php_expr(m.group('data')) if m.group('data') else '')
                + ")")),

    # `redirect()->route('name', ...)` (with optional extra args) and
    # `redirect()->back()`. The extra args are dropped — Django's
    # redirect() takes the URL name and positional kwargs differently;
    # the porter wires them via reverse() if needed.
    (re.compile(r"redirect\(\)->route\(\s*(['\"])([^'\"]+)\1[^)]*\)"),
     lambda m: f"redirect({m.group(1)}{m.group(2)}{m.group(1)})"),
    (re.compile(r"redirect\(\)->back\(\)"),
     'redirect(request.META.get("HTTP_REFERER", "/"))'),
    (re.compile(r"redirect\(\)->away\(\s*(?P<url>[^)]+)\)"),
     lambda m: f"redirect({_translate_php_expr(m.group('url'))})"),
    (re.compile(r"redirect\(\s*(['\"])([^'\"]+)\1\s*\)"),
     lambda m: f"redirect({m.group(1)}{m.group(2)}{m.group(1)})"),

    # `response()->json($x)` → `JsonResponse(x)`
    (re.compile(r"response\(\)->json\(\s*(?P<arg>[^)]+)\)"),
     lambda m: f"JsonResponse({_translate_php_expr(m.group('arg'))})"),

    # `Auth::user()` / `auth()->user()` → request.user
    (re.compile(r"Auth::user\(\)"),  'request.user'),
    (re.compile(r"auth\(\)->user\(\)"),  'request.user'),
    (re.compile(r"Auth::check\(\)"), 'request.user.is_authenticated'),
    (re.compile(r"Auth::id\(\)"),    'request.user.id'),

    # `request()->input('key')` etc.
    (re.compile(r"request\(\)->input\(\s*(['\"])([^'\"]+)\1\s*\)"),
     lambda m: f"request.POST.get({m.group(1)}{m.group(2)}{m.group(1)}, request.GET.get({m.group(1)}{m.group(2)}{m.group(1)}))"),
    (re.compile(r"request\(\)->get\(\s*(['\"])([^'\"]+)\1\s*\)"),
     lambda m: f"request.GET.get({m.group(1)}{m.group(2)}{m.group(1)})"),
    (re.compile(r"request\(\)->post\(\s*(['\"])([^'\"]+)\1\s*\)"),
     lambda m: f"request.POST.get({m.group(1)}{m.group(2)}{m.group(1)})"),
    (re.compile(r"request\(\)->all\(\)"),
     'dict(request.POST.items()) | dict(request.GET.items())'),
    (re.compile(r"request\(\s*(['\"])([^'\"]+)\1\s*\)"),
     lambda m: f"request.POST.get({m.group(1)}{m.group(2)}{m.group(1)}, request.GET.get({m.group(1)}{m.group(2)}{m.group(1)}))"),

    # Eloquent: Model::all() → Model.objects.all()
    (re.compile(r"\b(?P<model>[A-Z]\w*)::all\(\)"),
     lambda m: f"{m.group('model')}.objects.all()"),
    (re.compile(r"\b(?P<model>[A-Z]\w*)::find\(\s*(?P<id>[^)]+)\)"),
     lambda m: f"{m.group('model')}.objects.filter(id={_translate_php_expr(m.group('id'))}).first()"),
    (re.compile(r"\b(?P<model>[A-Z]\w*)::findOrFail\(\s*(?P<id>[^)]+)\)"),
     lambda m: f"get_object_or_404({m.group('model')}, id={_translate_php_expr(m.group('id'))})"),
    (re.compile(r"\b(?P<model>[A-Z]\w*)::create\(\s*(?P<args>[^)]+)\)"),
     lambda m: f"{m.group('model')}.objects.create(**{_translate_php_expr(m.group('args'))})"),
    (re.compile(r"\b(?P<model>[A-Z]\w*)::count\(\)"),
     lambda m: f"{m.group('model')}.objects.count()"),
    (re.compile(r"\b(?P<model>[A-Z]\w*)::first\(\)"),
     lambda m: f"{m.group('model')}.objects.first()"),

    # `$model->save()` / `->delete()` / `->update([...])`
    (re.compile(r"\$(?P<v>\w+)->save\(\)"),
     lambda m: f"{m.group('v')}.save()"),
    (re.compile(r"\$(?P<v>\w+)->delete\(\)"),
     lambda m: f"{m.group('v')}.delete()"),
    (re.compile(r"\$(?P<v>\w+)->update\(\s*(?P<args>[^)]+)\)"),
     lambda m: f"{m.group('v')}.objects.filter(pk={m.group('v')}.pk).update(**{_translate_php_expr(m.group('args'))})"),

    # `array(...)` literal → `dict(...)` (PHP arrays often used as kwargs)
    (re.compile(r"\barray\((?P<args>[^()]*)\)"),
     lambda m: '{' + _translate_php_array_inner(m.group('args')) + '}'),

    # `[$key => $val, ...]` short-form array → dict literal
    # (we translate the contents)
    # The `=>` operator → `:`
    (re.compile(r"=>"), ':'),

    # null/true/false → None/True/False
    (re.compile(r"\bnull\b"), 'None'),
    (re.compile(r"\btrue\b"), 'True'),
    (re.compile(r"\bfalse\b"), 'False'),

    # PHP `.` string concat → Python `+`. Use `\s+\.\s+` so we don't
    # eat method-access dots that have no surrounding whitespace.
    (re.compile(r"\s+\.\s+"), ' + '),

    # `->` PHP property/method access → Python `.`
    (re.compile(r"->"), '.'),

    # `$var` → `var`
    (re.compile(r"\$(?P<v>\w+)"), lambda m: m.group('v')),
]


def _translate_php_expr(expr: str) -> str:
    """Translate a single PHP expression to Python.

    Best-effort. Used by both the body translator (for embedded args)
    and externally for things like the genmodels integration.
    """
    s = expr.strip()
    for pat, repl in _BODY_RULES:
        if callable(repl):
            s = pat.sub(repl, s)
        else:
            s = pat.sub(repl, s)
    return s


_PHP_KEYVAL_RE = re.compile(
    r"\s*(['\"])(?P<key>[^'\"]+)\1\s*=>\s*(?P<val>[^,]+?)\s*(?:,|$)"
)


def _translate_php_array_inner(inner: str) -> str:
    """Translate the contents of an `array(...)` or `[...]` literal
    into a Python dict body. Best-effort: matches `'key' => value`
    pairs and emits `'key': translated_value`."""
    out: list[str] = []
    for m in _PHP_KEYVAL_RE.finditer(inner + ','):
        key = m.group('key')
        val = _translate_php_expr(m.group('val'))
        out.append(f"'{key}': {val}")
    return ', '.join(out)


def translate_method_body(php_body: str) -> tuple[str, list[str]]:
    """Translate a controller method body. Returns (python, skipped)."""
    skipped: list[str] = []
    body = _strip_php_comments(php_body)

    # Apply rules over the whole body.
    out = body
    for pat, repl in _BODY_RULES:
        out = pat.sub(repl, out) if callable(repl) else pat.sub(repl, out)

    # Statement-level cleanup: convert `;` line endings to nothing
    # (Python statements end with newlines).
    lines = []
    for raw in out.split('\n'):
        stripped = raw.rstrip().rstrip(';')
        if stripped.strip():
            lines.append(stripped)
    out = '\n'.join(lines)

    # Translate `return view(...)` patterns where the rule already
    # rewrote the call but not the surrounding `return`.
    out = re.sub(r'\breturn\s+', 'return ', out)

    # Detect leftover PHP-only constructs and flag them. After the
    # `->` → `.` rule, smells use `.` for chained access, not `->`.
    php_smell_rules = [
        (r'\b\w+::where\(',  'Model::where (Eloquent — port to .objects.filter())'),
        (r'\.where\(',       '.where (Eloquent — port to .objects.filter())'),
        (r'\.orderBy\(',     '.orderBy (Eloquent — translate to .order_by())'),
        (r'\.paginate\(',    '.paginate (Eloquent — Django uses Paginator)'),
        (r'\bDB::',          'DB:: facade — port to Django ORM by hand'),
        (r'\bMail::',        'Mail:: facade — port to django.core.mail'),
        (r'\bCache::',       'Cache:: facade — port to django.core.cache'),
        (r'\bSession::',     'Session:: facade — port to request.session'),
        (r'this\.',          'this. (controller-internal call — port via self.)'),
    ]
    for pat, label in php_smell_rules:
        if re.search(pat, out):
            skipped.append(label)
            out = out + f'\n# LARAVEL-LIFT: {label}'

    return out, skipped


# ── Controller class parsing ───────────────────────────────────────

_CLASS_HEADER = re.compile(
    r'class\s+(?P<name>\w+)\s*(?:extends\s+(?P<base>\w+))?'
)
_USE_STMT = re.compile(r'use\s+([\\\w]+)\s*;')

# Method header: `public function name(args) { ... }`. We match up to
# the opening brace; the body is captured separately by walking braces.
_METHOD_HEADER = re.compile(
    r'(?P<vis>public|protected|private)\s+function\s+'
    r'(?P<name>\w+)\s*\((?P<args>[^)]*)\)\s*'
    r'(?::\s*\??[\\\w]+\s*)?'   # PHP return-type hint
    r'\{'
)


def _extract_brace_block(src: str, start: int) -> tuple[str, int]:
    """Given a `{` at index `start`, return (body, end_index_after_})
    where body is the contents between matched braces (excluding the
    outer `{` and `}`). Tracks string state to avoid being fooled."""
    depth = 1
    in_str: str | None = None
    i = start + 1
    n = len(src)
    while i < n:
        ch = src[i]
        if in_str:
            if ch == '\\' and i + 1 < n:
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ('"', "'"):
            in_str = ch
            i += 1
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return src[start + 1:i], i + 1
        i += 1
    return src[start + 1:], n


def parse_controller(php: str, source: Path | None = None) -> ControllerRecord:
    """Parse a Laravel controller class from PHP source."""
    src = _strip_php_comments(php)
    rec = ControllerRecord(
        source=source or Path('controller.php'),
        class_name='', base_class='',
    )

    # Imports
    for m in _USE_STMT.finditer(src):
        rec.imports.append(m.group(1))

    cm = _CLASS_HEADER.search(src)
    if not cm:
        rec.skipped.append('no class header found')
        return rec
    rec.class_name = cm.group('name')
    rec.base_class = cm.group('base') or ''

    # Find each method and extract its body.
    for mm in _METHOD_HEADER.finditer(src):
        body, end = _extract_brace_block(src, mm.end() - 1)
        py_body, skipped = translate_method_body(body)
        method = ControllerMethod(
            name=mm.group('name'),
            visibility=mm.group('vis'),
            args=[a.strip() for a in mm.group('args').split(',') if a.strip()],
            body_php=body,
            body_django=py_body,
            skipped=skipped,
        )
        rec.methods.append(method)
        rec.skipped.extend(skipped)

    return rec


# ── Code generation ────────────────────────────────────────────────

_VIEWS_HEADER = '''"""Auto-generated by datalift liftlaravel.

Translated from Laravel controllers. Each function-based view
corresponds to one controller method. Eloquent calls are translated
to the Django ORM where the patterns line up; anything more complex
is left as a `# LARAVEL-LIFT:` marker for the porter.
"""
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

# from .models import *  # uncomment after models.py is generated
'''


def _php_args_to_python(args: list[str]) -> list[str]:
    """Translate PHP method args to Python view args.

    Drops the `Request $request` arg (Django gets request automatically).
    Strips `$` prefixes. Strips type hints. The first arg is always
    `request` (Django convention).
    """
    out = ['request']
    for arg in args:
        # Strip leading type hint and `$`.
        a = arg.strip()
        # `Request $request` → drop
        if re.match(r'^(?:\w+\\?)*\s*Request\s*\$\w+\s*$', a, re.IGNORECASE):
            continue
        # `int $id`, `string $slug` → just the name
        m = re.match(r'^(?:\??[\\\w]+\s+)?\$(?P<name>\w+)(?:\s*=\s*[^,]+)?$', a)
        if m:
            out.append(m.group('name'))
        else:
            out.append(re.sub(r'^[^$]*\$', '', a))
    return out


def _dedent_body(body: str) -> str:
    """Remove the common leading whitespace from each non-blank line.

    PHP method bodies typically have 8-space (or tab) indentation
    inherited from being inside `class { method { } }`. We strip that
    so the Python version can have a consistent 4-space indent applied
    by the renderer.
    """
    lines = body.split('\n')
    nonblank = [ln for ln in lines if ln.strip()]
    if not nonblank:
        return body
    # Compute the minimum leading-whitespace count across non-blank lines.
    def _leading(s: str) -> int:
        i = 0
        while i < len(s) and s[i] in ' \t':
            i += 1
        return i
    min_indent = min(_leading(ln) for ln in nonblank)
    if min_indent == 0:
        return body
    return '\n'.join(
        ln[min_indent:] if len(ln) >= min_indent and ln.strip() else ln
        for ln in lines
    )


def render_views(controllers: list[ControllerRecord]) -> str:
    """Render a Django views.py from one or more controller records."""
    parts = [_VIEWS_HEADER]
    for ctrl in controllers:
        parts.append(f'\n# ── {ctrl.class_name} ──\n')
        for method in ctrl.methods:
            if method.visibility != 'public':
                continue
            args = _php_args_to_python(method.args)
            sig = f"def {ctrl.class_name}_{method.name}({', '.join(args)}):"
            parts.append(sig)
            body = _dedent_body(method.body_django).strip()
            if not body:
                parts.append('    pass  # empty controller method')
            else:
                indented = '\n'.join('    ' + ln if ln.strip() else ''
                                     for ln in body.split('\n'))
                parts.append(indented)
            parts.append('')
    return '\n'.join(parts) + '\n'


# ── Walker / orchestration ────────────────────────────────────────

def parse_laravel(app_dir: Path) -> LiftResult:
    """Walk a Laravel app directory, parse routes and controllers."""
    result = LiftResult()
    if not app_dir.is_dir():
        return result

    # Routes — usually at routes/web.php and routes/api.php
    routes_dir = app_dir / 'routes'
    if routes_dir.is_dir():
        for routefile in sorted(routes_dir.glob('*.php')):
            try:
                php = routefile.read_text(encoding='utf-8', errors='replace')
            except OSError:
                result.unhandled_files.append(
                    routefile.relative_to(app_dir)
                )
                continue
            routes, skipped = parse_routes(php)
            result.routes.extend(routes)
            result.skipped_routes.extend(skipped)

    # Controllers — usually under app/Http/Controllers/
    controllers_dir = app_dir / 'app' / 'Http' / 'Controllers'
    if controllers_dir.is_dir():
        for php_file in sorted(controllers_dir.rglob('*.php')):
            try:
                php = php_file.read_text(encoding='utf-8', errors='replace')
            except OSError:
                result.unhandled_files.append(
                    php_file.relative_to(app_dir)
                )
                continue
            ctrl = parse_controller(
                php, source=php_file.relative_to(app_dir)
            )
            if ctrl.class_name:
                result.controllers.append(ctrl)
            else:
                result.unhandled_files.append(
                    php_file.relative_to(app_dir)
                )

    return result


# ── Worklist + apply ──────────────────────────────────────────────

def render_worklist(result: LiftResult, app_label: str, app_dir: Path) -> str:
    lines = [
        f'# liftlaravel worklist — {app_dir.name}',
        '',
        f'Target app: `{app_label}`. Generated by `datalift liftlaravel`.',
        '',
        '## Routes parsed',
        '',
    ]
    if not result.routes:
        lines.append('_(none)_')
    else:
        for r in result.routes:
            mw = f' [middleware: {", ".join(r.middleware)}]' if r.middleware else ''
            line = (f'- `{r.method.upper()} {r.path}` → '
                    f'`{r.controller}@{r.action}`'
                    + (f' (name: `{r.name}`)' if r.name else '')
                    + mw)
            lines.append(line)
    lines += ['', '## Controllers parsed', '']
    if not result.controllers:
        lines.append('_(none)_')
    for c in result.controllers:
        skip = (f' — **{len(c.skipped)} skipped fragment(s)**'
                if c.skipped else '')
        lines.append(
            f'- `{c.source}` — `{c.class_name}` '
            f'({len(c.methods)} method(s)){skip}'
        )
    lines += ['', '## Unhandled route fragments', '']
    if not result.skipped_routes:
        lines.append('_(none — every Route::* call matched a known shape)_')
    for s in result.skipped_routes:
        lines.append(f'- `{s}`')
    lines += ['', '## Per-controller skipped expressions', '']
    saw_any = False
    for c in result.controllers:
        if not c.skipped:
            continue
        saw_any = True
        lines.append(f'### `{c.source}` ({c.class_name})')
        for s in c.skipped:
            lines.append(f'- `{s}`')
        lines.append('')
    if not saw_any:
        lines.append('_(every controller method translated cleanly)_')
    return '\n'.join(lines)


def apply(result: LiftResult, project_root: Path, app_label: str,
          dry_run: bool = False) -> list[str]:
    """Write urls.py + views.py."""
    log: list[str] = []
    app_dir = project_root / app_label
    if not dry_run:
        app_dir.mkdir(parents=True, exist_ok=True)

    if result.routes:
        urls_text = render_urls(result.routes, app_label)
        urls_path = app_dir / 'urls_laravel.py'
        if not dry_run:
            urls_path.write_text(urls_text, encoding='utf-8')
        log.append(f'urls      → {urls_path.relative_to(project_root)} '
                   f'({len(result.routes)} route(s))')

    if result.controllers:
        views_text = render_views(result.controllers)
        views_path = app_dir / 'views_laravel.py'
        if not dry_run:
            views_path.write_text(views_text, encoding='utf-8')
        total_methods = sum(len(c.methods) for c in result.controllers)
        log.append(f'views     → {views_path.relative_to(project_root)} '
                   f'({len(result.controllers)} controller(s), '
                   f'{total_methods} method(s))')

    return log
