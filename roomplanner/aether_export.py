"""Export a Building (or single Room) to an Aether World.

Conventions:
    Room Planner is in centimetres. Its SVG plan uses standard SVG
    axes: +X right, +Y *down* the page. Aether uses metres and
    three.js-style axes: +X right, +Y up, -Z forward (the camera's
    default view direction).

    The mapping:
        rp.x_cm / 100  →  ae.x              (right on the floor)
        rp.y_cm / 100  →  (rp.y - length)/100 → ae.z
                                          (the plan's "top edge",
                                           rp_y=0, lands at -length
                                           which is the camera's
                                           forward; the plan's
                                           "bottom edge" ends up
                                           behind the camera)
        rp.height/100  →  ae.y              (up out of the floor)

    Why this mapping: a reader looking at a plan naturally treats
    "up the page" as "forward in the room". Spawning the camera in
    the room's centre with yaw=0 (facing -Z) makes the plan's top
    edge the wall you walk toward, which preserves left/right from
    the plan in the walkable view. An earlier `ae.z = -rp.y` mapping
    flipped the handedness and caused a left/right mirror whenever
    the user turned 180° to look at the "top of the plan".

    A Floor sits at base_y = sum of heights of the floors below it.
    Rooms on the same floor are laid out in a row with a 2 m gap.

Idempotency: every entity created here gets a name prefix of `rp:`,
so re-export deletes only its own entities and leaves user-added
geometry alone.
"""

from __future__ import annotations

from django.db import transaction

from aether.models import Entity, EntityScript, Script, World

from .models import Building, Floor, Room


PIECE_MESH_SCRIPT_SLUG = 'piece-mesh-render'
PIECE_WIREFRAME_SCRIPT_SLUG = 'piece-wireframe-render'


PREFIX = 'rp:'

# How far apart adjacent rooms sit on the same floor (metres).
ROOM_GAP_M = 2.0

# Wall thickness in metres.
WALL_T_M = 0.10

# Default ceiling height when a floor is missing (cm).
DEFAULT_FLOOR_HEIGHT_CM = 280


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

FLOOR_PANEL_COLOR = '#4a4a4a'
WALL_COLOR = '#cfcfcf'


def _world_for_building(building: Building) -> World:
    slug = f'roomplanner-{building.slug}'
    world, created = World.objects.get_or_create(
        slug=slug,
        defaults={
            'title':        f'{building.name} (Room Planner)',
            'description':  f'Auto-generated walkable export of building "{building.name}".',
            'sky_color':    '#9ab8d6',
            'ground_color': '#2c2c2c',
            'fog_far':      400.0,
            'ambient_light': 0.55,
            'allow_flight': True,
            'spawn_x':      0.0,
            'spawn_y':      1.6,
            'spawn_z':      0.0,
        },
    )
    if not created:
        world.description = f'Auto-generated walkable export of building "{building.name}".'
        world.save(update_fields=['description'])
    return world


def _world_for_room(room: Room) -> World:
    slug = f'roomplanner-{room.slug}'
    world, created = World.objects.get_or_create(
        slug=slug,
        defaults={
            'title':        f'{room.name} (Room Planner)',
            'description':  f'Auto-generated walkable export of room "{room.name}".',
            'sky_color':    '#9ab8d6',
            'ground_color': '#2c2c2c',
            'fog_far':      300.0,
            'ambient_light': 0.55,
            'allow_flight': True,
            'spawn_x':      0.0,
            'spawn_y':      1.6,
            'spawn_z':      0.0,
        },
    )
    return world


def _clear_existing(world: World):
    Entity.objects.filter(world=world, name__startswith=PREFIX).delete()


def _make_box(world, name, x, y, z, sx, sy, sz, color, sort_order=0):
    return Entity(
        world=world,
        name=PREFIX + name,
        primitive='box',
        primitive_color=color,
        pos_x=x, pos_y=y, pos_z=z,
        scale_x=sx, scale_y=sy, scale_z=sz,
        sort_order=sort_order,
    )


def _floor_layout(building: Building):
    """Yield (floor, base_y_metres). Ground floor at 0; each next
    floor stacks on the heights below it."""
    floors = list(Floor.objects.filter(building=building).order_by('level'))
    base = 0.0
    for f in floors:
        yield f, base
        base += (f.height_cm or DEFAULT_FLOOR_HEIGHT_CM) / 100.0


def _room_origin(rooms_on_floor):
    """Yield (room, origin_x_m) for rooms laid out left-to-right on
    a floor, separated by ROOM_GAP_M."""
    cursor = 0.0
    for r in rooms_on_floor:
        w_m = r.width_cm / 100.0
        # Origin is the room's lower-left corner.
        yield r, cursor
        cursor += w_m + ROOM_GAP_M


def _emit_rect_shell(room, world, base_y, origin_x, w_m, d_m, cx, cz,
                     floor_height_m, ents):
    """Original axis-aligned floor + 4 walls path."""
    # Floor slab — 5 cm thick, sitting just at base_y so its top is base_y.
    ents.append(_make_box(
        world, f'floor-{room.slug}',
        cx, base_y - 0.025, cz, w_m, 0.05, d_m,
        FLOOR_PANEL_COLOR, sort_order=0,
    ))

    wall_y = base_y + floor_height_m / 2.0
    ents.append(_make_box(
        world, f'wall-W-{room.slug}',
        origin_x - WALL_T_M / 2.0, wall_y, cz,
        WALL_T_M, floor_height_m, d_m,
        WALL_COLOR, sort_order=1,
    ))
    ents.append(_make_box(
        world, f'wall-E-{room.slug}',
        origin_x + w_m + WALL_T_M / 2.0, wall_y, cz,
        WALL_T_M, floor_height_m, d_m,
        WALL_COLOR, sort_order=1,
    ))
    ents.append(_make_box(
        world, f'wall-N-{room.slug}',
        cx, wall_y, -d_m - WALL_T_M / 2.0,
        w_m, floor_height_m, WALL_T_M,
        WALL_COLOR, sort_order=1,
    ))
    ents.append(_make_box(
        world, f'wall-S-{room.slug}',
        cx, wall_y, WALL_T_M / 2.0,
        w_m, floor_height_m, WALL_T_M,
        WALL_COLOR, sort_order=1,
    ))


def _emit_polygon_shell(room, world, base_y, origin_x, floor_height_m,
                        polygon, ents, scripted, piece_script):
    """Polygon-shaped room: one extruded floor + one thin box per edge.

    `polygon` is a list of [x_cm, y_cm] in plan coords (SVG: +Y down,
    (0,0) at the room's NW bounding-box corner). We map plan_x → ae_x
    via `origin_x + px/100` and plan_y → ae_z via `py/100 - d_m`, so
    the plan's top edge sits at the far wall and the bottom edge lands
    behind spawn — same convention as the rectangular path.
    """
    import math
    d_m = room.length_cm / 100.0

    # ---- Floor: reuse piece-mesh-render with a 5 cm extrusion. The
    # script centres the polygon on its bounding box, so we position
    # the anchor entity at the bbox centre (in aether coords).
    xs = [float(v[0]) for v in polygon]
    ys = [float(v[1]) for v in polygon]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    cx_plan = (minx + maxx) / 2.0
    cy_plan = (miny + maxy) / 2.0
    # piece-mesh-render centres the mesh on its own origin, so
    # pos_y = base_y - thickness/2 puts the slab TOP at base_y —
    # matching the rect path (which also sits the slab top at base_y
    # via pos_y = base_y - 0.025 on a 5 cm box).
    FLOOR_THICKNESS_CM = 5.0
    ae_cx = origin_x + cx_plan / 100.0
    ae_cz = cy_plan / 100.0 - d_m
    floor_ent = Entity(
        world=world,
        name=PREFIX + f'floor-{room.slug}',
        primitive='box', primitive_color=FLOOR_PANEL_COLOR,
        pos_x=ae_cx,
        pos_y=base_y - (FLOOR_THICKNESS_CM / 100.0) / 2.0,
        pos_z=ae_cz,
        scale_x=1.0, scale_y=1.0, scale_z=1.0,
        behavior='scripted',
        sort_order=0,
    )
    # The script expects polygon coords in an XZ-like plane (it treats
    # the input as [x, y] in the Shape plane, then rotateX(-π/2) turns
    # that Y into aether -Z). To land plan_y at aether_z = py/100 - d_m,
    # pass the plan polygon verbatim — the script's bbox-centring + the
    # rotate flip produces the right layout once the entity is anchored
    # at (ae_cx, base_y, ae_cz).
    scripted.append((
        floor_ent,
        {
            'polygon': [[float(v[0]), float(v[1])] for v in polygon],
            'heightCm': FLOOR_THICKNESS_CM,
            'color': FLOOR_PANEL_COLOR,
        },
    ))

    # ---- Walls: one box per polygon edge.
    wall_y = base_y + floor_height_m / 2.0
    n = len(polygon)
    for i in range(n):
        px1, py1 = float(polygon[i][0]), float(polygon[i][1])
        px2, py2 = float(polygon[(i + 1) % n][0]), float(polygon[(i + 1) % n][1])
        # Endpoints in aether coords.
        ax1 = origin_x + px1 / 100.0
        az1 = py1 / 100.0 - d_m
        ax2 = origin_x + px2 / 100.0
        az2 = py2 / 100.0 - d_m
        dx = ax2 - ax1
        dz = az2 - az1
        length_m = math.hypot(dx, dz)
        if length_m < 1e-6:
            continue
        mx = (ax1 + ax2) / 2.0
        mz = (az1 + az2) / 2.0
        # Box scale_x aligned with +X by default. We want it to point
        # along the edge direction (dx, dz); in three.js rot_y rotates
        # from +X toward -Z, so rot_y = atan2(-dz, dx).
        rot_y_rad = math.atan2(-dz, dx)
        rot_y_deg = math.degrees(rot_y_rad)
        # Extend length slightly so adjacent walls overlap at corners.
        ents.append(Entity(
            world=world,
            name=PREFIX + f'wall-{i}-{room.slug}',
            primitive='box', primitive_color=WALL_COLOR,
            pos_x=mx, pos_y=wall_y, pos_z=mz,
            scale_x=length_m + WALL_T_M,
            scale_y=floor_height_m,
            scale_z=WALL_T_M,
            rot_y=rot_y_deg,
            sort_order=1,
        ))


def _emit_room(room: Room, world: World, base_y: float, origin_x: float,
               floor_height_m: float, ents: list,
               scripted: list, piece_script):
    """Append all primitives for one room to `ents`.

    Pieces without real geometry become plain box entities in `ents`.
    Pieces whose `geometry` is `{type: 'extrusion', ...}` become
    scripted entities in `scripted` — (Entity, props) tuples that the
    caller saves one-by-one so each row's PK is available for the
    matching EntityScript attachment. If `piece_script` is None
    (script not seeded), every piece falls back to a box.

    When `room.polygon_cm` is set the floor becomes an extruded polygon
    and walls become one thin box per polygon edge; otherwise the four
    axis-aligned walls + rectangular floor path is used.
    """
    w_m = room.width_cm  / 100.0  # X extent (plan bounding box)
    d_m = room.length_cm / 100.0  # Z extent (plan bounding box)
    cx = origin_x + w_m / 2.0
    # Rooms extend from ae_z=-d_m (plan top edge, y=0) to ae_z=0 (plan
    # bottom edge). Camera spawns at the centre facing -Z, so the plan's
    # "up the page" direction is what the user walks toward.
    cz = -d_m / 2.0

    polygon = list(room.polygon_cm or [])
    if len(polygon) >= 3 and piece_script is not None:
        _emit_polygon_shell(room, world, base_y, origin_x, floor_height_m,
                            polygon, ents, scripted, piece_script)
    else:
        _emit_rect_shell(room, world, base_y, origin_x, w_m, d_m, cx, cz,
                         floor_height_m, ents)

    # Features: small boxes near the floor.
    for feat in room.features.all():
        fw = feat.width_cm / 100.0
        fd = feat.depth_cm / 100.0
        fh = 0.4 if feat.kind != 'window' else 0.6
        # Centre in plan coords:
        plan_cx = feat.x_cm / 100.0 + fw / 2.0
        plan_cy = feat.y_cm / 100.0 + fd / 2.0
        ae_x = origin_x + plan_cx
        ae_z = plan_cy - d_m
        ae_y = base_y + (fh / 2.0 if feat.kind != 'window'
                         else floor_height_m / 2.0)
        color = FEATURE_COLORS.get(feat.kind, FEATURE_COLORS['other'])
        ents.append(_make_box(
            world,
            f'feature-{feat.kind}-{feat.pk}',
            ae_x, ae_y, ae_z,
            fw, fh, fd,
            color, sort_order=10,
        ))

    # Placements: box per furniture piece, height from FurniturePiece.height_cm
    # (fall back to a reasonable default by kind).
    # Wireframe script (optional, separate from the extrusion mesh
    # script). Looked up here so _emit_room only needs the mesh script
    # passed in; this is module-local and cheap.
    wireframe_script = Script.objects.filter(
        slug=PIECE_WIREFRAME_SCRIPT_SLUG).first()

    for pl in room.placements.select_related('piece').all():
        piece = pl.piece
        geom = piece.geometry or {}
        is_extrusion = (piece_script is not None
                        and geom.get('type') == 'extrusion'
                        and geom.get('polygon'))
        is_wireframe = (wireframe_script is not None
                        and geom.get('type') == 'wireframe'
                        and geom.get('vertices')
                        and geom.get('edges'))

        # Rotation 90/270 swaps W and D in plan footprint.
        w_plan = piece.width_cm
        d_plan = piece.depth_cm
        if pl.rotation_deg in (90, 270):
            w_plan, d_plan = d_plan, w_plan

        pw = w_plan / 100.0
        pd = d_plan / 100.0
        ph_cm = piece.height_cm or _default_height_cm(piece.kind)
        ph = ph_cm / 100.0

        plan_cx = pl.x_cm / 100.0 + pw / 2.0
        plan_cy = pl.y_cm / 100.0 + pd / 2.0
        ae_x = origin_x + plan_cx
        ae_z = plan_cy - d_m
        ae_y = base_y + ph / 2.0
        color = PIECE_COLORS.get(piece.kind, PIECE_COLORS['other'])

        # Map roomplanner rotation (around floor normal = +Y in Aether)
        # to rot_y degrees. rotation_deg goes 0/90/180/270 clockwise on the
        # plan (which looks down -Y in three.js); negate for handedness.
        if is_extrusion:
            # The polygon lives in un-rotated local cm coords; rot_y
            # handles orientation, so we don't swap polygon vertices.
            # The piece-mesh-render script centres the mesh on its own
            # origin, so pos_y = base_y + height/2 puts the bottom on
            # the floor — same anchor convention as the plain box path.
            h_cm = geom.get('height_cm') or ph_cm
            scripted.append((
                Entity(
                    world=world,
                    name=PREFIX + f'piece-{pl.pk}',
                    primitive='box', primitive_color=color,
                    pos_x=ae_x, pos_y=base_y + (h_cm / 100.0) / 2.0,
                    pos_z=ae_z,
                    scale_x=1.0, scale_y=1.0, scale_z=1.0,
                    rot_y=-(pl.rotation_deg or 0),
                    behavior='scripted',
                    sort_order=20,
                ),
                {
                    'polygon': list(geom['polygon']),
                    'heightCm': h_cm,
                    'color': color,
                },
                piece_script,
            ))
        elif is_wireframe:
            # Vertices in cm with (0,0,0) at SW-bottom corner; the
            # wireframe script centres the bounding-box and the
            # entity's pos_y = base_y + ph/2 puts the bottom on the
            # floor.
            scripted.append((
                Entity(
                    world=world,
                    name=PREFIX + f'piece-{pl.pk}',
                    primitive='box', primitive_color=color,
                    pos_x=ae_x, pos_y=ae_y, pos_z=ae_z,
                    scale_x=1.0, scale_y=1.0, scale_z=1.0,
                    rot_y=-(pl.rotation_deg or 0),
                    behavior='scripted',
                    sort_order=20,
                ),
                {
                    'vertices': list(geom['vertices']),
                    'edges':    list(geom['edges']),
                    'color':    geom.get('color') or color,
                    'lineWidth': geom.get('line_width', 2),
                },
                wireframe_script,
            ))
        else:
            ents.append(_make_box(
                world,
                f'piece-{pl.pk}',
                ae_x, ae_y, ae_z,
                pw, ph, pd,
                color, sort_order=20,
            ))


def _default_height_cm(kind: str) -> int:
    """Reasonable fallback heights when the catalog entry didn't set one."""
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


def _attach_scripts(scripted, piece_script):
    """Save scripted entities one-by-one (each needs a PK) and attach
    the right Aether script to each. Tuples can be either the legacy
    2-tuple `(Entity, props)` (uses `piece_script`) or the new
    3-tuple `(Entity, props, script)` so wireframe and mesh entities
    can coexist in one export."""
    attachments = []
    for item in scripted:
        if len(item) == 3:
            ent, props, script = item
        else:
            ent, props = item
            script = piece_script
        if script is None:
            ent.save()
            continue
        ent.save()
        attachments.append(EntityScript(
            entity=ent, script=script, props=props,
        ))
    EntityScript.objects.bulk_create(attachments)


@transaction.atomic
def export_building(building: Building) -> World:
    world = _world_for_building(building)
    _clear_existing(world)
    piece_script = Script.objects.filter(
        slug=PIECE_MESH_SCRIPT_SLUG).first()

    ents: list = []
    scripted: list = []
    spawn_set = False
    for floor, base_y in _floor_layout(building):
        floor_h_m = (floor.height_cm or DEFAULT_FLOOR_HEIGHT_CM) / 100.0
        rooms = list(Room.objects.filter(floor=floor).order_by('name'))
        for room, origin_x in _room_origin(rooms):
            _emit_room(room, world, base_y, origin_x, floor_h_m,
                       ents, scripted, piece_script)
            if not spawn_set:
                # Spawn at the centre of the first room on the lowest
                # floor, eyeline 1.6 m above the slab.
                w_m = room.width_cm / 100.0
                d_m = room.length_cm / 100.0
                world.spawn_x = origin_x + w_m / 2.0
                world.spawn_y = base_y + 1.6
                world.spawn_z = -d_m / 2.0
                world.save(update_fields=['spawn_x', 'spawn_y', 'spawn_z'])
                spawn_set = True

    Entity.objects.bulk_create(ents)
    _attach_scripts(scripted, piece_script)
    return world


@transaction.atomic
def export_room(room: Room) -> World:
    """Single-room shortcut. Floors are not stacked; the room sits at Y=0."""
    world = _world_for_room(room)
    _clear_existing(world)
    piece_script = Script.objects.filter(
        slug=PIECE_MESH_SCRIPT_SLUG).first()

    floor_h_m = ((room.floor.height_cm if room.floor else DEFAULT_FLOOR_HEIGHT_CM)
                 / 100.0)
    ents: list = []
    scripted: list = []
    _emit_room(room, world, base_y=0.0, origin_x=0.0,
               floor_height_m=floor_h_m, ents=ents,
               scripted=scripted, piece_script=piece_script)

    w_m = room.width_cm / 100.0
    d_m = room.length_cm / 100.0
    world.spawn_x = w_m / 2.0
    world.spawn_y = 1.6
    world.spawn_z = -d_m / 2.0
    world.save(update_fields=['spawn_x', 'spawn_y', 'spawn_z'])

    Entity.objects.bulk_create(ents)
    _attach_scripts(scripted, piece_script)
    return world


def export_summary(world: World) -> dict:
    qs = Entity.objects.filter(world=world, name__startswith=PREFIX)
    by_prefix = {}
    for name in qs.values_list('name', flat=True):
        # rp:floor-..., rp:wall-W-..., rp:feature-door-..., rp:piece-...
        bare = name[len(PREFIX):]
        kind = bare.split('-', 1)[0]
        by_prefix[kind] = by_prefix.get(kind, 0) + 1
    return {
        'total':   qs.count(),
        'by_kind': by_prefix,
        'world_slug': world.slug,
    }
