"""Train the 4-way intent router from caformer.router_corpus.

A single chain → cell (0,0) ∈ {0..3} = category.  Per-cell GA with
const-LUT seeding, same shape as everything else in the stack.

Usage::

    manage.py caformer_train_router
    manage.py caformer_train_router --cell-iters 8000 --pop 16
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

from caformer.router import LUT_SIZE, N_STATES, TICKS, embed_prompt, _run
from caformer.router_corpus import CORPUS, CATEGORY_NAMES, by_category


def _random_lut(rng):
    return bytes(rng.randint(0, 3) for _ in range(LUT_SIZE))


def _const_lut(val):
    return bytes([val & 3]) * LUT_SIZE


def _mutate(lut, rng, n_flips):
    arr = bytearray(lut)
    for _ in range(n_flips):
        idx = rng.randrange(LUT_SIZE)
        cur = arr[idx] & 3
        nu  = rng.randint(0, 3)
        while nu == cur:
            nu = rng.randint(0, 3)
        arr[idx] = nu
    return bytes(arr)


def _fitness(lut_arr, stims, targets, ticks):
    n = 0
    for stim, tgt in zip(stims, targets):
        if int(_run(lut_arr, stim, ticks)[0, 0]) == tgt:
            n += 1
    return n


def _evolve(stims, targets, ticks, iters, pop, flips_min, flips_max,
              seed, log):
    rng = random.Random(seed)
    M = len(targets)
    pop_list = []
    # const-LUT seeds
    for v in range(N_STATES):
        lut = _const_lut(v)
        arr = np.frombuffer(lut, dtype=np.uint8) & 3
        pop_list.append((lut, _fitness(arr, stims, targets, ticks)))
    # random filler
    for _ in range(max(0, pop - N_STATES)):
        lut = _random_lut(rng)
        arr = np.frombuffer(lut, dtype=np.uint8) & 3
        pop_list.append((lut, _fitness(arr, stims, targets, ticks)))
    pop_list.sort(key=lambda x: -x[1])
    best_lut, best_n = pop_list[0]
    log(f'  init: best={best_n}/{M}')
    last_report = 0
    for it in range(iters):
        if best_n >= M:
            break
        parent = pop_list[rng.randrange(max(1, pop // 2))]
        n_flips = rng.randint(flips_min, flips_max)
        child = _mutate(parent[0], rng, n_flips)
        carr = np.frombuffer(child, dtype=np.uint8) & 3
        fit  = _fitness(carr, stims, targets, ticks)
        # replace worst
        worst_idx = 0
        for i, (_, f) in enumerate(pop_list):
            if f < pop_list[worst_idx][1]:
                worst_idx = i
        if fit > pop_list[worst_idx][1]:
            pop_list[worst_idx] = (child, fit)
            if fit > best_n:
                best_lut, best_n = child, fit
                if it - last_report >= 50:
                    log(f'  it {it:>5}: ACCEPT {best_n}/{M}')
                    last_report = it
    return best_lut, best_n


class Command(BaseCommand):
    help = 'Train the 4-way intent router from caformer.router_corpus.CORPUS.'

    def add_arguments(self, parser):
        parser.add_argument('--ticks', type=int, default=TICKS)
        parser.add_argument('--pop', type=int, default=16)
        parser.add_argument('--cell-iters', type=int, default=20000)
        parser.add_argument('--flips-min', type=int, default=4)
        parser.add_argument('--flips-max', type=int, default=400)
        parser.add_argument('--n-chains', type=int, default=3,
                              help='independent chains for majority vote')
        parser.add_argument('--out-dir', type=str,
                              default='.artifacts/router_v1')
        parser.add_argument('--seed', type=int, default=0x5A1A_F00D)

    def handle(self, *, ticks, pop, cell_iters, flips_min, flips_max,
                 n_chains, out_dir, seed, **opts):
        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        out = Path(settings.BASE_DIR) / out_dir
        out.mkdir(parents=True, exist_ok=True)

        log(f'=== Router train ({n_chains} chain{"s" if n_chains>1 else ""} → 0..3 majority) ===')
        log(f'  corpus: {len(CORPUS)} pairs')
        for cat, names in by_category().items():
            log(f'    {cat} ({CATEGORY_NAMES[cat]:12}): {len(names)} examples')
        log(f'  ticks={ticks} pop={pop} cell-iters={cell_iters}')

        stims = [embed_prompt(p) for (p, _) in CORPUS]
        targets = [c for (_, c) in CORPUS]

        all_chains = []
        all_chain_n = []
        t_global = time.time()
        for ch in range(n_chains):
            log('')
            log(f'== chain {ch} (seed {seed ^ (ch * 0xC0DE)}) ==')
            best_lut, best_n = _evolve(
                stims, targets, ticks,
                iters=cell_iters, pop=pop,
                flips_min=flips_min, flips_max=flips_max,
                seed=seed ^ (ch * 0xC0DE), log=log)
            all_chains.append(best_lut)
            all_chain_n.append(best_n)
            (out / f'router_chain_{ch}.lut').write_bytes(best_lut)
            log(f'  chain {ch}: {best_n}/{len(CORPUS)} = '
                f'{best_n/len(CORPUS):.3f}')
        wall = time.time() - t_global

        # Also write legacy single-chain LUT for back-compat (chain 0).
        (out / 'router_chain.lut').write_bytes(all_chains[0])

        (out / 'router_meta.json').write_text(json.dumps({
            'n_corpus': len(CORPUS),
            'n_chains': n_chains,
            'per_chain_correct': all_chain_n,
            'ticks': ticks,
            'wall_seconds': wall,
        }, indent=2))

        # Per-pair report + confusion matrix (with N-chain majority vote).
        from caformer.router import RouterModel
        m = RouterModel(out, ticks=ticks)
        confusion = [[0] * 4 for _ in range(4)]
        n_majority_correct = 0
        for (prompt, expected) in CORPUS:
            got = m.route(prompt)
            confusion[expected][got] += 1
            if got == expected: n_majority_correct += 1
        log('')
        log(f'  majority-vote accuracy: {n_majority_correct}/{len(CORPUS)} = '
            f'{n_majority_correct/len(CORPUS):.3f}')
        log(f'  per-chain accuracies: {all_chain_n}')
        log(f'  total wall: {wall:.0f}s')
        log('')
        log('  confusion (rows=expected, cols=predicted):')
        log('         ' + ' '.join(f'{CATEGORY_NAMES[c][:4]:>5}'
                                       for c in range(4)))
        for e in range(4):
            log(f'    {CATEGORY_NAMES[e][:4]:<5} ' +
                ' '.join(f'{confusion[e][p]:>5}' for p in range(4)))

        # Probe a few novel prompts.
        novel = [
            'hey',                          # → personality
            'how big is mars',              # → information
            'write me some HTML',           # → action
            'what does it mean to know',    # → meta
            'sup',                          # → personality (slang)
            'when was jazz invented',       # → information
            'paint a landscape',            # → action
            'consider this carefully',      # → meta
        ]
        log('')
        log('  novel probes:')
        for p in novel:
            got = m.route(p)
            log(f'    {p!r:38} → {got} ({CATEGORY_NAMES[got]})')
