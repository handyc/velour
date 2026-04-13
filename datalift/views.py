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
            try:
                from databases.models import Database
                job.source_db_ref = Database.objects.get(pk=db_ref_id)
            except Exception:
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
