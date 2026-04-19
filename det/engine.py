"""Det — search primitives for finding Class-4 (edge-of-chaos)
rulesets on hexagonal cellular automata.

The substrate is the one Automaton already runs: a W×H hex grid
with 6 neighbors per cell and n ∈ {2, 3, 4} colors. We reuse
`automaton.detector.step_exact` as the stepper so that any ruleset
Det discovers can be promoted to an `automaton.RuleSet` and run
interactively without any translation.

The interesting question is: given 4^7 = 16,384 possible 7-tuples
(and more when wildcards are allowed), which small random subsets
behave like Rule 110 in 2D — localized structures, gliders,
long transients — rather than freezing (Class 1), oscillating
trivially (Class 2), or saturating to noise (Class 3)?

This module provides the measurements; `det.search` provides the
generator and the scorer that combine them.
"""

from collections import Counter
from math import log2
import random


def block_entropy_grid(grid, k=2):
    """Shannon entropy of k×k blocks across a 2-D grid, in bits.

    A uniform grid → 0. A grid of independent random cells with c
    colors → 2 k² log2(c) in the limit. Rule-110-like grids sit in
    the middle: coherent local patches embedded in a varied background.
    """
    H = len(grid)
    if H < k:
        return 0.0
    W = len(grid[0])
    if W < k:
        return 0.0
    counts = Counter()
    for r in range(H - k + 1):
        for c in range(W - k + 1):
            block = tuple(grid[r + dr][c + dc]
                          for dr in range(k) for dc in range(k))
            counts[block] += 1
    n = sum(counts.values())
    return -sum((v / n) * log2(v / n) for v in counts.values() if v > 0)


def density_profile(grid, n_colors):
    """Fraction of cells in each color. Returns a list of length n_colors.
    Uniform [1/n, 1/n, ...] means all colors equally represented; a
    very skewed profile means the dynamics collapsed toward one color."""
    total = 0
    counts = [0] * n_colors
    for row in grid:
        for c in row:
            if 0 <= c < n_colors:
                counts[c] += 1
            total += 1
    if total == 0:
        return [0.0] * n_colors
    return [c / total for c in counts]


def is_uniform(grid):
    """True iff all cells share a color."""
    first = grid[0][0]
    for row in grid:
        for c in row:
            if c != first:
                return False
    return True


def activity_rate(prev, curr):
    """Fraction of cells that changed between two grids of equal shape.
    Rule-110-like dynamics hover in the range ~0.02-0.25: not frozen,
    not boiling."""
    total = 0
    changed = 0
    for r in range(len(prev)):
        for c in range(len(prev[0])):
            total += 1
            if prev[r][c] != curr[r][c]:
                changed += 1
    return changed / total if total else 0.0


def _hash_grid(grid):
    """Tuple-of-tuples works well as a dict key for the modest grid
    sizes we screen at (16×16 or 24×24). Cheaper than crypto hashes
    and exact."""
    return tuple(tuple(row) for row in grid)


def detect_cycle(history, max_period=40):
    """Does the current grid match any grid within the last
    `max_period` steps? Returns (period, entered_at) or (None, None)."""
    if len(history) < 2:
        return (None, None)
    last = _hash_grid(history[-1])
    limit = min(max_period, len(history) - 1)
    for back in range(1, limit + 1):
        if _hash_grid(history[-1 - back]) == last:
            return (back, len(history) - 1 - back)
    return (None, None)


def seeded_random_grid(W, H, n_colors, seed):
    """A deterministic random initial grid. Same seed → same grid."""
    rng = random.Random(seed)
    return [[rng.randrange(n_colors) for _ in range(W)] for _ in range(H)]
