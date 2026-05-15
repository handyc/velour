"""Café-wall illusion (hex variant).

Rows of alternating black/white hex bands separated by a thin
"mortar" row of medium grey.  Adjacent black-white bands are offset
horizontally by `shift` hexes; the mortar between sloped bands then
appears tilted even though every row is geometrically straight.

The classic Café-wall on the Wall of the Café in Bristol used
brick-shaped tiles with thin grout; the hex analogue uses single
hexes for the bricks and a single mortar row.

Output is one palette index per hex.
"""

from . import Param

SLUG        = 'cafe-wall'
NAME        = 'Café-wall'
DESCRIPTION = ('Alternating black/white hex bands offset between '
                'rows, separated by a thin mortar row of mid-grey. '
                'Geometrically straight band edges appear sloped.')

PALETTE = ['#000000', '#ffffff', '#888888']     # 0=black 1=white 2=mortar

PARAMS = [
    Param('band_height',  'band height (hex rows)',  'int',   2,  1, 8, 1,
           help='How tall each black/white band is, in hex rows.'),
    Param('mortar_height','mortar height (hex rows)','int',   1,  0, 4, 1,
           help='Thickness of the mid-grey mortar between bands.'),
    Param('brick_width',  'brick width (hexes)',     'int',   3,  1, 12, 1,
           help='Length of each black or white run inside a band.'),
    Param('shift',        'inter-band shift',         'int',   1, -8, 8, 1,
           help='Horizontal offset between consecutive bands. '
                '0 = aligned (no illusion); 1-2 = strong slope.'),
]


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    bh = max(1, int(params.get('band_height',  2)))
    mh = max(0, int(params.get('mortar_height',1)))
    bw = max(1, int(params.get('brick_width',  3)))
    sh = int(params.get('shift', 1))
    cycle = bh + mh
    out = [[0] * grid_w for _ in range(grid_h)]
    for r in range(grid_h):
        in_band  = (r % cycle) < bh
        if not in_band:
            for c in range(grid_w): out[r][c] = 2     # mortar
            continue
        # Which "stripe of bands" are we in (0,1,2,3,...)
        band_idx = r // cycle
        # Offset by shift × band_idx, modulo (2 × brick_width) so
        # adjacent bands flip phase and the eye reads the slope.
        period   = 2 * bw
        offset   = (band_idx * sh) % period
        for c in range(grid_w):
            phase = ((c + offset) // bw) & 1
            out[r][c] = phase    # 0=black 1=white
    return out
