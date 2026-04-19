import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import Candidate, SearchRun
from .search import execute, import_agent_as_candidate, promote, promote_to_evolution


@login_required
def index(request):
    runs = SearchRun.objects.all()[:50]
    top_candidates = (Candidate.objects
                      .select_related('run', 'promoted_to')
                      .order_by('-score', '-id')[:12])
    return render(request, 'det/index.html', {
        'runs': runs,
        'top_candidates': top_candidates,
    })


@login_required
@require_POST
def create_search(request):
    """Kick off a new SearchRun. Runs synchronously for modest params
    (default ~5-15s). For heavier sweeps the operator should use the
    `det_search` management command instead."""
    try:
        n_colors = int(request.POST.get('n_colors', 4))
        n_candidates = int(request.POST.get('n_candidates', 150))
        n_rules = int(request.POST.get('n_rules_per_candidate', 80))
        wildcard_pct = int(request.POST.get('wildcard_pct', 25))
        horizon = int(request.POST.get('horizon', 40))
        W = int(request.POST.get('screen_width', 20))
        H = int(request.POST.get('screen_height', 20))
    except ValueError:
        return HttpResponseBadRequest('Bad integer parameter.')

    if not (2 <= n_colors <= 4):
        return HttpResponseBadRequest('n_colors must be 2, 3, or 4.')
    if not (20 <= n_candidates <= 600):
        return HttpResponseBadRequest('n_candidates out of range 20-600.')

    label = request.POST.get('label', '').strip()

    run = SearchRun.objects.create(
        label=label, n_colors=n_colors,
        n_candidates=n_candidates,
        n_rules_per_candidate=n_rules,
        wildcard_pct=wildcard_pct,
        screen_width=W, screen_height=H,
        horizon=horizon,
    )
    try:
        execute(run)
    except Exception as exc:
        messages.error(request, f'Search failed: {exc}')
        return redirect('det:search_detail', pk=run.pk)

    n_interesting = run.candidates.filter(est_class='class4').count()
    messages.success(request,
        f'Search finished: {run.candidates.count()} candidates screened, '
        f'{n_interesting} look Class-4-like.')
    return redirect('det:search_detail', pk=run.pk)


@login_required
def search_detail(request, pk):
    run = get_object_or_404(SearchRun, pk=pk)
    # Filter by class if the UI asks for it
    class_filter = request.GET.get('class', '')
    qs = run.candidates.select_related('promoted_to')
    if class_filter:
        qs = qs.filter(est_class=class_filter)
    candidates = qs.order_by('-score', 'id')[:120]
    class_counts = {}
    for est, _label in Candidate.CLASS_CHOICES:
        class_counts[est] = run.candidates.filter(est_class=est).count()
    return render(request, 'det/search_detail.html', {
        'run': run,
        'candidates': candidates,
        'class_counts': class_counts,
        'class_filter': class_filter,
    })


@login_required
def candidate_detail(request, pk):
    cand = get_object_or_404(Candidate.objects.select_related(
        'run', 'promoted_to'), pk=pk)
    # A small preview: re-run the candidate forward from the same seed
    # and stream the frames to the template for a client-side player.
    from automaton.detector import step_exact
    from . import engine
    W = cand.run.screen_width
    H = cand.run.screen_height
    grid_seed = cand.analysis.get('grid_seed', f'preview-{cand.pk}')
    grid = engine.seeded_random_grid(W, H, cand.run.n_colors, grid_seed)
    frames = [grid]
    for _ in range(cand.run.horizon):
        grid = step_exact(grid, W, H, cand.rules_json)
        frames.append(grid)

    palette = ['#0d1117', '#58a6ff', '#f85149', '#2ea043'][:cand.run.n_colors]
    return render(request, 'det/candidate_detail.html', {
        'cand': cand,
        'frames_json': json.dumps(frames),
        'palette_json': json.dumps(palette),
        'rules_pretty': json.dumps(cand.rules_json, indent=2),
    })


@login_required
@require_POST
def promote_candidate(request, pk):
    cand = get_object_or_404(Candidate, pk=pk)
    name = request.POST.get('name', '').strip() or None
    rs = promote(cand, name=name)
    messages.success(request,
        f'Promoted to Automaton ruleset "{rs.name}". '
        f'Run it from /automaton/.')
    return redirect('det:candidate_detail', pk=cand.pk)


@login_required
def candidate_json(request, pk):
    """Raw dump — useful for copying a ruleset between installs."""
    cand = get_object_or_404(Candidate, pk=pk)
    return JsonResponse({
        'run': {
            'n_colors': cand.run.n_colors,
            'screen_width': cand.run.screen_width,
            'screen_height': cand.run.screen_height,
            'horizon': cand.run.horizon,
        },
        'score': cand.score,
        'est_class': cand.est_class,
        'analysis': cand.analysis,
        'rules': cand.rules_json,
    })


@login_required
@require_POST
def promote_candidate_to_evolution(request, pk):
    """Hand a Candidate to the Evolution Engine as an L0 founder with a
    hex-CA gene. Creates an Agent + EvolutionRun wired with
    gene_type='hexca' and a hexca_target matching this Candidate's
    screening substrate, then redirects to the run page."""
    cand = get_object_or_404(Candidate.objects.select_related('run'), pk=pk)
    try:
        pop = max(4, min(48, int(request.POST.get('population_size') or 16)))
        gens = max(10, min(400, int(request.POST.get('generations') or 80)))
        mut = float(request.POST.get('mutation_rate') or 0.15)
    except (TypeError, ValueError):
        return HttpResponseBadRequest('bad numeric parameter')
    mut = max(0.01, min(0.6, mut))
    try:
        run, agent = promote_to_evolution(cand, population_size=pop,
                                          generations=gens, mutation_rate=mut)
    except Exception as exc:
        messages.error(request, f'Promote to Evolution failed: {exc}')
        return redirect('det:candidate_detail', pk=cand.pk)
    messages.success(
        request,
        f'Created Evolution run "{run.name}" seeded with hex-CA agent '
        f'"{agent.name}". Open it, press start, watch the children breed.'
    )
    return redirect('evolution:run_detail', slug=run.slug)


@login_required
@require_POST
def import_agent_from_evolution(request):
    """Pull an evolved Agent back into Det as a Candidate row. The Agent
    must carry a hex-CA gene ({rules: [...], n_colors, ...}) —
    typically one produced by a run Det itself started.

    Creates a fresh SearchRun-style row (size 1) if no `run_id` is
    supplied; otherwise appends the Candidate to an existing run so the
    operator can compare the imported score alongside the original.
    """
    from evolution.models import Agent as EvoAgent

    agent_ref = (request.POST.get('agent') or '').strip()
    if not agent_ref:
        return HttpResponseBadRequest('agent required (pk or slug)')
    agent = None
    if agent_ref.isdigit():
        agent = EvoAgent.objects.filter(pk=int(agent_ref)).first()
    if not agent:
        agent = EvoAgent.objects.filter(slug=agent_ref).first()
    if not agent:
        messages.error(request, f'No Evolution Agent matching "{agent_ref}".')
        return redirect('det:index')

    run_ref = (request.POST.get('run') or '').strip()
    run = None
    if run_ref:
        if run_ref.isdigit():
            run = SearchRun.objects.filter(pk=int(run_ref)).first()

    try:
        with transaction.atomic():
            cand, sr = import_agent_as_candidate(agent, run=run)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('det:index')

    messages.success(
        request,
        f'Imported Agent "{agent.name}" → Candidate #{cand.pk} '
        f'(score {cand.score:.2f}, {cand.get_est_class_display()}).'
    )
    return redirect('det:candidate_detail', pk=cand.pk)
