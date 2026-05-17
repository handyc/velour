"""Watercolour illusion (hex variant).

A closed region outlined by two thin contours — one darker, one a
saturated light tint — appears to be *filled* with a faint wash of
the light tint, even though the interior cells are pure white.  The
filling is entirely perceptual; remove the inner saturated contour
and the wash disappears.

Described by Pinna, Brelstaff & Spillmann (2001).  The effect is
strongest when the dark contour sits *outside* and the saturated
tint sits *immediately inside*; switching the order kills it.

Each hex is one solid colour from the palette.
"""

from . import Param

SLUG        = 'watercolor'
NAME        = 'Watercolour'
DESCRIPTION = ('White hex regions bounded by a dark contour + an '
                'inner saturated tint appear gently washed with that '
                'tint.  Swap the contour order and the wash vanishes.')

# 0 = white background, 1 = dark contour, 2 = orange tint,
# 3 = teal tint  (two regions, two tints — the eye fills both)
PALETTE = ['#ffffff', '#1a1a1a', '#ff9966', '#66ccaa']


PARAMS = [
    Param('region_size',  'region radius (hexes)', 'int', 6, 3, 14, 1,
           help='Half-size of each closed region.'),
    Param('gap',          'gap between regions',   'int', 4, 2,  8, 1,
           help='Hex columns/rows of background between regions.'),
    Param('swap_order',   'swap contour order',    'choice',
                            'no', None, None, None, ['no', 'yes'],
           help='Put the saturated tint outside and dark inside — '
                'the illusion should disappear.'),
]


def _is_on_ring(r: int, c: int, cr: int, cc: int, radius: int) -> int:
    """Return Chebyshev-style ring distance from (cr, cc).
    0 = centre, 1 = first ring out, etc.  -1 if outside the box."""
    dr = abs(r - cr)
    dc = abs(c - cc)
    d = max(dr, dc)
    return d if d <= radius else -1


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    radius = max(2, int(params.get('region_size', 6)))
    gap    = max(1, int(params.get('gap',         4)))
    swap   = str(params.get('swap_order', 'no')) == 'yes'

    WHITE, DARK, T1, T2 = 0, 1, 2, 3
    out = [[WHITE] * grid_w for _ in range(grid_h)]

    period = 2 * radius + gap + 1
    for region_r in range(radius + 1, grid_h, period):
        for region_c in range(radius + 1, grid_w, period):
            # alternate the two tints by region parity so the page
            # shows both fills side-by-side
            parity = ((region_r // period) + (region_c // period)) & 1
            tint = T1 if parity == 0 else T2
            for r in range(grid_h):
                for c in range(grid_w):
                    d = _is_on_ring(r, c, region_r, region_c, radius)
                    if d < 0: continue
                    if d == radius:
                        out[r][c] = tint if swap else DARK
                    elif d == radius - 1:
                        out[r][c] = DARK if swap else tint
    return out
