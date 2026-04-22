"""Inventory and HTML-rewrite a legacy site tree for Django port.

Pure Python, no Django imports. The management command
:mod:`datalift.management.commands.liftsite` wraps this to produce the
actual file moves and the ``worklist.md`` artifact.

Scope (Phase 1): HTML + JS + CSS + static assets. PHP files are
inventoried and flagged but never read/rewritten — that is Phase 2
after a sensitive-string scanner is added.

The rewrites it performs are deliberately conservative. Nothing with
an existing Django template marker (``{% ``, ``{{ ``) is touched:
we assume a human has already started converting that file and
respect their in-progress work. For clean HTML files, the rewriter:

* retargets relative asset URLs (``href``, ``src``) to ``{% static %}``
* resolves legacy URLs via an optional ``url_map`` to ``{% url %}``
* adds ``{% load static %}`` at the top if it added any ``{% static %}``

Anything it cannot resolve (unknown URLs, JS fetch endpoints, form
actions, PHP files) is recorded in a structured worklist so the
human or Claude can walk through it item by item without re-crawling.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# ── Extension routing ──────────────────────────────────────────────

_HTML_EXTS = {'.html', '.htm', '.tpl'}
_JS_EXTS = {'.js', '.mjs'}
_CSS_EXTS = {'.css'}
_ASSET_EXTS = {
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico',
    '.woff', '.woff2', '.ttf', '.otf', '.eot',
    '.mp3', '.mp4', '.webm', '.ogg', '.wav',
    '.pdf',
}
_PHP_EXTS = {'.php', '.phtml', '.inc'}


def classify(path: Path) -> str:
    """Return a bucket name: html, js, css, asset, php, other."""
    ext = path.suffix.lower()
    if ext in _HTML_EXTS:
        return 'html'
    if ext in _JS_EXTS:
        return 'js'
    if ext in _CSS_EXTS:
        return 'css'
    if ext in _ASSET_EXTS:
        return 'asset'
    if ext in _PHP_EXTS:
        return 'php'
    return 'other'


# Top-level directory names we recognize as "already bucketed" in the
# source tree — stripped before appending to avoid `static/app/js/js/…`.
_BUCKET_DIR_ALIASES = {
    'js': {'js', 'scripts', 'javascript'},
    'css': {'css', 'styles', 'stylesheets'},
    'assets': {'images', 'img', 'assets', 'fonts', 'media'},
}


def _strip_bucket_prefix(bucket: str, rel: Path) -> Path:
    aliases = _BUCKET_DIR_ALIASES.get(bucket)
    if aliases and len(rel.parts) > 1 and rel.parts[0] in aliases:
        return Path(*rel.parts[1:])
    return rel


def target_relpath(bucket: str, app: str, rel: Path) -> Path | None:
    """Where a source file lands under the Django project.

    ``rel`` is the path relative to the source tree root. Returns
    ``None`` for files we don't route in Phase 1 (php, other).
    """
    if bucket == 'html':
        return Path('templates') / app / rel
    if bucket == 'js':
        return Path('static') / app / 'js' / _strip_bucket_prefix('js', rel)
    if bucket == 'css':
        return Path('static') / app / 'css' / _strip_bucket_prefix('css', rel)
    if bucket == 'asset':
        return (
            Path('static') / app / 'assets'
            / _strip_bucket_prefix('assets', rel)
        )
    return None


# ── HTML rewriting ─────────────────────────────────────────────────

# Detect "this file already has Django in it" — we then don't rewrite.
_DJANGO_MARKER_RE = re.compile(r'\{%\s|\{\{\s|\{\{-|\{#')

# Asset-ish attributes with their tag — href mostly for <link>, src for
# <script>/<img>/<source>/<iframe>/<video>/<audio>. We don't try to be
# picky about tags here: we just match relative-looking values on
# those attributes. Anything that starts with a scheme, //, or {
# (template code) is skipped.
_ATTR_URL_RE = re.compile(
    r'''(?P<attr>\b(?:href|src|poster|action|data-src))\s*=\s*'''
    r'''(?P<q>['"])(?P<url>[^'"]+)(?P=q)''',
    re.IGNORECASE,
)


def _is_relative_asset(url: str) -> bool:
    if not url:
        return False
    if url.startswith(('http://', 'https://', '//', 'mailto:', 'tel:',
                       'javascript:', 'data:', '#')):
        return False
    if url.startswith('{'):  # already a Django/Jinja tag
        return False
    return True


def _asset_category(url: str) -> str | None:
    """Return 'js' | 'css' | 'assets' for a URL path, else None."""
    # Strip query/fragment before looking at extension.
    clean = url.split('?', 1)[0].split('#', 1)[0]
    ext = Path(clean).suffix.lower()
    if ext in _JS_EXTS:
        return 'js'
    if ext in _CSS_EXTS:
        return 'css'
    if ext in _ASSET_EXTS:
        return 'assets'
    return None


def _static_path(app: str, url: str) -> str:
    """Convert a legacy relative URL to the ``<app>/<bucket>/<name>`` form.

    The result is suitable as the argument to ``{% static '…' %}``.
    """
    clean = url.split('?', 1)[0].split('#', 1)[0]
    # Drop leading slashes and ./
    while clean.startswith(('/', './')):
        clean = clean.lstrip('/').removeprefix('./')
    # If someone already pointed at 'static/…', use it as-is.
    if clean.startswith(f'static/{app}/'):
        return clean[len('static/'):]
    bucket = _asset_category(clean) or 'assets'
    # Use just the basename under the bucket — original subfolders are
    # flattened the same way target_relpath does for the file itself.
    name = Path(clean).name
    return f'{app}/{bucket}/{name}'


@dataclass
class UrlMapEntry:
    """A legacy-URL → Django-URL rule.

    Exact matches (``/about.php``) are checked before regex patterns.
    Regex patterns use named groups whose names become keyword
    arguments in the emitted ``{% url %}`` tag.
    """
    pattern: str
    name: str
    is_regex: bool = False
    _compiled: re.Pattern | None = None

    def match(self, url: str) -> tuple[str, dict[str, str]] | None:
        clean = url.split('?', 1)[0].split('#', 1)[0]
        if self.is_regex:
            if self._compiled is None:
                self._compiled = re.compile(self.pattern)
            m = self._compiled.match(clean)
            if m:
                return self.name, m.groupdict()
            return None
        if clean == self.pattern:
            return self.name, {}
        return None


def build_url_map(entries: dict[str, str]) -> list[UrlMapEntry]:
    """Turn a ``{pattern: name}`` JSON dict into match-order rules.

    Keys starting with ``^`` are treated as regex, exact otherwise.
    Exact matches take priority: we sort exact first.
    """
    rules: list[UrlMapEntry] = []
    for pat, name in entries.items():
        is_regex = pat.startswith('^') or '(?' in pat
        rules.append(UrlMapEntry(pat, name, is_regex=is_regex))
    rules.sort(key=lambda r: (r.is_regex, r.pattern))
    return rules


def has_django_markers(text: str) -> bool:
    return bool(_DJANGO_MARKER_RE.search(text))


@dataclass
class RewriteResult:
    text: str
    added_static: bool
    unresolved_urls: list[tuple[str, str]] = field(default_factory=list)
    form_actions: list[str] = field(default_factory=list)
    rewrote: int = 0


def rewrite_html(
    text: str,
    app: str,
    url_rules: list[UrlMapEntry] | None = None,
) -> RewriteResult:
    """Rewrite relative asset/URL attributes in a pristine HTML file.

    Returns the new text plus a record of what could not be resolved.
    """
    url_rules = url_rules or []
    added_static = False
    unresolved: list[tuple[str, str]] = []
    form_actions: list[str] = []
    rewrote = 0

    def _sub(m: re.Match) -> str:
        nonlocal added_static, rewrote
        attr = m.group('attr').lower()
        q = m.group('q')
        url = m.group('url')
        if not _is_relative_asset(url):
            return m.group(0)
        # Try URL map first (for page-level links that hit other views).
        if attr in ('href', 'action'):
            for rule in url_rules:
                hit = rule.match(url)
                if hit:
                    name, kwargs = hit
                    if kwargs:
                        args = ' '.join(f'{k}={v!r}' for k, v in kwargs.items())
                        replacement = f"{{% url '{name}' {args} %}}"
                    else:
                        replacement = f"{{% url '{name}' %}}"
                    rewrote += 1
                    return f'{m.group("attr")}={q}{replacement}{q}'
        # Fall back to {% static %} for asset-looking URLs.
        if _asset_category(url) is not None:
            static_arg = _static_path(app, url)
            added_static = True
            rewrote += 1
            replacement = f"{{% static '{static_arg}' %}}"
            return f'{m.group("attr")}={q}{replacement}{q}'
        # Unresolved — leave as-is, record for the worklist.
        unresolved.append((attr, url))
        if attr == 'action':
            form_actions.append(url)
        return m.group(0)

    new_text = _ATTR_URL_RE.sub(_sub, text)

    if added_static and '{% load static %}' not in new_text:
        # Inject after <!DOCTYPE …> if present, otherwise at top.
        if new_text.lstrip().lower().startswith('<!doctype'):
            idx = new_text.find('>')
            if idx != -1:
                new_text = (
                    new_text[: idx + 1]
                    + '\n{% load static %}'
                    + new_text[idx + 1 :]
                )
            else:
                new_text = '{% load static %}\n' + new_text
        else:
            new_text = '{% load static %}\n' + new_text

    return RewriteResult(
        text=new_text,
        added_static=added_static,
        unresolved_urls=unresolved,
        form_actions=form_actions,
        rewrote=rewrote,
    )


# ── JS scan (flag only, never rewrite) ─────────────────────────────

_JS_ENDPOINT_RE = re.compile(
    r"""(?:fetch|axios\.(?:get|post|put|delete|patch)|"""
    r"""\$\.(?:get|post|ajax)|XMLHttpRequest)\s*\(\s*"""
    r"""(?P<q>['"`])(?P<url>[^'"`]+)(?P=q)""",
)


def scan_js_endpoints(text: str) -> list[str]:
    return [m.group('url') for m in _JS_ENDPOINT_RE.finditer(text)]


# ── Inventory + worklist ───────────────────────────────────────────

@dataclass
class FileRecord:
    src: Path                 # absolute
    rel: Path                 # relative to source root
    bucket: str               # html/js/css/asset/php/other
    dst: Path | None          # relative to project root, or None
    partial: bool = False     # HTML had Django markers
    unresolved_urls: list[tuple[str, str]] = field(default_factory=list)
    form_actions: list[str] = field(default_factory=list)
    js_endpoints: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    rewrote: int = 0


def walk_site(root: Path) -> Iterable[Path]:
    """Yield all regular files under ``root``, skipping hidden/VCS dirs."""
    skip_dirnames = {'.git', '.hg', '.svn', 'node_modules', '__pycache__'}
    for p in sorted(root.rglob('*')):
        if not p.is_file():
            continue
        if any(part in skip_dirnames or part.startswith('.')
               for part in p.relative_to(root).parts[:-1]):
            continue
        yield p


def inventory(
    root: Path,
    app: str,
    url_rules: list[UrlMapEntry] | None = None,
    asset_map: dict[str, str] | None = None,
) -> list[FileRecord]:
    """Walk the site and produce one :class:`FileRecord` per file.

    For HTML files this also runs the rewrite pass (or detects
    partial-conversion). JS files are scanned for endpoint URLs. The
    records carry enough info to write the worklist and to either
    copy/move the file verbatim or write rewritten HTML.
    """
    url_rules = url_rules or []
    asset_map = asset_map or {}
    records: list[FileRecord] = []

    for src in walk_site(root):
        rel = src.relative_to(root)
        bucket = classify(src)
        dst = target_relpath(bucket, app, rel)

        # Asset-map override — lets the user redirect a single file.
        if asset_map and str(rel) in asset_map:
            dst = Path(asset_map[str(rel)])

        rec = FileRecord(src=src, rel=rel, bucket=bucket, dst=dst)

        if bucket == 'html':
            try:
                text = src.read_text(encoding='utf-8', errors='replace')
            except OSError as e:
                rec.notes.append(f'read error: {e}')
                records.append(rec)
                continue
            if has_django_markers(text):
                rec.partial = True
                rec.notes.append('already has Django markers — moved verbatim')
                if '{% static %}' in text and '{% load static %}' not in text:
                    rec.notes.append('uses {% static %} without {% load static %}')
            else:
                result = rewrite_html(text, app, url_rules)
                rec.unresolved_urls = result.unresolved_urls
                rec.form_actions = result.form_actions
                rec.rewrote = result.rewrote
                # Store the rewritten text on the record so the command
                # layer can write it without re-running the rewriter.
                rec.notes.append(f'rewrote {result.rewrote} attribute(s)')
                rec._rewritten_text = result.text  # type: ignore[attr-defined]

        elif bucket == 'js':
            try:
                text = src.read_text(encoding='utf-8', errors='replace')
                rec.js_endpoints = scan_js_endpoints(text)
            except OSError as e:
                rec.notes.append(f'read error: {e}')

        records.append(rec)
    return records


# ── Worklist rendering ─────────────────────────────────────────────

def render_worklist(records: list[FileRecord], app: str, root: Path) -> str:
    """Produce a markdown worklist suitable for a human or Claude."""
    partial = [r for r in records if r.bucket == 'html' and r.partial]
    unresolved: list[tuple[FileRecord, str, str]] = []
    for r in records:
        for attr, url in r.unresolved_urls:
            if attr != 'action':
                unresolved.append((r, attr, url))
    forms: list[tuple[FileRecord, str]] = []
    for r in records:
        for u in r.form_actions:
            forms.append((r, u))
    js_calls: list[tuple[FileRecord, str]] = []
    for r in records:
        for u in r.js_endpoints:
            js_calls.append((r, u))
    php = [r for r in records if r.bucket == 'php']
    other = [r for r in records if r.bucket == 'other']

    asset_count = sum(1 for r in records if r.bucket == 'asset')
    html_count = sum(1 for r in records if r.bucket == 'html')
    js_count = sum(1 for r in records if r.bucket == 'js')
    css_count = sum(1 for r in records if r.bucket == 'css')

    out: list[str] = []
    out.append(f'# liftsite worklist — {app}')
    out.append('')
    out.append(f'Source: `{root}`')
    out.append('')
    out.append('## Summary')
    out.append('')
    out.append(f'- HTML: {html_count} ({len(partial)} partial)')
    out.append(f'- JS: {js_count}')
    out.append(f'- CSS: {css_count}')
    out.append(f'- Assets: {asset_count}')
    out.append(f'- PHP (deferred to Phase 2): {len(php)}')
    out.append(f'- Other (unrouted): {len(other)}')
    out.append('')

    if partial:
        out.append('## Partial conversions (review & merge)')
        out.append('')
        for r in partial:
            notes = '; '.join(r.notes)
            out.append(f'- `{r.rel}` — {notes}')
        out.append('')

    if unresolved:
        out.append('## Unresolved URLs (add --url-map entries or hand-edit)')
        out.append('')
        for r, attr, url in unresolved:
            out.append(f'- `{r.rel}` — {attr}="{url}"')
        out.append('')

    if forms:
        out.append('## Forms pointing at legacy actions')
        out.append('')
        for r, url in forms:
            out.append(f'- `{r.rel}` — <form action="{url}">')
        out.append('')

    if js_calls:
        out.append('## JS endpoint calls (probably need URL rewriting)')
        out.append('')
        for r, url in js_calls:
            out.append(f'- `{r.rel}` — {url}')
        out.append('')

    if php:
        out.append('## PHP files (Phase 2)')
        out.append('')
        for r in php:
            size = r.src.stat().st_size
            out.append(f'- `{r.rel}` ({size} bytes)')
        out.append('')

    if other:
        out.append('## Unrouted files (manual decision)')
        out.append('')
        for r in other:
            out.append(f'- `{r.rel}`')
        out.append('')

    return '\n'.join(out) + '\n'


def apply_records(
    records: list[FileRecord],
    project_root: Path,
    move: bool = False,
    dry_run: bool = False,
) -> list[str]:
    """Copy/move files + write rewritten HTML. Returns action log."""
    log: list[str] = []
    for r in records:
        if r.dst is None:
            continue
        dst_abs = project_root / r.dst
        if dry_run:
            log.append(f'[dry] {r.bucket:5} {r.rel} → {r.dst}')
            continue
        dst_abs.parent.mkdir(parents=True, exist_ok=True)
        rewritten = getattr(r, '_rewritten_text', None)
        if r.bucket == 'html' and not r.partial and rewritten is not None:
            dst_abs.write_text(rewritten, encoding='utf-8')
            if move:
                r.src.unlink()
            log.append(f'rewrote {r.rel} → {r.dst}')
        else:
            if move:
                shutil.move(str(r.src), str(dst_abs))
            else:
                shutil.copy2(r.src, dst_abs)
            log.append(f'{"moved" if move else "copied"} {r.rel} → {r.dst}')
    return log
