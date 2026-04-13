"""Seed the Velour Metropolis — buildings, L-system plants, and V6 NPCs.

Registers four reusable scripts (available to all worlds):
  1. procedural-building (start) — parameterized buildings
  2. lsystem-plant (start) — L-system trees, bushes, palms
  3. humanoid-builder-v6 (start) — detailed face with 4 LOD tiers
  4. npc-lod-manager (update) — FPS + distance LOD switching

Then creates a demo "Velour Metropolis" world with mixed buildings,
plants, and V6 NPCs.
"""

from django.core.management.base import BaseCommand

from aether.models import Entity, EntityScript, Script, World

import math
import random as rng


# ===================================================================
# 1. PROCEDURAL BUILDING SCRIPT (start)
# ===================================================================

BUILDING_SCRIPT = r"""
const S = ctx.state;
const P = ctx.props;
const type = P.type || 'house';
const floors = P.floors || 2;
const w = P.width || 6;
const d = P.depth || 6;
const floorH = P.floorHeight || 3.2;
const wallC = new THREE.Color(P.color || '#b0a898');
const trimC = new THREE.Color(P.trim || '#808080');
const roofC = new THREE.Color(P.roof || '#6a4030');
const windowC = new THREE.Color(P.windowColor || '#a8c8e0');
const windowLit = P.windowLit || 0.3; // fraction of windows that glow

if (ctx.entity.isMesh) {
    ctx.entity.material.visible = false;
    ctx.entity.castShadow = false;
}

function part(geo, mat) {
    const m = new THREE.Mesh(geo, mat);
    m.castShadow = true; m.receiveShadow = true;
    return m;
}
function ns(m) { m.castShadow = false; m.receiveShadow = false; return m; }

const root = new THREE.Group();
ctx.entity.add(root);
S.building = root;

// --- Window texture generator ---
function windowTex(tilesX, tilesY, baseColor, winColor, litFrac) {
    const c = document.createElement('canvas');
    const px = tilesX * 8; c.width = px;
    const py = tilesY * 8; c.height = py;
    const g = c.getContext('2d');
    g.fillStyle = '#' + baseColor.getHexString();
    g.fillRect(0, 0, px, py);
    for (let y = 0; y < tilesY; y++) {
        for (let x = 0; x < tilesX; x++) {
            const lit = Math.random() < litFrac;
            const wc = lit ? '#ffe880' : '#' + winColor.getHexString();
            g.fillStyle = wc;
            g.globalAlpha = lit ? 0.9 : 0.7;
            g.fillRect(x*8+1, y*8+1, 6, 5);
            g.globalAlpha = 1;
        }
    }
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    return tex;
}

const wallM = new THREE.MeshStandardMaterial({color: wallC, roughness: 0.85});
const trimM = new THREE.MeshStandardMaterial({color: trimC, roughness: 0.7});
const roofM = new THREE.MeshStandardMaterial({color: roofC, roughness: 0.75});
const h = floors * floorH;

if (type === 'house') {
    // Main body
    const body = part(new THREE.BoxGeometry(w, h, d), wallM.clone());
    body.material.map = windowTex(Math.ceil(w), floors, wallC, windowC, windowLit);
    body.position.y = h / 2;
    root.add(body);
    // Peaked roof
    const roofGeo = new THREE.ConeGeometry(w * 0.75, floorH * 0.8, 4);
    const rf = part(roofGeo, roofM);
    rf.position.y = h + floorH * 0.4;
    rf.rotation.y = Math.PI / 4;
    root.add(rf);
    // Door
    const door = ns(part(new THREE.BoxGeometry(1.2, 2.2, 0.05),
        new THREE.MeshStandardMaterial({color: '#4a3020', roughness: 0.8})));
    door.position.set(0, 1.1, d/2 + 0.03);
    root.add(door);
    // Chimney
    if (Math.random() > 0.4) {
        const ch = part(new THREE.BoxGeometry(0.6, floorH*0.7, 0.6), trimM);
        ch.position.set(w*0.25, h + floorH*0.3, -d*0.2);
        root.add(ch);
    }

} else if (type === 'shop') {
    const body = part(new THREE.BoxGeometry(w, h, d), wallM.clone());
    body.material.map = windowTex(Math.ceil(w), floors, wallC, windowC, windowLit);
    body.position.y = h / 2;
    root.add(body);
    // Flat roof with parapet
    const parapet = part(new THREE.BoxGeometry(w+0.3, 0.4, d+0.3), trimM);
    parapet.position.y = h + 0.2;
    root.add(parapet);
    // Awning
    const awn = ns(part(new THREE.BoxGeometry(w*0.9, 0.08, 1.5),
        new THREE.MeshStandardMaterial({color: P.awningColor || '#c84040', roughness: 0.6})));
    awn.position.set(0, floorH*0.85, d/2 + 0.75);
    awn.rotation.x = 0.15;
    root.add(awn);
    // Sign
    const sign = ns(part(new THREE.BoxGeometry(w*0.6, 0.8, 0.06),
        new THREE.MeshStandardMaterial({color: '#e8d8c0', roughness: 0.5})));
    sign.position.set(0, floorH + 0.8, d/2 + 0.04);
    root.add(sign);
    // Large display window
    const dispW = ns(part(new THREE.BoxGeometry(w*0.7, floorH*0.5, 0.04),
        new THREE.MeshPhysicalMaterial({color: windowC, roughness: 0.02, transmission: 0.6, thickness: 0.1})));
    dispW.position.set(0, floorH*0.45, d/2 + 0.03);
    root.add(dispW);

} else if (type === 'skyscraper') {
    // Glass curtain wall
    const winTex = windowTex(Math.ceil(w*2), floors, new THREE.Color('#384050'), windowC, windowLit);
    const glassM = new THREE.MeshPhysicalMaterial({
        color: '#506878', roughness: 0.1, metalness: 0.3,
        map: winTex, clearcoat: 0.5, clearcoatRoughness: 0.1,
    });
    const body = part(new THREE.BoxGeometry(w, h, d), glassM);
    body.position.y = h / 2;
    root.add(body);
    // Crown/spire
    const crown = part(new THREE.BoxGeometry(w*0.6, floorH, d*0.6), trimM);
    crown.position.y = h + floorH/2;
    root.add(crown);
    if (floors > 8) {
        const spire = part(new THREE.ConeGeometry(0.3, floorH*2, 8), trimM);
        spire.position.y = h + floorH*2;
        root.add(spire);
    }
    // Base podium
    const pod = part(new THREE.BoxGeometry(w+2, floorH*0.4, d+2),
        new THREE.MeshStandardMaterial({color: '#383838', roughness: 0.6}));
    pod.position.y = floorH*0.2;
    root.add(pod);
    // Entrance
    const ent = ns(part(new THREE.BoxGeometry(3, 3.5, 0.06),
        new THREE.MeshPhysicalMaterial({color: '#90b0c8', transmission: 0.5, thickness: 0.1})));
    ent.position.set(0, 1.75, d/2 + 1.04);
    root.add(ent);

} else if (type === 'factory') {
    const body = part(new THREE.BoxGeometry(w, h, d), wallM);
    body.position.y = h / 2;
    root.add(body);
    // Sawtooth roof
    const teeth = Math.ceil(w / 4);
    for (let i = 0; i < teeth; i++) {
        const tx = -w/2 + (i+0.5) * (w/teeth);
        const tooth = part(new THREE.BoxGeometry(w/teeth*0.95, floorH*0.5, d),
            new THREE.MeshStandardMaterial({color: '#607068', roughness: 0.8}));
        tooth.position.set(tx, h + floorH*0.25, 0);
        tooth.rotation.z = 0.15;
        root.add(tooth);
    }
    // Smokestacks
    const nStacks = 1 + Math.floor(Math.random() * 3);
    for (let i = 0; i < nStacks; i++) {
        const sx = -w*0.3 + i * w*0.3;
        const stack = part(new THREE.CylinderGeometry(0.4, 0.5, h*0.6, 8), trimM);
        stack.position.set(sx, h + h*0.3, -d*0.3);
        root.add(stack);
    }
    // Loading dock
    const dock = part(new THREE.BoxGeometry(w*0.4, 1.2, 1.5),
        new THREE.MeshStandardMaterial({color: '#505050', roughness: 0.8}));
    dock.position.set(w*0.2, 0.6, d/2 + 0.75);
    root.add(dock);

} else if (type === 'warehouse') {
    // Quonset hut shape
    const body = part(new THREE.BoxGeometry(w, h*0.7, d), wallM);
    body.position.y = h*0.35;
    root.add(body);
    const roof = part(new THREE.CylinderGeometry(w/2, w/2, d, 12, 1, false, 0, Math.PI),
        new THREE.MeshStandardMaterial({color: '#707878', roughness: 0.6, metalness: 0.2}));
    roof.position.y = h*0.7;
    roof.rotation.set(Math.PI/2, 0, Math.PI/2);
    root.add(roof);
    // Roll-up door
    const door = ns(part(new THREE.BoxGeometry(w*0.35, h*0.55, 0.05),
        new THREE.MeshStandardMaterial({color: '#404848', roughness: 0.7})));
    door.position.set(0, h*0.275, d/2 + 0.03);
    root.add(door);

} else if (type === 'church') {
    const body = part(new THREE.BoxGeometry(w, h, d), wallM);
    body.position.y = h/2;
    root.add(body);
    // Steeple
    const tower = part(new THREE.BoxGeometry(w*0.35, h*0.8, w*0.35), wallM);
    tower.position.set(0, h + h*0.4, -d*0.2);
    root.add(tower);
    const spire = part(new THREE.ConeGeometry(w*0.25, h*0.5, 4), roofM);
    spire.position.set(0, h*1.8 + h*0.25, -d*0.2);
    spire.rotation.y = Math.PI/4;
    root.add(spire);
    // Main roof
    const mainRoof = part(new THREE.ConeGeometry(w*0.72, h*0.4, 4), roofM);
    mainRoof.position.y = h + h*0.2;
    mainRoof.rotation.y = Math.PI/4;
    root.add(mainRoof);
    // Arched doorway
    const arch = ns(part(new THREE.TorusGeometry(1, 0.15, 6, 12, Math.PI),
        new THREE.MeshStandardMaterial({color: '#605040', roughness: 0.8})));
    arch.position.set(0, 2, d/2 + 0.1);
    root.add(arch);
    // Rose window
    const rose = ns(part(new THREE.RingGeometry(0.3, 0.8, 12),
        new THREE.MeshStandardMaterial({color: '#4060a0', roughness: 0.3, emissive: '#203050', emissiveIntensity: 0.3})));
    rose.position.set(0, h*0.7, d/2 + 0.05);
    root.add(rose);

} else if (type === 'tower') {
    // Cylindrical tower with crenellations
    const body = part(new THREE.CylinderGeometry(w/2, w/2*1.1, h, 12), wallM);
    body.position.y = h/2;
    root.add(body);
    // Crenellations
    const nCren = 8;
    for (let i = 0; i < nCren; i++) {
        const a = (i / nCren) * Math.PI * 2;
        const cr = part(new THREE.BoxGeometry(0.8, 0.8, 0.4), wallM);
        cr.position.set(Math.sin(a)*w/2, h+0.4, Math.cos(a)*w/2);
        cr.rotation.y = a;
        root.add(cr);
    }
    // Conical roof
    const rf = part(new THREE.ConeGeometry(w/2*1.05, h*0.3, 12), roofM);
    rf.position.y = h + h*0.15 + 0.8;
    root.add(rf);
    // Arrow slit windows
    for (let f = 0; f < floors; f++) {
        const a = (f * 1.3) % (Math.PI*2);
        const slit = ns(part(new THREE.BoxGeometry(0.15, 0.7, 0.1),
            new THREE.MeshStandardMaterial({color: '#202020'})));
        slit.position.set(Math.sin(a)*(w/2+0.04), floorH*(f+0.5), Math.cos(a)*(w/2+0.04));
        slit.rotation.y = a;
        root.add(slit);
    }
}

S.built = true;
"""


# ===================================================================
# 2. L-SYSTEM PLANT SCRIPT (start)
# ===================================================================

PLANT_SCRIPT = r"""
const S = ctx.state;
const P = ctx.props;
const species = P.species || 'oak';
const iterations = Math.min(P.iterations || 4, 6);
const scale = P.scale || 1.0;
const trunkColor = new THREE.Color(P.trunk || '#5a4020');
const leafColor = new THREE.Color(P.leaf || '#2a6818');
const leafColor2 = new THREE.Color(P.leaf2 || '#3a7828');

if (ctx.entity.isMesh) {
    ctx.entity.material.visible = false;
    ctx.entity.castShadow = false;
}

// --- L-system presets ---
const presets = {
    oak: {
        axiom: 'F',
        rules: {'F': 'FF+[+F-F-F]-[-F+F+F]'},
        angle: 22.5, lengthFactor: 0.65, startLength: 0.8,
        trunkTaper: 0.7, leafSize: 0.35, leafDensity: 0.6,
    },
    pine: {
        axiom: 'F',
        rules: {'F': 'F[+F][-F]F[+F][-F]'},
        angle: 25, lengthFactor: 0.55, startLength: 0.6,
        trunkTaper: 0.65, leafSize: 0.25, leafDensity: 0.8,
        leafShape: 'cone',
    },
    birch: {
        axiom: 'F',
        rules: {'F': 'F[-F][+F]F'},
        angle: 30, lengthFactor: 0.7, startLength: 0.7,
        trunkTaper: 0.75, leafSize: 0.2, leafDensity: 0.5,
    },
    palm: {
        axiom: 'FFFFF',
        rules: {'F': 'F'},
        angle: 0, lengthFactor: 1.0, startLength: 0.9,
        trunkTaper: 0.92, leafSize: 0.5, leafDensity: 0,
        fronds: true,
    },
    bush: {
        axiom: 'F',
        rules: {'F': 'F[+F]F[-F][F]'},
        angle: 35, lengthFactor: 0.6, startLength: 0.3,
        trunkTaper: 0.6, leafSize: 0.18, leafDensity: 0.9,
    },
    willow: {
        axiom: 'F',
        rules: {'F': 'FF[-F+F+F][+F-F]'},
        angle: 18, lengthFactor: 0.68, startLength: 0.75,
        trunkTaper: 0.72, leafSize: 0.15, leafDensity: 0.7,
        droop: 0.15,
    },
    cactus: {
        axiom: 'F',
        rules: {'F': 'F[+F][-F]'},
        angle: 90, lengthFactor: 0.5, startLength: 0.6,
        trunkTaper: 0.85, leafSize: 0, leafDensity: 0,
        trunkIsGreen: true,
    },
};

const preset = presets[species] || presets.oak;

// --- L-system string rewriting ---
let str = preset.axiom;
for (let i = 0; i < iterations; i++) {
    let next = '';
    for (const ch of str) {
        next += preset.rules[ch] || ch;
    }
    str = next;
}

// --- Turtle interpretation ---
const root = new THREE.Group();
ctx.entity.add(root);

const trunkM = new THREE.MeshStandardMaterial({
    color: preset.trunkIsGreen ? '#2a6030' : trunkColor, roughness: 0.85
});
const leafM = new THREE.MeshStandardMaterial({color: leafColor, roughness: 0.7});
const leafM2 = new THREE.MeshStandardMaterial({color: leafColor2, roughness: 0.7});

const stack = [];
let pos = new THREE.Vector3(0, 0, 0);
let dir = new THREE.Vector3(0, 1, 0);
let right = new THREE.Vector3(1, 0, 0);
let len = preset.startLength * scale;
let radius = 0.06 * scale;
let depth = 0;

const angle = preset.angle * Math.PI / 180;
const droop = preset.droop || 0;
const maxSegs = 800; // budget cap
let segCount = 0;

function addBranch(from, to, r) {
    if (segCount >= maxSegs) return;
    const diff = new THREE.Vector3().subVectors(to, from);
    const length = diff.length();
    if (length < 0.01) return;
    const geo = new THREE.CylinderGeometry(r * preset.trunkTaper, r, length, 5, 1);
    const mesh = new THREE.Mesh(geo, trunkM);
    mesh.castShadow = true; mesh.receiveShadow = true;
    const mid = new THREE.Vector3().addVectors(from, to).multiplyScalar(0.5);
    mesh.position.copy(mid);
    // Orient cylinder to point from→to
    const axis = new THREE.Vector3(0, 1, 0);
    const q = new THREE.Quaternion().setFromUnitVectors(axis, diff.clone().normalize());
    mesh.quaternion.copy(q);
    root.add(mesh);
    segCount++;
}

function addLeaf(p, size) {
    if (segCount >= maxSegs) return;
    if (preset.leafSize <= 0) return;
    const geo = preset.leafShape === 'cone'
        ? new THREE.ConeGeometry(size, size*2, 6)
        : new THREE.SphereGeometry(size, 6, 4);
    const m = Math.random() > 0.5 ? leafM : leafM2;
    const mesh = new THREE.Mesh(geo, m);
    mesh.castShadow = true; mesh.receiveShadow = false;
    mesh.position.copy(p);
    root.add(mesh);
    segCount++;
}

// Simple deterministic seed for variation
let rngState = (P.seed || 42) * 127.1;
function rnd() { rngState = (rngState * 16807 + 0.5) % 2147483647; return rngState / 2147483647; }

for (const ch of str) {
    if (segCount >= maxSegs) break;
    if (ch === 'F') {
        const droopV = new THREE.Vector3(0, -droop * depth, 0);
        const jitter = new THREE.Vector3((rnd()-0.5)*0.05, 0, (rnd()-0.5)*0.05);
        const end = pos.clone().add(dir.clone().multiplyScalar(len)).add(droopV).add(jitter);
        addBranch(pos, end, radius);
        pos.copy(end);
        // Leaves at branch tips / along branches
        if (depth >= 2 && rnd() < preset.leafDensity) {
            addLeaf(pos, preset.leafSize * scale * (0.7 + rnd()*0.6));
        }
    } else if (ch === '+') {
        // Rotate direction around a random-ish axis incorporating 'right'
        const rotAxis = new THREE.Vector3().crossVectors(dir, right).normalize();
        if (rotAxis.length() < 0.01) rotAxis.set(0, 0, 1);
        const q = new THREE.Quaternion().setFromAxisAngle(rotAxis, angle + (rnd()-0.5)*angle*0.3);
        dir.applyQuaternion(q).normalize();
    } else if (ch === '-') {
        const rotAxis = new THREE.Vector3().crossVectors(dir, right).normalize();
        if (rotAxis.length() < 0.01) rotAxis.set(0, 0, 1);
        const q = new THREE.Quaternion().setFromAxisAngle(rotAxis, -angle + (rnd()-0.5)*angle*0.3);
        dir.applyQuaternion(q).normalize();
    } else if (ch === '[') {
        stack.push({
            pos: pos.clone(), dir: dir.clone(), right: right.clone(),
            len, radius, depth
        });
        len *= preset.lengthFactor;
        radius *= preset.trunkTaper;
        depth++;
        // Slight random twist on branch
        const twist = new THREE.Quaternion().setFromAxisAngle(dir, (rnd()-0.5)*Math.PI*0.5);
        right.applyQuaternion(twist).normalize();
    } else if (ch === ']') {
        if (stack.length > 0) {
            // Leaf cluster at branch tip
            if (depth >= 2 && preset.leafDensity > 0) {
                addLeaf(pos, preset.leafSize * scale * (0.8 + rnd()*0.4));
            }
            const s = stack.pop();
            pos.copy(s.pos); dir.copy(s.dir); right.copy(s.right);
            len = s.len; radius = s.radius; depth = s.depth;
        }
    }
}

// Palm fronds (special case)
if (preset.fronds) {
    const topY = pos.y;
    const nFronds = 8 + Math.floor(rnd() * 5);
    for (let i = 0; i < nFronds; i++) {
        const a = (i / nFronds) * Math.PI * 2 + rnd() * 0.3;
        const frondLen = (1.5 + rnd()) * scale;
        const droop2 = 0.3 + rnd() * 0.4;
        const segs = 5;
        let fp = new THREE.Vector3(0, topY, 0);
        for (let s = 0; s < segs; s++) {
            const t = s / segs;
            const ep = new THREE.Vector3(
                Math.sin(a) * frondLen * (t + 1/segs),
                topY - droop2 * t * t * frondLen,
                Math.cos(a) * frondLen * (t + 1/segs)
            );
            addBranch(fp, ep, 0.02 * scale * (1 - t*0.5));
            fp = ep;
            // Leaf segments along frond
            if (s >= 1) {
                const lp = ep.clone();
                lp.y += 0.05;
                addLeaf(lp, 0.2 * scale * (1 - t*0.3));
            }
        }
    }
}

S.built = true;
S.plant = root;
"""


# ===================================================================
# 3. NPC LOD MANAGER SCRIPT (update)
# ===================================================================

LOD_MANAGER_SCRIPT = r"""
const S = ctx.state;
if (!S.built || !S.faceLOD) return;

// --- Global FPS tracking (shared across all NPCs) ---
if (!window._lodFPS) {
    window._lodFPS = {frames: new Float32Array(60), idx: 0, avg: 60};
}
const f = window._lodFPS;
f.frames[f.idx] = 1.0 / Math.max(ctx.deltaTime, 0.001);
f.idx = (f.idx + 1) % 60;
let sum = 0;
for (let i = 0; i < 60; i++) sum += f.frames[i];
f.avg = sum / 60;

// --- Throttle: re-evaluate every 10 frames ---
if (!S._lodFrame) S._lodFrame = 0;
S._lodFrame++;
if (S._lodFrame % 10 !== 0) return;

// --- Distance to camera ---
const cam = ctx.camera;
const ep = ctx.entity.position;
const dx = cam.position.x - ep.x;
const dz = cam.position.z - ep.z;
const dist = Math.sqrt(dx*dx + dz*dz);
const fps = f.avg;

// --- Determine target tier ---
let target = 3;
if      (dist < 4  && fps >= 40) target = 0;
else if (dist < 12 && fps >= 28) target = 1;
else if (dist < 25 && fps >= 18) target = 2;

// FPS emergency downgrade
if      (fps < 18) target = Math.max(target, 3);
else if (fps < 28) target = Math.max(target, 2);

const lod = S.faceLOD;
if (target === lod.currentTier) { S._lodPending = null; return; }

// --- Hysteresis: 5 consecutive checks wanting same tier ---
if (!S._lodPending || S._lodPending.tier !== target) {
    S._lodPending = {tier: target, count: 1};
    return;
}
S._lodPending.count++;
if (S._lodPending.count < 5) return;
S._lodPending = null;

// --- Commit tier change ---
lod.currentTier = target;
if (lod.faceUltra)   lod.faceUltra.visible   = (target === 0);
if (lod.faceHigh)    lod.faceHigh.visible     = (target <= 1);
if (lod.faceMedium)  lod.faceMedium.visible   = (target === 2);
if (lod.faceLow)     lod.faceLow.visible      = (target === 3);

// Swap head mesh
if (lod.heads) {
    for (let i = 0; i < lod.heads.length; i++) {
        lod.heads[i].visible = (i === target);
    }
}

// Material quality swap: ultra/high get physical, medium/low get standard
if (lod.faceHigh && lod.skinMats) {
    const usePhysical = (target <= 1);
    lod.faceHigh.traverse(c => {
        if (c.isMesh && c.userData.skinSlot) {
            c.material = usePhysical ? lod.skinMats.physical : lod.skinMats.standard;
        }
    });
}
"""


# ===================================================================
# 4. HUMANOID V6 FACE BUILDER (start)
#    Extreme facial detail with 4 LOD tiers.
#    Body construction is inherited from V5; this replaces the face.
# ===================================================================

HUMANOID_V6_SCRIPT = r"""
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

const KH = 1.3;
const KE = 1.45;
const KN = 0.7;
const KM = 0.8;
const HEAD_R = 0.12 * KH;
const HEAD_CY = 0.13 * KH;

function part(g, m) { const o = new THREE.Mesh(g, m); o.castShadow=true; o.receiveShadow=true; return o; }
function ns(m) { m.castShadow=false; m.receiveShadow=false; return m; }
function pivot(x,y,z) { const g = new THREE.Group(); g.position.set(x,y,z); return g; }

// === SKIN TEXTURE GENERATORS ===
// Zone-aware skin canvas: warm on cheeks/nose, cooler on temples/jaw
function skinTexture(w, h, base, zone) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    const id = g.createImageData(w, h);
    const br = base.r*255, bg = base.g*255, bb = base.b*255;
    // Zone tint: 'warm' adds red, 'cool' adds blue, 'neutral' no shift
    const wr = zone === 'warm' ? 8 : zone === 'cool' ? -4 : 0;
    const wb = zone === 'warm' ? -4 : zone === 'cool' ? 6 : 0;
    for (let i = 0; i < id.data.length; i += 4) {
        const n = (Math.random()-0.5) * 12; // pore-level noise
        // Subtle pore pattern: darken every ~4th pixel cluster
        const px = (i/4) % w, py = Math.floor((i/4) / w);
        const pore = ((px*7+py*13) % 5 === 0) ? -6 : 0;
        id.data[i]   = Math.max(0, Math.min(255, br + n + wr + pore));
        id.data[i+1] = Math.max(0, Math.min(255, bg + n + pore));
        id.data[i+2] = Math.max(0, Math.min(255, bb + n + wb + pore));
        id.data[i+3] = 255;
    }
    g.putImageData(id, 0, 0);
    return new THREE.CanvasTexture(c);
}

// Roughness map: T-zone shinier, cheeks rougher
function roughnessMap(w, h) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    // Base roughness (medium)
    g.fillStyle = '#999';
    g.fillRect(0, 0, w, h);
    // T-zone (center strip): shinier
    g.fillStyle = '#777';
    g.fillRect(w*0.35, 0, w*0.3, h);
    // Cheek area: rougher
    g.fillStyle = '#bbb';
    g.beginPath(); g.arc(w*0.2, h*0.5, w*0.15, 0, Math.PI*2); g.fill();
    g.beginPath(); g.arc(w*0.8, h*0.5, w*0.15, 0, Math.PI*2); g.fill();
    return new THREE.CanvasTexture(c);
}

// === MATERIALS ===
const faceSkinC = new THREE.Color().copy(skinC).lerp(new THREE.Color('#ffaa99'), 0.04);
const warmSkinC = new THREE.Color().copy(skinC).lerp(new THREE.Color('#ff8877'), 0.08);
const coolSkinC = new THREE.Color().copy(skinC).lerp(new THREE.Color('#8899aa'), 0.05);
const handSkinC = new THREE.Color().copy(skinC).lerp(new THREE.Color('#ffe0d0'), 0.06);
const neckSkinC = new THREE.Color().copy(skinC).multiplyScalar(0.96);
const lipC = new THREE.Color().copy(skinC).lerp(new THREE.Color('#cc6666'), 0.25);
const aoC = new THREE.Color().copy(skinC).multiplyScalar(0.8);
const creaseSkinC = new THREE.Color().copy(skinC).multiplyScalar(0.88);

// Physical skin material (tier 0-1)
const skinPhysM = new THREE.MeshPhysicalMaterial({
    color: faceSkinC,
    map: skinTexture(64, 64, faceSkinC, 'neutral'),
    roughnessMap: roughnessMap(32, 32),
    roughness: 0.5,
    metalness: 0,
    sheen: 0.5,
    sheenRoughness: 0.35,
    sheenColor: new THREE.Color().copy(skinC).lerp(new THREE.Color('#ffccbb'), 0.3),
    clearcoat: 0.04,
    clearcoatRoughness: 0.5,
});

// Standard skin material (tier 2)
const skinStdM = new THREE.MeshStandardMaterial({
    color: faceSkinC, roughness: 0.55, metalness: 0,
});

// Lambert skin material (tier 3)
const skinLambM = new THREE.MeshLambertMaterial({color: faceSkinC});

// Warm zone physical (cheeks, nose, ears)
const warmPhysM = new THREE.MeshPhysicalMaterial({
    color: warmSkinC,
    map: skinTexture(32, 32, warmSkinC, 'warm'),
    roughness: 0.55, sheen: 0.4, sheenRoughness: 0.4,
    sheenColor: new THREE.Color('#ffbbaa'),
});

// Crease/AO material
const creaseM = new THREE.MeshStandardMaterial({color: creaseSkinC, roughness: 0.7});
const aoM = new THREE.MeshStandardMaterial({color: aoC, roughness: 0.8, transparent: true, opacity: 0.4});

// Lip material
const lipM = new THREE.MeshPhysicalMaterial({
    color: lipC, roughness: 0.3, sheen: 0.7,
    sheenColor: new THREE.Color().copy(lipC).lerp(new THREE.Color('#ff8888'), 0.3),
    sheenRoughness: 0.2, clearcoat: 0.15, clearcoatRoughness: 0.3,
});

// Shirt, pants, shoe materials
const shirtM = new THREE.MeshStandardMaterial({color: shirtC, roughness: 0.6});
const pantsM = new THREE.MeshStandardMaterial({color: pantsC, roughness: 0.7});
const shoeM  = new THREE.MeshStandardMaterial({color: shoesC, roughness: 0.65});
const neckM  = new THREE.MeshStandardMaterial({color: neckSkinC, roughness: 0.6});
const handM  = new THREE.MeshStandardMaterial({color: handSkinC, roughness: 0.55});

// ============================================================
// BODY CONSTRUCTION (compact — same skeleton as V5)
// ============================================================
const hipsPivot = pivot(0, 0.92 * HS, 0);
ctx.entity.add(hipsPivot);

// Lower torso
const hips = part(new THREE.BoxGeometry(0.28*HW, 0.14, 0.16), shirtM);
hips.position.y = 0;
hipsPivot.add(hips);

// Upper torso
const upperTorsoPivot = pivot(0, 0.08, 0);
hipsPivot.add(upperTorsoPivot);
const chest = part(new THREE.BoxGeometry(0.32*SW, 0.22, 0.18), shirtM);
upperTorsoPivot.add(chest);

// Neck
const neckPivot = pivot(0, 0.14, 0);
upperTorsoPivot.add(neckPivot);
const neck = part(new THREE.CylinderGeometry(0.04, 0.05, 0.08, 8), neckM);
neckPivot.add(neck);

// Head pivot
const headPivot = pivot(0, 0.06, 0);
neckPivot.add(headPivot);

// ============================================================
// FACE LOD GROUPS — built into headPivot
// ============================================================
const faceUltra  = new THREE.Group(); faceUltra.name = 'faceUltra';
const faceHigh   = new THREE.Group(); faceHigh.name = 'faceHigh';
const faceMedium = new THREE.Group(); faceMedium.name = 'faceMedium';
const faceLow    = new THREE.Group(); faceLow.name = 'faceLow';

faceUltra.visible = false;
faceMedium.visible = false;
faceLow.visible = false;
// faceHigh visible by default (tier 1 is starting tier)

headPivot.add(faceUltra);
headPivot.add(faceHigh);
headPivot.add(faceMedium);
headPivot.add(faceLow);

// --- Head spheres per tier ---
const heads = [];
const headSegs = [48, 32, 12, 6];
for (let tier = 0; tier < 4; tier++) {
    const hMat = tier <= 1 ? skinPhysM : tier === 2 ? skinStdM : skinLambM;
    const hd = ns(part(new THREE.SphereGeometry(HEAD_R, headSegs[tier], headSegs[tier]), hMat));
    hd.position.y = HEAD_CY;
    hd.scale.set(1.0, 0.98, 0.96);
    hd.visible = (tier === 1);
    headPivot.add(hd);
    heads.push(hd);
}

// ============================================================
// TIER 1 (HIGH) — enhanced V5 face features
// ============================================================

// Jaw
const jaw = ns(part(
    new THREE.SphereGeometry(0.1*KH, 24, 12, 0, Math.PI*2, Math.PI*0.55, Math.PI*0.45),
    skinPhysM
));
jaw.position.set(0, 0.05*KH, -0.02*KH);
jaw.scale.set(JW*0.95, 0.7, 0.55);
jaw.userData.skinSlot = true;
faceHigh.add(jaw);

// Chin
const chin = ns(part(
    new THREE.SphereGeometry(0.03*KH, 12, 8, 0, Math.PI*2, 0, Math.PI*0.5),
    skinPhysM
));
chin.position.set(0, 0.02*KH, 0.065*KH);
chin.scale.set(JW*0.8, 0.9, 0.5);
chin.userData.skinSlot = true;
faceHigh.add(chin);

// Forehead
const forehead = ns(part(
    new THREE.SphereGeometry(0.11*KH, 20, 10, 0, Math.PI*2, 0, Math.PI*0.35),
    skinPhysM
));
forehead.position.set(0, 0.2*KH*FH, -0.02*KH);
forehead.scale.set(1.0, 1.0, 0.45);
forehead.userData.skinSlot = true;
faceHigh.add(forehead);

// Cheeks
for (const side of [-1, 1]) {
    const cheek = ns(part(new THREE.SphereGeometry(0.04*KH, 10, 8), warmPhysM));
    cheek.position.set(side*0.065*KH, 0.09*KH, 0.06*KH);
    cheek.scale.set(1.0*CF, 0.7, 0.4);
    cheek.name = 'cheek_' + (side < 0 ? 'L' : 'R');
    faceHigh.add(cheek);
}

// Nose — bridge + tip + nostrils + alar
const noseBridge = ns(part(
    new THREE.CylinderGeometry(0.012*KN, 0.016*KN, 0.05*KH, 8),
    skinPhysM
));
noseBridge.position.set(0, 0.1*KH, 0.1*KH);
noseBridge.rotation.x = 0.3;
noseBridge.userData.skinSlot = true;
faceHigh.add(noseBridge);

const noseTip = ns(part(new THREE.SphereGeometry(0.016*KN, 10, 8), warmPhysM));
noseTip.position.set(0, 0.075*KH, 0.115*KH);
faceHigh.add(noseTip);

for (const side of [-1, 1]) {
    const nostril = ns(part(new THREE.SphereGeometry(0.008*KN, 6, 4), creaseM));
    nostril.position.set(side*0.012*KN, 0.068*KH, 0.112*KH);
    faceHigh.add(nostril);
    // Alar (nose wing)
    const alar = ns(part(new THREE.SphereGeometry(0.01*KN, 6, 4), warmPhysM));
    alar.position.set(side*0.018*KN, 0.072*KH, 0.108*KH);
    alar.scale.set(0.8, 0.6, 0.5);
    faceHigh.add(alar);
}

// Lips — upper with cupid's bow shape, lower with volume
const upperLip = ns(part(
    new THREE.TorusGeometry(0.025*KM, 0.006, 6, 16, Math.PI),
    lipM
));
upperLip.position.set(0, 0.055*KH, 0.098*KH);
upperLip.rotation.x = -0.1;
upperLip.rotation.z = Math.PI;
faceHigh.add(upperLip);

// Cupid's bow dip
const cupidBow = ns(part(new THREE.SphereGeometry(0.004, 4, 4), lipM));
cupidBow.position.set(0, 0.062*KH, 0.1*KH);
faceHigh.add(cupidBow);

const lowerLip = ns(part(
    new THREE.TorusGeometry(0.022*KM, 0.007, 6, 16, Math.PI),
    lipM
));
lowerLip.position.set(0, 0.049*KH, 0.097*KH);
lowerLip.rotation.x = 0.15;
faceHigh.add(lowerLip);

// Lip line
const lipLine = ns(part(new THREE.BoxGeometry(0.042*KM, 0.002, 0.008),
    new THREE.MeshStandardMaterial({color: creaseSkinC, roughness: 0.7})));
lipLine.position.set(0, 0.057*KH, 0.1*KH);
faceHigh.add(lipLine);

// Lip corners
for (const side of [-1, 1]) {
    const corner = ns(part(new THREE.SphereGeometry(0.003, 4, 4), creaseM));
    corner.position.set(side*0.024*KM, 0.056*KH, 0.095*KH);
    faceHigh.add(corner);
}

// Blush spots
const blushM = new THREE.MeshStandardMaterial({
    color: new THREE.Color().copy(faceSkinC).lerp(new THREE.Color('#ff7788'), 0.2),
    roughness: 0.7, transparent: true, opacity: 0.3,
});
for (const side of [-1, 1]) {
    const blush = ns(part(new THREE.CircleGeometry(0.018*KH, 12), blushM));
    blush.position.set(side*0.06*KH, 0.08*KH, 0.1*KH);
    faceHigh.add(blush);
}

// Ears
for (const side of [-1, 1]) {
    const ear = ns(part(
        new THREE.TorusGeometry(0.022, 0.008, 6, 8, Math.PI*1.4),
        skinPhysM
    ));
    ear.position.set(side*0.125*KH, HEAD_CY, 0);
    ear.rotation.y = side * Math.PI/2;
    ear.rotation.z = -0.15;
    ear.userData.skinSlot = true;
    faceHigh.add(ear);
    // Earlobe
    const lobe = ns(part(new THREE.SphereGeometry(0.008, 6, 4), warmPhysM));
    lobe.position.set(side*0.125*KH, HEAD_CY - 0.025, 0);
    faceHigh.add(lobe);
}

// --- EYES (high detail for tier 0-1) ---
const eyeTargets = [];
for (const side of [-1, 1]) {
    // Orbital shadow
    const orbitShadow = ns(part(
        new THREE.CircleGeometry(0.022*KE, 12),
        new THREE.MeshStandardMaterial({color: aoC, roughness: 0.9, transparent: true, opacity: 0.25})
    ));
    orbitShadow.position.set(side*0.045*KH, 0.105*KH, 0.1*KH);
    faceHigh.add(orbitShadow);

    const eyeGroup = pivot(side*0.045*KH, 0.105*KH, 0.1*KH);
    faceHigh.add(eyeGroup);

    // Sclera with subtle vessels
    const scleraC = document.createElement('canvas');
    scleraC.width = 64; scleraC.height = 64;
    const sg = scleraC.getContext('2d');
    sg.fillStyle = '#f8f8f4';
    sg.fillRect(0, 0, 64, 64);
    // Subtle veins
    sg.strokeStyle = 'rgba(180,60,60,0.08)';
    sg.lineWidth = 0.5;
    for (let v = 0; v < 8; v++) {
        sg.beginPath();
        sg.moveTo(Math.random()*64, Math.random()*64);
        sg.quadraticCurveTo(Math.random()*64, Math.random()*64, Math.random()*64, Math.random()*64);
        sg.stroke();
    }

    const eyeball = ns(part(
        new THREE.SphereGeometry(0.022*KE, 24, 24),
        new THREE.MeshPhysicalMaterial({
            map: new THREE.CanvasTexture(scleraC),
            roughness: 0.02, clearcoat: 1.0, clearcoatRoughness: 0.02,
        })
    ));
    eyeball.position.z = 0.003;
    eyeGroup.add(eyeball);

    // Corneal bulge
    const cornea = ns(part(
        new THREE.SphereGeometry(0.017*KE, 24, 24, 0, Math.PI*2, 0, Math.PI*0.5),
        new THREE.MeshPhysicalMaterial({
            color: '#ffffff', transparent: true, opacity: 0.12,
            roughness: 0.0, clearcoat: 1.0, clearcoatRoughness: 0.0,
            ior: 1.376,
        })
    ));
    cornea.position.set(0, 0, 0.018);
    cornea.rotation.x = -Math.PI/2;
    eyeGroup.add(cornea);

    // Detailed iris (128px canvas)
    const ic = document.createElement('canvas');
    ic.width = 128; ic.height = 128;
    const ig = ic.getContext('2d');
    const cx = 64, cy = 64;
    // Limbal ring
    ig.fillStyle = '#000000';
    ig.beginPath(); ig.arc(cx, cy, 62, 0, Math.PI*2); ig.fill();
    // Iris gradient with crypts
    for (let r = 60; r > 0; r -= 0.5) {
        const t = r / 60;
        const c2 = new THREE.Color().copy(eyeC).lerp(new THREE.Color('#000'), (1-t)*0.3);
        if (t > 0.5) c2.lerp(new THREE.Color('#fff'), (t-0.5)*0.12);
        ig.fillStyle = '#'+c2.getHexString();
        ig.beginPath(); ig.arc(cx, cy, r, 0, Math.PI*2); ig.fill();
    }
    // Collarette ring
    ig.strokeStyle = '#'+new THREE.Color().copy(eyeC).lerp(new THREE.Color('#fff'), 0.5).getHexString();
    ig.lineWidth = 1.5;
    ig.beginPath(); ig.arc(cx, cy, 32, 0, Math.PI*2); ig.stroke();
    // Radial fibers (more detailed)
    ig.globalAlpha = 0.15;
    for (let a = 0; a < Math.PI*2; a += 0.06) {
        ig.strokeStyle = Math.random() > 0.5 ? '#ffffff' : '#000000';
        ig.lineWidth = 0.4;
        ig.beginPath();
        ig.moveTo(cx + Math.cos(a)*20, cy + Math.sin(a)*20);
        ig.lineTo(cx + Math.cos(a)*58, cy + Math.sin(a)*58);
        ig.stroke();
    }
    // Iris crypts (dark spots)
    ig.globalAlpha = 0.1;
    ig.fillStyle = '#000';
    for (let cr = 0; cr < 12; cr++) {
        const ca = Math.random() * Math.PI * 2;
        const cd = 25 + Math.random() * 25;
        ig.beginPath(); ig.arc(cx+Math.cos(ca)*cd, cy+Math.sin(ca)*cd, 2+Math.random()*3, 0, Math.PI*2); ig.fill();
    }
    ig.globalAlpha = 1.0;
    // Pupil
    ig.fillStyle = '#020202';
    ig.beginPath(); ig.arc(cx, cy, 18, 0, Math.PI*2); ig.fill();
    // Catchlights (kawaii sparkle)
    ig.fillStyle = 'rgba(255,255,255,0.85)';
    ig.beginPath(); ig.arc(cx-12, cy-14, 8, 0, Math.PI*2); ig.fill();
    ig.fillStyle = 'rgba(255,255,255,0.5)';
    ig.beginPath(); ig.arc(cx+8, cy+8, 5, 0, Math.PI*2); ig.fill();
    ig.fillStyle = 'rgba(255,255,255,0.25)';
    ig.beginPath(); ig.arc(cx-4, cy+12, 2.5, 0, Math.PI*2); ig.fill();

    const irisTex = new THREE.CanvasTexture(ic);
    const iris = ns(part(
        new THREE.CircleGeometry(0.016*KE, 32),
        new THREE.MeshPhysicalMaterial({map: irisTex, roughness: 0.08, clearcoat: 0.9})
    ));
    iris.position.set(0, 0, 0.019);
    eyeGroup.add(iris);

    // Upper eyelid
    const lid = ns(part(
        new THREE.SphereGeometry(0.025*KE, 16, 8, 0, Math.PI*2, 0, Math.PI*0.4),
        skinPhysM
    ));
    lid.position.set(0, 0.006, 0.002);
    lid.name = 'upperLid';
    lid.userData.skinSlot = true;
    eyeGroup.add(lid);

    // Lower eyelid
    const lowerLid = ns(part(
        new THREE.SphereGeometry(0.023*KE, 12, 6, 0, Math.PI*2, Math.PI*0.65, Math.PI*0.35),
        skinPhysM
    ));
    lowerLid.position.set(0, -0.008, 0.002);
    lowerLid.userData.skinSlot = true;
    eyeGroup.add(lowerLid);

    // Eyelashes
    const lash = ns(part(
        new THREE.TorusGeometry(0.023*KE, 0.0025, 4, 20, Math.PI),
        new THREE.MeshStandardMaterial({color: '#060606', roughness: 0.8})
    ));
    lash.position.set(0, 0.01, 0.012);
    lash.rotation.x = 0.25; lash.rotation.z = Math.PI;
    eyeGroup.add(lash);

    // Lower lashes
    const lLash = ns(part(
        new THREE.TorusGeometry(0.02*KE, 0.001, 3, 14, Math.PI),
        new THREE.MeshStandardMaterial({color: '#181818', roughness: 0.85})
    ));
    lLash.position.set(0, -0.008, 0.012);
    lLash.rotation.x = -0.2;
    eyeGroup.add(lLash);

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
    faceHigh.add(brow);
}

// ============================================================
// TIER 0 (ULTRA) — additional anatomical detail
// ============================================================

// Nasolabial folds (nose-to-mouth creases)
for (const side of [-1, 1]) {
    const fold = ns(part(
        new THREE.CylinderGeometry(0.002, 0.002, 0.04*KH, 4),
        creaseM
    ));
    fold.position.set(side*0.03*KH, 0.07*KH, 0.095*KH);
    fold.rotation.z = side * 0.25;
    fold.rotation.x = 0.1;
    faceUltra.add(fold);
}

// Philtrum (vertical groove nose→lip)
const philtrum1 = ns(part(new THREE.BoxGeometry(0.003, 0.015*KH, 0.003), creaseM));
philtrum1.position.set(-0.004, 0.065*KH, 0.105*KH);
faceUltra.add(philtrum1);
const philtrum2 = ns(part(new THREE.BoxGeometry(0.003, 0.015*KH, 0.003), creaseM));
philtrum2.position.set(0.004, 0.065*KH, 0.105*KH);
faceUltra.add(philtrum2);

// Zygomatic arch (cheekbone ridge)
for (const side of [-1, 1]) {
    const zyg = ns(part(
        new THREE.CylinderGeometry(0.006, 0.005, 0.04*KH, 6),
        skinPhysM
    ));
    zyg.position.set(side*0.08*KH, 0.1*KH, 0.06*KH);
    zyg.rotation.z = Math.PI/2;
    zyg.scale.set(1, 1, 0.5);
    zyg.userData.skinSlot = true;
    faceUltra.add(zyg);
}

// Orbital bone ridges
for (const side of [-1, 1]) {
    const orb = ns(part(
        new THREE.TorusGeometry(0.024*KE, 0.004, 4, 12, Math.PI*1.2),
        skinPhysM
    ));
    orb.position.set(side*0.045*KH, 0.115*KH, 0.095*KH);
    orb.rotation.z = side * 0.15;
    orb.userData.skinSlot = true;
    faceUltra.add(orb);
}

// Glabella (between brows)
const glabella = ns(part(new THREE.SphereGeometry(0.01*KH, 6, 4), skinPhysM));
glabella.position.set(0, 0.14*KH, 0.1*KH);
glabella.scale.set(1, 0.6, 0.4);
glabella.userData.skinSlot = true;
faceUltra.add(glabella);

// Tear ducts (inner eye corner)
for (const side of [-1, 1]) {
    const td = ns(part(new THREE.SphereGeometry(0.003, 4, 4),
        new THREE.MeshStandardMaterial({color: '#cc8888', roughness: 0.4})));
    td.position.set(side*0.028*KH, 0.103*KH, 0.11*KH);
    faceUltra.add(td);
}

// Eyelid creases (double eyelid)
for (const side of [-1, 1]) {
    const crease = ns(part(
        new THREE.TorusGeometry(0.02*KE, 0.001, 3, 10, Math.PI),
        creaseM
    ));
    crease.position.set(side*0.045*KH, 0.117*KH, 0.1*KH);
    crease.rotation.z = Math.PI;
    faceUltra.add(crease);
}

// Mentolabial sulcus (groove between lower lip and chin)
const mento = ns(part(new THREE.BoxGeometry(0.03*KM, 0.002, 0.006), creaseM));
mento.position.set(0, 0.04*KH, 0.09*KH);
faceUltra.add(mento);

// Under-eye subtle puffiness
for (const side of [-1, 1]) {
    const ue = ns(part(new THREE.SphereGeometry(0.012, 6, 4), warmPhysM));
    ue.position.set(side*0.04*KH, 0.095*KH, 0.105*KH);
    ue.scale.set(1.2, 0.4, 0.3);
    faceUltra.add(ue);
}

// Vermilion border (lip edge detail)
const vermUpper = ns(part(
    new THREE.TorusGeometry(0.026*KM, 0.0015, 3, 16, Math.PI),
    new THREE.MeshStandardMaterial({color: new THREE.Color().copy(lipC).multiplyScalar(0.85), roughness: 0.5})
));
vermUpper.position.set(0, 0.06*KH, 0.099*KH);
vermUpper.rotation.z = Math.PI;
faceUltra.add(vermUpper);

// Individual eyelash strands (ultra only)
for (const side of [-1, 1]) {
    for (let i = 0; i < 8; i++) {
        const a = -Math.PI*0.35 + (i / 7) * Math.PI*0.7;
        const lashStrand = ns(part(
            new THREE.CylinderGeometry(0.0003, 0.0005, 0.008, 3),
            new THREE.MeshStandardMaterial({color: '#040404'})
        ));
        lashStrand.position.set(
            side*0.045*KH + Math.cos(a)*0.02*KE,
            0.115*KH + Math.sin(a)*0.005,
            0.115*KH
        );
        lashStrand.rotation.x = -0.5 + Math.sin(a)*0.3;
        lashStrand.rotation.z = side * 0.15;
        faceUltra.add(lashStrand);
    }
}

// ============================================================
// TIER 2 (MEDIUM) — simplified face
// ============================================================

// Simple jaw
const jawMed = ns(part(
    new THREE.SphereGeometry(0.1*KH, 10, 6, 0, Math.PI*2, Math.PI*0.55, Math.PI*0.45),
    skinStdM
));
jawMed.position.set(0, 0.05*KH, -0.02*KH);
jawMed.scale.set(JW*0.95, 0.7, 0.55);
faceMedium.add(jawMed);

// Simple eyes (flat circles)
for (const side of [-1, 1]) {
    const eyeSimple = ns(part(new THREE.SphereGeometry(0.018*KE, 8, 8),
        new THREE.MeshStandardMaterial({color: '#f0f0ec', roughness: 0.1})));
    eyeSimple.position.set(side*0.045*KH, 0.105*KH, 0.11*KH);
    faceMedium.add(eyeSimple);
    // Iris dot
    const irisDot = ns(part(new THREE.CircleGeometry(0.01*KE, 8),
        new THREE.MeshStandardMaterial({color: eyeC})));
    irisDot.position.set(side*0.045*KH, 0.105*KH, 0.128*KH);
    faceMedium.add(irisDot);
}

// Simple nose
const noseSimple = ns(part(new THREE.SphereGeometry(0.014*KN, 6, 4), skinStdM));
noseSimple.position.set(0, 0.075*KH, 0.115*KH);
faceMedium.add(noseSimple);

// Simple mouth line
const mouthSimple = ns(part(new THREE.BoxGeometry(0.035*KM, 0.003, 0.006),
    new THREE.MeshStandardMaterial({color: lipC})));
mouthSimple.position.set(0, 0.055*KH, 0.1*KH);
faceMedium.add(mouthSimple);

// ============================================================
// TIER 3 (LOW) — minimal (canvas-painted face texture)
// ============================================================

// Just two eye dots and a mouth line
for (const side of [-1, 1]) {
    const dot = ns(part(new THREE.CircleGeometry(0.008, 6),
        new THREE.MeshLambertMaterial({color: '#202020'})));
    dot.position.set(side*0.04*KH, 0.105*KH, HEAD_R + 0.01);
    faceLow.add(dot);
}
const mouthLow = ns(part(new THREE.BoxGeometry(0.03, 0.002, 0.004),
    new THREE.MeshLambertMaterial({color: lipC})));
mouthLow.position.set(0, 0.055*KH, HEAD_R + 0.01);
faceLow.add(mouthLow);

// ============================================================
// HAIR (same as V5 — shells centered at HEAD_CY)
// ============================================================
const hairM = new THREE.MeshStandardMaterial({color: hairC, roughness: 0.75});

// Scalp cap
const scalp = ns(part(new THREE.SphereGeometry(HEAD_R*1.02, 20, 10, 0, Math.PI*2, 0, Math.PI*0.5), hairM));
scalp.position.y = HEAD_CY;
headPivot.add(scalp);

// Hair shells
for (const [rMul, phiMax, yOff] of [[1.18, 0.65, 0.0], [1.24, 0.62, 0.005], [1.30, 0.58, 0.008]]) {
    const shell = ns(part(
        new THREE.SphereGeometry(HEAD_R*rMul, 20, 10, 0, Math.PI*2, 0, Math.PI*phiMax),
        hairM
    ));
    shell.position.y = HEAD_CY + yOff;
    headPivot.add(shell);
}

// Hair back
const hairBack = ns(part(
    new THREE.SphereGeometry(HEAD_R*1.12, 16, 8, 0, Math.PI*2, Math.PI*0.3, Math.PI*0.5),
    hairM
));
hairBack.position.set(0, HEAD_CY - 0.01, -0.02);
headPivot.add(hairBack);

// Bangs
const hairlineY = HEAD_CY + HEAD_R * 0.55;
const bangsGeo = new THREE.BoxGeometry(HEAD_R * 2.1, 0.02, HEAD_R * 0.6);
const bangs = ns(part(bangsGeo, hairM));
bangs.position.set(0, hairlineY, HEAD_R * 0.55);
bangs.rotation.x = 0.2;
headPivot.add(bangs);

// Side hair
for (const side of [-1, 1]) {
    const sideHair = ns(part(
        new THREE.BoxGeometry(0.025, HEAD_R*1.2, HEAD_R*0.8),
        hairM
    ));
    sideHair.position.set(side * HEAD_R * 1.05, HEAD_CY - 0.01, HEAD_R * 0.15);
    headPivot.add(sideHair);
}

// ============================================================
// ARMS + LEGS (compact, same skeleton as V5)
// ============================================================
function buildArm(side) {
    const shoulderPivot = pivot(side * 0.18 * SW, 0.1, 0);
    upperTorsoPivot.add(shoulderPivot);
    const upper = part(new THREE.CylinderGeometry(0.03, 0.035, 0.22, 8), shirtM);
    upper.position.y = -0.11;
    shoulderPivot.add(upper);
    const elbowPivot = pivot(0, -0.22, 0);
    shoulderPivot.add(elbowPivot);
    const forearm = part(new THREE.CylinderGeometry(0.025, 0.03, 0.2, 8), shirtM);
    forearm.position.y = -0.1;
    elbowPivot.add(forearm);
    const wristPivot = pivot(0, -0.2, 0);
    elbowPivot.add(wristPivot);
    // Hand
    const hand = part(new THREE.BoxGeometry(0.04, 0.05, 0.025), handM);
    hand.position.y = -0.03;
    wristPivot.add(hand);

    // Fingers (4 + thumb)
    const fingers = [];
    for (let fi = 0; fi < 4; fi++) {
        const fx = -0.015 + fi * 0.01;
        const mcpPivot = pivot(fx, -0.055, 0);
        wristPivot.add(mcpPivot);
        const seg1 = ns(part(new THREE.CylinderGeometry(0.003, 0.0035, 0.018, 4), handM));
        seg1.position.y = -0.009;
        mcpPivot.add(seg1);
        const pipPivot = pivot(0, -0.018, 0);
        mcpPivot.add(pipPivot);
        const seg2 = ns(part(new THREE.CylinderGeometry(0.0025, 0.003, 0.014, 4), handM));
        seg2.position.y = -0.007;
        pipPivot.add(seg2);
        const dipPivot = pivot(0, -0.014, 0);
        pipPivot.add(dipPivot);
        const seg3 = ns(part(new THREE.CylinderGeometry(0.002, 0.0025, 0.01, 4), handM));
        seg3.position.y = -0.005;
        dipPivot.add(seg3);
        // Fingernail
        const nail = ns(part(new THREE.BoxGeometry(0.005, 0.003, 0.004),
            new THREE.MeshStandardMaterial({color: '#e8d0c0', roughness: 0.3, clearcoat: 0.5})));
        nail.position.set(0, -0.01, 0.003);
        dipPivot.add(nail);
        fingers.push({mcpPivot, pipPivot, dipPivot});
    }
    // Thumb
    const thumbMcp = pivot(side*0.022, -0.04, 0.01);
    wristPivot.add(thumbMcp);
    const ts1 = ns(part(new THREE.CylinderGeometry(0.004, 0.005, 0.016, 4), handM));
    ts1.position.y = -0.008;
    thumbMcp.add(ts1);
    const thumbIp = pivot(0, -0.016, 0);
    thumbMcp.add(thumbIp);
    const ts2 = ns(part(new THREE.CylinderGeometry(0.003, 0.004, 0.012, 4), handM));
    ts2.position.y = -0.006;
    thumbIp.add(ts2);

    return {shoulderPivot, elbowPivot, wristPivot, fingers,
            thumb: {mcpPivot: thumbMcp, ipPivot: thumbIp}};
}

function buildLeg(side) {
    const hipPivot = pivot(side * 0.08 * HW, -0.08, 0);
    hipsPivot.add(hipPivot);
    const thigh = part(new THREE.CylinderGeometry(0.045, 0.055, 0.35, 8), pantsM);
    thigh.position.y = -0.175;
    hipPivot.add(thigh);
    const kneePivot = pivot(0, -0.35, 0);
    hipPivot.add(kneePivot);
    const shin = part(new THREE.CylinderGeometry(0.035, 0.045, 0.35, 8), pantsM);
    shin.position.y = -0.175;
    kneePivot.add(shin);
    const anklePivot = pivot(0, -0.35, 0);
    kneePivot.add(anklePivot);
    const shoe = part(new THREE.BoxGeometry(0.06, 0.04, 0.1), shoeM);
    shoe.position.set(0, -0.02, 0.015);
    anklePivot.add(shoe);
    return {hipPivot, kneePivot, anklePivot};
}

const leftArm = buildArm(-1);
const rightArm = buildArm(1);
const leftLeg = buildLeg(-1);
const rightLeg = buildLeg(1);

// ============================================================
// STATE — expose skeleton + LOD data
// ============================================================
S.body = {
    hips: hipsPivot, upperTorsoPivot, neckPivot, headPivot,
    leftArm, rightArm, leftLeg, rightLeg,
};
S.eyes = eyeTargets;
S.faceLOD = {
    currentTier: 1,
    faceUltra, faceHigh, faceMedium, faceLow,
    heads,
    skinMats: {physical: skinPhysM, standard: skinStdM},
};
S.built = true;
"""


# ===================================================================
# SEED COMMAND
# ===================================================================

class Command(BaseCommand):
    help = 'Create the Velour Metropolis with buildings, plants, and V6 NPCs.'

    def handle(self, *args, **options):
        # --- Register reusable scripts ---
        building_script = _script('Procedural Building', 'start', BUILDING_SCRIPT,
            'Generates parameterized buildings: house, shop, skyscraper, factory, warehouse, church, tower.')
        plant_script = _script('L-System Plant', 'start', PLANT_SCRIPT,
            'L-system trees/bushes: oak, pine, birch, palm, bush, willow, cactus.')
        lod_script = _script('NPC LOD Manager', 'update', LOD_MANAGER_SCRIPT,
            'FPS + distance LOD switching for V6 humanoid faces.')
        v6_script = _script('Humanoid Builder V6', 'start', HUMANOID_V6_SCRIPT,
            'Detailed humanoid with 4-tier LOD face: ultra, high, medium, low.')
        motion_lib = Script.objects.filter(slug='motion-quality-library').first()
        react = Script.objects.filter(slug='plaza-react-v5').first()

        # --- Create world ---
        World.objects.filter(slug='velour-metropolis').delete()
        world = World.objects.create(
            title='Velour Metropolis',
            slug='velour-metropolis',
            description='Mixed cityscape with procedural buildings, L-system plants, '
                        'and V6 NPCs with variable-resolution faces.',
            skybox='procedural',
            sky_color='#88b0d8',
            ground_color='#606058',
            ground_size=80.0,
            ambient_light=0.5,
            fog_near=40.0,
            fog_far=120.0,
            fog_color='#b8c8d8',
            gravity=-9.81,
            spawn_x=0.0, spawn_y=1.6, spawn_z=15.0,
            soundscape='city',
            ambient_volume=0.2,
            published=True, featured=True,
        )

        entities = []
        attachments = []

        def ent(name, prim, color, x, y, z, sx=1, sy=1, sz=1, shadow=True):
            e = Entity(
                world=world, name=name, primitive=prim, primitive_color=color,
                pos_x=x, pos_y=y, pos_z=z,
                scale_x=sx, scale_y=sy, scale_z=sz,
                cast_shadow=shadow, receive_shadow=shadow,
                behavior='static',
            )
            entities.append(e)
            return e

        # Ground
        ent('Ground', 'box', '#606058', 0, -0.05, 0, 80, 0.1, 80, shadow=False)

        # Roads (cross pattern)
        for z in range(-30, 31, 30):
            ent(f'Road EW {z}', 'box', '#383838', 0, 0.005, z, 70, 0.01, 6, shadow=False)
        for x in range(-30, 31, 30):
            ent(f'Road NS {x}', 'box', '#383838', x, 0.005, 0, 6, 0.01, 70, shadow=False)

        # Sidewalks
        for z in [-33, -27, 27, 33]:
            ent(f'Sidewalk {z}', 'box', '#787870', 0, 0.01, z, 70, 0.02, 2, shadow=False)
        for x in [-33, -27, 27, 33]:
            ent(f'Sidewalk {x}', 'box', '#787870', x, 0.01, 0, 2, 0.02, 70, shadow=False)

        Entity.objects.bulk_create(entities)
        entities = []

        # --- Buildings ---
        BUILDING_CONFIGS = [
            # (name, type, x, z, ry, floors, width, depth, color, trim, roof, extras)
            ('Town Hall', 'church', 0, -40, 0, 3, 12, 10, '#c8b8a0', '#808080', '#504030', {}),
            ('Skyscraper A', 'skyscraper', -20, -20, 15, 18, 10, 10, '#607080', '#505050', '#404040',
             {'windowLit': 0.5}),
            ('Skyscraper B', 'skyscraper', 20, -20, -10, 12, 8, 8, '#506878', '#404848', '#383838',
             {'windowLit': 0.4}),
            ('Corner Shop', 'shop', -15, 10, 0, 1, 8, 6, '#e0d0b8', '#908070', '#604030',
             {'awningColor': '#c84040'}),
            ('Bakery', 'shop', -5, 10, 0, 1, 6, 5, '#e8d8c0', '#887868', '#504028',
             {'awningColor': '#3080c0'}),
            ('Bookstore', 'shop', 5, 10, 0, 2, 7, 6, '#b8a888', '#706050', '#5a3820',
             {'awningColor': '#408040'}),
            ('Residence 1', 'house', 20, 15, 30, 2, 7, 6, '#c0b098', '#706060', '#804830', {}),
            ('Residence 2', 'house', 30, 20, -20, 2, 6, 5, '#d0c0a8', '#807070', '#6a3828', {}),
            ('Residence 3', 'house', -25, 20, 10, 3, 8, 7, '#b0a890', '#606060', '#704028', {}),
            ('Factory', 'factory', -30, -15, 45, 2, 14, 10, '#909088', '#606060', '#505050', {}),
            ('Warehouse', 'warehouse', 30, -10, -30, 2, 12, 8, '#808878', '#606060', '#505050', {}),
            ('Tower', 'tower', -35, -35, 0, 5, 6, 6, '#b0a898', '#808080', '#604838', {}),
            ('Skyscraper C', 'skyscraper', 0, -25, 5, 25, 12, 12, '#5a6878', '#484848', '#383838',
             {'windowLit': 0.6}),
        ]

        building_ents = []
        for name, btype, x, z, ry, floors, w, d, color, trim, roof, extras in BUILDING_CONFIGS:
            e = Entity.objects.create(
                world=world, name=name, primitive='box',
                primitive_color='#000000',
                pos_x=x, pos_y=0, pos_z=z, rot_y=ry,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            props = {
                'type': btype, 'floors': floors, 'width': w, 'depth': d,
                'color': color, 'trim': trim, 'roof': roof,
                **extras,
            }
            attachments.append(EntityScript(entity=e, script=building_script, props=props))

        # --- Plants ---
        PLANT_CONFIGS = [
            # Street trees
            *[(f'Street Tree {i}', 'oak', x, z, rng.uniform(0.8, 1.2))
              for i, (x, z) in enumerate([
                  (-12, 8), (-2, 8), (8, 8), (18, 8),
                  (-12, -8), (-2, -8), (8, -8), (18, -8),
                  (-8, 22), (8, 22), (-8, -32), (8, -32),
              ])],
            # Park area
            ('Park Oak', 'oak', 35, 35, 1.5),
            ('Park Birch 1', 'birch', 32, 38, 1.1),
            ('Park Birch 2', 'birch', 38, 32, 1.0),
            ('Park Willow', 'willow', 28, 38, 1.3),
            # Decorative
            ('Palm 1', 'palm', -35, 15, 1.2),
            ('Palm 2', 'palm', -35, 18, 1.0),
            ('Pine 1', 'pine', -20, 35, 1.4),
            ('Pine 2', 'pine', -18, 38, 1.1),
            ('Bush 1', 'bush', 10, 12, 0.6),
            ('Bush 2', 'bush', -10, 12, 0.7),
            ('Bush 3', 'bush', 15, 25, 0.5),
            ('Cactus', 'cactus', 25, -30, 0.8),
        ]

        for name, species, x, z, scale in PLANT_CONFIGS:
            e = Entity.objects.create(
                world=world, name=name, primitive='box',
                primitive_color='#000000',
                pos_x=x, pos_y=0, pos_z=z,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            attachments.append(EntityScript(entity=e, script=plant_script, props={
                'species': species, 'iterations': 4, 'scale': scale,
                'seed': hash(name) % 10000,
            }))

        # --- V6 NPCs ---
        SKINS = ['#c89870', '#704020', '#a87040', '#d4a470', '#e8c898',
                 '#f0d4b0', '#8b5030', '#b88050', '#d0ac80', '#b06038']
        SHIRTS = ['#f0e8e0', '#2a4060', '#6a3838', '#385838', '#483858',
                  '#684038', '#364050', '#584830', '#385058', '#5a4440']
        PANTS = ['#1c1c28', '#282830', '#323240', '#1e1e30', '#2a2a38']
        SHOES = ['#181818', '#3a2418', '#1a1a1a', '#3e2c1e', '#242424']
        HAIRS = ['#1a1008', '#080808', '#301a0e', '#b89040', '#4a2818',
                 '#7a3c10', '#201008']
        EYES = ['#3a2818', '#1e4a1e', '#3868a8', '#4a7a4a', '#5a3418']
        NAMES = ['Avery', 'Blake', 'Casey', 'Dana', 'Ellis',
                 'Frankie', 'Gray', 'Harper', 'Indigo', 'Jules',
                 'Kai', 'Lane']
        REACTIONS = ['flee', 'approach', 'follow', 'notice', 'ignore',
                     'shy', 'curious', 'wave', 'mimic', 'startle']

        NPC_POSITIONS = [
            (3, 5, 0), (-5, 8, 90), (12, 3, -30), (-10, -5, 180),
            (0, -10, 45), (8, -15, -60), (-15, 0, 120), (25, 25, -90),
            (-8, 25, 30), (15, 20, 150), (-25, -5, -45), (5, -20, 70),
        ]

        for i, (name, (px, pz, ry)) in enumerate(zip(NAMES, NPC_POSITIONS)):
            e = Entity.objects.create(
                world=world, name=name, primitive='box',
                primitive_color='#000000',
                pos_x=px, pos_y=0, pos_z=pz, rot_y=ry,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            if motion_lib:
                attachments.append(EntityScript(entity=e, script=motion_lib, props={}))
            attachments.append(EntityScript(entity=e, script=v6_script, props={
                'skin': SKINS[i % len(SKINS)],
                'shirt': SHIRTS[i % len(SHIRTS)],
                'pants': rng.choice(PANTS),
                'shoes': rng.choice(SHOES),
                'hair': HAIRS[i % len(HAIRS)],
                'eyes': EYES[i % len(EYES)],
                'shoulderW': round(0.85 + rng.random() * 0.2, 2),
                'hipW': round(0.88 + rng.random() * 0.15, 2),
                'heightScale': round(0.92 + rng.random() * 0.12, 2),
                'jawW': round(0.88 + rng.random() * 0.2, 2),
                'cheekFull': round(0.92 + rng.random() * 0.16, 2),
                'foreheadH': round(0.95 + rng.random() * 0.1, 2),
            }))
            attachments.append(EntityScript(entity=e, script=lod_script, props={}))
            if react:
                attachments.append(EntityScript(entity=e, script=react, props={
                    'reaction': REACTIONS[i % len(REACTIONS)],
                    'bounds': [-30, -30, 30, 30],
                    'speed': round(0.4 + rng.random() * 0.5, 2),
                }))

        EntityScript.objects.bulk_create(attachments)

        total = Entity.objects.filter(world=world).count()
        self.stdout.write(self.style.SUCCESS(
            f'Velour Metropolis created: {total} entities, '
            f'{len(BUILDING_CONFIGS)} buildings, {len(PLANT_CONFIGS)} plants, '
            f'{len(NAMES)} V6 NPCs.'
        ))


def _script(name, event, code, desc=''):
    from django.utils.text import slugify
    slug = slugify(name)
    s, _ = Script.objects.get_or_create(slug=slug, defaults={
        'name': name, 'event': event, 'code': code, 'description': desc,
    })
    if s.code != code:
        s.code = code
        s.event = event
        s.description = desc
        s.save()
    return s
