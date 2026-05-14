"""Holiday-album image-seeded pacts.

A user uploads N images (N ∈ {2, 4, 8, 16}).  Each image owns
``components_per_image = 64 // N`` of the pact's 64 components.
The image is split into ``k × k`` tiles where ``k = sqrt(components_per_image)``
(so 16-comp/image → 4×4 tile grid, 8 → ≈2.83 ⇒ 2x4 layout, etc.).
Each tile is quantized to 4 states under a single palette derived
from the whole album, and becomes the *target* initial-state of one
of that image's components.

A GA then searches for a (``seed_matrix``, ``rule_snapshot``,
``target_generation``) tuple whose CA, starting from seed and run
under the rule for ``target_generation`` ticks, produces tile states
close to the targets.  The resulting Pact's gen-T render shows the
album.  The seal is exactly that tuple — no salt; security is the
proof-of-work cost of the GA search.

Quantization is deterministic given the same input bytes — both
parties can recompute the targets from the same album to verify.

This module exposes:
- ``quantize_album(image_bytes_list, n, side)`` → target grids + palette
- ``evolve(targets, side, generations, pop_size, max_iters)`` →
  best (seed_bytes, rule_bytes, target_gen, fitness)
"""

from __future__ import annotations
import hashlib
import math
from dataclasses import dataclass
from io import BytesIO
from typing import Iterable, List, Sequence, Tuple

import numpy as np
from PIL import Image


# ─── Tile layout ─────────────────────────────────────────────────────

VALID_N = (1, 2, 4, 8, 16)


def album_layout(n: int) -> Tuple[int, int, int]:
    """For an album of N images, return (components_per_image, k_rows,
    k_cols) where the image is split into k_rows×k_cols tiles per
    image.  We always keep k_rows * k_cols = components_per_image.
    """
    if n not in VALID_N:
        raise ValueError(f'album size must be one of {VALID_N}, got {n}')
    cpi = 64 // n
    # Prefer square-ish layouts.
    if cpi == 64: return (64, 8, 8)   # n=1 → one image owns all 64 components
    if cpi == 32: return (32, 4, 8)
    if cpi == 16: return (16, 4, 4)
    if cpi ==  8: return ( 8, 2, 4)
    if cpi ==  4: return ( 4, 2, 2)
    raise AssertionError('unreachable')


# ─── Palette + quantize ─────────────────────────────────────────────

def album_palette(rgb_images: List[Image.Image], k: int = 4) -> np.ndarray:
    """Derive a single k-colour palette spanning the whole album by
    median-cut over a downsampled concatenation of all images.
    Deterministic given the same input bytes.
    Returns (k, 3) uint8.
    """
    # Concatenate all images horizontally after thumbnailing each so
    # the median cut sees the album as one mosaic.
    thumbs = []
    for img in rgb_images:
        t = img.copy()
        t.thumbnail((96, 96), Image.Resampling.LANCZOS)
        thumbs.append(t)
    max_h = max(t.size[1] for t in thumbs)
    canvas = Image.new('RGB', (sum(t.size[0] for t in thumbs), max_h), (0, 0, 0))
    x = 0
    for t in thumbs:
        canvas.paste(t, (x, 0))
        x += t.size[0]
    # Median-cut quantize.
    quant = canvas.quantize(colors=k, method=Image.Quantize.MEDIANCUT,
                             kmeans=0, dither=Image.Dither.NONE)
    pal_flat = quant.getpalette()[:k * 3]
    return np.asarray(pal_flat, dtype=np.uint8).reshape(k, 3)


def quantize_to_palette(img_rgb: Image.Image, palette: np.ndarray) -> np.ndarray:
    """Map every pixel of ``img_rgb`` to its nearest palette index.
    Deterministic.  Returns (H, W) uint8 array of indices 0..k-1.
    """
    arr = np.asarray(img_rgb, dtype=np.int32)         # (H, W, 3)
    p   = palette.astype(np.int32)                     # (k, 3)
    # Squared distance to each palette colour.
    d = ((arr[..., None, :] - p[None, None, :, :]) ** 2).sum(-1)  # (H, W, k)
    return d.argmin(-1).astype(np.uint8)


# ─── Image album → 64 target grids ──────────────────────────────────

@dataclass
class AlbumTargets:
    n_images:           int
    components_per_image: int
    k_rows:             int
    k_cols:             int
    side:               int
    palette_rgb:        np.ndarray             # (4, 3) uint8
    target_grids:       List[np.ndarray]       # 64 entries, each (side, side) uint8
    album_hash:         str                    # SHA-256 of the canonical concatenation


def _normalize_image_bytes(b: bytes) -> bytes:
    """Re-encode any input image bytes as a deterministic PNG so the
    album hash is stable across input file formats."""
    img = Image.open(BytesIO(b)).convert('RGB')
    buf = BytesIO()
    img.save(buf, format='PNG', optimize=False)
    return buf.getvalue()


def quantize_album(images_bytes: Sequence[bytes], side: int = 16
                    ) -> AlbumTargets:
    """Pipeline: list of image byte blobs → 64 quantized target grids,
    one per component, plus the album palette and a content hash."""
    n = len(images_bytes)
    cpi, kr, kc = album_layout(n)

    # Normalize and load.
    norm_bytes = [_normalize_image_bytes(b) for b in images_bytes]
    rgb_images = [Image.open(BytesIO(b)).convert('RGB') for b in norm_bytes]

    # Palette spans the whole album.
    palette = album_palette(rgb_images, k=4)

    # Hash inputs in album order so the album hash is order-sensitive.
    h = hashlib.sha256()
    for b in norm_bytes:
        h.update(b)
    album_hash = h.hexdigest()

    # For each image, resize to (kc * side, kr * side) and slice into
    # cpi tiles ordered row-major.
    target_grids: List[np.ndarray] = []
    target_w, target_h = kc * side, kr * side
    for img in rgb_images:
        img_resized = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        qi = quantize_to_palette(img_resized, palette)   # (target_h, target_w)
        for ty in range(kr):
            for tx in range(kc):
                tile = qi[ty*side:(ty+1)*side, tx*side:(tx+1)*side]
                target_grids.append(tile.astype(np.uint8))

    assert len(target_grids) == n * cpi == 64, \
        f'expected 64 tiles, got {len(target_grids)}'

    return AlbumTargets(
        n_images=n, components_per_image=cpi,
        k_rows=kr, k_cols=kc, side=side,
        palette_rgb=palette,
        target_grids=target_grids,
        album_hash=album_hash)


# ─── Pact derivation from album hash ──────────────────────────────
# All of (seed_matrix, rule_snapshot, supporting bytes) come from
# a SHA-256 chain rooted at the album hash, with domain-separated
# labels so different downstream uses don't overlap.  The pact's
# initial_grids field is set explicitly to the quantized target
# tiles so gen 0 renders as the cover album.

_RULE_TABLE_SIZE = 16384   # mirrors models.RULE_TABLE_SIZE


def _kdf_bytes(album_hash_bytes: bytes, label: bytes, n: int) -> bytes:
    """Deterministic byte sponge: SHA-256(album_hash || label || counter)
    chained until we have ``n`` bytes."""
    out = bytearray()
    counter = 0
    while len(out) < n:
        import hashlib, struct
        h = hashlib.sha256()
        h.update(album_hash_bytes)
        h.update(label)
        h.update(struct.pack('<I', counter))
        out.extend(h.digest())
        counter += 1
    return bytes(out[:n])


def derive_seed_and_rule(album_hash_hex: str) -> Tuple[bytes, bytes]:
    """From the album's SHA-256 hex, derive a (seed_matrix_64_bytes,
    rule_snapshot_16384_bytes) pair.  Same album → same bytes on
    every machine.  The rule is broadcast to all 64 components
    (shared-rule diversity).

    Rule bytes are masked to 0..3 because the 4-state CA only
    consumes the low 2 bits per entry; leaving the upper bits set
    would produce out-of-palette cell values once the CA ticks.
    """
    h_raw = bytes.fromhex(album_hash_hex)
    seed = _kdf_bytes(h_raw, b'spoeqi-album/seed/1', 64)
    raw_rule = _kdf_bytes(h_raw, b'spoeqi-album/rule/1', _RULE_TABLE_SIZE)
    rule = bytes(b & 0x03 for b in raw_rule)
    return seed, rule


def palette_to_pact_palette(rgb: np.ndarray) -> list:
    """Convert (4, 3) uint8 → ``[[r,g,b], ...]`` list-of-lists ready
    for Pact.palette JSON storage."""
    return [[int(c) for c in row] for row in rgb]


def targets_to_initial_grids(targets: AlbumTargets) -> list:
    """Convert the AlbumTargets' (side, side) uint8 ndarrays into the
    list-of-lists JSON shape Pact.initial_grids expects."""
    return [[int(v) for v in tile.flatten()] for tile in targets.target_grids]
