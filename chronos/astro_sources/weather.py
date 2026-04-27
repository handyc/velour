"""Weather forecast for the observer location — Open-Meteo.

Free, no auth, no key. Same shape as the air-quality fetcher.

Hourly metrics ingested into chronos.Measurement:
  temperature_2m, cloud_cover, precipitation, precipitation_probability,
  relative_humidity_2m, wind_speed_10m, wind_direction_10m, visibility,
  weather_code

Daily metrics:
  temperature_2m_max, temperature_2m_min, sunshine_duration_hours,
  precipitation_sum, uv_index_max, weather_code

Sunrise/sunset are stored as `extra` JSON on the daily weather_code
sample (one row per day) rather than as numeric metrics.
"""

import datetime as dt
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


OPEN_METEO_FORECAST = 'https://api.open-meteo.com/v1/forecast'

HOURLY_METRICS = [
    ('temperature_2m',            '°C'),
    ('cloud_cover',               '%'),
    ('precipitation',             'mm'),
    ('precipitation_probability', '%'),
    ('relative_humidity_2m',      '%'),
    ('wind_speed_10m',            'km/h'),
    ('wind_direction_10m',        '°'),
    ('visibility',                'm'),
    ('weather_code',              ''),
]

DAILY_METRICS = [
    ('temperature_2m_max',     '°C'),
    ('temperature_2m_min',     '°C'),
    ('sunshine_duration',      's'),
    ('precipitation_sum',      'mm'),
    ('uv_index_max',           ''),
    # Daily weather_code stored under a distinct metric name so it
    # doesn't mix with the hourly weather_code series in queries.
    ('weather_code_daily',     ''),
]


# WMO weather code lookup → (label, emoji).
# https://open-meteo.com/en/docs#weathervariables
WMO_CODES = {
    0:  ('Clear sky', '☀️'),
    1:  ('Mainly clear', '🌤'),
    2:  ('Partly cloudy', '⛅'),
    3:  ('Overcast', '☁️'),
    45: ('Fog', '🌫'),
    48: ('Rime fog', '🌫'),
    51: ('Light drizzle', '🌦'),
    53: ('Moderate drizzle', '🌦'),
    55: ('Dense drizzle', '🌦'),
    56: ('Light freezing drizzle', '🌨'),
    57: ('Dense freezing drizzle', '🌨'),
    61: ('Slight rain', '🌦'),
    63: ('Moderate rain', '🌧'),
    65: ('Heavy rain', '🌧'),
    66: ('Light freezing rain', '🌨'),
    67: ('Heavy freezing rain', '🌨'),
    71: ('Slight snow', '🌨'),
    73: ('Moderate snow', '🌨'),
    75: ('Heavy snow', '❄️'),
    77: ('Snow grains', '❄️'),
    80: ('Slight rain showers', '🌦'),
    81: ('Moderate rain showers', '🌧'),
    82: ('Violent rain showers', '⛈'),
    85: ('Slight snow showers', '🌨'),
    86: ('Heavy snow showers', '❄️'),
    95: ('Thunderstorm', '⛈'),
    96: ('Thunderstorm with slight hail', '⛈'),
    99: ('Thunderstorm with heavy hail', '⛈'),
}


def wmo_label(code):
    if code is None:
        return ('Unknown', '')
    code = int(code)
    return WMO_CODES.get(code, (f'WMO {code}', ''))


def _fetch_json(url, timeout=20):
    req = Request(url, headers={'User-Agent': 'velour-chronos/1.0'})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def fetch_weather(lat, lon, forecast_days=7, past_days=1):
    """Pull hourly + daily weather for the observer location.

    Returns dict with two keys:
      'hourly': flat list of {metric, at, value, unit}
      'daily':  flat list of {metric, at, value, unit, extra}
        where 'at' is the start of the local day in UTC and 'extra'
        on weather_code rows carries sunrise/sunset ISO strings.
    """
    # Map storage-metric → API field name for daily metrics. The
    # daily weather_code is stored as 'weather_code_daily' in our
    # Measurement table to keep it distinct from hourly weather_code,
    # but the API only knows 'weather_code'.
    daily_api_names = {
        'temperature_2m_max':  'temperature_2m_max',
        'temperature_2m_min':  'temperature_2m_min',
        'sunshine_duration':   'sunshine_duration',
        'precipitation_sum':   'precipitation_sum',
        'uv_index_max':        'uv_index_max',
        'weather_code_daily':  'weather_code',
    }
    params = {
        'latitude':  f'{lat}',
        'longitude': f'{lon}',
        'hourly':    ','.join(m for m, _ in HOURLY_METRICS),
        'daily':     ','.join(daily_api_names[m] for m, _ in DAILY_METRICS) + ',sunrise,sunset',
        'timezone':  'auto',
        'forecast_days': str(forecast_days),
        'past_days':     str(past_days),
    }
    data = _fetch_json(f'{OPEN_METEO_FORECAST}?{urlencode(params)}')
    tz_offset = data.get('utc_offset_seconds', 0)
    tz_offset_td = dt.timedelta(seconds=tz_offset)

    out_hourly = []
    hourly = data.get('hourly') or {}
    times = hourly.get('time') or []
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
            out_hourly.append({
                'metric': metric, 'at': utc_at,
                'value':  value,  'unit': unit,
            })

    out_daily = []
    daily = data.get('daily') or {}
    days = daily.get('time') or []
    sunrises = daily.get('sunrise') or []
    sunsets = daily.get('sunset') or []
    for i, day_str in enumerate(days):
        try:
            d = dt.datetime.fromisoformat(day_str)
        except ValueError:
            continue
        utc_day = (d - tz_offset_td).replace(tzinfo=dt.timezone.utc)
        for metric, unit in DAILY_METRICS:
            api_name = daily_api_names.get(metric, metric)
            series = daily.get(api_name)
            if not series or i >= len(series):
                continue
            value = series[i]
            if value is None:
                continue
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            extra = {}
            if metric == 'weather_code_daily' and i < len(sunrises) and i < len(sunsets):
                extra = {
                    'sunrise_local': sunrises[i],
                    'sunset_local':  sunsets[i],
                    'date_local':    day_str,
                }
            out_daily.append({
                'metric': metric, 'at': utc_day,
                'value':  value,  'unit': unit,
                'extra':  extra,
            })

    return {'hourly': out_hourly, 'daily': out_daily}


def get(year):
    return []
