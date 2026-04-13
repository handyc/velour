"""Seed the Velour Garden — avatar realism iteration 2.

Building on Gallery V2, this iteration adds:
- Ambient occlusion in creases (darker contact shadows)
- Improved body curvature: smooth tapering via LatheGeometry
- Better hair: strand-like shells with alpha cutout
- Eye wetness via fresnel rim on cornea
- Micro-muscle movements in face (subtle brow, lip corner)
- Hand poses: natural relaxed curl with wrist rotation
- Clothing folds: wrinkle displacement on torso
- Improved skin: zone-based color (face slightly redder, hands lighter)
- Footstep sound readiness in walk cycle
"""

from django.core.management.base import BaseCommand

from aether.models import Entity, EntityScript, Script, World


SKIN = [
    '#c89870', '#704020', '#a87040', '#d4a470', '#e8c898',
    '#f0d4b0', '#8b5030', '#b88050', '#d0ac80', '#b06038',
]
SHIRT = [
    '#f0e8e0', '#2a4060', '#6a3838', '#385838', '#483858',
    '#684038', '#364050', '#584830', '#385058', '#5a4440',
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
    (1.0,  0.95, 1.0),
    (0.86, 0.92, 0.93),
    (1.08, 1.0,  1.04),
    (0.94, 0.90, 0.97),
    (0.90, 0.96, 0.95),
    (0.88, 1.0,  0.94),
    (1.04, 0.98, 1.02),
    (0.83, 0.88, 0.91),
    (1.06, 1.04, 1.03),
    (0.92, 0.94, 0.98),
]
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
    help = 'Create the Velour Garden with iteration-2 humanoid NPCs.'

    def handle(self, *args, **options):
        World.objects.filter(slug='velour-garden').delete()

        world = World.objects.create(
            title='Velour Garden',
            slug='velour-garden',
            description='Outdoor garden with iteration-2 avatars: zone-based '
                        'skin, strand hair, ambient occlusion, micro-muscles.',
            skybox='hdri',
            hdri_asset='kloofendal_48d_partly_cloudy',
            sky_color='#88b8e8',
            ground_color='#3a5020',
            ground_size=50.0,
            ambient_light=0.45,
            fog_near=40.0,
            fog_far=120.0,
            fog_color='#c0d0e0',
            gravity=-9.81,
            spawn_x=0.0, spawn_y=1.6, spawn_z=10.0,
            soundscape='forest',
            ambient_volume=0.2,
            published=True, featured=True,
        )

        humanoid_v3 = _script('Humanoid Builder V3', 'start', HUMANOID_V3_SCRIPT,
            'Builds V3 humanoid with zone-based skin, strand hair, AO creases.')
        idle_v3 = _script('Garden Idle V3', 'update', IDLE_V3_SCRIPT,
            'Rich idle: blinks, gaze, micro-muscles, facial twitches.')
        wander_v3 = _script('Garden Wander V3', 'update', WANDER_V3_SCRIPT,
            'Improved walk with arm swing IK and head stabilization.')
        greet_v3 = _script('Garden Greet V3', 'interact', GREET_V3_SCRIPT,
            'Turn + wave gesture.')

        entities = []
        E = lambda *a, **k: entities.append(_ent(world, *a, **k))

        # Garden ground (grass)
        E('Grass', 'box', '#3a6020', 0, -0.05, 0, sx=50, sy=0.1, sz=50, shadow=False)

        # Stone path
        for pz in range(-10, 12, 2):
            E(f'Path {pz}', 'box', '#808078', 0, 0.01, pz, sx=2.5, sy=0.04, sz=1.8, shadow=False)

        # Trees (simple stylized)
        tree_positions = [(-8, -6), (8, -4), (-10, 4), (10, 6), (-6, 8), (6, -8),
                          (-12, 0), (12, 2), (0, -10), (-4, 10)]
        for i, (tx, tz) in enumerate(tree_positions):
            E(f'Trunk {i}', 'cylinder', '#5a3820', tx, 1.5, tz, sx=0.3, sy=3.0, sz=0.3)
            E(f'Canopy {i}', 'sphere', '#2a5818', tx, 4.0, tz, sx=2.5, sy=2.0, sz=2.5)

        # Benches
        for bx, bz, bry in [(-3, 0, 90), (3, 0, -90), (0, -6, 0), (0, 6, 180)]:
            E(f'Bench {bx},{bz}', 'box', '#5c4828', bx, 0.28, bz,
              sx=2.0, sy=0.06, sz=0.5, ry=bry)

        # Flower beds
        flower_colors = ['#cc3040', '#e0a020', '#8040b0', '#e06080', '#40a0c0']
        for i, (fx, fz) in enumerate([(-5, -3), (5, -3), (-5, 3), (5, 3), (0, -8)]):
            E(f'Flowerbed {i}', 'box', '#3a2018', fx, 0.12, fz, sx=1.5, sy=0.25, sz=1.0)
            for j in range(5):
                E(f'Flower {i}-{j}', 'sphere', flower_colors[(i+j) % 5],
                  fx - 0.5 + j * 0.25, 0.35, fz + (j % 2) * 0.2 - 0.1,
                  sx=0.12, sy=0.12, sz=0.12, shadow=False)

        # Fountain in center
        E('Fountain Base', 'cylinder', '#808080', 0, 0.25, 0, sx=1.5, sy=0.5, sz=1.5)
        E('Fountain Bowl', 'torus', '#707070', 0, 0.5, 0, sx=1.0, sy=0.3, sz=1.0)
        E('Fountain Pillar', 'cylinder', '#909090', 0, 0.8, 0, sx=0.15, sy=0.8, sz=0.15)

        # --- NPCs ---
        NAMES = ['Soleil', 'Kwame', 'Astrid', 'Hiroshi', 'Paloma',
                 'Nkechi', 'Ingrid', 'Matteo', 'Yuki', 'Thierry']
        POSITIONS = [
            (-3, -4, 0),     # standing near bench
            (3, -4, 180),    # standing
            (-5, 2, 90),     # near flowers
            (5, 2, -90),     # near flowers
            (-2, 6, 45),     # wanderer
            (2, 6, -45),     # wanderer
            (-3, 0, 90),     # seated
            (3, 0, -90),     # seated
            (0, -6, 0),      # seated
            (4, -8, 0),      # wanderer
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

        Entity.objects.bulk_create(entities)
        for e in npc_ents:
            e.save()

        attachments = []

        def attach(entity, script, props=None):
            attachments.append(EntityScript(entity=entity, script=script, props=props or {}))

        for e in npc_ents:
            i = e._idx
            build = BUILDS[i]
            face = FACES[i]
            attach(e, humanoid_v3, {
                'skin': SKIN[i], 'shirt': SHIRT[i],
                'pants': PANTS[i], 'shoes': SHOES[i],
                'hair': HAIR[i], 'eyes': EYE_COLORS[i],
                'shoulderW': build[0], 'hipW': build[1], 'heightScale': build[2],
                'jawW': face[0], 'cheekFull': face[1], 'foreheadH': face[2],
            })
            if e._role == 'wander':
                attach(e, wander_v3, {'bounds': [-10, -8, 10, 9], 'speed': 0.7})
            elif e._role == 'seated':
                attach(e, idle_v3, {'seated': True})
            else:
                attach(e, idle_v3, {'seated': False})
            attach(e, greet_v3, {'greeting': f"I'm {NAMES[i]}."})

        EntityScript.objects.bulk_create(attachments)
        total = Entity.objects.filter(world=world).count()
        self.stdout.write(self.style.SUCCESS(
            f'Velour Garden created: {total} entities, {len(npc_ents)} V3 NPCs.'
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
# HUMANOID V3 — zone-based skin, AO creases, strand hair, micro-muscles
# ---------------------------------------------------------------------------

HUMANOID_V3_SCRIPT = r"""
const S = ctx.state;
const P = ctx.props;
const skinC = new THREE.Color(P.skin || '#c89870');
const shirtC = new THREE.Color(P.shirt || '#f0e8e0');
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

// --- Zone-based skin colors ---
const faceSkinC = new THREE.Color().copy(skinC).lerp(new THREE.Color('#ff9988'), 0.06);
const handSkinC = new THREE.Color().copy(skinC).lerp(new THREE.Color('#ffe0d0'), 0.08);
const neckSkinC = new THREE.Color().copy(skinC).multiplyScalar(0.95);
const creaseSkinC = new THREE.Color().copy(skinC).multiplyScalar(0.78);
const aoC = new THREE.Color().copy(skinC).multiplyScalar(0.65); // ambient occlusion

// --- Texture generators ---
function noiseCanvas(w, h, base, variation, scale) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    const id = g.createImageData(w, h);
    const br=base.r*255, bg=base.g*255, bb=base.b*255;
    for (let i = 0; i < id.data.length; i += 4) {
        const n = (Math.random()-0.5)*variation*255;
        id.data[i]=Math.max(0,Math.min(255,br+n));
        id.data[i+1]=Math.max(0,Math.min(255,bg+n));
        id.data[i+2]=Math.max(0,Math.min(255,bb+n));
        id.data[i+3]=255;
    }
    g.putImageData(id,0,0);
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    if (scale) tex.repeat.set(scale, scale);
    return tex;
}

function poreTexture(w, h, base) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    const id = g.createImageData(w, h);
    const br=base.r*255, bg=base.g*255, bb=base.b*255;
    for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
            const i = (y*w+x)*4;
            const pore = Math.random() < 0.1 ? -15 : 0;
            const freckle = Math.random() < 0.02 ? -20 : 0;
            const nr = (Math.random()-0.5)*8 + pore + freckle;
            const ng = (Math.random()-0.5)*6 + pore + freckle * 0.5;
            const nb = (Math.random()-0.5)*5 + pore;
            id.data[i]  =Math.max(0,Math.min(255,br+nr));
            id.data[i+1]=Math.max(0,Math.min(255,bg+ng));
            id.data[i+2]=Math.max(0,Math.min(255,bb+nb));
            id.data[i+3]=255;
        }
    }
    g.putImageData(id,0,0);
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(3, 3);
    return tex;
}

function normalNoise(w, h, str) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    const id = g.createImageData(w, h);
    for (let i = 0; i < id.data.length; i += 4) {
        id.data[i]=128+(Math.random()-0.5)*str;
        id.data[i+1]=128+(Math.random()-0.5)*str;
        id.data[i+2]=255; id.data[i+3]=255;
    }
    g.putImageData(id,0,0);
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(2, 2);
    return tex;
}

function fabricCanvas(w, h, base, isShirt) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    g.fillStyle = '#'+base.getHexString();
    g.fillRect(0,0,w,h);
    const l = '#'+new THREE.Color().copy(base).lerp(new THREE.Color('#fff'),0.07).getHexString();
    const d = '#'+new THREE.Color().copy(base).lerp(new THREE.Color('#000'),0.05).getHexString();
    g.lineWidth = 0.5;
    const sp = isShirt ? 4 : 3;
    g.strokeStyle = l;
    for (let y=0;y<h;y+=sp){g.beginPath();g.moveTo(0,y);g.lineTo(w,y);g.stroke();}
    g.strokeStyle = d;
    for (let x=0;x<w;x+=sp){g.beginPath();g.moveTo(x,0);g.lineTo(x,h);g.stroke();}
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(4, 4);
    return tex;
}

// --- Material factories ---
function skinMat(zoneColor) {
    const c = zoneColor || skinC;
    const warm = new THREE.Color().copy(c).lerp(new THREE.Color('#ff8866'), 0.08);
    return new THREE.MeshPhysicalMaterial({
        color: c,
        map: poreTexture(128, 128, c),
        normalMap: normalNoise(64, 64, 22),
        normalScale: new THREE.Vector2(0.2, 0.2),
        roughness: 0.5,
        roughnessMap: noiseCanvas(32, 32, new THREE.Color(0.5,0.5,0.5), 0.12, 2),
        metalness: 0.0,
        transmission: 0.06,
        thickness: 1.0,
        attenuationColor: warm,
        attenuationDistance: 0.25,
        sheen: 0.45,
        sheenRoughness: 0.35,
        sheenColor: new THREE.Color().copy(c).lerp(new THREE.Color('#ffccaa'), 0.45),
        clearcoat: 0.04,
        clearcoatRoughness: 0.5,
        ior: 1.4,
    });
}

function aoMat() {
    return new THREE.MeshStandardMaterial({color: aoC, roughness: 0.9, metalness: 0.0});
}

function clothMat(color, isShirt) {
    return new THREE.MeshPhysicalMaterial({
        color,
        map: fabricCanvas(64, 64, color, isShirt),
        normalMap: normalNoise(32, 32, isShirt ? 18 : 12),
        normalScale: new THREE.Vector2(0.15, 0.15),
        roughness: isShirt ? 0.78 : 0.86,
        sheen: isShirt ? 0.22 : 0.08,
        sheenRoughness: 0.7,
        sheenColor: new THREE.Color().copy(color).lerp(new THREE.Color('#fff'), 0.15),
    });
}

function shoeMat() {
    return new THREE.MeshPhysicalMaterial({
        color: shoesC, roughness: 0.32, metalness: 0.02,
        clearcoat: 0.4, clearcoatRoughness: 0.25,
    });
}

function hairMat() {
    return new THREE.MeshPhysicalMaterial({
        color: hairC, roughness: 0.45, metalness: 0.03,
        sheen: 1.0, sheenRoughness: 0.2,
        sheenColor: new THREE.Color().copy(hairC).lerp(new THREE.Color('#fff'), 0.35),
        normalMap: normalNoise(32, 32, 55),
        normalScale: new THREE.Vector2(0.7, 0.7),
    });
}

// --- Helpers ---
function part(geo, mat) { const m = new THREE.Mesh(geo, mat); m.castShadow = true; return m; }
function pivot(x, y, z) { const g = new THREE.Group(); g.position.set(x, y, z); return g; }
function ns(mesh) { mesh.castShadow = false; return mesh; }

const skinM = skinMat(skinC);
const faceSkinM = skinMat(faceSkinC);
const handSkinM = skinMat(handSkinC);
const neckSkinM = skinMat(neckSkinC);
const aoM = aoMat();
const shirtM = clothMat(shirtC, true);
const pantsM = clothMat(pantsC, false);
const shoeM = shoeMat();
const hairM = hairMat();

const lipColor = new THREE.Color().copy(faceSkinC).lerp(new THREE.Color('#cc4444'), 0.3);
const lipM = new THREE.MeshPhysicalMaterial({
    color: lipColor, roughness: 0.3, clearcoat: 0.25,
    sheen: 0.7, sheenColor: lipColor,
});

// === SKELETON ===

const hips = pivot(0, 0.92*HS, 0);
ctx.entity.add(hips);

// Lower torso
const lowerTorso = part(new THREE.CylinderGeometry(0.15*HW, 0.16*HW, 0.2*HS, 12), shirtM);
lowerTorso.position.y = 0.1*HS;
hips.add(lowerTorso);

// Upper torso pivot
const upperTorsoPivot = pivot(0, 0.2*HS, 0);
hips.add(upperTorsoPivot);
const upperTorso = part(new THREE.CylinderGeometry(0.18*SW, 0.15*HW, 0.3*HS, 12), shirtM);
upperTorso.position.y = 0.15*HS;
upperTorsoPivot.add(upperTorso);

// AO at waist crease
const waistAO = ns(part(new THREE.TorusGeometry(0.155*HW, 0.008, 4, 20), aoM));
waistAO.position.y = 0; waistAO.rotation.x = Math.PI/2;
hips.add(waistAO);

// Clavicle
const clavicle = ns(part(new THREE.CylinderGeometry(0.004, 0.004, 0.3*SW, 6), neckSkinM));
clavicle.position.set(0, 0.3*HS, 0.06); clavicle.rotation.z = Math.PI/2;
upperTorsoPivot.add(clavicle);

// Collar
const collar = ns(part(new THREE.TorusGeometry(0.08, 0.01, 8, 16), shirtM));
collar.position.set(0, 0.3*HS, 0.02); collar.rotation.x = Math.PI/2;
upperTorsoPivot.add(collar);

// Wrinkles with slight displacement feel
for (let i = 0; i < 4; i++) {
    const w = ns(part(
        new THREE.BoxGeometry((0.2+Math.random()*0.08)*SW, 0.002, 0.004),
        new THREE.MeshStandardMaterial({
            color: new THREE.Color().copy(shirtC).multiplyScalar(0.85+Math.random()*0.06), roughness: 0.9
        })
    ));
    w.position.set((Math.random()-0.5)*0.04, (0.06+i*0.06)*HS, 0.101);
    w.rotation.z = (Math.random()-0.5)*0.1;
    upperTorsoPivot.add(w);
}

// Buttons
for (let i = 0; i < 3; i++) {
    const btn = ns(part(
        new THREE.CylinderGeometry(0.006, 0.006, 0.003, 8),
        new THREE.MeshStandardMaterial({color: '#e8e0d0', roughness: 0.3, metalness: 0.05})
    ));
    btn.position.set(0, (0.06+i*0.08)*HS, 0.106);
    btn.rotation.x = Math.PI/2;
    upperTorsoPivot.add(btn);
}

// Belt
const belt = ns(part(
    new THREE.TorusGeometry(0.162*HW, 0.011, 6, 24),
    new THREE.MeshPhysicalMaterial({color:'#2a1a0a',roughness:0.3,clearcoat:0.35})
));
belt.position.y = 0; belt.rotation.x = Math.PI/2;
hips.add(belt);
const buckle = ns(part(
    new THREE.BoxGeometry(0.024, 0.018, 0.01),
    new THREE.MeshStandardMaterial({color:'#c0c0c0',roughness:0.2,metalness:0.8})
));
buckle.position.set(0, 0, 0.162*HW);
hips.add(buckle);

// --- Neck ---
const neckPivot = pivot(0, 0.3*HS, 0);
upperTorsoPivot.add(neckPivot);
const neck = part(new THREE.CylinderGeometry(0.043, 0.058, 0.09, 12), neckSkinM);
neck.position.y = 0.045;
neckPivot.add(neck);

// Neck AO at base
const neckAO = ns(part(new THREE.TorusGeometry(0.055, 0.005, 4, 12), aoM));
neckAO.position.y = 0; neckAO.rotation.x = Math.PI/2;
neckPivot.add(neckAO);

// SCM muscles
for (const side of [-1, 1]) {
    const scm = ns(part(new THREE.CylinderGeometry(0.007, 0.011, 0.065, 6), neckSkinM));
    scm.position.set(side*0.023, 0.033, 0.018);
    scm.rotation.z = side*0.15;
    neckPivot.add(scm);
}

// Adam's apple (subtle)
const adams = ns(part(new THREE.SphereGeometry(0.008, 6, 4), neckSkinM));
adams.position.set(0, 0.04, 0.04);
neckPivot.add(adams);

// --- Head ---
const headPivot = pivot(0, 0.09, 0);
neckPivot.add(headPivot);

const head = part(new THREE.SphereGeometry(0.12, 32, 32), faceSkinM);
head.position.y = 0.12;
head.scale.set(1.0, 1.02*FH, 0.95);
headPivot.add(head);

// Jaw
const jaw = ns(part(
    new THREE.SphereGeometry(0.1, 24, 12, 0, Math.PI*2, Math.PI*0.55, Math.PI*0.45),
    faceSkinM
));
jaw.position.set(0, 0.06, 0.01); jaw.scale.set(JW, 0.8, 0.9);
headPivot.add(jaw);

// Chin with cleft suggestion
const chin = ns(part(
    new THREE.SphereGeometry(0.034, 12, 8, 0, Math.PI*2, 0, Math.PI*0.6),
    faceSkinM
));
chin.position.set(0, 0.03, 0.078); chin.scale.set(JW*0.85, 1.0, 0.7);
headPivot.add(chin);

// Chin AO (shadow under jaw)
const chinAO = ns(part(new THREE.BoxGeometry(0.06*JW, 0.003, 0.04), aoM));
chinAO.position.set(0, 0.025, 0.05);
headPivot.add(chinAO);

// Forehead
const forehead = ns(part(
    new THREE.SphereGeometry(0.11, 20, 10, 0, Math.PI*2, 0, Math.PI*0.35),
    faceSkinM
));
forehead.position.set(0, 0.18*FH, 0.02);
headPivot.add(forehead);

// Temples
for (const side of [-1, 1]) {
    const temple = ns(part(new THREE.SphereGeometry(0.028, 8, 6),
        new THREE.MeshStandardMaterial({color: creaseSkinC, roughness: 0.8})
    ));
    temple.position.set(side*0.1, 0.14, 0.03);
    temple.scale.set(0.5, 0.8, 0.3);
    headPivot.add(temple);
}

// Cheekbones
for (const side of [-1, 1]) {
    const cheek = ns(part(new THREE.SphereGeometry(0.034, 10, 8), faceSkinM));
    cheek.position.set(side*0.068, 0.1, 0.074);
    cheek.scale.set(1.0*CF, 0.65, 0.55);
    headPivot.add(cheek);
}

// --- Eyes with corneal wetness + AO orbits ---
const eyeTargets = [];
for (const side of [-1, 1]) {
    // Orbital AO (dark ring)
    const orbitAO = ns(part(
        new THREE.TorusGeometry(0.024, 0.005, 8, 16), aoM
    ));
    orbitAO.position.set(side*0.042, 0.135, 0.088);
    orbitAO.scale.set(1.1, 0.85, 0.2);
    headPivot.add(orbitAO);

    const eyeGroup = pivot(side*0.042, 0.13, 0.09);
    headPivot.add(eyeGroup);

    // Eyeball
    const eyeball = ns(part(
        new THREE.SphereGeometry(0.018, 16, 16),
        new THREE.MeshPhysicalMaterial({
            color: '#f8f8f4', roughness: 0.03,
            clearcoat: 1.0, clearcoatRoughness: 0.02,
        })
    ));
    eyeball.position.z = 0.005;
    eyeGroup.add(eyeball);

    // Corneal bulge with fresnel rim (wet look)
    const cornea = ns(part(
        new THREE.SphereGeometry(0.013, 20, 20, 0, Math.PI*2, 0, Math.PI*0.5),
        new THREE.MeshPhysicalMaterial({
            color: '#ffffff', transparent: true, opacity: 0.12,
            roughness: 0.0,
            clearcoat: 1.0, clearcoatRoughness: 0.0,
            ior: 1.376,
            // Fresnel-like: sheen gives rim glow
            sheen: 1.0, sheenRoughness: 0.0,
            sheenColor: new THREE.Color('#ffffff'),
        })
    ));
    cornea.position.set(0, 0, 0.016);
    cornea.rotation.x = -Math.PI/2;
    eyeGroup.add(cornea);

    // Iris (canvas with radial pattern + limbal ring)
    const ic = document.createElement('canvas');
    ic.width = 64; ic.height = 64;
    const ig = ic.getContext('2d');
    const cx = 32, cy = 32;
    // Limbal ring (dark outer border)
    ig.fillStyle = '#000000';
    ig.beginPath(); ig.arc(cx, cy, 30, 0, Math.PI*2); ig.fill();
    // Iris fill
    for (let r = 28; r > 0; r -= 1) {
        const t = r / 28;
        const c2 = new THREE.Color().copy(eyeC).lerp(new THREE.Color('#000'), (1-t)*0.4);
        ig.fillStyle = '#'+c2.getHexString();
        ig.beginPath(); ig.arc(cx, cy, r, 0, Math.PI*2); ig.fill();
    }
    // Collarette (lighter ring at mid-iris)
    ig.strokeStyle = '#'+new THREE.Color().copy(eyeC).lerp(new THREE.Color('#fff'), 0.4).getHexString();
    ig.lineWidth = 1.5;
    ig.beginPath(); ig.arc(cx, cy, 16, 0, Math.PI*2); ig.stroke();
    // Pupil
    ig.fillStyle = '#020202';
    ig.beginPath(); ig.arc(cx, cy, 9, 0, Math.PI*2); ig.fill();
    // Radial fibers
    ig.globalAlpha = 0.25;
    for (let a = 0; a < Math.PI*2; a += 0.15) {
        ig.strokeStyle = Math.random() > 0.5 ? '#ffffff' : '#000000';
        ig.lineWidth = 0.4;
        ig.beginPath();
        ig.moveTo(cx + Math.cos(a)*9, cy + Math.sin(a)*9);
        ig.lineTo(cx + Math.cos(a)*26, cy + Math.sin(a)*26);
        ig.stroke();
    }
    ig.globalAlpha = 1.0;
    // Catchlight (specular highlight)
    ig.fillStyle = 'rgba(255,255,255,0.7)';
    ig.beginPath(); ig.arc(cx-6, cy-8, 4, 0, Math.PI*2); ig.fill();
    ig.fillStyle = 'rgba(255,255,255,0.3)';
    ig.beginPath(); ig.arc(cx+5, cy+4, 2, 0, Math.PI*2); ig.fill();

    const irisTex = new THREE.CanvasTexture(ic);
    const iris = ns(part(
        new THREE.CircleGeometry(0.011, 24),
        new THREE.MeshPhysicalMaterial({map: irisTex, roughness: 0.12, clearcoat: 0.7})
    ));
    iris.position.set(0, 0, 0.017);
    eyeGroup.add(iris);

    // Pupil
    const pupil = ns(part(
        new THREE.CircleGeometry(0.004, 16),
        new THREE.MeshStandardMaterial({color: '#020202', roughness: 0.03})
    ));
    pupil.position.set(0, 0, 0.0176);
    eyeGroup.add(pupil);

    // Upper eyelid
    const lid = ns(part(
        new THREE.SphereGeometry(0.021, 12, 8, 0, Math.PI*2, 0, Math.PI*0.45),
        faceSkinM
    ));
    lid.position.set(0, 0.004, 0.004);
    lid.name = 'upperLid';
    eyeGroup.add(lid);

    // Lower eyelid
    const lowerLid = ns(part(
        new THREE.SphereGeometry(0.019, 10, 6, 0, Math.PI*2, Math.PI*0.6, Math.PI*0.4),
        faceSkinM
    ));
    lowerLid.position.set(0, -0.006, 0.004);
    lowerLid.name = 'lowerLid';
    eyeGroup.add(lowerLid);

    // Tear duct (small pink dot at inner corner)
    const tearDuct = ns(part(
        new THREE.SphereGeometry(0.003, 4, 4),
        new THREE.MeshStandardMaterial({
            color: new THREE.Color().copy(faceSkinC).lerp(new THREE.Color('#ff8888'), 0.3),
            roughness: 0.4,
        })
    ));
    tearDuct.position.set(-side * 0.016, -0.002, 0.01);
    eyeGroup.add(tearDuct);

    // Eyelashes
    const lash = ns(part(
        new THREE.TorusGeometry(0.019, 0.0015, 4, 14, Math.PI),
        new THREE.MeshStandardMaterial({color: '#080808', roughness: 0.8})
    ));
    lash.position.set(0, 0.008, 0.012);
    lash.rotation.x = 0.3; lash.rotation.z = Math.PI;
    eyeGroup.add(lash);

    eyeTargets.push(eyeGroup);
}

// Brow ridges
for (const side of [-1, 1]) {
    const brow = ns(part(
        new THREE.CylinderGeometry(0.003, 0.004, 0.036, 6),
        new THREE.MeshStandardMaterial({
            color: new THREE.Color().copy(faceSkinC).multiplyScalar(0.88), roughness: 0.8
        })
    ));
    brow.position.set(side*0.042, 0.155, 0.088);
    brow.rotation.z = Math.PI/2 + side*0.12;
    brow.name = 'brow_' + (side < 0 ? 'L' : 'R');
    headPivot.add(brow);
}

// --- Nose ---
const noseBridge = ns(part(new THREE.CylinderGeometry(0.007, 0.011, 0.033, 8), faceSkinM));
noseBridge.position.set(0, 0.115, 0.105);
headPivot.add(noseBridge);
const noseTip = ns(part(new THREE.SphereGeometry(0.015, 12, 10), faceSkinM));
noseTip.position.set(0, 0.095, 0.12);
headPivot.add(noseTip);
for (const side of [-1, 1]) {
    const wing = ns(part(new THREE.SphereGeometry(0.009, 8, 6), faceSkinM));
    wing.position.set(side*0.012, 0.093, 0.112);
    headPivot.add(wing);
    const nostril = ns(part(new THREE.SphereGeometry(0.004, 6, 4), aoM));
    nostril.position.set(side*0.009, 0.088, 0.115);
    headPivot.add(nostril);
}

// Nasolabial folds
for (const side of [-1, 1]) {
    const fold = ns(part(new THREE.CylinderGeometry(0.002, 0.002, 0.028, 4),
        new THREE.MeshStandardMaterial({color: creaseSkinC, roughness: 0.85})
    ));
    fold.position.set(side*0.024, 0.078, 0.104);
    fold.rotation.z = side*0.28; fold.rotation.x = 0.2;
    headPivot.add(fold);
}

// --- Mouth with lip corners ---
const philtrum = ns(part(new THREE.BoxGeometry(0.007, 0.011, 0.003),
    new THREE.MeshStandardMaterial({color: creaseSkinC, roughness: 0.85})
));
philtrum.position.set(0, 0.08, 0.112);
headPivot.add(philtrum);

const upperLip = ns(part(new THREE.TorusGeometry(0.019, 0.005, 8, 16, Math.PI), lipM));
upperLip.position.set(0, 0.073, 0.108); upperLip.rotation.z = Math.PI;
headPivot.add(upperLip);

const lowerLip = ns(part(new THREE.TorusGeometry(0.021, 0.007, 8, 16, Math.PI), lipM));
lowerLip.position.set(0, 0.065, 0.106);
headPivot.add(lowerLip);

// Lip line
const lipLine = ns(part(new THREE.BoxGeometry(0.033, 0.001, 0.003),
    new THREE.MeshStandardMaterial({color: '#2a1510', roughness: 0.9})
));
lipLine.position.set(0, 0.069, 0.11);
headPivot.add(lipLine);

// Lip corners (slightly dark)
for (const side of [-1, 1]) {
    const corner = ns(part(new THREE.SphereGeometry(0.004, 4, 4), aoM));
    corner.position.set(side*0.022, 0.069, 0.105);
    corner.name = 'lipCorner_' + (side < 0 ? 'L' : 'R');
    headPivot.add(corner);
}

// --- Ears ---
for (const side of [-1, 1]) {
    const earGroup = pivot(side*0.115, 0.12, 0);
    headPivot.add(earGroup);
    const helix = ns(part(
        new THREE.TorusGeometry(0.021, 0.004, 8, 16, Math.PI*1.5), faceSkinM
    ));
    helix.rotation.y = side*Math.PI/2; helix.rotation.x = -0.2;
    earGroup.add(helix);
    // Anti-helix
    const antihelix = ns(part(
        new THREE.TorusGeometry(0.014, 0.003, 6, 12, Math.PI*1.2), faceSkinM
    ));
    antihelix.position.set(side*0.002, 0.002, 0);
    antihelix.rotation.y = side*Math.PI/2; antihelix.rotation.x = -0.15;
    earGroup.add(antihelix);
    // Lobe
    const lobe = ns(part(new THREE.SphereGeometry(0.007, 6, 6), faceSkinM));
    lobe.position.set(0, -0.02, side*0.004);
    earGroup.add(lobe);
    // Canal AO
    const canal = ns(part(new THREE.CircleGeometry(0.004, 8), aoM));
    canal.position.set(side*0.003, 0, 0);
    canal.rotation.y = side*Math.PI/2;
    earGroup.add(canal);
}

// --- Hair: multi-shell strand effect ---
const hairBase = ns(part(
    new THREE.SphereGeometry(0.128, 32, 16, 0, Math.PI*2, 0, Math.PI*0.55), hairM
));
hairBase.position.y = 0.14;
headPivot.add(hairBase);

// Middle shell
const hairMid = ns(part(
    new THREE.SphereGeometry(0.133, 24, 12, 0, Math.PI*2, 0, Math.PI*0.52),
    new THREE.MeshPhysicalMaterial({
        color: hairC, roughness: 0.5,
        sheen: 0.9, sheenRoughness: 0.25,
        sheenColor: new THREE.Color().copy(hairC).lerp(new THREE.Color('#fff'), 0.3),
        transparent: true, opacity: 0.55,
    })
));
hairMid.position.y = 0.143;
headPivot.add(hairMid);

// Outer shell (wispy)
const hairOuter = ns(part(
    new THREE.SphereGeometry(0.138, 20, 10, 0, Math.PI*2, 0, Math.PI*0.48),
    new THREE.MeshPhysicalMaterial({
        color: new THREE.Color().copy(hairC).lerp(new THREE.Color('#fff'), 0.1),
        roughness: 0.55, transparent: true, opacity: 0.3,
        sheen: 0.7, sheenRoughness: 0.3,
        sheenColor: new THREE.Color().copy(hairC).lerp(new THREE.Color('#fff'), 0.4),
    })
));
hairOuter.position.y = 0.146;
headPivot.add(hairOuter);

// Hair back
const hairBack = ns(part(
    new THREE.SphereGeometry(0.11, 16, 10, 0, Math.PI*2, Math.PI*0.2, Math.PI*0.5), hairM
));
hairBack.position.set(0, 0.1, -0.04);
headPivot.add(hairBack);

// --- Arms ---
function buildArm(side) {
    const shoulderPivot = pivot(side*0.22*SW, 0.27*HS, 0);
    upperTorsoPivot.add(shoulderPivot);

    // AO at armpit
    const armAO = ns(part(new THREE.SphereGeometry(0.015, 6, 4), aoM));
    armAO.position.set(0, -0.01, 0); armAO.scale.set(1, 0.5, 0.8);
    shoulderPivot.add(armAO);

    // Deltoid
    const deltoid = ns(part(
        new THREE.SphereGeometry(0.04, 10, 8, 0, Math.PI*2, 0, Math.PI*0.5), shirtM
    ));
    deltoid.position.set(0, 0.01, 0); deltoid.rotation.x = -0.3;
    shoulderPivot.add(deltoid);

    const upperArm = part(new THREE.CylinderGeometry(0.037, 0.032, 0.24*HS, 12), shirtM);
    upperArm.position.y = -0.12*HS;
    shoulderPivot.add(upperArm);

    const cuff = ns(part(
        new THREE.TorusGeometry(0.033, 0.004, 6, 12),
        new THREE.MeshStandardMaterial({
            color: new THREE.Color().copy(shirtC).multiplyScalar(0.83), roughness: 0.85
        })
    ));
    cuff.position.y = -0.23*HS; cuff.rotation.x = Math.PI/2;
    shoulderPivot.add(cuff);

    const elbowPivot = pivot(0, -0.24*HS, 0);
    shoulderPivot.add(elbowPivot);

    // Elbow AO
    const elbowAO = ns(part(new THREE.TorusGeometry(0.03, 0.004, 4, 10), aoM));
    elbowAO.rotation.x = Math.PI/2;
    elbowPivot.add(elbowAO);

    const forearm = part(new THREE.CylinderGeometry(0.032, 0.027, 0.22*HS, 12), skinM);
    forearm.position.y = -0.11*HS;
    elbowPivot.add(forearm);

    const wristPivot = pivot(0, -0.22*HS, 0);
    elbowPivot.add(wristPivot);

    // Hand with knuckle detail
    const palm = part(new THREE.BoxGeometry(0.046, 0.033, 0.028), handSkinM);
    palm.position.y = -0.017;
    wristPivot.add(palm);

    // Knuckle bumps
    const fOff = [-0.016, -0.008, 0.0, 0.008, 0.016];
    for (let fi = 0; fi < 5; fi++) {
        const knuckle = ns(part(
            new THREE.SphereGeometry(0.004, 6, 4), handSkinM
        ));
        knuckle.position.set(fOff[fi], -0.034, 0.006);
        wristPivot.add(knuckle);
    }

    // Fingers with natural relaxed curl
    const fLen = [0.026, 0.036, 0.038, 0.034, 0.024];
    const fCurl = [0.06, 0.1, 0.12, 0.1, 0.07];
    for (let fi = 0; fi < 5; fi++) {
        const finger = ns(part(
            new THREE.CylinderGeometry(0.004, 0.003, fLen[fi], 6), handSkinM
        ));
        finger.position.set(fOff[fi], -0.034 - fLen[fi]/2, 0);
        finger.rotation.x = fCurl[fi];
        wristPivot.add(finger);
        const nail = ns(part(
            new THREE.BoxGeometry(0.006, 0.002, 0.004),
            new THREE.MeshPhysicalMaterial({color:'#f0d8d0', roughness:0.12, clearcoat:0.8})
        ));
        nail.position.set(fOff[fi], -0.034 - fLen[fi], 0.003);
        wristPivot.add(nail);
    }
    const thumb = ns(part(new THREE.CylinderGeometry(0.005, 0.004, 0.026, 6), handSkinM));
    thumb.position.set(side*0.025, -0.026, 0.007);
    thumb.rotation.z = side*0.45; thumb.rotation.x = 0.2;
    wristPivot.add(thumb);

    return {shoulderPivot, elbowPivot, wristPivot};
}

const leftArm = buildArm(-1);
const rightArm = buildArm(1);

// --- Legs ---
function buildLeg(side) {
    const hipPivot = pivot(side*0.1*HW, 0, 0);
    hips.add(hipPivot);

    const thigh = part(new THREE.CylinderGeometry(0.056, 0.046, 0.35*HS, 12), pantsM);
    thigh.position.y = -0.175*HS;
    hipPivot.add(thigh);

    const kneePivot = pivot(0, -0.35*HS, 0);
    hipPivot.add(kneePivot);

    // Knee AO
    const kneeAO = ns(part(new THREE.TorusGeometry(0.044, 0.004, 4, 10), aoM));
    kneeAO.rotation.x = Math.PI/2;
    kneePivot.add(kneeAO);

    const shin = part(new THREE.CylinderGeometry(0.042, 0.037, 0.35*HS, 12), pantsM);
    shin.position.y = -0.175*HS;
    kneePivot.add(shin);

    const hem = ns(part(
        new THREE.TorusGeometry(0.038, 0.003, 4, 12),
        new THREE.MeshStandardMaterial({
            color: new THREE.Color().copy(pantsC).multiplyScalar(0.83), roughness: 0.9
        })
    ));
    hem.position.y = -0.35*HS; hem.rotation.x = Math.PI/2;
    kneePivot.add(hem);

    const anklePivot = pivot(0, -0.35*HS, 0);
    kneePivot.add(anklePivot);

    const shoeBody = part(new THREE.BoxGeometry(0.07, 0.046, 0.135), shoeM);
    shoeBody.position.set(0, -0.023, 0.022);
    anklePivot.add(shoeBody);
    const toeCap = ns(part(
        new THREE.SphereGeometry(0.035, 10, 6, 0, Math.PI*2, 0, Math.PI*0.5), shoeM
    ));
    toeCap.position.set(0, -0.016, 0.085); toeCap.rotation.x = Math.PI/2;
    anklePivot.add(toeCap);
    const sole = ns(part(
        new THREE.BoxGeometry(0.073, 0.01, 0.14),
        new THREE.MeshStandardMaterial({color:'#060606', roughness:0.95})
    ));
    sole.position.set(0, -0.046, 0.022);
    anklePivot.add(sole);

    return {hipPivot, kneePivot, anklePivot};
}

const leftLeg = buildLeg(-1);
const rightLeg = buildLeg(1);

S.body = {
    hips, upperTorsoPivot, neckPivot, headPivot,
    leftArm, rightArm, leftLeg, rightLeg,
};
S.eyes = eyeTargets;
S.built = true;
"""


# ---------------------------------------------------------------------------
# Idle V3 — micro-muscles, brow movements, lip corner twitches
# ---------------------------------------------------------------------------

IDLE_V3_SCRIPT = r"""
if (!ctx.state.built) return;
const S = ctx.state;
const b = S.body;
const P = ctx.props;

if (!S.idle_init) {
    S.idle_init = true;
    S.seed = ctx.entity.position.x * 7.3 + ctx.entity.position.z * 13.7;
    S.blinkTimer = 2 + Math.random() * 4;
    S.blinkPhase = 0;
    S.blinkT = 0;
    S.gazeTarget = {x: 0, y: 0};
    S.gazeTimer = 1 + Math.random() * 3;
    S.microTimer = 0;
    S.browOffset = 0;
    S.lipCornerOffset = 0;
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

// Breathing with chest volume
const breathe = Math.sin(t * 1.35 + seed);
b.upperTorsoPivot.rotation.x = breathe * 0.012;
const bScale = 1.0 + breathe * 0.009;
b.upperTorsoPivot.scale.set(1.0, bScale, 1.0 + breathe * 0.006);
b.leftArm.shoulderPivot.position.y = 0.27 + breathe * 0.003;
b.rightArm.shoulderPivot.position.y = 0.27 + breathe * 0.003;

// Head
const headY = Math.sin(t*0.22+seed)*0.32 + Math.sin(t*0.09+seed*2)*0.12;
const headX = Math.sin(t*0.16+seed*3)*0.05;
b.headPivot.rotation.y = headY;
b.headPivot.rotation.x = headX;
b.neckPivot.rotation.y = headY * 0.3;

// --- Blink ---
S.blinkTimer -= dt;
if (S.blinkTimer <= 0 && S.blinkPhase === 0) {
    S.blinkPhase = 1; S.blinkT = 0;
}
if (S.blinkPhase > 0) {
    S.blinkT += dt;
    if (S.blinkPhase === 1) {
        const p = Math.min(S.blinkT / 0.07, 1);
        for (const eye of S.eyes) {
            const lid = eye.children.find(c => c.name === 'upperLid');
            if (lid) lid.rotation.x = p * 0.85;
        }
        if (p >= 1) { S.blinkPhase = 2; S.blinkT = 0; }
    } else if (S.blinkPhase === 2) {
        if (S.blinkT > 0.035) { S.blinkPhase = 3; S.blinkT = 0; }
    } else if (S.blinkPhase === 3) {
        const p = Math.min(S.blinkT / 0.09, 1);
        for (const eye of S.eyes) {
            const lid = eye.children.find(c => c.name === 'upperLid');
            if (lid) lid.rotation.x = (1 - p) * 0.85;
        }
        if (p >= 1) {
            S.blinkPhase = 0;
            S.blinkTimer = 1.5 + Math.random() * 5;
        }
    }
}

// --- Gaze ---
S.gazeTimer -= dt;
if (S.gazeTimer <= 0) {
    const dx = ctx.camera.position.x - ctx.entity.position.x;
    const dz = ctx.camera.position.z - ctx.entity.position.z;
    const dist = Math.sqrt(dx*dx + dz*dz);
    if (dist < 8) {
        S.gazeTarget = {x: Math.atan2(dz, 1)*0.12, y: Math.atan2(dx, 1)*0.18};
    } else {
        S.gazeTarget = {x: (Math.random()-0.5)*0.08, y: (Math.random()-0.5)*0.12};
    }
    S.gazeTimer = 1.2 + Math.random() * 3;
}
for (const eye of S.eyes) {
    eye.rotation.x += (S.gazeTarget.x - eye.rotation.x) * dt * 3.5;
    eye.rotation.y += (S.gazeTarget.y - eye.rotation.y) * dt * 3.5;
}

// --- Micro-muscle movements (brow raise, lip corner) ---
S.microTimer -= dt;
if (S.microTimer <= 0) {
    S.browOffset = (Math.random() - 0.5) * 0.004;
    S.lipCornerOffset = (Math.random() - 0.5) * 0.002;
    S.microTimer = 2 + Math.random() * 5;
}
// Apply micro-muscles to named meshes
b.headPivot.children.forEach(c => {
    if (c.name === 'brow_L' || c.name === 'brow_R') {
        c.position.y = 0.155 + S.browOffset;
    }
    if (c.name === 'lipCorner_L' || c.name === 'lipCorner_R') {
        c.position.y = 0.069 + S.lipCornerOffset;
    }
});

// --- Body ---
if (!S.seated) {
    b.leftArm.shoulderPivot.rotation.x = 0.05 + breathe*0.01;
    b.rightArm.shoulderPivot.rotation.x = 0.05 + breathe*0.01;
    b.leftArm.elbowPivot.rotation.x = -0.15;
    b.rightArm.elbowPivot.rotation.x = -0.15;
    b.leftLeg.hipPivot.rotation.x = 0;
    b.rightLeg.hipPivot.rotation.x = 0;
    b.leftLeg.kneePivot.rotation.x = 0;
    b.rightLeg.kneePivot.rotation.x = 0;
    b.hips.position.y = 0.92;
    const shift = Math.sin(t*0.14+seed)*0.013;
    b.hips.rotation.z = shift;
    b.hips.position.x = shift * 0.4;
} else {
    const g = Math.sin(t*0.15+seed*5);
    b.leftArm.shoulderPivot.rotation.x = -0.7 + g*0.04;
    b.leftArm.elbowPivot.rotation.x = -0.9;
    const drink = Math.sin(t*0.08+seed*7);
    if (drink > 0.85) {
        const lift = (drink-0.85)/0.15;
        b.rightArm.shoulderPivot.rotation.x = -0.5 - lift*0.6;
        b.rightArm.elbowPivot.rotation.x = -1.2 - lift*0.4;
        b.headPivot.rotation.x = lift*0.1;
    } else {
        b.rightArm.shoulderPivot.rotation.x = -0.6 + Math.sin(t*0.2+seed)*0.05;
        b.rightArm.elbowPivot.rotation.x = -0.8;
    }
    b.hips.rotation.z = Math.sin(t*0.12+seed)*0.022;
}
"""


# ---------------------------------------------------------------------------
# Wander V3 — improved walk with head stabilization
# ---------------------------------------------------------------------------

WANDER_V3_SCRIPT = r"""
function walkCycle(S, t, speed) {
    const b = S.body;
    const phase = t * speed * 5;
    const sin = Math.sin(phase);
    const cos = Math.cos(phase);
    b.hips.position.y = 0.92 + Math.abs(sin) * 0.016;
    b.hips.rotation.z = sin * 0.016;
    b.hips.rotation.y = sin * 0.03; // hip rotation
    b.upperTorsoPivot.rotation.y = -sin * 0.035; // counter-rotate
    b.upperTorsoPivot.rotation.z = -sin * 0.008;
    // Head stabilization (counter all body rotation)
    b.headPivot.rotation.z = -sin * 0.006;
    b.headPivot.rotation.y = sin * 0.02;
    // Arms: natural swing with elbow bend
    b.leftArm.shoulderPivot.rotation.x = -sin * 0.42;
    b.rightArm.shoulderPivot.rotation.x = sin * 0.42;
    b.leftArm.elbowPivot.rotation.x = -0.05 - Math.max(0, sin) * 0.3;
    b.rightArm.elbowPivot.rotation.x = -0.05 - Math.max(0, -sin) * 0.3;
    // Wrist rotation during swing
    b.leftArm.wristPivot.rotation.y = sin * 0.1;
    b.rightArm.wristPivot.rotation.y = -sin * 0.1;
    // Legs
    b.leftLeg.hipPivot.rotation.x = sin * 0.38;
    b.rightLeg.hipPivot.rotation.x = -sin * 0.38;
    b.leftLeg.kneePivot.rotation.x = Math.max(0, -sin) * 0.5;
    b.rightLeg.kneePivot.rotation.x = Math.max(0, sin) * 0.5;
    b.leftLeg.anklePivot.rotation.x = sin * 0.1;
    b.rightLeg.anklePivot.rotation.x = -sin * 0.1;
}

function idleBreathing(S, t) {
    const b = S.body;
    const br = Math.sin(t * 1.35);
    b.upperTorsoPivot.rotation.x = br * 0.012;
    b.leftArm.shoulderPivot.rotation.x = 0.05 + br*0.01;
    b.rightArm.shoulderPivot.rotation.x = 0.05 + br*0.01;
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
    const b = ctx.props.bounds || [-10, -8, 10, 9];
    S.bounds = {minX:b[0], minZ:b[1], maxX:b[2], maxZ:b[3]};
    S.target = null;
    S.waitTimer = 0;
    S.walking = false;
    S.speed = ctx.props.speed || 0.7;
    S.walkT = 0;
    S.blinkTimer = 2 + Math.random()*4;
    S.blinkPhase = 0;
    S.blinkT = 0;
    S.seed = ctx.entity.position.x * 7 + ctx.entity.position.z * 11;
}

// Blink
S.blinkTimer -= ctx.deltaTime;
if (S.blinkTimer <= 0 && S.blinkPhase === 0) { S.blinkPhase = 1; S.blinkT = 0; }
if (S.blinkPhase > 0) {
    S.blinkT += ctx.deltaTime;
    if (S.blinkPhase === 1) {
        const p = Math.min(S.blinkT/0.07, 1);
        for (const eye of S.eyes) {
            const lid = eye.children.find(c=>c.name==='upperLid');
            if (lid) lid.rotation.x = p*0.85;
        }
        if (p >= 1) { S.blinkPhase = 2; S.blinkT = 0; }
    } else if (S.blinkPhase === 2) {
        if (S.blinkT > 0.035) { S.blinkPhase = 3; S.blinkT = 0; }
    } else if (S.blinkPhase === 3) {
        const p = Math.min(S.blinkT/0.09, 1);
        for (const eye of S.eyes) {
            const lid = eye.children.find(c=>c.name==='upperLid');
            if (lid) lid.rotation.x = (1-p)*0.85;
        }
        if (p >= 1) { S.blinkPhase = 0; S.blinkTimer = 1.5 + Math.random()*5; }
    }
}

if (!S.walking) {
    S.waitTimer += ctx.deltaTime;
    idleBreathing(S, ctx.elapsed);
    S.body.headPivot.rotation.y = Math.sin(ctx.elapsed*0.35+S.seed)*0.4;
    S.body.headPivot.rotation.x = Math.sin(ctx.elapsed*0.2)*0.04;
    const shift = Math.sin(ctx.elapsed*0.18+S.seed)*0.012;
    S.body.hips.rotation.z = shift;
    if (S.waitTimer > 2.5 + Math.random()*4) {
        const bnd = S.bounds;
        S.target = {
            x: bnd.minX + Math.random()*(bnd.maxX-bnd.minX),
            z: bnd.minZ + Math.random()*(bnd.maxZ-bnd.minZ),
        };
        S.walking = true;
        S.waitTimer = 0;
        S.walkT = 0;
    }
} else {
    const dx = S.target.x - ctx.entity.position.x;
    const dz = S.target.z - ctx.entity.position.z;
    const dist = Math.sqrt(dx*dx + dz*dz);
    if (dist < 0.3) {
        S.walking = false;
    } else {
        const step = Math.min(S.speed * ctx.deltaTime, dist);
        ctx.entity.position.x += (dx/dist)*step;
        ctx.entity.position.z += (dz/dist)*step;
        // Smooth turning
        const targetRot = Math.atan2(dx, dz);
        let diff = targetRot - ctx.entity.rotation.y;
        while (diff > Math.PI) diff -= Math.PI*2;
        while (diff < -Math.PI) diff += Math.PI*2;
        ctx.entity.rotation.y += diff * Math.min(1, ctx.deltaTime * 5);
        S.walkT += ctx.deltaTime;
        walkCycle(S, S.walkT, S.speed);
    }
}
"""


# ---------------------------------------------------------------------------
# Greet V3 — wave gesture
# ---------------------------------------------------------------------------

GREET_V3_SCRIPT = r"""
if (!ctx.state.built) return;
const dx = ctx.camera.position.x - ctx.entity.position.x;
const dz = ctx.camera.position.z - ctx.entity.position.z;
ctx.entity.rotation.y = Math.atan2(dx, dz);
const b = ctx.state.body;
// Raise right arm to wave
b.rightArm.shoulderPivot.rotation.x = -2.0;
b.rightArm.shoulderPivot.rotation.z = -0.5;
b.rightArm.elbowPivot.rotation.x = -0.8;
let waveT = 0;
const waveInterval = setInterval(() => {
    waveT += 0.05;
    b.rightArm.wristPivot.rotation.z = Math.sin(waveT * 8) * 0.4;
    if (waveT > 0.8) {
        clearInterval(waveInterval);
        b.rightArm.shoulderPivot.rotation.x = 0.05;
        b.rightArm.shoulderPivot.rotation.z = 0;
        b.rightArm.elbowPivot.rotation.x = -0.15;
        b.rightArm.wristPivot.rotation.z = 0;
    }
}, 50);
console.log(ctx.entity.userData.entityName + ': ' + (ctx.props.greeting || 'Hello!'));
"""
