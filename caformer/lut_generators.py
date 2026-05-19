"""Alternative LUT generators to test against the Mandelbrot baseline.

Each generator produces a 16,384-byte K=4 LUT (interpreted as a
128×128 Ouroboros LUT-as-board).  The hypothesis tests:

  - random:     baseline; uniform random K=4 bytes
  - mandelbrot: posterised Mandelbrot region (same as mandelhunt)
  - banded:     horizontal stripes of solid K=4 colors with optional
                sparse pixel-noise overlay.  Matches the visual
                signature of true L0 ouroboros quines observed in
                Taxon DB (2026-05-19).
  - ltree:      Lindenmayer-system turtle-graphics tree rendered to
                a 128×128 K=4 image.  Tests whether branching/
                self-similar structure helps (hypothesis: it doesn't
                — true L0 quines are banded, not branched).

All generators take a numpy RandomState for reproducibility and
return a (16384,) uint8 array of values in {0, 1, 2, 3}.
"""
from __future__ import annotations

import numpy as np


SIDE = 128
BOARD_CELLS = SIDE * SIDE


# ── 0. Random baseline ────────────────────────────────────────────

def gen_random(rng: np.random.RandomState) -> np.ndarray:
    return rng.randint(0, 4, BOARD_CELLS, dtype=np.uint8)


# ── 1. Mandelbrot (wrapper around loupe.render) ───────────────────

def _posterise_escape(escape: np.ndarray, iter_cap: int) -> np.ndarray:
    """Tertile-bucket an escape-time grid into K=4 cells the same way
    mandelhunt / loupe.render does (in-set → 3, finite → 0/1/2 by
    tertile of finite escape values).  Shared between mandelbrot,
    julia, burning ship, phoenix — anything escape-time based."""
    flat = escape.ravel()
    finite = flat[flat < iter_cap]
    if finite.size < 3:
        bin1, bin2 = iter_cap // 3, (2 * iter_cap) // 3
    else:
        finite_sorted = np.sort(finite)
        bin1 = int(finite_sorted[finite_sorted.size // 3])
        bin2 = int(finite_sorted[(2 * finite_sorted.size) // 3])
        if bin2 <= bin1:
            bin2 = bin1 + 1
    out = np.where(flat >= iter_cap, 3,
            np.where(flat < bin1, 0,
              np.where(flat < bin2, 1, 2))).astype(np.uint8)
    return out


def _escape_iter(zx_init, zy_init, cx, cy, iter_cap, mode='mandelbrot'):
    """Vectorised escape-time iteration for several quadratic fractals.
    `zx_init/zy_init` are SIDE×SIDE float64 arrays of initial z values;
    `cx/cy` are either arrays (Julia: constant per pixel) or scalars
    (Mandelbrot: c = pixel coord, so cx/cy are the pixel grids).
    Returns an int array of escape iteration counts."""
    zx = zx_init.copy().astype(np.float64)
    zy = zy_init.copy().astype(np.float64)
    if np.isscalar(cx):
        cx = np.full_like(zx, cx)
        cy = np.full_like(zy, cy)
    escape = np.full(zx.shape, iter_cap, dtype=np.int32)
    mask = np.ones(zx.shape, dtype=bool)
    for i in range(iter_cap):
        if mode == 'mandelbrot' or mode == 'julia':
            # z = z² + c
            new_zx = zx * zx - zy * zy + cx
            new_zy = 2.0 * zx * zy + cy
        elif mode == 'burning_ship':
            # z = (|x| + i|y|)² + c
            ax = np.abs(zx); ay = np.abs(zy)
            new_zx = ax * ax - ay * ay + cx
            new_zy = 2.0 * ax * ay + cy
        elif mode == 'tricorn':
            # z = conj(z)² + c
            new_zx = zx * zx - zy * zy + cx
            new_zy = -2.0 * zx * zy + cy
        else:
            raise ValueError(f'unknown escape-iter mode {mode!r}')
        zx[mask] = new_zx[mask]
        zy[mask] = new_zy[mask]
        diverged = (zx * zx + zy * zy) > 4.0
        new_escape = mask & diverged
        escape[new_escape] = i
        mask &= ~diverged
        if not mask.any():
            break
    return escape


def gen_julia(rng: np.random.RandomState, *, cx=None, cy=None,
                  zoom=None, center_x=0.0, center_y=0.0) -> np.ndarray:
    """Julia set posterised to K=4.  Picks a c value near the boundary
    of the Mandelbrot set (where Julia sets are most fractal-rich)
    and renders the Julia set of that c over a viewport zoomed to
    fit the structure."""
    if cx is None or cy is None:
        # Bias c toward known-interesting Julia regions.
        choices = [
            (-0.4,    0.6),       # rabbit
            ( 0.285,  0.01),      # near tip of cardioid
            (-0.835, -0.2321),    # spiral
            ( 0.45,   0.1428),    # douady rabbit-ish
            (-0.70176, -0.3842),  # dragon
            ( 0.0,    1.0),       # dendrite-like
            ( -1.476, 0.0),       # period-3 along real axis
            ( -0.12,  0.74),      # Newton-like spirals
            (-0.75,   0.11),      # near main bulb
        ]
        cx_, cy_ = choices[rng.randint(0, len(choices))]
        cx = cx_ + (rng.uniform() - 0.5) * 0.05
        cy = cy_ + (rng.uniform() - 0.5) * 0.05
    if zoom is None:
        log_zoom = rng.uniform(0.4, 1.6)    # 1.5 to ~5 viewport
        zoom = 10.0 ** log_zoom * 0.3
    # Pixel grid: viewport from (center - zoom/2, center + zoom/2).
    side = SIDE
    half = zoom / 2.0
    xs = np.linspace(center_x - half, center_x + half, side)
    ys = np.linspace(center_y - half, center_y + half, side)
    zx0, zy0 = np.meshgrid(xs, ys)
    iter_cap = 192 + int(64 * max(0, 1.6 - np.log10(zoom + 1e-9)))
    escape = _escape_iter(zx0, zy0, cx, cy, iter_cap, mode='julia')
    return _posterise_escape(escape, iter_cap)


def gen_burning_ship(rng: np.random.RandomState) -> np.ndarray:
    """Burning Ship fractal posterised to K=4.  Mandelbrot-like
    iteration with |z| in place of z each step → produces the
    iconic ship silhouette and similar bulbous detail."""
    # Burning Ship's interesting region is centred near (-1.7, -0.03).
    cx_c = -1.75 + (rng.uniform() - 0.5) * 0.3
    cy_c = -0.03 + (rng.uniform() - 0.5) * 0.3
    span = 10.0 ** rng.uniform(-3, 0.3)   # 0.001 to 2.0
    side = SIDE
    half = span / 2.0
    xs = np.linspace(cx_c - half, cx_c + half, side)
    ys = np.linspace(cy_c - half, cy_c + half, side)
    cx_grid, cy_grid = np.meshgrid(xs, ys)
    zx0 = np.zeros_like(cx_grid)
    zy0 = np.zeros_like(cy_grid)
    iter_cap = 192 + int(64 * max(0, -np.log10(span + 1e-9)))
    escape = _escape_iter(zx0, zy0, cx_grid, cy_grid, iter_cap,
                              mode='burning_ship')
    return _posterise_escape(escape, iter_cap)


def gen_tricorn(rng: np.random.RandomState) -> np.ndarray:
    """Tricorn (Mandelbar) fractal — z = conj(z)² + c.  Three-fold
    symmetry; bulb-on-bulb structure like Mandelbrot but rougher."""
    cx_c = 0.0 + (rng.uniform() - 0.5) * 2.0
    cy_c = 0.0 + (rng.uniform() - 0.5) * 2.0
    span = 10.0 ** rng.uniform(-2, 0.5)
    side = SIDE
    half = span / 2.0
    xs = np.linspace(cx_c - half, cx_c + half, side)
    ys = np.linspace(cy_c - half, cy_c + half, side)
    cx_grid, cy_grid = np.meshgrid(xs, ys)
    zx0 = np.zeros_like(cx_grid)
    zy0 = np.zeros_like(cy_grid)
    iter_cap = 192
    escape = _escape_iter(zx0, zy0, cx_grid, cy_grid, iter_cap, mode='tricorn')
    return _posterise_escape(escape, iter_cap)


def gen_multibrot(rng: np.random.RandomState, *, d: int = None) -> np.ndarray:
    """Multibrot — z = z^d + c for integer d ≥ 3.  d=2 is regular
    Mandelbrot; higher d gives d-fold rotational symmetry and a
    'pinched' bulb structure with more lobes."""
    if d is None:
        d = int(rng.choice([3, 4, 5, 6, 7]))
    cx_c = (rng.uniform() - 0.5) * 2.0
    cy_c = (rng.uniform() - 0.5) * 2.0
    span = 10.0 ** rng.uniform(-2, 0.5)
    half = span / 2.0
    xs = np.linspace(cx_c - half, cx_c + half, SIDE)
    ys = np.linspace(cy_c - half, cy_c + half, SIDE)
    cx_grid, cy_grid = np.meshgrid(xs, ys)
    zx = np.zeros_like(cx_grid)
    zy = np.zeros_like(cy_grid)
    iter_cap = 192
    escape = np.full(zx.shape, iter_cap, dtype=np.int32)
    mask = np.ones(zx.shape, dtype=bool)
    for i in range(iter_cap):
        # z^d via polar form: r^d, angle*d.
        r2 = zx * zx + zy * zy
        # Avoid log(0); when r==0, z^d = 0 too.
        r = np.sqrt(r2)
        theta = np.arctan2(zy, zx)
        rd = r ** d
        new_zx = rd * np.cos(d * theta) + cx_grid
        new_zy = rd * np.sin(d * theta) + cy_grid
        zx[mask] = new_zx[mask]
        zy[mask] = new_zy[mask]
        diverged = (zx * zx + zy * zy) > 4.0
        new_escape = mask & diverged
        escape[new_escape] = i
        mask &= ~diverged
        if not mask.any():
            break
    return _posterise_escape(escape, iter_cap)


def gen_newton(rng: np.random.RandomState) -> np.ndarray:
    """Newton fractal for f(z) = z³ − 1.  Each pixel is a starting z;
    we iterate Newton's step z -= f(z)/f'(z) and colour by which of
    the 3 roots we landed in (or 'didn't converge' for the 4th).

    Topologically very different from escape-time fractals: basins
    interlock at every scale instead of nesting in bulbs, so the
    LUT structure has *different* spatial statistics."""
    # The three cube roots of 1.
    roots = np.array([[1.0, 0.0],
                       [-0.5,  np.sqrt(3) / 2],
                       [-0.5, -np.sqrt(3) / 2]])
    cx_c = (rng.uniform() - 0.5) * 1.0
    cy_c = (rng.uniform() - 0.5) * 1.0
    span = 10.0 ** rng.uniform(-1.5, 0.6)
    half = span / 2.0
    xs = np.linspace(cx_c - half, cx_c + half, SIDE)
    ys = np.linspace(cy_c - half, cy_c + half, SIDE)
    zx, zy = np.meshgrid(xs, ys)
    zx = zx.astype(np.float64); zy = zy.astype(np.float64)
    iters = 32
    for _ in range(iters):
        # f(z) = z³ − 1
        # f(z)/f'(z) = (z³ − 1) / (3z²) = z/3 − 1/(3z²)
        # z' = z − f/f' = z − z/3 + 1/(3z²) = 2z/3 + 1/(3z²)
        r2 = zx * zx + zy * zy
        # 1/z² = conj(z²)/|z|⁴
        z2x = zx * zx - zy * zy
        z2y = 2 * zx * zy
        denom = 3 * (z2x * z2x + z2y * z2y) + 1e-20
        inv3z2_x =  z2x / denom
        inv3z2_y = -z2y / denom
        zx = (2.0 / 3.0) * zx + inv3z2_x
        zy = (2.0 / 3.0) * zy + inv3z2_y
    # Classify by nearest root.
    out = np.zeros(zx.shape, dtype=np.uint8)
    best_d = np.full(zx.shape, np.inf)
    for k, (rx, ry) in enumerate(roots):
        d2 = (zx - rx) ** 2 + (zy - ry) ** 2
        closer = d2 < best_d
        out = np.where(closer, k, out)
        best_d = np.where(closer, d2, best_d)
    # Unconverged → bucket 3.
    out = np.where(best_d > 0.01, 3, out)
    return out.astype(np.uint8).ravel()


def gen_phoenix(rng: np.random.RandomState) -> np.ndarray:
    """Phoenix fractal — z_{n+1} = z_n² + Re(c) + Im(c)·z_{n-1}.
    Has memory (depends on previous z), so the iteration is NOT a
    pure quadratic map.  Classic c = (0.5667, −0.5)."""
    # The standard Phoenix lives near (-0.5, 0) in the z-plane with
    # those c values; we randomise around it.
    p_re = 0.5667 + (rng.uniform() - 0.5) * 0.4
    p_im = -0.5 + (rng.uniform() - 0.5) * 0.4
    cx_c = 0.0 + (rng.uniform() - 0.5) * 1.0
    cy_c = 0.0 + (rng.uniform() - 0.5) * 1.0
    span = 10.0 ** rng.uniform(-1.5, 0.4)
    half = span / 2.0
    xs = np.linspace(cx_c - half, cx_c + half, SIDE)
    ys = np.linspace(cy_c - half, cy_c + half, SIDE)
    zx, zy = np.meshgrid(xs, ys)
    zx = zx.astype(np.float64); zy = zy.astype(np.float64)
    # Previous-step z; start at 0.
    pzx = np.zeros_like(zx); pzy = np.zeros_like(zy)
    iter_cap = 192
    escape = np.full(zx.shape, iter_cap, dtype=np.int32)
    mask = np.ones(zx.shape, dtype=bool)
    for i in range(iter_cap):
        # z' = z² + p_re + p_im * z_prev
        new_zx = zx * zx - zy * zy + p_re + p_im * pzx
        new_zy = 2 * zx * zy + p_im * pzy
        pzx, pzy = zx.copy(), zy.copy()
        zx[mask] = new_zx[mask]
        zy[mask] = new_zy[mask]
        diverged = (zx * zx + zy * zy) > 4.0
        new_escape = mask & diverged
        escape[new_escape] = i
        mask &= ~diverged
        if not mask.any():
            break
    return _posterise_escape(escape, iter_cap)


def gen_mandelbrot(rng: np.random.RandomState, *, cx=None, cy=None,
                       span=None) -> np.ndarray:
    """Random Mandelbrot region (cx, cy in the famous box, span in
    [1e-6, 4]).  Same posterise as mandelhunt."""
    from loupe.render import mandelbrot_buckets
    if cx is None:
        cx = rng.uniform(-2.0, 0.5)
    if cy is None:
        cy = rng.uniform(-1.25, 1.25)
    if span is None:
        log_span = rng.uniform(-6, 0.6)
        span = 10.0 ** log_span
    buckets = mandelbrot_buckets(cx, cy, span, SIDE, SIDE, iter_cap=None)
    return buckets.astype(np.uint8).ravel()


# ── 2. Banded-noise generator ─────────────────────────────────────
#
# Produces a 128×128 image where each row is either a SOLID strip
# of one K=4 colour, or a NOISY strip whose base is a colour but
# with sparse random pixels overlaid.  Parameters:
#   - band_height_min/max: how tall each strip is
#   - noise_density:       prob a cell in a noisy strip flips to
#                          random colour (vs band base)
#   - noise_strip_prob:    prob a strip is "noisy" vs solid

def gen_banded(rng: np.random.RandomState, *,
                  band_height_min: int = 1, band_height_max: int = 6,
                  noise_density: float = 0.3,
                  noise_strip_prob: float = 0.6,
                  base_colour: int = None) -> np.ndarray:
    """Horizontal band pattern."""
    img = np.zeros((SIDE, SIDE), dtype=np.uint8)
    r = 0
    while r < SIDE:
        h = rng.randint(band_height_min, band_height_max + 1)
        h = min(h, SIDE - r)
        if base_colour is None:
            base = rng.randint(0, 4)
        else:
            base = int(base_colour)
        img[r:r + h, :] = base
        if rng.uniform() < noise_strip_prob:
            mask = rng.uniform(size=(h, SIDE)) < noise_density
            noise = rng.randint(0, 4, size=(h, SIDE))
            img[r:r + h, :] = np.where(mask, noise.astype(np.uint8),
                                              img[r:r + h, :])
        r += h
    return img.ravel()


# Specialised variant: mostly-black background with sparse coloured
# pixels (matches the visual of the highest-sr L0 quines exactly).

def gen_sparse_on_black(rng: np.random.RandomState, *,
                              noise_density: float = 0.05) -> np.ndarray:
    img = np.zeros((SIDE, SIDE), dtype=np.uint8)
    mask = rng.uniform(size=(SIDE, SIDE)) < noise_density
    noise = rng.randint(1, 4, size=(SIDE, SIDE))  # 1..3, not 0
    img = np.where(mask, noise.astype(np.uint8), img)
    return img.ravel()


# ── 3. L-system turtle-graphics generator ─────────────────────────

# Simple stochastic L-system.  Symbols:
#   F = forward 1 unit, drawing
#   +  = turn right by angle
#   -  = turn left by angle
#   [  = push state
#   ]  = pop state
#   X  = variable (replaced by production rule)
#
# Each "F" draws a pixel in the current colour.  Colour cycles
# through 0..3 with branch depth (so different branches get
# different colours).

def _expand(axiom: str, rules: dict, iters: int) -> str:
    s = axiom
    for _ in range(iters):
        s = ''.join(rules.get(c, c) for c in s)
        if len(s) > 200_000:    # safety cap on growth
            break
    return s


def _render_lsystem(commands: str, *, side: int = SIDE,
                       step_px: float = 1.5, angle_deg: float = 22.5,
                       start_x: float = None, start_y: float = None,
                       start_heading: float = -90.0,
                       max_colour: int = 4) -> np.ndarray:
    """Run the turtle, stamp each F draw into a (side, side) image."""
    import math
    img = np.zeros((side, side), dtype=np.uint8)
    if start_x is None:
        start_x = side / 2
    if start_y is None:
        start_y = side * 0.85
    x, y = start_x, start_y
    heading = start_heading
    depth = 0
    stack = []
    for c in commands:
        if c == 'F' or c == 'G':
            rad = math.radians(heading)
            nx = x + step_px * math.cos(rad)
            ny = y + step_px * math.sin(rad)
            # Bresenham-ish stamp.
            steps = max(1, int(step_px))
            for s in range(steps + 1):
                t = s / max(1, steps)
                px = int(round(x + (nx - x) * t))
                py = int(round(y + (ny - y) * t))
                if 0 <= px < side and 0 <= py < side:
                    img[py, px] = (depth % max_colour)
            x, y = nx, ny
        elif c == '+':
            heading += angle_deg
        elif c == '-':
            heading -= angle_deg
        elif c == '[':
            stack.append((x, y, heading, depth))
            depth += 1
        elif c == ']':
            if stack:
                x, y, heading, depth = stack.pop()
    return img


# Several canonical L-systems:

L_SYSTEMS = [
    # Plant 1 (Lindenmayer book p.25)
    {'axiom': 'X',
     'rules': {'X': 'F-[[X]+X]+F[+FX]-X', 'F': 'FF'},
     'iters': 5, 'angle': 22.5, 'step': 1.5},
    # Algae-like
    {'axiom': 'F',
     'rules': {'F': 'F[+F]F[-F]F'},
     'iters': 4, 'angle': 25.7, 'step': 1.4},
    # Bushy
    {'axiom': 'F',
     'rules': {'F': 'FF-[-F+F+F]+[+F-F-F]'},
     'iters': 4, 'angle': 22.5, 'step': 1.6},
    # Dragon curve
    {'axiom': 'FX',
     'rules': {'X': 'X+YF+', 'Y': '-FX-Y'},
     'iters': 11, 'angle': 90.0, 'step': 1.0},
    # Sierpinski triangle
    {'axiom': 'F-G-G',
     'rules': {'F': 'F-G+F+G-F', 'G': 'GG'},
     'iters': 5, 'angle': 120.0, 'step': 1.0},
]


def gen_ltree(rng: np.random.RandomState, *,
                  n_stamps: int = 3) -> np.ndarray:
    """Render N L-systems with random parameters into one 128×128
    image.  Multiple stamps add overlap and break the strong
    upward bias of a single tree."""
    img = np.zeros((SIDE, SIDE), dtype=np.uint8)
    for _ in range(n_stamps):
        spec = L_SYSTEMS[rng.randint(0, len(L_SYSTEMS))]
        commands = _expand(spec['axiom'], spec['rules'], spec['iters'])
        ang_jitter = rng.uniform(-5, 5)
        step_jitter = rng.uniform(0.8, 1.2)
        sx = rng.uniform(0.2, 0.8) * SIDE
        sy = rng.uniform(0.2, 0.95) * SIDE
        heading = rng.uniform(-180, 180)
        tile = _render_lsystem(
            commands, side=SIDE,
            step_px=spec['step'] * step_jitter,
            angle_deg=spec['angle'] + ang_jitter,
            start_x=sx, start_y=sy,
            start_heading=heading)
        # Overlay: non-zero tile pixels overwrite img (so trees can stack).
        nonzero = tile > 0
        img[nonzero] = tile[nonzero]
    return img.ravel()
