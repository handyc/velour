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


def _extract_group_prefixes(php: str) -> list[tuple[int, int, str, str]]:
    """Find every ``Route::group([..., 'prefix' => 'X', ...], function () { ... });``
    or ``Route::prefix('X')->...->group(function () { ... });`` and
    return a list of (start, end, prefix, name_prefix) tuples covering
    the byte range of each group's *body* (the closure inside).

    Nested groups are returned in source order; a route's effective
    prefix is the concatenation of every group whose range contains
    that route.
    """
    out: list[tuple[int, int, str, str]] = []
    n = len(php)
    i = 0
    # Match openers: `Route::group(` or `Route::prefix(` (with optional
    # chained builders). For each, we extract any 'prefix' or 'name'
    # configuration and then locate the matching closure body span.
    opener_re = re.compile(
        r"Route::(?:group|prefix|middleware|name|namespace|domain)\s*\("
    )
    while i < n:
        m = opener_re.search(php, i)
        if not m:
            break
        start = m.start()
        # Walk the chain of `Route::X(...)->Y(...)->...->group(function ...)`
        # collecting prefix/name modifiers and finding the closure.
        prefix_parts: list[str] = []
        name_prefix_parts: list[str] = []
        cursor = m.start()
        # Loop over chained calls — each is `Route::method(...)` or
        # `->method(...)` — and capture prefix / name args. Stop when
        # we hit the call whose first arg is `function (`.
        chain_re = re.compile(
            r"(?:Route::|->)(?P<m>\w+)\("
        )
        chain_m = chain_re.match(php, cursor)
        if not chain_m:
            i = m.end()
            continue
        # Walk chain until we find the closure.
        while chain_m:
            method = chain_m.group('m')
            args_start = chain_m.end()
            # Find matching `)` for this call (balanced parens).
            depth = 1
            in_str: str | None = None
            j = args_start
            while j < n and depth > 0:
                ch = php[j]
                if in_str:
                    if ch == '\\' and j + 1 < n:
                        j += 2
                        continue
                    if ch == in_str:
                        in_str = None
                    j += 1
                    continue
                if ch in ('"', "'"):
                    in_str = ch
                elif ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                j += 1
            if depth != 0:
                break  # Unbalanced; bail out.
            args = php[args_start:j - 1]

            # Capture method-specific config.
            if method == 'group':
                # Args may be: `[...config...], function () { ... }`
                # or just `function () { ... }`.
                # Find the closure body braces.
                # Look for `function` keyword in args.
                fn_m = re.search(r'function\s*\([^)]*\)\s*(?:use\s*\([^)]*\)\s*)?\{', args)
                if not fn_m:
                    break
                # The brace at fn_m.end() - 1 is the body opener,
                # but we have `args` as a substring; convert positions
                # back to the original `php`.
                fn_brace_in_php = args_start + fn_m.end() - 1
                body_start = fn_brace_in_php + 1
                # Find matching `}`.
                d = 1
                in_s: str | None = None
                k = body_start
                while k < n and d > 0:
                    ch = php[k]
                    if in_s:
                        if ch == '\\' and k + 1 < n:
                            k += 2
                            continue
                        if ch == in_s:
                            in_s = None
                        k += 1
                        continue
                    if ch in ('"', "'"):
                        in_s = ch
                    elif ch == '{':
                        d += 1
                    elif ch == '}':
                        d -= 1
                    k += 1
                # Also check for `'prefix' => 'X'` in this group's
                # config (the array part before the closure).
                config_part = args[:fn_m.start()]
                p_m = re.search(
                    r"['\"]prefix['\"]\s*=>\s*['\"]([^'\"]*)['\"]",
                    config_part,
                )
                if p_m:
                    prefix_parts.append(p_m.group(1))
                n_m = re.search(
                    r"['\"]as['\"]\s*=>\s*['\"]([^'\"]*)['\"]",
                    config_part,
                )
                if n_m:
                    name_prefix_parts.append(n_m.group(1))
                # Record the group's body span with combined prefix/name.
                full_prefix = '/'.join(p.strip('/') for p in prefix_parts if p)
                if full_prefix:
                    full_prefix = '/' + full_prefix
                full_name = ''.join(name_prefix_parts)
                out.append((body_start, k - 1, full_prefix, full_name))
                # Advance just past the opener (NOT past the body) so the
                # next iteration can find any nested Route::group / prefix
                # inside this body.
                i = m.end()
                break
            elif method == 'prefix':
                p_m = re.match(
                    r"\s*['\"]([^'\"]*)['\"]",
                    args,
                )
                if p_m:
                    prefix_parts.append(p_m.group(1))
            elif method == 'name':
                n_m = re.match(
                    r"\s*['\"]([^'\"]*)['\"]",
                    args,
                )
                if n_m:
                    name_prefix_parts.append(n_m.group(1))
            # Move past the closing `)` and look for the next `->`.
            cursor = j
            # Skip whitespace, then look for `->`.
            while cursor < n and php[cursor] in ' \t\n':
                cursor += 1
            if php[cursor:cursor + 2] != '->':
                break
            chain_m = chain_re.match(php, cursor)
            if not chain_m:
                break
        else:
            # While loop exited without break — no group found.
            i = m.end()
            continue

        i = max(i + 1, m.end())
    return out


def _prefix_for(spans: list[tuple[int, int, str, str]],
                 pos: int) -> tuple[str, str]:
    """Return (combined_prefix, combined_name_prefix) for a route at
    position `pos`, by concatenating every span that contains it
    (innermost last)."""
    p_parts: list[str] = []
    n_parts: list[str] = []
    for start, end, prefix, name in spans:
        if start <= pos <= end:
            if prefix:
                p_parts.append(prefix.strip('/'))
            if name:
                n_parts.append(name)
    return ('/'.join(p for p in p_parts if p), ''.join(n_parts))


def parse_routes(php: str) -> tuple[list[RouteRecord], list[str]]:
    """Parse a Laravel routes file. Returns (routes, unhandled-fragments)."""
    php = _strip_php_comments(php)
    routes: list[RouteRecord] = []
    skipped: list[str] = []

    # Track lines we've consumed so we can flag the rest.
    seen_spans: list[tuple[int, int]] = []

    # Find every Route::group / Route::prefix(...)->group container
    # and record (body_start, body_end, prefix, name_prefix) for each.
    # Routes inside a group inherit its prefix.
    group_spans = _extract_group_prefixes(php)

    def _apply_prefix(path: str, pos: int) -> str:
        prefix, _ = _prefix_for(group_spans, pos)
        if not prefix:
            return path
        path_clean = path.lstrip('/')
        return '/' + prefix + ('/' + path_clean if path_clean else '')

    def _apply_name_prefix(name: str | None, pos: int) -> str | None:
        _, name_prefix = _prefix_for(group_spans, pos)
        if not name:
            return name
        if not name_prefix:
            return name
        # Don't double-prefix.
        if name.startswith(name_prefix):
            return name
        return name_prefix + name

    # 1. Resource and apiResource (each expands to multiple routes).
    for m in _ROUTE_RESOURCE.finditer(php):
        seen_spans.append((m.start(), m.end()))
        kind = m.group('kind')
        name = m.group('name')
        ctrl = m.group('ctrl')
        prefix, _ = _prefix_for(group_spans, m.start())
        full_name = (prefix.replace('/', '.') + '.' + name).strip('.') if prefix else name
        if kind == 'resource':
            sub = _resource_routes(name, ctrl)
        else:
            sub = _api_resource_routes(name, ctrl)
        for r in sub:
            r.path = _apply_prefix(r.path, m.start())
            r.name = full_name + r.name[len(name):]  # rename prefix
        routes.extend(sub)

    # 2. Route::view (no controller) — emit a TemplateView-like marker.
    for m in _ROUTE_VIEW.finditer(php):
        seen_spans.append((m.start(), m.end()))
        path = m.group('path')
        view_name = m.group('view').replace('.', '/') + '.html'
        routes.append(RouteRecord(
            method='get', path=_apply_prefix(path, m.start()),
            controller='', action='_view_only',
            name=None, raw=f'Route::view({path!r}, {view_name!r})',
        ))

    # 3. Bracket form: Route::method('path', [Ctrl::class, 'action'])
    for m in _ROUTE_BRACKET.finditer(php):
        seen_spans.append((m.start(), m.end()))
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
            path=_apply_prefix(m.group('path'), m.start()),
            controller=m.group('ctrl'),
            action=m.group('action'),
            name=_apply_name_prefix(name_m.group(2) if name_m else None,
                                     m.start()),
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
            path=_apply_prefix(m.group('path'), m.start()),
            controller=m.group('ctrl'),
            action='__invoke',
            name=_apply_name_prefix(name_m.group(2) if name_m else None,
                                     m.start()),
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
            path=_apply_prefix(m.group('path'), m.start()),
            controller=m.group('ctrl'),
            action=m.group('action'),
            name=_apply_name_prefix(name_m.group(2) if name_m else None,
                                     m.start()),
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


def _safe_dispatcher_name(django_path: str) -> str:
    """Turn a Django URL pattern into a Python identifier suitable for
    a dispatcher function name. ``view/<int:host_id>/`` →
    ``_dispatch_view_int_host_id``."""
    s = re.sub(r'[^A-Za-z0-9]+', '_', django_path).strip('_')
    return f'_dispatch_{s}' if s else '_dispatch_root'


def render_urls(routes: list[RouteRecord], app_label: str = 'app') -> str:
    """Render a Django ``urls.py`` from a list of routes.

    Critical: when multiple HTTP methods share a URL path (the
    conventional REST resource layout), Django's first-match URL
    resolver routes all of them to the first handler, so only the
    GET handler ever fires. We work around this by grouping routes
    by path and emitting a small dispatcher view for any path with
    more than one method. The dispatcher inspects ``request.method``
    and delegates to the right handler.
    """
    # Group routes by their final Django path string, preserving
    # original order for the first-seen-name + first-seen-middleware.
    paths_by_url: dict[str, list[RouteRecord]] = {}
    order: list[str] = []
    for r in routes:
        if not r.controller:
            # Route::view / closure — emit a TemplateView marker line
            # and don't fold into the dispatch table.
            url = laravel_path_to_django(r.path)
            paths_by_url.setdefault(url, []).append(r)
            if url not in order:
                order.append(url)
            continue
        url = laravel_path_to_django(r.path)
        if url not in paths_by_url:
            paths_by_url[url] = []
            order.append(url)
        paths_by_url[url].append(r)

    needs_views_import = False
    needs_http_imports = False
    dispatchers: list[str] = []   # Python source for each dispatcher fn
    url_lines: list[str] = []

    for url in order:
        rs = paths_by_url[url]
        # Closure / Route::view-only paths
        controllered = [r for r in rs if r.controller]
        if not controllered:
            url_lines.append(
                f"    # path({url!r}, "
                f"TemplateView.as_view(template_name='...')),"
            )
            continue

        if len(controllered) == 1:
            r = controllered[0]
            ctrl_short = _short_controller_name(r.controller)
            view_name = f'{ctrl_short}_{r.action}'
            line = (
                f"    path({url!r}, views.{view_name}"
                + (f", name={r.name!r}" if r.name else '')
                + "),  # " + r.method.upper()
            )
            if r.middleware:
                line += f' [middleware: {", ".join(r.middleware)}]'
            url_lines.append(line)
            needs_views_import = True
            continue

        # Multi-method case — emit a dispatcher.
        needs_views_import = True
        needs_http_imports = True
        disp_name = _safe_dispatcher_name(url)
        # Dispatcher source.
        method_table = ', '.join(
            f"{r.method.upper()!r}: views.{_short_controller_name(r.controller)}_{r.action}"
            for r in controllered
        )
        # Pick the first-seen route name (Django path name; we choose the GET if available).
        chosen_name = None
        for r in controllered:
            if r.name and (chosen_name is None or r.method == 'get'):
                chosen_name = r.name
        dispatchers.append(
            f"def {disp_name}(request, *args, **kwargs):\n"
            f"    \"\"\"HTTP-method dispatcher for {url!r}.\"\"\"\n"
            f"    _handlers = {{{method_table}}}\n"
            f"    handler = _handlers.get(request.method)\n"
            f"    if handler is None:\n"
            f"        return HttpResponseNotAllowed(_handlers.keys())\n"
            f"    return handler(request, *args, **kwargs)\n"
        )
        line = (
            f"    path({url!r}, {disp_name}"
            + (f", name={chosen_name!r}" if chosen_name else '')
            + "),  # methods: "
            + ', '.join(sorted({r.method.upper() for r in controllered}))
        )
        url_lines.append(line)

    out = [
        '"""Auto-generated by datalift liftlaravel.',
        '',
        'Routes that share a URL pattern with different HTTP methods',
        'are dispatched through a small per-path handler that switches',
        'on request.method. This is required because Django\'s URL',
        'resolver matches first-seen-only — without dispatching, only',
        'the GET handler of a REST resource would ever fire.',
        '"""',
        'from django.urls import path',
    ]
    if needs_http_imports:
        out.append('from django.http import HttpResponseNotAllowed')
    out.append('')
    if needs_views_import:
        out.append('from . import views')
        out.append('')

    out.extend(dispatchers)
    if dispatchers:
        out.append('')

    out.append('urlpatterns = [')
    out.extend(url_lines)
    out.append(']')
    return '\n'.join(out) + '\n'


# ── Controller body translation ───────────────────────────────────

# ── Eloquent query builder translation ───────────────────────────
#
# Eloquent chains like
#   User::where('age', '>', 18)->whereNull('deleted_at')->orderBy('name')->get()
# translate to
#   User.objects.filter(age__gt=18, deleted_at__isnull=True).order_by('name')
#
# Step 1: translate ``Model::method(...)`` openers to
# ``Model.objects.method(...)`` shape.
# Step 2: translate chained ``->method(...)`` calls one at a time.
# Step 3: drop terminal ``->get()`` / ``->all()`` (Django querysets are
# lazy; the chain itself is the queryset).

_ELOQUENT_OP_TO_DJANGO = {
    '=':  '',
    '<>': '_NEG_',
    '!=': '_NEG_',
    '>':  '__gt',
    '>=': '__gte',
    '<':  '__lt',
    '<=': '__lte',
    'like':     '__icontains',
    'not like': '_NEG_icontains',
}


def _eloquent_where_to_filter(args: str) -> str:
    """Translate the args of a ``where(...)`` call to Django filter kwargs.

    ``where('age', '>', 18)``       → ``age__gt=18``
    ``where('name', 'Jane')``       → ``name='Jane'``
    ``where('deleted_at', '!=', null)`` → ``.exclude(deleted_at=null)``
        (handled by the caller; we return a sentinel.)
    """
    # Split on top-level commas.
    parts = _split_top_level_commas(args)
    if len(parts) == 2:
        col = parts[0].strip().strip("'\"")
        val = _translate_php_expr(parts[1].strip())
        return f'{col}={val}'
    if len(parts) == 3:
        col = parts[0].strip().strip("'\"")
        op = parts[1].strip().strip("'\"").lower()
        val = _translate_php_expr(parts[2].strip())
        suffix = _ELOQUENT_OP_TO_DJANGO.get(op)
        if suffix is None:
            return f'{col}={val}  # eloquent op {op!r}'
        if suffix.startswith('_NEG_'):
            # Caller should turn this into .exclude(...) instead.
            inner = suffix[len('_NEG_'):]
            tail = inner if inner else ''
            return f'__EXCLUDE__:{col}{tail}={val}'
        return f'{col}{suffix}={val}'
    return f'  # eloquent where(...) with {len(parts)} args — port manually'


def _split_top_level_commas(s: str) -> list[str]:
    out: list[str] = []
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
            in_str = ch
            buf.append(ch)
            continue
        if ch in '([{':
            depth += 1
            buf.append(ch)
        elif ch in ')]}':
            depth -= 1
            buf.append(ch)
        elif ch == ',' and depth == 0:
            out.append(''.join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append(''.join(buf))
    return out


# Match a chained Eloquent call: ->method(args). Handles balanced
# parens with simple recursion (good enough for one level of nesting).
_CHAIN_CALL_RE = re.compile(
    r"->(?P<m>\w+)\((?P<a>(?:[^()]|\([^()]*\))*)\)"
)

# Static opener: Model::method(args), where Model starts capital.
_STATIC_CALL_RE = re.compile(
    r"\b(?P<model>[A-Z]\w*)::(?P<m>\w+)\((?P<a>(?:[^()]|\([^()]*\))*)\)"
)


def _translate_chain_call(method: str, args: str) -> str:
    """Translate one ``->method(args)`` chain step. Returns the
    Django ORM equivalent (without the leading dot)."""
    a = args.strip()
    if method == 'where':
        kw = _eloquent_where_to_filter(a)
        if kw.startswith('__EXCLUDE__:'):
            return f"exclude({kw[len('__EXCLUDE__:'):]})"
        return f'filter({kw})'
    if method == 'whereNull':
        col = a.strip().strip("'\"")
        return f'filter({col}__isnull=True)'
    if method == 'whereNotNull':
        col = a.strip().strip("'\"")
        return f'filter({col}__isnull=False)'
    if method == 'whereIn':
        parts = _split_top_level_commas(a)
        if len(parts) == 2:
            col = parts[0].strip().strip("'\"")
            return f'filter({col}__in={_translate_php_expr(parts[1].strip())})'
    if method == 'whereNotIn':
        parts = _split_top_level_commas(a)
        if len(parts) == 2:
            col = parts[0].strip().strip("'\"")
            return f'exclude({col}__in={_translate_php_expr(parts[1].strip())})'
    if method == 'whereBetween':
        parts = _split_top_level_commas(a)
        if len(parts) == 2:
            col = parts[0].strip().strip("'\"")
            return (f'filter({col}__range='
                    f'{_translate_php_expr(parts[1].strip())})')
    if method == 'orderBy':
        parts = _split_top_level_commas(a)
        col = parts[0].strip().strip("'\"")
        if len(parts) >= 2 and parts[1].strip().strip("'\"").lower() == 'desc':
            return f"order_by('-{col}')"
        return f"order_by('{col}')"
    if method == 'orderByDesc':
        col = a.strip().strip("'\"")
        return f"order_by('-{col}')"
    if method == 'latest':
        col = a.strip().strip("'\"") if a.strip() else 'created_at'
        return f"order_by('-{col}')"
    if method == 'oldest':
        col = a.strip().strip("'\"") if a.strip() else 'created_at'
        return f"order_by('{col}')"
    if method == 'limit' or method == 'take':
        # `.limit(10)` / `.take(10)` — Django uses slicing, but we
        # can't mix that into a chain mid-stream. Emit a marker.
        return f'[:{ _translate_php_expr(a) }]'
    if method == 'first':
        return 'first()'
    if method == 'count':
        return 'count()'
    if method == 'exists':
        return 'exists()'
    if method == 'pluck':
        parts = _split_top_level_commas(a)
        col = parts[0].strip().strip("'\"")
        return f"values_list('{col}', flat=True)"
    if method == 'select':
        cols = [p.strip().strip("'\"") for p in _split_top_level_commas(a)]
        return f"values({', '.join(repr(c) for c in cols)})"
    if method == 'distinct':
        return 'distinct()'
    if method in ('get', 'all', 'cursor'):
        # Django querysets are lazy; the terminal -> drops.
        return ''
    if method == 'find':
        return f'filter(id={_translate_php_expr(a)}).first()'
    if method == 'findOrFail':
        return f'filter(id={_translate_php_expr(a)}).first()  # findOrFail — port to get_object_or_404'
    if method == 'paginate':
        return 'all()  # paginate — wrap in Paginator at the view level'
    if method == 'with':
        parts = [p.strip().strip("'\"") for p in _split_top_level_commas(a)]
        return f'select_related({", ".join(repr(p) for p in parts)})'
    return f'{method}({_translate_php_expr(a)})  # eloquent — port manually'


# Names that look like models but are actually Laravel facades / global
# helpers — the chain translator must not touch their static calls,
# they're handled by _BODY_RULES instead.
_FACADE_NAMES = {
    'Auth', 'DB', 'Mail', 'Cache', 'Session', 'Storage', 'Queue',
    'Redis', 'Log', 'Config', 'Lang', 'Hash', 'Crypt', 'Cookie',
    'Event', 'File', 'Gate', 'Notification', 'Password', 'Schema',
    'Validator', 'View', 'Response', 'Request', 'Route', 'URL',
    'Artisan', 'Bus', 'Broadcast',
}


def _translate_eloquent_chains(text: str) -> str:
    """Walk the source, find each ``Model::method(...)->method(...)..->terminal()``
    chain, and rewrite to a Django ORM expression.

    The chain is recognised lazily — start at any ``Model::`` opener,
    consume as many `->method(...)` segments as follow with no
    intervening whitespace beyond what fits in the regex. Skips
    Laravel facades (Auth, DB, Mail, etc.) so their static calls
    flow through to _BODY_RULES.
    """
    out: list[str] = []
    pos = 0
    while pos < len(text):
        m = _STATIC_CALL_RE.search(text, pos)
        if not m:
            out.append(text[pos:])
            break
        out.append(text[pos:m.start()])
        model = m.group('model')
        method = m.group('m')
        args = m.group('a')
        end = m.end()

        # Skip facades — those have dedicated rules in _BODY_RULES.
        if model in _FACADE_NAMES:
            out.append(text[m.start():m.end()])
            pos = end
            continue

        # Skip if the static method is one we already have a rule for
        # in _BODY_RULES (e.g. all(), find, findOrFail, create, count).
        # We let _BODY_RULES handle those.
        if method in {'all', 'find', 'findOrFail', 'create',
                       'count', 'first'}:
            out.append(text[m.start():m.end()])
            pos = end
            continue

        # Begin a chain
        chain_parts: list[str] = []
        opener = _translate_chain_call(method, args)
        if opener:
            chain_parts.append(opener)

        # Consume `->method(args)` segments while present.
        while True:
            cm = _CHAIN_CALL_RE.match(text, end)
            if not cm:
                break
            cm_method = cm.group('m')
            cm_args = cm.group('a')
            tr = _translate_chain_call(cm_method, cm_args)
            if tr:
                chain_parts.append(tr)
            end = cm.end()

        body = '.'.join(chain_parts)
        if body:
            out.append(f'{model}.objects.{body}')
        else:
            out.append(f'{model}.objects.all()')
        pos = end

    return ''.join(out)


# ── Generic body rule pass ────────────────────────────────────────
#
# Order matters in this rule list — earlier rules win.
# Each rule: (pattern, replacement). Replacement may use named groups.

_BODY_RULES: list[tuple[re.Pattern[str], object]] = [
    # `$this->view->make('foo.bar', $data)` — Pterodactyl-style view
    # rendering through an injected View service. Translates to the
    # same `render()` call as the global `view()` helper.
    (re.compile(
        r"\$this->view->make\(\s*(['\"])(?P<view>[^'\"]+)\1"
        r"(?:\s*,\s*(?P<data>[^)]+))?\)"
    ),
     lambda m: ("render(request, '"
                + m.group('view').replace('.', '/') + ".html'"
                + (', ' + _translate_php_expr(m.group('data')) if m.group('data') else '')
                + ")")),

    # Same pattern but with `with()` chaining the data:
    # `$this->view->make('foo.bar')->with('users', $users)` — too
    # contextual; flag it for the porter.
    # (Handled by the `$this->` smell rule below.)

    # `view('foo.bar', $data)` — the global Laravel helper.
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

    # Step 1: Collapse Eloquent query-builder chains BEFORE the
    # generic rule pass, so a chain like
    #   `User::where('a', $b)->orderBy('c')->get()`
    # becomes `User.objects.filter(a=b).order_by('c')` in one shot
    # rather than getting partially shredded by individual rules.
    body = _translate_eloquent_chains(body)

    # Step 2: Apply the generic rule pass.
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
