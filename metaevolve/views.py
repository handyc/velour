"""metaevolve views — orchestration over doom_ca.evolve.

Index lists Targets + archive.  Runner is the embedded-iframe batch
driver.  Archive POST endpoint accepts a gene JSON from the evolve
page and stores it.  Archive detail + materialize let the user
turn a saved gene into a real doom_ca GameSession.
"""

from __future__ import annotations
import json

from django.contrib import messages
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Target, ArchivedWinner


def index(request):
    targets = (Target.objects
               .annotate(winner_count=Count('winners'))
               .order_by('-priority', 'name'))
    recent = ArchivedWinner.objects.order_by('-created_at')[:20]
    top    = ArchivedWinner.objects.order_by('-fitness')[:20]
    return render(request, 'metaevolve/index.html', {
        'targets': targets,
        'recent':  recent,
        'top':     top,
    })


def runner(request):
    """Batch runner page — embeds doom_ca/evolve in an iframe and
    walks through active Targets in priority order, archiving the
    top winners after each run."""
    targets = list(Target.objects.filter(active=True)
                   .order_by('-priority', 'name'))
    return render(request, 'metaevolve/runner.html', {
        'targets':      targets,
        'targets_json': json.dumps([{
            'id':              t.id,
            'name':            t.name,
            'archetype':       t.archetype,
            'population_size': t.population_size,
            'generations':     t.generations,
            'max_turns':       t.max_turns,
            'grid_side':       t.grid_side,
            'runs_per_batch':  t.runs_per_batch,
            'archive_top_k':   t.archive_top_k,
        } for t in targets]),
    })


@csrf_exempt
@require_POST
def archive(request):
    """Accept a winner gene from the evolve page via JSON.  Returns
    {ok, id} on success.  CSRF-exempt because it's called from an
    iframe-embedded evolve page, where threading the CSRF token is
    non-trivial — the endpoint only writes to ArchivedWinner so risk
    is low; production deployments behind auth can re-enable CSRF."""
    try:
        body = json.loads(request.body.decode())
    except (ValueError, UnicodeDecodeError) as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    target_id = body.get('target_id')
    target = Target.objects.filter(pk=target_id).first() if target_id else None
    if not target:
        return JsonResponse({'ok': False,
            'error': 'unknown target_id'}, status=400)

    gene = body.get('gene') or {}
    fitness = float(body.get('fitness') or 0.0)
    components = body.get('components')
    notes = (body.get('notes') or '')[:1000]

    if not gene.get('rule'):
        return JsonResponse({'ok': False,
            'error': 'gene.rule missing'}, status=400)

    w = ArchivedWinner.objects.create(
        target=target, fitness=fitness, gene_json=gene,
        components_json=components, notes=notes,
    )
    # Update target run stats.
    from django.utils import timezone
    target.total_runs += 1
    target.last_run_at = timezone.now()
    target.save(update_fields=['total_runs', 'last_run_at'])
    return JsonResponse({'ok': True, 'id': w.id, 'fitness': w.fitness})


def archive_detail(request, pk):
    w = get_object_or_404(ArchivedWinner, pk=pk)
    return render(request, 'metaevolve/archive_detail.html', {'w': w})


@require_POST
def materialize_winner(request, pk):
    """Turn an archived gene into a real doom_ca GameSession + Pact
    by reusing doom_ca.views.materialize_agent's logic via direct
    model construction.  Returns redirect to the new play page."""
    from spoeqi.models import Pact, COMPONENTS
    from doom_ca.models import GameSession
    from django.utils import timezone

    w = get_object_or_404(ArchivedWinner, pk=pk)
    gene = w.gene_json

    rule = gene.get('rule') or []
    if len(rule) != 16384:
        messages.error(request, 'Gene rule must be 16,384 entries.')
        return redirect('metaevolve:archive_detail', pk=pk)
    try:
        rule_bytes = bytes(int(b) & 3 for b in rule)
    except (TypeError, ValueError) as exc:
        messages.error(request, f'Bad rule data: {exc}')
        return redirect('metaevolve:archive_detail', pk=pk)

    seed_byte    = int(gene.get('seed_byte', 0)) & 0xFF
    component_grid = int(gene.get('component_grid', 24))
    world_mode   = gene.get('world_mode', 'overlay')
    monster_count = max(0, min(64, int(gene.get('monster_count', 8))))
    wall_threshold = max(1, min(3, int(gene.get('wall_threshold', 2))))
    pure_mode    = bool(gene.get('pure_mode', False))
    health_pack_count = max(0, min(12, int(gene.get('health_pack_count', 3))))
    ammo_pack_count   = max(0, min(12, int(gene.get('ammo_pack_count',   3))))
    door_count        = max(0, min(1,  int(gene.get('door_count',        1))))
    music_style_idx   = max(0, min(15, int(gene.get('music_style_idx',   0))))

    base = f'meta-{w.target.archetype}-{w.id}'
    pact_name = base + '-pact'
    n = 2
    while Pact.objects.filter(name=pact_name).exists():
        pact_name = f'{base}-pact-{n}'; n += 1
    game_name = base + '-game'
    n = 2
    while GameSession.objects.filter(name=game_name).exists():
        game_name = f'{base}-game-{n}'; n += 1

    pact = Pact(
        name=pact_name,
        seed_matrix=bytes([seed_byte] * COMPONENTS),
        rule_snapshot=rule_bytes,
        rule_diversity='shared',
        component_grid=component_grid,
        clock_model='synced',
        launch_time=timezone.now(),
        notes=f'Materialised from metaevolve.ArchivedWinner #{w.id}.',
    )
    palette = gene.get('palette')
    if isinstance(palette, list) and len(palette) == 4:
        try:
            pact.palette = [[int(c[0]) & 0xFF, int(c[1]) & 0xFF, int(c[2]) & 0xFF]
                            for c in palette if isinstance(c, list) and len(c) == 3]
            if len(pact.palette) != 4:
                pact.palette = None
        except (TypeError, ValueError):
            pact.palette = None
    pact.save()

    session = GameSession(
        name=game_name, pact=pact, component=0,
        world_mode=world_mode, monster_count=monster_count,
        wall_threshold=wall_threshold, pure_mode=pure_mode,
        health_pack_count=health_pack_count,
        ammo_pack_count=ammo_pack_count,
        door_count=door_count,
        music_style_idx=music_style_idx,
        target_game=w.target.target_game,
        notes=f'Materialised from metaevolve archive #{w.id} '
              f'(target: {w.target.name}, fitness {w.fitness:.3f}).',
    )
    session.save()
    w.materialised_session_slug = session.slug
    w.save(update_fields=['materialised_session_slug'])

    messages.success(request,
        f'Materialised "{game_name}" from archive #{w.id}.')
    return redirect('doom_ca:play', slug=session.slug)
