"""Solar and lunar eclipses for a given year via skyfield.

Eclipse detection is computed by checking when the Sun, Moon, and
Earth are aligned within the appropriate angular tolerance.
Skyfield doesn't ship a built-in eclipse predicate, so we use a
simple algorithm: walk the year sampling the Moon's ecliptic
latitude near each new and full moon, and report events where
the latitude is small enough to suggest an eclipse.
"""

import datetime as dt

from ._skyfield_loader import get as _loader_get


def get(year):
    ts, eph = _loader_get()
    if ts is None:
        return []

    from skyfield import almanac
    from skyfield.api import wgs84

    earth = eph['earth']
    moon = eph['moon']
    sun = eph['sun']

    t0 = ts.utc(year, 1, 1)
    t1 = ts.utc(year + 1, 1, 1)

    # Find new moons and full moons; eclipses can only happen at these times.
    times, phases = almanac.find_discrete(t0, t1, almanac.moon_phases(eph))

    out = []
    for t, p in zip(times, phases):
        # New moon = potential solar eclipse; full moon = potential lunar eclipse
        ph = int(p)
        if ph not in (0, 2):
            continue
        # Compute the angular separation between the Moon and the Sun
        # as seen from the Earth's geocenter. For an eclipse the
        # separation is very small (or 180° for lunar).
        e = earth.at(t)
        m = e.observe(moon).apparent()
        s = e.observe(sun).apparent()
        sep_deg = m.separation_from(s).degrees
        if ph == 0:  # new moon → solar eclipse if sep < ~1.5°
            if sep_deg < 1.5:
                out.append((t.utc_datetime().date(),
                            f'Solar eclipse ({sep_deg:.2f}° separation)'))
        else:  # full moon → lunar eclipse if sep > 178.5°
            if sep_deg > 178.5:
                out.append((t.utc_datetime().date(),
                            f'Lunar eclipse ({180 - sep_deg:.2f}° from anti-solar)'))
    return out
