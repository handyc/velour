"""Christian liturgical year — Easter and its dependent feasts.

Easter is computed via dateutil.easter (Western/Gregorian rule by
default). The dependent moveable feasts are derived as offsets:

  Ash Wednesday    Easter - 46 days
  Palm Sunday      Easter - 7 days
  Good Friday      Easter - 2 days
  Pentecost        Easter + 49 days
  Ascension        Easter + 39 days

Fixed feasts: Epiphany (Jan 6), Annunciation (Mar 25), Assumption
(Aug 15), All Saints' Day (Nov 1), Christmas (Dec 25).
"""

from datetime import date, timedelta


def get(year):
    try:
        from dateutil.easter import easter
    except ImportError:
        return []

    e = easter(year)
    return [
        (date(year, 1, 6),  'Epiphany'),
        (e - timedelta(days=46),  'Ash Wednesday'),
        (e - timedelta(days=7),   'Palm Sunday'),
        (e - timedelta(days=2),   'Good Friday'),
        (e,                       'Easter Sunday'),
        (e + timedelta(days=39),  'Ascension Day'),
        (e + timedelta(days=49),  'Pentecost'),
        (date(year, 3, 25), 'Annunciation'),
        (date(year, 8, 15), 'Assumption of Mary'),
        (date(year, 11, 1), 'All Saints\' Day'),
        (date(year, 12, 24), 'Christmas Eve'),
        (date(year, 12, 25), 'Christmas Day'),
        (date(year, 12, 26), 'Boxing Day / St Stephen\'s Day'),
    ]
