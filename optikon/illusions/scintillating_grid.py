"""Scintillating grid illusion (Schrauf, Lingelbach & Wist, 1997).

Hermann grid plus white discs at every band intersection.  The discs
make the phantom dark spots flicker in and out as you scan the page —
a much sharper effect than the plain Hermann grid produces.

In the hex variant, the "discs" are just the single hex cell at each
intersection drawn in white (the band cells stay grey).  The eye
fills in flickering black dots that vanish whenever you look
directly at one.
"""

from . import Param

SLUG        = 'scintillating-grid'
NAME        = 'Scintillating grid'
DESCRIPTION = ('Hermann grid with white discs at every intersection.  '
                'Look slightly off-axis — the dark dots flicker in and '
                'out at every intersection in your peripheral vision.')

PALETTE = ['#000000', '#888888', '#ffffff']    # 0=bg, 1=band-grey, 2=white-disc


PARAMS = [
    Param('band_spacing', 'band spacing (hexes)',  'int', 5,  3, 24, 1,
           help='Distance between successive bands along each axis.'),
    Param('band_width',   'band width (hexes)',    'int', 1,  1,  4, 1,
           help='Thickness of each grey band.'),
    Param('disc_size',    'disc radius (hexes)',   'int', 1,  1,  3, 1,
           help='How wide each white intersection disc is.  1 = single cell.'),
]


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    spacing = max(2, int(params.get('band_spacing', 5)))
    width   = max(1, int(params.get('band_width',   1)))
    disc_r  = max(1, int(params.get('disc_size',    1)))

    out = [[0] * grid_w for _ in range(grid_h)]
    for r in range(grid_h):
        in_row_band = (r % spacing) < width
        for c in range(grid_w):
            in_col_band = (c % spacing) < width
            if in_row_band and in_col_band:
                # we'll mark intersection centres below
                out[r][c] = 1
            elif in_row_band or in_col_band:
                out[r][c] = 1
            # else: stay 0 (background)

    # Place white discs at intersection centres.
    for ir in range(0, grid_h, spacing):
        for ic in range(0, grid_w, spacing):
            for dr in range(-disc_r + 1, disc_r):
                for dc in range(-disc_r + 1, disc_r):
                    rr = ir + dr
                    cc = ic + dc
                    if 0 <= rr < grid_h and 0 <= cc < grid_w:
                        if abs(dr) + abs(dc) < disc_r:
                            out[rr][cc] = 2
    return out
