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


def colourise_posterized(escape: np.ndarray, iter_cap: int,
                          palette4: Sequence[Sequence[int]],
                          bin1: float, bin2: float) -> np.ndarray:
    """4-colour posterise.  Bucket 3 = in-set; buckets 0/1/2 = finite
    escapes split at ``bin1`` and ``bin2``.  Mirrors loupe.js
    renderPosterized so server-side prints match the browser preview
    pixel-for-pixel given the same (cx, cy, span, palette, bins)."""
    pal = np.asarray(palette4, dtype=np.uint8)
    if pal.shape[0] != 4:
        raise ValueError(f'posterised palette needs 4 colours, got {pal.shape[0]}')
    bucket = np.where(escape < bin1, 0,
              np.where(escape < bin2, 1, 2))
    bucket = np.where(escape >= iter_cap, 3, bucket)
    rgb = pal[bucket]
    return rgb.astype(np.uint8)


def render_mandelbrot_posterized_png(cx: float, cy: float, span: float,
                                       w: int, h: int,
                                       palette4: Sequence[Sequence[int]],
                                       bin1: float, bin2: float,
                                       *, iter_cap: int | None = None
                                       ) -> bytes:
    """End-to-end PNG render in 4-colour posterise mode."""
    iter_cap = iter_cap or auto_iter(span)
    escape = mandelbrot_escape(cx, cy, span, w, h, iter_cap)
    rgb = colourise_posterized(escape, iter_cap, palette4, bin1, bin2)
    img = Image.fromarray(rgb, mode='RGB')
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def default_poster_palette() -> tuple[tuple[int, int, int], ...]:
    """A reasonable 4-colour palette when the caller asks for posterize
    without specifying one — picked so the four buckets are visually
    distinct on both screen and paper."""
    return (
        ( 30,  40, 100),    # bucket 0 — deep navy (low escape)
        (200, 110,  40),    # bucket 1 — burnt orange
        (245, 215,  85),    # bucket 2 — sand
        ( 18,  18,  20),    # bucket 3 — in-set
    )


def mandelbrot_buckets(cx: float, cy: float, span: float,
                        w: int, h: int,
                        *, iter_cap: int | None = None) -> np.ndarray:
    """4-colour bucket array (0..3, uint8) for a Mandelbrot region.
    Same auto-binning the posterised PNG renderer uses, but returns
    the *labels* directly so callers can feed the array straight into
    a K=4 CA without going via PNG → RGB → quantize.

    Used by gridprint to seed the spoeqi CA print with a Mandelbrot
    walk's final image instead of an LCG-random initial state.
    """
    iter_cap = iter_cap or auto_iter(span)
    escape   = mandelbrot_escape(cx, cy, span, w, h, iter_cap)
    finite   = escape[escape < iter_cap]
    if finite.size < 3:
        bin1, bin2 = iter_cap / 3.0, 2.0 * iter_cap / 3.0
    else:
        sorted_f = np.sort(finite)
        bin1 = float(sorted_f[len(sorted_f) // 3])
        bin2 = float(sorted_f[2 * len(sorted_f) // 3])
        if bin2 <= bin1:
            bin2 = bin1 + 1
    bucket = np.where(escape < bin1, 0,
              np.where(escape < bin2, 1, 2))
    bucket = np.where(escape >= iter_cap, 3, bucket)
    return bucket.astype(np.uint8)


def render_mandelbrot_posterized_auto_png(cx: float, cy: float, span: float,
                                            w: int, h: int,
                                            palette4: Sequence[Sequence[int]],
                                            *, iter_cap: int | None = None
                                            ) -> bytes:
    """Same as render_mandelbrot_posterized_png but derives the bin
    boundaries from the escape array's 1/3 and 2/3 quantiles — mirrors
    loupe.js renderPosterized's auto-bin behaviour so a server-side
    print without explicit bins still buckets sensibly for any zoom."""
    iter_cap = iter_cap or auto_iter(span)
    escape   = mandelbrot_escape(cx, cy, span, w, h, iter_cap)
    finite   = escape[escape < iter_cap]
    if finite.size < 3:
        bin1, bin2 = iter_cap / 3.0, 2.0 * iter_cap / 3.0
    else:
        # Quantile-based binning so each visible bucket carries roughly
        # equal pixel area regardless of how deep the zoom is.
        sorted_f = np.sort(finite)
        bin1 = float(sorted_f[len(sorted_f) // 3])
        bin2 = float(sorted_f[2 * len(sorted_f) // 3])
        if bin2 <= bin1:
            bin2 = bin1 + 1
    rgb = colourise_posterized(escape, iter_cap, palette4, bin1, bin2)
    img = Image.fromarray(rgb, mode='RGB')
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()
