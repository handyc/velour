"""Autostereogram (Magic Eye) on a hex grid.

Each hex is one solid colour drawn from a small palette.  The
horizontal pattern repeats with period `period` hexes; *within* the
shape region, columns are offset by `depth × amplitude` hexes,
which the visual system fuses into a 3-D pop-out when the viewer
crosses (or diverges) their eyes by one period.

Single-image-random-dot-stereograms (SIRDS) normally use random
pixels; here we use a deterministic hex-color pattern seeded from
`pattern_seed` so the result is reproducible and printable.

Depth shapes:

  Geometric primitives:
    'circle', 'square', 'ring', 'plus', 'gradient_x', 'gradient_y'

  Classic-image silhouettes (encoded as ASCII bitmaps below):
    'heart', 'hand', 'dolphin', 'star', 'fish', 'mountain'

The classic-image shapes scale to fit `shape_size` × shape_size
hexes centred on the grid, so the autostereogram contains a
recognisable figure when fused.

For printing big stereograms on A4 we want lots of cells, so this
illusion sets a small DEFAULT_CELL_MM (≈ 1.4 mm side) and a wide
DEFAULT_GRID_W/H — the playground preview shows enough cells for
the depth shape to be readable, and the gridprint hand-off fills
A4 at the same hex size for a print-grade rendering.
"""

from __future__ import annotations
from . import Param

SLUG        = 'autostereogram'
NAME        = 'Autostereogram'
DESCRIPTION = ('Magic-Eye-style hex stereogram. Cross or diverge '
                'your eyes by one period (the configured pattern '
                'width) and the depth shape pops out of the page. '
                'Default hex size is small (~1.4 mm) so an A4 print '
                'fills with ~110 columns of useful resolution.')

# Tighter default than the geometric illusions: small hexes give
# enough columns that the silhouette shapes read as recognisable
# figures.
DEFAULT_CELL_MM = 1.4
DEFAULT_GRID_W  = 90
DEFAULT_GRID_H  = 60

PALETTE = [
    '#202020', '#5a3a1a', '#a07020',
    '#306030', '#3070a0', '#a03060',
    '#c0a040', '#e0e0e0',
]


# ── Classic-image silhouette bitmaps ─────────────────────────────────
# '#' = "in shape" (depth = amplitude); '.' = background (depth 0).
# Sized at module import; the rasteriser scales whatever bitmap it
# gets to fit the requested shape_size square centred on the grid.

SILHOUETTES: dict[str, list[str]] = {
    'heart': [
        ".###....###.",
        "############",
        "############",
        "############",
        ".##########.",
        "..########..",
        "...######...",
        "....####....",
        ".....##.....",
    ],
    'hand': [
        ".....##.........",
        ".#...##...##....",
        ".#.#.##.#.##.#..",
        ".#.#.##.#.##.#..",
        ".#.#.##.#.##.#..",
        "##.#.##.#.##.##.",
        "################",
        "################",
        ".##############.",
        "..############..",
        "...##########...",
        "....########....",
    ],
    'dolphin': [
        "...........####.",
        "..........#####.",
        "....#####.#####.",
        "...#######.####.",
        "..########.####.",
        ".###############",
        "################",
        ".##############.",
        "..############..",
        "...##.######....",
        "...##....##.....",
    ],
    'star': [
        ".......##.......",
        ".......##.......",
        "......####......",
        "......####......",
        "################",
        ".##############.",
        "..############..",
        "...##########...",
        "....########....",
        "...##########...",
        "..####....####..",
        ".####......####.",
        "###..........###",
    ],
    'fish': [
        "............###.",
        "..........#####.",
        ".####....#####..",
        "########.######.",
        "##############..",
        "########.#####..",
        ".####....#####..",
        "..........#####.",
        "............###.",
    ],
    'mountain': [
        "................",
        ".......##.......",
        "......####......",
        "......####......",
        ".....######.....",
        ".....######.....",
        "....########....",
        "....########....",
        "...####.#####...",
        "...##########...",
        "..############..",
        ".##############.",
        "################",
        "################",
    ],
}


PARAMS = [
    Param('period',     'pattern period (hex columns)', 'int', 8,  4, 32, 1,
           help='Horizontal repeat period.  Cross-eyed fusion at this '
                'width gives the depth illusion.'),
    Param('amplitude',  'depth amplitude (hexes)',       'int', 2,  1, 6, 1,
           help='How many hex columns the depth shape pops out by.  '
                'Larger = more dramatic but harder to fuse.'),
    Param('shape',      'depth shape',                   'choice',
                        'heart', None, None, None,
                        ['custom-image',
                          'heart','hand','dolphin','star','fish','mountain',
                          'circle','square','ring','plus','gradient_x','gradient_y'],
           help='What the depth map looks like.  Silhouettes (heart, '
                'hand, …) read as recognisable figures when fused.  '
                'Pick "custom-image" and use the upload widget to '
                'supply your own depth map from any image.'),
    Param('shape_size', 'shape size (hex radius)',       'int', 28,  4, 80, 1,
           help='Half-extent of the shape in hex cells.  For silhouettes '
                'and custom images this is the bounding-box half-side.'),
    Param('palette_n',  'palette size',                  'int', 6,  2, 8, 1,
           help='How many distinct colours the repeating pattern uses.  '
                'Smaller is easier to fuse; 4-6 is the sweet spot.'),
    Param('pattern_seed','pattern seed',                 'int', 42, 0, 1<<30, 1,
           help='Deterministic seed for the in-period colour pattern.'),
    Param('depth_image_hash', 'depth image hash',         'text', '',
                              None, 64, None, None,
           help='SHA-256 of an uploaded depth-map image.  Set '
                'automatically by the upload widget; leave blank to '
                'use a built-in shape.'),
]


# Tells the optikon detail template to surface the upload widget for
# this illusion (other illusions don't accept custom depth maps).
SUPPORTS_CUSTOM_IMAGE = True


# ── deterministic LCG (matches hexhunter.c so users can predict it) ──
def _rng_step(state: int) -> tuple[int, int]:
    state = (state * 1103515245 + 12345) & 0xFFFFFFFF
    return state, state >> 16


def _build_pattern_row(period: int, n_colors: int, seed: int) -> list[int]:
    """One period worth of palette indices, deterministic in (period,
    n_colors, seed)."""
    state = (seed if seed != 0 else 1) & 0xFFFFFFFF
    out = []
    for _ in range(period):
        state, v = _rng_step(state)
        out.append(v % n_colors)
    return out


def _silhouette_depth(name: str, r: int, c: int, gw: int, gh: int,
                       size: int, amp: int) -> int:
    """Sample a named silhouette bitmap centred on the grid, scaled to
    fit a (2*size) × (2*size) hex region.  Returns `amp` if the
    bitmap cell at this position is filled, else 0."""
    bitmap = SILHOUETTES.get(name)
    if not bitmap:
        return 0
    bh = len(bitmap)
    bw = max(len(row) for row in bitmap)
    cx, cy = gw / 2.0, gh / 2.0
    half = max(1, size)
    # Map (r, c) → bitmap (by, bx).  Outside the bounding box → 0.
    if not (cx - half <= c < cx + half and cy - half <= r < cy + half):
        return 0
    bx = int((c - (cx - half)) / (2 * half) * bw)
    by = int((r - (cy - half)) / (2 * half) * bh)
    if not (0 <= bx < bw and 0 <= by < bh):
        return 0
    row = bitmap[by]
    if bx < len(row) and row[bx] == '#':
        return amp
    return 0


# Cached depth maps keyed by (sha, max_n_levels) so render() doesn't
# re-load the same JSON for every cell.  Cleared between calls by
# render() itself; lives in module scope so a single render reuses.
_RENDER_CACHE: dict = {}


def _custom_image_depth(sha: str, r: int, c: int, gw: int, gh: int,
                         size: int, amp: int) -> int:
    """Sample an uploaded depth map by hash.  The cached map carries
    its own (w, h, n_levels); we scale to fit (2*size) × (2*size)
    centred on the grid and rescale per-pixel depth to amplitude."""
    payload = _RENDER_CACHE.get(('depth', sha))
    if payload is None:
        from optikon import depth_cache
        payload = depth_cache.load(sha)
        if payload is None:
            return 0
        _RENDER_CACHE[('depth', sha)] = payload
    bw, bh = int(payload['w']), int(payload['h'])
    if bw <= 0 or bh <= 0:
        return 0
    n_levels = max(1, int(payload.get('n_levels', 4)))
    cx, cy = gw / 2.0, gh / 2.0
    half = max(1, size)
    if not (cx - half <= c < cx + half and cy - half <= r < cy + half):
        return 0
    bx = int((c - (cx - half)) / (2 * half) * bw)
    by = int((r - (cy - half)) / (2 * half) * bh)
    if not (0 <= bx < bw and 0 <= by < bh):
        return 0
    d = int(payload['depths'][by][bx])
    # Map cached level (0..n_levels-1) onto requested amplitude.
    if n_levels <= 1:
        return amp if d > 0 else 0
    return int(round(d * amp / (n_levels - 1)))


def _depth(shape: str, r: int, c: int, gw: int, gh: int, size: int,
           amp: int, depth_image_hash: str = '') -> int:
    """Return depth shift in hexes (0 = background) for the cell."""
    if shape == 'custom-image' and depth_image_hash:
        return _custom_image_depth(depth_image_hash, r, c, gw, gh, size, amp)
    if shape in SILHOUETTES:
        return _silhouette_depth(shape, r, c, gw, gh, size, amp)
    cx, cy = gw / 2.0, gh / 2.0
    dx, dy = c - cx, r - cy
    if shape == 'circle':
        return amp if (dx * dx + dy * dy) <= size * size else 0
    if shape == 'square':
        return amp if (abs(dx) <= size and abs(dy) <= size) else 0
    if shape == 'ring':
        d2 = dx * dx + dy * dy
        outer = size * size
        inner = (size - max(2, size // 2)) ** 2
        return amp if (inner <= d2 <= outer) else 0
    if shape == 'plus':
        arm = max(1, size // 2)
        if (abs(dx) <= size and abs(dy) <= arm) or \
           (abs(dy) <= size and abs(dx) <= arm):
            return amp
        return 0
    if shape == 'gradient_x':
        return int(round(amp * (c / max(1, gw - 1))))
    if shape == 'gradient_y':
        return int(round(amp * (r / max(1, gh - 1))))
    return 0


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    period   = max(2, int(params.get('period', 8)))
    amp      = max(1, int(params.get('amplitude', 2)))
    shape    = str(params.get('shape', 'heart'))
    size     = max(1, int(params.get('shape_size', 28)))
    n_cols   = max(2, min(len(PALETTE), int(params.get('palette_n', 6))))
    seed     = int(params.get('pattern_seed', 42)) & 0xFFFFFFFF
    depth_h  = str(params.get('depth_image_hash', ''))

    # Drop the cached depth-map look-up between renders so an updated
    # upload (same hash → fine, different hash → loaded fresh) is
    # picked up correctly.
    _RENDER_CACHE.clear()

    out = [[0] * grid_w for _ in range(grid_h)]
    for r in range(grid_h):
        row_pattern = _build_pattern_row(
            period, n_cols, (seed * 2654435761 + r) & 0xFFFFFFFF)
        for c in range(grid_w):
            if c < period:
                out[r][c] = row_pattern[c]
            else:
                d = _depth(shape, r, c, grid_w, grid_h, size, amp, depth_h)
                src = c - period + d
                if src < 0:
                    src = 0
                if src >= grid_w:
                    src = grid_w - 1
                out[r][c] = out[r][src]
    return out
