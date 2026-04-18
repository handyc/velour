"""Registry of Oracle lobes.

A lobe is a trained decision tree with a well-defined feature vector
and class set. Declaring one here makes it trainable via

    python manage.py train_lobes <name>

and inspectable via

    python manage.py show_lobe <name>

The existing rumination_template lobe was originally trained by a
dedicated command; it is now one entry in this registry alongside any
future lobes. Adding a lobe is: (1) write a `synthesize` callable that
returns (features, class_label) pairs, (2) list its feature + class
names, (3) append to LOBES. No new management-command wiring required.
"""

import random
from dataclasses import dataclass
from typing import Callable, List, Tuple


@dataclass
class LobeSpec:
    name:              str
    description:       str
    features:          List[str]
    classes:           List[str]
    synthesize:        Callable[[random.Random], Tuple[List[float], str]]
    default_samples:   int = 2000
    default_max_depth: int = 6


# -----------------------------------------------------------------------
# rumination_template — picks a thought-template family for Identity.
# Historically trained by train_rumination_lobe; kept here so the
# behaviour is preserved byte-for-byte when train_lobes runs against it.
# -----------------------------------------------------------------------

_RUMINATION_FEATURES = [
    'mood_group', 'tod_group', 'moon_group', 'open_concern_count',
    'nodes_total', 'nodes_silent', 'upcoming_events', 'upcoming_holidays',
]
_RUMINATION_CLASSES = ['observation', 'concern', 'subject', 'holiday']


def _synth_rumination(rng: random.Random):
    mood_group = rng.randint(0, 9)
    tod_group  = rng.randint(0, 3)
    moon_group = rng.randint(0, 3)
    open_concern_count = rng.choice([0, 0, 0, 1, 1, 2, 3, 5])
    nodes_total  = rng.choice([0, 1, 2, 3, 5, 10])
    nodes_silent = rng.randint(0, nodes_total) if nodes_total else 0
    upcoming_events   = rng.choice([0, 0, 1, 2, 3, 5])
    upcoming_holidays = rng.choice([0, 0, 1, 2, 3])

    features = [
        float(mood_group), float(tod_group), float(moon_group),
        float(open_concern_count),
        float(nodes_total), float(nodes_silent),
        float(upcoming_events), float(upcoming_holidays),
    ]
    r = rng.random()
    if open_concern_count > 0 and r < 0.30:
        label = 'concern'
    elif r < 0.55 and (nodes_total > 0 or upcoming_events > 0):
        label = 'subject'
    elif upcoming_holidays > 0 and r < 0.75:
        label = 'holiday'
    else:
        label = 'observation'
    return features, label


# -----------------------------------------------------------------------
# water_plant — the canonical "poor-man's AI" use case. Given a few
# readings about a plant's current state, decide whether to water it
# right now. Bootstrap rule: water if the soil is dry AND it hasn't
# been watered recently AND it's not the middle of the night. The
# tree will pick this up and refine it once real labels arrive.
# -----------------------------------------------------------------------

_WATER_PLANT_FEATURES = [
    'soil_moisture_pct',     # 0..100, lower = drier
    'temperature_c',         # ambient air
    'hours_since_water',     # since last watering event
    'is_daytime',            # 0 or 1
    'days_since_rain',       # 0..14 (clipped); outdoor plants only
]
_WATER_PLANT_CLASSES = ['skip', 'water']


def _synth_water_plant(rng: random.Random):
    moisture      = rng.uniform(0, 100)
    temperature   = rng.uniform(5, 35)
    hours_since   = rng.choice([0, 1, 2, 6, 12, 24, 36, 48, 72])
    is_daytime    = rng.choice([0, 1])
    days_no_rain  = rng.choice([0, 0, 1, 2, 3, 5, 7, 10, 14])

    dry        = moisture < 30
    just_watered = hours_since < 6
    hot        = temperature > 26
    night      = is_daytime == 0
    thirsty_outdoor = days_no_rain >= 5 and moisture < 50

    if night:
        label = 'skip'
    elif just_watered:
        label = 'skip'
    elif dry or thirsty_outdoor:
        label = 'water' if rng.random() > 0.05 else 'skip'
    elif hot and moisture < 45:
        label = 'water' if rng.random() > 0.25 else 'skip'
    else:
        label = 'skip'

    return [float(moisture), float(temperature), float(hours_since),
            float(is_daytime), float(days_no_rain)], label


LOBES = {
    'rumination_template': LobeSpec(
        name='rumination_template',
        description='Pick a thought-template family for Identity ruminations.',
        features=_RUMINATION_FEATURES,
        classes=_RUMINATION_CLASSES,
        synthesize=_synth_rumination,
        default_max_depth=6,
    ),
    'water_plant': LobeSpec(
        name='water_plant',
        description='Decide whether a plant needs watering right now.',
        features=_WATER_PLANT_FEATURES,
        classes=_WATER_PLANT_CLASSES,
        synthesize=_synth_water_plant,
        default_max_depth=5,
    ),
}
