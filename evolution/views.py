"""Evolution Engine views.

The engine itself runs in the browser. Server-side we list/create
runs, persist the live best-score back, save Agents, and offer
export endpoints to L-System / Legolith.
"""

import json
import random

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
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
    from grammar_engine.models import Language
    species = PlantSpecies.objects.all().order_by('name')[:200]
    seed_agents = Agent.objects.all().order_by('-score')[:50]
    popular_languages = (Language.objects
                         .order_by('-use_count', '-modified')[:40])
    return render(request, 'evolution/list.html', {
        'page': page,
        'runs': page.object_list,
        'total': total,
        'grand_total': grand_total,
        'q': q,
        'species': species,
        'seed_agents': seed_agents,
        'popular_languages': popular_languages,
    })


@login_required
@require_POST
def run_new(request):
    """Create an EvolutionRun. Goal source (priority):
       1. explicit `goal_string` textarea
       2. `goal_language` slug (+ optional `goal_variant` "cat/var")
       3. `goal_species` id
    """
    from lsystem.models import PlantSpecies
    from grammar_engine.models import Language
    from django.db.models import F
    from django.utils import timezone

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
    goal_language = None
    goal_variant = ''

    lang_ref = (request.POST.get('goal_language') or '').strip()
    if lang_ref:
        goal_language = (Language.objects.filter(slug=lang_ref).first()
                         or Language.objects.filter(name__iexact=lang_ref).first())
    if goal_language:
        variant_ref = (request.POST.get('goal_variant') or '').strip()
        cat_name = var_name = ''
        if '/' in variant_ref:
            cat_name, var_name = variant_ref.split('/', 1)
            expanded = goal_language.expand_variant(cat_name, var_name)
        else:
            first = goal_language.first_variant()
            if first:
                cat_name, var_name, axiom, iters, rules = first
                expanded = _expand_lsystem(axiom, rules, iters)
            else:
                expanded = ''
        if expanded and not goal_string:
            goal_string = expanded
        if cat_name and var_name:
            goal_variant = f'{cat_name}/{var_name}'
        Language.objects.filter(pk=goal_language.pk).update(
            use_count=F('use_count') + 1, last_used=timezone.now(),
        )

    species_id = request.POST.get('goal_species') or ''
    if species_id and not goal_string:
        goal_species = PlantSpecies.objects.filter(pk=species_id).first()
        if goal_species:
            goal_string = _expand_species(goal_species)
    elif species_id:
        goal_species = PlantSpecies.objects.filter(pk=species_id).first()

    seed_agent = None
    seed_id = request.POST.get('seed_agent') or ''
    if seed_id:
        seed_agent = Agent.objects.filter(pk=seed_id).first()

    run = EvolutionRun.objects.create(
        name=name,
        level=level,
        goal_string=goal_string,
        goal_species=goal_species,
        goal_language=goal_language,
        goal_variant=goal_variant,
        population_size=pop_size,
        generations_target=gens,
        target_score=target,
        seed_agent=seed_agent,
    )
    messages.success(request, f'Created run "{run.name}".')
    return redirect('evolution:run_detail', slug=run.slug)


def _expand_lsystem(axiom, rules, iterations, max_len=4000):
    s = axiom or ''
    for _ in range(max(0, min(8, int(iterations or 0)))):
        out = []
        total = 0
        for ch in s:
            r = rules.get(ch, ch) if rules else ch
            out.append(r)
            total += len(r)
            if total > max_len:
                break
        s = ''.join(out)[:max_len]
    return s


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
    gene = agent.gene or {}
    is_hexca = (
        isinstance(gene, dict)
        and isinstance(gene.get('rules'), list)
        and bool(gene['rules'])
        and all(isinstance(r, dict) and 'n' in r and 's' in r and 'r' in r
                for r in gene['rules'])
    )
    return render(request, 'evolution/agent_detail.html', {
        'agent': agent,
        'gene_json': json.dumps(gene, indent=2),
        'is_hexca': is_hexca,
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
@require_POST
def agent_export_grammar(request, slug):
    """Export an L0 Agent as a new Grammar Engine Language. The agent's
    {axiom, rules, iterations} becomes one grammar-variant; seed and the
    rest of the acoustic stack are regenerated by the Grammar Engine
    from the new Language's deterministic seed on first open.
    """
    from grammar_engine.models import Language
    import secrets

    agent = get_object_or_404(Agent, slug=slug)
    if agent.level != 0:
        messages.error(request, 'Only L0 (worker) agents export to Grammar Engine.')
        return redirect('evolution:agent_detail', slug=slug)

    gene = agent.gene or {}
    axiom = gene.get('axiom') or agent.seed_string or 'F'
    rules_raw = gene.get('rules') or {}
    rules = {}
    if isinstance(rules_raw, dict):
        rules = {k: v for k, v in rules_raw.items() if isinstance(v, str)}
    elif isinstance(rules_raw, list):
        for entry in rules_raw:
            if isinstance(entry, dict):
                for k, v in entry.items():
                    if isinstance(v, str):
                        rules[k] = v
    iters = int(gene.get('iterations') or 4)

    base = f'evo-{agent.slug}'
    name = base
    n = 2
    while Language.objects.filter(name=name).exists():
        name = f'{base}-{n}'
        n += 1

    spec = {
        'grammars': {
            'evolved': {
                'note': f'Bred by Evolution Engine — agent "{agent.name}"'
                        f' (score {agent.score:.3f}).',
                'axiom': axiom,
                'iterations': iters,
                'variants': {
                    'primary': rules,
                },
            },
        },
    }
    language = Language.objects.create(
        name=name,
        seed=secrets.randbits(31),
        spec=spec,
        notes=f'Exported from Evolution Agent "{agent.name}".',
    )
    messages.success(
        request, f'Exported as Language "{language.name}".'
    )
    return redirect('evolution:agent_detail', slug=slug)


@login_required
def agent_json(request, slug):
    """JSON endpoint — engine fetches an Agent to seed a new run."""
    agent = get_object_or_404(Agent, slug=slug)
    return JsonResponse(_agent_to_dict(agent))


@login_required
@require_POST
def speciate(request):
    """Run N rounds of random-goal evolution, each producing a new Language.
    Thin wrapper around the same helpers the `speciate` management command
    uses. Runs server-side in-request — keep rounds × generations × pop
    modest or it'll time the request out.
    """
    from evolution.management.commands.speciate import (
        run_ga, export_as_language, expand_lsystem,
    )
    from grammar_engine.models import Language

    try:
        rounds = max(1, min(10, int(request.POST.get('rounds') or 1)))
        gens   = max(10, min(400, int(request.POST.get('generations') or 80)))
        pop    = max(8, min(64, int(request.POST.get('population') or 24)))
    except (TypeError, ValueError):
        messages.error(request, 'Invalid speciate params.')
        return redirect('evolution:list')

    candidates = [L for L in Language.objects.all()
                  if L.first_variant() is not None]
    if not candidates:
        messages.error(
            request, 'No Grammar Engine Languages with variants to speciate from.'
        )
        return redirect('evolution:list')

    created = []
    for _ in range(rounds):
        src = random.choice(candidates)
        variants_list = list(src.variants())
        cat_name, var_name, axiom, iters, rules = random.choice(variants_list)
        goal = expand_lsystem(axiom, rules, iters)
        best = run_ga(goal, generations=gens, population=pop,
                      mutation_rate=0.25)
        with transaction.atomic():
            lang = export_as_language(
                best['gene'], best['score'], src,
                f'{cat_name}/{var_name}',
                goal[:160],
            )
        created.append((lang, best['score']))

    if len(created) == 1:
        lang, sc = created[0]
        messages.success(
            request,
            f'Speciated 1 Language: "{lang.name}" (score {sc:.3f}).'
        )
    else:
        avg = sum(sc for _, sc in created) / max(1, len(created))
        names = ', '.join(lang.name for lang, _ in created[:5])
        more = '' if len(created) <= 5 else f', +{len(created) - 5} more'
        messages.success(
            request,
            f'Speciated {len(created)} Languages (avg score {avg:.3f}): '
            f'{names}{more}.'
        )
    return redirect('evolution:list')


@login_required
@require_POST
def populate_languages(request):
    """Fill in particles / subwords / words for Languages that lack them.

    Targets speciated Languages (which only carry an `evolved` grammar
    variant) and any others whose spec has no `particles`. Existing
    grammars are preserved — only the empty tiers get populated.
    """
    from grammar_engine.models import Language
    from grammar_engine.seed_gen import generate_spec

    only_speciated = request.POST.get('scope', 'speciated') == 'speciated'
    try:
        word_count = max(100, min(20000,
                                  int(request.POST.get('word_count') or 2000)))
    except (TypeError, ValueError):
        word_count = 2000

    qs = Language.objects.all()
    if only_speciated:
        qs = qs.filter(slug__startswith='evo-')

    populated = 0
    skipped = 0
    for lang in qs.iterator():
        spec = lang.spec or {}
        if spec.get('particles'):
            skipped += 1
            continue
        existing_grammars = spec.get('grammars') or {}
        new_spec = generate_spec(
            seed=lang.seed,
            limits={'WORD_COUNT': word_count},
            preserve_grammars=existing_grammars,
        )
        lang.spec = new_spec
        lang.save(update_fields=['spec', 'modified'])
        populated += 1

    scope_label = 'speciated' if only_speciated else 'all'
    messages.success(
        request,
        f'Populated {populated} {scope_label} Language(s) '
        f'({skipped} already had particles).'
    )
    return redirect('evolution:list')


@login_required
@require_POST
def language_tournament(request):
    """A language-competition game.

    Build a random goal string. Enter N competitor Languages. Each
    runs a short L-system GA seeded from its own `seed` XOR the goal
    — so the competitor's identity determines its trajectory. Lowest
    K scorers are deleted from the Grammar Engine. Survivors absorb
    the best evolved grammar variant they produced.
    """
    import hashlib
    from evolution.management.commands.speciate import (
        run_ga, random_gene, expand_lsystem,
    )
    from grammar_engine.models import Language

    try:
        competitors_n = max(2, min(20, int(request.POST.get('competitors') or 6)))
        eliminate_n   = max(1, min(10, int(request.POST.get('eliminate') or 2)))
        generations   = max(10, min(300, int(request.POST.get('generations') or 50)))
        population    = max(8, min(48, int(request.POST.get('population') or 16)))
        floor         = max(2, min(50, int(request.POST.get('floor') or 4)))
    except (TypeError, ValueError):
        messages.error(request, 'Invalid tournament params.')
        return redirect('evolution:list')

    if eliminate_n >= competitors_n:
        eliminate_n = competitors_n - 1

    entrants = [L for L in Language.objects.all() if L.first_variant() is not None]
    if len(entrants) < 2:
        messages.error(
            request, 'Need at least 2 Languages with variants for a tournament.'
        )
        return redirect('evolution:list')
    if len(entrants) <= floor:
        messages.error(
            request,
            f'Only {len(entrants)} eligible Language(s); at or below floor '
            f'({floor}). No one would survive — aborting.'
        )
        return redirect('evolution:list')

    random.shuffle(entrants)
    competitors = entrants[:competitors_n]

    # Generate a neutral random goal from a fresh random gene.
    goal_rng_seed = random.randint(0, 2**31 - 1)
    random.seed(goal_rng_seed)
    goal_gene = random_gene()
    goal_str = expand_lsystem(goal_gene['axiom'], goal_gene.get('rules') or {},
                              goal_gene.get('iterations') or 2)
    goal_hash = int.from_bytes(
        hashlib.sha256(goal_str.encode('utf-8')).digest()[:4], 'big'
    )
    goal_short = hashlib.sha1(goal_str.encode('utf-8')).hexdigest()[:8]

    results = []
    for lang in competitors:
        random.seed(lang.seed ^ goal_hash)
        best = run_ga(
            goal_str, generations=generations,
            population=population, mutation_rate=0.25,
        )
        results.append({'language': lang, 'score': best['score'],
                        'gene': best['gene']})

    results.sort(key=lambda r: r['score'])  # lowest first
    max_can_delete = max(0, len(entrants) - floor)
    eliminate_n = min(eliminate_n, max_can_delete)
    losers = results[:eliminate_n]
    winners = results[eliminate_n:]

    deleted_names = []
    with transaction.atomic():
        for r in losers:
            deleted_names.append(f"{r['language'].name} ({r['score']:.3f})")
            r['language'].delete()

        for r in winners:
            lang = r['language']
            spec = dict(lang.spec or {})
            grammars = dict(spec.get('grammars') or {})
            cat = dict(grammars.get('tournament') or {})
            cat.setdefault('note',
                           'Grammar variants won in language-competition '
                           'tournaments. Each variant is the best L-system '
                           'gene the language evolved against a random goal.')
            cat['axiom'] = r['gene'].get('axiom') or 'F'
            cat['iterations'] = int(r['gene'].get('iterations') or 4)
            variants = dict(cat.get('variants') or {})
            variants[f'g-{goal_short}'] = {
                k: v for k, v in (r['gene'].get('rules') or {}).items()
                if isinstance(v, str)
            }
            cat['variants'] = variants
            grammars['tournament'] = cat
            spec['grammars'] = grammars
            lang.spec = spec
            lang.save(update_fields=['spec', 'modified'])

    top = results[-1]
    msg = (
        f'Tournament done. Goal={len(goal_str)} chars (hash {goal_short}). '
        f'Winner: "{top["language"].name}" ({top["score"]:.3f}). '
    )
    if deleted_names:
        msg += f'Eliminated {len(deleted_names)}: ' + ', '.join(deleted_names) + '.'
    else:
        msg += 'No eliminations (floor held).'
    messages.success(request, msg)
    return redirect('evolution:list')


@login_required
@require_POST
def language_championship(request):
    """A bracket-style tournament-of-tournaments.

    Level 1: shuffle all eligible Languages, chunk into groups of
    `per_group`, run a tournament in each, top `winners_per_group`
    advance. Level 2 repeats on level-1 winners; level 3 on level-2
    winners; and so on up to `levels` deep.

    Losers are deleted subject to a single total floor budget that
    applies across all levels — so the Grammar Engine library never
    drops below `floor` Languages no matter how deep the bracket.

    Winners of each match absorb the evolved grammar variant as
    `grammars.championship.variants['L{level}-{goalshort}']`, so
    multi-level survivors collect stacks of trophies.
    """
    import hashlib
    from evolution.management.commands.speciate import (
        run_ga, random_gene, expand_lsystem,
    )
    from grammar_engine.models import Language

    try:
        levels            = max(1, min(5,  int(request.POST.get('levels') or 2)))
        per_group         = max(2, min(10, int(request.POST.get('per_group') or 5)))
        winners_per_group = max(1, min(per_group - 1,
                                       int(request.POST.get('winners_per_group') or 2)))
        generations       = max(10, min(200, int(request.POST.get('generations') or 40)))
        population        = max(8,  min(32,  int(request.POST.get('population') or 14)))
        floor             = max(2,  min(50,  int(request.POST.get('floor') or 4)))
    except (TypeError, ValueError):
        messages.error(request, 'Invalid championship params.')
        return redirect('evolution:list')

    active = [L for L in Language.objects.all() if L.first_variant() is not None]
    if len(active) < per_group:
        messages.error(
            request,
            f'Need at least {per_group} Languages with variants; have {len(active)}.'
        )
        return redirect('evolution:list')

    budget = max(0, len(active) - floor)
    all_deleted = []
    level_summaries = []

    def merge_trophy(lang, gene, level, goal_short):
        spec = dict(lang.spec or {})
        grammars = dict(spec.get('grammars') or {})
        cat = dict(grammars.get('championship') or {})
        cat.setdefault('note',
                       'Trophies from the Grammar Engine championship '
                       'bracket — one variant per match the language '
                       'survived.')
        cat['axiom'] = gene.get('axiom') or 'F'
        cat['iterations'] = int(gene.get('iterations') or 4)
        variants = dict(cat.get('variants') or {})
        variants[f'L{level}-{goal_short}'] = {
            k: v for k, v in (gene.get('rules') or {}).items()
            if isinstance(v, str)
        }
        cat['variants'] = variants
        grammars['championship'] = cat
        spec['grammars'] = grammars
        lang.spec = spec
        lang.save(update_fields=['spec', 'modified'])

    for level in range(1, levels + 1):
        if len(active) < 2:
            break
        random.shuffle(active)
        groups = [active[i:i + per_group]
                  for i in range(0, len(active), per_group)]
        next_round = []
        level_deleted = []
        level_match_count = 0

        for group in groups:
            if len(group) < 2:
                # Lone language: auto-advance, no match run.
                next_round.extend(group)
                continue
            level_match_count += 1

            goal_gene = random_gene()
            goal_str = expand_lsystem(
                goal_gene['axiom'], goal_gene.get('rules') or {},
                goal_gene.get('iterations') or 2,
            )
            goal_hash = int.from_bytes(
                hashlib.sha256(goal_str.encode('utf-8')).digest()[:4], 'big'
            )
            goal_short = hashlib.sha1(goal_str.encode('utf-8')).hexdigest()[:8]

            scored = []
            for lang in group:
                random.seed(lang.seed ^ goal_hash ^ (level * 0x9E3779B1))
                best = run_ga(
                    goal_str, generations=generations,
                    population=population, mutation_rate=0.25,
                )
                scored.append({'language': lang, 'score': best['score'],
                               'gene': best['gene'], 'goal_short': goal_short})

            scored.sort(key=lambda r: r['score'], reverse=True)
            keep = min(winners_per_group, len(scored) - 1)
            winners = scored[:keep]
            losers = scored[keep:]

            with transaction.atomic():
                for r in winners:
                    merge_trophy(r['language'], r['gene'],
                                 level, r['goal_short'])
                    next_round.append(r['language'])
                for r in losers:
                    if budget > 0:
                        level_deleted.append(
                            f"{r['language'].name} ({r['score']:.3f})"
                        )
                        r['language'].delete()
                        budget -= 1
                    else:
                        # Floor held — language survives but doesn't advance.
                        pass

        level_summaries.append(
            f'L{level}: {level_match_count} match(es), '
            f'{len(next_round)} advanced, {len(level_deleted)} eliminated'
        )
        all_deleted.extend(level_deleted)
        active = next_round
        if len(active) < 2:
            break

    champions = active
    champ_names = ', '.join(c.name for c in champions[:5])
    more = '' if len(champions) <= 5 else f', +{len(champions) - 5} more'

    msg = (
        f'Championship done. {levels}-level bracket, per_group={per_group}, '
        f'winners/group={winners_per_group}. '
        f'Champions ({len(champions)}): {champ_names}{more}. '
        + ' · '.join(level_summaries) + '. '
        + (f'Eliminated {len(all_deleted)} total.' if all_deleted
           else 'No eliminations (floor held).')
    )
    messages.success(request, msg)
    return redirect('evolution:list')
