"""Moon phases — only Full Moon and New Moon, the visible and visible-by-absence
phases that humans actually plan around. Skip first/last quarter to keep the
calendar uncluttered."""

import datetime as dt

from ._skyfield_loader import get as _loader_get


_FULL_MOON_NAMES = {
    1:  'Wolf Moon',
    2:  'Snow Moon',
    3:  'Worm Moon',
    4:  'Pink Moon',
    5:  'Flower Moon',
    6:  'Strawberry Moon',
    7:  'Buck Moon',
    8:  'Sturgeon Moon',
    9:  'Harvest Moon',
    10: 'Hunter\'s Moon',
    11: 'Beaver Moon',
    12: 'Cold Moon',
}


def get(year):
    ts, eph = _loader_get()
    if ts is None:
        return []
    from skyfield import almanac
    t0 = ts.utc(year, 1, 1)
    t1 = ts.utc(year, 12, 31, 23, 59)
    times, phases = almanac.find_discrete(t0, t1, almanac.moon_phases(eph))
    out = []
    # almanac.MOON_PHASES = ['New Moon', 'First Quarter', 'Full Moon', 'Last Quarter']
    for t, p in zip(times, phases):
        if int(p) == 0:
            out.append((t.utc_datetime().date(), 'New Moon'))
        elif int(p) == 2:
            d = t.utc_datetime().date()
            traditional = _FULL_MOON_NAMES.get(d.month, '')
            label = f'Full Moon ({traditional})' if traditional else 'Full Moon'
            out.append((d, label))
    return out
