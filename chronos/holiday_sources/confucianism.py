"""Confucian observances — Confucius's birthday and Tomb-Sweeping Day."""

from datetime import date


def get(year):
    return [
        (date(year, 4, 5),  'Tomb Sweeping Day (Qingming)'),
        (date(year, 9, 28), 'Confucius\'s Birthday (Teachers\' Day)'),
    ]
