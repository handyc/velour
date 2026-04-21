"""Planetary clocks — Mars Coordinated Time, rover LMST, Venus solar time.

MTC (Airy Mean Time) follows Allison & McEwen 2000. LMST at a given
east longitude = MTC + λ/15 hours (mod 24). Rover mission sol counts
local solar days since landing. Venus has no consensus convention —
we report local solar time at 0° longitude.
"""

from datetime import datetime, timezone


J1970 = 2440587.5
J2000 = 2451545.0
MARS_EPOCH_MSD = 44796.0
MARS_SOL_IN_EARTH_DAYS = 1.02749125
MARS_CORRECTION = 0.00072

VENUS_SIDEREAL_DAY = 243.0226
VENUS_ORBITAL_YEAR = 224.70069
VENUS_SOLAR_DAY = 1.0 / (1.0 / VENUS_ORBITAL_YEAR + 1.0 / VENUS_SIDEREAL_DAY)


MARS_LANDMARKS = [
    {
        'key': 'mtc',
        'label': 'Mars',
        'tz_name': 'MTC · Airy Mean Time',
        'longitude_east': 0.0,
        'longitude_label': 'λ 0° Airy-0',
        'sol_mode': 'msd',
    },
    {
        'key': 'curiosity',
        'label': 'Mars · Gale Crater',
        'tz_name': 'Curiosity LMST',
        'longitude_east': 137.4417,
        'longitude_label': 'λ 137°E',
        'sol_mode': 'mission',
        # Sol 0 = landing day local at Gale (2012-08-06 UTC, MSD_local ~49269.6)
        'landing_msd_local': 49269,
    },
    {
        'key': 'perseverance',
        'label': 'Mars · Jezero Crater',
        'tz_name': 'Perseverance LMST',
        'longitude_east': 77.4500,
        'longitude_label': 'λ 77°E',
        'sol_mode': 'mission',
        # Sol 0 = landing day local at Jezero (2021-02-18 UTC, MSD_local ~52304.7)
        'landing_msd_local': 52304,
    },
]


def _julian_date_ut(dt_utc):
    return dt_utc.timestamp() / 86400.0 + J1970


def _julian_date_tt(dt_utc):
    return _julian_date_ut(dt_utc) + 69.184 / 86400.0


def _mars_msd(now_utc):
    jd_tt = _julian_date_tt(now_utc)
    return (jd_tt - 2451549.5) / MARS_SOL_IN_EARTH_DAYS + MARS_EPOCH_MSD - MARS_CORRECTION


def _lmst_snapshot(msd, landmark, now_utc):
    """Compute LMST at landmark's longitude and build a snapshot dict."""
    lon_offset = landmark['longitude_east'] / 360.0
    msd_local = msd + lon_offset
    local_sol_floor = int(msd_local) if msd_local >= 0 else int(msd_local) - 1
    frac = msd_local - local_sol_floor
    total_seconds = frac * 24 * 3600
    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    s = int(total_seconds % 60)
    if landmark['sol_mode'] == 'mission':
        sol = local_sol_floor - landmark['landing_msd_local']
        sol_str = f'Sol {sol}' if sol >= 0 else f'Pre-landing ({sol})'
    else:
        sol_str = f'MSD {local_sol_floor}'
    return {
        'key': landmark['key'],
        'label': landmark['label'],
        'tz_name': landmark['tz_name'],
        'date_str': sol_str,
        'time_str': f'{h:02d}:{m:02d}:{s:02d}',
        'utc_offset': landmark['longitude_label'],
        'epoch_ms': int(now_utc.timestamp() * 1000),
    }


def mars_snapshots(now_utc=None):
    """Return a list of Mars clocks: MTC + active rover LMST clocks."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    msd = _mars_msd(now_utc)
    return [_lmst_snapshot(msd, lm, now_utc) for lm in MARS_LANDMARKS]


def mars_snapshot(now_utc=None):
    """Backwards-compatible single-clock accessor (MTC only)."""
    return mars_snapshots(now_utc)[0]


def venus_snapshot(now_utc=None):
    """Return Venus local solar time at 0° longitude + solar-day number."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    days_since_j2000 = _julian_date_ut(now_utc) - J2000
    solar_days = days_since_j2000 / VENUS_SOLAR_DAY
    sol = int(solar_days) if solar_days >= 0 else int(solar_days) - 1
    frac = solar_days - sol
    total_seconds = frac * 24 * 3600
    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    s = int(total_seconds % 60)
    return {
        'key': 'venus',
        'label': 'Venus',
        'tz_name': 'VST · Venus Solar Time',
        'date_str': f'Sol {sol}',
        'time_str': f'{h:02d}:{m:02d}:{s:02d}',
        'utc_offset': 'λ 0° · retrograde',
        'epoch_ms': int(now_utc.timestamp() * 1000),
    }
