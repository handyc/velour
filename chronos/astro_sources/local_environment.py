"""Local environment — air quality, UV, pollen for the observer location.

Single Open-Meteo air-quality endpoint covers everything we want:
PM10/PM2.5/NO₂/SO₂/O₃/CO + European AQI + UV index + 6 pollen species
(alder, birch, grass, mugwort, olive, ragweed). 120 hourly rows
returned per call (5-day forecast window). No auth, no key, free.

Same time-series substrate as space_weather: rows go into
chronos.Measurement with source='open-meteo'. Past-only or future-
inclusive ingest is selectable — past-only for the dashboard,
future-inclusive when we want a forecast strip.
"""

import datetime as dt
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


OPEN_METEO_AQ = 'https://air-quality-api.open-meteo.com/v1/air-quality'

# Metric → unit. Order matters for the dashboard card ordering
# (most-actionable first: AQI, ozone in pollen season, then UV).
METRICS = [
    ('european_aqi',      ''),       # 0-100 scale, lower=better
    ('pm2_5',             'µg/m³'),
    ('pm10',              'µg/m³'),
    ('nitrogen_dioxide',  'µg/m³'),
    ('ozone',             'µg/m³'),
    ('sulphur_dioxide',   'µg/m³'),
    ('carbon_monoxide',   'µg/m³'),
    ('uv_index',          ''),
    ('uv_index_clear_sky', ''),
    ('alder_pollen',      'grains/m³'),
    ('birch_pollen',      'grains/m³'),
    ('grass_pollen',      'grains/m³'),
    ('mugwort_pollen',    'grains/m³'),
    ('olive_pollen',      'grains/m³'),
    ('ragweed_pollen',    'grains/m³'),
]


def _fetch_json(url, timeout=20):
    req = Request(url, headers={'User-Agent': 'velour-chronos/1.0'})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def fetch_air_quality(lat, lon, timezone='auto', forecast_days=5):
    """Pull the 5-day hourly air-quality + UV + pollen series for the
    observer location.

    Returns a flat list of dicts:

        [{'metric':'pm2_5', 'at': datetime(UTC), 'value': 9.4,
          'unit': 'µg/m³'}, ...]

    Times in the API response are in the requested timezone but
    naive — we convert to UTC so Measurement.at stores aware UTC.
    """
    params = {
        'latitude':       f'{lat}',
        'longitude':      f'{lon}',
        'hourly':         ','.join(m for m, _ in METRICS),
        'timezone':       timezone,
        'forecast_days':  str(forecast_days),
    }
    data = _fetch_json(f'{OPEN_METEO_AQ}?{urlencode(params)}')
    hourly = data.get('hourly') or {}
    times = hourly.get('time') or []
    if not times:
        return []
    tz_offset = data.get('utc_offset_seconds', 0)
    tz_offset_td = dt.timedelta(seconds=tz_offset)

    out = []
    metric_units = {m: u for m, u in METRICS}
    for i, ts in enumerate(times):
        try:
            local = dt.datetime.fromisoformat(ts)
        except ValueError:
            continue
        # Local time (naive) → UTC aware
        utc_at = (local - tz_offset_td).replace(tzinfo=dt.timezone.utc)
        for metric, _unit in METRICS:
            series = hourly.get(metric)
            if not series or i >= len(series):
                continue
            value = series[i]
            if value is None:
                continue
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            out.append({
                'metric': metric,
                'at':     utc_at,
                'value':  value,
                'unit':   metric_units[metric],
            })
    return out


# --- Categorisation helpers (used by the dashboard) ---------------------


def european_aqi_band(value):
    """EEA's six-band classification.
    https://airindex.eea.europa.eu/Map/AQI/Viewer/
    """
    if value is None:
        return ''
    if value <= 20:  return 'very good'
    if value <= 40:  return 'good'
    if value <= 60:  return 'moderate'
    if value <= 80:  return 'poor'
    if value <= 100: return 'very poor'
    return 'extremely poor'


def uv_band(value):
    """WHO UV index bands."""
    if value is None:
        return ''
    if value < 3:   return 'low'
    if value < 6:   return 'moderate'
    if value < 8:   return 'high'
    if value < 11:  return 'very high'
    return 'extreme'


def pollen_band(grains):
    """Generic pollen levels (grains/m³). Species-specific thresholds
    differ slightly but this 4-band grouping is a reasonable proxy."""
    if grains is None or grains <= 0:
        return 'none'
    if grains < 10:    return 'low'
    if grains < 50:    return 'moderate'
    if grains < 200:   return 'high'
    return 'very high'


def get(year):
    """ASTRO_SOURCES protocol — local environment is continuous."""
    return []
