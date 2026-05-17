"""Evolve the 9 shared base rules to make per-token chains argmax-competent.

The per-token chains alone can't escape the "natural prior" set by the
random base rules (they push final-state cells into low-byte indices
regardless of which chain level we apply).  Co-evolving the base rules
*against the fixed chain library* re-shapes that prior so the chain's
output rules can actually argmax the right bytes.

Storage: base rules are 36,864 packed bytes, shared across ALL QRPairs
forever.  Per-token origins stay at 4,096 packed bytes each.

Usage::

    venv/bin/python manage.py caformer_coevolve_base --pairs 2,11
    venv/bin/python manage.py caformer_coevolve_base --pairs 2 --gens 16 --pop 12
"""
from __future__ import annotations

import sys

from django.core.management.base import BaseCommand, CommandError

from caformer.per_token_chain import CoevolveConfig, coevolve_base


class Command(BaseCommand):
    help = 'Co-evolve 9 shared base rules against fixed per-token chains.'

    def add_arguments(self, parser):
        parser.add_argument('--pairs', type=str, required=True,
                              help='comma-separated QRPair pks (e.g. 2,11)')
        parser.add_argument('--depth', type=int, default=16)
        parser.add_argument('--ticks', type=int, default=8)
        parser.add_argument('--select-n', type=int, default=8,
                              help='per-token L0 candidates considered')
        parser.add_argument('--pop', type=int, default=8)
        parser.add_argument('--gens', type=int, default=8,
                              help='base-GA generations per alt round')
        parser.add_argument('--alt-rounds', type=int, default=1,
                              help='alternations of (re-select origins) + (base GA)')
        parser.add_argument('--mu', type=int, default=3)
        parser.add_argument('--mut-rate', type=float, default=0.003)
        parser.add_argument('--seed', type=int, default=0xC0E0_0001)
        parser.add_argument('--fitness', choices=['lp', 'matches'], default='lp',
                              help='fitness mode: lp (smooth, default) or matches (legacy step)')
        parser.add_argument('--no-smart-mutation', action='store_true',
                              help='disable smart mutation (use untargeted random flips)')

    def handle(self, *args, pairs, depth, ticks, select_n, pop, gens, mu,
                 mut_rate, seed, alt_rounds, fitness, no_smart_mutation, **opts):
        try:
            pair_ids = [int(x) for x in pairs.split(',')]
        except ValueError:
            raise CommandError(f'--pairs must be comma-separated ints, got {pairs!r}')

        def _log(msg):
            sys.stdout.write(str(msg) + '\n')
            sys.stdout.flush()

        cfg = CoevolveConfig(
            pair_ids=pair_ids, chain_depth=depth, ticks_per_level=ticks,
            select_n=select_n, pop_size=pop, generations=gens, mu=mu,
            mutation_rate=mut_rate, rng_seed=seed,
            alt_rounds=alt_rounds, fitness_mode=fitness,
            smart_mutation=not no_smart_mutation, log=_log,
        )
        result = coevolve_base(cfg)

        self.stdout.write('')
        self.stdout.write(self.style.NOTICE('=== summary ==='))
        N = result.total_positions
        self.stdout.write(
            f'corpus positions      : {N}\n'
            f'initial base matches  : {result.initial_base_matches}/{N}  '
            f'(lp {result.initial_base_lp:+.2f})\n'
            f'final base matches    : {result.final_base_matches}/{N}  '
            f'(lp {result.final_base_lp:+.2f})\n'
            f'Δ matches             : '
            f'{result.final_base_matches - result.initial_base_matches:+d}'
        )
        self.stdout.write('')
        self.stdout.write(self.style.NOTICE('per-pair (final base):'))
        for pk, (m, n) in sorted(result.per_pair_matches.items()):
            self.stdout.write(f'  pair #{pk}: {m}/{n}')
        self.stdout.write('')
        self.stdout.write(self.style.NOTICE('history (gen, best_matches, best_lp):'))
        for gen, m, lp in result.history:
            self.stdout.write(f'  gen {gen:>2}: {m}/{N}  lp={lp:+.2f}')
