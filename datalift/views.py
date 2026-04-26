import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import LiftJob


# ── Gallery: past successes for demoing the toolkit ───────────────
#
# Each entry is a hand-curated record of one Datalift demonstration.
# Live entries that the runtime can verify (model counts, schema
# stats from the SQLite db.sqlite3 in the demo project) are
# refreshed on every page render. Static entries (case-study
# headlines, screenshot paths) come from this list directly.

_DEMO_DIR = Path(__file__).resolve().parent / 'demo'

GALLERY_ENTRIES = [
    {
        'slug': 'lime_django_schema',
        'title': 'LimeSurvey schema, served live',
        'subtitle': 'genmodels → models.py → Django ORM → real HTTP page',
        'image': 'lime_django_demo.png',
        'metrics': [
            ('schema tables', '45'),
            ('Django check issues', '0'),
            ('migration ops', '45'),
            ('porter source-edits', '0'),
            ('HTTP response', '200, 1.5 KB, 8 ms'),
        ],
        'body': (
            "The unmodified models.py emitted by genmodels from "
            "LimeSurvey's MariaDB schema, dropped into a 30-line "
            "Django project. manage.py check is silent, "
            "makemigrations generates 45 Create-model ops, migrate "
            "applies them. The view inserts and reads sample User "
            "rows via the lifted ORM and renders an HTML table. "
            "browsershot captures the page through real Chromium."
        ),
        'reproduce': 'datalift/demo/lime_django/',
        'codex': 'limesurvey-case-study',
    },
    {
        'slug': 'lime_django_typeurl',
        'title': 'phpBB type_url class running inside Django',
        'subtitle': "lifted application code, not just lifted schema",
        'image': 'lime_django_typeurl.png',
        'metrics': [
            ('lifted methods called', '3'),
            ('framework deps stubbed', '3'),
            ('lifted lines (unmodified)', '16'),
            ('shim lines added', '~25'),
            ('porter line-edits', '0'),
        ],
        'body': (
            "The class type_url from phpBB/phpbb/profilefields/type/"
            "type_url.php — unmodified liftphpcode output — runs "
            "inside Django with three minimum-viable dependency "
            "stubs (a type_string base class, a get_preg_expression "
            "URL-regex helper, and a self.user.lang i18n dict). "
            "All four methods execute against live input: defaults, "
            "HTML form-field generation via translated PHP "
            "string-concat, and URL validation with both pass and "
            "fail paths."
        ),
        'reproduce': 'datalift/demo/lime_django/lime_app/lifted_typeurl.py',
        'codex': 'liftphpcode-guide',
    },
    {
        'slug': 'limesurvey_endtoend',
        'title': 'LimeSurvey full pipeline',
        'subtitle': 'Yii 1.x + Twig + MariaDB road test',
        'image': None,
        'metrics': [
            ('files translated', '1,134'),
            ('compile-rate', '89.4%'),
            ('schema → Django models', '100% (45 tables)'),
            ('Twig templates', '122 / 122 clean'),
            ('Yii controllers', '25 / 223 actions / 231 routes'),
        ],
        'body': (
            "End-to-end pipeline against the LimeSurvey 6.x source "
            "tree. dumpschema → genmodels → migrate → liftwig → "
            "liftyii → liftphpcode → liftphp security scan. Every "
            "stage clean; one liftwig bug found and fixed in-session "
            "(if(cond) paren form). Two roundtrip layers proven: "
            "Django check / migrate / ORM (100%) and py_compile of "
            "the lifted application code (89.4%)."
        ),
        'reproduce': 'See limesurvey-case-study Codex manual.',
        'codex': 'limesurvey-case-study',
    },
    {
        'slug': 'mediawiki_endtoend',
        'title': 'MediaWiki end-to-end',
        'subtitle': 'Wiki engine on a custom framework — 2,235 PHP files',
        'image': None,
        'metrics': [
            ('files translated', '2,235'),
            ('compile-rate', '86.7%'),
            ('schema → Django models', '100% (64 tables)'),
            ('PHP-8 idioms surfaced + fixed', "??=, attribute access ->class"),
        ],
        'body': (
            "The platform behind Wikipedia. 2,235 files in includes/, "
            "all processed through liftphpcode. Schema dump (MySQL "
            "dialect) lifted by genmodels into 64 Django models, "
            "Django check silent, all 64 mw_* tables created in "
            "SQLite. Two PHP-8 idioms surfaced: ??= null-coalescing "
            "assign and Python-keyword attribute access (->class)."
        ),
        'reproduce': 'See mediawiki-case-study Codex manual.',
        'codex': 'mediawiki-case-study',
    },
    {
        'slug': 'phpbb_endtoend',
        'title': 'phpBB end-to-end',
        'subtitle': 'Custom-MVC forum software (no schema dump shipped)',
        'image': None,
        'metrics': [
            ('files translated', '960'),
            ('compile-rate', '92.0%'),
            ('schema', 'N/A — postgres-only schema'),
            ('Triple-quote-trap fixed', "''..''  →  \"\"..\"\""),
        ],
        'body': (
            "Custom-MVC forum software started in 2000. None of the "
            "framework lifters apply (no Yii / Symfony / Laravel / "
            "Cake / CodeIgniter). Pure catch-all territory. Six new "
            "PHP idioms surfaced and fixed in-session: multi-line "
            "single-quoted strings, Elvis ?:, standalone static $x, "
            "keyword-as-subscript-var, [&$this, 'm'] callable, "
            "keyword-as-param-name."
        ),
        'reproduce': 'See phpbb-case-study Codex manual.',
        'codex': 'phpbb-case-study',
    },
    {
        'slug': 'symfony_demo',
        'title': 'Symfony Demo: 4 controllers → urls.py + views.py',
        'subtitle': 'liftsymfony — attribute routes, class-level prefixes, namespace-disambiguated controllers',
        'image': 'symfony_demo.png',
        'metrics': [
            ('controllers parsed', '4'),
            ('methods translated', '12'),
            ('attribute routes', '19'),
            ('YAML routes', '0 (Demo uses pure attribute routing)'),
            ('compile rate', 'urls.py + views.py both clean'),
        ],
        'body': (
            "The official Symfony Demo (symfony/demo) — the corpus "
            "liftsymfony was iterated against. Class-level "
            "#[Route('/admin/post')] prefixes propagate to every "
            "method route. Two controllers with the same short "
            "name in different namespaces (Admin\\BlogController vs "
            "BlogController) get disambiguated by namespace prefix. "
            "Doctrine relations handled by liftdoctrine alongside."
        ),
        'reproduce': '/tmp/sfdemo_lift/datalift/views_symfony.py',
        'codex': 'liftsymfony-guide',
    },
    {
        'slug': 'cakephp_skeleton',
        'title': 'CakePHP skeleton: PagesController::display',
        'subtitle': 'liftcakephp — RouteBuilder closure, scope+fallbacks, controller actions',
        'image': 'cakephp_skeleton.png',
        'metrics': [
            ('controllers parsed', '1'),
            ('actions translated', '1 (display)'),
            ('routes', '2 (/, /pages/*)'),
            ('fallbacks() flagged', '✓ porter marker'),
            ('compile rate', 'urls.py + views.py both clean'),
        ],
        'body': (
            "CakePHP's official `cakephp/app` skeleton — the "
            "smallest possible CakePHP installation. Tests every "
            "router shape liftcakephp covers: scope('/'), "
            "connect() with both string-target and array-target "
            "forms, the greedy * pattern, fallbacks(). The "
            "$builder->fallbacks() call gets a porter marker (it "
            "expands to /<controller>/<action>/* dispatch which "
            "Datalift doesn't auto-translate)."
        ),
        'reproduce': '/tmp/cake_lift/datalift/views_cakephp.py',
        'codex': 'liftcakephp-guide',
    },
    {
        'slug': 'yii_basic',
        'title': 'Yii 2 basic-app: SiteController, 5 actions',
        'subtitle': 'liftyii — actionFoo() → /<controller-id>/<action-id>/, VerbFilter pinning',
        'image': 'yii_basic.png',
        'metrics': [
            ('controllers parsed', '1'),
            ('actions translated', '5 (Index, Login, Logout, Contact, About)'),
            ('routes', '6 (5 actions + implicit site/ → actionIndex)'),
            ('VerbFilter pin applied', "1 (logout → POST-only)"),
            ('compile rate', 'urls.py + views.py both clean'),
        ],
        'body': (
            "The official yii2-app-basic skeleton. Every public "
            "actionFoo() method becomes a Django route at "
            "/<controller-id>/<action-id>/. Yii also auto-routes "
            "/<controller-id>/ to actionIndex — the lifter "
            "honours that with an extra implicit route. The "
            "behaviors() VerbFilter declaration pins logout to "
            "POST-only via a per-path dispatcher."
        ),
        'reproduce': '/tmp/yii_lift/datalift/views_yii.py',
        'codex': 'liftyii-guide',
    },
    {
        'slug': 'tt2_block_theme',
        'title': 'Twenty Twenty-Two → Django, fully styled',
        'subtitle': "WordPress's flagship FSE block theme, lifted intact",
        'image': 'tt2_block_theme.png',
        'metrics': [
            ('templates lifted', '11 (index, page, single, archive, …)'),
            ('parts lifted', '4 (header × 3 + footer)'),
            ('blocks translated', '153'),
            ('porter markers', '56 (nav menu + comments + page-list)'),
            ('theme.json tokens', '40+ CSS variables (colors, fonts, spacing)'),
            ('HTTP response', '200, 6.1 KB, runs against fake-post stub'),
        ],
        'body': (
            "Twenty Twenty-Two — WordPress's flagship full-site-editing "
            "block theme — fed straight into liftwpblock. Every "
            "<!-- wp:* --> comment block is translated to its Django "
            "equivalent: wp:query becomes {% for post in posts %}, "
            "wp:template-part becomes {% include %}, post-title / "
            "post-date / post-featured-image / post-excerpt all bind "
            "to a Django Post instance. theme.json colors, font "
            "families, font sizes and spacing tokens are written into "
            "a synthesised base.html as --wp--preset--* CSS variables, "
            "so the lifted templates render with the original theme's "
            "look out of the box. Run against a 3-post fake context, "
            "rendered live, screenshotted through Chromium."
        ),
        'reproduce': 'manage.py liftwpblock /path/to/tt2 --app tt2_app',
        'codex': 'liftwpblock-guide',
    },
    {
        'slug': 'tt2_single_page',
        'title': 'TT2 single-page template',
        'subtitle': 'wp:post-content + wp:separator + wp:post-comments',
        'image': 'tt2_page_template.png',
        'metrics': [
            ('source', 'tt2/templates/page.html (26 lines)'),
            ('output', 'tt2_app/page.html (24 lines, extends base)'),
            ('porter markers', '1 (post-comments → wire to comments app)'),
            ('HTTP response', '200, 4.4 KB'),
        ],
        'body': (
            "Same theme, the single-page template (`page.html`). "
            "Renders post.title in <h1> (level=1 from block attrs), "
            "post.featured_image, the wp:separator, post.content "
            "marked |safe so authored HTML survives, and a porter "
            "marker where the WP comments block needs to be wired "
            "to whatever Django comments app the porter prefers."
        ),
        'reproduce': 'datalift/tests/test_wp_block_lifter.py',
        'codex': 'liftwpblock-guide',
    },
    {
        'slug': 'piwigo_endtoend',
        'title': 'Piwigo: the original road test',
        'subtitle': '2002-era PHP photo gallery + Smarty templates',
        'image': None,
        'metrics': [
            ('PHP files in source', '924'),
            ('SQL tables', '34'),
            ('Smarty templates', '36'),
            ('static assets', '~750'),
        ],
        'body': (
            "The first end-to-end Datalift case study. A PHP+MySQL "
            "photo-gallery application started in 2002. Tests "
            "Datalift against an 'arbitrary' codebase — different "
            "domain, different template language, different schema "
            "dialect. Closed by adding the liftsmarty command "
            "in-session."
        ),
        'reproduce': 'See piwigo-case-study Codex manual.',
        'codex': 'piwigo-case-study',
    },
]


def _live_metrics():
    """Refresh metrics that the runtime can verify on each render."""
    metrics = {}
    db = _DEMO_DIR / 'lime_django' / '..' / '..' / 'lime_django' / 'db.sqlite3'
    # Demo SQLite lives at /tmp/lime_django/db.sqlite3 by convention;
    # also accept a copy under datalift/demo/.
    for candidate in (Path('/tmp/lime_django/db.sqlite3'),
                       _DEMO_DIR / 'lime_django' / 'db.sqlite3'):
        if candidate.exists():
            try:
                import sqlite3
                con = sqlite3.connect(candidate)
                tables = con.execute(
                    "SELECT count(*) FROM sqlite_master "
                    "WHERE type='table' AND name LIKE 'lime_%'"
                ).fetchone()[0]
                metrics['sqlite_tables'] = str(tables)
                con.close()
                break
            except Exception:
                pass
    return metrics


def gallery(request):
    """Public gallery of past Datalift successes — for demoing the
    toolkit to people who want to see what it can do."""
    live = _live_metrics()
    return render(request, 'datalift/gallery.html', {
        'entries': GALLERY_ENTRIES,
        'live': live,
        'total_files': '4,329',
        'total_compile': '88.6%',
        'codex_manuals': '27',
    })


def gallery_image(request, slug):
    """Serve a screenshot from the demo dir."""
    for entry in GALLERY_ENTRIES:
        if entry['slug'] == slug and entry.get('image'):
            path = _DEMO_DIR / entry['image']
            if path.exists():
                return FileResponse(open(path, 'rb'),
                                    content_type='image/png')
    raise Http404


@login_required
def job_list(request):
    jobs = LiftJob.objects.all()
    return render(request, 'datalift/list.html', {'jobs': jobs})


@login_required
def job_add(request):
    db_refs = []
    try:
        from databases.models import Database
        db_refs = Database.objects.filter(engine='mysql')
    except Exception:
        pass

    if request.method == 'POST':
        job = LiftJob()
        job.name = request.POST.get('name', 'Unnamed Job')
        job.job_type = request.POST.get('job_type', 'convert')

        db_ref_id = request.POST.get('source_db_ref')
        if db_ref_id:
            # Just store the PK — resolution happens lazily via
            # LiftJob.resolved_source_db. No import of the databases
            # app here means datalift stays usable standalone.
            try:
                job.source_db_ref = int(db_ref_id)
            except (TypeError, ValueError):
                pass
        else:
            job.source_host = request.POST.get('source_host', 'localhost')
            job.source_port = int(request.POST.get('source_port', 3306))
            job.source_user = request.POST.get('source_user', '')
            job.source_password = request.POST.get('source_password', '')
            job.source_database = request.POST.get('source_database', '')

        job.save()
        messages.success(request, f'Created job "{job.name}".')
        return redirect('datalift:job_detail', slug=job.slug)

    return render(request, 'datalift/form.html', {
        'job': None,
        'db_refs': db_refs,
    })


@login_required
def job_detail(request, slug):
    job = get_object_or_404(LiftJob, slug=slug)
    return render(request, 'datalift/detail.html', {'job': job})


@login_required
@require_POST
def job_run(request, slug):
    """Execute the conversion or anonymization job."""
    job = get_object_or_404(LiftJob, slug=slug)

    from . import engine

    job.status = 'running'
    job.error_message = ''
    job.save()

    try:
        conn = engine.connect_mysql(
            job.source_host, job.source_port,
            job.source_user, job.source_password,
            job.source_database,
        )

        tables = engine.introspect_tables(conn)
        job.tables_found = len(tables)

        if job.job_type == 'convert':
            # Generate models.py
            job.output_models_py = engine.generate_models_py(tables)

            # Generate SQLite
            os.makedirs(os.path.join(settings.MEDIA_ROOT, 'datalift'), exist_ok=True)
            sqlite_path = os.path.join(
                settings.MEDIA_ROOT, 'datalift',
                f'{job.slug}.sqlite3',
            )
            total = engine.convert_to_sqlite(conn, tables, sqlite_path)
            job.output_sqlite.name = f'datalift/{job.slug}.sqlite3'
            job.rows_converted = total

        elif job.job_type == 'anonymize':
            # Generate anonymized SQLite
            os.makedirs(os.path.join(settings.MEDIA_ROOT, 'datalift', 'anon'), exist_ok=True)
            anon_path = os.path.join(
                settings.MEDIA_ROOT, 'datalift', 'anon',
                f'{job.slug}-anon.sqlite3',
            )
            total = engine.anonymize_to_sqlite(conn, tables, anon_path)
            job.output_anonymized.name = f'datalift/anon/{job.slug}-anon.sqlite3'
            job.rows_converted = total

        conn.close()
        job.status = 'done'
        job.save()

        # Auto-register the output SQLite as a Database record
        if job.job_type == 'convert' and job.output_sqlite:
            try:
                from databases.models import Database
                abs_path = os.path.join(settings.MEDIA_ROOT, job.output_sqlite.name)
                Database.objects.create(
                    nickname=f'{job.name} (Datalift)',
                    engine='sqlite',
                    file_path=abs_path,
                    notes=f'Auto-created by Datalift job "{job.name}".\n'
                          f'{job.tables_found} tables, {job.rows_converted} rows.\n'
                          f'Source: {job.source_database}@{job.source_host}',
                )
            except Exception:
                pass  # non-critical

        messages.success(request,
            f'Job complete: {job.tables_found} tables, {job.rows_converted} rows.')

    except Exception as e:
        job.status = 'failed'
        job.error_message = str(e)
        job.save()
        messages.error(request, f'Job failed: {e}')

    return redirect('datalift:job_detail', slug=job.slug)


@login_required
@require_POST
def job_delete(request, slug):
    job = get_object_or_404(LiftJob, slug=slug)
    name = job.name
    # Clean up files
    if job.output_sqlite:
        try:
            path = os.path.join(settings.MEDIA_ROOT, job.output_sqlite.name)
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    if job.output_anonymized:
        try:
            path = os.path.join(settings.MEDIA_ROOT, job.output_anonymized.name)
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    job.delete()
    messages.success(request, f'Deleted "{name}".')
    return redirect('datalift:job_list')


@login_required
def download_models(request, slug):
    """Download the generated models.py."""
    job = get_object_or_404(LiftJob, slug=slug)
    if not job.output_models_py:
        messages.error(request, 'No models generated yet.')
        return redirect('datalift:job_detail', slug=slug)
    response = HttpResponse(job.output_models_py, content_type='text/plain')
    response['Content-Disposition'] = f'attachment; filename="{job.slug}_models.py"'
    return response


@login_required
def download_sqlite(request, slug):
    """Download the converted SQLite database."""
    job = get_object_or_404(LiftJob, slug=slug)
    if not job.output_sqlite:
        messages.error(request, 'No SQLite file generated yet.')
        return redirect('datalift:job_detail', slug=slug)
    path = os.path.join(settings.MEDIA_ROOT, job.output_sqlite.name)
    return FileResponse(open(path, 'rb'),
                        as_attachment=True,
                        filename=f'{job.slug}.sqlite3')


@login_required
def download_anonymized(request, slug):
    """Download the anonymized database."""
    job = get_object_or_404(LiftJob, slug=slug)
    if not job.output_anonymized:
        messages.error(request, 'No anonymized file generated yet.')
        return redirect('datalift:job_detail', slug=slug)
    path = os.path.join(settings.MEDIA_ROOT, job.output_anonymized.name)
    return FileResponse(open(path, 'rb'),
                        as_attachment=True,
                        filename=f'{job.slug}-anonymized.sqlite3')


@login_required
def anonymize_upload(request):
    """Upload any SQLite file and get an anonymized version back."""
    if request.method == 'POST' and request.FILES.get('sqlite_file'):
        from . import engine

        uploaded = request.FILES['sqlite_file']
        # Write to temp file
        with tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False) as tmp:
            for chunk in uploaded.chunks():
                tmp.write(chunk)
            tmp_input = tmp.name

        tmp_output = tmp_input + '.anon.sqlite3'
        try:
            total = engine.anonymize_sqlite_file(tmp_input, tmp_output)
            response = FileResponse(
                open(tmp_output, 'rb'),
                as_attachment=True,
                filename=f'anonymized_{uploaded.name}',
            )
            # Clean up on close
            response._tmp_files = [tmp_input, tmp_output]
            return response
        except Exception as e:
            messages.error(request, f'Anonymization failed: {e}')
            for f in [tmp_input, tmp_output]:
                try:
                    os.remove(f)
                except Exception:
                    pass

    return render(request, 'datalift/anonymize_upload.html')


@login_required
def port_upload(request):
    """Upload a mysqldump; get back a zip of models.py + admin.py +
    table_map.json + a README of next steps.

    Everything runs locally in the Django process; nothing leaves the
    machine. The zip is assembled in-memory.
    """
    if request.method == 'POST' and request.FILES.get('dump_file'):
        import io
        import json
        import zipfile
        from .model_generator import generate_all

        uploaded = request.FILES['dump_file']
        app_label = (request.POST.get('app_label') or '').strip() or 'app'
        source_db = (request.POST.get('source_database') or '').strip()

        try:
            text = uploaded.read().decode('utf-8', errors='replace')
        except Exception as e:
            messages.error(request, f'cannot read dump: {e}')
            return render(request, 'datalift/port_upload.html')

        try:
            models_src, admin_src, tmap = generate_all(
                text, app_label=app_label, source_database=source_db,
            )
        except Exception as e:
            messages.error(request, f'port failed while parsing the dump: {e}')
            return render(request, 'datalift/port_upload.html')

        n_tables = len(tmap.get('tables') or {})
        readme = (
            f"# Datalift port — {app_label}\n\n"
            f"Generated from `{uploaded.name}`.\n"
            f"{n_tables} model(s) inferred.\n\n"
            f"## Files in this zip\n\n"
            f"- `{app_label}/models.py` — one class per legacy table with\n"
            f"  inferred field types, FK resolution, Laravel soft-delete\n"
            f"  hints, TextChoices for ENUMs, sensible Meta, `__str__`.\n"
            f"- `{app_label}/admin.py` — one `ModelAdmin` per model with\n"
            f"  list_display / search_fields / list_filter /\n"
            f"  date_hierarchy / raw_id_fields inferred.\n"
            f"- `{app_label}/ingest/table_map.json` — starter map for\n"
            f"  `manage.py ingestdump`: value_maps for ENUMs, drop_columns\n"
            f"  for Laravel cruft, synthesize for users-without-username,\n"
            f"  rewrite_laravel_passwords when a password column is found.\n\n"
            f"## Install into your Django project\n\n"
            f"```\n"
            f"python manage.py startapp {app_label}   # if not yet created\n"
            f"# extract the zip contents over the generated app skeleton:\n"
            f"unzip datalift_port.zip -d .\n"
            f"# then\n"
            f"python manage.py makemigrations {app_label}\n"
            f"python manage.py migrate\n"
            f"python manage.py ingestdump <your-dump.sql> --app {app_label} "
            f"--map {app_label}/ingest/table_map.json --truncate\n"
            f"python manage.py createsuperuser\n"
            f"python manage.py runserver\n"
            f"```\n\n"
            f"## Review checklist\n\n"
            f"- Field types where the inference had to guess (ENUM keys\n"
            f"  especially — the map's value_maps are identity-mapped by\n"
            f"  default; change values when your Django choices use\n"
            f"  different slugs).\n"
            f"- Pluralisation — models.py handles common irregulars but\n"
            f"  check verbose_name_plural on anything unusual.\n"
            f"- Junction tables are flagged for M2M promotion in their\n"
            f"  docstring. Promote by moving the relation to the parent\n"
            f"  as `ManyToManyField(..., through=<JunctionModel>)`.\n"
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f'{app_label}/models.py', models_src)
            zf.writestr(f'{app_label}/admin.py', admin_src)
            zf.writestr(
                f'{app_label}/ingest/table_map.json',
                json.dumps(tmap, indent=2, ensure_ascii=False) + '\n',
            )
            zf.writestr('README.md', readme)

        buf.seek(0)
        resp = HttpResponse(buf.getvalue(), content_type='application/zip')
        resp['Content-Disposition'] = (
            f'attachment; filename="datalift_port_{app_label}.zip"'
        )
        return resp

    return render(request, 'datalift/port_upload.html')
