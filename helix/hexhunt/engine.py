"""Hex CA engine — vectorised step + spacetime scoring.

Topology and rule format match ``automaton.packed`` / ``s3lab`` so
rules transfer between apps unchanged: K=4, 7-cell positional
(self + N, NE, SE, S, SW, NW), offset coordinates with edge cells
treated as colour 0.

The reference per-cell loop lives in ``automaton.detector.step_packed``;
this module rewrites it as a single numpy expression so 200 generations
× 256 rules × 8 windows × 128 steps stays in the seconds-not-hours
regime.
"""

from __future__ import annotations

import gzip
from typing import Tuple

import numpy as np

from automaton.packed import PackedRuleset


N_COLORS = 4
BURN_IN = 32
TOTAL_STEPS = 128


def _neighbor_index_arrays(W: int, H: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Precompute the six neighbour-cell index lookups for a W×H grid.

    Returns ``(rr, cc, valid)`` each of shape ``(6, H, W)``: ``rr[k]``
    and ``cc[k]`` are the row/col of neighbour ``k`` for every cell;
    ``valid[k]`` is True where that neighbour exists. The neighbour
    order matches ``automaton.detector._hex_neighbors_padded``:
    N, NE, SE, S, SW, NW. We compute these once per grid shape and
    cache them on the module.
    """
    r = np.arange(H).reshape(H, 1).repeat(W, axis=1)
    c = np.arange(W).reshape(1, W).repeat(H, axis=0)
    even = (c % 2 == 0)

    deltas = []   # six (dr, dc)-as-arrays pairs
    # N
    deltas.append((np.full_like(r, -1), np.zeros_like(c)))
    # NE
    deltas.append((np.where(even, -1, 0), np.ones_like(c)))
    # SE
    deltas.append((np.where(even, 0, 1), np.ones_like(c)))
    # S
    deltas.append((np.ones_like(r), np.zeros_like(c)))
    # SW
    deltas.append((np.where(even, 0, 1), -np.ones_like(c)))
    # NW
    deltas.append((np.where(even, -1, 0), -np.ones_like(c)))

    rr = np.stack([r + dr for (dr, _) in deltas], axis=0)
    cc = np.stack([c + dc for (_, dc) in deltas], axis=0)
    valid = (rr >= 0) & (rr < H) & (cc >= 0) & (cc < W)
    # Clamp out-of-bounds to (0,0) — we'll mask the colour read to 0.
    rr = np.where(valid, rr, 0)
    cc = np.where(valid, cc, 0)
    return rr.astype(np.intp), cc.astype(np.intp), valid


_NB_CACHE: dict = {}


def neighbor_arrays(W: int, H: int):
    key = (W, H)
    cached = _NB_CACHE.get(key)
    if cached is None:
        cached = _neighbor_index_arrays(W, H)
        _NB_CACHE[key] = cached
    return cached


def unpack_rule(packed: PackedRuleset) -> np.ndarray:
    """Materialise the rule's 16,384 lookups into a flat int8 array.

    PackedRuleset stores 2 bits per output, 4 outputs per byte; we
    expand once at the start of an evolution so the hot loop is just
    one ``rule[idx]`` gather.
    """
    if packed.n_colors != N_COLORS:
        raise ValueError('hexhunt only supports K=4')
    raw = np.frombuffer(bytes(packed.data), dtype=np.uint8)
    # Each byte holds four 2-bit outputs in little-endian order:
    # bits 0-1 → cell 0, bits 2-3 → cell 1, bits 4-5 → cell 2, bits 6-7 → cell 3.
    a = raw & 0b11
    b = (raw >> 2) & 0b11
    c = (raw >> 4) & 0b11
    d = (raw >> 6) & 0b11
    out = np.empty(N_COLORS ** 7, dtype=np.int8)
    out[0::4] = a
    out[1::4] = b
    out[2::4] = c
    out[3::4] = d
    return out


# Precompute the K^i powers used by the rule index.
_W = (N_COLORS ** 6, N_COLORS ** 5, N_COLORS ** 4,
      N_COLORS ** 3, N_COLORS ** 2, N_COLORS ** 1, 1)


def step(grid: np.ndarray, rule_table: np.ndarray) -> np.ndarray:
    """Advance ``grid`` (H, W) one tick. ``rule_table`` is the 16,384-entry
    flat lookup from :func:`unpack_rule`."""
    H, W = grid.shape
    rr, cc, valid = neighbor_arrays(W, H)
    # Gather the 6 neighbour colours for every cell.
    nbs = grid[rr, cc] * valid  # invalid → 0
    # Build the per-cell rule index: self*K^6 + n0*K^5 + ... + n5.
    idx = (
        grid.astype(np.int32) * _W[0]
        + nbs[0].astype(np.int32) * _W[1]
        + nbs[1].astype(np.int32) * _W[2]
        + nbs[2].astype(np.int32) * _W[3]
        + nbs[3].astype(np.int32) * _W[4]
        + nbs[4].astype(np.int32) * _W[5]
        + nbs[5].astype(np.int32)
    )
    return rule_table[idx].astype(np.int8)


def evolve(grid: np.ndarray, rule_table: np.ndarray,
           steps: int = TOTAL_STEPS) -> np.ndarray:
    """Run ``steps`` ticks. Returns spacetime stack of shape
    ``(steps + 1, H, W)`` — initial state in slot 0, then each tick."""
    out = np.empty((steps + 1, *grid.shape), dtype=np.int8)
    out[0] = grid
    cur = grid
    for t in range(1, steps + 1):
        cur = step(cur, rule_table)
        out[t] = cur
    return out


# ── Scoring ──────────────────────────────────────────────────────────


def _gzip_ratio(buf: bytes) -> float:
    """Compressed/raw ratio. Lower = more redundant; higher = more random."""
    if not buf:
        return 0.0
    compressed = gzip.compress(buf, compresslevel=6)
    return len(compressed) / len(buf)


def score_gzip(spacetime: np.ndarray) -> float:
    """Compressibility of the post-burn-in spacetime stack.

    Monotonic: Class I → ~0, Class III → ~1. Useful as a raw signal
    but not as a fitness function on its own — Class IV (the goal)
    sits in the middle, so the parabolic ``score_edge`` is the default.
    """
    if spacetime.shape[0] <= BURN_IN:
        return 0.0
    tail = spacetime[BURN_IN:]
    flat = tail.reshape(-1).astype(np.uint8)
    if flat.size % 2:
        flat = np.concatenate([flat, np.zeros(1, dtype=np.uint8)])
    packed = (flat[0::2] | (flat[1::2] << 2)).tobytes()
    return _gzip_ratio(packed)


def _change_rate(spacetime: np.ndarray) -> float:
    """Mean fraction of cells that change between consecutive frames
    after burn-in. Class I → ~0, Class IV → moderate, Class III → ~0.75."""
    if spacetime.shape[0] <= BURN_IN + 1:
        return 0.0
    tail = spacetime[BURN_IN:].astype(np.int16)
    return float((tail[1:] != tail[:-1]).mean())


def score_change(spacetime: np.ndarray) -> float:
    """Raw change rate. Monotonic — peaks at Class III. Use ``edge``
    if you want a fitness function that peaks at Class IV."""
    return _change_rate(spacetime)


def score_edge(spacetime: np.ndarray) -> float:
    """Edge-of-chaos parabola on the change rate.

    ``4 * chg * (1 - chg)`` — peaks at ``chg = 0.5`` with value 1.0.
    Class I (chg ≈ 0) → 0, Class III (chg ≈ 0.75) → 0.75, Class IV
    (chg ≈ 0.2-0.4) → 0.6-1.0. Penalises both freeze-out and chaos,
    so selection drives toward intermediate dynamics — what we want
    for "rules that produce rich behaviour on organic input."
    """
    chg = _change_rate(spacetime)
    return 4.0 * chg * (1.0 - chg)


SCORING_FNS = {
    'gzip':   score_gzip,
    'change': score_change,
    'edge':   score_edge,
}


def score(spacetime: np.ndarray, fn_name: str = 'gzip') -> float:
    fn = SCORING_FNS.get(fn_name)
    if fn is None:
        raise ValueError(f'unknown scoring function: {fn_name!r}')
    return float(fn(spacetime))
