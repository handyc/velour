"""Take one SystemSample row and prune old rows.

Designed for cron / supervisor — schedule it every 30 s for unattended
sampling, e.g. via a supervisor entry like::

    [program:velour-sysampler]
    command=/path/to/venv/bin/python /path/to/manage.py sample_system
    autorestart=true
    stopasgroup=true

The graphs/sample/ endpoint also persists samples opportunistically,
so this command is only needed if you want the ring buffer to fill
even when nobody is looking at the dashboard.
"""

from django.core.management.base import BaseCommand

from graphs.views import take_persistent_sample


class Command(BaseCommand):
    help = 'Take one SystemSample row (cpu/mem/swap/load/entropy) and prune.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force', action='store_true',
            help='Take a sample even if the throttle window has not elapsed.'
        )

    def handle(self, *args, **opts):
        row = take_persistent_sample(force=opts['force'])
        if row is None:
            self.stdout.write(self.style.NOTICE('throttled — last sample is too recent'))
            return
        self.stdout.write(self.style.SUCCESS(
            f'sampled · cpu={row.cpu_pct:.1f}%  mem={row.mem_used_pct:.1f}%  '
            f'load={row.load1:.2f}/{row.load5:.2f}/{row.load15:.2f}  '
            f'entropy={row.entropy}'
        ))
