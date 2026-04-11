"""Buddhist observances.

Vesak (Buddha Day) is the central Theravāda holiday — full moon of
the Vaisakha month, typically late April or May. The exact date
varies by tradition (Mahayana / Theravada use slightly different
rules) and by country.

This adapter pulls Sri Lanka's calendar from the holidays library
which is one of the most comprehensive Buddhist sources, falling
back to fixed approximate dates.
"""

from datetime import date


_FALLBACK = [
    (5, 26, 'Vesak (Buddha Day, approx.)'),
    (7, 19, 'Asalha Puja (approx.)'),
    (7, 20, 'Vassa begins (approx.)'),
    (10, 17, 'Vassa ends / Pavarana (approx.)'),
    (12,  8, 'Bodhi Day (Rohatsu)'),
]


def get(year):
    try:
        import holidays
        cal = holidays.country_holidays('LK', years=[year])
        # Filter to Buddhist-specific entries by name match.
        items = [
            (d, name) for d, name in sorted(cal.items())
            if any(k in name.lower() for k in ('poya', 'buddha', 'vesak'))
        ]
        if items:
            return items
    except Exception:
        pass
    return [(date(year, m, d), name) for m, d, name in _FALLBACK]
