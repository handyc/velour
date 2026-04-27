import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .evolve_dispatch import (
    DispatchError, dispatch_via_conduit, parse_evolve_stdout,
)
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
    # slugify so "3w system weird" → "3w-system-weird"; the URL pattern
    # only matches [-a-zA-Z0-9_]+ and a redirect with raw spaces would
    # NoReverseMatch on the way back.
    slug = slugify(request.POST.get('slug') or '')
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

    # Recent Conduit jobs that targeted this system as their parent,
    # so the user can jump to status / import a completed winner
    # without detouring through /conduit/. Imported lazily so Naiad
    # doesn't hard-fail if Conduit is uninstalled.
    conduit_jobs: list = []
    try:
        from conduit.models import Job
        conduit_jobs = list(
            Job.objects.filter(
                payload__naiad__parent_slug=system.slug,
            ).order_by('-created_at')[:10]
        )
    except Exception:
        conduit_jobs = []

    # Physical layout — pack stage bounding boxes into a 1 m³ cube
    # for the "best smallest filter" scoreboard.
    from .physical import (
        chain_volume_litres, fits_in_cube, pack_chain, CUBE_LITRES,
    )
    chain_stage_types = [s.stage_type for s in stages]
    physical = {
        'volume_l':      chain_volume_litres(chain_stage_types),
        'cube_l':        CUBE_LITRES,
        'fits_in_cube':  fits_in_cube(chain_stage_types),
        'pack':          pack_chain(chain_stage_types),
    }

    return render(request, 'naiad/system_detail.html', {
        'system':       system,
        'stages':       stages,
        'stage_types':  stage_types,
        'test_runs':    test_runs,
        'sources':      sources,
        'targets':      targets,
        'contaminants': CONTAMINANTS,
        'conduit_jobs': conduit_jobs,
        'physical':     physical,
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
def evolve(request, slug):
    """Open the evolve page for a system. Embeds the StageType
    catalog + source + target as JSON so the browser-side Evolution
    Engine (gene_type='naiad') can score candidate chains without a
    round-trip."""
    system = get_object_or_404(
        System.objects.select_related('source', 'target'), slug=slug)
    if not system.target:
        messages.error(
            request,
            'Evolve needs a target profile on the system — '
            'set one before evolving.')
        return redirect('naiad:system_detail', slug=system.slug)

    stage_types = list(StageType.objects.all())
    stage_types_json = [
        {
            'slug': st.slug,
            'name': st.name,
            'kind': st.kind,
            'removal': st.removal or {},
            'converts': st.converts or {},
            'cost_eur': st.cost_eur,
            'energy_watts': st.energy_watts,
            'maintenance_days': st.maintenance_days,
            'flow_lpm': st.flow_lpm,
        }
        for st in stage_types
    ]
    payload = {
        'system_slug':  system.slug,
        'system_name':  system.name,
        'source_slug':  system.source.slug,
        'source_name':  system.source.name,
        'source_values': system.source.values or {},
        'target_slug':  system.target.slug,
        'target_name':  system.target.name,
        'target_values': system.target.values or {},
        'stage_types':  stage_types_json,
        'contaminants': [
            {'key': k, 'label': label, 'unit': unit}
            for (k, label, unit) in CONTAMINANTS
        ],
    }
    # Conduit targets eligible for naiad_evolve dispatch. Imported
    # lazily so naiad doesn't hard-depend on conduit being installed.
    try:
        from conduit.models import JobTarget
        conduit_targets = list(JobTarget.objects.filter(
            enabled=True,
            kind__in=('local', 'vps', 'slurm', 'slurm_manual'),
        ).order_by('kind', '-priority', 'name'))
    except Exception:
        conduit_targets = []

    return render(request, 'naiad/evolve.html', {
        'system':  system,
        'payload_json': json.dumps(payload),
        'conduit_targets': conduit_targets,
    })


@login_required
@require_POST
def evolve_via_conduit(request, slug):
    """Dispatch a server-side GA for this system through Conduit on
    the chosen JobTarget. Redirects to the Conduit job detail page so
    the user can watch status / read stdout."""
    system = get_object_or_404(
        System.objects.select_related('source', 'target'), slug=slug)
    if not system.target:
        messages.error(request, 'Evolve needs a target profile first.')
        return redirect('naiad:system_detail', slug=system.slug)

    def _int(name, default, lo, hi):
        try:
            v = int(request.POST.get(name, default))
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    def _float(name, default, lo, hi):
        try:
            v = float(request.POST.get(name, default))
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    target_slug = (request.POST.get('target_slug') or '').strip()
    if not target_slug:
        messages.error(request, 'Pick a Conduit target.')
        return redirect('naiad:evolve', slug=system.slug)

    seed_raw = (request.POST.get('seed') or '').strip()
    save_raw = (request.POST.get('save') or '').strip()
    opts = {
        'pop':       _int('pop', 60, 4, 400),
        'gens':      _int('gens', 120, 1, 10_000),
        'rate':      _float('rate', 0.25, 0.0, 1.0),
        'crossover': _float('crossover', 0.7, 0.0, 1.0),
        'elite':     _int('elite', 2, 0, 20),
        'every':     _int('every', 10, 1, 1_000),
        'seed':      int(seed_raw) if seed_raw else None,
        'save':      slugify(save_raw) if save_raw else None,
        'requester': request.user if request.user.is_authenticated else None,
    }

    try:
        job = dispatch_via_conduit(system, target_slug, opts)
    except DispatchError as exc:
        messages.error(request, f'dispatch failed: {exc}')
        return redirect('naiad:evolve', slug=system.slug)

    messages.success(
        request,
        f'Dispatched {job.name} to {job.target.name}.')
    return redirect('conduit:job_detail', slug=job.slug)


@login_required
@require_POST
def import_evolve_job(request, job_slug):
    """Parse the 'Best chain found' block out of a completed Conduit
    Job's stdout and materialise a new Naiad System from it. Needed
    when the GA ran on a remote checkout (ALICE) whose SQLite doesn't
    round-trip to this one — the user copies stdout into the
    handoff-complete form, then comes here to turn it into a real
    System. Also works for local runs where the user skipped --save
    and decides later they want to keep the winner."""
    from conduit.models import Job

    job = get_object_or_404(Job, slug=job_slug)
    meta = (job.payload or {}).get('naiad') or {}
    parent_slug = meta.get('parent_slug')
    if not parent_slug:
        messages.error(request,
            f'Job {job.slug} is not a Naiad dispatch — no parent to '
            f'inherit source/target from.')
        return redirect('conduit:job_detail', slug=job.slug)

    try:
        parent = System.objects.select_related(
            'source', 'target').get(slug=parent_slug)
    except System.DoesNotExist:
        messages.error(request,
            f'Parent System {parent_slug!r} has gone missing locally.')
        return redirect('conduit:job_detail', slug=job.slug)

    winner = parse_evolve_stdout(job.stdout or '')
    if not winner or not winner.get('stages'):
        messages.error(request,
            f'Could not find a winning chain in the job stdout. '
            f'Is the run complete and the output pasted in?')
        return redirect('conduit:job_detail', slug=job.slug)

    # Save-as slug: prefer any user-supplied slug on the form, else
    # the one the dispatch stashed in payload, else derive from the
    # parent + Job id.
    form_slug = slugify((request.POST.get('save_as') or '').strip())
    save_as = (form_slug or slugify(meta.get('save_as') or '')
               or f'{parent.slug}-from-job-{job.pk}')
    if System.objects.filter(slug=save_as).exists():
        messages.error(request,
            f'System slug {save_as!r} already exists. Pick another.')
        return redirect('conduit:job_detail', slug=job.slug)

    stage_slugs = winner['stages']
    types_by_slug = {
        st.slug: st for st in StageType.objects.filter(slug__in=stage_slugs)
    }
    missing = [s for s in stage_slugs if s not in types_by_slug]
    if missing:
        messages.error(request,
            f'unknown stage types in winner: {", ".join(sorted(set(missing)))}')
        return redirect('conduit:job_detail', slug=job.slug)

    score_str = f'{winner.get("score", 0):.4f}'
    pass_str  = 'passing' if winner.get('passed') else 'failing'
    with transaction.atomic():
        new_system = System.objects.create(
            slug=save_as,
            name=f'{parent.name} (from job {job.pk})',
            source=parent.source, target=parent.target,
            description=(
                f'Imported from Conduit job {job.slug}, score={score_str} '
                f'({pass_str}). Parent: {parent.slug}.'),
        )
        for i, slug_ in enumerate(stage_slugs):
            Stage.objects.create(
                system=new_system,
                stage_type=types_by_slug[slug_],
                position=i,
            )

    messages.success(request,
        f'Imported as /naiad/{new_system.slug}/ ({len(stage_slugs)} stages, '
        f'{pass_str}).')
    return redirect('naiad:system_detail', slug=new_system.slug)


@login_required
@require_POST
def evolve_save(request, slug):
    """Save an evolved chain as a new Naiad System, cloning the
    parent's source + target. Body is JSON: {name, slug?, stages}."""
    parent = get_object_or_404(
        System.objects.select_related('source', 'target'), slug=slug)
    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
    except ValueError:
        return JsonResponse({'error': 'invalid json'}, status=400)

    name = (body.get('name') or '').strip()
    new_slug = (body.get('slug') or '').strip() or slugify(name)
    stages = body.get('stages') or []
    if not name or not new_slug or not stages:
        return JsonResponse(
            {'error': 'name, slug, and at least one stage are required.'},
            status=400)
    if System.objects.filter(slug=new_slug).exists():
        return JsonResponse(
            {'error': f'slug "{new_slug}" is already taken.'}, status=400)

    types_by_slug = {
        st.slug: st for st in StageType.objects.filter(slug__in=stages)
    }
    missing = [s for s in stages if s not in types_by_slug]
    if missing:
        return JsonResponse(
            {'error': f'unknown stage types: {", ".join(missing)}'},
            status=400)

    with transaction.atomic():
        new_system = System.objects.create(
            slug=new_slug, name=name,
            source=parent.source, target=parent.target,
            description=f'Evolved from {parent.name} ({parent.slug}). '
                        f'Score: {body.get("score", "?")}.',
        )
        for i, s in enumerate(stages):
            Stage.objects.create(
                system=new_system, stage_type=types_by_slug[s], position=i)
    return JsonResponse({
        'ok':  True,
        'url': f'/naiad/{new_system.slug}/',
        'slug': new_system.slug,
        'name': new_system.name,
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
