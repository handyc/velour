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


class Command(BaseCommand):
    help = 'Seed Codex manuals for the Datalift toolset.'

    def handle(self, *args, **opts):
        seed_liftwp_quickstart()
        self.stdout.write(self.style.SUCCESS(
            '  liftwp Quickstart  → /codex/liftwp-quickstart/'
        ))
        seed_liftwp_short()
        self.stdout.write(self.style.SUCCESS(
            '  liftwp Guide       → /codex/liftwp-guide/'
        ))
        self.stdout.write(self.style.SUCCESS('Datalift manuals seeded.'))
