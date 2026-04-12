"""Identity cron dispatcher — the single crontab entry point.

Wire ONE crontab entry, firing every minute so the tile-generation
frequency slider can run at its highest setting without needing a
second crontab line:

    * * * * * /var/www/webapps/<user>/apps/velour/venv/bin/python \\
              /var/www/webapps/<user>/apps/velour/manage.py identity_cron

On each invocation, the dispatcher checks the last successful run
of each pipeline kind and only fires those whose interval has
elapsed. Interval per kind (in seconds):

  - tick             — 600   (10 min)
  - reflect_hourly   — 3600  (1 h)
  - reflect_daily    — 86400 (1 d)
  - reflect_weekly   — 604800 (1 w)
  - reflect_monthly  — 2592000 (30 d)
  - meditate_ladder  — 604800 (1 w)
  - rebuild_document — 604800 (1 w)
  - tile_reflect     — operator-configurable via the slider on
                       the Identity home page, from 0 (never) to
                       1 second (in principle; in practice capped
                       by OS cron cadence which is 1 minute).

Flags:

    --force KIND
        Run a specific pipeline regardless of the interval gate.
        Repeat for multiple. --force all fires every pipeline.

    --quiet
        Suppress per-pipeline stdout output; only the summary
        line is printed. Useful when running from cron to keep
        cron email noise down.
"""

from django.core.management.base import BaseCommand

from identity.cron import dispatch


class Command(BaseCommand):
    help = 'Identity cron dispatcher — runs ticks + periodic rollups.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='append', default=[],
                            help='Pipeline kind(s) to run regardless of '
                                 'the clock. Repeat for multiple.')
        parser.add_argument('--quiet', action='store_true',
                            help='Only print the final summary line.')

    def handle(self, *args, **opts):
        results = dispatch(force=opts['force'])
        if not opts['quiet']:
            for kind, (status, summary) in results.items():
                if status == 'ok':
                    self.stdout.write(self.style.SUCCESS(
                        f'  [{kind:18s}] {summary}'))
                else:
                    self.stdout.write(self.style.ERROR(
                        f'  [{kind:18s}] {summary}'))
        ok_count = sum(1 for s, _ in results.values() if s == 'ok')
        total = len(results)
        msg = f'dispatched {ok_count}/{total} pipelines'
        if ok_count == total:
            self.stdout.write(self.style.SUCCESS(msg))
        else:
            self.stdout.write(self.style.WARNING(msg))
