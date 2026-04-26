# Datalift

Port a legacy MySQL/PostgreSQL database to a Django project. Ten
corpora tested end-to-end: Laravel (Babybase), Sakila, employees,
MediaWiki, WordPress, Joomla, PrestaShop, Chinook (SQL-Server port),
Pagila (pg_dump), Dolibarr (409-table ERP), MyBB.

## Four-command pipeline

```
dump.sql ─┬─► genmodels   → models.py + admin.py + table_map.json
         │
         ├─► makemigrations + migrate   (Django standard)
         │
         └─► ingestdump   → rows loaded into SQLite / your DB
```

And a one-shot wrapper that runs the first three in order:
```
dump.sql ─► port   → models + admin + map (review, then migrate, then ingest)
```

## Quickstart

```bash
# 1. Generate models from the dump.
python manage.py genmodels path/to/dump.sql --app myapp

# 2. Review myapp/models.py and myapp/ingest/table_map.json.
#    Rename classes, promote junction tables to M2M, etc.

# 3. Migrate the schema.
python manage.py makemigrations myapp
python manage.py migrate

# 4. Load data.
python manage.py ingestdump path/to/dump.sql --app myapp \
    --map myapp/ingest/table_map.json --truncate
```

## Commands

| Command | Purpose |
|---|---|
| `genmodels` | Parse CREATE TABLE blocks → emit `models.py`, `admin.py`, `table_map.json` |
| `ingestdump` | Parse INSERT blocks → populate the generated models |
| `dumpschema` | Extract just the schema portion of a mysqldump for easier review |
| `liftphp` | Scan a legacy PHP tree for secrets / PII before sharing it |
| `liftsite` | Convert legacy HTML/JS/CSS into a Django `templates/` + `static/` layout |
| `liftwp` | Translate a *classic* WordPress theme (PHP files) into Django templates + views + urls |
| `liftwpblock` | Translate a *block* WordPress theme (`templates/*.html` + `theme.json`) — Twenty Twenty-Two and friends — into Django templates + a `theme.json`-driven `base.html` |
| `liftsmarty` | Translate a Smarty theme directory (`.tpl`) into Django templates |
| `liftwig` | Translate a Twig template directory (`.twig`) into Django templates (Drupal/Symfony/Slim) |
| `liftblade` | Translate a Laravel Blade view directory (`.blade.php`) into Django templates |
| `liftvolt` | Translate a Phalcon Volt template directory (`.volt`) into Django templates |
| `liftlaravel` | **Translate Laravel routes and controllers into Django urls.py + views.py.** First PHP business-logic lifter. |
| `liftmigrations` | Parse Laravel `database/migrations/*.php` (Schema::create blueprints) into Django models — for projects with no SQL dump. |
| `liftsymfony` | Translate a Symfony application — controllers (PHP attributes / docblock annotations) + YAML route files — into Django urls.py + views.py. |
| `liftdoctrine` | Translate Doctrine entity classes (`#[ORM\Entity]`, `#[ORM\Column]`, `#[ORM\ManyToOne]`) into Django models. PHP-type-hint inference covers bare `#[ORM\Column]` attributes. |
| `liftcodeigniter` | Translate a CodeIgniter app (CI3 `application/` or CI4 `app/`/`src/`) — routes (incl. `group()`/`resource()`) + controllers — into Django urls.py + views.py. |
| `liftcakephp` | Translate a CakePHP 4/5 app (`config/routes.php` + `src/Controller/`) — routes (incl. `scope`/`prefix`/`resources`/`fallbacks`) + controllers — into Django urls.py + views.py. |
| `liftyii` | Translate a Yii 2 app (`controllers/` + optional `config/web.php` `urlManager.rules`) — every public `actionFoo()` becomes a Django route at `/<controller-id>/<action-id>/`, with VerbFilter HTTP-method pinning honoured. |
| `liftphpcode` | **The catch-all PHP → Python translator.** Walks any PHP source tree (no framework assumed), translates expressions, control flow, classes, and ~150 stdlib functions. Output is Python-shaped PHP for the porter to refine. |
| `liftall` | End-to-end orchestrator — chains scan, genmodels, migrate, ingest, liftphp, liftsite, theme lifter, liftlaravel, liftmigrations, liftsymfony, liftdoctrine, liftcodeigniter, liftcakephp, liftyii, and liftphpcode in one command |
| `browsershot` | Take a real-browser PNG screenshot of any URL — for visually verifying lifted sites match the original |
| `shotdiff` | Diff two PNG screenshots and emit an overlay highlighting the changes |
| `port` | Run `liftphp` (optional) + `genmodels` + print remaining manual steps |

## `genmodels` — what it infers

Legacy SQL is full of dialect quirks. Datalift recognises:

**Dialect placeholders** (all stripped from table names)
- MediaWiki: `CREATE TABLE /*_*/actor`
- WordPress: `CREATE TABLE $wpdb->users`, `${wpdb}->termmeta`
- Joomla: `CREATE TABLE #__users`
- PrestaShop / osCommerce: `PREFIX_orders`, `DB_PREFIX_customers`
- Generic: `{PREFIX}_tablename`
- Schema-qualified: `public.customer`, `dbo.Orders`, `"public"."my_table"`
- Common-prefix auto-detection: if every table starts with `xxx_`,
  the stem is stripped automatically (handles Dolibarr `llx_`,
  vBulletin `vb_`, legacy WordPress `wp_`)

**Type registry** (see `model_generator.py`'s top-of-file constants)
- Integers: `tinyint` / `smallint` / `mediumint` / `int` / `bigint`
  + Postgres `int2/4/8`, `serial` / `bigserial`, with signed ↔
  unsigned routing
- Floats: `float` / `double` / `real` / `float4/8`
- Decimal: `decimal(M,D)` + Oracle-style `numeric(M,D)`
- Char: `char` / `varchar` + SQL-Server `nchar` / `nvarchar`
  + Oracle `varchar2` + Postgres `bpchar`
- Text: `text` family + Postgres `citext`, SQL-Server `ntext`
- Dates: `date` / `time` / `timestamp` / `datetime` +
  Postgres tz-aware variants + SQL-Server `datetime2` /
  `smalldatetime`
- Binary: `blob` family + Postgres `bytea`, SQL-Server `image`,
  Oracle `raw`
- JSON: `json` / `jsonb`
- UUID: `uuid` / `uniqueidentifier`
- `ENUM('A','B')` → TextChoices class + CharField (case preserved)
- `SET('A','B')` → CharField with help_text noting the legacy
  comma-separated format

**Structural patterns**
- Inline FK: `FOREIGN KEY (x) REFERENCES t (x) ON DELETE CASCADE`
- Separate FK: `ALTER TABLE t ADD CONSTRAINT … FOREIGN KEY (…)
  REFERENCES …` (Chinook, pg_dump)
- Post-hoc PK: `ALTER TABLE … ADD CONSTRAINT … PRIMARY KEY (…)`
  (pg_dump) and `ALTER TABLE … ADD PRIMARY KEY pk_name (…)`
  (Dolibarr MySQL-permissive)
- Inline PK on a single column: `id smallint PRIMARY KEY`
  (Dolibarr)
- Composite PK: emits `UniqueConstraint` on the tuple. If one of
  the composite columns is literally named `id`, it gets
  `primary_key=True` (Django reserves that name for PKs)
- Auto-increment: MySQL `AUTO_INCREMENT` and Postgres
  `DEFAULT nextval(seq)` — both become `BigAutoField(primary_key=True)`
- Non-PK FK target: when a FK references a non-PK column,
  `to_field='col'` is emitted and the target column is promoted
  to `unique=True`
- Duplicate `CREATE TABLE` (WordPress single-site vs multisite):
  last definition wins

**Admin inference** (`admin.py`)
- `list_display`, `search_fields`, `list_filter`, `raw_id_fields`
- `date_hierarchy` only when the column's actual SQL type is
  date-shaped (MyBB stores dates as Unix-epoch ints; those get
  no hierarchy)

## `ingestdump` — what it handles

**Value parsing** (see `dump_parser._parse_value`)
- Quoted strings, numeric literals, NULL, hex (`0xDEADBEEF`)
- SQL-Server Unicode prefix: `N'Rock'`
- Postgres booleans: `true` / `false` → Python `bool`
- SQL functions: `CURRENT_TIMESTAMP()`, `NOW()`, `CURDATE()` →
  tz-aware `datetime.now()`. Unknown functions
  (`DATE_FORMAT(…)`) → None
- Installer placeholders: `__UPPER_SNAKE__` (e.g. Dolibarr's
  `__ENTITY__`) → None
- Version-gated values: `/*!50705 0xABCD */` (Sakila BLOBs)
- `_binary 'xxx'` prefix (MySQL bytea)

**Comment awareness**
- `-- …`, `# …`, `/* … */` skipped everywhere (column bodies,
  between statements, even inside the paren walker). Dolibarr
  ships bash snippets inside `-- for x in …; echo "INSERT INTO …"`
  comments — Datalift ignores them instead of matching them as
  real INSERTs.

**Row-level coercions**
- Postgres `bytea` `'\x…'` hex → actual bytes (BinaryField)
- Legacy date strings (`YYYY/M/D`, `DD-MM-YYYY`, `YYYYMMDD`) →
  ISO format
- Empty string into numeric field → None
- None into a NOT NULL field with a default → kwarg dropped so
  the model default fires

**Deduplication**
- Cross-batch PK dedup: the same `rowid` appearing in multiple
  INSERT statements (Dolibarr multicompany data) is silently
  collapsed on the PK — first wins, drops are reported
- Explicit `dedupe_by` in table_map.json collapses on an
  arbitrary field (Babybase: duplicate email addresses)

**Error resilience**
- `--continue-on-error` drops the top-level atomic wrapper. On
  any batch failure, falls back to per-row `save(force_insert=True)`
  and isolates the offending rows — `✗ {table} row {N}: {msg}`.
- `--max-errors=N` caps the log output (ingest always completes;
  this is just display).
- `--dry-run` parses + resolves without writing.

## `table_map.json` — customising the port

`genmodels` emits a starter file at `<app>/ingest/table_map.json`.
Typical edits:

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

* `drop_columns` — silently discard columns from the INSERT
* `value_maps` — per-column value translation
* `synthesize` — derive a column from another (`username ← email`
  when the legacy schema didn't have a username)
* `dedupe_by` — collapse duplicates on this field
* `rewrite_laravel_passwords` — convert Laravel `$2y$` bcrypt
  prefix to Django's `bcrypt$$2b$` format
* `skip_tables` — bypass entire tables

## `liftwp` — WordPress theme → Django templates

After `genmodels` + `ingestdump` give you the WP data, `liftwp`
translates a WordPress theme directory into Django templates,
views, and url patterns so the public-facing site can render.

```bash
python manage.py liftwp /path/to/wp-content/themes/mytheme \
    --app wp \
    [--out /path/to/django/project] \
    [--worklist liftwp_worklist.md] \
    [--dry-run]
```

What it translates deterministically:

* The classic Loop (`if (have_posts()) : while (have_posts()) : the_post()`)
* `get_header()` / `get_footer()` / `get_sidebar()` / `comments_template()`
  → Django `{% include 'wp/X.html' %}`
* `the_title()` / `the_content()` / `the_excerpt()` / `the_permalink()` /
  `the_date()` / `the_author()` / `the_ID()` / `the_category()` / `the_tags()`
* Comment loop: `have_comments()`, `wp_list_comments()`, `comments_number()`,
  `comment_author()`, `comment_text()`, `comment_date()` (read-only)
* Pagination: `next_posts_link()`, `previous_posts_link()`, `the_posts_pagination()`
* Archive titles: `the_archive_title()`, `single_cat_title()`, `single_tag_title()`
* `bloginfo('name'|'description'|'charset'|'url'|'stylesheet_url')`
* `wp_head()` / `wp_footer()` → empty Django blocks
* `language_attributes()` / `body_class()` / `post_class()`
* `echo home_url()` / `echo site_url()` / `echo get_stylesheet_uri()`
* PHP comments (`//`, `#`, `/* */`)
* Short-echo `<?= expr ?>`
* Standard theme files: `index.php`, `single.php`, `page.php`,
  `archive.php`, `404.php`, `search.php`, plus partials
  (`header.php`, `footer.php`, `sidebar.php`, `comments.php`, etc.)

URL surface generated:

* `/` — paginated post list (`?page=N`)
* `/post/<id>/` — single post (with comments)
* `/page/<id>/` — single page
* `/category/<slug>/` — paginated category archive
* `/tag/<slug>/` — paginated tag archive
* `/<year>/` and `/<year>/<month>/` — date archives
* `/search/?s=<q>` — search by title OR content

Default partial templates are auto-emitted (and only auto-emitted)
when a translated theme references them but didn't ship its own
copy: `comments.html`, `comment.html`, `pagination.html`,
`searchform.html`, `sidebar.html`. Auto-emission is fixed-point —
e.g. the default `sidebar.html` includes `searchform.html`, so
both land. Defaults degrade gracefully — `searchform.html` uses
`{% url ... as %}` so the form falls back to `action="/"` if no
`wp_search` route exists.

What it explicitly does NOT translate (flagged in the worklist
instead):

* Custom post types, shortcodes
* Plugin hooks (`add_action`, `add_filter`)
* Theme options pages, widgets, admin screens
* Comment submission (display only — `comment_form()` returns a
  no-op marker)
* AJAX endpoints, REST API routes
* `functions.php` / `*.functions.php` / non-standard PHP files

Everything in the second list — and any unrecognised PHP fragment
inside a translated template — is preserved as a
`{# WP-LIFT? <original> #}` Django comment AND collected in
`liftwp_worklist.md`, so a human or Claude can walk through them
without re-crawling the source.

Output:

* `templates/<app>/index.html`, `single.html`, `page.html`, etc.
* `<app>/views_wp.py` — view functions that read from the
  datalifted WP models
* `<app>/urls_wp.py` — `path('post/<int:post_id>/', ...)` etc.
* `liftwp_worklist.md` at the project root

Wire the URLs into your project with:

```python
# myproject/urls.py
urlpatterns = [
    ...,
    path('', include('wp.urls_wp')),
]
```

## `browsershot` + `shotdiff` — visual verification of lifted sites

Headless-browser PNG screenshot of any URL, then a Pillow-driven
overlay diff so you can see at a glance where the lifted site
differs from the original:

```bash
python manage.py browsershot https://legacy-site.example/post/42 \
    --out /tmp/before.png
python manage.py browsershot http://127.0.0.1:7778/post/42/ \
    --out /tmp/after.png
python manage.py shotdiff /tmp/before.png /tmp/after.png \
    --out /tmp/diff.png
```

`shotdiff` reports the percentage of pixels above the per-channel
threshold (default 16) and writes an overlay PNG: `after` is shown
desaturated with diff regions painted bright red.

`browsershot` is backed by Playwright + Chromium (already in the
venv); `shotdiff` is backed by Pillow. See `:mod:datalift.browsershot`
for the Python API.

## `liftwpblock` — WordPress *block* theme → Django templates

WordPress 5.9 (2022) introduced full-site editing and block themes
— Twenty Twenty-Two, Twenty Twenty-Three, etc. These don't ship
PHP templates: instead `templates/*.html` and `parts/*.html` carry
serialized block markup (`<!-- wp:query -->`, `<!-- wp:post-title /-->`)
and `theme.json` carries colors, fonts, sizes, spacing tokens.

```bash
python manage.py liftwpblock /path/to/wp-content/themes/twentytwentytwo \
    --app tt2_app \
    [--out /path/to/django/project] \
    [--worklist liftwpblock_worklist.md] \
    [--dry-run]
```

What it translates deterministically:

* `wp:query` → `{% for post in posts %}` (paginated post loop)
* `wp:post-template` → the loop body
* `wp:post-title`, `wp:post-content`, `wp:post-excerpt`, `wp:post-date`,
  `wp:post-featured-image`, `wp:post-author`, `wp:post-comments`,
  `wp:post-terms` — all bind to a Django `post` instance
* `wp:template-part {"slug":"header"}` → `{% include "<app>/parts/header.html" %}`
  (with optional `tagName` honoured: `<header>{% include … %}</header>`)
* `wp:site-logo` / `wp:site-title` / `wp:site-tagline` → `site.logo`,
  `site.name`, `site.tagline` (porter wires the context)
* `wp:query-pagination`, `wp:query-pagination-previous`, `-next`,
  `-numbers` → Django paginator (`posts.has_previous`, `posts.number`,
  `posts.paginator.num_pages`, etc.)
* `wp:separator`, `wp:spacer` (with `height` attr), `wp:image`,
  `wp:paragraph`, `wp:heading` (`level` attr honoured)
* `wp:group`, `wp:columns`, `wp:column`, `wp:cover`, `wp:gallery`
  and the rest of the static-layout long tail — pass through their
  literal HTML, drop the comment markers
* `wp:html` (custom HTML) — raw passthrough
* Nested JSON in block attrs (`{"query":{"perPage":10,"postType":"post"}}`)
  is parsed correctly via balanced-brace scanning

`theme.json` becomes a synthesised `base.html` (`{% extends "<app>/base.html" %}`)
with every palette colour, font family, font size, and `custom.*`
spacing token written as a CSS variable using WordPress's own
`--wp--preset--*` and `--wp--custom--*` naming. The lifted
templates render with the original theme's look out of the box;
the porter is meant to edit `base.html` to taste.

What it explicitly flags as porter work (`{# PORTER: ... #}`):

* `wp:navigation` / `wp:page-list` — wire to your nav source
* `wp:post-comments` / `wp:post-comments-form` — wire to your
  comments app
* `wp:shortcode` — translate to a Django template tag
* Unknown blocks — strip the comment, keep the inner HTML, count
  in the worklist

Output:

* `templates/<app>/base.html` — synthesised once, never overwritten
  on re-runs (so porter edits survive)
* `templates/<app>/<template>.html` for each `templates/*.html`
* `templates/<app>/parts/<part>.html` for each `parts/*.html`
* `<app>/wp_theme.json` — the original `theme.json` for further
  porter wiring (e.g. into a context processor)
* `liftwpblock_worklist.md` — block frequencies, porter markers,
  per-template breakdown

## Coverage proof: 10 default WP themes, 0 unhandled fragments

`liftwp` was iterated against the 10 official WordPress default
themes spanning 13 years (Twenty Twelve through Twenty Twenty-One)
plus the Underscores starter template. Every theme lifts to a
fully-translated set of Django templates with **0 unhandled PHP
fragments** — 232 templates total. The 24-test
`Phase3RealWorldTranslationTests` suite pins each pattern surfaced
during that iteration so it can't regress:

* Brace-style `if (foo) { ... } elseif (bar) { ... } else { ... }`
  (no `:`/`endif;`)
* `} elseif (X) {` keeps the chain in one statement (lookahead in
  the splitter)
* Generalised alt-syntax `if (...) :` / `elseif (...) :` that
  defaults to `{% if False %}` with the original condition preserved
  as a comment
* `while ($x->have_posts()) :` and other alt-while with arbitrary
  conditions
* Ternary: `echo $var ? 'A' : 'B'` (specific) and
  `echo <any-expr> ? 'A' : 'B'` (general — emits comment + truthy)
* `++$i` / `--$i` and `$x .= 'foo'` — silent skip
* `$var = ...` — porter-facing comment
* `echo $var` → `{{ var }}`, `echo "literal"` → `literal`
* `get_template_part('a/b', 'c')` → `{% include 'wp/a/b-c.html' %}`
* `get_sidebar('content-bottom')` → `{% include 'wp/sidebar-content-bottom.html' %}`
* `printf(__('text %s'), expr)` — best-effort substitution
* Nested i18n `esc_html(_nx(...))` — recursive string extraction
* `<?php` at end-of-file with no `?>` close tag (WP convention)
* `template-parts/*.php` translated as partials at
  `templates/<app>/template-parts/*.html`
* `inc/`, `includes/`, `lib/` etc. recognised as PHP-code dirs and
  flagged unhandled
* Theme-internal functions: `parse_theme()` scans `inc/` +
  `functions.php` for `function name()` definitions and treats any
  call to one as a quiet `{# theme function #}` marker rather than
  worklist noise. Falls back to a directory-name prefix heuristic.

## Running the tests

```bash
venv/bin/python manage.py test datalift.tests
```

258 tests, ~30 ms. Every corpus-level bug we've fixed has a
named regression here.

## Known limits

* **Multi-tenant data.** If the legacy schema's logical PK is
  `(tenant, rowid)` and all `__TENANT__` placeholders collapse to
  one value, cross-tenant rows collide on the physical PK. The
  cross-batch dedup drops duplicates; to import a specific
  tenant, filter via `value_maps` or pre-process the dump.
  Dolibarr's accounting plans are the motivating case (45%
  ceiling without filtering).
* **CREATE VIEW / TRIGGER / PROCEDURE / FUNCTION.** Bodies are
  stripped from the INSERT scan (so trigger code's literal
  `INSERT INTO` fragments don't look like data). Views themselves
  aren't translated into Django code — Datalift doesn't handle
  query-level logic.
* **`COPY … FROM stdin` blocks** (pg_dump without `--inserts`).
  Supported only in INSERT form; use `pg_dump --inserts` or the
  `pagila-insert-data.sql` variant. COPY parsing is on the
  roadmap.
* **`schema.rb` / Laravel migration files.** Only raw SQL dumps;
  not ORM migration files.

## Layout

```
datalift/
  dump_parser.py      — iter_create_tables, iter_inserts, _parse_value
  model_generator.py  — parse_create_table, infer_field, generate_models_py
  php_scanner.py      — secret / PII scanner for liftphp
  site_lifter.py      — HTML/JS/CSS → Django layout for liftsite
  engine.py           — runtime port orchestrator
  management/commands/
    genmodels.py      — schema → Django models
    ingestdump.py     — data → Django rows
    dumpschema.py     — mysqldump → schema-only
    liftphp.py        — PHP scanner front-end
    liftsite.py       — legacy web → Django layout
    port.py           — one-shot wrapper
  tests/              — 118 parser / generator / ingest regressions
```
