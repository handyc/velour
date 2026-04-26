"""Translate a Symfony application's controllers into Django.

Symfony's routing surface comes in three forms; this lifter handles
all of them:

* **PHP 8 attributes** — `#[Route('/users', name: 'users_index',
  methods: ['GET'])]` directly on controller methods. The modern
  default since Symfony 5.2.
* **Annotations** — `@Route("/users", name="users_index")` inside
  docblock comments. Older Symfony.
* **YAML route files** — `config/routes/*.yaml` listing routes by
  name with `path` / `controller` / `methods`. Always supported.

Controller method bodies are translated using a similar rule table
to liftlaravel — the Symfony idioms (`$this->render(...)`,
`$this->redirectToRoute(...)`, `$repository->findAll()` for
Doctrine) map to Django equivalents.

Same deterministic discipline: pure Python, no LLM, no network.
Doctrine entities are out of scope here (use genmodels with the
SQL dump instead, or write a separate `liftdoctrine` later).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Records ────────────────────────────────────────────────────────

@dataclass
class SymfonyRoute:
    method: str        # 'GET', 'POST', etc., or 'ANY'
    path: str
    controller: str    # full class name or 'class@method'
    action: str
    name: str | None = None
    raw: str = ''


@dataclass
class SymfonyController:
    source: Path
    class_name: str
    namespace: str = ''
    methods: list['SymfonyMethod'] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


@dataclass
class SymfonyMethod:
    name: str
    visibility: str
    args: list[str]
    body_php: str
    body_django: str
    routes: list[SymfonyRoute] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


@dataclass
class SymfonyLiftResult:
    controllers: list[SymfonyController] = field(default_factory=list)
    yaml_routes: list[SymfonyRoute] = field(default_factory=list)
    skipped_files: list[Path] = field(default_factory=list)


# ── Source-text utilities ─────────────────────────────────────────

def _strip_php_comments_keep_docblocks(src: str) -> str:
    """Strip `//` and `#` line comments. Keeps `/* */` block comments
    because Symfony annotation routes live in docblocks. Delegates
    to the shared string-aware walker."""
    from datalift._php import strip_php_comments
    return strip_php_comments(src, keep_docblocks=True)


def _extract_brace_block(src: str, start: int) -> tuple[str, int]:
    depth = 1; in_str: str | None = None
    i = start + 1; n = len(src)
    while i < n:
        ch = src[i]
        if in_str:
            if ch == '\\' and i + 1 < n: i += 2; continue
            if ch == in_str: in_str = None
            i += 1; continue
        if ch in ('"', "'"): in_str = ch; i += 1; continue
        if ch == '{': depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0: return src[start + 1:i], i + 1
        i += 1
    return src[start + 1:], n


# ── Route parsing — PHP attributes ─────────────────────────────────

# `#[Route('/path', name: 'foo', methods: ['GET', 'POST'])]`
# `#[Route(path: '/path', name: 'foo', methods: ['GET'])]`
_ATTR_ROUTE_RE = re.compile(
    r"#\[Route\s*\(\s*"
    r"(?P<args>(?:[^\[\]]|\[[^\[\]]*\])*?)"
    r"\s*\)\s*\]",
    re.DOTALL,
)


def _parse_route_args(args: str) -> dict[str, object]:
    """Parse Symfony Route attribute args into a dict.

    Examples:
      "/users"                                       → {path: '/users'}
      "'/users', name: 'x', methods: ['GET']"        → {path, name, methods}
      "path: '/users', name: 'x'"                    → {path, name}
    """
    out: dict[str, object] = {}
    parts = _split_top_level_commas(args)
    for i, p in enumerate(parts):
        p = p.strip()
        if not p:
            continue
        if ':' in p and not p.startswith(("'", '"')):
            key, _, val = p.partition(':')
            key = key.strip()
            val = val.strip()
            out[key] = _php_value_to_python(val)
        else:
            # Positional first arg = path.
            if i == 0:
                out['path'] = _strip_quotes(p)
    return out


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


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _normalise_template_path(view: str) -> str:
    """Symfony view names take three shapes: 'user/index.html.twig',
    'user.index', or 'user/index'. Normalise to a Django-style path
    ending in '.html' (no .twig)."""
    # If it already has filesystem separators, just trim the .twig
    # extension and ensure .html ending.
    if '/' in view:
        if view.endswith('.html.twig'):
            return view[:-len('.html.twig')] + '.html'
        if view.endswith('.twig'):
            return view[:-len('.twig')] + '.html'
        if view.endswith('.html'):
            return view
        return view + '.html'
    # Pure-dotted form (e.g. 'user.index') — convert to slashes.
    return view.replace('.', '/') + '.html'


def _php_value_to_python(s: str) -> object:
    s = s.strip()
    if not s: return None
    if (s.startswith("'") and s.endswith("'")) or \
       (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    if s.startswith('[') and s.endswith(']'):
        return [_php_value_to_python(p) for p in
                _split_top_level_commas(s[1:-1])]
    if s.lower() == 'true': return True
    if s.lower() == 'false': return False
    if s.lower() == 'null': return None
    try: return int(s)
    except ValueError: pass
    try: return float(s)
    except ValueError: pass
    return s


# ── Route parsing — annotations ───────────────────────────────────

# `@Route("/path", name="foo", methods={"GET"})` inside docblock /* */.
_ANN_ROUTE_RE = re.compile(
    r"@Route\s*\(\s*(?P<args>[^)]*)\s*\)",
    re.DOTALL,
)


def _parse_annotation_args(args: str) -> dict[str, object]:
    """`"/path", name="foo", methods={"GET"}` → dict."""
    # Convert `methods={"GET"}` to `methods=['GET']` for our parser.
    a = re.sub(r'\{', '[', args)
    a = a.replace('}', ']')
    out: dict[str, object] = {}
    parts = _split_top_level_commas(a)
    for i, p in enumerate(parts):
        p = p.strip()
        if '=' in p and not p.startswith(('"', "'")):
            key, _, val = p.partition('=')
            out[key.strip()] = _php_value_to_python(val.strip())
        elif i == 0:
            out['path'] = _strip_quotes(p)
    return out


# ── Class + method walking ────────────────────────────────────────

_NAMESPACE_RE = re.compile(r'^\s*namespace\s+([\\\w]+)\s*;', re.MULTILINE)
_CLASS_HEADER = re.compile(
    r'class\s+(?P<name>\w+)\s*(?:extends\s+(?P<base>[\\\w]+))?'
)
_METHOD_HEADER = re.compile(
    r'(?P<vis>public|protected|private)\s+function\s+'
    r'(?P<name>\w+)\s*\((?P<args>[^)]*)\)\s*'
    r'(?::\s*\??[\\\w]+\s*)?'
    r'\{'
)


def parse_controller(php: str, source: Path | None = None) -> SymfonyController:
    """Parse a Symfony controller class. Each method's preceding
    docblock and PHP attributes are scanned for @Route / #[Route]."""
    src = _strip_php_comments_keep_docblocks(php)

    rec = SymfonyController(
        source=source or Path('controller.php'),
        class_name='', namespace='',
    )
    ns = _NAMESPACE_RE.search(src)
    if ns:
        rec.namespace = ns.group(1)

    cm = _CLASS_HEADER.search(src)
    if not cm:
        rec.skipped.append('no class header found')
        return rec
    rec.class_name = cm.group('name')

    # Class-level #[Route(...)] / @Route(...) — applies as a prefix
    # to every method route. Look at the source between the start of
    # file (or namespace decl) and the class header.
    pre_class_region = src[:cm.start()]
    class_path_prefix = ''
    class_name_prefix = ''
    for am in _ATTR_ROUTE_RE.finditer(pre_class_region):
        args = _parse_route_args(am.group('args'))
        p = args.get('path', '')
        if p:
            class_path_prefix = p.rstrip('/')
        n = args.get('name', '')
        if n:
            class_name_prefix = n
    for an in _ANN_ROUTE_RE.finditer(pre_class_region):
        args = _parse_annotation_args(an.group('args'))
        p = args.get('path', '')
        if p:
            class_path_prefix = p.rstrip('/')
        n = args.get('name', '')
        if n:
            class_name_prefix = n

    # For each method header, look at the source between the previous
    # method end (or class open) and this method header for any
    # docblock-annotation routes or PHP-attribute routes.
    last_end = src.find('{', cm.end())
    if last_end < 0:
        return rec
    last_end += 1

    for mm in _METHOD_HEADER.finditer(src, last_end):
        attr_region = src[last_end:mm.start()]
        method_routes: list[SymfonyRoute] = []

        def _combine_path(method_path: str) -> str:
            mp = method_path.lstrip('/')
            if not class_path_prefix:
                return '/' + mp if mp else '/'
            if not mp:
                return class_path_prefix or '/'
            return class_path_prefix + '/' + mp

        def _combine_name(method_name: str | None) -> str | None:
            if method_name is None:
                return class_name_prefix or None
            if class_name_prefix and not method_name.startswith(class_name_prefix):
                return class_name_prefix + method_name
            return method_name

        # PHP attributes
        for am in _ATTR_ROUTE_RE.finditer(attr_region):
            args = _parse_route_args(am.group('args'))
            path = args.get('path', '/')
            name = args.get('name')
            methods = args.get('methods') or ['GET']
            if isinstance(methods, str):
                methods = [methods]
            for method in methods:
                method_routes.append(SymfonyRoute(
                    method=method.upper() if isinstance(method, str) else 'GET',
                    path=_combine_path(path),
                    controller=rec.class_name,
                    action=mm.group('name'),
                    name=_combine_name(name),
                    raw=am.group(0),
                ))

        # Doc-block annotations
        for an in _ANN_ROUTE_RE.finditer(attr_region):
            args = _parse_annotation_args(an.group('args'))
            path = args.get('path', '/')
            name = args.get('name')
            methods = args.get('methods') or ['GET']
            if isinstance(methods, str):
                methods = [methods]
            for method in methods:
                method_routes.append(SymfonyRoute(
                    method=method.upper() if isinstance(method, str) else 'GET',
                    path=_combine_path(path),
                    controller=rec.class_name,
                    action=mm.group('name'),
                    name=_combine_name(name),
                    raw=an.group(0),
                ))

        body, body_end = _extract_brace_block(src, mm.end() - 1)
        py_body, body_skipped = translate_method_body(body)

        sm = SymfonyMethod(
            name=mm.group('name'),
            visibility=mm.group('vis'),
            args=[a.strip() for a in mm.group('args').split(',') if a.strip()],
            body_php=body, body_django=py_body,
            routes=method_routes, skipped=body_skipped,
        )
        rec.methods.append(sm)
        last_end = body_end

    return rec


# ── Body translation rules ────────────────────────────────────────

_SYMFONY_BODY_RULES: list[tuple[re.Pattern[str], object]] = [
    # `$this->render('user/index.html.twig', [...])` — paths come in
    # two shapes: filesystem-shape ('user/index.html.twig') and dotted
    # ('user.index'). We normalise to filesystem-shape and ensure the
    # final extension is '.html'.
    (re.compile(
        r"\$this->render\(\s*(['\"])(?P<view>[^'\"]+)\1"
        r"(?:\s*,\s*(?P<data>[^)]+))?\)"
    ),
     lambda m: ("render(request, '"
                + _normalise_template_path(m.group('view'))
                + "'"
                + (', ' + _translate_php_expr(m.group('data')) if m.group('data') else '')
                + ")")),

    # `$this->redirectToRoute('name')` — only matches the
    # zero-extra-arg form. Multi-arg forms (e.g. with `['id' =>
    # $post]` and an HTTP status code) used to be matched by a
    # `[^)]*` pattern that stopped at the FIRST `)` inside the args,
    # corrupting nested method calls like `$post->getId()`. They now
    # fall through to the catch-all (`php_code_lifter._translate_block`)
    # which handles them with proper paren tracking.
    (re.compile(r"\$this->redirectToRoute\(\s*(['\"])([^'\"]+)\1\s*\)"),
     lambda m: f"redirect({m.group(1)}{m.group(2)}{m.group(1)})"),
    (re.compile(r"\$this->redirect\(\s*(['\"])([^'\"]+)\1\s*\)"),
     lambda m: f"redirect({m.group(1)}{m.group(2)}{m.group(1)})"),

    # `$this->json(...)` / new JsonResponse(...)
    (re.compile(r"\$this->json\(\s*(?P<arg>[^)]+)\)"),
     lambda m: f"JsonResponse({_translate_php_expr(m.group('arg'))})"),
    (re.compile(r"new\s+JsonResponse\(\s*(?P<arg>[^)]+)\)"),
     lambda m: f"JsonResponse({_translate_php_expr(m.group('arg'))})"),
    (re.compile(r"new\s+Response\(\s*(?P<arg>[^)]*)\)"),
     lambda m: f"HttpResponse({_translate_php_expr(m.group('arg'))})"
               if m.group('arg').strip()
               else "HttpResponse('')"),

    # `$this->getUser()` → request.user
    (re.compile(r"\$this->getUser\(\)"), 'request.user'),
    # `$this->isGranted('ROLE_X')` — porter (Django uses different perms model)
    (re.compile(r"\$this->isGranted\(\s*(['\"])([^'\"]+)\1\s*\)"),
     lambda m: f"request.user.has_perm({m.group(1)}{m.group(2)}{m.group(1)})  "
               "# symfony @IsGranted; Django perm name may differ"),

    # `$request->request->get('key')` (POST), `$request->query->get('key')` (GET)
    (re.compile(r"\$request->request->get\(\s*(['\"])([^'\"]+)\1\s*\)"),
     lambda m: f"request.POST.get({m.group(1)}{m.group(2)}{m.group(1)})"),
    (re.compile(r"\$request->query->get\(\s*(['\"])([^'\"]+)\1\s*\)"),
     lambda m: f"request.GET.get({m.group(1)}{m.group(2)}{m.group(1)})"),
    (re.compile(r"\$request->get\(\s*(['\"])([^'\"]+)\1\s*\)"),
     lambda m: f"request.POST.get({m.group(1)}{m.group(2)}{m.group(1)}, "
               f"request.GET.get({m.group(1)}{m.group(2)}{m.group(1)}))"),

    # Doctrine repository: `$repo->findAll()` / `findOneBy(...)` / `find($id)`
    (re.compile(r"\$(?P<v>\w+)->findAll\(\)"),
     lambda m: f"{m.group('v')}.objects.all()"),
    # findBy / findOneBy — single-criteria form only. Multi-arg
    # forms (with $orderBy, $limit, $offset) used to be matched by
    # `[^)]+` which silently included the extra args, producing
    # `.filter(**{a:b}, {c:d})` (positional after kw unpacking).
    # Multi-arg forms now fall through to the catch-all which
    # produces syntactically-valid `.findBy({a:b}, {c:d})` for the
    # porter to refactor.
    (re.compile(r"\$(?P<v>\w+)->findOneBy\(\s*(?P<a>\[[^\[\]]*\])\s*\)"),
     lambda m: f"{m.group('v')}.objects.filter(**{_translate_php_expr(m.group('a'))}).first()"),
    (re.compile(r"\$(?P<v>\w+)->findBy\(\s*(?P<a>\[[^\[\]]*\])\s*\)"),
     lambda m: f"{m.group('v')}.objects.filter(**{_translate_php_expr(m.group('a'))})"),
    (re.compile(r"\$(?P<v>\w+)->find\(\s*(?P<id>[^)(]+)\)"),
     lambda m: f"{m.group('v')}.objects.filter(id={_translate_php_expr(m.group('id'))}).first()"),

    # `$entityManager->persist($x); $entityManager->flush()` — keep
    # the trailing `;` on the emitted Python so the catch-all's
    # statement-boundary parser still finds a separator. Without
    # the `;`, `_find_statement_end` would gobble the next real
    # statement into the same chunk and break indentation.
    (re.compile(r"\$(?P<em>\w+)->persist\(\s*\$(?P<x>\w+)\s*\)\s*;?"),
     lambda m: f"{m.group('x')}.save();"),
    (re.compile(r"\$(?P<em>\w+)->flush\(\)\s*;?"),
     ';'),  # keep `;` so statement boundaries survive; `;` alone is
            # a no-op after the catch-all's blank-line cleanup

    # The generic PHP-syntax rewrites (`=>` → `:`, `->` → `.`,
    # `null/true/false`, string concat, `$var` strip) used to live
    # here. They're now all handled by the catch-all
    # (`php_code_lifter._translate_block`) — and crucially the
    # catch-all's `=>` rewrite is bracket-aware, so `['k' => v]`
    # becomes `{'k': v}` (dict) instead of `['k' : v]` (list with a
    # stray `:`, invalid Python). Local versions stripped.
]


def _translate_php_expr(expr: str) -> str:
    """Translate a single PHP expression to Python.

    Used inline by `_SYMFONY_BODY_RULES` callbacks (e.g. for the
    array argument to `findBy(...)`). Delegates to
    `php_code_lifter._translate_expr` which handles `array(...)`/
    `[...]` literal-vs-dict detection (so `['k' => $v]` becomes
    `{'k': v}` and not `['k' : v]`)."""
    from datalift.php_code_lifter import _translate_expr
    return _translate_expr(expr.strip())
    # (Original Symfony-only rule pass kept below as dead code for
    # reference, but the catch-all subsumes it cleanly.)
    s = expr.strip()
    for pat, repl in _SYMFONY_BODY_RULES:
        s = pat.sub(repl, s) if callable(repl) else pat.sub(repl, s)
    return s


def translate_method_body(php_body: str) -> tuple[str, list[str]]:
    """Translate a Symfony controller method body.

    Two-stage:
      1. Symfony-specific rules (`$this->render`, `$this->redirectToRoute`,
         `$repo->find`, etc.) — handle the rich framework idioms first.
      2. Generic PHP → Python pass via
         `php_code_lifter._translate_block` — handles control flow,
         array literals, type casts, ternary, namespace `\\`, Python
         keyword renames, walrus, and the dozens of other patterns
         the catch-all has accumulated through the LimeSurvey /
         MediaWiki / phpBB road tests."""
    skipped: list[str] = []
    body = _strip_php_comments_keep_docblocks(php_body)
    out = body
    for pat, repl in _SYMFONY_BODY_RULES:
        out = pat.sub(repl, out) if callable(repl) else pat.sub(repl, out)

    # The previous per-line `;` strip + blank-line filter is now
    # redundant — _translate_block handles statement parsing.
    from datalift.php_code_lifter import _translate_block
    out = _translate_block(out, indent=0)

    # Detect remaining smells.
    smell_rules = [
        (r'\bDoctrine::',
         'Doctrine:: facade — port via Django ORM by hand'),
        (r'\bgetDoctrine\(\)',
         '$this->getDoctrine() — DI removed in Symfony 4+; Django uses'
         ' module-level imports'),
        (r'\$form\b', 'Symfony form objects — Django uses django.forms'),
        (r'this\.', 'this. (controller-internal — port to Django CBV or '
                    'module-level deps)'),
    ]
    for pat, label in smell_rules:
        if re.search(pat, out):
            skipped.append(label)
            out += f'\n# SYMFONY-LIFT: {label}'
    return out, skipped


# ── Path translation ──────────────────────────────────────────────

_SYMFONY_PARAM_RE = re.compile(
    r'\{'
    r'(?P<name>\w+)'                           # the URL param name
    r'(?::(?P<entity>\w+))?'                   # entity-binding shortcut: {id:post}
    r'(?:<(?P<requirement>[^>]+)>)?'           # regex requirement
    r'\}'
)


def symfony_path_to_django(path: str) -> str:
    """``/users/{id}`` → ``users/<int:id>/``.

    Honors Symfony's optional ``<requirement>`` regex shorthand:
    ``{id<\\d+>}`` → ``<int:id>``;
    ``{slug<[a-z-]+>}`` → ``<slug:slug>``.

    Also handles the param-converter shorthand ``{id:post}`` which
    Symfony uses to auto-resolve a Post entity by id — the param
    converter is server-side magic Django doesn't have, so we just
    keep ``id`` as the kwarg and infer it as ``<int:id>``.
    """
    def _repl(m: re.Match) -> str:
        name = m.group('name')
        entity = m.group('entity')
        req = m.group('requirement') or ''

        # `{id:post}` form — entity converter, treat as int id.
        if entity:
            if name == 'slug' or name.endswith('_slug'):
                return f'<slug:{name}>'
            # Default: integer primary key.
            return f'<int:{name}>'

        if req in (r'\d+', r'[0-9]+'):
            return f'<int:{name}>'
        if 'a-z' in req or 'A-Z' in req:
            return f'<slug:{name}>' if name == 'slug' else f'<str:{name}>'
        if name in ('id', 'page', 'count', 'limit', 'offset',
                    'year', 'month', 'day', 'pk'):
            return f'<int:{name}>'
        if name == 'slug' or name.endswith('_slug'):
            return f'<slug:{name}>'
        return f'<str:{name}>'
    p = _SYMFONY_PARAM_RE.sub(_repl, path)
    p = p.lstrip('/')
    if p and not p.endswith('/'): p += '/'
    return p


# ── YAML route parsing ────────────────────────────────────────────

_YAML_ROUTE_RE = re.compile(
    r"^(?P<name>[\w.]+):\s*\n"
    r"(?P<body>(?:^[ \t]+.*\n?)+)",
    re.MULTILINE,
)


def parse_yaml_routes(yaml_text: str) -> list[SymfonyRoute]:
    """Parse a Symfony config/routes/*.yaml file.

    Recognised keys per route:
      path:        /users/{id}
      controller:  App\\Controller\\UserController::show
      methods:     [GET, POST]
    """
    out: list[SymfonyRoute] = []
    for m in _YAML_ROUTE_RE.finditer(yaml_text):
        name = m.group('name')
        body = m.group('body')
        path_m = re.search(r'^[ \t]+path:\s*(.+)$', body, re.MULTILINE)
        ctrl_m = re.search(r'^[ \t]+controller:\s*(.+)$', body, re.MULTILINE)
        methods_m = re.search(r'^[ \t]+methods:\s*(.+)$', body, re.MULTILINE)
        if not path_m or not ctrl_m:
            continue
        path = path_m.group(1).strip().strip("'\"")
        ctrl = ctrl_m.group(1).strip()
        if '::' in ctrl:
            ctrl_class, _, action = ctrl.partition('::')
        else:
            ctrl_class, action = ctrl, '__invoke'
        # Normalize backslashes — drop the `App\Controller\` namespace.
        short_ctrl = ctrl_class.replace('\\\\', '\\').rsplit('\\', 1)[-1]
        methods: list[str] = ['GET']
        if methods_m:
            mlist = methods_m.group(1).strip().lstrip('[').rstrip(']')
            methods = [s.strip().strip("'\"") for s in mlist.split(',') if s.strip()]
            if not methods:
                methods = ['GET']
        for method in methods:
            out.append(SymfonyRoute(
                method=method.upper(), path=path,
                controller=short_ctrl, action=action,
                name=name, raw=body.strip()[:200],
            ))
    return out


# ── Walker ────────────────────────────────────────────────────────

def parse_symfony(app_dir: Path) -> SymfonyLiftResult:
    """Walk a Symfony application and parse routes + controllers."""
    result = SymfonyLiftResult()
    if not app_dir.is_dir():
        return result

    # YAML routes — prefer the standard `config/routes/` location;
    # only fall back to `config/` if the conventional dir is missing.
    yaml_dir = None
    for candidate in ('config/routes', 'config/routing', 'config'):
        d = app_dir / candidate
        if d.is_dir():
            yaml_dir = d
            break
    if yaml_dir is not None:
        seen_paths: set[Path] = set()
        for yf in sorted(yaml_dir.rglob('*.y*ml')):
            if yf in seen_paths:
                continue
            seen_paths.add(yf)
            try:
                text = yf.read_text(encoding='utf-8', errors='replace')
            except OSError:
                result.skipped_files.append(yf.relative_to(app_dir))
                continue
            result.yaml_routes.extend(parse_yaml_routes(text))

    # Controllers — usually src/Controller/*.php
    for ctrl_dir_rel in ('src/Controller', 'src/Controllers'):
        ctrl_dir = app_dir / ctrl_dir_rel
        if not ctrl_dir.is_dir():
            continue
        for php_file in sorted(ctrl_dir.rglob('*.php')):
            try:
                php = php_file.read_text(encoding='utf-8', errors='replace')
            except OSError:
                result.skipped_files.append(php_file.relative_to(app_dir))
                continue
            ctrl = parse_controller(php, source=php_file.relative_to(app_dir))
            if ctrl.class_name:
                result.controllers.append(ctrl)

    return result


# ── Renderers ─────────────────────────────────────────────────────

_VIEWS_HEADER = '''"""Auto-generated by datalift liftsymfony.

Translated from Symfony controllers + YAML route files.
"""
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

# Repositories live as Django ORM managers; the controller methods
# below reference them as if they were already wired into module
# scope. The porter wires those via the matching liftmigrations
# / genmodels output.
'''


def _php_args_to_python(args: list[str]) -> list[str]:
    out = ['request']
    for a in args:
        a = a.strip()
        # `Request $request` → drop
        if re.match(r'^(?:\w+\\?)*\s*Request\s*\$\w+\s*$', a, re.IGNORECASE):
            continue
        # Doctrine repository injection: `UserRepository $userRepository`
        # — drop the type hint; the porter wires it.
        # `int $id`, `string $slug` → just the name
        m = re.match(
            r'^(?:\??[\\\w]+\s+)?\$(?P<n>\w+)(?:\s*=\s*[^,]+)?$',
            a,
        )
        if m:
            out.append(m.group('n'))
        else:
            out.append(re.sub(r'^[^$]*\$', '', a))
    return out


def _qualified_class_name(ctrl: SymfonyController) -> str:
    """Disambiguate same-named classes from different namespaces.

    Symfony apps commonly have e.g. ``App\\Controller\\BlogController``
    AND ``App\\Controller\\Admin\\BlogController`` — the short class
    name collides. We prepend the last segment of the namespace
    (after `App\\Controller\\`) when one is present.
    """
    if not ctrl.namespace:
        return ctrl.class_name
    # Strip a leading App\Controller (or just App\) and use what's left.
    ns = ctrl.namespace.replace('\\\\', '\\')
    for prefix in ('App\\Controller\\', 'App\\'):
        if ns.startswith(prefix):
            ns = ns[len(prefix):]
            break
    if not ns:
        return ctrl.class_name
    last_seg = ns.split('\\')[-1]
    return f'{last_seg}_{ctrl.class_name}'


def render_views(controllers: list[SymfonyController]) -> str:
    parts = [_VIEWS_HEADER]
    for ctrl in controllers:
        qn = _qualified_class_name(ctrl)
        parts.append(f'\n# ── {qn} ──\n')
        for method in ctrl.methods:
            if method.visibility != 'public':
                continue
            args = _php_args_to_python(method.args)
            parts.append(f"def {qn}_{method.name}({', '.join(args)}):")
            body = method.body_django.strip()
            if not body:
                parts.append('    pass  # empty controller method')
            else:
                indented = '\n'.join('    ' + ln if ln.strip() else ''
                                     for ln in body.split('\n'))
                parts.append(indented)
            parts.append('')
    return '\n'.join(parts) + '\n'


def render_urls(result: SymfonyLiftResult) -> str:
    """Render a Django urls.py from both attribute / annotation routes
    (collected from controller methods) and YAML routes."""
    # Build a map from short class name → qualified name so attribute
    # route records (which have only the short name) get rewired.
    qualified_map: dict[str, str] = {}
    for ctrl in result.controllers:
        qualified_map[ctrl.class_name] = _qualified_class_name(ctrl)

    routes: list[SymfonyRoute] = []
    for r in result.yaml_routes:
        # YAML route controllers use the same short-name convention.
        # Use the qualified version if we know it.
        qc = qualified_map.get(r.controller, r.controller)
        if qc != r.controller:
            r = SymfonyRoute(method=r.method, path=r.path, controller=qc,
                              action=r.action, name=r.name, raw=r.raw)
        routes.append(r)

    for ctrl in result.controllers:
        qc = _qualified_class_name(ctrl)
        for method in ctrl.methods:
            for r in method.routes:
                if r.controller != qc:
                    routes.append(SymfonyRoute(
                        method=r.method, path=r.path, controller=qc,
                        action=r.action, name=r.name, raw=r.raw,
                    ))
                else:
                    routes.append(r)

    # Group by path so multi-method dispatch works (same as liftlaravel).
    paths_by_url: dict[str, list[SymfonyRoute]] = {}
    order: list[str] = []
    for r in routes:
        url = symfony_path_to_django(r.path)
        if url not in paths_by_url:
            paths_by_url[url] = []
            order.append(url)
        paths_by_url[url].append(r)

    out = ['"""Auto-generated by datalift liftsymfony."""',
           'from django.urls import path',
           'from django.http import HttpResponseNotAllowed',
           '',
           'from . import views',
           '']
    dispatchers: list[str] = []
    url_lines: list[str] = []
    for url in order:
        rs = paths_by_url[url]
        if len(rs) == 1:
            r = rs[0]
            view = f'{r.controller}_{r.action}'
            line = (f"    path({url!r}, views.{view}"
                    + (f", name={r.name!r}" if r.name else '')
                    + f"),  # {r.method}")
            url_lines.append(line)
            continue

        # Multi-method dispatcher.
        safe = re.sub(r'[^A-Za-z0-9]+', '_', url).strip('_') or 'root'
        disp_name = f'_dispatch_{safe}'
        method_table = ', '.join(
            f"{r.method!r}: views.{r.controller}_{r.action}" for r in rs
        )
        chosen_name = next((r.name for r in rs if r.name), None)
        dispatchers.append(
            f"def {disp_name}(request, *args, **kwargs):\n"
            f"    \"\"\"HTTP-method dispatcher for {url!r}.\"\"\"\n"
            f"    _handlers = {{{method_table}}}\n"
            f"    handler = _handlers.get(request.method)\n"
            f"    if handler is None:\n"
            f"        return HttpResponseNotAllowed(_handlers.keys())\n"
            f"    return handler(request, *args, **kwargs)\n"
        )
        line = (f"    path({url!r}, {disp_name}"
                + (f", name={chosen_name!r}" if chosen_name else '')
                + f"),  # methods: "
                + ', '.join(sorted({r.method for r in rs})))
        url_lines.append(line)

    out.extend(dispatchers)
    if dispatchers:
        out.append('')
    out.append('urlpatterns = [')
    out.extend(url_lines)
    out.append(']')
    return '\n'.join(out) + '\n'


# ── Worklist + apply ──────────────────────────────────────────────

def render_worklist(result: SymfonyLiftResult, app_label: str,
                    app_dir: Path) -> str:
    routes: list[SymfonyRoute] = list(result.yaml_routes)
    for ctrl in result.controllers:
        for method in ctrl.methods:
            routes.extend(method.routes)
    lines = [
        f'# liftsymfony worklist — {app_dir.name}',
        '',
        f'Target app: `{app_label}`. Generated by `datalift liftsymfony`.',
        '',
        f'## Routes ({len(routes)})',
        '',
    ]
    if not routes:
        lines.append('_(none)_')
    for r in routes:
        lines.append(f'- `{r.method} {r.path}` → '
                     f'`{r.controller}@{r.action}`'
                     + (f' (name: `{r.name}`)' if r.name else ''))
    lines += ['', f'## Controllers ({len(result.controllers)})', '']
    for c in result.controllers:
        skip = (f' — **{len(c.skipped)} skipped**'
                if c.skipped else '')
        lines.append(f'- `{c.source}` — `{c.class_name}` '
                     f'({len(c.methods)} method(s)){skip}')
    return '\n'.join(lines)


def apply(result: SymfonyLiftResult, project_root: Path,
          app_label: str, dry_run: bool = False) -> list[str]:
    log: list[str] = []
    app_dir = project_root / app_label
    if not dry_run:
        app_dir.mkdir(parents=True, exist_ok=True)

    if result.controllers or result.yaml_routes:
        urls_text = render_urls(result)
        urls_path = app_dir / 'urls_symfony.py'
        if not dry_run:
            urls_path.write_text(urls_text, encoding='utf-8')
        n_routes = sum(len(m.routes) for c in result.controllers for m in c.methods)
        n_routes += len(result.yaml_routes)
        log.append(f'urls      → {urls_path.relative_to(project_root)} '
                   f'({n_routes} route(s))')

    if result.controllers:
        views_text = render_views(result.controllers)
        views_path = app_dir / 'views_symfony.py'
        if not dry_run:
            views_path.write_text(views_text, encoding='utf-8')
        n_methods = sum(len(c.methods) for c in result.controllers)
        log.append(f'views     → {views_path.relative_to(project_root)} '
                   f'({len(result.controllers)} controller(s), '
                   f'{n_methods} method(s))')

    return log
