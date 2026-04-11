"""Jewish holidays via the pyluach Hebrew calendar library.

Computes major holidays for any Gregorian year by walking the
Hebrew years that touch it. The Jewish calendar year starts in
Tishrei (autumn), so a Gregorian year usually contains parts of
two Hebrew years.
"""

from datetime import date


# (Hebrew month, Hebrew day, name) — non-Pesach/non-Sukkot list
_FIXED = [
    (7,  1, 'Rosh Hashanah'),
    (7,  10, 'Yom Kippur'),
    (7,  15, 'Sukkot (start)'),
    (7,  22, 'Shemini Atzeret'),
    (7,  23, 'Simchat Torah'),
    (9,  25, 'Hanukkah (start)'),
    (11, 15, 'Tu BiShvat'),
    (12, 14, 'Purim'),         # Adar in non-leap; Adar II in leap
    (1,  15, 'Pesach (start)'),
    (1,  22, 'Pesach (end)'),
    (3,   6, 'Shavuot'),
    (5,   9, 'Tisha B\'Av'),
]


def get(year):
    try:
        from pyluach import dates
    except ImportError:
        return []

    out = []
    # Two Hebrew years touch any Gregorian year. Find them.
    heb_year_start = dates.GregorianDate(year, 1, 1).to_heb().year
    heb_year_end = dates.GregorianDate(year, 12, 31).to_heb().year

    for hy in range(heb_year_start, heb_year_end + 1):
        for hmonth, hday, name in _FIXED:
            try:
                hd = dates.HebrewDate(hy, hmonth, hday)
            except (ValueError, TypeError):
                continue
            try:
                gd = hd.to_pydate()
            except Exception:
                continue
            if gd.year == year:
                out.append((gd, name))

    out.sort(key=lambda x: x[0])
    return out
