"""Domain-aware simulation of a System.

Phase 1: water purification only.  Each stage attenuated each
contaminant fraction (`removal` JSON on StageType), with optional
transformations (`converts`).

Phase 2 (ev40 era): adds the data-domain simulator.  System.domain
selects which transformation model runs:

  domain='water' → contaminant attenuation, additive transforms
  domain='data'  → metric-vector composition for OSI 7-layer
                   pipelines (latency adds, throughput/range cap,
                   reliability multiplies, etc.)

Both share the same trace shape so the existing funnel UI works for
either domain — it just shows different keys per row.

Intentionally simple — real membrane kinetics, real TCP congestion
control, etc. are out of scope.  This gets the data-flow plumbing
right so subsystems can refine the math without reshaping the model.
"""

from __future__ import annotations

from .models import (
    CONTAMINANT_KEYS,
    NETWORK_METRIC_KEYS,
    NETWORK_METRIC_DIRECTION,
    Stage, System, WaterProfile,
)


# ────────────────────────────────────────────────────────────────
# Public entry point — dispatches on domain
# ────────────────────────────────────────────────────────────────
def simulate(system: System, source: WaterProfile,
             target: WaterProfile | None = None) -> dict:
    """Run `source` through `system`'s stages.  Returns a dict with
    trace (per-stage values), output (final values), passed (bool or
    None), and failures (list of metric/contaminant keys missing the
    target).  Dispatches on system.domain — water or data.

    Domain mismatch (system.domain != source.domain) returns a
    no-op trace with passed=False so the UI flags it loudly.
    """
    if source and source.domain and source.domain != system.domain:
        return {
            'trace': [{'position': -1, 'stage': 'error',
                       'label': 'domain mismatch',
                       'values': dict(source.values or {})}],
            'output': dict(source.values or {}),
            'passed': False,
            'failures': ['__domain_mismatch__'],
        }
    if system.domain == 'data':
        return _simulate_data(system, source, target)
    return _simulate_water(system, source, target)


# ────────────────────────────────────────────────────────────────
# Water domain — Phase 1 logic, unchanged behaviour
# ────────────────────────────────────────────────────────────────
def _simulate_water(system: System, source: WaterProfile,
                    target: WaterProfile | None) -> dict:
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
        converts = stg.stage_type.converts or {}
        produced: dict[str, float] = {}
        for key, value in list(current.items()):
            frac = float(removal.get(key, 0.0) or 0.0)
            if frac <= 0:
                continue
            frac = min(max(frac, 0.0), 1.0)
            removed = value * frac
            current[key] = value - removed
            for dst, yield_factor in (converts.get(key) or {}).items():
                produced[dst] = produced.get(dst, 0.0) + removed * float(yield_factor)
        for dst, amount in produced.items():
            current[dst] = current.get(dst, 0.0) + amount
        trace.append({
            'position': stg.position,
            'stage':    stg.stage_type.slug,
            'label':    stg.label or stg.stage_type.name,
            'values':   dict(current),
        })

    output = dict(current)

    passed = None
    failures: list[str] = []
    DETECTION_EPS = 1e-6
    if target is not None and target.values:
        passed = True
        for key, limit in target.values.items():
            try:
                lim = float(limit)
            except (TypeError, ValueError):
                continue
            if key not in output:
                continue
            if lim <= 0:
                lim = DETECTION_EPS
            if output[key] > lim:
                passed = False
                failures.append(key)

    return {
        'trace':    trace,
        'output':   output,
        'passed':   passed,
        'failures': failures,
    }


# ────────────────────────────────────────────────────────────────
# Data domain — OSI 7-layer pipeline composition
# ────────────────────────────────────────────────────────────────

# Additive transforms: stage value is added to current.
# Used for metrics where each stage layers on top of the previous.
_DATA_ADDITIVE = {'latency_ms', 'jitter_ms', 'cost_eur_month', 'energy_watts'}

# Multiplicative transforms: stage value multiplies current.
# Reliability uses this — each layer either degrades (val<1) or
# adds redundancy (val>1).  Capped at the [0, 99.99]% range so
# infinite chains can't asymptote past 100%.
_DATA_MULTIPLY = {'reliability_pct'}

# Cap-or-multiply: values < 1 act as multipliers, values >= 1 act
# as caps (the chain is bottlenecked by the most restrictive stage).
# Used for "amount-of-something" metrics where each stage either
# downsizes the budget or imposes its own ceiling.
_DATA_CAP_OR_MUL = {'throughput_kbps', 'range_m', 'payload_bytes',
                    'duty_cycle_pct'}


def _apply_data_stage(current: dict, params: dict) -> None:
    """Mutate `current` by applying one stage's transformations."""
    for key, raw in params.items():
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if key in _DATA_ADDITIVE:
            current[key] = float(current.get(key, 0.0)) + val
        elif key in _DATA_MULTIPLY:
            cur = float(current.get(key, 100.0))
            new = cur * val
            # 99.99% asymptote so a long redundant chain doesn't
            # claim 100% reliability — there's always residual risk.
            if new > 99.99:
                new = 99.99
            if new < 0:
                new = 0.0
            current[key] = new
        elif key in _DATA_CAP_OR_MUL:
            cur = float(current.get(key, val))
            if 0 < val < 1.0:
                # multiplicative — fractional scaling
                current[key] = cur * val
            else:
                # cap — pipeline limited by tightest stage
                current[key] = min(cur, val)
        # Unknown keys are ignored (forward-compat — adding new
        # metrics to a stage doesn't crash old simulators).


def _simulate_data(system: System, source: WaterProfile,
                   target: WaterProfile | None) -> dict:
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
        params = stg.stage_type.removal or {}
        _apply_data_stage(current, params)
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
        for key, want in target.values.items():
            try:
                target_val = float(want)
            except (TypeError, ValueError):
                continue
            if key not in output:
                continue
            actual = float(output[key])
            direction = NETWORK_METRIC_DIRECTION.get(key, 'lower')
            ok = (actual <= target_val) if direction == 'lower' \
                 else (actual >= target_val)
            if not ok:
                passed = False
                failures.append(key)

    return {
        'trace':    trace,
        'output':   output,
        'passed':   passed,
        'failures': failures,
    }


# ────────────────────────────────────────────────────────────────
# Fitness scoring (used by the GA in evolve_dispatch + UI funnel)
# ────────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────────
# Fitness scoring (used by the GA in evolve_dispatch + UI funnel)
# ────────────────────────────────────────────────────────────────

# Default per-metric weights for the data domain.  Reliability is
# heavily preferred per the user's directive — operational uptime
# is the default goal, with speed/cost as user-elevated overrides.
# Water domain uses uniform weight=1 by default — the existing
# water GA's penalty system already encodes its multi-objective
# trade-offs separately.
DATA_DEFAULT_WEIGHTS = {
    'reliability_pct':  5.0,
    'latency_ms':       1.0,
    'jitter_ms':        1.0,
    'throughput_kbps':  1.0,
    'cost_eur_month':   1.0,
    'energy_watts':     1.0,
    'range_m':          1.0,
    'payload_bytes':    1.0,
    'duty_cycle_pct':   1.0,
}


def _resolve_weights(domain: str, overrides: dict | None) -> dict:
    """Compose effective per-metric weights: domain defaults +
    user/system overrides.  Overrides win on key collision."""
    base = dict(DATA_DEFAULT_WEIGHTS) if domain == 'data' else {}
    if overrides:
        for k, v in overrides.items():
            try:
                base[k] = float(v)
            except (TypeError, ValueError):
                continue
    return base


def fitness(result: dict, target: WaterProfile,
            domain: str = 'water',
            weights: dict | None = None) -> float:
    """Single-number score in [0, 1] for how close `result['output']`
    is to `target.values`.  1.0 = exactly meets every target metric;
    0.0 = far from every target.

    Water domain: lower contaminant = better.  Score per key =
    max(0, 1 - actual / max(target, eps)).
    Data domain: each metric uses its NETWORK_METRIC_DIRECTION
    (lower-better or higher-better) to compute a [0, 1] score; final
    is the WEIGHTED MEAN of per-metric scores.  Reliability is the
    default-heavy weight (uptime > everything else unless told
    otherwise) — pass `weights={...}` to override.
    """
    if not target or not target.values:
        return 0.0
    output = result.get('output') or {}
    if not output:
        return 0.0

    eff_weights = _resolve_weights(domain, weights)

    weighted_sum = 0.0
    weight_total = 0.0
    for key, want in target.values.items():
        try:
            want_val = float(want)
        except (TypeError, ValueError):
            continue
        if key not in output:
            continue
        actual = float(output[key])
        if domain == 'data':
            direction = NETWORK_METRIC_DIRECTION.get(key, 'lower')
            if direction == 'higher':
                if want_val <= 0:
                    s = 1.0 if actual > 0 else 0.0
                else:
                    s = min(1.0, actual / want_val)
            else:
                if want_val <= 0 and actual <= 0:
                    s = 1.0
                elif want_val <= 0:
                    s = 0.0
                else:
                    s = max(0.0, 1.0 - actual / max(want_val, 1e-9))
        else:
            # water — always "lower is better"
            eps = max(want_val, 1e-9)
            s = max(0.0, min(1.0, 1.0 - actual / eps))

        w = float(eff_weights.get(key, 1.0))
        weighted_sum += s * w
        weight_total += w

    if weight_total <= 0:
        return 0.0
    return weighted_sum / weight_total
