"""Holiday source adapters.

Each tradition has a small adapter module with a `get(year)` function
returning an iterable of (date, name) tuples for the given Gregorian
year. The seeder iterates the registry and creates CalendarEvent rows
attached to the matching Tradition.

Adding a new tradition: write `chronos/holiday_sources/<slug>.py`
exposing `get(year)`, then register it in TRADITIONS below.

Tradition metadata:
  slug      stable identifier (also matches the module name)
  name      display name
  color     hex tint used in calendar views
"""

from . import (
    buddhism, chinese, christianity, civic, confucianism, daoism,
    hinduism, islam, judaism, shinto, wicca,
)


TRADITIONS = [
    {
        'slug': 'civic', 'name': 'Civic / National',
        'color': '#FF7B00',
        'module': civic,
        'description': 'National civic holidays for the country '
                       'configured in ClockPrefs.country.',
    },
    {
        'slug': 'christianity', 'name': 'Christianity',
        'color': '#9B2226',
        'module': christianity,
        'description': 'Major Christian observances including Easter '
                       '(computed via dateutil) and the principal feast '
                       'days of the liturgical calendar.',
    },
    {
        'slug': 'judaism', 'name': 'Judaism',
        'color': '#005A9C',
        'module': judaism,
        'description': 'Major Jewish holidays computed via the pyluach '
                       'Hebrew calendar library.',
    },
    {
        'slug': 'islam', 'name': 'Islam',
        'color': '#006400',
        'module': islam,
        'description': 'Major Islamic observances computed via the '
                       'hijridate Hijri ↔ Gregorian library.',
    },
    {
        'slug': 'hinduism', 'name': 'Hinduism (Vedic)',
        'color': '#FF9933',
        'module': hinduism,
        'description': 'Major Hindu observances. Lunisolar dates are '
                       'pulled from the holidays library where available.',
    },
    {
        'slug': 'buddhism', 'name': 'Buddhism',
        'color': '#F58025',
        'module': buddhism,
        'description': 'Major Buddhist observances including Vesak '
                       '(Buddha Day) and the principal Theravāda dates.',
    },
    {
        'slug': 'chinese', 'name': 'Chinese (lunisolar)',
        'color': '#DC143C',
        'module': chinese,
        'description': 'Chinese New Year, Mid-Autumn, Dragon Boat, and '
                       'other Chinese lunisolar festivals via cnlunar.',
    },
    {
        'slug': 'shinto', 'name': 'Shinto',
        'color': '#E03C31',
        'module': shinto,
        'description': 'Major Shinto observances on fixed Gregorian '
                       'dates following modern Japanese practice.',
    },
    {
        'slug': 'daoism', 'name': 'Daoism (Taoism)',
        'color': '#A9A9A9',
        'module': daoism,
        'description': 'Major Daoist observances; key birthdays of '
                       'Daoist deities, computed via cnlunar.',
    },
    {
        'slug': 'confucianism', 'name': 'Confucianism',
        'color': '#B8860B',
        'module': confucianism,
        'description': 'Confucius\'s birthday and major Confucian '
                       'observances.',
    },
    {
        'slug': 'wicca', 'name': 'Wicca',
        'color': '#5D3FD3',
        'module': wicca,
        'description': 'The Wheel of the Year — eight sabbats including '
                       'the four cross-quarter days and approximate '
                       'equinox/solstice dates.',
    },
]
