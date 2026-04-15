"""Bridge between Legolith's brick model and Aether's scene graph.

The actual Legoworld generator lives here so the management command and
the web view both call into the same code path. Bricks are flattened to
a compact JSON payload [w, d, plates, color, x, y, z, studs] and shipped
as a single EntityScript prop blob — the legoworld-render script does
the three.js work client-side.
"""
from __future__ import annotations

import random as _random

from django.utils.text import slugify

from .models import Entity, EntityScript, Script, World

from legolith import worlds as W
from legolith.brick_render import PLATE_H


BIOMES = W.BIOMES
DEFAULT_SCALE = 0.4   # meters per stud — walkable but not gigantic
BASEPLATE_STUDS = W.BASEPLATE_STUDS

LEGOWORLD_SCRIPT_SLUG = 'legoworld-render'

# Poly Haven HDRI assets already verified to load elsewhere in Aether. Empty
# asset name = fall back to the biome's solid-color sky.
HDRI_OPTIONS = [
    ('',                              'None (solid biome sky)'),
    ('kloofendal_48d_partly_cloudy',  'Kloofendal — partly cloudy'),
    ('forest_slope',                  'Forest slope'),
    ('potsdamer_platz',               'Potsdamer Platz (urban)'),
    ('snowy_park_01',                 'Snowy park'),
    ('brown_photostudio_02',          'Brown photostudio'),
]
HDRI_SLUGS = [s for s, _ in HDRI_OPTIONS if s]


# Surrounding ground tint — picked to flatter each biome's baseplate
# without competing with it. Falls back to dark slate.
_GROUND_AROUND = {
    'plains':  '#2a3a24',
    'forest':  '#1c2a18',
    'desert':  '#a8884c',
    'snow':    '#dde2ea',
    'harbor':  '#1a3850',
    'autumn':  '#5a3a20',
    'town':    '#3a3a3a',
    'dusk':    '#1a2438',
    'meadow':  '#2a3a24',
    'island':  '#1a3850',
}

_SKY_FOR_BIOME = {
    'plains':  '#9bb8d8',
    'forest':  '#7a98b8',
    'desert':  '#e6c890',
    'snow':    '#d8e4ee',
    'harbor':  '#a8c0d8',
    'autumn':  '#c89870',
    'town':    '#a0a8b0',
    'dusk':    '#5a6a90',
    'meadow':  '#9bb8d8',
    'island':  '#a8c8e0',
}


def _flatten_brick(brick, pos):
    """(Brick, (x, y, z)) -> [w, d, plates, color, x, y, z, studs]."""
    x, y, z = pos
    return [
        int(brick.w), int(brick.d), int(brick.plates), brick.color,
        float(x), float(y), float(z), 1 if brick.studs else 0,
    ]


def build_brick_payload(world: W.World) -> list[list]:
    """Flatten a Legolith World into the JSON payload the script consumes."""
    placements = W.world_to_bricks(world)
    return [_flatten_brick(b, p) for (b, p) in placements]


def _world_slug(name: str, seed: int) -> str:
    base = slugify(name)[:60] or 'legoworld'
    return f'legoworld-{base}-s{seed:04d}'


def build_legoworld_in_aether(
    *, name: str, biome: str, seed: int,
    n_buildings: int, n_trees: int, n_flowers: int, n_people: int,
    n_hills: int = 0, n_lamps: int = 0, n_rocks: int = 0,
    scale: float = DEFAULT_SCALE, show_studs: bool = True,
    library_placements: list[tuple[str, int]] | None = None,
    hdri_asset: str = '',
) -> tuple[World, dict]:
    """Generate the Legolith world, write it into Aether, return (world, stats).

    Replaces any existing Aether World with the same derived slug so the
    operation is idempotent for a given (name, seed) pair.
    """
    legolith_world = W.build_world(
        name=name, biome=biome, seed=seed,
        n_buildings=n_buildings, n_trees=n_trees,
        n_flowers=n_flowers, n_people=n_people,
        n_hills=n_hills, n_lamps=n_lamps, n_rocks=n_rocks,
        library_placements=library_placements,
    )
    bricks = build_brick_payload(legolith_world)

    script = Script.objects.filter(slug=LEGOWORLD_SCRIPT_SLUG).first()
    if script is None:
        raise RuntimeError(
            f'Aether script "{LEGOWORLD_SCRIPT_SLUG}" missing — run '
            '`manage.py seed_legoworld_script` first.')

    slug = _world_slug(name, seed)
    World.objects.filter(slug=slug).delete()

    baseplate_m = BASEPLATE_STUDS * scale
    ground_size = max(80.0, baseplate_m * 6.0)

    sky = _SKY_FOR_BIOME.get(biome, '#9bb8d8')
    ground = _GROUND_AROUND.get(biome, '#2a2a2a')

    title = f'Legoworld — {name} (s{seed:04d}, {biome})'
    description = (
        f'Studded-brick world grown from Legolith\'s L-system grammar: '
        f'{n_buildings} buildings, {n_trees} trees, {n_flowers} flowers, '
        f'{n_people} people, {n_hills} hills, {n_lamps} lamps, '
        f'{n_rocks} rocks on a {BASEPLATE_STUDS}x{BASEPLATE_STUDS} '
        f'{biome} baseplate. {len(bricks)} bricks total. '
        f'Same avatars and controls as the rest of Aether.'
    )

    skybox = 'hdri' if hdri_asset else 'procedural'
    aether_world = World.objects.create(
        slug=slug, title=title, description=description,
        skybox=skybox, hdri_asset=hdri_asset, sky_color=sky,
        ground_color=ground, ground_size=ground_size,
        ambient_light=0.55,
        fog_near=ground_size * 0.4, fog_far=ground_size * 1.4,
        fog_color=sky,
        gravity=-9.81, allow_flight=False,
        spawn_x=0.0, spawn_y=1.6, spawn_z=baseplate_m * 0.55 + 1.5,
        soundscape='', ambient_volume=0.0,
        published=True, featured=False,
    )

    # Scale stays 1.0 — the script attaches its brick group to this
    # entity, so any non-unit scale would propagate to every brick.
    # Visibility is killed client-side by hiding the anchor material.
    anchor = Entity.objects.create(
        world=aether_world,
        name=f'Legoworld bricks ({len(bricks)})',
        primitive='box', primitive_color='#000000',
        pos_x=0.0, pos_y=0.0, pos_z=0.0,
        scale_x=1.0, scale_y=1.0, scale_z=1.0,
        cast_shadow=False, receive_shadow=False, visible=True,
        behavior='scripted',
    )
    EntityScript.objects.create(
        entity=anchor, script=script,
        props={
            'bricks': bricks,
            'scale': scale,
            'showStuds': show_studs,
            'center': BASEPLATE_STUDS / 2,
        },
    )

    studs_estimate = sum(
        b[0] * b[1] for b in bricks if b[7] and b[0] * b[1] <= 32 * 32
    )
    stats = {
        'bricks': len(bricks),
        'studs_estimate': studs_estimate,
        'objects': len(legolith_world.objects),
    }
    return aether_world, stats


def _mega_slug(name: str, seed: int, grid: int) -> str:
    base = slugify(name)[:50] or 'mega'
    return f'megalegoworld-{base}-{grid}x{grid}-s{seed:04d}'


def build_megalegoworld_in_aether(
    *, name: str, seed: int, grid: int = 4,
    n_buildings: int = 4, n_trees: int = 6, n_flowers: int = 4,
    n_people: int = 2, n_hills: int = 0, n_lamps: int = 2, n_rocks: int = 2,
    scale: float = DEFAULT_SCALE, show_studs: bool = True,
    hdri_asset: str | None = None,
) -> tuple[World, dict]:
    """Generate a grid×grid matrix of Legoworlds stitched into one Aether world.

    Each tile is an independent Legolith world on its own 32-stud baseplate,
    rendered by its own anchor entity offset so the baseplates tile seamlessly.
    Biomes are picked per tile from `seed`, so reruns with the same seed are
    reproducible.
    """
    script = Script.objects.filter(slug=LEGOWORLD_SCRIPT_SLUG).first()
    if script is None:
        raise RuntimeError(
            f'Aether script "{LEGOWORLD_SCRIPT_SLUG}" missing — run '
            '`manage.py seed_legoworld_script` first.')

    rng = _random.Random(seed)
    biome_names = sorted(BIOMES.keys())

    # Sprinkle library models across tiles: each tile picks 0-3 slugs with
    # small counts. If the library is empty this just yields no extra placements.
    from legolith.models import LegoModel
    library_slugs = list(LegoModel.objects.values_list('slug', flat=True))

    slug = _mega_slug(name, seed, grid)
    World.objects.filter(slug=slug).delete()

    baseplate_m = BASEPLATE_STUDS * scale
    total_span = baseplate_m * grid
    ground_size = total_span * 1.4 + baseplate_m

    center_biome = rng.choice(biome_names)
    sky = _SKY_FOR_BIOME.get(center_biome, '#9bb8d8')
    ground = _GROUND_AROUND.get(center_biome, '#2a2a2a')

    # hdri_asset: None -> random pick; ''/omitted -> no HDRI; otherwise the
    # caller-supplied asset name.
    if hdri_asset is None:
        hdri_pick = rng.choice(HDRI_SLUGS) if HDRI_SLUGS else ''
    else:
        hdri_pick = hdri_asset
    skybox = 'hdri' if hdri_pick else 'procedural'

    title = f'MegaLegoworld — {name} ({grid}×{grid}, s{seed:04d})'
    aether_world = World.objects.create(
        slug=slug, title=title,
        description=(
            f'{grid}×{grid} grid of Legoworlds stitched together — '
            f'{grid * grid} independent baseplates, each with its own '
            f'biome/seed.  Built from the same Legolith L-system grammar. '
            f'Same avatars and controls as the rest of Aether.'
        ),
        skybox=skybox, hdri_asset=hdri_pick, sky_color=sky,
        ground_color=ground, ground_size=ground_size,
        ambient_light=0.55,
        fog_near=ground_size * 0.45, fog_far=ground_size * 1.6,
        fog_color=sky,
        gravity=-9.81, allow_flight=False,
        spawn_x=0.0, spawn_y=1.6, spawn_z=baseplate_m * 0.55 + 1.5,
        soundscape='', ambient_volume=0.0,
        published=True, featured=False,
    )

    tile_biomes: list[str] = []
    total_bricks = 0
    total_objects = 0
    total_studs = 0
    total_library = 0

    for row in range(grid):
        for col in range(grid):
            tile_seed = (seed * 10007 + row * 131 + col) & 0x7FFFFFFF
            tile_biome = rng.choice(biome_names)
            tile_biomes.append(tile_biome)
            tile_name = f'{name} r{row}c{col}'

            tile_library: list[tuple[str, int]] = []
            if library_slugs:
                n_picks = rng.randint(0, min(3, len(library_slugs)))
                for picked in rng.sample(library_slugs, n_picks):
                    tile_library.append((picked, rng.randint(1, 3)))
                    total_library += tile_library[-1][1]

            legolith_world = W.build_world(
                name=tile_name, biome=tile_biome, seed=tile_seed,
                n_buildings=n_buildings, n_trees=n_trees,
                n_flowers=n_flowers, n_people=n_people,
                n_hills=n_hills, n_lamps=n_lamps, n_rocks=n_rocks,
                library_placements=tile_library or None,
            )
            bricks = build_brick_payload(legolith_world)
            total_bricks += len(bricks)
            total_objects += len(legolith_world.objects)
            total_studs += sum(
                b[0] * b[1] for b in bricks
                if b[7] and b[0] * b[1] <= 32 * 32
            )

            dx = (col - (grid - 1) / 2.0) * baseplate_m
            dz = (row - (grid - 1) / 2.0) * baseplate_m

            anchor = Entity.objects.create(
                world=aether_world,
                name=f'Tile r{row}c{col} — {tile_biome} ({len(bricks)})',
                primitive='box', primitive_color='#000000',
                pos_x=dx, pos_y=0.0, pos_z=dz,
                scale_x=1.0, scale_y=1.0, scale_z=1.0,
                cast_shadow=False, receive_shadow=False, visible=True,
                behavior='scripted',
            )
            EntityScript.objects.create(
                entity=anchor, script=script,
                props={
                    'bricks': bricks,
                    'scale': scale,
                    'showStuds': show_studs,
                    'center': BASEPLATE_STUDS / 2,
                },
            )

    stats = {
        'tiles': grid * grid,
        'grid': grid,
        'bricks': total_bricks,
        'library_placements': total_library,
        'studs_estimate': total_studs,
        'objects': total_objects,
        'biomes': tile_biomes,
    }
    return aether_world, stats
