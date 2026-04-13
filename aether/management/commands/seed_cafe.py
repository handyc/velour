"""Seed a fully populated cafe demo world with NPCs, furniture, and props."""

from django.core.management.base import BaseCommand

from aether.models import Entity, EntityScript, Portal, Script, World


# --- Cafe layout constants ---
# The cafe is ~16m x 12m. Kitchen in back (z < -8), counter at z=-6,
# tables in the main area (z = -4 to 4), entrance at z=6.

CAFE_TABLES = [
    # (x, z, seats) — each table is a cylinder, chairs around it
    (-4.0, -3.0, 2),
    (-4.0,  0.0, 2),
    (-4.0,  3.0, 2),
    ( 0.0, -3.0, 4),
    ( 0.0,  1.0, 4),
    ( 4.0, -3.0, 2),
    ( 4.0,  0.0, 2),
    ( 4.0,  3.0, 2),
]

KITCHEN_CENTER = (0.0, 0.0, -9.5)

# NPC skin tones and shirt colors for variety
NPC_COLORS = [
    '#d4a373', '#8d5524', '#c68642', '#e0ac69', '#f1c27d',
    '#ffdbac', '#a0522d', '#cd853f', '#deb887', '#d2691e', '#8b6914',
]
SHIRT_COLORS = [
    '#4a6fa5', '#c23b22', '#6b8e23', '#8b4513', '#483d8b',
    '#2f4f4f', '#b22222', '#556b2f', '#4682b4', '#8b0000', '#2e8b57',
]


class Command(BaseCommand):
    help = 'Create the Velour Cafe demo world with 11 NPCs and ~80 objects.'

    def handle(self, *args, **options):
        # Delete existing cafe if re-running
        World.objects.filter(slug='velour-cafe').delete()

        world = World.objects.create(
            title='Velour Cafe',
            slug='velour-cafe',
            description='A cozy cafe with 11 NPCs, an AI waiter, ambient jazz, '
                        'and handcrafted primitive geometry.',
            skybox='procedural',
            sky_color='#87CEEB',
            ground_color='#5c4033',
            ground_size=30.0,
            ambient_light=0.5,
            fog_near=25.0,
            fog_far=60.0,
            fog_color='#d4c5b0',
            gravity=-9.81,
            allow_flight=False,
            spawn_x=0.0,
            spawn_y=1.6,
            spawn_z=6.0,
            ambient_audio_url='https://stream.zeno.fm/0r0xa792kwzuv',
            ambient_volume=0.3,
            soundscape='cafe',
            published=True,
            featured=True,
        )

        # --- Scripts ---
        waiter_script = _get_or_create_script(
            'Waiter Patrol',
            'update',
            WAITER_SCRIPT,
            'AI waiter: patrol tables, pick up dishes, deliver to kitchen.',
        )
        patron_sit_script = _get_or_create_script(
            'Patron Seated',
            'update',
            PATRON_SEATED_SCRIPT,
            'Seated patron: idle fidget, occasional head turn.',
        )
        patron_wander_script = _get_or_create_script(
            'Patron Wander',
            'update',
            PATRON_WANDER_SCRIPT,
            'Standing patron: wander slowly between areas.',
        )
        barista_script = _get_or_create_script(
            'Barista Work',
            'update',
            BARISTA_SCRIPT,
            'Barista: shift weight, lean, occasional reach animation.',
        )
        interact_greet = _get_or_create_script(
            'NPC Greet',
            'interact',
            NPC_GREET_SCRIPT,
            'When clicked, NPC turns to face player briefly.',
        )

        entities = []

        # --- Floor ---
        entities.append(_ent(world, 'Cafe Floor', 'box', '#6b4226',
                              0, -0.05, -2, sx=18, sy=0.1, sz=16, shadow=False))

        # --- Walls ---
        entities.append(_ent(world, 'Back Wall', 'box', '#8b7355',
                              0, 1.5, -10.5, sx=18, sy=3, sz=0.2))
        entities.append(_ent(world, 'Left Wall', 'box', '#8b7355',
                              -9, 1.5, -2, sx=0.2, sy=3, sz=16))
        entities.append(_ent(world, 'Right Wall', 'box', '#8b7355',
                              9, 1.5, -2, sx=0.2, sy=3, sz=16))

        # --- Counter ---
        entities.append(_ent(world, 'Counter', 'box', '#5c3317',
                              0, 0.55, -6, sx=6, sy=1.1, sz=0.8))
        entities.append(_ent(world, 'Counter Top', 'box', '#d2b48c',
                              0, 1.12, -6, sx=6.1, sy=0.04, sz=0.9))

        # --- Kitchen area ---
        entities.append(_ent(world, 'Kitchen Counter', 'box', '#696969',
                              0, 0.45, -9, sx=4, sy=0.9, sz=0.6))
        entities.append(_ent(world, 'Oven', 'box', '#2f2f2f',
                              -3, 0.5, -9.5, sx=1.2, sy=1.0, sz=0.8))
        entities.append(_ent(world, 'Fridge', 'box', '#c0c0c0',
                              3, 0.9, -9.5, sx=0.8, sy=1.8, sz=0.7))
        entities.append(_ent(world, 'Sink', 'box', '#a9a9a9',
                              1.5, 0.45, -9, sx=0.8, sy=0.9, sz=0.6))

        # --- Coffee machine on counter ---
        entities.append(_ent(world, 'Coffee Machine', 'box', '#1a1a1a',
                              -1.5, 1.35, -6, sx=0.5, sy=0.6, sz=0.4))
        entities.append(_ent(world, 'Cash Register', 'box', '#2a2a2a',
                              1.5, 1.25, -6, sx=0.4, sy=0.3, sz=0.3))

        # --- Menu board ---
        entities.append(_ent(world, 'Menu Board', 'box', '#1a1a1a',
                              0, 2.5, -10.4, sx=2.5, sy=1.2, sz=0.05))

        # --- Tables, chairs, and tableware ---
        table_positions = []
        for i, (tx, tz, seats) in enumerate(CAFE_TABLES):
            table_positions.append((tx, tz))
            # Table (cylinder)
            entities.append(_ent(world, f'Table {i+1}', 'cylinder', '#5c3317',
                                  tx, 0.38, tz, sx=0.9, sy=0.76, sz=0.9))
            # Table top (thin cylinder)
            entities.append(_ent(world, f'Tabletop {i+1}', 'cylinder', '#d2b48c',
                                  tx, 0.77, tz, sx=1.0, sy=0.04, sz=1.0, shadow=False))

            # Chairs
            chair_offsets = [(-0.6, 0), (0.6, 0)] if seats == 2 else \
                            [(-0.6, -0.5), (0.6, -0.5), (-0.6, 0.5), (0.6, 0.5)]
            for ci, (cx, cz) in enumerate(chair_offsets):
                # Seat
                entities.append(_ent(world, f'Chair {i+1}{chr(65+ci)}', 'box', '#8b6914',
                                      tx+cx, 0.28, tz+cz, sx=0.4, sy=0.06, sz=0.4))
                # Backrest
                back_z = tz + cz + (0.2 if cz >= 0 else -0.2)
                entities.append(_ent(world, f'Backrest {i+1}{chr(65+ci)}', 'box', '#8b6914',
                                      tx+cx, 0.52, back_z, sx=0.4, sy=0.5, sz=0.04,
                                      shadow=False))

            # Tableware on each table
            entities.append(_ent(world, f'Cup {i+1}', 'cylinder', '#f5f5dc',
                                  tx+0.15, 0.83, tz-0.1, sx=0.06, sy=0.08, sz=0.06,
                                  shadow=False))
            entities.append(_ent(world, f'Saucer {i+1}', 'cylinder', '#f5f5dc',
                                  tx+0.15, 0.79, tz-0.1, sx=0.1, sy=0.015, sz=0.1,
                                  shadow=False))
            entities.append(_ent(world, f'Plate {i+1}', 'cylinder', '#fafafa',
                                  tx-0.15, 0.79, tz+0.1, sx=0.14, sy=0.015, sz=0.14,
                                  shadow=False))
            if seats == 4:
                # Extra place settings for 4-seat tables
                entities.append(_ent(world, f'Cup {i+1}b', 'cylinder', '#f5f5dc',
                                      tx-0.2, 0.83, tz-0.15, sx=0.06, sy=0.08, sz=0.06,
                                      shadow=False))
                entities.append(_ent(world, f'Glass {i+1}', 'cylinder', '#b0e0e6',
                                      tx+0.25, 0.84, tz+0.15, sx=0.04, sy=0.1, sz=0.04,
                                      shadow=False))

            # Cutlery (tiny boxes)
            entities.append(_ent(world, f'Fork {i+1}', 'box', '#c0c0c0',
                                  tx-0.3, 0.79, tz+0.08, sx=0.015, sy=0.005, sz=0.12,
                                  shadow=False))
            entities.append(_ent(world, f'Spoon {i+1}', 'box', '#c0c0c0',
                                  tx-0.32, 0.79, tz+0.08, sx=0.015, sy=0.005, sz=0.12,
                                  shadow=False))

        # --- Ingredient bags and boxes on kitchen counter ---
        entities.append(_ent(world, 'Coffee Beans Bag', 'box', '#3e2723',
                              -0.5, 0.95, -9, sx=0.25, sy=0.35, sz=0.15))
        entities.append(_ent(world, 'Sugar Box', 'box', '#fff8dc',
                              0.3, 0.95, -9, sx=0.2, sy=0.25, sz=0.15))
        entities.append(_ent(world, 'Flour Bag', 'box', '#faebd7',
                              -1.0, 0.95, -9, sx=0.3, sy=0.3, sz=0.2))
        entities.append(_ent(world, 'Tea Box', 'box', '#228b22',
                              0.8, 0.95, -9, sx=0.15, sy=0.2, sz=0.1))
        entities.append(_ent(world, 'Milk Carton', 'box', '#f0f0f0',
                              -0.2, 0.95, -9.3, sx=0.1, sy=0.25, sz=0.1))
        entities.append(_ent(world, 'Cocoa Tin', 'cylinder', '#4a2c0a',
                              0.5, 0.95, -9.3, sx=0.08, sy=0.2, sz=0.08))

        # --- Drinking glasses on counter ---
        for gi in range(4):
            entities.append(_ent(world, f'Counter Glass {gi+1}', 'cylinder', '#d4f1f9',
                                  -2.2 + gi*0.3, 1.2, -5.7, sx=0.04, sy=0.12, sz=0.04,
                                  shadow=False))

        # --- Decor ---
        entities.append(_ent(world, 'Plant 1', 'sphere', '#2e7d32',
                              -8, 0.5, 4, sx=0.6, sy=0.8, sz=0.6))
        entities.append(_ent(world, 'Plant Pot 1', 'cylinder', '#8d6e63',
                              -8, 0.2, 4, sx=0.3, sy=0.4, sz=0.3))
        entities.append(_ent(world, 'Plant 2', 'sphere', '#388e3c',
                              8, 0.5, 4, sx=0.5, sy=0.7, sz=0.5))
        entities.append(_ent(world, 'Plant Pot 2', 'cylinder', '#8d6e63',
                              8, 0.2, 4, sx=0.3, sy=0.4, sz=0.3))

        # --- Ceiling lights (glowing spheres, no shadow) ---
        for lx in [-4, 0, 4]:
            for lz in [-3, 1, 5]:
                entities.append(_ent(world, f'Light {lx},{lz}', 'sphere', '#fff5e1',
                                      lx, 2.8, lz, sx=0.15, sy=0.15, sz=0.15,
                                      shadow=False, behavior='bob', speed=0.3))

        # --- NPCs ---
        # NPC 0: AI Waiter
        waiter = _npc(world, 'Marco the Waiter', NPC_COLORS[0], '#ffffff',
                       0, 0, -5, behavior='scripted')
        entities.append(waiter)

        # NPC 1-2: Baristas behind counter
        barista1 = _npc(world, 'Ava', NPC_COLORS[1], SHIRT_COLORS[1],
                         -1, 0, -7, ry=180, behavior='scripted')
        barista2 = _npc(world, 'Sam', NPC_COLORS[2], SHIRT_COLORS[2],
                         1.5, 0, -7, ry=180, behavior='scripted')
        entities.append(barista1)
        entities.append(barista2)

        # NPC 3-6: Seated patrons at 4-seat tables
        seated_tables = [(i, tx, tz) for i, (tx, tz, s) in enumerate(CAFE_TABLES) if s == 4]
        patrons_seated = []
        for pi, (ti, tx, tz) in enumerate(seated_tables):
            for si, (ox, oz) in enumerate([(-0.6, -0.5), (0.6, -0.5)]):
                idx = 3 + pi * 2 + si
                name = ['Kenji', 'Liu', 'Rosa', 'Dante'][pi * 2 + si]
                npc = _npc(world, name, NPC_COLORS[idx], SHIRT_COLORS[idx],
                           tx+ox, 0, tz+oz, behavior='scripted')
                entities.append(npc)
                patrons_seated.append(npc)

        # NPC 7-8: Seated patrons at 2-seat tables
        two_seat = [(i, tx, tz) for i, (tx, tz, s) in enumerate(CAFE_TABLES) if s == 2]
        for pi, (ti, tx, tz) in enumerate(two_seat[:2]):
            idx = 7 + pi
            name = ['Yara', 'Benny'][pi]
            npc = _npc(world, name, NPC_COLORS[idx], SHIRT_COLORS[idx],
                       tx-0.6, 0, tz, behavior='scripted')
            entities.append(npc)
            patrons_seated.append(npc)

        # NPC 9-10: Wandering patrons (just arrived / browsing)
        wander1 = _npc(world, 'Cleo', NPC_COLORS[9], SHIRT_COLORS[9],
                        3, 0, 4, behavior='scripted')
        wander2 = _npc(world, 'Felix', NPC_COLORS[10], SHIRT_COLORS[10],
                        -3, 0, 3, behavior='scripted')
        entities.append(wander1)
        entities.append(wander2)

        # Bulk create all non-NPC entities
        non_npc = [e for e in entities if not hasattr(e, '_is_npc')]
        Entity.objects.bulk_create(non_npc)

        # Save NPC entities individually (need PKs for scripts)
        npc_entities = [e for e in entities if hasattr(e, '_is_npc')]
        for e in npc_entities:
            e.save()

        # --- Attach scripts ---
        script_attachments = []

        # Waiter gets the patrol script with table positions as props
        script_attachments.append(EntityScript(
            entity=waiter, script=waiter_script,
            props={
                'tables': [[tx, 0.79, tz] for tx, tz in table_positions],
                'kitchen': list(KITCHEN_CENTER),
                'speed': 2.0,
            },
        ))
        script_attachments.append(EntityScript(
            entity=waiter, script=interact_greet, props={'greeting': 'One moment please!'},
        ))

        # Baristas
        for b in [barista1, barista2]:
            script_attachments.append(EntityScript(
                entity=b, script=barista_script, props={},
            ))
            script_attachments.append(EntityScript(
                entity=b, script=interact_greet, props={'greeting': 'What can I get you?'},
            ))

        # Seated patrons
        for p in patrons_seated:
            script_attachments.append(EntityScript(
                entity=p, script=patron_sit_script, props={},
            ))
            script_attachments.append(EntityScript(
                entity=p, script=interact_greet, props={'greeting': 'Hey there!'},
            ))

        # Wanderers
        for w in [wander1, wander2]:
            script_attachments.append(EntityScript(
                entity=w, script=patron_wander_script,
                props={'bounds': [-7, -4, 7, 5], 'speed': 0.8},
            ))
            script_attachments.append(EntityScript(
                entity=w, script=interact_greet,
                props={'greeting': 'Just looking around!'},
            ))

        EntityScript.objects.bulk_create(script_attachments)

        total = Entity.objects.filter(world=world).count()
        npc_count = len(npc_entities)
        self.stdout.write(self.style.SUCCESS(
            f'Velour Cafe created: {total} entities ({npc_count} NPCs), '
            f'{len(script_attachments)} script attachments.'
        ))


def _ent(world, name, prim, color, x, y, z,
         sx=1, sy=1, sz=1, rx=0, ry=0, rz=0,
         shadow=True, behavior='static', speed=1.0):
    return Entity(
        world=world, name=name, primitive=prim, primitive_color=color,
        pos_x=x, pos_y=y, pos_z=z,
        rot_x=rx, rot_y=ry, rot_z=rz,
        scale_x=sx, scale_y=sy, scale_z=sz,
        cast_shadow=shadow, receive_shadow=shadow,
        behavior=behavior, behavior_speed=speed,
    )


def _npc(world, name, skin_color, shirt_color, x, y, z,
         rx=0, ry=0, rz=0, behavior='static'):
    """Create a humanoid NPC as a group of primitives.

    Since we can't group primitives in a single Entity, we use a
    cylinder (body) as the root. The script will create the head
    and limbs dynamically on first frame using ctx.state.
    The body color encodes the shirt; skin is in props.
    """
    e = Entity(
        world=world, name=name, primitive='cylinder',
        primitive_color=shirt_color,
        pos_x=x, pos_y=y + 0.65, pos_z=z,
        rot_x=rx, rot_y=ry, rot_z=rz,
        scale_x=0.35, scale_y=0.7, scale_z=0.25,
        cast_shadow=True, receive_shadow=False,
        behavior=behavior, behavior_speed=1.0,
    )
    e._is_npc = True
    e._skin_color = skin_color
    return e


def _get_or_create_script(name, event, code, description=''):
    script, _ = Script.objects.get_or_create(
        slug=name.lower().replace(' ', '-'),
        defaults={
            'name': name,
            'event': event,
            'code': code,
            'description': description,
        },
    )
    if script.code != code:
        script.code = code
        script.save()
    return script


# ---------------------------------------------------------------------------
# NPC Scripts — executed client-side in the three.js animation loop
# ---------------------------------------------------------------------------

WAITER_SCRIPT = """\
// AI Waiter: patrol tables picking up dishes, deliver to kitchen
if (!ctx.state.init) {
    ctx.state.init = true;
    ctx.state.phase = 'goto_table';
    ctx.state.tableIdx = 0;
    ctx.state.tables = ctx.props.tables || [[0,0.79,-3]];
    ctx.state.kitchen = ctx.props.kitchen || [0,0,-9.5];
    ctx.state.speed = ctx.props.speed || 2.0;
    ctx.state.waitTimer = 0;
    ctx.state.carrying = false;

    // Build head + limbs
    const head = new THREE.Mesh(
        new THREE.SphereGeometry(0.15, 16, 16),
        new THREE.MeshStandardMaterial({color: '#d4a373'})
    );
    head.position.y = 0.55;
    ctx.entity.add(head);

    // Tray (visible when carrying)
    const tray = new THREE.Mesh(
        new THREE.CylinderGeometry(0.2, 0.2, 0.03, 16),
        new THREE.MeshStandardMaterial({color: '#8b4513'})
    );
    tray.position.set(0.35, 0.3, 0);
    tray.visible = false;
    ctx.entity.add(tray);
    ctx.state.tray = tray;
}

const s = ctx.state;
const speed = s.speed * ctx.deltaTime;

function moveTo(target) {
    const dx = target[0] - ctx.entity.position.x;
    const dz = target[2] - ctx.entity.position.z;
    const dist = Math.sqrt(dx*dx + dz*dz);
    if (dist < 0.3) return true;
    const step = Math.min(speed, dist);
    ctx.entity.position.x += (dx / dist) * step;
    ctx.entity.position.z += (dz / dist) * step;
    ctx.entity.rotation.y = Math.atan2(dx, dz);
    return false;
}

if (s.phase === 'goto_table') {
    const table = s.tables[s.tableIdx];
    if (moveTo(table)) {
        s.phase = 'pickup';
        s.waitTimer = 0;
    }
} else if (s.phase === 'pickup') {
    s.waitTimer += ctx.deltaTime;
    // Bend down briefly
    ctx.entity.rotation.x = Math.sin(s.waitTimer * 4) * 0.15;
    if (s.waitTimer > 1.0) {
        ctx.entity.rotation.x = 0;
        s.carrying = true;
        s.tray.visible = true;
        s.phase = 'goto_kitchen';
    }
} else if (s.phase === 'goto_kitchen') {
    if (moveTo(s.kitchen)) {
        s.phase = 'dropoff';
        s.waitTimer = 0;
    }
} else if (s.phase === 'dropoff') {
    s.waitTimer += ctx.deltaTime;
    if (s.waitTimer > 0.8) {
        s.carrying = false;
        s.tray.visible = false;
        s.tableIdx = (s.tableIdx + 1) % s.tables.length;
        s.phase = 'goto_table';
    }
}
"""

PATRON_SEATED_SCRIPT = """\
// Seated patron: subtle idle animation
if (!ctx.state.init) {
    ctx.state.init = true;
    ctx.state.phase = 0;
    // Head
    const head = new THREE.Mesh(
        new THREE.SphereGeometry(0.14, 16, 16),
        new THREE.MeshStandardMaterial({color: '#d4a373'})
    );
    head.position.y = 0.52;
    ctx.entity.add(head);
    ctx.state.head = head;
    // Sit lower
    ctx.entity.position.y -= 0.2;
}
ctx.state.phase += ctx.deltaTime;
// Gentle head turn
ctx.state.head.rotation.y = Math.sin(ctx.state.phase * 0.3 + ctx.entity.position.x * 7) * 0.3;
// Very slight body sway
ctx.entity.rotation.z = Math.sin(ctx.state.phase * 0.2 + ctx.entity.position.z * 5) * 0.02;
"""

PATRON_WANDER_SCRIPT = """\
// Wandering patron: slow walk within bounds
if (!ctx.state.init) {
    ctx.state.init = true;
    const b = ctx.props.bounds || [-7, -4, 7, 5];
    ctx.state.bounds = {minX: b[0], minZ: b[1], maxX: b[2], maxZ: b[3]};
    ctx.state.target = null;
    ctx.state.waitTimer = 0;
    ctx.state.speed = ctx.props.speed || 0.8;
    ctx.state.walking = false;
    // Head
    const head = new THREE.Mesh(
        new THREE.SphereGeometry(0.14, 16, 16),
        new THREE.MeshStandardMaterial({color: '#d4a373'})
    );
    head.position.y = 0.52;
    ctx.entity.add(head);
    ctx.state.head = head;
}
const s = ctx.state;
if (!s.walking) {
    s.waitTimer += ctx.deltaTime;
    if (s.waitTimer > 2 + Math.random() * 3) {
        const b = s.bounds;
        s.target = {
            x: b.minX + Math.random() * (b.maxX - b.minX),
            z: b.minZ + Math.random() * (b.maxZ - b.minZ),
        };
        s.walking = true;
        s.waitTimer = 0;
    }
    // Idle: look around
    s.head.rotation.y = Math.sin(ctx.elapsed * 0.5 + ctx.entity.position.x) * 0.4;
} else {
    const dx = s.target.x - ctx.entity.position.x;
    const dz = s.target.z - ctx.entity.position.z;
    const dist = Math.sqrt(dx*dx + dz*dz);
    if (dist < 0.3) {
        s.walking = false;
    } else {
        const step = Math.min(s.speed * ctx.deltaTime, dist);
        ctx.entity.position.x += (dx / dist) * step;
        ctx.entity.position.z += (dz / dist) * step;
        ctx.entity.rotation.y = Math.atan2(dx, dz);
        // Walk bob
        ctx.entity.position.y = 0.65 + Math.sin(ctx.elapsed * 8) * 0.02;
    }
}
"""

BARISTA_SCRIPT = """\
// Barista: shift weight, reach for cups
if (!ctx.state.init) {
    ctx.state.init = true;
    ctx.state.phase = 0;
    const head = new THREE.Mesh(
        new THREE.SphereGeometry(0.14, 16, 16),
        new THREE.MeshStandardMaterial({color: '#d4a373'})
    );
    head.position.y = 0.52;
    ctx.entity.add(head);
    ctx.state.head = head;
}
ctx.state.phase += ctx.deltaTime;
const p = ctx.state.phase;
// Weight shift
ctx.entity.position.x += Math.sin(p * 0.4) * 0.001;
// Occasional reach
ctx.entity.rotation.z = Math.sin(p * 0.15) * 0.06;
ctx.state.head.rotation.y = Math.sin(p * 0.25) * 0.3;
"""

NPC_GREET_SCRIPT = """\
// On interact: turn toward player briefly
if (!ctx.state.greetTimer) {
    ctx.state.greetTimer = 0;
    ctx.state.origRotY = ctx.entity.rotation.y;
}
// Face player
const dx = ctx.camera.position.x - ctx.entity.position.x;
const dz = ctx.camera.position.z - ctx.entity.position.z;
ctx.entity.rotation.y = Math.atan2(dx, dz);
// Log greeting
const msg = ctx.props.greeting || 'Hello!';
console.log(ctx.entity.userData.entityName + ': ' + msg);
"""
