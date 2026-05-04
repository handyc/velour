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

from .models import Circuit, EvolutionRun
from .runner import is_running, start_run
from .score import (
    analog_preset_rows, preset_truth_table,
    score_circuit, score_circuit_analog,
)
from .sim import hex_step, wireworld_lookup
from .wireworld import WIREWORLD_NAME, WIREWORLD_PALETTE


@login_required
def circuit_list(request):
    circuits = Circuit.objects.all()
    return render(request, 'forge/list.html', {'circuits': circuits})


@login_required
def gates_json(request):
    """Verified-gate catalog as JSON for the import-gate UI."""
    from django.db.models import Max, Q
    qs = (Circuit.objects
          .filter(evolution_runs__best_fitness__gte=1.0 - 1e-9)
          .annotate(best_run_fitness=Max(
              'evolution_runs__best_fitness',
              filter=Q(evolution_runs__status='done')))
          .distinct()
          .order_by('-updated_at'))
    out = []
    for c in qs:
        run = (c.evolution_runs
               .filter(best_fitness__gte=1.0 - 1e-9)
               .order_by('-finished_at').first())
        gate_type = (run.target.get('preset') if run and run.target
                     else '?')
        out.append({
            'slug':      c.slug,
            'name':      c.name,
            'gate_type': gate_type,
            'width':     c.width,
            'height':    c.height,
            'grid':      c.grid,
            'ports':     c.ports,
            'fitness':   c.best_run_fitness or 0.0,
        })
    return JsonResponse({'ok': True, 'gates': out})


@login_required
def gate_list(request):
    """Catalogue of verified gates — circuits with at least one
    EvolutionRun at fitness >= 1.0. The annotation buys us per-gate
    type, fitness, last verification time without an N+1."""
    from django.db.models import Max, Q
    qs = (Circuit.objects
          .filter(evolution_runs__best_fitness__gte=1.0 - 1e-9)
          .annotate(
              best_run_fitness=Max('evolution_runs__best_fitness',
                                   filter=Q(evolution_runs__status='done')),
              last_verified=Max('evolution_runs__finished_at',
                                filter=Q(evolution_runs__best_fitness__gte=1.0 - 1e-9)),
          )
          .distinct()
          .order_by('-last_verified', '-updated_at'))

    gates = []
    for c in qs:
        # Derive gate type from the most recent perfect run's target preset.
        run = (c.evolution_runs
               .filter(best_fitness__gte=1.0 - 1e-9)
               .order_by('-finished_at').first())
        gate_type = '?'
        if run and run.target:
            gate_type = run.target.get('preset') or '?'
        gates.append({
            'circuit':  c,
            'gate_type': gate_type,
            'fitness':  c.best_run_fitness or 0.0,
            'verified_at': c.last_verified,
            'best_run': run,
        })
    return render(request, 'forge/gates.html', {'gates': gates})


@login_required
@require_POST
def circuit_clone(request, slug):
    """Make a copy of `circuit` so the user can iterate without
    overwriting a verified gate."""
    src = get_object_or_404(Circuit, slug=slug)
    name = request.POST.get('name', '').strip() or f'{src.name} (copy)'
    dup = Circuit.objects.create(
        name=name[:160],
        description=src.description,
        width=src.width, height=src.height,
        palette=list(src.palette),
        grid=[row[:] for row in src.grid],
        rule_sha1=src.rule_sha1,
        rule_name=src.rule_name,
        ports=[dict(p) for p in (src.ports or [])],
        target=dict(src.target or {}),
    )
    return redirect('forge:detail', slug=dup.slug)


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
            entry = {
                'role': role,
                'name': str(p.get('name', ''))[:40],
                'x': x, 'y': y,
                'schedule': [int(t) for t in (p.get('schedule') or [])
                             if isinstance(t, (int, float))],
            }
            try:
                period = int(p.get('period') or 0)
                if period > 0:
                    entry['period'] = period
                    entry['offset'] = int(p.get('offset') or 0)
            except (TypeError, ValueError):
                pass
            clean.append(entry)
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

    def _pulses_at(port: dict, t: int) -> bool:
        """Honour either an explicit schedule list, a periodic
        period/offset pair, or fall back to "every tick". A schedule
        of [-1] is the standard "never fires" sentinel used by the
        score-row replay button."""
        sched = port.get('schedule')
        period = port.get('period')
        if sched is not None:
            if not sched:
                return True   # empty list = always-on (existing behaviour)
            return t in sched
        if period and int(period) > 0:
            offset = int(port.get('offset') or 0)
            return t >= offset and (t - offset) % int(period) == 0
        return True   # neither set = every tick

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

    lut = wireworld_lookup()
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
            if _pulses_at(p, t_now):
                grid = grid.copy()
                grid[p['y'], p['x']] = 2
        grid = hex_step(grid, lut, n_colors=4)
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
    kind = (target.get('kind') or '').strip().lower() or 'logic'
    rows = target.get('rows')
    if preset and preset != 'CUSTOM' and not rows:
        if kind == 'analog':
            rows = analog_preset_rows(preset)
        else:
            rows = preset_truth_table(preset)
        if rows is None:
            return JsonResponse({'ok': False,
                                 'reason': f'unknown preset: {preset}'},
                                status=400)

    full_target = {
        'preset':  preset or 'CUSTOM',
        'kind':    kind,
        'inputs':  target.get('inputs', ['A', 'B']),
        'outputs': target.get('outputs', ['Q']),
        'rows':    rows or [],
        'ticks':   target.get('ticks', 60 if kind == 'analog' else 30),
        'eval_window': target.get('eval_window'),
    }

    if kind == 'analog':
        result = score_circuit_analog(
            grid=grid, ports=ports,
            width=c.width, height=c.height, target=full_target,
        )
    else:
        result = score_circuit(
            grid=grid, ports=ports,
            width=c.width, height=c.height, target=full_target,
        )
    result['preset'] = preset or 'CUSTOM'
    result['target'] = full_target

    c.target = full_target
    c.save(update_fields=['target', 'updated_at'])
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
    kind = (target.get('kind') or '').strip().lower() or 'logic'
    rows = target.get('rows')
    if not rows:
        rows = (analog_preset_rows(preset) if kind == 'analog'
                else preset_truth_table(preset))
    if rows is None:
        return JsonResponse({'ok': False,
                             'reason': f'unknown preset: {preset}'},
                            status=400)
    full_target = {
        'preset':  preset,
        'kind':    kind,
        'inputs':  target.get('inputs', ['A', 'B']),
        'outputs': target.get('outputs', ['Q']),
        'rows':    rows,
        'ticks':   int(target.get('ticks', 60 if kind == 'analog' else 30)),
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
