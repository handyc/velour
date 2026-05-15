"""Zöllner illusion (hex variant).

Long horizontal lines decorated with short oblique tick marks at
regular intervals.  The lines are exactly parallel, but the eye
reads them as converging or diverging because adjacent rows have
their tick-marks angled in opposite directions.

Johann Zöllner, 1860.

Hex implementation: every `row_spacing` hex rows we draw a long
horizontal line.  Along each line, every `tick_spacing` columns we
stamp a short diagonal tick.  Tick angle alternates row by row.
"""

from . import Param

SLUG        = 'zollner'
NAME        = 'Zöllner'
DESCRIPTION = ('Parallel horizontal lines decorated with short oblique '
                'tick marks angled in alternating directions.  The '
                'lines look fan-shaped — convergent or divergent — '
                'even though every line is geometrically parallel.')

PALETTE = ['#ffffff', '#000000']           # 0=bg, 1=line


PARAMS = [
    Param('row_spacing',  'row spacing (hexes)',     'int', 6, 3, 20, 1,
           help='Vertical distance between successive parallel lines.'),
    Param('tick_spacing', 'tick spacing (hexes)',    'int', 3, 2, 12, 1,
           help='Horizontal distance between successive ticks on a line.'),
    Param('tick_length',  'tick length (hexes)',     'int', 2, 1,  8, 1,
           help='Half-length of each tick (extends ± from the line).'),
    Param('tick_run',     'tick run (cells per rise)','int', 1, 1,  4, 1,
           help='How shallow the tick angle is.  1 = 45°; 2 = ~27°; '
                '3 = ~18°.'),
    Param('line_thickness','line thickness (hexes)', 'int', 1, 1,  3, 1,
           help='Stroke width of the long horizontal lines.'),
]


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    rs    = max(2, int(params.get('row_spacing',     6)))
    ts    = max(1, int(params.get('tick_spacing',    3)))
    tl    = max(1, int(params.get('tick_length',     2)))
    trun  = max(1, int(params.get('tick_run',        1)))
    thick = max(1, int(params.get('line_thickness',  1)))
    half_t = thick // 2

    out = [[0] * grid_w for _ in range(grid_h)]

    line_idx = 0
    for r0 in range(rs // 2, grid_h, rs):
        # the long horizontal line
        for r in range(max(0, r0 - half_t), min(grid_h, r0 + half_t + 1)):
            for c in range(grid_w):
                out[r][c] = 1
        # tick direction alternates per line
        slope = 1 if (line_idx % 2 == 0) else -1
        for c0 in range(ts // 2, grid_w, ts):
            # stamp ticks above and below, at a (1, trun)-ish slope
            for d in range(-tl, tl + 1):
                if d == 0: continue
                # walk d cells outward in y, |d|/trun cells in x
                rr = r0 + d
                cc = c0 + slope * (d // max(1, trun))
                if 0 <= rr < grid_h and 0 <= cc < grid_w:
                    out[rr][cc] = 1
        line_idx += 1
    return out
