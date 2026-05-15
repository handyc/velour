"""Kanizsa triangle (illusory contours).

Three "Pac-Man" discs are arranged at the vertices of an invisible
equilateral triangle, each with its missing wedge facing inward.
The visual system fills in an illusory bright triangle in the middle
— complete with sharp edges, even though no edges are drawn.

Gaetano Kanizsa, 1955.

Hex variant: cells inside any disc are dark; cells inside that disc's
inward-facing wedge revert to background.  The "edges" of the
illusory triangle are perceived between the wedge tips.
"""

import math
from . import Param

SLUG        = 'kanizsa-triangle'
NAME        = 'Kanizsa triangle'
DESCRIPTION = ('Three notched dark discs evoke an illusory bright '
                'triangle floating above a blank background.  The '
                'triangle has no edges drawn — your visual cortex '
                'completes them between the notches.')

PALETTE = ['#ffffff', '#000000']               # 0=bg, 1=disc


PARAMS = [
    Param('disc_radius',    'disc radius (hexes)',     'int',  6,  2, 30, 1,
           help='Radius of each Pac-Man disc.'),
    Param('triangle_radius','triangle radius (hexes)', 'int', 14,  4, 60, 1,
           help='Distance from page centre to each vertex (controls '
                'how big the implied triangle is).'),
    Param('wedge_angle',    'wedge angle (degrees)',   'int', 60,  20,180, 5,
           help='Opening angle of the missing-wedge.  60° is the '
                'classic Kanizsa setting.'),
    Param('orientation',    'orientation',             'choice',
                            'point-up', None, None, None,
                            ['point-up', 'point-down'],
           help='Which way the implied triangle points.'),
]


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    disc_r  = max(1, int(params.get('disc_radius',     6)))
    tri_r   = max(disc_r + 1, int(params.get('triangle_radius', 14)))
    wedge_d = max(5,  int(params.get('wedge_angle',    60)))
    orient  = str(params.get('orientation', 'point-up'))

    cx, cy = grid_w / 2.0, grid_h / 2.0
    base = -math.pi / 2.0 if orient == 'point-up' else math.pi / 2.0
    # 3 vertex angles around the page-centre
    vertex_angles = [base + 2.0 * math.pi * i / 3.0 for i in range(3)]
    vertices = [(cx + tri_r * math.cos(a), cy + tri_r * math.sin(a))
                for a in vertex_angles]
    # Each disc's wedge faces the centre (so the triangle interior is
    # the illusory side).
    wedge_face = [math.atan2(cy - vy, cx - vx) for (vx, vy) in vertices]
    half_wedge = math.radians(wedge_d) / 2.0

    out = [[0] * grid_w for _ in range(grid_h)]
    for r in range(grid_h):
        for c in range(grid_w):
            for (vx, vy), face in zip(vertices, wedge_face):
                dx, dy = c - vx, r - vy
                if dx * dx + dy * dy > disc_r * disc_r:
                    continue
                # inside this disc; check wedge
                ang = math.atan2(dy, dx)
                d = abs(ang - face)
                if d > math.pi: d = 2.0 * math.pi - d
                if d < half_wedge:
                    continue   # in the wedge → leave background
                out[r][c] = 1
                break
    return out
