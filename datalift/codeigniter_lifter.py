"""Translate CodeIgniter routes + controllers into Django.

Covers both CodeIgniter 3 (legacy) and CodeIgniter 4 (modern):

CodeIgniter 3 — `application/config/routes.php`:

    $route['default_controller'] = 'welcome';
    $route['users/(:num)']      = 'users/show/$1';
    $route['products/(:any)']   = 'catalog/product/$1';

CodeIgniter 4 — `app/Config/Routes.php`:

    $routes->get('/', 'Home::index');
    $routes->get('users/(:num)', 'Users::show/$1');
    $routes->resource('photos');
    $routes->group('admin', static function ($routes) {
        $routes->get('/', 'Admin::index');
    });

Controllers (CI3 extends `CI_Controller`, CI4 extends
`BaseController` and lives under `App\\Controllers`). Methods
become Django view functions; `$this->load->view(...)`,
`$this->input->post(...)`, `$this->session->userdata(...)`,
`redirect(...)` and friends are translated into their Django
equivalents.

Pure Python, no LLM, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Records ────────────────────────────────────────────────────────

@dataclass
class CIRoute:
    http_method: str        # 'GET', 'POST', ... or 'ANY'
    path: str               # Django path string e.g. 'users/<int:id>/'
    controller: str         # Bare class name (no namespace)
    method: str             # PHP method name
    name: str = ''          # Route name (CI4 'as' alias)


@dataclass
class CIMethod:
    name: str
    args: list[str]          # PHP parameter names (positional)
    body: str                # Translated Python body
    raw_body: str            # Original PHP body (for porter)


@dataclass
class CIController:
    source: Path
    class_name: str          # e.g. 'AuthController'
    qualified_name: str      # e.g. 'Myth_Auth_AuthController' (disambiguated)
    methods: list[CIMethod] = field(default_factory=list)


@dataclass
class CILiftResult:
    routes: list[CIRoute] = field(default_factory=list)
    controllers: list[CIController] = field(default_factory=list)
    skipped_files: list[Path] = field(default_factory=list)


# ── Shared PHP utilities ──────────────────────────────────────────

def _strip_php_comments(src: str) -> str:
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.DOTALL)
    src = re.sub(r'(?m)//.*?$', '', src)
    src = re.sub(r'(?m)#(?!\[).*?$', '', src)
    return src


_CAMEL_BOUNDARY = re.compile(r'(?<!^)(?=[A-Z])')


def _camel_to_snake(name: str) -> str:
    return _CAMEL_BOUNDARY.sub('_', name).lower()


def _php_str(s: str) -> str | None:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return None


# ── URL pattern → Django path ─────────────────────────────────────

_PARAM_RE = re.compile(r'\(([^)]+)\)')

_DJANGO_CONVERTERS = {
    ':num':     ('int',  'arg'),
    ':any':     ('str',  'arg'),
    ':segment': ('slug', 'arg'),
    ':hash':    ('str',  'arg'),
    ':alpha':   ('str',  'arg'),
    ':alphanum':('str',  'arg'),
}


def _convert_path(ci_path: str) -> tuple[str, list[str]]:
    """Translate a CodeIgniter URL into a Django path string + the
    inferred positional arg names (`arg1`, `arg2`, ...)."""
    ci_path = ci_path.strip().lstrip('/')
    args: list[str] = []
    counter = [0]

    def _sub(m: re.Match[str]) -> str:
        token = m.group(1)
        counter[0] += 1
        name = f'arg{counter[0]}'
        args.append(name)
        # CI placeholders start with `:`
        key = ':' + token.split(':', 1)[1] if token.startswith(':') \
              else (':' + token if not token.startswith('(') else token)
        if key not in _DJANGO_CONVERTERS:
            # Treat raw regex like `\d+` heuristically.
            if token.startswith('\\d') or token in ('[0-9]+',):
                return f'<int:{name}>'
            return f'<str:{name}>'
        conv, _ = _DJANGO_CONVERTERS[key]
        return f'<{conv}:{name}>'

    out = _PARAM_RE.sub(_sub, ci_path)
    if out and not out.endswith('/'):
        out += '/'
    return out, args


# ── Controller body translation ───────────────────────────────────

_BODY_RULES: list[tuple[re.Pattern[str], str]] = [
    # CI4 `view('welcome_message', $data)` — bare function
    (re.compile(r"\bview\(\s*'([^']+)'\s*\)"),
     r"render(request, '\1.html')"),
    (re.compile(r"\bview\(\s*'([^']+)'\s*,\s*\$([a-zA-Z_]\w*)\s*\)"),
     r"render(request, '\1.html', \2)"),

    # CI3 `$this->load->view('foo', $data)`
    (re.compile(r"\$this->load->view\(\s*'([^']+)'\s*\)"),
     r"render(request, '\1.html')"),
    (re.compile(r"\$this->load->view\(\s*'([^']+)'\s*,\s*\$([a-zA-Z_]\w*)\s*\)"),
     r"render(request, '\1.html', \2)"),
    (re.compile(r"\$this->load->model\(\s*'([^']+)'\s*\);?"),
     r"# PORTER: $this->load->model('\1') — Django auto-imports models"),
    (re.compile(r"\$this->load->helper\(\s*'([^']+)'\s*\);?"),
     r"# PORTER: $this->load->helper('\1') — replace with Django utility"),
    (re.compile(r"\$this->load->library\(\s*'([^']+)'\s*\);?"),
     r"# PORTER: $this->load->library('\1') — replace with Django service"),

    # CI3 input
    (re.compile(r"\$this->input->post\(\s*'([^']+)'\s*\)"),
     r"request.POST.get('\1')"),
    (re.compile(r"\$this->input->get\(\s*'([^']+)'\s*\)"),
     r"request.GET.get('\1')"),
    (re.compile(r"\$this->input->cookie\(\s*'([^']+)'\s*\)"),
     r"request.COOKIES.get('\1')"),

    # CI4 request
    (re.compile(r"\$this->request->getPost\(\s*'([^']+)'\s*\)"),
     r"request.POST.get('\1')"),
    (re.compile(r"\$this->request->getGet\(\s*'([^']+)'\s*\)"),
     r"request.GET.get('\1')"),
    (re.compile(r"\$this->request->getVar\(\s*'([^']+)'\s*\)"),
     r"(request.POST.get('\1') or request.GET.get('\1'))"),
    (re.compile(r"\$this->request->getJSON\(\s*\)"),
     r"json.loads(request.body)"),
    (re.compile(r"\$this->request->isAJAX\(\s*\)"),
     r"request.headers.get('x-requested-with') == 'XMLHttpRequest'"),

    # Sessions
    (re.compile(r"\$this->session->userdata\(\s*'([^']+)'\s*\)"),
     r"request.session.get('\1')"),
    (re.compile(r"\$this->session->set_userdata\(\s*'([^']+)'\s*,\s*([^)]+)\)"),
     r"request.session['\1'] = \2"),
    (re.compile(r"\$this->session->unset_userdata\(\s*'([^']+)'\s*\)"),
     r"request.session.pop('\1', None)"),
    (re.compile(r"\bsession\(\)\s*->\s*get\(\s*'([^']+)'\s*\)"),
     r"request.session.get('\1')"),
    (re.compile(r"\bsession\(\)\s*->\s*set\(\s*'([^']+)'\s*,\s*([^)]+)\)"),
     r"request.session['\1'] = \2"),

    # Redirects — `(?:return\s+)?` consumes any caller-supplied
    # `return` so we never emit `return return redirect(...)`.
    (re.compile(r"(?:return\s+)?\bredirect\(\s*'([^']+)'\s*\)"),
     r"return redirect('/\1/')"),
    (re.compile(r"(?:return\s+)?\bredirect\(\s*\)\s*->\s*to\(\s*'([^']+)'\s*\)"),
     r"return redirect('/\1/')"),
    (re.compile(r"(?:return\s+)?\bredirect\(\s*\)\s*->\s*route\(\s*'([^']+)'\s*\)"),
     r"return redirect('\1')"),
    (re.compile(r"(?:return\s+)?\bredirect\(\s*\)\s*->\s*back\(\s*\)"),
     r"return redirect(request.META.get('HTTP_REFERER', '/'))"),

    # JSON responses (CI4)
    (re.compile(r"return\s+\$this->response->setJSON\(\s*([^)]+)\)\s*;"),
     r"return JsonResponse(\1);"),
    (re.compile(r"return\s+\$this->response->setStatusCode\(\s*(\d+)\s*\)"),
     r"return HttpResponse(status=\1)"),

    # Database (CI3) — porter markers
    (re.compile(r"\$this->db->get\(\s*'([^']+)'\s*\)"),
     r"# PORTER: $this->db->get('\1') → \1.objects.all()"),
    (re.compile(r"\$this->db->where\(\s*'([^']+)'\s*,\s*([^)]+)\)"),
     r"# PORTER: $this->db->where('\1', \2) → .filter(\1=\2)"),
    (re.compile(r"\$this->db->insert\(\s*'([^']+)'\s*,\s*([^)]+)\)"),
     r"# PORTER: $this->db->insert('\1', \2) → \1(**\2).save()"),

    # CI4 Model facade
    (re.compile(r"\$this->\$([A-Za-z_]\w*Model)->find\(\s*([^)]+)\)"),
     r"\1.objects.filter(id=\2).first()"),
    (re.compile(r"\bmodel\(\s*'([^']+)'\s*\)"),
     r"# PORTER: model('\1') → import \1 from app.models"),

    # Misc
    (re.compile(r"\bsite_url\(\s*'([^']+)'\s*\)"),
     r"reverse('\1')"),
    (re.compile(r"\bbase_url\(\s*\)"),
     r"settings.BASE_URL"),
    (re.compile(r"\bbase_url\(\s*'([^']+)'\s*\)"),
     r"(settings.BASE_URL + '/\1')"),
    (re.compile(r"\bset_value\(\s*'([^']+)'\s*\)"),
     r"request.POST.get('\1', '')"),
    (re.compile(r"\bcsrf_token\(\)"),
     r"'csrfmiddlewaretoken'"),

    # Variable assignments — `$var = expr;` becomes `var = expr;`
    (re.compile(r"\$([a-zA-Z_]\w*)"), r"\1"),
]


def _translate_body(php_body: str) -> str:
    """Translate one method body's PHP into best-effort Django Python."""
    body = php_body
    for pat, repl in _BODY_RULES:
        body = pat.sub(repl, body)
    # Trailing semicolons → blank
    out_lines: list[str] = []
    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip():
            out_lines.append('')
            continue
        if line.endswith(';'):
            line = line[:-1]
        out_lines.append(line)
    return '\n'.join(out_lines).strip('\n')


# ── Controller parsing ────────────────────────────────────────────

_NAMESPACE_RE = re.compile(r'^\s*namespace\s+([\w\\]+)\s*;', re.MULTILINE)
_CLASS_RE = re.compile(
    r'(?m)^\s*(?:abstract\s+|final\s+)?class\s+(?P<name>\w+)'
    r'(?:\s+extends\s+(?P<parent>[\w\\]+))?'
)
_METHOD_RE = re.compile(
    r'(?m)^\s*public\s+function\s+(?P<name>\w+)\s*\((?P<args>[^)]*)\)'
    r'(?:\s*:\s*[\w\\?|]+)?\s*\{'
)


def _balanced_block(src: str, open_idx: int) -> tuple[int, int] | None:
    """Find the closing `}` for the `{` at `open_idx`. Returns the
    `(start, end)` slice (start = open_idx+1, end = position of `}`)."""
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


def parse_controller(php: str, source: Path | None = None,
                     namespace_prefix: str = '') -> CIController | None:
    """Parse one CodeIgniter controller class file."""
    src = _strip_php_comments(php)
    cm = _CLASS_RE.search(src)
    if not cm:
        return None
    parent = cm.group('parent') or ''
    if 'CI_Controller' not in parent and 'BaseController' not in parent \
       and parent and not parent.endswith('Controller'):
        # Not obviously a controller class — skip.
        return None
    nm = _NAMESPACE_RE.search(src)
    namespace = nm.group(1) if nm else ''
    qual_prefix = namespace_prefix or _qualified_prefix(namespace)
    qualified = f'{qual_prefix}_{cm.group("name")}' if qual_prefix \
                else cm.group('name')
    rec = CIController(
        source=source or Path('Controller.php'),
        class_name=cm.group('name'),
        qualified_name=qualified,
    )
    body_open = src.find('{', cm.end())
    if body_open < 0:
        return rec
    span = _balanced_block(src, body_open)
    if span is None:
        return rec
    class_body = src[span[0]:span[1]]
    for mm in _METHOD_RE.finditer(class_body):
        name = mm.group('name')
        if name.startswith('_'):
            continue
        if name in ('initController', 'initialize'):
            continue
        body_open_i = mm.end() - 1
        body_span = _balanced_block(class_body, body_open_i)
        if body_span is None:
            continue
        php_body = class_body[body_span[0]:body_span[1]]
        translated = _translate_body(php_body)
        args_src = mm.group('args').strip()
        args = _parse_args(args_src)
        rec.methods.append(CIMethod(
            name=name, args=args, body=translated,
            raw_body=php_body,
        ))
    return rec


def _qualified_prefix(namespace: str) -> str:
    """Build a class-name prefix from a PHP namespace, dropping the
    trailing `Controllers` segment if present (matches the convention
    other lifters use)."""
    if not namespace:
        return ''
    parts = [p for p in namespace.split('\\') if p]
    while parts and parts[-1] in ('Controllers', 'Controller'):
        parts.pop()
    return '_'.join(parts)


_PHP_PARAM_RE = re.compile(
    r'(?:\??[\w\\]+\s+)?\$(?P<name>\w+)(?:\s*=\s*[^,]+)?'
)


def _parse_args(args_src: str) -> list[str]:
    if not args_src.strip():
        return []
    return [m.group('name') for m in _PHP_PARAM_RE.finditer(args_src)]


# ── Routes parsing ────────────────────────────────────────────────

# CI3: `$route['<pattern>'] = '<controller>/<method>[/<args>]'`
_CI3_ROUTE_RE = re.compile(
    r"\$route\[\s*'(?P<pattern>[^']+)'\s*\]\s*=\s*'(?P<dest>[^']+)'"
)

# CI4 — verb routes. Includes the optional 3rd arg (options array
# — we only care about the `as` key for naming).
_CI4_VERB_RE = re.compile(
    r"\$routes\s*->\s*(?P<verb>get|post|put|delete|patch|options|head|"
    r"add|match)\s*\(\s*"
    r"(?P<args>(?:[^()]|\([^()]*\))*)"
    r"\)\s*;",
    re.DOTALL,
)
_CI4_RESOURCE_RE = re.compile(
    r"\$routes\s*->\s*(?P<kind>resource|presenter)\s*\(\s*"
    r"'(?P<name>[^']+)'\s*"
    r"(?:,\s*\[(?P<opts>[^\]]*)\])?"
    r"\s*\)\s*;"
)
_CI4_GROUP_RE = re.compile(
    r"\$routes\s*->\s*group\s*\(\s*"
    r"'(?P<prefix>[^']*)'\s*"
    r"(?:,\s*\[(?P<opts>[^\]]*)\]\s*)?"
    r",\s*(?:static\s+)?function\s*\([^)]*\)\s*\{"
)


def parse_routes_ci3(php: str) -> list[CIRoute]:
    """Parse a CodeIgniter 3 `routes.php` file."""
    src = _strip_php_comments(php)
    routes: list[CIRoute] = []
    for m in _CI3_ROUTE_RE.finditer(src):
        pat = m.group('pattern')
        dest = m.group('dest')
        if pat in ('default_controller', '404_override',
                   'translate_uri_dashes'):
            continue
        # dest like 'controller/method' or 'controller/method/$1'
        bits = dest.split('/')
        if len(bits) < 2:
            continue
        controller = bits[0]
        method = bits[1] or 'index'
        path, _ = _convert_path(pat)
        routes.append(CIRoute(
            http_method='ANY', path=path,
            controller=_camel_pascal(controller),
            method=method,
        ))
    return routes


def _camel_pascal(name: str) -> str:
    """`users` → `Users`. Controller URL fragments are lowercase but
    the actual class is PascalCase."""
    return name[:1].upper() + name[1:]


def parse_routes_ci4(php: str, namespace_prefix: str = '') -> list[CIRoute]:
    """Parse a CodeIgniter 4 `Routes.php` file."""
    src = _strip_php_comments(php)
    return _parse_ci4_block(src, prefix='', name_prefix=namespace_prefix)


def _parse_ci4_block(src: str, prefix: str = '',
                     name_prefix: str = '') -> list[CIRoute]:
    routes: list[CIRoute] = []
    i = 0
    while i < len(src):
        # Look for a group first, then verb routes, then resource.
        gm = _CI4_GROUP_RE.search(src, i)
        vm = _CI4_VERB_RE.search(src, i)
        rm = _CI4_RESOURCE_RE.search(src, i)
        # Pick the earliest match; if no match at all, stop.
        candidates = [(m.start(), m, kind) for m, kind in
                      ((gm, 'group'), (vm, 'verb'), (rm, 'resource'))
                      if m is not None]
        if not candidates:
            break
        candidates.sort(key=lambda t: t[0])
        _, m, kind = candidates[0]

        if kind == 'group':
            new_prefix = prefix
            grp_pref = m.group('prefix').strip().strip('/')
            if grp_pref:
                new_prefix = (prefix.rstrip('/') + '/' + grp_pref
                              if prefix else grp_pref).strip('/')
            opts = m.group('opts') or ''
            grp_name_prefix = name_prefix
            ns_match = re.search(r"'namespace'\s*=>\s*'([^']+)'", opts)
            if ns_match:
                grp_name_prefix = _qualified_prefix(
                    ns_match.group(1).lstrip('\\'))
            body_open = m.end() - 1
            span = _balanced_block(src, body_open)
            if span is None:
                i = m.end()
                continue
            inner = src[span[0]:span[1]]
            routes.extend(_parse_ci4_block(
                inner, prefix=new_prefix, name_prefix=grp_name_prefix,
            ))
            i = span[1] + 1
            continue

        if kind == 'verb':
            verb = m.group('verb').upper()
            if verb == 'ADD':
                verb = 'ANY'
            args_src = m.group('args')
            parts = _split_args(args_src)
            if len(parts) < 2:
                i = m.end()
                continue
            raw_path = _php_str(parts[0]) or ''
            target = parts[1].strip()
            target_str = _php_str(target)
            if target_str is None:
                # Closure or non-string handler — skip.
                i = m.end()
                continue
            if '::' not in target_str:
                # Only handle Controller::method form.
                i = m.end()
                continue
            ctrl, _, method = target_str.partition('::')
            ctrl = ctrl.replace('\\', '_').strip('_')
            full_path = (prefix.rstrip('/') + '/' + raw_path.lstrip('/')
                         if prefix else raw_path).strip('/')
            path, _args = _convert_path(full_path)
            name = ''
            if len(parts) >= 3:
                opts = parts[2]
                am = re.search(r"'as'\s*=>\s*'([^']+)'", opts)
                if am:
                    name = am.group(1)
            qualified = (f'{name_prefix}_{ctrl}' if name_prefix else ctrl)
            if verb == 'MATCH':
                # `$routes->match(['get', 'post'], '/x', 'X::y')`
                # parts[0] is the methods array; reparse.
                methods_src = parts[0]
                methods = re.findall(r"'(\w+)'", methods_src)
                if len(parts) >= 3:
                    raw_path = _php_str(parts[1]) or ''
                    target_str = _php_str(parts[2]) or ''
                    full_path = (prefix.rstrip('/') + '/' + raw_path.lstrip('/')
                                 if prefix else raw_path).strip('/')
                    path, _args = _convert_path(full_path)
                    if '::' in target_str:
                        ctrl, _, method = target_str.partition('::')
                        ctrl = ctrl.replace('\\', '_').strip('_')
                        qualified = (f'{name_prefix}_{ctrl}'
                                     if name_prefix else ctrl)
                        for hv in (m.upper() for m in methods):
                            routes.append(CIRoute(
                                http_method=hv, path=path,
                                controller=qualified, method=method,
                                name=name,
                            ))
                i = m.end()
                continue
            routes.append(CIRoute(
                http_method=verb, path=path,
                controller=qualified, method=method, name=name,
            ))
            i = m.end()
            continue

        if kind == 'resource':
            name = m.group('name')
            controller = _camel_pascal(name)
            qualified = (f'{name_prefix}_{controller}'
                         if name_prefix else controller)
            base = (prefix.rstrip('/') + '/' + name
                    if prefix else name).strip('/')
            # CI4 resource → 7 conventional REST routes
            rest = [
                ('GET',    base,                   'index'),
                ('GET',    base + '/new',          'new'),
                ('POST',   base,                   'create'),
                ('GET',    base + '/(:segment)',   'show'),
                ('GET',    base + '/(:segment)/edit', 'edit'),
                ('PUT',    base + '/(:segment)',   'update'),
                ('DELETE', base + '/(:segment)',   'delete'),
            ]
            for verb, raw_path, method in rest:
                path, _args = _convert_path(raw_path)
                routes.append(CIRoute(
                    http_method=verb, path=path,
                    controller=qualified, method=method,
                ))
            i = m.end()
            continue

    return routes


def _split_args(s: str) -> list[str]:
    """Split a comma-separated PHP arg list, respecting nested brackets."""
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


# ── File walker ───────────────────────────────────────────────────

def parse_codeigniter(app_dir: Path) -> CILiftResult:
    """Walk a CodeIgniter application root and parse routes +
    controllers. Recognises both CI3 (`application/`) and CI4 (`app/`
    or `src/`) layouts."""
    result = CILiftResult()
    if not app_dir.is_dir():
        return result

    # Discover the CI version by directory layout.
    ci3_routes = app_dir / 'application' / 'config' / 'routes.php'
    ci4_routes_candidates = [
        app_dir / 'app' / 'Config' / 'Routes.php',
        app_dir / 'src' / 'Config' / 'Routes.php',
    ]
    ci3_ctrls = app_dir / 'application' / 'controllers'
    ci4_ctrl_candidates = [
        app_dir / 'app' / 'Controllers',
        app_dir / 'src' / 'Controllers',
    ]

    # Routes
    if ci3_routes.is_file():
        result.routes.extend(parse_routes_ci3(_safe_read(ci3_routes)))
    for routes_file in ci4_routes_candidates:
        if routes_file.is_file():
            # Pull a default namespace prefix from the routes file's
            # parent (e.g. `Myth\Auth\Controllers` lives next door).
            ns_prefix = ''
            ctrl_dir = routes_file.parent.parent / 'Controllers'
            if ctrl_dir.is_dir():
                ns_prefix = _detect_namespace_prefix(ctrl_dir)
            result.routes.extend(
                parse_routes_ci4(_safe_read(routes_file), ns_prefix)
            )

    # Controllers
    for ctrl_dir in (ci3_ctrls, *ci4_ctrl_candidates):
        if not ctrl_dir.is_dir():
            continue
        for php_file in sorted(ctrl_dir.rglob('*.php')):
            text = _safe_read(php_file)
            if not text.strip():
                result.skipped_files.append(php_file.relative_to(app_dir))
                continue
            namespace_prefix = ''
            ctl = parse_controller(text, source=php_file.relative_to(app_dir),
                                    namespace_prefix=namespace_prefix)
            if ctl is not None and ctl.methods:
                result.controllers.append(ctl)
    return result


def _safe_read(p: Path) -> str:
    try:
        return p.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def _detect_namespace_prefix(controllers_dir: Path) -> str:
    """Sniff one PHP file's `namespace` line to pick a default prefix."""
    for php in controllers_dir.rglob('*.php'):
        text = _safe_read(php)
        nm = _NAMESPACE_RE.search(text)
        if nm:
            return _qualified_prefix(nm.group(1))
    return ''


# ── Renderers ─────────────────────────────────────────────────────

def render_urls(result: CILiftResult, app_label: str) -> str:
    out = [
        '"""Auto-generated by datalift liftcodeigniter.',
        '',
        'CodeIgniter routes (CI3 routes.php + CI4 Routes.php) translated',
        'into Django URL patterns. Where multiple HTTP methods land at',
        'the same path, a per-path dispatcher is emitted.',
        '"""',
        'from django.urls import path',
        f'from . import views_codeigniter as views',
        '',
        '',
    ]
    # Group by Django path for HTTP-method dispatch.
    by_path: dict[str, list[CIRoute]] = {}
    for r in result.routes:
        by_path.setdefault(r.path, []).append(r)

    out.append('urlpatterns = [')
    for path_, rs in by_path.items():
        if len(rs) == 1:
            r = rs[0]
            view = f'views.{r.controller}_{r.method}'
            name_kw = f", name='{r.name}'" if r.name else ''
            out.append(f"    path('{path_}', {view}{name_kw}),")
        else:
            disp = '_dispatch_' + re.sub(r'[^a-zA-Z0-9]+', '_', path_).strip('_')
            disp = disp or '_dispatch_root'
            out.append(f"    path('{path_}', views.{disp}),")
    out.append(']')
    out.append('')

    # Emit dispatchers for shared-path routes.
    for path_, rs in by_path.items():
        if len(rs) == 1:
            continue
        disp = '_dispatch_' + re.sub(r'[^a-zA-Z0-9]+', '_', path_).strip('_')
        disp = disp or '_dispatch_root'
        out.append('')
        out.append(f'def {disp}(request, *args, **kwargs):')
        out.append('    method = request.method')
        for r in rs:
            view = f'views.{r.controller}_{r.method}'
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


def render_views(result: CILiftResult) -> str:
    out = [
        '"""Auto-generated by datalift liftcodeigniter.',
        '',
        'CodeIgniter controller methods translated into Django view',
        'functions. Every method gets one Django view; ',
        '`$this->load->view`, `$this->input->post`, `redirect()` and',
        'friends are translated to their Django equivalents. Anything',
        'that requires service injection (`$this->load->library`,',
        '`$this->load->model`) emits a # PORTER marker.',
        '"""',
        'import json',
        '',
        'from django.conf import settings',
        'from django.http import HttpResponse, JsonResponse',
        'from django.shortcuts import redirect, render',
        'from django.urls import reverse',
        '',
        '',
    ]
    for ctl in result.controllers:
        for m in ctl.methods:
            arg_list = ['request'] + m.args
            out.append(f'def {ctl.qualified_name}_{m.name}'
                       f'({", ".join(arg_list)}):')
            body = m.body or 'pass'
            for line in body.splitlines() or ['pass']:
                if not line.strip():
                    out.append('')
                else:
                    out.append('    ' + line)
            out.append('')
    return '\n'.join(out)


def render_worklist(result: CILiftResult, app_label: str,
                    app_dir: Path) -> str:
    lines = [
        f'# liftcodeigniter worklist — {app_dir.name}',
        '',
        f'Target app: `{app_label}`. Generated by `datalift liftcodeigniter`.',
        '',
        f'## Routes ({len(result.routes)})',
        '',
    ]
    for r in result.routes:
        lines.append(f'- `{r.http_method:>6} {r.path}` → '
                     f'`{r.controller}::{r.method}`'
                     + (f' (name={r.name})' if r.name else ''))
    lines.append('')
    lines.append(f'## Controllers ({len(result.controllers)})')
    lines.append('')
    for c in result.controllers:
        lines.append(f'- `{c.source}` — `{c.class_name}` '
                     f'({len(c.methods)} method(s))')
    return '\n'.join(lines)


def apply(result: CILiftResult, project_root: Path,
          app_label: str, dry_run: bool = False) -> list[str]:
    log: list[str] = []
    if not result.routes and not result.controllers:
        return log
    app_dir = project_root / app_label
    if not dry_run:
        app_dir.mkdir(parents=True, exist_ok=True)
    if result.routes:
        target = app_dir / 'urls_codeigniter.py'
        if not dry_run:
            target.write_text(render_urls(result, app_label), encoding='utf-8')
        log.append(f'urls      → {target.relative_to(project_root)} '
                   f'({len(result.routes)} route(s))')
    if result.controllers:
        target = app_dir / 'views_codeigniter.py'
        if not dry_run:
            target.write_text(render_views(result), encoding='utf-8')
        method_count = sum(len(c.methods) for c in result.controllers)
        log.append(f'views     → {target.relative_to(project_root)} '
                   f'({len(result.controllers)} controller(s), '
                   f'{method_count} method(s))')
    return log
