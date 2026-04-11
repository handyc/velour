"""Shinto observances on fixed Gregorian dates (modern practice)."""

from datetime import date


def get(year):
    return [
        (date(year, 1, 1),   'Shōgatsu (New Year)'),
        (date(year, 2, 3),   'Setsubun'),
        (date(year, 3, 3),   'Hinamatsuri (Doll Festival)'),
        (date(year, 5, 5),   'Kodomo no Hi (Children\'s Day)'),
        (date(year, 7, 7),   'Tanabata (Star Festival)'),
        (date(year, 8, 13),  'Obon begins'),
        (date(year, 8, 15),  'Obon (peak)'),
        (date(year, 11, 15), 'Shichi-Go-San'),
    ]
