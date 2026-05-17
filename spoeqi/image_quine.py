"""Image → K=4 hex CA rule LUT — posterize-and-test.

Given any image, posterize to 4 colours, resize to 128×128 so the
result lays out as a 16,384-entry hex CA LUT (4^7 entries), and run
the standard quine scoring (self_reproduce_score, sr_arbitrary_sigma,
classify_rule, chain walk).

The bijection here is the same one used everywhere else in spoeqi:
``rule_arr.reshape(128, 128)`` IS the rule's own initial state, so
"image-as-rule" and "rule-as-image" are the same operation.

If an uploaded image happens to be a quine when interpreted this way,
it goes into the regular ``ComponentChampion(class4_quine)`` archive
with provenance ``origin='image-upload'``.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Optional

import numpy as np


GRID_SIDE = 128            # 4^7 = 16_384 = 128*128 exactly
LUT_SIZE  = GRID_SIDE * GRID_SIDE
N_COLORS  = 4              # K=4 hex CA


@dataclass
class ImageRule:
    """The output of converting an image to a candidate rule LUT."""
    rule_bytes: bytes                  # 16,384 cells, values 0..3
    palette_rgb: list[tuple[int, int, int]]  # 4 RGB tuples (final palette)
    preview_png: bytes                 # 128×128 PNG of the posterized image
    src_size: tuple[int, int]          # original image (w, h)
    quantize_method: str               # 'median_cut' | 'kmeans' | …


def _open_rgb(file_bytes: bytes):
    """Decode any browser-friendly image to a PIL RGB Image."""
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(file_bytes))
    im.load()
    # EXIF orientation can flip portraits; respect it.
    im = ImageOps.exif_transpose(im)
    if im.mode != 'RGB':
        im = im.convert('RGB')
    return im


def _crop_centre_square(im):
    """Centre-crop to a square so the 128×128 resize doesn't squash."""
    w, h = im.size
    side = min(w, h)
    left = (w - side) // 2
    top  = (h - side) // 2
    return im.crop((left, top, left + side, top + side))


def _posterize_to_4(im, *, method: str = 'median_cut'):
    """Reduce to 4 distinct palette indices on a 128×128 grid.

    Returns (idx_arr uint8 0..3 shape (128,128), palette list[(r,g,b)]).

    ``method='median_cut'`` uses PIL's median-cut quantizer (built-in,
    deterministic on the same image+method).  ``method='kmeans'`` uses
    PIL's kmeans-based quantizer (slower, often better perceptual fit).
    """
    from PIL import Image
    im_sq = _crop_centre_square(im)
    im_small = im_sq.resize((GRID_SIDE, GRID_SIDE), Image.LANCZOS)
    if method == 'kmeans':
        # PIL's kmeans flag (kmeans=N → N kmeans passes after quantize).
        q = im_small.quantize(colors=N_COLORS, method=Image.MEDIANCUT,
                                kmeans=3)
    elif method == 'fast_octree':
        q = im_small.quantize(colors=N_COLORS, method=Image.FASTOCTREE)
    else:
        q = im_small.quantize(colors=N_COLORS, method=Image.MEDIANCUT)
    pal = q.getpalette()[:N_COLORS * 3]
    palette = [(pal[i*3], pal[i*3+1], pal[i*3+2]) for i in range(N_COLORS)]
    idx = np.asarray(q, dtype=np.uint8)
    # Pad with the most-common index if quantize returned <4 entries
    # (happens on near-monochrome images): map every >=K entry to 0.
    idx = np.clip(idx, 0, N_COLORS - 1)
    return idx, palette


def _render_preview_png(idx: np.ndarray,
                          palette: list[tuple[int, int, int]],
                          *, scale: int = 1) -> bytes:
    """128×128 (or scaled) PNG of the posterized grid."""
    from PIL import Image
    h, w = idx.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    pal_arr = np.array(palette, dtype=np.uint8)
    rgb[:] = pal_arr[idx]
    im = Image.fromarray(rgb, mode='RGB')
    if scale > 1:
        im = im.resize((w * scale, h * scale), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def image_to_rule(file_bytes: bytes, *,
                    quantize: str = 'median_cut',
                    preview_scale: int = 4) -> ImageRule:
    """Top-level pipeline: image bytes → 16,384-entry K=4 LUT."""
    im = _open_rgb(file_bytes)
    src_size = im.size
    idx, palette = _posterize_to_4(im, method=quantize)
    rule_bytes = bytes(idx.flatten())
    if len(rule_bytes) != LUT_SIZE:
        raise ValueError(
            f'internal error: posterised image yielded {len(rule_bytes)} '
            f'bytes, expected {LUT_SIZE}')
    preview = _render_preview_png(idx, palette, scale=preview_scale)
    return ImageRule(
        rule_bytes=rule_bytes,
        palette_rgb=palette,
        preview_png=preview,
        src_size=src_size,
        quantize_method=quantize)


def score_rule(rule_bytes: bytes, *,
                 sr_ticks: int = 16,
                 chain_depth: int = 20) -> dict:
    """Run the full quine-test battery on a rule LUT.

    Returns dict with: sr_strict, sr_arbsigma, c4, wolfram_class, act,
    chain_run_length, chain_distinct_levels.
    """
    from .metachain import (self_reproduce_score, sr_arbitrary_sigma,
                              classify_rule, probe_activity, walk_chain)
    if len(rule_bytes) != LUT_SIZE:
        raise ValueError(f'rule_bytes must be {LUT_SIZE} B; '
                         f'got {len(rule_bytes)}')
    sr = self_reproduce_score(rule_bytes, ticks=sr_ticks)
    arbs = sr_arbitrary_sigma(rule_bytes, ticks=sr_ticks)
    cls, c4 = classify_rule(rule_bytes, probe_ticks=24)
    act = probe_activity(rule_bytes, ticks=12)
    chain = walk_chain(rule_bytes, depth=chain_depth)
    return {
        'sr_strict':            float(sr),
        'sr_arbsigma':          float(arbs),
        'wolfram_class':        int(cls),
        'c4':                   float(c4),
        'act':                  float(act),
        'chain_run_length':     int(chain['class4_run_length']),
        'chain_distinct_levels': int(chain.get('distinct_levels', 0)),
    }


# ─── Persistence helpers ─────────────────────────────────────────────

# A rule from an arbitrary image is unlikely to hit SR>0.999, but it
# can still be a useful "soft quine" or an SR-arbsigma quine.  Use two
# bars: a hard one for the official class4_quine archive, and a softer
# one that the UI can flag as "interesting" without saving.
QUINE_SR_STRICT_THRESHOLD   = 0.99    # near-perfect fixed point
QUINE_SR_ARBSIGMA_THRESHOLD = 0.95    # high histogram-preserving
INTERESTING_SR_THRESHOLD    = 0.50    # better than K=4 random (~0.25)


def is_official_quine(scores: dict) -> bool:
    """Hard bar for adding to the regular class4_quine archive."""
    return (scores['sr_strict'] >= QUINE_SR_STRICT_THRESHOLD
              or scores['sr_arbsigma'] >= QUINE_SR_ARBSIGMA_THRESHOLD)


def is_interesting(scores: dict) -> bool:
    """Soft bar — worth showing to the user even if not archive-worthy."""
    return (scores['sr_strict']   >= INTERESTING_SR_THRESHOLD
              or scores['sr_arbsigma'] >= INTERESTING_SR_THRESHOLD)


def persist_image_quine(rule_bytes: bytes, *,
                          scores: dict,
                          image_label: str,
                          quantize_method: str,
                          src_size: tuple[int, int],
                          palette_rgb: list[tuple[int, int, int]]):
    """Save an image-derived quine to ComponentChampion(class4_quine).

    Returns the new (or existing) ComponentChampion instance.  Idempotent
    on (rule_bytes): a second upload of an identical image just hands
    back the original row.
    """
    import json
    from caformer.models import ComponentChampion
    existing = ComponentChampion.objects.filter(
        component_slug='class4_quine', rules_blob=rule_bytes).first()
    if existing:
        return existing, False
    pal_hex = ['#%02x%02x%02x' % rgb for rgb in palette_rgb]
    meta = {
        'origin':                'image-upload',
        'image_label':           image_label[:120],
        'quantize_method':       quantize_method,
        'src_size':              [int(src_size[0]), int(src_size[1])],
        'palette_rgb':           [list(rgb) for rgb in palette_rgb],
        'palette_hex':           pal_hex,
        'sr':                    scores['sr_strict'],
        'arbsigma':              scores['sr_arbsigma'],
        'c4':                    scores['c4'],
        'act':                   scores['act'],
        'class4_run_length':     scores['chain_run_length'],
        'distinct_levels':       scores['chain_distinct_levels'],
        'wolfram_class':         scores['wolfram_class'],
    }
    label = (f'img:{image_label[:30]}'.strip() or 'image-upload')[:40]
    obj = ComponentChampion.objects.create(
        component_slug='class4_quine',
        rules_blob=rule_bytes,
        rule_names_csv='image-upload',
        fitness=float(scores['sr_strict']),
        generation=0,
        run_label=label,
        ga_pop_size=0, ga_generations=0,
        eval_count=1,
        notes=json.dumps(meta),
    )
    return obj, True
