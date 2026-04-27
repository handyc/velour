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

# Tick rates: how fast a *local* second advances per real (SI) second.
#   Earth: 1.0 (definition).
#   Mars: 86400 / (88775.244 SI sec per sol) ≈ 0.97324  → MTC ticks ~3% slower.
#   Venus: 86400 / (~10_087_193 SI sec per Venus solar day) ≈ 0.00857
#          → VST ticks ~117× slower than Earth.
# Used by the home page's JS so each clock advances at the right rate
# from a single page-load snapshot, without per-second server polling.
MARS_TICK_RATE = 1.0 / MARS_SOL_IN_EARTH_DAYS
VENUS_TICK_RATE = 1.0 / VENUS_SOLAR_DAY


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
    {
        'key': 'insight',
        'label': 'Mars · Elysium Planitia',
        'tz_name': 'InSight LMST',
        'longitude_east': 135.623,
        'longitude_label': 'λ 136°E',
        'sol_mode': 'mission',
        # Sol 0 = landing day local at Elysium Planitia
        # (2018-11-26 19:52:59 UTC, MSD_local ~51511.6).
        # InSight's heat-flow / seismic mission ended 2022-12-21
        # but the LMST clock keeps ticking — the mission sol count
        # is a permanent timeline, not a status indicator.
        'landing_msd_local': 51511,
    },
    {
        'key': 'ingenuity',
        'label': 'Mars · Wright Brothers Field',
        'tz_name': 'Ingenuity Flight Sol',
        # Co-located with Perseverance at Jezero; the named "Wright
        # Brothers Field" is the takeoff site of Flight 1.
        'longitude_east': 77.4500,
        'longitude_label': 'λ 77°E',
        'sol_mode': 'mission',
        # Sol 0 = first powered flight on another planet
        # (2021-04-19 12:33 UTC, MSD_local ~52362.7). Ingenuity's
        # mission-sol count is conventionally the "Flight Sol"
        # numbering — independent of Perseverance's landing-sol clock
        # so the two run side-by-side at the same longitude.
        'landing_msd_local': 52362,
    },
    {
        'key': 'zhurong',
        'label': 'Mars · Utopia Planitia',
        'tz_name': 'Zhurong LMST',
        'longitude_east': 109.925,
        'longitude_label': 'λ 110°E',
        'sol_mode': 'mission',
        # Sol 0 = landing day local at Utopia Planitia
        # (2021-05-14 23:18 UTC, MSD_local ~52387.6). Zhurong went
        # into planned hibernation in May 2022 and didn't wake; like
        # InSight, the LMST clock continues regardless.
        'landing_msd_local': 52387,
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
    """Compute LMST at landmark's longitude and build a snapshot dict.

    Includes tick parameters so JS can advance the displayed clock
    between page loads at the correct (slower-than-Earth) rate.
    """
    lon_offset = landmark['longitude_east'] / 360.0
    msd_local = msd + lon_offset
    local_sol_floor = int(msd_local) if msd_local >= 0 else int(msd_local) - 1
    frac = msd_local - local_sol_floor
    total_seconds = frac * 24 * 3600
    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    s = int(total_seconds % 60)
    if landmark['sol_mode'] == 'mission':
        sol_offset = landmark['landing_msd_local']
        sol = local_sol_floor - sol_offset
        sol_prefix = 'Sol '
        sol_str = f'{sol_prefix}{sol}' if sol >= 0 else f'Pre-landing ({sol})'
    else:
        sol_offset = 0
        sol_prefix = 'MSD '
        sol_str = f'{sol_prefix}{local_sol_floor}'
    return {
        'key': landmark['key'],
        'label': landmark['label'],
        'tz_name': landmark['tz_name'],
        'date_str': sol_str,
        'time_str': f'{h:02d}:{m:02d}:{s:02d}',
        'utc_offset': landmark['longitude_label'],
        'epoch_ms': int(now_utc.timestamp() * 1000),
        # JS-tick parameters
        'kind': 'planet',
        'tick_rate': MARS_TICK_RATE,
        'sol_at_epoch': local_sol_floor,
        'second_at_epoch': total_seconds,
        'sol_prefix': sol_prefix,
        'sol_offset': sol_offset,
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
        # JS-tick parameters — Venus seconds are ~117× slower than Earth's,
        # so this clock will visibly tick once every ~1.95 minutes of real time.
        'kind': 'planet',
        'tick_rate': VENUS_TICK_RATE,
        'sol_at_epoch': sol,
        'second_at_epoch': total_seconds,
        'sol_prefix': 'Sol ',
        'sol_offset': 0,
    }
