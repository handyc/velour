"""Import existing world_*.json files into the LegoWorld table.

These came from the standalone sharepointq project that seeded Legolith;
the files are the authoritative JSON payload, so we round-trip them
through worlds.World to pick up the denormalized counts consistently.
"""

import glob
import json
import os

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from legolith import worlds as W
from legolith.models import LegoWorld


DEFAULT_DIR = '/home/handyc/projects/sharepointq/worlds'


class Command(BaseCommand):
    help = 'Import world_*.json files into LegoWorld.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dir', default=DEFAULT_DIR,
            help=f'Directory containing world_*.json (default: {DEFAULT_DIR}).',
        )
        parser.add_argument(
            '--limit', type=int, default=0,
            help='Max worlds to import (0 = all).',
        )
        parser.add_argument(
            '--skip-existing', action='store_true',
            help='Skip files whose derived slug already exists.',
        )

    def handle(self, *args, **opts):
        root = opts['dir']
        limit = opts['limit']
        skip = opts['skip_existing']
        paths = sorted(glob.glob(os.path.join(root, 'world_*.json')))
        if limit:
            paths = paths[:limit]
        if not paths:
            self.stderr.write(f'No world_*.json files in {root}')
            return

        created = 0
        skipped = 0
        errored = 0
        for p in paths:
            try:
                with open(p, encoding='utf-8') as f:
                    blob = f.read()
                world = W.World.from_json(blob)
            except Exception as e:
                self.stderr.write(f'  parse error {os.path.basename(p)}: {e}')
                errored += 1
                continue

            base_slug = slugify(world.name)[:120] or 'world'
            candidate = f'{base_slug}-s{world.seed:04d}'
            if LegoWorld.objects.filter(slug=candidate).exists():
                if skip:
                    skipped += 1
                    continue
                # bump seed suffix until unique
                n = 2
                while LegoWorld.objects.filter(slug=f'{candidate}-{n}').exists():
                    n += 1
                candidate = f'{candidate}-{n}'

            payload = json.loads(blob)
            LegoWorld.objects.create(
                name=world.name,
                slug=candidate,
                biome=world.biome,
                seed=world.seed,
                baseplate_color=world.baseplate_color,
                n_buildings=world.n_buildings,
                n_trees=world.n_trees,
                n_flowers=world.n_flowers,
                n_people=world.n_people,
                n_hills=world.n_hills,
                n_lamps=world.n_lamps,
                n_rocks=world.n_rocks,
                payload=payload,
            )
            created += 1
            if created % 50 == 0:
                self.stdout.write(f'  imported {created}/{len(paths)}')

        self.stdout.write(self.style.SUCCESS(
            f'Imported {created}, skipped {skipped}, errored {errored} '
            f'(total files: {len(paths)}).'))
