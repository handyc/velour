"""DNA → board mapping.

Phase 1 is the simplest sensible scheme: each base maps to one cell on
a 16×16 hex grid in column-major order (left-to-right, top-to-bottom),
no curves, no codon-folding. ``A=0, T/U=1, G=2, C=3``. Anything else
(``N``, ``R``, ``Y``, masked lowercase, gaps) is filled with a uniform-
random colour using a per-window seed so a given window always maps to
the same board across runs.
"""

from __future__ import annotations

import numpy as np

BOARD_W = 16
BOARD_H = 16
WINDOW_SIZE = BOARD_W * BOARD_H  # 256 bases


_BASE_LUT = {
    'A': 0,
    'T': 1, 'U': 1,
    'G': 2,
    'C': 3,
}


def dna_to_board(seq: str, seed: int = 0) -> np.ndarray:
    """Map a 256-base window to a 16×16 ``int8`` grid.

    Sequence shorter than ``WINDOW_SIZE`` is right-padded with random
    colours; longer is truncated. Non-ACGT/U bases (``N``, ambiguity
    codes, gaps) are also filled randomly. ``seed`` makes the random
    fill deterministic per window so successive scoring passes compare
    apples to apples.
    """
    rng = np.random.RandomState(seed & 0xFFFFFFFF)
    grid = rng.randint(0, 4, size=(BOARD_H, BOARD_W), dtype=np.int8)
    s = seq.upper()
    n = min(len(s), WINDOW_SIZE)
    for i in range(n):
        c = _BASE_LUT.get(s[i])
        if c is not None:
            grid[i // BOARD_W, i % BOARD_W] = c
    return grid
