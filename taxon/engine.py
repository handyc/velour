"""Hex CA simulator + trajectory recorder for taxon metrics.

Wraps automaton.detector.step_packed but operates on numpy arrays
for speed and returns the full grid trajectory so metrics can
inspect transients, periodicity, density, entropy, etc. without
re-simulating per metric.

Hex topology, neighbor order (N, NE, SE, S, SW, NW), and edge
padding all match automaton — so metric values computed here are
comparable across apps.
"""
from __future__ import annotations

import hashlib
from typing import List, Tuple

import numpy as np

from automaton.packed import PackedRuleset


def _seed_grid(W: int, H: int, n_colors: int, seed: int) -> np.ndarray:
    """Reproducible random initial state. Same seed → same grid."""
    rng = np.random.default_rng(seed or 1)
    return rng.integers(0, n_colors, size=(H, W), dtype=np.uint8)


def _step(grid: np.ndarray, packed: PackedRuleset) -> np.ndarray:
    """One hex CA tick on a numpy grid. Pure-python lookup loop —
    fine at 24×24×120 (~70k cell-steps per sim, sub-50ms in practice).
    For larger horizons we'd vectorize; not needed yet."""
    H, W = grid.shape
    K = packed.n_colors
    w = (K**6, K**5, K**4, K**3, K**2, K**1)
    bits = packed.bits_per_cell
    mask = (1 << bits) - 1
    data = packed.data
    out = np.zeros_like(grid)

    g = grid  # local alias
    for r in range(H):
        for c in range(W):
            self_c = int(g[r, c])
            even = (c % 2) == 0
            # Six neighbors with 0-padding for out-of-bounds. Order
            # matches automaton.detector._hex_neighbors_padded exactly.
            n0 = int(g[r-1, c]) if r-1 >= 0 else 0
            nec_r = r-1 if even else r
            n1 = int(g[nec_r, c+1]) if (nec_r >= 0 and c+1 < W) else 0
            sec_r = r if even else r+1
            n2 = int(g[sec_r, c+1]) if (sec_r < H and c+1 < W) else 0
            n3 = int(g[r+1, c]) if r+1 < H else 0
            swc_r = r if even else r+1
            n4 = int(g[swc_r, c-1]) if (swc_r < H and c-1 >= 0) else 0
            nwc_r = r-1 if even else r
            n5 = int(g[nwc_r, c-1]) if (nwc_r >= 0 and c-1 >= 0) else 0

            idx = (self_c*w[0] + n0*w[1] + n1*w[2] + n2*w[3]
                   + n3*w[4] + n4*w[5] + n5)
            bit_offset = idx * bits
            byte_i = bit_offset >> 3
            bit_i = bit_offset & 7
            out[r, c] = (data[byte_i] >> bit_i) & mask
    return out


def simulate(packed: PackedRuleset, W: int, H: int,
             horizon: int, seed: int) -> Tuple[np.ndarray, List[str]]:
    """Run the rule for `horizon` steps from a seeded random grid.

    Returns:
      trajectory : (horizon+1, H, W) uint8 array of grid states
      hashes     : list of sha1 of each grid (for cycle detection)
    """
    grid = _seed_grid(W, H, packed.n_colors, seed)
    traj = [grid.copy()]
    hashes = [hashlib.sha1(grid.tobytes()).hexdigest()]
    for _ in range(horizon):
        grid = _step(grid, packed)
        traj.append(grid.copy())
        hashes.append(hashlib.sha1(grid.tobytes()).hexdigest())
    return np.stack(traj, axis=0), hashes
