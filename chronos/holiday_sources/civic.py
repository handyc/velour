"""Civic / national holidays via the `holidays` library."""


def get(year, country='NL'):
    try:
        import holidays
    except ImportError:
        return []
    try:
        cal = holidays.country_holidays(country, years=[year])
    except Exception:
        return []
    return [(d, name) for d, name in sorted(cal.items())]
