"""Cornsweet edge illusion (hex variant).

Two large regions of identical mid-grey are separated by a narrow
"edge profile" — a thin band that ramps slightly darker on one side
and slightly brighter on the other.  Cover the edge with a finger
and the two regions clearly read as the same grey.  Uncover the
edge and the left region appears noticeably darker than the right,
even though only the edge pixels differ.

Described by Tom Cornsweet (1970) and earlier independently by Craik
and O'Brien.  A direct demonstration that the brain encodes
*edge contrast* and infers regional brightness from it.

Each hex is one solid colour from a 7-step grey palette; the edge
is drawn with 3 darker hexes and 3 brighter ones, all the rest of
the grid is the same middle grey.
"""

from . import Param

SLUG        = 'cornsweet'
NAME        = 'Cornsweet edge'
DESCRIPTION = ('Two regions of identical mid-grey appear lighter or '
                'darker because of a tiny brightness ramp at the '
                'boundary.  Cover the ramp and they look identical.')

# 7-step grey ramp.  Mid-grey = index 3.
PALETTE = ['#222222', '#555555', '#888888',
           '#aaaaaa',                     # index 3 — mid grey (regions)
           '#cccccc', '#eeeeee', '#ffffff']


PARAMS = [
    Param('orientation',  'edge orientation', 'choice',
                            'vertical', None, None, None,
                            ['vertical', 'horizontal'],
           help='Whether the edge runs up-down or left-right.'),
    Param('ramp_width',   'ramp half-width (hexes)', 'int', 3, 1, 6, 1,
           help='Each side of the edge gets this many hexes of ramp.'),
    Param('contrast',     'ramp contrast',       'int', 3, 1, 3, 1,
           help='How many palette steps the ramp reaches from mid-grey '
                '(max 3 = full dark/bright at the inner edge).'),
    Param('swap',         'swap dark/bright',    'choice',
                            'no', None, None, None, ['no', 'yes'],
           help='Flip which side reads bright vs dark.'),
]


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    orient   = str(params.get('orientation', 'vertical'))
    width    = max(1, int(params.get('ramp_width', 3)))
    contrast = max(1, min(3, int(params.get('contrast', 3))))
    swap     = str(params.get('swap', 'no')) == 'yes'

    MID = 3
    out = [[MID] * grid_w for _ in range(grid_h)]

    if orient == 'vertical':
        centre = grid_w // 2
        for r in range(grid_h):
            for c in range(grid_w):
                d = c - centre
                if -width <= d < 0:
                    # left side of edge: darker ramp at the inner edge
                    step = contrast - (width + d)   # closest = full
                    step = max(0, min(contrast, step))
                    idx = MID - step
                    out[r][c] = idx if not swap else (MID + step)
                elif 0 <= d < width:
                    step = contrast - d
                    step = max(0, min(contrast, step))
                    idx = MID + step
                    out[r][c] = idx if not swap else (MID - step)
    else:
        centre = grid_h // 2
        for r in range(grid_h):
            d = r - centre
            for c in range(grid_w):
                if -width <= d < 0:
                    step = contrast - (width + d)
                    step = max(0, min(contrast, step))
                    idx = MID - step
                    out[r][c] = idx if not swap else (MID + step)
                elif 0 <= d < width:
                    step = contrast - d
                    step = max(0, min(contrast, step))
                    idx = MID + step
                    out[r][c] = idx if not swap else (MID - step)
    return out
