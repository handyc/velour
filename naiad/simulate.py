"""Phase-1 simulation of water flowing through a System.

Model: each stage attenuates each contaminant independently by a
fixed fraction (the `removal` JSON on StageType). Contaminants the
stage doesn't mention pass through. Contaminants not present in the
source profile are not invented. Stages apply in position order.

Intentionally simple — real membrane kinetics, biological
competition, and flow bottlenecks will be their own phases. This
gets the data-flow plumbing right so those can slot in later
without reshaping the schema.
"""

from __future__ import annotations

from .models import CONTAMINANT_KEYS, Stage, System, WaterProfile


def simulate(system: System, source: WaterProfile,
             target: WaterProfile | None = None) -> dict:
    """Run `source` through `system`'s stages. Returns a dict with
    trace (per-stage remaining values), output (final values),
    passed (bool or None), and failures (list of contaminants that
    missed the target). Does NOT write a TestRun — the caller
    decides whether to persist.
    """
    current = dict(source.values or {})
    trace = []
    stages = list(Stage.objects.filter(system=system)
                  .select_related('stage_type')
                  .order_by('position'))

    trace.append({
        'position': -1,
        'stage':    'source',
        'label':    source.name,
        'values':   dict(current),
    })

    for stg in stages:
        removal = stg.stage_type.removal or {}
        for key, value in list(current.items()):
            frac = float(removal.get(key, 0.0) or 0.0)
            if frac <= 0:
                continue
            frac = min(max(frac, 0.0), 1.0)
            current[key] = value * (1.0 - frac)
        trace.append({
            'position': stg.position,
            'stage':    stg.stage_type.slug,
            'label':    stg.label or stg.stage_type.name,
            'values':   dict(current),
        })

    output = dict(current)

    passed = None
    failures: list[str] = []
    if target is not None and target.values:
        passed = True
        for key, limit in target.values.items():
            try:
                lim = float(limit)
            except (TypeError, ValueError):
                continue
            if key not in output:
                # Source didn't measure it; we can't prove pass nor fail.
                continue
            if output[key] > lim:
                passed = False
                failures.append(key)

    return {
        'trace':    trace,
        'output':   output,
        'passed':   passed,
        'failures': failures,
    }
