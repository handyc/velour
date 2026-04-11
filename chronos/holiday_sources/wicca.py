"""Wiccan Wheel of the Year — the eight sabbats.

Four cross-quarter days at fixed Gregorian dates plus four
solar dates (equinoxes and solstices). The solar dates here are
approximate fixed values; Phase 2c will compute exact equinox
and solstice times via skyfield.
"""

from datetime import date


def get(year):
    return [
        (date(year, 2, 1),   'Imbolc'),
        (date(year, 3, 20),  'Ostara (Vernal Equinox, approx.)'),
        (date(year, 5, 1),   'Beltane'),
        (date(year, 6, 21),  'Litha (Summer Solstice, approx.)'),
        (date(year, 8, 1),   'Lughnasadh'),
        (date(year, 9, 22),  'Mabon (Autumnal Equinox, approx.)'),
        (date(year, 10, 31), 'Samhain'),
        (date(year, 12, 21), 'Yule (Winter Solstice, approx.)'),
    ]
