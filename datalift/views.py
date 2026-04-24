import os
import tempfile

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import LiftJob


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
