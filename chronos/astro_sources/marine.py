"""Marine forecast — tide level, waves, water temperature, currents.

Open-Meteo Marine API (free, no auth, no key) returns 5 days of
hourly samples for any coastal point. For Velour-typical inland
observers, the configured ClockPrefs.coast_lat/lon points at the
nearest sensible coastal point (default Katwijk aan Zee for Leiden).

Same shape as the air-quality and weather fetchers — feeds the
chronos.Measurement table under source='open-meteo-marine'.

Tide extremes (high/low) are derived from the sea_level_height_msl
series by detecting local minima/maxima.
"""

import datetime as dt
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


OPEN_METEO_MARINE = 'https://marine-api.open-meteo.com/v1/marine'

HOURLY_METRICS = [
    ('sea_level_height_msl',     'm'),
    ('wave_height',              'm'),
    ('wave_direction',           '°'),
    ('wave_period',              's'),
    ('sea_surface_temperature',  '°C'),
    ('ocean_current_velocity',   'km/h'),
    ('ocean_current_direction',  '°'),
]


def _fetch_json(url, timeout=20):
    req = Request(url, headers={'User-Agent': 'velour-chronos/1.0'})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def fetch_marine(lat, lon, forecast_days=5, past_days=1):
    """Pull marine forecast for a coastal point.

    Returns a flat list of {metric, at, value, unit} dicts spanning
    `past_days + forecast_days` of hourly samples.
    """
    params = {
        'latitude':       f'{lat}',
        'longitude':      f'{lon}',
        'hourly':         ','.join(m for m, _ in HOURLY_METRICS),
        'timezone':       'auto',
        'forecast_days':  str(forecast_days),
        'past_days':      str(past_days),
    }
    data = _fetch_json(f'{OPEN_METEO_MARINE}?{urlencode(params)}')
    hourly = data.get('hourly') or {}
    times = hourly.get('time') or []
    if not times:
        return []
    tz_offset = data.get('utc_offset_seconds', 0)
    tz_offset_td = dt.timedelta(seconds=tz_offset)

    out = []
    for i, ts in enumerate(times):
        try:
            local = dt.datetime.fromisoformat(ts)
        except ValueError:
            continue
        utc_at = (local - tz_offset_td).replace(tzinfo=dt.timezone.utc)
        for metric, unit in HOURLY_METRICS:
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
                'metric': metric, 'at': utc_at,
                'value':  value,  'unit': unit,
            })
    return out


def detect_tide_extremes(samples_sorted_by_at):
    """Find high/low tide turning points in a sorted sea-level series.

    Input: list of (at, value) sorted by at, ideally hourly.
    Output: list of {'kind': 'high'|'low', 'at': datetime, 'value': m}.

    A point is a high tide if its value is greater than both
    neighbours; low tide if less than both. Edges are skipped because
    we can't classify them. With Open-Meteo's hourly cadence and a
    typical 12.4-hour tide period, we'll catch all four extremes per
    day.
    """
    out = []
    for i in range(1, len(samples_sorted_by_at) - 1):
        prev_v = samples_sorted_by_at[i - 1][1]
        cur_at, cur_v = samples_sorted_by_at[i]
        next_v = samples_sorted_by_at[i + 1][1]
        if cur_v > prev_v and cur_v > next_v:
            out.append({'kind': 'high', 'at': cur_at, 'value': cur_v})
        elif cur_v < prev_v and cur_v < next_v:
            out.append({'kind': 'low', 'at': cur_at, 'value': cur_v})
    return out


def get(year):
    return []
