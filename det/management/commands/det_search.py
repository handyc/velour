"""Run a Det search from the command line — same logic as the web
flow, but comfortable for large sweeps that would time out a
request. Usage:

  venv/bin/python manage.py det_search \\
      --n-colors 3 --candidates 800 --rules 100 \\
      --wildcards 35 --width 24 --height 24 --horizon 60

Prints progress and the top 10 candidates at the end.

The defaults (3 colors, 35 % wildcards, 100 rules, 18×16, horizon 60)
were picked empirically — they land roughly 5 % of candidates in
class4 on a 200-candidate sweep. Earlier defaults (4c, 25 %, 40 horizon)
almost always produced pure class2 noise.

Cluster dispatch: `--via-conduit TARGET_SLUG` packages this sweep as
a Conduit Job (shell or Slurm, depending on the target kind) and
returns immediately. The remote process writes results.json into
VELOUR_RESULTS_DIR/<job_slug>/; the Det import view reads that file
to reconstruct the SearchRun + Candidates locally.
"""

import json
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from det.models import SearchRun
from det.search import execute


class Command(BaseCommand):
    help = ('Generate random hex CA rulesets and score each for '
            'Class-4 (Rule 110-like) behavior.')

    def add_arguments(self, parser):
        parser.add_argument('--label', default='',
            help='Optional human label for the SearchRun row.')
        parser.add_argument('--n-colors', type=int, default=3,
            help='Number of cell colors, 2-4 (default: 3).')
        parser.add_argument('--candidates', type=int, default=200,
            help='How many random rulesets to generate (default: 200).')
        parser.add_argument('--rules', type=int, default=100,
            help='Rules per candidate (default: 100).')
        parser.add_argument('--wildcards', type=int, default=35,
            help='Wildcard percentage on neighbor positions (default: 35).')
        parser.add_argument('--width', type=int, default=18)
        parser.add_argument('--height', type=int, default=16)
        parser.add_argument('--horizon', type=int, default=60,
            help='Screening horizon in ticks (default: 60).')
        parser.add_argument('--seed', default='',
            help='RNG seed string (default: timestamp).')
        parser.add_argument('--workers', type=int, default=1,
            help='Parallel worker processes for candidate scoring. '
                 '1 = in-process. 0 = auto-detect (os.cpu_count). '
                 'Candidates are independent and CPU-bound so scaling '
                 'is close to linear up to cpu_count.')
        parser.add_argument('--time-limit', type=int, default=None,
            dest='time_limit',
            help='Wall-clock cap in seconds. Once exceeded, no new '
                 'candidates are submitted and the run finalises with '
                 'whatever has been scored. Pair with SBATCH --time '
                 'on Slurm so the finaliser fits in the job\'s budget.')
        parser.add_argument('--export-json', default='',
            dest='export_json',
            help='After the run, write a JSON snapshot of the top '
                 'candidates to this path (used by Conduit dispatch to '
                 'carry results back across the SSH boundary).')
        parser.add_argument('--export-top', type=int, default=500,
            dest='export_top',
            help='How many candidates to include in --export-json '
                 '(sorted by score descending). 0 = all. Default 500 '
                 'keeps the JSON around ~1 MB for typical rulesets.')
        parser.add_argument('--export-class', default='',
            dest='export_class',
            help='If set (e.g. "class4"), only candidates with this '
                 'est_class are included in --export-json.')
        parser.add_argument('--via-conduit', default='',
            dest='via_conduit',
            help='JobTarget slug. Instead of running locally, package '
                 'this sweep as a Conduit Job and return immediately. '
                 'For shell targets the command runs inline; for Slurm '
                 'targets an sbatch script is rendered with an rclone '
                 'tail that ships results back to the Velour host.')

    def handle(self, *args, **opts):
        import os

        if opts['via_conduit']:
            self._dispatch_via_conduit(opts)
            return

        workers = opts['workers']
        if workers == 0:
            workers = max(1, os.cpu_count() or 1)
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
            f'{run.n_colors} colors, workers={workers}'
            + (f', time_limit={opts["time_limit"]}s' if opts['time_limit'] else '')
            + ')…'))

        def progress(done, total):
            self.stdout.write(f'  {done}/{total}')

        execute(run, progress_cb=progress, n_workers=workers,
                time_limit_seconds=opts['time_limit'])

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

        if opts['export_json']:
            self._export_json(run, opts)

    def _export_json(self, run, opts):
        qs = run.candidates.all()
        if opts['export_class']:
            qs = qs.filter(est_class=opts['export_class'])
        qs = qs.order_by('-score', 'id')
        if opts['export_top'] and opts['export_top'] > 0:
            qs = qs[:opts['export_top']]
        payload = {
            'run': {
                'label':                 run.label,
                'n_colors':              run.n_colors,
                'n_candidates':          run.n_candidates,
                'n_rules_per_candidate': run.n_rules_per_candidate,
                'wildcard_pct':          run.wildcard_pct,
                'screen_width':          run.screen_width,
                'screen_height':         run.screen_height,
                'horizon':               run.horizon,
                'seed':                  run.seed,
                'status':                run.status,
                'duration_seconds':      run.duration_seconds,
            },
            'filter': {
                'est_class': opts['export_class'] or None,
                'top':       opts['export_top'],
            },
            'candidates': [
                {
                    'rules_hash': c.rules_hash,
                    'score':      c.score,
                    'est_class':  c.est_class,
                    'n_rules':    c.n_rules,
                    'rules':      c.rules_json,
                    'analysis':   c.analysis,
                }
                for c in qs
            ],
        }
        path = Path(opts['export_json'])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, separators=(',', ':')))
        self.stdout.write(self.style.SUCCESS(
            f'Wrote {len(payload["candidates"])} candidates to {path}'))

    def _dispatch_via_conduit(self, opts):
        """Package as a Conduit Job and block on its status. Local
        shell executors run in a daemon thread that would otherwise
        die when this CLI process exits — polling keeps the foreground
        alive until the job reaches a terminal state."""
        from det.dispatch import DispatchError, dispatch_via_conduit
        try:
            job = dispatch_via_conduit(opts, opts['via_conduit'])
        except DispatchError as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(
            f'dispatched Conduit job {job.slug}'))
        self.stdout.write(
            f'  target: {job.target.name} '
            f'({job.target.get_kind_display()})')
        self.stdout.write(f'  watch : /conduit/jobs/{job.slug}/')
        if job.results_subdir:
            self.stdout.write(
                f'  expect: VELOUR_RESULTS_DIR/{job.results_subdir}/')

        terminal = {'done', 'failed', 'cancelled', 'handoff'}
        last_status = None
        while job.status not in terminal:
            time.sleep(1.0)
            job.refresh_from_db()
            if job.status != last_status:
                self.stdout.write(
                    f'  status: {job.get_status_display()}')
                last_status = job.status

        self.stdout.write(f'  final : {job.get_status_display()}')
        if job.status == 'handoff':
            self.stdout.write(
                '  next  : open /conduit/handoffs/ to submit on '
                'the cluster, then import results from '
                f'/conduit/jobs/{job.slug}/ once done.')
            return
        if job.status == 'done':
            self.stdout.write(
                '  next  : import into Det from '
                f'/conduit/jobs/{job.slug}/.')
        if job.stdout:
            self.stdout.write('── job stdout ──')
            self.stdout.write(job.stdout[-4000:])
        if job.stderr:
            self.stdout.write('── job stderr ──')
            self.stdout.write(job.stderr[-2000:])
