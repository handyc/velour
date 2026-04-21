"""Build and run a Det Tournament from the command line.

Typical use:

    # Pull the top candidate from each of four SearchRuns into a
    # 5-seed tournament and run it end-to-end.
    manage.py det_tournament --label "3c-shootout" \\
        --n-colors 3 --seeds 5 --top-of-each 36 37 38 39

    # Print the leaderboard for an existing tournament.
    manage.py det_tournament --show 1
"""

import time

from django.core.management.base import BaseCommand, CommandError

from det.models import Candidate, SearchRun, Tournament
from det.tournament import add_candidate, autofill_random, execute


class Command(BaseCommand):
    help = 'Build and run a Det Tournament, or inspect an existing one.'

    def add_arguments(self, parser):
        parser.add_argument('--label', default='')
        parser.add_argument('--n-colors', type=int, default=3)
        parser.add_argument('--seeds', type=int, default=5,
            help='How many shared initial grids each entry faces.')
        parser.add_argument('--width', type=int, default=18)
        parser.add_argument('--height', type=int, default=16)
        parser.add_argument('--horizon', type=int, default=60)
        parser.add_argument('--top-of-each', nargs='*', type=int, default=[],
            metavar='RUN_ID',
            help='For each SearchRun ID, add its top-scoring candidate.')
        parser.add_argument('--top-n-from', nargs=2, type=int, default=None,
            metavar=('RUN_ID', 'N'),
            help='Add the top N candidates from one SearchRun.')
        parser.add_argument('--candidates', nargs='*', type=int, default=[],
            metavar='CAND_ID',
            help='Explicit candidate IDs to add.')
        parser.add_argument('--random', type=int, default=0, metavar='N',
            help='Autofill N random compatible candidates from the pool '
                 '(matching n_colors, score ≥ --min-score).')
        parser.add_argument('--min-score', type=float, default=2.0,
            help='Native-score floor for --random (default 2.0). '
                 'Bump to 3.5 to restrict to the class-4 band.')
        parser.add_argument('--rng-seed', default=None,
            help='Seed for reproducible random selection.')
        parser.add_argument('--auto-promote', type=int, default=0,
            metavar='N',
            help='After running, auto-promote up to N top class-4 '
                 'winners (aggregate ≥ 3.5) to Automaton + Evolution. '
                 '0 = off (default).')
        parser.add_argument('--no-run', action='store_true',
            help='Create and populate without scoring — useful for '
                 'staging a tournament then kicking it off from the UI.')
        parser.add_argument('--show', type=int,
            help='Print the leaderboard for Tournament ID and exit.')

    def handle(self, **opts):
        if opts['show'] is not None:
            self._print_board(opts['show'])
            return

        n_colors = opts['n_colors']
        if not (2 <= n_colors <= 4):
            raise CommandError('n_colors must be 2, 3, or 4.')

        auto_promote = max(0, min(10, int(opts.get('auto_promote') or 0)))
        tourney = Tournament.objects.create(
            label=opts['label'],
            n_colors=n_colors,
            n_seeds=opts['seeds'],
            screen_width=opts['width'],
            screen_height=opts['height'],
            horizon=opts['horizon'],
            auto_promote_top=auto_promote,
        )

        added = 0
        for run_id in opts['top_of_each']:
            run = SearchRun.objects.filter(pk=run_id).first()
            if not run:
                self.stderr.write(f'  - skipped run #{run_id}: not found')
                continue
            top = run.candidates.order_by('-score', 'id').first()
            if top is None:
                self.stderr.write(f'  - skipped run #{run_id}: no candidates')
                continue
            added += self._try_add(tourney, top,
                                   note=f'top of run #{run_id}')

        if opts['top_n_from']:
            rid, n = opts['top_n_from']
            cands = list(Candidate.objects.filter(run_id=rid)
                         .order_by('-score', 'id')[:n])
            if not cands:
                self.stderr.write(f'  - run #{rid} has no candidates')
            for c in cands:
                added += self._try_add(tourney, c,
                                       note=f'top-{n} of run #{rid}')

        for cid in opts['candidates']:
            c = Candidate.objects.filter(pk=cid).first()
            if c is None:
                self.stderr.write(f'  - skipped candidate #{cid}: not found')
                continue
            added += self._try_add(tourney, c)

        if opts['random']:
            n_auto, pool = autofill_random(
                tourney, n=opts['random'],
                min_score=opts['min_score'],
                rng_seed=opts['rng_seed'],
            )
            added += n_auto
            self.stdout.write(
                f'  + {n_auto} random candidate(s) from pool of {pool} '
                f'(n_colors={opts["n_colors"]}, '
                f'min_score={opts["min_score"]})')

        if added == 0:
            tourney.delete()
            raise CommandError(
                'No entries were added — tournament would be empty. '
                'Supply --top-of-each, --top-n-from, or --candidates.')

        self.stdout.write(self.style.SUCCESS(
            f'Tournament #{tourney.pk} created: {added} entries, '
            f'{opts["seeds"]} shared seeds, '
            f'{opts["width"]}x{opts["height"]}, '
            f'horizon={opts["horizon"]}.'))

        if opts['no_run']:
            self.stdout.write('--no-run set; stopping before execute.')
            return

        self.stdout.write('Running…')
        t0 = time.time()
        execute(tourney, progress_cb=self._progress)
        self.stdout.write(self.style.SUCCESS(
            f'Finished in {time.time() - t0:.1f}s.'))
        self._print_board(tourney.pk)

    def _try_add(self, tourney, cand, note=None) -> int:
        try:
            entry = add_candidate(tourney, cand)
        except ValueError as exc:
            self.stderr.write(f'  - skipped cand #{cand.pk}: {exc}')
            return 0
        if note and not entry.note:
            entry.note = note
            entry.save(update_fields=['note'])
        self.stdout.write(
            f'  + cand #{cand.pk} (native score {cand.score:.2f}, '
            f'{cand.get_est_class_display()}) — {note or ""}')
        return 1

    def _progress(self, done, total):
        self.stdout.write(f'  scored {done}/{total}')

    def _print_board(self, pk):
        t = Tournament.objects.filter(pk=pk).first()
        if not t:
            raise CommandError(f'Tournament #{pk} not found.')
        self.stdout.write('')
        self.stdout.write(
            f'Tournament #{t.pk} — {t.label or "(unlabeled)"}')
        self.stdout.write(
            f'  status={t.get_status_display()}, n_colors={t.n_colors}, '
            f'{t.n_seeds} seeds, '
            f'{t.screen_width}x{t.screen_height}, horizon={t.horizon}')
        if t.duration_seconds is not None:
            self.stdout.write(f'  duration={t.duration_seconds:.1f}s')
        entries = list(t.entries.select_related('candidate', 'candidate__run')
                       .order_by('rank', '-aggregate_score', 'id'))
        if not entries:
            self.stdout.write('  (no entries)')
            return
        self.stdout.write('')
        for e in entries:
            tag = 'DQ' if e.disqualified else f'#{e.rank}' if e.rank else ' ?'
            native = e.candidate.score
            delta = e.aggregate_score - native
            self.stdout.write(
                f'  {tag:>4}  cand #{e.candidate_id:<5}  '
                f'agg={e.aggregate_score:6.3f}  '
                f'native={native:6.2f}  '
                f'Δ={delta:+6.2f}  '
                f'(run #{e.candidate.run_id}, '
                f'{e.candidate.get_est_class_display()})')
