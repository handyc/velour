"""Train the phrase layer — per-input-slot chains emitting phrase IDs.

See caformer.phrase_binder for the architecture.  Functionally
identical to caformer_word_binder_v2 except the vocab atoms are
whole responses (phrases) instead of individual words.  Each chain
emits one phrase ID; decoding expands phrase → word IDs → strings.

Usage::

    manage.py caformer_phrase_binder
    manage.py caformer_phrase_binder --pairs ... \\
                                       --holdout-prompts 'look up wolves'
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

from caformer import phrase_binder as pb
from caformer.phrase_binder import (
    LUT_SIZE, N_STATES, STOP_ID, UNK_ID, MAX_INPUT_SLOTS, MAX_OUT_PER_SLOT,
    _embed_word, _run, tokenize, build_phrase_vocab, training_targets,
)
from caformer.word_binder_v2 import build_vocab as build_word_vocab


DEFAULT_PAIRS = '2,3,4,5,6,9,10,11,12,13,15,16,17,18,19,20,21,22'


def _random_lut(rng):
    return bytes(rng.randint(0, 3) for _ in range(LUT_SIZE))


def _const_lut(val):
    return bytes([val & 3]) * LUT_SIZE


def _mutate(lut, rng, n_flips):
    arr = bytearray(lut)
    for _ in range(n_flips):
        idx = rng.randrange(LUT_SIZE)
        cur = arr[idx] & 3
        new = rng.randint(0, 3)
        while new == cur:
            new = rng.randint(0, 3)
        arr[idx] = new
    return bytes(arr)


def _cell_fitness(lut_arr, stimuli, targets, ticks):
    n = 0
    for stim, tgt in zip(stimuli, targets):
        if int(_run(lut_arr, stim, ticks)[0, 0]) == tgt:
            n += 1
    return n


def _evolve_cell(stimuli, targets, ticks, iters, seed,
                  flips_min, flips_max, pop, log):
    rng = random.Random(seed)
    M = len(targets)
    if M == 0:
        return {'lut': _const_lut(0), 'n_correct': 0, 'total': 0, 'iters_used': 0}
    pop_list = []
    for v in range(N_STATES):
        lut = _const_lut(v)
        arr = np.frombuffer(lut, dtype=np.uint8) & 3
        pop_list.append((lut, _cell_fitness(arr, stimuli, targets, ticks)))
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
        parent = rng.choice(pop_list[:max(1, pop // 2)])
        n_flips = rng.randint(flips_min, flips_max)
        child = _mutate(parent[0], rng, n_flips)
        carr = np.frombuffer(child, dtype=np.uint8) & 3
        n = _cell_fitness(carr, stimuli, targets, ticks)
        pop_list.append((child, n))
        pop_list.sort(key=lambda x: -x[1])
        pop_list = pop_list[:pop]
        if pop_list[0][1] > best_n:
            best_lut, best_n = pop_list[0]
    return {'lut': best_lut, 'n_correct': best_n, 'total': M, 'iters_used': iters_used}


class Command(BaseCommand):
    help = ('Train the phrase layer — per-input-slot chains emitting '
              'phrase (whole-response) IDs.')

    def add_arguments(self, parser):
        parser.add_argument('--pairs', type=str, default=DEFAULT_PAIRS)
        parser.add_argument('--max-slots', type=int, default=MAX_INPUT_SLOTS)
        parser.add_argument('--max-out', type=int, default=2)
        parser.add_argument('--ticks', type=int, default=6)
        parser.add_argument('--cell-pop', type=int, default=10)
        parser.add_argument('--cell-iters', type=int, default=5000)
        parser.add_argument('--cell-flips-min', type=int, default=4)
        parser.add_argument('--cell-flips-max', type=int, default=200)
        parser.add_argument('--out-dir', type=str,
                              default='.artifacts/phrase_binder_v1')
        parser.add_argument('--seed', type=int, default=0xFAB1_C0DE)
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

        word_vocab = build_word_vocab(responses)
        phrase_vocab = build_phrase_vocab(responses, word_vocab)

        log(f'=== Phrase-binder (recursive: phrase → words → bytes) ===')
        log(f'  pairs:           {len(pairs_obj)}')
        log(f'  word vocab:      {word_vocab["size"]} tokens (K={word_vocab["k_cells"]} cells)')
        log(f'  phrase vocab:    {phrase_vocab["size"]} phrases (K={phrase_vocab["k_cells"]} cells)')
        log(f'  max slots:       {max_slots}')
        log(f'  ticks:           {ticks}')
        log(f'  cell GA:         pop={cell_pop} iters={cell_iters}')
        log('')
        log('  phrase vocab table:')
        for i, ph in enumerate(phrase_vocab['phrases']):
            tag = '  (STOP)' if i == 0 else '  (UNK)' if i == 1 else ''
            exp = phrase_vocab['expansions'][i]
            exp_words = [word_vocab['words'][wid] for wid in exp]
            log(f'    {i:>3}: {ph!r:45} {tag}  → words {exp_words}')

        # Training: per-pair → (slot, pos) → phrase_id targets.
        train_set: dict[tuple[int, int], list[tuple[np.ndarray, int]]] = {}
        for prompt, resp in zip(prompts, responses):
            tgts = training_targets(prompt, resp, phrase_vocab,
                                       max_slots=max_slots)
            p_words = tokenize(prompt)[:max_slots]
            for (s, p), pid in tgts.items():
                if s >= len(p_words): continue
                stim = _embed_word(p_words[s])
                train_set.setdefault((s, p), []).append((stim, pid))

        log('')
        log('  training (slot, pos) → n_examples:')
        for key in sorted(train_set.keys()):
            log(f'    {key}: {len(train_set[key])} examples')

        chains: dict[tuple[int, int], list[bytes]] = {}
        cell_stats = []
        t_global = time.time()
        K = phrase_vocab['k_cells']

        for (s, p) in sorted(train_set.keys()):
            t_pos = time.time()
            log(''); log(f'== slot {s}, pos {p} ==')
            ex = train_set[(s, p)]
            stims = [e[0] for e in ex]
            pids = [e[1] for e in ex]
            log(f'  n_examples: {len(ex)}  targets: {pids}')
            chains[(s, p)] = []
            for c in range(K):
                cell_targets = [(pid >> ((K - 1 - c) * 2)) & 3 for pid in pids]
                res = _evolve_cell(
                    stims, cell_targets, ticks, iters=cell_iters,
                    seed=seed ^ (s * 99991) ^ (p * 50101) ^ (c * 7919),
                    flips_min=cell_flips_min, flips_max=cell_flips_max,
                    pop=cell_pop, log=log)
                chains[(s, p)].append(res['lut'])
                cell_stats.append({'slot': s, 'pos': p, 'cell': c,
                                       'n_correct': res['n_correct'],
                                       'total': res['total'],
                                       'iters': res['iters_used']})
                tag = '✓' if res['n_correct'] == res['total'] else f'({res["n_correct"]}/{res["total"]})'
                log(f'  cell {c}: {tag}  iters={res["iters_used"]}  targets {cell_targets}')
                (out / f'chain_s{s:02d}_p{p:02d}_c{c}.lut').write_bytes(res['lut'])
            log(f'  (slot {s}, pos {p}) wall: {time.time()-t_pos:.0f}s '
                f'(global {time.time()-t_global:.0f}s)')

        (out / 'phrase_vocab.json').write_text(json.dumps({
            'phrases':    phrase_vocab['phrases'],
            'expansions': phrase_vocab['expansions'],
            'k_cells':    K,
            'max_slots':  max_slots,
            'max_out':    max_out,
            'pairs':      pair_ids,
            'ticks':      ticks,
            'word_vocab': {'words': word_vocab['words'],
                            'k_cells': word_vocab['k_cells']},
            'cell_stats': cell_stats,
        }, indent=2))

        log(''); log(f'=== Eval: training set ===')
        model = pb.PhraseBinder(out, ticks=ticks)
        full = 0
        per_pair = []
        for p, r in zip(pairs_obj, responses):
            gen = model.generate(p.prompt)
            ex = (gen['text'] == r)
            if ex: full += 1
            tag = '✓ EXACT' if ex else '(mismatch)'
            log(f'  pair {p.pk:>3}: {p.prompt!r:25}')
            log(f'    expected: {r!r}')
            log(f'    got:      {gen["text"]!r}  {tag}')
            log(f'    per-slot: {[(s["input_word"], s["output_phrases"]) for s in gen["per_slot"]]}')
            per_pair.append({'pair_id': p.pk, 'prompt': p.prompt,
                               'expected': r, 'got': gen['text'],
                               'exact': ex,
                               'phrase_ids': gen['phrase_ids']})

        log(''); log(f'=== Training summary ===')
        log(f'  full-text exact: {full}/{len(pairs_obj)}')
        log(f'  total wall:      {time.time()-t_global:.0f}s')
        log(f'  chains:          {len(chains) * K} '
            f'({len(chains) * K * LUT_SIZE / 1024:.0f} KB)')

        holdouts = [s for s in (holdout_prompts or '').split(',') if s.strip()]
        if holdouts:
            log(''); log(f'=== Held-out / novel prompts ===')
            for hp in holdouts:
                gen = model.generate(hp)
                log(f'  {hp!r:30}')
                log(f'    text:     {gen["text"]!r}')
                log(f'    per-slot: {[(s["input_word"], s["output_phrases"]) for s in gen["per_slot"]]}')

        (out / 'training_eval.json').write_text(json.dumps({
            'pairs': pair_ids, 'full_match': full,
            'n_pairs': len(pairs_obj),
            'per_pair': per_pair,
            'holdouts': [{'prompt': hp,
                            'got': model.generate(hp)['text'],
                            'per_slot': model.generate(hp)['per_slot']}
                           for hp in holdouts],
        }, indent=2))
