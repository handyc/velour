from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import (
    CONTAMINANTS, CONTAMINANT_LABELS, CONTAMINANT_UNITS,
    Stage, StageType, System, TestRun, WaterProfile,
)
from .simulate import simulate


@login_required
def index(request):
    systems = System.objects.select_related('source', 'target').all()
    stage_types = StageType.objects.all()
    profiles = WaterProfile.objects.all()
    recent_runs = (TestRun.objects
                   .select_related('system', 'source', 'target')
                   .order_by('-created_at')[:10])
    return render(request, 'naiad/index.html', {
        'systems':      systems,
        'stage_types':  stage_types,
        'profiles':     profiles,
        'recent_runs':  recent_runs,
    })


@login_required
@require_POST
def create_system(request):
    name = (request.POST.get('name') or '').strip()
    slug = (request.POST.get('slug') or '').strip()
    source_id = request.POST.get('source')
    if not name or not slug or not source_id:
        return HttpResponseBadRequest('name, slug, source are required.')
    source = get_object_or_404(WaterProfile, pk=source_id, scope='source')
    target = None
    if request.POST.get('target'):
        target = WaterProfile.objects.filter(
            pk=request.POST.get('target'), scope='target').first()
    if System.objects.filter(slug=slug).exists():
        messages.error(request, f'Slug "{slug}" already exists.')
        return redirect('naiad:index')
    system = System.objects.create(
        slug=slug, name=name, source=source, target=target,
        description=(request.POST.get('description') or '').strip(),
    )
    messages.success(request, f'Created system "{system.name}".')
    return redirect('naiad:system_detail', slug=system.slug)


@login_required
def system_detail(request, slug):
    system = get_object_or_404(
        System.objects.select_related('source', 'target'), slug=slug)
    stages = (Stage.objects.filter(system=system)
              .select_related('stage_type').order_by('position'))
    stage_types = StageType.objects.all()
    test_runs = (system.test_runs.select_related('source', 'target')
                 .order_by('-created_at')[:10])
    sources = WaterProfile.objects.filter(scope='source')
    targets = WaterProfile.objects.filter(scope='target')
    return render(request, 'naiad/system_detail.html', {
        'system':       system,
        'stages':       stages,
        'stage_types':  stage_types,
        'test_runs':    test_runs,
        'sources':      sources,
        'targets':      targets,
        'contaminants': CONTAMINANTS,
    })


@login_required
@require_POST
def add_stage(request, slug):
    system = get_object_or_404(System, slug=slug)
    stage_type = get_object_or_404(
        StageType, pk=request.POST.get('stage_type'))
    next_pos = (Stage.objects.filter(system=system)
                .order_by('-position').values_list('position', flat=True)
                .first())
    pos = 0 if next_pos is None else next_pos + 1
    Stage.objects.create(
        system=system, stage_type=stage_type, position=pos,
        label=(request.POST.get('label') or '').strip(),
    )
    return redirect('naiad:system_detail', slug=system.slug)


@login_required
@require_POST
def remove_stage(request, slug, stage_id):
    system = get_object_or_404(System, slug=slug)
    stage = get_object_or_404(Stage, pk=stage_id, system=system)
    removed_pos = stage.position
    stage.delete()
    # Close the gap so positions stay contiguous.
    with transaction.atomic():
        for later in (Stage.objects.filter(system=system,
                                           position__gt=removed_pos)
                      .order_by('position')):
            later.position -= 1
            later.save(update_fields=['position'])
    return redirect('naiad:system_detail', slug=system.slug)


@login_required
@require_POST
def run_test(request, slug):
    system = get_object_or_404(
        System.objects.select_related('source', 'target'), slug=slug)
    source = system.source
    # Let the form override the source for "what if this well went
    # brackish" exploration without editing the system.
    if request.POST.get('source'):
        maybe = WaterProfile.objects.filter(
            pk=request.POST.get('source'), scope='source').first()
        if maybe:
            source = maybe
    target = system.target
    if request.POST.get('target'):
        maybe = WaterProfile.objects.filter(
            pk=request.POST.get('target'), scope='target').first()
        target = maybe
    result = simulate(system, source, target)
    run = TestRun.objects.create(
        system=system, source=source, target=target,
        trace=result['trace'], output=result['output'],
        passed=result['passed'], failures=result['failures'],
    )
    return redirect('naiad:test_detail', pk=run.pk)


@login_required
def test_detail(request, pk):
    run = get_object_or_404(TestRun.objects.select_related(
        'system', 'source', 'target'), pk=pk)
    # Build a per-contaminant funnel — for each contaminant in source,
    # the sequence of remaining values at each stage.
    keys = []
    seen = set()
    for entry in run.trace:
        for k in (entry.get('values') or {}).keys():
            if k not in seen:
                seen.add(k)
                keys.append(k)
    funnel = []
    for k in keys:
        target_val = None
        if run.target and run.target.values:
            target_val = run.target.values.get(k)
        funnel.append({
            'key':     k,
            'label':   CONTAMINANT_LABELS.get(k, k),
            'unit':    CONTAMINANT_UNITS.get(k, ''),
            'target':  target_val,
            'values':  [(e.get('label'), e.get('values', {}).get(k))
                        for e in run.trace],
        })
    return render(request, 'naiad/test_detail.html', {
        'run':     run,
        'funnel':  funnel,
    })


@login_required
def catalog(request):
    stage_types = StageType.objects.all()
    profiles = WaterProfile.objects.all()
    return render(request, 'naiad/catalog.html', {
        'stage_types':  stage_types,
        'profiles':     profiles,
        'contaminants': CONTAMINANTS,
    })
