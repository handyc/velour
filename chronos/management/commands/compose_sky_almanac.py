"""Compose the yearly Sky Almanac — a Codex Manual ranking and
narrating the next 12 months of celestial events from the observer's
location.

Counterpart to compose_pass_digest (weekly): the digest is operational
("set your alarm tomorrow"), the almanac is editorial ("2026's best
skywatching opportunities, in order").

Composes from existing CalendarEvent data — eclipses, equinoxes,
solstices, planetary conjunctions, meteor shower peaks, NEO close
approaches, and any upcoming on-disk satellite transits — into one
medium-format Codex Manual.

Idempotent per calendar year: a manual with slug `sky-almanac-<YYYY>`
is created once and re-rendered (sections wiped + rewritten) on
subsequent runs the same year. Wire as a monthly cron pipeline so the
content stays current as new NEOs are discovered and TLEs drift.

Usage:

    python manage.py compose_sky_almanac
        Compose the almanac covering the next 12 months.

    python manage.py compose_sky_almanac --quiet
        Suppress per-section output (useful from cron).
"""

import datetime as dt

from django.core.management.base import BaseCommand
from django.utils import timezone as djtz
from zoneinfo import ZoneInfo


def _local_tz():
    from chronos.models import ClockPrefs
    return ZoneInfo(ClockPrefs.load().home_tz)


def _events_in_window(now, days, sources=None, tradition_slugs=None,
                      title_excludes=None):
    """Pull CalendarEvents in [now, now+days] filtered by source +
    tradition + title-substring exclusions."""
    from chronos.models import CalendarEvent
    qs = CalendarEvent.objects.filter(
        start__gte=now, start__lte=now + dt.timedelta(days=days),
    )
    if sources:
        qs = qs.filter(source__in=sources)
    if tradition_slugs:
        qs = qs.filter(tradition__slug__in=tradition_slugs)
    if title_excludes:
        for ex in title_excludes:
            qs = qs.exclude(title__icontains=ex)
    return list(qs.order_by('start'))


def _highlights_section(eclipses, conjunctions, meteors,
                        neos, transits, equinoxes, tz):
    """Build the editorial 'Highlights of the year' section."""
    lines = [
        '## At a glance',
        '',
        f'Over the next 12 months from {djtz.now().astimezone(tz):%d %B %Y}, '
        f'the sky will host:',
        '',
        f'- **{len(eclipses)} eclipses** of the Sun or Moon',
        f'- **{len(equinoxes)} equinoxes / solstices** marking the seasons',
        f'- **{len(conjunctions)} planetary conjunctions** (naked-eye pairs '
        f'within 3°)',
        f'- **{len(meteors)} meteor shower peaks** worth tracking',
        f'- **{len(neos)} near-Earth-object close approaches** under 10 '
        f'lunar distances',
    ]
    if transits:
        lines.append(
            f'- **{len(transits)} satellite transits / appulses** of the '
            f'Sun or Moon predicted from this observer location'
        )
    lines.append('')

    # Pick the top 3 marquee events by date proximity + intrinsic interest.
    marquee = []
    for ev in eclipses[:2]:
        marquee.append(('🌑' if 'lunar' in ev.title.lower() else '☀️', ev))
    for ev in meteors[:1]:
        marquee.append(('☄', ev))
    for ev in conjunctions[:1]:
        marquee.append(('🪐', ev))
    if marquee:
        lines.append('### Marquee events')
        lines.append('')
        for emoji, ev in marquee[:4]:
            local = ev.start.astimezone(tz)
            lines.append(f'- {emoji} **{ev.title}** — {local:%A %d %B %Y · %H:%M}')
        lines.append('')

    return '\n'.join(lines)


def _events_table(events, tz, with_kind=False):
    """Render a list of events as a Markdown table sorted by date."""
    if not events:
        return '_None in the next 12 months._'
    rows = ['| Date (local) | Event |',
            '|:--|:--|']
    for ev in events:
        local = ev.start.astimezone(tz)
        rows.append(f'| {local:%a %d %b %Y · %H:%M} | {ev.title} |')
    return '\n'.join(rows)


def _meteor_tips(events, tz):
    """Annotated list — meteor showers carry observer-side tips."""
    if not events:
        return '_No meteor shower peaks in the next 12 months._'
    lines = []
    for ev in events:
        local = ev.start.astimezone(tz)
        when = local.strftime('%A %d %B %Y, %H:%M')
        lines.append(f'- **{ev.title}** — peak {when} local')
    lines.append('')
    lines.append(
        '### Observation tips'
    )
    lines.append('')
    lines.append(
        'For a meteor shower, peak rates are best observed *after midnight* '
        'when the observer\'s side of Earth is rotating into the meteor '
        'stream. Get away from city lights, give your eyes 20 minutes to '
        'adapt to the dark, and look up — meteors can appear anywhere in '
        'the sky, not just near the radiant. The Moon\'s phase matters: a '
        'bright Moon washes out fainter meteors, so a dark-Moon shower '
        'easily doubles the visible count.'
    )
    return '\n'.join(lines)


def _neo_table(events, tz):
    """NEOs need extra columns (distance, size, velocity)."""
    import re
    if not events:
        return '_No close NEO approaches under 10 LD in the next 12 months._'
    rows = ['| Date (local) | Designation | LD | Velocity | ~Size |',
            '|:--|:--|--:|--:|:--|']
    for ev in events:
        local = ev.start.astimezone(tz)
        notes = ev.notes or ''
        m_des = re.search(r'Designation:[ \t]*([^\n]+)', notes)
        m_ld = re.search(r'=\s*([\d.]+)\s*lunar', notes)
        m_v = re.search(r'velocity:\s*([\d.]+)\s*km', notes)
        m_size = re.search(r'estimated diameter\s+([^)]+?)\s*\)', notes)
        des = m_des.group(1).strip() if m_des else ev.title.split(' ·')[0]
        ld = f'{float(m_ld.group(1)):.2f}' if m_ld else '—'
        v = f'{float(m_v.group(1)):.1f} km/s' if m_v else '—'
        size = m_size.group(1).strip() if m_size else '—'
        rows.append(f'| {local:%a %d %b · %H:%M} | {des} | {ld} | {v} | {size} |')
    return '\n'.join(rows)


def _transits_section(events, tz):
    if not events:
        return ('_No satellite transits or appulses across the Sun/Moon '
                'predicted in the next 12 months from this observer '
                'location. These events are rare — a few per satellite '
                'per year — and depend on the precise alignment of the '
                'satellite\'s orbit, the Sun or Moon, and the observer._')
    import re
    rows = ['| Date (local) | Object | Body | Kind | Min sep |',
            '|:--|:--|:--|:--|--:|']
    for ev in events:
        local = ev.start.astimezone(tz)
        tags = ev.tags or ''
        kind = 'transit' if 'kind:transit' in tags else 'appulse'
        body = ('Sun' if 'body:sun' in tags else
                'Moon' if 'body:moon' in tags else '?')
        m = re.search(r"sep\s+([\d.]+)'", ev.title)
        sep = f"{m.group(1)}'" if m else '—'
        sat = ev.title.split(' ')[0] + ' ' + ev.title.split(' ')[1] if ' ' in ev.title else ev.title
        rows.append(f'| {local:%a %d %b · %H:%M} | {sat} | {body} | {kind} | {sep} |')
    return '\n'.join(rows)


class Command(BaseCommand):
    help = 'Compose the yearly Sky Almanac as a Codex Manual.'

    def add_arguments(self, parser):
        parser.add_argument('--quiet', action='store_true')

    def handle(self, *args, **opts):
        from chronos.models import ClockPrefs
        from codex.models import Manual, Section

        prefs = ClockPrefs.load()
        tz = _local_tz()
        now = djtz.now()
        local = now.astimezone(tz)
        year = local.year
        slug = f'sky-almanac-{year}'
        title = f'Sky Almanac · {year}'

        # Pull events
        eclipses = [e for e in _events_in_window(now, 365, sources=['astro'])
                    if 'eclipse' in e.title.lower()]
        equinoxes = [e for e in _events_in_window(now, 365, sources=['astro'])
                     if any(w in e.title.lower()
                            for w in ('equinox', 'solstice'))]
        conjunctions = [e for e in _events_in_window(now, 365, sources=['astro'])
                        if 'conjunction' in e.title.lower()]
        meteors = [e for e in _events_in_window(now, 365, sources=['astro'])
                   if 'meteor' in e.title.lower()
                   or '(peak)' in e.title.lower()]
        neos = _events_in_window(now, 365, tradition_slugs=['neos'])
        transits = _events_in_window(now, 365, tradition_slugs=['sat-transits'])

        manual, created = Manual.objects.update_or_create(
            slug=slug,
            defaults={
                'title':    title,
                'subtitle': (
                    f'A 12-month forward look from '
                    f'{prefs.home_lat:.2f}°N {prefs.home_lon:.2f}°E '
                    f'· compiled {local:%a %d %b %Y %H:%M %Z}'
                ),
                'format':   'medium',
                'author':   'Velour · Chronos',
                'abstract': (
                    'A yearly editorial digest of the celestial events '
                    'visible from the configured observer location: '
                    'eclipses, equinoxes, planetary conjunctions, meteor '
                    'shower peaks, near-Earth-object close approaches, '
                    'and any predicted satellite transits across the Sun '
                    'or Moon. Composed from skyfield + JPL DE421 '
                    '(astronomical events), JPL CNEOS (NEOs), and '
                    'CelesTrak TLE + skyfield SGP4 (satellite transits). '
                    'Refreshed monthly so the catalog stays current.'
                ),
            },
        )

        # Wipe and re-render sections
        manual.sections.all().delete()

        Section.objects.create(
            manual=manual, title='Highlights',
            body=_highlights_section(eclipses, conjunctions, meteors,
                                     neos, transits, equinoxes, tz),
            sort_order=10,
        )

        Section.objects.create(
            manual=manual, title='Eclipses',
            body=(
                'Eclipses are the year\'s most spectacular astronomical '
                'events, watched and photographed from across the world. '
                'Local visibility depends on geography — a total solar '
                'eclipse is total only along a narrow ground track, while '
                'lunar eclipses are visible from the entire night side of '
                'Earth.\n\n'
                + _events_table(eclipses, tz)
            ),
            sort_order=20,
        )

        Section.objects.create(
            manual=manual, title='Equinoxes & solstices',
            body=(
                'The four cardinal points of the solar year — when the '
                'Sun crosses the celestial equator (equinoxes) or reaches '
                'its declination extremes (solstices). They mark the '
                'astronomical onset of the four seasons.\n\n'
                + _events_table(equinoxes, tz)
            ),
            sort_order=30,
        )

        Section.objects.create(
            manual=manual, title='Planetary conjunctions',
            body=(
                'A conjunction is a moment when two naked-eye planets '
                'appear close together in the sky, typically within a '
                'few degrees. The pairs covered here are Mercury, Venus, '
                'Mars, Jupiter, and Saturn — the five classical planets '
                'visible without optical aid. Times are the local minimum '
                'of apparent angular separation; both planets must be '
                'above the horizon to see the event.\n\n'
                + _events_table(conjunctions, tz)
            ),
            sort_order=40,
        )

        Section.objects.create(
            manual=manual, title='Meteor showers',
            body=(
                'Meteor showers happen when Earth crosses a stream of '
                'debris left by a comet (or, rarely, an asteroid). The '
                'peak rates listed below are zenith hourly counts under '
                'ideal dark-sky conditions; actual visible counts in '
                'light-polluted areas are typically a third to a tenth '
                'of these.\n\n'
                + _meteor_tips(meteors, tz)
            ),
            sort_order=50,
        )

        Section.objects.create(
            manual=manual, title='Near-Earth objects',
            body=(
                'Asteroids passing within 10 lunar distances of Earth, '
                'sourced from the JPL Center for NEO Studies. The '
                'distance shown is the *nominal* close approach; the '
                'actual distance has uncertainty, especially for objects '
                'with short observation arcs. None of these are predicted '
                'to impact Earth.\n\n'
                + _neo_table(neos, tz)
            ),
            sort_order=60,
        )

        Section.objects.create(
            manual=manual, title='Satellite transits',
            body=(
                'Predicted moments when a watched satellite (ISS, '
                'Tiangong, Hubble, etc.) silhouettes across — or passes '
                'very close to — the Sun or Moon as seen from this '
                'observer location. Genuine on-disk transits are rare '
                'and last fractions of a second, but well-timed photographs '
                'can capture the silhouette in striking detail.\n\n'
                'See `compute_sat_transits` and the `/chronos/sky/transits/` '
                'overview page for the live photo-conditions assessment.\n\n'
                + _transits_section(transits, tz)
            ),
            sort_order=70,
        )

        Section.objects.create(
            manual=manual, title='Sources & methods',
            body=(
                'All data in this almanac is computed locally, with no '
                'AI-model dependency. Sources:\n\n'
                '- **Astronomical events** (eclipses, conjunctions, '
                'equinoxes, solstices) — `skyfield` + JPL DE421 '
                'planetary ephemeris.\n'
                '- **Meteor showers** — hand-curated table of fixed '
                'Gregorian peak dates, since shower peaks shift only '
                'slightly year to year.\n'
                '- **Near-Earth objects** — JPL CNEOS Close Approach API '
                '(`ssd-api.jpl.nasa.gov/cad.api`).\n'
                '- **Satellite transits** — `chronos.astro_sources.satellites'
                '.find_transits()` (skyfield SGP4 + DE421, observer-relative '
                'sat-vs-body angular separation scan).\n\n'
                'This manual is composed and refreshed monthly by '
                '`identity_cron` via `compose_sky_almanac`. Re-running '
                'the command rebuilds every section in place — '
                'idempotent per calendar year.'
            ),
            sort_order=99,
        )

        manual.save(update_fields=['updated_at'])
        action = 'created' if created else 're-rendered'

        if not opts['quiet']:
            self.stdout.write(self.style.SUCCESS(
                f'{action} {manual.title} (slug {manual.slug}) · '
                f'{len(eclipses)} eclipses · '
                f'{len(equinoxes)} equinox/solstice · '
                f'{len(conjunctions)} conjunctions · '
                f'{len(meteors)} meteor peaks · '
                f'{len(neos)} NEOs · '
                f'{len(transits)} sat transits.'
            ))
