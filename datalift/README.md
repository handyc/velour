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
| `liftwp` | Translate a WordPress theme into Django templates + views + urls (public-facing only) |
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
* `bloginfo('name'|'description'|'charset'|'url'|'stylesheet_url')`
* `wp_head()` / `wp_footer()` → empty Django blocks
* `language_attributes()` / `body_class()` / `post_class()`
* `echo home_url()` / `echo site_url()` / `echo get_stylesheet_uri()`
* PHP comments (`//`, `#`, `/* */`)
* Short-echo `<?= expr ?>`
* Standard theme files: `index.php`, `single.php`, `page.php`,
  `archive.php`, `404.php`, `search.php`, plus partials
  (`header.php`, `footer.php`, `sidebar.php`, etc.)

What it explicitly does NOT translate (Phase 1 — flagged in the
worklist instead):

* Custom post types, shortcodes
* Plugin hooks (`add_action`, `add_filter`)
* Theme options pages, widgets, admin screens
* Comment submission (display only)
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

## Running the tests

```bash
venv/bin/python manage.py test datalift.tests
```

206 tests, ~30 ms. Every corpus-level bug we've fixed has a
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
