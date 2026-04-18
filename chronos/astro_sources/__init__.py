"""Astronomical event sources for the chronos calendar.

Equinoxes, solstices, eclipses, and major moon phases come from
skyfield using the JPL DE421 ephemeris (auto-downloaded on first
use to chronos/data/de421.bsp). Meteor showers come from a
hand-curated table of fixed Gregorian dates because their peaks
shift only slightly year-to-year.

Each adapter exposes get(year) -> [(date, name), ...] following
the same protocol as the religious holiday adapters.
"""

from . import conjunctions, equinoxes, eclipses, meteors, moon_phases


ASTRO_SOURCES = [
    equinoxes,
    moon_phases,
    eclipses,
    meteors,
    conjunctions,
]


def get_all(year):
    """Aggregate all astronomical events for a year."""
    out = []
    for module in ASTRO_SOURCES:
        try:
            out.extend(module.get(year))
        except Exception:
            continue
    out.sort(key=lambda x: x[0])
    return out
