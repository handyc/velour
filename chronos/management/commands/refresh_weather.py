"""Pull weather forecast for the observer location and store in
chronos.Measurement under source='open-meteo-weather'.

Open-Meteo's free `/v1/forecast` returns 7 days of hourly + daily
data. Same idempotent upsert and per-metric retention pattern as
refresh_local_environment.

Sunrise/sunset times come along on the daily weather_code rows in
`extra` JSON, so the dome can highlight a sunset window without a
second round-trip.
"""

import datetime as dt

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone as djtz

from chronos.astro_sources.weather import fetch_weather
from chronos.models import ClockPrefs, Measurement


SOURCE = 'open-meteo-weather'

# Hourly metrics — short retention since forecast rolls daily.
HOURLY_RETENTION = {
    'temperature_2m':            14,
    'cloud_cover':               14,
    'precipitation':             14,
    'precipitation_probability': 14,
    'relative_humidity_2m':      14,
    'wind_speed_10m':            14,
    'wind_direction_10m':        14,
    'visibility':                14,
    'weather_code':              14,
}

# Daily metrics — keep longer for trend lines.
DAILY_RETENTION = {
    'temperature_2m_max':     180,
    'temperature_2m_min':     180,
    'sunshine_duration':      180,
    'precipitation_sum':      180,
    'uv_index_max':           90,
    'weather_code_daily':     180,
}

ALL_RETENTION = {**HOURLY_RETENTION, **DAILY_RETENTION}


def _upsert(samples, daily=False):
    """Bulk upsert. Daily samples carry an extra dict; hourly don't."""
    new = 0
    for s in samples:
        defaults = {'value': s['value'], 'unit': s['unit']}
        if s.get('extra'):
            defaults['extra'] = s['extra']
        _, created = Measurement.objects.update_or_create(
            source=SOURCE, metric=s['metric'], at=s['at'],
            defaults=defaults,
        )
        if created:
            new += 1
    return new, len(samples)


def _prune():
    total = 0
    for metric, days in ALL_RETENTION.items():
        cutoff = djtz.now() - dt.timedelta(days=days)
        total += Measurement.objects.filter(
            source=SOURCE, metric=metric, at__lt=cutoff,
        ).delete()[0]
    return total


class Command(BaseCommand):
    help = 'Pull weather forecast from Open-Meteo for ClockPrefs.home_*.'

    def add_arguments(self, parser):
        parser.add_argument('--no-prune', action='store_true')

    @transaction.atomic
    def handle(self, *args, **opts):
        prefs = ClockPrefs.load()
        try:
            data = fetch_weather(prefs.home_lat, prefs.home_lon)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(
                f'Open-Meteo weather fetch failed: {exc}'
            ))
            return

        new_h, seen_h = _upsert(data['hourly'])
        new_d, seen_d = _upsert(data['daily'], daily=True)
        pruned = _prune() if not opts['no_prune'] else 0

        self.stdout.write(self.style.SUCCESS(
            f'Done. {seen_h} hourly + {seen_d} daily processed · '
            f'{new_h + new_d} new rows · {pruned} pruned.'
        ))
