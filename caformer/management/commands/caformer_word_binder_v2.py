"""Train word-binder v2 — per-input-slot chains for compositional binding.

See caformer.word_binder_v2 for the architecture.  Each chain[s, p, c]
takes the s-th prompt word (alone) as input, emits a single base-4
digit (cell c of word ID at output position p within the slot's
output bag).  The response is built by concatenating across slots.

This is the compositional generalisation step: chain[2, 0, *] sees
only the third word of the prompt, so for 'look up wolves' it routes
'wolves' through whatever it learned from {bees, cats, dogs, ants}
at slot 2.  Won't synthesize URL_WOLF (vocab is fixed) but will emit
a trained URL — visible compositional structure.

Usage::

    manage.py caformer_word_binder_v2
    manage.py caformer_word_binder_v2 --pairs 2,3,...,22 \\
                                         --max-slots 4 --max-out 4 \\
                                         --cell-iters 4000 \\
                                         --holdout-prompts 'look up wolves,look up zebras'
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

from caformer import word_binder_v2 as wbv2
from caformer.word_binder_v2 import (
    LUT_SIZE, N_STATES, STOP_ID, UNK_ID, MAX_INPUT_SLOTS, MAX_OUT_PER_SLOT,
    _embed_word, _run, tokenize, build_vocab, training_targets,
)


DEFAULT_PAIRS = '2,3,4,5,6,9,10,11,12,13,15,16,17,18,19,20,21,22'


def _random_lut(rng: random.Random) -> bytes:
    return bytes(rng.randint(0, 3) for _ in range(LUT_SIZE))


def _const_lut(val: int) -> bytes:
    return bytes([val & 3]) * LUT_SIZE


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


def _cell_fitness(lut_arr: np.ndarray, stimuli, targets, ticks) -> int:
    n = 0
    for stim, tgt in zip(stimuli, targets):
        if int(_run(lut_arr, stim, ticks)[0, 0]) == tgt:
            n += 1
    return n


def _evolve_cell(stimuli, targets, ticks, iters, seed,
                  flips_min, flips_max, pop, log) -> dict:
    """Per-cell GA, seeded with const-0..3 + random.  Const seeding
    fixes the plateau bug from v1 (where the GA couldn't find the
    trivial all-zero rule from random inits)."""
    rng = random.Random(seed)
    M = len(targets)
    if M == 0:
        return {'lut': _const_lut(0), 'n_correct': 0, 'total': 0,
                  'iters_used': 0}
    pop_list = []
    # Seed: include the 4 constant LUTs so trivial all-same targets converge instantly.
    for v in range(N_STATES):
        lut = _const_lut(v)
        arr = np.frombuffer(lut, dtype=np.uint8) & 3
        pop_list.append((lut, _cell_fitness(arr, stimuli, targets, ticks)))
    # Random additions to fill pop.
    for _ in range(max(0, pop - N_STATES)):
        lut = _random_lut(rng)
        arr = np.frombuffer(lut, dtype=np.uint8) & 3
        pop_list.append((lut, _cell_fitness(arr, stimuli, targets, ticks)))
    pop_list.sort(key=lambda x: -x[1])
    best_lut, best_n = pop_list[0]
    iters_used = 0
    for it in range(iters):
        iters_used = it + 1
        if best_n >= M:
            break
        parent = rng.choice(pop_list[: max(1, pop // 2)])
        n_flips = rng.randint(flips_min, flips_max)
        child = _mutate(parent[0], rng, n_flips)
        carr = np.frombuffer(child, dtype=np.uint8) & 3
        n = _cell_fitness(carr, stimuli, targets, ticks)
        pop_list.append((child, n))
        pop_list.sort(key=lambda x: -x[1])
        pop_list = pop_list[: pop]
        if pop_list[0][1] > best_n:
            best_lut, best_n = pop_list[0]
    return {'lut': best_lut, 'n_correct': best_n, 'total': M,
              'iters_used': iters_used}


class Command(BaseCommand):
    help = ('Train word-binder v2 — per-input-slot chains.  Compositional '
              'binding: each slot takes one prompt word as input, emits '
              'output word IDs.')

    def add_arguments(self, parser):
        parser.add_argument('--pairs', type=str, default=DEFAULT_PAIRS)
        parser.add_argument('--max-slots', type=int, default=MAX_INPUT_SLOTS)
        parser.add_argument('--max-out', type=int, default=MAX_OUT_PER_SLOT)
        parser.add_argument('--ticks', type=int, default=6)
        parser.add_argument('--cell-pop', type=int, default=10)
        parser.add_argument('--cell-iters', type=int, default=3000)
        parser.add_argument('--cell-flips-min', type=int, default=4)
        parser.add_argument('--cell-flips-max', type=int, default=200)
        parser.add_argument('--out-dir', type=str,
                              default='.artifacts/word_binder_v2')
        parser.add_argument('--seed', type=int, default=0xB1A0_C0DE)
        parser.add_argument('--holdout-prompts', type=str, default='')

    def handle(self, *, pairs, max_slots, max_out, ticks, cell_pop,
                 cell_iters, cell_flips_min, cell_flips_max, out_dir, seed,
                 holdout_prompts, **opts):
        from caformer.models import QRPair

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        out = Path(settings.BASE_DIR) / out_dir
        out.mkdir(parents=True, exist_ok=True)

        pair_ids = [int(x) for x in pairs.split(',')]
        pairs_obj = [QRPair.objects.get(pk=pk) for pk in pair_ids]
        responses = [p.expected for p in pairs_obj]
        prompts = [p.prompt for p in pairs_obj]

        vocab = build_vocab(responses)
        V = vocab['size']; K = vocab['k_cells']

        # Build (slot, pos) → list of (stim, target) training examples
        # by iterating pairs and computing per-pair targets.
        train_set: dict[tuple[int, int], list[tuple[np.ndarray, int]]] = {}
        for prompt, resp in zip(prompts, responses):
            tgts = training_targets(prompt, resp, vocab,
                                       max_slots=max_slots, max_out=max_out)
            p_words = tokenize(prompt)[:max_slots]
            for (s, p), tgt_wid in tgts.items():
                if s >= len(p_words): continue
                stim = _embed_word(p_words[s])
                train_set.setdefault((s, p), []).append((stim, tgt_wid))

        log(f'=== Word-binder v2 (per-input-slot) ===')
        log(f'  pairs:       {len(pairs_obj)}')
        log(f'  vocab:       {V} tokens (STOP=0, UNK=1)')
        log(f'  cells/word:  {K}')
        log(f'  max slots:   {max_slots}')
        log(f'  max out/slt: {max_out}')
        log(f'  ticks:       {ticks}')
        log(f'  cell GA:     pop={cell_pop} iters={cell_iters}')
        log('')
        log('  training-set (slot, pos) → n_examples:')
        for key in sorted(train_set.keys()):
            log(f'    {key}: {len(train_set[key])} examples')
        log('')
        log('  vocab:')
        for i, w in enumerate(vocab['words']):
            tag = '  (STOP)' if i == 0 else '  (UNK)' if i == 1 else ''
            log(f'    {i:>3}: {w!r}{tag}')

        chains: dict[tuple[int, int], list[bytes]] = {}
        cell_stats = []
        t_global = time.time()

        for (s, p) in sorted(train_set.keys()):
            t_pos = time.time()
            log('')
            log(f'== slot {s}, pos {p} ==')
            ex = train_set[(s, p)]
            stims = [e[0] for e in ex]
            wids = [e[1] for e in ex]
            log(f'  n_examples: {len(ex)}  targets: {wids}')
            chains[(s, p)] = []
            for c in range(K):
                cell_targets = [(wid >> ((K - 1 - c) * 2)) & 3 for wid in wids]
                res = _evolve_cell(
                    stims, cell_targets, ticks,
                    iters=cell_iters,
                    seed=seed ^ (s * 99991) ^ (p * 50101) ^ (c * 7919),
                    flips_min=cell_flips_min, flips_max=cell_flips_max,
                    pop=cell_pop, log=log)
                chains[(s, p)].append(res['lut'])
                cell_stats.append({
                    'slot': s, 'pos': p, 'cell': c,
                    'n_correct': res['n_correct'], 'total': res['total'],
                    'iters': res['iters_used'],
                })
                tag = '✓' if res['n_correct'] == res['total'] else \
                        f'({res["n_correct"]}/{res["total"]})'
                log(f'  cell {c}: {tag}  iters={res["iters_used"]}  '
                    f'targets {cell_targets}')
                (out / f'chain_s{s:02d}_p{p:02d}_c{c}.lut').write_bytes(res['lut'])
            log(f'  (slot {s}, pos {p}) wall: {time.time()-t_pos:.0f}s '
                f'(global {time.time()-t_global:.0f}s)')

        (out / 'vocab.json').write_text(json.dumps({
            'words':     vocab['words'],
            'k_cells':   K,
            'max_slots': max_slots,
            'max_out':   max_out,
            'pairs':     pair_ids,
            'ticks':     ticks,
            'cell_stats': cell_stats,
        }, indent=2))

        # ── Eval ──
        log('')
        log(f'=== Eval: training set ===')
        model = wbv2.WordBinderV2(out, ticks=ticks)
        full = 0
        per_pair = []
        for p, r in zip(pairs_obj, responses):
            gen = model.generate(p.prompt)
            ex = (gen['text'] == r)
            if ex: full += 1
            tag = '✓ EXACT' if ex else '(text mismatch)'
            log(f'  pair {p.pk:>3}: {p.prompt!r:25}')
            log(f'    expected: {r!r}')
            log(f'    got:      {gen["text"]!r}  {tag}')
            log(f'    per-slot: {[(s["input_word"], s["output_words"]) for s in gen["per_slot"]]}')
            per_pair.append({'pair_id': p.pk, 'prompt': p.prompt,
                               'expected': r, 'got': gen['text'],
                               'exact': ex,
                               'per_slot': gen['per_slot']})

        log('')
        log(f'=== Training summary ===')
        log(f'  full-text exact: {full}/{len(pairs_obj)}')
        log(f'  total wall:      {time.time()-t_global:.0f}s')
        log(f'  chains:          {len(chains) * K} '
            f'({len(chains) * K * LUT_SIZE / 1024:.0f} KB)')

        # ── Held-out / novel ──
        holdouts = [s for s in (holdout_prompts or '').split(',') if s.strip()]
        if holdouts:
            log('')
            log(f'=== Held-out / novel prompts ===')
            for hp in holdouts:
                gen = model.generate(hp)
                log(f'  {hp!r:30}')
                log(f'    text:     {gen["text"]!r}')
                log(f'    per-slot: {[(s["input_word"], s["output_words"]) for s in gen["per_slot"]]}')

        (out / 'training_eval.json').write_text(json.dumps({
            'pairs':      pair_ids,
            'full_match': full,
            'n_pairs':    len(pairs_obj),
            'per_pair':   per_pair,
            'holdouts':   [{'prompt': hp,
                              'got': model.generate(hp)['text'],
                              'per_slot': model.generate(hp)['per_slot']}
                             for hp in holdouts],
        }, indent=2))
