"""Translate WordPress block themes (Twenty Twenty-Two and friends)
into Django templates.

Block themes — WordPress's "Full Site Editing" since 5.9 — replace
PHP template files with HTML files in `templates/` and `parts/`,
each marked up with WordPress block-comment syntax:

    <!-- wp:template-part {"slug":"header","tagName":"header"} /-->
    <!-- wp:query {"query":{"perPage":10,"postType":"post"}} -->
    <main class="wp-block-query"><!-- wp:post-template -->
    <!-- wp:post-title {"isLink":true} /-->
    <!-- wp:post-content /-->
    <!-- /wp:post-template --></main>
    <!-- /wp:query -->
    <!-- wp:template-part {"slug":"footer","tagName":"footer"} /-->

This module walks `templates/` + `parts/`, parses the block
markup, and emits Django templates. Static blocks (paragraph,
group, columns, separator, etc.) are stripped to their inner
HTML. Dynamic blocks (post-title, post-content, query, etc.) are
translated to their Django equivalents (`{{ post.title }}`,
`{{ post.content|safe }}`, `{% for post in posts %}`).

Pure Python, no LLM, no network.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Records ────────────────────────────────────────────────────────

@dataclass
class WpBlockTemplate:
    source: Path           # relative path under the theme dir
    name: str              # template name (e.g. 'index', 'page')
    kind: str              # 'template' or 'part'
    django_html: str       # translated Django template
    blocks_seen: list[str] = field(default_factory=list)
    porter_markers: int = 0


@dataclass
class WpBlockTheme:
    theme_dir: Path
    theme_json: dict | None = None
    templates: list[WpBlockTemplate] = field(default_factory=list)
    parts: list[WpBlockTemplate] = field(default_factory=list)
    skipped_files: list[Path] = field(default_factory=list)


# ── Block-comment parser ──────────────────────────────────────────

_BLOCK_HEAD = re.compile(r'<!--\s*wp:(?P<name>[\w/-]+)\s*')
_BLOCK_CLOSE = re.compile(r'<!--\s*/wp:(?P<name>[\w/-]+)\s*-->')


def _parse_attrs(raw: str | None) -> dict:
    """Block attributes are a JSON object (sometimes nested). Parse
    defensively — bad JSON shouldn't kill the lift."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _scan_json_object(s: str, start: int) -> int | None:
    """Given s[start] == '{', return the index of the matching '}' + 1.
    Tracks string literals so braces inside JSON strings don't fool us."""
    depth = 0
    in_str = False
    esc = False
    i = start
    n = len(s)
    while i < n:
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return None


def _find_block_open(html: str, start: int):
    """Find the next opening block comment from `start`. Returns a
    dict {name, attrs, self, start, end} or None.

    Handles nested JSON in attributes — the regex-based version
    couldn't span braces correctly."""
    while True:
        m = _BLOCK_HEAD.search(html, start)
        if m is None:
            return None
        i = m.end()
        n = len(html)
        attrs_raw = None
        if i < n and html[i] == '{':
            end = _scan_json_object(html, i)
            if end is None:
                # Malformed — skip past this attempt and keep scanning.
                start = m.end()
                continue
            attrs_raw = html[i:end]
            i = end
        # Skip whitespace.
        while i < n and html[i] in ' \t\r\n':
            i += 1
        is_self = False
        if i < n and html[i] == '/':
            is_self = True
            i += 1
            while i < n and html[i] in ' \t\r\n':
                i += 1
        if html[i:i + 3] != '-->':
            # Not actually a block comment — keep searching.
            start = m.end()
            continue
        return {
            'name': m.group('name'),
            'attrs': attrs_raw,
            'self': is_self,
            'start': m.start(),
            'end': i + 3,
        }


def _balanced_block_end(html: str, name: str, start: int) -> int | None:
    """Walk forward from `start` (just past the opening `<!-- wp:NAME ... -->`)
    and find the matching `<!-- /wp:NAME -->`. Counts nested
    same-named blocks so we don't close on an inner one."""
    depth = 1
    i = start
    n = len(html)
    while i < n:
        m_open = _find_block_open(html, i)
        m_close = _BLOCK_CLOSE.search(html, i)
        if m_close is None:
            return None
        if m_open is not None and m_open['start'] < m_close.start():
            # An inner open that's NOT self-closing AND matches name → depth++
            if not m_open['self'] and m_open['name'] == name:
                depth += 1
            i = m_open['end']
            continue
        if m_close.group('name') == name:
            depth -= 1
            if depth == 0:
                return m_close.start()
        i = m_close.end()
    return None


# ── Block translators ────────────────────────────────────────────

# Each translator returns the Django-template fragment for one
# block. Translators for self-closing blocks ignore `inner_html`.

def _t_template_part(attrs, inner_html, lifter):
    slug = attrs.get('slug', 'unnamed')
    tag = attrs.get('tagName', 'div')
    prefix = f'{lifter.app_label}/' if lifter.app_label else ''
    # Emit a Django {% include %} pointing at the parts/ dir.
    inc = f'{{% include "{prefix}parts/{slug}.html" %}}'
    return f'<{tag}>{inc}</{tag}>' if tag != 'div' else inc


def _t_post_title(attrs, inner_html, lifter):
    level = attrs.get('level', 2)
    is_link = attrs.get('isLink', False)
    inner = '{{ post.title|default:"" }}'
    if is_link:
        inner = f'<a href="{{{{ post.get_absolute_url }}}}">{inner}</a>'
    return f'<h{level} class="wp-block-post-title">{inner}</h{level}>'


def _t_post_content(attrs, inner_html, lifter):
    return ('<div class="wp-block-post-content entry-content">'
            '{{ post.content|safe }}</div>')


def _t_post_excerpt(attrs, inner_html, lifter):
    return ('<p class="wp-block-post-excerpt">'
            '{{ post.excerpt|default:""|safe }}</p>')


def _t_post_date(attrs, inner_html, lifter):
    fmt = attrs.get('format', 'F j, Y')
    # PHP date format → Django (basic correspondence; porter refines)
    php_to_django = {'F': 'F', 'j': 'j', 'Y': 'Y',
                     'M': 'M', 'd': 'd', 'm': 'm', 'y': 'y',
                     'H': 'H', 'i': 'i', 's': 's'}
    django_fmt = ''.join(php_to_django.get(c, c) for c in fmt)
    is_link = attrs.get('isLink', False)
    inner = f'{{{{ post.published_at|date:"{django_fmt}" }}}}'
    if is_link:
        inner = f'<a href="{{{{ post.get_absolute_url }}}}">{inner}</a>'
    return f'<time class="wp-block-post-date">{inner}</time>'


def _t_post_featured_image(attrs, inner_html, lifter):
    is_link = attrs.get('isLink', False)
    img = ('<img src="{{ post.featured_image.url|default:\'\' }}" '
           'alt="{{ post.featured_image.alt|default:\'\' }}" />')
    if is_link:
        img = f'<a href="{{{{ post.get_absolute_url }}}}">{img}</a>'
    return f'<figure class="wp-block-post-featured-image">{img}</figure>'


def _t_post_comments(attrs, inner_html, lifter):
    lifter._porter('post-comments')
    return ('<div class="wp-block-post-comments">'
            '{# PORTER: WP comment list — wire to your Django comments app #}'
            '</div>')


def _t_site_logo(attrs, inner_html, lifter):
    width = attrs.get('width', '')
    style = f' style="width:{width}px"' if width else ''
    return (f'<img class="wp-block-site-logo"{style} '
            f'src="{{{{ site.logo|default:\'\' }}}}" '
            f'alt="{{{{ site.name|default:\'\' }}}}" />')


def _t_site_title(attrs, inner_html, lifter):
    return ('<a href="{{ site.url|default:\'/\' }}" '
            'class="wp-block-site-title">'
            '{{ site.name|default:"" }}</a>')


def _t_site_tagline(attrs, inner_html, lifter):
    return ('<p class="wp-block-site-tagline">'
            '{{ site.tagline|default:"" }}</p>')


def _t_navigation(attrs, inner_html, lifter):
    lifter._porter('navigation')
    # Replace inner page-list / nav-link / submenu with a placeholder.
    return ('<nav class="wp-block-navigation">\n'
            '  {# PORTER: WP navigation block — wire to your Django nav menu #}\n'
            f'  {inner_html}\n'
            '</nav>')


def _t_page_list(attrs, inner_html, lifter):
    lifter._porter('page-list')
    return ('<ul class="wp-block-page-list">'
            '{# PORTER: WP page list — render menu from a Django context var #}'
            '</ul>')


def _t_query(attrs, inner_html, lifter):
    """A WP query loop. Children include `wp:post-template` which is
    the actual loop body; translate inner_html so `{% for ... %}` is
    inserted via the post-template handler.

    The WP source usually has a literal wrapper element (`<main
    class="wp-block-query">`) between the open and close comments —
    if it does, splice our data attributes into that tag instead of
    generating our own. Otherwise emit a fresh wrapper."""
    tag = attrs.get('tagName', 'div')
    query = attrs.get('query', {})
    per_page = query.get('perPage', 10)
    post_type = query.get('postType', 'post')
    data_attrs = (f'data-per-page="{per_page}" '
                  f'data-post-type="{post_type}"')
    stripped = inner_html.lstrip()
    m = re.match(r'<(\w+)\b([^>]*)>', stripped)
    if m and ('wp-block-query' in m.group(2) or m.group(1) == tag):
        head = inner_html[:len(inner_html) - len(stripped)]
        rest = stripped[m.end():]
        return f'{head}<{m.group(1)}{m.group(2)} {data_attrs}>{rest}'
    return (f'<{tag} class="wp-block-query" {data_attrs}>\n'
            f'{inner_html}\n'
            f'</{tag}>')


def _t_post_template(attrs, inner_html, lifter):
    """The loop body inside `wp:query`. inner_html is what gets
    rendered per post — wrap in a Django for-loop."""
    return (f'{{% for post in posts %}}\n'
            f'{inner_html}\n'
            f'{{% endfor %}}')


def _t_query_pagination(attrs, inner_html, lifter):
    return ('<nav class="wp-block-query-pagination">\n'
            f'{inner_html}\n'
            '</nav>')


def _t_query_pagination_previous(attrs, inner_html, lifter):
    return ('{% if posts.has_previous %}'
            '<a href="?page={{ posts.previous_page_number }}" '
            'class="wp-block-query-pagination-previous">← Previous</a>'
            '{% endif %}')


def _t_query_pagination_next(attrs, inner_html, lifter):
    return ('{% if posts.has_next %}'
            '<a href="?page={{ posts.next_page_number }}" '
            'class="wp-block-query-pagination-next">Next →</a>'
            '{% endif %}')


def _t_query_pagination_numbers(attrs, inner_html, lifter):
    return ('<span class="wp-block-query-pagination-numbers">'
            '{{ posts.number }} / {{ posts.paginator.num_pages }}'
            '</span>')


def _t_post_author(attrs, inner_html, lifter):
    return ('<span class="wp-block-post-author">'
            '{{ post.author.display_name|default:post.author.username|default:"" }}'
            '</span>')


def _t_post_terms(attrs, inner_html, lifter):
    term = attrs.get('term', 'category')
    lifter._porter(f'post-terms ({term})')
    return (f'<div class="wp-block-post-terms" data-taxonomy="{term}">'
            f'{{# PORTER: WP {term} terms — wire to a Django M2M #}}'
            f'</div>')


def _t_image(attrs, inner_html, lifter):
    # Static image block — just keep inner HTML, which is the <img>.
    return f'<figure class="wp-block-image">{inner_html}</figure>'


def _t_paragraph(attrs, inner_html, lifter):
    align = attrs.get('align', '')
    cls = f' style="text-align:{align}"' if align else ''
    return f'<p class="wp-block-paragraph"{cls}>{inner_html}</p>' \
           if inner_html.strip() and not inner_html.strip().startswith('<p') \
           else inner_html


def _t_heading(attrs, inner_html, lifter):
    level = attrs.get('level', 2)
    # WP normally puts an <h2> already inside; just keep it.
    if inner_html.strip().startswith('<h'):
        return inner_html
    return f'<h{level} class="wp-block-heading">{inner_html}</h{level}>'


def _t_separator(attrs, inner_html, lifter):
    return inner_html or '<hr class="wp-block-separator" />'


def _t_spacer(attrs, inner_html, lifter):
    height = attrs.get('height', 32)
    return (f'<div class="wp-block-spacer" '
            f'style="height:{height}px" aria-hidden="true"></div>')


def _t_html(attrs, inner_html, lifter):
    # Custom HTML block — pass through.
    return inner_html


def _t_shortcode(attrs, inner_html, lifter):
    lifter._porter('shortcode')
    return (f'{{# PORTER: WP shortcode {inner_html.strip()!r} — '
            f'translate to Django template tag #}}')


def _t_default(name):
    """Generic translator for blocks without a dedicated handler.
    Strip the wp:* comment, keep the inner HTML — works for the
    long tail of static layout blocks (group, columns, column,
    cover, gallery, etc.) since their inner HTML is already
    rendered."""
    def _impl(attrs, inner_html, lifter):
        return inner_html
    return _impl


_TRANSLATORS = {
    'template-part':              _t_template_part,
    'post-title':                 _t_post_title,
    'post-content':               _t_post_content,
    'post-excerpt':               _t_post_excerpt,
    'post-date':                  _t_post_date,
    'post-featured-image':        _t_post_featured_image,
    'post-comments':              _t_post_comments,
    'post-comments-form':         _t_post_comments,
    'post-author':                _t_post_author,
    'post-author-name':           _t_post_author,
    'post-terms':                 _t_post_terms,
    'site-logo':                  _t_site_logo,
    'site-title':                 _t_site_title,
    'site-tagline':               _t_site_tagline,
    'navigation':                 _t_navigation,
    'navigation-link':            _t_default('navigation-link'),
    'navigation-submenu':         _t_default('navigation-submenu'),
    'page-list':                  _t_page_list,
    'query':                      _t_query,
    'post-template':              _t_post_template,
    'query-pagination':           _t_query_pagination,
    'query-pagination-previous':  _t_query_pagination_previous,
    'query-pagination-next':      _t_query_pagination_next,
    'query-pagination-numbers':   _t_query_pagination_numbers,
    'image':                      _t_image,
    'paragraph':                  _t_paragraph,
    'heading':                    _t_heading,
    'separator':                  _t_separator,
    'spacer':                     _t_spacer,
    'html':                       _t_html,
    'shortcode':                  _t_shortcode,
}


# ── Per-template lift ─────────────────────────────────────────────

class _BlockLifter:
    """Walks the block-comment markup of one template file and
    emits a Django-template equivalent."""

    def __init__(self, app_label: str = '') -> None:
        self.blocks_seen: list[str] = []
        self.porter_count = 0
        self.app_label = app_label

    def _porter(self, msg: str) -> None:
        self.porter_count += 1

    def lift(self, html: str) -> str:
        out: list[str] = []
        i = 0
        n = len(html)
        while i < n:
            m = _find_block_open(html, i)
            if m is None:
                out.append(html[i:])
                break
            # Append any literal HTML between the previous block and this one.
            out.append(html[i:m['start']])
            name = m['name']
            attrs = _parse_attrs(m['attrs'])
            self.blocks_seen.append(name)
            if m['self']:
                # Self-closing block — no inner content.
                out.append(self._translate(name, attrs, ''))
                i = m['end']
                continue
            # Find matching close.
            close_at = _balanced_block_end(html, name, m['end'])
            if close_at is None:
                # Treat as self-closing; emit what we can.
                out.append(self._translate(name, attrs, ''))
                i = m['end']
                continue
            inner = html[m['end']:close_at]
            # Recurse into inner so nested blocks get translated too.
            inner_translated = self.lift(inner)
            out.append(self._translate(name, attrs, inner_translated))
            # Skip past the closing comment.
            close_match = _BLOCK_CLOSE.match(html, close_at)
            i = (close_match.end() if close_match else close_at)
        return ''.join(out)

    def _translate(self, name: str, attrs: dict, inner: str) -> str:
        translator = _TRANSLATORS.get(name)
        if translator is None:
            self._porter(f'unknown block wp:{name}')
            # Default behaviour — keep inner HTML, drop the comment markers.
            return inner
        return translator(attrs, inner, self)


def lift_block_template(html: str, app_label: str = '') \
        -> tuple[str, list[str], int]:
    """Translate one block-template file's HTML to a Django template.
    Returns (django_html, blocks_seen, porter_marker_count).

    `app_label` (optional) prefixes any `{% include %}` paths so
    parts resolve under `<app>/parts/...`."""
    l = _BlockLifter(app_label=app_label)
    out = l.lift(html)
    return out, l.blocks_seen, l.porter_count


# ── Theme walker ──────────────────────────────────────────────────

def parse_theme_json(theme_dir: Path) -> dict | None:
    p = theme_dir / 'theme.json'
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def parse_block_theme(theme_dir: Path,
                       app_label: str = '') -> WpBlockTheme:
    result = WpBlockTheme(theme_dir=theme_dir,
                            theme_json=parse_theme_json(theme_dir))
    if not theme_dir.is_dir():
        return result
    # Templates
    tpl_dir = theme_dir / 'templates'
    if tpl_dir.is_dir():
        for tpl in sorted(tpl_dir.glob('*.html')):
            try:
                src = tpl.read_text(encoding='utf-8', errors='replace')
            except OSError:
                result.skipped_files.append(tpl.relative_to(theme_dir))
                continue
            django_html, blocks, porter_n = lift_block_template(
                src, app_label=app_label)
            result.templates.append(WpBlockTemplate(
                source=tpl.relative_to(theme_dir),
                name=tpl.stem,
                kind='template',
                django_html=django_html,
                blocks_seen=blocks,
                porter_markers=porter_n,
            ))
    # Parts
    parts_dir = theme_dir / 'parts'
    if parts_dir.is_dir():
        for part in sorted(parts_dir.glob('*.html')):
            try:
                src = part.read_text(encoding='utf-8', errors='replace')
            except OSError:
                result.skipped_files.append(part.relative_to(theme_dir))
                continue
            django_html, blocks, porter_n = lift_block_template(
                src, app_label=app_label)
            result.parts.append(WpBlockTemplate(
                source=part.relative_to(theme_dir),
                name=part.stem,
                kind='part',
                django_html=django_html,
                blocks_seen=blocks,
                porter_markers=porter_n,
            ))
    return result


# ── Worklist + apply ──────────────────────────────────────────────

def render_worklist(result: WpBlockTheme, app_label: str) -> str:
    from collections import Counter
    block_counts: Counter = Counter()
    for t in result.templates + result.parts:
        block_counts.update(t.blocks_seen)
    lines = [
        f'# liftwpblock worklist — {result.theme_dir.name}',
        '',
        f'Target app: `{app_label}`. Generated by `datalift liftwpblock`.',
        '',
        f'## Templates ({len(result.templates)})',
        '',
    ]
    for t in result.templates:
        lines.append(f'- `{t.source}` → `templates/{app_label}/'
                     f'{t.name}.html` ({len(t.blocks_seen)} blocks, '
                     f'{t.porter_markers} porter marker(s))')
    lines.append('')
    lines.append(f'## Parts ({len(result.parts)})')
    lines.append('')
    for t in result.parts:
        lines.append(f'- `{t.source}` → `templates/{app_label}/parts/'
                     f'{t.name}.html` ({len(t.blocks_seen)} blocks, '
                     f'{t.porter_markers} porter marker(s))')
    if block_counts:
        lines.append('')
        lines.append('## Block frequency across the theme')
        lines.append('')
        for name, n in block_counts.most_common():
            handler = '✓' if name in _TRANSLATORS else '⚠ porter'
            lines.append(f'- `wp:{name}` × {n} — {handler}')
    if result.theme_json:
        lines.append('')
        lines.append('## theme.json')
        lines.append('')
        lines.append('Global styles + settings extracted to '
                     '`<app>/wp_theme.json` for the porter to wire into '
                     'Django settings or context-processor.')
    return '\n'.join(lines)


def render_base_html(theme_json: dict | None, app_label: str) -> str:
    """Synthesise a starter `base.html` that wires `theme.json` colors,
    fonts, sizes, and spacing tokens into CSS custom properties using
    WordPress's `--wp--preset--*` / `--wp--custom--*` naming. Designed
    so the lifted block templates render with the original theme's
    look out-of-the-box; the porter is meant to edit this file."""
    css_vars: list[str] = []
    settings = (theme_json or {}).get('settings', {})
    palette = (settings.get('color') or {}).get('palette', []) or []
    for c in palette:
        slug = c.get('slug', '')
        color = c.get('color', '')
        if slug and color:
            css_vars.append(f'    --wp--preset--color--{slug}: {color};')
    fonts = (settings.get('typography') or {}).get('fontFamilies', []) or []
    for f in fonts:
        slug = f.get('slug', '')
        family = f.get('fontFamily', '')
        if slug and family:
            css_vars.append(
                f'    --wp--preset--font-family--{slug}: {family};')
    font_sizes = (settings.get('typography') or {}).get('fontSizes', []) or []
    for fs in font_sizes:
        slug = fs.get('slug', '')
        size = fs.get('size', '')
        if slug and size:
            css_vars.append(f'    --wp--preset--font-size--{slug}: {size};')
    custom = settings.get('custom') or {}
    for group, items in custom.items():
        if not isinstance(items, dict):
            continue
        for k, v in items.items():
            if isinstance(v, dict):
                for k2, v2 in v.items():
                    css_vars.append(
                        f'    --wp--custom--{group}--{k}--{k2}: {v2};')
            else:
                css_vars.append(f'    --wp--custom--{group}--{k}: {v};')
    body_font = ('var(--wp--preset--font-family--source-serif-pro, '
                 'var(--wp--preset--font-family--system-font, serif))')
    body_color = 'var(--wp--preset--color--foreground, #111)'
    body_bg = 'var(--wp--preset--color--background, #fff)'
    css_var_block = '\n'.join(css_vars) if css_vars else \
        '    /* no theme.json — supply CSS variables manually */'
    return (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,'
        'initial-scale=1">\n'
        f'<title>{{% block title %}}{{{{ site.name|default:"Site" }}}}'
        f'{{% endblock %}}</title>\n'
        '<style>\n'
        ':root {\n'
        f'{css_var_block}\n'
        '}\n'
        f'body {{ margin: 0; font-family: {body_font}; '
        f'color: {body_color}; background: {body_bg}; '
        'line-height: 1.6; font-size: '
        'var(--wp--preset--font-size--medium, 1.125rem); }\n'
        'a { color: var(--wp--preset--color--primary, #1a4548); }\n'
        'img { max-width: 100%; height: auto; }\n'
        'main, header, footer { padding: 0 '
        'var(--wp--custom--spacing--outer, 1.25rem); }\n'
        '.wp-block-group, .wp-block-columns { '
        'max-width: 920px; margin-left: auto; margin-right: auto; '
        'padding-top: 1rem; padding-bottom: 1rem; }\n'
        '.wp-block-columns { display: flex; gap: 2rem; flex-wrap: wrap; }\n'
        '.wp-block-column { flex: 1; min-width: 250px; }\n'
        '.wp-block-post-title { '
        'font-family: var(--wp--preset--font-family--source-serif-pro, '
        'serif); font-weight: 300; line-height: 1.15; margin: 1rem 0; }\n'
        '.wp-block-post-title a { text-decoration: none; }\n'
        '.wp-block-post-date { '
        'color: var(--wp--preset--color--primary, #1a4548); '
        'font-size: var(--wp--preset--font-size--small, 1rem); }\n'
        '.wp-block-site-logo { display: block; margin: 1rem 0; }\n'
        '.wp-block-site-title { '
        'font-family: var(--wp--preset--font-family--source-serif-pro, '
        'serif); font-size: 1.5rem; text-decoration: none; '
        'color: inherit; }\n'
        '.wp-block-separator { '
        'border: 0; border-top: 1px solid currentColor; '
        'opacity: 0.4; margin: 2rem 0; }\n'
        '.wp-block-query-pagination { '
        'display: flex; gap: 1rem; justify-content: space-between; '
        'padding: 2rem 0; }\n'
        '</style>\n'
        '{% block extra_head %}{% endblock %}\n'
        '</head>\n'
        '<body class="wp-site-blocks">\n'
        '{% block content %}{% endblock %}\n'
        '</body>\n'
        '</html>\n'
    )


def _wrap_in_extends(html: str, app_label: str) -> str:
    """Wrap a lifted page template body in {% extends ... %}{% block %}
    so it can be rendered against the synthesised base.html."""
    return (f'{{% extends "{app_label}/base.html" %}}\n'
            f'{{% block content %}}\n{html}\n{{% endblock %}}\n')


def apply(result: WpBlockTheme, project_root: Path,
          app_label: str, dry_run: bool = False) -> list[str]:
    log: list[str] = []
    if not result.templates and not result.parts:
        return log
    tpl_root = project_root / 'templates' / app_label
    if not dry_run:
        tpl_root.mkdir(parents=True, exist_ok=True)
        (tpl_root / 'parts').mkdir(parents=True, exist_ok=True)
    base_target = tpl_root / 'base.html'
    if not dry_run and not base_target.exists():
        base_target.write_text(
            render_base_html(result.theme_json, app_label),
            encoding='utf-8')
        log.append(f'base.html → templates/{app_label}/base.html')
    for t in result.templates:
        target = tpl_root / f'{t.name}.html'
        if not dry_run:
            target.write_text(_wrap_in_extends(t.django_html, app_label),
                              encoding='utf-8')
    for t in result.parts:
        target = tpl_root / 'parts' / f'{t.name}.html'
        if not dry_run:
            target.write_text(t.django_html, encoding='utf-8')
    if result.theme_json and not dry_run:
        app_dir = project_root / app_label
        app_dir.mkdir(parents=True, exist_ok=True)
        (app_dir / 'wp_theme.json').write_text(
            json.dumps(result.theme_json, indent=2, ensure_ascii=False) + '\n',
            encoding='utf-8',
        )
    log.append(f'templates → templates/{app_label}/ '
               f'({len(result.templates)} template(s), '
               f'{len(result.parts)} part(s))')
    if result.theme_json:
        log.append(f'theme.json → {app_label}/wp_theme.json')
    return log
