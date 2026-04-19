"""Helpers for picking an Agent's origin world and other plausibles.

Phase 1 keeps these intentionally minimal — uniform random over what
Aether knows about. Future phases can filter by world disposition,
era, planet, etc.
"""

from __future__ import annotations

import datetime
import random
from typing import Optional


def random_aether_world():
    """Return a random aether.World instance, or None if Aether is empty."""
    from aether.models import World  # local import; avoids app-loading cycles
    pks = list(World.objects.values_list('pk', flat=True))
    if not pks:
        return None
    return World.objects.filter(pk=random.choice(pks)).first()


def random_birthdate(min_age: int = 5, max_age: int = 90,
                     reference: Optional[datetime.date] = None) -> datetime.date:
    today = reference or datetime.date.today()
    age = random.randint(min_age, max_age)
    day_offset = random.randint(0, 364)
    try:
        return today.replace(year=today.year - age) - datetime.timedelta(days=day_offset)
    except ValueError:
        # Feb 29 → fall back to Feb 28 in that year
        return today.replace(year=today.year - age, month=2, day=28) \
                    - datetime.timedelta(days=day_offset)


# Tiny pool of name fragments for bulk-fake generation. Intentionally
# small — Phase 1 just demonstrates scale; Phase 2 can pull from
# a wider corpus or per-language naming conventions.
_FIRST_F = [
    'Adelina', 'Beatrice', 'Camille', 'Diana', 'Elena', 'Fatima',
    'Greta', 'Hana', 'Ines', 'Junko', 'Kira', 'Lina', 'Maya',
    'Nadia', 'Ofelia', 'Priya', 'Quynh', 'Rosa', 'Sana', 'Talia',
]
_FIRST_M = [
    'Aldo', 'Bruno', 'Cesar', 'Dario', 'Eros', 'Felix', 'Gio',
    'Hiro', 'Ivan', 'Jin', 'Kenji', 'Luca', 'Marco', 'Nico',
    'Omar', 'Paolo', 'Quirino', 'Rafa', 'Salim', 'Tito',
]
_FAMILY = [
    'Andolini', 'Bertolucci', 'Carrasco', 'Devereux', 'Esposito',
    'Faraz', 'Galanis', 'Hayashi', 'Ito', 'Joshi', 'Kovac',
    'Laurent', 'Marquez', 'Nakamura', 'Okoye', 'Park', 'Quesada',
    'Reinholt', 'Saldana', 'Tanaka', 'Uribe', 'Vasquez', 'Watanabe',
    'Xu', 'Yildiz', 'Zanetti',
]
_OCCUPATIONS = [
    'waiter', 'baker', 'barista', 'librarian', 'fisher', 'tailor',
    'engineer', 'retired teacher', 'street musician', 'gardener',
    'priest', 'archivist', 'apothecary', 'pilot', 'mechanic',
    'student', 'cobbler', 'nurse', 'carpenter', 'tour guide',
]
_TRAITS = [
    'patient', 'observant', 'talkative', 'cautious', 'restless',
    'devout', 'cynical', 'generous', 'forgetful', 'meticulous',
    'whimsical', 'stoic', 'impulsive', 'loyal', 'curious', 'shy',
]


def random_name(gender: str = '?'):
    if gender == 'f':
        first = random.choice(_FIRST_F)
    elif gender == 'm':
        first = random.choice(_FIRST_M)
    else:
        first = random.choice(_FIRST_F + _FIRST_M)
    family = random.choice(_FAMILY)
    return first, family


def random_traits(k: int = 3):
    return random.sample(_TRAITS, k=min(k, len(_TRAITS)))


def random_occupation():
    return random.choice(_OCCUPATIONS)
