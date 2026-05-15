"""Munker-White illusion (hex variant).

Vertical "bars" of uniform grey overlap horizontal stripes of
alternating black and white.  Half the bars are configured to
*continue* the dark stripes and *interrupt* the bright stripes
(grey replaces bright); the other half do the opposite (grey
replaces dark).  Same grey on both sides, but the eye reads them as
distinctly different luminances — Bar A's grey looks lighter, Bar
B's grey looks darker.

Documented by Hans Munker in the 1970s and reformulated by Michael
White in 1979.  Famously robust: even when you know how it works,
the shift doesn't go away.

Each hex is one solid colour.  No subpixel cleverness needed.
"""

from . import Param

SLUG        = 'munker-white'
NAME        = 'Munker-White'
DESCRIPTION = ('Identical grey hex bars look light or dark depending '
                'on whether they interrupt the bright or the dark '
                'stripes they cross.  Look at any two grey bars and '
                'compare; they are the same hue.')

PALETTE = ['#888888', '#000000', '#ffffff']     # 0=grey, 1=dark, 2=bright


PARAMS = [
    Param('band_height',     'stripe height (hex rows)', 'int', 2, 1,  6, 1,
           help='Height of each black or white horizontal stripe.'),
    Param('column_spacing',  'bar spacing (hexes)',      'int', 5, 3, 16, 1,
           help='Distance between consecutive grey bars.'),
    Param('column_width',    'bar width (hexes)',         'int', 2, 1,  6, 1,
           help='Thickness of each grey bar.'),
]


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    bh    = max(1, int(params.get('band_height',     2)))
    cspac = max(2, int(params.get('column_spacing',  5)))
    cwid  = max(1, int(params.get('column_width',    2)))
    GRAY, DARK, BRIGHT = 0, 1, 2

    out = [[0] * grid_w for _ in range(grid_h)]
    for r in range(grid_h):
        is_dark_row = (r // bh) % 2 == 0
        for c in range(grid_w):
            in_bar = (c % cspac) < cwid
            if not in_bar:
                out[r][c] = DARK if is_dark_row else BRIGHT
                continue
            bar_kind = (c // cspac) % 2
            if bar_kind == 0:
                # Bar A: continues dark stripes, interrupts bright with grey
                out[r][c] = DARK if is_dark_row else GRAY
            else:
                # Bar B: continues bright stripes, interrupts dark with grey
                out[r][c] = GRAY if is_dark_row else BRIGHT
    return out
