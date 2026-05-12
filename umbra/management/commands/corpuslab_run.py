"""Run a CorpusLabSession's queued ops with no in-request cap.

The web UI caps each op at corpuslab.MAX_CELLS cells so a single
Django request finishes inside the runner wall.  Large linguistic
corpora belong here instead: the command processes the whole CSV in
chunks of MAX_CELLS, amortising the Concrete circuit compile across
every chunk.

Designed to be Slurm-friendly: prints structured progress lines to
stdout so a tail-driven dashboard or a slurm log can show liveness,
and writes results back to the same CorpusLabSession in the database.

Typical Leiden ALICE invocation:

    venv/bin/python manage.py corpuslab_run <slug>

…inside a Slurm job that asked for the default 20 cores × 4 h.
Concrete is multithreaded via HPX so a single op benefits from cores
directly; 288-CPU array-jobs land in a follow-up (see
project_velour_leiden_humanities_purpose memory for cluster shape).
"""
import time

from django.core.management.base import BaseCommand, CommandError

from umbra import corpuslab
from umbra.models import CorpusLabSession


class Command(BaseCommand):
    help = ('Run a CorpusLabSession\'s queued ops uncapped — for ALICE '
            'or any out-of-request batch run.')

    def add_arguments(self, parser):
        parser.add_argument('slug', help='session slug to run')
        parser.add_argument('--cap', type=int, default=None,
            help='per-op cell cap (default: uncapped).  Set to a small '
                 'value to compare timing against the web UI.')
        parser.add_argument('--dry-run', action='store_true',
            help='parse + report sizing but don\'t actually run.')

    def handle(self, *args, **opts):
        try:
            s = CorpusLabSession.objects.get(slug=opts['slug'])
        except CorpusLabSession.DoesNotExist:
            raise CommandError(f'no session with slug {opts["slug"]!r}')

        grid, rows, cols = corpuslab.parse_csv(s.original_csv or '')
        n_nonempty = corpuslab.count_nonempty(grid)
        profile    = corpuslab.get_profile(s.language_profile)

        self.stdout.write(f'session   : {s.slug}  ({s.name})')
        self.stdout.write(f'profile   : {profile.slug}  ({profile.name})')
        self.stdout.write(f'grid      : {rows} rows × {cols} cols, '
                          f'{n_nonempty} non-empty cells')
        self.stdout.write(f'cap       : {opts["cap"] or "uncapped"} cells / op')
        self.stdout.write(f'chunk size: {corpuslab.MAX_CELLS} cells '
                          f'× {corpuslab.MAX_CELL_LEN} chars')

        if opts['dry_run']:
            self.stdout.write(self.style.WARNING('dry run, exiting'))
            return

        def progress(op_idx, kind, chunk_done, chunk_total, chunk_cells):
            self.stdout.write(
                f'  op#{op_idx} {kind}: chunk {chunk_done}/{chunk_total} '
                f'({chunk_cells} cells)',
                ending='\n',
            )
            self.stdout.flush()

        t0 = time.monotonic()
        corpuslab.run_session(s, cap=opts['cap'], progress_cb=progress)
        s.save()
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if s.last_error:
            self.stdout.write(self.style.ERROR(
                f'errors:\n{s.last_error}'))
        self.stdout.write(self.style.SUCCESS(
            f'done in {elapsed_ms} ms · compile {s.compile_ms} ms · '
            f'ops {s.ops_ms} ms · {s.cells} cells'))
