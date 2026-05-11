"""manage.py umbra_run <slug> — execute an Umbra experiment from the
shell.  Same code path as the web Run button (umbra.runner)."""
from django.core.management.base import BaseCommand, CommandError

from umbra.models import Experiment
from umbra.runner import run_experiment


class Command(BaseCommand):
    help = 'Run an Umbra experiment by slug; prints status + output.'

    def add_arguments(self, parser):
        parser.add_argument('slug', help='Experiment slug to execute.')
        parser.add_argument('--quiet', action='store_true',
                            help='Only emit the final status line.')

    def handle(self, *args, **opts):
        slug = opts['slug']
        try:
            e = Experiment.objects.get(slug=slug)
        except Experiment.DoesNotExist:
            raise CommandError(f'no experiment with slug={slug!r}')

        run_experiment(e)

        if not opts['quiet']:
            if e.last_output:
                self.stdout.write('--- stdout ---')
                self.stdout.write(e.last_output.rstrip())
            if e.last_error:
                self.stderr.write('--- stderr ---')
                self.stderr.write(e.last_error.rstrip())
        line = f'{e.slug}: {e.status} ({e.last_run_ms} ms)'
        if e.status == Experiment.STATUS_DONE:
            self.stdout.write(self.style.SUCCESS(line))
        else:
            self.stdout.write(self.style.ERROR(line))
