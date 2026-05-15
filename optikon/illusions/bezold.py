"""Bezold effect (hex variant).

The same accent colour reads as a different shade depending on the
brightness of the surround.  Top half of the page: accent hexes
distributed through black background → the accent reads as a deep
maroon-like tone (cool / dark).  Bottom half: same accent hexes on
white background → the accent reads brighter and warmer (light /
saturated).

Wilhelm von Bezold described it in his 1874 colour treatise, in the
context of textile pattern design.

Each hex still carries exactly one solid colour from the palette;
the perceptual shift is entirely in the viewer's visual cortex.
"""

from . import Param

SLUG        = 'bezold'
NAME        = 'Bezold'
DESCRIPTION = ('Same accent-colour hexes appear warmer or cooler '
                'depending on whether they sit on a dark or bright '
                'background.  The top half is dark; the bottom half '
                'is bright.  Same accent in both.')

PALETTE = ['#000000', '#ffffff', '#cc4422']   # 0=dark, 1=bright, 2=accent


PARAMS = [
    Param('split_axis',     'split axis',  'choice',
                            'horizontal', None, None, None,
                            ['horizontal', 'vertical'],
           help='Where to place the dark/bright divider.'),
    Param('accent_density', 'accent every Nth cell', 'int', 3, 2, 8, 1,
           help='Smaller = denser accent pattern; larger = sparser.'),
    Param('accent_pattern', 'accent placement pattern', 'choice',
                            'columns', None, None, None,
                            ['columns', 'diamonds', 'random'],
           help='Where the accent hexes go: every Nth column, a '
                'staggered diamond grid, or a deterministic random '
                'sprinkle.'),
    Param('accent_seed',    'accent rng seed', 'int', 7, 0, 1<<30, 1,
           help='Only used when accent_pattern = random.'),
]


def _rng_step(state: int) -> tuple[int, int]:
    state = (state * 1103515245 + 12345) & 0xFFFFFFFF
    return state, state >> 16


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    axis    = str(params.get('split_axis', 'horizontal'))
    dens    = max(2, int(params.get('accent_density', 3)))
    pattern = str(params.get('accent_pattern', 'columns'))
    seed    = int(params.get('accent_seed', 7)) & 0xFFFFFFFF

    out = [[0] * grid_w for _ in range(grid_h)]
    half_h = grid_h // 2
    half_w = grid_w // 2

    for r in range(grid_h):
        for c in range(grid_w):
            if axis == 'horizontal':
                bg = 0 if r < half_h else 1
            else:
                bg = 0 if c < half_w else 1
            if   pattern == 'columns':  is_acc = (c % dens == 0)
            elif pattern == 'diamonds': is_acc = ((r + c) % dens == 0)
            else:                        # random
                state = (seed + r * 73856093 + c * 19349663) & 0xFFFFFFFF
                _, v = _rng_step(state)
                is_acc = (v % dens == 0)
            out[r][c] = 2 if is_acc else bg
    return out
