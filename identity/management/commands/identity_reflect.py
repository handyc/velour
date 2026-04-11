"""Compose an Identity reflection over a period of ticks.

Usage:
    python manage.py identity_reflect
        Weekly reflection for the most recently completed week.
    python manage.py identity_reflect --period daily
        Daily reflection for yesterday.
    python manage.py identity_reflect --period monthly
        Monthly reflection for the most recently completed month.
    python manage.py identity_reflect --no-codex
        Don't push the reflection into the Codex manual (Reflection
        row still written to the DB).

Intended to run from cron:

    0 0 * * *  python manage.py identity_reflect --period daily
    0 0 * * 1  python manage.py identity_reflect --period weekly
    0 0 1 * *  python manage.py identity_reflect --period monthly
"""

from django.core.management.base import BaseCommand

from identity.reflection import reflect


class Command(BaseCommand):
    help = 'Compose an Identity reflection from recent tick data.'

    def add_arguments(self, parser):
        parser.add_argument('--period', default='weekly',
                            choices=['hourly', 'daily', 'weekly',
                                     'monthly', 'yearly'],
                            help='Period to reflect on (default weekly).')
        parser.add_argument('--no-codex', action='store_true',
                            help='Skip pushing the reflection into the '
                                 "Identity's Journal Codex manual.")

    def handle(self, *args, **opts):
        row = reflect(period=opts['period'], push_to_codex=not opts['no_codex'])
        self.stdout.write(self.style.SUCCESS(
            f'Reflection: {row.title}'
        ))
        self.stdout.write(f'  ticks: {row.ticks_referenced}')
        self.stdout.write(f'  body: {len(row.body)} chars')
        self.stdout.write('')
        self.stdout.write(row.body)
