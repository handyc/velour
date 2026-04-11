"""Run one Identity tick — the cron entrypoint for turn-based attention.

A tick is one unit of attention: gather sensors, walk rules, derive a
mood + intensity, compose a one-line thought, write a Mood row, update
Identity. Designed to be cheap so cron can fire it on a tight cadence
without spinning up a fan.

Usage:

    python manage.py identity_tick
        One tick, triggered_by='cron'.

    python manage.py identity_tick --triggered-by manual
        Override the trigger label so the Mood row records who fired it.

Add to crontab for periodic ticks:

    */10 * * * * /var/www/webapps/<user>/apps/velour/venv/bin/python \\
                 /var/www/webapps/<user>/apps/velour/manage.py identity_tick
"""

from django.core.management.base import BaseCommand

from identity.ticking import tick


class Command(BaseCommand):
    help = 'Run one Identity attention tick.'

    def add_arguments(self, parser):
        parser.add_argument('--triggered-by', default='cron',
                            help='Label for the Mood.trigger field.')

    def handle(self, *args, **opts):
        row, thought = tick(triggered_by=opts['triggered_by'])
        self.stdout.write(self.style.SUCCESS(
            f'mood={row.mood} intensity={row.intensity:.2f}'
        ))
        self.stdout.write(f'thought: {thought}')
