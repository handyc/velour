"""Planetary clocks — Mars Coordinated Time and Venus solar time.

MTC (Airy Mean Time) follows Allison & McEwen 2000, used for
rover/lander mission clocks. Venus has no consensus convention —
we report local solar time at 0° longitude given that Venus's
mean solar day is ~116.75 Earth days (retrograde rotation).
"""

from datetime import datetime, timezone


J1970 = 2440587.5            # Julian Date of 1970-01-01 00:00 UT
J2000 = 2451545.0            # Julian Date of 2000-01-01 12:00 TT
MARS_EPOCH_MSD = 44796.0     # MSD at 1873-12-29 12:00 UT (Allison)
MARS_SOL_IN_EARTH_DAYS = 1.02749125
MARS_CORRECTION = 0.00072    # MSD epoch fine-tune (Allison & McEwen)

VENUS_SIDEREAL_DAY = 243.0226   # Earth days, retrograde
VENUS_ORBITAL_YEAR = 224.70069  # Earth days
# 1/solar_day = 1/orbital + 1/sidereal (retrograde gives + sign)
VENUS_SOLAR_DAY = 1.0 / (1.0 / VENUS_ORBITAL_YEAR + 1.0 / VENUS_SIDEREAL_DAY)


def _julian_date_ut(dt_utc):
    return dt_utc.timestamp() / 86400.0 + J1970


def _julian_date_tt(dt_utc):
    # TT ≈ UTC + 69.184 s (constant for ~2020s-2030s, within seconds)
    return _julian_date_ut(dt_utc) + 69.184 / 86400.0


def mars_snapshot(now_utc=None):
    """Return Mars Coordinated Time + sol number."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    jd_tt = _julian_date_tt(now_utc)
    msd = (jd_tt - 2451549.5) / MARS_SOL_IN_EARTH_DAYS + MARS_EPOCH_MSD - MARS_CORRECTION
    sol = int(msd)
    frac = msd - sol
    total_seconds = frac * 24 * 3600
    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    s = int(total_seconds % 60)
    return {
        'tz_name': 'MTC (Airy Mean Time)',
        'label': 'Mars',
        'date_str': f'Sol {sol}',
        'time_str': f'{h:02d}:{m:02d}:{s:02d}',
        'utc_offset': '',
        'epoch_ms': int(now_utc.timestamp() * 1000),
        'note': 'Mars Coordinated Time — prime meridian at Airy-0 crater',
    }


def venus_snapshot(now_utc=None):
    """Return Venus local solar time at 0° longitude + solar-day number.

    Epoch is J2000; sol counts Venus mean solar days since then.
    Venus rotates retrograde, so from the surface the sun rises in
    the west and a full solar day is ~117 Earth days.
    """
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
        'tz_name': 'VST (Venus Solar Time, 0° long)',
        'label': 'Venus',
        'date_str': f'Sol {sol}',
        'time_str': f'{h:02d}:{m:02d}:{s:02d}',
        'utc_offset': '',
        'epoch_ms': int(now_utc.timestamp() * 1000),
        'note': '1 Venus solar day ≈ 116.75 Earth days, retrograde rotation',
    }
