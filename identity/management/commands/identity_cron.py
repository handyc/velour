"""Identity cron dispatcher — the single crontab entry point.

Usage in crontab (pick a 10-minute cadence that suits you):

    */10 * * * * /var/www/webapps/<user>/apps/velour/venv/bin/python \\
                 /var/www/webapps/<user>/apps/velour/manage.py identity_cron

On each invocation, the dispatcher figures out what to run based
on the current wall clock — ticks always, reflections at period
boundaries, meditation ladders once a week on Sunday. See
identity/cron.py for the clock-based decision rules.

Flags:

    --force KIND
        Run a specific pipeline regardless of the clock.
        Accepted: tick, reflect_hourly, reflect_daily, reflect_weekly,
        reflect_monthly, meditate_ladder. Pass multiple times to
        run several in order. Pass --force all to run every
        pipeline regardless of schedule.

    --quiet
        Suppress per-pipeline stdout output. Only the summary line
        is printed. Useful when running from cron to avoid noisy
        email from the cron daemon.
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
