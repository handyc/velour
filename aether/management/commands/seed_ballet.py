"""Seed the Velour Ballet Studio — movement quality research world.

This world serves two purposes:
1. A ballet studio with dancers performing classical moves to showcase
   fluid, graceful procedural animation.
2. The proving ground for a reusable motion quality library (MOTION_LIB)
   that encodes ballet/animation principles:
   - Ease curves (cubic ease-in-out, overshoot, spring)
   - Successive motion (movement propagates with time delays)
   - Follow-through and overlapping action
   - Épaulement (shoulder-hip counter-rotation, head inclination)
   - Port de bras (flowing arm curves through positions)
   - Weight transfer (visible center-of-gravity shift)
   - Anticipation (counter-movement before action)
   - Breath phrasing (variable-depth breathing modulates all motion)

The MOTION_LIB script is a 'start' event that injects utility functions
into ctx.state so other scripts (idle, walk, react) can call them.
"""

from django.core.management.base import BaseCommand

from aether.models import Entity, EntityScript, Script, World


SKIN = [
    '#d4a470', '#c89870', '#e8c898', '#a87040', '#f0d4b0',
    '#8b5030', '#b88050', '#704020', '#d0ac80', '#b06038',
]
LEOTARD = [
    '#1a1a28', '#28182a', '#181828', '#2a1818', '#1a2028',
    '#201a28', '#281a20', '#1a2818', '#28201a', '#201828',
]
TIGHTS = [
    '#e8d8c8', '#f0e0d0', '#e0d0c0', '#f0e8e0', '#e8e0d0',
    '#d8c8b8', '#f0d8c8', '#e0d8c8', '#e8d0c0', '#f0e0d8',
]
SHOES_PINK = [
    '#e8c0b0', '#e0b8a8', '#d8b0a0', '#f0c8b8', '#e0c0b0',
    '#d0a898', '#e8b8a8', '#d8b8a8', '#e0c0a8', '#e8c8b0',
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
    (0.88, 0.90, 1.0),
    (0.85, 0.88, 0.97),
    (0.90, 0.92, 1.02),
    (0.86, 0.89, 0.98),
    (0.87, 0.91, 1.01),
    (0.84, 0.87, 0.96),
    (0.89, 0.90, 1.0),
    (0.86, 0.88, 0.99),
    (0.88, 0.91, 1.01),
    (0.85, 0.89, 0.98),
]
FACES = [
    (0.92, 1.0,  1.0),
    (0.88, 1.05, 0.98),
    (0.95, 0.95, 1.02),
    (0.90, 1.02, 0.97),
    (0.93, 0.98, 1.0),
    (0.89, 1.04, 0.99),
    (0.94, 0.97, 1.01),
    (0.87, 1.06, 0.96),
    (0.91, 1.0,  1.0),
    (0.90, 1.03, 0.98),
]

# Each dancer performs a different ballet sequence
CHOREO = [
    'adagio',       # slow sustained movement, full port de bras
    'pirouette',    # turns with spotting
    'arabesque',    # balanced on one leg, other extended behind
    'plié_relevé',  # deep bend then rise to toes
    'port_de_bras', # pure arm work through all 5 positions
    'tendu',        # extending leg along floor
    'développé',    # unfolding leg from retiré to extension
    'chassé',       # gliding step
    'reverence',    # the bow at the end of class
    'free',         # improvisation combining all elements
]


class Command(BaseCommand):
    help = 'Create the Velour Ballet Studio with dancers and motion quality library.'

    def handle(self, *args, **options):
        World.objects.filter(slug='velour-ballet').delete()

        world = World.objects.create(
            title='Velour Ballet Studio',
            slug='velour-ballet',
            description='Ballet studio showcasing fluid procedural animation. '
                        'Motion quality library: ease curves, successive motion, '
                        'épaulement, port de bras, follow-through.',
            skybox='color',
            sky_color='#f0e8e0',
            ground_color='#b09878',
            ground_size=30.0,
            ambient_light=0.6,
            fog_near=25.0,
            fog_far=60.0,
            fog_color='#f0e8e0',
            gravity=-9.81,
            spawn_x=0.0, spawn_y=1.6, spawn_z=12.0,
            soundscape='',
            ambient_volume=0.0,
            published=True, featured=True,
        )

        motion_lib = _script('Motion Quality Library', 'start', MOTION_LIB_SCRIPT,
            'Injects easing, successive motion, and ballet utilities into ctx.state.')
        humanoid_v5 = _get_script('humanoid-builder-v5')
        ballet_anim = _script('Ballet Animator', 'update', BALLET_ANIM_SCRIPT,
            'Ballet choreography: adagio, pirouette, arabesque, port de bras, etc.')

        entities = []
        E = lambda *a, **k: entities.append(_ent(world, *a, **k))

        # Studio floor (warm wood)
        E('Floor', 'box', '#b09878', 0, -0.05, 0, sx=30, sy=0.1, sz=30, shadow=False)

        # Floorboards
        for z in range(-12, 13, 2):
            E(f'Board {z}', 'box', '#a89070', 0, 0.001, z,
              sx=30, sy=0.003, sz=1.8, shadow=False)

        # Walls (three sides)
        E('BackWall', 'box', '#e8e0d8', 0, 2.5, -14, sx=30, sy=5, sz=0.15)
        E('LeftWall', 'box', '#e0d8d0', -14, 2.5, 0, sx=0.15, sy=5, sz=28)
        E('RightWall', 'box', '#e0d8d0', 14, 2.5, 0, sx=0.15, sy=5, sz=28)

        # Mirror wall (back wall is reflective)
        E('Mirror', 'box', '#d0d8e0', 0, 2.5, -13.85, sx=26, sy=4.0, sz=0.02)

        # Barre (ballet practice bar) along left and right walls
        for side, wx in [('L', -13.5), ('R', 13.5)]:
            E(f'Barre {side}', 'cylinder', '#8a6840', wx, 1.0, 0,
              sx=0.025, sy=0.025, sz=24)
            # Barre supports
            for bz in range(-10, 11, 4):
                E(f'BarreSupport {side} {bz}', 'cylinder', '#706040',
                  wx, 0.5, bz, sx=0.015, sy=1.0, sz=0.015)

        # Ceiling beams
        for x in range(-12, 13, 6):
            E(f'CeilBeam {x}', 'box', '#d0c8c0', x, 4.9, 0,
              sx=0.12, sy=0.08, sz=28)

        # Skylights (bright rectangles on ceiling)
        for x in range(-6, 7, 6):
            E(f'Skylight {x}', 'box', '#ffffff', x, 4.98, 0,
              sx=3, sy=0.01, sz=8, shadow=False)

        # Piano in corner
        E('Piano Body', 'box', '#1a1a1a', -10, 0.45, -10, sx=1.5, sy=0.9, sz=0.8)
        E('Piano Lid', 'box', '#181818', -10, 0.92, -10.15, sx=1.5, sy=0.03, sz=0.5)
        E('Piano Stool', 'cylinder', '#3a2818', -10, 0.25, -9, sx=0.2, sy=0.5, sz=0.2)

        # --- Dancers ---
        NAMES = ['Aurelia', 'Brigitte', 'Celeste', 'Daphne', 'Elodie',
                 'Fiona', 'Genevieve', 'Helena', 'Isabelle', 'Juliette']

        # Spread across studio floor in a loose arc
        import math
        POSITIONS = []
        for i in range(10):
            angle = -0.8 + (i / 9) * 1.6
            r = 4 + (i % 3) * 2.5
            x = math.sin(angle) * r
            z = -math.cos(angle) * r - 2
            ry = math.degrees(angle) + 180
            POSITIONS.append((round(x, 1), round(z, 1), round(ry, 1)))

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
            e._choreo = CHOREO[i]
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
            # Motion library first (injects utilities)
            attach(e, motion_lib, {})
            # Then humanoid builder
            if humanoid_v5:
                attach(e, humanoid_v5, {
                    'skin': SKIN[i],
                    'shirt': LEOTARD[i],
                    'pants': TIGHTS[i],
                    'shoes': SHOES_PINK[i],
                    'hair': HAIR[i],
                    'eyes': EYE_COLORS[i],
                    'shoulderW': build[0], 'hipW': build[1], 'heightScale': build[2],
                    'jawW': face[0], 'cheekFull': face[1], 'foreheadH': face[2],
                })
            # Ballet animation
            attach(e, ballet_anim, {
                'choreo': e._choreo,
                'tempo': 0.4 + (i % 3) * 0.08,
            })

        EntityScript.objects.bulk_create(attachments)
        total = Entity.objects.filter(world=world).count()
        self.stdout.write(self.style.SUCCESS(
            f'Velour Ballet Studio created: {total} entities, '
            f'{len(npc_ents)} dancers.'
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


def _get_script(slug):
    from aether.models import Script
    return Script.objects.filter(slug=slug).first()


# ---------------------------------------------------------------------------
# MOTION QUALITY LIBRARY — injected as ctx.state.M
# ---------------------------------------------------------------------------
# This is a 'start' script that creates a set of utility functions on
# ctx.state.M. Other scripts (ballet animator, idle, walk, react) can
# call these instead of raw Math.sin for natural-feeling motion.
# ---------------------------------------------------------------------------

MOTION_LIB_SCRIPT = r"""
const M = {};
ctx.state.M = M;

// === EASING FUNCTIONS ===
// All take t in [0,1], return [0,1]

// Cubic ease-in-out: slow start, fast middle, slow end
M.easeInOut = function(t) {
    return t < 0.5
        ? 4 * t * t * t
        : 1 - Math.pow(-2 * t + 2, 3) / 2;
};

// Ease-out cubic: fast start, decelerating
M.easeOut = function(t) {
    return 1 - Math.pow(1 - t, 3);
};

// Ease-in cubic: accelerating start
M.easeIn = function(t) {
    return t * t * t;
};

// Overshoot ease-out: goes past target then settles back
M.easeOutBack = function(t) {
    const c1 = 1.70158;
    const c3 = c1 + 1;
    return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
};

// Spring: damped oscillation settling to target
M.spring = function(t, damping) {
    damping = damping || 6;
    return 1 - Math.exp(-damping * t) * Math.cos(t * Math.PI * 3);
};

// Smooth sinusoidal with ease (not uniform speed like raw Math.sin)
// Returns [-1, 1] like sin but with softer peaks
M.breathSin = function(t) {
    const phase = (t % 1.0);
    // Faster exhale, slower inhale (like real breathing)
    if (phase < 0.4) {
        return M.easeInOut(phase / 0.4); // inhale
    } else {
        return M.easeInOut(1.0 - (phase - 0.4) / 0.6); // exhale
    }
};

// === SUCCESSIVE MOTION ===
// Propagates a value through a chain with time delays.
// Each element lags behind the previous by 'lag' seconds.
// chain: array of {current, target} objects (mutated in place)
// dt: delta time
// stiffness: how quickly each element follows (higher = snappier)
M.successive = function(chain, sourceValue, dt, stiffness, lag) {
    stiffness = stiffness || 5;
    lag = lag || 0.08;
    // First element follows source directly
    chain[0].target = sourceValue;
    chain[0].current += (chain[0].target - chain[0].current) * Math.min(1, dt * stiffness);
    // Each subsequent element follows the previous with lag
    for (let i = 1; i < chain.length; i++) {
        chain[i].target = chain[i-1].current;
        const s = stiffness * (1 - i * lag);
        chain[i].current += (chain[i].target - chain[i].current) * Math.min(1, dt * Math.max(s, 1));
    }
};

// === FOLLOW-THROUGH ===
// When a target changes, the value overshoots then settles.
// state: {value, velocity} object (mutated)
// target: desired value
// dt: delta time
// params: {stiffness, damping} — higher stiffness = faster, higher damping = less bounce
M.followThrough = function(state, target, dt, params) {
    params = params || {};
    const stiffness = params.stiffness || 12;
    const damping = params.damping || 4;
    const force = (target - state.value) * stiffness;
    state.velocity += force * dt;
    state.velocity *= Math.exp(-damping * dt); // damping
    state.value += state.velocity * dt;
};

// === ÉPAULEMENT ===
// Given hip rotation, compute counter-rotations for spine, shoulders, head.
// Returns {spine, shoulders, headY, headTilt}
M.epaulement = function(hipRot) {
    return {
        spine: -hipRot * 0.3,          // spine counters 30%
        shoulders: -hipRot * 0.6,       // shoulders counter 60%
        headY: hipRot * 0.4,            // head inclines toward forward shoulder
        headTilt: hipRot * 0.15,        // slight lateral tilt
    };
};

// === PORT DE BRAS (arm position interpolation) ===
// 5 classical arm positions. Each is [shoulderX, shoulderZ, elbowX, wristX]
M.armPositions = [
    // Bras bas (preparatory) — arms low, rounded
    [-0.05, 0.1, -0.15, 0.05],
    // First position — arms forward, rounded
    [-0.9, 0.0, -0.2, 0.1],
    // Second position — arms open to sides
    [-0.3, -0.8, -0.1, 0.05],
    // Third position — one arm high (using as both high)
    [-2.8, 0.0, -0.15, -0.1],
    // Fifth position (en haut) — arms overhead, rounded
    [-2.9, -0.1, -0.2, 0.0],
];

// Interpolate between two arm positions with easing
M.lerpArm = function(posA, posB, t) {
    const e = M.easeInOut(t);
    return posA.map((v, i) => v + (posB[i] - v) * e);
};

// === WEIGHT SHIFT ===
// Compute hip offset and tilt based on weight distribution.
// weight: 0 = centered, -1 = full left, +1 = full right
M.weightShift = function(weight) {
    return {
        hipX: weight * 0.04,        // lateral hip displacement
        hipTilt: weight * 0.03,      // hip tilt (z rotation)
        spineComp: -weight * 0.02,   // spine compensates opposite
    };
};

// === ANTICIPATION ===
// Before a move in direction d, briefly move opposite.
// Returns a multiplier curve: starts negative, then goes to 1
// t: 0 to 1 progress through the move
// antic: how much anticipation (0.1 = subtle, 0.3 = dramatic)
M.anticipation = function(t, antic) {
    antic = antic || 0.15;
    if (t < 0.12) {
        return -antic * M.easeOut(t / 0.12);
    } else if (t < 0.25) {
        return -antic + (1 + antic) * M.easeIn((t - 0.12) / 0.13);
    } else {
        return 1.0;
    }
};

// === BREATH with variable depth ===
// More natural than fixed-amplitude sine.
// Returns {phase, depth, value}
M.breath = function(t, seed) {
    seed = seed || 0;
    const period = 3.2 + Math.sin(t * 0.07 + seed) * 0.5; // variable period
    const phase = ((t + seed) % period) / period;
    const depth = 0.7 + Math.sin(t * 0.13 + seed * 3) * 0.3; // variable depth
    const value = M.breathSin(phase) * depth;
    return {phase, depth, value};
};

// === PIANIST FINGER SYSTEM ===
// Models individual finger independence observed in master pianists.
// Each finger has its own follow-through state and can be independently
// targeted. When one finger curls (strikes), adjacent fingers lift
// slightly (compensation). Movement propagates wrist → MCP → PIP → DIP
// with successive delays.

// fingerStates: create per-hand state for 4 fingers + thumb
M.createFingerStates = function() {
    const fingers = [];
    for (let i = 0; i < 4; i++) {
        fingers.push({
            mcp: {value: 0.12, velocity: 0},
            pip: {value: 0.1, velocity: 0},
            dip: {value: 0.08, velocity: 0},
            spread: {value: 0, velocity: 0}, // lateral spread (z rotation)
            target: 0.12, // rest curl
        });
    }
    const thumb = {
        mcp: {value: 0.1, velocity: 0},
        ip: {value: 0.08, velocity: 0},
        target: 0.1,
    };
    return {fingers, thumb, wristRot: {value: 0, velocity: 0}};
};

// Animate pianist-style finger movement for one hand.
// hand: the arm object (with .fingers and .thumb)
// fState: from createFingerStates()
// pattern: array of {finger: 0-3, curl: amount, time: offset}
// t: elapsed time
// dt: delta time
// tempo: speed multiplier
M.animateFingers = function(hand, fState, pattern, t, dt, tempo) {
    if (!hand.fingers) return;
    tempo = tempo || 1;

    // Compute per-finger targets from pattern
    const restCurl = [0.12, 0.10, 0.12, 0.16]; // index, middle, ring, pinky
    const targets = restCurl.slice(); // start at rest

    // Apply pattern keypresses
    for (const p of pattern) {
        const cycleT = ((t * tempo + p.time) % 2.0) / 2.0;
        // Each keypress is a quick strike and release
        if (cycleT < 0.08) {
            // Strike: finger curls down sharply
            targets[p.finger] = p.curl || 0.5;
            // Adjacent fingers compensate (lift slightly)
            if (p.finger > 0) targets[p.finger-1] = Math.max(targets[p.finger-1] - 0.06, 0);
            if (p.finger < 3) targets[p.finger+1] = Math.max(targets[p.finger+1] - 0.06, 0);
        } else if (cycleT < 0.2) {
            // Release: ease back
            const rel = (cycleT - 0.08) / 0.12;
            targets[p.finger] = p.curl * (1 - M.easeOut(rel)) + restCurl[p.finger] * M.easeOut(rel);
        }
    }

    // Apply through follow-through (spring-like, not snappy)
    const fP = {stiffness: 18, damping: 5}; // fast but with overshoot
    for (let i = 0; i < 4; i++) {
        const fs = fState.fingers[i];
        fs.target = targets[i];
        M.followThrough(fs.mcp, fs.target, dt, fP);
        M.followThrough(fs.pip, fs.target * 0.8, dt, {stiffness: 14, damping: 5}); // PIP lags
        M.followThrough(fs.dip, fs.target * 0.6, dt, {stiffness: 10, damping: 5}); // DIP lags more

        // Apply to actual finger pivots
        const f = hand.fingers[i];
        f.mcpPivot.rotation.x = fs.mcp.value;
        f.pipPivot.rotation.x = fs.pip.value;
        f.dipPivot.rotation.x = fs.dip.value;
    }

    // Thumb (simpler: just curl amount)
    const thumbTarget = 0.1 + Math.sin(t * tempo * 2) * 0.05;
    M.followThrough(fState.thumb.mcp, thumbTarget, dt, {stiffness: 12, damping: 4});
    M.followThrough(fState.thumb.ip, thumbTarget * 0.7, dt, {stiffness: 8, damping: 4});
    if (hand.thumb) {
        hand.thumb.mcpPivot.rotation.x = fState.thumb.mcp.value;
        hand.thumb.ipPivot.rotation.x = fState.thumb.ip.value;
    }

    // Wrist rotation (forearm rotation drives lateral movement)
    const wristTarget = Math.sin(t * tempo * 0.8) * 0.08;
    M.followThrough(fState.wristRot, wristTarget, dt, {stiffness: 6, damping: 3});
    hand.wristPivot.rotation.z = fState.wristRot.value;
};

// Generate a random pianist-like pattern for idle finger animation
M.randomFingerPattern = function(seed) {
    const patterns = [];
    const rng = function(i) { return Math.abs(Math.sin(seed * 127.1 + i * 311.7)) };
    const n = 3 + Math.floor(rng(0) * 4); // 3-6 keypress events
    for (let i = 0; i < n; i++) {
        patterns.push({
            finger: Math.floor(rng(i+1) * 4),
            curl: 0.3 + rng(i+2) * 0.25,
            time: rng(i+3) * 2.0,
        });
    }
    return patterns;
};

ctx.state.motionLib = true;
"""


# ---------------------------------------------------------------------------
# BALLET ANIMATOR — per-dancer choreography using the motion library
# ---------------------------------------------------------------------------

BALLET_ANIM_SCRIPT = r"""
if (!ctx.state.built || !ctx.state.M) return;
const S = ctx.state;
const M = S.M;
const b = S.body;
const P = ctx.props;
const t = ctx.elapsed;
const dt = ctx.deltaTime;

if (!S.ballet_init) {
    S.ballet_init = true;
    S.choreo = P.choreo || 'adagio';
    S.tempo = P.tempo || 0.4;
    S.seed = ctx.entity.position.x * 7.3 + ctx.entity.position.z * 13.7;
    S.phase = 0; // progress through current move [0,1]
    S.moveIdx = 0;
    S.moveTimer = 0;
    S.moveDuration = 3 + Math.random() * 2;

    // Follow-through state for each limb
    S.ft = {
        headY:  {value: 0, velocity: 0},
        headX:  {value: 0, velocity: 0},
        headZ:  {value: 0, velocity: 0},
        spineY: {value: 0, velocity: 0},
        hipZ:   {value: 0, velocity: 0},
        lShoulderX: {value: 0, velocity: 0},
        rShoulderX: {value: 0, velocity: 0},
        lShoulderZ: {value: 0, velocity: 0},
        rShoulderZ: {value: 0, velocity: 0},
        lElbow: {value: -0.15, velocity: 0},
        rElbow: {value: -0.15, velocity: 0},
        lWrist: {value: 0, velocity: 0},
        rWrist: {value: 0, velocity: 0},
    };

    // Successive chains for arms (shoulder → elbow → wrist → fingers)
    S.lArmChain = [{current:0,target:0},{current:0,target:0},{current:0,target:0}];
    S.rArmChain = [{current:0,target:0},{current:0,target:0},{current:0,target:0}];

    // Pianist finger states (per hand)
    S.lFingerState = M.createFingerStates();
    S.rFingerState = M.createFingerStates();
    // Each dancer gets a unique finger pattern based on seed
    S.lFingerPattern = M.randomFingerPattern(seed);
    S.rFingerPattern = M.randomFingerPattern(seed + 100);

    // Blink
    S.blinkTimer = 2 + Math.random() * 4;
    S.blinkPhase = 0;
    S.blinkT = 0;
}

const seed = S.seed;
const tempo = S.tempo;

// === Breath (always, variable depth) ===
const br = M.breath(t * tempo, seed);

// === Phase progression ===
S.moveTimer += dt * tempo;
S.phase = Math.min(S.moveTimer / S.moveDuration, 1.0);
if (S.phase >= 1.0) {
    S.moveIdx = (S.moveIdx + 1) % 8;
    S.moveTimer = 0;
    S.phase = 0;
    S.moveDuration = 2.5 + Math.random() * 3;
}
const ph = S.phase;
const mi = S.moveIdx;
const ft = S.ft;
const ftP = {stiffness: 8, damping: 3.5}; // ballet: smooth, slight overshoot

// === CHOREOGRAPHY TARGET COMPUTATION ===
// Each choreo type sets target values for the follow-through system.

let hipY = 0.92;
let hipRotY = 0;
let hipRotZ = 0;
let lHipX = 0, rHipX = 0;
let lKnee = 0, rKnee = 0;
let lAnkle = 0, rAnkle = 0;
let headTargetY = 0, headTargetX = 0, headTargetZ = 0;
let spineTargetY = 0;
let lArmPos = M.armPositions[0]; // bras bas
let rArmPos = M.armPositions[0];

const C = S.choreo;

if (C === 'adagio') {
    // Slow sustained movement cycling through arm positions with weight shifts
    const armIdx = mi % 5;
    const nextArm = (mi + 1) % 5;
    lArmPos = M.lerpArm(M.armPositions[armIdx], M.armPositions[nextArm], M.easeInOut(ph));
    rArmPos = M.lerpArm(M.armPositions[(armIdx+2)%5], M.armPositions[(nextArm+2)%5], M.easeInOut(ph));
    // Gentle weight shift
    const wt = Math.sin(ph * Math.PI) * (mi % 2 === 0 ? 1 : -1) * 0.6;
    const ws = M.weightShift(wt);
    hipRotZ = ws.hipTilt;
    hipY = 0.92 + ws.hipX * 0.5;
    // Épaulement
    hipRotY = Math.sin(ph * Math.PI) * 0.15 * (mi % 2 === 0 ? 1 : -1);
    const ep = M.epaulement(hipRotY);
    spineTargetY = ep.spine;
    headTargetY = ep.headY;
    headTargetZ = ep.headTilt;
    headTargetX = br.value * 0.015;

} else if (C === 'pirouette') {
    // Preparation then spin
    if (ph < 0.3) {
        // Plié preparation with anticipation
        const prep = M.anticipation(ph / 0.3, 0.2);
        hipY = 0.92 - prep * 0.08;
        lArmPos = M.lerpArm(M.armPositions[0], M.armPositions[1], M.easeInOut(ph / 0.3));
        rArmPos = M.lerpArm(M.armPositions[0], M.armPositions[1], M.easeInOut(ph / 0.3));
    } else if (ph < 0.8) {
        // Spin: body rotates, arms in first position
        const spinPh = (ph - 0.3) / 0.5;
        hipY = 0.92 + M.easeOut(spinPh) * 0.04; // relevé
        ctx.entity.rotation.y += dt * tempo * 12; // actual rotation
        lArmPos = M.armPositions[1];
        rArmPos = M.armPositions[1];
        // Spotting: head snaps to front
        headTargetY = -Math.sin(spinPh * Math.PI * 2) * 0.5;
        // Retiré: one leg drawn up
        rHipX = -0.4; rKnee = 1.2;
    } else {
        // Land: plié to absorb
        const land = M.easeOut((ph - 0.8) / 0.2);
        hipY = 0.92 - (1 - land) * 0.05;
        lArmPos = M.lerpArm(M.armPositions[1], M.armPositions[0], land);
        rArmPos = M.lerpArm(M.armPositions[1], M.armPositions[0], land);
        rHipX = -0.4 * (1 - land); rKnee = 1.2 * (1 - land);
    }

} else if (C === 'arabesque') {
    // Stand on one leg, other extended behind
    const up = M.easeInOut(Math.min(ph * 2, 1));
    const hold = ph > 0.5 ? M.easeInOut((ph - 0.5) * 2) : 0;
    hipY = 0.92 + up * 0.02;
    // Working leg extends behind
    rHipX = up * 0.9;  // hip extends back
    rKnee = -up * 0.05; // straight
    // Arms: one forward, one to side
    lArmPos = M.lerpArm(M.armPositions[0], M.armPositions[1], up);
    rArmPos = M.lerpArm(M.armPositions[0], M.armPositions[2], up);
    // Lean forward to counterbalance
    headTargetX = up * 0.08;
    spineTargetY = 0;
    // Slight épaulement
    hipRotY = up * 0.1;
    const ep = M.epaulement(hipRotY);
    headTargetY = ep.headY;
    headTargetZ = ep.headTilt;

} else if (C === 'plié_relevé') {
    // Deep plié then rise to relevé (toes)
    const cycle = (ph * 2) % 1;
    const isPlié = ph < 0.5;
    if (isPlié) {
        // Plié: knees bend, hips lower
        const depth = M.easeInOut(cycle);
        hipY = 0.92 - depth * 0.15;
        lKnee = depth * 0.6; rKnee = depth * 0.6;
        lArmPos = M.lerpArm(M.armPositions[0], M.armPositions[1], depth);
        rArmPos = M.lerpArm(M.armPositions[0], M.armPositions[1], depth);
    } else {
        // Relevé: rise up, arms to fifth
        const rise = M.easeInOut(cycle);
        hipY = 0.92 + rise * 0.06;
        lAnkle = -rise * 0.3; rAnkle = -rise * 0.3;
        lArmPos = M.lerpArm(M.armPositions[1], M.armPositions[4], rise);
        rArmPos = M.lerpArm(M.armPositions[1], M.armPositions[4], rise);
    }
    headTargetX = br.value * 0.02;

} else if (C === 'port_de_bras') {
    // Pure arm work through all 5 positions
    const posCount = M.armPositions.length;
    const posF = ph * (posCount - 1);
    const fromIdx = Math.floor(posF);
    const toIdx = Math.min(fromIdx + 1, posCount - 1);
    const localT = posF - fromIdx;
    lArmPos = M.lerpArm(M.armPositions[fromIdx], M.armPositions[toIdx], localT);
    // Right arm offset by one position for asymmetry
    const rFrom = (fromIdx + 2) % posCount;
    const rTo = (toIdx + 2) % posCount;
    rArmPos = M.lerpArm(M.armPositions[rFrom], M.armPositions[rTo], localT);
    // Épaulement follows arm movement
    hipRotY = Math.sin(ph * Math.PI * 2) * 0.12;
    const ep = M.epaulement(hipRotY);
    spineTargetY = ep.spine;
    headTargetY = ep.headY;
    headTargetZ = ep.headTilt;
    // Gentle weight shift
    const ws = M.weightShift(Math.sin(ph * Math.PI) * 0.4);
    hipRotZ = ws.hipTilt;

} else if (C === 'tendu') {
    // Extending leg along floor, alternating sides
    const side = mi % 2 === 0 ? 1 : -1;
    const ext = M.easeInOut(ph < 0.5 ? ph * 2 : 2 - ph * 2);
    if (side > 0) {
        rHipX = -ext * 0.3; // leg extends forward
    } else {
        lHipX = -ext * 0.3;
    }
    // Opposite arm rises
    if (side > 0) {
        lArmPos = M.lerpArm(M.armPositions[0], M.armPositions[2], ext);
    } else {
        rArmPos = M.lerpArm(M.armPositions[0], M.armPositions[2], ext);
    }
    hipRotY = side * ext * 0.08;
    const ep = M.epaulement(hipRotY);
    headTargetY = ep.headY;

} else if (C === 'développé') {
    // Unfolding: retiré → extension
    if (ph < 0.4) {
        // Draw knee up (retiré)
        const up = M.easeInOut(ph / 0.4);
        rHipX = -up * 0.3;
        rKnee = up * 1.4;
    } else if (ph < 0.7) {
        // Unfold to extension
        const unfold = M.easeOut((ph - 0.4) / 0.3);
        rHipX = -0.3 - unfold * 0.4;
        rKnee = 1.4 - unfold * 1.35;
    } else {
        // Hold then lower
        const lower = M.easeInOut((ph - 0.7) / 0.3);
        rHipX = -0.7 * (1 - lower);
        rKnee = 0.05 * (1 - lower);
    }
    lArmPos = M.lerpArm(M.armPositions[0], M.armPositions[2], M.easeInOut(Math.min(ph*2,1)));
    rArmPos = M.lerpArm(M.armPositions[0], M.armPositions[3], M.easeInOut(Math.min(ph*1.5,1)));
    hipY = 0.92 + M.easeInOut(Math.min(ph*2,1)) * 0.02;

} else if (C === 'chassé') {
    // Gliding step: slide, close, slide
    const glide = Math.sin(ph * Math.PI * 2);
    ctx.entity.position.x += glide * dt * tempo * 0.8;
    hipY = 0.92 - Math.abs(glide) * 0.03 + M.easeOut(Math.abs(glide)) * 0.05;
    lHipX = glide * 0.25;
    rHipX = -glide * 0.25;
    lKnee = Math.max(0, -glide) * 0.3;
    rKnee = Math.max(0, glide) * 0.3;
    lArmPos = M.armPositions[2]; // arms open
    rArmPos = M.armPositions[2];
    hipRotY = glide * 0.1;
    const ep = M.epaulement(hipRotY);
    spineTargetY = ep.spine;
    headTargetY = ep.headY;

} else if (C === 'reverence') {
    // The bow: graceful curtsy
    if (ph < 0.4) {
        // Step back, arms open
        const prep = M.easeInOut(ph / 0.4);
        rHipX = prep * 0.3;
        lArmPos = M.lerpArm(M.armPositions[0], M.armPositions[2], prep);
        rArmPos = M.lerpArm(M.armPositions[0], M.armPositions[2], prep);
    } else if (ph < 0.7) {
        // Deep curtsy
        const bow = M.easeInOut((ph - 0.4) / 0.3);
        hipY = 0.92 - bow * 0.2;
        lKnee = bow * 0.8; rKnee = bow * 0.4;
        rHipX = 0.3;
        headTargetX = bow * 0.15;
        // Arms sweep down
        lArmPos = M.lerpArm(M.armPositions[2], M.armPositions[0], bow);
        rArmPos = M.lerpArm(M.armPositions[2], M.armPositions[0], bow);
    } else {
        // Rise
        const rise = M.easeInOut((ph - 0.7) / 0.3);
        hipY = 0.92 - (1 - rise) * 0.2;
        lKnee = (1 - rise) * 0.8; rKnee = (1 - rise) * 0.4;
        rHipX = 0.3 * (1 - rise);
        headTargetX = (1 - rise) * 0.15;
        lArmPos = M.lerpArm(M.armPositions[0], M.armPositions[0], rise);
        rArmPos = M.lerpArm(M.armPositions[0], M.armPositions[0], rise);
    }

} else {
    // 'free' — improvisation combining elements
    const wave = Math.sin(t * tempo * 0.7 + seed);
    const wave2 = Math.sin(t * tempo * 0.5 + seed * 2);
    hipRotY = wave * 0.15;
    const ep = M.epaulement(hipRotY);
    spineTargetY = ep.spine;
    headTargetY = ep.headY + wave2 * 0.1;
    headTargetZ = ep.headTilt;
    // Cycling through arm positions
    const aIdx = Math.floor((t * tempo * 0.2 + seed) % 5);
    const aNext = (aIdx + 1) % 5;
    const aT = ((t * tempo * 0.2 + seed) % 1);
    lArmPos = M.lerpArm(M.armPositions[aIdx], M.armPositions[aNext], M.easeInOut(aT));
    rArmPos = M.lerpArm(M.armPositions[(aIdx+2)%5], M.armPositions[(aNext+2)%5], M.easeInOut(aT));
    // Weight shift
    const ws = M.weightShift(wave * 0.5);
    hipRotZ = ws.hipTilt;
    hipY = 0.92 + wave2 * 0.02;
    // Occasional développé
    if (wave > 0.7) {
        rHipX = -(wave - 0.7) / 0.3 * 0.5;
        rKnee = Math.max(0, (wave - 0.85) / 0.15) * 0.8;
    }
}

// === Apply targets through follow-through system ===
M.followThrough(ft.headY, headTargetY, dt, ftP);
M.followThrough(ft.headX, headTargetX, dt, ftP);
M.followThrough(ft.headZ, headTargetZ, dt, ftP);
M.followThrough(ft.spineY, spineTargetY, dt, ftP);
M.followThrough(ft.hipZ, hipRotZ, dt, ftP);

// Arms through successive motion (shoulder leads, elbow follows, wrist trails)
M.successive(S.lArmChain, lArmPos[0], dt, 6, 0.1);
M.successive(S.rArmChain, rArmPos[0], dt, 6, 0.1);

M.followThrough(ft.lShoulderX, lArmPos[0], dt, ftP);
M.followThrough(ft.rShoulderX, rArmPos[0], dt, ftP);
M.followThrough(ft.lShoulderZ, lArmPos[1], dt, ftP);
M.followThrough(ft.rShoulderZ, rArmPos[1], dt, ftP);
M.followThrough(ft.lElbow, lArmPos[2], dt, ftP);
M.followThrough(ft.rElbow, rArmPos[2], dt, ftP);
M.followThrough(ft.lWrist, lArmPos[3], dt, ftP);
M.followThrough(ft.rWrist, rArmPos[3], dt, ftP);

// === APPLY TO SKELETON ===

// Hips
b.hips.position.y = hipY;
b.hips.rotation.y = hipRotY;
b.hips.rotation.z = ft.hipZ.value;

// Spine (counter-rotation via épaulement)
b.upperTorsoPivot.rotation.y = ft.spineY.value;
// Breathing modulates chest
const bVal = br.value;
b.upperTorsoPivot.rotation.x = bVal * 0.015;
const bScale = 1.0 + bVal * 0.008;
b.upperTorsoPivot.scale.set(1.0, bScale, 1.0 + bVal * 0.005);

// Head — follow-through gives organic lag
b.headPivot.rotation.y = ft.headY.value;
b.headPivot.rotation.x = ft.headX.value;
b.headPivot.rotation.z = ft.headZ.value;
// Neck follows head with less amplitude
b.neckPivot.rotation.y = ft.headY.value * 0.4;

// Arms — successive motion: shoulder moves first, elbow lags, wrist trails
b.leftArm.shoulderPivot.rotation.x = ft.lShoulderX.value;
b.leftArm.shoulderPivot.rotation.z = ft.lShoulderZ.value;
b.leftArm.elbowPivot.rotation.x = ft.lElbow.value;
b.leftArm.wristPivot.rotation.x = ft.lWrist.value;
// Wrist trails shoulder rotation for successive feel
b.leftArm.wristPivot.rotation.y = S.lArmChain[2].current * 0.15;

b.rightArm.shoulderPivot.rotation.x = ft.rShoulderX.value;
b.rightArm.shoulderPivot.rotation.z = ft.rShoulderZ.value;
b.rightArm.elbowPivot.rotation.x = ft.rElbow.value;
b.rightArm.wristPivot.rotation.x = ft.rWrist.value;
b.rightArm.wristPivot.rotation.y = S.rArmChain[2].current * 0.15;

// Legs
b.leftLeg.hipPivot.rotation.x = lHipX;
b.rightLeg.hipPivot.rotation.x = rHipX;
b.leftLeg.kneePivot.rotation.x = lKnee;
b.rightLeg.kneePivot.rotation.x = rKnee;
b.leftLeg.anklePivot.rotation.x = lAnkle;
b.rightLeg.anklePivot.rotation.x = rAnkle;

// Fingers — pianist-style independent movement via motion library
// Choreography modulates intensity: port_de_bras and free get expressive fingers,
// others get softer ballet-hand patterns
const fingerIntensity = (C === 'port_de_bras' || C === 'free') ? 1.0
    : (C === 'adagio' || C === 'reverence') ? 0.5 : 0.3;
if (b.leftArm.fingers && S.lFingerState) {
    // Scale pattern curl amounts by intensity
    const lPat = S.lFingerPattern.map(p => ({...p, curl: p.curl * fingerIntensity}));
    M.animateFingers(b.leftArm, S.lFingerState, lPat, t, dt, tempo);
}
if (b.rightArm.fingers && S.rFingerState) {
    const rPat = S.rFingerPattern.map(p => ({...p, curl: p.curl * fingerIntensity}));
    M.animateFingers(b.rightArm, S.rFingerState, rPat, t, dt, tempo);
}

// === Blink ===
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
            S.blinkTimer = 2 + Math.random() * 5;
            for (const eye of S.eyes) eye.scale.set(1,1,1);
        }
    }
}

// === Gaze: dancers look at imaginary audience ===
const gazeY = Math.sin(t * 0.2 + seed) * 0.08;
const gazeX = 0.05;
for (const eye of S.eyes) {
    eye.rotation.x += (gazeX - eye.rotation.x) * dt * 2;
    eye.rotation.y += (gazeY - eye.rotation.y) * dt * 2;
}
"""
