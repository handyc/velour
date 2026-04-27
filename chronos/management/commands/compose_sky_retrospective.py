"""Compose the year-to-date Sky Retrospective — backward-looking
Codex Manual complement to the forward-looking Sky Almanac.

The almanac (Phase 16) lists what's coming. The retrospective tells
the story of what the year has been so far: eclipses observed,
notable satellite passes, closest NEO approaches, space-weather
peaks, weather extremes, coastal events.

Sources: existing CalendarEvent past entries + Measurement extremes.
First run mid-year is partial ("year so far"); the complete picture
naturally fills in as the year accumulates. End-of-year run captures
the full retrospective; we don't auto-freeze it because re-running
the same year just refreshes the same manual idempotently.

Usage:

    python manage.py compose_sky_retrospective
        Year-to-date retrospective for the current calendar year.

    python manage.py compose_sky_retrospective --year 2025
        Retrospective for a past year (whatever data is still on disk).

    python manage.py compose_sky_retrospective --quiet
        Suppress per-section output.
"""

import datetime as dt

from django.core.management.base import BaseCommand
from django.utils import timezone as djtz
from zoneinfo import ZoneInfo


def _local_tz():
    from chronos.models import ClockPrefs
    return ZoneInfo(ClockPrefs.load().home_tz)


def _astro_events_in(year_start, year_end, name_filter=None):
    """Pull source='astro' CalendarEvents in the period."""
    from chronos.models import CalendarEvent
    qs = CalendarEvent.objects.filter(
        source='astro',
        start__gte=year_start,
        start__lt=year_end,
    ).order_by('start')
    if name_filter:
        qs = [e for e in qs if any(w in e.title.lower() for w in name_filter)]
    else:
        qs = list(qs)
    return qs


def _past_calendar_events(year_start, year_end, tradition_slugs):
    from chronos.models import CalendarEvent
    return list(CalendarEvent.objects.filter(
        source='feed', tradition__slug__in=tradition_slugs,
        start__gte=year_start, start__lt=year_end,
    ).order_by('start'))


def _measurement_extremes(year_start, year_end, source, metric,
                          mode='max', limit=3):
    """Top-N (mode='max') or bottom-N (mode='min') Measurements
    for a given source/metric in the period."""
    from chronos.models import Measurement
    order = '-value' if mode == 'max' else 'value'
    return list(Measurement.objects.filter(
        source=source, metric=metric,
        at__gte=year_start, at__lt=year_end,
    ).order_by(order)[:limit])


def _flatten_past_events(events, tz):
    """Render a chronological table of past events."""
    if not events:
        return '_None on record._'
    rows = ['| Date | Event |',
            '|:--|:--|']
    for ev in events:
        local = ev.start.astimezone(tz)
        rows.append(f'| {local:%a %d %b %Y · %H:%M} | {ev.title} |')
    return '\n'.join(rows)


def _sw_section(year_start, year_end, tz):
    from chronos.astro_sources.space_weather import xray_class
    lines = []
    lines.append('Highlights from NOAA SWPC monitoring '
                 '(Kp index, X-ray flux, sunspots, aurora oval):')
    lines.append('')

    kp_max = _measurement_extremes(year_start, year_end, 'noaa-swpc',
                                   'kp_index', 'max', 3)
    if kp_max:
        lines.append('### Strongest geomagnetic activity (Kp index)')
        lines.append('')
        for m in kp_max:
            lines.append(f'- **Kp {m.value:.1f}** at '
                         f'{m.at.astimezone(tz):%a %d %b %Y · %H:%M local}')
        lines.append('')

    xray_max = _measurement_extremes(year_start, year_end, 'noaa-swpc',
                                     'xray_flux', 'max', 3)
    if xray_max:
        lines.append('### Strongest X-ray flares (GOES primary band)')
        lines.append('')
        for m in xray_max:
            cls = xray_class(m.value)
            lines.append(f'- **{cls}** ({m.value:.2e} W/m²) at '
                         f'{m.at.astimezone(tz):%a %d %b · %H:%M local}')
        lines.append('')

    sn = _measurement_extremes(year_start, year_end, 'noaa-swpc',
                               'sunspot_number', 'max', 1)
    if sn:
        m = sn[0]
        lines.append(f'### Peak sunspot number')
        lines.append('')
        lines.append(
            f'**{m.value:.0f}** in {m.at.astimezone(tz):%B %Y}.')
        lines.append('')

    if not (kp_max or xray_max or sn):
        return ('_No space-weather measurements on record for this period. '
                'Velour\'s SWPC pipeline begins accumulating once '
                '`refresh_space_weather` first runs._')
    return '\n'.join(lines)


def _weather_section(year_start, year_end, tz):
    """Weather + air-quality extremes from Measurement."""
    parts = []
    parts.append('Highlights from Open-Meteo monitoring:')
    parts.append('')

    # Hottest day, coldest day from daily max/min temps
    hot = _measurement_extremes(year_start, year_end, 'open-meteo-weather',
                                'temperature_2m_max', 'max', 3)
    cold = _measurement_extremes(year_start, year_end, 'open-meteo-weather',
                                 'temperature_2m_min', 'min', 3)
    if hot:
        parts.append('### Hottest days')
        parts.append('')
        for m in hot:
            parts.append(f'- **{m.value:.1f} °C** on '
                         f'{m.at.astimezone(tz):%A %d %B}')
        parts.append('')
    if cold:
        parts.append('### Coldest days')
        parts.append('')
        for m in cold:
            parts.append(f'- **{m.value:.1f} °C** on '
                         f'{m.at.astimezone(tz):%A %d %B}')
        parts.append('')

    # UV peak, AQI peak (worst air-quality day)
    uv = _measurement_extremes(year_start, year_end, 'open-meteo-weather',
                               'uv_index_max', 'max', 1)
    if uv:
        m = uv[0]
        parts.append(f'**Peak UV index**: {m.value:.1f} on '
                     f'{m.at.astimezone(tz):%A %d %B}.')
        parts.append('')

    aqi = _measurement_extremes(year_start, year_end, 'open-meteo',
                                'european_aqi', 'max', 3)
    if aqi:
        parts.append('### Worst air-quality readings (European AQI)')
        parts.append('')
        from chronos.astro_sources.local_environment import european_aqi_band
        for m in aqi:
            parts.append(f'- **EAQI {m.value:.0f}** ({european_aqi_band(m.value)}) at '
                         f'{m.at.astimezone(tz):%A %d %B · %H:%M}')
        parts.append('')

    o3 = _measurement_extremes(year_start, year_end, 'open-meteo',
                               'ozone', 'max', 1)
    if o3:
        m = o3[0]
        parts.append(f'**Peak ozone**: {m.value:.0f} µg/m³ at '
                     f'{m.at.astimezone(tz):%A %d %B · %H:%M}.')
        if m.value > 180:
            parts.append('Above the EU 1-hour info threshold (180 µg/m³).')

    if len(parts) <= 2:
        return ('_No weather measurements on record for this period yet. '
                'The pipeline starts accumulating once `refresh_weather` '
                'and `refresh_local_environment` first run._')
    return '\n'.join(parts)


def _coast_section(year_start, year_end, tz):
    """Tide + wave + SST extremes."""
    parts = []
    parts.append('Highlights from the Open-Meteo marine forecast:')
    parts.append('')
    high_tide = _measurement_extremes(year_start, year_end,
                                      'open-meteo-marine',
                                      'sea_level_height_msl', 'max', 3)
    low_tide = _measurement_extremes(year_start, year_end,
                                     'open-meteo-marine',
                                     'sea_level_height_msl', 'min', 3)
    if high_tide:
        parts.append('### Highest tides (relative to MSL)')
        parts.append('')
        for m in high_tide:
            parts.append(f'- **+{m.value:.2f} m** at '
                         f'{m.at.astimezone(tz):%A %d %B · %H:%M}')
        parts.append('')
    if low_tide:
        parts.append('### Lowest tides')
        parts.append('')
        for m in low_tide:
            parts.append(f'- **{m.value:+.2f} m** at '
                         f'{m.at.astimezone(tz):%A %d %B · %H:%M}')
        parts.append('')

    waves = _measurement_extremes(year_start, year_end,
                                  'open-meteo-marine',
                                  'wave_height', 'max', 3)
    if waves:
        parts.append('### Roughest seas')
        parts.append('')
        for m in waves:
            parts.append(f'- **{m.value:.2f} m wave height** on '
                         f'{m.at.astimezone(tz):%A %d %B · %H:%M}')
        parts.append('')

    if len(parts) <= 2:
        return ('_No marine measurements on record yet. The pipeline '
                'starts accumulating once `refresh_marine` first runs._')
    return '\n'.join(parts)


def _highlights_section(year_label, eclipses, neos, sat_passes, transits,
                        kp_max, year_start, year_end):
    lines = [f'## The year so far · {year_label}']
    lines.append('')
    lines.append(
        f'A backward look at celestial and environmental notables '
        f'on the record from {year_start:%d %B %Y} to '
        f'{year_end:%d %B %Y}.'
    )
    lines.append('')
    lines.append('At a glance:')
    lines.append('')
    lines.append(f'- **{len(eclipses)}** eclipses')
    lines.append(f'- **{len(neos)}** NEO close approaches under threshold')
    lines.append(f'- **{len(sat_passes)}** satellite passes recorded')
    lines.append(f'- **{len(transits)}** sun/moon transits or appulses')
    if kp_max:
        lines.append(f'- Strongest geomagnetic disturbance: **Kp {kp_max[0].value:.1f}**')
    lines.append('')
    return '\n'.join(lines)


class Command(BaseCommand):
    help = 'Compose the year-to-date Sky Retrospective Codex Manual.'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, default=None,
                            help='Calendar year. Default = current year.')
        parser.add_argument('--quiet', action='store_true')

    def handle(self, *args, **opts):
        from chronos.models import ClockPrefs
        from codex.models import Manual, Section

        prefs = ClockPrefs.load()
        tz = _local_tz()
        now = djtz.now()
        local_now = now.astimezone(tz)

        year = opts['year'] or local_now.year
        year_start = dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc)
        year_end_natural = dt.datetime(year + 1, 1, 1, tzinfo=dt.timezone.utc)
        # Cap at "now" so we don't include future predictions in a retrospective.
        year_end = min(year_end_natural, now)

        # Collect data
        eclipses = _astro_events_in(year_start, year_end,
                                    name_filter=['eclipse'])
        equinoxes = _astro_events_in(year_start, year_end,
                                     name_filter=['equinox', 'solstice'])
        conjunctions = _astro_events_in(year_start, year_end,
                                        name_filter=['conjunction'])
        meteors = _astro_events_in(year_start, year_end,
                                   name_filter=['meteor', '(peak)'])
        neos = _past_calendar_events(year_start, year_end, ['neos'])
        sat_passes = _past_calendar_events(year_start, year_end,
                                           ['satellites'])
        transits = _past_calendar_events(year_start, year_end,
                                         ['sat-transits'])
        kp_max = _measurement_extremes(year_start, year_end, 'noaa-swpc',
                                       'kp_index', 'max', 3)

        slug = f'sky-retrospective-{year}'
        title = f'Sky Retrospective · {year}'

        manual, created = Manual.objects.update_or_create(
            slug=slug,
            defaults={
                'title':    title,
                'subtitle': (
                    f'A year-to-date look back from '
                    f'{prefs.home_lat:.2f}°N {prefs.home_lon:.2f}°E '
                    f'· compiled {local_now:%a %d %b %Y %H:%M %Z}'
                ),
                'format':   'medium',
                'author':   'Velour · Chronos',
                'abstract': (
                    'A retrospective digest of the celestial and '
                    'environmental notables observed (or predicted to '
                    'have occurred) over the calendar year so far. '
                    'Counterpart to the forward-looking Sky Almanac. '
                    'Composed from CalendarEvent and Measurement records '
                    'in the chronos database; sections will fill out as '
                    'the year accumulates and as Velour\'s monitoring '
                    'pipelines accumulate history.'
                ),
            },
        )

        manual.sections.all().delete()

        Section.objects.create(
            manual=manual, title='At a glance',
            body=_highlights_section(year, eclipses, neos, sat_passes,
                                     transits, kp_max,
                                     year_start, year_end),
            sort_order=10,
        )
        Section.objects.create(
            manual=manual, title='Eclipses',
            body=(
                'Solar and lunar eclipses on record this year.\n\n'
                + _flatten_past_events(eclipses, tz)
            ),
            sort_order=20,
        )
        Section.objects.create(
            manual=manual, title='Equinoxes & solstices',
            body=(
                'The cardinal points of the solar year that have occurred:\n\n'
                + _flatten_past_events(equinoxes, tz)
            ),
            sort_order=25,
        )
        Section.objects.create(
            manual=manual, title='Planetary conjunctions',
            body=(
                'Naked-eye planetary pairs that came within 3° of each '
                'other:\n\n'
                + _flatten_past_events(conjunctions, tz)
            ),
            sort_order=30,
        )
        Section.objects.create(
            manual=manual, title='Meteor shower peaks',
            body=(
                'Annual meteor shower peaks reached this year:\n\n'
                + _flatten_past_events(meteors, tz)
            ),
            sort_order=35,
        )
        Section.objects.create(
            manual=manual, title='Near-Earth-object close approaches',
            body=(
                'Asteroids that passed within 10 lunar distances. None '
                'were predicted to impact Earth.\n\n'
                + _flatten_past_events(neos, tz)
            ),
            sort_order=40,
        )
        Section.objects.create(
            manual=manual, title='Space weather extremes',
            body=_sw_section(year_start, year_end, tz),
            sort_order=50,
        )
        Section.objects.create(
            manual=manual, title='Local weather extremes',
            body=_weather_section(year_start, year_end, tz),
            sort_order=60,
        )
        Section.objects.create(
            manual=manual, title='Coast notables',
            body=_coast_section(year_start, year_end, tz),
            sort_order=65,
        )
        Section.objects.create(
            manual=manual, title='Sources',
            body=(
                'Composed from existing chronos data:\n\n'
                '- **Astronomical events** — `chronos.astro_sources` '
                '(skyfield + JPL DE421 ephemeris).\n'
                '- **NEOs** — JPL CNEOS catalog mirrored into '
                'CalendarEvent under tradition `neos`.\n'
                '- **Satellite passes / transits** — `refresh_satellites` '
                '+ `compute_sat_transits` from CelesTrak TLE.\n'
                '- **Space weather** — NOAA SWPC '
                '(`services.swpc.noaa.gov`).\n'
                '- **Weather + air quality + marine** — Open-Meteo APIs '
                '(`api.open-meteo.com`, `air-quality-api.open-meteo.com`, '
                '`marine-api.open-meteo.com`).\n\n'
                'No AI involved in any computation. This manual is '
                'recomposed monthly by `identity_cron` via '
                '`compose_sky_retrospective`. Re-running the command '
                'rebuilds every section in place — idempotent per year.'
            ),
            sort_order=99,
        )

        manual.save(update_fields=['updated_at'])
        action = 'created' if created else 're-rendered'
        if not opts['quiet']:
            self.stdout.write(self.style.SUCCESS(
                f'{action} {manual.title} (slug {manual.slug}) · '
                f'{len(eclipses)} eclipses · {len(equinoxes)} '
                f'equinoxes/solstices · {len(conjunctions)} conjunctions '
                f'· {len(meteors)} meteor peaks · {len(neos)} NEOs · '
                f'{len(sat_passes)} sat passes · {len(transits)} '
                f'transits/appulses recorded · '
                f'{len(kp_max)} Kp samples on file.'
            ))
