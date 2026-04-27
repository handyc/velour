"""Pull space-weather data from NOAA SWPC and store as Measurements.

Idempotent: source/metric/at is unique, so re-runs upsert without
duplicating. Pruning is done after the upsert based on per-metric
retention windows (most metrics keep 90 days; sunspots keep forever
because the series is monthly and the historical context matters).

Usage:

    python manage.py refresh_space_weather
        Fetch all five SWPC sources at default windows.

    python manage.py refresh_space_weather --no-prune
        Skip the post-fetch retention prune.
"""

import datetime as dt

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone as djtz

from chronos.astro_sources import space_weather as sw
from chronos.models import Measurement


SOURCE = 'noaa-swpc'

# (metric, unit, retention_days) — None = keep forever.
RETENTION = {
    'kp_index':           ('',         180),
    'wind_speed':         ('km/s',      30),
    'wind_density':       ('p/cm³',     30),
    'wind_temperature':   ('K',         30),
    'xray_flux':          ('W/m²',      30),
    'sunspot_number':     ('',          None),
    'aurora_max_pct':     ('%',         30),
    'aurora_north_min_lat': ('°N',      30),
}


def _upsert(metric, samples):
    """Bulk-style upsert one metric. samples is a list of {at,value,extra}."""
    unit = RETENTION[metric][0]
    inserted = 0
    for s in samples:
        _, c = Measurement.objects.update_or_create(
            source=SOURCE, metric=metric, at=s['at'],
            defaults={
                'value': s['value'],
                'unit':  unit,
                'extra': s.get('extra', {}),
            },
        )
        if c:
            inserted += 1
    return inserted


def _prune(metric):
    days = RETENTION[metric][1]
    if days is None:
        return 0
    cutoff = djtz.now() - dt.timedelta(days=days)
    return Measurement.objects.filter(
        source=SOURCE, metric=metric, at__lt=cutoff,
    ).delete()[0]


class Command(BaseCommand):
    help = 'Pull NOAA SWPC space-weather metrics into Measurement.'

    def add_arguments(self, parser):
        parser.add_argument('--no-prune', action='store_true',
                            help='Skip the per-metric retention prune.')

    @transaction.atomic
    def handle(self, *args, **opts):
        results = []

        # Kp — last 72 h
        try:
            samples = sw.fetch_kp(hours_back=72)
            n = _upsert('kp_index', samples)
            results.append(('kp_index', len(samples), n))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  ! Kp fetch failed: {e}'))

        # Solar wind — last 24 h, three metrics
        try:
            wind = sw.fetch_solar_wind(hours_back=24)
            n_s = _upsert('wind_speed',       wind['speed'])
            n_d = _upsert('wind_density',     wind['density'])
            n_T = _upsert('wind_temperature', wind['temperature'])
            results.append(('wind_speed',       len(wind['speed']),       n_s))
            results.append(('wind_density',     len(wind['density']),     n_d))
            results.append(('wind_temperature', len(wind['temperature']), n_T))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  ! wind fetch failed: {e}'))

        # X-ray — last 6 h
        try:
            samples = sw.fetch_xray(hours_back=6)
            n = _upsert('xray_flux', samples)
            results.append(('xray_flux', len(samples), n))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  ! X-ray fetch failed: {e}'))

        # Sunspots — last 24 months
        try:
            samples = sw.fetch_sunspots(months_back=24)
            n = _upsert('sunspot_number', samples)
            results.append(('sunspot_number', len(samples), n))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  ! sunspot fetch failed: {e}'))

        # Aurora oval — store summarised global state as a single sample
        try:
            oval = sw.fetch_aurora_oval()
            obs_at = sw._parse_iso_utc(oval['observation_time'])
            _upsert('aurora_max_pct', [{
                'at':    obs_at,
                'value': float(oval['max_intensity']),
                'extra': {
                    'forecast_time': oval.get('forecast_time'),
                    'north_boundary_by_lon': oval.get('north_boundary_by_lon'),
                    'south_boundary_by_lon': oval.get('south_boundary_by_lon'),
                },
            }])
            # Min north-boundary latitude — proxy for "how far south does
            # the aurora reach?". Lower = bigger aurora event.
            north_lats = [v for v in (oval.get('north_boundary_by_lon') or {}).values()
                          if v is not None]
            if north_lats:
                _upsert('aurora_north_min_lat', [{
                    'at':    obs_at,
                    'value': float(min(north_lats)),
                    'extra': {},
                }])
            results.append(('aurora_oval', 1, 1))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  ! aurora fetch failed: {e}'))

        # Prune
        pruned_total = 0
        if not opts['no_prune']:
            for metric in RETENTION:
                pruned_total += _prune(metric)

        for metric, fetched, inserted in results:
            self.stdout.write(
                f'  {metric:20s} fetched={fetched:>3} new={inserted}'
            )
        self.stdout.write(self.style.SUCCESS(
            f'Done. {sum(r[1] for r in results)} samples processed, '
            f'{sum(r[2] for r in results)} new rows, '
            f'{pruned_total} stale rows pruned.'
        ))
