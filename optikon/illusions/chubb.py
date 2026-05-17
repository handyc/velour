"""Chubb contrast-illusion (hex variant).

The same medium-saturation patch surrounded by a *high-contrast*
texture appears noticeably less saturated than the identical patch
surrounded by a *low-contrast* texture.  Discovered by Chubb,
Sperling & Solomon (1989) as a direct counter to the simpler
"brightness contrast" model — the visual system normalises locally
by the *variance* of nearby cells, not just by their mean.

We render two square patches of identical mid-saturation pink on
two backgrounds: left = high-contrast checker (black/white), right
= low-contrast checker (grey-A / grey-B).  The left pink reads as
washed out, the right pink looks vivid — same hex colour both times.

Each hex carries one solid colour.
"""

from . import Param

SLUG        = 'chubb'
NAME        = 'Chubb contrast'
DESCRIPTION = ('A medium-pink patch on high-contrast black/white '
                'checker reads washed-out; the identical patch on a '
                'low-contrast grey/grey checker reads vivid.  Same '
                'pink in both — the surround texture variance does it.')

# 0 = pink target, 1 = black, 2 = white, 3 = grey-A, 4 = grey-B
PALETTE = ['#d97ca8', '#000000', '#ffffff', '#9a9a9a', '#b8b8b8']


PARAMS = [
    Param('checker',     'checker cell (hexes)', 'int', 2, 1, 5, 1,
           help='Side length of one checker square in hexes.'),
    Param('patch_size',  'patch half-width',     'int', 4, 2, 9, 1,
           help='Half-size of the central pink patch on each side.'),
    Param('split_gap',   'gap between sides',    'int', 2, 0, 8, 1,
           help='How many hex columns of blank between the two halves.'),
]


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    ck   = max(1, int(params.get('checker',     2)))
    half = max(2, int(params.get('patch_size',  4)))
    gap  = max(0, int(params.get('split_gap',   2)))

    PINK, BLACK, WHITE, GA, GB = 0, 1, 2, 3, 4
    out = [[WHITE] * grid_w for _ in range(grid_h)]

    mid = grid_w // 2
    left_end   = mid - gap // 2
    right_start = mid + (gap - gap // 2)

    for r in range(grid_h):
        for c in range(grid_w):
            cell_parity = ((r // ck) + (c // ck)) & 1
            if c < left_end:
                out[r][c] = BLACK if cell_parity == 0 else WHITE
            elif c >= right_start:
                out[r][c] = GA if cell_parity == 0 else GB

    # Two pink patches, one centred in each side
    cr = grid_h // 2
    for side_centre in (left_end // 2, right_start + (grid_w - right_start) // 2):
        for r in range(cr - half, cr + half + 1):
            for c in range(side_centre - half, side_centre + half + 1):
                if 0 <= r < grid_h and 0 <= c < grid_w:
                    out[r][c] = PINK
    return out
