"""Pluggable metric registry for taxon.

A metric is a function that takes (trajectory, hashes, packed) and
returns (value, extra_dict). The registry is code-based — register
with the @metric decorator. Metrics are stable identifiers used as
MetricRun.metric strings.

Phase 1 metrics (5):

  langton_lambda
      Fraction of rule-table outputs that differ from the cell's own
      state. The original "edge of chaos" knob — low λ → class 1/2,
      high λ → class 3, intermediate λ → class 4 (often).

  density_entropy
      Time-averaged Shannon entropy of the cell-color histogram. Low
      → homogeneous (class 1) or locked (class 2); high → chaotic.

  activity_rate
      Mean per-tick fraction of cells whose state changed. 0 → still
      life; 1 → maximum churn.

  transient_length
      First tick at which the trajectory enters a cycle (any earlier
      grid hash repeats). Caps at horizon if no cycle is found.

  attractor_period
      Period of the entered cycle (1 = still life). 0 if no cycle
      was detected within horizon.

Each returns (float, dict) where the dict is metadata for display.
"""
from __future__ import annotations

import math
from typing import Callable, Dict, List, Tuple

import numpy as np

from automaton.packed import PackedRuleset


MetricFn = Callable[[np.ndarray, List[str], PackedRuleset], Tuple[float, dict]]

REGISTRY: Dict[str, MetricFn] = {}
META: Dict[str, dict] = {}


def metric(name: str, *, label: str, blurb: str,
           range_hint: Tuple[float, float] = (0.0, 1.0)) -> Callable:
    """Decorator: register a metric function under ``name``."""
    def deco(fn: MetricFn) -> MetricFn:
        REGISTRY[name] = fn
        META[name] = {'name': name, 'label': label, 'blurb': blurb,
                      'range': list(range_hint)}
        return fn
    return deco


# ── Static metrics (operate on the rule table only) ────────────────

@metric(
    'langton_lambda',
    label='Langton λ',
    blurb='Fraction of rule outputs that differ from the cell self-state.',
    range_hint=(0.0, 1.0),
)
def m_langton_lambda(trajectory, hashes, packed: PackedRuleset):
    K = packed.n_colors
    differ = 0
    total = packed.n_situations
    pK6 = K ** 6
    for i in range(total):
        self_c = i // pK6
        out = packed.get_by_index(i)
        if out != self_c:
            differ += 1
    return differ / total, {'differ': differ, 'total': total}


# ── Dynamic metrics (operate on the trajectory) ────────────────────

@metric(
    'density_entropy',
    label='Density entropy',
    blurb='Time-averaged Shannon entropy of cell-color histograms (bits).',
    range_hint=(0.0, 2.0),
)
def m_density_entropy(trajectory: np.ndarray, hashes, packed):
    K = packed.n_colors
    T = trajectory.shape[0]
    total_h = 0.0
    for t in range(T):
        counts = np.bincount(trajectory[t].ravel(), minlength=K)
        total = counts.sum()
        if total == 0:
            continue
        p = counts / total
        h = 0.0
        for pi in p:
            if pi > 0:
                h -= pi * math.log2(pi)
        total_h += h
    mean_h = total_h / T
    max_h = math.log2(K)
    return mean_h, {'normalized': mean_h / max_h if max_h else 0.0,
                    'max_bits': max_h}


@metric(
    'activity_rate',
    label='Activity rate',
    blurb='Mean per-tick fraction of cells that changed state.',
    range_hint=(0.0, 1.0),
)
def m_activity_rate(trajectory: np.ndarray, hashes, packed):
    T = trajectory.shape[0]
    if T < 2:
        return 0.0, {'frames': T}
    changes = []
    for t in range(1, T):
        diff = (trajectory[t] != trajectory[t-1]).sum()
        changes.append(diff / trajectory[t].size)
    return float(np.mean(changes)), {'frames': T,
                                     'final_rate': float(changes[-1])}


@metric(
    'transient_length',
    label='Transient length',
    blurb='First tick at which a previously-seen grid state recurs.',
    range_hint=(0.0, 240.0),
)
def m_transient_length(trajectory, hashes: List[str], packed):
    seen = {}
    for t, h in enumerate(hashes):
        if h in seen:
            return float(seen[h]), {'cycle_at': t, 'period': t - seen[h]}
        seen[h] = t
    return float(len(hashes)), {'cycle_at': None, 'period': 0}


@metric(
    'attractor_period',
    label='Attractor period',
    blurb='Length of the cycle the trajectory entered (0 if none in horizon).',
    range_hint=(0.0, 30.0),
)
def m_attractor_period(trajectory, hashes: List[str], packed):
    seen = {}
    for t, h in enumerate(hashes):
        if h in seen:
            return float(t - seen[h]), {'cycle_at': t,
                                        'first_seen': seen[h]}
        seen[h] = t
    return 0.0, {'cycle_at': None}


def list_metrics() -> List[dict]:
    """Display order for UI tables. Static first, then dynamic."""
    order = ['langton_lambda', 'density_entropy', 'activity_rate',
             'transient_length', 'attractor_period']
    return [META[n] for n in order if n in META]


def run_all(trajectory, hashes, packed) -> Dict[str, Tuple[float, dict]]:
    """Compute every registered metric for one trajectory."""
    return {name: fn(trajectory, hashes, packed)
            for name, fn in REGISTRY.items()}
