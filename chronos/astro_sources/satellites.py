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


def find_transits(tle, lat, lon, elev_m=0.0, days=30,
                  appulse_max_deg=1.0, coarse_step_s=60,
                  fine_step_s=0.5):
    """Predict times when a satellite passes in front of (or very near)
    the Sun or Moon as seen from the observer.

    Algorithm:
      1. Coarse-scan the next `days` days at `coarse_step_s` resolution
         and compute the angular separation (sat ↔ body) at each step.
      2. Identify local minima where separation < `appulse_max_deg`.
      3. Around each local minimum, refine at `fine_step_s` resolution
         (typically 0.5-1 s) over a ±2-minute window to find the exact
         peak time and minimum separation.
      4. Classify each refined event:
            - 'transit'  : minimum < body angular radius (sat silhouette
                           crosses the disk)
            - 'appulse'  : minimum < appulse_max_deg but > body radius
                           (close approach, pretty in a wide-field shot)
      5. Filter out events when the body is below the observer's
         horizon (you can't see the sun if it's set).

    Returns a list of dicts:

        [{'body':'sun'|'moon',
          'kind':'transit'|'appulse',
          'peak_at':       datetime UTC of closest approach,
          'min_sep_deg':   float,
          'body_alt_deg':  float (alt of body at peak),
          'body_az_deg':   float,
          'sat_alt_deg':   float,
          'duration_s':    float (transit only — entry to exit),
         }, ...]

    Body angular radii used:
        Sun  ≈ 0.266° (varies ±1.7% with Earth's orbit)
        Moon ≈ 0.259° (varies ±5% with lunar distance)
    """
    import numpy as np
    ts, eph = _loader_get()
    if ts is None or eph is None:
        return []
    sat = _make_satellite(tle, ts)
    observer = _make_observer(lat, lon, elev_m)

    n = int(days * 86400 / coarse_step_s)
    t0_dt = dt.datetime.now(dt.timezone.utc)
    times_dt = [t0_dt + dt.timedelta(seconds=i * coarse_step_s) for i in range(n)]
    times = ts.from_datetimes(times_dt)

    sat_alt, sat_az, _ = (sat - observer).at(times).altaz()
    sun_pos = (eph['earth'] + observer).at(times).observe(eph['sun']).apparent()
    sun_alt, sun_az, _ = sun_pos.altaz()
    moon_pos = (eph['earth'] + observer).at(times).observe(eph['moon']).apparent()
    moon_alt, moon_az, _ = moon_pos.altaz()

    results = []
    for body_name, b_alt, b_az in [
        ('sun',  sun_alt.degrees,  sun_az.degrees),
        ('moon', moon_alt.degrees, moon_az.degrees),
    ]:
        sep = _ang_sep_deg(sat_alt.degrees, sat_az.degrees, b_alt, b_az)
        # Coarse local minima below the appulse threshold.
        candidates = []
        for i in range(1, n - 1):
            if sep[i] < appulse_max_deg and sep[i] <= sep[i-1] and sep[i] <= sep[i+1]:
                candidates.append(i)

        for idx in candidates:
            window = 120  # seconds either side
            t_min_dt = times_dt[idx] - dt.timedelta(seconds=window)
            t_max_dt = times_dt[idx] + dt.timedelta(seconds=window)
            n_fine = int((2 * window) / fine_step_s) + 1
            fine_dts = [t_min_dt + dt.timedelta(seconds=k * fine_step_s)
                        for k in range(n_fine)]
            fine_t = ts.from_datetimes(fine_dts)
            sat_a, sat_z, _ = (sat - observer).at(fine_t).altaz()
            body = eph['sun'] if body_name == 'sun' else eph['moon']
            body_p = (eph['earth'] + observer).at(fine_t).observe(body).apparent()
            body_a, body_z, _ = body_p.altaz()
            seps_fine = _ang_sep_deg(sat_a.degrees, sat_z.degrees,
                                     body_a.degrees, body_z.degrees)

            min_i = int(seps_fine.argmin())
            min_sep = float(seps_fine[min_i])
            peak_at = fine_dts[min_i]
            body_alt_at_peak = float(body_a.degrees[min_i])
            body_az_at_peak = float(body_z.degrees[min_i])
            sat_alt_at_peak = float(sat_a.degrees[min_i])

            if body_alt_at_peak <= 0:
                continue  # body below horizon — invisible

            body_radius = 0.266 if body_name == 'sun' else 0.259
            kind = 'transit' if min_sep < body_radius else 'appulse'

            duration_s = 0.0
            if kind == 'transit':
                # Walk outward from peak until separation exceeds body
                # radius — that's entry/exit.
                left = min_i
                while left > 0 and seps_fine[left] < body_radius:
                    left -= 1
                right = min_i
                while right < n_fine - 1 and seps_fine[right] < body_radius:
                    right += 1
                duration_s = (right - left) * fine_step_s

            results.append({
                'body':         body_name,
                'kind':         kind,
                'peak_at':      peak_at,
                'min_sep_deg':  min_sep,
                'body_alt_deg': body_alt_at_peak,
                'body_az_deg':  body_az_at_peak,
                'sat_alt_deg':  sat_alt_at_peak,
                'duration_s':   duration_s,
            })

    results.sort(key=lambda r: r['peak_at'])
    return results


def _ang_sep_deg(alt1, az1, alt2, az2):
    """Angular separation (great-circle) between two alt/az points
    on the celestial hemisphere, in degrees. Inputs are numpy arrays
    or scalars."""
    import numpy as np
    a1 = np.radians(alt1); z1 = np.radians(az1)
    a2 = np.radians(alt2); z2 = np.radians(az2)
    cos_d = (np.sin(a1) * np.sin(a2)
             + np.cos(a1) * np.cos(a2) * np.cos(z1 - z2))
    return np.degrees(np.arccos(np.clip(cos_d, -1, 1)))


def get(year):
    """Match the ASTRO_SOURCES protocol — but satellites don't seed
    yearly events. Return empty so seed_astronomy doesn't pull anything.
    The refresh_satellites command emits the live calendar entries.
    """
    return []
