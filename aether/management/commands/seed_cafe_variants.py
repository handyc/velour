"""Seed three Velour Cafe variants: Gun Cafe, Animal Cafe, Jungle Cafe.

Each reuses the humanoid-builder and animation scripts already registered
by seed_cafe_hdri.  The furniture/layout is shared; themes differ in
decor, NPCs, and extra scripts.
"""

from django.core.management.base import BaseCommand

from aether.models import Entity, EntityScript, Script, World

import random


# ---------------------------------------------------------------------------
# Shared cafe layout helpers
# ---------------------------------------------------------------------------

def _ent(world, name, prim, color, x, y, z,
         sx=1, sy=1, sz=1, rx=0, ry=0, rz=0,
         shadow=True, behavior='static', speed=1.0):
    return Entity(
        world=world, name=name, primitive=prim, primitive_color=color,
        pos_x=x, pos_y=y, pos_z=z, rot_x=rx, rot_y=ry, rot_z=rz,
        scale_x=sx, scale_y=sy, scale_z=sz,
        cast_shadow=shadow, receive_shadow=shadow,
        behavior=behavior, behavior_speed=speed,
    )


CAFE_TABLES = [
    (-4.0, -3.0, 2), (-4.0, 0.0, 2), (-4.0, 3.0, 2),
    (0.0, -3.0, 4), (0.0, 1.0, 4),
    (4.0, -3.0, 2), (4.0, 0.0, 2), (4.0, 3.0, 2),
]


def build_cafe_shell(world, entities, wall_color='#8b7355', floor_color='#6b4226',
                     counter_color='#5c3317', top_color='#d2b48c'):
    """Shared walls, floor, counter, kitchen, tables, chairs, tableware."""
    E = lambda *a, **k: entities.append(_ent(world, *a, **k))

    E('Cafe Floor', 'box', floor_color, 0, -0.05, -2, sx=18, sy=0.1, sz=16, shadow=False)
    E('Back Wall', 'box', wall_color, 0, 1.5, -10.5, sx=18, sy=3, sz=0.2)
    E('Left Wall', 'box', wall_color, -9, 1.5, -2, sx=0.2, sy=3, sz=16)
    E('Right Wall', 'box', wall_color, 9, 1.5, -2, sx=0.2, sy=3, sz=16)

    E('Counter', 'box', counter_color, 0, 0.55, -6, sx=6, sy=1.1, sz=0.8)
    E('Counter Top', 'box', top_color, 0, 1.12, -6, sx=6.1, sy=0.04, sz=0.9)

    E('Kitchen Counter', 'box', '#696969', 0, 0.45, -9, sx=4, sy=0.9, sz=0.6)
    E('Oven', 'box', '#2f2f2f', -3, 0.5, -9.5, sx=1.2, sy=1.0, sz=0.8)
    E('Fridge', 'box', '#c0c0c0', 3, 0.9, -9.5, sx=0.8, sy=1.8, sz=0.7)
    E('Sink', 'box', '#a9a9a9', 1.5, 0.45, -9, sx=0.8, sy=0.9, sz=0.6)
    E('Coffee Machine', 'box', '#1a1a1a', -1.5, 1.35, -6, sx=0.5, sy=0.6, sz=0.4)
    E('Cash Register', 'box', '#2a2a2a', 1.5, 1.25, -6, sx=0.4, sy=0.3, sz=0.3)
    E('Menu Board', 'box', '#1a1a1a', 0, 2.5, -10.4, sx=2.5, sy=1.2, sz=0.05)

    # Door — a dark panel at the street side of the cafe. Named "Door" so
    # the Aether viewer's door-teleport logic picks it up and warps the
    # player to a random world when they walk through it.
    E('Door', 'box', '#3a2a1c', 0, 1.0, 5.9, sx=1.4, sy=2.0, sz=0.08,
      shadow=False)
    E('Door Frame Top', 'box', '#2a1a0c', 0, 2.05, 5.9, sx=1.6, sy=0.1, sz=0.1,
      shadow=False)
    E('Door Frame L', 'box', '#2a1a0c', -0.78, 1.05, 5.9, sx=0.1, sy=2.1, sz=0.1,
      shadow=False)
    E('Door Frame R', 'box', '#2a1a0c', 0.78, 1.05, 5.9, sx=0.1, sy=2.1, sz=0.1,
      shadow=False)

    table_positions = []
    for i, (tx, tz, seats) in enumerate(CAFE_TABLES):
        table_positions.append((tx, tz))
        E(f'Table {i+1}', 'cylinder', counter_color, tx, 0.38, tz, sx=0.9, sy=0.76, sz=0.9)
        E(f'Tabletop {i+1}', 'cylinder', top_color, tx, 0.77, tz, sx=1.0, sy=0.04, sz=1.0, shadow=False)
        offsets = [(-0.6, 0), (0.6, 0)] if seats == 2 else \
                  [(-0.6, -0.5), (0.6, -0.5), (-0.6, 0.5), (0.6, 0.5)]
        for ci, (cx, cz) in enumerate(offsets):
            E(f'Chair {i+1}{chr(65+ci)}', 'box', '#8b6914', tx+cx, 0.28, tz+cz, sx=0.4, sy=0.06, sz=0.4)
            bz = tz + cz + (0.2 if cz >= 0 else -0.2)
            E(f'Backrest {i+1}{chr(65+ci)}', 'box', '#8b6914', tx+cx, 0.52, bz, sx=0.4, sy=0.5, sz=0.04, shadow=False)
        E(f'Cup {i+1}', 'cylinder', '#f5f5dc', tx+0.15, 0.83, tz-0.1, sx=0.06, sy=0.08, sz=0.06, shadow=False)
        E(f'Saucer {i+1}', 'cylinder', '#f5f5dc', tx+0.15, 0.79, tz-0.1, sx=0.1, sy=0.015, sz=0.1, shadow=False)
        E(f'Plate {i+1}', 'cylinder', '#fafafa', tx-0.15, 0.79, tz+0.1, sx=0.14, sy=0.015, sz=0.14, shadow=False)
        E(f'Fork {i+1}', 'box', '#c0c0c0', tx-0.3, 0.79, tz+0.08, sx=0.015, sy=0.005, sz=0.12, shadow=False)
        E(f'Spoon {i+1}', 'box', '#c0c0c0', tx-0.32, 0.79, tz+0.08, sx=0.015, sy=0.005, sz=0.12, shadow=False)

    return table_positions


# ---------------------------------------------------------------------------
# NPC helpers
# ---------------------------------------------------------------------------

SKINS = ['#d4a373', '#8d5524', '#c68642', '#e0ac69', '#f1c27d',
         '#ffdbac', '#a0522d', '#cd853f', '#deb887', '#d2691e', '#8b6914']
SHIRTS = ['#ffffff', '#c23b22', '#6b8e23', '#8b4513', '#483d8b',
          '#2f4f4f', '#b22222', '#556b2f', '#4682b4', '#8b0000', '#2e8b57']
PANTS = ['#1a1a2e', '#2d2d2d', '#3b3b3b', '#1c1c3a', '#2a2a2a',
         '#1e3a1e', '#2b1d0e', '#3d3d3d', '#1a1a1a', '#2e2e4e', '#333344']
SHOES = ['#1a1a1a', '#3e2723', '#1a1a1a', '#4a3728', '#2c2c2c',
         '#1a1a1a', '#3e2723', '#1a1a1a', '#2c2c2c', '#3e2723', '#1a1a1a']
HAIRS = ['#1a1209', '#0a0a0a', '#3b2314', '#c4a35a', '#1a1209',
         '#5a3825', '#0a0a0a', '#8b4513', '#2c1608', '#0a0a0a', '#3b2314']
EYES = ['#4a3728', '#2d5a27', '#4682b4', '#1a1209', '#5d8a5e',
        '#6b4423', '#2e4057', '#3a2415', '#5c7a3a', '#4a3020', '#3b6e8f']
BUILDS = [
    (1.0, 0.95, 1.0), (0.85, 0.9, 0.92), (1.1, 1.0, 1.05),
    (0.95, 0.9, 0.98), (0.9, 0.95, 0.95), (0.88, 1.0, 0.94),
    (1.05, 1.0, 1.02), (0.82, 0.88, 0.9), (1.08, 1.05, 1.04),
    (0.9, 0.92, 0.96), (1.02, 0.98, 1.01),
]


def make_npc(world, name, idx, x, z, ry=0):
    return Entity(
        world=world, name=name, primitive='box', primitive_color='#000000',
        pos_x=x, pos_y=0, pos_z=z, rot_y=ry,
        scale_x=1, scale_y=1, scale_z=1,
        cast_shadow=False, receive_shadow=False, behavior='scripted',
    )


def get_script(slug):
    return Script.objects.filter(slug=slug).first()


# ---------------------------------------------------------------------------
# Gun Cafe script — projectile shooting on click
# ---------------------------------------------------------------------------

GUN_CAFE_SHOOT_SCRIPT = r"""
// FPS shooting: click to fire a projectile from camera toward crosshair
if (!ctx.state.init) {
    ctx.state.init = true;
    ctx.state.projectiles = [];
    ctx.state.score = 0;

    // Crosshair
    const ch = document.createElement('div');
    ch.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);' +
        'width:20px;height:20px;border:2px solid #ff4444;border-radius:50%;pointer-events:none;z-index:999;';
    document.body.appendChild(ch);
    ctx.state.crosshair = ch;

    // Score display
    const sd = document.createElement('div');
    sd.style.cssText = 'position:fixed;top:10px;right:20px;color:#ff4444;font-size:1.2rem;' +
        'font-family:monospace;z-index:999;';
    sd.textContent = 'Score: 0';
    document.body.appendChild(sd);
    ctx.state.scoreEl = sd;

    // Click handler
    document.addEventListener('click', () => {
        if (!document.pointerLockElement) return;
        const cam = ctx.scene.getObjectByName('__camera__') || ctx.camera;
        if (!cam) return;
        const dir = new THREE.Vector3(0, 0, -1).applyQuaternion(cam.quaternion);
        const geo = new THREE.SphereGeometry(0.08, 8, 8);
        const mat = new THREE.MeshStandardMaterial({color: 0xff4400, emissive: 0xff2200, emissiveIntensity: 0.8});
        const bullet = new THREE.Mesh(geo, mat);
        bullet.position.copy(cam.position || cam.getWorldPosition(new THREE.Vector3()));
        bullet.position.add(dir.clone().multiplyScalar(0.5));
        ctx.scene.add(bullet);
        ctx.state.projectiles.push({mesh: bullet, vel: dir.multiplyScalar(30), age: 0});
    });
}

const dt = ctx.dt || 0.016;
const dead = [];
for (let i = ctx.state.projectiles.length - 1; i >= 0; i--) {
    const p = ctx.state.projectiles[i];
    p.mesh.position.add(p.vel.clone().multiplyScalar(dt));
    p.age += dt;
    if (p.age > 3) {
        ctx.scene.remove(p.mesh);
        ctx.state.projectiles.splice(i, 1);
        continue;
    }
    // Hit test against NPCs
    ctx.scene.traverse(child => {
        if (child.userData && child.userData.isNpcRoot && child !== ctx.entity) {
            const d = child.position.distanceTo(p.mesh.position);
            if (d < 1.2) {
                ctx.state.score++;
                ctx.state.scoreEl.textContent = 'Score: ' + ctx.state.score;
                // Knockback
                const kb = p.vel.clone().normalize().multiplyScalar(2);
                child.position.add(kb);
                ctx.scene.remove(p.mesh);
                ctx.state.projectiles.splice(i, 1);
            }
        }
    });
}
"""

# Mark NPC root for hit detection
GUN_NPC_MARKER_SCRIPT = r"""
if (!ctx.state.marked) {
    ctx.state.marked = true;
    ctx.entity.userData.isNpcRoot = true;
}
"""


# ---------------------------------------------------------------------------
# Animal Cafe — animal head overlay script
# ---------------------------------------------------------------------------

ANIMAL_HEAD_SCRIPT = r"""
// Replace NPC head mesh with an animal head shape
const P = ctx.props;
const animal = P.animal || 'cat';
const headColor = new THREE.Color(P.headColor || '#c8a070');

if (!ctx.state.init) {
    ctx.state.init = true;
    // Wait a frame for humanoid builder to finish
    ctx.state.waitFrames = 2;
}
if (ctx.state.waitFrames > 0) { ctx.state.waitFrames--; return; }
if (ctx.state.done) return;
ctx.state.done = true;

// Find the head pivot
let headPivot = null;
ctx.entity.traverse(c => {
    if (c.name === 'head_pivot') headPivot = c;
});
if (!headPivot) return;

// Remove existing head mesh
const old = [];
headPivot.traverse(c => { if (c.isMesh && c.name === 'head_mesh') old.push(c); });
old.forEach(m => m.parent.remove(m));

const mat = new THREE.MeshStandardMaterial({color: headColor, roughness: 0.7});
const group = new THREE.Group();
group.name = 'animal_head';

if (animal === 'cat') {
    // Round head + triangle ears
    group.add(new THREE.Mesh(new THREE.SphereGeometry(0.14, 12, 12), mat));
    const earGeo = new THREE.ConeGeometry(0.05, 0.08, 4);
    const earL = new THREE.Mesh(earGeo, mat); earL.position.set(-0.08, 0.14, 0);
    const earR = new THREE.Mesh(earGeo, mat); earR.position.set(0.08, 0.14, 0);
    group.add(earL, earR);
    // Nose
    const nose = new THREE.Mesh(new THREE.SphereGeometry(0.02, 6, 6),
        new THREE.MeshStandardMaterial({color: '#ff9999'}));
    nose.position.set(0, -0.02, 0.13);
    group.add(nose);
} else if (animal === 'dog') {
    group.add(new THREE.Mesh(new THREE.SphereGeometry(0.14, 12, 12), mat));
    // Floppy ears
    const earGeo = new THREE.SphereGeometry(0.05, 8, 8);
    const earL = new THREE.Mesh(earGeo, mat); earL.position.set(-0.12, 0.02, 0); earL.scale.set(1, 1.5, 0.5);
    const earR = new THREE.Mesh(earGeo, mat); earR.position.set(0.12, 0.02, 0); earR.scale.set(1, 1.5, 0.5);
    group.add(earL, earR);
    // Snout
    const snout = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.06, 0.1, 8),
        mat);
    snout.rotation.x = Math.PI / 2; snout.position.set(0, -0.04, 0.14);
    group.add(snout);
} else if (animal === 'rabbit') {
    group.add(new THREE.Mesh(new THREE.SphereGeometry(0.13, 12, 12), mat));
    const earGeo = new THREE.CylinderGeometry(0.02, 0.025, 0.16, 8);
    const earL = new THREE.Mesh(earGeo, mat); earL.position.set(-0.05, 0.2, 0);
    const earR = new THREE.Mesh(earGeo, mat); earR.position.set(0.05, 0.2, 0);
    group.add(earL, earR);
} else if (animal === 'bear') {
    group.add(new THREE.Mesh(new THREE.SphereGeometry(0.16, 12, 12), mat));
    const earGeo = new THREE.SphereGeometry(0.04, 8, 8);
    const earL = new THREE.Mesh(earGeo, mat); earL.position.set(-0.12, 0.12, 0);
    const earR = new THREE.Mesh(earGeo, mat); earR.position.set(0.12, 0.12, 0);
    group.add(earL, earR);
    const snout = new THREE.Mesh(new THREE.SphereGeometry(0.06, 8, 8), mat);
    snout.position.set(0, -0.04, 0.14);
    group.add(snout);
} else if (animal === 'fox') {
    group.add(new THREE.Mesh(new THREE.SphereGeometry(0.13, 12, 12), mat));
    const earGeo = new THREE.ConeGeometry(0.04, 0.1, 4);
    const earL = new THREE.Mesh(earGeo, mat); earL.position.set(-0.08, 0.15, 0);
    const earR = new THREE.Mesh(earGeo, mat); earR.position.set(0.08, 0.15, 0);
    group.add(earL, earR);
    const snout = new THREE.Mesh(new THREE.ConeGeometry(0.03, 0.1, 8),
        mat);
    snout.rotation.x = Math.PI / 2; snout.position.set(0, -0.04, 0.14);
    group.add(snout);
} else if (animal === 'owl') {
    group.add(new THREE.Mesh(new THREE.SphereGeometry(0.15, 12, 12), mat));
    // Big eyes
    const eyeMat = new THREE.MeshStandardMaterial({color: '#ffcc00', emissive: '#ffaa00', emissiveIntensity: 0.3});
    const eyeGeo = new THREE.SphereGeometry(0.04, 8, 8);
    const eyeL = new THREE.Mesh(eyeGeo, eyeMat); eyeL.position.set(-0.06, 0.03, 0.12);
    const eyeR = new THREE.Mesh(eyeGeo, eyeMat); eyeR.position.set(0.06, 0.03, 0.12);
    group.add(eyeL, eyeR);
    // Beak
    const beak = new THREE.Mesh(new THREE.ConeGeometry(0.02, 0.05, 4),
        new THREE.MeshStandardMaterial({color: '#cc8800'}));
    beak.rotation.x = Math.PI / 2; beak.position.set(0, -0.02, 0.15);
    group.add(beak);
}

group.position.y = 0.12;
headPivot.add(group);
"""


# ---------------------------------------------------------------------------
# Jungle decor script — vines + particle insects
# ---------------------------------------------------------------------------

JUNGLE_INSECTS_SCRIPT = r"""
// Ambient jungle insects — fireflies / beetles floating around
if (!ctx.state.init) {
    ctx.state.init = true;
    ctx.state.bugs = [];
    const colors = [0x88ff44, 0xffee44, 0x44ffaa, 0xff8844];
    for (let i = 0; i < 30; i++) {
        const geo = new THREE.SphereGeometry(0.03, 4, 4);
        const mat = new THREE.MeshStandardMaterial({
            color: colors[i % colors.length],
            emissive: colors[i % colors.length],
            emissiveIntensity: 0.6,
        });
        const m = new THREE.Mesh(geo, mat);
        m.position.set(
            (Math.random() - 0.5) * 16,
            0.5 + Math.random() * 2.5,
            (Math.random() - 0.5) * 14 - 2,
        );
        ctx.scene.add(m);
        ctx.state.bugs.push({
            mesh: m,
            vx: (Math.random() - 0.5) * 0.8,
            vy: (Math.random() - 0.5) * 0.3,
            vz: (Math.random() - 0.5) * 0.8,
            phase: Math.random() * Math.PI * 2,
        });
    }
}
const t = ctx.time || 0;
for (const b of ctx.state.bugs) {
    b.mesh.position.x += Math.sin(t * 0.7 + b.phase) * 0.005 + b.vx * 0.002;
    b.mesh.position.y += Math.cos(t * 1.1 + b.phase) * 0.003;
    b.mesh.position.z += Math.cos(t * 0.5 + b.phase) * 0.005 + b.vz * 0.002;
    // Wrap around cafe bounds
    if (b.mesh.position.x < -9) b.mesh.position.x = 9;
    if (b.mesh.position.x > 9) b.mesh.position.x = -9;
    if (b.mesh.position.z < -10) b.mesh.position.z = 5;
    if (b.mesh.position.z > 5) b.mesh.position.z = -10;
}
"""


# ===================================================================

def _get_or_create_script(name, event, code, desc=''):
    slug = name.lower().replace(' ', '-')
    s, _ = Script.objects.get_or_create(slug=slug, defaults={
        'name': name, 'event': event, 'code': code, 'description': desc,
    })
    if s.code != code:
        s.code = code
        s.event = event
        s.save()
    return s


class Command(BaseCommand):
    help = 'Create three Velour Cafe variants: Gun Cafe, Animal Cafe, Jungle Cafe.'

    def add_arguments(self, parser):
        parser.add_argument('--ultra', action='store_true',
                            help='Enable ultra-realistic NPC meshes')

    def handle(self, *args, **options):
        ultra = options.get('ultra', False)

        # Ensure base scripts exist (from seed_cafe_hdri)
        humanoid = get_script('humanoid-builder')
        waiter_anim = get_script('waiter-articulated')
        seated_anim = get_script('seated-articulated')
        wander_anim = get_script('wander-articulated')
        barista_anim = get_script('barista-articulated')
        greet = get_script('npc-greet')

        if not humanoid:
            self.stderr.write(self.style.ERROR(
                'Run seed_cafe_hdri first — humanoid-builder script not found.'))
            return

        # Variant-specific scripts
        shoot_script = _get_or_create_script(
            'Gun Cafe Shoot', 'update', GUN_CAFE_SHOOT_SCRIPT,
            'FPS shooting mechanic — click to fire projectiles at NPCs.')
        npc_marker = _get_or_create_script(
            'Gun NPC Marker', 'start', GUN_NPC_MARKER_SCRIPT,
            'Marks entity as NPC root for hit detection.')
        animal_head = _get_or_create_script(
            'Animal Head', 'start', ANIMAL_HEAD_SCRIPT,
            'Replaces NPC head with a procedural animal head.')
        jungle_insects = _get_or_create_script(
            'Jungle Insects', 'update', JUNGLE_INSECTS_SCRIPT,
            'Ambient firefly / insect particles in jungle cafe.')

        self._build_gun_cafe(ultra, humanoid, waiter_anim, seated_anim,
                             wander_anim, barista_anim, greet,
                             shoot_script, npc_marker)
        self._build_animal_cafe(ultra, humanoid, waiter_anim, seated_anim,
                                wander_anim, barista_anim, greet,
                                animal_head)
        self._build_jungle_cafe(ultra, humanoid, waiter_anim, seated_anim,
                                wander_anim, barista_anim, greet,
                                jungle_insects)

    # -------------------------------------------------------------------
    # GUN CAFE
    # -------------------------------------------------------------------
    def _build_gun_cafe(self, ultra, humanoid, waiter_anim, seated_anim,
                        wander_anim, barista_anim, greet,
                        shoot_script, npc_marker):
        World.objects.filter(slug='velour-gun-cafe').delete()
        world = World.objects.create(
            title='Velour Gun Cafe',
            slug='velour-gun-cafe',
            description='FPS cafe — shoot NPCs for points. Same cozy cafe, added firepower.',
            skybox='hdri', hdri_asset='brown_photostudio_02',
            sky_color='#1a0a0a', ground_color='#3a2020', ground_size=30.0,
            ambient_light=0.25, fog_near=15.0, fog_far=40.0, fog_color='#2a1515',
            gravity=-9.81, spawn_x=0, spawn_y=1.6, spawn_z=6.0,
            soundscape='cafe', ambient_volume=0.2,
            published=True, featured=False,
        )

        entities = []
        table_pos = build_cafe_shell(world, entities,
                                     wall_color='#5a3030', floor_color='#4a2020',
                                     counter_color='#3a1515', top_color='#8a6050')

        # Red ambient lighting
        E = lambda *a, **k: entities.append(_ent(world, *a, **k))
        for lx in [-4, 0, 4]:
            for lz in [-3, 1, 5]:
                E(f'Light {lx},{lz}', 'sphere', '#ff3333', lx, 2.8, lz,
                  sx=0.15, sy=0.15, sz=0.15, shadow=False, behavior='bob', speed=0.5)

        # Target displays on walls
        for i, z in enumerate([-5, -1, 3]):
            E(f'Target {i+1}', 'cylinder', '#ff2222', -8.9, 1.5, z,
              sx=0.4, sy=0.4, sz=0.04, rx=0, ry=0, rz=90, shadow=False)
            E(f'Target {i+4}', 'cylinder', '#ff2222', 8.9, 1.5, z,
              sx=0.4, sy=0.4, sz=0.04, rx=0, ry=0, rz=90, shadow=False)

        Entity.objects.bulk_create(entities)

        # Shoot controller — attached to a dummy entity
        shooter_ent = Entity.objects.create(
            world=world, name='Shoot Controller', primitive='box',
            primitive_color='#000000',
            pos_x=0, pos_y=-10, pos_z=0,
            scale_x=0.01, scale_y=0.01, scale_z=0.01,
            cast_shadow=False, receive_shadow=False, behavior='scripted',
        )
        EntityScript.objects.create(entity=shooter_ent, script=shoot_script, props={})

        # NPCs — same roster, all get npc_marker for hit detection
        names = ['Marco', 'Ava', 'Sam', 'Kenji', 'Liu', 'Rosa',
                 'Dante', 'Yara', 'Benny', 'Cleo', 'Felix']
        npc_ents = self._spawn_cafe_npcs(world, names, ultra, humanoid,
                                         waiter_anim, seated_anim, wander_anim,
                                         barista_anim, greet, table_pos)
        # Add marker to all NPCs
        attachments = [EntityScript(entity=e, script=npc_marker, props={})
                       for e in npc_ents]
        EntityScript.objects.bulk_create(attachments)

        total = Entity.objects.filter(world=world).count()
        self.stdout.write(self.style.SUCCESS(
            f'Gun Cafe created: {total} entities, {len(npc_ents)} NPCs.'))

    # -------------------------------------------------------------------
    # ANIMAL CAFE
    # -------------------------------------------------------------------
    def _build_animal_cafe(self, ultra, humanoid, waiter_anim, seated_anim,
                           wander_anim, barista_anim, greet, animal_head_script):
        World.objects.filter(slug='velour-animal-cafe').delete()
        world = World.objects.create(
            title='Velour Animal Cafe',
            slug='velour-animal-cafe',
            description='Cozy cafe where every patron has an animal head.',
            skybox='hdri', hdri_asset='brown_photostudio_02',
            sky_color='#87CEEB', ground_color='#5c4033', ground_size=30.0,
            ambient_light=0.35, fog_near=20.0, fog_far=50.0, fog_color='#d4c5b0',
            gravity=-9.81, spawn_x=0, spawn_y=1.6, spawn_z=6.0,
            soundscape='cafe', ambient_volume=0.3,
            published=True, featured=False,
        )

        entities = []
        table_pos = build_cafe_shell(world, entities)

        E = lambda *a, **k: entities.append(_ent(world, *a, **k))
        # Warm lighting
        for lx in [-4, 0, 4]:
            for lz in [-3, 1, 5]:
                E(f'Light {lx},{lz}', 'sphere', '#fff5e1', lx, 2.8, lz,
                  sx=0.15, sy=0.15, sz=0.15, shadow=False, behavior='bob', speed=0.3)
        # Paw-print decor
        for i in range(6):
            x = random.uniform(-7, 7)
            z = random.uniform(-8, 4)
            E(f'Paw Print {i+1}', 'cylinder', '#6b4226', x, 0.001, z,
              sx=0.15, sy=0.005, sz=0.15, shadow=False)

        Entity.objects.bulk_create(entities)

        names = ['Marco', 'Ava', 'Sam', 'Kenji', 'Liu', 'Rosa',
                 'Dante', 'Yara', 'Benny', 'Cleo', 'Felix']
        npc_ents = self._spawn_cafe_npcs(world, names, ultra, humanoid,
                                         waiter_anim, seated_anim, wander_anim,
                                         barista_anim, greet, table_pos)

        animals = [
            ('cat', '#c8a070'), ('dog', '#a08050'), ('rabbit', '#e0d0c0'),
            ('bear', '#7a5530'), ('fox', '#d08030'), ('owl', '#8a7060'),
            ('cat', '#404040'), ('dog', '#d0b090'), ('rabbit', '#b0a090'),
            ('bear', '#503020'), ('fox', '#c06020'),
        ]
        attachments = []
        for i, e in enumerate(npc_ents):
            animal, color = animals[i % len(animals)]
            attachments.append(EntityScript(
                entity=e, script=animal_head_script,
                props={'animal': animal, 'headColor': color}))
        EntityScript.objects.bulk_create(attachments)

        total = Entity.objects.filter(world=world).count()
        self.stdout.write(self.style.SUCCESS(
            f'Animal Cafe created: {total} entities, {len(npc_ents)} NPCs.'))

    # -------------------------------------------------------------------
    # JUNGLE CAFE
    # -------------------------------------------------------------------
    def _build_jungle_cafe(self, ultra, humanoid, waiter_anim, seated_anim,
                           wander_anim, barista_anim, greet, insect_script):
        World.objects.filter(slug='velour-jungle-cafe').delete()
        world = World.objects.create(
            title='Velour Jungle Cafe',
            slug='velour-jungle-cafe',
            description='Overgrown jungle cafe with vines, insects, and green everywhere.',
            skybox='hdri', hdri_asset='brown_photostudio_02',
            sky_color='#1a3a1a', ground_color='#2a3a20', ground_size=30.0,
            ambient_light=0.2, fog_near=12.0, fog_far=35.0, fog_color='#1a3020',
            gravity=-9.81, spawn_x=0, spawn_y=1.6, spawn_z=6.0,
            soundscape='forest', ambient_volume=0.35,
            published=True, featured=False,
        )

        entities = []
        table_pos = build_cafe_shell(world, entities,
                                     wall_color='#3a5a30', floor_color='#2a3a20',
                                     counter_color='#4a3a20', top_color='#6a8a50')

        E = lambda *a, **k: entities.append(_ent(world, *a, **k))

        # Green / amber lighting
        for lx in [-4, 0, 4]:
            for lz in [-3, 1, 5]:
                c = random.choice(['#44ff44', '#88ff44', '#aaff22'])
                E(f'Light {lx},{lz}', 'sphere', c, lx, 2.8, lz,
                  sx=0.12, sy=0.12, sz=0.12, shadow=False, behavior='bob', speed=0.2)

        # Vines on walls
        for i in range(12):
            x = random.choice([-8.8, 8.8])
            y = random.uniform(0.3, 2.5)
            z = random.uniform(-9, 4)
            E(f'Vine {i+1}', 'cylinder', '#2a5a18', x, y, z,
              sx=0.04, sy=random.uniform(0.5, 1.5), sz=0.04)

        # Hanging plants from ceiling
        for i in range(8):
            x = random.uniform(-7, 7)
            z = random.uniform(-8, 4)
            E(f'Hanging Plant {i+1}', 'sphere', '#3a7a28', x, 2.6, z,
              sx=0.4, sy=0.5, sz=0.4, shadow=False)
            E(f'Plant Stem {i+1}', 'cylinder', '#2a5a18', x, 2.85, z,
              sx=0.02, sy=0.15, sz=0.02, shadow=False)

        # Moss patches on floor
        for i in range(10):
            x = random.uniform(-8, 8)
            z = random.uniform(-9, 5)
            E(f'Moss {i+1}', 'cylinder', '#3a6a28', x, 0.001, z,
              sx=random.uniform(0.3, 0.8), sy=0.005,
              sz=random.uniform(0.3, 0.8), shadow=False)

        # Large tropical plants in corners
        for cx, cz in [(-8, -9), (8, -9), (-8, 4), (8, 4)]:
            E(f'Tropical {cx},{cz}', 'sphere', '#2e7d32', cx, 0.7, cz,
              sx=0.8, sy=1.2, sz=0.8)
            E(f'Trunk {cx},{cz}', 'cylinder', '#5a3a18', cx, 0.3, cz,
              sx=0.12, sy=0.6, sz=0.12)

        Entity.objects.bulk_create(entities)

        # Insect controller
        bug_ent = Entity.objects.create(
            world=world, name='Insect Swarm', primitive='box',
            primitive_color='#000000',
            pos_x=0, pos_y=-10, pos_z=0,
            scale_x=0.01, scale_y=0.01, scale_z=0.01,
            cast_shadow=False, receive_shadow=False, behavior='scripted',
        )
        EntityScript.objects.create(entity=bug_ent, script=insect_script, props={})

        # NPCs in jungle attire
        names = ['Marco', 'Ava', 'Sam', 'Kenji', 'Liu', 'Rosa',
                 'Dante', 'Yara', 'Benny', 'Cleo', 'Felix']
        npc_ents = self._spawn_cafe_npcs(world, names, ultra, humanoid,
                                         waiter_anim, seated_anim, wander_anim,
                                         barista_anim, greet, table_pos,
                                         shirt_override=['#556b2f', '#6b8e23', '#228b22',
                                                         '#2e8b57', '#3cb371', '#8fbc8f',
                                                         '#006400', '#4a7c59', '#355e3b',
                                                         '#2d5a27', '#3a5f0b'])

        total = Entity.objects.filter(world=world).count()
        self.stdout.write(self.style.SUCCESS(
            f'Jungle Cafe created: {total} entities, {len(npc_ents)} NPCs.'))

    # -------------------------------------------------------------------
    # Shared NPC spawner
    # -------------------------------------------------------------------
    def _spawn_cafe_npcs(self, world, names, ultra, humanoid,
                         waiter_anim, seated_anim, wander_anim,
                         barista_anim, greet, table_pos,
                         shirt_override=None):
        shirts = shirt_override or SHIRTS

        waiter = make_npc(world, names[0] + ' the Waiter', 0, 0, -5)
        barista1 = make_npc(world, names[1], 1, -1, -7, ry=180)
        barista2 = make_npc(world, names[2], 2, 1.5, -7, ry=180)
        waiter.save(); barista1.save(); barista2.save()

        seated_npcs = []
        four_seat = [(i, tx, tz) for i, (tx, tz, s) in enumerate(CAFE_TABLES) if s == 4]
        for pi, (ti, tx, tz) in enumerate(four_seat):
            for si, (ox, oz) in enumerate([(-0.6, -0.5), (0.6, -0.5)]):
                idx = 3 + pi * 2 + si
                n = make_npc(world, names[idx], idx, tx+ox, tz+oz)
                n.save()
                seated_npcs.append(n)

        two_seat = [(i, tx, tz) for i, (tx, tz, s) in enumerate(CAFE_TABLES) if s == 2]
        for pi, (ti, tx, tz) in enumerate(two_seat[:2]):
            idx = 7 + pi
            n = make_npc(world, names[idx], idx, tx-0.6, tz)
            n.save()
            seated_npcs.append(n)

        wanderer1 = make_npc(world, names[9], 9, 3, 4)
        wanderer2 = make_npc(world, names[10], 10, -3, 3)
        wanderer1.save(); wanderer2.save()

        all_npcs = [waiter, barista1, barista2] + seated_npcs + [wanderer1, wanderer2]
        attachments = []

        for e in all_npcs:
            idx = e.pos_x  # use index stored during creation
            # Find idx from all_npcs position
            i = all_npcs.index(e)
            build = BUILDS[i % len(BUILDS)]
            attachments.append(EntityScript(entity=e, script=humanoid, props={
                'skin': SKINS[i % len(SKINS)],
                'shirt': shirts[i % len(shirts)],
                'pants': PANTS[i % len(PANTS)],
                'shoes': SHOES[i % len(SHOES)],
                'hair': HAIRS[i % len(HAIRS)],
                'eyes': EYES[i % len(EYES)],
                'ultra': ultra,
                'shoulderW': build[0], 'hipW': build[1], 'heightScale': build[2],
            }))

        # Waiter
        if waiter_anim:
            attachments.append(EntityScript(entity=waiter, script=waiter_anim, props={
                'tables': [[tx, 0.79, tz] for tx, tz in table_pos],
                'kitchen': [0.0, 0.0, -9.5],
                'speed': 1.8,
            }))
        if greet:
            attachments.append(EntityScript(entity=waiter, script=greet,
                                            props={'greeting': 'One moment please!'}))

        # Baristas
        for b in [barista1, barista2]:
            if barista_anim:
                attachments.append(EntityScript(entity=b, script=barista_anim, props={}))
            if greet:
                attachments.append(EntityScript(entity=b, script=greet,
                                                props={'greeting': 'What can I get you?'}))

        # Seated
        for p in seated_npcs:
            if seated_anim:
                attachments.append(EntityScript(entity=p, script=seated_anim, props={}))
            if greet:
                attachments.append(EntityScript(entity=p, script=greet,
                                                props={'greeting': 'Hey there!'}))

        # Wanderers
        for w in [wanderer1, wanderer2]:
            if wander_anim:
                attachments.append(EntityScript(entity=w, script=wander_anim,
                                                props={'bounds': [-7, -4, 7, 5], 'speed': 1.0}))
            if greet:
                attachments.append(EntityScript(entity=w, script=greet,
                                                props={'greeting': 'Just looking around!'}))

        EntityScript.objects.bulk_create(attachments)
        return all_npcs
