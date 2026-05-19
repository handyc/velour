"""Funnel v2 — per-cell chain layer + optional combiner.

Replaces the deterministic mod-4 embedding of caformer_funnel_real
with a *trained* per-cell-position layer.  For each of the 16 cells
in a 4×4 gathered board, evolve one K=4 hex LUT (R[p]) that takes the
embedded prompt as initial state, runs T ticks, and emits cell (0,0)
of the final state as that gathered-board cell's value.

Two phases:

  1. **Cell training (independent).**  For each cell position p, run
     a hill-climber: each candidate rule is scored on how many pairs
     it puts the right value at cell (0,0).  16 independent K=4
     classifiers, each with M training examples (one per pair).

  2. **Combiner (optional).**  Train a second K=4 hex LUT on the
     gathered boards produced by Phase 1.  If the per-cell chains
     hit their targets perfectly, combiner is unnecessary and decode
     reads the gathered board directly.  Otherwise the combiner does
     error correction.

The architectural payoff this tests: does decomposing the funnel
search across 16 independent per-cell GAs beat the single 16,384-byte
combiner search that hit the 128×128 wall in caformer_funnel_dual?

Target encoding (per pair → 4×4 target board):
  cell p ← (class_i * (p+1) * 31 + p * 7) % 4
  — class-dependent injection that varies across cells so every cell
  carries class-discriminative info, not just the first two.

Usage::

    manage.py caformer_funnel_chains
    manage.py caformer_funnel_chains --pairs 2,3,4,5,6,9,10,11,12,13,15 \\
                                       --ticks 8 --cell-iters 800
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

import numpy as np
from django.core.management.base import BaseCommand


N_STATES = 4
LUT_SIZE = N_STATES ** 7   # 16,384
SIDE     = 4               # 4×4 gathered board


def _embed_prompt(prompt: str, side: int = SIDE) -> np.ndarray:
    """4 base-4 digits per byte, top-left layout, zero-pad/truncate.
    Same encoding as caformer_funnel_real with --side 4."""
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


def _random_lut(rng: random.Random) -> bytes:
    return bytes(rng.randint(0, 3) for _ in range(LUT_SIZE))


def _cell_fitness(lut: bytes, stimuli: list[np.ndarray],
                    targets: list[int], ticks: int) -> tuple[int, int]:
    """Score: number of pairs where cell (0,0) of R(stim, T) == target."""
    n_correct = 0
    for stim, tgt in zip(stimuli, targets):
        final = _run(lut, stim, ticks)
        if int(final[0, 0]) == tgt:
            n_correct += 1
    return n_correct, len(targets)


def _evolve_cell(stimuli: list[np.ndarray], targets: list[int],
                   ticks: int, iters: int, seed: int,
                   flips_min: int, flips_max: int,
                   pop: int, log) -> dict:
    """Hill-climber with mini population (μ+λ ES-lite).  Each cell is
    an independent K=4 classifier with len(stimuli) training examples."""
    rng = random.Random(seed)
    pop_list = []
    for _ in range(pop):
        lut = _random_lut(rng)
        n, tot = _cell_fitness(lut, stimuli, targets, ticks)
        pop_list.append((lut, n))
    pop_list.sort(key=lambda x: -x[1])
    best_lut, best_n = pop_list[0]
    M = len(targets)

    log(f'    cell-init: best={best_n}/{M}')
    for it in range(iters):
        parent = rng.choice(pop_list[: max(1, pop // 2)])
        n_flips = rng.randint(flips_min, flips_max)
        child = _mutate(parent[0], rng, n_flips)
        n, _ = _cell_fitness(child, stimuli, targets, ticks)
        pop_list.append((child, n))
        pop_list.sort(key=lambda x: -x[1])
        pop_list = pop_list[: pop]
        if pop_list[0][1] > best_n:
            best_lut, best_n = pop_list[0]
            log(f'      it {it:>4}: ACCEPT {best_n}/{M}')
            if best_n >= M:
                break
    return {'lut': best_lut, 'n_correct': best_n, 'total': M}


def _classify_with_chains(chains: list[bytes], combiner: bytes | None,
                            stim: np.ndarray, ticks: int,
                            combiner_ticks: int,
                            decode_cells: int) -> int:
    """Run all 16 chain rules on the stimulus, gather cell (0,0) of
    each into a 4×4 board, optionally run combiner, decode."""
    board = np.zeros((SIDE, SIDE), dtype=np.uint8)
    for p, lut in enumerate(chains):
        r, c = divmod(p, SIDE)
        final = _run(lut, stim, ticks)
        board[r, c] = int(final[0, 0])
    if combiner is not None:
        board = _run(combiner, board, combiner_ticks)
    val = 0
    for c in range(decode_cells):
        val = val * N_STATES + int(board[0, c])
    return val


def _evolve_combiner(stimuli: list[np.ndarray], targets: list[int],
                       chains: list[bytes], chain_ticks: int,
                       comb_ticks: int, decode_cells: int,
                       pop: int, gens: int, seed: int,
                       mut_min: int, mut_max: int, log) -> dict:
    rng = random.Random(seed)
    # Precompute gathered boards once — they don't depend on combiner.
    boards = []
    for stim in stimuli:
        b = np.zeros((SIDE, SIDE), dtype=np.uint8)
        for p, lut in enumerate(chains):
            r, c = divmod(p, SIDE)
            final = _run(lut, stim, chain_ticks)
            b[r, c] = int(final[0, 0])
        boards.append(b)

    def _fit(comb: bytes):
        n = 0
        for b, tgt in zip(boards, targets):
            out = _run(comb, b, comb_ticks)
            val = 0
            for c in range(decode_cells):
                val = val * N_STATES + int(out[0, c])
            if val == tgt:
                n += 1
        return n

    pop_list = []
    for _ in range(pop):
        comb = _random_lut(rng)
        pop_list.append((comb, _fit(comb)))
    pop_list.sort(key=lambda x: -x[1])
    best_comb, best_n = pop_list[0]
    M = len(targets)
    log(f'    combiner-init: best={best_n}/{M}')
    for g in range(gens):
        parents = pop_list[: max(1, pop // 3)]
        children = []
        for _ in range(pop - len(parents)):
            parent_comb, _ = rng.choice(parents)
            n_flips = rng.randint(mut_min, mut_max)
            child = _mutate(parent_comb, rng, n_flips)
            children.append((child, _fit(child)))
        pop_list = parents + children
        pop_list.sort(key=lambda x: -x[1])
        if pop_list[0][1] > best_n:
            best_comb, best_n = pop_list[0]
        if (g + 1) % 10 == 0 or best_n >= M:
            log(f'    combiner-gen {g+1:>3}: best={best_n}/{M}')
        if best_n >= M:
            break
    return {'lut': best_comb, 'n_correct': best_n, 'total': M}


def _make_target_boards(n_classes: int, decode_cells: int) -> list[np.ndarray]:
    """class i → 4×4 board.  First `decode_cells` of row 0 carry the
    base-4 digits of i (bijective, so chains-alone decode is correct
    when those cells train perfectly).  Remaining cells are
    class-dependent filler so each non-decoder cell still gives the
    chain GA something to discriminate (else cells 2..15 would all
    have target=0 and the chain layer would carry no extra info)."""
    out = []
    for cls in range(n_classes):
        b = np.zeros((SIDE, SIDE), dtype=np.uint8)
        # Bijective base-4 encoding into decode cells.
        for c in range(decode_cells):
            shift = (decode_cells - 1 - c) * 2
            b[0, c] = (cls >> shift) & 3
        # Filler for the rest — class-dependent but allowed to collide.
        for p in range(decode_cells, SIDE * SIDE):
            r, c = divmod(p, SIDE)
            b[r, c] = (cls * (p + 1) * 31 + p * 7) % N_STATES
        out.append(b)
    return out


class Command(BaseCommand):
    help = ('Per-cell-position trained chain layer feeding a 4×4 funnel '
              'combiner.  Tests whether decomposing the search across 16 '
              'independent per-cell GAs beats the single 128×128 search.')

    def add_arguments(self, parser):
        parser.add_argument('--pairs', type=str,
                              default='2,3,4,5,6,9,10,11,12,13,15')
        parser.add_argument('--ticks', type=int, default=6,
                              help='ticks per per-cell chain rule')
        parser.add_argument('--comb-ticks', type=int, default=6)
        parser.add_argument('--cell-pop', type=int, default=8)
        parser.add_argument('--cell-iters', type=int, default=800)
        parser.add_argument('--cell-flips-min', type=int, default=4)
        parser.add_argument('--cell-flips-max', type=int, default=120)
        parser.add_argument('--comb-pop', type=int, default=32)
        parser.add_argument('--comb-gens', type=int, default=80)
        parser.add_argument('--comb-mut-min', type=int, default=20)
        parser.add_argument('--comb-mut-max', type=int, default=400)
        parser.add_argument('--skip-combiner', action='store_true',
                              help='Eval chains alone (no combiner).')
        parser.add_argument('--decode-cells', type=int, default=2)
        parser.add_argument('--target-bytes', type=int, default=2)
        parser.add_argument('--out-dir', type=str,
                              default='.artifacts/funnel_chains_v1')
        parser.add_argument('--seed', type=int, default=0xC0FFEE)

    def handle(self, *, pairs, ticks, comb_ticks, cell_pop, cell_iters,
                 cell_flips_min, cell_flips_max, comb_pop, comb_gens,
                 comb_mut_min, comb_mut_max, skip_combiner, decode_cells,
                 target_bytes, out_dir, seed, **opts):
        from caformer.models import QRPair

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        from django.conf import settings
        out = Path(settings.BASE_DIR) / out_dir
        out.mkdir(parents=True, exist_ok=True)

        pair_ids = [int(x) for x in pairs.split(',')]
        pairs_obj = [QRPair.objects.get(pk=pk) for pk in pair_ids]
        n_pairs = len(pairs_obj)

        stimuli = [_embed_prompt(p.prompt) for p in pairs_obj]
        target_prefixes = [p.expected.encode('utf-8')[:target_bytes]
                              for p in pairs_obj]
        unique_targets = sorted(set(target_prefixes))
        max_classes = N_STATES ** decode_cells
        if len(unique_targets) > max_classes:
            self.stdout.write(self.style.ERROR(
                f'{len(unique_targets)} prefixes > {max_classes} max classes'))
            return
        prefix_to_class = {pref: i for i, pref in enumerate(unique_targets)}
        targets = [prefix_to_class[pref] for pref in target_prefixes]

        log(f'=== Funnel v2: per-cell chains ===')
        log(f'  board:        {SIDE}×{SIDE}, LUT {LUT_SIZE} B')
        log(f'  pairs:        {n_pairs} ({len(unique_targets)} distinct classes)')
        log(f'  chain ticks:  {ticks}')
        log(f'  cell-pop×its: {cell_pop}×{cell_iters} ({cell_flips_min}-{cell_flips_max} flips)')
        log(f'  decode cells: {decode_cells} → max {max_classes} classes')

        for p, pref, c in zip(pairs_obj, target_prefixes, targets):
            log(f'    pair {p.pk}: {p.prompt!r:18} → {pref!r:8} → class {c}')

        target_boards = _make_target_boards(max_classes, decode_cells)

        # ── Phase 1: per-cell training ──
        log('')
        log(f'== Phase 1: train {SIDE*SIDE} per-cell chains ==')
        chains: list[bytes] = []
        cell_n_correct = []
        t1 = time.time()
        for p in range(SIDE * SIDE):
            r, c = divmod(p, SIDE)
            cell_targets = [int(target_boards[cls][r, c]) for cls in targets]
            log(f'  cell {p:>2} (row {r}, col {c}): targets {cell_targets}')
            res = _evolve_cell(
                stimuli, cell_targets, ticks,
                iters=cell_iters,
                seed=seed ^ (p * 99991),
                flips_min=cell_flips_min, flips_max=cell_flips_max,
                pop=cell_pop,
                log=log)
            chains.append(res['lut'])
            cell_n_correct.append(res['n_correct'])

            (out / f'chain_p{p:02d}.lut').write_bytes(res['lut'])

        total_cells = SIDE * SIDE
        perfect_cells = sum(1 for n in cell_n_correct if n == n_pairs)
        avg_cell = float(np.mean(cell_n_correct))
        log('')
        log(f'  Phase-1 summary: {perfect_cells}/{total_cells} cells '
            f'perfect; avg {avg_cell:.2f}/{n_pairs}')
        log(f'  wall: {time.time()-t1:.0f}s')

        # ── Eval chains alone ──
        log('')
        log(f'== Eval: chains alone (read 2 cells of gathered board) ==')
        chain_correct = 0
        for stim, tgt in zip(stimuli, targets):
            board = np.zeros((SIDE, SIDE), dtype=np.uint8)
            for p, lut in enumerate(chains):
                r, c = divmod(p, SIDE)
                final = _run(lut, stim, ticks)
                board[r, c] = int(final[0, 0])
            # Decode cells 0..decode_cells-1 of row 0 as base-4 class.
            # Bijective encoding: cell c carries digit (cls >> (D-1-c)*2) & 3.
            val = 0
            for c in range(decode_cells):
                val = val * N_STATES + int(board[0, c])
            if val == tgt:
                chain_correct += 1
        log(f'  chains-alone (base-4 decode of {decode_cells} cells): '
            f'{chain_correct}/{n_pairs} = {chain_correct/n_pairs:.3f}')

        if skip_combiner:
            log('  combiner skipped')
            return

        # ── Phase 2: combiner GA on top of gathered boards ──
        log('')
        log(f'== Phase 2: combiner GA (pop={comb_pop}, gens={comb_gens}) ==')
        t2 = time.time()
        comb_res = _evolve_combiner(
            stimuli, targets, chains,
            chain_ticks=ticks, comb_ticks=comb_ticks,
            decode_cells=decode_cells,
            pop=comb_pop, gens=comb_gens,
            seed=seed ^ 0xCAFE,
            mut_min=comb_mut_min, mut_max=comb_mut_max,
            log=log)
        log(f'  combiner: {comb_res["n_correct"]}/{n_pairs} = '
            f'{comb_res["n_correct"]/n_pairs:.3f}  (wall {time.time()-t2:.0f}s)')
        (out / 'combiner.lut').write_bytes(comb_res['lut'])

        # ── Final eval ──
        final_correct = 0
        for stim, tgt in zip(stimuli, targets):
            pred = _classify_with_chains(
                chains, comb_res['lut'], stim, ticks,
                comb_ticks, decode_cells)
            if pred == tgt:
                final_correct += 1
        log('')
        log(f'=== FINAL ===')
        log(f'  chains-alone:     {chain_correct}/{n_pairs} = {chain_correct/n_pairs:.3f}')
        log(f'  + combiner:       {final_correct}/{n_pairs} = {final_correct/n_pairs:.3f}')
        log(f'  per-cell perfect: {perfect_cells}/{total_cells}')

        (out / 'summary.json').write_text(json.dumps({
            'n_pairs': n_pairs,
            'pairs': pair_ids,
            'cell_n_correct': cell_n_correct,
            'chain_alone_correct': chain_correct,
            'final_correct': final_correct,
            'combiner_train_correct': comb_res['n_correct'],
        }, indent=2))
