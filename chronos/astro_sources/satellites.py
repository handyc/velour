"""Satellite tracking — TLE fetch + visible-pass + live alt/az.

Satellites don't fit the seed-decades-in-advance pattern of the other
astro sources. TLEs (Two-Line Element sets) decay in accuracy after
roughly two weeks because of atmospheric drag and station-keeping
burns, so we re-fetch them on a schedule rather than once.

Data source: CelesTrak GP query (free, no auth, well-rate-limited).

This module exposes three things:

  * fetch_tle(catnr) -> {'name', 'line1', 'line2'} from CelesTrak
  * compute_passes(tle, lat, lon, ...) -> list of upcoming visible
    passes from an observer location, each with rise/culminate/set
    UTC datetimes plus max altitude and azimuth.
  * altaz_now(tle, lat, lon, ...) -> current (alt_deg, az_deg, dist_km)
    used by the live /chronos/sky/ view.

Everything calls into skyfield; we deliberately don't reimplement
SGP4. The de421 ephemeris isn't needed for SGP4 itself but IS needed
for the visible-pass illumination check (sat in sunlight + observer
in dark), so we reuse the existing _skyfield_loader cache.
"""

import datetime as dt
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ._skyfield_loader import get as _loader_get


CELESTRAK_GP = 'https://celestrak.org/NORAD/elements/gp.php'

# A few well-known satellites worth seeding by default. The CATNRs are
# stable across the satellite's operational life. Magnitudes are the
# typical maximum apparent brightness from a good pass, not exact.
SEED_SATELLITES = [
    {
        'name':        'ISS (ZARYA)',
        'slug':        'iss',
        'designation': '25544',
        'magnitude':   -3.5,
        'notes':       'International Space Station. Brightest artificial '
                       'object after the Sun and Moon — passes are obvious '
                       'naked-eye even from light-polluted city centres.',
    },
    {
        'name':        'HUBBLE SPACE TELESCOPE',
        'slug':        'hst',
        'designation': '20580',
        'magnitude':   2.0,
        'notes':       'Low orbit, ~28.5° inclination — only visible from '
                       'mid/low latitudes, never from poleward of ~50°. '
                       'Leiden (52° N) sees it rarely and low on the horizon.',
    },
    {
        'name':        'TIANGONG (CSS)',
        'slug':        'tiangong',
        'designation': '48274',
        'magnitude':   -1.0,
        'notes':       'Chinese Space Station — Tianhe core module. '
                       'Smaller than ISS but frequently visible from '
                       'mid-latitudes.',
    },
]


def _http_get(url, timeout=15):
    """Tiny HTTP GET — avoids pulling in `requests` for one call."""
    req = Request(url, headers={'User-Agent': 'velour-chronos/1.0'})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('ascii', errors='replace')


def fetch_tle(catnr):
    """Fetch the latest TLE for a NORAD catalog number from CelesTrak.

    Returns {'name', 'line1', 'line2', 'fetched_at'} or raises ValueError
    if the response doesn't contain a 3-line TLE.
    """
    url = f'{CELESTRAK_GP}?{urlencode({"CATNR": str(catnr), "FORMAT": "tle"})}'
    text = _http_get(url).strip()
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    if len(lines) < 3:
        raise ValueError(
            f'CelesTrak returned no TLE for CATNR={catnr}. '
            f'Response was: {text[:200]!r}'
        )
    return {
        'name':       lines[0].strip(),
        'line1':      lines[1],
        'line2':      lines[2],
        'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def _make_satellite(tle, ts):
    from skyfield.api import EarthSatellite
    return EarthSatellite(tle['line1'], tle['line2'],
                          tle.get('name', 'sat'), ts)


def _make_observer(lat, lon, elev_m):
    from skyfield.api import wgs84
    return wgs84.latlon(latitude_degrees=lat, longitude_degrees=lon,
                        elevation_m=elev_m)


def altaz_now(tle, lat, lon, elev_m=0.0):
    """Current alt/az/distance for a satellite from observer location.

    Returns (alt_deg, az_deg, distance_km) or None if skyfield isn't
    importable.
    """
    ts, _eph = _loader_get()
    if ts is None:
        return None
    sat = _make_satellite(tle, ts)
    observer = _make_observer(lat, lon, elev_m)
    t = ts.now()
    diff = (sat - observer).at(t)
    alt, az, distance = diff.altaz()
    return float(alt.degrees), float(az.degrees), float(distance.km)


def compute_passes(tle, lat, lon, elev_m=0.0,
                   days=14, min_alt_deg=10.0,
                   visible_only=True):
    """List upcoming passes of a satellite over the observer.

    A "pass" is a rise → culminate → set arc above the configured
    altitude horizon (default 10° to skip horizon clutter).

    With visible_only=True (the default) we keep only passes where, at
    culmination, the satellite is in sunlight AND the sun is below the
    civil-twilight threshold (-6°) at the observer. That's the
    naked-eye visibility condition. Set visible_only=False to also
    return daytime / shadowed passes (radio/scanner work).

    Returns a list of dicts:

        [{'rise': datetime, 'culminate': datetime, 'set': datetime,
          'max_alt_deg': float, 'culminate_az_deg': float,
          'visible': bool, 'duration_s': float}, ...]
    """
    ts, eph = _loader_get()
    if ts is None or eph is None:
        return []
    sat = _make_satellite(tle, ts)
    observer = _make_observer(lat, lon, elev_m)
    t0 = ts.now()
    t1 = ts.utc((t0.utc_datetime() + dt.timedelta(days=days)))
    times, kinds = sat.find_events(observer, t0, t1,
                                   altitude_degrees=min_alt_deg)

    sun = eph['sun']
    earth = eph['earth']

    passes = []
    cur = {}
    for t, kind in zip(times, kinds):
        when = t.utc_datetime()
        if kind == 0:
            cur = {'rise': when}
        elif kind == 1 and 'rise' in cur:
            cur['culminate'] = when
            alt, az, _d = (sat - observer).at(t).altaz()
            cur['max_alt_deg'] = float(alt.degrees)
            cur['culminate_az_deg'] = float(az.degrees)
            try:
                sat_sunlit = bool(sat.at(t).is_sunlit(eph))
            except Exception:
                sat_sunlit = True
            sun_alt = (earth + observer).at(t).observe(sun).apparent().altaz()[0].degrees
            cur['sat_sunlit'] = sat_sunlit
            cur['sun_alt_deg'] = float(sun_alt)
            cur['visible'] = sat_sunlit and sun_alt < -6.0
        elif kind == 2 and 'culminate' in cur:
            cur['set'] = when
            cur['duration_s'] = (cur['set'] - cur['rise']).total_seconds()
            if (not visible_only) or cur.get('visible'):
                passes.append(cur)
            cur = {}
    return passes


def altaz_track(tle, lat, lon, elev_m=0.0,
                minutes_back=10, minutes_ahead=10, step_seconds=30):
    """Sequence of (t_offset_s, alt_deg, az_deg) samples around now.

    Used by the sky dome to draw a fading past-trail and a brighter
    future-arc for each visible satellite, all in one round trip.
    Negative offsets are past; positive are future. Altitudes can be
    negative (below horizon) — the renderer can clip them.
    """
    ts, _eph = _loader_get()
    if ts is None:
        return []
    sat = _make_satellite(tle, ts)
    observer = _make_observer(lat, lon, elev_m)
    t0_dt = ts.now().utc_datetime()
    n_back = int(minutes_back * 60 / step_seconds)
    n_ahead = int(minutes_ahead * 60 / step_seconds)
    samples = []
    for i in range(-n_back, n_ahead + 1):
        when = t0_dt + dt.timedelta(seconds=i * step_seconds)
        t = ts.utc(when)
        alt, az, _d = (sat - observer).at(t).altaz()
        samples.append((i * step_seconds,
                        float(alt.degrees),
                        float(az.degrees)))
    return samples


def ground_track(tle, minutes=180, step_seconds=30):
    """Sub-satellite path for the upcoming `minutes` of orbit.

    Returns a list of (lat_deg, lon_deg, when_utc) tuples sampled at
    the requested step. Useful for drawing the ground track on a
    world map. Default span is ~2 orbits for a typical LEO satellite.
    """
    ts, _eph = _loader_get()
    if ts is None:
        return []
    sat = _make_satellite(tle, ts)
    t0 = ts.now()
    t0_dt = t0.utc_datetime()
    n_steps = int(minutes * 60 / step_seconds) + 1

    out = []
    for i in range(n_steps):
        when = t0_dt + dt.timedelta(seconds=i * step_seconds)
        t = ts.utc(when)
        sub = sat.at(t).subpoint()
        out.append((float(sub.latitude.degrees),
                    float(sub.longitude.degrees),
                    when))
    return out


def get(year):
    """Match the ASTRO_SOURCES protocol — but satellites don't seed
    yearly events. Return empty so seed_astronomy doesn't pull anything.
    The refresh_satellites command emits the live calendar entries.
    """
    return []
