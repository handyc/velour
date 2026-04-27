"""Space weather — solar + geomagnetic activity from NOAA SWPC.

Five public, no-auth JSON endpoints:

  * Kp index (3-hour planetary geomagnetic) — products/noaa-planetary-k-index
  * Solar wind plasma (DSCOVR) — products/solar-wind/plasma-1-day
  * GOES X-ray flux (1-min, 0.1-0.8nm primary band) — json/goes/...
  * Sunspot number (monthly, observed since 1749) — json/solar-cycle/...
  * Ovation aurora oval (gridded probability map) — json/ovation_aurora_latest

Normalised into chronos.Measurement rows with source='noaa-swpc'.

The aurora oval is too large to dump every 1°×1° cell; we summarise
it down to the equatorward boundary latitude per longitude band, which
is what an observer actually wants ("can I see aurora from 52° N?").
"""

import datetime as dt
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SWPC = 'https://services.swpc.noaa.gov'

ENDPOINTS = {
    'kp':       f'{SWPC}/products/noaa-planetary-k-index.json',
    'wind':     f'{SWPC}/products/solar-wind/plasma-1-day.json',
    'mag':      f'{SWPC}/products/solar-wind/mag-1-day.json',
    'xray':     f'{SWPC}/json/goes/primary/xrays-6-hour.json',
    'sunspots': f'{SWPC}/json/solar-cycle/observed-solar-cycle-indices.json',
    'aurora':   f'{SWPC}/json/ovation_aurora_latest.json',
}


def _fetch_json(url, timeout=20):
    req = Request(url, headers={'User-Agent': 'velour-chronos/1.0'})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def _parse_iso_utc(s):
    """SWPC uses several ISO-ish formats. Tolerate them all."""
    s = s.replace('Z', '').replace('T', ' ').strip()
    # Common: '2026-04-26 10:06:00.000'  |  '2026-04-20 00:00:00'
    # Sunspot uses 'YYYY-MM' which we treat as the 1st of that month UTC.
    if len(s) == 7 and s[4] == '-':
        return dt.datetime.fromisoformat(s + '-01').replace(
            tzinfo=dt.timezone.utc,
        )
    return dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc)


# --- Per-endpoint fetchers ----------------------------------------------


def fetch_kp(hours_back=72):
    """NOAA planetary Kp index, 3-hour cadence.

    Returns list of dicts {at, value, station_count}.
    """
    data = _fetch_json(ENDPOINTS['kp'])
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_back)
    out = []
    for row in data:
        try:
            at = _parse_iso_utc(row['time_tag'])
            if at < cutoff:
                continue
            out.append({
                'at':    at,
                'value': float(row['Kp']),
                'extra': {
                    'a_running':     row.get('a_running'),
                    'station_count': row.get('station_count'),
                },
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out


def fetch_solar_wind(hours_back=24):
    """DSCOVR solar wind plasma — speed, density, temperature.

    1-minute cadence. We sub-sample to every 15 minutes to keep the
    Measurement table from blowing up — ~96 rows/day is enough for
    sparklines.

    Returns dict with three lists keyed 'speed', 'density', 'temperature'.
    """
    data = _fetch_json(ENDPOINTS['wind'])
    if not data or not isinstance(data, list) or len(data) < 2:
        return {'speed': [], 'density': [], 'temperature': []}
    header = data[0]  # ['time_tag','density','speed','temperature']
    idx_t  = header.index('time_tag')
    idx_d  = header.index('density')
    idx_s  = header.index('speed')
    idx_T  = header.index('temperature')

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_back)
    speed = []
    density = []
    temperature = []
    last_at = None
    for row in data[1:]:
        try:
            at = _parse_iso_utc(row[idx_t])
            if at < cutoff:
                continue
            if last_at and (at - last_at).total_seconds() < 14 * 60:
                continue
            last_at = at
            speed.append({'at': at, 'value': float(row[idx_s])})
            density.append({'at': at, 'value': float(row[idx_d])})
            temperature.append({'at': at, 'value': float(row[idx_T])})
        except (ValueError, TypeError, IndexError):
            continue
    return {'speed': speed, 'density': density, 'temperature': temperature}


def fetch_xray(hours_back=6):
    """GOES X-ray flux, 0.1-0.8 nm primary band, 1-minute cadence.

    Sub-sampled to every 5 minutes. Flux is logarithmic — store raw
    W/m² but the page can render the standard A/B/C/M/X classification.

    Returns list of dicts {at, value (flux W/m²), satellite}.
    """
    data = _fetch_json(ENDPOINTS['xray'])
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_back)
    out = []
    last_at = None
    for row in data:
        try:
            energy = row.get('energy', '')
            if '0.1-0.8nm' not in energy and energy != '0.1-0.8nm':
                continue
            at = _parse_iso_utc(row['time_tag'])
            if at < cutoff:
                continue
            if last_at and (at - last_at).total_seconds() < 4.5 * 60:
                continue
            last_at = at
            flux = float(row.get('observed_flux') or row.get('flux'))
            out.append({
                'at':    at,
                'value': flux,
                'extra': {'satellite': row.get('satellite')},
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out


def xray_class(flux_w_m2):
    """Standard A/B/C/M/X letter grade for a GOES flux value."""
    if flux_w_m2 is None or flux_w_m2 <= 0:
        return ''
    if flux_w_m2 < 1e-7:
        letter, scale = 'A', 1e-8
    elif flux_w_m2 < 1e-6:
        letter, scale = 'B', 1e-7
    elif flux_w_m2 < 1e-5:
        letter, scale = 'C', 1e-6
    elif flux_w_m2 < 1e-4:
        letter, scale = 'M', 1e-5
    else:
        letter, scale = 'X', 1e-4
    return f'{letter}{flux_w_m2 / scale:.1f}'


def fetch_sunspots(months_back=24):
    """Monthly observed sunspot number (SILSO via SWPC).

    Returns list of dicts {at, value (smoothed_ssn or ssn), f10_7}.
    """
    data = _fetch_json(ENDPOINTS['sunspots'])
    if not isinstance(data, list):
        return []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=months_back * 31)
    out = []
    for row in data:
        try:
            tag = row.get('time-tag') or row.get('time_tag')
            if not tag:
                continue
            at = _parse_iso_utc(tag)
            if at < cutoff:
                continue
            ssn = row.get('ssn')
            if ssn is None or ssn < 0:
                continue
            out.append({
                'at':    at,
                'value': float(ssn),
                'extra': {
                    'smoothed_ssn': row.get('smoothed_ssn'),
                    'f10_7':        row.get('f10.7'),
                },
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out


def fetch_aurora_oval():
    """Ovation aurora oval — gridded aurora probability over the globe.

    Reduces the 1°×1° grid to per-longitude equatorward boundaries:
    for each longitude band (every 30°), find the most equatorward
    latitude (north) where intensity > 5%. That's the practical
    "where does the aurora oval reach down to" answer for an observer.

    Returns dict:
        {'observation_time': iso,
         'forecast_time': iso,
         'north_boundary_by_lon': {lon: lat},
         'south_boundary_by_lon': {lon: lat},
         'max_intensity': float}
    """
    raw = _fetch_json(ENDPOINTS['aurora'])
    coords = raw.get('coordinates') or []
    THRESH = 5  # % chance of visible aurora
    LON_BANDS = list(range(-180, 181, 30))

    def _band(lon):
        return min(LON_BANDS, key=lambda b: abs(((lon - b + 540) % 360) - 180))

    north = {b: None for b in LON_BANDS}  # most equatorward N-hemisphere
    south = {b: None for b in LON_BANDS}  # most equatorward S-hemisphere
    max_intensity = 0
    for lon, lat, intensity in coords:
        if intensity > max_intensity:
            max_intensity = intensity
        if intensity < THRESH:
            continue
        b = _band(lon)
        if lat > 0:
            cur = north[b]
            if cur is None or lat < cur:
                north[b] = lat
        else:
            cur = south[b]
            if cur is None or lat > cur:
                south[b] = lat

    return {
        'observation_time': raw.get('Observation Time'),
        'forecast_time':    raw.get('Forecast Time'),
        'north_boundary_by_lon': north,
        'south_boundary_by_lon': south,
        'max_intensity': max_intensity,
    }


def aurora_visible_at(observer_lat, oval_summary, slack_deg=2.0):
    """True if the Ovation oval reaches down to (or past) the observer's
    latitude in any longitude band. `slack_deg` adds a small buffer
    because aurora can be seen on the *southward* horizon from a few
    degrees south of the formal oval boundary.
    """
    if observer_lat >= 0:
        boundaries = oval_summary.get('north_boundary_by_lon', {})
        for lat in boundaries.values():
            if lat is not None and lat - slack_deg <= observer_lat:
                return True
    else:
        boundaries = oval_summary.get('south_boundary_by_lon', {})
        for lat in boundaries.values():
            if lat is not None and lat + slack_deg >= observer_lat:
                return True
    return False


def get(year):
    """ASTRO_SOURCES protocol — space weather is continuous, not yearly."""
    return []
