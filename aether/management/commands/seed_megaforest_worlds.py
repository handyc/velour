"""Seed several MegaForest worlds — MegaLegoworld variants populated with
super-tall L-system trees, swings, and barbecues.

    venv/bin/python manage.py seed_megaforest_worlds
    venv/bin/python manage.py seed_megaforest_worlds --count 6 --grid 4

Re-running with the same name+seed deletes and recreates each world.
Idempotently registers the swing/BBQ scripts first.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand

from aether.legoworld import DEFAULT_SCALE, build_megaforest_in_aether


# Hand-picked seed presets — each one biases the tile mix differently so
# the produced worlds feel distinct rather than just re-rolled.
PRESETS = [
    # (name,            seed,  giant_trees, trees, flowers, people, lamps,
    #  swings, bbqs, hdri)
    ('giants-grove',     1701,  6, 0, 6, 1, 1, 1, 1, 'forest_slope'),
    ('sequoia-festival', 4242,  5, 1, 4, 2, 2, 2, 1, 'kloofendal_48d_partly_cloudy'),
    ('moonlit-pines',    9111,  5, 0, 4, 1, 4, 1, 1, ''),
    ('baobab-bbq',       2718,  4, 0, 6, 2, 2, 1, 2, 'kloofendal_48d_partly_cloudy'),
    ('candy-canopy',     3142,  6, 0, 6, 1, 2, 2, 1, 'forest_slope'),
    ('camp-titan',       8675,  4, 1, 4, 2, 3, 2, 2, 'kloofendal_48d_partly_cloudy'),
]


class Command(BaseCommand):
    help = 'Generate several MegaForest worlds (giant trees + swings + barbecues).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--count', type=int, default=len(PRESETS),
            help=f'How many presets to seed (max {len(PRESETS)}).',
        )
        parser.add_argument('--grid', type=int, default=4,
                            help='Tiles per side (default 4 = 4×4).')
        parser.add_argument('--scale', type=float, default=DEFAULT_SCALE)

    def handle(self, *args, **opts):
        # Make sure the brick + interactable scripts are present.
        call_command('seed_legoworld_script')
        call_command('seed_giants_scripts')

        count = max(1, min(opts['count'], len(PRESETS)))
        grid = opts['grid']
        scale = opts['scale']

        urls: list[str] = []
        for preset in PRESETS[:count]:
            (name, seed, gt, t, fl, ppl, lamps, sw, bq, hdri) = preset
            world, stats = build_megaforest_in_aether(
                name=name, seed=seed, grid=grid,
                n_buildings=1, n_giant_trees=gt,
                n_trees=t, n_flowers=fl, n_people=ppl,
                n_lamps=lamps, n_rocks=1,
                n_swings_per_tile=sw, n_bbq_per_tile=bq,
                scale=scale, hdri_asset=hdri,
            )
            self.stdout.write(self.style.SUCCESS(
                f'  {world.title}: {stats["bricks"]} bricks, '
                f'{stats["swings"]} swings, {stats["barbecues"]} barbecues, '
                f'~{stats["studs_estimate"]} studs.'))
            urls.append(f'/aether/{world.slug}/enter/')

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Seeded {len(urls)} MegaForest worlds:'))
        for u in urls:
            self.stdout.write(f'  {u}')
