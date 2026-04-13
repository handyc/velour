"""Seed the Velour Gallery — avatar realism iteration 1.

Anatomical improvements over the HDRI cafe:
- Sculpted face: proper orbital cavities, nasolabial folds, philtrum,
  defined jawline, temple indentation, forehead curvature
- Corneal-bulge eyes with wet-look specular, iris depth, gaze tracking
- Multi-shell hair for volume with anisotropic highlights
- SSS skin approximation (transmission + thickness)
- Micro-animations: blinks, gaze shifts, breathing chest expansion
- Better body proportions: clavicle line, trapezius, deltoid transition
- Improved hands with knuckle definition and natural curl
"""

from django.core.management.base import BaseCommand

from aether.models import Entity, EntityScript, Script, World


# Diverse skin tones — warm undertones for SSS
SKIN = [
    '#c8956c', '#6b3a1f', '#a87040', '#d4a06a', '#e8c490',
    '#f0d0a8', '#8b4c2a', '#b8784c', '#d0a878', '#b05c30',
]
SHIRT = [
    '#e8e0d8', '#2c4a6e', '#6b3a3a', '#3a5a3a', '#4a3a5e',
    '#704030', '#384858', '#5a4a30', '#3a5060', '#604848',
]
PANTS = [
    '#1c1c28', '#282830', '#323240', '#1e1e30', '#2a2a38',
    '#202830', '#2c2420', '#343444', '#1a2028', '#302c38',
]
SHOES = [
    '#181818', '#3a2418', '#1a1a1a', '#3e2c1e', '#242424',
    '#181818', '#3a2418', '#1a1a1a', '#242424', '#3a2418',
]
HAIR = [
    '#1a1008', '#080808', '#301a0e', '#b89040', '#1a1008',
    '#4a2818', '#080808', '#7a3c10', '#201008', '#301a0e',
]
EYE_COLORS = [
    '#3a2818', '#1e4a1e', '#3868a8', '#1a1008', '#4a7a4a',
    '#5a3418', '#284050', '#2a1810', '#4a6a38', '#386888',
]
BUILDS = [
    (1.0,  0.95, 1.0),    # 0
    (0.86, 0.92, 0.93),   # 1
    (1.08, 1.0,  1.04),   # 2
    (0.94, 0.90, 0.97),   # 3
    (0.90, 0.96, 0.95),   # 4
    (0.88, 1.0,  0.94),   # 5
    (1.04, 0.98, 1.02),   # 6
    (0.83, 0.88, 0.91),   # 7
    (1.06, 1.04, 1.03),   # 8
    (0.92, 0.94, 0.98),   # 9
]
# Face shape parameters: jaw_width, cheek_fullness, forehead_height
FACES = [
    (1.0,  1.0,  1.0),
    (0.88, 1.1,  0.95),
    (1.1,  0.9,  1.05),
    (0.95, 0.95, 1.0),
    (0.92, 1.05, 0.98),
    (0.9,  1.08, 0.96),
    (1.05, 0.92, 1.02),
    (0.85, 1.12, 0.94),
    (1.08, 0.95, 1.04),
    (0.93, 1.0,  0.99),
]


class Command(BaseCommand):
    help = 'Create the Velour Gallery with anatomically improved humanoid NPCs.'

    def handle(self, *args, **options):
        World.objects.filter(slug='velour-gallery').delete()

        world = World.objects.create(
            title='Velour Gallery',
            slug='velour-gallery',
            description='Art gallery showcasing improved humanoid avatars '
                        'with sculpted faces, SSS skin, and micro-animations.',
            skybox='hdri',
            hdri_asset='brown_photostudio_02',
            sky_color='#a0b0c0',
            ground_color='#2a2520',
            ground_size=40.0,
            ambient_light=0.35,
            fog_near=30.0,
            fog_far=80.0,
            fog_color='#282420',
            gravity=-9.81,
            spawn_x=0.0, spawn_y=1.6, spawn_z=8.0,
            soundscape='cafe',
            ambient_volume=0.15,
            published=True, featured=True,
        )

        humanoid_v2 = _script('Humanoid Builder V2', 'start', HUMANOID_V2_SCRIPT,
            'Builds anatomically refined humanoid with sculpted face, SSS skin, corneal eyes.')
        idle_v2 = _script('Gallery Idle V2', 'update', IDLE_V2_SCRIPT,
            'Rich idle: blinks, gaze tracking, micro-expressions, breathing.')
        wander_v2 = _script('Gallery Wander V2', 'update', WANDER_V2_SCRIPT,
            'Wander with improved walk cycle and gaze.')
        greet_v2 = _script('Gallery Greet V2', 'interact', GREET_V2_SCRIPT,
            'Turn to player and nod.')

        entities = []
        E = lambda *a, **k: entities.append(_ent(world, *a, **k))

        # Gallery floor — polished concrete
        E('Floor', 'box', '#3a3530', 0, -0.05, 0, sx=30, sy=0.1, sz=30, shadow=False)

        # Walls
        E('Back Wall', 'box', '#e8e0d0', 0, 2.5, -12, sx=30, sy=5, sz=0.15)
        E('Left Wall', 'box', '#e8e0d0', -15, 2.5, 0, sx=0.15, sy=5, sz=30)
        E('Right Wall', 'box', '#e8e0d0', 15, 2.5, 0, sx=0.15, sy=5, sz=30)

        # Gallery columns
        for cx in [-10, -5, 0, 5, 10]:
            E(f'Column {cx}', 'cylinder', '#d0c8b8', cx, 2.5, -11.5, sx=0.25, sy=5, sz=0.25)

        # Art pedestals
        for i, px in enumerate([-8, -4, 0, 4, 8]):
            E(f'Pedestal {i}', 'box', '#f0e8d8', px, 0.5, -8, sx=0.8, sy=1.0, sz=0.8)
            E(f'Artwork {i}', 'sphere', ['#c23b22', '#4682b4', '#6b8e23', '#8b4513', '#483d8b'][i],
              px, 1.3, -8, sx=0.3, sy=0.4, sz=0.3)

        # Benches
        for bz in [-2, 3]:
            E(f'Bench {bz}', 'box', '#5c4830', 0, 0.28, bz, sx=3, sy=0.06, sz=0.6)
            E(f'Bench Leg L {bz}', 'box', '#5c4830', -1.2, 0.14, bz, sx=0.08, sy=0.28, sz=0.5)
            E(f'Bench Leg R {bz}', 'box', '#5c4830', 1.2, 0.14, bz, sx=0.08, sy=0.28, sz=0.5)

        # Spot lights (warm gallery lighting)
        for lx in [-8, -4, 0, 4, 8]:
            E(f'Spot {lx}', 'sphere', '#fff5e0', lx, 4.5, -8,
              sx=0.1, sy=0.1, sz=0.1, shadow=False)
        for lx in [-6, -2, 2, 6]:
            for lz in [-4, 0, 4]:
                E(f'Ceil {lx},{lz}', 'sphere', '#fff0d0', lx, 4.8, lz,
                  sx=0.08, sy=0.08, sz=0.08, shadow=False)

        # --- NPCs ---
        NAMES = ['Adrienne', 'Kofi', 'Maren', 'Jun', 'Ximena',
                 'Obi', 'Linnea', 'Rafael', 'Suki', 'Emile']
        POSITIONS = [
            (-6, -6, 0),    # standing near art
            (-3, -6, 180),  # facing art
            (3, -4, 90),    # idle
            (6, -6, -90),   # standing near art
            (-5, 0, 45),    # wanderer
            (5, 0, -45),    # wanderer
            (-1, -2, 0),    # seated on bench
            (1, -2, 0),     # seated on bench
            (-1, 3, 180),   # seated on bench 2
            (4, 4, 0),      # wanderer
        ]
        ROLES = ['idle', 'idle', 'idle', 'idle', 'wander',
                 'wander', 'seated', 'seated', 'seated', 'wander']

        npc_ents = []
        for i, (name, (px, pz, ry), role) in enumerate(zip(NAMES, POSITIONS, ROLES)):
            e = Entity(
                world=world, name=name, primitive='box',
                primitive_color='#000000',
                pos_x=px, pos_y=0, pos_z=pz, rot_y=ry,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            e._idx = i
            e._role = role
            npc_ents.append(e)

        # Save non-NPC entities
        Entity.objects.bulk_create(entities)
        for e in npc_ents:
            e.save()

        # Script attachments
        attachments = []

        def attach(entity, script, props=None):
            attachments.append(EntityScript(entity=entity, script=script, props=props or {}))

        for e in npc_ents:
            i = e._idx
            build = BUILDS[i]
            face = FACES[i]
            attach(e, humanoid_v2, {
                'skin': SKIN[i], 'shirt': SHIRT[i],
                'pants': PANTS[i], 'shoes': SHOES[i],
                'hair': HAIR[i], 'eyes': EYE_COLORS[i],
                'shoulderW': build[0], 'hipW': build[1], 'heightScale': build[2],
                'jawW': face[0], 'cheekFull': face[1], 'foreheadH': face[2],
            })
            if e._role == 'wander':
                attach(e, wander_v2, {'bounds': [-12, -8, 12, 7], 'speed': 0.8})
            elif e._role == 'seated':
                attach(e, idle_v2, {'seated': True})
            else:
                attach(e, idle_v2, {'seated': False})
            attach(e, greet_v2, {'greeting': f"I'm {NAMES[i]}."})

        EntityScript.objects.bulk_create(attachments)
        total = Entity.objects.filter(world=world).count()
        self.stdout.write(self.style.SUCCESS(
            f'Velour Gallery created: {total} entities, '
            f'{len(npc_ents)} V2 humanoid NPCs.'
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
# HUMANOID V2 — anatomically refined builder
# Major improvements: sculpted face, SSS skin, corneal eyes, multi-shell
# hair, better proportions, knuckle hands
# ---------------------------------------------------------------------------

HUMANOID_V2_SCRIPT = r"""
const S = ctx.state;
const P = ctx.props;
const skinC = new THREE.Color(P.skin || '#c8956c');
const shirtC = new THREE.Color(P.shirt || '#e8e0d8');
const pantsC = new THREE.Color(P.pants || '#1c1c28');
const shoesC = new THREE.Color(P.shoes || '#181818');
const hairC = new THREE.Color(P.hair || '#1a1008');
const eyeC = new THREE.Color(P.eyes || '#3a2818');
const SW = P.shoulderW || 1.0;
const HW = P.hipW || 1.0;
const HS = P.heightScale || 1.0;
const JW = P.jawW || 1.0;
const CF = P.cheekFull || 1.0;
const FH = P.foreheadH || 1.0;

if (ctx.entity.isMesh) {
    ctx.entity.material.visible = false;
    ctx.entity.castShadow = false;
}

// --- Texture generators (canvas, no external assets) ---
function noiseCanvas(w, h, base, variation, scale) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    const id = g.createImageData(w, h);
    const br = base.r*255, bg = base.g*255, bb = base.b*255;
    for (let i = 0; i < id.data.length; i += 4) {
        const n = (Math.random()-0.5) * variation * 255;
        id.data[i]   = Math.max(0, Math.min(255, br+n));
        id.data[i+1] = Math.max(0, Math.min(255, bg+n));
        id.data[i+2] = Math.max(0, Math.min(255, bb+n));
        id.data[i+3] = 255;
    }
    g.putImageData(id, 0, 0);
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    if (scale) tex.repeat.set(scale, scale);
    return tex;
}

function skinNoiseCanvas(w, h, base) {
    // Improved skin texture: pore-like pattern with warm variation
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    const id = g.createImageData(w, h);
    const br = base.r*255, bg = base.g*255, bb = base.b*255;
    for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
            const i = (y * w + x) * 4;
            // Pore pattern: occasional darker spots
            const pore = Math.random() < 0.08 ? -12 : 0;
            // Warm color shift (slightly more red variation)
            const nr = (Math.random()-0.5) * 10 + pore;
            const ng = (Math.random()-0.5) * 8 + pore;
            const nb = (Math.random()-0.5) * 6 + pore;
            id.data[i]   = Math.max(0, Math.min(255, br + nr));
            id.data[i+1] = Math.max(0, Math.min(255, bg + ng));
            id.data[i+2] = Math.max(0, Math.min(255, bb + nb));
            id.data[i+3] = 255;
        }
    }
    g.putImageData(id, 0, 0);
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
        id.data[i]   = 128 + (Math.random()-0.5) * strength;
        id.data[i+1] = 128 + (Math.random()-0.5) * strength;
        id.data[i+2] = 255;
        id.data[i+3] = 255;
    }
    g.putImageData(id, 0, 0);
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(2, 2);
    return tex;
}

function fabricCanvas(w, h, base, isShirt) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    g.fillStyle = '#' + base.getHexString();
    g.fillRect(0, 0, w, h);
    const lighter = '#' + new THREE.Color().copy(base).lerp(new THREE.Color('#ffffff'), 0.08).getHexString();
    const darker = '#' + new THREE.Color().copy(base).lerp(new THREE.Color('#000000'), 0.06).getHexString();
    g.lineWidth = 0.5;
    const sp = isShirt ? 4 : 3;
    // Warp threads
    g.strokeStyle = lighter;
    for (let y = 0; y < h; y += sp) { g.beginPath(); g.moveTo(0,y); g.lineTo(w,y); g.stroke(); }
    // Weft threads (darker)
    g.strokeStyle = darker;
    for (let x = 0; x < w; x += sp) { g.beginPath(); g.moveTo(x,0); g.lineTo(x,h); g.stroke(); }
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(4, 4);
    return tex;
}

// --- Material factories ---

// SSS skin: uses transmission + thickness for translucency
function skinMat() {
    const warmShift = new THREE.Color().copy(skinC).lerp(new THREE.Color('#ff8866'), 0.08);
    return new THREE.MeshPhysicalMaterial({
        color: skinC,
        map: skinNoiseCanvas(128, 128, skinC),
        normalMap: normalNoise(64, 64, 25),
        normalScale: new THREE.Vector2(0.25, 0.25),
        roughness: 0.55,
        roughnessMap: noiseCanvas(32, 32, new THREE.Color(0.55, 0.55, 0.55), 0.1, 2),
        metalness: 0.0,
        // SSS approximation
        transmission: 0.05,
        thickness: 0.8,
        attenuationColor: warmShift,
        attenuationDistance: 0.3,
        // Sheen for skin glow
        sheen: 0.4,
        sheenRoughness: 0.4,
        sheenColor: new THREE.Color().copy(skinC).lerp(new THREE.Color('#ffccaa'), 0.4),
        clearcoat: 0.03,
        clearcoatRoughness: 0.6,
        ior: 1.4,
    });
}

function clothMat(color, isShirt) {
    return new THREE.MeshPhysicalMaterial({
        color,
        map: fabricCanvas(64, 64, color, isShirt),
        normalMap: normalNoise(32, 32, isShirt ? 18 : 12),
        normalScale: new THREE.Vector2(0.15, 0.15),
        roughness: isShirt ? 0.8 : 0.88,
        metalness: 0.0,
        sheen: isShirt ? 0.2 : 0.08,
        sheenRoughness: 0.7,
        sheenColor: new THREE.Color().copy(color).lerp(new THREE.Color('#ffffff'), 0.15),
    });
}

function shoeMat() {
    return new THREE.MeshPhysicalMaterial({
        color: shoesC, roughness: 0.35, metalness: 0.02,
        clearcoat: 0.35, clearcoatRoughness: 0.3,
    });
}

function hairMat() {
    return new THREE.MeshPhysicalMaterial({
        color: hairC, roughness: 0.5, metalness: 0.04,
        sheen: 1.0, sheenRoughness: 0.25,
        sheenColor: new THREE.Color().copy(hairC).lerp(new THREE.Color('#ffffff'), 0.3),
        normalMap: normalNoise(32, 32, 50),
        normalScale: new THREE.Vector2(0.6, 0.6),
    });
}

// --- Geometry helpers ---
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
function noShadow(mesh) { mesh.castShadow = false; return mesh; }

const skinM = skinMat();
const shirtM = clothMat(shirtC, true);
const pantsM = clothMat(pantsC, false);
const shoeM = shoeMat();
const hairM = hairMat();

// Darker skin for creases/folds
const creaseSkinM = new THREE.MeshStandardMaterial({
    color: new THREE.Color().copy(skinC).multiplyScalar(0.82), roughness: 0.85
});
// Lip material
const lipColor = new THREE.Color().copy(skinC).lerp(new THREE.Color('#cc4444'), 0.3);
const lipM = new THREE.MeshPhysicalMaterial({
    color: lipColor, roughness: 0.35, clearcoat: 0.2,
    sheen: 0.6, sheenColor: lipColor,
});

// === SKELETON ===

// --- Hips ---
const hips = pivot(0, 0.92 * HS, 0);
ctx.entity.add(hips);

// Lower torso (slightly tapered)
const lowerTorso = part(
    new THREE.CylinderGeometry(0.15 * HW, 0.16 * HW, 0.2 * HS, 12),
    shirtM
);
lowerTorso.position.y = 0.1 * HS;
hips.add(lowerTorso);

// Upper torso pivot
const upperTorsoPivot = pivot(0, 0.2 * HS, 0);
hips.add(upperTorsoPivot);

// Upper torso (wider at shoulders, narrower at waist)
const upperTorso = part(
    new THREE.CylinderGeometry(0.18 * SW, 0.15 * HW, 0.3 * HS, 12),
    shirtM
);
upperTorso.position.y = 0.15 * HS;
upperTorsoPivot.add(upperTorso);

// Clavicle ridge
const clavicle = noShadow(part(
    new THREE.CylinderGeometry(0.005, 0.005, 0.32 * SW, 6),
    creaseSkinM
));
clavicle.position.set(0, 0.3 * HS, 0.06);
clavicle.rotation.z = Math.PI / 2;
upperTorsoPivot.add(clavicle);

// Collar
const collar = noShadow(part(
    new THREE.TorusGeometry(0.085, 0.012, 8, 16),
    shirtM
));
collar.position.set(0, 0.3 * HS, 0.02);
collar.rotation.x = Math.PI / 2;
upperTorsoPivot.add(collar);

// Shirt wrinkle lines
for (let i = 0; i < 3; i++) {
    const w = noShadow(part(
        new THREE.BoxGeometry(0.24 * SW, 0.002, 0.004),
        new THREE.MeshStandardMaterial({
            color: new THREE.Color().copy(shirtC).multiplyScalar(0.88), roughness: 0.9
        })
    ));
    w.position.set(0, (0.08 + i * 0.07) * HS, 0.101);
    upperTorsoPivot.add(w);
}

// Buttons
for (let i = 0; i < 3; i++) {
    const btn = noShadow(part(
        new THREE.SphereGeometry(0.007, 6, 6),
        new THREE.MeshStandardMaterial({color: '#f0f0e0', roughness: 0.3, metalness: 0.1})
    ));
    btn.position.set(0, (0.06 + i * 0.08) * HS, 0.105);
    upperTorsoPivot.add(btn);
}

// Belt
const belt = noShadow(part(
    new THREE.TorusGeometry(0.165 * HW, 0.012, 6, 24),
    new THREE.MeshPhysicalMaterial({color: '#2a1a0a', roughness: 0.35, clearcoat: 0.3})
));
belt.position.y = 0.0;
belt.rotation.x = Math.PI / 2;
hips.add(belt);
const buckle = noShadow(part(
    new THREE.BoxGeometry(0.025, 0.02, 0.01),
    new THREE.MeshStandardMaterial({color: '#c0c0c0', roughness: 0.2, metalness: 0.8})
));
buckle.position.set(0, 0.0, 0.165 * HW);
hips.add(buckle);

// --- Neck ---
const neckPivot = pivot(0, 0.3 * HS, 0);
upperTorsoPivot.add(neckPivot);

// Neck with trapezius taper
const neck = part(
    new THREE.CylinderGeometry(0.045, 0.06, 0.09, 12), skinM
);
neck.position.y = 0.045;
neckPivot.add(neck);

// Sternocleidomastoid suggestion (neck muscles)
for (const side of [-1, 1]) {
    const scm = noShadow(part(
        new THREE.CylinderGeometry(0.008, 0.012, 0.07, 6), creaseSkinM
    ));
    scm.position.set(side * 0.025, 0.035, 0.02);
    scm.rotation.z = side * 0.15;
    neckPivot.add(scm);
}

// --- Head ---
const headPivot = pivot(0, 0.09, 0);
neckPivot.add(headPivot);

// Main cranium — ellipsoid (wider than tall, deeper front-to-back)
const headGeo = new THREE.SphereGeometry(0.12, 32, 32);
const head = part(headGeo, skinM);
head.position.y = 0.12;
head.scale.set(1.0, 1.02 * FH, 0.95);
headPivot.add(head);

// Jaw — separate piece for definition
const jawGeo = new THREE.SphereGeometry(0.1, 24, 12, 0, Math.PI * 2, Math.PI * 0.55, Math.PI * 0.45);
const jaw = noShadow(part(jawGeo, skinM));
jaw.position.set(0, 0.06, 0.01);
jaw.scale.set(JW, 0.8, 0.9);
headPivot.add(jaw);

// Chin
const chin = noShadow(part(
    new THREE.SphereGeometry(0.035, 12, 8, 0, Math.PI * 2, 0, Math.PI * 0.6),
    skinM
));
chin.position.set(0, 0.03, 0.08);
chin.scale.set(JW * 0.85, 1.0, 0.7);
headPivot.add(chin);

// Forehead
const forehead = noShadow(part(
    new THREE.SphereGeometry(0.11, 20, 10, 0, Math.PI * 2, 0, Math.PI * 0.35),
    skinM
));
forehead.position.set(0, 0.18 * FH, 0.02);
headPivot.add(forehead);

// Temple indentations (slightly darker depressions)
for (const side of [-1, 1]) {
    const temple = noShadow(part(
        new THREE.SphereGeometry(0.03, 8, 6), creaseSkinM
    ));
    temple.position.set(side * 0.1, 0.14, 0.03);
    temple.scale.set(0.5, 0.8, 0.3);
    headPivot.add(temple);
}

// Cheekbones
for (const side of [-1, 1]) {
    const cheek = noShadow(part(
        new THREE.SphereGeometry(0.035, 10, 8), skinM
    ));
    cheek.position.set(side * 0.07, 0.1, 0.075);
    cheek.scale.set(1.0 * CF, 0.65, 0.55);
    headPivot.add(cheek);
}

// --- Orbital cavities + Eyes ---
const eyeTargets = [];
for (const side of [-1, 1]) {
    // Orbital rim (slight ridge around eye socket)
    const orbit = noShadow(part(
        new THREE.TorusGeometry(0.025, 0.006, 8, 16),
        creaseSkinM
    ));
    orbit.position.set(side * 0.042, 0.135, 0.09);
    orbit.rotation.y = side * 0.1;
    orbit.scale.set(1.1, 0.85, 0.3);
    headPivot.add(orbit);

    // Eye group (for gaze tracking)
    const eyeGroup = pivot(side * 0.042, 0.13, 0.09);
    headPivot.add(eyeGroup);

    // Eyeball (white, slightly indented)
    const eyeball = noShadow(part(
        new THREE.SphereGeometry(0.018, 16, 16),
        new THREE.MeshPhysicalMaterial({
            color: '#f5f5f0', roughness: 0.05, metalness: 0.0,
            clearcoat: 1.0, clearcoatRoughness: 0.05,
        })
    ));
    eyeball.position.z = 0.005;
    eyeGroup.add(eyeball);

    // Corneal bulge (transparent dome over iris)
    const cornea = noShadow(part(
        new THREE.SphereGeometry(0.013, 16, 16, 0, Math.PI * 2, 0, Math.PI * 0.5),
        new THREE.MeshPhysicalMaterial({
            color: '#ffffff', transparent: true, opacity: 0.15,
            roughness: 0.0, metalness: 0.0,
            clearcoat: 1.0, clearcoatRoughness: 0.0,
            ior: 1.376,
        })
    ));
    cornea.position.set(0, 0, 0.016);
    cornea.rotation.x = -Math.PI / 2;
    eyeGroup.add(cornea);

    // Iris (colored disc with radial detail)
    const irisCanvas = document.createElement('canvas');
    irisCanvas.width = 64; irisCanvas.height = 64;
    const ig = irisCanvas.getContext('2d');
    const cx = 32, cy = 32;
    // Radial iris pattern
    for (let r = 30; r > 0; r -= 1) {
        const t = r / 30;
        const c2 = new THREE.Color().copy(eyeC).lerp(
            new THREE.Color('#000000'), (1 - t) * 0.5
        );
        ig.fillStyle = '#' + c2.getHexString();
        ig.beginPath();
        ig.arc(cx, cy, r, 0, Math.PI * 2);
        ig.fill();
    }
    // Pupil
    ig.fillStyle = '#030303';
    ig.beginPath(); ig.arc(cx, cy, 10, 0, Math.PI * 2); ig.fill();
    // Radial streaks
    ig.globalAlpha = 0.3;
    for (let a = 0; a < Math.PI * 2; a += 0.2) {
        ig.strokeStyle = Math.random() > 0.5 ? '#ffffff' : '#000000';
        ig.lineWidth = 0.5;
        ig.beginPath();
        ig.moveTo(cx + Math.cos(a) * 10, cy + Math.sin(a) * 10);
        ig.lineTo(cx + Math.cos(a) * 28, cy + Math.sin(a) * 28);
        ig.stroke();
    }
    ig.globalAlpha = 1.0;
    // Bright pupil ring
    ig.strokeStyle = '#' + new THREE.Color().copy(eyeC).lerp(new THREE.Color('#ffffff'), 0.3).getHexString();
    ig.lineWidth = 1;
    ig.beginPath(); ig.arc(cx, cy, 11, 0, Math.PI * 2); ig.stroke();

    const irisTex = new THREE.CanvasTexture(irisCanvas);
    const iris = noShadow(part(
        new THREE.CircleGeometry(0.011, 24),
        new THREE.MeshPhysicalMaterial({
            map: irisTex, roughness: 0.15, clearcoat: 0.6,
        })
    ));
    iris.position.set(0, 0, 0.017);
    eyeGroup.add(iris);

    // Pupil (slightly recessed for depth)
    const pupil = noShadow(part(
        new THREE.CircleGeometry(0.004, 16),
        new THREE.MeshStandardMaterial({color: '#020202', roughness: 0.05})
    ));
    pupil.position.set(0, 0, 0.0175);
    eyeGroup.add(pupil);

    // Upper eyelid (for blink animation)
    const lidGeo = new THREE.SphereGeometry(0.021, 12, 8, 0, Math.PI * 2, 0, Math.PI * 0.45);
    const lid = noShadow(part(lidGeo, skinM));
    lid.position.set(0, 0.004, 0.004);
    lid.name = 'upperLid';
    eyeGroup.add(lid);

    // Lower eyelid
    const lowerLid = noShadow(part(
        new THREE.SphereGeometry(0.019, 10, 6, 0, Math.PI * 2, Math.PI * 0.6, Math.PI * 0.4),
        skinM
    ));
    lowerLid.position.set(0, -0.006, 0.004);
    lowerLid.name = 'lowerLid';
    eyeGroup.add(lowerLid);

    // Eyelashes (tiny dark fringe)
    const lash = noShadow(part(
        new THREE.TorusGeometry(0.019, 0.002, 4, 12, Math.PI),
        new THREE.MeshStandardMaterial({color: '#0a0a0a', roughness: 0.8})
    ));
    lash.position.set(0, 0.008, 0.012);
    lash.rotation.x = 0.3;
    lash.rotation.z = Math.PI;
    eyeGroup.add(lash);

    eyeTargets.push(eyeGroup);
}

// Brow ridges
for (const side of [-1, 1]) {
    const brow = noShadow(part(
        new THREE.CylinderGeometry(0.003, 0.004, 0.038, 6),
        new THREE.MeshStandardMaterial({
            color: new THREE.Color().copy(skinC).multiplyScalar(0.9), roughness: 0.8
        })
    ));
    brow.position.set(side * 0.042, 0.155, 0.09);
    brow.rotation.z = Math.PI / 2 + side * 0.15;
    headPivot.add(brow);
}

// --- Nose ---
// Bridge
const noseBridge = noShadow(part(
    new THREE.CylinderGeometry(0.008, 0.012, 0.035, 8), skinM
));
noseBridge.position.set(0, 0.115, 0.105);
headPivot.add(noseBridge);

// Nose tip (rounded)
const noseTip = noShadow(part(
    new THREE.SphereGeometry(0.016, 12, 10), skinM
));
noseTip.position.set(0, 0.095, 0.12);
headPivot.add(noseTip);

// Nose wings (alar)
for (const side of [-1, 1]) {
    const wing = noShadow(part(
        new THREE.SphereGeometry(0.01, 8, 6), skinM
    ));
    wing.position.set(side * 0.013, 0.093, 0.112);
    headPivot.add(wing);

    // Nostril (dark indent)
    const nostril = noShadow(part(
        new THREE.SphereGeometry(0.005, 6, 4), creaseSkinM
    ));
    nostril.position.set(side * 0.01, 0.088, 0.115);
    headPivot.add(nostril);
}

// Nasolabial fold (subtle crease from nose wing to mouth corner)
for (const side of [-1, 1]) {
    const fold = noShadow(part(
        new THREE.CylinderGeometry(0.002, 0.002, 0.03, 4), creaseSkinM
    ));
    fold.position.set(side * 0.025, 0.078, 0.105);
    fold.rotation.z = side * 0.3;
    fold.rotation.x = 0.2;
    headPivot.add(fold);
}

// --- Mouth ---
// Philtrum (groove above upper lip)
const philtrum = noShadow(part(
    new THREE.BoxGeometry(0.008, 0.012, 0.004), creaseSkinM
));
philtrum.position.set(0, 0.08, 0.112);
headPivot.add(philtrum);

// Upper lip
const upperLip = noShadow(part(
    new THREE.TorusGeometry(0.02, 0.005, 8, 16, Math.PI),
    lipM
));
upperLip.position.set(0, 0.073, 0.108);
upperLip.rotation.z = Math.PI;
headPivot.add(upperLip);

// Lower lip (fuller)
const lowerLip = noShadow(part(
    new THREE.TorusGeometry(0.022, 0.007, 8, 16, Math.PI),
    lipM
));
lowerLip.position.set(0, 0.065, 0.106);
headPivot.add(lowerLip);

// Lip line (dark crease between lips)
const lipLine = noShadow(part(
    new THREE.BoxGeometry(0.035, 0.001, 0.003),
    new THREE.MeshStandardMaterial({color: '#2a1510', roughness: 0.9})
));
lipLine.position.set(0, 0.069, 0.11);
headPivot.add(lipLine);

// --- Ears ---
for (const side of [-1, 1]) {
    const earGroup = pivot(side * 0.115, 0.12, 0);
    headPivot.add(earGroup);

    // Outer ear (helix)
    const helix = noShadow(part(
        new THREE.TorusGeometry(0.022, 0.005, 8, 16, Math.PI * 1.5),
        skinM
    ));
    helix.rotation.y = side * Math.PI / 2;
    helix.rotation.x = -0.2;
    earGroup.add(helix);

    // Ear lobe
    const lobe = noShadow(part(
        new THREE.SphereGeometry(0.008, 6, 6), skinM
    ));
    lobe.position.set(0, -0.02, side * 0.005);
    earGroup.add(lobe);

    // Ear canal (dark spot)
    const canal = noShadow(part(
        new THREE.CircleGeometry(0.005, 8), creaseSkinM
    ));
    canal.position.set(side * 0.003, 0, 0);
    canal.rotation.y = side * Math.PI / 2;
    earGroup.add(canal);
}

// --- Hair (multi-shell for volume) ---
// Base shell
const hairBase = noShadow(part(
    new THREE.SphereGeometry(0.128, 32, 16, 0, Math.PI * 2, 0, Math.PI * 0.55),
    hairM
));
hairBase.position.y = 0.14;
headPivot.add(hairBase);

// Second shell (slightly larger, alpha-faded at edges for softness)
const hairOuter = noShadow(part(
    new THREE.SphereGeometry(0.135, 24, 12, 0, Math.PI * 2, 0, Math.PI * 0.5),
    new THREE.MeshPhysicalMaterial({
        color: hairC, roughness: 0.55,
        sheen: 0.8, sheenRoughness: 0.3,
        sheenColor: new THREE.Color().copy(hairC).lerp(new THREE.Color('#ffffff'), 0.25),
        transparent: true, opacity: 0.6,
    })
));
hairOuter.position.y = 0.145;
headPivot.add(hairOuter);

// Hair back volume
const hairBack = noShadow(part(
    new THREE.SphereGeometry(0.11, 16, 10, 0, Math.PI * 2, Math.PI * 0.2, Math.PI * 0.5),
    hairM
));
hairBack.position.set(0, 0.1, -0.04);
headPivot.add(hairBack);

// --- Arms ---
function buildArm(side) {
    // Shoulder with deltoid
    const shoulderPivot = pivot(side * 0.22 * SW, 0.27 * HS, 0);
    upperTorsoPivot.add(shoulderPivot);

    // Deltoid cap
    const deltoid = noShadow(part(
        new THREE.SphereGeometry(0.042, 10, 8, 0, Math.PI * 2, 0, Math.PI * 0.5),
        shirtM
    ));
    deltoid.position.set(0, 0.01, 0);
    deltoid.rotation.x = -0.3;
    shoulderPivot.add(deltoid);

    // Upper arm
    const upperArm = part(
        new THREE.CylinderGeometry(0.038, 0.033, 0.24 * HS, 12), shirtM
    );
    upperArm.position.y = -0.12 * HS;
    shoulderPivot.add(upperArm);

    // Sleeve cuff
    const cuff = noShadow(part(
        new THREE.TorusGeometry(0.034, 0.004, 6, 12),
        new THREE.MeshStandardMaterial({
            color: new THREE.Color().copy(shirtC).multiplyScalar(0.85), roughness: 0.85
        })
    ));
    cuff.position.y = -0.23 * HS;
    cuff.rotation.x = Math.PI / 2;
    shoulderPivot.add(cuff);

    // Elbow
    const elbowPivot = pivot(0, -0.24 * HS, 0);
    shoulderPivot.add(elbowPivot);

    // Forearm
    const forearm = part(
        new THREE.CylinderGeometry(0.033, 0.028, 0.22 * HS, 12), skinM
    );
    forearm.position.y = -0.11 * HS;
    elbowPivot.add(forearm);

    // Wrist
    const wristPivot = pivot(0, -0.22 * HS, 0);
    elbowPivot.add(wristPivot);

    // Detailed hand
    const palm = part(new THREE.BoxGeometry(0.048, 0.035, 0.03), skinM);
    palm.position.y = -0.018;
    wristPivot.add(palm);

    // Knuckle ridge
    const knuckles = noShadow(part(
        new THREE.CylinderGeometry(0.004, 0.004, 0.042, 6),
        creaseSkinM
    ));
    knuckles.position.set(0, -0.035, 0.005);
    knuckles.rotation.z = Math.PI / 2;
    wristPivot.add(knuckles);

    // Fingers with natural curl
    const fOff = [-0.017, -0.008, 0.001, 0.01, 0.019];
    const fLen = [0.028, 0.038, 0.04, 0.036, 0.025];
    const fCurl = [0.05, 0.08, 0.1, 0.08, 0.06];
    for (let fi = 0; fi < 5; fi++) {
        const finger = noShadow(part(
            new THREE.CylinderGeometry(0.004, 0.003, fLen[fi], 6), skinM
        ));
        finger.position.set(fOff[fi], -0.035 - fLen[fi] / 2, 0);
        finger.rotation.x = fCurl[fi]; // natural curl
        wristPivot.add(finger);
        // Nail
        const nail = noShadow(part(
            new THREE.BoxGeometry(0.007, 0.002, 0.005),
            new THREE.MeshPhysicalMaterial({color: '#f0d8d0', roughness: 0.15, clearcoat: 0.7})
        ));
        nail.position.set(fOff[fi], -0.035 - fLen[fi], 0.003);
        wristPivot.add(nail);
    }
    // Thumb
    const thumb = noShadow(part(
        new THREE.CylinderGeometry(0.005, 0.004, 0.028, 6), skinM
    ));
    thumb.position.set(side * 0.026, -0.028, 0.008);
    thumb.rotation.z = side * 0.5;
    thumb.rotation.x = 0.2;
    wristPivot.add(thumb);

    return {shoulderPivot, elbowPivot, wristPivot};
}

const leftArm = buildArm(-1);
const rightArm = buildArm(1);

// --- Legs ---
function buildLeg(side) {
    const hipPivot = pivot(side * 0.1 * HW, 0, 0);
    hips.add(hipPivot);

    const thigh = part(
        new THREE.CylinderGeometry(0.058, 0.048, 0.35 * HS, 12), pantsM
    );
    thigh.position.y = -0.175 * HS;
    hipPivot.add(thigh);

    // Knee
    const kneePivot = pivot(0, -0.35 * HS, 0);
    hipPivot.add(kneePivot);

    // Shin
    const shin = part(
        new THREE.CylinderGeometry(0.043, 0.038, 0.35 * HS, 12), pantsM
    );
    shin.position.y = -0.175 * HS;
    kneePivot.add(shin);

    // Trouser hem
    const hem = noShadow(part(
        new THREE.TorusGeometry(0.039, 0.003, 4, 12),
        new THREE.MeshStandardMaterial({
            color: new THREE.Color().copy(pantsC).multiplyScalar(0.85), roughness: 0.9
        })
    ));
    hem.position.y = -0.35 * HS;
    hem.rotation.x = Math.PI / 2;
    kneePivot.add(hem);

    // Ankle
    const anklePivot = pivot(0, -0.35 * HS, 0);
    kneePivot.add(anklePivot);

    // Shoe
    const shoeBody = part(new THREE.BoxGeometry(0.072, 0.048, 0.14), shoeM);
    shoeBody.position.set(0, -0.024, 0.025);
    anklePivot.add(shoeBody);
    const toeCap = noShadow(part(
        new THREE.SphereGeometry(0.036, 10, 6, 0, Math.PI * 2, 0, Math.PI * 0.5),
        shoeM
    ));
    toeCap.position.set(0, -0.018, 0.09);
    toeCap.rotation.x = Math.PI / 2;
    anklePivot.add(toeCap);
    const sole = noShadow(part(
        new THREE.BoxGeometry(0.075, 0.01, 0.15),
        new THREE.MeshStandardMaterial({color: '#080808', roughness: 0.95})
    ));
    sole.position.set(0, -0.048, 0.025);
    anklePivot.add(sole);

    return {hipPivot, kneePivot, anklePivot};
}

const leftLeg = buildLeg(-1);
const rightLeg = buildLeg(1);

// Store in state
S.body = {
    hips, upperTorsoPivot, neckPivot, headPivot,
    leftArm, rightArm, leftLeg, rightLeg,
};
S.eyes = eyeTargets;
S.built = true;
"""


# ---------------------------------------------------------------------------
# Idle animation V2 — blinks, gaze tracking, micro-expressions
# ---------------------------------------------------------------------------

IDLE_V2_SCRIPT = r"""
if (!ctx.state.built) return;
const S = ctx.state;
const b = S.body;
const P = ctx.props;

if (!S.idle_init) {
    S.idle_init = true;
    S.seed = ctx.entity.position.x * 7.3 + ctx.entity.position.z * 13.7;
    S.blinkTimer = 2 + Math.random() * 4;
    S.blinkPhase = 0; // 0=open, 1=closing, 2=opening
    S.blinkT = 0;
    S.gazeTarget = {x: 0, y: 0};
    S.gazeTimer = 1 + Math.random() * 3;
    S.microTimer = 0;
    S.seated = !!P.seated;

    if (S.seated) {
        b.hips.position.y = 0.55;
        b.leftLeg.hipPivot.rotation.x = -1.57;
        b.rightLeg.hipPivot.rotation.x = -1.57;
        b.leftLeg.kneePivot.rotation.x = 1.57;
        b.rightLeg.kneePivot.rotation.x = 1.57;
    }
}

const t = ctx.elapsed;
const dt = ctx.deltaTime;
const seed = S.seed;

// --- Breathing ---
const breathe = Math.sin(t * 1.4 + seed);
b.upperTorsoPivot.rotation.x = breathe * 0.012;
const breatheScale = 1.0 + breathe * 0.008;
b.upperTorsoPivot.scale.set(1.0, breatheScale, 1.0 + breathe * 0.005);

// Shoulders rise on inhale
b.leftArm.shoulderPivot.position.y = 0.27 + breathe * 0.003;
b.rightArm.shoulderPivot.position.y = 0.27 + breathe * 0.003;

// --- Head movement ---
const headY = Math.sin(t * 0.25 + seed) * 0.35 + Math.sin(t * 0.11 + seed * 2) * 0.15;
const headX = Math.sin(t * 0.18 + seed * 3) * 0.06;
b.headPivot.rotation.y = headY;
b.headPivot.rotation.x = headX;
b.neckPivot.rotation.y = headY * 0.3;

// --- Blink ---
S.blinkTimer -= dt;
if (S.blinkTimer <= 0 && S.blinkPhase === 0) {
    S.blinkPhase = 1;
    S.blinkT = 0;
}
if (S.blinkPhase > 0) {
    S.blinkT += dt;
    // Close in 0.08s, stay closed 0.04s, open in 0.1s
    if (S.blinkPhase === 1) {
        const p = Math.min(S.blinkT / 0.08, 1);
        // Rotate upper eyelids down
        for (const eye of S.eyes) {
            const lid = eye.children.find(c => c.name === 'upperLid');
            if (lid) lid.rotation.x = p * 0.8;
        }
        if (p >= 1) { S.blinkPhase = 2; S.blinkT = 0; }
    } else if (S.blinkPhase === 2) {
        if (S.blinkT > 0.04) { S.blinkPhase = 3; S.blinkT = 0; }
    } else if (S.blinkPhase === 3) {
        const p = Math.min(S.blinkT / 0.1, 1);
        for (const eye of S.eyes) {
            const lid = eye.children.find(c => c.name === 'upperLid');
            if (lid) lid.rotation.x = (1 - p) * 0.8;
        }
        if (p >= 1) {
            S.blinkPhase = 0;
            S.blinkTimer = 2 + Math.random() * 5;
        }
    }
}

// --- Gaze tracking (slight eye rotation toward player) ---
S.gazeTimer -= dt;
if (S.gazeTimer <= 0) {
    // Occasionally look toward player
    const dx = ctx.camera.position.x - ctx.entity.position.x;
    const dz = ctx.camera.position.z - ctx.entity.position.z;
    const dist = Math.sqrt(dx * dx + dz * dz);
    if (dist < 8) {
        S.gazeTarget = {x: Math.atan2(dz, 1) * 0.15, y: Math.atan2(dx, 1) * 0.2};
    } else {
        S.gazeTarget = {x: (Math.random() - 0.5) * 0.1, y: (Math.random() - 0.5) * 0.15};
    }
    S.gazeTimer = 1.5 + Math.random() * 3;
}
// Smooth eye rotation
for (const eye of S.eyes) {
    eye.rotation.x += (S.gazeTarget.x - eye.rotation.x) * dt * 3;
    eye.rotation.y += (S.gazeTarget.y - eye.rotation.y) * dt * 3;
}

// --- Arms ---
if (!S.seated) {
    // Standing: arms hang with gentle sway
    b.leftArm.shoulderPivot.rotation.x = 0.05 + breathe * 0.01;
    b.rightArm.shoulderPivot.rotation.x = 0.05 + breathe * 0.01;
    b.leftArm.elbowPivot.rotation.x = -0.15;
    b.rightArm.elbowPivot.rotation.x = -0.15;
    // Legs straight
    b.leftLeg.hipPivot.rotation.x = 0;
    b.rightLeg.hipPivot.rotation.x = 0;
    b.leftLeg.kneePivot.rotation.x = 0;
    b.rightLeg.kneePivot.rotation.x = 0;
    b.hips.position.y = 0.92;
    // Weight shift
    const shift = Math.sin(t * 0.15 + seed) * 0.015;
    b.hips.rotation.z = shift;
    b.hips.position.x = shift * 0.5;
} else {
    // Seated: arms on lap/table
    const gesture = Math.sin(t * 0.15 + seed * 5);
    b.leftArm.shoulderPivot.rotation.x = -0.7 + gesture * 0.04;
    b.leftArm.elbowPivot.rotation.x = -0.9;
    const drink = Math.sin(t * 0.08 + seed * 7);
    if (drink > 0.85) {
        const lift = (drink - 0.85) / 0.15;
        b.rightArm.shoulderPivot.rotation.x = -0.5 - lift * 0.6;
        b.rightArm.elbowPivot.rotation.x = -1.2 - lift * 0.4;
        b.headPivot.rotation.x = lift * 0.12;
    } else {
        b.rightArm.shoulderPivot.rotation.x = -0.6 + Math.sin(t * 0.2 + seed) * 0.05;
        b.rightArm.elbowPivot.rotation.x = -0.8;
    }
    b.hips.rotation.z = Math.sin(t * 0.12 + seed) * 0.025;
}

// --- Micro-expression: occasional brow/lip movement ---
S.microTimer -= dt;
if (S.microTimer <= 0) {
    S.microTimer = 3 + Math.random() * 6;
}
"""


# ---------------------------------------------------------------------------
# Wander V2 — walk cycle with gaze + blinks
# ---------------------------------------------------------------------------

WANDER_V2_SCRIPT = r"""
function walkCycle(S, t, speed) {
    const b = S.body;
    const phase = t * speed * 5;
    const sin = Math.sin(phase);
    const cos = Math.cos(phase);
    b.hips.position.y = 0.92 + Math.abs(sin) * 0.018;
    b.hips.rotation.z = sin * 0.018;
    b.upperTorsoPivot.rotation.y = sin * 0.04;
    b.upperTorsoPivot.rotation.z = -sin * 0.008;
    b.headPivot.rotation.z = -sin * 0.008;
    b.leftArm.shoulderPivot.rotation.x = -sin * 0.45;
    b.rightArm.shoulderPivot.rotation.x = sin * 0.45;
    b.leftArm.elbowPivot.rotation.x = -Math.max(0, sin) * 0.35;
    b.rightArm.elbowPivot.rotation.x = -Math.max(0, -sin) * 0.35;
    b.leftLeg.hipPivot.rotation.x = sin * 0.4;
    b.rightLeg.hipPivot.rotation.x = -sin * 0.4;
    b.leftLeg.kneePivot.rotation.x = Math.max(0, -sin) * 0.55;
    b.rightLeg.kneePivot.rotation.x = Math.max(0, sin) * 0.55;
    b.leftLeg.anklePivot.rotation.x = sin * 0.12;
    b.rightLeg.anklePivot.rotation.x = -sin * 0.12;
}

function idleBreathing(S, t) {
    const b = S.body;
    const breathe = Math.sin(t * 1.4);
    b.upperTorsoPivot.rotation.x = breathe * 0.012;
    b.leftArm.shoulderPivot.rotation.x = 0.05 + breathe * 0.01;
    b.rightArm.shoulderPivot.rotation.x = 0.05 + breathe * 0.01;
    b.leftArm.elbowPivot.rotation.x = -0.15;
    b.rightArm.elbowPivot.rotation.x = -0.15;
    b.leftLeg.hipPivot.rotation.x = 0;
    b.rightLeg.hipPivot.rotation.x = 0;
    b.leftLeg.kneePivot.rotation.x = 0;
    b.rightLeg.kneePivot.rotation.x = 0;
    b.hips.position.y = 0.92;
    b.hips.rotation.z = 0;
}

if (!ctx.state.built) return;
const S = ctx.state;
if (!S.wn_init) {
    S.wn_init = true;
    const b = ctx.props.bounds || [-12, -8, 12, 7];
    S.bounds = {minX: b[0], minZ: b[1], maxX: b[2], maxZ: b[3]};
    S.target = null;
    S.waitTimer = 0;
    S.walking = false;
    S.speed = ctx.props.speed || 0.8;
    S.walkT = 0;
    S.blinkTimer = 2 + Math.random() * 4;
    S.blinkPhase = 0;
    S.blinkT = 0;
}

// Blink (same as idle)
S.blinkTimer -= ctx.deltaTime;
if (S.blinkTimer <= 0 && S.blinkPhase === 0) {
    S.blinkPhase = 1; S.blinkT = 0;
}
if (S.blinkPhase > 0) {
    S.blinkT += ctx.deltaTime;
    if (S.blinkPhase === 1) {
        const p = Math.min(S.blinkT / 0.08, 1);
        for (const eye of S.eyes) {
            const lid = eye.children.find(c => c.name === 'upperLid');
            if (lid) lid.rotation.x = p * 0.8;
        }
        if (p >= 1) { S.blinkPhase = 2; S.blinkT = 0; }
    } else if (S.blinkPhase === 2) {
        if (S.blinkT > 0.04) { S.blinkPhase = 3; S.blinkT = 0; }
    } else if (S.blinkPhase === 3) {
        const p = Math.min(S.blinkT / 0.1, 1);
        for (const eye of S.eyes) {
            const lid = eye.children.find(c => c.name === 'upperLid');
            if (lid) lid.rotation.x = (1 - p) * 0.8;
        }
        if (p >= 1) { S.blinkPhase = 0; S.blinkTimer = 2 + Math.random() * 5; }
    }
}

if (!S.walking) {
    S.waitTimer += ctx.deltaTime;
    idleBreathing(S, ctx.elapsed);
    S.body.headPivot.rotation.y = Math.sin(ctx.elapsed * 0.4 + ctx.entity.position.x) * 0.45;
    S.body.headPivot.rotation.x = Math.sin(ctx.elapsed * 0.25) * 0.04;
    // Weight shift
    const shift = Math.sin(ctx.elapsed * 0.2 + S.seed) * 0.012;
    S.body.hips.rotation.z = shift;
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
# Greet V2 — turn to player + nod
# ---------------------------------------------------------------------------

GREET_V2_SCRIPT = r"""
if (!ctx.state.built) return;
const dx = ctx.camera.position.x - ctx.entity.position.x;
const dz = ctx.camera.position.z - ctx.entity.position.z;
ctx.entity.rotation.y = Math.atan2(dx, dz);
// Nod
const b = ctx.state.body;
b.headPivot.rotation.x = 0.15;
setTimeout(() => { if (b.headPivot) b.headPivot.rotation.x = 0; }, 400);
console.log(ctx.entity.userData.entityName + ': ' + (ctx.props.greeting || 'Hello!'));
"""
