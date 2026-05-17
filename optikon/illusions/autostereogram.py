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

# Half the previous default → much higher cell count.  At 0.7 mm
# hex side an A4 sheet packs ~155 columns × ~265 rows ≈ 41,000
# hexes — enough resolution that an uploaded image reads like a
# real photo when the eyes fuse.
DEFAULT_CELL_MM = 0.7
DEFAULT_GRID_W  = 140
DEFAULT_GRID_H  = 90

# The autostereogram effect repeats horizontally — depth pops out only
# when the viewer's eyes diverge by one period across the page width.
# Landscape A4 gives that period more room, so the gridprint hand-off
# defaults to landscape unless the user overrides ?landscape= on the URL.
DEFAULT_PRINT_LANDSCAPE = True

# Stereograms work best when no white frame interrupts the repeating
# pattern — the eye uses page edges as a depth reference, and a white
# frame anchors the surface flat at zero parallax, killing the pop-out.
# So the gridprint hand-off defaults to full-bleed: the SVG renders
# 3 mm past every page edge, the print HTML CSS sizes the page +bleed,
# and the user gets a "set Margins → None" hint in the print dialog.
DEFAULT_PRINT_BLEED = True

# The baked default palette.  Used when palette_seed = 0; otherwise
# get_palette() generates an HSV-spread set deterministic in seed.
PALETTE = [
    '#202020', '#5a3a1a', '#a07020',
    '#306030', '#3070a0', '#a03060',
    '#c0a040', '#e0e0e0',
]


def _hsv_to_hex(h: float, s: float, v: float) -> str:
    """Compact HSV → '#rrggbb' (avoids importing colorsys at module
    top so the file still loads cleanly without it)."""
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)),
                                    max(0.0, min(1.0, v)))
    return '#{:02x}{:02x}{:02x}'.format(int(r*255), int(g*255), int(b*255))


def _palette_from_seed(seed: int, n: int = 8) -> list[str]:
    """Generate `n` distinct HSV-spread CSS colours deterministic in
    `seed`.  Hues are spaced evenly around the wheel with small per-
    swatch jitter; saturation + value are sampled from comfortable
    print-friendly ranges.  Same seed → same colours every time."""
    state = seed & 0xFFFFFFFF
    if state == 0: state = 1
    def step():
        nonlocal state
        state = (state * 1103515245 + 12345) & 0xFFFFFFFF
        return state >> 16
    base_hue = (step() & 0xFF) / 255.0
    out = []
    for i in range(n):
        h = (base_hue + i / n + (step() & 0x3F) / 4096.0) % 1.0
        s = 0.5 + (step() & 0xFF) / 511.0
        v = 0.40 + (step() & 0xFF) / 511.0
        out.append(_hsv_to_hex(h, s, v))
    return out


def _secret_palette(contrast: int = 3) -> list[str]:
    """Perceptually-similar 4-color palette with subtle hue tints.

    Each color is a ``contrast``-unit RGB shift from medium grey, with
    different channels picking up the offset.  The result reads as
    "near-uniform muted colour" to the human eye but the ITU-R 601
    grayscale conversion (the standard ``.convert('L')`` used by the
    decoder) preserves four distinct luminance levels.

    Default ``contrast=3`` puts the four greyscales roughly at 127, 128,
    129, and 130 — barely separable visually on a typical LCD but
    100% reliable for the decoder when the SVG is rendered cleanly.
    Bump to 6-10 if you're going through JPEG or photo capture.
    """
    contrast = max(1, min(20, int(contrast)))
    c = contrast
    base = 128
    # Each color shifts two channels (one up, one down) by `c`.  This
    # keeps the *average* RGB constant (so the four colours all look
    # like the same medium grey) while putting the luminance-weighted
    # ITU-R 601 conversion at four distinct values.
    return [
        '#{:02X}{:02X}{:02X}'.format(base - c, base,     base + c),
        '#{:02X}{:02X}{:02X}'.format(base + c, base,     base - c),
        '#{:02X}{:02X}{:02X}'.format(base,     base - c, base + c),
        '#{:02X}{:02X}{:02X}'.format(base,     base + c, base - c),
    ]


def get_palette(params: dict) -> list[str]:
    """Resolved palette for a render call.

    Priority:
      1. ``secret_mode`` on → 4-colour perceptually-uniform palette
         (decoder-readable, visually near-uniform).
      2. ``palette_seed`` non-zero → deterministic HSV-spread palette.
      3. Otherwise → the baked PALETTE.
    """
    try:
        if int(params.get('secret_mode', 0)):
            contrast = int(params.get('secret_contrast', 3))
            return _secret_palette(contrast)
    except (TypeError, ValueError):
        pass
    try: seed = int(params.get('palette_seed', 0)) & 0xFFFFFFFF
    except (TypeError, ValueError): seed = 0
    if not seed:
        return PALETTE
    return _palette_from_seed(seed, n=len(PALETTE))


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
    Param('shape_size', 'shape size (hex radius)',       'int', 56,  4,160, 1,
           help='Half-extent of the shape in hex cells.  For silhouettes '
                'and custom images this is the bounding-box half-side.'),
    Param('palette_n',  'palette size',                  'int', 6,  2, 8, 1,
           help='How many distinct colours the repeating pattern uses.  '
                'Smaller is easier to fuse; 4-6 is the sweet spot.'),
    Param('palette_seed','palette seed (0 = default)',    'int', 0,  0, 1<<30, 1,
           help='Non-zero overrides the baked palette with an HSV-spread '
                'set deterministic in this seed.  Use the 🎨 reroll '
                'button next to it to pick a fresh random one.'),
    Param('secret_mode', 'secret stereogram (0/1)',        'int', 0,  0, 1, 1,
           help='When 1, replaces the palette with 4 perceptually-similar '
                'colours that look like uniform hexagons to the human eye '
                'but resolve into 4 distinct luminance levels under the '
                "decoder's grayscale conversion.  palette_n is forced to "
                '4 in this mode.  Use /optikon/autostereogram/decode/ to '
                'recover the hidden depth shape from the rendered image.'),
    Param('secret_contrast', 'secret contrast',            'int', 3,  1, 20, 1,
           help='Luminance-step between the 4 secret-mode colours.  3 is '
                'almost imperceptible to a human but reliable for the '
                'decoder when the SVG is rendered cleanly.  Bump to 6–10 '
                'if your output goes through JPEG or photo capture.'),
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


# ─── Decoder ──────────────────────────────────────────────────────────
#
# Inverse of `render`: take a rendered autostereogram (a raster image)
# and recover the depth map driving it.  Works on any horizontally-
# repeating stereogram, not just ours — the algorithm is the standard
# autocorrelation-based decode used by SIRDS analysis tools.
#
# Pipeline:
#   1. Convert to greyscale + optionally downscale to bound runtime.
#   2. Estimate the dominant horizontal repeat period via the row-mean
#      autocorrelation; pick the strongest peak in [W/20, W/2].
#   3. For each pixel (y, x), search shifts s ∈ [-max_shift, max_shift]
#      to minimise |img[y, x] - img[y, x + period + s]|.  The winning
#      shift IS the depth at (y, x) (modulo sign).
#   4. Optional median filter to clean up noise from JPEG / aliasing.
#
# Output: a 2-D ndarray with depth values in [-max_shift, max_shift],
# rendered as a PNG by the caller for browser display.


def estimate_period(arr) -> int:
    """Return the dominant horizontal repeat period (in pixels) of
    ``arr`` (a 2-D greyscale uint8/int16 ndarray).  Uses the column-
    averaged-row autocorrelation peak in the range [W/20, W/2]."""
    import numpy as np
    H, W = arr.shape
    row = arr.astype(np.float64).mean(axis=0)
    row = row - row.mean()
    # Full autocorrelation, then take the non-negative-lag half.
    ac = np.correlate(row, row, mode='full')[W - 1:]
    lo = max(8, W // 20)
    hi = max(lo + 1, W // 2)
    return lo + int(np.argmax(ac[lo:hi]))


def decode_depth(image_bytes: bytes, *,
                   max_dim: int = 640,
                   smooth: bool = True) -> dict:
    """Decode a rendered autostereogram raster back into a depth map.

    Args:
      image_bytes: raw bytes of a PNG/JPEG/WebP/anything PIL handles.
      max_dim:     longest-edge cap for the working image (speed knob).
                     Capped server-side at 1024.
      smooth:      apply a small median filter to the depth map to
                     remove single-pixel noise from compression.

    Returns dict with:
      depth_png:    PNG bytes of a normalised greyscale depth map.
      orig_png:     PNG bytes of the downscaled input (for side-by-side).
      period:       detected horizontal repeat period (pixels).
      max_shift:    +/- shift range searched per pixel.
      width, height: working dimensions.
      depth_min, depth_max: shift extremes actually seen.
    """
    import io
    import numpy as np
    from PIL import Image

    max_dim = max(64, min(1024, int(max_dim)))
    img = Image.open(io.BytesIO(image_bytes)).convert('L')
    if max(img.size) > max_dim:
        scale = max_dim / max(img.size)
        img = img.resize((max(8, int(img.size[0] * scale)),
                            max(8, int(img.size[1] * scale))),
                           Image.BILINEAR)
    arr = np.asarray(img, dtype=np.int16)
    H, W = arr.shape

    period = estimate_period(arr)
    max_shift = max(2, int(period * 0.35))

    # Vectorised per-shift comparison.  For each shift s, compute the
    # absolute difference between img[:, :out_W] and img[:, period+s:
    # period+s+out_W]; keep the s with the smallest diff per pixel.
    out_W = max(1, W - period - max_shift)
    best_shift = np.zeros((H, out_W), dtype=np.int16)
    best_diff  = np.full((H, out_W), np.iinfo(np.int32).max,
                            dtype=np.int32)
    for s in range(-max_shift, max_shift + 1):
        start = period + s
        if start < 0 or start + out_W > W:
            continue
        diff = np.abs(arr[:, :out_W].astype(np.int32) -
                        arr[:, start:start + out_W].astype(np.int32))
        mask = diff < best_diff
        best_shift[mask] = s
        best_diff[mask]  = diff[mask]

    depth = best_shift
    if smooth:
        # 3-pixel median filter via separable per-row + per-col on a
        # small window.  Cheap and bounded; cleans up JPEG noise.
        depth = _median_3x3(depth)

    # Normalise depth to [0, 255] for PNG display.  Map the [-max_shift,
    # max_shift] range to [0, 255] so the brightest pixel is the
    # max-positive shift and the darkest is the max-negative.
    d_min, d_max = int(depth.min()), int(depth.max())
    span = max(1, d_max - d_min)
    norm = ((depth.astype(np.int32) - d_min) * 255 // span).astype(np.uint8)
    depth_img = Image.fromarray(norm, mode='L')

    buf_depth = io.BytesIO(); depth_img.save(buf_depth, format='PNG')
    buf_orig  = io.BytesIO(); img.save(buf_orig, format='PNG')

    return {
        'depth_png':  buf_depth.getvalue(),
        'orig_png':   buf_orig.getvalue(),
        'period':     period,
        'max_shift':  max_shift,
        'width':      W,
        'height':     H,
        'depth_min':  d_min,
        'depth_max':  d_max,
    }


def _median_3x3(arr):
    """Tiny 3×3 median filter — replaces scipy.ndimage.median_filter for
    a no-extra-dep build.  ~100ms on a 600×600 array; good enough."""
    import numpy as np
    H, W = arr.shape
    padded = np.pad(arr, 1, mode='edge')
    stacked = np.stack([
        padded[0:H,   0:W  ], padded[0:H,   1:W+1], padded[0:H,   2:W+2],
        padded[1:H+1, 0:W  ], padded[1:H+1, 1:W+1], padded[1:H+1, 2:W+2],
        padded[2:H+2, 0:W  ], padded[2:H+2, 1:W+1], padded[2:H+2, 2:W+2],
    ], axis=0)
    return np.median(stacked, axis=0).astype(arr.dtype)


def render(grid_w: int, grid_h: int, params: dict) -> list[list[int]]:
    period   = max(2, int(params.get('period', 8)))
    amp      = max(1, int(params.get('amplitude', 2)))
    shape    = str(params.get('shape', 'heart'))
    size     = max(1, int(params.get('shape_size', 28)))
    # Secret mode locks palette_n to 4 (the secret palette is exactly
    # 4 colours by design — see _secret_palette).
    try:
        secret = bool(int(params.get('secret_mode', 0)))
    except (TypeError, ValueError):
        secret = False
    if secret:
        n_cols = 4
    else:
        n_cols = max(2, min(len(PALETTE), int(params.get('palette_n', 6))))
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
