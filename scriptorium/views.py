"""Views for Scriptorium.

Every operation route is POST-only and re-renders with messages so the
user can see what happened. No JSON API in phase 1; everything is form
submits + page reloads.
"""
from __future__ import annotations

import os
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from . import services
from .models import PhilologyProject, SyncRun


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

@login_required
def home(request):
    projects = list(PhilologyProject.objects.all())
    rows = []
    for p in projects:
        last_local = SyncRun.objects.filter(project=p, op='ingest_local').order_by('-started_at').first()
        last_remote = SyncRun.objects.filter(project=p, op='ingest_remote').order_by('-started_at').first()
        last_deploy = SyncRun.objects.filter(project=p, op='deploy').order_by('-started_at').first()
        rows.append({
            'p': p,
            'last_local_ingest': last_local,
            'last_remote_ingest': last_remote,
            'last_deploy': last_deploy,
        })
    return render(request, 'scriptorium/home.html', {
        'projects': rows,
        'env_help': {
            'DANWSI_LOCAL_PATH': os.environ.get('DANWSI_LOCAL_PATH', ''),
            'DANWSI_DB_PATH': os.environ.get('DANWSI_DB_PATH', ''),
        },
    })


# ---------------------------------------------------------------------------
# Project detail / dashboard
# ---------------------------------------------------------------------------

def _project(slug):
    return get_object_or_404(PhilologyProject, slug=slug)


@login_required
def project_detail(request, slug):
    project = _project(slug)
    local = services.local_counts()
    remote = services.remote_counts(project) if project.remote_host else None
    recent = SyncRun.objects.filter(project=project)[:12]
    return render(request, 'scriptorium/project.html', {
        'project': project,
        'local': local,
        'remote': remote,
        'recent_runs': recent,
        'data_drops': services.list_data_drops(project),
    })


# ---------------------------------------------------------------------------
# Data-drop ingest flow
# ---------------------------------------------------------------------------

@login_required
def ingest_page(request, slug):
    project = _project(slug)
    drops = services.list_data_drops(project)
    recent = SyncRun.objects.filter(project=project, op__in=['ingest_local', 'ingest_remote'])[:10]
    return render(request, 'scriptorium/ingest.html', {
        'project': project,
        'data_drops': drops,
        'recent_runs': recent,
    })


@login_required
@require_http_methods(['POST'])
def ingest_run(request, slug):
    project = _project(slug)
    drop_name = request.POST.get('data_drop', '').strip()
    if not drop_name:
        messages.error(request, 'No data drop selected.')
        return HttpResponseRedirect(reverse('scriptorium:ingest', args=[slug]))
    take_backup = request.POST.get('take_backup', 'on') == 'on'

    run = SyncRun.objects.create(
        project=project, op='ingest_local',
        data_dir=drop_name,
        triggered_by=request.user if request.user.is_authenticated else None,
    )
    if take_backup:
        try:
            run.backup_path = str(services.make_local_backup(project, run))
            run.save(update_fields=['backup_path'])
        except Exception as exc:
            run.status = 'failed'
            run.stderr = f'Backup failed: {exc}'
            run.finished_at = timezone.now()
            run.save()
            messages.error(request, f'Backup failed: {exc}')
            return HttpResponseRedirect(reverse('scriptorium:run_detail', args=[run.id]))

    try:
        services.run_local_ingest(project, drop_name, run)
    except Exception as exc:
        run.status = 'failed'
        run.stderr = (run.stderr or '') + f'\n[scriptorium] {exc}'
        run.finished_at = timezone.now()
        run.save()
        messages.error(request, f'Ingest failed: {exc}')
    else:
        if run.status == 'ok':
            t = run.summary.get('totals', {})
            messages.success(
                request,
                f"Ingest OK: {t.get('inscriptions')} inscriptions, "
                f"{t.get('words')} words, {t.get('content')} content entries."
            )
        else:
            messages.error(request, f'Ingest exited with code {run.exit_code}.')
    return HttpResponseRedirect(reverse('scriptorium:run_detail', args=[run.id]))


# ---------------------------------------------------------------------------
# Deploy + remote ingest
# ---------------------------------------------------------------------------

@login_required
def deploy_page(request, slug):
    project = _project(slug)
    recent = SyncRun.objects.filter(
        project=project, op__in=['deploy', 'ingest_remote']
    )[:10]
    return render(request, 'scriptorium/deploy.html', {
        'project': project,
        'recent_runs': recent,
        'data_drops': services.list_data_drops(project),
    })


@login_required
@require_http_methods(['POST'])
def deploy_run(request, slug):
    project = _project(slug)
    run = SyncRun.objects.create(
        project=project, op='deploy',
        triggered_by=request.user if request.user.is_authenticated else None,
    )
    try:
        services.run_deploy(project, run)
    except Exception as exc:
        run.status = 'failed'
        run.stderr = (run.stderr or '') + f'\n[scriptorium] {exc}'
        run.finished_at = timezone.now()
        run.save()
        messages.error(request, f'Deploy failed: {exc}')
    else:
        if run.status == 'ok':
            messages.success(request, 'Deploy OK.')
        else:
            messages.error(request, f'Deploy exited with code {run.exit_code}.')
    return HttpResponseRedirect(reverse('scriptorium:run_detail', args=[run.id]))


@login_required
@require_http_methods(['POST'])
def remote_ingest_run(request, slug):
    project = _project(slug)
    drop_name = request.POST.get('data_drop', '').strip()
    take_backup = request.POST.get('take_backup', 'on') == 'on'
    if not drop_name:
        messages.error(request, 'No data drop selected for remote ingest.')
        return HttpResponseRedirect(reverse('scriptorium:deploy', args=[slug]))

    run = SyncRun.objects.create(
        project=project, op='ingest_remote',
        data_dir=drop_name,
        triggered_by=request.user if request.user.is_authenticated else None,
    )
    if take_backup:
        try:
            run.backup_path = services.make_remote_backup(project, run)
            run.save(update_fields=['backup_path'])
        except Exception as exc:
            run.status = 'failed'
            run.stderr = f'Remote backup failed: {exc}'
            run.finished_at = timezone.now()
            run.save()
            messages.error(request, f'Remote backup failed: {exc}')
            return HttpResponseRedirect(reverse('scriptorium:run_detail', args=[run.id]))

    try:
        services.run_remote_ingest(project, drop_name, run)
    except Exception as exc:
        run.status = 'failed'
        run.stderr = (run.stderr or '') + f'\n[scriptorium] {exc}'
        run.finished_at = timezone.now()
        run.save()
        messages.error(request, f'Remote ingest failed: {exc}')
    else:
        if run.status == 'ok':
            t = run.summary.get('totals', {})
            messages.success(
                request,
                f"Remote ingest OK: {t.get('inscriptions')} inscriptions, "
                f"{t.get('words')} words, {t.get('content')} content entries."
            )
        else:
            messages.error(request, f'Remote ingest exited with code {run.exit_code}.')
    return HttpResponseRedirect(reverse('scriptorium:run_detail', args=[run.id]))


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------

@login_required
def backups_page(request, slug):
    project = _project(slug)
    local = services.list_local_backups(project)
    remote = []
    remote_error = None
    if project.remote_host:
        try:
            remote = services.list_remote_backups(project)
        except Exception as exc:
            remote_error = str(exc)
    return render(request, 'scriptorium/backups.html', {
        'project': project,
        'local_backups': local,
        'remote_backups': remote,
        'remote_error': remote_error,
    })


@login_required
@require_http_methods(['POST'])
def local_backup_now(request, slug):
    project = _project(slug)
    run = SyncRun.objects.create(
        project=project, op='backup_local',
        triggered_by=request.user if request.user.is_authenticated else None,
    )
    try:
        path = services.make_local_backup(project, run)
        run.backup_path = str(path)
        run.status = 'ok'
        run.finished_at = timezone.now()
        run.save()
        messages.success(request, f'Local backup written to {path}')
    except Exception as exc:
        run.status = 'failed'
        run.stderr = str(exc)
        run.finished_at = timezone.now()
        run.save()
        messages.error(request, f'Backup failed: {exc}')
    return HttpResponseRedirect(reverse('scriptorium:backups', args=[slug]))


@login_required
@require_http_methods(['POST'])
def remote_backup_now(request, slug):
    project = _project(slug)
    run = SyncRun.objects.create(
        project=project, op='backup_remote',
        triggered_by=request.user if request.user.is_authenticated else None,
    )
    try:
        path = services.make_remote_backup(project, run)
        run.backup_path = path
        run.status = 'ok'
        run.finished_at = timezone.now()
        run.save()
        messages.success(request, f'Remote backup written to {path}')
    except Exception as exc:
        run.status = 'failed'
        run.stderr = str(exc)
        run.finished_at = timezone.now()
        run.save()
        messages.error(request, f'Remote backup failed: {exc}')
    return HttpResponseRedirect(reverse('scriptorium:backups', args=[slug]))


@login_required
@require_http_methods(['POST'])
def restore_backup(request, slug):
    project = _project(slug)
    name = request.POST.get('backup_name', '').strip()
    location = request.POST.get('location', 'local')
    confirm = request.POST.get('confirm_text', '')
    if confirm != 'RESTORE':
        messages.error(request, 'Restore not confirmed (type RESTORE exactly).')
        return HttpResponseRedirect(reverse('scriptorium:backups', args=[slug]))

    if location == 'local':
        run = SyncRun.objects.create(
            project=project, op='restore_local', data_dir=name,
            triggered_by=request.user if request.user.is_authenticated else None,
        )
        try:
            dst = services.restore_local_backup(project, name)
            run.backup_path = str(dst)
            run.status = 'ok'
            run.finished_at = timezone.now()
            run.save()
            messages.success(request, f'Restored {name} into {dst}.')
        except Exception as exc:
            run.status = 'failed'
            run.stderr = str(exc)
            run.finished_at = timezone.now()
            run.save()
            messages.error(request, f'Restore failed: {exc}')
    else:
        # Remote restore is intentionally not implemented in phase 1 — too risky
        # for a web button without a streaming confirmation. Use the backup
        # file remotely with `cp` from a shell when needed.
        messages.error(request, 'Remote restore is disabled in this version. Restore by hand on the staging host.')
    return HttpResponseRedirect(reverse('scriptorium:backups', args=[slug]))


@login_required
def download_backup(request, slug, name):
    project = _project(slug)
    bdir = Path(project.local_backup_dir).expanduser() if project.local_backup_dir else Path(project.local_path) / 'backups'
    target = (bdir / name).resolve()
    # Path-confinement check: refuse to serve files outside the backup dir.
    try:
        target.relative_to(bdir.resolve())
    except ValueError:
        raise Http404
    if not target.is_file():
        raise Http404
    return FileResponse(open(target, 'rb'), as_attachment=True, filename=name)


# ---------------------------------------------------------------------------
# Run detail
# ---------------------------------------------------------------------------

@login_required
def run_detail(request, run_id):
    run = get_object_or_404(SyncRun, id=run_id)
    return render(request, 'scriptorium/run.html', {'run': run})
