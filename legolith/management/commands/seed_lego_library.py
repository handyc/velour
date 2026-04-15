"""Bootstrap the Legolith Object Library with a handful of starter models.

These are deterministic L-System specs (the library is a *template* store;
random-per-placement variation comes from the built-in generators, not from
library models). Idempotent — reruns upsert by slug.
"""
from django.core.management.base import BaseCommand

from legolith.models import LegoModel


STARTERS = [
    {
        'name': 'Pine Tree',
        'kind': 'tree',
        'description': 'Tall brown trunk with a cone of dark green needles.',
        'axiom': 'T',
        'rules': {
            'T': '{C:6b4a2e}FFF{C:2d6b2a}K',
            'K': 'L[>L][<L][^L][&L]FL[>L][<L][^L][&L]FLL',
        },
        'iterations': 2,
        'init_color': '#6b4a2e',
        'init_shape': (1, 1, 3),
        'footprint': (2, 2),
    },
    {
        'name': 'Oak Tree',
        'kind': 'tree',
        'description': 'Sturdy trunk with a wide bushy canopy.',
        'axiom': 'T',
        'rules': {
            'T': '{C:6b4a2e}FFFF{C:2d6b2a}C',
            'C': 'L[>L][<L][^L][&L][>^L][<^L][>&L][<&L]FL',
        },
        'iterations': 2,
        'init_color': '#6b4a2e',
        'init_shape': (1, 1, 3),
        'footprint': (2, 2),
    },
    {
        'name': 'Cherry Blossom',
        'kind': 'tree',
        'description': 'Pink-capped blossom tree with petal accents.',
        'axiom': 'T',
        'rules': {
            'T': '{C:6b4a2e}FFF{C:2d6b2a}C{C:d98bb4}[>L][<L][^L][&L]',
            'C': 'L[>L][<L][^L][&L][>^L][<^L][>&L][<&L]F',
        },
        'iterations': 2,
        'init_color': '#6b4a2e',
        'init_shape': (1, 1, 3),
        'footprint': (2, 2),
    },
    {
        'name': 'Daisy',
        'kind': 'flower',
        'description': 'Cross-layout flower: stem, four petals, yellow center.',
        'axiom': 'X',
        'rules': {
            'X': '{S:1,1,1}{C:2d6b2a}PPP{C:ffffff}L[>L][<L][^L][&L]{C:f0c040}F',
        },
        'iterations': 1,
        'init_color': '#2d6b2a',
        'init_shape': (1, 1, 1),
        'footprint': (1, 1),
    },
    {
        'name': 'Tulip Ring',
        'kind': 'flower',
        'description': 'Ringed pink petals around a white center.',
        'axiom': 'X',
        'rules': {
            'X': '{S:1,1,1}{C:2d6b2a}PPPP{C:d01712}L[>L][<L][^L][&L]'
                 '[>^L][<^L][>&L][<&L]{C:ffffff}F',
        },
        'iterations': 1,
        'init_color': '#2d6b2a',
        'init_shape': (1, 1, 1),
        'footprint': (1, 1),
    },
    {
        'name': 'Lamppost',
        'kind': 'lamp',
        'description': 'Tall dark post topped with a bright yellow bulb cluster.',
        'axiom': 'P',
        'rules': {
            'P': '{S:1,1,3}{C:222222}FFFF{S:1,1,1}{C:f5cd30}F[>L][<L][^L][&L]',
        },
        'iterations': 1,
        'init_color': '#222222',
        'init_shape': (1, 1, 3),
        'footprint': (1, 1),
    },
    {
        'name': 'Mossy Rock',
        'kind': 'rock',
        'description': '2×2 grey base, small cap, touch of green moss.',
        'axiom': 'X',
        'rules': {
            'X': '{S:2,2,1}{C:b4b2ad}P{S:1,1,3}{C:8c8a85}F{S:1,1,1}{C:2d6b2a}L',
        },
        'iterations': 1,
        'init_color': '#b4b2ad',
        'init_shape': (2, 2, 1),
        'footprint': (2, 2),
    },
    {
        'name': 'Obelisk',
        'kind': 'other',
        'description': 'Tall slender monument with a golden cap.',
        'axiom': 'O',
        'rules': {
            'O': '{S:1,1,3}{C:efdca2}FFFFF{S:1,1,1}{C:f5cd30}F',
        },
        'iterations': 1,
        'init_color': '#efdca2',
        'init_shape': (1, 1, 3),
        'footprint': (1, 1),
    },
]


class Command(BaseCommand):
    help = 'Seed the Legolith Object Library with starter L-System models.'

    def handle(self, *args, **opts):
        created = 0
        updated = 0
        for spec in STARTERS:
            fw, fd = spec['footprint']
            isw, isd, ish = spec['init_shape']
            defaults = {
                'name': spec['name'],
                'kind': spec['kind'],
                'description': spec['description'],
                'axiom': spec['axiom'],
                'rules': spec['rules'],
                'iterations': spec['iterations'],
                'init_color': spec['init_color'],
                'init_shape_w': isw,
                'init_shape_d': isd,
                'init_shape_plates': ish,
                'footprint_w': fw,
                'footprint_d': fd,
            }
            slug = spec['name'].lower().replace(' ', '-')
            obj, was_created = LegoModel.objects.update_or_create(
                slug=slug, defaults=defaults,
            )
            created += 1 if was_created else 0
            updated += 0 if was_created else 1
            self.stdout.write(f'  {"+" if was_created else "~"} {obj.slug}')
        self.stdout.write(self.style.SUCCESS(
            f'Library: {created} created, {updated} updated, '
            f'{LegoModel.objects.count()} total.'
        ))
