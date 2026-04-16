"""Populate astronomical CalendarEvent rows from skyfield + meteor table.

Creates an "Astronomy" Tradition (idempotent) and seeds CalendarEvents
with source='astro' for equinoxes/solstices, full moons, new moons,
solar/lunar eclipses, and major meteor shower peaks.

The skyfield ephemeris is auto-downloaded on first use to
chronos/data/de421.bsp (~17MB). It's gitignored.

Usage:

    python manage.py seed_astronomy
        Seeds astronomy for the current year.

    python manage.py seed_astronomy --year-from 2026 --year-to 2030
        Seeds astronomy for a year range.

    python manage.py seed_astronomy --reset
        Delete existing astro events before re-seeding.
"""

import datetime as dt
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand

from chronos.astro_sources import get_all
from chronos.models import CalendarEvent, ClockPrefs, Tradition


ASTRONOMY_TRADITION = {
    'slug':        'astronomy',
    'name':        'Astronomy',
    'color':       '#1F3C6E',  # deep night-sky blue
    'description': 'Astronomical events: equinoxes, solstices, moon '
                   'phases, eclipses, and meteor shower peaks. '
                   'Computed via skyfield and the JPL DE421 ephemeris.',
}


class Command(BaseCommand):
    help = 'Seed astronomical events into the calendar.'

    def add_arguments(self, parser):
        parser.add_argument('--year-from', type=int, default=None)
        parser.add_argument('--year-to', type=int, default=None)
        parser.add_argument('--reset', action='store_true',
                            help='Delete existing astro events first.')

    def handle(self, *args, **opts):
        prefs = ClockPrefs.load()
        tz = ZoneInfo(prefs.home_tz)

        tradition, _ = Tradition.objects.update_or_create(
            slug=ASTRONOMY_TRADITION['slug'],
            defaults={
                'name':        ASTRONOMY_TRADITION['name'],
                'color':       ASTRONOMY_TRADITION['color'],
                'description': ASTRONOMY_TRADITION['description'],
            },
        )

        today = dt.date.today()
        y_from = opts['year_from'] or today.year
        y_to = opts['year_to'] or y_from
        if y_to < y_from:
            y_from, y_to = y_to, y_from

        if opts['reset']:
            n = CalendarEvent.objects.filter(source='astro').delete()[0]
            self.stdout.write(self.style.WARNING(
                f'Deleted {n} existing astro events.'
            ))

        total_created = 0
        total_updated = 0
        for year in range(y_from, y_to + 1):
            events = get_all(year)
            for d, name in events:
                start_dt = dt.datetime.combine(d, dt.time(0, 0), tzinfo=tz)
                end_dt = dt.datetime.combine(d, dt.time(23, 59), tzinfo=tz)
                # See seed_holidays.py for the reason start=start_dt
                # (not start__date=d): __date compares in UTC.
                obj, created = CalendarEvent.objects.update_or_create(
                    source='astro',
                    tradition=tradition,
                    title=name,
                    start=start_dt,
                    defaults={
                        'end':     end_dt,
                        'all_day': True,
                        'color':   tradition.color,
                    },
                )
                if created:
                    total_created += 1
                else:
                    total_updated += 1
            self.stdout.write(f'   {year}: {len(events)} events')

        self.stdout.write(self.style.SUCCESS(
            f'Done. Created {total_created}, updated {total_updated}, '
            f'across years {y_from}-{y_to}.'
        ))
