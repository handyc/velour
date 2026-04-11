"""Major annual meteor showers.

Peak dates shift by about ±1 day year-to-year, so this table is
"approximately right". The radiant constellations are noted in
the names because they double as good visual markers.
"""

import datetime as dt


_SHOWERS = [
    (1,  3, 'Quadrantids (peak)'),
    (4, 22, 'Lyrids (peak)'),
    (5,  5, 'Eta Aquariids (peak)'),
    (7, 30, 'Southern Delta Aquariids (peak)'),
    (8, 12, 'Perseids (peak)'),
    (10, 9, 'Draconids (peak)'),
    (10, 21, 'Orionids (peak)'),
    (11, 5, 'Southern Taurids (peak)'),
    (11, 12, 'Northern Taurids (peak)'),
    (11, 17, 'Leonids (peak)'),
    (12, 14, 'Geminids (peak)'),
    (12, 22, 'Ursids (peak)'),
]


def get(year):
    return [(dt.date(year, m, d), name) for m, d, name in _SHOWERS]
