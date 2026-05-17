"""manage.py deep_chain_search — direct-on-depth GA for class-4 quines.

Optimises rules whose iterated chain stays class-4 for as many levels
as possible.  Seeds from existing saved ComponentChampions; persists
new champions as it discovers them.

Usage:

    manage.py deep_chain_search
        Defaults: mu=4 lambda=6 gens=50 target=64 max=1024.

    manage.py deep_chain_search --gens 100 --target 128 --max 2048
        Aim for deeper chains; takes proportionally longer.

    manage.py deep_chain_search --log /tmp/deep-chain.log
        Tee progress to a file so background runs are inspectable.
"""
from __future__ import annotations

import time
from pathlib import Path

from django.core.management.base import BaseCommand

from spoeqi.deep_chain_search import GAConfig, run_deep_chain_search


class Command(BaseCommand):
    help = ('Evolutionary search for class-4 hex CA quines with very '
              'deep chain run lengths.')

    def add_arguments(self, parser):
        parser.add_argument('--mu',  type=int, default=4)
        parser.add_argument('--lam', type=int, default=6)
        parser.add_argument('--gens', type=int, default=50)
        parser.add_argument('--target', type=int, default=64,
                                help='Starting chain depth target.')
        parser.add_argument('--max',    type=int, default=1024,
                                help='Maximum chain depth target.')
        parser.add_argument('--metric', default='arbsigma',
                                choices=['arbsigma', 'strict'])
        parser.add_argument('--mutation-min', type=int, default=2)
        parser.add_argument('--mutation-max', type=int, default=64)
        parser.add_argument('--seed-top-n',   type=int, default=8)
        parser.add_argument('--seed-blockflip', type=int, default=4)
        parser.add_argument('--promote-at', type=float, default=0.92)
        parser.add_argument('--save-runlen', type=int, default=50,
                                help='Persist candidates whose run_length '
                                     'reaches this many levels.')
        parser.add_argument('--rng-seed', type=int, default=0)
        parser.add_argument('--exclude-pks', default='',
                                help='Comma-separated ComponentChampion '
                                     'pks to exclude from seeding (force '
                                     'GA to explore other rule regions).')
        parser.add_argument('--log',
                                help='Mirror stdout to this file as well.')
        parser.add_argument('--dry-run', action='store_true',
                                help='Run the GA but do not persist '
                                     'discoveries.')

    def handle(self, *args, **opts):
        excl = tuple(int(x.strip()) for x in opts['exclude_pks'].split(',')
                       if x.strip().isdigit())
        cfg = GAConfig(
            mu=opts['mu'], lam=opts['lam'],
            n_generations=opts['gens'],
            target_depth=opts['target'], max_depth=opts['max'],
            promote_at=opts['promote_at'],
            mutation_min=opts['mutation_min'],
            mutation_max=opts['mutation_max'],
            seed_top_n=opts['seed_top_n'],
            seed_blockflip=opts['seed_blockflip'],
            exclude_pks=excl,
            metric=opts['metric'],
            save_threshold_runlen=opts['save_runlen'],
            rng_seed=opts['rng_seed'],
        )

        log_path = Path(opts['log']) if opts.get('log') else None
        log_fh = None
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_fh = open(log_path, 'a', buffering=1)
            log_fh.write(f'\n=== deep_chain_search start {time.ctime()} ===\n')

        def log(line: str) -> None:
            self.stdout.write(line)
            if log_fh:
                log_fh.write(line + '\n')

        log('config: ' + ', '.join(
            f'{k}={v}' for k, v in cfg.__dict__.items()))
        t0 = time.time()
        result = run_deep_chain_search(
            cfg, log=log, save=not opts['dry_run'])
        dt = time.time() - t0

        log('')
        log(f'elapsed: {dt:.1f}s ({dt/cfg.n_generations:.2f}s/gen)')
        log(f'best fitness curve: '
            f'{[f"{f:.3f}" for f in result.best_history]}')
        log(f'persisted ComponentChampion pks: {result.persisted_pks}')
        log(f'final target depth: {result.final_target_depth}')

        if log_fh:
            log_fh.write(f'=== deep_chain_search end {time.ctime()} ===\n')
            log_fh.close()
