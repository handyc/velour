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

def _strip_php_comments(php: str) -> str:
    """String-aware PHP comment stripper. Delegates to shared helper."""
    from datalift._php import strip_php_comments
    return strip_php_comments(php)


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

    # Brace-style control flow (Twenty Sixteen mixes brace + alt). ───
    # The split_statements pass has separated `if (...) {` from `}`
    # from the body, so each shows up as its own statement.
    (re.compile(r'^if\s*\(.*\)\s*\{$'),
     '{% if False %}{# brace-if condition not translated #}'),
    (re.compile(r'^elseif\s*\(.*\)\s*\{$'),
     '{% elif False %}{# brace-elseif condition not translated #}'),
    (re.compile(r'^else\s*\{$'),
     '{% else %}'),
    (re.compile(r'^\}\s*else\s*\{$'),
     '{% else %}'),
    (re.compile(r'^\}\s*elseif\s*\(.*\)\s*\{$'),
     '{% elif False %}{# brace-elseif condition not translated #}'),
    (re.compile(r'^\}$'),
     '{% endif %}'),
    (re.compile(r'^foreach\s*\(.*\)\s*\{$'),
     '{% for _item in _items %}{# brace-foreach not fully translated #}'),
    (re.compile(r'^while\s*\(.*\)\s*\{$'),
     '{% for _item in _items %}{# brace-while not fully translated #}'),
    (re.compile(r'^return\s*\??$'),
     '{# return — early-exit dropped in template translation #}'),

]


# Some rules need access to captured groups; handle them in a small
# parallel table. Each entry: (pattern, callable(match) -> str).
_STMT_RULES_DYNAMIC: list[tuple[re.Pattern[str], 'callable']] = [
    (re.compile(r"^get_sidebar\s*\(\s*['\"](?P<n>[\w-]+)['\"]\s*\)\s*;?\s*$"),
     lambda m: f"{{% include 'wp/sidebar-{m.group('n')}.html' %}}"),
    (re.compile(r"^get_template_part\s*\(\s*['\"](?P<base>[^'\"]+)['\"]\s*(?:,\s*['\"](?P<suf>[^'\"]+)['\"])?\s*\)\s*;?\s*$"),
     lambda m: ("{% include 'wp/" + m.group('base')
                + ('-' + m.group('suf') if m.group('suf') else '')
                + ".html' %}")),
    # Generalised alt-syntax control flow: any condition the lifter
    # can't evaluate becomes a False branch with the original
    # condition preserved as a comment for the porter.
    (re.compile(r'^if\s*\((?P<cond>.+)\)\s*:\s*$'),
     lambda m: '{% if False %}{# alt-if condition: ' +
               _safe_comment(m.group('cond').strip()) + ' #}'),
    (re.compile(r'^elseif\s*\((?P<cond>.+)\)\s*:\s*$'),
     lambda m: '{% elif False %}{# alt-elseif condition: ' +
               _safe_comment(m.group('cond').strip()) + ' #}'),
    # echo $var → {{ var }} — variable likely not in template context, but
    # this is the best we can do without a custom view.
    (re.compile(r'^echo\s+\$(?P<name>\w+)\s*;?\s*$'),
     lambda m: '{{ ' + m.group('name') + ' }}'),
    # echo "literal string"
    (re.compile(r"^echo\s+(['\"])(?P<text>.*?)(?<!\\)\1\s*;?\s*$"),
     lambda m: m.group('text')),
    # echo $var ? 'A' : 'B' → {% if var %}A{% else %}B{% endif %}
    (re.compile(
        r"^echo\s+\$(?P<name>\w+)\s*\?\s*"
        r"(['\"])(?P<a>.*?)(?<!\\)\2\s*:\s*(['\"])(?P<b>.*?)(?<!\\)\4\s*;?\s*$"),
     lambda m: ('{% if ' + m.group('name') + ' %}'
                + m.group('a')
                + ('{% else %}' + m.group('b') if m.group('b') else '')
                + '{% endif %}')),
    # echo <ANY-EXPR> ? 'A' : 'B' — a generalised ternary that handles
    # property access, function calls, and comparisons. We can't
    # evaluate the LHS, so emit BOTH strings as a comment + the truthy
    # one (whichever is more likely to be the "default" — the second).
    (re.compile(
        r"^echo\s+(?P<lhs>[^?]+?)\?\s*"
        r"(['\"])(?P<a>.*?)(?<!\\)\2\s*:\s*(['\"])(?P<b>.*?)(?<!\\)\4\s*;?\s*$"),
     lambda m: ('{# ternary: ' + _safe_comment(m.group('lhs').strip())
                + " ? '" + m.group('a') + "' : '" + m.group('b') + "' #}"
                + m.group('a'))),
    # Alt-syntax while with arbitrary condition.
    (re.compile(r'^while\s*\((?P<cond>.+)\)\s*:\s*$'),
     lambda m: '{% for _item in _items %}{# alt-while condition: '
               + _safe_comment(m.group('cond').strip()) + ' #}'),
    # PHP increment / decrement — no Django equivalent, drop with a note.
    (re.compile(r'^(?:\+\+|--)\$\w+\s*$'),
     lambda m: ''),
    (re.compile(r'^\$\w+(?:\+\+|--)\s*$'),
     lambda m: ''),
    # Concat-assign onto a PHP var — silent skip
    (re.compile(r'^\$\w+(?:->\w+)?\s*\.=\s*.+$'),
     lambda m: ''),
    # Bare object method call — silent skip
    (re.compile(r'^\$\w+(?:->\w+)+\s*\([^)]*\)\s*$'),
     lambda m: ''),
    # $var = ... assignments — silent skip with a porter-facing comment.
    (re.compile(r'^\$(?P<name>\w+)\s*=\s*(?P<rhs>.+)$'),
     lambda m: '{# php: $' + m.group('name') + ' = '
               + _safe_comment(m.group('rhs').strip()[:80]) + ' #}'),
]


def _safe_comment(s: str) -> str:
    """Escape `#}` so it can't terminate the surrounding Django comment."""
    return s.replace('#}', '#}}')

# Statements we drop silently (pre-Loop setup that doesn't translate
# but doesn't need flagging either).
_DROP_RULES = [
    re.compile(r'^global\s+\$\w+(?:\s*,\s*\$\w+)*\s*;?\s*$'),
    re.compile(r'^\$\w+\s*=\s*get_the_ID\s*\(\s*\)\s*;?\s*$'),
]


def _translate_php_block(php: str, skipped: list[str],
                          theme_prefix: str = '',
                          theme_funcs: set[str] | None = None) -> str:
    """Translate the body of one <?php ... ?> block."""
    if theme_funcs is None:
        theme_funcs = set()
    php = _strip_php_comments(php)
    statements = _split_statements(php)
    out_parts: list[str] = []
    for raw_stmt in statements:
        # Collapse runs of whitespace inside the statement so multi-line
        # WP calls match single-line regexes.
        s = ' '.join(raw_stmt.split())
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
        if replaced:
            continue
        for pat, fn in _STMT_RULES_DYNAMIC:
            m = pat.match(s)
            if m:
                out_parts.append(fn(m))
                replaced = True
                break
        if replaced:
            continue
        # Function-name dispatch — handles tags with arbitrary arg lists
        # by ignoring the parenthesised payload.
        translated = _translate_call(s, skipped, theme_prefix, theme_funcs)
        if translated is not None:
            out_parts.append(translated)
            continue
        skipped.append(s)
        out_parts.append('{# WP-LIFT? ' + s.replace('#}', '#}}') + ' #}')
    return ''.join(out_parts)


# ── Function-name dispatch (tolerates any arg payload) ─────────────

_CALL_HEAD = re.compile(r'^(?:echo\s+)?(\w+)\s*\(')

# Tag functions where the arg list is formatting hints we ignore;
# the basic Django output is sufficient.
_FUNC_RULES = {
    'the_archive_title':         '{{ archive_title|default:"Archive" }}',
    'the_archive_description':   '{{ archive_description|default:"" }}',
    'single_cat_title':          '{{ archive_title|default:"" }}',
    'single_tag_title':          '{{ archive_title|default:"" }}',
    'the_title':                 '{{ post.post_title }}',
    'the_content':               '{{ post.post_content|safe }}',
    'the_excerpt':               '{{ post.post_excerpt }}',
    'the_ID':                    '{{ post.id }}',
    'the_permalink':             '{{ post.permalink }}',
    'the_date':                  '{{ post.post_date|date:"F j, Y" }}',
    'the_time':                  '{{ post.post_date|date:"g:i a" }}',
    'the_author':                '{{ post.author_obj.display_name|default:"Anonymous" }}',
    'the_category':              '{{ post.categories_html|safe }}',
    'the_tags':                  '{{ post.tags_html|safe }}',
    'the_post_thumbnail':        '{# the_post_thumbnail — manual port if you use featured images #}',
    'post_class':                'class="post"',
    'body_class':                'class="wp"',
    'language_attributes':       'lang="en"',
    'wp_head':                   '{% block extra_head %}{% endblock %}',
    'wp_footer':                 '{% block extra_foot %}{% endblock %}',
    'wp_link_pages':             '{# wp_link_pages — multi-page posts not lifted #}',
    'the_posts_pagination':      "{% include 'wp/pagination.html' %}",
    'the_comments_navigation':   "{% include 'wp/pagination.html' %}",
    'next_posts_link':           '{% if posts.has_next %}<a class="next" href="?page={{ posts.next_page_number }}">Older posts &rarr;</a>{% endif %}',
    'previous_posts_link':       '{% if posts.has_previous %}<a class="prev" href="?page={{ posts.previous_page_number }}">&larr; Newer posts</a>{% endif %}',
    'posts_nav_link':            "{% include 'wp/pagination.html' %}",
    'paginate_links':            "{% include 'wp/pagination.html' %}",
    'wp_list_comments':          "{% for c in post.comments_list %}{% include 'wp/comment.html' %}{% endfor %}",
    'comments_number':           '{{ post.comments_list|length }}',
    'comment_author':            '{{ c.comment_author }}',
    'comment_text':              '{{ c.comment_content|safe }}',
    'comment_date':              '{{ c.comment_date|date:"F j, Y" }}',
    'comment_time':              '{{ c.comment_date|date:"g:i a" }}',
    'comment_form':              '{# comment_form() — submission not in Phase 2 #}',
    'edit_comment_link':         '',
    'wp_nav_menu':               '{# wp_nav_menu — register nav menu support manually #}',
    'do_action':                 '',
    'wp_register':               '',
    'wp_loginout':               '',
    'wp_meta':                   '',
    'get_calendar':              '{# get_calendar() — not implemented #}',
    # Boolean predicates — return false unless explicitly handled.
    'has_nav_menu':              'false',
    'is_singular':               'false',
    'is_archive':                'false',
    'is_page':                   'false',
    'is_home':                   'false',
    'is_front_page':             'false',
    'is_search':                 'false',
    'is_paged':                  'false',
    'is_active_sidebar':         'false',
    'is_customize_preview':      'false',
    'is_admin':                  'false',
    'pings_open':                'false',
    'post_password_required':    'false',
    'function_exists':           'false',
    'is_user_logged_in':         'false',
    'current_user_can':          'false',
    'comments_open':             'false',
    'get_header_image':          'false',
    'has_post_thumbnail':        'false',
    # Sidebar / widget plumbing — silent skip
    'dynamic_sidebar':           '{# dynamic_sidebar — register widget areas manually #}',
    # Hooks / filters — silent skip
    'apply_filters':             '{# apply_filters — hook ignored #}',
    'wp_body_open':              '',
    # Theme-utility tags
    'wp_title':                  '{{ blog_name }}',
    'single_post_title':         '{{ post.post_title|default:blog_name }}',
    'get_search_query':          '{{ search_query }}',
    'get_comments_number':       '{{ post.comments_list|length }}',
    'the_post_navigation':       "{# the_post_navigation — manual port #}",
    'the_posts_navigation':      "{% include 'wp/pagination.html' %}",
    'the_header_image_tag':      '{# the_header_image_tag — manual port #}',
    'get_avatar':                '{# get_avatar — manual port #}',
    'get_the_author':            '{{ post.author_obj.display_name|default:"Anonymous" }}',
    'get_the_author_meta':       '{{ post.author_obj.user_email }}',
    'the_author_meta':           '{{ post.author_obj.user_email }}',
    'get_post_format':           "''",
    'get_post_type':             "''",
    'get_post_type_object':      "''",
    'get_queried_object':        "''",
    'get_queried_object_id':     "''",
    'edit_post_link':            '',
    'edit_comment_link':         '',
    'the_privacy_policy_link':   '',
    'post_type_supports':        'false',
    'number_format_i18n':        '{{ value }}',
    # Boolean-ish info that returns content when echoed
    'home_url':                  "{% url 'wp_index' %}",
    'site_url':                  "{% url 'wp_index' %}",
    'get_stylesheet_uri':        "{% static 'wp/style.css' %}",
    'get_template_directory_uri':"{% static 'wp' %}",
    'get_bloginfo':              '',  # handled by bloginfo regex; rare echo form
    # Widgets / list helpers — manual port
    'the_widget':                '{# the_widget — manual port #}',
    'wp_list_categories':        '{# wp_list_categories — manual port #}',
    'wp_list_pages':             '{# wp_list_pages — manual port #}',
    'wp_list_authors':           '{# wp_list_authors — manual port #}',
    'wp_list_bookmarks':         '{# wp_list_bookmarks — manual port #}',
    'get_archives':              '{# get_archives — manual port #}',
    'wp_get_archives':           '{# wp_get_archives — manual port #}',
    'the_custom_logo':           '{# the_custom_logo — manual port #}',
    'has_custom_logo':           'false',
    'get_custom_logo':           '',
    'get_search_form':           "{% include 'wp/searchform.html' %}",
    # Pagination cousins
    'the_comments_pagination':   "{% include 'wp/pagination.html' %}",
    'previous_comments_link':    '{% if post.comments_list %}<a class="prev" href="?cpage={{ comment_page|add:-1 }}">&larr; Older comments</a>{% endif %}',
    'next_comments_link':        '{% if post.comments_list %}<a class="next" href="?cpage={{ comment_page|add:1 }}">Newer comments &rarr;</a>{% endif %}',
    'comments_popup_link':       '{# comments_popup_link — manual port #}',
    # Get-the-X family
    'get_the_post_thumbnail':    '',
    'get_the_date':              '{{ post.post_date|date:"F j, Y" }}',
    'get_the_time':              '{{ post.post_date|date:"g:i a" }}',
    'get_the_title':             '{{ post.post_title }}',
    'get_the_excerpt':           '{{ post.post_excerpt }}',
    'get_the_author_link':       '{{ post.author_obj.display_name|default:"Anonymous" }}',
    'get_the_category_list':     '{{ post.categories_html|safe }}',
    'get_the_tag_list':          '{{ post.tags_html|safe }}',
    'get_the_terms':             '',
    'get_the_ID':                '{{ post.id }}',
    'get_the_permalink':         "{{ post.permalink }}",
    'get_permalink':             "{{ post.permalink }}",
    'get_the_content':           '{{ post.post_content|safe }}',
    'get_post_format':           "''",
    'get_post_format_string':    '',
    'get_post_gallery':          '',
    'category_description':      '{{ archive_description|default:"" }}',
    'tag_description':           '{{ archive_description|default:"" }}',
    'term_description':          '{{ archive_description|default:"" }}',
    'wp_date':                   '{{ now|date:"F j, Y" }}',
    'date_i18n':                 '{{ now|date:"F j, Y" }}',
    'wp_reset_postdata':         '',
    'wp_reset_query':            '',
    'rewind_posts':              '',
    'is_page_template':          'false',
    'is_sticky':                 'false',
    'is_attachment':             'false',
    'is_tax':                    'false',
    'is_tag':                    'false',
    'is_category':               'false',
    'is_404':                    'false',
    'is_rtl':                    'false',
    'is_main_query':             'true',
    'has_excerpt':               'false',
    'is_multi_author':           'false',
    'comments_link':             "{{ post.permalink }}#comments",
    'get_comments_link':         "{{ post.permalink }}#comments",
    'get_avatar_url':            "''",
    'wp_get_attachment_image':   '',
    'wp_get_attachment_url':     "''",
    'wp_get_attachment_link':    '',
    'the_custom_header_markup':  '{# the_custom_header_markup — manual port #}',
    'header_image':              "''",
    'wp_body_open':              '',
    'get_template_directory':    "''",
    'get_stylesheet_directory':  "''",
    'get_theme_mod':             "''",
    'get_option':                "''",
    'set_query_var':             '',
    'wp_nonce_field':            '',
    'wp_create_nonce':           "''",
    'admin_url':                 "''",
    # Comments + post-nav variants with arg lists
    'comments_template':         "{% include 'wp/comments.html' %}",
    'previous_post_link':        '{# previous_post_link — manual port #}',
    'next_post_link':            '{# next_post_link — manual port #}',
    'the_post_thumbnail_url':    "''",
}

# String-returning translation functions: drop wrapper, keep first arg
_I18N_FUNCS = {
    # echo-translate family
    '_e', '_ex', 'esc_attr_e', 'esc_html_e', 'esc_attr_x', 'esc_html_x',
    # return-translate family
    '__', '_x', '_n', '_nx',
    'esc_html__', 'esc_attr__', 'esc_url__',
    'esc_html_x', 'esc_attr_x',
    'translate', 'translate_with_gettext_context',
    # escape family
    'esc_html', 'esc_attr', 'esc_url', 'esc_url_raw', 'esc_textarea',
    'esc_js', 'esc_xml',
    # sanitize family
    'wp_kses_post', 'wp_kses_data', 'wp_kses',
    'sanitize_text_field', 'sanitize_html_class', 'sanitize_title',
    # type coercion
    'absint', 'intval', 'strval', 'floatval',
    # other passthroughs
    'antispambot',
}

_FIRST_STRING = re.compile(r"\s*(['\"])(.*?)(?<!\\)\1")


def _translate_call(stmt: str, skipped: list[str],
                     theme_prefix: str = '',
                     theme_funcs: set[str] | None = None) -> str | None:
    if theme_funcs is None:
        theme_funcs = set()
    m = _CALL_HEAD.match(stmt)
    if not m:
        return None
    name = m.group(1)

    if name in _I18N_FUNCS:
        body = stmt[m.end():].rstrip(';)').rstrip()
        sm = _FIRST_STRING.match(body)
        if sm:
            return _html_escape_literal(sm.group(2))
        return _translate_call(body.strip(), skipped, theme_prefix, theme_funcs) or ''

    if name == 'printf':
        return _translate_printf(stmt[m.end():], skipped, theme_prefix, theme_funcs)

    if name == 'get_template_part':
        return _translate_get_template_part(stmt[m.end():])

    if name in _FUNC_RULES:
        return _FUNC_RULES[name]

    # Theme-defined function (scanned from theme's inc/ + functions.php).
    # Authoritative — beats the prefix heuristic.
    if name in theme_funcs:
        return '{# theme function ' + name + '() — port manually #}'

    # Prefix heuristic fallback (theme dir name). Catches functions in
    # themes whose inc/ wasn't scannable for whatever reason.
    if theme_prefix and name.startswith(theme_prefix + '_'):
        return '{# theme function ' + name + '() — port manually #}'

    return None


def _translate_printf(args: str, skipped: list[str],
                       theme_prefix: str,
                       theme_funcs: set[str] | None = None) -> str | None:
    if theme_funcs is None:
        theme_funcs = set()
    """``printf("Search Results for: %s", get_search_query())`` →
    ``Search Results for: {{ search_query }}``.
    Best-effort: only handles printf with a literal-or-i18n format string
    and one or more simple %s/%d substitutions filled by translatable calls.
    """
    body = args.strip()
    # Strip outer trailing `);`
    body = body.rstrip(';').rstrip()
    if body.endswith(')'):
        body = body[:-1]
    # Split top-level commas — same depth/string awareness as _split_statements.
    parts = _split_top_level_commas(body)
    if not parts:
        return None
    fmt_raw = parts[0].strip()
    # Resolve the format string: literal, or wrapped in __('...', 'domain') / _x(...)
    fmt = _extract_literal_or_i18n_string(fmt_raw)
    if fmt is None:
        return None
    rest = parts[1:]
    # Translate each %s/%d placeholder to its corresponding arg.
    placeholder = re.compile(r'%(?:\d+\$)?[sdif]')
    out: list[str] = []
    last = 0
    arg_index = 0
    for m in placeholder.finditer(fmt):
        out.append(fmt[last:m.start()])
        if arg_index < len(rest):
            arg = rest[arg_index].strip()
            # String literal — emit verbatim
            sm = _FIRST_STRING.match(arg)
            if sm and sm.end() == len(arg):
                out.append(sm.group(2))
            else:
                translated = _translate_call(arg, skipped, theme_prefix, theme_funcs)
                out.append(translated if translated is not None else '{# ' + arg + ' #}')
        arg_index += 1
        last = m.end()
    out.append(fmt[last:])
    return ''.join(out)


def _split_top_level_commas(body: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    in_str: str | None = None
    i = 0
    while i < len(body):
        ch = body[i]
        if in_str:
            buf.append(ch)
            if ch == '\\' and i + 1 < len(body):
                buf.append(body[i + 1])
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
        elif ch == ',' and depth == 0:
            parts.append(''.join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        parts.append(''.join(buf))
    return parts


def _extract_literal_or_i18n_string(expr: str) -> str | None:
    """Pull a string out of nested i18n/escape wrappers.

    ``'foo'`` → ``foo``
    ``__('foo', 'domain')`` → ``foo``
    ``esc_html(_nx('singular', 'plural', $n, 'ctx', 'domain'))`` → ``singular``
    """
    expr = expr.strip()
    while True:
        sm = _FIRST_STRING.match(expr)
        if sm:
            return sm.group(2)
        m = _CALL_HEAD.match(expr)
        if not m or m.group(1) not in _I18N_FUNCS:
            return None
        expr = expr[m.end():].lstrip()


def _html_escape_literal(s: str) -> str:
    """Escape an i18n literal that's about to land in HTML."""
    # The literal might already contain HTML entities (&ldquo; etc.) — pass
    # those through. Just mark it safe-ish.
    return s


_GET_TEMPLATE_PART = re.compile(
    r"\s*(['\"])(?P<base>[^'\"]+)\1\s*(?:,\s*(['\"])(?P<suffix>[^'\"]+)\3)?",
)


def _translate_get_template_part(args: str) -> str:
    """``get_template_part('template-parts/content', 'single')`` →
    ``{% include 'wp/template-parts/content-single.html' %}``.
    A non-literal suffix degrades to the no-suffix include.
    """
    m = _GET_TEMPLATE_PART.match(args)
    if not m:
        return None  # type: ignore[return-value]
    base = m.group('base')
    suffix = m.group('suffix')
    if suffix:
        path = f'wp/{base}-{suffix}.html'
    else:
        path = f'wp/{base}.html'
    return "{% include '" + path + "' %}"


def _split_statements(php: str) -> list[str]:
    """Split PHP source into top-level statements.

    Splits at ``;``, at ``:`` after control-flow keywords (alt syntax:
    ``if (...) :`` ... ``endif;``), and at top-level ``{`` / ``}``
    so that brace-style ``if (...) { ... }`` blocks are translatable
    statement-by-statement. Tracks paren depth and string state so
    that ``;`` inside ``"abc;"`` or ``for (;;)`` doesn't split.
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
        elif ch == '{' and depth == 0:
            buf.append(ch)
            out.append(''.join(buf))
            buf = []
        elif ch == '}' and depth == 0:
            # Lookahead: keep `}` glued to a following `else`/`elseif` so
            # the brace-style if/elif/else chain stays in one statement
            # ("} else {" / "} elseif (...) {").
            rest = php[i + 1:]
            stripped = rest.lstrip()
            if stripped.startswith(('else ', 'else{', 'else\n', 'else\t',
                                     'elseif ', 'elseif(', 'elseif\n',
                                     'elseif\t')):
                buf.append(ch)
            else:
                if buf and ''.join(buf).strip():
                    out.append(''.join(buf))
                out.append('}')
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

def translate_template(php_source: str,
                       theme_prefix: str = '',
                       theme_funcs: set[str] | None = None) -> tuple[str, list[str]]:
    """Translate one PHP theme file → (django html, skipped statements)."""
    skipped: list[str] = []
    out: list[str] = []
    pos = 0
    if theme_funcs is None:
        theme_funcs = set()
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
            block = php_source[m_open.end():]
            if is_short_echo:
                block = 'echo ' + block.strip().rstrip(';') + ';'
            out.append(_translate_php_block(block, skipped, theme_prefix, theme_funcs))
            break
        block = php_source[m_open.end():m_close.start()]
        if is_short_echo:
            block = 'echo ' + block.strip().rstrip(';') + ';'
        out.append(_translate_php_block(block, skipped, theme_prefix, theme_funcs))
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

# Subdirectories whose .php files are PHP CODE, not templates.
_CODE_DIR_PARTS = {'inc', 'includes', 'lib', 'vendor', 'src', 'classes'}

# Subdirectories whose .php files are explicitly templates/partials.
_PARTIAL_DIR_PARTS = {'template-parts', 'parts', 'partials', 'templates'}

# WP template-hierarchy filename patterns at the theme root.
_TEMPLATE_HIERARCHY_PATTERNS = [
    re.compile(r'^single-[\w-]+\.php$'),
    re.compile(r'^archive-[\w-]+\.php$'),
    re.compile(r'^category-[\w-]+\.php$'),
    re.compile(r'^tag-[\w-]+\.php$'),
    re.compile(r'^page-[\w-]+\.php$'),
    re.compile(r'^taxonomy-[\w-]+\.php$'),
    re.compile(r'^author-[\w-]+\.php$'),
    re.compile(r'^date-[\w-]+\.php$'),
    re.compile(r'^header-[\w-]+\.php$'),
    re.compile(r'^footer-[\w-]+\.php$'),
    re.compile(r'^sidebar-[\w-]+\.php$'),
    re.compile(r'^content-[\w-]+\.php$'),
]


def _is_template_file(rel: Path) -> bool:
    """True if rel looks like a WP template/partial, not PHP code."""
    name = rel.name
    if name in _THEME_FILE_TARGETS:
        return True
    parents = set(rel.parts[:-1])
    if parents & _CODE_DIR_PARTS:
        return False
    if parents & _PARTIAL_DIR_PARTS:
        return True
    if name == 'functions.php' or name.endswith(('.functions.php',
                                                  '-functions.php')):
        return False
    if name.startswith('class-'):
        return False
    if rel.parent != Path('.'):
        # Some other subdir we don't recognize → treat as code (safer).
        return False
    return any(p.match(name) for p in _TEMPLATE_HIERARCHY_PATTERNS)


def _partial_target_name(rel: Path) -> str:
    """``template-parts/content-single.php`` → ``template-parts/content-single.html``"""
    return str(rel.with_suffix('.html'))


_THEME_PREFIX_RE = re.compile(r'[^a-z0-9]+')
_PHP_FUNC_DEF = re.compile(r'function\s+(\w+)\s*\(')


def _derive_theme_prefix(theme_dir: Path) -> str:
    """Auto-derive a theme prefix from the directory name.

    ``twentysixteen`` → ``twentysixteen``; ``my-cool-theme`` → ``my_cool_theme``.
    Used to silently skip ``themename_*`` function calls that we know are
    theme-internal helpers (defined in inc/ or functions.php).
    """
    return _THEME_PREFIX_RE.sub('_', theme_dir.name.lower()).strip('_')


def _scan_theme_functions(theme_dir: Path) -> set[str]:
    """Collect function names defined in the theme's PHP code paths.

    Far more precise than prefix-matching: a theme like Twenty Twenty-One
    lives in dir ``twentytwentyone`` but defines ``twenty_twenty_one_*``
    functions, which prefix-match would miss. Reading the actual
    ``inc/`` / ``functions.php`` PHP gives the truth.
    """
    names: set[str] = set()
    candidates: list[Path] = []
    for d in ('inc', 'includes', 'lib', 'src', 'classes'):
        sub = theme_dir / d
        if sub.is_dir():
            candidates.extend(sub.rglob('*.php'))
    fn = theme_dir / 'functions.php'
    if fn.is_file():
        candidates.append(fn)
    for path in candidates:
        try:
            txt = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        names.update(_PHP_FUNC_DEF.findall(txt))
    return names


def parse_theme(theme_dir: Path,
                theme_prefix: str | None = None,
                theme_funcs: set[str] | None = None) -> LiftResult:
    """Walk a WordPress theme directory and translate every PHP file
    that looks like a template (skipping recognized PHP-code files).

    ``theme_prefix`` defaults to a sanitised version of the directory
    name; any function call ``<prefix>_<name>(...)`` is quietly marked
    as theme-internal.

    ``theme_funcs`` defaults to function names actually defined in the
    theme's ``inc/`` / ``functions.php`` — far more precise than the
    prefix heuristic. Both sets are checked.
    """
    result = LiftResult()
    if not theme_dir.is_dir():
        return result
    if theme_prefix is None:
        theme_prefix = _derive_theme_prefix(theme_dir)
    if theme_funcs is None:
        theme_funcs = _scan_theme_functions(theme_dir)
    for path in sorted(theme_dir.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(theme_dir)
        name = path.name
        ext = path.suffix.lower()
        if ext in _STATIC_ASSET_EXTS:
            result.static_assets.append(rel)
            continue
        if ext not in {'.php', '.phtml'}:
            continue
        if not _is_template_file(rel):
            result.unhandled_files.append(rel)
            continue
        if name in _THEME_FILE_TARGETS:
            target_name, view_name = _THEME_FILE_TARGETS[name]
        else:
            target_name = _partial_target_name(rel)
            view_name = None
        php = path.read_text(encoding='utf-8', errors='replace')
        body, skipped = translate_template(
            php, theme_prefix=theme_prefix, theme_funcs=theme_funcs,
        )
        result.records.append(TemplateRecord(
            source=rel,
            target_name=target_name,
            view_name=view_name,
            body=body,
            skipped=skipped,
        ))
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
            target.parent.mkdir(parents=True, exist_ok=True)
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
