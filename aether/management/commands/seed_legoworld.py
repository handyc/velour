"""Seed an Aether world built entirely from Legolith bricks.

Generates a Legolith world via legolith.worlds.build_world(), flattens it
to (Brick, (x,y,z)) placements via world_to_bricks(), and packs the
result onto a single Aether Entity that runs the legoworld-render
script. The result is a walkable Lego scene in Aether — same avatars,
same controls — built from L-system buildings, trees, flowers, people,
and a 32x32 studded baseplate.

    venv/bin/python manage.py seed_legoworld --name meadow --biome plains \\
        --seed 42 --buildings 4 --trees 6 --flowers 4 --people 2

Re-running with the same name+seed deletes and recreates the world.
"""

from django.core.management.base import BaseCommand

from aether.legoworld import (
    BIOMES, DEFAULT_SCALE, build_legoworld_in_aether,
)


class Command(BaseCommand):
    help = 'Generate an Aether world built from a Legolith brick payload.'

    def add_arguments(self, parser):
        parser.add_argument('--name', default='legoworld')
        parser.add_argument('--biome', default='plains',
                            choices=sorted(BIOMES.keys()))
        parser.add_argument('--seed', type=int, default=42)
        parser.add_argument('--buildings', type=int, default=4)
        parser.add_argument('--trees', type=int, default=6)
        parser.add_argument('--flowers', type=int, default=4)
        parser.add_argument('--people', type=int, default=2)
        parser.add_argument('--hills', type=int, default=0)
        parser.add_argument('--lamps', type=int, default=2)
        parser.add_argument('--rocks', type=int, default=2)
        parser.add_argument('--scale', type=float, default=DEFAULT_SCALE,
                            help='Meters per stud (default 0.4).')
        parser.add_argument('--no-studs', action='store_true',
                            help='Skip stud rendering — flat-top bricks only.')

    def handle(self, *args, **opts):
        world, stats = build_legoworld_in_aether(
            name=opts['name'], biome=opts['biome'], seed=opts['seed'],
            n_buildings=opts['buildings'], n_trees=opts['trees'],
            n_flowers=opts['flowers'], n_people=opts['people'],
            n_hills=opts['hills'], n_lamps=opts['lamps'],
            n_rocks=opts['rocks'],
            scale=opts['scale'], show_studs=not opts['no_studs'],
        )
        self.stdout.write(self.style.SUCCESS(
            f'Created world "{world.title}" ({stats["bricks"]} bricks, '
            f'~{stats["studs_estimate"]} studs).'))
        self.stdout.write(f'  URL: /aether/{world.slug}/enter/')
