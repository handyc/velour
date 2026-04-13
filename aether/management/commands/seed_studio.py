"""Seed the Velour Studio — avatar realism iteration 3.

Building on Garden V3, this iteration addresses uncanny valley by:
- Kawaii proportions: larger head (1.3x), bigger rounder eyes, smaller nose/mouth
- Eyes placed lower on face with larger irises and prominent catchlights
- Softer features: less harsh AO, gentler creases, rounder jawline
- Articulated fingers: 3 phalanges per finger with individual pivot joints
- Thumb: metacarpal + 2 phalanges, natural opposition angle
- Finger idle animation: individual fidgeting, natural spread
- Enhanced micro-facial: cheek puff, squash-stretch blinks, brow asymmetry
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
    help = 'Create the Velour Studio with kawaii V4 humanoids + articulated fingers.'

    def handle(self, *args, **options):
        World.objects.filter(slug='velour-studio').delete()

        world = World.objects.create(
            title='Velour Studio',
            slug='velour-studio',
            description='Art studio with V4 avatars: kawaii proportions, '
                        'articulated finger joints, enhanced micro-expressions.',
            skybox='hdri',
            hdri_asset='kloofendal_48d_partly_cloudy',
            sky_color='#a0b8d8',
            ground_color='#2a2a30',
            ground_size=40.0,
            ambient_light=0.5,
            fog_near=35.0,
            fog_far=100.0,
            fog_color='#d0d8e8',
            gravity=-9.81,
            spawn_x=0.0, spawn_y=1.6, spawn_z=8.0,
            soundscape='indoor',
            ambient_volume=0.15,
            published=True, featured=True,
        )

        humanoid_v4 = _script('Humanoid Builder V4', 'start', HUMANOID_V4_SCRIPT,
            'Kawaii-proportioned V4 humanoid with articulated finger joints.')
        idle_v4 = _script('Studio Idle V4', 'update', IDLE_V4_SCRIPT,
            'Rich idle: blinks with squash-stretch, finger fidget, cheek puff.')
        wander_v4 = _script('Studio Wander V4', 'update', WANDER_V4_SCRIPT,
            'Walk cycle with finger sway and hand gestures.')
        greet_v4 = _script('Studio Greet V4', 'interact', GREET_V4_SCRIPT,
            'Turn + open-hand wave with finger spread.')

        entities = []
        E = lambda *a, **k: entities.append(_ent(world, *a, **k))

        # Studio floor
        E('Floor', 'box', '#353540', 0, -0.05, 0, sx=40, sy=0.1, sz=40, shadow=False)

        # Wooden floor planks (subtle)
        for z in range(-15, 16, 2):
            E(f'Plank {z}', 'box', '#3a3530', 0, 0.001, z,
              sx=40, sy=0.003, sz=1.8, shadow=False)

        # Studio walls (three sides, open front)
        E('BackWall', 'box', '#404048', 0, 2.5, -18, sx=40, sy=5, sz=0.2)
        E('LeftWall', 'box', '#3c3c44', -18, 2.5, 0, sx=0.2, sy=5, sz=36)
        E('RightWall', 'box', '#3c3c44', 18, 2.5, 0, sx=0.2, sy=5, sz=36)

        # Ceiling beams
        for x in range(-15, 16, 6):
            E(f'Beam {x}', 'box', '#2a2420', x, 4.9, 0, sx=0.2, sy=0.15, sz=36)

        # Art on walls
        wall_art = [
            (-8, 2.0, -17.8, '#cc3040', 2.4, 1.8),
            (0, 2.5, -17.8, '#2060a0', 3.0, 2.2),
            (8, 2.0, -17.8, '#40a050', 2.0, 2.0),
        ]
        for i, (ax, ay, az, ac, aw, ah) in enumerate(wall_art):
            E(f'Frame {i}', 'box', '#3a2818', ax, ay, az, sx=aw+0.2, sy=ah+0.2, sz=0.04)
            E(f'Canvas {i}', 'box', ac, ax, ay, az+0.03, sx=aw, sy=ah, sz=0.02)

        # Easels
        for ex, ez, ery in [(-6, -5, 15), (6, -5, -15), (-4, 4, 30)]:
            E(f'Easel {ex},{ez}', 'box', '#5a4020', ex, 1.0, ez,
              sx=0.04, sy=2.0, sz=0.04, ry=ery)
            E(f'EaselCanvas {ex},{ez}', 'box', '#e8e0d0', ex, 1.5, ez+0.05,
              sx=0.8, sy=0.6, sz=0.02, ry=ery)

        # Stools
        for sx2, sz2 in [(-3, -3), (3, -3), (0, 3), (-5, 1), (5, 1)]:
            E(f'Stool {sx2},{sz2}', 'cylinder', '#5c4828', sx2, 0.35, sz2,
              sx=0.22, sy=0.7, sz=0.22)

        # Spotlights (visual markers)
        for lx, lz in [(-5, -8), (0, -8), (5, -8), (-8, 0), (8, 0)]:
            E(f'SpotBase {lx},{lz}', 'cylinder', '#202028', lx, 4.6, lz,
              sx=0.08, sy=0.3, sz=0.08)
            E(f'SpotBulb {lx},{lz}', 'sphere', '#ffe880', lx, 4.4, lz,
              sx=0.06, sy=0.06, sz=0.06, shadow=False)

        # Supply tables
        for tx, tz in [(-12, -6), (12, -6)]:
            E(f'Table {tx}', 'box', '#484038', tx, 0.4, tz, sx=1.5, sy=0.04, sz=0.7)
            for leg_x, leg_z in [(-0.6, -0.3), (0.6, -0.3), (-0.6, 0.3), (0.6, 0.3)]:
                E(f'Leg {tx},{leg_x},{leg_z}', 'cylinder', '#3a3430',
                  tx+leg_x, 0.2, tz+leg_z, sx=0.03, sy=0.4, sz=0.03)

        # --- NPCs ---
        NAMES = ['Cleo', 'Dante', 'Freya', 'Kenji', 'Luna',
                 'Nadia', 'Oscar', 'Priya', 'Remy', 'Sage']
        POSITIONS = [
            (-3, -4, 0),
            (3, -4, 180),
            (-6, -1, 90),
            (6, -1, -90),
            (-2, 4, 45),
            (2, 4, -45),
            (-3, -3, 90),   # seated on stool
            (3, -3, -90),   # seated on stool
            (0, 3, 0),      # seated on stool
            (5, -8, 0),     # wanderer
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
            attach(e, humanoid_v4, {
                'skin': SKIN[i], 'shirt': SHIRT[i],
                'pants': PANTS[i], 'shoes': SHOES[i],
                'hair': HAIR[i], 'eyes': EYE_COLORS[i],
                'shoulderW': build[0], 'hipW': build[1], 'heightScale': build[2],
                'jawW': face[0], 'cheekFull': face[1], 'foreheadH': face[2],
            })
            if e._role == 'wander':
                attach(e, wander_v4, {'bounds': [-12, -10, 12, 10], 'speed': 0.6})
            elif e._role == 'seated':
                attach(e, idle_v4, {'seated': True})
            else:
                attach(e, idle_v4, {'seated': False})
            attach(e, greet_v4, {'greeting': f"I'm {NAMES[i]}."})

        EntityScript.objects.bulk_create(attachments)
        total = Entity.objects.filter(world=world).count()
        self.stdout.write(self.style.SUCCESS(
            f'Velour Studio created: {total} entities, {len(npc_ents)} V4 NPCs.'
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
# HUMANOID V4 — kawaii proportions + articulated finger joints
# ---------------------------------------------------------------------------

HUMANOID_V4_SCRIPT = r"""
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

// --- Kawaii head scale factor (1.3x bigger head) ---
const KAWAII_HEAD = 1.3;
const KAWAII_EYE = 1.45;   // eyes even bigger than head scale
const KAWAII_NOSE = 0.7;   // smaller nose
const KAWAII_MOUTH = 0.8;  // smaller mouth

// --- Zone-based skin colors (gentler than V3) ---
const faceSkinC = new THREE.Color().copy(skinC).lerp(new THREE.Color('#ffaa99'), 0.04);
const handSkinC = new THREE.Color().copy(skinC).lerp(new THREE.Color('#ffe0d0'), 0.06);
const neckSkinC = new THREE.Color().copy(skinC).multiplyScalar(0.96);
const aoC = new THREE.Color().copy(skinC).multiplyScalar(0.8); // gentler AO

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
            // Subtler pores for kawaii — less visible texture
            const pore = Math.random() < 0.05 ? -8 : 0;
            const nr = (Math.random()-0.5)*5 + pore;
            const ng = (Math.random()-0.5)*4 + pore;
            const nb = (Math.random()-0.5)*3 + pore;
            id.data[i]  =Math.max(0,Math.min(255,br+nr));
            id.data[i+1]=Math.max(0,Math.min(255,bg+ng));
            id.data[i+2]=Math.max(0,Math.min(255,bb+nb));
            id.data[i+3]=255;
        }
    }
    g.putImageData(id,0,0);
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(2, 2);
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
        map: poreTexture(64, 64, c),
        normalMap: normalNoise(32, 32, 15),
        normalScale: new THREE.Vector2(0.12, 0.12),
        roughness: 0.5,
        metalness: 0.0,
        transmission: 0.06,
        thickness: 1.0,
        attenuationColor: warm,
        attenuationDistance: 0.25,
        sheen: 0.5,
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
        normalMap: normalNoise(32, 32, isShirt ? 14 : 10),
        normalScale: new THREE.Vector2(0.12, 0.12),
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
        normalMap: normalNoise(32, 32, 40),
        normalScale: new THREE.Vector2(0.5, 0.5),
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

const lipColor = new THREE.Color().copy(faceSkinC).lerp(new THREE.Color('#cc5555'), 0.25);
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

// Collar
const collar = ns(part(new THREE.TorusGeometry(0.08, 0.01, 8, 16), shirtM));
collar.position.set(0, 0.3*HS, 0.02); collar.rotation.x = Math.PI/2;
upperTorsoPivot.add(collar);

// Subtle wrinkles
for (let i = 0; i < 3; i++) {
    const w = ns(part(
        new THREE.BoxGeometry((0.18+Math.random()*0.06)*SW, 0.002, 0.003),
        new THREE.MeshStandardMaterial({
            color: new THREE.Color().copy(shirtC).multiplyScalar(0.87), roughness: 0.9
        })
    ));
    w.position.set((Math.random()-0.5)*0.03, (0.08+i*0.07)*HS, 0.1);
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

// --- Neck ---
const neckPivot = pivot(0, 0.3*HS, 0);
upperTorsoPivot.add(neckPivot);
const neck = part(new THREE.CylinderGeometry(0.04, 0.055, 0.08, 12), neckSkinM);
neck.position.y = 0.04;
neckPivot.add(neck);

// --- HEAD (kawaii: 1.3x scale, eyes lower and bigger) ---
const headPivot = pivot(0, 0.08, 0);
neckPivot.add(headPivot);

// Rounder head (more spherical, less elongated)
const KH = KAWAII_HEAD;
const head = part(new THREE.SphereGeometry(0.12*KH, 32, 32), faceSkinM);
head.position.y = 0.13*KH;
head.scale.set(1.0, 0.98, 0.96); // slightly rounder
headPivot.add(head);

// Softer jaw (rounder, less angular)
const jaw = ns(part(
    new THREE.SphereGeometry(0.1*KH, 24, 12, 0, Math.PI*2, Math.PI*0.55, Math.PI*0.45),
    faceSkinM
));
jaw.position.set(0, 0.05*KH, -0.02*KH);
jaw.scale.set(JW*0.95, 0.7, 0.55); // pulled back so eyes show through
headPivot.add(jaw);

// Chin (softer, rounder)
const chin = ns(part(
    new THREE.SphereGeometry(0.03*KH, 12, 8, 0, Math.PI*2, 0, Math.PI*0.5),
    faceSkinM
));
chin.position.set(0, 0.02*KH, 0.09*KH);
chin.scale.set(JW*0.8, 0.9, 0.6);
headPivot.add(chin);

// Forehead (smoother)
const forehead = ns(part(
    new THREE.SphereGeometry(0.11*KH, 20, 10, 0, Math.PI*2, 0, Math.PI*0.35),
    faceSkinM
));
forehead.position.set(0, 0.2*KH*FH, -0.02*KH);
forehead.scale.set(1.0, 1.0, 0.45); // flattened so eyes aren't occluded
headPivot.add(forehead);

// Cheeks (kawaii: puffier, higher — pulled back from eye plane)
for (const side of [-1, 1]) {
    const cheek = ns(part(new THREE.SphereGeometry(0.04*KH, 10, 8), faceSkinM));
    cheek.position.set(side*0.065*KH, 0.09*KH, 0.06*KH);
    cheek.scale.set(1.0*CF, 0.7, 0.4);
    cheek.name = 'cheek_' + (side < 0 ? 'L' : 'R');
    headPivot.add(cheek);
}

// Blush spots (kawaii signature)
const blushM = new THREE.MeshStandardMaterial({
    color: new THREE.Color().copy(faceSkinC).lerp(new THREE.Color('#ff7788'), 0.2),
    roughness: 0.7, transparent: true, opacity: 0.35,
});
for (const side of [-1, 1]) {
    const blush = ns(part(new THREE.CircleGeometry(0.018*KH, 12), blushM));
    blush.position.set(side*0.072*KH, 0.08*KH, 0.1*KH);
    blush.name = 'blush_' + (side < 0 ? 'L' : 'R');
    headPivot.add(blush);
}

// --- EYES (kawaii: placed lower on face, much bigger, bigger iris) ---
const eyeTargets = [];
const KE = KAWAII_EYE;
for (const side of [-1, 1]) {
    // Softer orbital shadow (no harsh AO ring)
    const orbitShadow = ns(part(
        new THREE.CircleGeometry(0.022*KE, 12),
        new THREE.MeshStandardMaterial({color: aoC, roughness: 0.9, transparent: true, opacity: 0.3})
    ));
    orbitShadow.position.set(side*0.045*KH, 0.1*KH, 0.1*KH);
    headPivot.add(orbitShadow);

    // Eyes lower on face (0.1 instead of 0.13) and wider apart
    const eyeGroup = pivot(side*0.045*KH, 0.105*KH, 0.1*KH);
    headPivot.add(eyeGroup);

    // Larger eyeball
    const eyeball = ns(part(
        new THREE.SphereGeometry(0.022*KE, 20, 20),
        new THREE.MeshPhysicalMaterial({
            color: '#f8f8f4', roughness: 0.03,
            clearcoat: 1.0, clearcoatRoughness: 0.02,
        })
    ));
    eyeball.position.z = 0.003;
    eyeGroup.add(eyeball);

    // Corneal bulge (bigger, more prominent reflection)
    const cornea = ns(part(
        new THREE.SphereGeometry(0.017*KE, 24, 24, 0, Math.PI*2, 0, Math.PI*0.5),
        new THREE.MeshPhysicalMaterial({
            color: '#ffffff', transparent: true, opacity: 0.15,
            roughness: 0.0,
            clearcoat: 1.0, clearcoatRoughness: 0.0,
            ior: 1.376,
            sheen: 1.0, sheenRoughness: 0.0,
            sheenColor: new THREE.Color('#ffffff'),
        })
    ));
    cornea.position.set(0, 0, 0.018);
    cornea.rotation.x = -Math.PI/2;
    eyeGroup.add(cornea);

    // Larger iris with kawaii style (bigger iris-to-eye ratio)
    const ic = document.createElement('canvas');
    ic.width = 80; ic.height = 80;
    const ig = ic.getContext('2d');
    const cx = 40, cy = 40;
    // Limbal ring
    ig.fillStyle = '#000000';
    ig.beginPath(); ig.arc(cx, cy, 38, 0, Math.PI*2); ig.fill();
    // Iris gradient (richer colors for kawaii)
    for (let r = 36; r > 0; r -= 1) {
        const t = r / 36;
        const c2 = new THREE.Color().copy(eyeC).lerp(new THREE.Color('#000'), (1-t)*0.3);
        if (t > 0.5) c2.lerp(new THREE.Color('#fff'), (t-0.5)*0.15);
        ig.fillStyle = '#'+c2.getHexString();
        ig.beginPath(); ig.arc(cx, cy, r, 0, Math.PI*2); ig.fill();
    }
    // Collarette
    ig.strokeStyle = '#'+new THREE.Color().copy(eyeC).lerp(new THREE.Color('#fff'), 0.5).getHexString();
    ig.lineWidth = 2;
    ig.beginPath(); ig.arc(cx, cy, 20, 0, Math.PI*2); ig.stroke();
    // Pupil (larger for kawaii)
    ig.fillStyle = '#020202';
    ig.beginPath(); ig.arc(cx, cy, 13, 0, Math.PI*2); ig.fill();
    // Radial fibers
    ig.globalAlpha = 0.2;
    for (let a = 0; a < Math.PI*2; a += 0.12) {
        ig.strokeStyle = Math.random() > 0.5 ? '#ffffff' : '#000000';
        ig.lineWidth = 0.5;
        ig.beginPath();
        ig.moveTo(cx + Math.cos(a)*13, cy + Math.sin(a)*13);
        ig.lineTo(cx + Math.cos(a)*34, cy + Math.sin(a)*34);
        ig.stroke();
    }
    ig.globalAlpha = 1.0;
    // Catchlights (bigger, more prominent for kawaii sparkle)
    ig.fillStyle = 'rgba(255,255,255,0.85)';
    ig.beginPath(); ig.arc(cx-8, cy-10, 6, 0, Math.PI*2); ig.fill();
    ig.fillStyle = 'rgba(255,255,255,0.5)';
    ig.beginPath(); ig.arc(cx+6, cy+5, 3.5, 0, Math.PI*2); ig.fill();
    ig.fillStyle = 'rgba(255,255,255,0.25)';
    ig.beginPath(); ig.arc(cx-3, cy+8, 2, 0, Math.PI*2); ig.fill();

    const irisTex = new THREE.CanvasTexture(ic);
    const iris = ns(part(
        new THREE.CircleGeometry(0.016*KE, 28),
        new THREE.MeshPhysicalMaterial({map: irisTex, roughness: 0.1, clearcoat: 0.8})
    ));
    iris.position.set(0, 0, 0.019);
    eyeGroup.add(iris);

    // Upper eyelid (rounder for kawaii)
    const lid = ns(part(
        new THREE.SphereGeometry(0.025*KE, 14, 8, 0, Math.PI*2, 0, Math.PI*0.4),
        faceSkinM
    ));
    lid.position.set(0, 0.006, 0.002);
    lid.name = 'upperLid';
    eyeGroup.add(lid);

    // Lower eyelid (subtler)
    const lowerLid = ns(part(
        new THREE.SphereGeometry(0.023*KE, 10, 6, 0, Math.PI*2, Math.PI*0.65, Math.PI*0.35),
        faceSkinM
    ));
    lowerLid.position.set(0, -0.008, 0.002);
    lowerLid.name = 'lowerLid';
    eyeGroup.add(lowerLid);

    // Eyelashes (thicker, more prominent for kawaii)
    const lash = ns(part(
        new THREE.TorusGeometry(0.023*KE, 0.002, 4, 16, Math.PI),
        new THREE.MeshStandardMaterial({color: '#080808', roughness: 0.8})
    ));
    lash.position.set(0, 0.01, 0.012);
    lash.rotation.x = 0.25; lash.rotation.z = Math.PI;
    eyeGroup.add(lash);

    // Lower lash line
    const lowerLash = ns(part(
        new THREE.TorusGeometry(0.02*KE, 0.001, 3, 12, Math.PI),
        new THREE.MeshStandardMaterial({color: '#181818', roughness: 0.85})
    ));
    lowerLash.position.set(0, -0.008, 0.012);
    lowerLash.rotation.x = -0.2;
    eyeGroup.add(lowerLash);

    eyeTargets.push(eyeGroup);
}

// Eyebrows (softer, higher for kawaii expressiveness)
for (const side of [-1, 1]) {
    const brow = ns(part(
        new THREE.CylinderGeometry(0.004, 0.003, 0.04*KH, 6),
        new THREE.MeshStandardMaterial({
            color: new THREE.Color().copy(hairC).lerp(faceSkinC, 0.15), roughness: 0.8
        })
    ));
    brow.position.set(side*0.044*KH, 0.15*KH, 0.1*KH);
    brow.rotation.z = Math.PI/2 + side*0.1;
    brow.name = 'brow_' + (side < 0 ? 'L' : 'R');
    headPivot.add(brow);
}

// --- Nose (kawaii: smaller, simpler, button-like) ---
const KN = KAWAII_NOSE;
const noseTip = ns(part(new THREE.SphereGeometry(0.013*KH*KN, 10, 8), faceSkinM));
noseTip.position.set(0, 0.085*KH, 0.13*KH);
headPivot.add(noseTip);
// Just tiny nostril shadows (no bridge, no wings — kawaii simplicity)
for (const side of [-1, 1]) {
    const nostril = ns(part(new THREE.SphereGeometry(0.003*KH, 5, 4), aoM));
    nostril.position.set(side*0.007*KH, 0.08*KH, 0.132*KH);
    headPivot.add(nostril);
}

// --- Mouth (kawaii: smaller, rounder) ---
const KM = KAWAII_MOUTH;
const upperLip = ns(part(
    new THREE.TorusGeometry(0.015*KH*KM, 0.005, 8, 16, Math.PI), lipM
));
upperLip.position.set(0, 0.063*KH, 0.12*KH); upperLip.rotation.z = Math.PI;
headPivot.add(upperLip);

const lowerLip = ns(part(
    new THREE.TorusGeometry(0.017*KH*KM, 0.006, 8, 16, Math.PI), lipM
));
lowerLip.position.set(0, 0.056*KH, 0.118*KH);
headPivot.add(lowerLip);

// Lip line
const lipLine = ns(part(new THREE.BoxGeometry(0.025*KH*KM, 0.001, 0.002),
    new THREE.MeshStandardMaterial({color: '#2a1510', roughness: 0.9})
));
lipLine.position.set(0, 0.059*KH, 0.123*KH);
headPivot.add(lipLine);

// Lip corners
for (const side of [-1, 1]) {
    const corner = ns(part(new THREE.SphereGeometry(0.003, 4, 4), aoM));
    corner.position.set(side*0.017*KH*KM, 0.059*KH, 0.118*KH);
    corner.name = 'lipCorner_' + (side < 0 ? 'L' : 'R');
    headPivot.add(corner);
}

// --- Ears (slightly smaller for kawaii, simpler) ---
for (const side of [-1, 1]) {
    const earGroup = pivot(side*0.12*KH, 0.11*KH, 0);
    headPivot.add(earGroup);
    const helix = ns(part(
        new THREE.TorusGeometry(0.018*KH, 0.004, 8, 14, Math.PI*1.5), faceSkinM
    ));
    helix.rotation.y = side*Math.PI/2; helix.rotation.x = -0.2;
    earGroup.add(helix);
    const lobe = ns(part(new THREE.SphereGeometry(0.006*KH, 6, 6), faceSkinM));
    lobe.position.set(0, -0.017, side*0.003);
    earGroup.add(lobe);
}

// --- Hair: multi-shell (scaled for kawaii head) ---
const hairBase = ns(part(
    new THREE.SphereGeometry(0.13*KH, 32, 16, 0, Math.PI*2, 0, Math.PI*0.55), hairM
));
hairBase.position.y = 0.15*KH;
headPivot.add(hairBase);

const hairMid = ns(part(
    new THREE.SphereGeometry(0.135*KH, 24, 12, 0, Math.PI*2, 0, Math.PI*0.52),
    new THREE.MeshPhysicalMaterial({
        color: hairC, roughness: 0.5,
        sheen: 0.9, sheenRoughness: 0.25,
        sheenColor: new THREE.Color().copy(hairC).lerp(new THREE.Color('#fff'), 0.3),
        transparent: true, opacity: 0.55,
    })
));
hairMid.position.y = 0.153*KH;
headPivot.add(hairMid);

const hairOuter = ns(part(
    new THREE.SphereGeometry(0.14*KH, 20, 10, 0, Math.PI*2, 0, Math.PI*0.48),
    new THREE.MeshPhysicalMaterial({
        color: new THREE.Color().copy(hairC).lerp(new THREE.Color('#fff'), 0.1),
        roughness: 0.55, transparent: true, opacity: 0.3,
        sheen: 0.7, sheenRoughness: 0.3,
        sheenColor: new THREE.Color().copy(hairC).lerp(new THREE.Color('#fff'), 0.4),
    })
));
hairOuter.position.y = 0.156*KH;
headPivot.add(hairOuter);

const hairBack = ns(part(
    new THREE.SphereGeometry(0.11*KH, 16, 10, 0, Math.PI*2, Math.PI*0.2, Math.PI*0.5), hairM
));
hairBack.position.set(0, 0.1*KH, -0.04*KH);
headPivot.add(hairBack);

// Fringe/bangs (kawaii touch)
for (let i = -2; i <= 2; i++) {
    const bang = ns(part(
        new THREE.SphereGeometry(0.025*KH, 8, 6, 0, Math.PI*2, 0, Math.PI*0.5),
        hairM
    ));
    bang.position.set(i*0.03*KH, 0.19*KH, 0.1*KH);
    bang.rotation.x = 0.3;
    headPivot.add(bang);
}

// === ARMS with ARTICULATED HANDS ===
function buildArm(side) {
    const shoulderPivot = pivot(side*0.22*SW, 0.27*HS, 0);
    upperTorsoPivot.add(shoulderPivot);

    // Deltoid
    const deltoid = ns(part(
        new THREE.SphereGeometry(0.038, 10, 8, 0, Math.PI*2, 0, Math.PI*0.5), shirtM
    ));
    deltoid.position.set(0, 0.01, 0); deltoid.rotation.x = -0.3;
    shoulderPivot.add(deltoid);

    const upperArm = part(new THREE.CylinderGeometry(0.035, 0.03, 0.24*HS, 12), shirtM);
    upperArm.position.y = -0.12*HS;
    shoulderPivot.add(upperArm);

    // Cuff
    const cuff = ns(part(
        new THREE.TorusGeometry(0.031, 0.003, 6, 12),
        new THREE.MeshStandardMaterial({
            color: new THREE.Color().copy(shirtC).multiplyScalar(0.85), roughness: 0.85
        })
    ));
    cuff.position.y = -0.23*HS; cuff.rotation.x = Math.PI/2;
    shoulderPivot.add(cuff);

    const elbowPivot = pivot(0, -0.24*HS, 0);
    shoulderPivot.add(elbowPivot);

    const forearm = part(new THREE.CylinderGeometry(0.03, 0.025, 0.22*HS, 12), skinM);
    forearm.position.y = -0.11*HS;
    elbowPivot.add(forearm);

    const wristPivot = pivot(0, -0.22*HS, 0);
    elbowPivot.add(wristPivot);

    // === ARTICULATED HAND ===
    const palm = part(new THREE.BoxGeometry(0.044, 0.03, 0.026), handSkinM);
    palm.position.y = -0.015;
    wristPivot.add(palm);

    // Finger data: [xOffset, totalLength, proximalLen, middleLen, distalLen, restCurl]
    const fingerData = [
        [-0.016, 0.032, 0.013, 0.010, 0.009, 0.15],  // index
        [-0.006, 0.036, 0.015, 0.012, 0.009, 0.12],  // middle
        [0.005,  0.034, 0.014, 0.011, 0.009, 0.14],   // ring
        [0.015,  0.028, 0.012, 0.009, 0.007, 0.18],   // pinky
    ];
    const fingerRadius = 0.0035;
    const nailM = new THREE.MeshPhysicalMaterial({color:'#f0d8d0', roughness:0.12, clearcoat:0.8});

    const fingers = [];
    for (let fi = 0; fi < fingerData.length; fi++) {
        const [fx, , pLen, mLen, dLen, curl] = fingerData[fi];

        // Metacarpophalangeal joint (MCP) — base of finger
        const mcpPivot = pivot(fx, -0.03, 0);
        wristPivot.add(mcpPivot);
        mcpPivot.rotation.x = curl;

        // Knuckle bump
        const knuckle = ns(part(new THREE.SphereGeometry(fingerRadius*1.2, 6, 4), handSkinM));
        knuckle.position.set(0, 0, 0.005);
        mcpPivot.add(knuckle);

        // Proximal phalanx
        const proximal = ns(part(
            new THREE.CylinderGeometry(fingerRadius, fingerRadius*0.95, pLen, 6), handSkinM
        ));
        proximal.position.y = -pLen/2;
        mcpPivot.add(proximal);

        // Proximal interphalangeal joint (PIP)
        const pipPivot = pivot(0, -pLen, 0);
        mcpPivot.add(pipPivot);
        pipPivot.rotation.x = curl * 0.8;

        // Joint bump
        const pipBump = ns(part(new THREE.SphereGeometry(fingerRadius*1.05, 5, 3), handSkinM));
        pipPivot.add(pipBump);

        // Middle phalanx
        const middle = ns(part(
            new THREE.CylinderGeometry(fingerRadius*0.95, fingerRadius*0.9, mLen, 6), handSkinM
        ));
        middle.position.y = -mLen/2;
        pipPivot.add(middle);

        // Distal interphalangeal joint (DIP)
        const dipPivot = pivot(0, -mLen, 0);
        pipPivot.add(dipPivot);
        dipPivot.rotation.x = curl * 0.6;

        // Distal phalanx
        const distal = ns(part(
            new THREE.CylinderGeometry(fingerRadius*0.9, fingerRadius*0.7, dLen, 6), handSkinM
        ));
        distal.position.y = -dLen/2;
        dipPivot.add(distal);

        // Fingernail
        const nail = ns(part(new THREE.BoxGeometry(fingerRadius*2, 0.002, dLen*0.6), nailM));
        nail.position.set(0, 0.002, -dLen/2);
        nail.rotation.x = -0.1;
        dipPivot.add(nail);

        fingers.push({mcpPivot, pipPivot, dipPivot, restCurl: curl});
    }

    // === THUMB (2 phalanges + metacarpal) ===
    const thumbCMC = pivot(side*0.023, -0.015, 0.008);
    wristPivot.add(thumbCMC);
    thumbCMC.rotation.z = side*0.55;
    thumbCMC.rotation.x = 0.15;

    // Metacarpal
    const thumbMeta = ns(part(
        new THREE.CylinderGeometry(0.005, 0.0045, 0.016, 6), handSkinM
    ));
    thumbMeta.position.y = -0.008;
    thumbCMC.add(thumbMeta);

    // MCP joint
    const thumbMCP = pivot(0, -0.016, 0);
    thumbCMC.add(thumbMCP);
    thumbMCP.rotation.x = 0.1;

    const thumbProx = ns(part(
        new THREE.CylinderGeometry(0.0048, 0.004, 0.014, 6), handSkinM
    ));
    thumbProx.position.y = -0.007;
    thumbMCP.add(thumbProx);

    // IP joint (thumb only has one interphalangeal)
    const thumbIP = pivot(0, -0.014, 0);
    thumbMCP.add(thumbIP);
    thumbIP.rotation.x = 0.08;

    const thumbDistal = ns(part(
        new THREE.CylinderGeometry(0.004, 0.003, 0.011, 6), handSkinM
    ));
    thumbDistal.position.y = -0.0055;
    thumbIP.add(thumbDistal);

    // Thumbnail
    const thumbNail = ns(part(new THREE.BoxGeometry(0.007, 0.002, 0.006), nailM));
    thumbNail.position.set(0, 0.002, -0.005);
    thumbIP.add(thumbNail);

    const thumb = {cmcPivot: thumbCMC, mcpPivot: thumbMCP, ipPivot: thumbIP, restCurl: 0.1};

    return {shoulderPivot, elbowPivot, wristPivot, fingers, thumb};
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

    const shin = part(new THREE.CylinderGeometry(0.042, 0.037, 0.35*HS, 12), pantsM);
    shin.position.y = -0.175*HS;
    kneePivot.add(shin);

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
# Idle V4 — finger fidget, cheek puff, squash-stretch blink
# ---------------------------------------------------------------------------

IDLE_V4_SCRIPT = r"""
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
    S.browOffset = {l: 0, r: 0};
    S.lipCornerOffset = 0;
    S.cheekPuff = 0;
    S.cheekTarget = 0;
    S.fingerTimer = 0;
    S.fingerTargets = {};
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

// Breathing
const breathe = Math.sin(t * 1.35 + seed);
b.upperTorsoPivot.rotation.x = breathe * 0.012;
const bScale = 1.0 + breathe * 0.009;
b.upperTorsoPivot.scale.set(1.0, bScale, 1.0 + breathe * 0.006);
b.leftArm.shoulderPivot.position.y = 0.27 + breathe * 0.003;
b.rightArm.shoulderPivot.position.y = 0.27 + breathe * 0.003;

// Head (gentle sway)
const headY = Math.sin(t*0.22+seed)*0.3 + Math.sin(t*0.09+seed*2)*0.1;
const headX = Math.sin(t*0.16+seed*3)*0.04;
b.headPivot.rotation.y = headY;
b.headPivot.rotation.x = headX;
b.neckPivot.rotation.y = headY * 0.3;

// --- Blink with squash-stretch ---
S.blinkTimer -= dt;
if (S.blinkTimer <= 0 && S.blinkPhase === 0) {
    S.blinkPhase = 1; S.blinkT = 0;
}
if (S.blinkPhase > 0) {
    S.blinkT += dt;
    if (S.blinkPhase === 1) {
        // Close: squash eyes vertically, stretch horizontally
        const p = Math.min(S.blinkT / 0.06, 1);
        for (const eye of S.eyes) {
            const lid = eye.children.find(c => c.name === 'upperLid');
            if (lid) lid.rotation.x = p * 0.9;
            // Squash-stretch: compress Y, expand X slightly
            eye.scale.set(1.0 + p*0.04, 1.0 - p*0.12, 1.0);
        }
        if (p >= 1) { S.blinkPhase = 2; S.blinkT = 0; }
    } else if (S.blinkPhase === 2) {
        if (S.blinkT > 0.03) { S.blinkPhase = 3; S.blinkT = 0; }
    } else if (S.blinkPhase === 3) {
        // Open: reverse squash-stretch with slight overshoot
        const p = Math.min(S.blinkT / 0.08, 1);
        const overshoot = p < 0.7 ? 0 : Math.sin((p-0.7)/0.3 * Math.PI) * 0.03;
        for (const eye of S.eyes) {
            const lid = eye.children.find(c => c.name === 'upperLid');
            if (lid) lid.rotation.x = (1 - p) * 0.9;
            eye.scale.set(1.0 + (1-p)*0.04, 1.0 - (1-p)*0.12 + overshoot, 1.0);
        }
        if (p >= 1) {
            S.blinkPhase = 0;
            S.blinkTimer = 1.5 + Math.random() * 5;
            for (const eye of S.eyes) eye.scale.set(1, 1, 1);
        }
    }
}

// --- Gaze (track player when close) ---
S.gazeTimer -= dt;
if (S.gazeTimer <= 0) {
    const dx = ctx.camera.position.x - ctx.entity.position.x;
    const dz = ctx.camera.position.z - ctx.entity.position.z;
    const dist = Math.sqrt(dx*dx + dz*dz);
    if (dist < 8) {
        S.gazeTarget = {x: Math.atan2(dz, 1)*0.12, y: Math.atan2(dx, 1)*0.18};
    } else {
        S.gazeTarget = {x: (Math.random()-0.5)*0.06, y: (Math.random()-0.5)*0.1};
    }
    S.gazeTimer = 1.2 + Math.random() * 3;
}
for (const eye of S.eyes) {
    eye.rotation.x += (S.gazeTarget.x - eye.rotation.x) * dt * 3.5;
    eye.rotation.y += (S.gazeTarget.y - eye.rotation.y) * dt * 3.5;
}

// --- Micro-facial: asymmetric brows, lip corners, cheek puff ---
S.microTimer -= dt;
if (S.microTimer <= 0) {
    S.browOffset = {
        l: (Math.random() - 0.5) * 0.005,
        r: (Math.random() - 0.5) * 0.005,
    };
    S.lipCornerOffset = (Math.random() - 0.5) * 0.002;
    S.cheekTarget = Math.random() < 0.15 ? (Math.random() * 0.04 + 0.01) : 0;
    S.microTimer = 2 + Math.random() * 5;
}
S.cheekPuff += (S.cheekTarget - S.cheekPuff) * dt * 2;

const KH = 1.3; // must match builder
b.headPivot.children.forEach(c => {
    if (c.name === 'brow_L') c.position.y = 0.15*KH + S.browOffset.l;
    if (c.name === 'brow_R') c.position.y = 0.15*KH + S.browOffset.r;
    if (c.name === 'lipCorner_L' || c.name === 'lipCorner_R')
        c.position.y = 0.059*KH + S.lipCornerOffset;
    // Cheek puff
    if (c.name === 'cheek_L' || c.name === 'cheek_R') {
        c.scale.z = 0.6 + S.cheekPuff;
    }
    // Blush intensity varies with mood
    if (c.name === 'blush_L' || c.name === 'blush_R') {
        const blushPulse = 0.3 + Math.sin(t*0.5+seed)*0.08;
        if (c.material) c.material.opacity = blushPulse;
    }
});

// --- Finger fidgeting ---
S.fingerTimer -= dt;
if (S.fingerTimer <= 0) {
    // Pick random fingers to move
    for (const arm of [b.leftArm, b.rightArm]) {
        if (!arm.fingers) continue;
        for (let fi = 0; fi < arm.fingers.length; fi++) {
            if (Math.random() < 0.3) {
                const f = arm.fingers[fi];
                const target = f.restCurl + (Math.random() - 0.3) * 0.4;
                if (!S.fingerTargets[fi]) S.fingerTargets[fi] = {};
                S.fingerTargets[fi][arm === b.leftArm ? 'l' : 'r'] = {
                    mcp: target,
                    pip: target * 0.8,
                    dip: target * 0.6,
                };
            }
        }
        // Thumb occasionally
        if (arm.thumb && Math.random() < 0.2) {
            const key = arm === b.leftArm ? 'thumbL' : 'thumbR';
            S.fingerTargets[key] = {
                mcp: 0.1 + (Math.random() - 0.5) * 0.25,
                ip: 0.08 + (Math.random() - 0.5) * 0.2,
            };
        }
    }
    S.fingerTimer = 0.8 + Math.random() * 2.5;
}

// Animate fingers toward targets
for (const arm of [b.leftArm, b.rightArm]) {
    if (!arm.fingers) continue;
    const side = arm === b.leftArm ? 'l' : 'r';
    for (let fi = 0; fi < arm.fingers.length; fi++) {
        const f = arm.fingers[fi];
        const tgt = S.fingerTargets[fi] && S.fingerTargets[fi][side];
        if (tgt) {
            f.mcpPivot.rotation.x += (tgt.mcp - f.mcpPivot.rotation.x) * dt * 4;
            f.pipPivot.rotation.x += (tgt.pip - f.pipPivot.rotation.x) * dt * 4;
            f.dipPivot.rotation.x += (tgt.dip - f.dipPivot.rotation.x) * dt * 4;
        }
    }
    if (arm.thumb) {
        const key = arm === b.leftArm ? 'thumbL' : 'thumbR';
        const tgt = S.fingerTargets[key];
        if (tgt) {
            arm.thumb.mcpPivot.rotation.x += (tgt.mcp - arm.thumb.mcpPivot.rotation.x) * dt * 4;
            arm.thumb.ipPivot.rotation.x += (tgt.ip - arm.thumb.ipPivot.rotation.x) * dt * 4;
        }
    }
}

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
# Wander V4 — walk with finger sway
# ---------------------------------------------------------------------------

WANDER_V4_SCRIPT = r"""
function walkCycle(S, t, speed) {
    const b = S.body;
    const phase = t * speed * 5;
    const sin = Math.sin(phase);
    const cos = Math.cos(phase);
    b.hips.position.y = 0.92 + Math.abs(sin) * 0.016;
    b.hips.rotation.z = sin * 0.016;
    b.hips.rotation.y = sin * 0.03;
    b.upperTorsoPivot.rotation.y = -sin * 0.035;
    b.upperTorsoPivot.rotation.z = -sin * 0.008;
    b.headPivot.rotation.z = -sin * 0.006;
    b.headPivot.rotation.y = sin * 0.02;
    // Arms: natural swing
    b.leftArm.shoulderPivot.rotation.x = -sin * 0.42;
    b.rightArm.shoulderPivot.rotation.x = sin * 0.42;
    b.leftArm.elbowPivot.rotation.x = -0.05 - Math.max(0, sin) * 0.3;
    b.rightArm.elbowPivot.rotation.x = -0.05 - Math.max(0, -sin) * 0.3;
    b.leftArm.wristPivot.rotation.y = sin * 0.1;
    b.rightArm.wristPivot.rotation.y = -sin * 0.1;
    // Finger sway during walk — fingers curl more on backswing
    for (const arm of [b.leftArm, b.rightArm]) {
        if (!arm.fingers) continue;
        const armSin = arm === b.leftArm ? -sin : sin;
        const curlAdd = Math.max(0, armSin) * 0.25; // curl on backswing
        for (const f of arm.fingers) {
            f.mcpPivot.rotation.x = f.restCurl + curlAdd;
            f.pipPivot.rotation.x = (f.restCurl + curlAdd) * 0.8;
            f.dipPivot.rotation.x = (f.restCurl + curlAdd) * 0.6;
        }
    }
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

// Blink with squash-stretch
S.blinkTimer -= ctx.deltaTime;
if (S.blinkTimer <= 0 && S.blinkPhase === 0) { S.blinkPhase = 1; S.blinkT = 0; }
if (S.blinkPhase > 0) {
    S.blinkT += ctx.deltaTime;
    if (S.blinkPhase === 1) {
        const p = Math.min(S.blinkT/0.06, 1);
        for (const eye of S.eyes) {
            const lid = eye.children.find(c=>c.name==='upperLid');
            if (lid) lid.rotation.x = p*0.9;
            eye.scale.set(1.0 + p*0.04, 1.0 - p*0.12, 1.0);
        }
        if (p >= 1) { S.blinkPhase = 2; S.blinkT = 0; }
    } else if (S.blinkPhase === 2) {
        if (S.blinkT > 0.03) { S.blinkPhase = 3; S.blinkT = 0; }
    } else if (S.blinkPhase === 3) {
        const p = Math.min(S.blinkT/0.08, 1);
        for (const eye of S.eyes) {
            const lid = eye.children.find(c=>c.name==='upperLid');
            if (lid) lid.rotation.x = (1-p)*0.9;
            eye.scale.set(1.0 + (1-p)*0.04, 1.0 - (1-p)*0.12, 1.0);
        }
        if (p >= 1) {
            S.blinkPhase = 0; S.blinkTimer = 1.5 + Math.random()*5;
            for (const eye of S.eyes) eye.scale.set(1,1,1);
        }
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
# Greet V4 — open-hand wave with finger spread
# ---------------------------------------------------------------------------

GREET_V4_SCRIPT = r"""
if (!ctx.state.built) return;
const dx = ctx.camera.position.x - ctx.entity.position.x;
const dz = ctx.camera.position.z - ctx.entity.position.z;
ctx.entity.rotation.y = Math.atan2(dx, dz);
const b = ctx.state.body;

// Raise right arm to wave
b.rightArm.shoulderPivot.rotation.x = -2.0;
b.rightArm.shoulderPivot.rotation.z = -0.5;
b.rightArm.elbowPivot.rotation.x = -0.8;

// Spread fingers open for wave
if (b.rightArm.fingers) {
    const spread = [-0.08, -0.04, 0, 0.04]; // slight fan
    for (let fi = 0; fi < b.rightArm.fingers.length; fi++) {
        const f = b.rightArm.fingers[fi];
        f.mcpPivot.rotation.x = -0.05; // straighten
        f.mcpPivot.rotation.z = spread[fi] || 0;
        f.pipPivot.rotation.x = -0.02;
        f.dipPivot.rotation.x = -0.01;
    }
    // Thumb out
    if (b.rightArm.thumb) {
        b.rightArm.thumb.cmcPivot.rotation.z = 0.8;
        b.rightArm.thumb.mcpPivot.rotation.x = -0.05;
    }
}

let waveT = 0;
const waveInterval = setInterval(() => {
    waveT += 0.05;
    b.rightArm.wristPivot.rotation.z = Math.sin(waveT * 8) * 0.4;
    // Fingers wiggle slightly
    if (b.rightArm.fingers) {
        for (let fi = 0; fi < b.rightArm.fingers.length; fi++) {
            const f = b.rightArm.fingers[fi];
            f.mcpPivot.rotation.x = -0.05 + Math.sin(waveT*10 + fi*0.8) * 0.06;
        }
    }
    if (waveT > 0.8) {
        clearInterval(waveInterval);
        b.rightArm.shoulderPivot.rotation.x = 0.05;
        b.rightArm.shoulderPivot.rotation.z = 0;
        b.rightArm.elbowPivot.rotation.x = -0.15;
        b.rightArm.wristPivot.rotation.z = 0;
        // Return fingers to rest
        if (b.rightArm.fingers) {
            for (const f of b.rightArm.fingers) {
                f.mcpPivot.rotation.x = f.restCurl;
                f.mcpPivot.rotation.z = 0;
                f.pipPivot.rotation.x = f.restCurl * 0.8;
                f.dipPivot.rotation.x = f.restCurl * 0.6;
            }
        }
    }
}, 50);
console.log(ctx.entity.userData.entityName + ': ' + (ctx.props.greeting || 'Hello!'));
"""
