"""Neon colour spreading (hex variant).

A grid of black lines crosses a region where the *intersections*
(or short segments) have been replaced by a saturated colour.  The
viewer perceives a soft glowing disc of that colour spreading out
between the line crossings, as though a neon tube were behind the
grid — even though every hex outside the coloured cells is pure
white.

Reported by van Tuijl (1975) and Varin (1971).  Like the watercolour
effect, the "filling-in" is a property of the visual cortex.  The
effect is killed by breaking the line continuity or by removing the
black grid.

Each hex carries one solid colour.
"""

from . import Param

SLUG        = 'neon-spreading'
NAME        = 'Neon spreading'
DESCRIPTION = ('Black grid lines with coloured short segments at the '
                'crossings appear to glow with a soft colour wash '
                'around each junction — even though only the junction '
                'hexes are coloured.')

PALETTE = ['#ffffff', '#0a0a0a', '#3398ff', '#ff5577']


PARAMS = [
    Param('spacing',    'grid spacing (hexes)',  'int', 6, 4, 14, 1,
           help='Distance between consecutive lines of the black grid.'),
    Param('line_thick', 'line thickness',         'int', 1, 1,  3, 1,
           help='Hex thickness of the black grid lines.'),
    Param('junction',   'junction half-width',    'int', 1, 1,  3, 1,
           help='Hex half-width of the coloured neon junction patch.'),
    Param('color_mode', 'colour scheme',          'choice',
                          'alternate', None, None, None,
                          ['blue', 'pink', 'alternate'],
           help='Use blue, pink, or alternate the two colours by '
                'junction parity.'),
]


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    sp      = max(3, int(params.get('spacing', 6)))
    thick   = max(1, int(params.get('line_thick', 1)))
    jhw     = max(1, int(params.get('junction', 1)))
    mode    = str(params.get('color_mode', 'alternate'))
    WHITE, BLACK, BLUE, PINK = 0, 1, 2, 3

    out = [[WHITE] * grid_w for _ in range(grid_h)]

    # First: draw the black grid lines.
    for r in range(grid_h):
        for c in range(grid_w):
            on_h = (r % sp) < thick
            on_v = (c % sp) < thick
            if on_h or on_v:
                out[r][c] = BLACK

    # Second: paint the coloured junctions over the crossings.
    for jr in range(0, grid_h, sp):
        for jc in range(0, grid_w, sp):
            # alternate colour by junction parity
            parity = ((jr // sp) + (jc // sp)) & 1
            if mode == 'blue':
                col = BLUE
            elif mode == 'pink':
                col = PINK
            else:
                col = BLUE if parity == 0 else PINK
            for dr in range(-jhw, jhw + 1):
                for dc in range(-jhw, jhw + 1):
                    rr = jr + dr
                    cc = jc + dc
                    if 0 <= rr < grid_h and 0 <= cc < grid_w:
                        out[rr][cc] = col
    return out
