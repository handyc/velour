"""Forge views — list / edit / run hex CA circuits.

The editor is server-rendered as an SVG and made interactive in JS;
edits are saved with a single POST that ships the full grid + ports
JSON. The runner steps the wireworld rule via taxon.engine and
returns trajectories as JSON for the page to animate."""
from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import (
    HttpResponse, HttpResponseBadRequest, JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

import numpy as np

from automaton.packed import PackedRuleset
from taxon.engine import _step

from .models import Circuit, EvolutionRun
from .runner import is_running, start_run
from .score import preset_truth_table, score_circuit
from .wireworld import WIREWORLD_NAME, WIREWORLD_PALETTE, build_wireworld_rule


def _wireworld_packed() -> PackedRuleset:
    """Cached singleton — built once per process."""
    pr = getattr(_wireworld_packed, '_cached', None)
    if pr is None:
        pr = build_wireworld_rule()
        _wireworld_packed._cached = pr
    return pr


@login_required
def circuit_list(request):
    circuits = Circuit.objects.all()
    return render(request, 'forge/list.html', {'circuits': circuits})


@login_required
def circuit_new(request):
    """Make a blank 16x16 wireworld circuit and bounce to its editor."""
    name = request.POST.get('name', '').strip() or 'untitled circuit'
    width = max(4, min(64, int(request.POST.get('width', 16) or 16)))
    height = max(4, min(64, int(request.POST.get('height', 16) or 16)))
    c = Circuit.objects.create(
        name=name, width=width, height=height,
        palette=list(WIREWORLD_PALETTE),
        rule_name=WIREWORLD_NAME,
    )
    return redirect('forge:detail', slug=c.slug)


@login_required
def circuit_detail(request, slug):
    c = get_object_or_404(Circuit, slug=slug)
    return render(request, 'forge/detail.html', {
        'circuit':  c,
        'palette':  c.palette_or_default,
        'wireworld_palette': WIREWORLD_PALETTE,
    })


@login_required
@require_POST
def circuit_save(request, slug):
    c = get_object_or_404(Circuit, slug=slug)
    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return HttpResponseBadRequest('bad JSON')

    grid = payload.get('grid')
    if not isinstance(grid, list) or len(grid) != c.height:
        return HttpResponseBadRequest('grid must be HxW list of ints')
    for row in grid:
        if not isinstance(row, list) or len(row) != c.width:
            return HttpResponseBadRequest('grid row width mismatch')
        for v in row:
            if not isinstance(v, int) or v < 0 or v > 3:
                return HttpResponseBadRequest('grid values must be 0..3')
    c.grid = grid

    ports = payload.get('ports')
    if isinstance(ports, list):
        clean = []
        for p in ports:
            if not isinstance(p, dict):
                continue
            role = p.get('role')
            if role not in ('input', 'output'):
                continue
            try:
                x = int(p.get('x'))
                y = int(p.get('y'))
            except (TypeError, ValueError):
                continue
            if not (0 <= x < c.width and 0 <= y < c.height):
                continue
            clean.append({
                'role': role,
                'name': str(p.get('name', ''))[:40],
                'x': x, 'y': y,
                'schedule': [int(t) for t in (p.get('schedule') or [])
                             if isinstance(t, (int, float))],
            })
        c.ports = clean

    name = payload.get('name')
    if isinstance(name, str) and name.strip():
        c.name = name.strip()[:160]

    c.save()
    return JsonResponse({'ok': True, 'slug': c.slug,
                         'updated_at': c.updated_at.isoformat()})


@login_required
def circuit_run(request, slug):
    """Step the circuit forward and return the trajectory.

    Accepts either:
      - GET ?ticks=N — runs from the *saved* grid (legacy)
      - POST {grid, ports, ticks} JSON — runs from the supplied (live)
        grid without touching the DB. The page uses POST so you don't
        have to Save before pressing Play.
    """
    c = get_object_or_404(Circuit, slug=slug)

    grid_data = c.grid
    ports = c.ports or []
    ticks = 24
    autosave = False

    if request.method == 'POST':
        try:
            payload = json.loads(request.body or b'{}')
        except json.JSONDecodeError:
            return HttpResponseBadRequest('bad JSON')
        if 'grid' in payload:
            grid_data = payload['grid']
        if 'ports' in payload:
            ports = payload['ports'] or []
        if 'ticks' in payload:
            try:
                ticks = max(0, min(200, int(payload['ticks'])))
            except (TypeError, ValueError):
                pass
        autosave = bool(payload.get('autosave', False))
    else:
        try:
            ticks = max(0, min(200, int(request.GET.get('ticks', 24))))
        except (TypeError, ValueError):
            ticks = 24

    packed = _wireworld_packed()
    try:
        grid = np.array(grid_data, dtype=np.uint8)
    except (TypeError, ValueError):
        return HttpResponseBadRequest('grid must be a 2D int array')
    if grid.shape != (c.height, c.width):
        return HttpResponseBadRequest(
            f'grid shape {tuple(grid.shape)} != ({c.height}, {c.width})')

    if autosave and request.method == 'POST':
        c.grid = grid.tolist()
        c.ports = ports
        c.save(update_fields=['grid', 'ports', 'updated_at'])

    traj = [grid.tolist()]
    for _ in range(ticks):
        t_now = len(traj) - 1
        for p in ports:
            if p.get('role') != 'input':
                continue
            sched = p.get('schedule') or [t_now]
            if t_now in sched:
                grid = grid.copy()
                grid[p['y'], p['x']] = 2
        grid = _step(grid, packed)
        traj.append(grid.tolist())

    outputs = []
    for p in ports:
        if p.get('role') != 'output':
            continue
        outputs.append({
            'name': p.get('name'),
            'x': p['x'], 'y': p['y'],
            'reads': [int(traj[t][p['y']][p['x']])
                      for t in range(len(traj))],
        })

    return JsonResponse({
        'ok': True,
        'ticks': ticks,
        'trajectory': traj,
        'outputs': outputs,
        'palette': c.palette_or_default,
        'autosaved': autosave,
    })


@login_required
@require_POST
def circuit_score(request, slug):
    """Score the circuit against a target truth table.

    Request JSON:
        grid:   2D array (live, may differ from saved)
        ports:  list of port dicts (live)
        target: {
            preset: 'AND'|'OR'|'XOR'|'NAND'|'NOR'|'XNOR'|'CUSTOM',
            inputs: ['A', 'B'],
            outputs: ['Q'],
            rows: [{in, out}, …]   # required if preset == 'CUSTOM'
            ticks: 30,
            eval_window: [5, 30],
        }
    """
    c = get_object_or_404(Circuit, slug=slug)
    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return HttpResponseBadRequest('bad JSON')

    grid = payload.get('grid') or c.grid
    ports = payload.get('ports') if 'ports' in payload else (c.ports or [])
    target = payload.get('target') or {}

    preset = (target.get('preset') or '').strip().upper()
    rows = target.get('rows')
    if preset and preset != 'CUSTOM' and not rows:
        rows = preset_truth_table(preset)
        if rows is None:
            return JsonResponse({'ok': False,
                                 'reason': f'unknown preset: {preset}'},
                                status=400)

    full_target = {
        'inputs':  target.get('inputs', ['A', 'B']),
        'outputs': target.get('outputs', ['Q']),
        'rows':    rows or [],
        'ticks':   target.get('ticks', 30),
        'eval_window': target.get('eval_window'),
    }

    result = score_circuit(
        grid=grid, ports=ports,
        width=c.width, height=c.height, target=full_target,
    )
    result['preset'] = preset or 'CUSTOM'
    result['target'] = full_target
    return JsonResponse(result)


@login_required
def circuit_evolve(request, slug):
    """Evolve page — recent GA runs + form to start a new one."""
    c = get_object_or_404(Circuit, slug=slug)
    runs = c.evolution_runs.order_by('-started_at')[:20]
    return render(request, 'forge/evolve.html', {
        'circuit':  c,
        'runs':     runs,
        'palette':  c.palette_or_default,
    })


@login_required
@require_POST
def circuit_evolve_start(request, slug):
    """Create an EvolutionRun row and spawn the GA thread."""
    c = get_object_or_404(Circuit, slug=slug)

    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return HttpResponseBadRequest('bad JSON')

    grid = payload.get('grid')
    ports = payload.get('ports')
    if grid is not None:
        c.grid = grid
    if ports is not None:
        c.ports = ports
    if grid is not None or ports is not None:
        c.save(update_fields=['grid', 'ports', 'updated_at'])

    target = payload.get('target') or {}
    preset = (target.get('preset') or '').strip().upper() or 'AND'
    rows = target.get('rows') or preset_truth_table(preset)
    if rows is None:
        return JsonResponse({'ok': False,
                             'reason': f'unknown preset: {preset}'},
                            status=400)
    full_target = {
        'preset':  preset,
        'inputs':  target.get('inputs', ['A', 'B']),
        'outputs': target.get('outputs', ['Q']),
        'rows':    rows,
        'ticks':   int(target.get('ticks', 30)),
        'eval_window': target.get('eval_window'),
    }

    def _i(name, default, lo, hi):
        try:
            v = int(payload.get(name, default))
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    def _f(name, default, lo, hi):
        try:
            v = float(payload.get(name, default))
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    run = EvolutionRun.objects.create(
        circuit=c, status='queued',
        pop_size=_i('pop_size', 32, 4, 128),
        generations=_i('generations', 30, 1, 200),
        mutation_rate=_f('mutation_rate', 0.03, 0.0, 1.0),
        crossover_rate=_f('crossover_rate', 0.85, 0.0, 1.0),
        tournament_k=_i('tournament_k', 3, 2, 10),
        init_density=_f('init_density', 0.20, 0.0, 1.0),
        seed=_i('seed', 7, 0, 2**31 - 1),
        target=full_target,
    )
    start_run(run.pk)
    return JsonResponse({'ok': True, 'run_id': run.pk})


@login_required
def circuit_evolve_status(request, slug, run_id):
    """JSON status for a running / completed evolution run."""
    c = get_object_or_404(Circuit, slug=slug)
    run = get_object_or_404(EvolutionRun, pk=run_id, circuit=c)
    return JsonResponse({
        'ok': True,
        'run_id': run.pk,
        'status': run.status,
        'is_active': run.is_active,
        'is_alive': is_running(run.pk),
        'current_gen': run.current_gen,
        'generations': run.generations,
        'best_fitness': run.best_fitness,
        'fitness_history': run.fitness_history,
        'best_grid': run.best_grid,
        'finished_at': run.finished_at.isoformat() if run.finished_at else None,
        'started_at': run.started_at.isoformat(),
        'error': run.error,
        'target': run.target,
    })


@login_required
@require_POST
def circuit_evolve_promote(request, slug, run_id):
    """Copy a finished run's best_grid into the circuit's design."""
    c = get_object_or_404(Circuit, slug=slug)
    run = get_object_or_404(EvolutionRun, pk=run_id, circuit=c)
    if not run.best_grid:
        return JsonResponse({'ok': False, 'reason': 'no best grid'},
                            status=400)
    c.grid = run.best_grid
    c.save(update_fields=['grid', 'updated_at'])
    return JsonResponse({
        'ok': True, 'fitness': run.best_fitness,
        'detail_url': reverse('forge:detail', args=[c.slug]),
    })


@login_required
@require_POST
def circuit_delete(request, slug):
    c = get_object_or_404(Circuit, slug=slug)
    name = c.name
    c.delete()
    messages.success(request, f'Deleted circuit "{name}".')
    return redirect('forge:list')
