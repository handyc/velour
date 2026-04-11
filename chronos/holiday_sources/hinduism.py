"""Hindu (Vedic) observances.

Tries the holidays library's India calendar first; falls back to
a small set of approximate fixed Gregorian dates if the library
isn't available or doesn't have the year.
"""

from datetime import date


# Approximate fixed Gregorian dates for major Hindu festivals.
# Many actually drift each year (lunisolar) — these are only used
# as a stub when no better data source is available.
_FALLBACK = [
    (1, 14, 'Makar Sankranti'),
    (3,  8, 'Holi (approx.)'),
    (4, 14, 'Tamil New Year'),
    (4, 14, 'Vaisakhi'),
    (8, 15, 'Janmashtami (approx.)'),
    (8, 30, 'Ganesh Chaturthi (approx.)'),
    (10, 15, 'Navaratri begins (approx.)'),
    (10, 23, 'Dussehra (approx.)'),
    (11, 12, 'Diwali (approx.)'),
]


def get(year):
    try:
        import holidays
        cal = holidays.country_holidays('IN', years=[year])
        items = [(d, name) for d, name in sorted(cal.items())]
        if items:
            return items
    except Exception:
        pass
    return [(date(year, m, d), name) for m, d, name in _FALLBACK]
