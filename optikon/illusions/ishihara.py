"""Ishihara plate (hex variant) — colour-blindness test.

Standard Ishihara plates show a number formed by dots of one colour
embedded in a field of dots in a confusable colour.  Viewers with
typical colour vision read the number; viewers with red-green colour
deficiency see a uniform field (or a different number, on certain
"transformation" plates).

Hex variant: each cell of the hex grid is one dot.  ``digit`` (0-9)
selects which numeral to embed; ``palette_pair`` picks one of three
classic confusion-line palettes:

  * red-green  — the classic "protan / deutan" pair (red dots inside
                  a field of green dots; both look brownish to a
                  red-green colour-blind viewer).
  * blue-yellow — the rarer tritan deficiency test.
  * grayscale  — high-contrast control (everyone sees this).

Use the playground's "?palette_pair=red-green" knob to switch.
"""
from . import Param

SLUG        = 'ishihara'
NAME        = 'Ishihara plate'
DESCRIPTION = ('Number embedded in dots — visible to typical colour '
                'vision, hidden to colour-blind viewers depending on '
                'which confusion-line palette is selected.')

# Three palettes — index 0 = background, index 1 = digit, index 2 =
# accent (used for some bitmap-anti-aliasing effects). The first two
# are the classic confusion pairs from the original plates.
PALETTES = {
    'red-green':   ['#7c8b3a', '#a96342', '#c2a35c'],
    'blue-yellow': ['#5e72a8', '#a59c4d', '#7c8caa'],
    'grayscale':   ['#888888', '#222222', '#bbbbbb'],
}

PALETTE = PALETTES['red-green']   # default; chat_view picks per request

PARAMS = [
    Param('digit',         'digit (0-9)',     'int', 5, 0, 9, 1,
           help='Numeral hidden in the dot field.'),
    Param('palette_pair',  'colour pair',     'choice',
                              'red-green', None, None, None,
                              list(PALETTES.keys()),
           help='Which confusion-line palette to use.'),
    Param('noise',          'background noise', 'int', 4, 0, 8, 1,
           help='How often to insert accent dots in the background '
                '(0 = clean, higher = more variation; mimics how '
                'real plates use multiple background tones).'),
]


# 5×7 bitmap font for digits 0-9. 1 = digit pixel, 0 = background.
_DIGIT_BITMAPS = {
    0: ['01110','10001','10011','10101','11001','10001','01110'],
    1: ['00100','01100','00100','00100','00100','00100','01110'],
    2: ['01110','10001','00001','00010','00100','01000','11111'],
    3: ['01110','10001','00001','00110','00001','10001','01110'],
    4: ['00010','00110','01010','10010','11111','00010','00010'],
    5: ['11111','10000','11110','00001','00001','10001','01110'],
    6: ['00110','01000','10000','11110','10001','10001','01110'],
    7: ['11111','00001','00010','00100','01000','01000','01000'],
    8: ['01110','10001','10001','01110','10001','10001','01110'],
    9: ['01110','10001','10001','01111','00001','00010','01100'],
}


def _digit_pixel(digit: int, x: int, y: int, w: int, h: int) -> bool:
    """True if the (x, y) cell falls on the digit's bitmap. The 5×7
    glyph is centered + scaled to fit the inner 60% of the grid."""
    bm = _DIGIT_BITMAPS.get(digit)
    if bm is None:
        return False
    margin_x = w // 5
    margin_y = h // 8
    inner_w = max(5, w - 2 * margin_x)
    inner_h = max(7, h - 2 * margin_y)
    bx = x - margin_x
    by = y - margin_y
    if bx < 0 or by < 0 or bx >= inner_w or by >= inner_h:
        return False
    fx = (bx * 5) // inner_w
    fy = (by * 7) // inner_h
    return bm[fy][fx] == '1'


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    digit  = max(0, min(9, int(params.get('digit', 5))))
    pair   = str(params.get('palette_pair', 'red-green'))
    noise  = max(0, int(params.get('noise', 4)))

    # Swap PALETTE for this render so the playground picks up the
    # palette the user selected.  (Module-level PALETTE is used as
    # the *default*; per-call we override.)
    palette = PALETTES.get(pair, PALETTES['red-green'])

    out = [[0] * grid_w for _ in range(grid_h)]
    for y in range(grid_h):
        for x in range(grid_w):
            on_digit = _digit_pixel(digit, x, y, grid_w, grid_h)
            if on_digit:
                # Sometimes use the accent (3rd palette colour) so the
                # digit reads as a textured shape, not a solid block.
                hash_v = (x * 73856093 ^ y * 19349663) & 0xFF
                out[y][x] = 1 if (hash_v & 7) != 0 else 2
            else:
                # Background: mix of palette[0] and palette[2] noise.
                hash_v = ((x + 1) * 374761393 ^ (y + 1) * 668265263) & 0xFF
                out[y][x] = 2 if (noise > 0 and hash_v % (16 - noise) == 0) else 0
    return out


# Optikon's view layer calls get_palette(params) when present so the
# palette can vary per request — needed because Ishihara has 3 palette
# choices and the user picks via the playground knob.
def get_palette(params: dict) -> list[str]:
    pair = str(params.get('palette_pair', 'red-green'))
    return PALETTES.get(pair, PALETTES['red-green'])
