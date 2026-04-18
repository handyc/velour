"""Planetary conjunctions — when two naked-eye planets appear close
together in the sky as seen from Earth's geocenter.

Conjunction threshold is 3 degrees of apparent angular separation, a
commonly-used popular-astronomy cutoff (naked-eye observers see two
planets in the same low-power telescope field at that distance).

We scan every four days for each planet pair, and record the local
minimum of angular separation when it drops below the threshold.
This catches the short, few-day-wide conjunction windows without the
cost of a daily scan.

Naked-eye pairs covered: Mercury, Venus, Mars, Jupiter, Saturn — ten
unique pairs. Uranus and Neptune are skipped: both are too faint to
be "appearing close in the sky" in the popular sense, and conjunctions
involving them are of interest only to specialists.
"""

import datetime as dt

from ._skyfield_loader import get as _loader_get


_PAIRS = [
    ('mercury', 'venus'),
    ('mercury', 'mars'),
    ('mercury', 'jupiter barycenter'),
    ('mercury', 'saturn barycenter'),
    ('venus',   'mars'),
    ('venus',   'jupiter barycenter'),
    ('venus',   'saturn barycenter'),
    ('mars',    'jupiter barycenter'),
    ('mars',    'saturn barycenter'),
    ('jupiter barycenter', 'saturn barycenter'),
]

_PRETTY = {
    'mercury': 'Mercury',
    'venus': 'Venus',
    'mars': 'Mars',
    'jupiter barycenter': 'Jupiter',
    'saturn barycenter': 'Saturn',
}

_THRESHOLD_DEG = 3.0
_STEP_DAYS = 4


def get(year):
    ts, eph = _loader_get()
    if ts is None:
        return []

    earth = eph['earth']
    bodies = {key: eph[key] for key in _PRETTY}

    # Sample the year on a coarse grid for each pair, then refine local
    # minima to nearest day. Keep only minima below the threshold.
    year_start = dt.date(year, 1, 1)
    year_end = dt.date(year, 12, 31)
    total_days = (year_end - year_start).days + 1

    out = []
    seen_keys = set()

    for a_key, b_key in _PAIRS:
        a_body = bodies[a_key]
        b_body = bodies[b_key]

        # Coarse scan
        seps = []
        for offset in range(0, total_days, _STEP_DAYS):
            d = year_start + dt.timedelta(days=offset)
            t = ts.utc(d.year, d.month, d.day)
            e_pos = earth.at(t)
            sep = e_pos.observe(a_body).apparent().separation_from(
                e_pos.observe(b_body).apparent()
            ).degrees
            seps.append((offset, sep))

        # Find local minima in the coarse scan below threshold.
        for i in range(1, len(seps) - 1):
            prev_sep = seps[i - 1][1]
            cur_sep = seps[i][1]
            next_sep = seps[i + 1][1]
            if cur_sep >= _THRESHOLD_DEG:
                continue
            if not (cur_sep < prev_sep and cur_sep < next_sep):
                continue
            # Refine to the nearest day inside the coarse bucket.
            lo = max(0, seps[i - 1][0])
            hi = min(total_days - 1, seps[i + 1][0])
            best_sep = cur_sep
            best_day = seps[i][0]
            for off in range(lo, hi + 1):
                d = year_start + dt.timedelta(days=off)
                t = ts.utc(d.year, d.month, d.day)
                e_pos = earth.at(t)
                sep = e_pos.observe(a_body).apparent().separation_from(
                    e_pos.observe(b_body).apparent()
                ).degrees
                if sep < best_sep:
                    best_sep = sep
                    best_day = off

            min_date = year_start + dt.timedelta(days=best_day)
            key = (min_date, a_key, b_key)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            label = (
                f'Conjunction: {_PRETTY[a_key]} & {_PRETTY[b_key]} '
                f'({best_sep:.1f}\u00b0 apart)'
            )
            out.append((min_date, label))

    out.sort(key=lambda x: x[0])
    return out
