"""Müller-Lyer illusion (hex variant).

Two horizontal segments of identical length, each ending in a pair
of "fins":

    >─────<      (fins point inward — line looks shorter)
    <─────>      (fins point outward — line looks longer)

Franz Carl Müller-Lyer, 1889.

In the hex variant each fin is rendered as a short diagonal hex
trail at the line endpoint, angled inward or outward depending on
the configuration.
"""

from . import Param

SLUG        = 'muller-lyer'
NAME        = 'Müller-Lyer'
DESCRIPTION = ('Two horizontal segments of identical length: the top '
                'one with fins pointing outward, the bottom with fins '
                'pointing inward.  The outward-fin segment looks '
                'noticeably longer.  Same length.  Measure if you doubt.')

PALETTE = ['#ffffff', '#000000']           # 0=bg, 1=line


PARAMS = [
    Param('line_length',      'line length (hexes)',   'int', 18,  6, 60, 1,
           help='Length of each horizontal segment in cells.'),
    Param('fin_length',       'fin length (hexes)',    'int',  4,  1, 16, 1,
           help='Length of each diagonal fin.'),
    Param('line_thickness',   'line thickness (hexes)', 'int', 1,  1,  3, 1,
           help='Stroke width of the line and fins.'),
    Param('vertical_separation', 'vertical separation (hexes)',
                              'int', 8, 2, 30, 1,
           help='Distance between the two segments.'),
]


def _stamp_segment(out, x0, y0, x1, y1, thick, gw, gh):
    """Rasterise a thick line segment into the grid via DDA."""
    half_t = thick / 2.0
    dx, dy = x1 - x0, y1 - y0
    steps = max(1, int(max(abs(dx), abs(dy)) * 2))
    for i in range(steps + 1):
        t = i / steps
        x = x0 + t * dx
        y = y0 + t * dy
        # mark a small disc of `thick` cells around (x, y)
        ri = int(round(y))
        ci = int(round(x))
        for dr in range(-int(half_t), int(half_t) + 1):
            for dc in range(-int(half_t), int(half_t) + 1):
                rr = ri + dr
                cc = ci + dc
                if 0 <= rr < gh and 0 <= cc < gw:
                    out[rr][cc] = 1


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    L     = max(2, int(params.get('line_length',         18)))
    F     = max(1, int(params.get('fin_length',           4)))
    thick = max(1, int(params.get('line_thickness',       1)))
    sep   = max(2, int(params.get('vertical_separation',  8)))

    cx = grid_w / 2.0
    y_top = max(1.0, grid_h / 2.0 - sep / 2.0)
    y_bot = min(grid_h - 2.0, grid_h / 2.0 + sep / 2.0)

    out = [[0] * grid_w for _ in range(grid_h)]

    # Top segment — fins point OUTWARD (looks longer)
    x0, x1 = cx - L / 2.0, cx + L / 2.0
    _stamp_segment(out, x0, y_top, x1, y_top, thick, grid_w, grid_h)
    # outward fins on left endpoint
    _stamp_segment(out, x0, y_top, x0 - F, y_top - F, thick, grid_w, grid_h)
    _stamp_segment(out, x0, y_top, x0 - F, y_top + F, thick, grid_w, grid_h)
    # outward fins on right endpoint
    _stamp_segment(out, x1, y_top, x1 + F, y_top - F, thick, grid_w, grid_h)
    _stamp_segment(out, x1, y_top, x1 + F, y_top + F, thick, grid_w, grid_h)

    # Bottom segment — fins point INWARD (looks shorter)
    _stamp_segment(out, x0, y_bot, x1, y_bot, thick, grid_w, grid_h)
    _stamp_segment(out, x0, y_bot, x0 + F, y_bot - F, thick, grid_w, grid_h)
    _stamp_segment(out, x0, y_bot, x0 + F, y_bot + F, thick, grid_w, grid_h)
    _stamp_segment(out, x1, y_bot, x1 - F, y_bot - F, thick, grid_w, grid_h)
    _stamp_segment(out, x1, y_bot, x1 - F, y_bot + F, thick, grid_w, grid_h)

    return out
