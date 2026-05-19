"""Funnel v3 — per-position byte generation via per-cell chain layer.

End-to-end CA-LLM built on the per-cell-chain validation from
caformer_funnel_chains.  For each output position i in the response,
trains 4 per-cell chains (one per decoder cell) so that the gathered
4×4 board at position i decodes to expected[i] when run on the
embedded prompt.

Architecture (per output position i)::

  prompt → 4×4 embedding (top-left layout, 4 base-4 digits/byte)
  for each cell c in {0..3}: R[(i, c)] runs T ticks on the embedding
                              → cell (0, 0) of output = board[0, c]
  decode: byte = board[0,0]<<6 | board[0,1]<<4 | board[0,2]<<2 | board[0,3]
  emit the byte as expected[i]

For each pair P with response length > i, the per-cell chain at
(i, c) sees target ``(expected_P[i] >> (3-c)*2) & 3``.  Pairs with
shorter responses than i contribute no constraint for that position.

Storage: 4 × max_response_length × 16,384 B.  For 30-byte responses:
~1.9 MB per model.  Independent per-(i, c) GA — fully parallelizable
within the half-CPU budget.

This is the actual CA-LLM autoregressive generation: at inference the
prompt embedding doesn't change with position (we don't teacher-force
prior outputs into the embedding), so each position only sees the
prompt.  That's a simplification vs qr_trainer's full teacher-forcing,
but matches the funnel architecture.

Usage::

    manage.py caformer_funnel_tokens
    manage.py caformer_funnel_tokens --pairs 2,3,4,5,6,9,10,11,12,13,15 \\
                                        --max-pos 10 --cell-iters 1500
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

import numpy as np
from django.core.management.base import BaseCommand


N_STATES    = 4
LUT_SIZE    = N_STATES ** 7   # 16,384
SIDE        = 4               # 4×4 gathered board
DECODE_CELLS = 4              # 4 cells × 2 bits = 8-bit byte


def _embed_prompt(prompt: str, side: int = SIDE) -> np.ndarray:
    n_cells = side * side
    bytes_per_board = n_cells // 4
    raw = prompt.encode('utf-8')[:bytes_per_board]
    out = np.zeros(n_cells, dtype=np.uint8)
    for i, b in enumerate(raw):
        out[i * 4 + 0] = (b >> 6) & 3
        out[i * 4 + 1] = (b >> 4) & 3
        out[i * 4 + 2] = (b >> 2) & 3
        out[i * 4 + 3] =  b       & 3
    return out.reshape(side, side)


def _run(lut: bytes, state0: np.ndarray, ticks: int) -> np.ndarray:
    from caformer.primitives import hex_ca_step
    rule_arr = np.frombuffer(lut, dtype=np.uint8) & 3
    state = state0.copy()
    for _ in range(ticks):
        state = hex_ca_step(state, rule_arr)
    return state


def _random_lut(rng: random.Random) -> bytes:
    return bytes(rng.randint(0, 3) for _ in range(LUT_SIZE))


def _mutate(lut: bytes, rng: random.Random, n_flips: int) -> bytes:
    arr = bytearray(lut)
    for _ in range(n_flips):
        idx = rng.randrange(LUT_SIZE)
        cur = arr[idx] & 3
        new = rng.randint(0, 3)
        while new == cur:
            new = rng.randint(0, 3)
        arr[idx] = new
    return bytes(arr)


def _cell_fitness(lut: bytes, stimuli: list[np.ndarray],
                    targets: list[int], ticks: int) -> int:
    n = 0
    for stim, tgt in zip(stimuli, targets):
        if int(_run(lut, stim, ticks)[0, 0]) == tgt:
            n += 1
    return n


def _evolve_cell(stimuli, targets, ticks, iters, seed,
                  flips_min, flips_max, pop, log) -> dict:
    rng = random.Random(seed)
    pop_list = []
    for _ in range(pop):
        lut = _random_lut(rng)
        pop_list.append((lut, _cell_fitness(lut, stimuli, targets, ticks)))
    pop_list.sort(key=lambda x: -x[1])
    best_lut, best_n = pop_list[0]
    M = len(targets)
    for it in range(iters):
        parent = rng.choice(pop_list[: max(1, pop // 2)])
        n_flips = rng.randint(flips_min, flips_max)
        child = _mutate(parent[0], rng, n_flips)
        n = _cell_fitness(child, stimuli, targets, ticks)
        pop_list.append((child, n))
        pop_list.sort(key=lambda x: -x[1])
        pop_list = pop_list[:pop]
        if pop_list[0][1] > best_n:
            best_lut, best_n = pop_list[0]
            if best_n >= M:
                break
    return {'lut': best_lut, 'n_correct': best_n, 'total': M,
              'iters_used': it + 1}


def _generate(chains_by_pos: dict[int, list[bytes]], prompt: str,
                ticks: int, max_pos: int) -> bytes:
    stim = _embed_prompt(prompt)
    out_bytes = bytearray()
    for i in range(max_pos):
        if i not in chains_by_pos:
            break
        board_row0 = []
        for c in range(DECODE_CELLS):
            lut = chains_by_pos[i][c]
            board_row0.append(int(_run(lut, stim, ticks)[0, 0]))
        byte = (board_row0[0] << 6) | (board_row0[1] << 4) | \
                  (board_row0[2] << 2) | board_row0[3]
        out_bytes.append(byte)
    return bytes(out_bytes)


class Command(BaseCommand):
    help = ('End-to-end CA-LLM via per-position byte generation.  Trains '
              '4 per-cell chains per output position; decode 4 cells → byte.')

    def add_arguments(self, parser):
        parser.add_argument('--pairs', type=str,
                              default='2,3,4,5,6,9,10,11,12,13,15')
        parser.add_argument('--max-pos', type=int, default=10,
                              help='train chains for output positions 0..max_pos-1')
        parser.add_argument('--ticks', type=int, default=6)
        parser.add_argument('--cell-pop', type=int, default=8)
        parser.add_argument('--cell-iters', type=int, default=1500)
        parser.add_argument('--cell-flips-min', type=int, default=4)
        parser.add_argument('--cell-flips-max', type=int, default=120)
        parser.add_argument('--out-dir', type=str,
                              default='.artifacts/funnel_tokens_v1')
        parser.add_argument('--seed', type=int, default=0xC0FFEE)

    def handle(self, *, pairs, max_pos, ticks, cell_pop, cell_iters,
                 cell_flips_min, cell_flips_max, out_dir, seed, **opts):
        from caformer.models import QRPair
        from django.conf import settings

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        out = Path(settings.BASE_DIR) / out_dir
        out.mkdir(parents=True, exist_ok=True)

        pair_ids = [int(x) for x in pairs.split(',')]
        pairs_obj = [QRPair.objects.get(pk=pk) for pk in pair_ids]
        stimuli = [_embed_prompt(p.prompt) for p in pairs_obj]
        responses = [p.expected.encode('utf-8') for p in pairs_obj]
        max_len = max(len(r) for r in responses)
        actual_max = min(max_pos, max_len)
        n_pairs = len(pairs_obj)

        log(f'=== Funnel v3: per-position byte generation ===')
        log(f'  pairs:           {n_pairs}')
        log(f'  max response:    {max_len} bytes')
        log(f'  training positions: {actual_max}')
        log(f'  ticks:           {ticks}')
        log(f'  cell-pop×iters:  {cell_pop}×{cell_iters}')
        for p, r in zip(pairs_obj, responses):
            log(f'    pair {p.pk}: {p.prompt!r:18} → {r!r}  (len {len(r)})')

        chains_by_pos: dict[int, list[bytes]] = {}
        cell_stats = []
        t_global = time.time()

        # ── Per-position training ──
        for pos in range(actual_max):
            log('')
            log(f'== position {pos} ==')
            t_pos = time.time()
            # Collect (stim, target_byte) pairs that have this position.
            pos_stim, pos_tgt = [], []
            for stim, resp in zip(stimuli, responses):
                if len(resp) > pos:
                    pos_stim.append(stim)
                    pos_tgt.append(resp[pos])
            log(f'  applicable pairs: {len(pos_tgt)}')
            log(f'  target bytes:     {[chr(b) if 32 <= b < 127 else hex(b) for b in pos_tgt]}')
            chains_by_pos[pos] = []
            for c in range(DECODE_CELLS):
                shift = (DECODE_CELLS - 1 - c) * 2
                cell_targets = [(b >> shift) & 3 for b in pos_tgt]
                res = _evolve_cell(
                    pos_stim, cell_targets, ticks,
                    iters=cell_iters,
                    seed=seed ^ (pos * 99991) ^ (c * 7919),
                    flips_min=cell_flips_min, flips_max=cell_flips_max,
                    pop=cell_pop, log=log)
                chains_by_pos[pos].append(res['lut'])
                cell_stats.append({
                    'pos': pos, 'cell': c,
                    'n_correct': res['n_correct'], 'total': res['total'],
                    'iters': res['iters_used'],
                })
                tag = '✓' if res['n_correct'] == res['total'] else f'({res["n_correct"]}/{res["total"]})'
                log(f'  cell {c}: {tag}  iters={res["iters_used"]}  '
                    f'targets {cell_targets}')
                (out / f'chain_p{pos:02d}_c{c}.lut').write_bytes(res['lut'])
            log(f'  pos {pos} wall: {time.time()-t_pos:.0f}s '
                f'(global {time.time()-t_global:.0f}s)')

        # ── Eval: generate response for each pair ──
        log('')
        log(f'=== Eval: full-response generation ===')
        per_pair_results = []
        total_byte_match = 0
        total_bytes = 0
        full_match = 0
        for p, resp in zip(pairs_obj, responses):
            gen = _generate(chains_by_pos, p.prompt, ticks, actual_max)
            expected_pref = resp[:actual_max]
            n_match = sum(1 for a, b in zip(gen, expected_pref) if a == b)
            n_total = len(expected_pref)
            total_byte_match += n_match
            total_bytes += n_total
            is_full = (gen[:n_total] == expected_pref)
            if is_full:
                full_match += 1
            gen_repr = gen.decode('utf-8', errors='replace')
            exp_repr = expected_pref.decode('utf-8', errors='replace')
            tag = '✓ EXACT' if is_full else f'({n_match}/{n_total})'
            log(f'  pair {p.pk}: {p.prompt!r:18}')
            log(f'    expected: {exp_repr!r}')
            log(f'    got:      {gen_repr!r}  {tag}')
            per_pair_results.append({
                'pair_id': p.pk, 'prompt': p.prompt,
                'expected': exp_repr, 'got': gen_repr,
                'n_match': n_match, 'n_total': n_total,
                'full_match': is_full,
            })

        log('')
        log(f'=== SUMMARY ===')
        log(f'  full-response exact matches: {full_match}/{n_pairs}')
        log(f'  per-byte accuracy:           {total_byte_match}/{total_bytes} '
            f'= {total_byte_match/total_bytes:.3f}')
        log(f'  total wall:                  {time.time()-t_global:.0f}s')
        log(f'  positions trained:           {actual_max}')
        log(f'  chains total:                {actual_max * DECODE_CELLS} '
            f'({actual_max * DECODE_CELLS * 16384 / 1024:.0f} KB)')

        # Per-position byte accuracy table
        log('')
        log('  per-position byte accuracy:')
        for pos in range(actual_max):
            cells = [s for s in cell_stats if s['pos'] == pos]
            cell_summary = ' '.join(
                f'c{s["cell"]}={s["n_correct"]}/{s["total"]}'
                for s in cells)
            log(f'    pos {pos}: {cell_summary}')

        (out / 'summary.json').write_text(json.dumps({
            'n_pairs': n_pairs,
            'pairs': pair_ids,
            'max_pos': actual_max,
            'full_match': full_match,
            'total_byte_match': total_byte_match,
            'total_bytes': total_bytes,
            'cell_stats': cell_stats,
            'per_pair_results': per_pair_results,
        }, indent=2))
