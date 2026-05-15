"""Poggendorff illusion (hex variant).

A straight diagonal line passes behind a wide vertical band.  The
two visible halves of the line are colinear, but the eye reads them
as offset — one half appears lower than the other.  Discovered by
Johann Poggendorff in 1860 while editing a paper of Zöllner's.

Hex variant: each cell is one of {background, line, band}.  The
line is rasterised as the hex cells whose row-coordinate falls
within ±line_thickness/2 of the slope-row at that column.
"""

from . import Param

SLUG        = 'poggendorff'
NAME        = 'Poggendorff'
DESCRIPTION = ('A diagonal line passes behind a vertical band.  The '
                'two halves are colinear but appear offset.')

PALETTE = ['#ffffff', '#000000', '#cccccc']    # 0=bg, 1=line, 2=band


PARAMS = [
    Param('band_width',      'band width (hexes)',      'int', 8,  3, 30, 1,
           help='Width of the vertical band that hides the middle of the line.'),
    Param('line_slope',      'line slope (rise/run × 100)', 'int', 60,
                              10, 200, 5,
           help='Diagonal steepness as a percentage.  60 = ~31°.'),
    Param('line_thickness',  'line thickness (hexes)',   'int', 1,  1,  4, 1,
           help='Stroke width of the diagonal in hex cells.'),
]


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    bw    = max(1, int(params.get('band_width',     8)))
    slope = int(params.get('line_slope',           60)) / 100.0
    thick = max(1, int(params.get('line_thickness', 1)))

    band_x_lo = grid_w // 2 - bw // 2
    band_x_hi = band_x_lo + bw
    cy = grid_h / 2.0
    cx = grid_w / 2.0
    half_t = thick / 2.0

    out = [[0] * grid_w for _ in range(grid_h)]
    for c in range(grid_w):
        if band_x_lo <= c < band_x_hi:
            for r in range(grid_h): out[r][c] = 2
            continue
        # Where the geometric line crosses this column
        line_y = cy + slope * (c - cx)
        for r in range(grid_h):
            if abs(r - line_y) < half_t:
                out[r][c] = 1
    return out
