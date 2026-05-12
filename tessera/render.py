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
import os

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


def _make_toroidal(img: np.ndarray, blend_px: int = None) -> np.ndarray:
    """Cross-fade `img` against its own torus-rolled copies so the
    left/right and top/bottom seams of the resulting image match.

    User-uploaded photos aren't toroidal by construction; without
    this step, two adjacent tiles sampling the same uploaded source
    at x=0 vs x=W-1 would pull markedly different pixels and the
    seam would scream.  Blend width defaults to 12 % of the shorter
    side — large enough to hide a hard transition, small enough that
    the interior still reads as the original.
    """
    h, w = img.shape[:2]
    bp = blend_px if blend_px is not None else max(2, min(h, w) // 8)
    out = img.astype(np.float64).copy()
    # Horizontal seam: blend column 0..bp with rolled column (W-bp)..W
    rolled_x = np.roll(out, w // 2, axis=1)
    ramp_x = np.linspace(0, 1, bp)[None, :, None]   # (1, bp, 1)
    # Left edge: fade from rolled (which carries the right edge) to original.
    out[:, :bp] = rolled_x[:, :bp] * (1 - ramp_x) + out[:, :bp] * ramp_x
    # Right edge: fade from original to rolled (which carries the left edge).
    out[:, -bp:] = out[:, -bp:] * (1 - ramp_x[:, ::-1]) + rolled_x[:, -bp:] * ramp_x[:, ::-1]
    # Vertical seam
    rolled_y = np.roll(out, h // 2, axis=0)
    ramp_y = np.linspace(0, 1, bp)[:, None, None]   # (bp, 1, 1)
    out[:bp]  = rolled_y[:bp]  * (1 - ramp_y) + out[:bp]  * ramp_y
    out[-bp:] = out[-bp:] * (1 - ramp_y[::-1]) + rolled_y[-bp:] * ramp_y[::-1]
    return np.clip(out, 0, 255).astype(np.uint8)


def _load_upload(field_file, w: int, h: int) -> np.ndarray:
    """Open the ImageFieldFile, resize to (w, h), force RGB, make
    toroidal.  Returns a (h, w, 3) uint8 array."""
    img = Image.open(field_file.path).convert('RGB')
    img = img.resize((w, h), Image.Resampling.LANCZOS)
    arr = np.asarray(img, dtype=np.uint8)
    return _make_toroidal(arr)


def _palette_shift(rgb: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Apply a random hue rotation + saturation/value jitter in HSV.
    Returns a new (h, w, 3) uint8 array with the same structure but a
    different palette feel — used by `upload-1-palette` to derive
    four distinct colour-source images from one uploaded photo."""
    # Vectorised RGB→HSV→shifted→RGB.
    rgb_f = rgb.astype(np.float64) / 255.0
    r, g, b = rgb_f[..., 0], rgb_f[..., 1], rgb_f[..., 2]
    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    v = maxc
    s = np.where(maxc > 0, (maxc - minc) / np.maximum(maxc, 1e-9), 0)
    rc = (maxc - r) / np.maximum(maxc - minc, 1e-9)
    gc = (maxc - g) / np.maximum(maxc - minc, 1e-9)
    bc = (maxc - b) / np.maximum(maxc - minc, 1e-9)
    h = np.where(r == maxc, bc - gc,
        np.where(g == maxc, 2.0 + rc - bc, 4.0 + gc - rc))
    h = (h / 6.0) % 1.0
    h = np.where(maxc == minc, 0, h)
    # Random shifts.
    h = (h + rng.uniform(0, 1)) % 1.0
    s = np.clip(s * rng.uniform(0.5, 1.4), 0, 1)
    v = np.clip(v * rng.uniform(0.7, 1.15), 0, 1)
    # HSV→RGB.
    i = (h * 6.0).astype(np.int64) % 6
    f = h * 6.0 - i
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    cond = [i == k for k in range(6)]
    r2 = np.select(cond, [v, q, p, p, t, v])
    g2 = np.select(cond, [t, v, v, q, p, p])
    b2 = np.select(cond, [p, p, t, v, v, q])
    out = np.stack([r2, g2, b2], axis=-1)
    return np.clip(out * 255, 0, 255).astype(np.uint8)


def make_source_images(seed: int, palette, w: int, h: int,
                       method: str = 'fbm-tileable',
                       tess_set=None) -> list[np.ndarray]:
    """Return 4 toroidally-tileable RGB source images, one per color.

    For procedural methods, each image is the tile-color anchor RGB
    modulated by a tileable scalar field.  For upload methods, the
    user-provided image(s) are resized + edge-blended to be toroidal
    and used directly (palette is ignored).
    """
    # Upload paths: bypass procedural generation entirely.
    if method == 'upload-4' and tess_set is not None:
        slots = [tess_set.upload_a, tess_set.upload_b,
                 tess_set.upload_c, tess_set.upload_d]
        sources = []
        for slot in slots:
            if slot and slot.name:
                sources.append(_load_upload(slot, w, h))
            else:
                # Missing slot: fall back to a flat grey so the tile
                # still renders.  User notices and re-uploads.
                sources.append(np.full((h, w, 3), 128, dtype=np.uint8))
        return sources
    if method == 'upload-1-palette' and tess_set is not None:
        if tess_set.upload_a and tess_set.upload_a.name:
            base = _load_upload(tess_set.upload_a, w, h)
        else:
            base = np.full((h, w, 3), 128, dtype=np.uint8)
        sources = []
        for c in range(4):
            rng = np.random.default_rng(np.int64(seed) * 7919 + c * 31 + 1)
            sources.append(_palette_shift(base, rng))
        return sources

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

# ── Hex geometry ────────────────────────────────────────────────────
#
# Pointy-top hex inscribed in a (W, H) box, centred at (cx, cy) =
# ((W-1)/2, (H-1)/2).  Six vertices, counted clockwise from the top:
#   k=0  (cx,         cy - R)               top
#   k=1  (cx + R·s,   cy - R/2)             top-right
#   k=2  (cx + R·s,   cy + R/2)             bottom-right
#   k=3  (cx,         cy + R)               bottom
#   k=4  (cx - R·s,   cy + R/2)             bottom-left
#   k=5  (cx - R·s,   cy - R/2)             top-left
# where s = sqrt(3)/2 and R is the circumradius — chosen so the hex
# fits inside (W, H).
#
# Edge i runs from vertex i to vertex (i+1) % 6, clockwise.

_HEX_SQRT3_2 = 0.8660254037844386

# Bump RENDER_VERSION whenever the rendering math changes so the
# templates can append ?v=N to PNG URLs and force browsers off the
# stale immutable cache entries left by previous revisions.
RENDER_VERSION = 4


def _hex_geometry(w: int, h: int):
    """Return (cx, cy, R, vertices) where vertices is a (6, 2) array
    of (x, y) for the hexagon inscribed in a (w, h) rectangle."""
    cx = (w - 1) / 2.0
    cy = (h - 1) / 2.0
    # Pointy-top hexagon's bounding box is (2 R · sqrt(3)/2, 2 R) =
    # (R·sqrt(3), 2 R).  Fit into (w, h) by taking the binding axis.
    R = min((w - 1) / (2 * _HEX_SQRT3_2), (h - 1) / 2.0)
    verts = np.array([
        [cx,                    cy - R],
        [cx + R * _HEX_SQRT3_2, cy - R / 2],
        [cx + R * _HEX_SQRT3_2, cy + R / 2],
        [cx,                    cy + R],
        [cx - R * _HEX_SQRT3_2, cy + R / 2],
        [cx - R * _HEX_SQRT3_2, cy - R / 2],
    ], dtype=np.float64)
    return cx, cy, R, verts


def _hex_mask_and_edge_distances(w: int, h: int):
    """For an (h, w) pixel grid: build a boolean inside-hexagon mask
    AND a (6, h, w) array of perpendicular distances to each of the
    six edges (positive on the inside, negative outside).  Pixels
    outside the hex get masked out by the caller."""
    cx, cy, R, verts = _hex_geometry(w, h)
    yy, xx = np.meshgrid(np.arange(h, dtype=np.float64),
                         np.arange(w, dtype=np.float64), indexing='ij')
    # For each edge i: signed distance = (P - V_i) · n_i  where n_i is
    # the inward unit normal.  Inward normal points from the edge
    # midpoint toward the hex centre.
    dists = np.zeros((6, h, w), dtype=np.float64)
    for i in range(6):
        v0 = verts[i]
        v1 = verts[(i + 1) % 6]
        mid = (v0 + v1) / 2
        # Inward normal: unit vector from mid toward the centre.
        nx, ny = (cx - mid[0]), (cy - mid[1])
        L = (nx * nx + ny * ny) ** 0.5
        nx, ny = nx / L, ny / L
        dists[i] = (xx - mid[0]) * nx + (yy - mid[1]) * ny
    inside = np.all(dists > -0.5, axis=0)   # half-pixel slack
    return inside, dists


# ── Inverse-distance blend (square + hex) ───────────────────────────

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


def composite_tile_idw_hex(sources, edges, power: float = 2.0,
                           blur_sigma: float = 0.0,
                           magenta_outside: bool = True) -> np.ndarray:
    """6-edge IDW blend with a hex clip mask.

    `edges` is a 6-tuple of edge colours in [0, 3] for edges 0..5
    (clockwise from top).  Each interior pixel of the inscribed
    hexagon is the inverse-distance-weighted blend of the 6 edge
    sources — but unlike square Tessera, each edge does NOT sample
    the source at the tile-local coordinate.  Instead, every edge
    pulls a 1-D strip out of S_c's bottom row, parametrised by the
    pixel's projection onto that edge (with u flipped on edges 3..5
    so adjacent tiles agree on absolute u at the seam).  The IDW
    weights then blur the six strips into the smooth interior the
    user expects.

    Seam-cancellation for hex tiling: at edge i, d_i → 0 ⇒ w_i → ∞,
    so the boundary pixel collapses to S_{e_i}[H-1, eff_u·(W-1)].
    Two adjacent hex tiles sharing edge i ↔ (i+3) %% 6 see the same
    physical point with the same eff_u (the flip on i≥3 cancels the
    CW-frame reversal between neighbours) ⇒ identical pixel.

    Source coord y = (1 - d/apothem)·(H-1):  bottom row at the edge,
    top row at the centre, exactly as wedge-cut.  This gives a
    "hex-toroidal-equivalent" rendering on top of the existing
    rectangular-toroidal sources, without needing to regenerate
    sources on a hex domain."""
    H, W = sources[0].shape[:2]
    inside, dists = _hex_mask_and_edge_distances(W, H)
    cx, cy, R, verts = _hex_geometry(W, H)
    yy, xx = np.meshgrid(
        np.arange(H, dtype=np.float64),
        np.arange(W, dtype=np.float64),
        indexing='ij',
    )
    # apothem = perpendicular distance from centre to any edge of the
    # inscribed hex; depth coord = 0 at edge → H-1 at centre.
    apothem = R * _HEX_SQRT3_2
    # Weight floor `eps_w` sits inside d^p, NOT (d+eps)^p — the old
    # form left the dominant edge with only ≈99.87 % weight at the
    # seam (1 / (0+0.5)² = 4, with five other edges totalling ≈ 0.005),
    # which leaked ≈1–15 RGB across the boundary.  Floor inside d^p
    # gives 1 / eps_w ≈ 10⁶ at d=0 and ≈16 at d=0.5, so the edge
    # sample wins by ten-million-to-one near the boundary while the
    # blend in the interior is unchanged.
    eps_w = 1e-6
    half = 3  # edges 0..2 use eff_u = u; edges 3..5 use eff_u = 1-u
    out = np.zeros((H, W, 3), dtype=np.float64)
    total = np.zeros((H, W), dtype=np.float64)
    for i in range(6):
        v0 = verts[i]
        v1 = verts[(i + 1) % 6]
        evx, evy = v1[0] - v0[0], v1[1] - v0[1]
        edge_len = (evx * evx + evy * evy) ** 0.5
        ux_, uy_ = evx / edge_len, evy / edge_len
        u_i = ((xx - v0[0]) * ux_ + (yy - v0[1]) * uy_) / edge_len
        eff_u = u_i if i < half else (1.0 - u_i)
        eff_u = np.clip(eff_u, 0.0, 1.0)
        x_src = np.clip(eff_u * (W - 1), 0, W - 1).astype(np.int64)
        d_i = np.maximum(dists[i], 0.0)
        y_src = np.clip((1.0 - d_i / apothem) * (H - 1),
                        0, H - 1).astype(np.int64)
        w_i = 1.0 / (d_i ** power + eps_w)
        src = sources[edges[i]]
        out += src[y_src, x_src].astype(np.float64) * w_i[..., None]
        total += w_i
    out = out / total[..., None]
    if magenta_outside:
        bg = np.array([255, 0, 255], dtype=np.float64)
        out = np.where(inside[..., None], out, bg)
    out = np.clip(out, 0, 255).astype(np.uint8)
    if blur_sigma > 0:
        img = Image.fromarray(out)
        img = img.filter(ImageFilter.GaussianBlur(radius=blur_sigma))
        out = np.asarray(img)
    return out


# ── Wedge-cut (square + hex) ────────────────────────────────────────
#
# Each tile is divided into N triangular wedges meeting at the centre.
# Wedge i sources from S_{edge_color_i}'s bottom row — that 1D strip
# becomes the wedge's outer edge (the actual tile edge), and the
# interior linearly interpolates inward to the source image's top row
# at the apex (centre).  The "stained-glass" aesthetic the user
# described.
#
# Seam cancellation requires that the bottom row of each source image
# be effectively palindromic on its u-axis so adjacent tiles' wedges
# meeting at the same physical edge sample the same pixels — Tessera's
# toroidal sources already give S_c[*, 0] = S_c[*, W-1] which means the
# bottom row wraps cleanly, but isn't strictly palindromic.  Visible
# seam variance for wedge-cut is generally small but non-zero;
# documented honestly in the model help text.


def _wedge_uv(w: int, h: int, n_wedges: int):
    """For an (h, w) pixel grid, compute per-pixel (wedge_idx, u, v).

    `wedge_idx`: which of the N wedges this pixel belongs to.
    `u`: position along the outer edge of that wedge (0..1).
    `v`: depth from outer edge (0) to apex (1).

    Returns: (wedge_idx, u, v) all shape (h, w).  For square (N=4)
    the wedges are the 4 triangles formed by the centre and the
    midpoints of opposite edges; for hex (N=6) the 6 triangles
    meeting at the centre of an inscribed hexagon.  Pixels outside
    the inscribed shape (hex only) get wedge_idx=-1.
    """
    yy, xx = np.meshgrid(np.arange(h, dtype=np.float64),
                         np.arange(w, dtype=np.float64), indexing='ij')
    # Geometry first so we know V_0's position before angular indexing.
    if n_wedges == 6:
        cx, cy, R, verts = _hex_geometry(w, h)
        inside, _ = _hex_mask_and_edge_distances(w, h)
    else:
        # Square: vertices at the four corners (CW from NW so wedge 0
        # = NW→NE = top edge).
        cx = (w - 1) / 2.0
        cy = (h - 1) / 2.0
        R = max(w, h) / 2.0
        verts = np.array([
            [0,         0    ],   # NW       wedge 0 top edge: NW→NE
            [w - 1,     0    ],   # NE
            [w - 1, h - 1    ],   # SE
            [0,     h - 1    ],   # SW
        ], dtype=np.float64)
        inside = np.ones((h, w), dtype=bool)
    dx = xx - cx
    dy = yy - cy
    angle = np.arctan2(dy, dx)                    # (-π, π]
    # Map to "clockwise from V_0" 0..2π so wedge_idx = floor(...)
    # picks the wedge whose far edge runs V_i→V_{i+1}.  In screen
    # coords (y-down), CW means angle *increasing*, so the offset is
    # -atan2(V0.y-cy, V0.x-cx).  Hex: V_0 is at top, offset = π/2.
    # Square: V_0 is at NW, offset = 3π/4 (= wedge boundaries on the
    # diagonals).  Bug fix 2026-05-12: hardcoded offset = π/2 was
    # correct for hex but rotated square wedges 45°, scrambling
    # which edge colour each square wedge displayed and making
    # Wang-matched neighbours look mismatched even though propagation
    # was correct.
    v0_angle = math.atan2(verts[0, 1] - cy, verts[0, 0] - cx)
    a_norm = (angle - v0_angle) % (2 * np.pi)
    wedge_idx = np.floor(a_norm / (2 * np.pi / n_wedges)).astype(np.int64)
    wedge_idx = np.clip(wedge_idx, 0, n_wedges - 1)
    # Within each wedge, u is position along its outer edge and v is
    # depth from edge to centre.  Compute by projecting onto each
    # wedge's outer-edge frame.
    # The outer edge of wedge i runs between vertices V_i and V_{i+1};
    # u = projection along V_{i+1}-V_i normalised, v = 1 - (distance
    # from centre / radius).
    u = np.zeros_like(xx)
    v = np.zeros_like(xx)
    for i in range(n_wedges):
        v0 = verts[i]
        v1 = verts[(i + 1) % n_wedges]
        edge_vec = v1 - v0
        edge_len = (edge_vec[0] ** 2 + edge_vec[1] ** 2) ** 0.5
        edge_ux = edge_vec[0] / edge_len
        edge_uy = edge_vec[1] / edge_len
        mask = (wedge_idx == i)
        u_i = ((xx - v0[0]) * edge_ux + (yy - v0[1]) * edge_uy) / edge_len
        # Distance from centre along inward direction → v ∈ [0, 1].
        # v = 0 at outer edge (max distance), v = 1 at centre.
        # Approximate outer-edge distance via perpendicular distance
        # to the v0→v1 line, divided by the wedge's apothem.
        # Inward normal to edge i.
        nx_, ny_ = (cx - (v0[0] + v1[0]) / 2), (cy - (v0[1] + v1[1]) / 2)
        L = (nx_ * nx_ + ny_ * ny_) ** 0.5
        nx_, ny_ = nx_ / L, ny_ / L
        d_inward = (xx - v0[0]) * nx_ + (yy - v0[1]) * ny_
        # apothem (distance from centre to edge midpoint)
        ap = L
        v_i = np.clip(d_inward / ap, 0.0, 1.0)
        u = np.where(mask, np.clip(u_i, 0.0, 1.0), u)
        v = np.where(mask, v_i, v)
    wedge_idx[~inside] = -1
    return wedge_idx, u, v


def _wedge_render(sources, edges, n_wedges: int,
                  magenta_outside: bool = True) -> np.ndarray:
    """Common renderer: take the N-wedge layout for the topology, look
    each pixel up in the appropriate source by its (u, v) inside its
    wedge.

    Source coord: x = eff_u · (W-1)  with `eff_u` flipped on the back
    half of the edges; y = (1 - v) · (H-1)  (outer edge sources from
    row H-1, apex sources from row 0).

    Why the flip: two adjacent tiles share a physical edge but each
    parameterises it in its own CW frame, so tile L's u and tile R's u
    run in opposite directions on the same edge.  Flipping u for half
    the edges (i ≥ n_wedges/2) makes the *effective* u agree, so both
    tiles sample S_c's bottom row at the same column and the seam is
    pixel-identical when the Wang colours match.  Half-set assignment
    must be consistent under the (i ↔ (i+n_wedges/2)) partner pairing,
    which i<half / i≥half satisfies."""
    H, W = sources[0].shape[:2]
    wedge_idx, u, v = _wedge_uv(W, H, n_wedges)
    y_src = np.clip((1 - v) * (H - 1), 0, H - 1).astype(np.int64)
    out = np.zeros((H, W, 3), dtype=np.uint8)
    half = n_wedges // 2
    for i in range(n_wedges):
        eff_u = u if i < half else (1.0 - u)
        x_src_i = np.clip(eff_u * (W - 1), 0, W - 1).astype(np.int64)
        src = sources[edges[i]]
        mask = (wedge_idx == i)
        gathered = src[y_src, x_src_i]
        out = np.where(mask[..., None], gathered, out)
    if magenta_outside:
        bg = np.array([255, 0, 255], dtype=np.uint8)
        outside = (wedge_idx < 0)
        out = np.where(outside[..., None], bg, out)
    return out


def composite_tile_wedge_square(sources, edges,
                                blur_sigma: float = 0.0) -> np.ndarray:
    """4-wedge stained-glass square tile.  `edges` is (n, e, s, w)."""
    out = _wedge_render(sources, edges, 4, magenta_outside=False)
    if blur_sigma > 0:
        img = Image.fromarray(out)
        img = img.filter(ImageFilter.GaussianBlur(radius=blur_sigma))
        out = np.asarray(img)
    return out


def composite_tile_wedge_hex(sources, edges,
                             blur_sigma: float = 0.0,
                             magenta_outside: bool = True) -> np.ndarray:
    """6-wedge stained-glass hex tile.  `edges` is a 6-tuple."""
    out = _wedge_render(sources, edges, 6,
                        magenta_outside=magenta_outside)
    if blur_sigma > 0:
        img = Image.fromarray(out)
        img = img.filter(ImageFilter.GaussianBlur(radius=blur_sigma))
        out = np.asarray(img)
    return out


def composite_tile_for(tess_set, edges, blur_sigma: float = 0.0,
                       power: float = 2.0) -> np.ndarray:
    """Dispatch on (topology, blend_method).  `edges` is a 4-tuple
    for square or a 6-tuple for hex."""
    sources = get_sources_for(tess_set)
    if tess_set.topology == 'hex':
        if tess_set.blend_method == 'wedge':
            return composite_tile_wedge_hex(sources, edges,
                                            blur_sigma=blur_sigma)
        return composite_tile_idw_hex(sources, edges, power=power,
                                      blur_sigma=blur_sigma)
    # square
    if tess_set.blend_method == 'wedge':
        return composite_tile_wedge_square(sources, edges,
                                           blur_sigma=blur_sigma)
    n, e, s, w = edges
    return composite_tile(sources, n, e, s, w,
                          power=power, blur_sigma=blur_sigma)


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
    # Upload mtimes are part of the cache key so re-uploaded files
    # invalidate cleanly without an explicit bust.
    def _slot_key(slot):
        if slot and slot.name:
            try:
                return (slot.name, os.path.getmtime(slot.path))
            except OSError:
                return (slot.name, None)
        return None
    key = (tess_set.pk, tess_set.seed, tess_set.tile_px,
           tess_set.method, tuple(map(tuple, tess_set.palette)),
           _slot_key(tess_set.upload_a), _slot_key(tess_set.upload_b),
           _slot_key(tess_set.upload_c), _slot_key(tess_set.upload_d))
    cached = _SRC_CACHE.get(key)
    if cached is not None:
        return cached
    if len(_SRC_CACHE) >= _SRC_CACHE_MAX:
        _SRC_CACHE.pop(next(iter(_SRC_CACHE)))
    sources = make_source_images(
        tess_set.seed, tess_set.palette,
        tess_set.tile_px, tess_set.tile_px,
        method=tess_set.method,
        tess_set=tess_set,
    )
    _SRC_CACHE[key] = sources
    return sources
