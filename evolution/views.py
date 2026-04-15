"""Evolution Engine views.

The engine itself runs in the browser. Server-side we list/create
runs, persist the live best-score back, save Agents, and offer
export endpoints to L-System / Legolith.
"""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.crypto import get_random_string
from django.views.decorators.http import require_POST

from .models import Agent, EvolutionRun


@login_required
def run_list(request):
    from lsystem.models import PlantSpecies

    qs = EvolutionRun.objects.all()
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(slug__icontains=q)
                       | Q(notes__icontains=q))
    total = qs.count()
    grand_total = EvolutionRun.objects.count()
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get('page'))
    species = PlantSpecies.objects.all().order_by('name')[:200]
    seed_agents = Agent.objects.all().order_by('-score')[:50]
    return render(request, 'evolution/list.html', {
        'page': page,
        'runs': page.object_list,
        'total': total,
        'grand_total': grand_total,
        'q': q,
        'species': species,
        'seed_agents': seed_agents,
    })


@login_required
@require_POST
def run_new(request):
    """Create an EvolutionRun. Goal is either a pasted string or a
    PlantSpecies (whose expanded L-system string becomes the target).
    """
    from lsystem.models import PlantSpecies

    name = request.POST.get('name', '').strip()
    if not name:
        name = 'Run-' + get_random_string(6).lower()

    try:
        level = int(request.POST.get('level') or 0)
    except (TypeError, ValueError):
        level = 0
    level = max(0, min(2, level))

    try:
        pop_size = int(request.POST.get('population_size') or 24)
    except (TypeError, ValueError):
        pop_size = 24

    try:
        gens = int(request.POST.get('generations_target') or 200)
    except (TypeError, ValueError):
        gens = 200

    try:
        target = float(request.POST.get('target_score') or 0.95)
    except (TypeError, ValueError):
        target = 0.95

    goal_string = request.POST.get('goal_string', '').strip()
    goal_species = None
    species_id = request.POST.get('goal_species') or ''
    if species_id:
        goal_species = PlantSpecies.objects.filter(pk=species_id).first()
        if goal_species and not goal_string:
            goal_string = _expand_species(goal_species)

    seed_agent = None
    seed_id = request.POST.get('seed_agent') or ''
    if seed_id:
        seed_agent = Agent.objects.filter(pk=seed_id).first()

    run = EvolutionRun.objects.create(
        name=name,
        level=level,
        goal_string=goal_string,
        goal_species=goal_species,
        population_size=pop_size,
        generations_target=gens,
        target_score=target,
        seed_agent=seed_agent,
    )
    messages.success(request, f'Created run "{run.name}".')
    return redirect('evolution:run_detail', slug=run.slug)


def _expand_species(species):
    """Expand a PlantSpecies's L-system to a string for goal-matching."""
    s = species.axiom or ''
    rules = species.rules or {}
    iters = max(0, min(8, int(species.iterations or 0)))
    for _ in range(iters):
        out = []
        for ch in s:
            out.append(rules.get(ch, ch))
        s = ''.join(out)
    return s[:4000]


@login_required
def run_detail(request, slug):
    run = get_object_or_404(EvolutionRun, slug=slug)
    saved_agents = run.saved_agents.all()[:50]
    library = Agent.objects.all()[:50]
    return render(request, 'evolution/run.html', {
        'run': run,
        'run_json': json.dumps({
            'id': run.id,
            'slug': run.slug,
            'name': run.name,
            'level': run.level,
            'goal_string': run.goal_string,
            'population_size': run.population_size,
            'generations_target': run.generations_target,
            'target_score': run.target_score,
            'params': run.params or {},
            'seed_agent': _agent_to_dict(run.seed_agent) if run.seed_agent else None,
        }),
        'saved_agents': saved_agents,
        'library': library,
    })


@login_required
@require_POST
def run_delete(request, slug):
    run = get_object_or_404(EvolutionRun, slug=slug)
    name = run.name
    run.delete()
    messages.info(request, f'Deleted run "{name}".')
    return redirect('evolution:list')


@login_required
@require_POST
def run_update(request, slug):
    """Browser pings here with current generation/best_score so the run
    list shows live progress when reopened later.
    """
    run = get_object_or_404(EvolutionRun, slug=slug)
    try:
        body = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return HttpResponse('invalid json', status=400)
    if 'generation' in body:
        run.generation = int(body['generation'])
    if 'best_score' in body:
        run.best_score = float(body['best_score'])
    if 'status' in body and body['status'] in dict(EvolutionRun.STATUS_CHOICES):
        run.status = body['status']
    run.save()
    return HttpResponse('ok')


def _agent_to_dict(agent):
    return {
        'id': agent.id,
        'slug': agent.slug,
        'name': agent.name,
        'level': agent.level,
        'gene': agent.gene or {},
        'seed_string': agent.seed_string,
        'script': agent.script,
        'score': agent.score,
    }


@login_required
def agent_list(request):
    qs = Agent.objects.all()
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(slug__icontains=q)
                       | Q(notes__icontains=q))
    total = qs.count()
    grand_total = Agent.objects.count()
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'evolution/agents.html', {
        'page': page,
        'agents': page.object_list,
        'total': total,
        'grand_total': grand_total,
        'q': q,
    })


@login_required
def agent_detail(request, slug):
    agent = get_object_or_404(Agent, slug=slug)
    return render(request, 'evolution/agent_detail.html', {
        'agent': agent,
        'gene_json': json.dumps(agent.gene or {}, indent=2),
    })


@login_required
@require_POST
def agent_save(request):
    """Live-save endpoint: the running engine POSTs an Agent snapshot
    here; we persist it to the library. Body is the full agent JSON.
    """
    try:
        body = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': 'invalid json'}, status=400)

    name = (body.get('name') or '').strip()
    if not name:
        name = 'Agent-' + get_random_string(8).lower()
    # de-dup
    base = name
    n = 2
    while Agent.objects.filter(name=name).exists():
        name = f'{base}-{n}'
        n += 1

    run_slug = body.get('run_slug') or body.get('run_id')
    source_run = (EvolutionRun.objects.filter(slug=run_slug).first()
                  if run_slug else None)

    parent_id = body.get('parent_id')
    parent = Agent.objects.filter(pk=parent_id).first() if parent_id else None

    agent = Agent.objects.create(
        name=name,
        level=int(body.get('level') or 0),
        gene=body.get('gene') or {},
        seed_string=body.get('seed_string') or '',
        script=body.get('script') or '',
        score=float(body.get('score') or 0.0),
        parent=parent,
        source_run=source_run,
        notes=body.get('notes') or '',
    )
    return JsonResponse({
        'ok': True,
        'id': agent.id,
        'slug': agent.slug,
        'name': agent.name,
        'url': f'/evolution/agents/{agent.slug}/',
    })


@login_required
@require_POST
def agent_delete(request, slug):
    agent = get_object_or_404(Agent, slug=slug)
    name = agent.name
    agent.delete()
    messages.info(request, f'Deleted agent "{name}".')
    return redirect('evolution:agents')


@login_required
@require_POST
def agent_export_lsystem(request, slug):
    """Export an L0 Agent as a PlantSpecies in the L-System library."""
    from lsystem.models import PlantSpecies

    agent = get_object_or_404(Agent, slug=slug)
    if agent.level != 0:
        messages.error(request, 'Only L0 (worker) agents export to L-System.')
        return redirect('evolution:agent_detail', slug=slug)

    gene = agent.gene or {}
    axiom = gene.get('axiom') or agent.seed_string or 'F'
    rules_raw = gene.get('rules') or {}
    if isinstance(rules_raw, dict):
        rules = [{k: v} for k, v in rules_raw.items()]
    else:
        rules = list(rules_raw)
    iters = int(gene.get('iterations') or 4)

    name = f'evo-{agent.slug}'

    species = PlantSpecies.objects.create(
        name=name,
        axiom=axiom,
        rules=rules,
        iterations=iters,
        description=f'Exported from Evolution Agent "{agent.name}" '
                    f'(score {agent.score:.3f}).',
    )
    messages.success(
        request, f'Exported as PlantSpecies "{species.name}".'
    )
    return redirect('evolution:agent_detail', slug=slug)


@login_required
def agent_json(request, slug):
    """JSON endpoint — engine fetches an Agent to seed a new run."""
    agent = get_object_or_404(Agent, slug=slug)
    return JsonResponse(_agent_to_dict(agent))
