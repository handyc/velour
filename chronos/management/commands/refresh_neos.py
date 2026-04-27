"""Refresh near-Earth-object close approaches from JPL CNEOS and emit
them as CalendarEvents under the "Near-Earth Objects" Tradition.

NEOs differ from satellites: we don't track every one continuously,
because there are millions and most are dim and far. JPL has already
done the orbit-propagation work and publishes the upcoming close
approaches as a clean catalog. We just consume that catalog and
mirror it into the chronos calendar so close approaches show up next
to eclipses, conjunctions, and (now) satellite passes.

Idempotent re-run: deletes future-dated NEO events under the
tradition before re-emitting, so each run replaces the forecast.

Usage:

    python manage.py refresh_neos
        Default: next 60 days, threshold 10 LD.

    python manage.py refresh_neos --days 90 --max-ld 20
        Wider net (90 days, 20 lunar distances).

    python manage.py refresh_neos --au 0.05
        Threshold by AU instead of LD (0.05 AU ≈ 19.5 LD —
        the IAU "potentially hazardous" distance cutoff).

    python manage.py refresh_neos --sentry
        Only objects on JPL's Sentry impact-monitoring list.
"""

import datetime as dt

from django.core.management.base import BaseCommand
from django.utils import timezone as djtz

from chronos.astro_sources.neos import (
    LD_AU, fetch_close_approaches,
)
from chronos.models import CalendarEvent, Tradition


NEOS_TRADITION = {
    'slug':        'neos',
    'name':        'Near-Earth Objects',
    'color':       '#F59E0B',  # amber — distinct from satellites violet
    'description': 'Close approaches of near-Earth asteroids and comets, '
                   'mirrored from JPL CNEOS. Dates and distances are '
                   'predictions; small bodies have meaningful position '
                   'uncertainty until their orbits are well-determined.',
}


def _format_event(row):
    """Compose title + notes for a CalendarEvent from a CNEOS row."""
    des = row['designation']
    ld = row['dist_ld']
    h = row['h']
    d_est = row['diameter_km_est']
    if d_est is None:
        size = '?'
    elif d_est < 0.05:
        size = f'~{d_est * 1000:.0f} m'
    elif d_est < 1.0:
        size = f'~{d_est * 1000:.0f} m'
    else:
        size = f'~{d_est:.2f} km'

    title = f'{des} · {ld:.1f} LD ({size})'
    notes_lines = [
        f'Near-Earth object close approach from JPL CNEOS.',
        f'Designation: {des}',
        f'Distance (nominal): {row["dist_au"]:.6f} AU = '
        f'{ld:.2f} lunar distances',
    ]
    if row.get('dist_min_ld') and row.get('dist_max_ld'):
        notes_lines.append(
            f'1-sigma range: {row["dist_min_ld"]:.2f} – '
            f'{row["dist_max_ld"]:.2f} LD'
        )
    if row.get('v_rel_km_s'):
        notes_lines.append(
            f'Relative velocity: {row["v_rel_km_s"]:.2f} km/s'
        )
    if h is not None:
        notes_lines.append(
            f'Absolute magnitude H = {h:.1f}  (estimated diameter {size})'
        )
    if row.get('time_uncertainty'):
        notes_lines.append(
            f'Time uncertainty (1σ): {row["time_uncertainty"]}'
        )
    return title, '\n'.join(notes_lines)


class Command(BaseCommand):
    help = 'Mirror upcoming NEO close approaches from JPL CNEOS.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=60,
                            help='Look-ahead window in days (default 60).')
        parser.add_argument('--max-ld', type=float, default=10.0,
                            help='Max approach distance in lunar distances '
                                 '(default 10).')
        parser.add_argument('--au', type=float, default=None,
                            help='Override --max-ld with an AU threshold.')
        parser.add_argument('--sentry', action='store_true',
                            help='Only Sentry impact-monitor list objects.')

    def handle(self, *args, **opts):
        tradition, _ = Tradition.objects.update_or_create(
            slug=NEOS_TRADITION['slug'],
            defaults={
                'name':        NEOS_TRADITION['name'],
                'color':       NEOS_TRADITION['color'],
                'description': NEOS_TRADITION['description'],
            },
        )

        if opts['au'] is not None:
            dist_max = f'{opts["au"]:g}'
            threshold_label = f'{opts["au"]} AU ({opts["au"]/LD_AU:.1f} LD)'
        else:
            dist_max = f'{opts["max_ld"]:g}LD'
            threshold_label = f'{opts["max_ld"]} LD'

        try:
            rows = fetch_close_approaches(
                date_min='now',
                date_max=f'+{opts["days"]}',
                dist_max=dist_max,
                include_sentry=opts['sentry'],
            )
        except Exception as exc:
            self.stdout.write(self.style.ERROR(
                f'JPL CNEOS fetch failed: {exc}'
            ))
            return

        # Wipe future NEO events before re-emitting (idempotent run).
        deleted = CalendarEvent.objects.filter(
            source='feed',
            tradition=tradition,
            start__gte=djtz.now(),
        ).delete()[0]

        n_created = 0
        for row in rows:
            when = row['when_utc']
            title, notes = _format_event(row)
            CalendarEvent.objects.create(
                source='feed',
                tradition=tradition,
                title=title,
                start=when,
                end=when + dt.timedelta(minutes=30),
                all_day=False,
                color=tradition.color,
                tags=f'neo,des:{row["designation"]}',
                notes=notes,
            )
            n_created += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done. Threshold {threshold_label} · {opts["days"]} days · '
            f'{deleted} stale events removed · '
            f'{n_created} close approaches emitted.'
        ))
