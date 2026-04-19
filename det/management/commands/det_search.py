"""Run a Det search from the command line — same logic as the web
flow, but comfortable for large sweeps that would time out a
request. Usage:

  venv/bin/python manage.py det_search \\
      --n-colors 4 --candidates 800 --rules 100 \\
      --wildcards 25 --width 24 --height 24 --horizon 60

Prints progress and the top 10 candidates at the end.
"""

from django.core.management.base import BaseCommand

from det.models import SearchRun
from det.search import execute


class Command(BaseCommand):
    help = ('Generate random hex CA rulesets and score each for '
            'Class-4 (Rule 110-like) behavior.')

    def add_arguments(self, parser):
        parser.add_argument('--label', default='',
            help='Optional human label for the SearchRun row.')
        parser.add_argument('--n-colors', type=int, default=4,
            help='Number of cell colors, 2-4 (default: 4).')
        parser.add_argument('--candidates', type=int, default=200,
            help='How many random rulesets to generate (default: 200).')
        parser.add_argument('--rules', type=int, default=80,
            help='Rules per candidate (default: 80).')
        parser.add_argument('--wildcards', type=int, default=25,
            help='Wildcard percentage on neighbor positions (0-80).')
        parser.add_argument('--width', type=int, default=20)
        parser.add_argument('--height', type=int, default=20)
        parser.add_argument('--horizon', type=int, default=40,
            help='Screening horizon in ticks (default: 40).')
        parser.add_argument('--seed', default='',
            help='RNG seed string (default: timestamp).')

    def handle(self, *args, **opts):
        run = SearchRun.objects.create(
            label=opts['label'],
            n_colors=opts['n_colors'],
            n_candidates=opts['candidates'],
            n_rules_per_candidate=opts['rules'],
            wildcard_pct=opts['wildcards'],
            screen_width=opts['width'],
            screen_height=opts['height'],
            horizon=opts['horizon'],
            seed=opts['seed'],
        )
        self.stdout.write(self.style.NOTICE(
            f'SearchRun #{run.pk} started ({run.n_candidates} candidates, '
            f'{run.n_colors} colors)…'))

        def progress(done, total):
            self.stdout.write(f'  {done}/{total}')

        execute(run, progress_cb=progress)

        top = (run.candidates.order_by('-score', 'id')[:10])
        self.stdout.write(self.style.SUCCESS(
            f'Done. status={run.status}, '
            f'duration={run.duration_seconds:.1f}s'))
        self.stdout.write('')
        self.stdout.write('Top 10 candidates:')
        for c in top:
            self.stdout.write(
                f'  #{c.pk:>6}  score={c.score:5.2f}  '
                f'{c.est_class:7}  '
                f'act={c.analysis.get("activity_tail", 0):.3f}  '
                f'ent={c.analysis.get("block_entropy", 0):.2f}  '
                f'period={c.analysis.get("period")}'
            )
