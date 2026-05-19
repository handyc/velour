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
