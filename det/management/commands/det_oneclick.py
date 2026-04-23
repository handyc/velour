"""One-click Class-4 hunt: random packed seed → GA → tournament →
promote top winners as Automaton rulesets.

    venv/bin/python manage.py det_oneclick
    venv/bin/python manage.py det_oneclick --generations 30 --population 50

All the heavy lifting lives in det.pipeline.run_oneclick_pipeline.
"""
from django.core.management.base import BaseCommand

from det.pipeline import run_oneclick_pipeline


class Command(BaseCommand):
    help = 'Hunt a Class-4 hex CA ruleset: seed → GA → tournament → promote.'

    def add_arguments(self, parser):
        parser.add_argument('--seed-candidates', type=int, default=15)
        parser.add_argument('--population', type=int, default=25)
        parser.add_argument('--generations', type=int, default=12)
        parser.add_argument('--grid', type=int, default=18,
            help='Grid size for the GA screen (square).')
        parser.add_argument('--horizon', type=int, default=30)
        parser.add_argument('--mutation-rate', type=float, default=0.005)
        parser.add_argument('--tournament-seeds', type=int, default=5)
        parser.add_argument('--winners', type=int, default=3,
            help='Top N to promote to Automaton.RuleSet.')
        parser.add_argument('--rng-seed', type=int, default=None)

    def handle(self, *args, **opts):
        result = run_oneclick_pipeline(
            seed_candidates=opts['seed_candidates'],
            population_size=opts['population'],
            generations=opts['generations'],
            grid_W=opts['grid'], grid_H=opts['grid'],
            horizon=opts['horizon'],
            mutation_rate=opts['mutation_rate'],
            tournament_seeds=opts['tournament_seeds'],
            final_winners=opts['winners'],
            rng_seed=opts['rng_seed'],
            progress_cb=self.stdout.write,
        )
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done. Promoted RuleSet ids: {result.promoted_ruleset_ids}'
        ))
        for s in result.stages:
            self.stdout.write(
                f'  {s.name:12} {s.elapsed_s:5.2f}s  {s.detail}'
            )
