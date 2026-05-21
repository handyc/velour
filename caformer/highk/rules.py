"""High-K rule storage + CA stepping.

A high-K rule maps a 7-tuple of K=2^32 neighbour values to a single
K=2^32 output value.  The input space is (2^32)^7 ≈ 2^224, so we
NEVER enumerate it.  We define a sparse subset and pick a default
behavior for everything else.

Phase 1 design: rules are derived from a Mandelbrot pixel grid.
The input pattern is mapped to a Mandelbrot pixel position via the
first two neighbour values:

      (x, y) = (input[0] mod 1024, input[1] mod 1024)

and the rule output is the K=2^32 colour at that pixel.  This means
the rule table is effectively a function of just the first two
neighbours — a simplification that lets us actually compute things.

Default behavior for "undefined" inputs (any input where the
derived pixel is the inside-set sentinel 0) is configurable:

  identity  — output = input[0] (center cell carries forward)
  zero      — output = 0 (silent / sink)
  hash      — output = hash(input) & 0xFFFFFFFF (chaotic)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np


@dataclass
class HighKRule:
    """Wraps a Mandelbrot pixel grid + default policy.

    Apply via `step(state)` for one tick on a 2D grid."""
    pixel_grid: np.ndarray         # uint32, shape (1024, 1024)
    default: Literal['identity', 'zero', 'hash'] = 'identity'

    def __post_init__(self):
        self.pixel_grid = np.asarray(self.pixel_grid, dtype=np.uint32)
        assert self.pixel_grid.ndim == 2

    # ── lookup ─────────────────────────────────────────────────

    def lookup_many(self, in0: np.ndarray, in1: np.ndarray,
                          in_center: np.ndarray
                          ) -> np.ndarray:
        """Vectorised rule lookup for a whole grid at once.

        in0, in1, in_center: uint32 arrays of identical shape.  The
        center is used only for the 'identity' default."""
        h, w = self.pixel_grid.shape
        x = (in0 % w).astype(np.int64)
        y = (in1 % h).astype(np.int64)
        out = self.pixel_grid[y, x].astype(np.uint32)
        if self.default != 'zero':
            mask = (out == 0)
            if mask.any():
                if self.default == 'identity':
                    out[mask] = in_center[mask]
                elif self.default == 'hash':
                    # Mix the three inputs into one uint32.
                    # Simple but reproducible.
                    h0 = in0[mask].astype(np.uint64)
                    h1 = in1[mask].astype(np.uint64)
                    h2 = in_center[mask].astype(np.uint64)
                    mixed = (
                        (h0 * np.uint64(0x9E3779B185EBCA87))
                        ^ (h1 * np.uint64(0xC2B2AE3D27D4EB4F))
                        ^ (h2 * np.uint64(0x165667B19E3779F9))
                    ) & np.uint64(0xFFFFFFFF)
                    out[mask] = mixed.astype(np.uint32)
        return out

    # ── stepping ───────────────────────────────────────────────

    def step(self, state: np.ndarray) -> np.ndarray:
        """One CA tick on a 2D uint32 grid.

        Neighbourhood: hex-like 6 around + 1 center = 7 inputs.  We
        only consult the first two (top-left & top-right) plus
        center, since that's the lookup signature.  Toroidal
        wrap-around at the grid edges."""
        state = np.asarray(state, dtype=np.uint32)
        h, w = state.shape
        # Top-left and top-right neighbours (hex-grid analogues).
        nw = np.roll(state, shift=(-1, -1), axis=(0, 1))   # up-left
        ne = np.roll(state, shift=(-1,  1), axis=(0, 1))   # up-right
        return self.lookup_many(nw, ne, state)

    # ── analysis ───────────────────────────────────────────────

    @staticmethod
    def stats(state: np.ndarray) -> dict:
        """Quick diagnostic on a CA grid."""
        state = state.flatten()
        unique = np.unique(state)
        n_unique = int(unique.size)
        n_total  = int(state.size)
        n_zero   = int((state == 0).sum())
        # Shannon entropy of the value distribution (bits).
        if n_unique > 1:
            _, counts = np.unique(state, return_counts=True)
            p = counts.astype(np.float64) / counts.sum()
            entropy = float(-(p * np.log2(p)).sum())
        else:
            entropy = 0.0
        return {
            'n_cells':       n_total,
            'n_unique':      n_unique,
            'n_zero':        n_zero,
            'frac_zero':     n_zero / max(1, n_total),
            'entropy_bits':  entropy,
            'max_value':     int(state.max()),
        }
