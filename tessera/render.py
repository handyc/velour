"""Tessera image generation: 4 toroidally-tileable color sources →
inverse-distance composite → 256-tile complete Wang set.

The math, condensed:

  ─ Each edge color c has a single source image S_c of size W×H,
    constructed to be torus-wrapping (S_c(0,y) ≡ S_c(W-1,y), and
    likewise vertically).
  ─ Tile (n, e, s, w) at pixel (x, y) is the inverse-distance-
    weighted blend of S_n, S_e, S_s, S_w sampled at (x, y):

        wN = 1 / (y + ε)^p
        wE = 1 / (W-1 - x + ε)^p
        wS = 1 / (H-1 - y + ε)^p
        wW = 1 / (x + ε)^p

        pixel = (wN·S_n + wE·S_e + wS·S_s + wW·S_w) / (wN+wE+wS+wW)

  ─ At y=0 the wN term diverges; the limit is pixel = S_n(x, 0).
    Vertically adjacent tile B with N=c samples S_c(x, 0) along
    its top row.  Tile A above with S=c samples S_c(x, H-1) along
    its bottom row.  Toroidal wrap of S_c gives S_c(x, H-1) ≡
    S_c(x, 0), so the seam is identical pixel-for-pixel.

  ─ Same argument for left/right edges.  Corner pixels are 0/0
    in the IDW limit (two infinities), but they collapse to the
    average of the two corner-meeting sources, which is again
    deterministic and matches across the four-corner meeting of
    any compatible 2×2 tile patch.

So if S_c is genuinely toroidal, every Wang-legal tiling produced
by any subset of the 256 tiles is seamless by construction — no
post-processing, no Poisson blending, no dual-mesh tricks.

Source generation strategy: low-octave fBm noise with toroidally
wrapping basis (sum of cos waves with integer frequencies inside
[0, W) so the texture wraps exactly), then colorised toward the
palette anchor.  Cheap, deterministic, and tileable by maths
rather than by stitching.
"""
from __future__ import annotations

import io
import math

import numpy as np
from PIL import Image, ImageFilter


# ---------------------------------------------------------------
# Source images — one per edge color.
# ---------------------------------------------------------------

def _tileable_fbm(rng: np.random.Generator, w: int, h: int,
                  octaves: int = 4) -> np.ndarray:
    """Toroidally-tileable fBm in [0, 1].

    Period is chosen as (w-1, h-1) instead of (w, h) so the basis
    cosines satisfy cos(2π·f·0) ≡ cos(2π·f·(w-1)/(w-1)) — i.e.,
    array column 0 and column w-1 carry the same value, and ditto
    for rows.  That makes the seam between two tiles exactly byte-
    identical (left tile's column w-1 sources from S_c[y, w-1] and
    the right tile's column 0 sources from S_c[y, 0], and those
    are the same number now).
    """
    yy, xx = np.meshgrid(
        np.arange(h, dtype=np.float64),
        np.arange(w, dtype=np.float64),
        indexing='ij',
    )
    Wp = max(w - 1, 1)
    Hp = max(h - 1, 1)
    out = np.zeros((h, w), dtype=np.float64)
    amp = 1.0
    for o in range(octaves):
        # Integer frequency scaling so the wave wraps exactly.
        fx = (1 << o)
        fy = (1 << o)
        ph_x = rng.random() * 2 * math.pi
        ph_y = rng.random() * 2 * math.pi
        amplitude_x = rng.random() + 0.3
        amplitude_y = rng.random() + 0.3
        layer = (
            amplitude_x * np.cos(2 * math.pi * fx * xx / Wp + ph_x) +
            amplitude_y * np.cos(2 * math.pi * fy * yy / Hp + ph_y) +
            0.6 * np.cos(2 * math.pi * fx * xx / Wp + ph_x) *
                  np.cos(2 * math.pi * fy * yy / Hp + ph_y)
        )
        out += amp * layer
        amp *= 0.55
    lo, hi = out.min(), out.max()
    if hi - lo < 1e-9:
        out = np.full_like(out, 0.5)
    else:
        out = (out - lo) / (hi - lo)
    return out


def _domain_warped(rng: np.random.Generator, w: int, h: int) -> np.ndarray:
    """Domain-warped fBm: sample fBm at (x + α·fBm₂(x,y), y + α·fBm₃)
    so the warped field still tiles (because both fBm sources tile),
    but the visual reads as more "organic" with branching/swirling.
    """
    base = _tileable_fbm(rng, w, h, octaves=4)
    warp_u = _tileable_fbm(rng, w, h, octaves=3)
    warp_v = _tileable_fbm(rng, w, h, octaves=3)
    yy, xx = np.meshgrid(np.arange(h), np.arange(w), indexing='ij')
    # Warp amplitude in pixels — kept small so the wrap-period
    # arithmetic still holds at the boundary.
    amp = min(w, h) * 0.12
    Wp = max(w - 1, 1)
    Hp = max(h - 1, 1)
    sx = (xx + amp * (warp_u - 0.5)) % Wp
    sy = (yy + amp * (warp_v - 0.5)) % Hp
    # Bilinear sample of `base` at (sx, sy) with the period-(W-1)
    # wrap that matches _tileable_fbm above (so column 0 and column
    # W-1 of the warped result are still byte-identical).
    x0 = sx.astype(np.int64)
    y0 = sy.astype(np.int64)
    x1 = (x0 + 1) % Wp
    y1 = (y0 + 1) % Hp
    fx = sx - x0
    fy = sy - y0
    out = (base[y0, x0] * (1 - fx) * (1 - fy) +
           base[y0, x1] *      fx  * (1 - fy) +
           base[y1, x0] * (1 - fx) *      fy  +
           base[y1, x1] *      fx  *      fy)
    return out


def _hex_ca_field(rng: np.random.Generator, w: int, h: int) -> np.ndarray:
    """4-color hex-ish CA evolved on a toroidal grid.

    Simple totalistic rule on an offset-r hex topology with periodic
    wrap; produces blobby class-1/3 patterns that share Velour's
    visual vocabulary with the rest of the suite.  Output is the
    cell value normalised to [0, 1].
    """
    # Random initial configuration.
    grid = rng.integers(0, 4, size=(h, w), dtype=np.int8)
    # Random totalistic rule table indexed by (self*7 + sum_neighbours)
    # — small lookup keeps the output stable across runs of the same
    # seed.
    rule = rng.integers(0, 4, size=(4 * (4 * 6 + 1),), dtype=np.int8)
    for _ in range(8):
        # Six hex neighbours with wrap.  Even rows: NW=(-1,-1), NE=(0,-1),
        # E=(1,0), SE=(0,1), SW=(-1,1), W=(-1,0).  Odd rows shift +1 in x
        # for the diagonal neighbours.  np.roll handles the toroidal wrap.
        n_nw_e = np.roll(grid, ( 1,  1), axis=(0, 1))
        n_ne_e = np.roll(grid, ( 1,  0), axis=(0, 1))
        n_nw_o = np.roll(grid, ( 1,  0), axis=(0, 1))
        n_ne_o = np.roll(grid, ( 1, -1), axis=(0, 1))
        n_w    = np.roll(grid, ( 0,  1), axis=(0, 1))
        n_e    = np.roll(grid, ( 0, -1), axis=(0, 1))
        n_sw_e = np.roll(grid, (-1,  1), axis=(0, 1))
        n_se_e = np.roll(grid, (-1,  0), axis=(0, 1))
        n_sw_o = np.roll(grid, (-1,  0), axis=(0, 1))
        n_se_o = np.roll(grid, (-1, -1), axis=(0, 1))
        # Even rows pick the *_e variants, odd rows the *_o.
        odd = (np.arange(h) & 1).astype(bool)[:, None]
        nw = np.where(odd, n_nw_o, n_nw_e)
        ne = np.where(odd, n_ne_o, n_ne_e)
        sw = np.where(odd, n_sw_o, n_sw_e)
        se = np.where(odd, n_se_o, n_se_e)
        nsum = nw + ne + n_w + n_e + sw + se
        idx = grid.astype(np.int32) * (4 * 6 + 1) + nsum.astype(np.int32)
        grid = rule[idx % rule.size]
    return grid.astype(np.float64) / 3.0


def make_source_images(seed: int, palette, w: int, h: int,
                       method: str = 'fbm-tileable') -> list[np.ndarray]:
    """Return 4 toroidally-tileable RGB source images, one per color.

    Each image is the tile-color anchor RGB modulated by a tileable
    scalar field; the anchors give the four edges visually distinct
    moods, the field gives every tile its own internal grain.
    """
    sources: list[np.ndarray] = []
    for c, anchor in enumerate(palette[:4]):
        # Per-color sub-seed so neighbouring colors diverge but
        # remain reproducible from the master seed.
        rng = np.random.default_rng(np.int64(seed) * 7919 + c * 31 + 1)
        if method == 'hex-ca':
            field = _hex_ca_field(rng, w, h)
        elif method == 'domain-warp':
            field = _domain_warped(rng, w, h)
        else:
            field = _tileable_fbm(rng, w, h, octaves=4)
        # Modulate the RGB anchor by the field.  Mix between
        # `anchor * 0.55` (dim) and `anchor * 1.0 + 40 highlight`
        # (bright) so the field looks like depth shading.
        anchor = np.asarray(anchor, dtype=np.float64)
        dim    = anchor * 0.45
        bright = np.minimum(anchor * 1.05 + 35, 255)
        f = field[..., None]
        rgb = dim * (1 - f) + bright * f
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        sources.append(rgb)
    return sources


# ---------------------------------------------------------------
# Tile compositing — IDW from 4 edges.
# ---------------------------------------------------------------

def composite_tile(sources, n: int, e: int, s: int, w: int,
                   power: float = 2.0,
                   blur_sigma: float = 0.0) -> np.ndarray:
    """Inverse-distance blend the 4 edge sources into one tile.

    Identical pixels at boundary rows/columns of adjacent tiles
    follow from S_n / S_s / S_e / S_w being toroidal copies of the
    same per-color source.  See the module docstring for the
    seam-cancellation argument.
    """
    H, W = sources[0].shape[:2]
    yy, xx = np.meshgrid(
        np.arange(H, dtype=np.float64),
        np.arange(W, dtype=np.float64),
        indexing='ij',
    )
    # ε keeps the centre pixel from going to NaN at exact midline
    # crossings; small enough that the edges still dominate.
    eps = 0.5
    dN = (yy + eps) ** power
    dS = ((H - 1 - yy) + eps) ** power
    dE = ((W - 1 - xx) + eps) ** power
    dW = (xx + eps) ** power
    wN = 1.0 / dN
    wE = 1.0 / dE
    wS = 1.0 / dS
    wW = 1.0 / dW
    total = (wN + wE + wS + wW)[..., None]
    out = (
        sources[n].astype(np.float64) * wN[..., None] +
        sources[e].astype(np.float64) * wE[..., None] +
        sources[s].astype(np.float64) * wS[..., None] +
        sources[w].astype(np.float64) * wW[..., None]
    ) / total
    out = np.clip(out, 0, 255).astype(np.uint8)
    if blur_sigma > 0:
        img = Image.fromarray(out)
        img = img.filter(ImageFilter.GaussianBlur(radius=blur_sigma))
        out = np.asarray(img)
    return out


def png_bytes(arr: np.ndarray) -> bytes:
    """Encode a uint8 HxWx3 array as PNG bytes."""
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format='PNG', optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------
# Convenience: cache + retrieve.
# ---------------------------------------------------------------

# In-process cache keyed by (set_id, set.updated_marker) so view
# requests don't regenerate the 4 source images on every PNG hit.
# Keeps a small bounded set in memory; the OS file cache handles
# the rest if a disk cache is wired up later.
_SRC_CACHE: dict = {}
_SRC_CACHE_MAX = 8


def get_sources_for(tess_set):
    """Memoised source-image build for one TessSet."""
    key = (tess_set.pk, tess_set.seed, tess_set.tile_px,
           tess_set.method, tuple(map(tuple, tess_set.palette)))
    cached = _SRC_CACHE.get(key)
    if cached is not None:
        return cached
    if len(_SRC_CACHE) >= _SRC_CACHE_MAX:
        _SRC_CACHE.pop(next(iter(_SRC_CACHE)))
    sources = make_source_images(
        tess_set.seed, tess_set.palette,
        tess_set.tile_px, tess_set.tile_px,
        method=tess_set.method,
    )
    _SRC_CACHE[key] = sources
    return sources
