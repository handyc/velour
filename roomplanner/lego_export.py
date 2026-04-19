"""Export a Building/Room to a studded-brick Aether world.

Reuses the same brick-payload format the Legolith/Aether
`legoworld-render` script already understands — each brick is
`[w, d, plates, color, x_studs, y_studs, z_plates, has_studs]` — so
once we emit the list, the shared renderer does all the three.js work.

Scale:
    1 stud  = 40 cm   (so a 4 m × 3 m room lands as a 10 × 8 baseplate)
    1 plate = 16 cm   (1/3 of a standard brick, matching LDraw ratios)

Idempotent: the derived Aether slug is deterministic and
`export_*_to_lego()` wipes the existing world before rebuilding it.
"""
from __future__ import annotations

from django.db import transaction

from aether.legoworld import DEFAULT_SCALE, LEGOWORLD_SCRIPT_SLUG
from aether.models import Entity, EntityScript, Script, World

from .models import Building, Floor, Room


STUD_CM = 40.0
PLATE_CM = STUD_CM * 0.4          # 16 cm per plate
DEFAULT_CEILING_CM = 280
ROOM_GAP_STUDS = 4                # empty gutter between rooms on the same floor

BASEPLATE_COLOR = '#58a84d'       # Lego classic green
WALL_COLOR      = '#e4cd9e'       # Lego tan
FLOOR_ACCENT    = '#9aa0a6'       # (unused for now — reserved for interior trim)

PIECE_COLORS = {
    'desk':       '#8B4513',
    'chair':      '#CD853F',
    'shelf':      '#6B8E23',
    'cabinet':    '#708090',
    'rack':       '#2F4F4F',
    'aquarium':   '#4682B4',
    'lightbox':   '#DAA520',
    'breadboard': '#9370DB',
    'storage':    '#A9A9A9',
    'other':      '#808080',
}
FEATURE_COLORS = {
    'door':     '#5C4033',
    'window':   '#87CEEB',
    'outlet':   '#B22222',
    'vent':     '#D3D3D3',
    'radiator': '#C0C0C0',
    'pillar':   '#696969',
    'sink':     '#F5F5F5',
    'ethernet': '#FFD700',
    'other':    '#808080',
}


def _cm_to_studs(cm):
    return max(1, round(cm / STUD_CM))


def _cm_to_plates(cm):
    return max(1, round(cm / PLATE_CM))


def _default_height_cm(kind):
    return {
        'desk':       75,
        'chair':      90,
        'shelf':     180,
        'cabinet':   200,
        'rack':      150,
        'aquarium':   60,
        'lightbox':   30,
        'breadboard': 10,
        'storage':    40,
    }.get(kind, 80)


def _ensure_script():
    s = Script.objects.filter(slug=LEGOWORLD_SCRIPT_SLUG).first()
    if s is None:
        raise RuntimeError(
            f'Aether script "{LEGOWORLD_SCRIPT_SLUG}" missing — run '
            '`manage.py seed_legoworld_script` first.'
        )
    return s


def _emit_room_bricks(room, origin_x, origin_y, base_plates, bricks):
    """Append bricks for one room to `bricks`.

    origin_x, origin_y are in studs (room's SW corner on the world plate).
    base_plates is the z-offset in plates (0 for ground floor; higher for
    stacked storeys in a building export).
    """
    w_s = _cm_to_studs(room.width_cm)
    d_s = _cm_to_studs(room.length_cm)

    floor_h_cm = (room.floor.height_cm if room.floor else DEFAULT_CEILING_CM)
    h_plates = _cm_to_plates(floor_h_cm)

    # Baseplate — 1 plate thick, studded.
    bricks.append([
        w_s, d_s, 1, BASEPLATE_COLOR,
        origin_x, origin_y, base_plates, 1,
    ])

    wall_z = base_plates + 1

    # Four walls, one stud thick. South/north run the full width; east/west
    # fill the interior so corners aren't double-stacked.
    bricks.append([
        w_s, 1, h_plates, WALL_COLOR,
        origin_x, origin_y, wall_z, 1,
    ])
    bricks.append([
        w_s, 1, h_plates, WALL_COLOR,
        origin_x, origin_y + d_s - 1, wall_z, 1,
    ])
    if d_s > 2:
        bricks.append([
            1, d_s - 2, h_plates, WALL_COLOR,
            origin_x, origin_y + 1, wall_z, 1,
        ])
        bricks.append([
            1, d_s - 2, h_plates, WALL_COLOR,
            origin_x + w_s - 1, origin_y + 1, wall_z, 1,
        ])

    def _clamp(val, lo, hi):
        return max(lo, min(val, hi))

    # Features: small coloured brick at the plan position. Doors/windows sit
    # taller so they read from the outside without cutting through the walls.
    for feat in room.features.all():
        fw = _cm_to_studs(feat.width_cm)
        fd = _cm_to_studs(feat.depth_cm)
        fx = origin_x + _cm_to_studs(feat.x_cm or 0) - (1 if feat.x_cm else 0)
        fy = origin_y + _cm_to_studs(feat.y_cm or 0) - (1 if feat.y_cm else 0)
        fx = _clamp(fx, origin_x, origin_x + max(0, w_s - fw))
        fy = _clamp(fy, origin_y, origin_y + max(0, d_s - fd))
        fh_plates = 6 if feat.kind in ('door', 'window') else 3
        color = FEATURE_COLORS.get(feat.kind, FEATURE_COLORS['other'])
        bricks.append([
            fw, fd, fh_plates, color,
            fx, fy, wall_z, 1,
        ])

    # Placements: one stack of bricks per piece, height proportional to the
    # catalog entry. Rotation 90/270 swaps footprint.
    for pl in room.placements.select_related('piece').all():
        piece = pl.piece
        w_plan = piece.width_cm
        d_plan = piece.depth_cm
        if pl.rotation_deg in (90, 270):
            w_plan, d_plan = d_plan, w_plan
        pw = _cm_to_studs(w_plan)
        pd = _cm_to_studs(d_plan)
        ph_cm = piece.height_cm or _default_height_cm(piece.kind)
        ph_plates = _cm_to_plates(ph_cm)

        px = origin_x + _cm_to_studs(pl.x_cm or 0) - (1 if pl.x_cm else 0)
        py = origin_y + _cm_to_studs(pl.y_cm or 0) - (1 if pl.y_cm else 0)
        px = _clamp(px, origin_x, origin_x + max(0, w_s - pw))
        py = _clamp(py, origin_y, origin_y + max(0, d_s - pd))

        color = PIECE_COLORS.get(piece.kind, PIECE_COLORS['other'])
        bricks.append([
            pw, pd, ph_plates, color,
            px, py, wall_z, 1,
        ])


def _make_world(slug, title, description, total_w_studs, total_d_studs):
    """Create (replace) the Aether world. Returns the fresh World row."""
    World.objects.filter(slug=slug).delete()
    scale = DEFAULT_SCALE
    span_m = max(total_w_studs, total_d_studs) * scale
    ground_size = max(80.0, span_m * 3.0)
    return World.objects.create(
        slug=slug,
        title=title,
        description=description,
        skybox='procedural',
        sky_color='#9ab8d6',
        ground_color='#30402a',
        ground_size=ground_size,
        ambient_light=0.55,
        fog_near=ground_size * 0.5, fog_far=ground_size * 1.4,
        fog_color='#9ab8d6',
        gravity=-9.81, allow_flight=True,
        spawn_x=0.0, spawn_y=1.6, spawn_z=0.0,
        published=True, featured=False,
    )


def _attach_bricks(world, script, bricks, center_studs):
    anchor = Entity.objects.create(
        world=world,
        name=f'Lego RoomPlanner bricks ({len(bricks)})',
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
            'scale': DEFAULT_SCALE,
            'showStuds': True,
            'center': center_studs,
        },
    )


@transaction.atomic
def export_room_to_lego(room: Room) -> World:
    script = _ensure_script()
    w_s = _cm_to_studs(room.width_cm)
    d_s = _cm_to_studs(room.length_cm)

    bricks: list = []
    _emit_room_bricks(room, origin_x=0, origin_y=0,
                      base_plates=0, bricks=bricks)

    slug = f'lego-rp-{room.slug}'
    title = f'Lego {room.name} (Room Planner)'
    desc = (f'Studded-brick export of "{room.name}" — {len(bricks)} bricks on a '
            f'{w_s}×{d_s}-stud baseplate. Re-export replaces this world only.')
    world = _make_world(slug, title, desc, w_s, d_s)

    # Spawn inside the room, aligned with how the legoworld script
    # centres bricks on `center`.
    center = max(w_s, d_s) / 2.0
    world.spawn_x = (w_s / 2.0 - center) * DEFAULT_SCALE
    world.spawn_z = (d_s / 2.0 - center) * DEFAULT_SCALE
    world.spawn_y = 1.6
    world.save(update_fields=['spawn_x', 'spawn_y', 'spawn_z'])

    _attach_bricks(world, script, bricks, center_studs=center)
    return world


@transaction.atomic
def export_building_to_lego(building: Building) -> World:
    script = _ensure_script()

    bricks: list = []
    total_max_w = 1
    total_max_d = 1
    z_cursor_plates = 0

    floors = list(Floor.objects.filter(building=building).order_by('level'))
    for floor in floors:
        floor_h_cm = floor.height_cm or DEFAULT_CEILING_CM
        floor_plates = _cm_to_plates(floor_h_cm) + 1   # walls + baseplate

        rooms = list(Room.objects.filter(floor=floor).order_by('name'))
        x_cursor = 0
        floor_d = 1
        for room in rooms:
            w_s = _cm_to_studs(room.width_cm)
            d_s = _cm_to_studs(room.length_cm)
            _emit_room_bricks(
                room, origin_x=x_cursor, origin_y=0,
                base_plates=z_cursor_plates, bricks=bricks,
            )
            x_cursor += w_s + ROOM_GAP_STUDS
            floor_d = max(floor_d, d_s)

        total_max_w = max(total_max_w, x_cursor)
        total_max_d = max(total_max_d, floor_d)
        z_cursor_plates += floor_plates

    slug = f'lego-rp-{building.slug}'
    title = f'Lego {building.name} (Room Planner)'
    desc = (f'Studded-brick export of {building.name} — {len(bricks)} bricks '
            f'across {len(floors)} floor(s), stacked vertically.')
    world = _make_world(slug, title, desc, total_max_w, total_max_d)

    center = max(total_max_w, total_max_d) / 2.0
    world.spawn_x = (total_max_w / 2.0 - center) * DEFAULT_SCALE
    world.spawn_z = (total_max_d / 2.0 - center) * DEFAULT_SCALE
    world.spawn_y = 1.6
    world.save(update_fields=['spawn_x', 'spawn_y', 'spawn_z'])

    _attach_bricks(world, script, bricks, center_studs=center)
    return world
