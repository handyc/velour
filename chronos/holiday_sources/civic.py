"""Civic / national holidays.

Baseline: the `holidays` library for any country (public holidays as
defined by statute).

For country='NL' (the default and only heavily-curated locale), we
layer on a set of widely-observed Dutch dates that the `holidays`
library omits because they are not official paid-leave holidays but
*are* important to Dutch civic and cultural life — the Remembrance +
Liberation pair, government ceremonial days (Prinsjesdag,
Verantwoordingsdag), the Sinterklaas cycle, Carnaval, and so on.

Sources for the Dutch extras:
  - rijksoverheid.nl for government ceremonial days
  - tweedekamer.nl for Prinsjesdag / Verantwoordingsdag rules
  - the standard Dutch cultural calendar for Sinterklaas, Carnaval, etc.
"""

import datetime as dt


def get(year, country='NL'):
    try:
        import holidays
    except ImportError:
        return []
    try:
        cal = holidays.country_holidays(country, years=[year])
    except Exception:
        return []
    items = [(d, name) for d, name in sorted(cal.items())]
    if country == 'NL':
        items = _merge(items, _nl_extras(year))
    return items


def _merge(base, extras):
    # De-dup on (date, lowercased-name) so library + extras don't
    # double-book the same holiday (e.g. Bevrijdingsdag in lustrum years).
    seen = {(d, n.lower().strip()) for d, n in base}
    out = list(base)
    for d, n in extras:
        key = (d, n.lower().strip())
        if key not in seen:
            seen.add(key)
            out.append((d, n))
    out.sort(key=lambda x: x[0])
    return out


# -- Dutch civic & cultural calendar --------------------------------

def _nth_weekday(year, month, weekday, n):
    """The n-th occurrence of `weekday` (0=Mon..6=Sun) in year-month."""
    first = dt.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + dt.timedelta(days=offset + 7 * (n - 1))


def _nl_extras(year):
    # Easter anchors the moveable feasts. Carnaval Zondag/Maandag/Dinsdag
    # are the three days ending on Vastenavond (Shrove Tuesday), i.e.
    # Easter minus 49/48/47 days.
    try:
        from dateutil.easter import easter
        e = easter(year)
    except Exception:
        e = None

    out = [
        (dt.date(year,  2, 14), 'Valentijnsdag'),
        (dt.date(year,  3,  8), 'Internationale Vrouwendag'),
        (dt.date(year,  5,  4), 'Dodenherdenking'),
        (dt.date(year,  5,  5), 'Bevrijdingsdag'),
        (dt.date(year,  7,  1), 'Keti Koti'),
        (dt.date(year, 10,  4), 'Dierendag'),
        (dt.date(year, 10, 31), 'Halloween'),
        (dt.date(year, 11, 11), 'Sint-Maarten'),
        (dt.date(year, 12,  5), 'Sinterklaasavond'),
        (dt.date(year, 12, 31), 'Oudejaarsavond'),

        # Floating government + cultural dates.
        (_nth_weekday(year,  5, 6, 2), 'Moederdag'),              # 2nd Sunday of May
        (_nth_weekday(year,  5, 2, 3), 'Verantwoordingsdag'),     # 3rd Wednesday of May
        (_nth_weekday(year,  6, 6, 3), 'Vaderdag'),               # 3rd Sunday of June
        (_nth_weekday(year,  9, 5, 2), 'Open Monumentendag'),     # 2nd Saturday of September
        (_nth_weekday(year,  9, 1, 3), 'Prinsjesdag'),            # 3rd Tuesday of September
        (_nth_weekday(year, 11, 5, 2), 'Intocht van Sinterklaas'),# 2nd Saturday of November
    ]

    if e is not None:
        out += [
            (e - dt.timedelta(days=49), 'Carnavalszondag'),
            (e - dt.timedelta(days=48), 'Carnavalsmaandag'),
            (e - dt.timedelta(days=47), 'Vastenavond (Carnavalsdinsdag)'),
        ]

    return out
