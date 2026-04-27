"""Pull air quality + UV + pollen for the observer location and store
as Measurements (source='open-meteo').

Open-Meteo returns 5 days × 24 h of data per call — past observations
plus a forecast strip — so a single fetch every 6 h keeps the
dashboard fresh and gives us a "next 24-48 h" outlook.

Idempotent re-runs (unique source/metric/at). Per-metric retention
prune included.

Usage:

    python manage.py refresh_local_environment
        Fetch all metrics for the configured ClockPrefs.home_lat/lon.

    python manage.py refresh_local_environment --no-prune
        Skip the retention prune (useful when backfilling).

    python manage.py refresh_local_environment --no-concerns
        Don't open/close Identity Concerns for threshold breaches.
"""

import datetime as dt

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone as djtz

from chronos.astro_sources.local_environment import (
    METRICS, fetch_air_quality,
)
from chronos.models import ClockPrefs, Measurement


SOURCE = 'open-meteo'

# (metric, retention_days). UV + pollen kept short because forecast
# rolls daily; pollutants kept longer for trend lines.
RETENTION = {
    'european_aqi':       60,
    'pm2_5':              60,
    'pm10':               60,
    'nitrogen_dioxide':   60,
    'ozone':              60,
    'sulphur_dioxide':    60,
    'carbon_monoxide':    60,
    'uv_index':           14,
    'uv_index_clear_sky': 14,
    'alder_pollen':       14,
    'birch_pollen':       14,
    'grass_pollen':       14,
    'mugwort_pollen':     14,
    'olive_pollen':       14,
    'ragweed_pollen':     14,
}


# Threshold (metric → (value cutoff, severity, name template, why).
# Severity is the Concern.severity scalar (0..1).
CONCERN_THRESHOLDS = {
    'european_aqi':     (60,  0.5, 'Air quality moderate-poor (EAQI {v:.0f})',
                         'European AQI in the moderate-or-worse band; '
                         'sensitive groups should consider limiting '
                         'prolonged outdoor exertion.'),
    'pm2_5':            (25,  0.5, 'PM2.5 above WHO daily ({v:.0f} µg/m³)',
                         'WHO 24-hour guideline for PM2.5 is 15 µg/m³; '
                         'sustained exposure above 25 raises cardiovascular '
                         'risk for sensitive groups.'),
    'ozone':            (180, 0.6, 'Ozone above EU info threshold ({v:.0f} µg/m³)',
                         'EU info threshold for O₃ (1-hour) is 180 µg/m³; '
                         'limit strenuous outdoor activity, especially for '
                         'children and asthmatics.'),
    'nitrogen_dioxide': (200, 0.6, 'NO₂ above EU 1-hour limit ({v:.0f} µg/m³)',
                         'EU 1-hour NO₂ limit is 200 µg/m³; typically only '
                         'reached near heavy traffic or industrial sources.'),
    'uv_index':         (7,   0.4, 'UV index high or higher ({v:.1f})',
                         'UV index ≥ 7 — burn time on unprotected fair skin '
                         'is under 30 minutes; use SPF and shade.'),
    'grass_pollen':     (50,  0.4, 'Grass pollen high ({v:.0f} grains/m³)',
                         'High grass-pollen reading; allergic individuals '
                         'should expect symptoms outdoors.'),
    'birch_pollen':     (50,  0.4, 'Birch pollen high ({v:.0f} grains/m³)',
                         'High birch-pollen reading.'),
    'ragweed_pollen':   (50,  0.5, 'Ragweed pollen high ({v:.0f} grains/m³)',
                         'High ragweed-pollen reading; cross-reactive with '
                         'mugwort and several food allergens.'),
}


def _upsert(samples):
    """Bulk upsert. Returns (total_new, total_seen)."""
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


def _sync_concerns(prefs):
    """Open/close Identity Concerns based on the most-recent past-or-now
    Measurement for each thresholded metric. Idempotent.

    Aspect format: 'env_threshold__<metric>'. Re-running won't open
    duplicate concerns; it'll update severity/description in place.
    """
    try:
        from identity.models import Concern
    except Exception:
        return (0, 0)

    now = djtz.now()
    opened = 0
    seen = set()

    for metric, (cutoff, sev, name_tmpl, why) in CONCERN_THRESHOLDS.items():
        latest = Measurement.objects.filter(
            source=SOURCE, metric=metric, at__lte=now,
        ).order_by('-at').first()
        if not latest:
            continue
        if latest.value < cutoff:
            continue
        aspect = f'env_threshold__{metric}'
        seen.add(aspect)
        existing = Concern.objects.filter(
            aspect=aspect, closed_at__isnull=True,
        ).first()
        name = name_tmpl.format(v=latest.value)
        description = (
            f'{why}\n\n'
            f'Latest value: {latest.value:.2f} {latest.unit} '
            f'at {latest.at:%Y-%m-%d %H:%M} UT\n'
            f'Source: Open-Meteo air-quality API for '
            f'{prefs.home_lat:.2f}°N {prefs.home_lon:.2f}°E.'
        )
        if existing:
            existing.severity = sev
            existing.name = name
            existing.description = description
            existing.save(update_fields=['severity', 'name', 'description'])
        else:
            Concern.objects.create(
                aspect=aspect, name=name,
                description=description, severity=sev,
            )
            opened += 1

    closed = 0
    stale_qs = Concern.objects.filter(
        aspect__startswith='env_threshold__', closed_at__isnull=True,
    ).exclude(aspect__in=seen)
    for c in stale_qs:
        c.close(reason='resolved',
                note='Reading fell back below the threshold.')
        closed += 1

    return (opened, closed)


class Command(BaseCommand):
    help = 'Pull local air quality / UV / pollen from Open-Meteo.'

    def add_arguments(self, parser):
        parser.add_argument('--no-prune',    action='store_true')
        parser.add_argument('--no-concerns', action='store_true')

    @transaction.atomic
    def handle(self, *args, **opts):
        prefs = ClockPrefs.load()
        try:
            samples = fetch_air_quality(prefs.home_lat, prefs.home_lon)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(
                f'Open-Meteo fetch failed: {exc}'
            ))
            return

        new, seen = _upsert(samples)
        pruned = _prune() if not opts['no_prune'] else 0
        opened, closed = (
            (0, 0) if opts['no_concerns'] else _sync_concerns(prefs)
        )

        self.stdout.write(self.style.SUCCESS(
            f'Done. {seen} samples processed · {new} new rows · '
            f'{pruned} pruned · '
            f'{opened} concerns opened, {closed} closed.'
        ))
