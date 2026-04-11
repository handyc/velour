"""Chinese lunisolar festivals.

Walks the Gregorian year day-by-day looking for the lunar dates
that mark major festivals. cnlunar gives us the lunar month and
day for any Gregorian date, so we collect the matches.

Festivals returned:
  Chinese New Year      Lunar 1/1
  Lantern Festival      Lunar 1/15
  Qingming              ~April 4-5 (solar term)
  Dragon Boat           Lunar 5/5
  Double Seventh        Lunar 7/7
  Mid-Autumn            Lunar 8/15
  Double Ninth          Lunar 9/9
  Laba Festival         Lunar 12/8
"""

from datetime import date, timedelta


_TARGETS = {
    (1,  1):  'Chinese New Year',
    (1,  15): 'Lantern Festival',
    (5,  5):  'Dragon Boat Festival',
    (7,  7):  'Double Seventh (Qixi)',
    (8,  15): 'Mid-Autumn Festival',
    (9,  9):  'Double Ninth (Chongyang)',
    (12, 8):  'Laba Festival',
}


def get(year):
    try:
        import cnlunar
    except ImportError:
        return []

    out = []
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    while d <= end:
        try:
            ln = cnlunar.Lunar(__import__('datetime').datetime(d.year, d.month, d.day))
            key = (ln.lunarMonth, ln.lunarDay)
            if key in _TARGETS:
                out.append((d, _TARGETS[key]))
        except Exception:
            pass
        d += timedelta(days=1)

    # Add Qingming as an approximate fixed Gregorian date.
    out.append((date(year, 4, 5), 'Qingming Festival'))
    out.sort(key=lambda x: x[0])
    return out
