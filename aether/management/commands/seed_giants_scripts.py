"""Register Aether scripts for the MegaForest interactables: swing + barbecue.

Each script is self-contained — it builds its own brick-styled three.js
geometry under ctx.entity, animates it, and reacts to player interaction
(click). No legoworld-render anchor is involved; these entities live next
to the brick payload in the world tree.

    venv/bin/python manage.py seed_giants_scripts

Idempotent — re-running upserts each script's code.
"""

from django.core.management.base import BaseCommand

from aether.models import Script


# All visuals scale with ctx.props.scale (meters per stud) so the swing /
# barbecue match the brick world they sit in. Default 0.4 mirrors the
# legoworld-render default.

SWING_BUILD = r"""
// MegaForest swing — builds a tall A-frame swing with a hanging seat
// you can click to ride. Geometry is brick-styled (BoxGeometry + studs)
// and matches the legoworld scale.
const P = ctx.props || {};
const SCALE = P.scale || 0.4;
const POST_COLOR = P.postColor || '#6b4a2e';
const CHAIN_COLOR = P.chainColor || '#888888';
const SEAT_COLOR = P.seatColor || '#d01712';

const PLATE_H = 0.4;
const POST_STUDS = 8;          // 8 studs tall ≈ 3.2 m at scale 0.4
const SPAN_STUDS = 6;
const SEAT_DROP_STUDS = 4;     // chain length

function box(w, h, d, color) {
    return new THREE.Mesh(
        new THREE.BoxGeometry(w, h, d),
        new THREE.MeshStandardMaterial({color: color, roughness: 0.6})
    );
}

if (ctx.entity.isMesh) {
    ctx.entity.material.visible = false;
    ctx.entity.castShadow = false;
}

const root = new THREE.Group();
root.name = 'swing';

// Two posts, slightly tilted outward for the A-frame look
const postH = POST_STUDS * SCALE;
const postW = 0.6 * SCALE;
for (const sx of [-1, 1]) {
    const post = box(postW, postH, postW, POST_COLOR);
    post.position.set(sx * SPAN_STUDS * 0.5 * SCALE, postH / 2, 0);
    post.rotation.z = sx * 0.08;
    post.castShadow = true;
    post.receiveShadow = true;
    root.add(post);
}

// Crossbar at the top
const beamW = (SPAN_STUDS + 1) * SCALE;
const beam = box(beamW, postW, postW, POST_COLOR);
beam.position.set(0, postH, 0);
beam.castShadow = true;
root.add(beam);

// Pivot group — animation rotates this around the crossbar
const pivot = new THREE.Group();
pivot.position.set(0, postH, 0);
root.add(pivot);

// Two chains
const chainLen = SEAT_DROP_STUDS * SCALE;
const chainW = 0.18 * SCALE;
for (const sx of [-1, 1]) {
    const chain = box(chainW, chainLen, chainW, CHAIN_COLOR);
    chain.position.set(sx * 1.0 * SCALE, -chainLen / 2, 0);
    chain.castShadow = true;
    pivot.add(chain);
}

// Seat
const seatW = 2.4 * SCALE;
const seatD = 0.9 * SCALE;
const seatH = 0.4 * SCALE;
const seat = box(seatW, seatH, seatD, SEAT_COLOR);
seat.position.set(0, -chainLen - seatH / 2, 0);
seat.castShadow = true;
seat.receiveShadow = true;
pivot.add(seat);

// Studs on top of the seat — visual continuity with the lego world
const studGeo = new THREE.CylinderGeometry(0.30 * SCALE, 0.30 * SCALE,
                                           0.20 * SCALE, 10);
const studMat = new THREE.MeshStandardMaterial({color: SEAT_COLOR,
                                                roughness: 0.5});
for (let i = -1; i <= 1; i++) {
    const stud = new THREE.Mesh(studGeo, studMat);
    stud.position.set(i * 0.7 * SCALE,
                      -chainLen - seatH - 0.10 * SCALE, 0);
    pivot.add(stud);
}

// Invisible large click-target so the click raycaster reliably hits us.
const clickGeo = new THREE.BoxGeometry(SPAN_STUDS * SCALE,
                                        postH + chainLen,
                                        2.0 * SCALE);
const clickMat = new THREE.MeshBasicMaterial({visible: false});
const clickbox = new THREE.Mesh(clickGeo, clickMat);
clickbox.position.set(0, (postH - chainLen) / 2, 0);
clickbox.userData.entityId = ctx.entityId;
root.add(clickbox);

ctx.state.swingPivot = pivot;
ctx.state.swingSeatY = -chainLen - seatH;
ctx.state.swingChainLen = chainLen;
ctx.state.swingPostH = postH;
ctx.state.swingPhase = Math.random() * Math.PI * 2;
ctx.state.swingAmp = 0.6;       // radians of swing
ctx.state.swingFreq = 1.4;      // rad/s drift
ctx.state.riding = false;

ctx.entity.add(root);
"""


SWING_UPDATE = r"""
// Animate the swing seat. When ctx.state.riding is true, also drag the
// player camera along the seat's swing arc.
const st = ctx.state;
if (!st.swingPivot) return;

st.swingPhase = (st.swingPhase || 0) + ctx.deltaTime * (st.swingFreq || 1.4);
const angle = (st.swingAmp || 0.6) * Math.sin(st.swingPhase);
st.swingPivot.rotation.x = angle;

if (st.riding) {
    // World-space position of the seat
    const seatLocal = new THREE.Vector3(0, st.swingSeatY, 0);
    seatLocal.applyEuler(new THREE.Euler(angle, 0, 0));
    seatLocal.add(new THREE.Vector3(0, st.swingPostH, 0));
    const seatWorld = ctx.entity.localToWorld(seatLocal.clone());
    // Camera (player) sits ~1.4 m above the seat
    ctx.camera.position.set(seatWorld.x,
                            seatWorld.y + 1.4,
                            seatWorld.z);
}
"""


SWING_INTERACT = r"""
// Click toggles riding the swing.
const st = ctx.state;
st.riding = !st.riding;
if (!st.riding) {
    // Dismount: step the player a stride in front of the swing
    const offset = new THREE.Vector3(0, 1.6, 2.5);
    const world = ctx.entity.localToWorld(offset);
    ctx.camera.position.set(world.x, world.y, world.z);
}
console.log('Swing ride:', st.riding);
"""


BBQ_BUILD = r"""
// MegaForest barbecue — squat brick-styled grill with flickering flames.
const P = ctx.props || {};
const SCALE = P.scale || 0.4;
const STONE = P.stoneColor || '#3a3a3a';
const GRILL = P.grillColor || '#888888';
const HOOD  = P.hoodColor  || '#1a1a1a';
const FLAME_COLORS = ['#ffb020', '#ff5520', '#ff8030', '#ffd060'];

function box(w, h, d, color, opts) {
    const o = opts || {};
    const mat = new THREE.MeshStandardMaterial({
        color: color, roughness: o.rough != null ? o.rough : 0.6,
        emissive: o.emissive || '#000000',
        emissiveIntensity: o.emissiveI || 0.0,
        transparent: !!o.transparent, opacity: o.opacity != null ? o.opacity : 1,
    });
    return new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
}

if (ctx.entity.isMesh) {
    ctx.entity.material.visible = false;
    ctx.entity.castShadow = false;
}

const root = new THREE.Group();
root.name = 'bbq';

// 4 short legs
const legH = 0.8 * SCALE;
const legW = 0.4 * SCALE;
for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
    const leg = box(legW, legH, legW, STONE);
    leg.position.set(sx * 0.7 * SCALE, legH / 2, sz * 0.5 * SCALE);
    leg.castShadow = true;
    root.add(leg);
}

// Firebox
const fbW = 2.0 * SCALE, fbH = 1.2 * SCALE, fbD = 1.6 * SCALE;
const firebox = box(fbW, fbH, fbD, STONE);
firebox.position.set(0, legH + fbH / 2, 0);
firebox.castShadow = true;
firebox.receiveShadow = true;
root.add(firebox);

// Grill plate (slightly on top of firebox)
const grill = box(fbW * 0.9, 0.2 * SCALE, fbD * 0.9, GRILL,
                  {rough: 0.3, emissive: '#1a0a00', emissiveI: 0.4});
grill.position.set(0, legH + fbH + 0.1 * SCALE, 0);
root.add(grill);

// Hood (open back, simple curved-look = box rotated)
const hoodH = 0.8 * SCALE;
const hood = box(fbW, hoodH, fbD * 0.6, HOOD);
hood.position.set(0, legH + fbH + 0.2 * SCALE + hoodH / 2, -fbD * 0.2);
hood.rotation.x = -0.35;
hood.castShadow = true;
root.add(hood);

// Flame group — animated cluster of small glowing boxes
const flameGroup = new THREE.Group();
flameGroup.position.set(0, legH + fbH + 0.2 * SCALE, 0);
const flames = [];
for (let i = 0; i < 5; i++) {
    const fx = (Math.random() - 0.5) * fbW * 0.6;
    const fz = (Math.random() - 0.5) * fbD * 0.6;
    const fc = FLAME_COLORS[i % FLAME_COLORS.length];
    const flame = box(0.25 * SCALE, 0.6 * SCALE, 0.25 * SCALE, fc, {
        emissive: fc, emissiveI: 1.6, transparent: true, opacity: 0.9,
    });
    flame.position.set(fx, 0.3 * SCALE, fz);
    flameGroup.add(flame);
    flames.push(flame);
}
root.add(flameGroup);

// Point light over the grill — warms the surrounding bricks
const fireLight = new THREE.PointLight(0xff7020, 0.6, 6 * SCALE);
fireLight.position.set(0, legH + fbH + 0.6 * SCALE, 0);
root.add(fireLight);

// Smoke puffs — small grey planes that float up + fade
ctx.state.smokeMat = new THREE.MeshBasicMaterial({
    color: '#aaaaaa', transparent: true, opacity: 0.35,
});
ctx.state.smokeGeo = new THREE.PlaneGeometry(0.6 * SCALE, 0.6 * SCALE);

// Click-target encompasses the whole grill
const clickGeo = new THREE.BoxGeometry(fbW * 1.2, legH + fbH + hoodH + 0.4,
                                        fbD * 1.2);
const clickbox = new THREE.Mesh(clickGeo,
    new THREE.MeshBasicMaterial({visible: false}));
clickbox.position.set(0, (legH + fbH + hoodH) / 2, 0);
clickbox.userData.entityId = ctx.entityId;
root.add(clickbox);

ctx.state.bbqFlames = flames;
ctx.state.bbqLight = fireLight;
ctx.state.bbqRoot = root;
ctx.state.bbqCooking = false;
ctx.state.bbqFood = null;
ctx.state.bbqGrillTopY = legH + fbH + 0.2 * SCALE;
ctx.state.bbqHalfW = fbW * 0.4;
ctx.state.bbqHalfD = fbD * 0.4;
ctx.state.bbqSmokes = [];

ctx.entity.add(root);
"""


BBQ_UPDATE = r"""
// Flicker the flames; emit smoke puffs while cooking.
const st = ctx.state;
if (!st.bbqFlames) return;

const t = ctx.elapsed;
for (let i = 0; i < st.bbqFlames.length; i++) {
    const f = st.bbqFlames[i];
    const wobble = 0.7 + 0.3 * Math.sin(t * 6 + i * 1.7)
                       + 0.2 * Math.sin(t * 11 + i * 0.9);
    f.scale.set(1, wobble, 1);
    f.position.y = 0.3 * (ctx.props.scale || 0.4) * wobble;
}
if (st.bbqLight) {
    st.bbqLight.intensity = (st.bbqCooking ? 1.2 : 0.6)
        + 0.2 * Math.sin(t * 8.0);
}

if (st.bbqCooking) {
    // Spawn smoke puffs
    if ((st.bbqSmokeAcc = (st.bbqSmokeAcc || 0) + ctx.deltaTime) > 0.18) {
        st.bbqSmokeAcc = 0;
        const puff = new THREE.Mesh(st.bbqSmokeGeo || st.smokeGeo,
                                    st.bbqSmokeMat || st.smokeMat);
        const SCALE = ctx.props.scale || 0.4;
        puff.position.set((Math.random() - 0.5) * 0.6 * SCALE,
                          st.bbqGrillTopY + 0.4 * SCALE,
                          (Math.random() - 0.5) * 0.6 * SCALE);
        puff.userData.born = ctx.elapsed;
        st.bbqRoot.add(puff);
        st.bbqSmokes.push(puff);
    }
}
// Age smoke puffs
const SCALE = ctx.props.scale || 0.4;
for (let i = st.bbqSmokes.length - 1; i >= 0; i--) {
    const p = st.bbqSmokes[i];
    const age = ctx.elapsed - p.userData.born;
    p.position.y += ctx.deltaTime * 0.8 * SCALE;
    p.material.opacity = Math.max(0, 0.35 - age * 0.18);
    p.lookAt(ctx.camera.position);
    if (age > 1.8) {
        st.bbqRoot.remove(p);
        st.bbqSmokes.splice(i, 1);
    }
}
"""


BBQ_INTERACT = r"""
// Click toggles cooking mode. While cooking, a sausage-shaped food brick
// appears on the grill and the flames burn brighter.
const st = ctx.state;
st.bbqCooking = !st.bbqCooking;
const SCALE = ctx.props.scale || 0.4;
if (st.bbqCooking) {
    const food = new THREE.Mesh(
        new THREE.BoxGeometry(1.4 * SCALE, 0.3 * SCALE, 0.4 * SCALE),
        new THREE.MeshStandardMaterial({color: '#a05030', roughness: 0.7}),
    );
    food.position.set(0, st.bbqGrillTopY + 0.15 * SCALE, 0);
    food.castShadow = true;
    st.bbqRoot.add(food);
    st.bbqFood = food;
    st.bbqCookStart = ctx.elapsed;
    console.log('BBQ on — food on the grill.');
} else if (st.bbqFood) {
    st.bbqRoot.remove(st.bbqFood);
    st.bbqFood = null;
    console.log('BBQ off — food removed.');
}
"""


SCRIPTS = [
    ('giants-swing-build', 'MegaForest Swing — Build', 'start',
     'Builds the swing geometry (A-frame posts + crossbar + hanging seat) '
     'as brick-styled three.js meshes under ctx.entity.', SWING_BUILD),
    ('giants-swing-update', 'MegaForest Swing — Animate', 'update',
     'Sways the seat each frame; while ctx.state.riding is true, drags '
     'the player camera with the seat.', SWING_UPDATE),
    ('giants-swing-interact', 'MegaForest Swing — Interact', 'interact',
     'Click toggles riding the swing.', SWING_INTERACT),
    ('giants-bbq-build', 'MegaForest Barbecue — Build', 'start',
     'Builds the barbecue (legs, firebox, grill, hood, flame cluster, '
     'glow light) under ctx.entity.', BBQ_BUILD),
    ('giants-bbq-update', 'MegaForest Barbecue — Animate', 'update',
     'Flickers flames + light; while cooking, emits rising smoke puffs.',
     BBQ_UPDATE),
    ('giants-bbq-interact', 'MegaForest Barbecue — Interact', 'interact',
     'Click toggles cooking — adds/removes a food piece on the grill.',
     BBQ_INTERACT),
]


class Command(BaseCommand):
    help = 'Register / update Aether scripts for MegaForest swing + barbecue.'

    def handle(self, *args, **opts):
        for slug, name, event, desc, code in SCRIPTS:
            s, created = Script.objects.get_or_create(
                slug=slug,
                defaults={'name': name, 'event': event,
                          'code': code, 'description': desc,
                          'is_builtin': True},
            )
            changed = False
            if not created:
                if s.code != code:
                    s.code = code
                    changed = True
                if s.event != event:
                    s.event = event
                    changed = True
                if s.description != desc:
                    s.description = desc
                    changed = True
                if changed:
                    s.save()
            tag = 'created' if created else ('updated' if changed else 'kept')
            self.stdout.write(f'  [{tag}] {slug}')
        self.stdout.write(self.style.SUCCESS(
            f'Registered {len(SCRIPTS)} MegaForest scripts.'))
