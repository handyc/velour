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
from django.views.decorators.http import require_POST

import numpy as np

from automaton.packed import PackedRuleset
from taxon.engine import _step

from .models import Circuit
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

    Query params:
        ticks=N    (default 24, max 200)
    """
    c = get_object_or_404(Circuit, slug=slug)
    try:
        ticks = max(0, min(200, int(request.GET.get('ticks', 24))))
    except (TypeError, ValueError):
        ticks = 24

    packed = _wireworld_packed()
    grid = np.array(c.grid, dtype=np.uint8)
    if grid.shape != (c.height, c.width):
        return HttpResponseBadRequest('grid shape mismatch')

    traj = [grid.tolist()]
    for _ in range(ticks):
        # Inputs: any port with role=input pulses its cell to head (2)
        # at every tick whose offset matches `len(traj) - 1`.
        t_now = len(traj) - 1
        for p in (c.ports or []):
            if p.get('role') != 'input':
                continue
            sched = p.get('schedule') or [t_now]
            if t_now in sched:
                # Force the cell to head BEFORE stepping; the rule will
                # then propagate as usual.
                grid = grid.copy()
                grid[p['y'], p['x']] = 2
        grid = _step(grid, packed)
        traj.append(grid.tolist())

    # Output reads — ALL output cell values across all ticks.
    outputs = []
    for p in (c.ports or []):
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
    })


@login_required
@require_POST
def circuit_delete(request, slug):
    c = get_object_or_404(Circuit, slug=slug)
    name = c.name
    c.delete()
    messages.success(request, f'Deleted circuit "{name}".')
    return redirect('forge:list')
