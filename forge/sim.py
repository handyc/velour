"""Vectorized hex CA stepper.

The taxon.engine._step routine loops over every cell in pure Python.
At forge's GA scale (pop × generations × truth-rows × ticks ≈ 4M
cell-steps) that's the biggest bottleneck. Replacing it with a
single numpy lookup brings the step from ~17 ms (16×16) to ~0.3 ms
— roughly 50× faster for the same rule.

Hex-adjacency convention matches taxon.engine exactly:
  - flat-top hex with offset columns
  - neighbour order: N, NE, SE, S, SW, NW
  - row-offset rule: even columns (c % 2 == 0) → NE/NW go to (r-1),
    odd columns → NE/NW stay at (r). Mirrored for SE/SW.

For arbitrary K (≤ 16) the lookup table has K**7 entries (16384 for
K=4). Building it once per rule and re-using it across every step
of every individual is the savings.
"""
from __future__ import annotations

import numpy as np

from automaton.packed import PackedRuleset


def build_lookup(packed: PackedRuleset) -> np.ndarray:
    """Materialise the rule table as a flat uint8 array of K**7 entries.

    Index ordering matches taxon.engine._step:
        idx = self*K^6 + n0*K^5 + n1*K^4 + n2*K^3 + n3*K^2 + n4*K + n5
    """
    n = packed.n_situations
    arr = np.empty(n, dtype=np.uint8)
    for i in range(n):
        arr[i] = packed.get_by_index(i)
    return arr


def hex_step(grid: np.ndarray, lookup: np.ndarray, *,
             n_colors: int = 4) -> np.ndarray:
    """One synchronous hex CA tick using a precomputed lookup.

    Behaviourally identical to taxon.engine._step for the same rule,
    just much faster. Out-of-bounds neighbours are treated as 0
    (substrate), matching automaton/detector and the firmware.
    """
    H, W = grid.shape
    K = n_colors
    P = np.zeros((H + 2, W + 2), dtype=grid.dtype)
    P[1:H+1, 1:W+1] = grid

    cols = np.arange(W)
    even = (cols % 2 == 0)[None, :]    # broadcast to (H, W)

    # 6 neighbour planes — each one (H, W) of cell values at neighbour.
    n0 = P[0:H, 1:W+1]                                          # N
    n3 = P[2:H+2, 1:W+1]                                        # S
    n1 = np.where(even, P[0:H,   2:W+2], P[1:H+1, 2:W+2])       # NE
    n2 = np.where(even, P[1:H+1, 2:W+2], P[2:H+2, 2:W+2])       # SE
    n4 = np.where(even, P[1:H+1, 0:W],   P[2:H+2, 0:W])         # SW
    n5 = np.where(even, P[0:H,   0:W],   P[1:H+1, 0:W])         # NW

    g = grid.astype(np.int32)
    K6 = K ** 6
    idx = (g * K6
           + n0.astype(np.int32) * (K ** 5)
           + n1.astype(np.int32) * (K ** 4)
           + n2.astype(np.int32) * (K ** 3)
           + n3.astype(np.int32) * (K ** 2)
           + n4.astype(np.int32) * K
           + n5.astype(np.int32))
    return lookup[idx]


# ── Module-level cache of the wireworld lookup ─────────────────
_WIREWORLD_LUT: np.ndarray | None = None


def wireworld_lookup() -> np.ndarray:
    global _WIREWORLD_LUT
    if _WIREWORLD_LUT is None:
        from .wireworld import build_wireworld_rule
        _WIREWORLD_LUT = build_lookup(build_wireworld_rule())
    return _WIREWORLD_LUT
