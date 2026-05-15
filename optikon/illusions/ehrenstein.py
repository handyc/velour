"""Ehrenstein illusion (hex variant).

Dark spokes radiate outward from a centre point, stopping short of
it.  The empty centre reads as a bright disc — even though it's the
same background color as the rest of the page.  The eye fills in an
illusory edge along the inner radius where the spokes terminate.

Walter Ehrenstein, 1941.

Spoke thickness is computed in radians at the cell's distance from
the centre, so spokes look uniformly thick at any radius rather than
flaring outward like wedges.
"""

import math
from . import Param

SLUG        = 'ehrenstein'
NAME        = 'Ehrenstein'
DESCRIPTION = ('Radial dark spokes around a clear centre create an '
                'illusory bright disc at the gap.  Look at the centre '
                'and a faint round contour appears.')

PALETTE = ['#ffffff', '#000000']     # 0=bg, 1=spoke


PARAMS = [
    Param('n_spokes',        'number of spokes',     'int',  16, 4, 48, 2,
           help='How many radial spokes around the centre.'),
    Param('inner_radius',    'inner gap (hexes)',    'int',   5, 1, 30, 1,
           help='Radius of the empty centre — the apparent disc.'),
    Param('outer_radius',    'spoke length (hexes)', 'int',  20, 3, 60, 1,
           help='How far the spokes extend before they end.'),
    Param('spoke_thickness', 'spoke thickness (hexes)', 'int', 1, 1, 5, 1,
           help='Stroke width measured in hex cells at the spoke base.'),
]


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    n_sp  = max(2, int(params.get('n_spokes',        16)))
    r_in  = max(1, int(params.get('inner_radius',     5)))
    r_out = max(r_in + 1, int(params.get('outer_radius', 20)))
    thick = max(1, int(params.get('spoke_thickness',  1)))

    cx, cy = grid_w / 2.0, grid_h / 2.0
    spoke_angles = [2.0 * math.pi * i / n_sp for i in range(n_sp)]

    out = [[0] * grid_w for _ in range(grid_h)]
    for r in range(grid_h):
        for c in range(grid_w):
            dx, dy = c - cx, r - cy
            d2 = dx * dx + dy * dy
            if d2 < r_in * r_in:  continue   # inside the gap
            if d2 > r_out * r_out: continue   # past the spoke ends
            radial = math.sqrt(d2)
            ang = math.atan2(dy, dx)
            # find min angular distance to any spoke
            best = math.pi
            for sa in spoke_angles:
                d = abs(ang - sa)
                if d > math.pi: d = 2.0 * math.pi - d
                if d < best: best = d
            # convert thickness in hexes to angular tolerance at this radius;
            # thickness "1" corresponds to ~one cell-width across the spoke.
            tol = thick / max(1.0, radial)
            if best < tol:
                out[r][c] = 1
    return out
