"""Seed Codex manuals for the Datalift toolset (genmodels, ingestdump,
liftwp, browsershot, shotdiff, ...).

First batch: the liftwp Quickstart (1pp) and the liftwp Short Guide
(~10-15pp). More command-specific manuals can be added in later
iterations of this same command.

Idempotent: re-running updates the existing manuals in place.

    python manage.py seed_datalift_manuals
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from codex.models import Manual, Section


def upsert_manual(slug, **fields):
    m, _ = Manual.objects.get_or_create(slug=slug, defaults=fields)
    for k, v in fields.items():
        setattr(m, k, v)
    m.save()
    return m


def upsert_section(manual, slug, sort_order, title, body, sidenotes=''):
    s, _ = Section.objects.get_or_create(
        manual=manual, slug=slug,
        defaults={'sort_order': sort_order, 'title': title},
    )
    s.sort_order = sort_order
    s.title = title
    s.body = body
    s.sidenotes = sidenotes
    s.save()
    return s


def seed_liftwp_quickstart():
    m = upsert_manual(
        'liftwp-quickstart',
        title='liftwp — Quickstart',
        subtitle='Port a WordPress theme to Django in three commands',
        format='quickstart',
        author='Velour / Datalift',
        version='1.0',
        abstract=(
            'A one-page recipe for translating a WordPress theme into a '
            'Django app. Assumes the data half is already datalifted '
            '(genmodels + ingestdump). For the long form see "liftwp — '
            'A WordPress-to-Django Translator".'
        ),
    )

    upsert_section(m, 'recipe', 0, 'The recipe', """
**1. Lift the theme into your Django app.**

```
python manage.py liftwp /path/to/wp-content/themes/mytheme \\
    --app wp
```

This writes `templates/wp/*.html`, `wp/views_wp.py`, `wp/urls_wp.py`,
default partials for any `{% include %}` the lifter emits, and
`liftwp_worklist.md` at the project root.

**2. Wire it into your project URLs.**

In `myproject/urls.py`:

```
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('wp.urls_wp')),
]
```

**3. Stage the theme's static assets and settings.**

```
cp -r /path/to/wp-content/themes/mytheme/{css,js,fonts,style.css} \\
      static/wp/
```

In `settings.py`:

```
TEMPLATES = [{
    ...,
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    ...
}]
STATICFILES_DIRS = [BASE_DIR / 'static']
```

**That's it.** Browse the lifted site at the URLs in `wp/urls_wp.py`:
`/`, `/post/<id>/`, `/page/<id>/`, `/category/<slug>/`, `/tag/<slug>/`,
`/<year>/`, `/<year>/<month>/`, `/search/?s=<q>`.

For visual fidelity verification:

```
python manage.py browsershot https://legacy-site.example/ --out before.png
python manage.py browsershot http://127.0.0.1:8000/      --out after.png
python manage.py shotdiff before.png after.png --out diff.png
```
""")


def seed_liftwp_short():
    m = upsert_manual(
        'liftwp-guide',
        title='liftwp',
        subtitle='A deterministic WordPress-to-Django theme translator',
        format='short',
        author='Velour / Datalift',
        version='1.0',
        abstract=(
            'liftwp translates a WordPress theme directory into Django '
            'templates, views, and URL patterns — no LLM, no network, '
            'no runtime dependency on PHP. It pairs with genmodels and '
            'ingestdump (which port the data side) to give you a '
            'browsable Django site lifted from a legacy WordPress '
            'install. This guide walks through what it translates, what '
            'it deliberately does not, how to wire the output into your '
            'project, and how to use browsershot/shotdiff to verify the '
            'lift visually against the original.'
        ),
        edition='First edition',
        license='CC BY-SA 4.0',
        copyright_year='2026',
        copyright_holder='Velour Project',
    )

    upsert_section(m, 'why-liftwp', 0,
                   'Why liftwp exists', """
WordPress is a PHP application stack. Django is a Python application
stack. Porting a WP site to Django by hand has two distinct halves:

- **The data half:** translate a MySQL schema and dataset into Django
  models with a working SQLite (or Postgres) database. Datalift's
  `genmodels` and `ingestdump` cover this.

- **The presentation half:** translate the theme's PHP templates into
  Django templates, plus generate views and URL patterns that read
  from the lifted models.

`liftwp` covers the second half. It is a *deterministic* translator —
pure regex and Python, no language models in the loop. That means it
runs in milliseconds, produces the same output every time, and is
something you can audit. It also means it can only translate patterns
it knows about; anything else is honestly preserved as a comment for
the porter.

The design target is the public-facing surface of any standard-shape
WordPress theme: the post list, single post, page, archive (category /
tag / date), 404, search, and partials (header, footer, sidebar,
comments, searchform). Admin screens, plugin hooks, AJAX endpoints,
and theme settings pages are explicitly out of scope.
""", sidenotes=(
        'The split between deterministic translation and AI-augmented '
        'translation is intentional. liftwp is the deterministic floor; '
        'an LLM-assisted Phase 4 layer can be added later for variable '
        'tracking and complex conditionals, but the core stays auditable.'
    ))

    upsert_section(m, 'pipeline', 1,
                   'Where liftwp fits in the pipeline', """
The full Datalift port of a WordPress site is four commands:

```
mysqldump --> genmodels      ==> models.py + admin.py + table_map.json
          --> makemigrations / migrate    (Django standard)
          --> ingestdump      ==> rows loaded into SQLite
          --> liftwp          ==> templates + views_wp.py + urls_wp.py
```

Each step is independent and idempotent: you can re-run `liftwp` after
editing the theme without disturbing your data. You can re-run
`ingestdump` after editing the schema without disturbing your
templates. You can also use `liftwp` against a theme without ever
running `genmodels` — the generated views will reference models you
write yourself, which is occasionally useful when you want a fresh
schema rather than a faithful one.

`liftwp` assumes the target Django app has `Post`, `User`, `Comment`,
`Term`, `TermTaxonomy`, `TermRelationship`, and `Option` models with
the conventional WordPress field names. If you used `genmodels` against
a `wp_*` mysqldump those names line up automatically.
""")

    upsert_section(m, 'quickstart', 2,
                   'Quickstart', """
Assume your Django app is `wp` and your theme lives at
`/themes/mytheme`.

```
python manage.py liftwp /themes/mytheme --app wp
```

Output:

- `templates/wp/index.html`, `single.html`, `page.html`, `archive.html`,
  `404.html`, `search.html`, plus partials (`header.html`, `footer.html`,
  `sidebar.html`, etc.)
- `wp/views_wp.py` — view functions that read from the WP models
- `wp/urls_wp.py` — `path('', views.wp_index, ...)` and friends
- `liftwp_worklist.md` — a per-template log of any unhandled fragments

Then in `myproject/urls.py`:

```
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('wp.urls_wp')),
]
```

And in `settings.py`:

```
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {...},
}]
STATICFILES_DIRS = [BASE_DIR / 'static']
```

Stage the theme's static assets:

```
cp -r /themes/mytheme/{css,js,fonts,style.css,screenshot.png} \\
      static/wp/
```

`runserver` and browse `/`. If the WP `Post` table has any rows with
`post_status='publish'` and `post_type='post'`, they appear on the
index. Click a title to load the single view.
""")

    upsert_section(m, 'output-structure', 3,
                   'What liftwp produces', """
For a typical WP theme, `liftwp` writes four kinds of artifact.

### Translated templates

Each PHP template in the theme becomes a Django template at the
matching path under `templates/<app>/`. Standard names like
`index.php`, `single.php`, `page.php` map to `index.html`,
`single.html`, `page.html` directly. Partials in `template-parts/`,
`parts/`, `partials/`, or `templates/` subdirectories preserve their
relative path: `template-parts/content-single.php` becomes
`templates/wp/template-parts/content-single.html`.

PHP-code files (`functions.php`, anything in `inc/`, `includes/`,
`lib/`, `src/`, `classes/`, files starting with `class-`, files
ending in `-functions.php`) are recognised as code rather than
templates and listed in the worklist as files for manual port. They
are *not* translated — most don't apply to a Django port and what
does apply needs a Django author.

### views_wp.py

A views module that reads from the datalifted WP models. It includes
helper functions:

- `_site_context()` — pulls `blogname` and `blogdescription` from the
  `options` table for use as `{{ blog_name }}` and `{{ blog_description }}`
- `_published_posts(post_type='post')` — base queryset
- `_attach_authors(posts)` — bulk-resolves `posts.post_author` (a bare
  int in WP, not an FK) to `post.author_obj`
- `_attach_comments(posts)` — bulk-attaches approved comments to
  `post.comments_list`
- `_post_ids_for_term(taxonomy, slug)` — joins through `terms`,
  `term_taxonomy`, `term_relationships`
- `_paginate(qs, page)` — wraps Django's `Paginator`

And one view per URL the lifter recognised: `wp_index`, `wp_single`,
`wp_page`, `wp_category`, `wp_tag`, `wp_archive_year`,
`wp_archive_month`, `wp_search`, `wp_404`.

### urls_wp.py

A URLconf with the standard WordPress route shapes:

```
path('',                              views.wp_index,         name='wp_index')
path('post/<int:post_id>/',           views.wp_single,        name='wp_single')
path('page/<int:page_id>/',           views.wp_page,          name='wp_page')
path('category/<slug:slug>/',         views.wp_category,      name='wp_category')
path('tag/<slug:slug>/',              views.wp_tag,           name='wp_tag')
path('<int:year>/',                   views.wp_archive_year,  name='wp_archive_year')
path('<int:year>/<int:month>/',       views.wp_archive_month, name='wp_archive_month')
path('search/',                       views.wp_search,        name='wp_search')
```

### Default partial templates

When a translated template references a partial via
`{% include 'wp/X.html' %}` but the theme didn't ship its own copy,
`liftwp` writes a sensible default:

- `comments.html` — iterates `post.comments_list`, includes the
  per-comment partial
- `comment.html` — one comment row
- `pagination.html` — previous / next page links driven by the Django
  `Paginator`
- `searchform.html` — form posting to `wp_search` (or to `/` if no
  search.php was lifted)
- `sidebar.html` — wraps `searchform.html`

Auto-emission is fixed-point: the default `sidebar.html` includes
`searchform.html`, so both land. Default `searchform.html` uses
`{% url 'wp_search' as wp_search_url %}` so it never raises
`NoReverseMatch` if the search route isn't wired.
""")

    upsert_section(m, 'translation-table', 4,
                   'What translates deterministically', """
The translator recognises about seventy WordPress template tags and
the standard control-flow shapes. The table below covers the most
common.

### The Loop

```
<?php if ( have_posts() ) : while ( have_posts() ) : the_post(); ?>
   <article>
     <h2><a href="<?php the_permalink(); ?>"><?php the_title(); ?></a></h2>
     <?php the_excerpt(); ?>
   </article>
<?php endwhile; else : ?>
   <p>No posts yet.</p>
<?php endif; ?>
```

becomes

```
{% if posts %}{% for post in posts %}
   <article>
     <h2><a href="{% url 'wp_single' post.id %}">{{ post.post_title }}</a></h2>
     {{ post.post_excerpt }}
   </article>
{% endfor %}{% else %}
   <p>No posts yet.</p>
{% endif %}
```

### Template tags

| WP tag                              | Django output                                    |
|---|---|
| `the_title()`                       | `{{ post.post_title }}`                          |
| `the_content()`                     | `{{ post.post_content|safe }}`                   |
| `the_excerpt()`                     | `{{ post.post_excerpt }}`                        |
| `the_permalink()`                   | `{% url 'wp_single' post.id %}`                  |
| `the_date()`                        | `{{ post.post_date|date:"F j, Y" }}`             |
| `the_author()`                      | `{{ post.author_obj.display_name|default:"Anonymous" }}` |
| `bloginfo('name')`                  | `{{ blog_name }}`                                |
| `bloginfo('description')`           | `{{ blog_description }}`                         |
| `wp_head()`                         | `{% block extra_head %}{% endblock %}`           |
| `wp_footer()`                       | `{% block extra_foot %}{% endblock %}`           |
| `get_header()`                      | `{% include 'wp/header.html' %}`                 |
| `get_footer()`                      | `{% include 'wp/footer.html' %}`                 |
| `get_sidebar()`                     | `{% include 'wp/sidebar.html' %}`                |
| `get_sidebar('content-bottom')`     | `{% include 'wp/sidebar-content-bottom.html' %}` |
| `get_template_part('a/b', 'c')`     | `{% include 'wp/a/b-c.html' %}`                  |
| `comments_template()`               | `{% include 'wp/comments.html' %}`               |
| `the_posts_pagination(...)`         | `{% include 'wp/pagination.html' %}`             |
| `the_archive_title(...)`            | `{{ archive_title|default:"Archive" }}`          |

Tags accept any argument list — `the_archive_title('<h1>', '</h1>')`
matches the same rule as `the_archive_title()`. The arguments are
ignored because they're formatting hints whose exact meaning doesn't
translate.

### Comment loop

`have_comments()`, `wp_list_comments()`, `comments_number()`,
`comment_author()`, `comment_text()`, `comment_date()` all translate
to a `{% for c in post.comments_list %}`-style block reading from
the bulk-attached comments queryset. `comments_open()` and
`comment_form()` are display-only — submission is out of scope.

### Pagination

`next_posts_link()`, `previous_posts_link()`, `the_posts_pagination()`,
`posts_nav_link()`, `paginate_links()` map to Django's `Paginator`
hooks (`posts.has_next`, `posts.next_page_number`).
`the_comments_pagination()` and the per-comment cousins do the same
but use `?cpage=N` for the comment page.

### i18n and escape wrappers

Wrappers like `_e()`, `__()`, `_x()`, `_n()`, `_nx()`, `esc_html()`,
`esc_attr()`, `esc_url()`, `esc_html__()`, `esc_attr_e()`,
`wp_kses_post()`, `sanitize_text_field()`, `intval()`, etc. unwrap
to their first string argument. Recursive: `esc_html(_nx('singular',
'plural', $n, 'ctx', 'domain'))` extracts to `singular`.

### printf

`printf("Search Results for: %s", get_search_query())` becomes
`Search Results for: {{ search_query }}`. The translator handles
`%s`, `%d`, `%f`, `%i`, and positional `%1$s` placeholders, with
arguments that are either string literals (rendered verbatim) or
calls in the function table (rendered as their Django translation).

### Control flow

Both alt-syntax (`if (...) : ... endif;`) and brace-syntax
(`if (...) { ... }`) work. Conditions the lifter can't evaluate
default to `{% if False %}` with the original PHP condition preserved
as a Django comment so a porter can re-enable the branch by hand.

### Variables

`$var = ...` assignments emit `{# php: $var = ... #}`. `++$var` and
`$var .= ...` drop silently. `echo $var` becomes `{{ var }}` (the
variable likely isn't in template context — this is the best the
translator can do without a custom view). `echo $var ? 'A' : 'B'`
becomes a proper `{% if var %}A{% else %}B{% endif %}`.
""")

    upsert_section(m, 'theme-internal-functions', 5,
                   'Theme-internal functions', """
WordPress themes typically define their own helper functions in
`inc/template-tags.php` or `functions.php`. Examples from the default
themes: `twentysixteen_post_thumbnail()`,
`twenty_twenty_one_entry_meta_footer()`,
`twentyfourteen_paging_nav()`.

`liftwp` reads the theme's `inc/`, `includes/`, `lib/`, `src/`,
`classes/` directories and `functions.php` at parse time and
collects every `function name()` definition into a set. Any call to
one of these functions from a template becomes a quiet
`{# theme function NAME() — port manually #}` marker rather than
worklist noise.

The intent is honesty: those functions emit theme-specific HTML that
can't be deterministically translated, but they're not a translator
bug — they're work for the porter. The marker tells the porter
exactly what to write.

A directory-name prefix heuristic is also applied as a fallback,
in case the `inc/` files aren't readable. For a theme directory named
`mytheme`, any call to `mytheme_*` is treated as theme-internal.
""")

    upsert_section(m, 'worklist', 6,
                   'The worklist', """
At project root after each lift, you'll find `liftwp_worklist.md`. It
has four sections:

- **Translated templates** — one bullet per `.php` file the lifter
  picked up, with its target Django path and a count of unhandled
  fragments.
- **Theme files we did not translate** — `functions.php` and other
  PHP-code files. These need a Django author.
- **Static assets passed through** — every `.css`, `.js`, `.woff`,
  `.png`, etc. with its `static/<app>/` target path.
- **Per-template unhandled PHP fragments** — for each translated
  template that had any unhandled PHP, the literal PHP statements
  the translator left as `{# WP-LIFT? ... #}` markers.

The fragment list is the porter's TODO. If a template has zero
fragments, the lifter handled every PHP statement it saw — which
doesn't mean the page renders pixel-perfectly (variables and
computed flags can still break visual fidelity), but it does mean
no manual translation is required at the PHP-fragment level.

For the ten official WordPress default themes (Twenty Twelve through
Twenty Twenty-One) plus the Underscores starter, every template
lifts with zero unhandled fragments — 232 templates total.
""")

    upsert_section(m, 'verifying', 7,
                   'Verifying with browsershot + shotdiff', """
After lifting, you want to know whether the Django port matches the
legacy site visually. Two tools, both in the `datalift` app.

`browsershot` snaps a full-page PNG of any URL using Playwright +
Chromium:

```
python manage.py browsershot https://legacy.example/post/42 \\
    --out before.png
python manage.py browsershot http://127.0.0.1:8000/post/42/ \\
    --out after.png
```

`shotdiff` overlays the two:

```
python manage.py shotdiff before.png after.png --out diff.png
```

The output PNG shows `after` desaturated to grayscale with every
pixel whose channel-wise delta exceeds the threshold (default 16)
painted bright red. The command also prints the diff-pixel
percentage and the maximum per-channel delta. Anything under 1% is
usually a font-rendering or CSS rounding difference; visible
content shifts show up as obvious red regions.

This is the verification primitive. A higher-level "lift this whole
site, snap every page on both sides, diff each pair" workflow could
be built on top, but is not currently part of `liftwp`.
""", sidenotes=(
        'The 16-per-channel default threshold is conservative — it '
        'accepts subpixel font hinting differences but flags any colour '
        'or layout change. Drop to 4 if you want to catch font rendering, '
        'raise to 64 if you only care about gross layout.'
    ))

    upsert_section(m, 'wiring', 8,
                   'Wiring liftwp output into a project', """
Three project-level edits are needed beyond running `liftwp`.

### settings.py

```
TEMPLATES = [{
    ...,
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    ...,
}]
STATICFILES_DIRS = [BASE_DIR / 'static']
```

`liftwp` writes to `templates/<app>/` (project-level), so
`TEMPLATES.DIRS` must include `BASE_DIR / 'templates'`. The
`APP_DIRS=True` setting alone won't find them.

`STATICFILES_DIRS` is needed because `liftwp` also writes to
`static/<app>/` (project-level) and the dev server only auto-discovers
inside `<app>/static/<app>/` (app-level).

### urls.py

```
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('<app>.urls_wp')),
]
```

Mount the lifted URLs wherever you want them. Mounting at `''`
matches WordPress's permalink shapes.

### Static assets

```
cp -r /path/to/theme/{css,js,fonts,style.css,screenshot.png} \\
      static/<app>/
```

`liftwp` registers the asset paths in the worklist but doesn't move
the files itself — you copy them once. After that, references like
`{% static 'wp/style.css' %}` in the lifted templates resolve.
""")

    upsert_section(m, 'limitations', 9,
                   'Known limitations', """
liftwp is honest about what it cannot do.

- **PHP variable tracking.** A theme's header.php commonly contains
  `$site_name = get_bloginfo('name', 'display');` followed by
  `if ($site_name && is_front_page()) : echo $site_name; endif;`.
  The translator records the assignment as a comment, but the if-block
  becomes `{% if False %}` and nothing renders. The fix is on the
  porter: replace the if-block with a direct reference to
  `{{ blog_name }}`, or write a custom view that exposes the variable
  in template context.
- **Custom post types beyond the standard URL surface.** The lifter
  generates routes for `post`, `page`, category, tag, and dates. If
  a theme has `single-event.php` it gets translated as a partial
  but no route binds to it; you wire that yourself.
- **Shortcodes.** `[gallery]`, `[caption]`, `[embed]`, etc. are
  rendered by WP at content-fetch time and are not interpreted by
  the lifter. Shortcode-heavy posts will show the shortcode markup
  literally in the lifted output.
- **Plugin hooks.** `add_action()` and `add_filter()` calls from
  plugins or `functions.php` aren't in scope.
- **Comment submission.** Display only. `comment_form()` becomes a
  no-op marker.
- **Theme settings pages, widgets, the customizer.** Out of scope.
  Widget areas come up as `{# dynamic_sidebar — register widget areas
  manually #}` markers; the porter writes Django views or template
  tags to fill them.
- **AJAX endpoints, REST API routes.** Out of scope.

The shape of these limitations is intentional: liftwp does the work
that's deterministic and leaves a clear marker for everything that
isn't. It does not pretend to be smart.
""")

    upsert_section(m, 'tested-themes', 10,
                   'The tested-themes proof', """
The translator was iterated against every official WordPress default
theme released in the thirteen years from Twenty Twelve through
Twenty Twenty-One, plus the Underscores starter template. Every
theme lifts with zero unhandled fragments. 232 translated templates
total.

| Theme               | Templates | Unhandled |
|---|---:|---:|
| Twenty Twelve       | 20 | 0 |
| Twenty Thirteen     | 25 | 0 |
| Twenty Fourteen     | 25 | 0 |
| Twenty Fifteen      | 15 | 0 |
| Twenty Sixteen      | 18 | 0 |
| Twenty Seventeen    | 26 | 0 |
| Twenty Nineteen     | 19 | 0 |
| Twenty Twenty       | 18 | 0 |
| Twenty Twenty-One   | 32 | 0 |
| Underscores starter | 14 | 0 |

Note: "zero unhandled" is a translator-coverage claim, not a
visual-fidelity claim. Pages render with structure and content
correct, but theme-specific styling that depends on PHP variable
tracking will need a porter to wire properly. See the Limitations
section.

The Twenty Twenty-Two and later themes are *block themes* (built
around the Gutenberg block editor and Full Site Editing JSON), not
classical PHP themes. These are a different format and are not
in scope for liftwp.
""")

    upsert_section(m, 'when-to-port-by-hand', 11,
                   'When to drop into manual porting', """
liftwp gives you a working starting point. A complete port may still
benefit from manual work in these areas:

- **Site title and tagline rendering** if the theme uses variable
  assignments in `header.php`. Replace the false-gated branches with
  direct `{{ blog_name }}` / `{{ blog_description }}` references.
- **Featured images** (`the_post_thumbnail()`). The lifter emits a
  marker; wire your own image field on `Post` or use a generic
  attachments lookup.
- **Navigation menus** (`wp_nav_menu()`). Build a small Django model
  for menu items and a template tag that renders it.
- **Comment submission.** Add a Django form + POST view if you want
  comments to be writeable.
- **Custom post types.** Add views and URL routes for any
  `single-X.php` partials the lifter translated but didn't route.
- **Shortcodes.** Register Django template filters for the ones
  you actually use.

Each of these can be done independently and incrementally. The lifter
output is normal Django code — there's no special "lifted mode" to
maintain. Once you've ported what matters, you own the templates and
views like any other Django project.
""")


def seed_datalift_overview():
    m = upsert_manual(
        'datalift',
        title='Datalift',
        subtitle='Lift legacy MySQL/PHP sites into Django',
        format='short',
        author='Velour / Datalift',
        version='1.0',
        abstract=(
            'Datalift is a deterministic toolkit that turns a legacy '
            'MySQL+PHP site into a runnable Django+SQLite project. The '
            'data half (genmodels, ingestdump, dumpschema) translates '
            'a mysqldump into Django models and loads the rows. The '
            'presentation half (liftsite, liftphp, liftwp) lifts '
            'static assets, scans PHP for secrets, and translates '
            'WordPress themes. browsershot and shotdiff close the '
            'loop with visual verification. Everything runs locally, '
            'in milliseconds, with no LLM in the path.'
        ),
        edition='First edition',
        license='CC BY-SA 4.0',
        copyright_year='2026',
        copyright_holder='Velour Project',
    )

    upsert_section(m, 'what-it-is', 0,
                   'What Datalift is', """
A Velour app at `/datalift/`. Eight management commands. About 7000
lines of Python with 258 regression tests covering ten WordPress
themes, eleven mysqldump dialects, and every fix that ever surfaced
during a real corpus port.

The promise is narrow: take a `mysqldump` (or PostgreSQL `pg_dump
--inserts`) plus optionally the legacy site's filesystem tree, and
emit a Django app with working models, the rows loaded, the static
assets staged, the WordPress theme translated to Django templates,
and a worklist showing what still needs a human. No part of this
sends any byte over the network. No part calls an LLM. The whole
pipeline runs in well under a minute on a million-row dump.

The promise it does not make: pixel-perfect visual fidelity on
arbitrary themes, or a full port of plugin-driven business logic.
Those need a porter. Datalift gives the porter a starting point
that's rich enough to browse, narrow enough to audit, and
predictable enough to re-run.
""", sidenotes=(
        'The "no LLM" rule is a design constraint, not a values '
        'statement. A future Phase 4 layer may opt into an LLM for '
        'specific narrow jobs (variable tracking, complex conditionals) '
        'gated behind a flag. The core stays auditable.'
    ))

    upsert_section(m, 'commands', 1,
                   'The eight commands', """
| Command       | What it does                                                    |
|---|---|
| `dumpschema`  | Slice the schema out of a mysqldump for a Claude-safe review.   |
| `genmodels`   | Parse CREATE TABLE blocks → emit `models.py` + `table_map.json`.|
| `ingestdump`  | Parse INSERT blocks → load rows into the generated models.      |
| `liftsite`    | Move HTML/JS/CSS/static assets into Django's `templates/static/`.|
| `liftphp`     | Scan PHP for secrets/PII; optionally write redacted copies.     |
| `liftwp`      | Translate a WordPress theme into Django templates+views+urls.   |
| `browsershot` | Take a real-browser PNG screenshot of any URL.                  |
| `shotdiff`    | Diff two PNGs and emit an overlay highlighting the changes.     |

Each command has its own manual in this set. Read this one for the
shape; jump to the command-specific manual for the details.
""")

    upsert_section(m, 'pipeline', 2,
                   'A typical port, end to end', """
A complete port of a legacy WordPress install through Datalift looks
like this:

```
# 1. Schema audit (optional but recommended).
manage.py dumpschema legacy.sql --out schema.sql
# review schema.sql by hand; it has no row data.

# 2. Generate models from the dump.
manage.py genmodels legacy.sql --app wp
# review wp/models.py; rename anything ugly; promote junction tables.

# 3. Migrate.
manage.py makemigrations wp && manage.py migrate

# 4. Load data.
manage.py ingestdump legacy.sql --app wp \\
    --map wp/ingest/table_map.json --truncate

# 5. Sanity-check the PHP tree before sharing it.
manage.py liftphp /legacy/site --app wp --strict --redact

# 6. Lift the static assets.
manage.py liftsite /legacy/site --app wp

# 7. Lift the WordPress theme.
manage.py liftwp /legacy/site/wp-content/themes/mytheme --app wp

# 8. Visual verification.
manage.py browsershot https://legacy.example/      --out before.png
manage.py browsershot http://127.0.0.1:8000/       --out after.png
manage.py shotdiff before.png after.png --out diff.png
```

Steps 1-4 are the data half. Steps 5-7 are the presentation half.
Step 8 is the verification half. Each step is independent and
idempotent — re-running step 7 doesn't disturb step 4, and so on.
""")

    upsert_section(m, 'corpora', 3,
                   'What it has been tested against', """
The data half (`genmodels` + `ingestdump`) has been validated end-to-end
on these corpora:

- **Sakila** (MySQL film-rental sample, 16 tables)
- **Pagila** (PostgreSQL film-rental sample, 16 tables, via `pg_dump --inserts`)
- **Chinook** (SQL-Server origin music store, 11 tables)
- **employees** (MySQL HR sample, 6 tables, 3.9M rows in 2m33s)
- **MediaWiki** (32 tables, dialect placeholders)
- **WordPress** (20+ tables, multisite included)
- **Joomla** (#__-prefixed tables)
- **PrestaShop** (ps_-prefix conventions)
- **MyBB** (forum schema)
- **Dolibarr ERP** (409 tables, multitenant placeholders)
- **Oracle HR** (Oracle dialect — VARCHAR2 / NUMBER / TO_DATE)
- **Babybase / Laravel** (custom Laravel app, soft deletes)

The presentation half (`liftwp`) has been validated against the
ten official WordPress default themes (Twenty Twelve through
Twenty Twenty-One) plus the Underscores starter — 232 templates,
zero unhandled fragments per theme.
""")

    upsert_section(m, 'privacy', 4,
                   'Privacy posture', """
Datalift assumes the data being lifted is potentially sensitive
(real user PII, credentials, internal email addresses). The toolkit
is designed to keep that data on the lifting machine.

- **No outbound network calls.** Every command operates on local
  files. There is no telemetry, no version-check, no font-fetch,
  no plugin-update.
- **No LLM in the path.** Translation is deterministic regex/AST.
  An assistant *can* be involved, but only by reading a prepared
  artifact (`schema.sql` from `dumpschema`, redacted PHP from
  `liftphp --redact`, the worklist Markdown) — never the raw dump.
- **`dumpschema` strips data values** so the schema can be shared
  for review without leaking rows.
- **`liftphp` finds secrets** (DB credentials, API keys, private
  keys, basic-auth URLs, email PII, inline INSERTs with row data)
  and reports them with masked snippets — never the raw secret.
  `--redact` writes parallel files with findings replaced by
  `/*<<REDACTED_CATEGORY>>*/` markers; `--strict` exits nonzero
  if any finding is present.

These properties are tested. The only data that ever touches the
network is the data you choose to deploy after reviewing it.
""", sidenotes=(
        'The "Claude-safe" framing in some docstrings reflects how '
        'this toolkit grew up — alongside an AI assistant — and the '
        'discipline of never feeding row data into the assistant '
        'context. The same posture applies whether the reader is an '
        'LLM or a colleague.'
    ))

    upsert_section(m, 'when-not', 5,
                   'When Datalift is not the right tool', """
- **Block themes** (Twenty Twenty-Two and later WordPress defaults).
  These are JSON + block markup, not classical PHP themes. liftwp
  doesn't read them. A separate "block theme to Django" lifter
  would be a different design.
- **Plugin-heavy sites** where most of the rendering lives in plugin
  shortcodes. Datalift translates the data and the theme; plugins
  need a porter.
- **Sites with their own application logic in PHP.** liftphp scans
  for secrets but does not translate business logic into Python.
  An assistant can read the redacted PHP and write the equivalent
  Django views by hand.
- **Greenfield Django projects.** Datalift is a porting tool. If
  you're not porting from MySQL+PHP, none of these commands apply.

In all of these cases the right answer is to use Datalift for the
parts it covers (data, schema, static assets, secret-scanning) and
write the rest by hand.
""")

    upsert_section(m, 'reading-order', 6,
                   'Suggested reading order', """
Most readers want one of three things:

- **Read about a specific command.** Each command has its own manual
  in this set. The Quickstart manuals are one-page recipes for the
  most common path.
- **Port a real legacy site end-to-end.** Read the four data manuals
  in pipeline order: `dumpschema` (1pp), `genmodels` (~12pp),
  `ingestdump` (~12pp), then the three presentation manuals
  (`liftsite`, `liftphp`, `liftwp`), then the two verification
  manuals (`browsershot`, `shotdiff`).
- **Understand the design.** Read this overview, then `liftwp` for
  the deepest treatment of how a deterministic translator handles
  a real corpus.

All ten manuals are in the same Codex installation, browseable at
`/codex/`. Each has an HTML render, a PDF render, and is tracked
through Codex's standard versioning.
""")


def seed_dumpschema_quickstart():
    m = upsert_manual(
        'dumpschema-quickstart',
        title='dumpschema — Quickstart',
        subtitle='Slice the schema out of a mysqldump',
        format='quickstart',
        author='Velour / Datalift',
        version='1.0',
        abstract=(
            'Strip every INSERT, every LOCK TABLES, every '
            'AUTO_INCREMENT count out of a mysqldump and keep just '
            'the CREATE TABLE / CREATE INDEX / ALTER TABLE blocks. '
            'The result is safe to share with an assistant.'
        ),
    )
    upsert_section(m, 'recipe', 0, 'The recipe', """
```
python manage.py dumpschema /path/to/legacy_full_dump.sql \\
    --out schema.sql
```

Output: `schema.sql` containing only the structural statements. No
INSERTs, no row data, no `LOCK TABLES`, no `AUTO_INCREMENT=NN`
metadata. Safe to read out loud, paste into a chat with an assistant,
or attach to a ticket.

Useful precisely because the original dump may contain real PII,
real credentials, or real customer data that you don't want to
spread further than necessary. After `dumpschema`, you and a porter
(human or AI) can discuss the schema design without that risk.

Next step is usually `manage.py genmodels` against the original
(full) dump — `genmodels` reads only the CREATE TABLE statements
itself, but having `schema.sql` on disk gives you a stable reference
for review.
""")


def seed_genmodels_guide():
    m = upsert_manual(
        'genmodels-guide',
        title='genmodels',
        subtitle='Generate Django models from a mysqldump',
        format='short',
        author='Velour / Datalift',
        version='1.0',
        abstract=(
            'genmodels parses CREATE TABLE blocks out of a mysqldump '
            '(or pg_dump --inserts file) and emits a Django models.py '
            'plus a starter table_map.json. It handles MySQL, '
            'PostgreSQL, SQL-Server, and Oracle dialect quirks; '
            'recognises composite primary keys, post-hoc PK ALTERs, '
            'inline and separate FOREIGN KEY clauses, ENUM/SET, '
            'unsigned integers, and a long list of CMS-specific '
            'prefix conventions. Every generated file is meant to '
            'be reviewed; nothing is authoritative.'
        ),
        edition='First edition',
        license='CC BY-SA 4.0',
        copyright_year='2026',
        copyright_holder='Velour Project',
    )

    upsert_section(m, 'what-it-does', 0, 'What genmodels does', """
genmodels takes a SQL dump and writes three artifacts:

- `<app>/models.py` — one `class` per CREATE TABLE, with field types
  inferred from SQL types and constraints, an `class Meta` block
  pinning `db_table` and `ordering`, plus `__str__` heuristics.
- `<app>/admin.py` — `ModelAdmin` registrations with reasonable
  defaults for `list_display`, `search_fields`, `list_filter`,
  `raw_id_fields`, and `date_hierarchy` (only when the column
  is actually date-shaped).
- `<app>/ingest/table_map.json` — a starter mapping from legacy
  table names to model paths. Edit this before running `ingestdump`.

The generated `models.py` is meant to be read and edited. The
inference is best-effort: it'll get most of it right, but renaming
classes, promoting junction tables to ManyToMany relations, and
splitting wide-but-related tables are work for the porter.
""")

    upsert_section(m, 'invocation', 1, 'Invocation', """
```
python manage.py genmodels path/to/dump.sql \\
    --app myapp \\
    [--out myapp/models.py] \\
    [--map-out myapp/ingest/table_map.json] \\
    [--source-database <name>]
```

`--source-database` is used in the `verbose_name` of each model and
in a docstring header in the generated file. It's purely cosmetic
but useful when porting several databases into one project.

The command exits 0 on success and prints a per-table summary:
`<table_name> → <ModelName> (<n> fields, <m> FKs)`. Skipped tables
(views, system tables) are noted separately.
""")

    upsert_section(m, 'dialect-handling', 2, 'Dialect handling', """
Legacy SQL dumps differ wildly in detail. genmodels recognises:

### Table-name placeholders

Many CMS dumps wrap table names with installer placeholders. genmodels
strips them all:

- MediaWiki: `CREATE TABLE /*_*/actor`
- WordPress: `CREATE TABLE $wpdb->users`, `${wpdb}->termmeta`
- Joomla: `CREATE TABLE #__users`
- PrestaShop / osCommerce: `PREFIX_orders`, `DB_PREFIX_customers`
- Generic: `{PREFIX}_tablename`
- Schema-qualified: `public.customer`, `dbo.Orders`,
  `"public"."my_table"`

Plus an automatic common-prefix detector: if every table in the
dump starts with the same `xxx_`, that stem is stripped. This
handles Dolibarr's `llx_`, vBulletin's `vb_`, legacy WordPress's
`wp_`, etc., without configuration.

### Type inference

| Source family   | Members                                                |
|---|---|
| Integer         | `tinyint`, `smallint`, `mediumint`, `int`, `bigint`, Postgres `int2/4/8`, `serial`, `bigserial`, with signed↔unsigned routing |
| Float           | `float`, `double`, `real`, `float4/8`                  |
| Decimal         | `decimal(M,D)`, Oracle `numeric(M,D)`                  |
| Char            | `char`, `varchar`, SQL-Server `nchar`, `nvarchar`, Oracle `varchar2`, Postgres `bpchar` |
| Text            | `text` family, Postgres `citext`, SQL-Server `ntext`   |
| Date            | `date`, `time`, `timestamp`, `datetime`, Postgres tz-aware variants, SQL-Server `datetime2`, `smalldatetime` |
| Binary          | `blob` family, Postgres `bytea`, SQL-Server `image`, Oracle `raw` |
| JSON            | `json`, `jsonb`                                        |
| UUID            | `uuid`, `uniqueidentifier`                             |

### Special cases

- `ENUM('A','B')` → an inner `class TextChoices`-style class plus
  a `CharField(choices=...)`. Case is preserved.
- `SET('A','B')` → `CharField` with help text noting the legacy
  comma-separated semantics (Django doesn't have a native SET).
- Email-shaped column names (`*_email`, `email`) → `EmailField`.
- URL-shaped column names (`*_url`, `link`) → `URLField`.
- Slug-shaped column names (`slug`, `*_slug`) → `SlugField`.
""")

    upsert_section(m, 'structural-patterns', 3,
                   'Structural patterns', """
SQL dumps express the same structural intent in a half-dozen
different ways. genmodels reads all of them.

### Primary keys

- Inline: `id BIGINT PRIMARY KEY AUTO_INCREMENT`
- Trailing on a single column: `id smallint PRIMARY KEY` (Dolibarr)
- Trailing tuple: `PRIMARY KEY (id, tenant_id)` → composite,
  emitted as a `UniqueConstraint` (Django requires a single column
  for `primary_key=True`)
- Post-hoc ALTER (pg_dump): `ALTER TABLE foo ADD CONSTRAINT foo_pkey
  PRIMARY KEY (id)`
- Dolibarr-style permissive: `ALTER TABLE foo ADD PRIMARY KEY pk_foo
  (id)` (no CONSTRAINT keyword)

When a composite PK includes a column literally named `id`, that
column gets `primary_key=True` (Django reserves the name `id` for
PKs and would otherwise create a duplicate auto-id).

### Auto-increment

Both MySQL `AUTO_INCREMENT` and Postgres `DEFAULT
nextval('seq_name')` are recognised and emitted as
`BigAutoField(primary_key=True)`.

### Foreign keys

- Inline: `FOREIGN KEY (x) REFERENCES t (x) ON DELETE CASCADE`
- Separate ALTER: `ALTER TABLE t ADD CONSTRAINT … FOREIGN KEY …`
  (Chinook, pg_dump)
- Non-PK target: when a FK references a column that isn't the
  target's PK, `to_field='colname'` is emitted and the target column
  is promoted to `unique=True`.

### Other

- Duplicate `CREATE TABLE` (WordPress single-site vs multisite
  schemas in one dump) — last definition wins, with a worklist note.
- Reserved Python identifiers as column names — suffixed with `_`
  in the model field name and remapped via `db_column='original'`.
- Column comments — propagated as `help_text`.
""")

    upsert_section(m, 'admin-inference', 4, 'admin.py inference', """
genmodels also writes `<app>/admin.py` with one `ModelAdmin` per
generated model. Defaults:

- `list_display` — id, the most-name-shaped CharField (heuristic:
  ends in `name`, `title`, `label`), the first DateTimeField.
- `search_fields` — every CharField, TextField, EmailField, SlugField.
- `list_filter` — every BooleanField, ForeignKey, DateField. Capped
  at six entries to keep the sidebar usable.
- `raw_id_fields` — every ForeignKey to a table with > 100 rows
  (avoids the giant select-dropdown on writes).
- `date_hierarchy` — the first DateField only when the underlying
  SQL type was actually date-shaped. (MyBB stores dates as
  Unix-epoch ints; those get no hierarchy.)

The generated admin is meant to be a starting point. Edit before
shipping; the heuristics are deliberately conservative.
""")

    upsert_section(m, 'table-map', 5, 'The starter table_map.json', """
genmodels emits `<app>/ingest/table_map.json` alongside the models.
This is the file `ingestdump` reads to learn how to map legacy
tables to your (possibly renamed) Django models.

The starter file maps every CREATE TABLE one-to-one:

```json
{
  "tables": {
    "users":  "myapp.User",
    "posts":  "myapp.Post",
    "comments": "myapp.Comment"
  }
}
```

Edit it to add per-table customisation. The full schema is
documented in the `ingestdump` manual (drop_columns, value_maps,
synthesize, dedupe_by, rewrite_laravel_passwords, skip_tables).
The shorthand `"users": "myapp.User"` is equivalent to
`"users": {"model": "myapp.User"}`.
""")

    upsert_section(m, 'review-checklist', 6, 'Review checklist', """
The generated `models.py` is a starting point. Read every model
before migrating. Things to look for:

- **Junction tables.** A CREATE TABLE with exactly two FKs and no
  other meaningful columns is almost certainly a many-to-many
  bridge. Promote it to `ManyToManyField` on one side and delete
  the bridge model.
- **Class names.** PascalCase is applied automatically but the
  result might be ugly: `WpPostmeta` should probably become just
  `PostMeta`. Renaming here is one git diff; renaming after migration
  is many.
- **TextField vs CharField.** Anything that's intuitively short and
  searchable (titles, names, slugs) might have been emitted as
  `TextField` because the SQL type was MEDIUMTEXT or LONGTEXT.
  Convert to CharField with an explicit max_length if it matters.
- **NULL vs default.** genmodels copies the SQL `DEFAULT` and
  `NOT NULL` exactly. Sometimes the legacy schema is sloppy —
  `comment TEXT NOT NULL` with rows that contain empty strings,
  for example. Adjust to match what your Django app needs.
- **Chemistry between models.** If two models conceptually relate
  (Post and Author) but the legacy schema didn't enforce a FK
  (WordPress does this with `posts.post_author` as a bare int),
  decide whether to add a real ForeignKey now or use a bulk
  resolver in views (see liftwp's `_attach_authors`).
""")

    upsert_section(m, 'caveats', 7, 'Caveats and limits', """
- **CREATE VIEW / TRIGGER / PROCEDURE / FUNCTION.** Bodies are
  stripped from the INSERT scan (so trigger code's literal
  `INSERT INTO` fragments don't look like data). Views themselves
  aren't translated into Django code; they need a manual
  query-level port.
- **`COPY ... FROM stdin` blocks** (pg_dump without `--inserts`).
  Not currently parsed. Use `pg_dump --inserts` or the
  `pagila-insert-data.sql` variant.
- **Multi-tenant data.** If the logical PK is `(tenant, rowid)`
  and all `__TENANT__` placeholders collapse to one value, rows
  collide on the physical PK. Cross-batch dedup drops duplicates;
  to import a specific tenant, filter via `value_maps` or
  pre-process the dump.
- **`schema.rb` / Laravel migration files.** Only raw SQL dumps;
  not ORM migration files.
- **Generated columns / virtual columns.** Skipped — Django doesn't
  have a clean equivalent. The column is recorded in the worklist.
""")


def seed_ingestdump_guide():
    m = upsert_manual(
        'ingestdump-guide',
        title='ingestdump',
        subtitle='Load mysqldump rows into Django models',
        format='short',
        author='Velour / Datalift',
        version='1.0',
        abstract=(
            'ingestdump reads INSERT statements out of a SQL dump and '
            'writes the rows into the matching Django models. It '
            'handles dialect quirks (NOW(), 0xDEADBEEF, _binary, '
            'N\'unicode\', /*!50705 ...*/, __TENANT__ placeholders), '
            'comment skipping (-- # /* */), per-row value coercions, '
            'cross-batch deduplication, and graceful error continuation. '
            'Validated against ten corpora including a 3.9-million-row '
            'employees dump that lifts in 2m33s.'
        ),
        edition='First edition',
        license='CC BY-SA 4.0',
        copyright_year='2026',
        copyright_holder='Velour Project',
    )

    upsert_section(m, 'invocation', 0, 'Invocation', """
```
python manage.py ingestdump path/to/full_dump.sql \\
    --app myapp \\
    [--map myapp/ingest/table_map.json] \\
    [--truncate] \\
    [--chunk 500] \\
    [--dry-run] \\
    [--no-fk-sweep] \\
    [--continue-on-error] [--max-errors 100]
```

Common path:

```
manage.py ingestdump dump.sql --app myapp \\
    --map myapp/ingest/table_map.json --truncate
```

`--truncate` empties target tables before loading so the run is
idempotent. Drop it for incremental loads. `--dry-run` parses the
dump and resolves every value but writes nothing.
""")

    upsert_section(m, 'value-parsing', 1, 'Value parsing', """
The INSERT row parser handles the union of MySQL, PostgreSQL,
SQL-Server, and Oracle `INSERT ... VALUES` shapes. It recognises:

- **Quoted strings** with `\\\\`, `\\'`, `\\"` escapes.
- **Numeric literals** including negatives and scientific notation.
- **NULL.**
- **Hex literals**: `0xDEADBEEF` → bytes for `BinaryField`,
  hex string for textual columns.
- **SQL-Server Unicode prefix**: `N'Rock'` → `'Rock'`.
- **Postgres booleans**: `true` / `false` / `t` / `f` → Python
  `bool`.
- **Postgres bytea hex**: `'\\x...'` → bytes.
- **SQL functions in default position**:
  `CURRENT_TIMESTAMP()`, `NOW()`, `CURDATE()` → tz-aware
  `datetime.now()`. Unknown functions like `DATE_FORMAT(...)`
  are recorded as None with a worklist note.
- **Version-gated values**: `/*!50705 0xABCD */` (Sakila
  BLOBs) → unwrapped, parsed.
- **`_binary 'xxx'` prefix** (MySQL bytea) → bytes.
- **Installer placeholders** like `__ENTITY__` (Dolibarr's tenant
  marker) → None.
""")

    upsert_section(m, 'comment-handling', 2, 'Comment handling', """
SQL dumps include comments in three styles: `-- ...` (line),
`# ...` (MySQL), and `/* ... */` (block, possibly multiline).
ingestdump skips all three everywhere — between statements, inside
column lists, even nested inside the parenthesis-walking loop.

This matters more than it sounds: Dolibarr ships bash snippets
inside `-- for x in ...; echo "INSERT INTO ..."` comments. A naive
INSERT scanner would match those as real INSERTs and try to load
fictional data. ingestdump skips them.

The block-comment skipper is also nesting-aware (some dialects
allow `/*! ... /*!nested!*/ ... */`).
""")

    upsert_section(m, 'row-coercions', 3, 'Per-row value coercions', """
Once a value is parsed, it may need adjusting before it's safe to
hand to a Django model field. The coercions ingestdump performs:

- **Postgres bytea hex**: `'\\x68656c6c6f'` → `b'hello'`.
- **Legacy date strings**: `'2020/3/8'`, `'08-03-2020'`,
  `'20200308'` → ISO `'2020-03-08'`. Detected by shape, not by
  configuration.
- **Empty string into a numeric field** → `None`. Many legacy
  schemas use `''` for "no value" on what should be NULL.
- **None into a NOT NULL field that has a default** → kwarg
  dropped so Django's model default fires. Otherwise the load
  would crash.
- **Unicode normalisation**: NFC. Legacy data often mixes NFD
  (Mac-origin) and NFC (everywhere else); we pick one.
""")

    upsert_section(m, 'table-map', 4, 'The full table_map.json schema', """
Each table-spec value can be a string (just the model path) or a
dict with all of these knobs:

```json
{
  "tables": {
    "users": {
      "model": "myapp.User",
      "drop_columns": ["internal_flag"],
      "value_maps": {
        "gender": {"M": "male", "F": "female", "__default__": "unknown"}
      },
      "synthesize": {
        "username": "email"
      },
      "dedupe_by": "email",
      "rewrite_laravel_passwords": "password"
    }
  },
  "skip_tables": ["migrations", "password_resets"]
}
```

- **`drop_columns`** — silently discard columns from the INSERT.
  Useful for legacy fields that don't exist on the Django model.
- **`value_maps`** — per-column, value-by-value translation. The
  special key `__default__` covers anything the explicit map
  doesn't.
- **`synthesize`** — derive a column from another. Example: legacy
  schema has no `username` column but does have `email` — set
  `{"username": "email"}` and the row's email value lands in
  `username`.
- **`dedupe_by`** — collapse rows on this field. First wins. Useful
  when the legacy schema accidentally allowed duplicate emails or
  similar.
- **`rewrite_laravel_passwords`** — convert Laravel `$2y$` bcrypt
  prefix to Django's `bcrypt$$2b$` format. Names the column to
  rewrite; usually `password`.
- **`skip_tables`** — top-level list of legacy table names to
  ignore entirely (migration metadata, session tables, etc.).
""")

    upsert_section(m, 'dedup', 5, 'Deduplication', """
Two layers of deduplication are always on:

- **Cross-batch PK dedup.** Some dumps repeat the same row across
  multiple INSERT statements (Dolibarr's multicompany data does this
  with `__ENTITY__` placeholders that all collapse to a single
  tenant). The first occurrence wins; subsequent ones are dropped
  and reported in the run summary.
- **Explicit `dedupe_by` field.** Per-table, optional. Collapses
  rows on the named field. Useful when the legacy schema let a
  unique-by-convention field have duplicates.

The dedup layer is what makes idempotent re-runs possible:
`--truncate` empties tables, then dedup ensures one INSERT per
logical row even if the dump contains noise.
""")

    upsert_section(m, 'errors', 6, '--continue-on-error and reporting', """
By default, ingestdump runs every model's load inside one
`atomic()` block. Any error rolls back that table.

`--continue-on-error` drops the table-level atomic wrapper. On any
batch failure the loader falls back to per-row
`save(force_insert=True)` and isolates the offending rows. Each
row-level error is logged as `✗ {table} row {N}: {message}` —
useful when you have a dirty dump with a few rows that won't fit
the model.

`--max-errors=N` caps the number of error lines printed (the load
always completes; this is just display noise control).

The end-of-run summary always prints:

- Per-table: rows ingested, rows skipped (dedup), rows failed.
- Total wall time.
- Cross-table FK sweep: unresolved FK references after the load.
  Suppress with `--no-fk-sweep` if you know your dump has dangling
  references and don't want to see them.
""")

    upsert_section(m, 'performance', 7, 'Performance', """
ingestdump targets sub-minute lifts on million-row dumps. Two
levers:

- **`--chunk N`** controls the `bulk_create` batch size. Default
  500. Larger chunks are faster but use more memory; smaller
  chunks are slower but tolerate larger row sizes.
- **The dump is read once, top to bottom.** No back-and-forth, no
  index pre-build, no second pass.

Reference timings (single-thread, SQLite):

| Dump                  | Tables | Rows  | Wall time |
|---|---:|---:|---:|
| Sakila                | 16     | 47k   | 0.6s      |
| Chinook               | 11     | 15k   | 0.3s      |
| MediaWiki sample      | 32     | 200k  | 8s        |
| WordPress single-site | 22     | 150k  | 7s        |
| Dolibarr ERP          | 409    | 800k  | 1m12s     |
| **employees** (MySQL) | 6      | 3.9M  | **2m33s** |

SQLite is the bottleneck above ~500k rows — same loads against
PostgreSQL are roughly 30% faster.
""")

    upsert_section(m, 'caveats', 8, 'Caveats', """
- **Auto-increment sequences** are not bumped after the load. If
  you re-add rows in the Django admin afterwards, you'll get PK
  collisions. Bump the sequence manually:
  `INSERT INTO sqlite_sequence(name, seq) VALUES('foo', N)` for
  SQLite, or `SELECT setval('foo_id_seq', max(id)) FROM foo;`
  for Postgres.
- **`UNIQUE` constraint violations** during load are reported but
  not auto-resolved. Use `dedupe_by` in the table_map.
- **`NOT NULL` columns with no default** that receive None will
  fail the row (or the batch, without `--continue-on-error`).
  Fix in the table_map (`value_maps` with `__default__`) or in
  the model definition.
""")


def seed_liftphp_guide():
    m = upsert_manual(
        'liftphp-guide',
        title='liftphp',
        subtitle='Scan PHP for secrets and PII before sharing',
        format='short',
        author='Velour / Datalift',
        version='1.0',
        abstract=(
            'liftphp reads a tree of PHP files and reports every '
            'plausible secret, credential, or PII string it finds. '
            'It does this without ever surfacing the raw value: '
            'snippets are masked, categories are tagged, line numbers '
            'are exact. Optional flags write a redacted parallel tree '
            '(--redact) or fail the run if any finding is present '
            '(--strict). Built so that what an assistant sees about '
            'your legacy PHP is something you have looked at first.'
        ),
        edition='First edition',
        license='CC BY-SA 4.0',
        copyright_year='2026',
        copyright_holder='Velour Project',
    )

    upsert_section(m, 'why', 0, 'Why liftphp exists', """
The privacy premise of `liftsite` is that files shown to an
assistant must not carry row data or secrets. HTML/JS/CSS are
relatively low-risk because they're structural. PHP is high-risk
because it mixes structure with inline DB calls, credentials, API
keys, and occasionally fixture data.

liftphp reads PHP and emits structured findings — never the raw
secret. The findings drive three workflows:

1. A worklist annotation listing what's there, by category and
   severity, so you can decide what to do.
2. An optional redacted parallel tree (`--redact`) where every
   finding is replaced by a `/*<<REDACTED_CATEGORY>>*/` marker.
   These redacted files are safe to read with an assistant for
   "translate this PHP to Django" guidance.
3. A pre-share gate (`--strict`) that exits nonzero if any finding
   is present, so CI / pre-commit can refuse the lift until a
   human has cleared it.

No LLM. No subprocess. No network. Pure regex + rules.
""")

    upsert_section(m, 'invocation', 1, 'Invocation', """
```
python manage.py liftphp /path/to/old/site \\
    --app myapp \\
    [--out-dir redacted/] \\
    [--redact] [--strict] \\
    [--worklist worklist.md] \\
    [--dry-run]
```

Common paths:

```
# Scan and append findings to the standard worklist.
manage.py liftphp ./legacy --app myapp

# Write redacted copies and refuse to continue on any finding.
manage.py liftphp ./legacy --app myapp \\
    --redact --out-dir ./legacy-redacted/ --strict
```

Exit codes:

- `0` — scan complete, zero findings or `--strict` not set.
- `2` — scan complete with findings AND `--strict` is set.
- `1` — scan failed (path not found, app not registered, etc.).
""")

    upsert_section(m, 'finding-categories', 2, 'Finding categories', """
The current rule set covers eight categories. False positives are
preferred over false negatives — every finding is human-reviewed
anyway.

| Category              | Severity | Pattern                                                  |
|---|---|---|
| `db-credentials`      | critical | `mysql_connect(...)` with user+password literal          |
| `pdo-credentials`     | critical | `new PDO('mysql:...', user, pass)`                       |
| `password-const`      | critical | `define('DB_PASSWORD', '...')` and similar               |
| `password-var`        | critical | `$db_pass = '...'`, `$wp_password = '...'`               |
| `private-key-block`   | critical | A `-----BEGIN PRIVATE KEY-----` block in source          |
| `basic-auth-url`      | high     | URLs of the form `https://user:pass@host`                |
| `email-pii`           | medium   | Email addresses (excluding placeholder domains)          |
| `inline-sql-insert`   | medium   | `INSERT INTO ... VALUES(...)` literal in PHP source      |

Each finding records its category, severity, line number, column,
and a *masked* snippet (e.g. `'$db_pass = "█████"'`) so the porter
can find it without the report itself leaking the secret.

The `email-pii` rule excludes a small set of placeholder domains
(`example.com`, `test.com`, `localhost`, etc.) to keep the noise
down on documentation-shaped strings.
""")

    upsert_section(m, 'redaction', 3, '--redact: writing redacted files', """
With `--redact` and `--out-dir DIR`, liftphp writes a parallel
tree of PHP files where every finding has been replaced by a
marker comment:

```php
// before
$db_password = "supers3cret";

// after (in DIR/path/to/file.php)
$db_password = /*<<REDACTED_PASSWORD_VAR>>*/;
```

The redacted tree mirrors the source tree exactly: same paths,
same filenames, same non-PHP files copied through. What changes
is only the matched substrings inside `.php` / `.phtml` files.

This is the artifact you point an assistant at. It can read the
PHP structure (control flow, function names, comments, HTML in
templates) and write Django views that match — without ever
seeing the credentials.

Marker categories are stable strings; you can grep
`<<REDACTED_PASSWORD_VAR>>` if you want to find places that need
configuration in your Django port.
""")

    upsert_section(m, 'strict', 4, '--strict: gating shares', """
`--strict` flips the exit code: any finding causes a nonzero exit.
Useful in three places:

- **Pre-share automation.** A script that prepares an artifact for
  an assistant or a colleague can run liftphp first; if it returns
  2, the share is refused.
- **CI checks.** The same script in CI catches regressions where
  someone commits a credential.
- **Pre-commit hook.** Catches credentials before they leave the
  developer's machine.

`--strict --redact` together is a useful pattern: the redacted
tree is written (so the porter can use it) but the run still
exits 2 to flag that human review is required.
""")

    upsert_section(m, 'limits', 5, 'What liftphp does not catch', """
- **Computed credentials.** `$db_pass = base64_decode($encoded);` —
  the literal isn't visible. liftphp won't see this.
- **Credentials in databases.** liftphp scans only PHP source, not
  the data the PHP reads. Use `dumpschema` for the schema review;
  use `liftphp` for the code review.
- **Custom secret patterns.** API tokens with bespoke prefixes
  (e.g. `sk_live_...`, `xoxb-...`) are not recognised. Add a rule
  to `php_scanner.py` if you have one you want covered; the
  pattern format is straightforward.
- **Comments containing secrets.** `// password is "abc123"` —
  liftphp recognises the structural shapes (assignment, function
  call) but not free-form prose. False negative.

The conservative philosophy: make false positives easy to triage
and false negatives rare. The redaction marker reflects this — if
you see `<<REDACTED_PASSWORD_VAR>>` in your codebase, you can
trust it; if you don't, that doesn't *prove* there's no secret,
just that the structural rules didn't fire.
""")


def seed_liftsite_guide():
    m = upsert_manual(
        'liftsite-guide',
        title='liftsite',
        subtitle='Lift HTML/JS/CSS into a Django app layout',
        format='short',
        author='Velour / Datalift',
        version='1.0',
        abstract=(
            'liftsite walks a legacy site directory, classifies every '
            'file, and routes it to the right place under a Django '
            'app: HTML to templates/, JS/CSS/fonts/images to static/, '
            'PHP to a "deferred" worklist for liftphp/liftwp. Performs '
            'conservative HTML rewrites (relative href/src → '
            '{% static %}, legacy URLs → {% url %}) without ever '
            'breaking files that already contain Django template '
            'markers.'
        ),
        edition='First edition',
        license='CC BY-SA 4.0',
        copyright_year='2026',
        copyright_holder='Velour Project',
    )

    upsert_section(m, 'invocation', 0, 'Invocation', """
```
python manage.py liftsite /path/to/old/site \\
    --app myapp \\
    [--url-map urls.json] \\
    [--asset-map assets.json] \\
    [--worklist worklist.md] \\
    [--out /path/to/django/project] \\
    [--move] [--dry-run]
```

`--move` moves files instead of copying (mutates the source tree).
`--dry-run` writes only the worklist; no files are placed.
""")

    upsert_section(m, 'classification', 1, 'How files are classified', """
Each file in the source tree is bucketed by extension:

| Bucket  | Extensions                                                   | Routed to                       |
|---|---|---|
| `html`  | `.html`, `.htm`, `.tpl`                                      | `templates/<app>/`              |
| `js`    | `.js`, `.mjs`                                                | `static/<app>/js/`              |
| `css`   | `.css`                                                       | `static/<app>/css/`             |
| `asset` | images, fonts, audio/video, pdf                              | `static/<app>/<category>/`      |
| `php`   | `.php`, `.phtml`, `.inc`                                     | inventoried, deferred to liftphp/liftwp |
| `other` | anything else                                                | inventoried, no auto-placement  |

A small set of conventional source directories is collapsed when
routing to avoid double-bucketing: `js/`, `scripts/`,
`javascript/` collapse to JS; `css/`, `styles/`, `stylesheets/`
collapse to CSS; `images/`, `img/`, `assets/`, `fonts/`, `media/`
collapse to assets.
""")

    upsert_section(m, 'rewriting', 2, 'HTML rewriting', """
liftsite performs conservative rewrites on HTML files:

- **Relative asset URLs** (`href`, `src`) → `{% static %}` tags.
- **Legacy URLs** matched by `--url-map` → `{% url %}` tags.
- **`{% load static %}`** is added at the top if any
  `{% static %}` was inserted.

Files that already contain Django template markers (`{% ` or
`{{ `) are skipped by the rewriter — the assumption is that a
human (or a previous lift) has begun converting them, and we
shouldn't disturb in-progress work.

Anything liftsite cannot resolve (URLs not in `--url-map`, JS
fetch endpoints, form actions, PHP-to-Django translations) is
recorded as a structured worklist entry so a human or assistant
can walk through it without re-crawling the site.
""")

    upsert_section(m, 'url-map', 3, 'The optional url-map.json', """
A JSON file mapping legacy URL patterns (or regex strings) to
Django URL names. Example:

```json
{
  "/index.php":         "homepage",
  "/about-us.php":      "about",
  "/contact.html":      "contact",
  "^/blog/(\\\\d+)$":   ["post_detail", "post_id"]
}
```

The list form `["urlname", "argname"]` lets you target Django URLs
that take captured arguments. The first capture group from the
regex becomes the value for `argname`.

Every translated URL turns up in the resulting HTML as a Django
`{% url %}` tag. Unmatched URLs are kept as-is and listed in the
worklist so the porter can decide.
""")

    upsert_section(m, 'asset-map', 4, 'The optional asset-map.json', """
For when the default classification gets the path wrong. Map a
specific source path to a target path inside `static/<app>/`:

```json
{
  "old/legacy_logo.png": "branding/logo.png",
  "vendor/jquery.min.js": "vendor/jquery.min.js"
}
```

This is rarely needed — the bucket-based routing covers most
sites — but useful when you want to enforce a particular layout
in `static/`.
""")

    upsert_section(m, 'worklist', 5, 'The worklist', """
After a run, `liftsite_worklist.md` (default location:
project root) lists:

- **HTML rewrites performed.** Files that had asset URLs or legacy
  URLs translated.
- **Deferred PHP files.** With suggested next-step (`liftphp`
  or `liftwp`).
- **Unresolved URLs.** Each occurrence with its file and line.
- **Skipped files.** With the reason (already-Django, unrecognised
  extension, etc.).

The worklist is the porter's TODO. After running `liftsite`, run
`liftphp` (and possibly `liftwp`) to handle the deferred files,
then iterate on the worklist.
""")


def seed_browsershot_guide():
    m = upsert_manual(
        'browsershot-guide',
        title='browsershot',
        subtitle='Real-browser PNG screenshots',
        format='short',
        author='Velour / Datalift',
        version='1.0',
        abstract=(
            'browsershot takes a real-browser PNG screenshot of any '
            'URL using Playwright + Chromium. The primary use is '
            'visual verification of lifted sites: snap before/after '
            'PNGs of legacy and ported pages, then diff with shotdiff. '
            'Returns full-page or viewport-only renderings, with '
            'configurable wait conditions and viewport size.'
        ),
        edition='First edition',
        license='CC BY-SA 4.0',
    )

    upsert_section(m, 'invocation', 0, 'Invocation', """
```
python manage.py browsershot URL \\
    --out path.png \\
    [--width 1280] [--height 800] \\
    [--viewport-only] \\
    [--wait load|domcontentloaded|networkidle|commit] \\
    [--timeout 15000]
```

Defaults: 1280×800 viewport, full-page capture, `networkidle`
wait condition, 15-second timeout.

Output: a PNG written to `--out`. The command also prints the URL,
the page `<title>`, the rendered size, and the byte count of the
file.
""")

    upsert_section(m, 'wait-conditions', 1, '--wait: when to capture', """
Playwright supports four wait conditions; browsershot exposes all
four with sensible defaults.

- **`networkidle`** (default). Wait until there are no more than 0
  network connections for at least 500ms. Safest for static sites
  — captures after every font, every image, every analytics
  pixel has settled.
- **`domcontentloaded`**. Wait until the HTML is parsed and the
  initial DOM is built. Faster but may miss late-arriving CSS or
  fonts. Useful for SPAs where you want to capture before the JS
  has finished hydrating.
- **`load`**. Wait until the `load` event fires (all subresources).
  Between `domcontentloaded` and `networkidle`.
- **`commit`**. Just wait for navigation to commit. The fastest;
  use only when you know the page is server-rendered HTML with
  no async resources to wait for.

For most lifted-WordPress verification, the default `networkidle`
is correct. For comparing two SPAs you may need to drop to
`domcontentloaded` and add an explicit sleep in your script.
""")

    upsert_section(m, 'viewport', 2, '--viewport-only vs full-page', """
By default, browsershot captures the full page — the entire
scroll height, however long. Pages that are 5000px tall produce
PNGs that are 1280×5000.

`--viewport-only` truncates to just the visible viewport (default
1280×800). Useful when:

- You want a uniform-size diff target (every snapshot is the same
  dimensions, easier to compare).
- The page is very long and you only care about the above-the-fold
  region.
- You're saving bytes for storage or transmission.

Adjust `--width` and `--height` to control the viewport. The
`width` is the browser window width — affects responsive layouts
(media queries fire as if the window were that size).
""")

    upsert_section(m, 'use-with-shotdiff', 3,
                   'The browsershot + shotdiff loop', """
The intended pairing:

```
manage.py browsershot https://legacy.example/post/42 --out before.png
manage.py browsershot http://127.0.0.1:8000/post/42/ --out after.png
manage.py shotdiff before.png after.png --out diff.png
```

`shotdiff` writes an overlay PNG showing where the two differ.
The Datalift `liftwp` flow produces sites that visually approach
their legacy origin but won't match pixel-for-pixel — variables
that didn't translate, fonts that aren't local, dates that have
shifted. The diff overlay shows you exactly where to start
investigating.

For a multi-URL diff workflow you can drive both commands from
a shell loop:

```bash
for path in /post/1/ /post/2/ /category/news/; do
    manage.py browsershot "https://legacy.example$path" \\
        --out "shots/before${path//\\//_}.png"
    manage.py browsershot "http://127.0.0.1:8000$path" \\
        --out "shots/after${path//\\//_}.png"
    manage.py shotdiff "shots/before${path//\\//_}.png" \\
                       "shots/after${path//\\//_}.png" \\
        --out "shots/diff${path//\\//_}.png"
done
```
""")

    upsert_section(m, 'caveats', 4, 'Caveats', """
- **Site-required login.** browsershot uses an unauthenticated
  Chromium context. For pages behind auth, write a small script
  that uses Playwright directly with a logged-in context.
- **Robots / rate-limiting.** Real legacy sites may rate-limit
  rapid sequential captures. Add `sleep` between runs if you're
  snapping many pages.
- **Heavy SPAs.** `networkidle` is conservative but won't wait for
  application-state to settle. If you have a SPA that loads data
  in `useEffect`, you may need a custom Playwright script with an
  explicit `page.wait_for_selector('...')` call.
- **GPU-rendered content.** Headless Chromium has CPU-only
  rendering by default. Most sites look identical; some (heavy
  WebGL canvases) may render differently from a desktop browser.
""")


def seed_shotdiff_guide():
    m = upsert_manual(
        'shotdiff-guide',
        title='shotdiff',
        subtitle='Visual diff of two PNG screenshots',
        format='short',
        author='Velour / Datalift',
        version='1.0',
        abstract=(
            'shotdiff takes two PNG screenshots, computes the per-pixel '
            'difference, and writes an overlay PNG with the second '
            'image desaturated and the differences painted bright red. '
            'Reports diff-pixel percent and max channel delta. Built '
            'for verifying that a lifted Django site visually matches '
            'its legacy origin.'
        ),
        edition='First edition',
        license='CC BY-SA 4.0',
    )

    upsert_section(m, 'invocation', 0, 'Invocation', """
```
python manage.py shotdiff before.png after.png \\
    --out diff.png \\
    [--threshold 16]
```

The output PNG has:

- The `after` image desaturated to grayscale as the base layer.
- Every pixel whose channel-wise delta vs `before` exceeds the
  threshold painted bright red on top.

The command also prints:

- The dimensions of both inputs (and the union, if they differ).
- The number and percentage of pixels above the threshold.
- The maximum per-channel delta encountered (0–255).
""")

    upsert_section(m, 'threshold', 1, '--threshold: tuning sensitivity', """
The threshold is a per-channel delta in the 0–255 range. A pixel
counts as "different" if **any** of its R/G/B channels differs from
the corresponding pixel in the other image by more than the
threshold.

| Threshold | What it catches                                          |
|---|---|
| `4`       | Subpixel font hinting differences. Very noisy.           |
| `16` (default) | Color/layout shifts; ignores anti-alias jitter.     |
| `32`      | Mid-range — content moves and background changes.        |
| `64`      | Only obvious changes (different sections of layout).     |
| `128+`    | Only catastrophic differences (entire color swaps).      |

For lifted-site verification, the default 16 is well-calibrated:
font hinting and shadow rendering noise stays out of the report,
but any actual text difference, missing image, or layout shift
shows up as a clear red region.
""")

    upsert_section(m, 'mismatched-sizes', 2, 'Mismatched image sizes', """
If the before and after PNGs are different sizes, shotdiff pads
both to the larger dimensions (with white) and diffs the union.

This is the right behaviour when the lifted site is missing
content — the gap shows up as a red region in the part of the
overlay that exists only in the original.

If you want to enforce exact size equality, snap with
`--viewport-only` from browsershot using the same `--width` and
`--height` on both runs.
""")

    upsert_section(m, 'reading-output', 3, 'Reading the output overlay', """
The desaturated base shows you context: where on the page the
differences are. The red regions show you what changed.

Common patterns:

- **Single short red strip in the header.** Site title rendering
  difference (often: the original used a custom font; the port
  is using the system fallback).
- **Red region around byline.** Author name or date format
  differs.
- **Blocky red rectangles in the body.** Featured images or
  shortcode-rendered content didn't translate.
- **Red strip down a sidebar.** Widget area didn't render
  (`dynamic_sidebar` is a no-op marker in liftwp output).
- **Diffuse red noise everywhere.** Different font face. Drop the
  threshold and confirm; if so, copy the legacy site's webfont
  files into `static/<app>/fonts/` and update the font-face
  declarations.
- **Red line across the bottom.** Footer text or copyright string
  differs.

A diff that's <1% with no contiguous red regions is essentially a
match — what's left is anti-alias noise.
""")

    upsert_section(m, 'caveats', 4, 'Caveats', """
- **Color-space.** Both inputs are converted to RGB. Alpha is
  flattened against white. Sites that render against a transparent
  or non-white body background will show false differences.
- **Dynamic content.** Pages that include the current time,
  random promotion banners, or per-request session IDs will show
  diffs every run. Consider stubbing dynamic content for
  comparison runs.
- **Anti-aliased text rendering** between Linux and macOS Chromium
  builds is not pixel-identical. If you're comparing snapshots
  taken on different OSes, raise the threshold to 32+.
- **Threshold tuning is per-project.** Once you find a value that
  filters noise but keeps real differences, write it into your
  diff script.
""")


class Command(BaseCommand):
    help = 'Seed Codex manuals for the Datalift toolset.'

    def handle(self, *args, **opts):
        seed_datalift_overview()
        self.stdout.write(self.style.SUCCESS(
            '  Datalift overview     → /codex/datalift/'
        ))
        seed_dumpschema_quickstart()
        self.stdout.write(self.style.SUCCESS(
            '  dumpschema Quickstart → /codex/dumpschema-quickstart/'
        ))
        seed_genmodels_guide()
        self.stdout.write(self.style.SUCCESS(
            '  genmodels Guide       → /codex/genmodels-guide/'
        ))
        seed_ingestdump_guide()
        self.stdout.write(self.style.SUCCESS(
            '  ingestdump Guide      → /codex/ingestdump-guide/'
        ))
        seed_liftphp_guide()
        self.stdout.write(self.style.SUCCESS(
            '  liftphp Guide         → /codex/liftphp-guide/'
        ))
        seed_liftsite_guide()
        self.stdout.write(self.style.SUCCESS(
            '  liftsite Guide        → /codex/liftsite-guide/'
        ))
        seed_liftwp_quickstart()
        self.stdout.write(self.style.SUCCESS(
            '  liftwp Quickstart     → /codex/liftwp-quickstart/'
        ))
        seed_liftwp_short()
        self.stdout.write(self.style.SUCCESS(
            '  liftwp Guide          → /codex/liftwp-guide/'
        ))
        seed_browsershot_guide()
        self.stdout.write(self.style.SUCCESS(
            '  browsershot Guide     → /codex/browsershot-guide/'
        ))
        seed_shotdiff_guide()
        self.stdout.write(self.style.SUCCESS(
            '  shotdiff Guide        → /codex/shotdiff-guide/'
        ))
        self.stdout.write(self.style.SUCCESS(
            '\nDatalift manuals seeded (10 manuals).'
        ))
