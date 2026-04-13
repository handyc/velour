"""Seed the HDRI cafe with fully articulated humanoid NPCs.

Each NPC has 15 body segments (head, neck, upper/lower torso,
upper/lower arms x2, hands x2, upper/lower legs x2, feet x2)
connected via pivot groups for independent joint rotation.
Procedural animation drives walk cycles, idle breathing, arm
swing, seated fidgeting, and barista work motions.
"""

from django.core.management.base import BaseCommand

from aether.models import Entity, EntityScript, Script, World


CAFE_TABLES = [
    (-4.0, -3.0, 2), (-4.0, 0.0, 2), (-4.0, 3.0, 2),
    (0.0, -3.0, 4), (0.0, 1.0, 4),
    (4.0, -3.0, 2), (4.0, 0.0, 2), (4.0, 3.0, 2),
]
KITCHEN_CENTER = (0.0, 0.0, -9.5)

# Diverse skin tones
SKIN = [
    '#d4a373', '#8d5524', '#c68642', '#e0ac69', '#f1c27d',
    '#ffdbac', '#a0522d', '#cd853f', '#deb887', '#d2691e', '#8b6914',
]
# Shirt colors
SHIRT = [
    '#ffffff', '#c23b22', '#6b8e23', '#8b4513', '#483d8b',
    '#2f4f4f', '#b22222', '#556b2f', '#4682b4', '#8b0000', '#2e8b57',
]
# Trouser colors
PANTS = [
    '#1a1a2e', '#2d2d2d', '#3b3b3b', '#1c1c3a', '#2a2a2a',
    '#1e3a1e', '#2b1d0e', '#3d3d3d', '#1a1a1a', '#2e2e4e', '#333344',
]
# Shoe colors
SHOES = [
    '#1a1a1a', '#3e2723', '#1a1a1a', '#4a3728', '#2c2c2c',
    '#1a1a1a', '#3e2723', '#1a1a1a', '#2c2c2c', '#3e2723', '#1a1a1a',
]
# Hair colors
HAIR = [
    '#1a1209', '#0a0a0a', '#3b2314', '#c4a35a', '#1a1209',
    '#5a3825', '#0a0a0a', '#8b4513', '#2c1608', '#0a0a0a', '#3b2314',
]


EYE_COLORS = [
    '#4a3728', '#2d5a27', '#4682b4', '#1a1209', '#5d8a5e',
    '#6b4423', '#2e4057', '#3a2415', '#5c7a3a', '#4a3020', '#3b6e8f',
]
# Build variation — body proportions (shoulder_w, hip_w, height_scale)
BUILDS = [
    (1.0, 0.95, 1.0),   # Marco - average
    (0.85, 0.9, 0.92),  # Ava - smaller
    (1.1, 1.0, 1.05),   # Sam - broad
    (0.95, 0.9, 0.98),  # Kenji
    (0.9, 0.95, 0.95),  # Liu
    (0.88, 1.0, 0.94),  # Rosa
    (1.05, 1.0, 1.02),  # Dante
    (0.82, 0.88, 0.9),  # Yara - petite
    (1.08, 1.05, 1.04), # Benny - stocky
    (0.9, 0.92, 0.96),  # Cleo
    (1.02, 0.98, 1.01), # Felix
]


class Command(BaseCommand):
    help = 'Create the HDRI cafe with fully articulated humanoid NPCs.'

    def add_arguments(self, parser):
        parser.add_argument('--ultra', action='store_true',
                            help='Enable ultra-realistic NPC meshes (faces, clothing detail, skin textures)')

    def handle(self, *args, **options):
        ultra = options.get('ultra', False)
        World.objects.filter(slug='velour-cafe-hdri').delete()

        world = World.objects.create(
            title='Velour Cafe (HDRI)',
            slug='velour-cafe-hdri',
            description='The Velour Cafe with articulated humanoid NPCs '
                        'and a Poly Haven HDRI skybox.',
            skybox='hdri',
            hdri_asset='brown_photostudio_02',
            sky_color='#87CEEB',
            ground_color='#5c4033',
            ground_size=30.0,
            ambient_light=0.3,
            fog_near=20.0,
            fog_far=50.0,
            fog_color='#d4c5b0',
            gravity=-9.81,
            spawn_x=0.0, spawn_y=1.6, spawn_z=6.0,
            ambient_audio_url='https://stream.zeno.fm/0r0xa792kwzuv',
            ambient_volume=0.3,
            soundscape='cafe',
            published=True, featured=True,
        )

        # Scripts
        humanoid_builder = _script('Humanoid Builder', 'start', HUMANOID_BUILDER_SCRIPT,
            'Builds a 15-segment articulated humanoid body on the root entity.')
        waiter_anim = _script('Waiter Articulated', 'update', WAITER_ANIM_SCRIPT,
            'Walk cycle + pickup animation for the waiter.')
        seated_anim = _script('Seated Articulated', 'update', SEATED_ANIM_SCRIPT,
            'Seated idle: breathing, head turns, arm/hand fidgets.')
        wander_anim = _script('Wander Articulated', 'update', WANDER_ANIM_SCRIPT,
            'Walk to random points with full walk cycle animation.')
        barista_anim = _script('Barista Articulated', 'update', BARISTA_ANIM_SCRIPT,
            'Standing work: weight shift, reach, pour motions.')
        interact_greet = _script('NPC Greet', 'interact', NPC_GREET_SCRIPT,
            'Turn toward player on click.')

        entities = []

        # --- Furniture (reuse from original cafe) ---
        E = lambda *a, **k: entities.append(_ent(world, *a, **k))

        # Floor + walls
        E('Cafe Floor', 'box', '#6b4226', 0, -0.05, -2, sx=18, sy=0.1, sz=16, shadow=False)
        E('Back Wall', 'box', '#8b7355', 0, 1.5, -10.5, sx=18, sy=3, sz=0.2)
        E('Left Wall', 'box', '#8b7355', -9, 1.5, -2, sx=0.2, sy=3, sz=16)
        E('Right Wall', 'box', '#8b7355', 9, 1.5, -2, sx=0.2, sy=3, sz=16)

        # Counter
        E('Counter', 'box', '#5c3317', 0, 0.55, -6, sx=6, sy=1.1, sz=0.8)
        E('Counter Top', 'box', '#d2b48c', 0, 1.12, -6, sx=6.1, sy=0.04, sz=0.9)

        # Kitchen
        E('Kitchen Counter', 'box', '#696969', 0, 0.45, -9, sx=4, sy=0.9, sz=0.6)
        E('Oven', 'box', '#2f2f2f', -3, 0.5, -9.5, sx=1.2, sy=1.0, sz=0.8)
        E('Fridge', 'box', '#c0c0c0', 3, 0.9, -9.5, sx=0.8, sy=1.8, sz=0.7)
        E('Sink', 'box', '#a9a9a9', 1.5, 0.45, -9, sx=0.8, sy=0.9, sz=0.6)
        E('Coffee Machine', 'box', '#1a1a1a', -1.5, 1.35, -6, sx=0.5, sy=0.6, sz=0.4)
        E('Cash Register', 'box', '#2a2a2a', 1.5, 1.25, -6, sx=0.4, sy=0.3, sz=0.3)
        E('Menu Board', 'box', '#1a1a1a', 0, 2.5, -10.4, sx=2.5, sy=1.2, sz=0.05)

        # Tables + chairs + tableware
        table_positions = []
        for i, (tx, tz, seats) in enumerate(CAFE_TABLES):
            table_positions.append((tx, tz))
            E(f'Table {i+1}', 'cylinder', '#5c3317', tx, 0.38, tz, sx=0.9, sy=0.76, sz=0.9)
            E(f'Tabletop {i+1}', 'cylinder', '#d2b48c', tx, 0.77, tz, sx=1.0, sy=0.04, sz=1.0, shadow=False)
            offsets = [(-0.6, 0), (0.6, 0)] if seats == 2 else \
                      [(-0.6, -0.5), (0.6, -0.5), (-0.6, 0.5), (0.6, 0.5)]
            for ci, (cx, cz) in enumerate(offsets):
                E(f'Chair {i+1}{chr(65+ci)}', 'box', '#8b6914', tx+cx, 0.28, tz+cz, sx=0.4, sy=0.06, sz=0.4)
                bz = tz + cz + (0.2 if cz >= 0 else -0.2)
                E(f'Backrest {i+1}{chr(65+ci)}', 'box', '#8b6914', tx+cx, 0.52, bz, sx=0.4, sy=0.5, sz=0.04, shadow=False)
            E(f'Cup {i+1}', 'cylinder', '#f5f5dc', tx+0.15, 0.83, tz-0.1, sx=0.06, sy=0.08, sz=0.06, shadow=False)
            E(f'Saucer {i+1}', 'cylinder', '#f5f5dc', tx+0.15, 0.79, tz-0.1, sx=0.1, sy=0.015, sz=0.1, shadow=False)
            E(f'Plate {i+1}', 'cylinder', '#fafafa', tx-0.15, 0.79, tz+0.1, sx=0.14, sy=0.015, sz=0.14, shadow=False)
            if seats == 4:
                E(f'Cup {i+1}b', 'cylinder', '#f5f5dc', tx-0.2, 0.83, tz-0.15, sx=0.06, sy=0.08, sz=0.06, shadow=False)
                E(f'Glass {i+1}', 'cylinder', '#b0e0e6', tx+0.25, 0.84, tz+0.15, sx=0.04, sy=0.1, sz=0.04, shadow=False)
            E(f'Fork {i+1}', 'box', '#c0c0c0', tx-0.3, 0.79, tz+0.08, sx=0.015, sy=0.005, sz=0.12, shadow=False)
            E(f'Spoon {i+1}', 'box', '#c0c0c0', tx-0.32, 0.79, tz+0.08, sx=0.015, sy=0.005, sz=0.12, shadow=False)

        # Kitchen ingredients
        E('Coffee Beans Bag', 'box', '#3e2723', -0.5, 0.95, -9, sx=0.25, sy=0.35, sz=0.15)
        E('Sugar Box', 'box', '#fff8dc', 0.3, 0.95, -9, sx=0.2, sy=0.25, sz=0.15)
        E('Flour Bag', 'box', '#faebd7', -1.0, 0.95, -9, sx=0.3, sy=0.3, sz=0.2)
        E('Tea Box', 'box', '#228b22', 0.8, 0.95, -9, sx=0.15, sy=0.2, sz=0.1)
        E('Milk Carton', 'box', '#f0f0f0', -0.2, 0.95, -9.3, sx=0.1, sy=0.25, sz=0.1)
        E('Cocoa Tin', 'cylinder', '#4a2c0a', 0.5, 0.95, -9.3, sx=0.08, sy=0.2, sz=0.08)
        for gi in range(4):
            E(f'Counter Glass {gi+1}', 'cylinder', '#d4f1f9', -2.2+gi*0.3, 1.2, -5.7, sx=0.04, sy=0.12, sz=0.04, shadow=False)

        # Decor + lights
        E('Plant 1', 'sphere', '#2e7d32', -8, 0.5, 4, sx=0.6, sy=0.8, sz=0.6)
        E('Plant Pot 1', 'cylinder', '#8d6e63', -8, 0.2, 4, sx=0.3, sy=0.4, sz=0.3)
        E('Plant 2', 'sphere', '#388e3c', 8, 0.5, 4, sx=0.5, sy=0.7, sz=0.5)
        E('Plant Pot 2', 'cylinder', '#8d6e63', 8, 0.2, 4, sx=0.3, sy=0.4, sz=0.3)
        for lx in [-4, 0, 4]:
            for lz in [-3, 1, 5]:
                E(f'Light {lx},{lz}', 'sphere', '#fff5e1', lx, 2.8, lz,
                  sx=0.15, sy=0.15, sz=0.15, shadow=False, behavior='bob', speed=0.3)

        # --- NPCs ---
        # The root entity is a small invisible box at ground level.
        # The humanoid builder script constructs the full body as children.
        def npc(name, idx, x, z, ry=0):
            e = Entity(
                world=world, name=name, primitive='box',
                primitive_color='#000000',
                pos_x=x, pos_y=0, pos_z=z,
                rot_y=ry,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            e._is_npc = True
            e._idx = idx
            return e

        waiter = npc('Marco the Waiter', 0, 0, -5)
        barista1 = npc('Ava', 1, -1, -7, ry=180)
        barista2 = npc('Sam', 2, 1.5, -7, ry=180)
        entities.extend([waiter, barista1, barista2])

        patrons_seated = []
        seated_tables = [(i, tx, tz) for i, (tx, tz, s) in enumerate(CAFE_TABLES) if s == 4]
        names_seated = ['Kenji', 'Liu', 'Rosa', 'Dante']
        for pi, (ti, tx, tz) in enumerate(seated_tables):
            for si, (ox, oz) in enumerate([(-0.6, -0.5), (0.6, -0.5)]):
                idx = 3 + pi * 2 + si
                n = npc(names_seated[pi*2+si], idx, tx+ox, tz+oz)
                entities.append(n)
                patrons_seated.append(n)

        two_seat = [(i, tx, tz) for i, (tx, tz, s) in enumerate(CAFE_TABLES) if s == 2]
        for pi, (ti, tx, tz) in enumerate(two_seat[:2]):
            idx = 7 + pi
            name = ['Yara', 'Benny'][pi]
            n = npc(name, idx, tx-0.6, tz)
            entities.append(n)
            patrons_seated.append(n)

        wander1 = npc('Cleo', 9, 3, 4)
        wander2 = npc('Felix', 10, -3, 3)
        entities.extend([wander1, wander2])

        # --- Save ---
        non_npc = [e for e in entities if not hasattr(e, '_is_npc')]
        Entity.objects.bulk_create(non_npc)
        npc_ents = [e for e in entities if hasattr(e, '_is_npc')]
        for e in npc_ents:
            e.save()

        # --- Script attachments ---
        attachments = []

        def attach(entity, script, props=None):
            attachments.append(EntityScript(entity=entity, script=script, props=props or {}))

        # All NPCs get the humanoid builder (start script)
        for e in npc_ents:
            build = BUILDS[e._idx]
            attach(e, humanoid_builder, {
                'skin': SKIN[e._idx], 'shirt': SHIRT[e._idx],
                'pants': PANTS[e._idx], 'shoes': SHOES[e._idx],
                'hair': HAIR[e._idx], 'eyes': EYE_COLORS[e._idx],
                'ultra': ultra,
                'shoulderW': build[0], 'hipW': build[1], 'heightScale': build[2],
            })

        # Waiter
        attach(waiter, waiter_anim, {
            'tables': [[tx, 0.79, tz] for tx, tz in table_positions],
            'kitchen': list(KITCHEN_CENTER),
            'speed': 1.8,
        })
        attach(waiter, interact_greet, {'greeting': 'One moment please!'})

        # Baristas
        for b in [barista1, barista2]:
            attach(b, barista_anim)
            attach(b, interact_greet, {'greeting': 'What can I get you?'})

        # Seated
        for p in patrons_seated:
            attach(p, seated_anim)
            attach(p, interact_greet, {'greeting': 'Hey there!'})

        # Wanderers
        for w in [wander1, wander2]:
            attach(w, wander_anim, {'bounds': [-7, -4, 7, 5], 'speed': 1.0})
            attach(w, interact_greet, {'greeting': 'Just looking around!'})

        EntityScript.objects.bulk_create(attachments)

        total = Entity.objects.filter(world=world).count()
        self.stdout.write(self.style.SUCCESS(
            f'Velour Cafe (HDRI) created: {total} entities, '
            f'{len(npc_ents)} articulated NPCs, '
            f'{len(attachments)} script attachments.'
        ))


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


def _script(name, event, code, desc=''):
    slug = name.lower().replace(' ', '-')
    s, _ = Script.objects.get_or_create(slug=slug, defaults={
        'name': name, 'event': event, 'code': code, 'description': desc,
    })
    if s.code != code:
        s.code = code
        s.event = event
        s.save()
    return s


# ---------------------------------------------------------------------------
# The humanoid body builder — runs once on 'start'
# Builds 15 body parts as child objects of ctx.entity, stored in ctx.state.
# All parts are THREE.Group pivots with a mesh child so rotation
# happens around the joint, not the mesh center.
# ---------------------------------------------------------------------------

HUMANOID_BUILDER_SCRIPT = r"""
// Build articulated humanoid body on entity root
// Props: skin, shirt, pants, shoes, hair, eyes, ultra,
//        shoulderW, hipW, heightScale
const S = ctx.state;
const P = ctx.props;
const ULTRA = !!P.ultra;
const skinC = new THREE.Color(P.skin || '#d4a373');
const shirtC = new THREE.Color(P.shirt || '#4a6fa5');
const pantsC = new THREE.Color(P.pants || '#2d2d2d');
const shoesC = new THREE.Color(P.shoes || '#1a1a1a');
const hairC = new THREE.Color(P.hair || '#1a1209');
const eyeC = new THREE.Color(P.eyes || '#4a3728');
const SW = P.shoulderW || 1.0;
const HW = P.hipW || 1.0;
const HS = P.heightScale || 1.0;

// Hide the root box mesh
if (ctx.entity.isMesh) {
    ctx.entity.material.visible = false;
    ctx.entity.castShadow = false;
}

// --- Procedural texture helpers (canvas-based, no external assets) ---
function noiseCanvas(w, h, base, variation, scale) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    const id = g.createImageData(w, h);
    const br = base.r * 255, bg = base.g * 255, bb = base.b * 255;
    for (let i = 0; i < id.data.length; i += 4) {
        const n = (Math.random() - 0.5) * variation * 255;
        id.data[i]   = Math.max(0, Math.min(255, br + n));
        id.data[i+1] = Math.max(0, Math.min(255, bg + n));
        id.data[i+2] = Math.max(0, Math.min(255, bb + n));
        id.data[i+3] = 255;
    }
    g.putImageData(id, 0, 0);
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    if (scale) tex.repeat.set(scale, scale);
    return tex;
}

function fabricCanvas(w, h, base, lineColor, spacing) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    g.fillStyle = '#' + base.getHexString();
    g.fillRect(0, 0, w, h);
    g.strokeStyle = lineColor;
    g.lineWidth = 0.5;
    for (let y = 0; y < h; y += spacing) {
        g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke();
    }
    for (let x = 0; x < w; x += spacing) {
        g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke();
    }
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(3, 3);
    return tex;
}

function normalNoise(w, h, strength) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    const id = g.createImageData(w, h);
    for (let i = 0; i < id.data.length; i += 4) {
        id.data[i]   = 128 + (Math.random() - 0.5) * strength;
        id.data[i+1] = 128 + (Math.random() - 0.5) * strength;
        id.data[i+2] = 255;
        id.data[i+3] = 255;
    }
    g.putImageData(id, 0, 0);
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(2, 2);
    return tex;
}

// --- Material factories ---
function skinMat() {
    if (!ULTRA) return new THREE.MeshStandardMaterial({color: skinC, roughness: 0.8, metalness: 0.05});
    return new THREE.MeshPhysicalMaterial({
        color: skinC,
        map: noiseCanvas(64, 64, skinC, 0.04, 2),
        normalMap: normalNoise(64, 64, 30),
        normalScale: new THREE.Vector2(0.3, 0.3),
        roughness: 0.65,
        roughnessMap: noiseCanvas(32, 32, new THREE.Color(0.65, 0.65, 0.65), 0.08, 2),
        metalness: 0.0,
        sheen: 0.3,
        sheenRoughness: 0.5,
        sheenColor: new THREE.Color().copy(skinC).lerp(new THREE.Color('#ffccaa'), 0.3),
        clearcoat: 0.05,
        thickness: 0.3,
        transmission: 0.02,
    });
}

function clothMat(color, isShirt) {
    if (!ULTRA) return new THREE.MeshStandardMaterial({color, roughness: 0.8, metalness: 0.05});
    const lighter = '#' + new THREE.Color().copy(color).lerp(new THREE.Color('#ffffff'), 0.15).getHexString();
    return new THREE.MeshPhysicalMaterial({
        color,
        map: fabricCanvas(64, 64, color, lighter, isShirt ? 4 : 3),
        normalMap: normalNoise(32, 32, isShirt ? 20 : 15),
        normalScale: new THREE.Vector2(0.2, 0.2),
        roughness: isShirt ? 0.85 : 0.9,
        metalness: 0.0,
        sheen: isShirt ? 0.15 : 0.05,
        sheenRoughness: 0.8,
        sheenColor: new THREE.Color().copy(color).lerp(new THREE.Color('#ffffff'), 0.2),
    });
}

function shoeMat() {
    if (!ULTRA) return new THREE.MeshStandardMaterial({color: shoesC, roughness: 0.8, metalness: 0.05});
    return new THREE.MeshPhysicalMaterial({
        color: shoesC,
        roughness: 0.4,
        metalness: 0.02,
        clearcoat: 0.3,
        clearcoatRoughness: 0.4,
    });
}

function hairMat() {
    if (!ULTRA) return new THREE.MeshStandardMaterial({color: hairC, roughness: 0.8, metalness: 0.05});
    return new THREE.MeshPhysicalMaterial({
        color: hairC,
        roughness: 0.6,
        metalness: 0.05,
        sheen: 0.8,
        sheenRoughness: 0.3,
        sheenColor: new THREE.Color().copy(hairC).lerp(new THREE.Color('#ffffff'), 0.25),
        normalMap: normalNoise(32, 32, 40),
        normalScale: new THREE.Vector2(0.5, 0.5),
    });
}

// --- Part builders ---
function part(geo, material) {
    const m = new THREE.Mesh(geo, material);
    m.castShadow = true;
    return m;
}
function pivot(x, y, z) {
    const g = new THREE.Group();
    g.position.set(x, y, z);
    return g;
}

const skinM = skinMat();
const shirtM = clothMat(shirtC, true);
const pantsM = clothMat(pantsC, false);
const shoeM = shoeMat();
const hairM = hairMat();

// --- Hips (root of skeleton) ---
const hips = pivot(0, 0.92 * HS, 0);
ctx.entity.add(hips);

// Lower torso
const lowerTorso = part(
    new THREE.BoxGeometry(0.32 * HW, 0.2 * HS, 0.18), shirtM
);
lowerTorso.position.y = 0.1 * HS;
hips.add(lowerTorso);

// Upper torso pivot
const upperTorsoPivot = pivot(0, 0.2 * HS, 0);
hips.add(upperTorsoPivot);
const upperTorso = part(
    new THREE.BoxGeometry(0.36 * SW, 0.3 * HS, 0.2), shirtM
);
upperTorso.position.y = 0.15 * HS;
upperTorsoPivot.add(upperTorso);

// --- Ultra: collar detail ---
if (ULTRA) {
    const collar = part(
        new THREE.TorusGeometry(0.09, 0.015, 8, 16, Math.PI * 2),
        shirtM
    );
    collar.position.set(0, 0.3 * HS, 0.02);
    collar.rotation.x = Math.PI / 2;
    collar.castShadow = false;
    upperTorsoPivot.add(collar);

    // Shirt wrinkle lines (thin boxes across chest)
    for (let i = 0; i < 3; i++) {
        const wrinkle = part(
            new THREE.BoxGeometry(0.28 * SW, 0.003, 0.005),
            new THREE.MeshStandardMaterial({
                color: new THREE.Color().copy(shirtC).multiplyScalar(0.85),
                roughness: 0.9
            })
        );
        wrinkle.position.set(0, (0.08 + i * 0.07) * HS, 0.101);
        wrinkle.castShadow = false;
        upperTorsoPivot.add(wrinkle);
    }

    // Buttons (3 small spheres down center)
    for (let i = 0; i < 3; i++) {
        const btn = part(
            new THREE.SphereGeometry(0.008, 6, 6),
            new THREE.MeshStandardMaterial({color: '#f0f0e0', roughness: 0.3, metalness: 0.1})
        );
        btn.position.set(0, (0.06 + i * 0.08) * HS, 0.105);
        btn.castShadow = false;
        upperTorsoPivot.add(btn);
    }
}

// Neck + Head
const neckPivot = pivot(0, 0.3 * HS, 0);
upperTorsoPivot.add(neckPivot);
const neck = part(new THREE.CylinderGeometry(0.05, 0.06, 0.08, ULTRA ? 12 : 8), skinM);
neck.position.y = 0.04;
neckPivot.add(neck);

const headPivot = pivot(0, 0.08, 0);
neckPivot.add(headPivot);
const headGeo = new THREE.SphereGeometry(0.12, ULTRA ? 32 : 16, ULTRA ? 32 : 16);
const head = part(headGeo, skinM);
head.position.y = 0.12;
headPivot.add(head);

// Hair
const hairGeo = new THREE.SphereGeometry(0.125, ULTRA ? 32 : 16, ULTRA ? 16 : 8,
    0, Math.PI * 2, 0, Math.PI * 0.55);
const hairMesh = part(hairGeo, hairM);
hairMesh.position.y = 0.14;
hairMesh.castShadow = false;
headPivot.add(hairMesh);

// --- Face ---
if (ULTRA) {
    // Nose bridge + tip
    const noseBridge = part(
        new THREE.BoxGeometry(0.025, 0.04, 0.03), skinM
    );
    noseBridge.position.set(0, 0.12, 0.105);
    noseBridge.castShadow = false;
    headPivot.add(noseBridge);
    const noseTip = part(
        new THREE.SphereGeometry(0.018, 12, 8), skinM
    );
    noseTip.position.set(0, 0.1, 0.12);
    noseTip.castShadow = false;
    headPivot.add(noseTip);
    // Nostrils
    for (const side of [-1, 1]) {
        const nostril = part(
            new THREE.SphereGeometry(0.008, 6, 6),
            new THREE.MeshStandardMaterial({
                color: new THREE.Color().copy(skinC).multiplyScalar(0.7), roughness: 0.9
            })
        );
        nostril.position.set(side * 0.012, 0.095, 0.115);
        nostril.castShadow = false;
        headPivot.add(nostril);
    }

    // Lips
    const lipColor = new THREE.Color().copy(skinC).lerp(new THREE.Color('#cc5555'), 0.35);
    const upperLip = part(
        new THREE.TorusGeometry(0.022, 0.006, 6, 12, Math.PI),
        new THREE.MeshPhysicalMaterial({color: lipColor, roughness: 0.5, sheen: 0.4, sheenColor: lipColor, clearcoat: 0.15})
    );
    upperLip.position.set(0, 0.075, 0.11);
    upperLip.rotation.z = Math.PI;
    upperLip.castShadow = false;
    headPivot.add(upperLip);
    const lowerLip = part(
        new THREE.TorusGeometry(0.024, 0.007, 6, 12, Math.PI),
        new THREE.MeshPhysicalMaterial({color: lipColor, roughness: 0.45, sheen: 0.5, sheenColor: lipColor, clearcoat: 0.2})
    );
    lowerLip.position.set(0, 0.068, 0.108);
    lowerLip.castShadow = false;
    headPivot.add(lowerLip);

    // Brow ridges
    for (const side of [-1, 1]) {
        const brow = part(
            new THREE.BoxGeometry(0.04, 0.008, 0.015),
            new THREE.MeshStandardMaterial({color: new THREE.Color().copy(skinC).multiplyScalar(0.92), roughness: 0.8})
        );
        brow.position.set(side * 0.04, 0.155, 0.085);
        brow.rotation.z = side * -0.15;
        brow.castShadow = false;
        headPivot.add(brow);
    }

    // Ears
    for (const side of [-1, 1]) {
        const ear = part(
            new THREE.SphereGeometry(0.025, 8, 6, 0, Math.PI),
            skinM
        );
        ear.position.set(side * 0.115, 0.12, 0);
        ear.rotation.y = side * Math.PI / 2;
        ear.scale.set(0.6, 1.2, 0.5);
        ear.castShadow = false;
        headPivot.add(ear);
    }

    // Chin definition
    const chin = part(
        new THREE.SphereGeometry(0.03, 10, 8, 0, Math.PI * 2, Math.PI * 0.5, Math.PI * 0.5),
        skinM
    );
    chin.position.set(0, 0.04, 0.07);
    chin.castShadow = false;
    headPivot.add(chin);

    // Cheekbones
    for (const side of [-1, 1]) {
        const cheek = part(
            new THREE.SphereGeometry(0.03, 8, 6), skinM
        );
        cheek.position.set(side * 0.065, 0.1, 0.055);
        cheek.scale.set(1, 0.7, 0.35);
        cheek.castShadow = false;
        headPivot.add(cheek);
    }

    // Detailed eyes: white sclera + colored iris + dark pupil + eyelids
    for (const side of [-1, 1]) {
        // Sclera (white sphere, slightly indented)
        const sclera = part(
            new THREE.SphereGeometry(0.02, 12, 12),
            new THREE.MeshPhysicalMaterial({color: '#f5f5f0', roughness: 0.1, clearcoat: 0.8, clearcoatRoughness: 0.1})
        );
        sclera.position.set(side * 0.04, 0.13, 0.095);
        sclera.castShadow = false;
        headPivot.add(sclera);
        // Iris
        const iris = part(
            new THREE.CircleGeometry(0.012, 16),
            new THREE.MeshPhysicalMaterial({color: eyeC, roughness: 0.2, clearcoat: 0.5})
        );
        iris.position.set(side * 0.04, 0.13, 0.115);
        iris.castShadow = false;
        headPivot.add(iris);
        // Pupil
        const pupil = part(
            new THREE.CircleGeometry(0.006, 12),
            new THREE.MeshStandardMaterial({color: '#050505', roughness: 0.1})
        );
        pupil.position.set(side * 0.04, 0.13, 0.1155);
        pupil.castShadow = false;
        headPivot.add(pupil);
        // Upper eyelid
        const lid = part(
            new THREE.SphereGeometry(0.022, 10, 6, 0, Math.PI * 2, 0, Math.PI * 0.4),
            skinM
        );
        lid.position.set(side * 0.04, 0.135, 0.095);
        lid.castShadow = false;
        headPivot.add(lid);
    }
} else {
    // Simple eyes (non-ultra)
    for (const side of [-1, 1]) {
        const eye = part(new THREE.SphereGeometry(0.015, 8, 8),
            new THREE.MeshStandardMaterial({color: '#1a1a1a', roughness: 0.8}));
        eye.position.set(side * 0.04, 0.13, 0.1);
        eye.castShadow = false;
        headPivot.add(eye);
    }
}

// --- Arms ---
function buildArm(side) {
    const shoulderPivot = pivot(side * 0.22 * SW, 0.27 * HS, 0);
    upperTorsoPivot.add(shoulderPivot);

    // Upper arm (sleeve)
    const upperArm = part(
        new THREE.CylinderGeometry(0.04, 0.035, 0.24 * HS, ULTRA ? 12 : 8), shirtM
    );
    upperArm.position.y = -0.12 * HS;
    shoulderPivot.add(upperArm);

    // Ultra: sleeve cuff ring
    if (ULTRA) {
        const cuff = part(
            new THREE.TorusGeometry(0.036, 0.005, 6, 12),
            new THREE.MeshStandardMaterial({
                color: new THREE.Color().copy(shirtC).multiplyScalar(0.85), roughness: 0.85
            })
        );
        cuff.position.y = -0.23 * HS;
        cuff.rotation.x = Math.PI / 2;
        cuff.castShadow = false;
        shoulderPivot.add(cuff);
    }

    // Elbow pivot
    const elbowPivot = pivot(0, -0.24 * HS, 0);
    shoulderPivot.add(elbowPivot);

    // Forearm (skin)
    const forearm = part(
        new THREE.CylinderGeometry(0.035, 0.03, 0.22 * HS, ULTRA ? 12 : 8), skinM
    );
    forearm.position.y = -0.11 * HS;
    elbowPivot.add(forearm);

    // Ultra: elbow crease
    if (ULTRA) {
        const crease = part(
            new THREE.TorusGeometry(0.033, 0.003, 4, 12),
            new THREE.MeshStandardMaterial({
                color: new THREE.Color().copy(skinC).multiplyScalar(0.88), roughness: 0.9
            })
        );
        crease.position.y = 0.0;
        crease.rotation.x = Math.PI / 2;
        crease.castShadow = false;
        elbowPivot.add(crease);
    }

    // Wrist pivot
    const wristPivot = pivot(0, -0.22 * HS, 0);
    elbowPivot.add(wristPivot);

    if (ULTRA) {
        // Detailed hand: palm + 5 fingers
        const palm = part(
            new THREE.BoxGeometry(0.05, 0.04, 0.035), skinM
        );
        palm.position.y = -0.02;
        wristPivot.add(palm);
        // Fingers (5 small cylinders)
        const fingerOffsets = [-0.018, -0.009, 0, 0.009, 0.018];
        const fingerLengths = [0.03, 0.04, 0.042, 0.038, 0.028];
        for (let fi = 0; fi < 5; fi++) {
            const finger = part(
                new THREE.CylinderGeometry(0.005, 0.004, fingerLengths[fi], 6), skinM
            );
            finger.position.set(fingerOffsets[fi], -0.04 - fingerLengths[fi] / 2, 0);
            finger.castShadow = false;
            wristPivot.add(finger);
            // Fingernail
            const nail = part(
                new THREE.BoxGeometry(0.008, 0.003, 0.006),
                new THREE.MeshPhysicalMaterial({color: '#f5ddd5', roughness: 0.2, clearcoat: 0.6})
            );
            nail.position.set(fingerOffsets[fi], -0.04 - fingerLengths[fi], 0.004);
            nail.castShadow = false;
            wristPivot.add(nail);
        }
        // Thumb (angled)
        const thumb = part(
            new THREE.CylinderGeometry(0.006, 0.005, 0.03, 6), skinM
        );
        thumb.position.set(side * 0.028, -0.03, 0.01);
        thumb.rotation.z = side * 0.6;
        thumb.castShadow = false;
        wristPivot.add(thumb);
    } else {
        const hand = part(new THREE.BoxGeometry(0.05, 0.07, 0.03), skinM);
        hand.position.y = -0.035;
        wristPivot.add(hand);
    }

    return {shoulderPivot, elbowPivot, wristPivot};
}

const leftArm = buildArm(-1);
const rightArm = buildArm(1);

// --- Legs ---
function buildLeg(side) {
    const hipPivot = pivot(side * 0.1 * HW, 0, 0);
    hips.add(hipPivot);

    // Upper leg (thigh)
    const thigh = part(
        new THREE.CylinderGeometry(0.06, 0.05, 0.35 * HS, ULTRA ? 12 : 8), pantsM
    );
    thigh.position.y = -0.175 * HS;
    hipPivot.add(thigh);

    // Ultra: belt loop + pocket line
    if (ULTRA && side === -1) {
        const pocket = part(
            new THREE.BoxGeometry(0.04, 0.001, 0.02),
            new THREE.MeshStandardMaterial({
                color: new THREE.Color().copy(pantsC).multiplyScalar(0.8), roughness: 0.9
            })
        );
        pocket.position.set(0.02, -0.05, 0.05);
        pocket.castShadow = false;
        hipPivot.add(pocket);
    }

    // Knee pivot
    const kneePivot = pivot(0, -0.35 * HS, 0);
    hipPivot.add(kneePivot);

    // Lower leg (shin)
    const shin = part(
        new THREE.CylinderGeometry(0.045, 0.04, 0.35 * HS, ULTRA ? 12 : 8), pantsM
    );
    shin.position.y = -0.175 * HS;
    kneePivot.add(shin);

    // Ultra: trouser hem
    if (ULTRA) {
        const hem = part(
            new THREE.TorusGeometry(0.041, 0.004, 4, 12),
            new THREE.MeshStandardMaterial({
                color: new THREE.Color().copy(pantsC).multiplyScalar(0.85), roughness: 0.9
            })
        );
        hem.position.y = -0.35 * HS;
        hem.rotation.x = Math.PI / 2;
        hem.castShadow = false;
        kneePivot.add(hem);
    }

    // Ankle pivot
    const anklePivot = pivot(0, -0.35 * HS, 0);
    kneePivot.add(anklePivot);

    // Foot / shoe
    if (ULTRA) {
        // Shoe body (rounded box approximation)
        const shoeBody = part(
            new THREE.BoxGeometry(0.075, 0.05, 0.15), shoeM
        );
        shoeBody.position.set(0, -0.025, 0.03);
        anklePivot.add(shoeBody);
        // Toe cap
        const toeCap = part(
            new THREE.SphereGeometry(0.038, 10, 6, 0, Math.PI * 2, 0, Math.PI * 0.5),
            shoeM
        );
        toeCap.position.set(0, -0.02, 0.1);
        toeCap.rotation.x = Math.PI / 2;
        toeCap.castShadow = false;
        anklePivot.add(toeCap);
        // Sole
        const sole = part(
            new THREE.BoxGeometry(0.078, 0.012, 0.155),
            new THREE.MeshStandardMaterial({color: '#0a0a0a', roughness: 0.95})
        );
        sole.position.set(0, -0.05, 0.03);
        sole.castShadow = false;
        anklePivot.add(sole);
    } else {
        const foot = part(new THREE.BoxGeometry(0.07, 0.05, 0.14), shoeM);
        foot.position.set(0, -0.025, 0.03);
        anklePivot.add(foot);
    }

    return {hipPivot, kneePivot, anklePivot};
}

const leftLeg = buildLeg(-1);
const rightLeg = buildLeg(1);

// Ultra: belt
if (ULTRA) {
    const belt = part(
        new THREE.TorusGeometry(0.17 * HW, 0.012, 6, 24),
        new THREE.MeshPhysicalMaterial({color: '#2a1a0a', roughness: 0.35, clearcoat: 0.3})
    );
    belt.position.y = 0.0;
    belt.rotation.x = Math.PI / 2;
    belt.castShadow = false;
    hips.add(belt);
    // Belt buckle
    const buckle = part(
        new THREE.BoxGeometry(0.025, 0.02, 0.01),
        new THREE.MeshStandardMaterial({color: '#c0c0c0', roughness: 0.2, metalness: 0.8})
    );
    buckle.position.set(0, 0.0, 0.17 * HW);
    buckle.castShadow = false;
    hips.add(buckle);
}

// Store all joints in state for animation scripts
S.body = {
    hips, upperTorsoPivot, neckPivot, headPivot,
    leftArm, rightArm, leftLeg, rightLeg,
};
S.built = true;
"""

# ---------------------------------------------------------------------------
# Walk cycle — drives all joints for realistic bipedal locomotion
# Called as a function from movement scripts (waiter, wander)
# ---------------------------------------------------------------------------

WALK_CYCLE_FN = r"""
function walkCycle(S, t, speed) {
    // t = phase accumulator, speed = stride frequency multiplier
    const b = S.body;
    const phase = t * speed * 5;  // ~5 strides/sec at speed=1
    const sin = Math.sin(phase);
    const cos = Math.cos(phase);

    // Hips: slight vertical bounce + lateral sway
    b.hips.position.y = 0.92 + Math.abs(sin) * 0.02;
    b.hips.rotation.z = sin * 0.02;

    // Upper torso: counter-rotate to hips
    b.upperTorsoPivot.rotation.y = sin * 0.05;
    b.upperTorsoPivot.rotation.z = -sin * 0.01;

    // Head: stabilize (counter hips sway)
    b.headPivot.rotation.z = -sin * 0.01;

    // Arms: swing opposite to legs
    b.leftArm.shoulderPivot.rotation.x = -sin * 0.5;
    b.rightArm.shoulderPivot.rotation.x = sin * 0.5;
    // Elbows bend on backswing
    b.leftArm.elbowPivot.rotation.x = -Math.max(0, sin) * 0.4;
    b.rightArm.elbowPivot.rotation.x = -Math.max(0, -sin) * 0.4;

    // Legs: stride
    b.leftLeg.hipPivot.rotation.x = sin * 0.45;
    b.rightLeg.hipPivot.rotation.x = -sin * 0.45;
    // Knees: bend when leg is behind
    b.leftLeg.kneePivot.rotation.x = Math.max(0, -sin) * 0.6;
    b.rightLeg.kneePivot.rotation.x = Math.max(0, sin) * 0.6;
    // Ankles: dorsiflex on forward swing
    b.leftLeg.anklePivot.rotation.x = sin * 0.15;
    b.rightLeg.anklePivot.rotation.x = -sin * 0.15;
}
"""

IDLE_FN = r"""
function idleBreathing(S, t) {
    const b = S.body;
    const breathe = Math.sin(t * 1.5);

    // Subtle chest rise/fall
    b.upperTorsoPivot.rotation.x = breathe * 0.01;
    // Shoulders rise slightly on inhale
    b.leftArm.shoulderPivot.position.y = 0.27 + breathe * 0.003;
    b.rightArm.shoulderPivot.position.y = 0.27 + breathe * 0.003;
    // Arms hang naturally with slight sway
    b.leftArm.shoulderPivot.rotation.x = 0.05 + breathe * 0.01;
    b.rightArm.shoulderPivot.rotation.x = 0.05 + breathe * 0.01;
    b.leftArm.elbowPivot.rotation.x = -0.15;
    b.rightArm.elbowPivot.rotation.x = -0.15;
    // Legs straight
    b.leftLeg.hipPivot.rotation.x = 0;
    b.rightLeg.hipPivot.rotation.x = 0;
    b.leftLeg.kneePivot.rotation.x = 0;
    b.rightLeg.kneePivot.rotation.x = 0;
    // Hips level
    b.hips.position.y = 0.92;
    b.hips.rotation.z = 0;
}
"""

# ---------------------------------------------------------------------------
# Waiter animation — walk cycle when moving, pickup when at table
# ---------------------------------------------------------------------------

WAITER_ANIM_SCRIPT = WALK_CYCLE_FN + IDLE_FN + r"""
if (!ctx.state.built) return;  // wait for builder
const S = ctx.state;
if (!S.w_init) {
    S.w_init = true;
    S.phase = 'goto_table';
    S.tableIdx = 0;
    S.tables = ctx.props.tables || [[0, 0.79, -3]];
    S.kitchen = ctx.props.kitchen || [0, 0, -9.5];
    S.speed = ctx.props.speed || 1.8;
    S.timer = 0;
    S.walkT = 0;
    // Tray
    const tray = new THREE.Mesh(
        new THREE.CylinderGeometry(0.15, 0.15, 0.02, 12),
        new THREE.MeshStandardMaterial({color: '#8b4513', roughness: 0.6})
    );
    tray.position.set(0.3, 0.2, 0);
    tray.visible = false;
    S.body.rightArm.wristPivot.add(tray);
    S.tray = tray;
}

function moveTo(target) {
    const dx = target[0] - ctx.entity.position.x;
    const dz = target[2] - ctx.entity.position.z;
    const dist = Math.sqrt(dx * dx + dz * dz);
    if (dist < 0.3) return true;
    const step = Math.min(S.speed * ctx.deltaTime, dist);
    ctx.entity.position.x += (dx / dist) * step;
    ctx.entity.position.z += (dz / dist) * step;
    ctx.entity.rotation.y = Math.atan2(dx, dz);
    S.walkT += ctx.deltaTime;
    walkCycle(S, S.walkT, 1.0);
    return false;
}

if (S.phase === 'goto_table') {
    const tbl = S.tables[S.tableIdx];
    if (moveTo(tbl)) {
        S.phase = 'pickup';
        S.timer = 0;
    }
} else if (S.phase === 'pickup') {
    S.timer += ctx.deltaTime;
    const t = S.timer;
    idleBreathing(S, ctx.elapsed);
    // Bend to pick up: torso leans forward, right arm reaches down
    const bend = Math.min(t * 2, 1);
    S.body.upperTorsoPivot.rotation.x = bend * 0.5;
    S.body.rightArm.shoulderPivot.rotation.x = bend * 1.2;
    S.body.rightArm.elbowPivot.rotation.x = -bend * 0.8;
    S.body.leftLeg.kneePivot.rotation.x = bend * 0.2;
    S.body.rightLeg.kneePivot.rotation.x = bend * 0.2;
    if (t > 1.5) {
        // Stand back up
        S.body.upperTorsoPivot.rotation.x = 0;
        S.tray.visible = true;
        // Hold tray: right arm out, elbow bent
        S.body.rightArm.shoulderPivot.rotation.x = -0.3;
        S.body.rightArm.shoulderPivot.rotation.z = -0.8;
        S.body.rightArm.elbowPivot.rotation.x = -1.2;
        S.phase = 'goto_kitchen';
        S.walkT = 0;
    }
} else if (S.phase === 'goto_kitchen') {
    // Keep tray arm posed while walking (override walk cycle for right arm)
    if (moveTo(S.kitchen)) {
        S.phase = 'dropoff';
        S.timer = 0;
    }
    // Override right arm to hold tray steady
    S.body.rightArm.shoulderPivot.rotation.x = -0.3;
    S.body.rightArm.shoulderPivot.rotation.z = -0.8;
    S.body.rightArm.elbowPivot.rotation.x = -1.2;
} else if (S.phase === 'dropoff') {
    S.timer += ctx.deltaTime;
    idleBreathing(S, ctx.elapsed);
    if (S.timer > 1.0) {
        S.tray.visible = false;
        S.tableIdx = (S.tableIdx + 1) % S.tables.length;
        S.phase = 'goto_table';
        S.walkT = 0;
    }
}
"""

# ---------------------------------------------------------------------------
# Seated patron — rich idle animation
# ---------------------------------------------------------------------------

SEATED_ANIM_SCRIPT = IDLE_FN + r"""
if (!ctx.state.built) return;
const S = ctx.state;
if (!S.s_init) {
    S.s_init = true;
    S.seed = ctx.entity.position.x * 7 + ctx.entity.position.z * 13;
    // Sit: lower hips, bend knees 90 degrees
    S.body.hips.position.y = 0.55;
    S.body.leftLeg.hipPivot.rotation.x = -1.57;
    S.body.rightLeg.hipPivot.rotation.x = -1.57;
    S.body.leftLeg.kneePivot.rotation.x = 1.57;
    S.body.rightLeg.kneePivot.rotation.x = 1.57;
    S.body.leftLeg.anklePivot.rotation.x = 0;
    S.body.rightLeg.anklePivot.rotation.x = 0;
}

const t = ctx.elapsed;
const seed = S.seed;
const b = S.body;

// Breathing
const breathe = Math.sin(t * 1.5 + seed);
b.upperTorsoPivot.rotation.x = breathe * 0.015;

// Head: look around slowly, occasionally nod
b.headPivot.rotation.y = Math.sin(t * 0.3 + seed) * 0.4 + Math.sin(t * 0.13 + seed * 2) * 0.2;
b.headPivot.rotation.x = Math.sin(t * 0.2 + seed * 3) * 0.08;
b.neckPivot.rotation.y = Math.sin(t * 0.25 + seed) * 0.1;

// Arms: resting on table or lap with occasional gestures
const gesture = Math.sin(t * 0.15 + seed * 5);
// Left arm rests on table
b.leftArm.shoulderPivot.rotation.x = -0.7 + gesture * 0.05;
b.leftArm.elbowPivot.rotation.x = -0.9;
b.leftArm.wristPivot.rotation.x = gesture * 0.1;
// Right arm: occasional lift (drinking/gesturing)
const drink = Math.sin(t * 0.08 + seed * 7);
if (drink > 0.85) {
    // Drinking motion
    const lift = (drink - 0.85) / 0.15;
    b.rightArm.shoulderPivot.rotation.x = -0.5 - lift * 0.6;
    b.rightArm.elbowPivot.rotation.x = -1.2 - lift * 0.4;
    b.rightArm.wristPivot.rotation.x = lift * 0.3;
    b.headPivot.rotation.x = lift * 0.15;  // tilt head back to drink
} else {
    b.rightArm.shoulderPivot.rotation.x = -0.6 + Math.sin(t * 0.2 + seed) * 0.06;
    b.rightArm.elbowPivot.rotation.x = -0.8;
    b.rightArm.wristPivot.rotation.x = 0;
}

// Slight body lean/weight shift
b.hips.rotation.z = Math.sin(t * 0.12 + seed) * 0.03;
b.upperTorsoPivot.rotation.z = Math.sin(t * 0.1 + seed * 2) * 0.02;
"""

# ---------------------------------------------------------------------------
# Wander animation — walk cycle with random destination
# ---------------------------------------------------------------------------

WANDER_ANIM_SCRIPT = WALK_CYCLE_FN + IDLE_FN + r"""
if (!ctx.state.built) return;
const S = ctx.state;
if (!S.wn_init) {
    S.wn_init = true;
    const b = ctx.props.bounds || [-7, -4, 7, 5];
    S.bounds = {minX: b[0], minZ: b[1], maxX: b[2], maxZ: b[3]};
    S.target = null;
    S.waitTimer = 0;
    S.walking = false;
    S.speed = ctx.props.speed || 1.0;
    S.walkT = 0;
}

if (!S.walking) {
    S.waitTimer += ctx.deltaTime;
    idleBreathing(S, ctx.elapsed);
    // Look around while waiting
    S.body.headPivot.rotation.y = Math.sin(ctx.elapsed * 0.5 + ctx.entity.position.x) * 0.5;
    S.body.headPivot.rotation.x = Math.sin(ctx.elapsed * 0.3) * 0.05;

    if (S.waitTimer > 2 + Math.random() * 4) {
        const bnd = S.bounds;
        S.target = {
            x: bnd.minX + Math.random() * (bnd.maxX - bnd.minX),
            z: bnd.minZ + Math.random() * (bnd.maxZ - bnd.minZ),
        };
        S.walking = true;
        S.waitTimer = 0;
        S.walkT = 0;
    }
} else {
    const dx = S.target.x - ctx.entity.position.x;
    const dz = S.target.z - ctx.entity.position.z;
    const dist = Math.sqrt(dx * dx + dz * dz);
    if (dist < 0.3) {
        S.walking = false;
    } else {
        const step = Math.min(S.speed * ctx.deltaTime, dist);
        ctx.entity.position.x += (dx / dist) * step;
        ctx.entity.position.z += (dz / dist) * step;
        ctx.entity.rotation.y = Math.atan2(dx, dz);
        S.walkT += ctx.deltaTime;
        walkCycle(S, S.walkT, S.speed);
    }
}
"""

# ---------------------------------------------------------------------------
# Barista — standing work animation
# ---------------------------------------------------------------------------

BARISTA_ANIM_SCRIPT = IDLE_FN + r"""
if (!ctx.state.built) return;
const S = ctx.state;
if (!S.b_init) {
    S.b_init = true;
    S.seed = ctx.entity.position.x * 11 + ctx.entity.position.z * 17;
    S.actionTimer = 0;
    S.action = 'idle';
}

const t = ctx.elapsed;
const seed = S.seed;
const b = S.body;
S.actionTimer += ctx.deltaTime;

if (S.action === 'idle') {
    idleBreathing(S, t + seed);
    // Weight shift
    b.hips.position.x = Math.sin(t * 0.3 + seed) * 0.03;
    b.hips.rotation.z = Math.sin(t * 0.3 + seed) * 0.02;
    // Look around
    b.headPivot.rotation.y = Math.sin(t * 0.4 + seed) * 0.35;

    if (S.actionTimer > 3 + Math.random() * 4) {
        S.action = Math.random() > 0.5 ? 'reach' : 'wipe';
        S.actionTimer = 0;
    }
} else if (S.action === 'reach') {
    // Reach for a cup/machine
    const p = Math.min(S.actionTimer / 1.5, 1);
    const ease = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;

    b.rightArm.shoulderPivot.rotation.x = -ease * 1.0;
    b.rightArm.shoulderPivot.rotation.z = -ease * 0.3;
    b.rightArm.elbowPivot.rotation.x = -ease * 0.6;
    b.upperTorsoPivot.rotation.y = ease * 0.2;
    b.headPivot.rotation.y = ease * 0.3;

    if (S.actionTimer > 3.0) {
        S.action = 'idle';
        S.actionTimer = 0;
    }
} else if (S.action === 'wipe') {
    // Wiping counter motion
    const p = S.actionTimer;
    const wipe = Math.sin(p * 4) * 0.3;

    b.rightArm.shoulderPivot.rotation.x = -0.8;
    b.rightArm.elbowPivot.rotation.x = -0.5;
    b.rightArm.wristPivot.rotation.z = wipe;
    b.upperTorsoPivot.rotation.x = 0.15;
    b.upperTorsoPivot.rotation.y = wipe * 0.2;

    if (S.actionTimer > 2.5) {
        S.action = 'idle';
        S.actionTimer = 0;
        b.rightArm.wristPivot.rotation.z = 0;
        b.upperTorsoPivot.rotation.x = 0;
    }
}

// Left arm rests on counter
b.leftArm.shoulderPivot.rotation.x = -0.3;
b.leftArm.elbowPivot.rotation.x = -0.5;
"""

NPC_GREET_SCRIPT = r"""
const dx = ctx.camera.position.x - ctx.entity.position.x;
const dz = ctx.camera.position.z - ctx.entity.position.z;
ctx.entity.rotation.y = Math.atan2(dx, dz);
console.log(ctx.entity.userData.entityName + ': ' + (ctx.props.greeting || 'Hello!'));
"""
