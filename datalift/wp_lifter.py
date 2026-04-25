"""Translate a WordPress theme directory into Django templates + views.

Pure Python, no Django imports, no network, no LLM. The management
command :mod:`datalift.management.commands.liftwp` wraps this for the
file-writing side.

Scope (Phase 1): the *standard* WordPress theme files that almost
every theme has — ``index.php``, ``single.php``, ``page.php``,
``archive.php``, ``404.php``, ``header.php``, ``footer.php``,
``sidebar.php``, ``search.php`` — plus the public URL surface
(homepage, single post, single page, category/tag/date archives).
We assume the data half has already been datalifted (so the WP
models exist) and emit views that read from them.

What it can translate deterministically:

* The classic Loop (``if (have_posts()) : while (have_posts()) : the_post()``)
* Header/footer/sidebar includes (``get_header()``, etc.)
* The common ``the_*()`` and ``get_the_*()`` template tags
* ``bloginfo('name'|'description'|'charset')`` and ``language_attributes()``
* ``echo home_url()`` / ``echo site_url()`` / ``the_permalink()``
* ``wp_head()`` / ``wp_footer()`` → empty Django blocks
* Conditional/loop alternative syntax (``if (...) :`` ... ``endif;``)
* PHP comments (``//``, ``#``, ``/* */``)
* Short echo ``<?= expr ?>``

Everything else is preserved as a ``{# WP-LIFT? <original> #}``
marker in the output template AND recorded in the worklist so the
human can walk through it without re-crawling. Custom post types,
shortcodes, plugin hooks, AJAX handlers, theme options pages,
widgets, and admin screens are explicitly NOT translated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Standard WP theme file → Django template name ──────────────────

_THEME_FILE_TARGETS = {
    'index.php':    ('index.html',    'wp_index'),
    'single.php':   ('single.html',   'wp_single'),
    'page.php':     ('page.html',     'wp_page'),
    'archive.php':  ('archive.html',  'wp_archive'),
    'category.php': ('archive.html',  'wp_archive'),
    'tag.php':      ('archive.html',  'wp_archive'),
    'date.php':     ('archive.html',  'wp_archive'),
    '404.php':      ('404.html',      'wp_404'),
    'search.php':   ('search.html',   'wp_search'),
    'header.php':   ('header.html',   None),
    'footer.php':   ('footer.html',   None),
    'sidebar.php':  ('sidebar.html',  None),
    'searchform.php': ('searchform.html', None),
    'comments.php': ('comments.html', None),
}


@dataclass
class TemplateRecord:
    """One WordPress theme file → one Django template."""

    source: Path
    target_name: str          # e.g. 'index.html'
    view_name: str | None     # e.g. 'wp_index' (None for partials)
    body: str                 # translated Django HTML
    skipped: list[str] = field(default_factory=list)
    # PHP fragments we left behind as {# WP-LIFT? ... #}


@dataclass
class LiftResult:
    """Output of parse_theme()."""

    records: list[TemplateRecord] = field(default_factory=list)
    # Files we recognized but couldn't classify
    unhandled_files: list[Path] = field(default_factory=list)
    # Files we never opened (assets passed through to static/)
    static_assets: list[Path] = field(default_factory=list)


# ── PHP comment + tag stripping ────────────────────────────────────

_PHP_OPEN = re.compile(r'<\?(?:php\b|=)')
_PHP_CLOSE = re.compile(r'\?>')

# Inside PHP, strip block + line comments. We are not building a real
# PHP parser; we're stripping enough to make the patterns below match.
_PHP_COMMENT_BLOCK = re.compile(r'/\*.*?\*/', re.DOTALL)
_PHP_COMMENT_LINE = re.compile(r'(?m)(?:^|\s)(?://|\#).*$')


def _strip_php_comments(php: str) -> str:
    php = _PHP_COMMENT_BLOCK.sub('', php)
    php = _PHP_COMMENT_LINE.sub('', php)
    return php


# ── Template tag → Django translation table ───────────────────────
#
# Each entry maps a regex (matched against a single trimmed PHP
# statement) to a Django snippet. Substitutions reference named groups.

_STMT_RULES: list[tuple[re.Pattern[str], str]] = [
    # Header / footer / sidebar includes -----------------------------
    (re.compile(r'^get_header\s*\(\s*\)\s*;?\s*$'),
     "{% include 'wp/header.html' %}"),
    (re.compile(r'^get_footer\s*\(\s*\)\s*;?\s*$'),
     "{% include 'wp/footer.html' %}"),
    (re.compile(r'^get_sidebar\s*\(\s*\)\s*;?\s*$'),
     "{% include 'wp/sidebar.html' %}"),
    (re.compile(r'^get_search_form\s*\(\s*\)\s*;?\s*$'),
     "{% include 'wp/searchform.html' %}"),
    (re.compile(r'^comments_template\s*\(\s*\)\s*;?\s*$'),
     "{% include 'wp/comments.html' %}"),

    # Loop control ---------------------------------------------------
    (re.compile(r'^if\s*\(\s*have_posts\s*\(\s*\)\s*\)\s*:\s*$'),
     '{% if posts %}'),
    (re.compile(r'^while\s*\(\s*have_posts\s*\(\s*\)\s*\)\s*:\s*the_post\s*\(\s*\)\s*;?\s*$'),
     '{% for post in posts %}'),
    (re.compile(r'^while\s*\(\s*have_posts\s*\(\s*\)\s*\)\s*:\s*$'),
     '{% for post in posts %}'),
    (re.compile(r'^the_post\s*\(\s*\)\s*;?\s*$'),
     ''),  # already iterated; drop
    (re.compile(r'^endwhile\s*;?\s*$'),
     '{% endfor %}'),
    (re.compile(r'^else\s*:\s*$'),
     '{% else %}'),
    (re.compile(r'^elseif\s*\(\s*have_posts\s*\(\s*\)\s*\)\s*:\s*$'),
     '{% elif posts %}'),
    (re.compile(r'^endif\s*;?\s*$'),
     '{% endif %}'),
    (re.compile(r'^endforeach\s*;?\s*$'),
     '{% endfor %}'),

    # Title / content tags ------------------------------------------
    (re.compile(r'^the_title\s*\(\s*\)\s*;?\s*$'),
     '{{ post.post_title }}'),
    (re.compile(r'^the_content\s*\(\s*\)\s*;?\s*$'),
     '{{ post.post_content|safe }}'),
    (re.compile(r'^the_excerpt\s*\(\s*\)\s*;?\s*$'),
     '{{ post.post_excerpt }}'),
    (re.compile(r'^the_ID\s*\(\s*\)\s*;?\s*$'),
     '{{ post.id }}'),
    (re.compile(r'^the_permalink\s*\(\s*\)\s*;?\s*$'),
     "{% url 'wp_single' post.id %}"),
    (re.compile(r'^the_date\s*\(\s*\)\s*;?\s*$'),
     '{{ post.post_date|date:"F j, Y" }}'),
    (re.compile(r'^the_time\s*\(\s*\)\s*;?\s*$'),
     '{{ post.post_date|date:"g:i a" }}'),
    (re.compile(r'^the_author\s*\(\s*\)\s*;?\s*$'),
     '{{ post.author_obj.display_name|default:"Anonymous" }}'),
    (re.compile(r'^the_category\s*\(\s*\)\s*;?\s*$'),
     '{{ post.categories_html|safe }}'),
    (re.compile(r'^the_tags\s*\(\s*\)\s*;?\s*$'),
     '{{ post.tags_html|safe }}'),
    (re.compile(r'^post_class\s*\(\s*\)\s*;?\s*$'),
     'class="post"'),
    (re.compile(r'^body_class\s*\(\s*\)\s*;?\s*$'),
     'class="wp"'),
    (re.compile(r'^language_attributes\s*\(\s*\)\s*;?\s*$'),
     'lang="en"'),

    # Site info ------------------------------------------------------
    (re.compile(r"^bloginfo\s*\(\s*['\"]name['\"]\s*\)\s*;?\s*$"),
     '{{ blog_name }}'),
    (re.compile(r"^bloginfo\s*\(\s*['\"]description['\"]\s*\)\s*;?\s*$"),
     '{{ blog_description }}'),
    (re.compile(r"^bloginfo\s*\(\s*['\"]charset['\"]\s*\)\s*;?\s*$"),
     'UTF-8'),
    (re.compile(r"^bloginfo\s*\(\s*['\"]url['\"]\s*\)\s*;?\s*$"),
     "{% url 'wp_index' %}"),
    (re.compile(r"^bloginfo\s*\(\s*['\"]template_url['\"]\s*\)\s*;?\s*$"),
     "{% static 'wp' %}"),
    (re.compile(r"^bloginfo\s*\(\s*['\"]stylesheet_url['\"]\s*\)\s*;?\s*$"),
     "{% static 'wp/style.css' %}"),

    # echo expressions for known helpers ----------------------------
    (re.compile(r'^echo\s+home_url\s*\(\s*\)\s*;?\s*$'),
     "{% url 'wp_index' %}"),
    (re.compile(r'^echo\s+site_url\s*\(\s*\)\s*;?\s*$'),
     "{% url 'wp_index' %}"),
    (re.compile(r'^echo\s+get_stylesheet_uri\s*\(\s*\)\s*;?\s*$'),
     "{% static 'wp/style.css' %}"),
    (re.compile(r'^echo\s+get_template_directory_uri\s*\(\s*\)\s*;?\s*$'),
     "{% static 'wp' %}"),
    (re.compile(r'^echo\s+esc_url\s*\(\s*home_url\s*\(\s*\)\s*\)\s*;?\s*$'),
     "{% url 'wp_index' %}"),

    # head/foot hook points → Django blocks --------------------------
    (re.compile(r'^wp_head\s*\(\s*\)\s*;?\s*$'),
     '{% block extra_head %}{% endblock %}'),
    (re.compile(r'^wp_footer\s*\(\s*\)\s*;?\s*$'),
     '{% block extra_foot %}{% endblock %}'),

    # Comments (Phase 2, read-only) ----------------------------------
    (re.compile(r'^if\s*\(\s*have_comments\s*\(\s*\)\s*\)\s*:\s*$'),
     '{% if post.comments_list %}'),
    (re.compile(r'^have_comments\s*\(\s*\)\s*;?\s*$'),
     '{{ post.comments_list|yesno:"true,false" }}'),
    (re.compile(r'^comments_number\s*\(\s*\)\s*;?\s*$'),
     '{{ post.comments_list|length }}'),
    (re.compile(r'^wp_list_comments\s*\(\s*\)\s*;?\s*$'),
     "{% for c in post.comments_list %}{% include 'wp/comment.html' %}{% endfor %}"),
    (re.compile(r'^the_comment\s*\(\s*\)\s*;?\s*$'),
     ''),  # already iterated as {% for c %}
    (re.compile(r'^comment_author\s*\(\s*\)\s*;?\s*$'),
     '{{ c.comment_author }}'),
    (re.compile(r'^comment_text\s*\(\s*\)\s*;?\s*$'),
     '{{ c.comment_content|safe }}'),
    (re.compile(r'^comment_date\s*\(\s*\)\s*;?\s*$'),
     '{{ c.comment_date|date:"F j, Y" }}'),
    (re.compile(r'^comment_time\s*\(\s*\)\s*;?\s*$'),
     '{{ c.comment_date|date:"g:i a" }}'),
    (re.compile(r'^if\s*\(\s*comments_open\s*\(\s*\)\s*\)\s*:\s*$'),
     '{% if False %}{# comments_open() — submission not in Phase 2 #}'),
    (re.compile(r'^comments_open\s*\(\s*\)\s*;?\s*$'),
     'false'),
    (re.compile(r'^comment_form\s*\(\s*\)\s*;?\s*$'),
     '{# comment_form() — submission not in Phase 2 #}'),

    # Pagination (Phase 2) -------------------------------------------
    (re.compile(r'^the_posts_pagination\s*\(\s*\)\s*;?\s*$'),
     "{% include 'wp/pagination.html' %}"),
    (re.compile(r'^posts_nav_link\s*\(\s*\)\s*;?\s*$'),
     "{% include 'wp/pagination.html' %}"),
    (re.compile(r'^next_posts_link\s*\(\s*\)\s*;?\s*$'),
     '{% if posts.has_next %}<a class="next" href="?page={{ posts.next_page_number }}">Older posts &rarr;</a>{% endif %}'),
    (re.compile(r'^previous_posts_link\s*\(\s*\)\s*;?\s*$'),
     '{% if posts.has_previous %}<a class="prev" href="?page={{ posts.previous_page_number }}">&larr; Newer posts</a>{% endif %}'),

    # Archive titles -------------------------------------------------
    (re.compile(r'^the_archive_title\s*\(\s*\)\s*;?\s*$'),
     '{{ archive_title|default:"Archive" }}'),
    (re.compile(r'^the_archive_description\s*\(\s*\)\s*;?\s*$'),
     '{{ archive_description|default:"" }}'),
    (re.compile(r'^single_cat_title\s*\(\s*\)\s*;?\s*$'),
     '{{ archive_title|default:"" }}'),
    (re.compile(r'^single_tag_title\s*\(\s*\)\s*;?\s*$'),
     '{{ archive_title|default:"" }}'),
]

# Statements we drop silently (pre-Loop setup that doesn't translate
# but doesn't need flagging either).
_DROP_RULES = [
    re.compile(r'^global\s+\$\w+(?:\s*,\s*\$\w+)*\s*;?\s*$'),
    re.compile(r'^\$\w+\s*=\s*get_the_ID\s*\(\s*\)\s*;?\s*$'),
]


def _translate_php_block(php: str, skipped: list[str]) -> str:
    """Translate the body of one <?php ... ?> block."""
    php = _strip_php_comments(php)
    statements = _split_statements(php)
    out_parts: list[str] = []
    for stmt in statements:
        s = stmt.strip()
        if not s:
            continue
        replaced = False
        for rule in _DROP_RULES:
            if rule.match(s):
                replaced = True
                break
        if replaced:
            continue
        for pat, repl in _STMT_RULES:
            if pat.match(s):
                out_parts.append(repl)
                replaced = True
                break
        if not replaced:
            skipped.append(s)
            out_parts.append('{# WP-LIFT? ' + s.replace('#}', '#}}') + ' #}')
    return ''.join(out_parts)


def _split_statements(php: str) -> list[str]:
    """Split PHP source into top-level statements.

    Statements end at ``;`` or at colons that follow control-flow
    keywords (``if (...) :``, ``while (...) :``, ``else :``). We
    track paren depth so that ``;`` inside ``for (;;)`` doesn't fool
    us, and string state so that ``;`` inside ``"abc;"`` doesn't.
    """
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    in_str: str | None = None
    i = 0
    while i < len(php):
        ch = php[i]
        if in_str:
            buf.append(ch)
            if ch == '\\' and i + 1 < len(php):
                buf.append(php[i + 1])
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ('"', "'"):
            in_str = ch
            buf.append(ch)
            i += 1
            continue
        if ch == '(':
            depth += 1
            buf.append(ch)
        elif ch == ')':
            depth -= 1
            buf.append(ch)
        elif ch == ';' and depth == 0:
            out.append(''.join(buf))
            buf = []
        elif ch == ':' and depth == 0 and _looks_like_alt_control(buf):
            buf.append(ch)
            out.append(''.join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        out.append(''.join(buf))
    return out


_ALT_CONTROL_START = re.compile(r'(?:^|\s)(?:if|elseif|else|while|for|foreach|switch)\b')


def _looks_like_alt_control(buf: list[str]) -> bool:
    text = ''.join(buf).strip()
    return bool(_ALT_CONTROL_START.search(text))


# ── Top-level: translate one .php file into one .html ──────────────

def translate_template(php_source: str) -> tuple[str, list[str]]:
    """Translate one PHP theme file → (django html, skipped statements)."""
    skipped: list[str] = []
    out: list[str] = []
    pos = 0
    while True:
        m_open = _PHP_OPEN.search(php_source, pos)
        if not m_open:
            out.append(php_source[pos:])
            break
        out.append(php_source[pos:m_open.start()])
        # short-echo <?= expr ?> — wrap in echo for the same machinery
        is_short_echo = php_source[m_open.start():m_open.end()] == '<?='
        m_close = _PHP_CLOSE.search(php_source, m_open.end())
        if not m_close:
            # Unterminated PHP block — leave as a marker, stop.
            tail = php_source[m_open.start():]
            skipped.append(tail.strip()[:120])
            out.append('{# WP-LIFT? unterminated PHP block #}')
            break
        block = php_source[m_open.end():m_close.start()]
        if is_short_echo:
            block = 'echo ' + block.strip().rstrip(';') + ';'
        out.append(_translate_php_block(block, skipped))
        pos = m_close.end()
    body = ''.join(out)
    # Any template that uses {% static %} needs the static loader.
    if '{% static' in body and '{% load static %}' not in body:
        body = '{% load static %}\n' + body
    return body, skipped


# ── Theme directory walker ────────────────────────────────────────

_STATIC_ASSET_EXTS = {
    '.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp',
    '.ico', '.woff', '.woff2', '.ttf', '.otf', '.eot',
}


def parse_theme(theme_dir: Path) -> LiftResult:
    """Walk a WordPress theme directory and translate every standard file."""
    result = LiftResult()
    if not theme_dir.is_dir():
        return result
    for path in sorted(theme_dir.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(theme_dir)
        name = path.name
        ext = path.suffix.lower()
        if ext in _STATIC_ASSET_EXTS:
            result.static_assets.append(rel)
            continue
        if name in _THEME_FILE_TARGETS:
            target_name, view_name = _THEME_FILE_TARGETS[name]
            php = path.read_text(encoding='utf-8', errors='replace')
            body, skipped = translate_template(php)
            result.records.append(TemplateRecord(
                source=rel,
                target_name=target_name,
                view_name=view_name,
                body=body,
                skipped=skipped,
            ))
        elif ext in {'.php', '.phtml'}:
            result.unhandled_files.append(rel)
    return result


# ── Generated views.py / urls.py ──────────────────────────────────

_VIEWS_HEADER = '''"""Auto-generated by datalift liftwp.

Reads from the datalifted WordPress models in this app.
The 'blog_name' / 'blog_description' context comes from the
``options`` table; override BLOG_NAME_FALLBACK below if the table
isn't populated yet.
"""
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render, get_object_or_404

from . import models

BLOG_NAME_FALLBACK = "WordPress"
BLOG_DESCRIPTION_FALLBACK = "Just another WordPress site"
POSTS_PER_PAGE = 10


def _site_context():
    name = BLOG_NAME_FALLBACK
    desc = BLOG_DESCRIPTION_FALLBACK
    try:
        opts = {o.option_name: o.option_value
                for o in models.Option.objects.filter(
                    option_name__in=("blogname", "blogdescription"))}
        name = opts.get("blogname", name)
        desc = opts.get("blogdescription", desc)
    except Exception:
        pass
    return {"blog_name": name, "blog_description": desc}


def _published_posts(post_type="post"):
    return (models.Post.objects
            .filter(post_status="publish", post_type=post_type)
            .order_by("-post_date"))


def _attach_authors(posts):
    """WP's posts.post_author is a bare int, not an FK. Resolve in one query."""
    ids = {p.post_author for p in posts if p.post_author}
    if not ids:
        return
    authors = {u.id: u for u in models.User.objects.filter(id__in=ids)}
    for p in posts:
        p.author_obj = authors.get(p.post_author)


def _attach_comments(posts):
    """Attach approved comments per post via one bulk query."""
    if not posts:
        return
    ids = [p.id for p in posts]
    by_post = {pid: [] for pid in ids}
    for c in (models.Comment.objects
              .filter(comment_post_id__in=ids, comment_approved="1")
              .order_by("comment_date")):
        by_post.setdefault(c.comment_post_id, []).append(c)
    for p in posts:
        p.comments_list = by_post.get(p.id, [])


def _post_ids_for_term(taxonomy, slug):
    """Resolve term slug → post ids via terms / term_taxonomy / term_relationships."""
    try:
        term = models.Term.objects.get(slug=slug)
    except models.Term.DoesNotExist:
        return [], None
    try:
        tt = models.TermTaxonomy.objects.get(term_id=term.term_id, taxonomy=taxonomy)
    except models.TermTaxonomy.DoesNotExist:
        return [], term
    ids = list(models.TermRelationship.objects
               .filter(term_taxonomy_id=tt.term_taxonomy_id)
               .values_list("object_id", flat=True))
    return ids, term


def _paginate(qs, page_number, per_page=POSTS_PER_PAGE):
    """Return (page_obj, paginator). page_obj iterates like a list of posts."""
    paginator = Paginator(qs, per_page)
    try:
        page = int(page_number or 1)
    except (TypeError, ValueError):
        page = 1
    return paginator.get_page(page)
'''

_VIEW_BODIES = {
    'wp_index': '''

def wp_index(request):
    posts = _paginate(_published_posts(), request.GET.get("page"))
    _attach_authors(list(posts))
    return render(request, "{app}/index.html",
                  {{**_site_context(), "posts": posts}})
''',
    'wp_single': '''

def wp_single(request, post_id):
    post = get_object_or_404(models.Post, id=post_id, post_status="publish")
    _attach_authors([post])
    _attach_comments([post])
    return render(request, "{app}/single.html",
                  {{**_site_context(), "post": post, "posts": [post]}})
''',
    'wp_page': '''

def wp_page(request, page_id):
    page = get_object_or_404(models.Post, id=page_id,
                             post_status="publish", post_type="page")
    _attach_authors([page])
    _attach_comments([page])
    return render(request, "{app}/page.html",
                  {{**_site_context(), "post": page, "posts": [page]}})
''',
    'wp_archive': '''

def wp_category(request, slug):
    ids, term = _post_ids_for_term("category", slug)
    qs = _published_posts().filter(id__in=ids) if ids else _published_posts().none()
    posts = _paginate(qs, request.GET.get("page"))
    _attach_authors(list(posts))
    return render(request, "{app}/archive.html",
                  {{**_site_context(), "posts": posts,
                    "archive_title": term.name if term else slug,
                    "archive_kind": "category"}})


def wp_tag(request, slug):
    ids, term = _post_ids_for_term("post_tag", slug)
    qs = _published_posts().filter(id__in=ids) if ids else _published_posts().none()
    posts = _paginate(qs, request.GET.get("page"))
    _attach_authors(list(posts))
    return render(request, "{app}/archive.html",
                  {{**_site_context(), "posts": posts,
                    "archive_title": term.name if term else slug,
                    "archive_kind": "tag"}})


def wp_archive_year(request, year):
    qs = _published_posts().filter(post_date__year=year)
    posts = _paginate(qs, request.GET.get("page"))
    _attach_authors(list(posts))
    return render(request, "{app}/archive.html",
                  {{**_site_context(), "posts": posts,
                    "archive_title": str(year), "archive_kind": "year"}})


def wp_archive_month(request, year, month):
    qs = _published_posts().filter(post_date__year=year, post_date__month=month)
    posts = _paginate(qs, request.GET.get("page"))
    _attach_authors(list(posts))
    return render(request, "{app}/archive.html",
                  {{**_site_context(), "posts": posts,
                    "archive_title": "{{}}-{{:02d}}".format(year, month),
                    "archive_kind": "month"}})
''',
    'wp_search': '''

def wp_search(request):
    q = request.GET.get("s", "") or request.GET.get("q", "")
    if q:
        qs = _published_posts().filter(
            Q(post_title__icontains=q) | Q(post_content__icontains=q)
        )
    else:
        qs = _published_posts().none()
    posts = _paginate(qs, request.GET.get("page"))
    _attach_authors(list(posts))
    return render(request, "{app}/search.html",
                  {{**_site_context(), "posts": posts, "search_query": q}})
''',
    'wp_404': '''

def wp_404(request, exception=None):
    return render(request, "{app}/404.html", _site_context(), status=404)
''',
}


def generate_views(records: list[TemplateRecord], app_label: str) -> str:
    """Render a views.py that satisfies every URL the lifter emits."""
    seen: set[str] = set()
    parts = [_VIEWS_HEADER]
    for rec in records:
        if rec.view_name and rec.view_name in _VIEW_BODIES and rec.view_name not in seen:
            parts.append(_VIEW_BODIES[rec.view_name].format(app=app_label))
            seen.add(rec.view_name)
    return ''.join(parts)


_URLS_HEADER = '''"""Auto-generated by datalift liftwp."""
from django.urls import path

from . import views_wp as views

urlpatterns = [
'''

_URL_LINES = {
    'wp_index':   "    path('', views.wp_index, name='wp_index'),\n",
    'wp_single':  "    path('post/<int:post_id>/', views.wp_single, name='wp_single'),\n",
    'wp_page':    "    path('page/<int:page_id>/', views.wp_page, name='wp_page'),\n",
    'wp_archive': (
        "    path('category/<slug:slug>/', views.wp_category, name='wp_category'),\n"
        "    path('tag/<slug:slug>/', views.wp_tag, name='wp_tag'),\n"
        "    path('<int:year>/', views.wp_archive_year, name='wp_archive_year'),\n"
        "    path('<int:year>/<int:month>/', views.wp_archive_month, name='wp_archive_month'),\n"
    ),
    'wp_search':  "    path('search/', views.wp_search, name='wp_search'),\n",
    'wp_404':     "    # 404 wired via project urls handler404; no path needed.\n",
}


def generate_urls(records: list[TemplateRecord]) -> str:
    seen: set[str] = set()
    parts = [_URLS_HEADER]
    for rec in records:
        if rec.view_name and rec.view_name in _URL_LINES and rec.view_name not in seen:
            parts.append(_URL_LINES[rec.view_name])
            seen.add(rec.view_name)
    parts.append(']\n')
    return ''.join(parts)


# ── Worklist (markdown) ───────────────────────────────────────────

def render_worklist(result: LiftResult, app_label: str, theme_dir: Path) -> str:
    lines = [
        f'# liftwp worklist — {theme_dir.name}',
        '',
        f'Target app: `{app_label}`. Generated by `datalift liftwp`.',
        '',
        '## Translated templates',
        '',
    ]
    if not result.records:
        lines.append('_(none)_')
    for rec in result.records:
        skip = f' — **{len(rec.skipped)} unhandled fragments**' if rec.skipped else ''
        lines.append(f'- `{rec.source}` → `templates/{app_label}/{rec.target_name}`{skip}')
    lines += ['', '## Theme files we did not translate', '']
    if not result.unhandled_files:
        lines.append('_(none)_')
    for p in result.unhandled_files:
        lines.append(f'- `{p}` (custom or non-standard — port by hand)')
    lines += ['', '## Static assets passed through', '']
    if not result.static_assets:
        lines.append('_(none)_')
    for p in result.static_assets:
        lines.append(f'- `{p}` → `static/{app_label}/{p}`')
    lines += ['', '## Per-template unhandled PHP fragments', '']
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
    lines += [
        '',
        '## Out of scope for Phase 1',
        '',
        '- Custom post types, shortcodes, plugin hooks (`add_action`/`add_filter`)',
        '- Theme options pages, widgets, admin screens',
        '- Comment submission (read-only display only)',
        '- AJAX endpoints, REST API routes',
        '',
        'These need a hand port. The model layer is already datalifted, so',
        'the data is queryable from Django ORM in the meantime.',
        '',
    ]
    return '\n'.join(lines)


# ── Default partial templates emitted when the theme didn't ship one
# but the translated output references them via {% include %}. ─────

_DEFAULT_PARTIALS = {
    'comments.html': '''{# Default comments.html — emitted by liftwp when the theme had no comments.php. #}
{% if post.comments_list %}
<section class="comments">
  <h3>{{ post.comments_list|length }} Comment{{ post.comments_list|length|pluralize }}</h3>
  <ol class="commentlist">
    {% for c in post.comments_list %}{% include 'wp/comment.html' %}{% endfor %}
  </ol>
</section>
{% endif %}
''',
    'comment.html': '''{# One comment row — emitted by liftwp. Customise as needed. #}
<li class="comment" id="comment-{{ c.comment_id }}">
  <div class="comment-meta">
    <strong class="comment-author">{{ c.comment_author }}</strong>
    <span class="comment-date">{{ c.comment_date|date:"F j, Y g:i a" }}</span>
  </div>
  <div class="comment-body">{{ c.comment_content|safe }}</div>
</li>
''',
    'pagination.html': '''{# Default pagination.html — emitted by liftwp. #}
{% if posts.has_other_pages %}
<nav class="pagination">
  {% if posts.has_previous %}
    <a class="prev" href="?page={{ posts.previous_page_number }}">&larr; Newer posts</a>
  {% endif %}
  <span class="page-info">Page {{ posts.number }} of {{ posts.paginator.num_pages }}</span>
  {% if posts.has_next %}
    <a class="next" href="?page={{ posts.next_page_number }}">Older posts &rarr;</a>
  {% endif %}
</nav>
{% endif %}
''',
    'searchform.html': '''{% url 'wp_search' as wp_search_url %}
<form class="search-form" method="get" action="{{ wp_search_url|default:'/' }}">
  <label for="wp-search">Search</label>
  <input type="search" id="wp-search" name="s" value="{{ search_query|default:'' }}">
  <button type="submit">Go</button>
</form>
''',
    'sidebar.html': '''{# Default sidebar.html — emitted by liftwp. #}
<aside class="sidebar">
  {% include 'wp/searchform.html' %}
</aside>
''',
}


def _missing_partials(records: list[TemplateRecord]) -> set[str]:
    """Return default partials that are referenced but not provided.

    Scans the translated record bodies, then iterates: default partials
    can themselves reference other partials (sidebar → searchform), so
    we fixed-point the scan over the defaults we're about to emit.
    """
    have = {r.target_name for r in records}
    needed: set[str] = set()

    def scan(body: str) -> None:
        for name in _DEFAULT_PARTIALS:
            if name in have or name in needed:
                continue
            if "'wp/" + name + "'" in body or '"wp/' + name + '"' in body:
                needed.add(name)

    for rec in records:
        scan(rec.body)
    # Fixed-point over the default partials' own bodies.
    while True:
        before = set(needed)
        for name in list(needed):
            scan(_DEFAULT_PARTIALS[name])
        if needed == before:
            break
    return needed


# ── File application ──────────────────────────────────────────────

def apply(result: LiftResult, project_root: Path, app_label: str,
          dry_run: bool = False) -> list[str]:
    """Write generated templates / views.py / urls.py / static assets."""
    log: list[str] = []
    templates_dir = project_root / 'templates' / app_label
    static_dir = project_root / 'static' / app_label
    app_dir = project_root / app_label

    if not dry_run:
        templates_dir.mkdir(parents=True, exist_ok=True)
        static_dir.mkdir(parents=True, exist_ok=True)

    for rec in result.records:
        target = templates_dir / rec.target_name
        if not dry_run:
            target.write_text(rec.body, encoding='utf-8')
        log.append(f'template  {rec.source} → {target.relative_to(project_root)}')

    for name in sorted(_missing_partials(result.records)):
        target = templates_dir / name
        if not dry_run:
            target.write_text(_DEFAULT_PARTIALS[name], encoding='utf-8')
        log.append(f'partial   (default) → {target.relative_to(project_root)}')

    if result.records:
        views_text = generate_views(result.records, app_label)
        urls_text = generate_urls(result.records)
        views_path = app_dir / 'views_wp.py'
        urls_path = app_dir / 'urls_wp.py'
        if not dry_run:
            app_dir.mkdir(parents=True, exist_ok=True)
            views_path.write_text(views_text, encoding='utf-8')
            urls_path.write_text(urls_text, encoding='utf-8')
        log.append(f'views     → {views_path.relative_to(project_root)}')
        log.append(f'urls      → {urls_path.relative_to(project_root)}')

    return log
