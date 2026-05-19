"""Train a word-binder: per-word-position chains emitting word IDs.

See caformer.word_binder for the architecture.  This command is the
GA trainer + persistence layer.  It mirrors caformer_funnel_tokens
but at word granularity instead of byte granularity.

Usage::

    manage.py caformer_word_binder
    manage.py caformer_word_binder --pairs 2,3,4,5,6,9,10,11,12,13,15,16,17,18,19,20,21,22 \\
                                      --max-words 8 --cell-iters 3000
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

from caformer import word_binder as wb
from caformer.word_binder import (
    LUT_SIZE, N_STATES, STOP_ID, _embed_prompt, _run,
    tokenize, build_vocab, encode_response, cell_targets_for_position,
)


# Default pairs: the original 11 conflict-free + the 7 compositional
# seeds added 2026-05-18 for word-binder training.
DEFAULT_PAIRS = '2,3,4,5,6,9,10,11,12,13,15,16,17,18,19,20,21,22'


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


def _cell_fitness(lut: bytes, stimuli, targets, ticks) -> int:
    n = 0
    for stim, tgt in zip(stimuli, targets):
        if int(_run(np.frombuffer(lut, dtype=np.uint8) & 3,
                       stim, ticks)[0, 0]) == tgt:
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
    if M == 0:
        return {'lut': best_lut, 'n_correct': 0, 'total': 0, 'iters_used': 0}
    for it in range(iters):
        parent = rng.choice(pop_list[:max(1, pop // 2)])
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
              'iters_used': it + 1 if M > 0 else 0}


class Command(BaseCommand):
    help = ('Train a word-level binder: per-word-position chains emitting '
              'vocab IDs (decode = lookup + space-join). Validates '
              'compositional generalisation of the per-cell-chain layer.')

    def add_arguments(self, parser):
        parser.add_argument('--pairs',   type=str, default=DEFAULT_PAIRS)
        parser.add_argument('--max-words', type=int, default=8)
        parser.add_argument('--ticks',   type=int, default=6)
        parser.add_argument('--cell-pop',   type=int, default=10)
        parser.add_argument('--cell-iters', type=int, default=3000)
        parser.add_argument('--cell-flips-min', type=int, default=4)
        parser.add_argument('--cell-flips-max', type=int, default=200)
        parser.add_argument('--out-dir', type=str,
                              default='.artifacts/word_binder_v1')
        parser.add_argument('--seed', type=int, default=0xB10D_C0DE)
        parser.add_argument('--holdout-prompts', type=str, default='',
            help='Comma-separated novel prompts to probe after training.')

    def handle(self, *, pairs, max_words, ticks, cell_pop, cell_iters,
                 cell_flips_min, cell_flips_max, out_dir, seed,
                 holdout_prompts, **opts):
        from caformer.models import QRPair

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        out = Path(settings.BASE_DIR) / out_dir
        out.mkdir(parents=True, exist_ok=True)

        pair_ids = [int(x) for x in pairs.split(',')]
        pairs_obj = [QRPair.objects.get(pk=pk) for pk in pair_ids]
        n_pairs = len(pairs_obj)
        responses = [p.expected for p in pairs_obj]
        prompts = [p.prompt for p in pairs_obj]

        # Vocab
        vocab = build_vocab(responses)
        V = vocab['size']
        K = vocab['k_cells']

        log(f'=== Word-binder ===')
        log(f'  pairs:       {n_pairs}')
        log(f'  vocab:       {V} tokens (STOP={STOP_ID}, UNK=1)')
        log(f'  cells/word:  {K} (encodes up to {N_STATES**K} vocab IDs)')
        log(f'  max words:   {max_words}')
        log(f'  ticks:       {ticks}')
        log(f'  cell GA:     pop={cell_pop} iters={cell_iters}')
        log('')
        log('  vocab table:')
        for i, w in enumerate(vocab['words']):
            tag = '  (STOP)' if i == STOP_ID else '  (UNK)' if i == 1 else ''
            log(f'    {i:>3}: {w!r}{tag}')
        log('')
        for p, r in zip(pairs_obj, responses):
            ids = encode_response(r, vocab, max_words)
            log(f'  pair {p.pk:>3}: {p.prompt!r:25} → {r!r:42} → {ids}')

        # Embed prompts
        stimuli = [_embed_prompt(p) for p in prompts]

        # Per-position word-ID targets (padded with STOP)
        word_ids_by_pair = [encode_response(r, vocab, max_words)
                              for r in responses]

        # ── Per-word-position training ──
        chains: dict[int, list[bytes]] = {}
        cell_stats = []
        t_global = time.time()
        for w in range(max_words):
            log('')
            log(f'== word position {w} ==')
            t_pos = time.time()
            # Find pairs where pos w isn't padding-only (any non-STOP at w).
            # For chains to make sense, train on ALL pairs (STOP is a legit
            # target — must emit STOP at the right position).
            pos_targets_wid = [word_ids_by_pair[i][w] for i in range(n_pairs)]
            log(f'  targets ({n_pairs} pairs): {pos_targets_wid}')
            chains[w] = []
            for c in range(K):
                cell_targets = [(wid >> ((K - 1 - c) * 2)) & 3
                                  for wid in pos_targets_wid]
                res = _evolve_cell(
                    stimuli, cell_targets, ticks,
                    iters=cell_iters,
                    seed=seed ^ (w * 99991) ^ (c * 7919),
                    flips_min=cell_flips_min, flips_max=cell_flips_max,
                    pop=cell_pop, log=log)
                chains[w].append(res['lut'])
                cell_stats.append({
                    'pos': w, 'cell': c,
                    'n_correct': res['n_correct'], 'total': res['total'],
                    'iters': res['iters_used'],
                })
                tag = '✓' if res['n_correct'] == res['total'] else \
                        f'({res["n_correct"]}/{res["total"]})'
                log(f'  cell {c}: {tag}  iters={res["iters_used"]}  '
                    f'targets {cell_targets}')
                (out / f'chain_w{w:02d}_c{c}.lut').write_bytes(res['lut'])
            log(f'  pos {w} wall: {time.time()-t_pos:.0f}s '
                f'(global {time.time()-t_global:.0f}s)')

        # Persist vocab + meta
        (out / 'vocab.json').write_text(json.dumps({
            'words':         vocab['words'],
            'k_cells':       K,
            'max_positions': max_words,
            'pairs':         pair_ids,
            'ticks':         ticks,
            'cell_stats':    cell_stats,
        }, indent=2))

        # ── Eval: training set ──
        log('')
        log(f'=== Eval: training set ===')
        model = wb.WordBinderModel(out, ticks=ticks)
        full_match = 0
        per_pair_results = []
        for p, r in zip(pairs_obj, responses):
            gen = model.generate(p.prompt)
            exp_words = tokenize(r)
            got_words = gen['words']
            # Stop comparison at first STOP / end
            n_compare = max(len(exp_words), len(got_words))
            byte_match = (gen['text'] == r)
            tag = '✓ EXACT' if byte_match else f'(text mismatch)'
            log(f'  pair {p.pk:>3}: {p.prompt!r:25}')
            log(f'    expected: {r!r}')
            log(f'    got:      {gen["text"]!r}  {tag}')
            log(f'    ids:      {gen["word_ids"]}')
            if byte_match:
                full_match += 1
            per_pair_results.append({
                'pair_id':  p.pk,
                'prompt':   p.prompt,
                'expected': r,
                'got':      gen['text'],
                'ids':      gen['word_ids'],
                'exact':    byte_match,
            })

        log('')
        log(f'=== Training summary ===')
        log(f'  full-text exact:   {full_match}/{n_pairs}')
        log(f'  total wall:        {time.time()-t_global:.0f}s')
        log(f'  chains:            {max_words * K} '
            f'({max_words * K * LUT_SIZE / 1024:.0f} KB)')

        # ── Probe held-out novel prompts ──
        holdouts = [s for s in (holdout_prompts or '').split(',') if s.strip()]
        if holdouts:
            log('')
            log(f'=== Held-out / novel prompts ===')
            for hp in holdouts:
                gen = model.generate(hp)
                log(f'  {hp!r:30} → {gen["text"]!r}')
                log(f'    ids:      {gen["word_ids"]}')

        (out / 'training_eval.json').write_text(json.dumps({
            'pairs':       pair_ids,
            'full_match':  full_match,
            'n_pairs':     n_pairs,
            'per_pair':    per_pair_results,
            'holdouts':    [{'prompt': hp,
                              'got': model.generate(hp)['text']}
                             for hp in holdouts],
        }, indent=2))
