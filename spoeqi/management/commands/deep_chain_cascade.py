"""manage.py deep_chain_cascade — autonomous multi-stage deep-chain hunt.

Stages: 256 → 512 → 1024 → 2048 → 4096 → 8192 → 16384 → 32768 → 65536
(or as configured).  Each stage runs ``run_deep_chain_search`` with
the previous stage's winners auto-included via the standard seeding
path (top-fitness ComponentChampions get pulled in automatically).

The cascade is meant to be launched in the background and left
alone.  Stops early if a stage produces no candidate exceeding the
previous stage's best — that signals a structural ceiling at the
current depth and continuing into deeper targets is unlikely to
help.

Usage:

    manage.py deep_chain_cascade --log /tmp/cascade.log
        Default schedule, autonomous.

    manage.py deep_chain_cascade --schedule 512,1024,2048,4096
        Custom stage list.

    manage.py deep_chain_cascade --max-stage-minutes 30
        Cap each stage to ~30 minutes of wall-clock; stages that
        plateau early move on sooner.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from django.core.management.base import BaseCommand


DEFAULT_SCHEDULE = [256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536]


class Command(BaseCommand):
    help = 'Cascading deep-chain quine search — stages of progressively deeper targets.'

    def add_arguments(self, parser):
        parser.add_argument('--schedule', default='',
                                help='Comma-separated target-depth list. '
                                     'Default: %s' % ','.join(str(x) for x in DEFAULT_SCHEDULE))
        parser.add_argument('--gens-per-stage', type=int, default=25,
                                help='GA generations per stage (default 25).')
        parser.add_argument('--mu',  type=int, default=6)
        parser.add_argument('--lam', type=int, default=12)
        parser.add_argument('--mutation-min', type=int, default=2)
        parser.add_argument('--mutation-max', type=int, default=128)
        parser.add_argument('--seed-top-n',  type=int, default=20)
        parser.add_argument('--seed-blockflip', type=int, default=4)
        parser.add_argument('--metric', default='arbsigma',
                                choices=['arbsigma', 'strict'])
        parser.add_argument('--act-hi', type=float, default=0.85,
                                help='Upper bound of activity band '
                                     '(default 0.85).')
        parser.add_argument('--sr-threshold', type=float, default=0.85)
        parser.add_argument('--rng-seed', type=int, default=0,
                                help='Base RNG seed; each stage uses '
                                     'rng_seed + stage_index.')
        parser.add_argument('--max-stage-seconds', type=int, default=0,
                                help='Soft cap per stage (0 = no cap).')
        parser.add_argument('--min-improvement', type=int, default=10,
                                help='If a stage does not exceed the '
                                     'previous best by at least this many '
                                     'levels, stop the cascade.')
        parser.add_argument('--log',
                                help='Mirror stdout to this file.')

    def handle(self, *args, **opts):
        from spoeqi.deep_chain_search import (
            GAConfig, run_deep_chain_search, chain_depth_fitness)

        if opts['schedule']:
            schedule = [int(x.strip()) for x in opts['schedule'].split(',')
                         if x.strip()]
        else:
            schedule = list(DEFAULT_SCHEDULE)

        log_path = Path(opts['log']) if opts.get('log') else None
        log_fh = None
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_fh = open(log_path, 'a', buffering=1)
            log_fh.write(f'\n=== deep_chain_cascade start '
                            f'{time.ctime()} (pid={os.getpid()}) ===\n')

        def log(line: str) -> None:
            self.stdout.write(line)
            if log_fh:
                log_fh.write(line + '\n')

        prev_best_run = 0
        cascade_start = time.time()
        log(f'cascade schedule: {schedule}')
        log(f'gens/stage={opts["gens_per_stage"]}  '
            f'mu={opts["mu"]} lam={opts["lam"]}  '
            f'mutation=[{opts["mutation_min"]},{opts["mutation_max"]}]  '
            f'metric={opts["metric"]}  '
            f'act_band=(0.05,{opts["act_hi"]})  '
            f'sr_threshold={opts["sr_threshold"]}')

        for stage_i, target in enumerate(schedule):
            stage_t0 = time.time()
            log('\n' + '═' * 72)
            log(f'STAGE {stage_i+1}/{len(schedule)}  target={target}')
            log('═' * 72)

            cfg = GAConfig(
                mu=opts['mu'], lam=opts['lam'],
                n_generations=opts['gens_per_stage'],
                target_depth=target,
                max_depth=target,        # don't auto-promote within a stage
                promote_at=2.0,          # effectively disable internal promote
                mutation_min=opts['mutation_min'],
                mutation_max=opts['mutation_max'],
                seed_top_n=opts['seed_top_n'],
                seed_blockflip=opts['seed_blockflip'],
                metric=opts['metric'],
                sr_threshold=opts['sr_threshold'],
                act_band=(0.05, opts['act_hi']),
                save_threshold_runlen=max(prev_best_run + 1,
                                                  int(target * 0.2)),
                rng_seed=opts['rng_seed'] + stage_i if opts['rng_seed']
                         else 0,
            )

            # Optional wall-clock cap: snip n_generations to fit.
            if opts['max_stage_seconds']:
                # Heuristic: gens roughly scale with target depth.
                ms = opts['max_stage_seconds']
                est_per_gen = (cfg.lam * target * 16 * 50e-6 + 1.0)
                max_gens = max(5, int(ms / est_per_gen))
                if max_gens < cfg.n_generations:
                    log(f'  capping gens: {cfg.n_generations} → {max_gens} '
                        f'(est {est_per_gen:.1f}s/gen, cap {ms}s/stage)')
                    cfg.n_generations = max_gens

            result = run_deep_chain_search(cfg, log=log, save=True)
            stage_dt = time.time() - stage_t0
            if result.generations:
                stage_best = result.generations[-1][0]
                stage_best_run = stage_best.run_length
            else:
                stage_best_run = 0

            log(f'\nSTAGE {stage_i+1} summary: best={stage_best_run}/{target} '
                f'in {stage_dt:.1f}s. '
                f'persisted={len(result.persisted_pks)}')

            if stage_best_run < prev_best_run + opts['min_improvement']:
                log(f'  ↳ improvement < {opts["min_improvement"]} levels '
                    f'over prev_best={prev_best_run}; cascade stops here.')
                break
            prev_best_run = stage_best_run

        total_dt = time.time() - cascade_start
        log(f'\n=== cascade complete in {total_dt:.0f}s '
            f'({total_dt/3600:.2f}h) ===')
        log(f'final best run_length: {prev_best_run}')
        # Final survey across deep-chain champions
        from caformer.models import ComponentChampion
        deep = list(ComponentChampion.objects.filter(
            component_slug='class4_quine',
            run_label='deep-chain-ga').order_by('-eval_count')[:10])
        log('Top 10 deep-chain champions by eval_count (= GA run_length):')
        for q in deep:
            log(f'  pk={q.pk:>4d}  fit={q.fitness:.3f}  '
                f'eval_count={q.eval_count:>6d}  '
                f'created={q.created_at.strftime("%Y-%m-%d %H:%M")}')

        if log_fh:
            log_fh.write(f'\n=== deep_chain_cascade end {time.ctime()} ===\n')
            log_fh.close()
