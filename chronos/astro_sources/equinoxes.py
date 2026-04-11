"""Equinoxes and solstices for a Gregorian year via skyfield."""

from ._skyfield_loader import get as _load_eph


_NAMES = {
    0: 'Vernal Equinox',
    1: 'Summer Solstice',
    2: 'Autumnal Equinox',
    3: 'Winter Solstice',
}


def get(year):
    ts, eph = _load_eph()
    if ts is None:
        return []
    from skyfield import almanac
    t0 = ts.utc(year, 1, 1)
    t1 = ts.utc(year, 12, 31, 23, 59)
    times, events = almanac.find_discrete(t0, t1, almanac.seasons(eph))
    return [
        (t.utc_datetime().date(), _NAMES.get(int(e), 'Season'))
        for t, e in zip(times, events)
    ]
