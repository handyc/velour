"""Tier-aware inference + comparison for board128 vs smaller boards.

Given a QRPair with rules at multiple resolutions (board128 + b064 +
b032 + b016 + b008), generate the response at each tier and compare:

  - byte-match rate vs target
  - wall-clock inference time
  - cell-update count

The dispatcher can serve at whichever tier is fast enough for the
current SLA — a fast tier for casual chat, the full tier for byte-
exact reproduction.
"""
from __future__ import annotations

import time

import numpy as np

from .board_multires import (decode_byte_at_position_tier,
                                    embed_prompt_tier, tier_geometry)
from .primitives import hex_ca_step


def _split_blob_per_position(blob: bytes) -> list:
    """Split a per-position chain blob into N × 16,384 byte arrays.
    Used by every tier — the LUT size is fixed at 16,384 across
    tiers; only the BOARD shrinks."""
    n = len(blob) // 16_384
    return [np.frombuffer(blob[i * 16_384:(i + 1) * 16_384],
                                  dtype=np.uint8).copy()
              for i in range(n)]


def inference_at_tier(prompt: str, blob: bytes, side: int,
                          *, expected: str = None,
                          n_ticks: int = None) -> dict:
    """Run a multi-position chain at a specific tier side.  Returns
    the produced bytes + wall + byte-match count if `expected`.

    Wall measures only the CA forward passes; the blob split and
    decode are constant-time."""
    if n_ticks is None:
        n_ticks = side
    rules = _split_blob_per_position(blob)
    if not rules:
        return {'produced_bytes': b'', 'wall': 0.0, 'n_rules': 0,
                'side': side, 'n_ticks': n_ticks,
                'byte_match': 0, 'n_target': 0, 'cell_updates': 0}

    state0 = embed_prompt_tier(prompt, side)
    out = bytearray()
    t0 = time.time()
    for pos, rule in enumerate(rules):
        state = state0.copy()
        for _ in range(n_ticks):
            state = hex_ca_step(state, rule)
        out.append(decode_byte_at_position_tier(state, pos, side))
    wall = time.time() - t0

    target_bytes = expected.encode('utf-8') if expected else b''
    n_target = min(len(target_bytes), len(rules))
    n_match  = sum(1 for i in range(n_target)
                       if out[i] == target_bytes[i])

    return {
        'produced_bytes':  bytes(out),
        'wall':            wall,
        'n_rules':         len(rules),
        'side':            side,
        'n_ticks':         n_ticks,
        'byte_match':      n_match,
        'n_target':        n_target,
        'cell_updates':    len(rules) * side * side * n_ticks,
    }


# ── Per-pair tier blob accessors ────────────────────────────────────

TIER_FIELDS = (
    (128, 'board128_rules_blob'),
    ( 64, 'b064_rules_blob'),
    ( 32, 'b032_rules_blob'),
    ( 16, 'b016_rules_blob'),
    (  8, 'b008_rules_blob'),
)


def available_tiers(pair) -> list:
    """List of (side, blob) pairs the QRPair has populated, biggest
    first.  Caller can choose any (e.g. smallest for cheap, biggest
    for byte-exact)."""
    out = []
    for side, field in TIER_FIELDS:
        blob = getattr(pair, field, None) or b''
        if blob:
            out.append((side, bytes(blob)))
    return out


def best_exact_tier(pair) -> tuple:
    """Pick the smallest tier whose chain produces the pair's expected
    response byte-exact.  Returns (side, blob) or (None, None) when
    no tier has an EXACT chain stored.

    Caches per (pair_id, updated_at) in process memory so back-to-
    back chat requests don't repeat the validation forward pass.
    """
    cache = getattr(best_exact_tier, '_cache', {})
    key = (pair.pk, pair.updated_at.timestamp() if pair.updated_at else 0)
    if key in cache:
        return cache[key]

    # Try tiers from smallest to largest (cheapest first).
    for side, blob in reversed(available_tiers(pair)):
        r = inference_at_tier(pair.prompt, blob, side,
                                  expected=pair.expected)
        if r['byte_match'] == r['n_target'] and r['n_target'] > 0:
            result = (side, blob)
            cache[key] = result
            best_exact_tier._cache = cache
            return result
    cache[key] = (None, None)
    best_exact_tier._cache = cache
    return (None, None)


def compare_all_tiers(pair) -> dict:
    """Run inference at every available tier and return a comparison
    table.  Used by /caformer/tier-compare/ to visualise speed vs
    fidelity trade-off per pair."""
    results = []
    for side, blob in available_tiers(pair):
        r = inference_at_tier(pair.prompt, blob, side,
                                  expected=pair.expected)
        results.append(r)
    if not results:
        return {'pair_id': pair.pk, 'prompt': pair.prompt,
                'expected': pair.expected, 'tiers': []}

    baseline_wall = results[0]['wall'] if results else 1e-3
    baseline_cells = results[0]['cell_updates'] if results else 1
    for r in results:
        r['speedup_wall']  = baseline_wall  / max(r['wall'], 1e-6)
        r['speedup_cells'] = baseline_cells / max(r['cell_updates'], 1)
        r['exact']         = (r['byte_match'] == r['n_target']
                                 and r['n_target'] > 0)

    return {
        'pair_id':  pair.pk,
        'prompt':   pair.prompt,
        'expected': pair.expected,
        'tiers':    results,
    }
