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
    # WP's the_title() lets editor-supplied HTML through (italics,
    # superscript, etc.), so render |safe to match WP behaviour.
    inner = '{{ post.title|default:""|safe }}'
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


def _t_embed(attrs, inner_html, lifter):
    """A wp:embed block. WP detects the URL provider and emits an
    iframe; we do the same for the common providers, fall back to
    a plain link otherwise. Block name `embed` (newer) and
    `core-embed/<provider>` (legacy) both flow here via aliases."""
    url = (attrs.get('url', '') or '').strip()
    provider = (attrs.get('providerNameSlug', '') or '').lower()
    # Sniff inner_html for the URL if attrs don't carry it (legacy
    # core-embed serialised the URL between the comments).
    if not url and inner_html:
        m = re.search(r'https?://[^\s<>"\']+', inner_html)
        if m:
            url = m.group(0)
    if not provider:
        for tag in ('youtube', 'youtu.be', 'vimeo', 'twitter', 'x.com',
                     'instagram', 'facebook', 'tiktok', 'soundcloud',
                     'spotify', 'wordpress.tv'):
            if tag in url.lower():
                provider = tag.replace('youtu.be', 'youtube').replace(
                    'x.com', 'twitter').replace('.', '_')
                break
    embed_url = url
    if 'youtube' in (provider or url.lower()):
        m = re.search(r'(?:v=|youtu\.be/|/embed/)([\w-]+)', url)
        if m:
            embed_url = f'https://www.youtube.com/embed/{m.group(1)}'
    elif 'vimeo' in (provider or url.lower()):
        m = re.search(r'vimeo\.com/(\d+)', url)
        if m:
            embed_url = f'https://player.vimeo.com/video/{m.group(1)}'
    if embed_url and embed_url != url:
        body = (f'<iframe class="wp-block-embed__iframe" '
                f'src="{embed_url}" width="560" height="315" '
                f'frameborder="0" allowfullscreen></iframe>')
    elif url:
        body = (f'<a href="{url}" class="wp-block-embed__link" '
                f'rel="noopener">{url}</a>')
    else:
        body = inner_html
    return (f'<figure class="wp-block-embed is-provider-{provider}">'
            f'{body}</figure>')


def _t_latest_posts(attrs, inner_html, lifter):
    """The "latest posts" widget. Reads {{ latest_posts }} from
    context (a list of objects with .title, .get_absolute_url,
    .published_at) — view supplies it."""
    n = attrs.get('postsToShow', 5)
    return (
        f'<ul class="wp-block-latest-posts" data-count="{n}">\n'
        f'  {{% for p in latest_posts|default_if_none:""|slice:":{n}" %}}\n'
        '    <li><a href="{{ p.get_absolute_url }}">'
        '{{ p.title|safe }}</a> '
        '<time>{{ p.published_at|date:"F j, Y" }}</time></li>\n'
        '  {% empty %}\n'
        '    <li><em>No recent posts.</em></li>\n'
        '  {% endfor %}\n'
        '</ul>'
    )


def _t_latest_comments(attrs, inner_html, lifter):
    n = attrs.get('commentsToShow', 5)
    return (
        f'<ul class="wp-block-latest-comments" data-count="{n}">\n'
        f'  {{% for c in latest_comments|default_if_none:""'
        f'|slice:":{n}" %}}\n'
        '    <li><span class="wp-block-latest-comments__author">'
        '{{ c.comment_author|default:"Anonymous" }}</span> on '
        '<a href="/post/{{ c.comment_post_id }}/">'
        '{{ c.post_title|default:"a post" }}</a></li>\n'
        '  {% empty %}\n'
        '    <li><em>No comments yet.</em></li>\n'
        '  {% endfor %}\n'
        '</ul>'
    )


def _t_archives(attrs, inner_html, lifter):
    """Monthly archive list — reads {{ archive_months }} (list of
    objects with .year, .month_name, .count, .url)."""
    return (
        '<ul class="wp-block-archives">\n'
        '  {% for m in archive_months|default_if_none:"" %}\n'
        '    <li><a href="{{ m.url }}">'
        '{{ m.month_name }} {{ m.year }}</a> '
        '({{ m.count }})</li>\n'
        '  {% endfor %}\n'
        '</ul>'
    )


def _t_tag_cloud(attrs, inner_html, lifter):
    return (
        '<div class="wp-block-tag-cloud">\n'
        '  {% for t in tag_cloud|default_if_none:"" %}\n'
        '    <a href="/tag/{{ t.slug }}/" '
        'style="font-size:{{ t.font_size|default:"1rem" }}">'
        '{{ t.name }}</a>\n'
        '  {% endfor %}\n'
        '</div>'
    )


def _t_calendar(attrs, inner_html, lifter):
    """Month-grid of post-bearing days. Reads {{ calendar_html }}
    pre-rendered from the view (rendering a calendar in pure
    template syntax is impractical)."""
    return ('<div class="wp-block-calendar">'
            '{{ calendar_html|default:""|safe }}'
            '</div>')


def _t_avatar(attrs, inner_html, lifter):
    size = attrs.get('size', 96)
    return (f'<img class="wp-block-avatar" width="{size}" height="{size}" '
            f'src="{{{{ avatar_url|default:"" }}}}" '
            f'alt="{{{{ avatar_alt|default:"" }}}}">')


def _t_loginout(attrs, inner_html, lifter):
    return ('<span class="wp-block-loginout">'
            '{% if request.user.is_authenticated %}'
            '<a href="/accounts/logout/">Log out</a>'
            '{% else %}'
            '<a href="/accounts/login/">Log in</a>'
            '{% endif %}'
            '</span>')


def _t_read_more(attrs, inner_html, lifter):
    label = attrs.get('content', 'Read more')
    return (f'<a class="wp-block-read-more" '
            f'href="{{{{ post.get_absolute_url }}}}">{label}</a>')


def _t_query_no_results(attrs, inner_html, lifter):
    return ('{% if not posts or posts|length == 0 %}'
            f'{inner_html or "<p>No posts found.</p>"}'
            '{% endif %}')


def _t_post_author_biography(attrs, inner_html, lifter):
    return ('<div class="wp-block-post-author-biography">'
            '{{ post.author.biography|default:""|safe }}'
            '</div>')


def _t_comments_title(attrs, inner_html, lifter):
    return ('<h3 class="wp-block-comments-title">'
            'Comments ({{ comments|length }})'
            '</h3>')


def _t_comment_template(attrs, inner_html, lifter):
    return (f'<ol class="wp-block-comment-template">\n'
            f'  {{% for c in comments %}}\n'
            f'    <li>{inner_html or ""}</li>\n'
            f'  {{% endfor %}}\n'
            f'</ol>')


def _t_comment_author_name(attrs, inner_html, lifter):
    return ('<span class="wp-block-comment-author-name">'
            '{{ c.comment_author|default:"Anonymous" }}'
            '</span>')


def _t_comment_content(attrs, inner_html, lifter):
    return ('<div class="wp-block-comment-content">'
            '{{ c.comment_content|linebreaks }}'
            '</div>')


def _t_comment_date(attrs, inner_html, lifter):
    return ('<time class="wp-block-comment-date">'
            '{{ c.comment_date|date:"F j, Y" }}'
            '</time>')


def _t_comment_reply_link(attrs, inner_html, lifter):
    return ('<a class="wp-block-comment-reply-link" '
            'href="#reply-{{ c.comment_id }}">Reply</a>')


def _t_comment_edit_link(attrs, inner_html, lifter):
    return ('{% if request.user.is_staff %}'
            '<a class="wp-block-comment-edit-link" '
            'href="/admin/wp/comment/{{ c.comment_id }}/change/">'
            'Edit</a>{% endif %}')


def _t_search(attrs, inner_html, lifter):
    """The WP search input. Emits a GET form posting back to the
    current URL with `?s=<term>` (the WP convention)."""
    label = attrs.get('label', 'Search')
    show_label = attrs.get('showLabel', True)
    placeholder = attrs.get('placeholder', '')
    button_text = attrs.get('buttonText', 'Search')
    label_html = (f'<label class="wp-block-search__label" '
                  f'for="wp-search">{label}</label>'
                  if show_label else '')
    return (
        '<form class="wp-block-search" method="get" role="search" '
        'action="/search/">'
        f'{label_html}'
        f'<input type="search" id="wp-search" name="s" '
        f'placeholder="{placeholder or label}" '
        f'value="{{{{ search_query|default:"" }}}}">'
        f'<button type="submit" '
        f'class="wp-block-search__button">{button_text}</button>'
        '</form>'
    )


def _t_pattern(attrs, inner_html, lifter):
    """A WP block pattern (reusable named markup, e.g.
    'twentytwentytwo/hidden-404'). The pattern markup lives in the
    theme's patterns/*.php files, which we don't read. Emit a
    porter-marker that surfaces the slug so a porter knows what to
    fill in."""
    slug = attrs.get('slug', 'unknown')
    lifter._porter(f'pattern {slug}')
    safe_slug = slug.replace('/', '_').replace('-', '_')
    return (f'<div class="wp-block-pattern" data-slug="{slug}">\n'
            f'  {{# PORTER: WP pattern {slug!r} — supply the markup, '
            f'or set context var pattern_{safe_slug} #}}\n'
            f'  {{{{ pattern_{safe_slug}|default:""|safe }}}}\n'
            f'</div>')


def _t_query_title(attrs, inner_html, lifter):
    """The archive title block — `Category: Foo`, `Tag: Bar`,
    `Year: 2023`, `Search results for: foo`, etc. Reads
    {{ archive_title }} from the view context."""
    kind = attrs.get('type', 'archive')
    return (f'<h1 class="wp-block-query-title" data-type="{kind}">'
            '{{ archive_title|default:"Archive" }}'
            '</h1>')


def _t_term_description(attrs, inner_html, lifter):
    """The term description block — renders {{ term_description }}
    from the view context (the wp_term_taxonomy.description column)."""
    return ('<div class="wp-block-term-description">'
            '{{ term_description|default:""|safe }}'
            '</div>')


def _t_post_navigation_link(attrs, inner_html, lifter):
    """Previous / next single-post navigation. Reads {{ prev_post }}
    or {{ next_post }} from the view context (objects with .title
    and .get_absolute_url)."""
    direction = attrs.get('type', 'next')
    var = 'prev_post' if direction == 'previous' else 'next_post'
    label_default = '← Previous' if direction == 'previous' else 'Next →'
    return (f'<nav class="wp-block-post-navigation-link">'
            f'{{% if {var} %}}'
            f'<a href="{{{{ {var}.get_absolute_url }}}}">'
            f'{label_default}: {{{{ {var}.title|safe }}}}'
            f'</a>'
            f'{{% endif %}}'
            f'</nav>')


def _t_post_comments(attrs, inner_html, lifter):
    """Emit a working default comment list. Reads `comments` from
    the view context — a queryset/iterable of objects with the WP
    schema (comment_author, comment_content, comment_date, etc.).
    The porter can swap this for a Django comments-app render."""
    lifter._porter('post-comments')
    return (
        '<div class="wp-block-post-comments">\n'
        '  {% if comments %}\n'
        '  <h3 class="wp-block-comments-title">'
        'Comments ({{ comments|length }})</h3>\n'
        '  <ol class="wp-block-comment-template">\n'
        '    {% for c in comments %}\n'
        '    <li class="wp-block-comment">\n'
        '      <div class="wp-block-comment-author-name">'
        '{{ c.comment_author|default:"Anonymous" }}</div>\n'
        '      <time class="wp-block-comment-date">'
        '{{ c.comment_date|date:"F j, Y" }}</time>\n'
        '      <div class="wp-block-comment-content">'
        '{{ c.comment_content|linebreaks }}</div>\n'
        '    </li>\n'
        '    {% endfor %}\n'
        '  </ol>\n'
        '  {% else %}\n'
        '  <p class="wp-block-comments-empty">No comments yet.</p>\n'
        '  {% endif %}\n'
        '  {# PORTER: replace with your comments app render #}\n'
        '</div>'
    )


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
    # WP stores wp:image as comment + an already-formed
    # <figure class="wp-block-image…"><img …/></figure>. Just keep
    # the inner HTML — wrapping again would nest two <figure>s.
    return inner_html


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


def _t_more(attrs, inner_html, lifter):
    # The <!--more--> separator. In single-post view we render
    # everything, so leave only an invisible anchor classic themes
    # can target. Theme CSS expects `<span id="more-…">` or similar;
    # emit a class-marked anchor with no text.
    return '<span class="wp-block-more"></span>'


def _t_nextpage(attrs, inner_html, lifter):
    # Page-break marker. WP paginates the_content() on this; the
    # lifted templates render the whole post in one go, so the
    # marker becomes invisible.
    return '<span class="wp-block-nextpage" aria-hidden="true"></span>'


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
    'query-title':                _t_query_title,
    'term-description':           _t_term_description,
    'post-navigation-link':       _t_post_navigation_link,
    'search':                     _t_search,
    'pattern':                    _t_pattern,
    'embed':                      _t_embed,
    'core-embed/youtube':         _t_embed,
    'core-embed/vimeo':           _t_embed,
    'core-embed/twitter':         _t_embed,
    'core-embed/instagram':       _t_embed,
    'core-embed/facebook':        _t_embed,
    'core-embed/tiktok':          _t_embed,
    'core-embed/wordpress-tv':    _t_embed,
    'core-embed/spotify':         _t_embed,
    'core-embed/soundcloud':      _t_embed,
    'latest-posts':               _t_latest_posts,
    'latest-comments':            _t_latest_comments,
    'archives':                   _t_archives,
    'tag-cloud':                  _t_tag_cloud,
    'calendar':                   _t_calendar,
    'avatar':                     _t_avatar,
    'loginout':                   _t_loginout,
    'read-more':                  _t_read_more,
    'query-no-results':           _t_query_no_results,
    'post-author-biography':      _t_post_author_biography,
    'comments':                   _t_default('comments'),
    'comments-title':             _t_comments_title,
    'comment-template':           _t_comment_template,
    'comment-author-name':        _t_comment_author_name,
    'comment-content':            _t_comment_content,
    'comment-date':               _t_comment_date,
    'comment-reply-link':         _t_comment_reply_link,
    'comment-edit-link':          _t_comment_edit_link,
    'comments-pagination':        _t_default('comments-pagination'),
    'comments-pagination-previous': _t_query_pagination_previous,
    'comments-pagination-numbers':  _t_query_pagination_numbers,
    'comments-pagination-next':   _t_query_pagination_next,
    'image':                      _t_image,
    'paragraph':                  _t_paragraph,
    'heading':                    _t_heading,
    'separator':                  _t_separator,
    'spacer':                     _t_spacer,
    'html':                       _t_html,
    'shortcode':                  _t_shortcode,
    # Static layout / content blocks. Their inner HTML is already
    # final (WP's editor stores rendered markup), so the only job
    # is to drop the comment markers — exactly what _t_default does.
    # Listing them here suppresses the "unknown block" porter count.
    'gallery':                    _t_default('gallery'),
    'cover':                      _t_default('cover'),
    'code':                       _t_default('code'),
    'preformatted':               _t_default('preformatted'),
    'verse':                      _t_default('verse'),
    'pullquote':                  _t_default('pullquote'),
    'quote':                      _t_default('quote'),
    'audio':                      _t_default('audio'),
    'video':                      _t_default('video'),
    'file':                       _t_default('file'),
    'media-text':                 _t_default('media-text'),
    'columns':                    _t_default('columns'),
    'column':                     _t_default('column'),
    'group':                      _t_default('group'),
    'buttons':                    _t_default('buttons'),
    'button':                     _t_default('button'),
    'table':                      _t_default('table'),
    'list':                       _t_default('list'),
    'list-item':                  _t_default('list-item'),
    'social-links':               _t_default('social-links'),
    'social-link':                _t_default('social-link'),
    'details':                    _t_default('details'),
    'footnotes':                  _t_default('footnotes'),
    'more':                       _t_more,
    'nextpage':                   _t_nextpage,
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


# ── Classic shortcode expansion ───────────────────────────────────
#
# Classic-format WP posts (the post-format / TUT corpus) use raw
# shortcodes that aren't wrapped in <!-- wp:shortcode --> blocks.
# The most-used ones in TUT are [caption] and [gallery]. Expand
# them to plain HTML so they render instead of leaking as text.

_SHORTCODE_ATTR_RE = re.compile(
    r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+))')


def _parse_shortcode_attrs(attr_str: str) -> dict:
    out = {}
    for m in _SHORTCODE_ATTR_RE.finditer(attr_str or ''):
        out[m.group(1)] = m.group(2) or m.group(3) or m.group(4) or ''
    return out


_CAPTION_RE = re.compile(
    r'\[caption([^\]]*)\](.*?)\[/caption\]',
    re.DOTALL | re.IGNORECASE)


def _expand_caption(m) -> str:
    attrs = _parse_shortcode_attrs(m.group(1))
    inner = (m.group(2) or '').strip()
    # Caption text comes either from caption= attr or from text
    # following the trailing </a> or <img/>.
    caption_text = attrs.get('caption', '')
    if not caption_text:
        # Strip the leading <a>...</a> or <img .../> and what
        # remains (if any) is the caption text.
        m2 = re.match(r'(\s*(?:<a[^>]*>)?<img[^>]*/?>(?:</a>)?)\s*(.*)',
                      inner, re.DOTALL | re.IGNORECASE)
        if m2:
            head, tail = m2.group(1), m2.group(2).strip()
            if tail:
                caption_text = tail
                inner = head
    cls_parts = ['wp-block-image']
    align = attrs.get('align', '')
    if align:
        cls_parts.append(align)
    width = attrs.get('width', '')
    style = f' style="width:{width}px"' if width.isdigit() else ''
    figcap = (f'<figcaption class="wp-element-caption">'
              f'{caption_text}</figcaption>') if caption_text else ''
    return (f'<figure class="{" ".join(cls_parts)}"{style}>'
            f'{inner}{figcap}</figure>')


_GALLERY_RE = re.compile(
    r'\[gallery([^\]]*)\]', re.IGNORECASE)


def _expand_gallery(m) -> str:
    attrs = _parse_shortcode_attrs(m.group(1))
    ids = attrs.get('ids', '')
    columns = attrs.get('columns', '3')
    if ids:
        # Render anchors per id — best-effort static placeholder
        # since we have no DB at template-lift time. Templates can
        # later override via a real {% gallery %} tag.
        items = ''.join(
            f'<figure class="wp-block-image gallery-item">'
            f'<a href="#attachment-{i.strip()}">'
            f'attachment {i.strip()}</a></figure>'
            for i in ids.split(',') if i.strip())
        body = items
    else:
        body = (
            '<p class="wp-block-gallery__placeholder">'
            '<em>gallery placeholder</em></p>')
    return (f'<figure class="wp-block-gallery '
            f'has-nested-images columns-{columns}">{body}</figure>')


def expand_classic_shortcodes(html: str) -> str:
    """Expand the [caption] and [gallery] shortcodes commonly seen
    in classic-format WP post bodies. Idempotent on shortcode-free
    input. Other shortcodes (audio/video/playlist/embed/...) are
    left as-is for downstream handling."""
    html = _CAPTION_RE.sub(_expand_caption, html)
    html = _GALLERY_RE.sub(_expand_gallery, html)
    return html


def lift_block_template(html: str, app_label: str = '') \
        -> tuple[str, list[str], int]:
    """Translate one block-template file's HTML to a Django template.
    Returns (django_html, blocks_seen, porter_marker_count).

    `app_label` (optional) prefixes any `{% include %}` paths so
    parts resolve under `<app>/parts/...`."""
    l = _BlockLifter(app_label=app_label)
    out = l.lift(html)
    out = expand_classic_shortcodes(out)
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
        '.wp-block-query-title { '
        'font-family: var(--wp--preset--font-family--source-serif-pro, '
        'serif); font-weight: 300; '
        'font-size: clamp(2rem, 4vw, 2.75rem); margin: 2rem 0; }\n'
        '.wp-block-search { display: flex; gap: 0.5rem; '
        'margin: 1rem 0 2rem; }\n'
        '.wp-block-search input[type=search] { flex: 1; '
        'padding: 0.5rem 0.75rem; '
        'border: 1px solid currentColor; '
        'background: var(--wp--preset--color--background, #fff); '
        'color: inherit; font-size: 1rem; }\n'
        '.wp-block-search__button { '
        'padding: 0.5rem 1rem; '
        'background: var(--wp--preset--color--primary, #1a4548); '
        'color: var(--wp--preset--color--background, #fff); '
        'border: 0; cursor: pointer; }\n'
        '.wp-block-comments-title { '
        'font-family: var(--wp--preset--font-family--source-serif-pro, '
        'serif); font-weight: 400; margin-top: 3rem; }\n'
        '.wp-block-comment { padding: 1rem 0; '
        'border-bottom: 1px solid currentColor; }\n'
        '.wp-block-comment-author-name { font-weight: 600; }\n'
        '.wp-block-comment-date { color: '
        'var(--wp--preset--color--primary, #1a4548); '
        'font-size: 0.9rem; }\n'
        '.wp-block-post-navigation-link { padding: 1rem 0; '
        'font-size: 0.95rem; }\n'
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
