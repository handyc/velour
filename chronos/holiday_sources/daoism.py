"""Daoist observances — birthdays of major deities and festivals.

Most are lunisolar dates computed via cnlunar.
"""

from datetime import date, timedelta


# (lunar month, lunar day, name)
_TARGETS = {
    (1,  9):  'Birthday of the Jade Emperor',
    (1, 15): 'Lantern Festival',
    (2, 15): 'Birthday of Lao Tzu',
    (3,  3): 'Birthday of the Pak Tai',
    (3, 15): 'Birthday of the Bao Sheng Da Di',
    (5, 13): 'Birthday of Guan Yu',
    (7, 15): 'Zhongyuan / Ghost Festival',
    (9,  9): 'Birthday of the Nine Emperor Gods',
}


def get(year):
    try:
        import cnlunar
        import datetime as _dt
    except ImportError:
        return []

    out = []
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    while d <= end:
        try:
            ln = cnlunar.Lunar(_dt.datetime(d.year, d.month, d.day))
            key = (ln.lunarMonth, ln.lunarDay)
            if key in _TARGETS:
                out.append((d, _TARGETS[key]))
        except Exception:
            pass
        d += timedelta(days=1)
    out.sort(key=lambda x: x[0])
    return out
