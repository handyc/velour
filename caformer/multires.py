"""Multi-resolution scaling primitives for K=4 hex CA rule tables.

Two distinct use cases live in this module:

  1. **Lossy compression** of a trained 7→1 rule for cheaper storage.
     Treat the 16,384-byte LUT as a 128×128 image (the Ouroboros
     interpretation), aggregate (factor × factor) blocks via mode-
     voting, and store the result.  Reverse via nearest-neighbour
     upscaling when the rule is needed at full resolution again.
     Storage at b064 = 4 KiB (4×), b032 = 1 KiB (16×), b016 = 256 B
     (64×), b008 = 64 B (256×).

  2. **Small-table-as-corrector** (user framing 2026-05-19): a small
     rule trained specifically to fix one byte of output where the
     large rule fails.  Storage tiny (b008-b016 range); runs alongside
     the big rule; overrides at the corrector's target position.  See
     `train_corrector` below.

This module only implements (1) — the mechanical compression
primitives + a round-trip integrity check.  (2) is Phase B and gets
its own file (`caformer/corrector.py`) when we build it.
"""
from __future__ import annotations

import numpy as np


# ── Resolution ladder ─────────────────────────────────────────────────
#
# The natural Ouroboros board sides at each tier (powers of 2 from 128
# down).  Each tier's LUT-as-image fits exactly in a side × side board.

LADDER_SIDES   = (128, 64, 32, 16, 8)
LADDER_BYTES   = tuple(s * s for s in LADDER_SIDES)
# At factor=2 between adjacent tiers, an N×N LUT becomes (N/2)×(N/2)
# via 2×2 mode-voting.  Each step compresses 4×.

FACTOR_BETWEEN = 2  # adjacent tiers always differ by 2× per side


# ── Mode-vote aggregation (block reduction) ──────────────────────────

def mode_vote_block(block: np.ndarray) -> int:
    """Most-common K=4 value (0..3) in `block`.  Ties broken by lower
    value (deterministic).  Used per (factor × factor) block during
    downscaling."""
    counts = np.bincount(block.ravel().astype(np.int64), minlength=4)
    return int(np.argmax(counts))


def _downscale_image(img: np.ndarray, factor: int) -> np.ndarray:
    """Aggregate `img` by `factor × factor` blocks using mode-voting.
    `img` shape (H, W) uint8, H % factor == W % factor == 0.  Returns
    shape (H/factor, W/factor) uint8."""
    H, W = img.shape
    if H % factor or W % factor:
        raise ValueError(f'img shape {img.shape} not divisible by {factor}')
    h2, w2 = H // factor, W // factor
    out = np.zeros((h2, w2), dtype=np.uint8)
    for i in range(h2):
        for j in range(w2):
            block = img[i * factor:(i + 1) * factor,
                          j * factor:(j + 1) * factor]
            out[i, j] = mode_vote_block(block)
    return out


def _upscale_image(img: np.ndarray, factor: int) -> np.ndarray:
    """Nearest-neighbour expand each cell of `img` into a (factor ×
    factor) block.  Inverse of `_downscale_image` shape-wise."""
    return np.repeat(np.repeat(img, factor, axis=0), factor, axis=1)


# ── LUT-as-image ↔ rule bytes ────────────────────────────────────────

def lut_to_image(rule_bytes: bytes, side: int) -> np.ndarray:
    """Reshape `rule_bytes` (len = side*side) into a (side, side)
    K=4 image array."""
    arr = np.frombuffer(rule_bytes, dtype=np.uint8)
    if arr.size != side * side:
        raise ValueError(
            f'rule has {arr.size} bytes; expected {side * side} for side={side}')
    return arr.reshape(side, side).copy()


def image_to_lut(img: np.ndarray) -> bytes:
    """Inverse of `lut_to_image` — flatten and clamp to K=4 range."""
    return bytes((img.ravel() & 3).astype(np.uint8))


# ── Public API: downscale / upscale a rule across tiers ──────────────

def downscale_rule(rule_bytes: bytes, src_side: int,
                     dst_side: int) -> bytes:
    """Compress a rule's LUT-as-image from `src_side` × `src_side`
    down to `dst_side` × `dst_side` via stepwise 2× mode-vote
    aggregation.  Both sides must be powers of 2 from LADDER_SIDES
    with dst_side ≤ src_side.  Returns `dst_side * dst_side` bytes."""
    if src_side not in LADDER_SIDES or dst_side not in LADDER_SIDES:
        raise ValueError(
            f'sides must be in {LADDER_SIDES}; got {src_side} → {dst_side}')
    if dst_side > src_side:
        raise ValueError(
            f'downscale only goes smaller; got {src_side} → {dst_side}')
    img = lut_to_image(rule_bytes, src_side)
    side = src_side
    while side > dst_side:
        img = _downscale_image(img, FACTOR_BETWEEN)
        side //= FACTOR_BETWEEN
    return image_to_lut(img)


def upscale_rule(rule_bytes: bytes, src_side: int,
                   dst_side: int) -> bytes:
    """Inflate a compressed rule back to a larger LUT via nearest-
    neighbour expansion.  Every 1 source cell becomes a (2×2) block
    of identical values.  Lossy: the upscaled rule has only
    src_side*src_side distinct LUT entries quantised into the bigger
    LUT space, so all 4 entries in each expanded block fire the same
    way."""
    if src_side not in LADDER_SIDES or dst_side not in LADDER_SIDES:
        raise ValueError(
            f'sides must be in {LADDER_SIDES}; got {src_side} → {dst_side}')
    if dst_side < src_side:
        raise ValueError(
            f'upscale only goes larger; got {src_side} → {dst_side}')
    img = lut_to_image(rule_bytes, src_side)
    side = src_side
    while side < dst_side:
        img = _upscale_image(img, FACTOR_BETWEEN)
        side *= FACTOR_BETWEEN
    return image_to_lut(img)


# ── Round-trip integrity ─────────────────────────────────────────────

def round_trip(rule_bytes: bytes, src_side: int,
                  via_side: int) -> dict:
    """Downscale then upscale; compare to the original.  Returns
    distance metrics — useful as a calibration check on how lossy
    each tier is for a given rule."""
    if via_side >= src_side:
        raise ValueError(f'via_side {via_side} must be < src_side {src_side}')
    small = downscale_rule(rule_bytes, src_side, via_side)
    recovered = upscale_rule(small, via_side, src_side)
    a = np.frombuffer(rule_bytes, dtype=np.uint8)
    b = np.frombuffer(recovered, dtype=np.uint8)
    matches = int((a == b).sum())
    total = int(a.size)
    return {
        'src_side':       src_side,
        'via_side':       via_side,
        'src_bytes':      total,
        'compressed_bytes': via_side * via_side,
        'compression_ratio': total / (via_side * via_side),
        'cells_matching': matches,
        'cells_total':    total,
        'fidelity':       matches / total if total else 1.0,
    }


# ── Apply a downscaled rule on the original board ────────────────────
#
# To USE a compressed rule at full board size without retraining, the
# simplest path is upscale back to LADDER_BYTES[0] (16,384 entries)
# and feed to the standard `hex_ca_step`.  This loses precision —
# every 2×2 LUT block has identical fire behaviour after upscaling —
# but is enough to act as a coarse approximation.

def inflate_for_full_board(rule_bytes: bytes, src_side: int) -> np.ndarray:
    """Return the upscale-to-128 form of a compressed rule, ready to
    pass to `caformer.primitives.hex_ca_step` as a 16,384-entry LUT.
    No-op when src_side already 128."""
    full = upscale_rule(rule_bytes, src_side, LADDER_SIDES[0])
    return np.frombuffer(full, dtype=np.uint8).copy()


# ── Storage helpers for QRPair multires blobs ────────────────────────
#
# A pair stores N concatenated per-position rules at each tier.  Each
# rule is side*side bytes (1 cell = 1 byte at K=4 unpacked).  When
# all four optional tiers are present, total storage per pair is:
#
#   board128: N × 16,384 = baseline
#   b064:     N ×  4,096 = 25 %  of baseline
#   b032:     N ×  1,024 = 6.25 %
#   b016:     N ×    256 = 1.56 %
#   b008:     N ×     64 = 0.39 %
#                          ─────
#                         33.2 % of baseline total when all tiers stored.

def split_blob(blob: bytes, side: int) -> list:
    """Slice a concatenated per-position blob into a list of N rules
    of `side * side` bytes each."""
    rule_bytes = side * side
    if not blob:
        return []
    n = len(blob) // rule_bytes
    return [blob[i * rule_bytes:(i + 1) * rule_bytes] for i in range(n)]


def join_rules(rules: list, side: int) -> bytes:
    """Concatenate per-position rules back into a single blob.  Each
    rule must already be exactly `side * side` bytes."""
    expected = side * side
    for i, r in enumerate(rules):
        if len(r) != expected:
            raise ValueError(
                f'rule {i} is {len(r)} B; expected {expected} for side={side}')
    return b''.join(rules)


def downscale_pair_blob(blob: bytes, src_side: int,
                            dst_side: int) -> bytes:
    """Convenience: downscale every per-position rule in a pair's
    blob and return the joined smaller blob."""
    rules = split_blob(blob, src_side)
    small = [downscale_rule(r, src_side, dst_side) for r in rules]
    return join_rules(small, dst_side)


# ── Tier accessor for a QRPair ───────────────────────────────────────

def best_available_tier(pair) -> tuple:
    """Returns (side, blob, exact) for the highest-fidelity tier the
    given QRPair has stored.  Defaults to (None, None, False) when
    the pair has nothing.  Used by tier-aware dispatch."""
    if pair.board128_rules_blob:
        return (128, bytes(pair.board128_rules_blob), bool(pair.board128_exact))
    if pair.b064_rules_blob:
        return (64, bytes(pair.b064_rules_blob), False)
    if pair.b032_rules_blob:
        return (32, bytes(pair.b032_rules_blob), False)
    if pair.b016_rules_blob:
        return (16, bytes(pair.b016_rules_blob), False)
    if pair.b008_rules_blob:
        return (8, bytes(pair.b008_rules_blob), False)
    return (None, None, False)
