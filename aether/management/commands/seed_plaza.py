"""Seed the Velour Plaza — avatar iteration 4.

Fixes from V4:
- Hair placement: shells centered at head center with larger radii,
  wider phi coverage so hair fully covers crown and sides of head.
  Dedicated scalp cap under hair prevents skin showing through.
- NPC player reactions: each NPC has a distinct behavioral response
  to the player (flee, approach, follow, notice, ignore, etc.)
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

# NPC behavior types — how each NPC responds to the player
REACTIONS = [
    'flee',        # runs away from player when close
    'approach',    # walks toward player when noticed, stops at conversation distance
    'follow',      # follows player at a distance like a companion
    'notice',      # turns head to watch player, body shifts slightly
    'ignore',      # completely ignores player, does own thing
    'shy',         # looks at player, but looks away when player looks back
    'curious',     # slowly edges closer, freezes if player turns toward them
    'wave',        # waves when player is nearby, then returns to idle
    'mimic',       # copies player's lateral movement with a delay
    'startle',     # jumps when player gets close, then recovers
]


class Command(BaseCommand):
    help = 'Create the Velour Plaza with V5 humanoids (fixed hair, player reactions).'

    def handle(self, *args, **options):
        World.objects.filter(slug='velour-plaza').delete()

        world = World.objects.create(
            title='Velour Plaza',
            slug='velour-plaza',
            description='Town plaza with V5 avatars: corrected hair, '
                        'varied player-reactive NPC behaviors.',
            skybox='hdri',
            hdri_asset='kloofendal_48d_partly_cloudy',
            sky_color='#90b8e0',
            ground_color='#706858',
            ground_size=50.0,
            ambient_light=0.5,
            fog_near=40.0,
            fog_far=110.0,
            fog_color='#c8d4e0',
            gravity=-9.81,
            spawn_x=0.0, spawn_y=1.6, spawn_z=10.0,
            soundscape='town',
            ambient_volume=0.18,
            published=True, featured=True,
        )

        # Motion library must be attached first (injects M utilities)
        motion_lib = _get_or_create_motion_lib()
        humanoid_v5 = _script('Humanoid Builder V5', 'start', HUMANOID_V5_SCRIPT,
            'V5 humanoid: fixed hair coverage, kawaii proportions, articulated hands.')
        react_v5 = _script('Plaza React V5', 'update', REACT_V5_SCRIPT,
            'Player-reactive idle: flee/approach/follow/notice/ignore/shy/curious/wave/mimic/startle.')
        wander_v5 = _script('Plaza Wander V5', 'update', WANDER_V5_SCRIPT,
            'Walk cycle with blink and finger sway.')

        entities = []
        E = lambda *a, **k: entities.append(_ent(world, *a, **k))

        # Plaza ground: stone pavement
        E('Pavement', 'box', '#807868', 0, -0.05, 0, sx=50, sy=0.1, sz=50, shadow=False)

        # Cobblestone texture (grid of slightly offset slabs)
        for z in range(-18, 19, 3):
            for x in range(-18, 19, 3):
                shade = '#' + hex(0x68 + hash((x, z)) % 24)[2:] * 3
                E(f'Cobble {x},{z}', 'box', '#787068', x+0.2, 0.005, z+0.1,
                  sx=2.7, sy=0.01, sz=2.7, shadow=False)

        # Central fountain
        E('FountainBase', 'cylinder', '#808888', 0, 0.3, 0, sx=2.5, sy=0.6, sz=2.5)
        E('FountainRim', 'torus', '#707878', 0, 0.6, 0, sx=2.5, sy=0.4, sz=2.5)
        E('FountainPillar', 'cylinder', '#909898', 0, 1.2, 0, sx=0.2, sy=1.4, sz=0.2)
        E('FountainTop', 'sphere', '#a0a8a8', 0, 1.95, 0, sx=0.4, sy=0.25, sz=0.4)

        # Trees around perimeter
        tree_pos = [(-12, -12), (12, -12), (-12, 12), (12, 12),
                    (-16, 0), (16, 0), (0, -16), (0, 16)]
        for i, (tx, tz) in enumerate(tree_pos):
            E(f'Trunk {i}', 'cylinder', '#5a4020', tx, 2.0, tz, sx=0.35, sy=4.0, sz=0.35)
            E(f'Canopy {i}', 'sphere', '#2a5818', tx, 5.0, tz, sx=3.0, sy=2.5, sz=3.0)

        # Benches around fountain
        for bx, bz, bry in [(4, 0, -90), (-4, 0, 90), (0, 4, 180), (0, -4, 0),
                             (3, 3, -135), (-3, 3, 135), (3, -3, -45), (-3, -3, 45)]:
            E(f'Bench {bx},{bz}', 'box', '#5c4828', bx, 0.3, bz,
              sx=1.8, sy=0.06, sz=0.45, ry=bry)
            # Legs
            for lx in [-0.7, 0.7]:
                E(f'BenchLeg {bx},{bz},{lx}', 'box', '#4a3818', bx+lx*0.7, 0.15, bz,
                  sx=0.06, sy=0.3, sz=0.35, ry=bry)

        # Lamp posts
        for lx, lz in [(-8, -8), (8, -8), (-8, 8), (8, 8)]:
            E(f'LampPost {lx},{lz}', 'cylinder', '#2a2a2a', lx, 2.0, lz,
              sx=0.06, sy=4.0, sz=0.06)
            E(f'Lamp {lx},{lz}', 'sphere', '#ffe880', lx, 4.1, lz,
              sx=0.15, sy=0.15, sz=0.15, shadow=False)

        # Planters with flowers
        planter_spots = [(-6, -2), (6, -2), (-6, 2), (6, 2)]
        flower_colors = ['#cc3040', '#e0a020', '#8040b0', '#e06080']
        for i, (px, pz) in enumerate(planter_spots):
            E(f'Planter {i}', 'box', '#504838', px, 0.2, pz, sx=0.8, sy=0.4, sz=0.8)
            for j in range(4):
                E(f'Flower {i}-{j}', 'sphere', flower_colors[(i+j) % 4],
                  px + (j-1.5)*0.15, 0.45, pz + (j % 2)*0.15 - 0.07,
                  sx=0.08, sy=0.08, sz=0.08, shadow=False)

        # --- NPCs ---
        NAMES = ['Arlo', 'Beatrix', 'Callum', 'Diana', 'Emory',
                 'Faye', 'Gideon', 'Hana', 'Idris', 'Jules']
        POSITIONS = [
            (6, -6, -90),     # flee
            (-5, 5, 45),      # approach
            (8, 3, 180),      # follow
            (-3, -3, 45),     # notice (on bench)
            (10, -10, 0),     # ignore (wanderer)
            (-6, -6, 90),     # shy
            (7, 7, -135),     # curious
            (-4, 0, 90),      # wave (on bench)
            (0, -8, 0),       # mimic
            (-8, 4, 0),       # startle
        ]

        npc_ents = []
        for i, (name, (px, pz, ry)) in enumerate(zip(NAMES, POSITIONS)):
            e = Entity(
                world=world, name=name, primitive='box',
                primitive_color='#000000',
                pos_x=px, pos_y=0, pos_z=pz, rot_y=ry,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            e._idx = i
            e._reaction = REACTIONS[i]
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
            # Motion library first (injects M utilities)
            attach(e, motion_lib, {})
            attach(e, humanoid_v5, {
                'skin': SKIN[i], 'shirt': SHIRT[i],
                'pants': PANTS[i], 'shoes': SHOES[i],
                'hair': HAIR[i], 'eyes': EYE_COLORS[i],
                'shoulderW': build[0], 'hipW': build[1], 'heightScale': build[2],
                'jawW': face[0], 'cheekFull': face[1], 'foreheadH': face[2],
            })
            attach(e, react_v5, {
                'reaction': e._reaction,
                'bounds': [-14, -14, 14, 14],
                'speed': 0.8 if e._reaction in ('flee', 'follow') else 0.5,
            })
            attach(e, wander_v5, {})

        EntityScript.objects.bulk_create(attachments)
        total = Entity.objects.filter(world=world).count()
        self.stdout.write(self.style.SUCCESS(
            f'Velour Plaza created: {total} entities, {len(npc_ents)} V5 NPCs '
            f'with reactions: {", ".join(REACTIONS)}.'
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


def _get_or_create_motion_lib():
    """Get the Motion Quality Library script (created by seed_ballet)."""
    s = Script.objects.filter(slug='motion-quality-library').first()
    if not s:
        # Import and run the ballet seed to create it, or create inline
        from aether.management.commands.seed_ballet import MOTION_LIB_SCRIPT
        s, _ = Script.objects.get_or_create(
            slug='motion-quality-library',
            defaults={
                'name': 'Motion Quality Library',
                'event': 'start',
                'code': MOTION_LIB_SCRIPT,
                'description': 'Injects easing, successive motion, and ballet utilities into ctx.state.',
            }
        )
    return s


# ---------------------------------------------------------------------------
# HUMANOID V5 — fixed hair coverage + kawaii + articulated fingers
# ---------------------------------------------------------------------------
#
# Hair fix rationale:
# Human hair grows from the scalp covering roughly the top 60-65% of the
# skull. A hairstyle's volume sits ABOVE and AROUND the skull — the hair
# mass should completely envelop the cranium from the hairline (above
# forehead, down to just above ears, back of head) upward. The center
# of the hair volume should be at or slightly above the center of the
# head sphere, with radius significantly larger than the head.
#
# V4 bug: hair shell centers were too high (0.15*KH vs head at 0.13*KH),
# so the lower edge of the hair shells didn't reach far enough down to
# cover the crown. The hair sat like a small cap on top rather than
# enveloping the skull.
#
# V5 fix: hair shell centers match head center (0.13*KH), radii are
# 15-25% larger than head radius, phi coverage extended to π*0.62-0.68
# so hair wraps well past the equator of the head. A solid scalp cap
# underneath prevents any skin showing through transparent shells.
# ---------------------------------------------------------------------------

HUMANOID_V5_SCRIPT = r"""
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

const KH = 1.3;    // kawaii head scale
const KE = 1.45;   // eye scale
const KN = 0.7;    // nose scale
const KM = 0.8;    // mouth scale

// Head geometry constants (used by hair)
const HEAD_R = 0.12 * KH;   // head radius = 0.156
const HEAD_CY = 0.13 * KH;  // head center Y = 0.169

const faceSkinC = new THREE.Color().copy(skinC).lerp(new THREE.Color('#ffaa99'), 0.04);
const handSkinC = new THREE.Color().copy(skinC).lerp(new THREE.Color('#ffe0d0'), 0.06);
const neckSkinC = new THREE.Color().copy(skinC).multiplyScalar(0.96);
const aoC = new THREE.Color().copy(skinC).multiplyScalar(0.8);

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
        roughness: 0.5, metalness: 0.0,
        transmission: 0.06, thickness: 1.0,
        attenuationColor: warm, attenuationDistance: 0.25,
        sheen: 0.5, sheenRoughness: 0.35,
        sheenColor: new THREE.Color().copy(c).lerp(new THREE.Color('#ffccaa'), 0.45),
        clearcoat: 0.04, clearcoatRoughness: 0.5, ior: 1.4,
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
        sheen: isShirt ? 0.22 : 0.08, sheenRoughness: 0.7,
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

const lowerTorso = part(new THREE.CylinderGeometry(0.15*HW, 0.16*HW, 0.2*HS, 12), shirtM);
lowerTorso.position.y = 0.1*HS;
hips.add(lowerTorso);

const upperTorsoPivot = pivot(0, 0.2*HS, 0);
hips.add(upperTorsoPivot);
const upperTorso = part(new THREE.CylinderGeometry(0.18*SW, 0.15*HW, 0.3*HS, 12), shirtM);
upperTorso.position.y = 0.15*HS;
upperTorsoPivot.add(upperTorso);

const collar = ns(part(new THREE.TorusGeometry(0.08, 0.01, 8, 16), shirtM));
collar.position.set(0, 0.3*HS, 0.02); collar.rotation.x = Math.PI/2;
upperTorsoPivot.add(collar);

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

for (let i = 0; i < 3; i++) {
    const btn = ns(part(
        new THREE.CylinderGeometry(0.006, 0.006, 0.003, 8),
        new THREE.MeshStandardMaterial({color: '#e8e0d0', roughness: 0.3, metalness: 0.05})
    ));
    btn.position.set(0, (0.06+i*0.08)*HS, 0.106);
    btn.rotation.x = Math.PI/2;
    upperTorsoPivot.add(btn);
}

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

// --- HEAD ---
const headPivot = pivot(0, 0.08, 0);
neckPivot.add(headPivot);

const head = part(new THREE.SphereGeometry(HEAD_R, 32, 32), faceSkinM);
head.position.y = HEAD_CY;
head.scale.set(1.0, 0.98, 0.96);
headPivot.add(head);

// Jaw (softer)
const jaw = ns(part(
    new THREE.SphereGeometry(0.1*KH, 24, 12, 0, Math.PI*2, Math.PI*0.55, Math.PI*0.45),
    faceSkinM
));
jaw.position.set(0, 0.05*KH, -0.02*KH);
jaw.scale.set(JW*0.95, 0.7, 0.55); // pulled back so eyes show through
headPivot.add(jaw);

// Chin
const chin = ns(part(
    new THREE.SphereGeometry(0.03*KH, 12, 8, 0, Math.PI*2, 0, Math.PI*0.5),
    faceSkinM
));
chin.position.set(0, 0.02*KH, 0.09*KH);
chin.scale.set(JW*0.8, 0.9, 0.6);
headPivot.add(chin);

// Forehead
const forehead = ns(part(
    new THREE.SphereGeometry(0.11*KH, 20, 10, 0, Math.PI*2, 0, Math.PI*0.35),
    faceSkinM
));
forehead.position.set(0, 0.2*KH*FH, -0.02*KH);
forehead.scale.set(1.0, 1.0, 0.45); // flattened so eyes aren't occluded
headPivot.add(forehead);

// Cheeks (kawaii: puffier — pulled back from eye plane)
for (const side of [-1, 1]) {
    const cheek = ns(part(new THREE.SphereGeometry(0.04*KH, 10, 8), faceSkinM));
    cheek.position.set(side*0.065*KH, 0.09*KH, 0.06*KH);
    cheek.scale.set(1.0*CF, 0.7, 0.4);
    cheek.name = 'cheek_' + (side < 0 ? 'L' : 'R');
    headPivot.add(cheek);
}

// Blush spots
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

// --- EYES (kawaii: big, low on face) ---
const eyeTargets = [];
for (const side of [-1, 1]) {
    const orbitShadow = ns(part(
        new THREE.CircleGeometry(0.022*KE, 12),
        new THREE.MeshStandardMaterial({color: aoC, roughness: 0.9, transparent: true, opacity: 0.3})
    ));
    orbitShadow.position.set(side*0.045*KH, 0.1*KH, 0.1*KH);
    headPivot.add(orbitShadow);

    const eyeGroup = pivot(side*0.045*KH, 0.105*KH, 0.1*KH);
    headPivot.add(eyeGroup);

    const eyeball = ns(part(
        new THREE.SphereGeometry(0.022*KE, 20, 20),
        new THREE.MeshPhysicalMaterial({
            color: '#f8f8f4', roughness: 0.03,
            clearcoat: 1.0, clearcoatRoughness: 0.02,
        })
    ));
    eyeball.position.z = 0.003;
    eyeGroup.add(eyeball);

    const cornea = ns(part(
        new THREE.SphereGeometry(0.017*KE, 24, 24, 0, Math.PI*2, 0, Math.PI*0.5),
        new THREE.MeshPhysicalMaterial({
            color: '#ffffff', transparent: true, opacity: 0.15,
            roughness: 0.0, clearcoat: 1.0, clearcoatRoughness: 0.0, ior: 1.376,
            sheen: 1.0, sheenRoughness: 0.0, sheenColor: new THREE.Color('#ffffff'),
        })
    ));
    cornea.position.set(0, 0, 0.018);
    cornea.rotation.x = -Math.PI/2;
    eyeGroup.add(cornea);

    // Iris canvas (kawaii: big iris, big catchlights)
    const ic = document.createElement('canvas');
    ic.width = 80; ic.height = 80;
    const ig = ic.getContext('2d');
    const cx = 40, cy = 40;
    ig.fillStyle = '#000000';
    ig.beginPath(); ig.arc(cx, cy, 38, 0, Math.PI*2); ig.fill();
    for (let r = 36; r > 0; r -= 1) {
        const t2 = r / 36;
        const c2 = new THREE.Color().copy(eyeC).lerp(new THREE.Color('#000'), (1-t2)*0.3);
        if (t2 > 0.5) c2.lerp(new THREE.Color('#fff'), (t2-0.5)*0.15);
        ig.fillStyle = '#'+c2.getHexString();
        ig.beginPath(); ig.arc(cx, cy, r, 0, Math.PI*2); ig.fill();
    }
    ig.strokeStyle = '#'+new THREE.Color().copy(eyeC).lerp(new THREE.Color('#fff'), 0.5).getHexString();
    ig.lineWidth = 2;
    ig.beginPath(); ig.arc(cx, cy, 20, 0, Math.PI*2); ig.stroke();
    ig.fillStyle = '#020202';
    ig.beginPath(); ig.arc(cx, cy, 13, 0, Math.PI*2); ig.fill();
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

    const lid = ns(part(
        new THREE.SphereGeometry(0.025*KE, 14, 8, 0, Math.PI*2, 0, Math.PI*0.4),
        faceSkinM
    ));
    lid.position.set(0, 0.006, 0.002);
    lid.name = 'upperLid';
    eyeGroup.add(lid);

    const lowerLid = ns(part(
        new THREE.SphereGeometry(0.023*KE, 10, 6, 0, Math.PI*2, Math.PI*0.65, Math.PI*0.35),
        faceSkinM
    ));
    lowerLid.position.set(0, -0.008, 0.002);
    lowerLid.name = 'lowerLid';
    eyeGroup.add(lowerLid);

    const lash = ns(part(
        new THREE.TorusGeometry(0.023*KE, 0.002, 4, 16, Math.PI),
        new THREE.MeshStandardMaterial({color: '#080808', roughness: 0.8})
    ));
    lash.position.set(0, 0.01, 0.012);
    lash.rotation.x = 0.25; lash.rotation.z = Math.PI;
    eyeGroup.add(lash);

    const lowerLash = ns(part(
        new THREE.TorusGeometry(0.02*KE, 0.001, 3, 12, Math.PI),
        new THREE.MeshStandardMaterial({color: '#181818', roughness: 0.85})
    ));
    lowerLash.position.set(0, -0.008, 0.012);
    lowerLash.rotation.x = -0.2;
    eyeGroup.add(lowerLash);

    eyeTargets.push(eyeGroup);
}

// Eyebrows
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

// --- Nose (small, kawaii) ---
const noseTip = ns(part(new THREE.SphereGeometry(0.013*KH*KN, 10, 8), faceSkinM));
noseTip.position.set(0, 0.085*KH, 0.13*KH);
headPivot.add(noseTip);
for (const side of [-1, 1]) {
    const nostril = ns(part(new THREE.SphereGeometry(0.003*KH, 5, 4), aoM));
    nostril.position.set(side*0.007*KH, 0.08*KH, 0.132*KH);
    headPivot.add(nostril);
}

// --- Mouth (small, kawaii) ---
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

const lipLine = ns(part(new THREE.BoxGeometry(0.025*KH*KM, 0.001, 0.002),
    new THREE.MeshStandardMaterial({color: '#2a1510', roughness: 0.9})
));
lipLine.position.set(0, 0.059*KH, 0.123*KH);
headPivot.add(lipLine);

for (const side of [-1, 1]) {
    const corner = ns(part(new THREE.SphereGeometry(0.003, 4, 4), aoM));
    corner.position.set(side*0.017*KH*KM, 0.059*KH, 0.118*KH);
    corner.name = 'lipCorner_' + (side < 0 ? 'L' : 'R');
    headPivot.add(corner);
}

// --- Ears ---
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

// ==================================================================
// HAIR — V5 FIX: properly enveloping the skull
// ==================================================================
// The key insight: human hair grows from the scalp and the resulting
// hairstyle volume must FULLY COVER the top of the head. The hair
// shells should be centered at the same Y as the head sphere (or
// slightly above), with radius larger than the head, and phi coverage
// wide enough to wrap past the temples/ears.
//
// Layering (inside to outside):
// 1. Scalp cap — solid hair-colored hemisphere, same center as head,
//    radius just barely larger than head. Prevents any skin showing.
// 2. Hair base — main volume, centered at head center, 18% larger
//    radius, phi 0 to 0.65π (covers well past equator).
// 3. Hair mid — semi-transparent volume layer for depth.
// 4. Hair outer — wispy transparent layer for softness.
// 5. Hair back — covers the back/nape area.
// 6. Fringe/bangs — individual pieces hanging over forehead.
// ==================================================================

const hairDarkC = new THREE.Color().copy(hairC).multiplyScalar(0.85);

// 1. Scalp cap — tight-fitting solid layer, no skin can peek through
const scalpCap = ns(part(
    new THREE.SphereGeometry(HEAD_R * 1.02, 24, 16, 0, Math.PI*2, 0, Math.PI*0.58),
    new THREE.MeshStandardMaterial({color: hairDarkC, roughness: 0.8})
));
scalpCap.position.y = HEAD_CY;
headPivot.add(scalpCap);

// 2. Hair base — main volume, same center as head, larger radius
const hairBaseR = HEAD_R * 1.18;
const hairBase = ns(part(
    new THREE.SphereGeometry(hairBaseR, 32, 20, 0, Math.PI*2, 0, Math.PI*0.65),
    hairM
));
hairBase.position.y = HEAD_CY;  // centered at head center
headPivot.add(hairBase);

// 3. Hair mid — volume layer
const hairMidR = HEAD_R * 1.24;
const hairMid = ns(part(
    new THREE.SphereGeometry(hairMidR, 24, 16, 0, Math.PI*2, 0, Math.PI*0.62),
    new THREE.MeshPhysicalMaterial({
        color: hairC, roughness: 0.5,
        sheen: 0.9, sheenRoughness: 0.25,
        sheenColor: new THREE.Color().copy(hairC).lerp(new THREE.Color('#fff'), 0.3),
        transparent: true, opacity: 0.55,
    })
));
hairMid.position.y = HEAD_CY + 0.005;
headPivot.add(hairMid);

// 4. Hair outer — wispy layer
const hairOuterR = HEAD_R * 1.30;
const hairOuter = ns(part(
    new THREE.SphereGeometry(hairOuterR, 20, 12, 0, Math.PI*2, 0, Math.PI*0.58),
    new THREE.MeshPhysicalMaterial({
        color: new THREE.Color().copy(hairC).lerp(new THREE.Color('#fff'), 0.08),
        roughness: 0.55, transparent: true, opacity: 0.28,
        sheen: 0.7, sheenRoughness: 0.3,
        sheenColor: new THREE.Color().copy(hairC).lerp(new THREE.Color('#fff'), 0.4),
    })
));
hairOuter.position.y = HEAD_CY + 0.008;
headPivot.add(hairOuter);

// 5. Hair back — covers nape
const hairBack = ns(part(
    new THREE.SphereGeometry(HEAD_R * 1.1, 16, 12,
        0, Math.PI*2, Math.PI*0.25, Math.PI*0.45),
    hairM
));
hairBack.position.set(0, HEAD_CY - 0.02, -HEAD_R * 0.25);
headPivot.add(hairBack);

// 6. Fringe/bangs — individual pieces over forehead
// Positioned at hairline (above forehead, in front of hair base)
const hairlineY = HEAD_CY + HEAD_R * 0.55;  // about 60% up the head
const hairlineZ = HEAD_R * 0.7;  // forward position
for (let i = -3; i <= 3; i++) {
    const bangW = 0.02 * KH + Math.random() * 0.008;
    const bang = ns(part(
        new THREE.SphereGeometry(bangW, 8, 6, 0, Math.PI*2, 0, Math.PI*0.6),
        hairM
    ));
    bang.position.set(
        i * 0.022 * KH,
        hairlineY - Math.abs(i) * 0.006,  // slight arch
        hairlineZ
    );
    bang.rotation.x = 0.5 + Math.random() * 0.15;  // tilt forward/down
    bang.rotation.z = (Math.random() - 0.5) * 0.1;
    headPivot.add(bang);
}

// Side hair pieces (cover temples, transition to ears)
for (const side of [-1, 1]) {
    const sideHair = ns(part(
        new THREE.SphereGeometry(HEAD_R * 0.4, 10, 8,
            0, Math.PI*2, 0, Math.PI*0.6),
        hairM
    ));
    sideHair.position.set(
        side * HEAD_R * 0.85,
        HEAD_CY + HEAD_R * 0.15,
        HEAD_R * 0.15
    );
    sideHair.rotation.z = side * 0.3;
    sideHair.rotation.x = 0.2;
    headPivot.add(sideHair);
}

// === ARMS with ARTICULATED HANDS ===
function buildArm(side) {
    const shoulderPivot = pivot(side*0.22*SW, 0.27*HS, 0);
    upperTorsoPivot.add(shoulderPivot);

    const deltoid = ns(part(
        new THREE.SphereGeometry(0.038, 10, 8, 0, Math.PI*2, 0, Math.PI*0.5), shirtM
    ));
    deltoid.position.set(0, 0.01, 0); deltoid.rotation.x = -0.3;
    shoulderPivot.add(deltoid);

    const upperArm = part(new THREE.CylinderGeometry(0.035, 0.03, 0.24*HS, 12), shirtM);
    upperArm.position.y = -0.12*HS;
    shoulderPivot.add(upperArm);

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

    // Articulated hand
    const palm = part(new THREE.BoxGeometry(0.044, 0.03, 0.026), handSkinM);
    palm.position.y = -0.015;
    wristPivot.add(palm);

    const fingerData = [
        [-0.016, 0.013, 0.010, 0.009, 0.15],
        [-0.006, 0.015, 0.012, 0.009, 0.12],
        [0.005,  0.014, 0.011, 0.009, 0.14],
        [0.015,  0.012, 0.009, 0.007, 0.18],
    ];
    const fRad = 0.0035;
    const nailM = new THREE.MeshPhysicalMaterial({color:'#f0d8d0', roughness:0.12, clearcoat:0.8});
    const fingers = [];

    for (let fi = 0; fi < fingerData.length; fi++) {
        const [fx, pLen, mLen, dLen, curl] = fingerData[fi];

        const mcpPivot = pivot(fx, -0.03, 0);
        wristPivot.add(mcpPivot);
        mcpPivot.rotation.x = curl;

        const knuckle = ns(part(new THREE.SphereGeometry(fRad*1.2, 6, 4), handSkinM));
        knuckle.position.set(0, 0, 0.005);
        mcpPivot.add(knuckle);

        const proximal = ns(part(
            new THREE.CylinderGeometry(fRad, fRad*0.95, pLen, 6), handSkinM
        ));
        proximal.position.y = -pLen/2;
        mcpPivot.add(proximal);

        const pipPivot = pivot(0, -pLen, 0);
        mcpPivot.add(pipPivot);
        pipPivot.rotation.x = curl * 0.8;

        const pipBump = ns(part(new THREE.SphereGeometry(fRad*1.05, 5, 3), handSkinM));
        pipPivot.add(pipBump);

        const middle = ns(part(
            new THREE.CylinderGeometry(fRad*0.95, fRad*0.9, mLen, 6), handSkinM
        ));
        middle.position.y = -mLen/2;
        pipPivot.add(middle);

        const dipPivot = pivot(0, -mLen, 0);
        pipPivot.add(dipPivot);
        dipPivot.rotation.x = curl * 0.6;

        const distal = ns(part(
            new THREE.CylinderGeometry(fRad*0.9, fRad*0.7, dLen, 6), handSkinM
        ));
        distal.position.y = -dLen/2;
        dipPivot.add(distal);

        const nail = ns(part(new THREE.BoxGeometry(fRad*2, 0.002, dLen*0.6), nailM));
        nail.position.set(0, 0.002, -dLen/2);
        nail.rotation.x = -0.1;
        dipPivot.add(nail);

        fingers.push({mcpPivot, pipPivot, dipPivot, restCurl: curl});
    }

    // Thumb
    const thumbCMC = pivot(side*0.023, -0.015, 0.008);
    wristPivot.add(thumbCMC);
    thumbCMC.rotation.z = side*0.55;
    thumbCMC.rotation.x = 0.15;

    const thumbMeta = ns(part(
        new THREE.CylinderGeometry(0.005, 0.0045, 0.016, 6), handSkinM
    ));
    thumbMeta.position.y = -0.008;
    thumbCMC.add(thumbMeta);

    const thumbMCP = pivot(0, -0.016, 0);
    thumbCMC.add(thumbMCP);
    thumbMCP.rotation.x = 0.1;

    const thumbProx = ns(part(
        new THREE.CylinderGeometry(0.0048, 0.004, 0.014, 6), handSkinM
    ));
    thumbProx.position.y = -0.007;
    thumbMCP.add(thumbProx);

    const thumbIP = pivot(0, -0.014, 0);
    thumbMCP.add(thumbIP);
    thumbIP.rotation.x = 0.08;

    const thumbDistal = ns(part(
        new THREE.CylinderGeometry(0.004, 0.003, 0.011, 6), handSkinM
    ));
    thumbDistal.position.y = -0.0055;
    thumbIP.add(thumbDistal);

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
# REACT V5 — player-reactive NPC behaviors
# ---------------------------------------------------------------------------
# Each NPC has a 'reaction' prop that determines how it responds to
# the player's presence and movement. All reactions share common
# subsystems (blink, breathing, micro-expression) but diverge in
# their locomotion and attention behavior.
# ---------------------------------------------------------------------------

REACT_V5_SCRIPT = r"""
if (!ctx.state.built) return;
const S = ctx.state;
const b = S.body;
const P = ctx.props;
// Use motion library if available (ballet-quality movement), fallback to basic math
const M = S.M || null;

if (!S.react_init) {
    S.react_init = true;
    S.seed = ctx.entity.position.x * 7.3 + ctx.entity.position.z * 13.7;
    S.reaction = P.reaction || 'ignore';
    S.speed = P.speed || 0.5;
    S.bounds = P.bounds ? {minX:P.bounds[0], minZ:P.bounds[1], maxX:P.bounds[2], maxZ:P.bounds[3]}
                        : {minX:-14, minZ:-14, maxX:14, maxZ:14};
    // Follow-through state (ballet-quality: values overshoot then settle)
    S.ft = {
        headY: {value:0, velocity:0}, headX: {value:0, velocity:0},
        headZ: {value:0, velocity:0}, hipZ: {value:0, velocity:0},
        spineY: {value:0, velocity:0},
        lShX: {value:0.05, velocity:0}, rShX: {value:0.05, velocity:0},
        lElb: {value:-0.15, velocity:0}, rElb: {value:-0.15, velocity:0},
    };
    // Successive motion chains for arms (shoulder → elbow → wrist)
    S.lArmChain = [{current:0,target:0},{current:0,target:0},{current:0,target:0}];
    S.rArmChain = [{current:0,target:0},{current:0,target:0},{current:0,target:0}];
    // Blink
    S.blinkTimer = 2 + Math.random() * 4;
    S.blinkPhase = 0;
    S.blinkT = 0;
    // Gaze
    S.gazeTarget = {x: 0, y: 0};
    S.gazeTimer = 1;
    // Micro
    S.microTimer = 0;
    S.browOffset = {l: 0, r: 0};
    S.lipCornerOffset = 0;
    S.cheekPuff = 0;
    S.cheekTarget = 0;
    // Finger fidget
    S.fingerTimer = 0.5;
    S.fingerTargets = {};
    // Movement
    S.moveTarget = null;
    S.walking = false;
    S.walkT = 0;
    S.restPos = {x: ctx.entity.position.x, z: ctx.entity.position.z};
    S.restRot = ctx.entity.rotation.y;
    // Reaction-specific state
    S.waveTimer = 0;
    S.waved = false;
    S.startleT = 0;
    S.startled = false;
    S.shyLooking = false;
    S.curDist = 999;
    S.prevPlayerX = 0;
    S.prevPlayerZ = 0;
    S.mimicDelay = [];
}

const t = ctx.elapsed;
const dt = ctx.deltaTime;
const seed = S.seed;
const KH = 1.3;

// === Player distance + direction ===
const px = ctx.camera.position.x;
const pz = ctx.camera.position.z;
const dx = px - ctx.entity.position.x;
const dz = pz - ctx.entity.position.z;
const dist = Math.sqrt(dx*dx + dz*dz);
S.curDist = dist;
const angleToPlayer = Math.atan2(dx, dz);
// Is player facing this NPC? (dot product of player forward and NPC direction)
const pFwd = new THREE.Vector3(0, 0, -1).applyQuaternion(ctx.camera.quaternion);
const toNPC = new THREE.Vector3(-dx, 0, -dz).normalize();
const playerFacingMe = pFwd.dot(toNPC) > 0.5;

// === Breathing (ballet-quality when motion lib available) ===
const br = M ? M.breath(t, seed) : {value: Math.sin(t * 1.35 + seed), depth: 1};
const breathe = br.value;
b.upperTorsoPivot.rotation.x = breathe * 0.012;
const bScale = 1.0 + breathe * 0.009;
b.upperTorsoPivot.scale.set(1.0, bScale, 1.0 + breathe * 0.006);

// === Blink with squash-stretch (always) ===
S.blinkTimer -= dt;
if (S.blinkTimer <= 0 && S.blinkPhase === 0) { S.blinkPhase = 1; S.blinkT = 0; }
if (S.blinkPhase > 0) {
    S.blinkT += dt;
    if (S.blinkPhase === 1) {
        const p = Math.min(S.blinkT / 0.06, 1);
        for (const eye of S.eyes) {
            const lid = eye.children.find(c => c.name === 'upperLid');
            if (lid) lid.rotation.x = p * 0.9;
            eye.scale.set(1.0 + p*0.04, 1.0 - p*0.12, 1.0);
        }
        if (p >= 1) { S.blinkPhase = 2; S.blinkT = 0; }
    } else if (S.blinkPhase === 2) {
        if (S.blinkT > 0.03) { S.blinkPhase = 3; S.blinkT = 0; }
    } else if (S.blinkPhase === 3) {
        const p = Math.min(S.blinkT / 0.08, 1);
        for (const eye of S.eyes) {
            const lid = eye.children.find(c => c.name === 'upperLid');
            if (lid) lid.rotation.x = (1 - p) * 0.9;
            eye.scale.set(1.0 + (1-p)*0.04, 1.0 - (1-p)*0.12, 1.0);
        }
        if (p >= 1) {
            S.blinkPhase = 0;
            S.blinkTimer = 1.5 + Math.random() * 5;
            for (const eye of S.eyes) eye.scale.set(1, 1, 1);
        }
    }
}

// === Micro-expressions (always) ===
S.microTimer -= dt;
if (S.microTimer <= 0) {
    S.browOffset = {l: (Math.random()-0.5)*0.005, r: (Math.random()-0.5)*0.005};
    S.lipCornerOffset = (Math.random()-0.5)*0.002;
    S.cheekTarget = Math.random() < 0.15 ? Math.random()*0.04 : 0;
    S.microTimer = 2 + Math.random()*5;
}
S.cheekPuff += (S.cheekTarget - S.cheekPuff) * dt * 2;
b.headPivot.children.forEach(c => {
    if (c.name === 'brow_L') c.position.y = 0.15*KH + S.browOffset.l;
    if (c.name === 'brow_R') c.position.y = 0.15*KH + S.browOffset.r;
    if (c.name === 'lipCorner_L' || c.name === 'lipCorner_R')
        c.position.y = 0.059*KH + S.lipCornerOffset;
    if (c.name === 'cheek_L' || c.name === 'cheek_R')
        c.scale.z = 0.6 + S.cheekPuff;
    if (c.name === 'blush_L' || c.name === 'blush_R') {
        if (c.material) c.material.opacity = 0.3 + Math.sin(t*0.5+seed)*0.08;
    }
});

// === Finger fidget (always) ===
S.fingerTimer -= dt;
if (S.fingerTimer <= 0) {
    for (const arm of [b.leftArm, b.rightArm]) {
        if (!arm.fingers) continue;
        const side = arm === b.leftArm ? 'l' : 'r';
        for (let fi = 0; fi < arm.fingers.length; fi++) {
            if (Math.random() < 0.3) {
                const f = arm.fingers[fi];
                const tgt = f.restCurl + (Math.random()-0.3)*0.4;
                if (!S.fingerTargets[fi]) S.fingerTargets[fi] = {};
                S.fingerTargets[fi][side] = {mcp: tgt, pip: tgt*0.8, dip: tgt*0.6};
            }
        }
    }
    S.fingerTimer = 0.8 + Math.random()*2.5;
}
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
}

// === Walk cycle helper ===
function walkCycle(walkT, spd) {
    const phase = walkT * spd * 5;
    const sin = Math.sin(phase);
    b.hips.position.y = 0.92 + Math.abs(sin) * 0.016;
    b.hips.rotation.z = sin * 0.016;
    b.hips.rotation.y = sin * 0.03;
    b.upperTorsoPivot.rotation.y = -sin * 0.035;
    b.leftArm.shoulderPivot.rotation.x = -sin * 0.42;
    b.rightArm.shoulderPivot.rotation.x = sin * 0.42;
    b.leftArm.elbowPivot.rotation.x = -0.05 - Math.max(0, sin) * 0.3;
    b.rightArm.elbowPivot.rotation.x = -0.05 - Math.max(0, -sin) * 0.3;
    b.leftLeg.hipPivot.rotation.x = sin * 0.38;
    b.rightLeg.hipPivot.rotation.x = -sin * 0.38;
    b.leftLeg.kneePivot.rotation.x = Math.max(0, -sin) * 0.5;
    b.rightLeg.kneePivot.rotation.x = Math.max(0, sin) * 0.5;
}

function idlePose() {
    b.hips.position.y = 0.92;
    b.hips.rotation.z = Math.sin(t*0.14+seed)*0.013;
    b.leftArm.shoulderPivot.rotation.x = 0.05 + breathe*0.01;
    b.rightArm.shoulderPivot.rotation.x = 0.05 + breathe*0.01;
    b.leftArm.elbowPivot.rotation.x = -0.15;
    b.rightArm.elbowPivot.rotation.x = -0.15;
    b.leftLeg.hipPivot.rotation.x = 0;
    b.rightLeg.hipPivot.rotation.x = 0;
    b.leftLeg.kneePivot.rotation.x = 0;
    b.rightLeg.kneePivot.rotation.x = 0;
}

function moveToward(tx, tz, spd) {
    const mdx = tx - ctx.entity.position.x;
    const mdz = tz - ctx.entity.position.z;
    const mdist = Math.sqrt(mdx*mdx + mdz*mdz);
    if (mdist < 0.3) return false;
    const step = Math.min(spd * dt, mdist);
    ctx.entity.position.x += (mdx/mdist)*step;
    ctx.entity.position.z += (mdz/mdist)*step;
    // Smooth turn
    const tr = Math.atan2(mdx, mdz);
    let diff = tr - ctx.entity.rotation.y;
    while (diff > Math.PI) diff -= Math.PI*2;
    while (diff < -Math.PI) diff += Math.PI*2;
    ctx.entity.rotation.y += diff * Math.min(1, dt * 5);
    S.walkT += dt;
    walkCycle(S.walkT, spd);
    return true;
}

function clampBounds() {
    const bn = S.bounds;
    ctx.entity.position.x = Math.max(bn.minX, Math.min(bn.maxX, ctx.entity.position.x));
    ctx.entity.position.z = Math.max(bn.minZ, Math.min(bn.maxZ, ctx.entity.position.z));
}

// === REACTION BEHAVIORS ===
const R = S.reaction;

if (R === 'flee') {
    // Run away from player when within 8 units
    if (dist < 8) {
        const fleeX = ctx.entity.position.x - dx/dist * 5;
        const fleeZ = ctx.entity.position.z - dz/dist * 5;
        moveToward(fleeX, fleeZ, S.speed * 1.5);
        clampBounds();
        // Panicked look back
        b.headPivot.rotation.y = Math.sin(t*3)*0.3;
    } else {
        idlePose();
        // Nervous head movement
        b.headPivot.rotation.y = Math.sin(t*0.4+seed)*0.25;
        b.headPivot.rotation.x = Math.sin(t*0.2)*0.03;
    }
    // Gaze: always watching player anxiously
    S.gazeTarget = {x: Math.atan2(dz,1)*0.15, y: Math.atan2(dx,1)*0.2};

} else if (R === 'approach') {
    // Walk toward player when noticed (within 12 units), stop at 2.5 units
    if (dist < 12 && dist > 2.5) {
        moveToward(px, pz, S.speed);
        clampBounds();
    } else if (dist <= 2.5) {
        idlePose();
        // Face player
        let diff = angleToPlayer - ctx.entity.rotation.y;
        while (diff > Math.PI) diff -= Math.PI*2;
        while (diff < -Math.PI) diff += Math.PI*2;
        ctx.entity.rotation.y += diff * dt * 3;
        // Friendly head tilt
        b.headPivot.rotation.z = Math.sin(t*0.3)*0.08;
    } else {
        idlePose();
        b.headPivot.rotation.y = Math.sin(t*0.25+seed)*0.3;
    }
    S.gazeTarget = dist < 12 ? {x: Math.atan2(dz,1)*0.12, y: Math.atan2(dx,1)*0.18}
                              : {x: (Math.random()-0.5)*0.06, y: (Math.random()-0.5)*0.1};

} else if (R === 'follow') {
    // Follow player at 4-unit distance, like a companion
    if (dist > 5) {
        moveToward(px, pz, S.speed * 1.2);
        clampBounds();
    } else if (dist < 3) {
        // Too close, back up slightly
        const backX = ctx.entity.position.x - dx/dist * 0.5;
        const backZ = ctx.entity.position.z - dz/dist * 0.5;
        moveToward(backX, backZ, S.speed * 0.5);
        clampBounds();
    } else {
        idlePose();
        // Face player direction of travel
        let diff = angleToPlayer - ctx.entity.rotation.y;
        while (diff > Math.PI) diff -= Math.PI*2;
        while (diff < -Math.PI) diff += Math.PI*2;
        ctx.entity.rotation.y += diff * dt * 2;
    }
    S.gazeTarget = {x: Math.atan2(dz,1)*0.1, y: Math.atan2(dx,1)*0.15};

} else if (R === 'notice') {
    // Subtle awareness: turn head toward player, body shifts slightly
    idlePose();
    if (dist < 10) {
        // Head turns to track player
        const headAngle = angleToPlayer - ctx.entity.rotation.y;
        let hDiff = headAngle;
        while (hDiff > Math.PI) hDiff -= Math.PI*2;
        while (hDiff < -Math.PI) hDiff += Math.PI*2;
        const headTurn = Math.max(-0.7, Math.min(0.7, hDiff));
        b.headPivot.rotation.y += (headTurn - b.headPivot.rotation.y) * dt * 2.5;
        // Slight body shift toward player
        b.upperTorsoPivot.rotation.y = headTurn * 0.15;
        b.hips.rotation.y = headTurn * 0.05;
        // Stronger gaze
        S.gazeTarget = {x: Math.atan2(dz,1)*0.15, y: Math.atan2(dx,1)*0.2};
    } else {
        b.headPivot.rotation.y = Math.sin(t*0.2+seed)*0.25;
        b.headPivot.rotation.x = Math.sin(t*0.15)*0.03;
        S.gazeTarget = {x: (Math.random()-0.5)*0.06, y: (Math.random()-0.5)*0.1};
    }

} else if (R === 'ignore') {
    // Completely ignores player, does own wandering
    if (!S.ignoreTarget || S.ignoreWait > 0) {
        S.ignoreWait = (S.ignoreWait || 0) - dt;
        idlePose();
        b.headPivot.rotation.y = Math.sin(t*0.3+seed)*0.35;
        if (S.ignoreWait <= 0) {
            const bn = S.bounds;
            S.ignoreTarget = {
                x: bn.minX + Math.random()*(bn.maxX-bn.minX),
                z: bn.minZ + Math.random()*(bn.maxZ-bn.minZ),
            };
        }
    } else {
        const arrived = !moveToward(S.ignoreTarget.x, S.ignoreTarget.z, S.speed * 0.6);
        if (arrived) {
            S.ignoreTarget = null;
            S.ignoreWait = 3 + Math.random() * 5;
        }
    }
    // Never looks at player
    S.gazeTarget = {x: (Math.random()-0.5)*0.08, y: (Math.random()-0.5)*0.12};

} else if (R === 'shy') {
    // Looks at player, but averts gaze when player looks back
    idlePose();
    if (dist < 10) {
        if (playerFacingMe) {
            // Player is looking at me — look away!
            S.shyLooking = false;
            b.headPivot.rotation.y += (-angleToPlayer*0.3 - b.headPivot.rotation.y) * dt * 4;
            b.headPivot.rotation.x = 0.1; // look down
            // Blush intensifies
            b.headPivot.children.forEach(c => {
                if ((c.name === 'blush_L' || c.name === 'blush_R') && c.material)
                    c.material.opacity = 0.55;
            });
            S.gazeTarget = {x: 0.1, y: (Math.random()-0.5)*0.1};
        } else {
            // Player not looking — peek at them
            S.shyLooking = true;
            const headAngle = angleToPlayer - ctx.entity.rotation.y;
            let hDiff = headAngle;
            while (hDiff > Math.PI) hDiff -= Math.PI*2;
            while (hDiff < -Math.PI) hDiff += Math.PI*2;
            b.headPivot.rotation.y += (Math.max(-0.5, Math.min(0.5, hDiff)) - b.headPivot.rotation.y) * dt * 2;
            b.headPivot.rotation.x = 0;
            S.gazeTarget = {x: Math.atan2(dz,1)*0.12, y: Math.atan2(dx,1)*0.18};
        }
    } else {
        b.headPivot.rotation.y = Math.sin(t*0.25+seed)*0.3;
        S.gazeTarget = {x: (Math.random()-0.5)*0.06, y: (Math.random()-0.5)*0.1};
    }

} else if (R === 'curious') {
    // Slowly edges closer, freezes if player turns toward them
    if (dist < 12 && dist > 2) {
        if (playerFacingMe) {
            // Freeze! Stand perfectly still
            idlePose();
            // Wide eyes (slightly raised brows)
            S.browOffset = {l: 0.004, r: 0.004};
        } else {
            // Sneak closer
            moveToward(px, pz, S.speed * 0.3);
            clampBounds();
        }
    } else {
        idlePose();
    }
    S.gazeTarget = dist < 12 ? {x: Math.atan2(dz,1)*0.15, y: Math.atan2(dx,1)*0.2}
                              : {x: (Math.random()-0.5)*0.06, y: (Math.random()-0.5)*0.1};

} else if (R === 'wave') {
    // Waves when player is within 6 units, then returns to idle
    idlePose();
    if (dist < 6 && !S.waved) {
        S.waveTimer += dt;
        // Face player
        let diff = angleToPlayer - ctx.entity.rotation.y;
        while (diff > Math.PI) diff -= Math.PI*2;
        while (diff < -Math.PI) diff += Math.PI*2;
        ctx.entity.rotation.y += diff * dt * 4;
        // Wave animation
        if (S.waveTimer < 1.2) {
            b.rightArm.shoulderPivot.rotation.x = -2.0;
            b.rightArm.shoulderPivot.rotation.z = -0.5;
            b.rightArm.elbowPivot.rotation.x = -0.8;
            b.rightArm.wristPivot.rotation.z = Math.sin(S.waveTimer * 10) * 0.4;
            // Spread fingers
            if (b.rightArm.fingers) {
                for (const f of b.rightArm.fingers) {
                    f.mcpPivot.rotation.x = -0.05;
                }
            }
        } else {
            S.waved = true;
            S.waveTimer = 0;
        }
    } else if (S.waved && dist > 10) {
        S.waved = false; // reset when player leaves
    } else {
        b.headPivot.rotation.y = Math.sin(t*0.25+seed)*0.3;
    }
    S.gazeTarget = dist < 8 ? {x: Math.atan2(dz,1)*0.12, y: Math.atan2(dx,1)*0.18}
                             : {x: (Math.random()-0.5)*0.06, y: (Math.random()-0.5)*0.1};

} else if (R === 'mimic') {
    // Copies player's lateral movement with a 0.5s delay
    idlePose();
    // Record player positions
    S.mimicDelay.push({x: px, z: pz, t: t});
    // Remove old entries
    while (S.mimicDelay.length > 0 && S.mimicDelay[0].t < t - 0.5) S.mimicDelay.shift();
    if (dist < 10 && S.mimicDelay.length > 1) {
        const delayed = S.mimicDelay[0];
        const ddx = delayed.x - S.prevPlayerX;
        const ddz = delayed.z - S.prevPlayerZ;
        // Mirror the movement
        const targetX = S.restPos.x + (delayed.x - S.restPos.x) * 0.3;
        const targetZ = S.restPos.z + (delayed.z - S.restPos.z) * 0.3;
        const mDist = Math.sqrt((targetX-ctx.entity.position.x)**2 + (targetZ-ctx.entity.position.z)**2);
        if (mDist > 0.1) {
            moveToward(targetX, targetZ, S.speed);
            clampBounds();
        }
    }
    S.prevPlayerX = px;
    S.prevPlayerZ = pz;
    S.gazeTarget = dist < 10 ? {x: Math.atan2(dz,1)*0.12, y: Math.atan2(dx,1)*0.18}
                              : {x: (Math.random()-0.5)*0.06, y: (Math.random()-0.5)*0.1};

} else if (R === 'startle') {
    // Jumps when player gets close, then recovers
    idlePose();
    if (dist < 4 && !S.startled) {
        S.startled = true;
        S.startleT = 0;
    }
    if (S.startled) {
        S.startleT += dt;
        if (S.startleT < 0.15) {
            // Jump back
            b.hips.position.y = 0.92 + (0.15 - S.startleT) * 1.5;
            // Arms fly up
            b.leftArm.shoulderPivot.rotation.x = -1.5;
            b.rightArm.shoulderPivot.rotation.x = -1.5;
            b.leftArm.elbowPivot.rotation.x = -0.8;
            b.rightArm.elbowPivot.rotation.x = -0.8;
            // Wide eyes (brows up)
            S.browOffset = {l: 0.008, r: 0.008};
            // Lean back
            const backStep = dt * 2;
            ctx.entity.position.x -= dx/dist * backStep;
            ctx.entity.position.z -= dz/dist * backStep;
        } else if (S.startleT < 0.8) {
            // Recovery — hand on chest
            b.leftArm.shoulderPivot.rotation.x = -0.6;
            b.leftArm.elbowPivot.rotation.x = -1.2;
            b.rightArm.shoulderPivot.rotation.x = 0.05;
            b.rightArm.elbowPivot.rotation.x = -0.15;
            b.hips.position.y = 0.92;
        } else {
            S.startled = false;
        }
    }
    if (dist > 8) S.startled = false; // reset when player leaves
    b.headPivot.rotation.y = Math.sin(t*0.3+seed)*0.25;
    S.gazeTarget = dist < 6 ? {x: Math.atan2(dz,1)*0.15, y: Math.atan2(dx,1)*0.2}
                             : {x: (Math.random()-0.5)*0.06, y: (Math.random()-0.5)*0.1};
}

// === Apply gaze with follow-through ===
for (const eye of S.eyes) {
    eye.rotation.x += (S.gazeTarget.x - eye.rotation.x) * dt * 3.5;
    eye.rotation.y += (S.gazeTarget.y - eye.rotation.y) * dt * 3.5;
}

// ============================================================
// BALLET-QUALITY POST-PROCESSING
// ============================================================
// The reaction behaviors above set skeleton values directly.
// This pass applies the motion library's follow-through and
// successive motion to smooth out those assignments, adding:
// - Organic lag (body parts don't snap instantly)
// - Overshoot and settle (like a spring, not a robot)
// - Successive motion (movement flows core → extremities)
// - Épaulement (shoulder-hip counter-rotation, head inclination)
// - Variable breathing depth
// ============================================================
if (M && S.ft) {
    const ftP = {stiffness: 10, damping: 4}; // NPC: slightly snappier than ballet

    // Read what the reaction behaviors set as raw targets
    const rawHeadY = b.headPivot.rotation.y;
    const rawHeadX = b.headPivot.rotation.x;
    const rawHipZ = b.hips.rotation.z;
    const rawLShX = b.leftArm.shoulderPivot.rotation.x;
    const rawRShX = b.rightArm.shoulderPivot.rotation.x;
    const rawLElb = b.leftArm.elbowPivot.rotation.x;
    const rawRElb = b.rightArm.elbowPivot.rotation.x;

    // Apply follow-through (values overshoot then settle)
    M.followThrough(S.ft.headY, rawHeadY, dt, ftP);
    M.followThrough(S.ft.headX, rawHeadX, dt, ftP);
    M.followThrough(S.ft.hipZ, rawHipZ, dt, ftP);
    M.followThrough(S.ft.lShX, rawLShX, dt, ftP);
    M.followThrough(S.ft.rShX, rawRShX, dt, ftP);
    M.followThrough(S.ft.lElb, rawLElb, dt, ftP);
    M.followThrough(S.ft.rElb, rawRElb, dt, ftP);

    // Write back smoothed values
    b.headPivot.rotation.y = S.ft.headY.value;
    b.headPivot.rotation.x = S.ft.headX.value;
    b.hips.rotation.z = S.ft.hipZ.value;
    b.leftArm.shoulderPivot.rotation.x = S.ft.lShX.value;
    b.rightArm.shoulderPivot.rotation.x = S.ft.rShX.value;
    b.leftArm.elbowPivot.rotation.x = S.ft.lElb.value;
    b.rightArm.elbowPivot.rotation.x = S.ft.rElb.value;

    // Épaulement: derive from hip rotation
    const hipRotY = b.hips.rotation.y || 0;
    if (Math.abs(hipRotY) > 0.01) {
        const ep = M.epaulement(hipRotY);
        M.followThrough(S.ft.spineY, ep.spine, dt, ftP);
        b.upperTorsoPivot.rotation.y = S.ft.spineY.value;
        // Head inclines over forward shoulder (additive)
        b.headPivot.rotation.y += ep.headY * 0.3;
        b.headPivot.rotation.z = ep.headTilt;
    }

    // Successive motion for arms (shoulder leads, wrist trails)
    M.successive(S.lArmChain, S.ft.lShX.value, dt, 6, 0.1);
    M.successive(S.rArmChain, S.ft.rShX.value, dt, 6, 0.1);
    b.leftArm.wristPivot.rotation.y = S.lArmChain[2].current * 0.12;
    b.rightArm.wristPivot.rotation.y = S.rArmChain[2].current * 0.12;

    // Neck follows head with damped lag
    b.neckPivot.rotation.y = S.ft.headY.value * 0.35;
}
"""


# ---------------------------------------------------------------------------
# WANDER V5 — shared walk animation helper (used by react script)
# This script just provides the blink animation during walk for NPCs
# that use the react script for movement. It's attached but only
# activates supplementary systems.
# ---------------------------------------------------------------------------

WANDER_V5_SCRIPT = r"""
// V5 wander is handled by react script — this is a no-op placeholder
// that ensures the entity has the expected script attachment pattern.
"""
