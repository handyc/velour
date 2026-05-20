"""(μ+λ) GA over stack genomes.

  manage.py boardstack_evolve --gens 50 --pop 16 --test-set v1
  manage.py boardstack_evolve --n-boards 32 --board-side 64 \\
      --gens 100 --persist
"""
from __future__ import annotations

import json
import sys
import time

from django.core.management.base import BaseCommand
from django.utils.text import slugify


class Command(BaseCommand):
    help = ('Evolve a stack-of-CAs genome against the byte-stream '
            'pair-match fitness.')

    def add_arguments(self, parser):
        parser.add_argument('--n-boards', type=int, default=16)
        parser.add_argument('--board-side', type=int, default=32)
        parser.add_argument('--stack-ticks', type=int, default=4)
        parser.add_argument('--test-set', type=str, default='v1',
                              choices=['v1', 'incr', 'echo'])
        parser.add_argument('--personality', type=int, default=0,
                              choices=[0, 1, 2, 3])
        parser.add_argument('--pop', type=int, default=16)
        parser.add_argument('--elite-n', type=int, default=2)
        parser.add_argument('--gens', type=int, default=30)
        parser.add_argument('--mutation-rate', type=float, default=0.10)
        parser.add_argument('--seed', type=int, default=0xB05ACE)
        parser.add_argument('--seed-init', type=str, default='random',
                              choices=['random', 'naive_pipeline', 'echo'],
                              help='initial-population shape: '
                                     'random = fully random wiring; '
                                     'naive_pipeline = board K reads board K-1 '
                                     'TL cell, linear chain; '
                                     'echo = every board reads prompt port')
        parser.add_argument('--persist', action='store_true',
                              help='save best genome + run summary to DB')
        parser.add_argument('--slug', type=str, default='',
                              help='override the auto-generated slug')

    def handle(self, *, n_boards, board_side, stack_ticks, test_set,
                 personality, pop, elite_n, gens, mutation_rate, seed,
                 seed_init, persist, slug, **opts):
        from boardstack.ga import evolve_stack
        from boardstack.models import StackGenome, EvolutionRun
        from django.utils.timezone import now

        def log(m): self.stdout.write(m + '\n'); self.stdout.flush()

        log(f'=== boardstack_evolve ===')
        log(f'  n_boards × side: {n_boards} × {board_side}')
        log(f'  stack_ticks:     {stack_ticks}')
        log(f'  test_set:        {test_set}')
        log(f'  pop / elite / gens: {pop} / {elite_n} / {gens}')
        log(f'  mutation rate:   {mutation_rate}')
        log(f'  seed:            0x{seed:08x}')
        log(f'  seed_init:       {seed_init}\n')

        def on_event(k, p):
            if k == 'init':
                log(f'  [gen   -] init  best_fit={p["best_fit"]:.4f}  '
                    f'best_byte_match={p["best_byte_match"]}')
            elif k == 'gen':
                log(f'  [gen {p["gen"]:3d}] '
                    f'best_fit={p["best_fit"]:.4f}  '
                    f'best_byte_match={p["best_byte_match"]:2d}  '
                    f'mean_fit={p["mean_fit"]:.4f}  '
                    f'wall={p["wall"]:.1f}s  '
                    f'(ever={p["best_ever_fit"]:.4f}/'
                    f'{p["best_ever_byte_match"]})')

        t0 = time.time()
        r = evolve_stack(
            n_boards=n_boards, board_side=board_side,
            stack_ticks=stack_ticks,
            test_set=test_set, personality=personality,
            pop_size=pop, elite_n=elite_n,
            generations=gens, mutation_rate=mutation_rate,
            seed=seed, seed_init=seed_init, on_event=on_event)
        wall = time.time() - t0

        log(f'\n=== done ({wall:.1f}s) ===')
        log(f'  best fitness:    {r["best_fitness"]:.4f}')
        log(f'  best byte match: {r["best_byte_match"]}/{r["n_pairs"]}')
        log(f'  n_evals:         {r["n_evals"]}  '
            f'({wall/r["n_evals"]:.2f}s/eval)')
        log(f'  pool LUTs used:  {r["pool_cache_hits"]}')

        if persist:
            run_slug = slug or slugify(
                f'evolve-{test_set}-{n_boards}x{board_side}-'
                f'gen{gens}-{int(time.time())}')[:80]
            gen_slug = (slug or f'best-{run_slug}')[:80]
            sg, _ = StackGenome.objects.update_or_create(
                slug=gen_slug, defaults={
                    'n_boards':    n_boards,
                    'board_side':  board_side,
                    'gene_json':   json.loads(json.dumps(
                        r['best_genome'], default=list)),
                    'fitness':     r['best_fitness'],
                    'test_set_id': test_set,
                    'notes':       f'gen={gens} pop={pop} mut={mutation_rate}',
                })
            run = EvolutionRun.objects.create(
                slug=run_slug,
                finished_at=now(),
                config_json={
                    'n_boards': n_boards, 'board_side': board_side,
                    'stack_ticks': stack_ticks, 'test_set': test_set,
                    'personality': personality, 'pop': pop,
                    'elite_n': elite_n, 'gens': gens,
                    'mutation_rate': mutation_rate, 'seed': seed,
                    'trajectory': r['trajectory'],
                },
                best_genome=sg,
                n_generations=gens,
                n_evals=r['n_evals'],
                notes=f'best fitness {r["best_fitness"]:.4f}, '
                          f'best byte_match {r["best_byte_match"]}/{r["n_pairs"]}',
            )
            log(f'\n  persisted as EvolutionRun slug={run.slug}')
            log(f'                StackGenome slug={sg.slug}')
