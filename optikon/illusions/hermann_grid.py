"""Hermann grid (hex variant).

Bright hex bands cross both axes on a dark background, leaving
square-ish dark "rooms" between them.  Look slightly off-center and
phantom dark spots flicker at the band intersections.

Discovered by Ludimar Hermann (1870) for square grids; the same
phenomenon survives the topology change to hex.

Single colour per hex; no analog band lighting required.
"""

from . import Param

SLUG        = 'hermann-grid'
NAME        = 'Hermann grid'
DESCRIPTION = ('Bright hex bands intersecting on a dark background. '
                'Phantom dark spots appear at the intersections in '
                'peripheral vision.')

PALETTE = ['#ffffff', '#000000']     # 0=bright, 1=dark


PARAMS = [
    Param('band_spacing', 'band spacing (hexes)', 'int', 5,  3, 24, 1,
           help='Distance between successive bands along each axis.'),
    Param('band_width',   'band width (hexes)',    'int', 1,  1,  6, 1,
           help='Thickness of each bright band.'),
    Param('invert',       'invert (dark on bright)', 'choice',
                          'no', None, None, None, ['no','yes'],
           help='Swap fg/bg.  Some find dark-on-bright produces '
                'sharper phantoms.'),
]


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    spacing = max(2, int(params.get('band_spacing', 5)))
    width   = max(1, int(params.get('band_width',   1)))
    invert  = (params.get('invert', 'no') == 'yes')
    bright_idx, dark_idx = (1, 0) if invert else (0, 1)
    out = [[dark_idx] * grid_w for _ in range(grid_h)]
    for r in range(grid_h):
        in_row_band = (r % spacing) < width
        for c in range(grid_w):
            in_col_band = (c % spacing) < width
            if in_row_band or in_col_band:
                out[r][c] = bright_idx
    return out
