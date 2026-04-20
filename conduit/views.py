"""Conduit views — jobs, targets, handoffs.

Minimal Phase-1 UI: enough to create a shell or Slurm job from the
browser, watch status, cancel a pending one, and work a handoff
queue. No fancy async — a quick page refresh shows updated status
once the background thread finishes.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .executors import dispatch
from .models import Job, JobHandoff, JobTarget
from .routing import RoutingError


NOTEBOOKS_DIR = Path(__file__).resolve().parent / 'notebooks'

NOTEBOOKS = [
    {
        'slug':        'loghi-htr',
        'filename':    'loghi_htr.ipynb',
        'title':       'Transkribus clone — Loghi HTR',
        'summary':     'Upload scanned pages, run KNAW-HuC Loghi HTR '
                       'through an ipywidgets GUI, download PAGE-XML. '
                       'Designed to run on ALICE Open OnDemand; falls '
                       'back to mock output when no container runtime '
                       'is available.',
        'venue':       'ALICE Open OnDemand (Jupyter)',
        'engine':      'knaw-huc/loghi via apptainer',
    },
]


@login_required
def index(request):
    recent_jobs = Job.objects.select_related('target').order_by(
        '-created_at')[:20]
    open_handoffs = JobHandoff.objects.select_related('job').filter(
        status__in=['pending', 'submitted']).order_by(
        'status', '-job__created_at')[:10]
    targets = JobTarget.objects.order_by('kind', '-priority', 'name')
    return render(request, 'conduit/index.html', {
        'recent_jobs':    recent_jobs,
        'open_handoffs':  open_handoffs,
        'targets':        targets,
    })


@login_required
def target_list(request):
    targets = JobTarget.objects.order_by('kind', '-priority', 'name')
    return render(request, 'conduit/target_list.html', {'targets': targets})


@login_required
def target_create(request):
    if request.method == 'POST':
        slug = slugify(request.POST.get('slug', '').strip()) or None
        name = request.POST.get('name', '').strip()
        kind = request.POST.get('kind', '').strip()
        if not slug or not name or not kind:
            messages.error(request, 'slug, name, and kind are required')
            return redirect('conduit:target_create')
        config_raw = request.POST.get('config', '').strip() or '{}'
        try:
            config = json.loads(config_raw)
        except json.JSONDecodeError as exc:
            messages.error(request, f'config is not valid JSON: {exc}')
            return redirect('conduit:target_create')
        JobTarget.objects.create(
            slug=slug, name=name, kind=kind,
            host=request.POST.get('host', '').strip(),
            config=config,
            priority=int(request.POST.get('priority') or 0),
            notes=request.POST.get('notes', '').strip(),
        )
        messages.success(request, f'Target {name} created')
        return redirect('conduit:target_list')
    return render(request, 'conduit/target_form.html', {
        'kinds': JobTarget.KIND_CHOICES,
    })


@login_required
def job_list(request):
    jobs = Job.objects.select_related('target', 'requester').order_by(
        '-created_at')[:100]
    return render(request, 'conduit/job_list.html', {'jobs': jobs})


@login_required
def job_create(request):
    if request.method == 'POST':
        slug = slugify(request.POST.get('slug', '').strip()) \
            or f'job-{timezone.now():%Y%m%d-%H%M%S}'
        name = request.POST.get('name', '').strip() or slug
        kind = request.POST.get('kind', 'shell').strip()
        payload_raw = request.POST.get('payload', '').strip() or '{}'
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError as exc:
            messages.error(request, f'payload is not valid JSON: {exc}')
            return redirect('conduit:job_create')

        requested_slug = request.POST.get('requested_target', '').strip()
        requested = None
        if requested_slug:
            requested = JobTarget.objects.filter(slug=requested_slug).first()

        job = Job.objects.create(
            slug=slug, name=name, kind=kind, payload=payload,
            requester=request.user if request.user.is_authenticated else None,
            requested_target=requested,
        )
        try:
            dispatch(job)
        except RoutingError as exc:
            job.status = 'failed'
            job.stderr = f'routing failed: {exc}'
            job.finished_at = timezone.now()
            job.save(update_fields=['status', 'stderr', 'finished_at'])
            messages.error(request, f'routing failed: {exc}')
        return redirect('conduit:job_detail', slug=job.slug)

    return render(request, 'conduit/job_form.html', {
        'kinds':   Job.KIND_CHOICES,
        'targets': JobTarget.objects.filter(enabled=True),
    })


@login_required
def job_detail(request, slug):
    job = get_object_or_404(
        Job.objects.select_related('target', 'requester'), slug=slug)
    handoff = getattr(job, 'handoff', None)
    return render(request, 'conduit/job_detail.html', {
        'job':     job,
        'handoff': handoff,
    })


@login_required
@require_POST
def job_cancel(request, slug):
    job = get_object_or_404(Job, slug=slug)
    if job.status not in ('pending', 'routing', 'dispatched', 'handoff'):
        messages.error(request, f'Cannot cancel a {job.status} job')
        return redirect('conduit:job_detail', slug=job.slug)
    job.status = 'cancelled'
    job.finished_at = timezone.now()
    job.save(update_fields=['status', 'finished_at'])
    if hasattr(job, 'handoff') and job.handoff.status == 'pending':
        job.handoff.status = 'cancelled'
        job.handoff.save(update_fields=['status'])
    messages.success(request, f'Job {job.name} cancelled')
    return redirect('conduit:job_detail', slug=job.slug)


@login_required
def handoff_list(request):
    handoffs = JobHandoff.objects.select_related('job').order_by(
        'status', '-job__created_at')
    return render(request, 'conduit/handoff_list.html', {
        'handoffs': handoffs,
    })


@login_required
def handoff_detail(request, pk):
    handoff = get_object_or_404(
        JobHandoff.objects.select_related('job', 'submitted_by'), pk=pk)
    return render(request, 'conduit/handoff_detail.html', {
        'handoff': handoff,
    })


@login_required
@require_POST
def handoff_submit(request, pk):
    handoff = get_object_or_404(JobHandoff, pk=pk)
    external_id = request.POST.get('external_id', '').strip()
    if not external_id:
        messages.error(request, 'External ID is required')
        return redirect('conduit:handoff_detail', pk=pk)
    handoff.external_id = external_id
    handoff.submitted_by = request.user
    handoff.submitted_at = timezone.now()
    handoff.status = 'submitted'
    handoff.notes = request.POST.get('notes', '').strip()
    handoff.save()
    handoff.job.status = 'running'
    handoff.job.save(update_fields=['status'])
    messages.success(request, f'Handoff submitted as {external_id}')
    return redirect('conduit:handoff_detail', pk=pk)


@login_required
def notebook_list(request):
    items = []
    for nb in NOTEBOOKS:
        path = NOTEBOOKS_DIR / nb['filename']
        items.append({
            **nb,
            'exists': path.exists(),
            'size_kb': (path.stat().st_size // 1024) if path.exists() else 0,
        })
    return render(request, 'conduit/notebook_list.html', {
        'notebooks': items,
    })


@login_required
def notebook_download(request, slug):
    nb = next((n for n in NOTEBOOKS if n['slug'] == slug), None)
    if nb is None:
        raise Http404(f'unknown notebook {slug!r}')
    path = NOTEBOOKS_DIR / nb['filename']
    if not path.exists():
        raise Http404(f'notebook file missing: {nb["filename"]}')
    return FileResponse(
        open(path, 'rb'),
        content_type='application/x-ipynb+json',
        as_attachment=True,
        filename=nb['filename'],
    )


@login_required
@require_POST
def handoff_complete(request, pk):
    handoff = get_object_or_404(JobHandoff, pk=pk)
    outcome = request.POST.get('outcome', 'done')
    if outcome not in ('done', 'failed'):
        return HttpResponseBadRequest('outcome must be done|failed')
    handoff.status = 'acknowledged'
    handoff.notes = (handoff.notes + '\n' +
                     request.POST.get('notes', '').strip()).strip()
    handoff.save(update_fields=['status', 'notes'])
    handoff.job.status = outcome
    handoff.job.stdout = request.POST.get('stdout', '')
    handoff.job.stderr = request.POST.get('stderr', '')
    handoff.job.finished_at = timezone.now()
    handoff.job.save(update_fields=[
        'status', 'stdout', 'stderr', 'finished_at'])
    messages.success(request, f'Handoff acknowledged as {outcome}')

    # If the dispatching app wired a follow-up (e.g. Naiad sets
    # payload['naiad']), stay on the handoff page so the follow-up
    # panel renders there and the user can act on the result without
    # navigating away. Plain shell/script handoffs keep the old
    # redirect to the Job detail.
    if outcome == 'done' and (handoff.job.payload or {}).get('naiad'):
        return redirect('conduit:handoff_detail', pk=handoff.pk)
    return redirect('conduit:job_detail', slug=handoff.job.slug)
