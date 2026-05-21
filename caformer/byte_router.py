"""byte_router — 4-layer × 4-board K=4 byte-chunk router.

A third deterministic prefilter alongside [[boardstack4]] (CA cascade
on 8×8 K=4 grid) and the PICM tree (vocabulary descent).

**Mechanism.**  One input byte is split into 4 × 2-bit chunks.  At
each of 4 layers, 4 cell8 boards receive one chunk each on their
``input_grid`` (broadcast across the 8×8 surface).  Each board runs
its CA for N ticks and emits a K=4 output value from cell (0, 0).
The 4 outputs reassemble into a new byte that feeds the next layer.
After 4 layers, the final byte's 4 chunks form a routing fingerprint
— a 4-symbol path over the K=4 alphabet.

**Why this is structurally distinct from boardstack4:**

- boardstack4 packs the prompt's bytes into an 8×8 K=4 grid as the
  *initial state* of board 0.  Each board reads the prior board's
  final state; output is cell (0,0) at depth N.
- byte_router uses cell8's *input cell* (the 8th cell from the
  7→1 → 8→1 generalisation) for its designed purpose: external
  data injection.  Each layer transforms one byte to another byte
  via parallel K=4 chunks.  Routing flows through the *byte stream*,
  not through cascaded board states.

**Cost.** 4 layers × 4 boards × 64 KB cell8 LUTs = **1 MB on disk**.
Per-route compute: 4 × 4 × N_TICKS × 8×8 cell evals ≈ 6,144 cell
evals per byte (numpy-vectorised, sub-ms).

Phase 1 here: random LUT initialisation so the cascade runs
end-to-end and produces a deterministic fingerprint per prompt.
Training (joint GA over all 16 LUTs) is a follow-up — Phase 1's
role is to validate the pipeline + surface fingerprints in the
harness for side-by-side comparison with the other two prefilters.
"""
from __future__ import annotations

import json
import random
import threading
from pathlib import Path
from typing import Sequence

import numpy as np

from caformer.cell8 import (LUT_SIZE_8, hex_ca_step_cell8,
                                       broadcast_input)


N_LAYERS = 4
N_BOARDS = 4
SIDE     = 8
TICKS    = 4    # K=4 alignment — see caformer/router.py for rationale.
DEFAULT_DIR = '.artifacts/byte_router_v1'


def _random_lut(rng: random.Random) -> np.ndarray:
    """Generate one random K=4 LUT for a cell8 board."""
    arr = np.empty(LUT_SIZE_8, dtype=np.uint8)
    # Vectorised random K=4: int32 → uint8 with mask 0x3.
    rand_words = rng.getrandbits(LUT_SIZE_8 * 2).to_bytes(LUT_SIZE_8 * 2 // 8 + 1, 'little')
    # Simpler & deterministic (sacrifice some speed):
    for i in range(LUT_SIZE_8):
        arr[i] = rng.randint(0, 3)
    return arr


def _random_layer_luts(seed: int) -> list[list[np.ndarray]]:
    """N_LAYERS × N_BOARDS random K=4 cell8 LUTs.  Seed deterministic."""
    rng = random.Random(seed)
    return [[_random_lut(rng) for _ in range(N_BOARDS)]
            for _ in range(N_LAYERS)]


class ByteRouter:
    """Stateless cascade: one byte → one 4-symbol fingerprint."""

    def __init__(self, layer_luts: Sequence[Sequence[np.ndarray]],
                       ticks: int = TICKS,
                       permutation: dict[int, int] | None = None,
                       n_bytes_train: int = 4):
        self.layer_luts = [list(layer) for layer in layer_luts]
        self.ticks = ticks
        # permutation: trained 256-byte → 4-category map.  When
        # None, the router can produce fingerprints but not categories.
        self.permutation: dict[int, int] = dict(permutation or {})
        self.n_bytes_train = int(n_bytes_train)
        if len(self.layer_luts) != N_LAYERS:
            raise ValueError(
                f'byte_router expects {N_LAYERS} layers, got {len(self.layer_luts)}')
        for li, layer in enumerate(self.layer_luts):
            if len(layer) != N_BOARDS:
                raise ValueError(
                    f'layer {li} has {len(layer)} boards, expected {N_BOARDS}')
            for bi, lut in enumerate(layer):
                if lut.size != LUT_SIZE_8:
                    raise ValueError(
                        f'layer {li} board {bi}: LUT size {lut.size} '
                        f'(expected {LUT_SIZE_8})')

    # A non-uniform initial state breaks the symmetry that would
    # otherwise keep the CA uniform under a broadcast input — without
    # this, every chunk_value converges to the same final value
    # under random LUTs and the routing collapses to a single
    # fingerprint regardless of input.  The pattern is fixed per
    # router so the cascade stays deterministic.
    _BASE_STATE = (np.arange(SIDE * SIDE, dtype=np.uint8)
                       .reshape(SIDE, SIDE) & 3)

    def _board_output(self, board_lut: np.ndarray, chunk_value: int) -> int:
        """Run one board's CA with the 2-bit chunk broadcast on the
        input cell.  Initial state is a fixed asymmetric pattern with
        cell (0, 0) primed by chunk_value, so the routing cell carries
        chunk signal directly into the cascade.  Returns cell (0, 0)
        of the final state."""
        state = self._BASE_STATE.copy()
        state[0, 0] = chunk_value & 3
        input_grid = broadcast_input(SIDE, chunk_value)
        for _ in range(self.ticks):
            state = hex_ca_step_cell8(state, input_grid, board_lut)
        return int(state[0, 0])

    def route_byte(self, byte_val: int
                       ) -> tuple[tuple[int, int, int, int], list[int]]:
        """Process one byte through all 4 layers.  Returns the final
        4-symbol fingerprint AND the per-layer intermediate byte
        values (for tracing)."""
        current = int(byte_val) & 0xFF
        intermediates = [current]
        for layer in self.layer_luts:
            chunks = (
                (current >> 6) & 3,
                (current >> 4) & 3,
                (current >> 2) & 3,
                 current       & 3,
            )
            outputs = [
                self._board_output(layer[b], chunks[b])
                for b in range(N_BOARDS)
            ]
            current = ((outputs[0] & 3) << 6
                       | (outputs[1] & 3) << 4
                       | (outputs[2] & 3) << 2
                       |  outputs[3] & 3)
            intermediates.append(current)
        fp = (
            (current >> 6) & 3,
            (current >> 4) & 3,
            (current >> 2) & 3,
             current       & 3,
        )
        return fp, intermediates

    def _aggregate_byte(self, prompt: str, n_bytes: int) -> int:
        """XOR-aggregate the first n_bytes routed bytes.  The result
        is a single byte in [0, 255]; the trained permutation maps
        this to a K=4 category."""
        raw = prompt.encode('utf-8')[:max(1, n_bytes)]
        if not raw:
            return 0
        agg = 0
        for b in raw:
            out_byte = self._route_byte_to_byte(int(b))
            agg ^= out_byte
        return agg & 0xFF

    def _route_byte_to_byte(self, byte_val: int) -> int:
        """Same as route_byte but returns the final byte (not the
        fingerprint tuple).  Used by classify_prompt for the
        permutation lookup path."""
        current = int(byte_val) & 0xFF
        for layer in self.layer_luts:
            chunks = (
                (current >> 6) & 3, (current >> 4) & 3,
                (current >> 2) & 3,  current       & 3)
            outs = [self._board_output(layer[b], chunks[b])
                    for b in range(N_BOARDS)]
            current = ((outs[0] & 3) << 6 | (outs[1] & 3) << 4
                       | (outs[2] & 3) << 2 |  outs[3] & 3)
        return current

    def classify_prompt(self, prompt: str,
                              n_bytes: int | None = None) -> dict:
        """Use the trained permutation to map an input prompt to a
        K=4 category + report fingerprint + the aggregated byte.

        Returns a dict {category, fingerprint, agg_byte,
        permutation_loaded}.  When no permutation is loaded, category
        is None and the caller should fall back to mode-projection
        or another prefilter."""
        n = n_bytes if n_bytes is not None else self.n_bytes_train
        agg_byte = self._aggregate_byte(prompt, n)
        fp = ((agg_byte >> 6) & 3, (agg_byte >> 4) & 3,
              (agg_byte >> 2) & 3,  agg_byte       & 3)
        cat = self.permutation.get(agg_byte) if self.permutation else None
        return {
            'category':           cat,
            'fingerprint':        fp,
            'agg_byte':           agg_byte,
            'permutation_loaded': bool(self.permutation),
            'n_bytes':            n,
        }

    def route_prompt(self, prompt: str, n_bytes: int = 4
                          ) -> dict | None:
        """Route the first ``n_bytes`` of the prompt and aggregate the
        per-byte fingerprints via bitwise XOR per chunk position.

        Aggregation: for each of the 4 chunk positions, XOR the
        corresponding chunk value across all routed bytes.  XOR over
        2-bit values preserves K=4 and is order-invariant — same
        input set, same fingerprint regardless of byte order.

        Returns: {
            'fingerprint':              (c0, c1, c2, c3),     # aggregate
            'per_byte_fingerprints':    [(c,c,c,c), …],       # one per byte
            'bytes_in':                 [int, int, …],
            'bytes_intermediate':       [[byte/layer], …],
            'first_byte':               int,                  # for back-compat
        } — or None when the prompt is empty."""
        raw = prompt.encode('utf-8')[:max(1, int(n_bytes))]
        if not raw:
            return None
        per_byte_fps: list[tuple[int, int, int, int]] = []
        all_inters: list[list[int]] = []
        for byte_val in raw:
            fp, inters = self.route_byte(byte_val)
            per_byte_fps.append(fp)
            all_inters.append(inters)
        # XOR aggregate across positions.
        agg = [0, 0, 0, 0]
        for fp in per_byte_fps:
            for i in range(4):
                agg[i] ^= fp[i] & 3
        return {
            'fingerprint':            tuple(agg),
            'per_byte_fingerprints':  per_byte_fps,
            'bytes_in':               [int(b) for b in raw],
            'bytes_intermediate':     all_inters,
            'first_byte':             int(raw[0]),
        }


# ─── Persistence ───────────────────────────────────────────────────


def save_router(router: ByteRouter, model_dir: str | Path) -> Path:
    """Write the router's 16 LUTs + meta.json + (optional) trained
    permutation.json.  Layout:

      ``layer_<L>_board_<B>.lut``  (raw bytes, 65,536 entries per file)
      ``meta.json``                (architecture + ticks + provenance)
      ``permutation.json``         (trained 256-byte → 4-category map,
                                    written only when router.permutation
                                    is populated)"""
    md = Path(model_dir).resolve()
    md.mkdir(parents=True, exist_ok=True)
    for l, layer in enumerate(router.layer_luts):
        for b, lut in enumerate(layer):
            (md / f'layer_{l}_board_{b}.lut').write_bytes(bytes(lut))
    (md / 'meta.json').write_text(json.dumps({
        'n_layers':       N_LAYERS,
        'n_boards':       N_BOARDS,
        'side':           SIDE,
        'ticks':          router.ticks,
        'lut_size':       LUT_SIZE_8,
        'n_bytes_train':  router.n_bytes_train,
    }, indent=2))
    if router.permutation:
        # JSON keys must be strings; convert byte → category dict.
        (md / 'permutation.json').write_text(json.dumps(
            {str(k): int(v) for k, v in router.permutation.items()},
            indent=2))
    return md


def load_router(model_dir: str | Path) -> ByteRouter:
    md = Path(model_dir)
    meta_path = md / 'meta.json'
    meta = json.loads(meta_path.read_text())
    luts: list[list[np.ndarray]] = []
    for l in range(int(meta.get('n_layers', N_LAYERS))):
        layer = []
        for b in range(int(meta.get('n_boards', N_BOARDS))):
            lp = md / f'layer_{l}_board_{b}.lut'
            arr = np.frombuffer(lp.read_bytes(), dtype=np.uint8).copy() & 3
            layer.append(arr)
        luts.append(layer)
    permutation: dict[int, int] = {}
    perm_path = md / 'permutation.json'
    if perm_path.exists():
        raw = json.loads(perm_path.read_text())
        permutation = {int(k): int(v) for k, v in raw.items()}
    return ByteRouter(
        luts, ticks=int(meta.get('ticks', TICKS)),
        permutation=permutation,
        n_bytes_train=int(meta.get('n_bytes_train', 4)))


# ─── Permutation derivation ────────────────────────────────────────


def compute_permutation_for_corpus(router: ByteRouter,
                                          corpus: list[tuple[str, int]],
                                          n_bytes: int | None = None
                                          ) -> tuple[dict[int, int], int]:
    """Walk the corpus through the router and derive a many-to-one
    output-byte → category mapping via greedy max-count assignment.

    Each prompt's aggregated output byte is bucketed against its
    target category; each bucket is then assigned to whichever
    category appears most in it.  Returns (mapping, n_correct).

    Use this when an existing router_v* artifact lacks a saved
    permutation — recompute against ``caformer.router_corpus.CORPUS``
    and persist via save_router()."""
    n = n_bytes if n_bytes is not None else router.n_bytes_train
    bag: dict[int, list[int]] = {}
    for prompt, target in corpus:
        agg = router._aggregate_byte(prompt, n)
        b = bag.get(agg)
        if b is None:
            b = [0, 0, 0, 0]
            bag[agg] = b
        b[int(target) & 3] += 1
    mapping: dict[int, int] = {}
    n_correct = 0
    for v, counts in bag.items():
        best_cat = 0
        best_count = counts[0]
        for t in range(1, 4):
            if counts[t] > best_count:
                best_count = counts[t]
                best_cat = t
        mapping[v] = best_cat
        n_correct += best_count
    return mapping, n_correct


_CACHE: dict[str, ByteRouter] = {}
_LOCK = threading.Lock()


def get_router(model_dir: str | Path | None = None) -> ByteRouter:
    """Cached loader.  Falls back to seeded random LUTs when no
    artifact dir exists — keeps the harness usable pre-seed."""
    if model_dir is None:
        model_dir = DEFAULT_DIR
    key = str(model_dir)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        md = Path(model_dir)
        if (md / 'meta.json').exists():
            r = load_router(md)
        else:
            r = ByteRouter(_random_layer_luts(seed=0xBE7E_F011))
        _CACHE[key] = r
        return r


def path_label(fp: Sequence[int]) -> str:
    return '-'.join(str(int(c) & 3) for c in fp)
