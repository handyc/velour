"""Server-side Mandelbrot renderer.

Used by the gridprint and escher bridges so the printed / tiled
output is high-resolution rather than the 128×128 thumbnail stored
on the Walk.  Vectorised in numpy; ~80 ms for 1024×1024 @ 256 iter
on a laptop.

Output is a PNG byte string.  Callers wrap it however they like
(an ``<image href="...">`` reference for SVG bridges, an explicit
HttpResponse for the standalone endpoint).
"""

from __future__ import annotations

import io
from typing import Iterable, Sequence

import numpy as np
from PIL import Image


# Default palette mirrors loupe.js's DEFAULT_PALETTE: index 0 is the
# in-set sentinel (forced black), 1..N are the escape-time bands.
DEFAULT_PALETTE: Sequence[Sequence[int]] = (
    (  0,   0,   0),
    ( 25,   7,  26), ( 30,  20,  90), ( 50,  50, 130), ( 90,  90, 180),
    (120, 150, 220), (180, 200, 240), (240, 220, 180), (240, 180,  80),
    (220, 120,  30), (180,  70,  20), (120,  40,  20), ( 70,  20,  30),
    ( 60,  60,  60), (120, 120, 120), (200, 200, 200),
)


def auto_iter(span: float, base: int = 192, cap: int = 4096) -> int:
    """Match LoupeEngine.retune(): +64 per halving below span=1."""
    n = base
    s = float(span)
    while s < 1.0 and n < cap:
        n += 64
        s *= 2.0
    return min(n, cap)


def mandelbrot_escape(cx: float, cy: float, span: float,
                       w: int, h: int, iter_cap: int) -> np.ndarray:
    """Return an ``(h, w)`` int32 array of escape counts.  Values
    equal to ``iter_cap`` indicate in-set pixels."""
    s = span / w
    ox = cx - s * w * 0.5
    oy = cy - s * h * 0.5
    xs = ox + np.arange(w, dtype=np.float64) * s
    ys = oy + np.arange(h, dtype=np.float64) * s
    C = xs[None, :] + 1j * ys[:, None]
    Z = np.zeros_like(C)
    out = np.full(C.shape, iter_cap, dtype=np.int32)
    active = np.ones(C.shape, dtype=bool)
    for i in range(iter_cap):
        Za = Z[active]
        Ca = C[active]
        Zn = Za * Za + Ca
        # Detect divergence on the active subset.
        mag2 = (Zn.real * Zn.real + Zn.imag * Zn.imag)
        diverged = mag2 > 4.0
        idx = np.where(active)
        # Mark escape time for newly-diverged pixels.
        flat_active = np.zeros(C.shape, dtype=bool)
        flat_active[idx] = diverged
        out[flat_active] = i
        # Update Z only for those still active.
        Z[active] = Zn
        # Drop diverged pixels from the active mask so we stop computing.
        active[idx] = ~diverged
        if not active.any():
            break
    return out


def colourise(escape: np.ndarray, iter_cap: int,
                palette: Sequence[Sequence[int]]) -> np.ndarray:
    """Map an escape-time array to (h, w, 3) uint8.  In-set → black."""
    pal = np.asarray(palette, dtype=np.uint8)
    n_colours = max(1, pal.shape[0] - 1)
    # Cycle palette[1..] over escape counts; in-set forced to palette[0]
    # which the renderer convention paints black.
    idx = 1 + (escape % n_colours)
    idx = np.where(escape >= iter_cap, 0, idx)
    rgb = pal[idx]
    return rgb.astype(np.uint8)


def render_mandelbrot_png(cx: float, cy: float, span: float,
                            w: int, h: int,
                            *, iter_cap: int | None = None,
                            palette: Sequence[Sequence[int]] | None = None
                            ) -> bytes:
    """End-to-end PNG render of one Mandelbrot view."""
    iter_cap = iter_cap or auto_iter(span)
    escape = mandelbrot_escape(cx, cy, span, w, h, iter_cap)
    rgb = colourise(escape, iter_cap, palette or DEFAULT_PALETTE)
    img = Image.fromarray(rgb, mode='RGB')
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()
