"""manage.py caformer_chain_probe — probe whether quine-chain levels
make competent caformer rules.

Compares two genome sources on the same fitness:

    A. RANDOM:   ``--n-random`` genomes built from independent random
                  rules (the existing baseline, scaled by the same RNG
                  the GA uses).
    B. CHAINS:   for the top ``--n-chains`` class-4 quines (or every
                  ``--run-label`` if specified), assemble a genome from
                  the chain's first 10 levels.  Optionally also probe
                  shifted windows (``--shifts 0,5,10``).

Fitness: ``make_text_fitness`` (logprob) on a small corpus.

If even one chain-derived genome's fitness lands meaningfully above
the random baseline's mean, the chain-attractor space contains useful
structure for caformer assembly and the bigger search (GA over chain
seeds) is worth running.
"""
from __future__ import annotations

import json
import time

from django.core.management.base import BaseCommand


# A compact corpus that doesn't require any model load.  Public-domain
# 19th-century English so byte-level perplexity has a meaningful baseline.
DEFAULT_CORPUS = (
    "It was the best of times, it was the worst of times, it was the age "
    "of wisdom, it was the age of foolishness, it was the epoch of belief, "
    "it was the epoch of incredulity, it was the season of Light, it was "
    "the season of Darkness, it was the spring of hope, it was the winter "
    "of despair, we had everything before us, we had nothing before us, "
    "we were all going direct to Heaven, we were all going direct the "
    "other way."
)


class Command(BaseCommand):
    help = ('Compare quine-chain-derived caformer genomes against '
            'random-rule baseline.')

    def add_arguments(self, parser):
        parser.add_argument('--n-chains', type=int, default=10,
                            help='top-K quines to probe (by fitness)')
        parser.add_argument('--n-random', type=int, default=20,
                            help='random baseline genomes to score')
        parser.add_argument('--run-label', type=str, default='',
                            help='restrict chain seeds to one run_label')
        parser.add_argument('--shifts', type=str, default='0',
                            help='comma-separated chain start offsets, '
                                 'e.g. "0,5,10" — each probed per quine')
        parser.add_argument('--n-blocks', type=int, default=1,
                            help='caformer depth (1 = matches qr_trainer)')
        parser.add_argument('--n-windows', type=int, default=16,
                            help='fitness sample windows on the corpus')
        parser.add_argument('--window-len', type=int, default=12)
        parser.add_argument('--corpus', type=str, default='',
                            help='custom text; falls back to DEFAULT_CORPUS')
        parser.add_argument('--save-json', type=str, default='',
                            help='write the full results table to this path')

    def handle(self, **opts):
        from caformer.chain_genome import genome_from_chain_shifted
        from caformer.ga import make_text_fitness, FULL_STACK_NAMES
        from caformer.primitives import random_rule_table
        from caformer.models import ComponentChampion
        import numpy as np

        corpus = opts['corpus'] or DEFAULT_CORPUS
        fitness = make_text_fitness(
            corpus, vocab_size=256, n_blocks=opts['n_blocks'],
            n_windows=opts['n_windows'],
            window_len=opts['window_len'], mode='logprob')

        def log(msg):
            ts = time.strftime('%H:%M:%S')
            self.stdout.write(f'[{ts}] {msg}'); self.stdout.flush()

        log(f'corpus: {len(corpus)} bytes  windows: {opts["n_windows"]}  '
            f'window_len: {opts["window_len"]}  n_blocks: {opts["n_blocks"]}')

        # ── A. random baseline ────────────────────────────────────────
        log(f'--- A. RANDOM baseline ({opts["n_random"]} genomes) ---')
        random_scores = []
        for i in range(opts['n_random']):
            g = {n: random_rule_table(0xC0DEC0DE ^ (i * 0x1234 + j))
                   for j, n in enumerate(FULL_STACK_NAMES)}
            t0 = time.time()
            s = fitness(g)
            random_scores.append(s)
            if i < 3 or (i % max(1, opts['n_random'] // 5)) == 0:
                log(f'  random[{i:>3d}]  fit={s:+.4f}  ({time.time()-t0:.2f}s)')
        rnd = np.array(random_scores)
        log(f'  RANDOM  mean={rnd.mean():+.4f}  std={rnd.std():.4f}  '
            f'best={rnd.max():+.4f}  worst={rnd.min():+.4f}')

        # ── B. quine-chain genomes ────────────────────────────────────
        qs = (ComponentChampion.objects
                .filter(component_slug='class4_quine')
                .order_by('-fitness'))
        if opts['run_label']:
            qs = qs.filter(run_label=opts['run_label'])
        quines = list(qs[:opts['n_chains']])
        shifts = [int(x) for x in opts['shifts'].split(',') if x.strip()]
        log(f'--- B. CHAIN-derived ({len(quines)} quines × {len(shifts)} '
            f'shifts = {len(quines)*len(shifts)} genomes) ---')

        chain_rows = []
        for q in quines:
            for sh in shifts:
                t0 = time.time()
                try:
                    g = genome_from_chain_shifted(bytes(q.rules_blob),
                                                       start=sh)
                except Exception as e:
                    log(f'  chain pk={q.pk} shift={sh}: ERROR {e}')
                    continue
                walk_s = time.time() - t0
                t1 = time.time()
                s = fitness(g)
                eval_s = time.time() - t1
                chain_rows.append({
                    'pk': q.pk, 'shift': sh, 'fitness': float(s),
                    'walk_s': walk_s, 'eval_s': eval_s,
                    'origin': q.run_label, 'champ_fit': float(q.fitness),
                })
                log(f'  chain  pk={q.pk:>5d}  shift={sh:>3d}  '
                    f'fit={s:+.4f}  walk={walk_s:.1f}s  '
                    f'eval={eval_s:.2f}s  ({q.run_label or "?"})')

        # ── Summary ───────────────────────────────────────────────────
        log('--- summary ---')
        if chain_rows:
            chain_fits = np.array([r['fitness'] for r in chain_rows])
            log(f'  CHAIN   mean={chain_fits.mean():+.4f}  '
                f'std={chain_fits.std():.4f}  '
                f'best={chain_fits.max():+.4f}  worst={chain_fits.min():+.4f}')
            best = max(chain_rows, key=lambda r: r['fitness'])
            log(f'  best chain genome: pk={best["pk"]} shift={best["shift"]}  '
                f'fit={best["fitness"]:+.4f}')
            gap = best['fitness'] - rnd.mean()
            n_better = int((chain_fits > rnd.mean()).sum())
            log(f'  gap vs RANDOM mean: {gap:+.4f}  '
                f'({n_better}/{len(chain_rows)} chains beat random mean)')
            if best['fitness'] > rnd.max():
                log('  VERDICT: at least one chain beats every random baseline. '
                    'The chain-attractor space contains useful structure.')
            elif gap > 0:
                log('  VERDICT: chains beat random-mean but not random-best. '
                    'Marginal; bigger GA over chain seeds may still be worth it.')
            else:
                log('  VERDICT: chains do not beat random baseline on this '
                    'corpus.  Chain attractors may not align with the '
                    'caformer fitness surface here.')

        if opts['save_json']:
            path = opts['save_json']
            json.dump({
                'corpus_len': len(corpus),
                'n_windows':  opts['n_windows'],
                'window_len': opts['window_len'],
                'n_blocks':   opts['n_blocks'],
                'random_scores': list(map(float, rnd)),
                'chain_rows':    chain_rows,
            }, open(path, 'w'), indent=2)
            log(f'wrote {path}')
