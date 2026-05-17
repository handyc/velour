"""manage.py caformer_autotournament — continuously evolve each of
the 8 caformer components and rank them.

Defaults pick a sensible cadence: 8 components × ~3s per cycle ≈
~25s per cycle.  Use ``--budget 1800`` for a 30-minute background run
under supervisor, or ``--cycles 1`` for a one-shot rotation.

  manage.py caformer_autotournament
      # one rotation through all 8 components

  manage.py caformer_autotournament --budget 1800 --label nightly
      # 30 min budget, labels saved champions 'nightly'

  manage.py caformer_autotournament --only embedding,mlp --pop 16 --gens 12
      # focus on two components with a deeper GA
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Run the per-component caformer autotournament loop. Each '
            'cycle rotates through 8 components, evolving each from its '
            'current champion and saving any improvement.')

    def add_arguments(self, parser):
        parser.add_argument('--pop',       type=int, default=8)
        parser.add_argument('--gens',      type=int, default=6)
        parser.add_argument('--cycles',    type=int, default=1,
                            help='number of full rotations; ignored if '
                                 '--budget is set')
        parser.add_argument('--budget',    type=float, default=0.0,
                            help='wall-clock seconds; 0 = unlimited')
        parser.add_argument('--mutation',  type=float, default=0.005)
        parser.add_argument('--seed',      type=int, default=0xC0FFEE_CA)
        parser.add_argument('--label',     type=str, default='auto')
        parser.add_argument('--only',      type=str, default='',
                            help='comma-separated component slugs '
                                 '(default = all 8)')
        parser.add_argument('--skip',      type=str, default='',
                            help='comma-separated component slugs to skip')
        parser.add_argument('--save-all',  action='store_true',
                            help='save EVERY scored individual as a '
                                 'ComponentChampion row (not just '
                                 'parent-beating ones); fast path to a '
                                 'large library, adds ~pop·gens rows per '
                                 'component per cycle')

    def handle(self, **opts):
        from caformer.component_tournament import (
            ComponentTournamentConfig, run_autotournament,
        )

        cfg = ComponentTournamentConfig(
            pop_size=opts['pop'],
            generations=opts['gens'],
            mutation_rate=opts['mutation'],
            seed=opts['seed'],
            max_cycles=opts['cycles'] if not opts['budget'] else 10_000,
            max_seconds=opts['budget'],
            only_components=tuple(s.strip() for s in opts['only'].split(',') if s.strip()),
            skip_components=tuple(s.strip() for s in opts['skip'].split(',') if s.strip()),
            run_label=opts['label'],
            save_all_individuals=opts['save_all'],
        )

        self.stdout.write(self.style.SUCCESS(
            f'autotournament: pop={cfg.pop_size} gens={cfg.generations} '
            f'budget={cfg.max_seconds}s cycles={cfg.max_cycles} '
            f'label={cfg.run_label!r}'))

        def _on_event(kind, payload):
            if kind == 'cycle_begin':
                self.stdout.write(
                    f'  ▸ cycle {payload["cycle"]} · {payload["component"]:18s} '
                    f'parent={payload["parent_fitness"]:+.4f} '
                    f'(g{payload["parent_generation"]})')
            elif kind == 'cycle_end':
                tag = self.style.SUCCESS('✓ SAVED') if payload['improved'] \
                       else '  skip  '
                self.stdout.write(
                    f'  {tag} {payload["component"]:18s} '
                    f'final={payload["final_fitness"]:+.4f} '
                    f'({payload["elapsed_seconds"]:.1f}s)')
            elif kind == 'tournament_end':
                self.stdout.write(self.style.SUCCESS(
                    f'\nDONE — {payload["cycles_completed"]} cycle(s), '
                    f'{payload["improvements"]} improvement(s), '
                    f'{payload["total_seconds"]:.1f}s'))

        result = run_autotournament(cfg, on_event=_on_event)
        # Per-component summary.
        from caformer.models import ComponentChampion
        self.stdout.write('\nCurrent leaderboard:')
        for slug in ['embedding', 'layer_norm', 'self_attention', 'projection',
                     'mlp', 'transformer', 'softmax', 'output']:
            best = ComponentChampion.best_for(slug)
            if best:
                self.stdout.write(
                    f'  {slug:18s} fit={best.fitness:+.4f} '
                    f'(g{best.generation}, {best.created_at:%Y-%m-%d %H:%M})')
            else:
                self.stdout.write(f'  {slug:18s} (no champion yet)')
