"""Populate Tradition rows + holiday CalendarEvent rows.

Walks the registered holiday source adapters and creates one
CalendarEvent per (tradition, date, name) tuple. Idempotent —
re-running with the same year range updates rather than
duplicates.

Usage:

    python manage.py seed_holidays
        Seeds Traditions table (idempotent), then holidays for
        the current year.

    python manage.py seed_holidays --year-from 2026 --year-to 2030
        Seeds holidays for 2026 through 2030 inclusive.

    python manage.py seed_holidays --traditions civic,christianity,islam
        Limit to specific traditions (slug list, comma-separated).

    python manage.py seed_holidays --reset
        Delete all existing holiday-source events before re-seeding.
"""

import datetime as dt
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand

from chronos.holiday_sources import TRADITIONS
from chronos.models import CalendarEvent, ClockPrefs, Tradition


class Command(BaseCommand):
    help = 'Seed Traditions and holiday CalendarEvent rows from source adapters.'

    def add_arguments(self, parser):
        parser.add_argument('--year-from', type=int, default=None)
        parser.add_argument('--year-to', type=int, default=None)
        parser.add_argument('--traditions', default='',
                            help='Comma-separated tradition slugs to seed (default: all).')
        parser.add_argument('--reset', action='store_true',
                            help='Delete existing holiday events before seeding.')

    def handle(self, *args, **opts):
        prefs = ClockPrefs.load()
        tz = ZoneInfo(prefs.home_tz)
        country = prefs.country or 'NL'

        # Idempotent tradition upsert.
        tradition_objs = {}
        for spec in TRADITIONS:
            obj, _ = Tradition.objects.update_or_create(
                slug=spec['slug'],
                defaults={
                    'name':        spec['name'],
                    'color':       spec['color'],
                    'description': spec.get('description', ''),
                },
            )
            tradition_objs[spec['slug']] = (obj, spec['module'])

        # Year range.
        today = dt.date.today()
        y_from = opts['year_from'] or today.year
        y_to = opts['year_to'] or y_from
        if y_to < y_from:
            y_from, y_to = y_to, y_from
        years = list(range(y_from, y_to + 1))

        # Tradition filter.
        wanted = set()
        if opts['traditions']:
            wanted = {s.strip() for s in opts['traditions'].split(',') if s.strip()}

        if opts['reset']:
            n = CalendarEvent.objects.filter(source='holiday').delete()[0]
            self.stdout.write(self.style.WARNING(f'Deleted {n} existing holiday events.'))

        total_created = 0
        total_updated = 0
        for slug, (tradition, module) in tradition_objs.items():
            if wanted and slug not in wanted:
                continue
            self.stdout.write(f'-- {tradition.name} ({slug})')

            for year in years:
                try:
                    if slug == 'civic':
                        items = module.get(year, country=country)
                    else:
                        items = module.get(year)
                except Exception as e:
                    self.stderr.write(self.style.WARNING(
                        f'   ! {year}: adapter raised {type(e).__name__}: {e}'
                    ))
                    continue

                for d, name in items:
                    start_dt = dt.datetime.combine(d, dt.time(0, 0), tzinfo=tz)
                    end_dt = dt.datetime.combine(d, dt.time(23, 59), tzinfo=tz)
                    # Dedup key must use concrete field values, NOT lookup
                    # transforms like start__date — under USE_TZ=True the
                    # __date transform compares in UTC, so an Amsterdam
                    # midnight stored as Apr 26 22:00 UTC never matches
                    # lookup date=Apr 27, and every re-run creates a dup.
                    obj, created = CalendarEvent.objects.update_or_create(
                        source='holiday',
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

                self.stdout.write(f'   {year}: {len(items)} entries')

        self.stdout.write(self.style.SUCCESS(
            f'Done. Created {total_created}, updated {total_updated}, '
            f'across years {y_from}-{y_to}.'
        ))
