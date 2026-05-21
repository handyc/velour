"""Train the byte_router (3rd substrate) against the 4-way router
corpus.

Genome: 16 cell8 LUTs (4 layers × 4 boards), each 65,536 K=4 entries.
Total genome size = 16 × 64 KB = **1 MB**.

Fitness: for each (prompt, category) in router_corpus.CORPUS,
route the first ``n_bytes`` through the cascade with XOR aggregation
across per-byte fingerprints; the aggregate fingerprint's *first
chunk* should equal the target category.  Accuracy = correct/total.

GA shape: single-genome hill climb (no pop concept across genomes
because each genome is 1 MB and pop=N puts N MB in memory; with
joint mutation already exploring across 16 LUTs, the additional
pop diversity is marginal).  Per iter: mutate one LUT in the
genome (pick LUT uniformly, flip random K bytes in it), accept if
fitness improves.

Same progress-logging shape as the boardstack4 trainer: init,
heartbeat every iters/40, ACCEPT on improvements.

  manage.py caformer_train_byte_router
  manage.py caformer_train_byte_router --iters 6000 --n-bytes 16
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

import numpy as np

from django.conf import settings
from django.core.management.base import BaseCommand

from caformer.byte_router import (ByteRouter, N_LAYERS, N_BOARDS,
                                            SIDE, TICKS,
                                            _random_layer_luts,
                                            _random_lut,
                                            save_router)
from caformer.cell8 import (LUT_SIZE_8, hex_ca_step_cell8,
                                       broadcast_input)
from caformer.router_corpus import CORPUS, CATEGORY_NAMES, by_category


# ─── Fitness (layer-table optimized) ──────────────────────────────


# Static asymmetric initial state — must match what
# byte_router.ByteRouter._board_output uses, otherwise the trained
# LUTs won't produce the same fingerprints at inference time.
_BASE_STATE = (np.arange(SIDE * SIDE, dtype=np.uint8)
                   .reshape(SIDE, SIDE) & 3)


# Precompute the 4 chunks of every byte 0..255 so the layer-table
# builder doesn't redo the shifts inside its hot loop.
_BYTE_CHUNKS = np.empty((256, 4), dtype=np.uint8)
for _b in range(256):
    _BYTE_CHUNKS[_b, 0] = (_b >> 6) & 3
    _BYTE_CHUNKS[_b, 1] = (_b >> 4) & 3
    _BYTE_CHUNKS[_b, 2] = (_b >> 2) & 3
    _BYTE_CHUNKS[_b, 3] =  _b       & 3


def _board_output(board_lut: np.ndarray, chunk_value: int,
                       ticks: int = TICKS) -> int:
    state = _BASE_STATE.copy()
    state[0, 0] = chunk_value & 3
    input_grid = broadcast_input(SIDE, chunk_value)
    for _ in range(ticks):
        state = hex_ca_step_cell8(state, input_grid, board_lut)
    return int(state[0, 0])


def _build_layer_table(layer: list[np.ndarray], ticks: int) -> np.ndarray:
    """For one layer (4 cell8 LUTs), build a 256-entry table mapping
    every input byte to the layer's output byte.  Each board only has
    4 possible chunk inputs (K=4), so we evaluate each board 4 times
    and combine — total 16 board-outputs to fully characterise the
    layer's byte → byte function.

    Returns: uint8 array of shape (256,)."""
    # board_lut_outputs[b, c] = board b's output for chunk value c.
    board_outs = np.zeros((N_BOARDS, 4), dtype=np.uint8)
    for b in range(N_BOARDS):
        for c in range(4):
            board_outs[b, c] = _board_output(layer[b], c, ticks)
    # Now compose: for byte_val v with chunks (c0, c1, c2, c3),
    #   output_byte = (board_outs[0, c0] << 6)
    #               | (board_outs[1, c1] << 4)
    #               | (board_outs[2, c2] << 2)
    #               |  board_outs[3, c3]
    # Vectorise across all 256 bytes using _BYTE_CHUNKS.
    c0 = _BYTE_CHUNKS[:, 0]
    c1 = _BYTE_CHUNKS[:, 1]
    c2 = _BYTE_CHUNKS[:, 2]
    c3 = _BYTE_CHUNKS[:, 3]
    out = ((board_outs[0, c0].astype(np.uint16) << 6)
           | (board_outs[1, c1].astype(np.uint16) << 4)
           | (board_outs[2, c2].astype(np.uint16) << 2)
           |  board_outs[3, c3].astype(np.uint16))
    return out.astype(np.uint8)


def _build_all_tables(genome: list[list[np.ndarray]],
                          ticks: int) -> list[np.ndarray]:
    return [_build_layer_table(layer, ticks) for layer in genome]


def _route_byte_via_tables(layer_tables: list[np.ndarray],
                                byte_val: int) -> int:
    """Cascade one byte through all N_LAYERS lookups."""
    cur = int(byte_val) & 0xFF
    for tbl in layer_tables:
        cur = int(tbl[cur])
    return cur


def _aggregate_first_chunk(layer_tables, prompt_bytes_array,
                              n_bytes) -> int:
    """XOR-aggregate the final bytes across the first n_bytes;
    return chunk[0] of the result.  Legacy 4-bin output."""
    agg = 0
    for b in prompt_bytes_array[:n_bytes]:
        agg ^= _route_byte_via_tables(layer_tables, b)
    return (agg >> 6) & 3


def _aggregate_full_byte(layer_tables, prompt_bytes_array,
                              n_bytes) -> int:
    """XOR-aggregate the final bytes across the first n_bytes;
    return the FULL output byte (256-bin output instead of 4-bin).
    Used by the full-fingerprint training path."""
    agg = 0
    for b in prompt_bytes_array[:n_bytes]:
        agg ^= _route_byte_via_tables(layer_tables, b)
    return agg & 0xFF


def _fitness_tables(layer_tables, prompts_encoded, targets,
                          n_bytes) -> int:
    """Strict label-match fitness — chunk[0] of aggregated fingerprint
    must equal the corpus category exactly.  Vulnerable to the
    "always output 0" degenerate basin."""
    n_correct = 0
    for raw, target in zip(prompts_encoded, targets):
        got = _aggregate_first_chunk(layer_tables, raw, n_bytes)
        if got == target:
            n_correct += 1
    return n_correct


def _fitness_purity(layer_tables, prompts_encoded, targets,
                          n_bytes) -> int:
    """Full-byte purity fitness: each prompt's aggregated output byte
    (0..255) lands in a bucket; purity = sum over buckets of the
    max-category count in each bucket.

    Floor = M/4 (all prompts in one bucket, 25% expected category
    correctness).  Ceiling = M (every prompt in its own bucket or
    perfectly category-pure buckets).  With 256 buckets and 80
    prompts, "every prompt unique" is achievable in principle.

    After training we recover a many-to-one mapping (256 → 4) via
    _best_permutation_full."""
    bag: dict[int, list[int]] = {}
    for raw, target in zip(prompts_encoded, targets):
        v = _aggregate_full_byte(layer_tables, raw, n_bytes)
        b = bag.get(v)
        if b is None:
            b = [0, 0, 0, 0]
            bag[v] = b
        b[target] += 1
    return sum(max(b) for b in bag.values())


def _best_permutation(layer_tables, prompts_encoded, targets,
                            n_bytes) -> tuple[dict, int]:
    """Many-to-one mapping: each output byte (0..255) is assigned to
    the category with the most prompts producing that byte.  Buckets
    with no prompts get no mapping.

    Returns (mapping dict {output_byte → category}, n_correct).  Note
    this is NOT a permutation in the strict sense — multiple output
    bytes can map to the same category, which is exactly what we want
    with 256 buckets feeding 4 categories."""
    bag: dict[int, list[int]] = {}
    for raw, target in zip(prompts_encoded, targets):
        v = _aggregate_full_byte(layer_tables, raw, n_bytes)
        b = bag.get(v)
        if b is None:
            b = [0, 0, 0, 0]
            bag[v] = b
        b[target] += 1
    mapping: dict[int, int] = {}
    n_correct = 0
    for v, b in bag.items():
        # Assign output v to the category with the most prompts in
        # this bucket.  Tie-break by lower category index.
        best_cat = 0
        best_count = b[0]
        for t in range(1, 4):
            if b[t] > best_count:
                best_count = b[t]
                best_cat = t
        mapping[v] = best_cat
        n_correct += best_count
    return mapping, n_correct


# ─── Mutation ──────────────────────────────────────────────────────


def _mutate_lut(lut: np.ndarray, rng: random.Random, n_flips: int) -> np.ndarray:
    """Return a new LUT with n_flips entries changed to a different K=4
    value.  Operates on a copy; original untouched."""
    out = lut.copy()
    for _ in range(n_flips):
        idx = rng.randrange(LUT_SIZE_8)
        cur = int(out[idx]) & 3
        nu = rng.randint(0, 3)
        while nu == cur:
            nu = rng.randint(0, 3)
        out[idx] = nu
    return out


def _mutate_genome(genome, rng: random.Random,
                       n_flips_min: int, n_flips_max: int
                       ) -> tuple[list[list[np.ndarray]], tuple[int, int]]:
    """Mutate ONE LUT in the genome (pick layer + board uniformly).
    Returns (new_genome, (layer_idx, board_idx))."""
    li = rng.randrange(N_LAYERS)
    bi = rng.randrange(N_BOARDS)
    n_flips = rng.randint(n_flips_min, n_flips_max)
    new_genome = [list(layer) for layer in genome]
    new_genome[li][bi] = _mutate_lut(genome[li][bi], rng, n_flips)
    return new_genome, (li, bi)


# ─── Command ──────────────────────────────────────────────────────


class Command(BaseCommand):
    help = ('Train the byte_router (16-LUT joint genome) against '
            'the 4-way router corpus.')

    def add_arguments(self, parser):
        parser.add_argument('--stage-a-iters', type=int, default=3000,
                              help='per-layer hill-climb iters in Stage A')
        parser.add_argument('--stage-b-iters', type=int, default=2000,
                              help='joint fine-tune iters in Stage B '
                                     '(0 = skip)')
        parser.add_argument('--n-bytes', type=int, default=4,
                              help='how many initial bytes of each '
                                     'prompt to aggregate per fitness eval '
                                     '(K=4 alignment: 4)')
        parser.add_argument('--ticks', type=int, default=TICKS,
                              help='CA ticks per board (must match '
                                     'inference-time byte_router.TICKS)')
        parser.add_argument('--flips-min', type=int, default=10)
        parser.add_argument('--flips-max', type=int, default=2000)
        parser.add_argument('--out-dir', type=str,
                              default='.artifacts/byte_router_v2')
        parser.add_argument('--seed', type=int, default=0xB17_E_72)

    def handle(self, *, stage_a_iters, stage_b_iters, n_bytes, ticks,
                 flips_min, flips_max, out_dir, seed, **opts):
        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        out = Path(settings.BASE_DIR) / out_dir
        out.mkdir(parents=True, exist_ok=True)

        log('=== byte_router train ===')
        log(f'  corpus: {len(CORPUS)} pairs')
        for cat, names in by_category().items():
            log(f'    {cat} ({CATEGORY_NAMES[cat]:12}): {len(names)} examples')
        log(f'  genome: {N_LAYERS} layers × {N_BOARDS} boards × '
            f'{LUT_SIZE_8} entries')
        log(f'  n_bytes={n_bytes}  ticks={ticks}  '
            f'stage_a_iters={stage_a_iters}  stage_b_iters={stage_b_iters}  '
            f'flips=[{flips_min}, {flips_max}]')
        log(f'  out-dir={out}')

        t0 = time.time()
        rng = random.Random(seed)
        M = len(CORPUS)
        prompts_encoded = [p.encode('utf-8') for (p, _) in CORPUS]
        targets = [c for (_, c) in CORPUS]

        # ── Stage A: train each layer in sequence, with already-
        #            trained layers frozen.  Each layer L's fitness =
        #            cascade-output's chunk[0] = category, where the
        #            cascade is just the (L+1) layers trained so far.
        log('\n=== Stage A: layer-by-layer training ===')
        genome: list[list[np.ndarray]] = []
        layer_tables: list[np.ndarray] = []

        for L in range(N_LAYERS):
            log(f'\n-- layer {L} ({stage_a_iters} iters) --')
            # Random init for this layer.
            current_layer = [_random_lut(rng) for _ in range(N_BOARDS)]
            current_table = _build_layer_table(current_layer, ticks)
            cascade_tables = layer_tables + [current_table]
            cur_fit = _fitness_purity(cascade_tables, prompts_encoded,
                                          targets, n_bytes)
            log(f'  layer {L} init fit (cascade of {L+1}): '
                f'{cur_fit}/{M} ({cur_fit/M:.3f})')

            last_accept_it = 0
            heartbeat_every = max(20, stage_a_iters // 40)
            next_heartbeat = heartbeat_every
            t_layer = time.time()
            for it in range(stage_a_iters):
                if cur_fit >= M:
                    log(f'    layer {L} it {it:>5}: PERFECT — stopping early')
                    break
                bi = rng.randrange(N_BOARDS)
                n_flips = rng.randint(flips_min, flips_max)
                old_lut = current_layer[bi]
                current_layer[bi] = _mutate_lut(old_lut, rng, n_flips)
                old_table = current_table
                current_table = _build_layer_table(current_layer, ticks)
                cascade_tables[-1] = current_table
                fit = _fitness_purity(cascade_tables, prompts_encoded,
                                            targets, n_bytes)
                if fit > cur_fit:
                    cur_fit = fit
                    if it - last_accept_it >= 20:
                        log(f'    layer {L} it {it:>5}: ACCEPT board={bi}  '
                            f'fit={cur_fit}/{M} ({cur_fit/M:.3f})')
                        last_accept_it = it
                else:
                    current_layer[bi] = old_lut
                    current_table = old_table
                    cascade_tables[-1] = current_table
                if it >= next_heartbeat:
                    elapsed = time.time() - t_layer
                    rate = (it + 1) / max(elapsed, 1e-6)
                    remaining = (stage_a_iters - it - 1) / max(rate, 1e-6)
                    log(f'    layer {L} hb {it:>5}/{stage_a_iters} '
                        f'({100*it/stage_a_iters:4.1f}%)  '
                        f'best={cur_fit}/{M}  '
                        f'{rate:.1f} it/s  ETA {remaining:.0f}s')
                    next_heartbeat += heartbeat_every
            wall_layer = time.time() - t_layer
            log(f'  layer {L} done in {wall_layer:.1f}s  '
                f'best={cur_fit}/{M} ({cur_fit/M:.3f})')
            genome.append(current_layer)
            layer_tables.append(current_table)

        # ── Stage B: joint fine-tune all 4 layers together ──────────
        best_fit = _fitness_purity(layer_tables, prompts_encoded,
                                          targets, n_bytes)  # purity (escapes degenerate basin)
        log(f'\n=== Stage B: joint fine-tune ===')
        log(f'  Stage A final cascade fit: {best_fit}/{M} ({best_fit/M:.3f})')
        if stage_b_iters > 0:
            last_accept_it = 0
            heartbeat_every = max(20, stage_b_iters // 40)
            next_heartbeat = heartbeat_every
            t_joint = time.time()
            for it in range(stage_b_iters):
                if best_fit >= M:
                    log(f'  it {it:>5}: PERFECT — stopping early')
                    break
                li = rng.randrange(N_LAYERS)
                bi = rng.randrange(N_BOARDS)
                n_flips = rng.randint(flips_min, flips_max)
                old_lut = genome[li][bi]
                genome[li][bi] = _mutate_lut(old_lut, rng, n_flips)
                old_table = layer_tables[li]
                layer_tables[li] = _build_layer_table(genome[li], ticks)
                fit = _fitness_purity(layer_tables, prompts_encoded,
                                            targets, n_bytes)
                if fit > best_fit:
                    best_fit = fit
                    if it - last_accept_it >= 20:
                        log(f'  joint it {it:>5}: ACCEPT layer={li} '
                            f'board={bi}  fit={best_fit}/{M} '
                            f'({best_fit/M:.3f})')
                        last_accept_it = it
                else:
                    genome[li][bi] = old_lut
                    layer_tables[li] = old_table
                if it >= next_heartbeat:
                    elapsed = time.time() - t_joint
                    rate = (it + 1) / max(elapsed, 1e-6)
                    remaining = (stage_b_iters - it - 1) / max(rate, 1e-6)
                    log(f'  joint hb {it:>5}/{stage_b_iters} '
                        f'({100*it/stage_b_iters:4.1f}%)  '
                        f'best={best_fit}/{M}  '
                        f'{rate:.1f} it/s  ETA {remaining:.0f}s')
                    next_heartbeat += heartbeat_every

        wall = time.time() - t0
        # Recover the (output value → category label) permutation
        # that maximises canonical-label accuracy.
        perm, n_canonical = _best_permutation(
            layer_tables, prompts_encoded, targets, n_bytes)
        log(f'\n-- done in {wall:.0f}s --')
        log(f'  purity:                {best_fit}/{M} '
            f'({best_fit/M:.3f})')
        log(f'  best-permutation acc:  {n_canonical}/{M} '
            f'({n_canonical/M:.3f})')
        log(f'  permutation: {perm}')
        # Surface the canonical fitness (with default identity mapping)
        # alongside for direct comparison with strict-label training.
        strict = _fitness_tables(layer_tables, prompts_encoded,
                                       targets, n_bytes)
        log(f'  strict (identity-map): {strict}/{M} '
            f'({strict/M:.3f})')

        # Save.
        router = ByteRouter(genome, ticks=ticks)
        save_router(router, out)
        # Persist meta alongside (overwrites byte_router's meta).
        (out / 'meta.json').write_text(json.dumps({
            'n_layers':       N_LAYERS,
            'n_boards':       N_BOARDS,
            'side':           SIDE,
            'ticks':          ticks,
            'lut_size':       LUT_SIZE_8,
            'n_bytes_train':  n_bytes,
            'stage_a_iters':  stage_a_iters,
            'stage_b_iters':  stage_b_iters,
            'flips_min':      flips_min,
            'flips_max':      flips_max,
            'n_corpus':       M,
            'final_fit':      best_fit,
            'final_accuracy': best_fit / M,
            'wall_seconds':   round(wall, 1),
        }, indent=2))
        log(f'  saved to {out}')

        # Per-category breakdown (using best many-to-one mapping).
        log('\n-- per-category accuracy (full-byte mapping) --')
        for cat, names in by_category().items():
            n = 0
            correct = 0
            for raw, target in zip(prompts_encoded, targets):
                if target != cat:
                    continue
                n += 1
                got_v = _aggregate_full_byte(layer_tables, raw, n_bytes)
                if perm.get(got_v) == cat:
                    correct += 1
            log(f'  {CATEGORY_NAMES[cat]:12}: {correct:>2}/{n:<2} '
                f'({100*correct/max(1,n):5.1f}%)')

        log(f'  ({len(perm)} distinct output bytes seen across corpus)')

        # A few novel probes.
        log('\n-- novel probes --')
        novel = [
            ('hey',                          'personality'),
            ('how big is mars',              'information'),
            ('write me some HTML',           'action'),
            ('what does it mean to know',    'meta'),
        ]
        for p, expected in novel:
            raw_b = p.encode('utf-8')
            got_v = _aggregate_full_byte(layer_tables, raw_b, n_bytes)
            got = perm.get(got_v)
            got_name = CATEGORY_NAMES.get(got, '?') if got is not None \
                       else '(unseen output)'
            log(f'    {p!r:38} → v={got_v:>3} → {got_name} '
                f'expected: {expected}')
