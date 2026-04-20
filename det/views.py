import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import Candidate, SearchRun, Tournament
from .search import execute, import_agent_as_candidate, promote, promote_to_evolution
from .tournament import add_candidate as add_tournament_candidate
from .tournament import execute as execute_tournament


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
        n_colors = int(request.POST.get('n_colors', 3))
        n_candidates = int(request.POST.get('n_candidates', 200))
        n_rules = int(request.POST.get('n_rules_per_candidate', 100))
        wildcard_pct = int(request.POST.get('wildcard_pct', 35))
        horizon = int(request.POST.get('horizon', 60))
        W = int(request.POST.get('screen_width', 18))
        H = int(request.POST.get('screen_height', 16))
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
        xover = float(request.POST.get('crossover_rate') or 0.5)
    except (TypeError, ValueError):
        return HttpResponseBadRequest('bad numeric parameter')
    mut = max(0.01, min(0.6, mut))
    xover = max(0.0, min(0.95, xover))
    try:
        run, agent = promote_to_evolution(cand, population_size=pop,
                                          generations=gens,
                                          mutation_rate=mut,
                                          crossover_rate=xover)
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


@login_required
@require_POST
def import_search_job(request, job_slug):
    """Import results.json from a completed Conduit Job into a new
    SearchRun + Candidate rows. Reads from Job.results_path, which is
    VELOUR_RESULTS_DIR/<job.results_subdir>/ — the same directory the
    remote sbatch rclone'd its output into.

    Idempotent per job_slug in the sense that each click creates a new
    SearchRun; the Candidate rows mirror the remote ones but carry
    fresh primary keys. The remote-side grid seed is preserved in
    `analysis`, so the Automaton preview matches what ran on the
    cluster."""
    from conduit.models import Job

    job = get_object_or_404(Job, slug=job_slug)
    det_meta = (job.payload or {}).get('det') or {}
    if not det_meta:
        messages.error(request, 'Job was not dispatched by Det.')
        return redirect('conduit:job_detail', slug=job.slug)

    path = job.results_path
    if path is None:
        messages.error(request, 'Job has no results_subdir set.')
        return redirect('conduit:job_detail', slug=job.slug)
    results_file = path / (det_meta.get('results_file') or 'results.json')
    if not results_file.exists():
        messages.error(request,
            f'No results.json under {path}. Click "Check results" '
            f'after the remote rclone step has finished.')
        return redirect('conduit:job_detail', slug=job.slug)

    try:
        payload = json.loads(results_file.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        messages.error(request, f'Could not parse {results_file}: {exc}')
        return redirect('conduit:job_detail', slug=job.slug)

    params = payload.get('run') or det_meta.get('params') or {}
    cands = payload.get('candidates') or []
    if not cands:
        messages.error(request,
            f'{results_file} has no candidates — remote run may have '
            f'failed before scoring anything.')
        return redirect('conduit:job_detail', slug=job.slug)

    label = (params.get('label') or '').strip() \
        or f'Conduit {job.slug}'
    try:
        with transaction.atomic():
            run = SearchRun.objects.create(
                label=label,
                n_colors=int(params.get('n_colors') or 3),
                n_candidates=int(params.get('n_candidates')
                                 or len(cands)),
                n_rules_per_candidate=int(
                    params.get('n_rules_per_candidate') or 0),
                wildcard_pct=int(params.get('wildcard_pct') or 0),
                screen_width=int(params.get('screen_width') or 18),
                screen_height=int(params.get('screen_height') or 16),
                horizon=int(params.get('horizon') or 60),
                seed=str(params.get('seed') or ''),
                status='finished',
            )
            Candidate.objects.bulk_create([
                Candidate(
                    run=run,
                    rules_json=c.get('rules') or [],
                    n_rules=int(c.get('n_rules') or len(c.get('rules') or [])),
                    rules_hash=str(c.get('rules_hash') or '')[:16],
                    score=float(c.get('score') or 0.0),
                    est_class=str(c.get('est_class') or 'unknown'),
                    analysis=c.get('analysis') or {},
                )
                for c in cands
            ], batch_size=200)
    except Exception as exc:
        messages.error(request, f'Import failed: {exc}')
        return redirect('conduit:job_detail', slug=job.slug)

    n_class4 = run.candidates.filter(est_class='class4').count()
    messages.success(request,
        f'Imported {run.candidates.count()} candidates from '
        f'{job.slug} ({n_class4} class-4) into SearchRun #{run.pk}.')
    return redirect('det:search_detail', pk=run.pk)


@login_required
def tournament_list(request):
    tourneys = Tournament.objects.all()[:50]
    open_tourneys = Tournament.objects.filter(status='pending')\
        .order_by('-created_at')[:20]
    return render(request, 'det/tournament_list.html', {
        'tournaments':       tourneys,
        'open_tournaments':  open_tourneys,
    })


@login_required
@require_POST
def tournament_create(request):
    try:
        n_colors = int(request.POST.get('n_colors', 3))
        n_seeds = int(request.POST.get('n_seeds', 5))
        W = int(request.POST.get('screen_width', 18))
        H = int(request.POST.get('screen_height', 16))
        horizon = int(request.POST.get('horizon', 60))
    except ValueError:
        return HttpResponseBadRequest('Bad integer parameter.')
    if not (2 <= n_colors <= 4):
        return HttpResponseBadRequest('n_colors must be 2, 3, or 4.')
    if not (2 <= n_seeds <= 20):
        return HttpResponseBadRequest('n_seeds must be 2..20.')

    t = Tournament.objects.create(
        label=(request.POST.get('label') or '').strip(),
        n_colors=n_colors, n_seeds=n_seeds,
        screen_width=W, screen_height=H, horizon=horizon,
    )
    messages.success(request,
        f'Created Tournament #{t.pk}. Add candidates, then run.')
    return redirect('det:tournament_detail', pk=t.pk)


@login_required
def tournament_detail(request, pk):
    t = get_object_or_404(Tournament, pk=pk)
    entries = list(
        t.entries.select_related('candidate', 'candidate__run',
                                 'candidate__promoted_to')
        .order_by('rank', '-aggregate_score', 'id')
    )
    for e in entries:
        e.delta = (round(e.aggregate_score - e.candidate.score, 2)
                   if e.aggregate_score else None)
    seeds_preview = [f'{t.master_seed or "(pending)"}-round-{i}'
                     for i in range(t.n_seeds)]
    addable_runs = (SearchRun.objects.filter(n_colors=t.n_colors,
                                             status='finished')
                    .order_by('-created_at')[:30])
    return render(request, 'det/tournament_detail.html', {
        'tournament':    t,
        'entries':       entries,
        'seeds_preview': seeds_preview,
        'addable_runs':  addable_runs,
    })


@login_required
@require_POST
def tournament_add(request, pk):
    """Add one or more candidates to a tournament.

    Accepts (in priority order):
      - `top_of_run`: SearchRun pk → add that run's top-scoring candidate.
      - `candidate`:  single Candidate pk.
      - `candidates`: comma-separated Candidate pks.
    """
    t = get_object_or_404(Tournament, pk=pk)
    if t.status != 'pending':
        messages.error(request,
            'Tournament has already been run — create a new one to add '
            'more candidates.')
        return redirect('det:tournament_detail', pk=t.pk)

    cand_ids: list[int] = []
    run_ref = (request.POST.get('top_of_run') or '').strip()
    if run_ref.isdigit():
        run = SearchRun.objects.filter(pk=int(run_ref)).first()
        if run:
            top = run.candidates.order_by('-score', 'id').first()
            if top:
                cand_ids.append(top.pk)

    single = (request.POST.get('candidate') or '').strip()
    if single.isdigit():
        cand_ids.append(int(single))

    many = (request.POST.get('candidates') or '').strip()
    if many:
        for chunk in many.replace(',', ' ').split():
            if chunk.isdigit():
                cand_ids.append(int(chunk))

    if not cand_ids:
        messages.error(request, 'No candidate specified.')
        return redirect('det:tournament_detail', pk=t.pk)

    added = 0
    skipped = []
    for cid in cand_ids:
        c = Candidate.objects.filter(pk=cid).first()
        if c is None:
            skipped.append(f'#{cid} (not found)')
            continue
        try:
            add_tournament_candidate(t, c)
            added += 1
        except ValueError as exc:
            skipped.append(f'#{cid} ({exc})')

    if added:
        messages.success(request, f'Added {added} candidate(s).')
    if skipped:
        messages.error(request, 'Skipped: ' + '; '.join(skipped))
    return redirect('det:tournament_detail', pk=t.pk)


@login_required
@require_POST
def tournament_run(request, pk):
    t = get_object_or_404(Tournament, pk=pk)
    if t.status not in ('pending', 'failed'):
        messages.error(request,
            f'Tournament is {t.get_status_display()} — can only run '
            f'pending or failed tournaments.')
        return redirect('det:tournament_detail', pk=t.pk)
    n_entries = t.entries.count()
    if n_entries == 0:
        messages.error(request, 'Add at least one candidate first.')
        return redirect('det:tournament_detail', pk=t.pk)
    try:
        execute_tournament(t)
    except Exception as exc:
        messages.error(request, f'Tournament run failed: {exc}')
        return redirect('det:tournament_detail', pk=t.pk)
    messages.success(request,
        f'Scored {n_entries} entries across {t.n_seeds} seeds '
        f'in {t.duration_seconds:.1f}s.')
    return redirect('det:tournament_detail', pk=t.pk)
