"""Near-Earth Object close approaches — JPL CNEOS feed.

NEOs (asteroids and comets that come close to Earth) are interesting at
the moment of close approach, not as live alt/az targets. JPL CNEOS
publishes the predicted close-approach catalog as a clean JSON feed,
so we can drop the entire ephemeris-computation question and just
ingest predictions.

Data source: JPL Center for NEO Studies Close Approach API
    https://ssd-api.jpl.nasa.gov/cad.api

Distance is reported in AU. We convert to lunar distances (LD) for
display because human intuition is calibrated to "Moon = 1 LD". H
(absolute magnitude) is converted to a rough diameter estimate using
the standard 0.14-albedo assumption — useful for "is this rock pebble-
sized or building-sized".
"""

import datetime as dt
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


CNEOS_URL = 'https://ssd-api.jpl.nasa.gov/cad.api'

AU_KM = 149_597_870.7
LD_KM = 384_400.0
LD_AU = LD_KM / AU_KM  # ≈ 0.00257


def _http_get_json(url, timeout=20):
    req = Request(url, headers={'User-Agent': 'velour-chronos/1.0'})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _parse_cd(cd):
    """JPL CNEOS calendar dates look like '2026-Apr-28 07:27' — UTC.

    Returns a timezone-aware UTC datetime. Returns None if unparseable.
    """
    try:
        return dt.datetime.strptime(cd, '%Y-%b-%d %H:%M').replace(
            tzinfo=dt.timezone.utc,
        )
    except ValueError:
        try:
            return dt.datetime.strptime(cd, '%Y-%b-%d').replace(
                tzinfo=dt.timezone.utc,
            )
        except ValueError:
            return None


def diameter_km_from_h(h, albedo=0.14):
    """Standard NEO size estimate from absolute magnitude.

    D(km) = 1329 / sqrt(albedo) * 10^(-0.2 * H)

    Default albedo of 0.14 is the IAU survey-average for a mixed
    C/S-type population. Real diameters can vary 2-3x either way for
    a given H without direct radar/thermal observation.
    """
    if h is None:
        return None
    try:
        h = float(h)
    except (TypeError, ValueError):
        return None
    import math
    return 1329.0 / math.sqrt(albedo) * (10 ** (-0.2 * h))


def fetch_close_approaches(date_min='now', date_max='+60',
                           dist_max='10LD', kind=None,
                           include_sentry=False):
    """Fetch upcoming close approaches from JPL CNEOS.

    Args:
        date_min: 'now', 'YYYY-MM-DD', or '-N' (days back).
        date_max: '+N' (days forward), or 'YYYY-MM-DD'.
        dist_max: distance threshold — '10LD' for lunar-distances or
            a bare AU number string (e.g. '0.05').
        kind: None (default — asteroids), 'a' (asteroids only),
            'c' (comets only), 'an' (numbered asteroids only).
        include_sentry: if True, set the `sentry` flag — only objects
            on JPL's Sentry impact-monitoring list.

    Returns a list of dicts:

        [{'designation': '2026 HW',
          'when_utc': datetime(2026, 4, 28, 7, 27, tzinfo=UTC),
          'dist_au': 0.02451,
          'dist_ld': 9.55,
          'dist_min_ld': 9.46, 'dist_max_ld': 9.64,
          'v_rel_km_s': 11.78,
          'h': 25.03,
          'diameter_km_est': 0.0299,
          'time_uncertainty': '< 00:01'}, ...]
    """
    params = {
        'date-min': date_min,
        'date-max': date_max,
        'dist-max': dist_max,
        'sort':     'date',
    }
    if kind:
        params['kind'] = kind
    if include_sentry:
        params['sentry'] = 'true'

    url = f'{CNEOS_URL}?{urlencode(params)}'
    data = _http_get_json(url)
    fields = data.get('fields') or []
    rows = data.get('data') or []
    if not fields or not rows:
        return []

    idx = {name: i for i, name in enumerate(fields)}

    def fget(row, key, cast=float, default=None):
        i = idx.get(key)
        if i is None or i >= len(row) or row[i] in (None, ''):
            return default
        try:
            return cast(row[i])
        except (TypeError, ValueError):
            return default

    out = []
    for row in rows:
        cd = row[idx['cd']] if 'cd' in idx else None
        when = _parse_cd(cd) if cd else None
        if when is None:
            continue
        dist_au = fget(row, 'dist')
        dist_min = fget(row, 'dist_min')
        dist_max = fget(row, 'dist_max')
        h = fget(row, 'h')
        out.append({
            'designation':       row[idx['des']].strip(),
            'when_utc':          when,
            'dist_au':           dist_au,
            'dist_ld':           dist_au / LD_AU if dist_au else None,
            'dist_min_ld':       dist_min / LD_AU if dist_min else None,
            'dist_max_ld':       dist_max / LD_AU if dist_max else None,
            'v_rel_km_s':        fget(row, 'v_rel'),
            'h':                 h,
            'diameter_km_est':   diameter_km_from_h(h),
            'time_uncertainty':  row[idx['t_sigma_f']]
                                 if 't_sigma_f' in idx else '',
        })
    return out


def get(year):
    """ASTRO_SOURCES protocol — but NEOs aren't year-seedable; the
    feed only forecasts a few years out and the catalog grows daily.
    refresh_neos emits live entries instead.
    """
    return []
