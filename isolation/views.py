from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .models import (IsolationTarget, Pipeline, STATUS_CHOICES, Stage,
                     TARGET_CHOICES, TARGET_ORDER)


def _unique_slug(name, exclude_pk=None):
    base = slugify(name)[:60] or 'pipeline'
    slug = base
    n = 2
    qs = Pipeline.objects.all()
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    while qs.filter(slug=slug).exists():
        slug = f'{base}-{n}'
        n += 1
    return slug


def _pipeline_form(request, pipeline=None):
    p = pipeline or Pipeline()
    p.name = (request.POST.get('name') or '').strip() or p.name
    p.description = (request.POST.get('description') or '').strip()
    p.apps_used = (request.POST.get('apps_used') or '').strip()
    p.notes = (request.POST.get('notes') or '').strip()
    return p


def _stage_form(request, stage):
    stage.app_label = (request.POST.get('app_label') or '').strip()
    stage.entrypoint = (request.POST.get('entrypoint') or '').strip()
    stage.produces = (request.POST.get('produces') or '').strip()
    stage.fields_used = (request.POST.get('fields_used') or '').strip()
    stage.notes = (request.POST.get('notes') or '').strip()
    try:
        stage.order = int(request.POST.get('order') or 0)
    except (TypeError, ValueError):
        stage.order = 0
    return stage


@login_required
def index(request):
    q = (request.GET.get('q') or '').strip()
    pipelines = Pipeline.objects.all()
    if q:
        pipelines = pipelines.filter(name__icontains=q) | \
                    pipelines.filter(description__icontains=q) | \
                    pipelines.filter(apps_used__icontains=q)
    pipelines = pipelines.distinct().prefetch_related('targets', 'stages')

    rows = []
    for p in pipelines:
        targets_by_key = {t.target: t for t in p.targets.all()}
        ordered_targets = [targets_by_key.get(k) for k in TARGET_ORDER]
        rows.append({'pipeline': p, 'targets': ordered_targets})
    return render(request, 'isolation/index.html', {
        'rows': rows,
        'q': q,
        'target_choices': TARGET_CHOICES,
    })


@login_required
def detail(request, slug):
    p = get_object_or_404(Pipeline, slug=slug)
    p.ensure_all_targets()
    stages = p.stages.all()
    targets_by_key = {t.target: t for t in p.targets.all()}
    ordered_targets = [(k, label, targets_by_key[k])
                       for (k, label) in TARGET_CHOICES]
    return render(request, 'isolation/detail.html', {
        'pipeline': p,
        'stages': stages,
        'targets': ordered_targets,
    })


@login_required
def create(request):
    if request.method == 'POST':
        p = _pipeline_form(request)
        if not p.name:
            messages.error(request, 'Name is required.')
            return redirect('isolation:create')
        p.slug = _unique_slug(p.name)
        p.save()
        p.ensure_all_targets()
        messages.success(request, f'Created pipeline "{p.name}".')
        return redirect('isolation:detail', slug=p.slug)
    return render(request, 'isolation/edit.html', {
        'pipeline': None,
    })


@login_required
def edit(request, slug):
    p = get_object_or_404(Pipeline, slug=slug)
    if request.method == 'POST':
        p = _pipeline_form(request, p)
        if not p.name:
            messages.error(request, 'Name is required.')
        else:
            p.slug = _unique_slug(p.name, exclude_pk=p.pk)
            p.save()
            messages.success(request, 'Saved.')
            return redirect('isolation:detail', slug=p.slug)
    return render(request, 'isolation/edit.html', {
        'pipeline': p,
    })


@login_required
@require_POST
def delete(request, slug):
    p = get_object_or_404(Pipeline, slug=slug)
    name = p.name
    p.delete()
    messages.success(request, f'Deleted pipeline "{name}".')
    return redirect('isolation:index')


@login_required
def stage_create(request, slug):
    p = get_object_or_404(Pipeline, slug=slug)
    if request.method == 'POST':
        stage = _stage_form(request, Stage(pipeline=p))
        if not stage.app_label or not stage.entrypoint:
            messages.error(request, 'app_label and entrypoint are required.')
        else:
            if not stage.order:
                stage.order = (p.stages.count() + 1)
            stage.save()
            messages.success(request, 'Stage added.')
            return redirect('isolation:detail', slug=p.slug)
    return render(request, 'isolation/stage_edit.html', {
        'pipeline': p,
        'stage': None,
    })


@login_required
def stage_edit(request, slug, pk):
    p = get_object_or_404(Pipeline, slug=slug)
    stage = get_object_or_404(Stage, pk=pk, pipeline=p)
    if request.method == 'POST':
        _stage_form(request, stage)
        stage.save()
        messages.success(request, 'Stage saved.')
        return redirect('isolation:detail', slug=p.slug)
    return render(request, 'isolation/stage_edit.html', {
        'pipeline': p,
        'stage': stage,
    })


@login_required
@require_POST
def stage_delete(request, slug, pk):
    p = get_object_or_404(Pipeline, slug=slug)
    stage = get_object_or_404(Stage, pk=pk, pipeline=p)
    stage.delete()
    messages.success(request, 'Stage deleted.')
    return redirect('isolation:detail', slug=p.slug)


@login_required
def target_edit(request, slug, pk):
    p = get_object_or_404(Pipeline, slug=slug)
    t = get_object_or_404(IsolationTarget, pk=pk, pipeline=p)
    if request.method == 'POST':
        t.status = (request.POST.get('status') or t.status).strip()
        t.artifact_text = (request.POST.get('artifact_text') or '').strip()
        t.artifact_path = (request.POST.get('artifact_path') or '').strip()
        t.notes = (request.POST.get('notes') or '').strip()
        size_raw = (request.POST.get('size_bytes') or '').strip()
        if size_raw:
            try:
                t.size_bytes = max(0, int(size_raw))
            except (TypeError, ValueError):
                pass
        else:
            t.size_bytes = None
        t.save()
        messages.success(request, f'Saved {t.get_target_display()}.')
        return redirect('isolation:detail', slug=p.slug)
    return render(request, 'isolation/target_edit.html', {
        'pipeline': p,
        'target': t,
        'status_choices': STATUS_CHOICES,
    })
