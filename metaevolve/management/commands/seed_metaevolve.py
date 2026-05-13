"""Seed metaevolve.Target with one entry per built-in archetype."""

from __future__ import annotations
from django.core.management.base import BaseCommand
from django.db import transaction

from metaevolve.models import Target


# Mirrors the 5 archetype labels in templates/doom_ca/evolve.html.
ARCHETYPES = [
    ('doom',    'Doom (find exit, fight monsters)',
     'Bias: openness + completion + corridor width.  Doom march music.'),
    ('pacman',  'Pacman (open maze, collect, no weapons)',
     'Bias: openness 1.0, exploration 1.0, no shotgun.  Common 4/4 music.'),
    ('pitfall', 'Pitfall (linear progression, sparse hazards)',
     'Bias: completion + time-to-exit, sparse monsters.  Celtic jig music.'),
    ('blob',    'Boy & His Blob (sparse, companion-ish)',
     'Bias: exploration + completion, very few monsters.  Ambient drift music.'),
    ('tmnt',    'TMNT (beat-em-up, lots of monsters + ammo)',
     'Bias: engagement 1.0, monster_count 16, lots of ammo.  Russian Trepak music.'),
]


class Command(BaseCommand):
    help = 'Seed one Target per archetype.'

    def handle(self, *args, **opts):
        with transaction.atomic():
            for key, label, notes in ARCHETYPES:
                obj, created = Target.objects.get_or_create(
                    name=label,
                    defaults={
                        'archetype':       key,
                        'population_size': 24,
                        'generations':     15,
                        'max_turns':       40,
                        'grid_side':       24,
                        'runs_per_batch':  3,
                        'archive_top_k':   3,
                        'notes':           notes,
                    })
                if created:
                    self.stdout.write(f'  + target {label}')
                else:
                    # Update notes / archetype but leave user-edited fields alone.
                    obj.notes = notes
                    obj.archetype = key
                    obj.save()
        self.stdout.write(self.style.SUCCESS(
            f'Seed complete · {Target.objects.count()} targets'))
