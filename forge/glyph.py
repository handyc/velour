"""Glyph-evolution mode for Forge.

Same GA / population / runner / threading machinery as wireworld; what
changes is the fitness function. Instead of asking "does this rule
substrate propagate signal correctly?", we ask "does this substrate's
ink mask, when compared to a target glyph, score well under Chamfer
distance?"

Conceptually: the genome is a binary mask (wire vs empty), exactly as
in wireworld. The GA preserves the start/end "ports" as wire so the
glyph always touches both endpoints. The fitness function ignores
wireworld dynamics entirely — it just compares the wire layout to a
target letter rendered at the circuit's resolution.

This is intentionally a *static* scorer for v1, even though the user's
sketch hinted at growing-CA dynamics. The static version gets the
corpus, the distance metric, the UI flow, and the GA dispatch in
place. v2 can swap in a stroke-cleaning rule and score the trajectory
without touching the corpus or the views.

Distance metric: bidirectional mean Chamfer (Euclidean distance
transform). For each ink pixel in the candidate, average distance to
the nearest target pixel; symmetrically the other way. Then map to
fitness via 1 - dist/normalize_max so it sits in [0, 1] like the
wireworld scorers.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy.ndimage import distance_transform_edt


# ── 16×16 corpus ─────────────────────────────────────────────────────
#
# Five small, unambiguous letter shapes — chosen for legibility at
# small resolution and for obvious endpoints. Strokes are 2 pixels
# wide so a single-pixel drift doesn't drop the candidate to fitness 0.
#
# Coordinate convention: rows go down (y=0 is top), columns go right
# (x=0 is left). The first row drawn corresponds to y=0.

_GLYPH_RAW: dict[str, list[str]] = {
    'L': [
        "................",
        "..11............",
        "..11............",
        "..11............",
        "..11............",
        "..11............",
        "..11............",
        "..11............",
        "..11............",
        "..11............",
        "..11............",
        "..11............",
        "..11............",
        "..1111111111....",
        "..1111111111....",
        "................",
    ],
    'T': [
        "................",
        ".11111111111111.",
        ".11111111111111.",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        "................",
    ],
    'I': [
        "................",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        ".....1111.......",
        "................",
    ],
    'V': [
        "................",
        "..11........11..",
        "..11........11..",
        "...11......11...",
        "...11......11...",
        "....11....11....",
        "....11....11....",
        ".....11..11.....",
        ".....11..11.....",
        "......1111......",
        "......1111......",
        ".......11.......",
        ".......11.......",
        "................",
        "................",
        "................",
    ],
    'X': [
        "................",
        "..11........11..",
        "..11........11..",
        "...11......11...",
        "...11......11...",
        "....11....11....",
        "....11....11....",
        ".....11..11.....",
        ".....11..11.....",
        "....11....11....",
        "....11....11....",
        "...11......11...",
        "...11......11...",
        "..11........11..",
        "..11........11..",
        "................",
    ],
}


# Suggested start/end pixels for each letter — these become the GA's
# port cells (forced wire so the GA never drops them). Picked to lie
# *inside* the target stroke so a perfect candidate keeps them.
_GLYPH_ENDPOINTS: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {
    'L': ((2,  1),  (11, 14)),    # top of vertical, right end of foot
    'T': ((1,  1),  (8,  14)),    # left end of crossbar, bottom of stem
    'I': ((5,  1),  (5,  14)),    # top, bottom
    'V': ((2,  1),  (11, 1)),     # two top tips
    'X': ((2,  1),  (13, 14)),    # two diagonal endpoints (one diagonal)
}


def parse_glyph(rows: list[str]) -> list[list[int]]:
    """Convert a stringy mask into a list[list[int]] grid."""
    out: list[list[int]] = []
    for row in rows:
        out.append([1 if ch == '1' else 0 for ch in row])
    return out


GLYPH_GRIDS: dict[str, list[list[int]]] = {
    name: parse_glyph(raw) for name, raw in _GLYPH_RAW.items()
}
GLYPH_LETTERS: list[str] = list(_GLYPH_RAW.keys())


def glyph_height(letter: str) -> int:
    return len(GLYPH_GRIDS.get(letter, []))


def glyph_width(letter: str) -> int:
    g = GLYPH_GRIDS.get(letter)
    return len(g[0]) if g else 0


def glyph_endpoints(letter: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    return _GLYPH_ENDPOINTS.get(letter)


def make_glyph_ports(letter: str) -> list[dict[str, Any]]:
    """Two ports — `start` and `end` — at the suggested endpoints.
    role 'input' for both because the GA's _force_port_wires loop
    treats every port as a forced-wire cell regardless of role."""
    ep = glyph_endpoints(letter)
    if not ep:
        return []
    (sx, sy), (ex, ey) = ep
    return [
        {'role': 'input', 'name': 'start', 'x': sx, 'y': sy, 'schedule': []},
        {'role': 'input', 'name': 'end',   'x': ex, 'y': ey, 'schedule': []},
    ]


def make_glyph_target(letter: str, *, normalize_max: float = 4.0) -> dict[str, Any]:
    """Build a `target` dict suitable for storing on a Circuit /
    EvolutionRun for glyph-mode evolution.

    `normalize_max` is the Chamfer distance at which fitness is
    pinned to 0 (anything worse also scores 0). 4.0 means an average
    pixel-to-target drift of 4 cells reads as "totally wrong"; 0.0
    means "perfect overlap". Lower values mean a stricter scoring
    landscape; higher values mean noisier candidates still get some
    fitness gradient to climb.
    """
    return {
        'kind':          'glyph',
        'preset':        f'GLYPH_{letter}',
        'letter':        letter,
        'normalize_max': normalize_max,
        # echoed for the runner / status JSON:
        'inputs':        ['start', 'end'],
        'outputs':       [],
        'rows':          [],
        'ticks':         0,
        'eval_window':   None,
    }


# ── distance metric ──────────────────────────────────────────────────
#
# Bidirectional mean Chamfer distance over Euclidean DT.
#
# A pure pixel-XOR loss punishes a one-cell drift exactly as hard as a
# completely wrong glyph, which collapses the GA's fitness gradient.
# Chamfer gives partial credit for "near-but-not-quite" pixels: a
# candidate that's the right shape one column too far left scores
# nearly perfectly.

def _ink_mean_distance_to(a: np.ndarray, b: np.ndarray) -> float:
    """Mean Euclidean distance from each ink pixel of `a` to nearest
    ink pixel of `b`. Returns 0 if `a` is empty (nothing to measure).
    Returns inf if `b` is empty (no targets at all)."""
    if not a.any():
        return 0.0
    if not b.any():
        return float('inf')
    # distance_transform_edt gives, for each cell, distance to nearest
    # 0 in its input. We want distance to nearest 1 in `b`, so feed it
    # `1 - b`.
    dt = distance_transform_edt(1 - b)
    return float(dt[a > 0].mean())


def chamfer_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Symmetric mean Chamfer distance.  Returns inf if either
    side is empty (nothing to compare)."""
    return 0.5 * (_ink_mean_distance_to(a, b)
                  + _ink_mean_distance_to(b, a))


# ── scorer ───────────────────────────────────────────────────────────


def score_circuit_glyph(*, grid: list[list[int]],
                        ports: list[dict[str, Any]],
                        width: int, height: int,
                        target: dict[str, Any]) -> dict[str, Any]:
    """Score a Circuit grid against a target letter glyph.

    Treats the candidate's wire (cell value 1) as ink, and scores its
    Chamfer distance to the letter's reference mask. Other states are
    ignored — wireworld dynamics are not run.

    Result shape mirrors `score_circuit` so the views / templates that
    consume fitness JSON don't have to special-case glyph mode beyond
    reading `kind` to decide which sub-fields are interesting.
    """
    letter = str(target.get('letter') or '').upper()
    ref = GLYPH_GRIDS.get(letter)
    if ref is None:
        return {'ok': False,
                'reason': f'unknown glyph letter: {letter!r}'}

    target_arr = np.array(ref, dtype=np.uint8)
    if target_arr.shape != (height, width):
        return {
            'ok': False,
            'reason': (f'glyph {letter} is '
                       f'{target_arr.shape[0]}x{target_arr.shape[1]}, '
                       f'circuit is {height}x{width} — sizes must match'),
        }

    cand_arr = (np.array(grid, dtype=np.uint8) == 1).astype(np.uint8)
    if cand_arr.shape != (height, width):
        return {
            'ok': False,
            'reason': (f'candidate grid shape {tuple(cand_arr.shape)} != '
                       f'({height}, {width})'),
        }

    cd = chamfer_distance(cand_arr, target_arr)
    norm_max = float(target.get('normalize_max', 4.0)) or 4.0

    # Three complementary terms, then multiplied so a candidate must
    # win on *all* axes — getting the shape (Chamfer), hitting the
    # target pixels (recall), and not over-painting (precision):
    #
    #   chamfer_fit — distance-transform gradient toward the right
    #                 *region*. Lets the GA climb out of zero-overlap
    #                 random init: even before any pixel agrees with
    #                 the target, getting nearer raises this score.
    #
    #   IoU         — exact-match overlap. This is what the GA is
    #                 ultimately optimising for; it reads 1.0 only on
    #                 a perfect mask.
    #
    #   precision   — penalises extra ink directly. A candidate that
    #                 fills a 100-pixel region around a 24-pixel
    #                 target pays a 0.24 multiplier here; pixel-XOR
    #                 would be silent on this case.
    #
    # Multiplicative combine: fitness = (a + 1) * (b + 1) - 1 style
    # would smooth the bottom; pure product zeros out unless all
    # three are nonzero, which empirically traps the GA. So we use a
    # weighted geometric mean: each term is mapped to [0.05, 1] before
    # multiplying, ensuring the GA always has a small slope to climb.
    if cd == float('inf'):
        chamfer_fit = 0.0
    else:
        chamfer_fit = max(0.0, 1.0 - cd / norm_max)

    intersection = int(np.logical_and(cand_arr, target_arr).sum())
    union        = int(np.logical_or(cand_arr,  target_arr).sum())
    cand_n   = int(cand_arr.sum())
    target_n = int(target_arr.sum())
    precision = (intersection / cand_n)   if cand_n   > 0 else 0.0
    recall    = (intersection / target_n) if target_n > 0 else 0.0
    beta = 0.5
    denom = (beta * beta) * precision + recall
    f_beta = ((1 + beta * beta) * precision * recall / denom
              if denom > 0 else 0.0)
    iou = (intersection / union) if union > 0 else 0.0

    # Geometric mean of (chamfer_fit, precision, recall) with a small
    # floor so the GA never sees a hard zero. Since precision and
    # recall both must be high for a clean match, the product
    # (precision * recall) drives the GA away from over-painting.
    floor = 0.05
    a = max(floor, chamfer_fit)
    p = max(floor, precision)
    r = max(floor, recall)
    fitness = (a * p * r) ** (1.0 / 3.0)
    # When all three are at floor (truly random) the geometric mean
    # is 0.05; remap so floor-only candidates read as 0.0:
    fitness = max(0.0, (fitness - floor) / (1.0 - floor))
    correct = 1 if fitness >= 0.95 else 0

    return {
        'ok':       True,
        'kind':     'glyph',
        'letter':   letter,
        'inputs':   ['start', 'end'],
        'outputs':  [],
        'ticks':    0,
        'eval_window': [0, 0],
        'chamfer':           cd if cd != float('inf') else None,
        'iou':               iou,
        'precision':         precision,
        'recall':            recall,
        'f_beta':            f_beta,
        'chamfer_fit':       chamfer_fit,
        'normalize_max':     norm_max,
        'target_pixels':     int(target_arr.sum()),
        'candidate_pixels':  int(cand_arr.sum()),
        'intersection':      intersection,
        'union':             union,
        'correct':  correct,
        'total':    1,
        'fitness':  fitness,
        'rows':     [{
            'ok':       fitness >= 0.95,
            'score':    fitness,
            'in':       [letter],
            'expected': [int(target_arr.sum())],
            'actual':   [int(cand_arr.sum())],
            'chamfer':  cd if cd != float('inf') else None,
            'iou':      iou,
        }],
    }
