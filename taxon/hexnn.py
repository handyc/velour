"""HexNN (K-dialable nearest-neighbour hex CA) support for taxon.

Mirrors `static/s3lab/js/hexnn_engine.mjs` so K=256 strateta rules can
be classified into Wolfram classes alongside the existing K=4 corpus.

Three pieces:

  HXNN binary blob format
      ``b'HXNN' + u32 K + u32 N + keys (N*7 bytes) + outs (N bytes)``.
      Stored verbatim in ``Rule.genome``; ~131 KB at the canonical
      N=16384. ``pack_hexnn`` / ``unpack_hexnn`` round-trip.

  HexNNRuleset
      Shim that mirrors the parts of ``automaton.packed.PackedRuleset``
      that ``taxon.metrics`` reads (``n_colors``, ``n_situations``,
      ``get_by_index``). Lets the existing dynamic metrics
      (density_entropy, activity_rate, transient_length,
      attractor_period) run against HexNN trajectories without any
      changes. Static metric ``langton_lambda`` is overridden below.

  simulate / langton_lambda_hexnn
      Trajectory recorder + a HexNN-flavoured langton λ (fraction of
      prototypes whose output differs from their self-color key).
"""
from __future__ import annotations

import hashlib
import struct
from typing import List, Tuple

import numpy as np


HXNN_MAGIC = b'HXNN'


def pack_hexnn(K: int, keys: bytes, outs: bytes) -> bytes:
    N = len(outs)
    if len(keys) != N * 7:
        raise ValueError(f'keys length {len(keys)} != N*7 = {N * 7}')
    return HXNN_MAGIC + struct.pack('<II', K, N) + keys + outs


def unpack_hexnn(blob: bytes) -> Tuple[int, np.ndarray, np.ndarray]:
    if len(blob) < 12 or blob[:4] != HXNN_MAGIC:
        raise ValueError('not an HXNN blob (bad magic)')
    K, N = struct.unpack('<II', blob[4:12])
    expected = 12 + N * 7 + N
    if len(blob) != expected:
        raise ValueError(f'HXNN length mismatch: got {len(blob)}, expected {expected}')
    keys = np.frombuffer(blob[12:12 + N * 7], dtype=np.uint8)
    outs = np.frombuffer(blob[12 + N * 7:], dtype=np.uint8)
    return K, keys, outs


class HexNNRuleset:
    """Drop-in for ``PackedRuleset`` for the parts ``taxon.metrics`` reads.

    Dynamic metrics need only ``n_colors``; static langton needs
    ``n_situations`` + ``get_by_index`` + a per-situation self-color
    lookup. We expose ``get_self_at`` for the latter so the HexNN
    langton metric can compare ``outs[i]`` to ``keys[i*7]``.
    """

    def __init__(self, K: int, keys: np.ndarray, outs: np.ndarray):
        self.n_colors = int(K)
        self.K = int(K)
        self.keys = keys
        self.outs = outs
        self.n_situations = int(len(outs))
        self._bins = self._build_bins()

    def _build_bins(self):
        K = self.K
        N = self.n_situations
        # counts of prototypes per self-color
        keys2d = self.keys.reshape(N, 7)
        self_col = keys2d[:, 0]
        nbs = keys2d[:, 1:7]                        # (N, 6) uint8
        order = np.argsort(self_col, kind='stable')
        sorted_self = self_col[order]
        # bin slice indices via searchsorted
        boundaries = np.searchsorted(sorted_self, np.arange(K + 1))
        bins = []
        for s in range(K):
            lo, hi = int(boundaries[s]), int(boundaries[s + 1])
            idx = order[lo:hi]
            bins.append({
                'nbs': nbs[idx],                    # (count, 6)
                'outs': self.outs[idx],             # (count,)
                'count': hi - lo,
            })
        return bins

    def get_by_index(self, i: int) -> int:
        return int(self.outs[i])

    def get_self_at(self, i: int) -> int:
        return int(self.keys[i * 7])

    @property
    def bins(self):
        return self._bins


# ── Step + simulate ────────────────────────────────────────────────


def _neighbours(grid: np.ndarray, r: int, c: int) -> np.ndarray:
    """Six neighbours (n0..n5) at (r, c), 0-padded. Matches JS engine
    pointy-top stagger: even-x columns shift NE/NW up, SE/SW same;
    odd-x columns shift SE/SW down, NE/NW same."""
    H, W = grid.shape
    even = (c & 1) == 0
    yN  = r - 1
    yS  = r + 1
    yNE = r - 1 if even else r
    ySE = r     if even else r + 1
    ySW = r     if even else r + 1
    yNW = r - 1 if even else r
    n0 = grid[yN,  c    ] if (yN  >= 0)                                  else 0
    n1 = grid[yNE, c + 1] if (yNE >= 0 and yNE < H and c + 1 < W)        else 0
    n2 = grid[ySE, c + 1] if (ySE >= 0 and ySE < H and c + 1 < W)        else 0
    n3 = grid[yS,  c    ] if (yS  < H)                                   else 0
    n4 = grid[ySW, c - 1] if (ySW >= 0 and ySW < H and c - 1 >= 0)       else 0
    n5 = grid[yNW, c - 1] if (yNW >= 0 and yNW < H and c - 1 >= 0)       else 0
    return np.array([n0, n1, n2, n3, n4, n5], dtype=np.int32)


def _step(grid: np.ndarray, ruleset: HexNNRuleset) -> np.ndarray:
    """One HexNN tick. Per-cell bin lookup is vectorised over the
    prototypes in that bin. Sub-100 ms per step for 16×16 K=256."""
    H, W = grid.shape
    out = np.empty_like(grid)
    bins = ruleset.bins
    for r in range(H):
        for c in range(W):
            self_c = int(grid[r, c])
            b = bins[self_c]
            if b['count'] == 0:
                out[r, c] = self_c
                continue
            target = _neighbours(grid, r, c)
            diffs = b['nbs'].astype(np.int32) - target
            d2 = (diffs * diffs).sum(axis=1)
            k = int(np.argmin(d2))
            out[r, c] = b['outs'][k]
    return out


def _seed_grid(W: int, H: int, K: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed or 1)
    return rng.integers(0, K, size=(H, W), dtype=np.uint8)


def simulate(ruleset: HexNNRuleset, W: int, H: int,
             horizon: int, seed: int) -> Tuple[np.ndarray, List[str]]:
    grid = _seed_grid(W, H, ruleset.K, seed)
    traj = [grid.copy()]
    hashes = [hashlib.sha1(grid.tobytes()).hexdigest()]
    for _ in range(horizon):
        grid = _step(grid, ruleset)
        traj.append(grid.copy())
        hashes.append(hashlib.sha1(grid.tobytes()).hexdigest())
    return np.stack(traj, axis=0), hashes


def langton_lambda_hexnn(ruleset: HexNNRuleset) -> Tuple[float, dict]:
    """HexNN-flavoured Langton λ: fraction of prototypes whose output
    differs from the prototype's self-color key. Same intuition as the
    K=4 packed version, applied to the N=16384 prototype table."""
    differ = int(np.sum(ruleset.outs != ruleset.keys.reshape(-1, 7)[:, 0]))
    total = ruleset.n_situations
    return differ / total, {'differ': differ, 'total': total}
