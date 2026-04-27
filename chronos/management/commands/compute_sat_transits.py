"""Predict satellite transits across (or near) the Sun and Moon.

For each watched TrackedObject of kind=satellite, compute the next
N days of transit + appulse events from the configured observer
location. Each event is mirrored into a CalendarEvent under a new
"Sat Transits" Tradition (so they appear on the chronos calendar
alongside conjunctions, eclipses, etc.) and — if it's an actual
on-disk transit — opens an Identity Concern as a flag.

Idempotent: future-dated events under the tradition are wiped per-
sat before re-emitting so each run replaces the forecast.

Usage:

    python manage.py compute_sat_transits
        Default: next 90 days, every watched satellite.

    python manage.py compute_sat_transits --days 180
        Wider look-ahead (slower).

    python manage.py compute_sat_transits --only iss,tiangong
        Limit to specific satellite slugs.

    python manage.py compute_sat_transits --no-concerns
        Don't open Identity Concerns; just emit calendar entries.
"""

import datetime as dt

from django.core.management.base import BaseCommand
from django.utils import timezone as djtz

from chronos.astro_sources.satellites import find_transits
from chronos.models import CalendarEvent, ClockPrefs, TrackedObject, Tradition


TRADITION = {
    'slug':        'sat-transits',
    'name':        'Sat Transits',
    'color':       '#ff7b72',  # warm red — distinct from sat passes (violet)
    'description': 'Times when a tracked satellite passes in front of '
                   '(or very close to) the Sun or Moon as seen from the '
                   'observer location. Computed from skyfield SGP4 + '
                   'JPL DE421 ephemeris; refreshed weekly. On-disk '
                   'silhouettes are rare (a few per year per observer) '
                   'and last fractions of a second.',
}


def _aspect(sat_slug, body, peak_at):
    return f'sat_transit__{sat_slug}__{body}__{peak_at:%Y%m%d_%H%M%S}'[:64]


def _format_event(sat, ev):
    """Build a (title, notes, severity_for_concern) tuple."""
    body = ev['body'].title()
    kind = ev['kind']
    if kind == 'transit':
        title = (f'{sat.name} transits the {body} · '
                 f'sep {ev["min_sep_deg"]*60:.1f}\' · '
                 f'{ev["duration_s"]:.1f} s')
    else:
        title = (f'{sat.name} appulse with the {body} · '
                 f'sep {ev["min_sep_deg"]*60:.1f}\'')
    notes_lines = [
        f'Predicted {kind} of {sat.name} across the {body}.',
        f'Peak: {ev["peak_at"]:%Y-%m-%d %H:%M:%S} UT',
        f'Minimum separation: {ev["min_sep_deg"]:.4f}° '
        f'({ev["min_sep_deg"]*60:.2f} arcminutes)',
        f'{body} altitude at peak: {ev["body_alt_deg"]:.1f}°',
        f'{body} azimuth at peak:  {ev["body_az_deg"]:.1f}°',
        f'Satellite altitude at peak: {ev["sat_alt_deg"]:.1f}°',
    ]
    if kind == 'transit':
        notes_lines.append(
            f'Transit duration: {ev["duration_s"]:.1f} s '
            f'(satellite silhouetted on the disk).'
        )
        # Severity scaled by how central the transit is. min_sep=0
        # is dead-centre (best photo), edge-grazing is min_sep ≈ body
        # radius. Solar/lunar radii ~0.26°, so ratio 0..1.
        body_radius = 0.266 if ev['body'] == 'sun' else 0.259
        centrality = max(0.0, 1.0 - ev['min_sep_deg'] / body_radius)
        severity = 0.5 + 0.4 * centrality  # 0.5 for grazing → 0.9 dead-centre
    else:
        body_radius = 0.266 if ev['body'] == 'sun' else 0.259
        notes_lines.append(
            f'Appulse: closest approach is {ev["min_sep_deg"] - body_radius:.4f}° '
            f'beyond the {body} disk edge.'
        )
        severity = 0.0  # appulses don't open concerns

    return title, '\n'.join(notes_lines), severity


class Command(BaseCommand):
    help = 'Predict next-N-days satellite transits across the Sun/Moon.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=90,
                            help='Look-ahead in days (default 90).')
        parser.add_argument('--only', default='',
                            help='Comma-separated sat slugs.')
        parser.add_argument('--no-concerns', action='store_true')

    def handle(self, *args, **opts):
        prefs = ClockPrefs.load()
        tradition, _ = Tradition.objects.update_or_create(
            slug=TRADITION['slug'],
            defaults={k: v for k, v in TRADITION.items() if k != 'slug'},
        )

        only = {s.strip() for s in opts['only'].split(',') if s.strip()}
        sats = TrackedObject.objects.filter(
            kind=TrackedObject.KIND_SATELLITE, is_watched=True,
        )
        if only:
            sats = sats.filter(slug__in=only)

        try:
            from identity.models import Concern
            have_identity = True
        except Exception:
            have_identity = False

        now = djtz.now()
        all_seen_aspects = set()
        total_transits = 0
        total_appulses = 0
        total_concerns_opened = 0

        for sat in sats:
            tle = sat.elements_json or {}
            if not tle.get('line1'):
                self.stdout.write(self.style.WARNING(
                    f'  ! {sat.name}: no TLE, skipped.'
                ))
                continue

            self.stdout.write(f'  · {sat.name}: scanning {opts["days"]} days…')
            try:
                events = find_transits(
                    tle, prefs.home_lat, prefs.home_lon, prefs.home_elev_m,
                    days=opts['days'],
                )
            except Exception as exc:
                self.stdout.write(self.style.WARNING(
                    f'  ! {sat.name}: scan failed: {exc}'
                ))
                continue

            slug_tag = f'sat-transit:{sat.slug}'
            CalendarEvent.objects.filter(
                source='feed', tradition=tradition,
                tags__contains=slug_tag,
                start__gte=now,
            ).delete()

            for ev in events:
                title, notes, severity = _format_event(sat, ev)
                end_at = ev['peak_at'] + dt.timedelta(seconds=max(60, ev['duration_s'] + 30))
                CalendarEvent.objects.create(
                    source='feed', tradition=tradition,
                    title=title,
                    start=ev['peak_at'],
                    end=end_at,
                    all_day=False,
                    color=tradition.color,
                    tags=f'sat-transit,{slug_tag},body:{ev["body"]},kind:{ev["kind"]}',
                    notes=notes,
                )
                if ev['kind'] == 'transit':
                    total_transits += 1
                    if have_identity and not opts['no_concerns']:
                        aspect = _aspect(sat.slug, ev['body'], ev['peak_at'])
                        all_seen_aspects.add(aspect)
                        existing = Concern.objects.filter(
                            aspect=aspect, closed_at__isnull=True,
                        ).first()
                        name = title
                        if not existing:
                            Concern.objects.create(
                                aspect=aspect, name=name,
                                description=notes, severity=severity,
                            )
                            total_concerns_opened += 1
                        else:
                            existing.severity = severity
                            existing.description = notes
                            existing.save(update_fields=['severity', 'description'])
                else:
                    total_appulses += 1

            self.stdout.write(
                f'    → {len(events)} events '
                f'({sum(1 for e in events if e["kind"]=="transit")} transits, '
                f'{sum(1 for e in events if e["kind"]=="appulse")} appulses)'
            )

        # Auto-close concerns whose transits have passed (or fallen
        # outside the recomputed window).
        closed = 0
        if have_identity and not opts['no_concerns']:
            from identity.models import Concern
            stale_qs = Concern.objects.filter(
                aspect__startswith='sat_transit__', closed_at__isnull=True,
            ).exclude(aspect__in=all_seen_aspects)
            for c in stale_qs:
                c.close(reason='resolved',
                        note='Transit window has passed or fell outside the '
                             'computed look-ahead.')
                closed += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done. {total_transits} transits + '
            f'{total_appulses} appulses · '
            f'{total_concerns_opened} concerns opened, {closed} closed.'
        ))
