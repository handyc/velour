"""Autostereogram (Magic Eye) on a hex grid.

Each hex is one solid colour drawn from a small palette.  The
horizontal pattern repeats with period `period` hexes; *within* the
shape region, columns are offset by `depth × amplitude` hexes,
which the visual system fuses into a 3-D pop-out when the viewer
crosses (or diverges) their eyes by one period.

Single-image-random-dot-stereograms (SIRDS) normally use random
pixels; here we use a deterministic hex-color pattern seeded from
`pattern_seed` so the result is reproducible and printable.

Depth-map shapes are built-in primitives so no upload is needed:
  - 'circle'    : a centred filled circle pops out by `amplitude`
  - 'square'    : centred square
  - 'ring'      : annulus
  - 'plus'      : 5-cell plus sign
  - 'gradient_x': linear depth ramp left→right
  - 'gradient_y': linear depth ramp top→bottom
"""

from __future__ import annotations
from . import Param

SLUG        = 'autostereogram'
NAME        = 'Autostereogram'
DESCRIPTION = ('Magic-Eye-style hex stereogram. Cross or diverge '
                'your eyes by one period (the configured pattern '
                'width) and the depth shape pops out of the page.')

PALETTE = [
    '#202020', '#5a3a1a', '#a07020',
    '#306030', '#3070a0', '#a03060',
    '#c0a040', '#e0e0e0',
]

PARAMS = [
    Param('period',     'pattern period (hex columns)', 'int', 8,  4, 32, 1,
           help='Horizontal repeat period.  Cross-eyed fusion at this '
                'width gives the depth illusion.'),
    Param('amplitude',  'depth amplitude (hexes)',       'int', 2,  1, 6, 1,
           help='How many hexes columns the depth shape pops out by.  '
                'Larger = more dramatic but harder to fuse.'),
    Param('shape',      'depth shape',                   'choice',
                        'circle', None, None, None,
                        ['circle','square','ring','plus','gradient_x','gradient_y'],
           help='Shape of the depth map (the thing that pops out).'),
    Param('shape_size', 'shape size (hex radius)',       'int', 6,  2, 30, 1,
           help='Half-extent of the shape in hex cells.'),
    Param('palette_n',  'palette size',                  'int', 6,  2, 8, 1,
           help='How many distinct colours the repeating pattern uses.  '
                'Smaller is easier to fuse; 4-6 is the sweet spot.'),
    Param('pattern_seed','pattern seed',                 'int', 42, 0, 1<<30, 1,
           help='Deterministic seed for the in-period colour pattern.'),
]


# ── deterministic LCG (matches hexhunter.c so users can predict it) ──
def _rng_step(state: int) -> tuple[int, int]:
    state = (state * 1103515245 + 12345) & 0xFFFFFFFF
    return state, state >> 16


def _build_pattern_row(period: int, n_colors: int, seed: int) -> list[int]:
    """One period worth of palette indices, deterministic in (period,
    n_colors, seed).  Different seeds produce different background
    textures; same seed always reproduces."""
    state = (seed if seed != 0 else 1) & 0xFFFFFFFF
    out = []
    for _ in range(period):
        state, v = _rng_step(state)
        out.append(v % n_colors)
    return out


def _depth(shape: str, r: int, c: int, gw: int, gh: int, size: int,
           amp: int) -> int:
    """Return depth shift in hexes (0 = background) for the cell."""
    cx, cy = gw / 2.0, gh / 2.0
    dx, dy = c - cx, r - cy
    if shape == 'circle':
        return amp if (dx * dx + dy * dy) <= size * size else 0
    if shape == 'square':
        return amp if (abs(dx) <= size and abs(dy) <= size) else 0
    if shape == 'ring':
        d2 = dx * dx + dy * dy
        outer = size * size
        inner = (size - max(2, size // 2)) ** 2
        return amp if (inner <= d2 <= outer) else 0
    if shape == 'plus':
        arm = max(1, size // 2)
        if (abs(dx) <= size and abs(dy) <= arm) or \
           (abs(dy) <= size and abs(dx) <= arm):
            return amp
        return 0
    if shape == 'gradient_x':
        # 0..amp linearly across the width
        return int(round(amp * (c / max(1, gw - 1))))
    if shape == 'gradient_y':
        return int(round(amp * (r / max(1, gh - 1))))
    return 0


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    period   = max(2, int(params.get('period', 8)))
    amp      = max(1, int(params.get('amplitude', 2)))
    shape    = str(params.get('shape', 'circle'))
    size     = max(1, int(params.get('shape_size', 6)))
    n_cols   = max(2, min(len(PALETTE), int(params.get('palette_n', 6))))
    seed     = int(params.get('pattern_seed', 42)) & 0xFFFFFFFF

    # Per-row pattern seeded from (seed, row) so vertical neighbours
    # share the same horizontal repeat-class but the random texture
    # varies enough that the depth shape doesn't read as a colour
    # block on its own.
    out = [[0] * grid_w for _ in range(grid_h)]
    for r in range(grid_h):
        row_pattern = _build_pattern_row(period, n_cols, (seed * 2654435761 + r) & 0xFFFFFFFF)
        # Walk left-to-right; the first `period` cells are the seed
        # texture, then each subsequent column copies from `c-period`
        # in the OUTPUT (so depth-shifted cells propagate forward),
        # adjusted by depth shift.
        for c in range(grid_w):
            if c < period:
                out[r][c] = row_pattern[c]
            else:
                d = _depth(shape, r, c, grid_w, grid_h, size, amp)
                src = c - period + d
                if src < 0:
                    src = 0
                if src >= grid_w:
                    src = grid_w - 1
                out[r][c] = out[r][src]
    return out
