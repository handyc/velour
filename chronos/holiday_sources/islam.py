"""Islamic holidays via hijridate (Hijri ↔ Gregorian conversion).

Computes major Islamic observances for any Gregorian year by
walking the Hijri years that touch it.

Note: actual observance of Islamic holidays varies by region
because traditional moon-sighting can shift the date by ±1 day.
The dates returned here are calendar-rule dates, which match
official Saudi/UAE practice.
"""

from datetime import date


# (Hijri month, Hijri day, name)
_FIXED = [
    (1,  1, 'Islamic New Year'),
    (1, 10, 'Day of Ashura'),
    (3, 12, 'Mawlid an-Nabi'),
    (7, 27, 'Isra and Mi\'raj'),
    (8, 15, 'Mid-Sha\'ban'),
    (9,  1, 'Ramadan begins'),
    (9, 27, 'Laylat al-Qadr (approx.)'),
    (10, 1, 'Eid al-Fitr'),
    (12, 8, 'Day of Tarwiyah'),
    (12, 9, 'Day of Arafah'),
    (12, 10, 'Eid al-Adha'),
]


def get(year):
    try:
        from hijridate import Gregorian
    except ImportError:
        try:
            from hijri_converter import Gregorian
        except ImportError:
            return []

    out = []
    hy_start = Gregorian(year, 1, 1).to_hijri().year
    hy_end = Gregorian(year, 12, 31).to_hijri().year

    try:
        from hijridate import Hijri
    except ImportError:
        from hijri_converter import Hijri

    for hy in range(hy_start, hy_end + 1):
        for hmonth, hday, name in _FIXED:
            try:
                gd = Hijri(hy, hmonth, hday).to_gregorian()
            except Exception:
                continue
            try:
                py_date = date(gd.year, gd.month, gd.day)
            except Exception:
                continue
            if py_date.year == year:
                out.append((py_date, name))

    out.sort(key=lambda x: x[0])
    return out
