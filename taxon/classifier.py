"""Heuristic Wolfram classifier (1–4) over taxon's metric vector.

The decision boundary intentionally treats class 4 (edge of chaos)
as a *narrow* zone, not a default — many "interesting" rules are
class 2 or class 3, and forcing everything into class 4 is the
exact bias the user called out.

Inputs (all in the canonical ranges set by metrics.py):
  langton_lambda     ∈ [0, 1]
  density_entropy    ∈ [0, log2(K)]   (normalized to [0,1])
  activity_rate      ∈ [0, 1]
  transient_length   ∈ [0, horizon]
  attractor_period   ∈ {0, 1, 2, ...}

Decision tree (in order; first match wins):

  Class 1 — homogeneous
    activity_rate < 0.005  AND  density_entropy_norm < 0.10
    → state collapses to a single colour or near-uniform.

  Class 2 — periodic
    attractor_period in {1..16}  AND  activity_rate < 0.30
    → enters a short cycle, low ongoing activity.

  Class 4 — complex (edge of chaos)
    transient_length > horizon * 0.5  AND
    0.20 < activity_rate < 0.55     AND
    0.45 < density_entropy_norm < 0.90
    → long transient with moderate, structured activity.

  Class 3 — chaotic (default for high activity / no cycle)
    everything else with activity_rate > 0.30
    → high churn, no detected periodicity.

  Otherwise: class 2 (low activity, no obvious chaos, no cycle found
  within horizon — most likely a slow oscillator or quasi-periodic).

Returns: (wolfram_class, confidence, basis_dict)
  confidence is a heuristic in [0, 1] tying to how well metrics
  cleared the boundary thresholds.
"""
from __future__ import annotations

import math
from typing import Dict, Tuple


def classify(metric_values: Dict[str, float],
             horizon: int = 120,
             n_colors: int = 4) -> Tuple[int, float, dict]:
    lam = metric_values.get('langton_lambda', 0.0)
    h = metric_values.get('density_entropy', 0.0)
    h_norm = h / math.log2(n_colors) if n_colors >= 2 else 0.0
    act = metric_values.get('activity_rate', 0.0)
    trans = metric_values.get('transient_length', 0.0)
    period = metric_values.get('attractor_period', 0.0)
    trans_frac = trans / horizon if horizon else 0.0

    basis = {
        'langton_lambda': lam,
        'density_entropy_norm': h_norm,
        'activity_rate': act,
        'transient_frac': trans_frac,
        'attractor_period': period,
    }

    # Class 1 — homogeneous / settled.
    if act < 0.005 and h_norm < 0.10:
        conf = 1.0 - max(act / 0.005, h_norm / 0.10)
        return 1, max(0.5, min(1.0, conf)), basis

    # Class 2 — short cycle, low-to-moderate activity.
    if 1 <= period <= 16 and act < 0.30:
        conf = 1.0 - (act / 0.30) * 0.5 - (period / 16) * 0.2
        return 2, max(0.5, min(1.0, conf)), basis

    # Class 4 — narrow band, only if the trajectory hasn't cycled,
    # activity is moderate, and entropy is in the structured range.
    if (trans_frac > 0.5
            and 0.20 < act < 0.55
            and 0.45 < h_norm < 0.90):
        # Confidence peaks in the middle of each band.
        act_center = abs(act - 0.375) / 0.175       # 0 at center, 1 at edge
        h_center = abs(h_norm - 0.675) / 0.225
        conf = 1.0 - 0.5 * (act_center + h_center) / 2
        return 4, max(0.4, min(1.0, conf)), basis

    # Class 3 — high churn, no detected period.
    if act > 0.30 and (period == 0 or period > 16):
        conf = min(1.0, (act - 0.30) / 0.40 + 0.5)
        return 3, conf, basis

    # Fallback — slow / quasi-periodic. Treat as class 2 with low confidence.
    return 2, 0.35, basis


def class_label(n: int) -> str:
    return {
        1: 'homogeneous',
        2: 'periodic',
        3: 'chaotic',
        4: 'complex (edge of chaos)',
    }.get(n, '—')


def class_color(n: int) -> str:
    """Distinguishable, colorblind-safe per Dark2."""
    return {
        1: '#1b9e77',  # green
        2: '#7570b3',  # purple
        3: '#d95f02',  # orange
        4: '#e7298a',  # magenta
    }.get(n, '#888')
