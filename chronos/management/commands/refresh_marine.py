"""Pull marine forecast for the configured coastal point and store as
Measurements under source='open-meteo-marine'.

Same idempotent upsert + per-metric retention pattern as
refresh_local_environment / refresh_weather.
"""

import datetime as dt

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone as djtz

from chronos.astro_sources.marine import fetch_marine
from chronos.models import ClockPrefs, Measurement


SOURCE = 'open-meteo-marine'

RETENTION = {
    'sea_level_height_msl':    30,
    'wave_height':             14,
    'wave_direction':          14,
    'wave_period':             14,
    'sea_surface_temperature': 60,
    'ocean_current_velocity':  14,
    'ocean_current_direction': 14,
}


def _upsert(samples):
    new = 0
    for s in samples:
        _, c = Measurement.objects.update_or_create(
            source=SOURCE, metric=s['metric'], at=s['at'],
            defaults={'value': s['value'], 'unit': s['unit']},
        )
        if c:
            new += 1
    return new, len(samples)


def _prune():
    total = 0
    for metric, days in RETENTION.items():
        cutoff = djtz.now() - dt.timedelta(days=days)
        total += Measurement.objects.filter(
            source=SOURCE, metric=metric, at__lt=cutoff,
        ).delete()[0]
    return total


class Command(BaseCommand):
    help = 'Pull marine forecast (tide / waves / temp / currents).'

    def add_arguments(self, parser):
        parser.add_argument('--no-prune', action='store_true')

    @transaction.atomic
    def handle(self, *args, **opts):
        prefs = ClockPrefs.load()
        try:
            samples = fetch_marine(prefs.coast_lat, prefs.coast_lon)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(
                f'Open-Meteo marine fetch failed: {exc}'
            ))
            return

        new, seen = _upsert(samples)
        pruned = _prune() if not opts['no_prune'] else 0
        self.stdout.write(self.style.SUCCESS(
            f'Done. {seen} samples processed · {new} new rows · '
            f'{pruned} pruned · coast {prefs.coast_label}.'
        ))
