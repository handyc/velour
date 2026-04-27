"""Refresh TLE elements for watched satellites and emit upcoming
visible passes as CalendarEvents.

On first run (--seed) creates the SEED_SATELLITES rows (ISS, Hubble,
Tiangong) so the table isn't empty.

Usage:

    python manage.py refresh_satellites
        Refresh TLE for every watched satellite, recompute the
        next 14 days of visible passes from the configured home
        location.

    python manage.py refresh_satellites --seed
        Also create the seeded satellites if they don't exist yet.

    python manage.py refresh_satellites --days 21
        Look further ahead.

    python manage.py refresh_satellites --no-fetch
        Use cached TLE — useful when offline.

The "Satellites" Tradition gets created idempotently so emitted
passes can be coloured + toggled like any other source.
"""

import datetime as dt

from django.core.management.base import BaseCommand
from django.utils import timezone as djtz

from chronos.astro_sources.satellites import (
    SEED_SATELLITES, compute_passes, fetch_tle,
)
from chronos.models import CalendarEvent, ClockPrefs, TrackedObject, Tradition


SATELLITES_TRADITION = {
    'slug':        'satellites',
    'name':        'Satellites',
    'color':       '#8B5CF6',  # violet — distinct from astronomy blue
    'description': 'Visible passes of artificial satellites '
                   '(ISS, Hubble, Tiangong, etc.) from the configured '
                   'home location. Refreshed via `refresh_satellites`.',
}


class Command(BaseCommand):
    help = 'Refresh satellite TLEs and seed visible-pass calendar events.'

    def add_arguments(self, parser):
        parser.add_argument('--seed', action='store_true',
                            help='Create SEED_SATELLITES rows if missing.')
        parser.add_argument('--days', type=int, default=14,
                            help='Look-ahead window for passes (default 14).')
        parser.add_argument('--no-fetch', action='store_true',
                            help='Skip TLE refresh; use cached elements.')
        parser.add_argument('--only', default='',
                            help='Comma-separated slugs to refresh '
                                 '(default: every watched satellite).')

    def handle(self, *args, **opts):
        prefs = ClockPrefs.load()
        tradition, _ = Tradition.objects.update_or_create(
            slug=SATELLITES_TRADITION['slug'],
            defaults={
                'name':        SATELLITES_TRADITION['name'],
                'color':       SATELLITES_TRADITION['color'],
                'description': SATELLITES_TRADITION['description'],
            },
        )

        if opts['seed']:
            self._seed()

        only = {s.strip() for s in opts['only'].split(',') if s.strip()}
        qs = TrackedObject.objects.filter(
            kind=TrackedObject.KIND_SATELLITE, is_watched=True,
        )
        if only:
            qs = qs.filter(slug__in=only)

        if not qs.exists():
            self.stdout.write(self.style.WARNING(
                'No watched satellites. Run with --seed to add ISS/Hubble/Tiangong.'
            ))
            return

        total_passes = 0
        for sat in qs:
            total_passes += self._refresh_one(
                sat, tradition, prefs,
                fetch=not opts['no_fetch'],
                days=opts['days'],
            )

        self.stdout.write(self.style.SUCCESS(
            f'Done. {qs.count()} satellites refreshed, '
            f'{total_passes} visible passes seeded for next {opts["days"]} days.'
        ))

    def _seed(self):
        for spec in SEED_SATELLITES:
            obj, created = TrackedObject.objects.get_or_create(
                slug=spec['slug'],
                defaults={
                    'kind':        TrackedObject.KIND_SATELLITE,
                    'name':        spec['name'],
                    'designation': spec['designation'],
                    'magnitude':   spec.get('magnitude'),
                    'notes':       spec.get('notes', ''),
                    'source_url':  f'https://celestrak.org/NORAD/elements/'
                                   f'gp.php?CATNR={spec["designation"]}'
                                   f'&FORMAT=tle',
                    'is_watched':  True,
                },
            )
            if created:
                self.stdout.write(f'  + seeded {obj.name}')

    def _refresh_one(self, sat, tradition, prefs, fetch, days):
        if fetch:
            try:
                tle = fetch_tle(sat.designation)
                sat.elements_json = {
                    'name':  tle['name'],
                    'line1': tle['line1'],
                    'line2': tle['line2'],
                }
                sat.elements_fetched_at = djtz.now()
                sat.save(update_fields=['elements_json',
                                        'elements_fetched_at'])
                self.stdout.write(f'  · {sat.name}: TLE refreshed')
            except Exception as exc:
                self.stdout.write(self.style.WARNING(
                    f'  ! {sat.name}: TLE fetch failed ({exc}); '
                    'falling back to cached.'
                ))

        tle = sat.elements_json
        if not (tle and tle.get('line1') and tle.get('line2')):
            self.stdout.write(self.style.WARNING(
                f'  ! {sat.name}: no TLE on record; skipped.'
            ))
            return 0

        passes = compute_passes(
            tle, prefs.home_lat, prefs.home_lon, prefs.home_elev_m,
            days=days, visible_only=True,
        )

        # Wipe future-dated calendar events for this satellite before
        # re-emitting — simpler than diffing, and they're cheap.
        slug_tag = f'sat:{sat.slug}'
        CalendarEvent.objects.filter(
            source='feed', tradition=tradition,
            tags__contains=slug_tag,
            start__gte=djtz.now(),
        ).delete()

        n = 0
        for p in passes:
            title = (
                f'{sat.name} pass · max {int(round(p["max_alt_deg"]))}°'
            )
            CalendarEvent.objects.create(
                source='feed',
                tradition=tradition,
                title=title,
                start=p['rise'],
                end=p['set'],
                all_day=False,
                color=tradition.color,
                tags=f'satellite,{slug_tag}',
                notes=(
                    f'Rise: {p["rise"]:%H:%M:%S} UT · '
                    f'Culminate: {p["culminate"]:%H:%M:%S} UT '
                    f'(alt {p["max_alt_deg"]:.1f}°, '
                    f'az {p["culminate_az_deg"]:.0f}°) · '
                    f'Set: {p["set"]:%H:%M:%S} UT · '
                    f'Duration {int(p["duration_s"])} s'
                ),
            )
            n += 1
        self.stdout.write(f'    → {n} visible passes')
        return n
