"""Python reference engine for the HXNN nearest-neighbour CA.

The hot loop scans, for each cell, the bin of prototypes that share
the cell's self-colour and picks the one whose 6-neighbour vector is
closest by squared Euclidean distance. Output of the winning
prototype is the cell's next colour.

This implementation is intentionally simple — vectorisable later
with numpy if needed. The browser-side engine in ``static/hexnn/js``
mirrors the same algorithm.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

from .genome import Genome


def build_bins(g: Genome) -> List[Tuple[np.ndarray, np.ndarray]]:
    """Group prototypes by self-colour for fast lookup.

    Returns a list of length K. ``bins[s]`` is ``(neighbours, outputs)``
    where ``neighbours`` has shape ``(M, 6)`` (the 6 neighbour values
    of every prototype with self-colour ``s``) and ``outputs`` is the
    matching ``(M,)`` array of output colours.
    """
    keys = np.asarray(g.keys, dtype=np.int16)         # (N, 7)
    outs = np.asarray(g.outputs, dtype=np.int16)      # (N,)
    bins: List[Tuple[np.ndarray, np.ndarray]] = []
    for s in range(g.k):
        mask = keys[:, 0] == s
        bins.append((keys[mask, 1:].copy(), outs[mask].copy()))
    return bins


def step(grid: np.ndarray, g: Genome,
         bins: Optional[List[Tuple[np.ndarray, np.ndarray]]] = None,
         ) -> np.ndarray:
    """Advance ``grid`` (H, W, dtype=int) one tick under genome ``g``.

    Edge cells treat out-of-bounds neighbours as colour 0, matching
    the existing HXC4 engine convention. Bin lookup pre-grouped by
    self-colour keeps the search size to ~N/K per cell.
    """
    if bins is None:
        bins = build_bins(g)

    H, W = grid.shape
    out = np.empty_like(grid)

    # Precompute neighbour offsets for flat-top, offset-column hex —
    # same convention as automaton.detector and the s3lab engine.
    for y in range(H):
        for x in range(W):
            self_c = int(grid[y, x])
            even = (x & 1) == 0
            n = (
                grid[y - 1, x]                         if y - 1 >= 0 else 0,
                grid[y - 1 if even else y, x + 1]      if 0 <= (y - 1 if even else y) < H and x + 1 < W else 0,
                grid[y     if even else y + 1, x + 1]  if 0 <= (y if even else y + 1) < H and x + 1 < W else 0,
                grid[y + 1, x]                         if y + 1 < H else 0,
                grid[y     if even else y + 1, x - 1]  if 0 <= (y if even else y + 1) < H and x - 1 >= 0 else 0,
                grid[y - 1 if even else y, x - 1]      if 0 <= (y - 1 if even else y) < H and x - 1 >= 0 else 0,
            )
            nbs, outs = bins[self_c]
            if nbs.shape[0] == 0:
                out[y, x] = self_c
                continue
            target = np.asarray(n, dtype=np.int16)
            diff = nbs - target
            d2 = np.einsum('ij,ij->i', diff, diff)
            best = int(np.argmin(d2))
            out[y, x] = int(outs[best])

    return out


# ── Helpers for building random / identity genomes ──────────────────


def random_genome(k: int = 4, n_log2: int = 14, seed: int = 0) -> Genome:
    """Uniformly-random prototypes — useful for "what does this look like?"
    scratch demos. Not a hunting strategy; most random rules at high K
    are visual noise."""
    rng = np.random.default_rng(seed)
    n = 1 << n_log2
    keys_arr = rng.integers(0, k, size=(n, 7), dtype=np.int16)
    outs_arr = rng.integers(0, k, size=(n,),  dtype=np.int16)
    return Genome(
        k=k, n_log2=n_log2,
        palette=bytes(rng.integers(16, 232, size=k, dtype=np.uint8).tolist()),
        keys=[tuple(int(v) for v in row) for row in keys_arr],
        outputs=[int(v) for v in outs_arr],
    )


def k4_lattice_genome(seed: int = 0) -> Genome:
    """A K=4 genome whose prototype keys sit on the K=4 lattice —
    every (s, n0..n5) ∈ {0,1,2,3}^7 occupies one slot. Outputs are
    random 0..3. Equivalent in *behaviour* to a random K=4 positional
    rule when run on K=4 input — so this format trivially subsumes the
    existing K=4 family. Useful as a sanity check."""
    rng = np.random.default_rng(seed)
    keys: List[Tuple[int, ...]] = []
    for idx in range(1 << 14):
        # Decode idx as a base-4 7-digit number; matches automaton.packed.
        rem = idx
        parts = []
        for _ in range(7):
            parts.append(rem & 3)
            rem >>= 2
        # Reverse so MSB is `self`, matching the s3lab/automaton convention.
        parts.reverse()
        keys.append(tuple(parts))
    outs = [int(v) for v in rng.integers(0, 4, size=1 << 14, dtype=np.int16)]
    return Genome(
        k=4, n_log2=14,
        palette=bytes([16, 196, 51, 226]),
        keys=keys, outputs=outs,
    )
