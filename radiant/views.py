from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .evolution import run_evolution, seed_population, step_generation
from .forecast import (forecast_table, purchase_recommendation,
                       evaluate_scenario, render_forecast_svg)
from .models import (HORIZON_YEARS, Candidate, EvoPopulation, Server,
                     WorkloadClass, HostedProject, Scenario, Snapshot)


def _speculative_notes():
    return {
        200:   'Beyond hardware replacement cycles; 50+ generations of '
               'storage media change. Numbers are curve extrapolation only.',
        500:   'Past the operational lifetime of most universities in '
               'continuous existence. Leiden University (founded 1575) is '
               'a rare example — here 951 years old.',
        1000:  'Past recorded history in any computing sense. Project counts '
               'are fictional; the saturation ceiling has dominated.',
        5000:  'Comparable to the entire span of written human history. '
               'Numbers are symbolic; treat as a reminder that predictions '
               'must degrade gracefully.',
        10000: 'Beyond any reasonable claim. Retained only because Seldon '
               'set his equations at this scale. Output is ceremonial.',
    }


def _current_forecast():
    classes = list(WorkloadClass.objects.all())
    rows = forecast_table(classes)
    notes = _speculative_notes()
    for row in rows:
        row['narrative'] = notes.get(row['years'], '')
    return rows, classes


@login_required
def home(request):
    """Prime Radiant itself — fleet + forecast + purchase rec."""
    split_wp = request.GET.get('split', '1') != '0'
    rows, classes = _current_forecast()
    rec = purchase_recommendation(rows, split_wordpress=split_wp)
    servers = Server.objects.all()
    projects = HostedProject.objects.select_related('server', 'workload_class')

    return render(request, 'radiant/home.html', {
        'servers':        servers,
        'classes':        classes,
        'projects':       projects,
        'forecast_rows':  rows,
        'forecast_svg':   render_forecast_svg(rows),
        'recommendation': rec,
        'split_wp':       split_wp,
        'horizons':       HORIZON_YEARS,
        'scenario_count': Scenario.objects.count(),
        'snapshot_count': Snapshot.objects.count(),
    })


@login_required
def scenarios(request):
    """Ranked list of scenarios with headroom evaluation."""
    rows, _ = _current_forecast()
    scenarios = list(Scenario.objects.prefetch_related('candidates'))

    evaluated = []
    for s in scenarios:
        ev = evaluate_scenario(s, rows)
        evaluated.append({'scenario': s, 'eval': ev})

    def _sort_key(entry):
        # Sort by lifetime_years descending; None (never exhausted) comes first.
        life = entry['eval']['lifetime_years']
        return (0 if life is None else 1, -(life or 0))

    evaluated.sort(key=_sort_key)

    return render(request, 'radiant/scenarios.html', {
        'evaluated': evaluated,
        'forecast_rows': rows,
    })


@login_required
def snapshots(request):
    """Chronological list of saved forecast snapshots."""
    return render(request, 'radiant/snapshots.html', {
        'snapshots': Snapshot.objects.all(),
    })


@login_required
@require_POST
def take_snapshot(request):
    """Freeze the current forecast + recommendation as a Snapshot."""
    name = (request.POST.get('name') or '').strip()
    notes = (request.POST.get('notes') or '').strip()
    if not name:
        messages.error(request, 'Snapshot needs a name.')
        return redirect('radiant:snapshots')

    rows, classes = _current_forecast()
    rec_split = purchase_recommendation(rows, split_wordpress=True)
    rec_unified = purchase_recommendation(rows, split_wordpress=False)

    payload = {
        'forecast_rows':        rows,
        'recommendation_split': rec_split,
        'recommendation_unified': rec_unified,
        'classes': [{
            'name': c.name,
            'current_count': c.current_count,
            'typical_ram_mb': c.typical_ram_mb,
            'typical_storage_mb': c.typical_storage_mb,
            'peak_concurrency': c.peak_concurrency,
            'new_per_year': c.new_per_year,
            'saturation_count': c.saturation_count,
        } for c in classes],
        'servers': [{
            'name': s.name,
            'role': s.role,
            'ram_gb': s.ram_gb,
            'storage_gb': s.storage_gb,
            'cpu_cores': s.cpu_cores,
            'storage_used_gb': s.storage_used_gb,
        } for s in Server.objects.all()],
    }
    snap = Snapshot.objects.create(name=name, notes=notes, payload=payload)
    messages.success(request, f'Snapshot "{snap.name}" saved.')
    return redirect('radiant:snapshot_detail', slug=snap.slug)


@login_required
def evolve_index(request):
    """List of evolved populations + form to create a new one."""
    populations = EvoPopulation.objects.all()
    return render(request, 'radiant/evolve_index.html', {
        'populations':     populations,
        'candidate_count': Candidate.objects.count(),
    })


@login_required
@require_POST
def evolve_create(request):
    name = (request.POST.get('name') or '').strip()
    if not name:
        messages.error(request, 'Name is required.')
        return redirect('radiant:evolve_index')
    if EvoPopulation.objects.filter(name=name).exists():
        messages.error(request, f'Population "{name}" already exists.')
        return redirect('radiant:evolve_index')
    if Candidate.objects.count() == 0:
        messages.error(request,
            'No Candidates in library — seed radiant first.')
        return redirect('radiant:evolve_index')

    def _int(key, default, lo, hi):
        try:
            v = int(request.POST.get(key, default))
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    def _float(key, default, lo, hi):
        try:
            v = float(request.POST.get(key, default))
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    pop = EvoPopulation.objects.create(
        name=name,
        population_size=_int('population_size', 32, 4, 256),
        min_boxes=_int('min_boxes', 1, 1, 10),
        max_boxes=_int('max_boxes', 5, 1, 12),
        mutation_rate=_float('mutation_rate', 0.3, 0.0, 1.0),
        elitism=_int('elitism', 2, 0, 10),
        weight_lifetime=_float('weight_lifetime', 1.0, 0.0, 10.0),
        weight_tco=_float('weight_tco', 0.5, 0.0, 10.0),
        weight_isolation=_float('weight_isolation', 2.0, 0.0, 10.0),
        weight_simplicity=_float('weight_simplicity', 0.3, 0.0, 10.0),
        weight_headroom=_float('weight_headroom', 1.0, 0.0, 10.0),
    )
    seed_population(pop)
    messages.success(request,
        f'Created "{pop.name}" — generation 0 seeded with '
        f'{pop.population_size} random bundles.')
    return redirect('radiant:evolve_detail', slug=pop.slug)


@login_required
def evolve_detail(request, slug):
    pop = get_object_or_404(EvoPopulation, slug=slug)
    top_n = 10
    leaders = list(pop.individuals.order_by('-fitness', 'id')[:top_n])
    cmap = {c.pk: c for c in Candidate.objects.all()}

    board = []
    for ind in leaders:
        names = [cmap[cid].name if cid in cmap else f'#{cid}'
                 for cid in ind.genome_ids]
        from collections import Counter
        counts = Counter(names)
        summary = ', '.join(f'{n}×{k}' if n > 1 else k
                            for k, n in counts.items())
        board.append({'ind': ind, 'summary': summary})

    return render(request, 'radiant/evolve_detail.html', {
        'pop':        pop,
        'leaders':    board,
        'pop_count':  pop.individuals.count(),
    })


@login_required
@require_POST
def evolve_step(request, slug):
    pop = get_object_or_404(EvoPopulation, slug=slug)
    result = step_generation(pop)
    if result.get('ok'):
        messages.success(request,
            f'Stepped to generation {result["generation"]} — '
            f'best fitness {result["best_fitness"]:.3f}.')
    else:
        messages.error(request, result.get('error', 'step failed'))
    return redirect('radiant:evolve_detail', slug=pop.slug)


@login_required
@require_POST
def evolve_run(request, slug):
    pop = get_object_or_404(EvoPopulation, slug=slug)
    try:
        gens = int(request.POST.get('gens', 10))
    except (TypeError, ValueError):
        gens = 10
    gens = max(1, min(500, gens))
    result = run_evolution(pop, generations=gens)
    if result.get('ok'):
        messages.success(request,
            f'Ran {gens} generations — now at gen '
            f'{result["final_generation"]}, best fitness '
            f'{result["best_fitness"]:.3f}.')
    else:
        messages.error(request, result.get('error', 'run failed'))
    return redirect('radiant:evolve_detail', slug=pop.slug)


@login_required
@require_POST
def evolve_reseed(request, slug):
    pop = get_object_or_404(EvoPopulation, slug=slug)
    seed_population(pop)
    messages.success(request,
        f'Reseeded "{pop.name}" — back to generation 0.')
    return redirect('radiant:evolve_detail', slug=pop.slug)


@login_required
@require_POST
def evolve_delete(request, slug):
    pop = get_object_or_404(EvoPopulation, slug=slug)
    name = pop.name
    pop.delete()
    messages.success(request, f'Deleted "{name}".')
    return redirect('radiant:evolve_index')


@login_required
def snapshot_detail(request, slug):
    snap = get_object_or_404(Snapshot, slug=slug)
    # Re-attach narrative to stored rows for display consistency.
    notes = _speculative_notes()
    rows = snap.payload.get('forecast_rows', [])
    for row in rows:
        row['narrative'] = notes.get(row.get('years'), '')
    return render(request, 'radiant/snapshot_detail.html', {
        'snapshot': snap,
        'rows': rows,
        'rec_split': snap.payload.get('recommendation_split'),
        'rec_unified': snap.payload.get('recommendation_unified'),
        'payload_classes': snap.payload.get('classes', []),
        'payload_servers': snap.payload.get('servers', []),
    })
