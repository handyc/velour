"""manage.py l0_fp_quine_search — hunt for a true L0 fixed-point
class-4 quine: a rule R such that CA^16 applied to R's LUT-as-image
returns R's LUT byte-for-byte AND R is itself class-4.

Two-phase:
    Phase A: scan every level of every saved quine's chain for an
             already-present hit.
    Phase B: directed (μ+λ) ES seeded from the closest near-quine
             rules in the existing chain library.
"""
from __future__ import annotations

import sys
import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Search for a true L0 fixed-point class-4 quine.'

    def add_arguments(self, parser):
        parser.add_argument('--mu', type=int, default=8,
                            help='ES parent population size')
        parser.add_argument('--lambda', type=int, dest='lam', default=24,
                            help='ES children per generation')
        parser.add_argument('--generations', type=int, default=2000,
                            help='Number of GA generations (Phase B)')
        parser.add_argument('--mutation-min', type=int, default=1)
        parser.add_argument('--mutation-max', type=int, default=8)
        parser.add_argument('--seed-top-n', type=int, default=32,
                            help='Number of near-quine seeds to gather')
        parser.add_argument('--seed-sr-min', type=float, default=0.85,
                            help='Min sr_strict for chain-level seeds')
        parser.add_argument('--rng-seed', type=int, default=0)
        parser.add_argument('--progress-every', type=int, default=5)
        parser.add_argument('--save-threshold-sr', type=float, default=0.98,
                            help='Save anything with sr_strict at or above this AND cls==4')
        parser.add_argument('--skip-phase-a', action='store_true',
                            help='Skip the existing-chain scan and jump to ES')
        parser.add_argument('--no-save', action='store_true',
                            help='Don\'t persist discoveries; for dry-run')

    def handle(self, **opts):
        from spoeqi.l0_quine_search import (L0GAConfig, run_l0_fp_search)
        cfg = L0GAConfig(
            mu=opts['mu'], lam=opts['lam'],
            n_generations=opts['generations'],
            mutation_min=opts['mutation_min'],
            mutation_max=opts['mutation_max'],
            seed_top_n=opts['seed_top_n'],
            seed_sr_min=opts['seed_sr_min'],
            rng_seed=opts['rng_seed'],
            progress_every=opts['progress_every'],
            save_threshold_sr=opts['save_threshold_sr'],
        )

        def log(msg: str) -> None:
            ts = time.strftime('%H:%M:%S')
            self.stdout.write(f'[{ts}] {msg}')
            self.stdout.flush()

        t0 = time.time()
        log(f'l0_fp_quine_search starting (mu={cfg.mu}, lam={cfg.lam}, '
            f'gens={cfg.n_generations}, mutation={cfg.mutation_min}'
            f'..{cfg.mutation_max})')

        if opts['skip_phase_a']:
            # Stub: skip Phase A by jumping in at Phase B seeding.
            from spoeqi.l0_quine_search import (gather_near_quine_seeds,
                                                    mutate_near_quine,
                                                    l0_fitness, Candidate,
                                                    _persist_l0_fp, L0GAResult)
            import random
            rng = random.Random(cfg.rng_seed or int(time.time()))
            result = L0GAResult()
            raw_seeds = gather_near_quine_seeds(sr_min=cfg.seed_sr_min,
                                                    max_depth=200,
                                                    top_n=cfg.seed_top_n,
                                                    log=log)
            if not raw_seeds:
                log('no seeds; aborting')
                return
            # Same loop as in run_l0_fp_search Phase B (copy-paste OK
            # for a one-shot CLI flag).
            pop = []
            for rule_b, origin, m in raw_seeds:
                pop.append(Candidate(rule=rule_b, origin=origin,
                                        fitness=m['fitness'],
                                        sr_strict=m['sr_strict'],
                                        cls=m['cls'], c4_score=m['c4_score'],
                                        act=m['act']))
            pop.sort(key=lambda c: -c.fitness)
            parents = pop[:cfg.mu]
            saved = set()
            for gen in range(cfg.n_generations):
                children = []
                per_parent = max(1, cfg.lam // max(len(parents), 1))
                for p in parents:
                    for _ in range(per_parent):
                        n = rng.randint(cfg.mutation_min, cfg.mutation_max)
                        children.append(Candidate(
                            rule=mutate_near_quine(p.rule, n, rng),
                            parent_id=p.short(),
                            origin=f'mut(n={n}) of {p.short()}'))
                for c in children:
                    f = l0_fitness(c.rule, ticks=16)
                    c.fitness = f['fitness']; c.sr_strict = f['sr_strict']
                    c.cls = f['cls']; c.c4_score = f['c4_score']; c.act = f['act']
                parents = sorted(parents + children, key=lambda c: -c.fitness)[:cfg.mu]
                best = parents[0]
                if (gen % cfg.progress_every) == 0 or best.sr_strict >= 0.9999:
                    log(f'gen {gen:>4}  best  sha={best.short()}  '
                        f'sr={best.sr_strict:.4f}  cls={best.cls}  '
                        f'c4={best.c4_score:.3f}  fit={best.fitness:.3f}  '
                        f'origin={best.origin}')
                for c in parents:
                    if c.sr_strict >= 0.9999 and c.cls == 4:
                        sha = c.short()
                        if sha in saved:
                            continue
                        saved.add(sha)
                        log(f'  ★ FOUND L0-FP C4!  sha={sha}  sr={c.sr_strict:.4f}')
                        if not opts['no_save']:
                            pk = _persist_l0_fp(c.rule,
                                                  origin=f'phase-B-only gen {gen}',
                                                  parent_sha=c.parent_id,
                                                  log=log)
                            if pk:
                                result.persisted_pks.append(pk)
        else:
            result = run_l0_fp_search(cfg, log=log,
                                         save=not opts['no_save'])

        elapsed = time.time() - t0
        log('')
        log(f'=== summary (elapsed {elapsed/60:.1f} min) ===')
        log(f'discoveries: {len(result.found_rules)}')
        log(f'persisted:   {len(result.persisted_pks)} new ComponentChampions')
        for pk in result.persisted_pks:
            log(f'  → #{pk}')
