"""White's illusion (hex variant).

Two equiluminant gray bars look notably different in lightness
depending on whether they sit BETWEEN black bars or BETWEEN white
bars — even though both gray bars are the exact same shade.

The classical version (Michael White, 1979) uses horizontal black/
white stripes with gray fragments embedded in some stripes; the gray
in the white stripes appears darker than the gray in the black
stripes.  Counter-intuitive because lateral inhibition predicts the
opposite — White's illusion is one of the canonical examples of
*assimilation* (where a colour gets pulled TOWARD its surround,
not away from it).

Hex variant: alternating dark/light hex rows ("stripes"); the two
gray test patches sit on different background rows.
"""
from . import Param

SLUG        = 'white_illusion'
NAME        = "White's illusion"
DESCRIPTION = ('Two equiluminant gray patches look like different '
                'shades depending on whether they sit on dark or '
                'bright background stripes.  A canonical example of '
                'assimilation, opposite of what lateral inhibition '
                'would predict.')

# 0 = black stripe, 1 = white stripe, 2 = the test gray (same shade
# in both patches; the illusion is purely perceptual).
PALETTE = ['#1a1a1a', '#f0f0f0', '#888888']

PARAMS = [
    Param('stripe_height', 'stripe height (rows)', 'int', 3, 1, 8, 1,
           help='How many hex rows make one dark or bright stripe.'),
    Param('patch_width',   'gray patch width', 'int', 4, 2, 12, 1,
           help='Width (in cells) of each gray test patch.'),
    Param('patch_height',  'gray patch height (in stripes)', 'int', 1, 1, 3, 1,
           help='How many stripes tall each gray patch is.'),
    Param('separation',    'patch separation (cells)', 'int', 6, 2, 20, 1,
           help='Horizontal gap between the two gray patches.'),
]


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    sh = max(1, int(params.get('stripe_height', 3)))
    pw = max(2, int(params.get('patch_width',   4)))
    ph = max(1, int(params.get('patch_height',  1)))
    sep = max(2, int(params.get('separation',   6)))

    out = [[0] * grid_w for _ in range(grid_h)]
    # Background: alternating stripes by row.
    for r in range(grid_h):
        stripe_idx = r // sh
        bg = 0 if (stripe_idx & 1) == 0 else 1   # 0 = dark, 1 = bright
        for c in range(grid_w):
            out[r][c] = bg

    # Centre the two patches horizontally.
    cx = grid_w // 2
    left_c0  = cx - sep // 2 - pw
    right_c0 = cx + sep // 2

    # Place each patch on a *different* stripe colour so the illusion
    # has both conditions side-by-side. Find the first dark stripe and
    # the first bright stripe near the vertical centre.
    centre_row = grid_h // 2
    stripe_at_centre = (centre_row // sh) & 1
    # Left patch sits on the centre stripe; right patch sits on the
    # next stripe (opposite background colour).
    left_r0  = (centre_row // sh) * sh
    right_r0 = left_r0 + sh         # next stripe
    if right_r0 + sh * ph > grid_h:
        right_r0 = max(0, left_r0 - sh * ph)

    def _place(r0, c0):
        for dr in range(sh * ph):
            for dc in range(pw):
                r = r0 + dr; c = c0 + dc
                if 0 <= r < grid_h and 0 <= c < grid_w:
                    out[r][c] = 2
    _place(left_r0,  max(0, left_c0))
    _place(right_r0, min(grid_w - pw, right_c0))
    return out
