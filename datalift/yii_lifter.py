"""Translate a Yii 2 application's controllers + routes into Django.

Yii 2 conventions:

    namespace app\\controllers;
    class SiteController extends \\yii\\web\\Controller
    {
        public function actionIndex(): string {
            return $this->render('index');
        }
        public function actionView($id) {
            $post = Post::findOne($id);
            return $this->render('view', ['post' => $post]);
        }
    }

URL: `/<controller-id>/<action-id>` where `controller-id` is the
class name minus `Controller` (lowercase), and `action-id` is the
method name minus `action` (camelCase → dashed-case).

`behaviors()` may declare a VerbFilter that pins certain actions
to specific HTTP methods (`'logout' => ['post']`).

Custom URL rules in `config/web.php` `urlManager.rules` override
the default routing — parsed where present.

Pure Python, no LLM, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from datalift._php import strip_php_comments


# ── Records ────────────────────────────────────────────────────────

@dataclass
class YiiRoute:
    http_method: str        # 'GET', 'POST', ..., or 'ANY'
    path: str               # Django path string, e.g. 'site/index/'
    controller: str         # bare 'SiteController'
    action: str             # PHP action name, e.g. 'actionIndex'


@dataclass
class YiiAction:
    name: str               # PHP method name e.g. 'actionLogin'
    action_id: str          # dashed-case URL id e.g. 'login'
    args: list[str]
    body: str
    raw_body: str


@dataclass
class YiiController:
    source: Path
    class_name: str         # 'SiteController'
    controller_id: str      # 'site'
    actions: list[YiiAction] = field(default_factory=list)
    verb_map: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class YiiLiftResult:
    routes: list[YiiRoute] = field(default_factory=list)
    controllers: list[YiiController] = field(default_factory=list)
    custom_rules: list[tuple[str, str]] = field(default_factory=list)
    skipped_files: list[Path] = field(default_factory=list)


# ── PHP utilities ─────────────────────────────────────────────────

def _balanced_block(src: str, open_idx: int) -> tuple[int, int] | None:
    depth = 0
    in_str: str | None = None
    i = open_idx
    while i < len(src):
        ch = src[i]
        if in_str:
            if ch == '\\' and i + 1 < len(src):
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


def _camel_to_dashed(name: str) -> str:
    """`actionLogin` → `login`, `actionLogOut` → `log-out`."""
    s = re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower()
    return s


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


# ── Body translation ──────────────────────────────────────────────

_BODY_RULES: list[tuple[re.Pattern[str], str]] = [
    # render — `$this->render('view')` (positional + with array)
    (re.compile(r"\$this->render\(\s*'([^']+)'\s*\)"),
     r"return render(request, '\1.html')"),
    (re.compile(r"\$this->render\(\s*'([^']+)'\s*,\s*\[(?P<arr>[^\]]*)\]\s*\)"),
     r"return render(request, '\1.html', { \g<arr> })"),
    (re.compile(r"\$this->renderPartial\(\s*'([^']+)'\s*\)"),
     r"return render(request, '\1.html')"),
    (re.compile(r"\$this->renderAjax\(\s*'([^']+)'\s*\)"),
     r"return render(request, '\1.html')"),

    # Navigation helpers
    (re.compile(r"(?:return\s+)?\$this->goHome\(\s*\)"),
     r"return redirect('/')"),
    (re.compile(r"(?:return\s+)?\$this->goBack\(\s*\)"),
     r"return redirect(request.session.get('return_url', '/'))"),
    (re.compile(r"(?:return\s+)?\$this->refresh\(\s*\)"),
     r"return redirect(request.path)"),
    (re.compile(r"(?:return\s+)?\$this->redirect\(\s*'([^']+)'\s*\)"),
     r"return redirect('\1')"),
    (re.compile(r"(?:return\s+)?\$this->redirect\(\s*\[\s*'([^']+)'\s*\]\s*\)"),
     r"return redirect('\1')"),

    # Yii::$app helpers
    (re.compile(r"Yii::\$app->user->isGuest"),
     r"(not request.user.is_authenticated)"),
    (re.compile(r"Yii::\$app->user->identity"),
     r"request.user"),
    (re.compile(r"Yii::\$app->user->logout\(\s*\)"),
     r"# PORTER: Yii::$app->user->logout() → logout(request) (django.contrib.auth)"),
    (re.compile(r"Yii::\$app->session->get\(\s*'([^']+)'\s*\)"),
     r"request.session.get('\1')"),
    (re.compile(r"Yii::\$app->session->set\(\s*'([^']+)'\s*,\s*([^)]+)\)"),
     r"request.session['\1'] = \2"),
    (re.compile(r"Yii::\$app->session->setFlash\(\s*'([^']+)'\s*,\s*([^)]+)\)"),
     r"# PORTER: Yii::$app->session->setFlash('\1', \2) → messages.\1(request, \2)"),
    (re.compile(r"Yii::\$app->request->post\(\s*'([^']+)'\s*\)"),
     r"request.POST.get('\1')"),
    (re.compile(r"Yii::\$app->request->get\(\s*'([^']+)'\s*\)"),
     r"request.GET.get('\1')"),
    (re.compile(r"Yii::\$app->request->isPost"),
     r"(request.method == 'POST')"),
    (re.compile(r"Yii::\$app->request->isAjax"),
     r"request.headers.get('x-requested-with') == 'XMLHttpRequest'"),

    # `$this->request` (alias when injected)
    (re.compile(r"\$this->request->post\(\s*'([^']+)'\s*\)"),
     r"request.POST.get('\1')"),
    (re.compile(r"\$this->request->get\(\s*'([^']+)'\s*\)"),
     r"request.GET.get('\1')"),
    (re.compile(r"\$this->request->post\(\s*\)"),
     r"request.POST"),

    # ActiveRecord queries — porter markers (Django ORM is structurally
    # similar but model classes need to be imported separately).
    (re.compile(r"\b([A-Z]\w*)::findOne\(\s*\$([a-zA-Z_]\w*)\s*\)"),
     r"# PORTER: \1::findOne(\2) → \1.objects.filter(pk=\2).first()"),
    (re.compile(r"\b([A-Z]\w*)::find\(\s*\)\s*->\s*all\(\s*\)"),
     r"# PORTER: \1::find()->all() → list(\1.objects.all())"),
    (re.compile(r"\b([A-Z]\w*)::find\(\s*\)\s*->\s*one\(\s*\)"),
     r"# PORTER: \1::find()->one() → \1.objects.first()"),
    (re.compile(r"\b([A-Z]\w*)::find\(\s*\)\s*->\s*count\(\s*\)"),
     r"# PORTER: \1::find()->count() → \1.objects.count()"),
    (re.compile(r"\$([a-zA-Z_]\w*)->save\(\s*\)"),
     r"\1.save()"),
    (re.compile(r"\$([a-zA-Z_]\w*)->delete\(\s*\)"),
     r"\1.delete()"),

    # Generic `$var = expr;` strip
    (re.compile(r"\$([a-zA-Z_]\w*)"), r"\1"),
]


def _translate_body(php_body: str) -> str:
    body = php_body
    for pat, repl in _BODY_RULES:
        body = pat.sub(repl, body)
    out: list[str] = []
    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip():
            out.append('')
            continue
        if line.endswith(';'):
            line = line[:-1]
        out.append(line)
    return '\n'.join(out).strip('\n')


# ── Controller parsing ────────────────────────────────────────────

_NAMESPACE_RE = re.compile(r'^\s*namespace\s+([\w\\]+)\s*;', re.MULTILINE)
_CLASS_RE = re.compile(
    r'(?m)^\s*(?:abstract\s+|final\s+)?class\s+(?P<name>\w+)'
    r'(?:\s+extends\s+(?P<parent>[\w\\]+))?'
)
_ACTION_RE = re.compile(
    r'(?m)^\s*public\s+function\s+(?P<name>action[A-Z]\w*)\s*'
    r'\((?P<args>[^)]*)\)'
    r'(?:\s*:\s*\??[\w\\|]+)?\s*\{'
)
_METHOD_RE = re.compile(
    r'(?m)^\s*public\s+function\s+(?P<name>\w+)\s*\((?P<args>[^)]*)\)'
    r'(?:\s*:\s*\??[\w\\|]+)?\s*\{'
)
_PHP_PARAM_RE = re.compile(
    r'(?:(?:\??[\w\\.]+\s+)|(?:private|protected|public|readonly|\s)+)*'
    r'\$(?P<name>\w+)(?:\s*=\s*[^,]+)?'
)


def parse_controller(php: str, source: Path | None = None
                     ) -> YiiController | None:
    src = strip_php_comments(php)
    cm = _CLASS_RE.search(src)
    if not cm:
        return None
    parent = cm.group('parent') or ''
    name = cm.group('name')
    if not name.endswith('Controller'):
        return None
    if parent and 'Controller' not in parent:
        return None
    ctrl_id = _camel_to_dashed(name[:-len('Controller')])
    rec = YiiController(
        source=source or Path('Controller.php'),
        class_name=name,
        controller_id=ctrl_id,
    )
    body_open = src.find('{', cm.end())
    if body_open < 0:
        return rec
    span = _balanced_block(src, body_open)
    if span is None:
        return rec
    body = src[span[0]:span[1]]

    # Parse `behaviors()` for VerbFilter mappings.
    rec.verb_map = _extract_verb_map(body)

    for mm in _ACTION_RE.finditer(body):
        action_name = mm.group('name')
        body_open_i = mm.end() - 1
        body_span = _balanced_block(body, body_open_i)
        if body_span is None:
            continue
        php_body = body[body_span[0]:body_span[1]]
        translated = _translate_body(php_body)
        args = [pm.group('name') for pm in _PHP_PARAM_RE.finditer(
            mm.group('args').strip())]
        # Action ID: actionLogin → login, actionMyView → my-view
        action_id = _camel_to_dashed(action_name[len('action'):])
        rec.actions.append(YiiAction(
            name=action_name, action_id=action_id, args=args,
            body=translated, raw_body=php_body,
        ))
    return rec


def _extract_verb_map(class_body: str) -> dict[str, list[str]]:
    """Pull out `'actions' => ['logout' => ['post']]` from a VerbFilter
    declaration in `behaviors()`. Uses bracket balancing so that the
    inner `[...]` arrays don't terminate the outer one prematurely."""
    out: dict[str, list[str]] = {}
    for vm in re.finditer(r"VerbFilter::class", class_body):
        # From the VerbFilter::class match, find the next 'actions' => [
        am = re.search(r"'actions'\s*=>\s*\[",
                        class_body[vm.end():vm.end() + 2000])
        if not am:
            continue
        actions_open = vm.end() + am.end() - 1
        actions_end = _balanced_bracket(class_body, actions_open)
        if actions_end is None:
            continue
        body = class_body[actions_open + 1:actions_end]
        # Each entry: 'name' => ['verb', ...]
        for em in re.finditer(
            r"'(?P<name>\w+)'\s*=>\s*\[(?P<verbs>[^\[\]]*)\]", body
        ):
            verbs = re.findall(r"'(\w+)'", em.group('verbs'))
            out[em.group('name')] = [v.upper() for v in verbs]
    return out


# ── URL rule parsing ──────────────────────────────────────────────

def parse_url_rules(php: str) -> list[tuple[str, str]]:
    """Pull `'rules' => ['<pattern>' => '<route>']` out of a Yii 2
    `urlManager` config block. Returns a list of (pattern, route)."""
    src = strip_php_comments(php)
    rules: list[tuple[str, str]] = []
    # Find `'urlManager' => [ ... 'rules' => [ ... ] ]`
    for um in re.finditer(
        r"'urlManager'\s*=>\s*\[", src,
    ):
        # Parse the bracket-balanced body of urlManager
        body_open = src.find('[', um.start())
        body_open = src.find('[', um.end() - 1)
        # Find matching `]`
        end = _balanced_bracket(src, body_open)
        if end is None:
            continue
        block = src[body_open + 1:end]
        # Find rules array
        rm = re.search(r"'rules'\s*=>\s*\[", block)
        if not rm:
            continue
        rules_open = block.find('[', rm.end() - 1)
        rules_end = _balanced_bracket(block, rules_open)
        if rules_end is None:
            continue
        rules_body = block[rules_open + 1:rules_end]
        for entry in re.finditer(
            r"'(?P<pat>[^']+)'\s*=>\s*'(?P<route>[^']+)'", rules_body,
        ):
            rules.append((entry.group('pat'), entry.group('route')))
    return rules


def _balanced_bracket(src: str, open_idx: int) -> int | None:
    """Find the matching `]` for a `[` at `open_idx`."""
    depth = 0
    in_str: str | None = None
    i = open_idx
    while i < len(src):
        ch = src[i]
        if in_str:
            if ch == '\\' and i + 1 < len(src):
                i += 2; continue
            if ch == in_str:
                in_str = None
            i += 1; continue
        if ch in ('"', "'"):
            in_str = ch; i += 1; continue
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


# ── Walker ────────────────────────────────────────────────────────

def parse_yii(app_dir: Path) -> YiiLiftResult:
    result = YiiLiftResult()
    if not app_dir.is_dir():
        return result

    # Controllers
    ctl_dir = app_dir / 'controllers'
    if ctl_dir.is_dir():
        for php_file in sorted(ctl_dir.rglob('*.php')):
            text = _safe_read(php_file)
            if not text.strip():
                result.skipped_files.append(php_file.relative_to(app_dir))
                continue
            ctl = parse_controller(text, source=php_file.relative_to(app_dir))
            if ctl is None:
                continue
            if ctl.actions:
                result.controllers.append(ctl)

    # Default routes — every action becomes a path
    # /<controller-id>/<action-id>/[args]
    for ctl in result.controllers:
        for a in ctl.actions:
            arg_segs = ''.join(f'<str:{n}>/' for n in a.args)
            base = f'{ctl.controller_id}/{a.action_id}/'
            full = base + arg_segs
            verbs = ctl.verb_map.get(a.action_id, ['ANY'])
            for v in verbs:
                result.routes.append(YiiRoute(
                    http_method=v, path=full,
                    controller=ctl.class_name, action=a.name,
                ))
        # Yii also routes /<controller-id> to actionIndex by default
        for a in ctl.actions:
            if a.action_id == 'index' and not a.args:
                verbs = ctl.verb_map.get('index', ['ANY'])
                for v in verbs:
                    result.routes.append(YiiRoute(
                        http_method=v,
                        path=f'{ctl.controller_id}/',
                        controller=ctl.class_name, action=a.name,
                    ))

    # Custom URL rules
    cfg = app_dir / 'config' / 'web.php'
    if cfg.is_file():
        result.custom_rules = parse_url_rules(_safe_read(cfg))

    return result


def _safe_read(p: Path) -> str:
    try:
        return p.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


# ── Renderers ─────────────────────────────────────────────────────

def render_urls(result: YiiLiftResult, app_label: str) -> str:
    out = [
        '"""Auto-generated by datalift liftyii.',
        '',
        'Yii 2 controllers translated into Django URL patterns. Each',
        'public actionFoo() method becomes a route at',
        '`/<controller-id>/<action-id>/<args>/`. VerbFilter HTTP-method',
        'pinning from `behaviors()` is honoured.',
        '"""',
        'from django.urls import path',
        'from . import views_yii as views',
        '',
        '',
    ]
    by_path: dict[str, list[YiiRoute]] = {}
    for r in result.routes:
        by_path.setdefault(r.path, []).append(r)
    out.append('urlpatterns = [')
    for path_, rs in by_path.items():
        if len(rs) == 1 and rs[0].http_method == 'ANY':
            r = rs[0]
            out.append(f"    path('{path_}', "
                       f"views.{r.controller}_{r.action}),")
        else:
            disp = '_dispatch_' + re.sub(r'[^a-zA-Z0-9]+', '_', path_).strip('_')
            disp = disp or '_dispatch_root'
            out.append(f"    path('{path_}', views.{disp}),")
    out.append(']')
    if result.custom_rules:
        out.append('')
        out.append('# Custom urlManager.rules from config/web.php:')
        for pat, route in result.custom_rules:
            out.append(f"#   '{pat}' => '{route}'  # PORTER: add as explicit path")
    out.append('')
    for path_, rs in by_path.items():
        if len(rs) == 1 and rs[0].http_method == 'ANY':
            continue
        disp = '_dispatch_' + re.sub(r'[^a-zA-Z0-9]+', '_', path_).strip('_')
        disp = disp or '_dispatch_root'
        out.append('')
        out.append(f'def {disp}(request, *args, **kwargs):')
        out.append('    method = request.method')
        for r in rs:
            view = f'views.{r.controller}_{r.action}'
            out.append(f"    if method == '{r.http_method}':")
            out.append(f'        return {view}(request, *args, **kwargs)')
        out.append("    from django.http import HttpResponseNotAllowed")
        verbs = sorted({r.http_method for r in rs if r.http_method != 'ANY'})
        out.append(f"    return HttpResponseNotAllowed({verbs!r})")
    return '\n'.join(out)


def render_views(result: YiiLiftResult) -> str:
    out = [
        '"""Auto-generated by datalift liftyii.',
        '',
        'Yii 2 actions translated into Django view functions. Yii\'s',
        '`$this->render`, `$this->goHome`, `Yii::$app->user/session`,',
        '`Yii::$app->request->post/get`, and ActiveRecord queries',
        'are translated to Django equivalents. ActiveRecord remains',
        'a porter marker since Django\'s ORM uses model imports.',
        '"""',
        'from django.http import HttpResponse, JsonResponse',
        'from django.shortcuts import redirect, render',
        '',
        '',
    ]
    for ctl in result.controllers:
        for a in ctl.actions:
            arg_list = ['request'] + a.args
            out.append(f'def {ctl.class_name}_{a.name}'
                       f'({", ".join(arg_list)}):')
            body = a.body or 'pass'
            for line in body.splitlines() or ['pass']:
                if not line.strip():
                    out.append('')
                else:
                    out.append('    ' + line)
            out.append('')
    return '\n'.join(out)


def render_worklist(result: YiiLiftResult, app_label: str,
                    app_dir: Path) -> str:
    lines = [
        f'# liftyii worklist — {app_dir.name}',
        '',
        f'Target app: `{app_label}`. Generated by `datalift liftyii`.',
        '',
        f'## Routes ({len(result.routes)})',
        '',
    ]
    for r in result.routes:
        lines.append(f'- `{r.http_method:>6} {r.path}` → '
                     f'`{r.controller}::{r.action}`')
    lines.append('')
    lines.append(f'## Controllers ({len(result.controllers)})')
    lines.append('')
    for c in result.controllers:
        lines.append(f'- `{c.source}` — `{c.class_name}` '
                     f'(id=`{c.controller_id}`, {len(c.actions)} action(s))')
    if result.custom_rules:
        lines.append('')
        lines.append(f'## Custom URL rules ({len(result.custom_rules)})')
        lines.append('')
        for pat, route in result.custom_rules:
            lines.append(f'- `{pat}` → `{route}` _(porter must add to urls.py)_')
    return '\n'.join(lines)


def apply(result: YiiLiftResult, project_root: Path,
          app_label: str, dry_run: bool = False) -> list[str]:
    log: list[str] = []
    if not result.routes and not result.controllers:
        return log
    app_dir = project_root / app_label
    if not dry_run:
        app_dir.mkdir(parents=True, exist_ok=True)
    if result.routes:
        target = app_dir / 'urls_yii.py'
        if not dry_run:
            target.write_text(render_urls(result, app_label), encoding='utf-8')
        log.append(f'urls      → {target.relative_to(project_root)} '
                   f'({len(result.routes)} route(s))')
    if result.controllers:
        target = app_dir / 'views_yii.py'
        if not dry_run:
            target.write_text(render_views(result), encoding='utf-8')
        action_count = sum(len(c.actions) for c in result.controllers)
        log.append(f'views     → {target.relative_to(project_root)} '
                   f'({len(result.controllers)} controller(s), '
                   f'{action_count} action(s))')
    return log
