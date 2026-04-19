"""Seed Room Planner with a starter furniture catalog and one example
lab room mirroring the Velour wet-lab layout.

Idempotent — upserts by slug.
"""
from django.core.management.base import BaseCommand

from roomplanner.models import (
    Building, Constraint, Feature, Floor, FurniturePiece, Placement, Room,
)


BUILDING_DATA = {
    'slug':    'home',
    'name':    'Home',
    'address': '',
    'notes':   (
        '3-storey house. The wet lab sits on the top floor; ground and '
        'first are living space. Edit in admin to rename or add rooms.'
    ),
}

FLOORS = [
    # (level, name, height_cm)
    (0, 'Ground floor', 260),
    (1, 'First floor',  260),
    (2, 'Top floor',    240),  # attic-ish, lower ceiling
]

LAB_FLOOR_LEVEL = 2  # wet lab sits on the top floor


CATALOG = [
    # slug, name, kind, w, d, h, heat_w, needs_outlet
    ('workbench-120',       'Workbench 120cm',        'desk',       120,  60,  75, 0, False),
    ('workbench-160',       'Workbench 160cm',        'desk',       160,  70,  75, 0, False),
    ('office-chair',        'Office chair',           'chair',       60,  60,  95, 0, False),
    ('shelf-ikea-kallax-2', 'Shelf 2x2 (Kallax)',     'shelf',       77,  39,  77, 0, False),
    ('shelf-ikea-kallax-4', 'Shelf 2x4 (Kallax)',     'shelf',       77,  39, 147, 0, False),
    ('cabinet-fireproof',   'Fireproof cabinet',      'cabinet',     90,  60, 120, 0, False),
    ('rack-19in-12u',       '19" rack, 12U',          'rack',        60,  60,  60, 30, True),
    ('aquarium-60l',        'Aquarium 60L',           'aquarium',    60,  30,  40, 60, True),
    ('aquarium-120l',       'Aquarium 120L',          'aquarium',    80,  35,  45, 120, True),
    ('lightbox-grow',       'Grow lightbox',          'lightbox',    60,  40,  60, 40, True),
    ('breadboard-station',  'Breadboard station',     'breadboard', 100,  50,  20, 10, True),
    ('storage-tote',        'Storage tote 40L',       'storage',     60,  40,  30, 0, False),
]


ROOM_DATA = {
    'slug':      'velour-lab',
    'name':      'Velour Wet Lab',
    'width_cm':  450,
    'length_cm': 300,
    # north_direction='right' means real-world north points to the right
    # side of the screen, so:  top=west, right=north, bottom=east, left=south
    'north_direction': 'right',
    'notes':     (
        'Primary home lab — aquarium micro-greenhouse, ESP fleet bench, '
        'breadboard station. Fire-safety spacing is the current driver '
        'for re-layout.'
    ),
}

FEATURES = [
    # kind, label, x, y, w, d, notes
    # door on east wall (bottom of screen), biased toward north (right)
    ('door',     'entry',       320, 290, 80,  10, 'east wall, near north corner'),
    # whole west wall (top of screen) is glass
    ('window',   'west wall',   0,   0,   450, 10, 'entire wall is window — main daylight'),
    ('outlet',   'north bench', 440, 80,  10,  10, '230V × 4'),
    ('outlet',   'south bench', 0,   80,  10,  10, '230V × 2'),
    ('outlet',   'rack',        440, 200, 10,  10, '230V × 4'),
    ('ethernet', 'rack',        440, 210, 10,  5,  'Cat6 to switch'),
]

PLACEMENTS = [
    # piece_slug, label, x, y, rot
    ('workbench-160',       'ESP fleet bench',    10,  80,  0),
    ('breadboard-station',  'breadboard',         180, 80,  0),
    ('rack-19in-12u',       'equipment rack',     330, 200, 0),
    # Gary's tank sits long-axis vertical — rotated 90° so footprint is 35×80.
    ('aquarium-120l',       'Gary tank',          10,  200, 90),
    ('lightbox-grow',       'micro-greenhouse',   100, 200, 0),
    ('shelf-ikea-kallax-4', 'parts shelf',        10,  20,  0),
    ('office-chair',        'main chair',         150, 170, 0),
    ('storage-tote',        'loose cables',       330, 20,  0),
]

CONSTRAINTS = [
    ('egress',         'Keep 10cm clear in front of the entry door',
     {'door_feature_kind': 'door', 'min_clearance_cm': 10}),
    ('heat_spacing',   'Heat-producing gear must sit ≥ 30cm from flammable shelves',
     {'min_spacing_cm': 30, 'source_kinds': ['aquarium', 'lightbox', 'rack']}),
    ('outlet_near',    'Anything that needs power must be within 200cm of an outlet',
     {'max_cable_cm': 200}),
    ('walkway',        'Primary walkway minimum width 90cm',
     {'min_cm': 90}),
    ('wall_clearance', 'Radiator must have ≥ 20cm clearance in front',
     {'source_feature_kind': 'radiator', 'min_clearance_cm': 20}),
]


class Command(BaseCommand):
    help = "Seed the Room Planner catalog + starter Velour lab room."

    def handle(self, *args, **opts):
        # Catalog
        for slug, name, kind, w, d, h, heat, outlet in CATALOG:
            p, created = FurniturePiece.objects.update_or_create(
                slug=slug,
                defaults={
                    'name':         name,
                    'kind':         kind,
                    'width_cm':     w,
                    'depth_cm':     d,
                    'height_cm':    h,
                    'heat_watts':   heat,
                    'needs_outlet': outlet,
                },
            )
            action = 'created' if created else 'updated'
            self.stdout.write(f"  [{action}] piece {slug}")

        # Building + floors
        building, b_created = Building.objects.update_or_create(
            slug=BUILDING_DATA['slug'],
            defaults={k: v for k, v in BUILDING_DATA.items() if k != 'slug'},
        )
        self.stdout.write(
            f"  [{'created' if b_created else 'updated'}] building {building.slug}"
        )
        for level, name, height in FLOORS:
            Floor.objects.update_or_create(
                building=building, level=level,
                defaults={'name': name, 'height_cm': height},
            )
        self.stdout.write(f"  [wrote] {len(FLOORS)} floors on {building.slug}")

        lab_floor = Floor.objects.get(building=building, level=LAB_FLOOR_LEVEL)

        # Room — pinned to the lab floor
        room_defaults = {k: v for k, v in ROOM_DATA.items() if k != 'slug'}
        room_defaults['floor'] = lab_floor
        room, created = Room.objects.update_or_create(
            slug=ROOM_DATA['slug'],
            defaults=room_defaults,
        )
        action = 'created' if created else 'updated'
        self.stdout.write(f"  [{action}] room {room.slug} on {lab_floor.display_name}")

        # Wipe + rewrite features / placements / constraints (idempotent).
        room.features.all().delete()
        for kind, label, x, y, w, d, notes in FEATURES:
            Feature.objects.create(
                room=room, kind=kind, label=label,
                x_cm=x, y_cm=y, width_cm=w, depth_cm=d, notes=notes,
            )
        self.stdout.write(f"  [wrote] {len(FEATURES)} features")

        room.placements.all().delete()
        for piece_slug, label, x, y, rot in PLACEMENTS:
            Placement.objects.create(
                room=room,
                piece=FurniturePiece.objects.get(slug=piece_slug),
                label=label, x_cm=x, y_cm=y, rotation_deg=rot,
            )
        self.stdout.write(f"  [wrote] {len(PLACEMENTS)} placements")

        room.constraints.all().delete()
        for kind, desc, vj in CONSTRAINTS:
            Constraint.objects.create(
                room=room, kind=kind, description=desc, value_json=vj,
            )
        self.stdout.write(f"  [wrote] {len(CONSTRAINTS)} constraints")

        self.stdout.write(self.style.SUCCESS("roomplanner seed complete"))
