"""Sun, Moon, and naked-eye planets — current alt/az from observer.

The dome stays evocative even when no satellites are passing because
the Sun, Moon, and bright planets are always somewhere — above or
below the horizon. This module is a thin wrapper around skyfield
that returns a snapshot of where everything is *right now* from the
configured home location.

Used by /chronos/sky.json so the same payload feeds the table and
the dome. Cheap enough to compute on every request (~5-10 ms for
seven bodies + Moon-phase math).
"""

import datetime as dt
import math

from ._skyfield_loader import get as _loader_get


# IAU/NASA naked-eye planets, plus Sun & Moon. Order is the rendering
# z-order on the dome (sun first so others draw over the corona).
NAKED_EYE = [
    ('sun',     'Sun',     'sun',                None),
    ('moon',    'Moon',    'moon',               None),
    ('mercury', 'Mercury', 'mercury',            None),
    ('venus',   'Venus',   'venus',              -4.6),
    ('mars',    'Mars',    'mars',                -2.9),
    ('jupiter', 'Jupiter', 'jupiter barycenter', -2.9),
    ('saturn',  'Saturn',  'saturn barycenter',  +0.5),
]


def _safe_eph_lookup(eph, key):
    """Some skyfield ephemeris kernels expose 'mercury' as 'mercury barycenter'.
    Try the requested key first, fall back to 'X barycenter'."""
    try:
        return eph[key]
    except KeyError:
        return eph[f'{key} barycenter']


def current_state(lat, lon, elev_m=0.0):
    """Snapshot of solar-system bodies relative to the observer.

    Returns a dict with:
      * 'computed_at': ISO timestamp of the underlying skyfield epoch.
      * 'sun': {'alt_deg', 'az_deg', 'distance_au'} — also sets a
               twilight band string ('day', 'civil', 'nautical',
               'astronomical', 'night') for the dome's background.
      * 'moon': {'alt_deg', 'az_deg', 'distance_km',
                 'phase_frac' (0=new, 0.5=full, 1=new),
                 'phase_name', 'illuminated_frac' (0..1),
                 'sun_az_relative_deg' (for shading).
      * 'planets': [{'slug','name','alt_deg','az_deg','magnitude',...}]
                   for naked-eye visible (mag ≤ 2) when above horizon,
                   below-horizon planets included with above_horizon=False.

    Returns None if skyfield/ephemeris isn't available (graceful degrade).
    """
    ts, eph = _loader_get()
    if ts is None or eph is None:
        return None
    from skyfield.api import wgs84
    from skyfield import almanac

    observer = wgs84.latlon(latitude_degrees=lat, longitude_degrees=lon,
                            elevation_m=elev_m)
    earth = eph['earth']
    obs = earth + observer
    t = ts.now()

    out = {'computed_at': t.utc_datetime().isoformat()}

    # Sun
    sun = eph['sun']
    sun_app = obs.at(t).observe(sun).apparent()
    sun_alt, sun_az, sun_dist = sun_app.altaz()
    sun_alt_deg = float(sun_alt.degrees)
    out['sun'] = {
        'alt_deg':     sun_alt_deg,
        'az_deg':      float(sun_az.degrees),
        'distance_au': float(sun_dist.au),
        'twilight':    _twilight_band(sun_alt_deg),
    }

    # Moon
    moon = eph['moon']
    moon_app = obs.at(t).observe(moon).apparent()
    moon_alt, moon_az, moon_dist = moon_app.altaz()

    # Phase: angular separation Sun–Moon as seen from Earth's centre.
    # 0° = new, 180° = full. Skyfield exposes almanac.fraction_illuminated.
    illum = float(almanac.fraction_illuminated(eph, 'moon', t))
    # Phase angle direction (waxing vs waning) — compare ecliptic
    # longitudes; a quick proxy is whether the Moon is east or west of
    # the Sun in apparent right ascension.
    sun_ra = sun_app.radec()[0].hours
    moon_ra = moon_app.radec()[0].hours
    delta = (moon_ra - sun_ra) % 24.0
    waxing = delta < 12.0
    if illum < 0.02:
        phase_name = 'new'
    elif illum > 0.98:
        phase_name = 'full'
    elif illum < 0.48:
        phase_name = 'waxing crescent' if waxing else 'waning crescent'
    elif illum < 0.52:
        phase_name = 'first quarter' if waxing else 'last quarter'
    else:
        phase_name = 'waxing gibbous' if waxing else 'waning gibbous'

    out['moon'] = {
        'alt_deg':           float(moon_alt.degrees),
        'az_deg':            float(moon_az.degrees),
        'distance_km':       float(moon_dist.km),
        'phase_frac':        delta / 24.0,
        'phase_name':        phase_name,
        'illuminated_frac':  illum,
        'sun_alt_deg':       sun_alt_deg,
        'sun_az_deg':        float(sun_az.degrees),
    }

    # Planets
    sun_xyz = obs.at(t).observe(sun).position.au  # earth→sun, BCRS au
    planets = []
    for slug, name, eph_key, default_mag in NAKED_EYE:
        if slug in ('sun', 'moon'):
            continue
        try:
            body = _safe_eph_lookup(eph, eph_key)
        except KeyError:
            continue
        astrom = obs.at(t).observe(body)
        app = astrom.apparent()
        alt, az, dist = app.altaz()
        row = {
            'slug':          slug,
            'name':          name,
            'alt_deg':       float(alt.degrees),
            'az_deg':        float(az.degrees),
            'distance_au':   float(dist.au),
            'magnitude':     default_mag,  # static estimate — fine for sizing
            'above_horizon': float(alt.degrees) > 0.0,
        }
        # Phase angle (Sun-Planet-Earth, measured at the planet) for the
        # inner planets. Mercury/Venus swing through full crescent–gibbous
        # cycles; Mars stays gibbous (≥84%) but the slight defect is still
        # visible. Outer planets stay essentially full from Earth, so we
        # skip them.
        if slug in ('mercury', 'venus', 'mars'):
            p_xyz = astrom.position.au  # earth→planet
            ps = [sun_xyz[i] - p_xyz[i] for i in range(3)]   # planet→sun
            pe = [-p_xyz[i] for i in range(3)]               # planet→earth
            ps_mag = math.sqrt(sum(x * x for x in ps))
            pe_mag = math.sqrt(sum(x * x for x in pe))
            if ps_mag > 0 and pe_mag > 0:
                cos_phase = sum(ps[i] * pe[i] for i in range(3)) \
                    / (ps_mag * pe_mag)
                cos_phase = max(-1.0, min(1.0, cos_phase))
                phase_angle = math.degrees(math.acos(cos_phase))
                row['phase_angle_deg'] = phase_angle
                row['illuminated_frac'] = (1.0 + cos_phase) / 2.0
        planets.append(row)
    out['planets'] = planets

    return out


def _twilight_band(sun_alt_deg):
    """Standard twilight bands, used by the dome to choose a sky tint.

    Day            ≥  0°
    Civil           0° to  -6°
    Nautical       -6° to -12°
    Astronomical  -12° to -18°
    Night          ≤ -18°
    """
    if sun_alt_deg >= 0:
        return 'day'
    if sun_alt_deg >= -6:
        return 'civil'
    if sun_alt_deg >= -12:
        return 'nautical'
    if sun_alt_deg >= -18:
        return 'astronomical'
    return 'night'


def get(year):
    """ASTRO_SOURCES protocol — solar-system positions are continuous,
    not yearly events. Equinoxes/solstices/eclipses already come from
    other modules; this one only feeds the live dome.
    """
    return []
