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

if (ctx.entity.isMesh) {
    ctx.entity.material.visible = false;
    ctx.entity.castShadow = false;
}

// Deterministic RNG
let rngState = (P.seed || 42) * 127.1;
function rnd() { rngState = (rngState * 16807 + 0.5) % 2147483647; return rngState / 2147483647; }

// --- 15 species presets ---
const presets = {
    oak: {
        axiom: 'F', rules: [{'F': 'FF+[+F-F-F]-[-F+F+F]'}],
        angle: 22.5, lengthFactor: 0.65, startLength: 0.8,
        trunkTaper: 0.7, leafSize: 0.35, leafDensity: 0.6,
        trunk: '#5a4020', leaf: '#2a6818', leaf2: '#3a7828',
    },
    pine: {
        axiom: 'F', rules: [{'F': 'F[+F][-F]F[+F][-F]'}],
        angle: 25, lengthFactor: 0.55, startLength: 0.6,
        trunkTaper: 0.65, leafSize: 0.25, leafDensity: 0.8,
        leafShape: 'cone', trunk: '#4a3018', leaf: '#1a4810', leaf2: '#2a5818',
    },
    birch: {
        axiom: 'F', rules: [{'F': 'F[-F][+F]F'}],
        angle: 30, lengthFactor: 0.7, startLength: 0.7,
        trunkTaper: 0.75, leafSize: 0.2, leafDensity: 0.5,
        trunk: '#d0c8b8', leaf: '#4a8830', leaf2: '#5a9838',
        barkStripes: true,
    },
    palm: {
        axiom: 'FFFFF', rules: [{'F': 'F'}],
        angle: 0, lengthFactor: 1.0, startLength: 0.9,
        trunkTaper: 0.92, leafSize: 0.5, leafDensity: 0,
        fronds: true, trunk: '#6a5838', leaf: '#2a7818', leaf2: '#3a8828',
        coconuts: true,
    },
    bush: {
        axiom: 'F', rules: [{'F': 'F[+F]F[-F][F]'}],
        angle: 35, lengthFactor: 0.6, startLength: 0.3,
        trunkTaper: 0.6, leafSize: 0.18, leafDensity: 0.9,
        trunk: '#4a3818', leaf: '#2a6020', leaf2: '#3a7028',
    },
    willow: {
        axiom: 'F', rules: [{'F': 'FF[-F+F+F][+F-F]'}],
        angle: 18, lengthFactor: 0.68, startLength: 0.75,
        trunkTaper: 0.72, leafSize: 0.15, leafDensity: 0.7,
        droop: 0.15, trunk: '#5a4828', leaf: '#6aa840', leaf2: '#7ab848',
    },
    cactus: {
        axiom: 'F', rules: [{'F': 'F[+F][-F]'}],
        angle: 90, lengthFactor: 0.5, startLength: 0.6,
        trunkTaper: 0.85, leafSize: 0, leafDensity: 0,
        trunkIsGreen: true, trunk: '#2a6030', leaf: '#2a6030', leaf2: '#2a6030',
        flower: true, flowerColor: '#e84080',
    },
    maple: {
        axiom: 'F', rules: [
            {'F': 'FF+[+F-F]-[-F+F]'},
            {'F': 'F[+F][-F]FF[-F+F]'},
        ],
        angle: 25, lengthFactor: 0.62, startLength: 0.75,
        trunkTaper: 0.68, leafSize: 0.3, leafDensity: 0.65,
        trunk: '#5a3818', leaf: '#c83020', leaf2: '#e86030',
        leafShape: 'star',
    },
    cherry: {
        axiom: 'F', rules: [{'F': 'FF[-F+F][+F-F]F'}],
        angle: 28, lengthFactor: 0.6, startLength: 0.55,
        trunkTaper: 0.7, leafSize: 0.22, leafDensity: 0.55,
        trunk: '#6a3028', leaf: '#ffa0b0', leaf2: '#ff80a0',
        flower: true, flowerColor: '#ffc0d0', flowerDensity: 0.4,
    },
    bamboo: {
        axiom: 'FFFFF', rules: [{'F': 'F'}],
        angle: 5, lengthFactor: 1.0, startLength: 0.6,
        trunkTaper: 0.98, leafSize: 0.2, leafDensity: 0,
        trunkIsGreen: true, trunk: '#4a8830', leaf: '#3a7020', leaf2: '#4a8030',
        culms: true,
    },
    fern: {
        axiom: 'X', rules: [{'X': 'F+[[X]-X]-F[-FX]+X', 'F': 'FF'}],
        angle: 25, lengthFactor: 0.55, startLength: 0.15,
        trunkTaper: 0.5, leafSize: 0.08, leafDensity: 0.85,
        trunk: '#2a4818', leaf: '#2a7818', leaf2: '#3a8828',
        isGroundCover: true,
    },
    succulent: {
        axiom: 'F', rules: [{'F': 'F[+F][-F]'}],
        angle: 137.5, lengthFactor: 0.75, startLength: 0.1,
        trunkTaper: 0.9, leafSize: 0.12, leafDensity: 0.95,
        trunkIsGreen: true, trunk: '#508848', leaf: '#70a860', leaf2: '#80b870',
        isGroundCover: true, rosette: true,
    },
    cypress: {
        axiom: 'F', rules: [{'F': 'F[+F]F[-F]F'}],
        angle: 12, lengthFactor: 0.6, startLength: 0.7,
        trunkTaper: 0.7, leafSize: 0.3, leafDensity: 0.75,
        leafShape: 'cone', trunk: '#4a3018', leaf: '#1a3810', leaf2: '#2a4818',
        narrow: true,
    },
    baobab: {
        axiom: 'F', rules: [{'F': 'FFF[+F][-F][+F-F]'}],
        angle: 40, lengthFactor: 0.45, startLength: 0.5,
        trunkTaper: 0.55, leafSize: 0.25, leafDensity: 0.35,
        trunk: '#8a7868', leaf: '#4a7828', leaf2: '#5a8838',
        fatTrunk: true,
    },
    vine: {
        axiom: 'F', rules: [{'F': 'F[-F][+F]F[-F]'}],
        angle: 35, lengthFactor: 0.72, startLength: 0.4,
        trunkTaper: 0.5, leafSize: 0.12, leafDensity: 0.6,
        droop: 0.2, trunk: '#3a5020', leaf: '#4a8030', leaf2: '#5a9040',
        isGroundCover: true,
    },
};

const preset = presets[species] || presets.oak;

// Stochastic rule selection: if multiple rule sets, pick per-iteration
function rewrite(str) {
    let next = '';
    const ruleSet = preset.rules[Math.floor(rnd() * preset.rules.length)];
    for (const ch of str) {
        next += ruleSet[ch] || ch;
    }
    return next;
}

let str = preset.axiom;
for (let i = 0; i < iterations; i++) str = rewrite(str);

// Colors (allow prop overrides)
const trunkColor = new THREE.Color(P.trunk || preset.trunk);
const leafColor = new THREE.Color(P.leaf || preset.leaf);
const leafColor2 = new THREE.Color(P.leaf2 || preset.leaf2);

// --- Canvas bark texture ---
function makeBarkTexture() {
    const c = document.createElement('canvas');
    c.width = 64; c.height = 128;
    const g = c.getContext('2d');
    const base = preset.trunkIsGreen ? preset.trunk : (P.trunk || preset.trunk);
    g.fillStyle = base;
    g.fillRect(0, 0, 64, 128);
    // Vertical grain lines
    for (let i = 0; i < 20; i++) {
        const x = rnd() * 64;
        g.strokeStyle = `rgba(0,0,0,${0.1 + rnd()*0.15})`;
        g.lineWidth = 0.5 + rnd() * 1.5;
        g.beginPath(); g.moveTo(x, 0); g.lineTo(x + (rnd()-0.5)*8, 128); g.stroke();
    }
    // Horizontal cracks for birch
    if (preset.barkStripes) {
        for (let i = 0; i < 12; i++) {
            const y = rnd() * 128;
            g.strokeStyle = `rgba(40,30,20,${0.2 + rnd()*0.3})`;
            g.lineWidth = 0.5 + rnd();
            g.beginPath(); g.moveTo(0, y); g.lineTo(64, y + (rnd()-0.5)*4); g.stroke();
        }
    }
    // Knots
    for (let i = 0; i < 3; i++) {
        g.fillStyle = `rgba(50,30,15,${0.15 + rnd()*0.15})`;
        g.beginPath();
        g.ellipse(rnd()*64, rnd()*128, 2+rnd()*3, 3+rnd()*5, rnd()*Math.PI, 0, Math.PI*2);
        g.fill();
    }
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    return tex;
}

const barkTex = makeBarkTexture();
const trunkM = new THREE.MeshStandardMaterial({
    map: barkTex, roughness: 0.85, color: trunkColor,
});
const leafM = new THREE.MeshStandardMaterial({color: leafColor, roughness: 0.7, side: THREE.DoubleSide});
const leafM2 = new THREE.MeshStandardMaterial({color: leafColor2, roughness: 0.7, side: THREE.DoubleSide});

// Flower material
const hasFlowers = preset.flower || preset.flowerDensity;
let flowerM;
if (hasFlowers) {
    flowerM = new THREE.MeshStandardMaterial({
        color: new THREE.Color(preset.flowerColor || '#ff80a0'), roughness: 0.5,
        emissive: new THREE.Color(preset.flowerColor || '#ff80a0'), emissiveIntensity: 0.1,
    });
}

// --- Turtle ---
const root = new THREE.Group();
ctx.entity.add(root);

const stack = [];
let pos = new THREE.Vector3(0, 0, 0);
let dir = new THREE.Vector3(0, 1, 0);
let right = new THREE.Vector3(1, 0, 0);
let len = preset.startLength * scale;
let radius = (preset.fatTrunk ? 0.15 : 0.06) * scale;
let depth = 0;

const angle = preset.angle * Math.PI / 180;
const droop = preset.droop || 0;
const maxSegs = 1000;
let segCount = 0;

function addBranch(from, to, r) {
    if (segCount >= maxSegs) return;
    const diff = new THREE.Vector3().subVectors(to, from);
    const length = diff.length();
    if (length < 0.01) return;
    const topR = r * preset.trunkTaper;
    const segs = depth === 0 ? 6 : 5;
    const geo = new THREE.CylinderGeometry(topR, r, length, segs, 1);
    const mesh = new THREE.Mesh(geo, trunkM);
    mesh.castShadow = true; mesh.receiveShadow = true;
    const mid = new THREE.Vector3().addVectors(from, to).multiplyScalar(0.5);
    mesh.position.copy(mid);
    const axis = new THREE.Vector3(0, 1, 0);
    const q = new THREE.Quaternion().setFromUnitVectors(axis, diff.clone().normalize());
    mesh.quaternion.copy(q);
    root.add(mesh);
    segCount++;
}

function addLeaf(p, size) {
    if (segCount >= maxSegs || preset.leafSize <= 0) return;
    let geo;
    if (preset.leafShape === 'cone') {
        geo = new THREE.ConeGeometry(size, size*2, 6);
    } else if (preset.leafShape === 'star') {
        // Star-shaped leaf (flat pentagon)
        const shape = new THREE.Shape();
        for (let i = 0; i < 5; i++) {
            const a1 = (i/5)*Math.PI*2 - Math.PI/2;
            const a2 = ((i+0.5)/5)*Math.PI*2 - Math.PI/2;
            const r1 = size, r2 = size*0.45;
            if (i === 0) shape.moveTo(Math.cos(a1)*r1, Math.sin(a1)*r1);
            else shape.lineTo(Math.cos(a1)*r1, Math.sin(a1)*r1);
            shape.lineTo(Math.cos(a2)*r2, Math.sin(a2)*r2);
        }
        shape.closePath();
        geo = new THREE.ShapeGeometry(shape);
    } else {
        geo = new THREE.SphereGeometry(size, 6, 4);
    }
    const m = rnd() > 0.5 ? leafM : leafM2;
    const mesh = new THREE.Mesh(geo, m);
    mesh.castShadow = true; mesh.receiveShadow = false;
    mesh.position.copy(p);
    // Random tilt for organic look
    mesh.rotation.set((rnd()-0.5)*0.8, rnd()*Math.PI*2, (rnd()-0.5)*0.5);
    root.add(mesh);
    segCount++;
}

function addFlower(p) {
    if (segCount >= maxSegs || !flowerM) return;
    const fd = preset.flowerDensity || 0.15;
    if (rnd() > fd) return;
    // Small cluster of petals
    const nPetals = 4 + Math.floor(rnd() * 3);
    const fSize = 0.04 * scale + rnd() * 0.03 * scale;
    for (let i = 0; i < nPetals; i++) {
        if (segCount >= maxSegs) break;
        const a = (i / nPetals) * Math.PI * 2;
        const off = 0.02 * scale;
        const geo = new THREE.SphereGeometry(fSize, 4, 3);
        const mesh = new THREE.Mesh(geo, flowerM);
        mesh.position.set(
            p.x + Math.cos(a) * off,
            p.y + rnd() * 0.01,
            p.z + Math.sin(a) * off
        );
        mesh.scale.set(1, 0.6, 1);
        root.add(mesh);
        segCount++;
    }
    // Center pistil
    if (segCount < maxSegs) {
        const cGeo = new THREE.SphereGeometry(fSize*0.5, 4, 3);
        const cM = new THREE.MeshStandardMaterial({color: '#f0e040', roughness: 0.6});
        const cm = new THREE.Mesh(cGeo, cM);
        cm.position.copy(p);
        root.add(cm);
        segCount++;
    }
}

function addFruit(p) {
    if (segCount >= maxSegs) return;
    if (!preset.coconuts || rnd() > 0.3) return;
    const geo = new THREE.SphereGeometry(0.08 * scale, 6, 5);
    const m = new THREE.MeshStandardMaterial({color: '#6a4828', roughness: 0.7});
    const mesh = new THREE.Mesh(geo, m);
    mesh.position.copy(p);
    root.add(mesh);
    segCount++;
}

for (const ch of str) {
    if (segCount >= maxSegs) break;
    if (ch === 'F') {
        const droopV = new THREE.Vector3(0, -droop * depth, 0);
        const jitter = new THREE.Vector3((rnd()-0.5)*0.05, 0, (rnd()-0.5)*0.05);
        // Narrow species constrain horizontal spread
        if (preset.narrow) { jitter.x *= 0.3; jitter.z *= 0.3; }
        const end = pos.clone().add(dir.clone().multiplyScalar(len)).add(droopV).add(jitter);
        addBranch(pos, end, radius);
        pos.copy(end);
        if (depth >= 2 && rnd() < preset.leafDensity) {
            addLeaf(pos, preset.leafSize * scale * (0.7 + rnd()*0.6));
            if (hasFlowers) addFlower(pos);
        }
    } else if (ch === 'X') {
        // X is a growth variable (used by fern) — treated as F for geometry
        if (depth >= 1 && rnd() < preset.leafDensity) {
            addLeaf(pos, preset.leafSize * scale * (0.5 + rnd()*0.5));
        }
    } else if (ch === '+') {
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
        const twist = new THREE.Quaternion().setFromAxisAngle(dir, (rnd()-0.5)*Math.PI*0.5);
        right.applyQuaternion(twist).normalize();
    } else if (ch === ']') {
        if (stack.length > 0) {
            if (depth >= 2 && preset.leafDensity > 0) {
                addLeaf(pos, preset.leafSize * scale * (0.8 + rnd()*0.4));
                if (hasFlowers) addFlower(pos);
            }
            const s = stack.pop();
            pos.copy(s.pos); dir.copy(s.dir); right.copy(s.right);
            len = s.len; radius = s.radius; depth = s.depth;
        }
    }
}

// Palm fronds with coconuts
if (preset.fronds) {
    const topY = pos.y;
    const nFronds = 8 + Math.floor(rnd() * 5);
    for (let i = 0; i < nFronds; i++) {
        const a = (i / nFronds) * Math.PI * 2 + rnd() * 0.3;
        const frondLen = (1.5 + rnd()) * scale;
        const droop2 = 0.3 + rnd() * 0.4;
        const segs = 6;
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
            if (s >= 1) {
                // Alternating leaflets along frond
                for (let side = -1; side <= 1; side += 2) {
                    if (segCount >= maxSegs) break;
                    const leafOff = new THREE.Vector3(
                        Math.cos(a) * 0.15 * scale * side,
                        0.02,
                        -Math.sin(a) * 0.15 * scale * side
                    );
                    const lp = ep.clone().add(leafOff);
                    addLeaf(lp, 0.15 * scale * (1 - t*0.3));
                }
            }
        }
    }
    // Coconut cluster at crown
    if (preset.coconuts) {
        for (let i = 0; i < 3 + Math.floor(rnd()*3); i++) {
            const cp = new THREE.Vector3(
                (rnd()-0.5)*0.15*scale, topY - 0.1*scale, (rnd()-0.5)*0.15*scale
            );
            addFruit(cp);
        }
    }
}

// Bamboo: multiple culms
if (preset.culms) {
    const nCulms = 4 + Math.floor(rnd() * 6);
    for (let c = 0; c < nCulms; c++) {
        if (segCount >= maxSegs) break;
        const cx = (rnd()-0.5) * 0.5 * scale;
        const cz = (rnd()-0.5) * 0.5 * scale;
        const height = (2 + rnd() * 2) * scale;
        const segs = 6 + Math.floor(rnd()*3);
        let bp = new THREE.Vector3(cx, 0, cz);
        const sway = (rnd()-0.5)*0.1;
        for (let s = 0; s < segs; s++) {
            if (segCount >= maxSegs) break;
            const segH = height / segs;
            const ep = new THREE.Vector3(
                cx + sway * (s/segs), bp.y + segH, cz + sway * 0.5 * (s/segs)
            );
            addBranch(bp, ep, 0.025 * scale);
            bp = ep;
            // Node ring
            if (segCount < maxSegs) {
                const nGeo = new THREE.TorusGeometry(0.03*scale, 0.005*scale, 4, 8);
                const nMesh = new THREE.Mesh(nGeo, trunkM);
                nMesh.position.copy(ep);
                nMesh.rotation.x = Math.PI/2;
                root.add(nMesh);
                segCount++;
            }
            // Leaf sprays at top nodes
            if (s >= segs - 3 && rnd() > 0.3) {
                for (let l = 0; l < 2 + Math.floor(rnd()*2); l++) {
                    const la = rnd() * Math.PI * 2;
                    const lp = ep.clone().add(new THREE.Vector3(
                        Math.cos(la)*0.2*scale, 0.05, Math.sin(la)*0.2*scale
                    ));
                    addLeaf(lp, 0.12*scale);
                }
            }
        }
    }
}

// Succulent rosette
if (preset.rosette) {
    const nLeaves = 12 + Math.floor(rnd()*8);
    const layers = 3;
    for (let layer = 0; layer < layers; layer++) {
        const layerR = (0.08 + layer * 0.06) * scale;
        const layerH = layer * 0.03 * scale;
        const nInLayer = Math.floor(nLeaves / layers);
        for (let i = 0; i < nInLayer; i++) {
            if (segCount >= maxSegs) break;
            const a = (i / nInLayer) * Math.PI * 2 + layer * 0.3;
            const geo = new THREE.SphereGeometry(0.04*scale, 5, 4);
            geo.scale(1.8, 0.5, 1);
            const m = rnd() > 0.5 ? leafM : leafM2;
            const mesh = new THREE.Mesh(geo, m);
            mesh.position.set(Math.cos(a)*layerR, layerH, Math.sin(a)*layerR);
            mesh.rotation.set(0, -a, layer * 0.3);
            root.add(mesh);
            segCount++;
        }
    }
}

// Ground cover: scatter small leaves/moss around base
if (!preset.isGroundCover && rnd() > 0.5) {
    const nGround = 3 + Math.floor(rnd() * 5);
    for (let i = 0; i < nGround; i++) {
        if (segCount >= maxSegs) break;
        const gx = (rnd()-0.5) * 1.5 * scale;
        const gz = (rnd()-0.5) * 1.5 * scale;
        const gSize = 0.06 * scale + rnd() * 0.08 * scale;
        const geo = new THREE.SphereGeometry(gSize, 4, 3);
        geo.scale(1.5, 0.3, 1.5);
        const gM = new THREE.MeshStandardMaterial({
            color: new THREE.Color().lerpColors(leafColor, new THREE.Color('#3a5020'), rnd()),
            roughness: 0.8,
        });
        const mesh = new THREE.Mesh(geo, gM);
        mesh.position.set(gx, 0.01, gz);
        root.add(mesh);
        segCount++;
    }
}

// Exposed roots for large trees
if (!preset.isGroundCover && scale > 0.8 && rnd() > 0.4) {
    const nRoots = 3 + Math.floor(rnd()*3);
    for (let i = 0; i < nRoots; i++) {
        if (segCount >= maxSegs) break;
        const ra = (i / nRoots) * Math.PI * 2 + rnd() * 0.5;
        const rLen = (0.3 + rnd() * 0.5) * scale;
        const rp = new THREE.Vector3(0, 0.02, 0);
        const re = new THREE.Vector3(Math.cos(ra)*rLen, -0.05, Math.sin(ra)*rLen);
        addBranch(rp, re, 0.03 * scale);
    }
}

S.built = true;
S.plant = root;
"""


# ===================================================================
# 3. ANIMAL BUILDER SCRIPT (start)
# ===================================================================

ANIMAL_SCRIPT = r"""
const S = ctx.state;
const P = ctx.props;
const species = P.species || 'dog';

if (ctx.entity.isMesh) {
    ctx.entity.material.visible = false;
    ctx.entity.castShadow = false;
}

let rngState = (P.seed || 1) * 127.1;
function rnd() { rngState = (rngState * 16807 + 0.5) % 2147483647; return rngState / 2147483647; }

// 4 size tiers
const tiers = {
    // --- TINY INSECTS (gnat-sized, ~2mm) ---
    gnat:       {tier:'tiny',  bodyLen:0.003, bodyW:0.001, legs:6, wings:2, color:'#303030'},
    midge:      {tier:'tiny',  bodyLen:0.003, bodyW:0.0008, legs:6, wings:2, color:'#404040'},
    fruit_fly:  {tier:'tiny',  bodyLen:0.003, bodyW:0.001, legs:6, wings:2, color:'#604020'},
    // --- INSECTS (bee-sized, ~1-3cm) ---
    bee:        {tier:'insect', bodyLen:0.015, bodyW:0.008, legs:6, wings:2, color:'#c8a020',
                 stripes:true, stripeColor:'#181010'},
    butterfly:  {tier:'insect', bodyLen:0.012, bodyW:0.003, legs:6, wings:2, color:'#2040a0',
                 bigWings:true, wingColor:'#e08020', wingColor2:'#3060c0'},
    beetle:     {tier:'insect', bodyLen:0.02, bodyW:0.012, legs:6, wings:0, color:'#1a3020',
                 shell:true, shellColor:'#2a6030'},
    ant:        {tier:'insect', bodyLen:0.008, bodyW:0.003, legs:6, wings:0, color:'#201010',
                 segments:3},
    dragonfly:  {tier:'insect', bodyLen:0.04, bodyW:0.003, legs:6, wings:4, color:'#2080a0',
                 longBody:true},
    ladybug:    {tier:'insect', bodyLen:0.008, bodyW:0.006, legs:6, wings:0, color:'#d03020',
                 shell:true, shellColor:'#d03020', spots:true},
    // --- PET-SIZED (mouse to cat, ~5-40cm) ---
    mouse:      {tier:'pet', bodyLen:0.06, bodyW:0.025, legs:4, color:'#a09080', tail:true,
                 ears:'round', earSize:0.015},
    rat:        {tier:'pet', bodyLen:0.1, bodyW:0.04, legs:4, color:'#706050', tail:true,
                 ears:'round', earSize:0.018},
    rabbit:     {tier:'pet', bodyLen:0.15, bodyW:0.08, legs:4, color:'#c8b8a0', tail:false,
                 ears:'long', earSize:0.06},
    cat:        {tier:'pet', bodyLen:0.35, bodyW:0.12, legs:4, color:'#806040', tail:true,
                 ears:'pointed', earSize:0.025},
    chicken:    {tier:'pet', bodyLen:0.2, bodyW:0.12, legs:2, color:'#c8a878',
                 beak:true, beakColor:'#e0a020', comb:true},
    frog:       {tier:'pet', bodyLen:0.06, bodyW:0.05, legs:4, color:'#308830',
                 eyes:'bulge', flat:true},
    turtle:     {tier:'pet', bodyLen:0.12, bodyW:0.1, legs:4, color:'#506838',
                 shell:true, shellColor:'#607848', flat:true},
    snake:      {tier:'pet', bodyLen:0.4, bodyW:0.02, legs:0, color:'#506030',
                 segments:8},
    // --- LARGE (horse-sized, 1-3m) ---
    horse:      {tier:'large', bodyLen:1.8, bodyW:0.5, legs:4, color:'#6a4828',
                 head:0.3, tail:true, mane:true, ears:'pointed', earSize:0.08},
    cow:        {tier:'large', bodyLen:1.6, bodyW:0.55, legs:4, color:'#e0d0c0',
                 head:0.28, ears:'round', earSize:0.06, spots:true, spotColor:'#302018'},
    deer:       {tier:'large', bodyLen:1.2, bodyW:0.35, legs:4, color:'#a08050',
                 head:0.22, tail:false, ears:'pointed', earSize:0.06, antlers:true},
    pig:        {tier:'large', bodyLen:0.9, bodyW:0.4, legs:4, color:'#e0a8a0',
                 head:0.2, ears:'floppy', earSize:0.06, snout:true},
    dog:        {tier:'large', bodyLen:0.6, bodyW:0.2, legs:4, color:'#8a6838',
                 head:0.15, tail:true, ears:'floppy', earSize:0.04},
    bear:       {tier:'large', bodyLen:1.5, bodyW:0.65, legs:4, color:'#4a3018',
                 head:0.3, ears:'round', earSize:0.07},
};

const spec = tiers[species] || tiers.dog;
const sc = P.animalScale || 1.0;
const root = new THREE.Group();
ctx.entity.add(root);

const bodyColor = new THREE.Color(P.color || spec.color);
const bodyM = new THREE.MeshStandardMaterial({color: bodyColor, roughness: 0.75});

const bL = spec.bodyLen * sc;
const bW = spec.bodyW * sc;
const bH = bW * (spec.flat ? 0.5 : 0.8);

// Leg height: insect/tiny legs are short, pets medium, large animals taller
const legH = spec.tier === 'tiny' ? bH*0.5
    : spec.tier === 'insect' ? bH*0.8
    : spec.tier === 'pet' ? bH * 1.2
    : bH * 1.5;
const legR = spec.tier === 'large' ? bW*0.1 : bW*0.12;

const baseY = legH + bH/2;

// Body
if (spec.segments && spec.segments > 2) {
    // Segmented body (ant, snake)
    const segLen = bL / spec.segments;
    for (let i = 0; i < spec.segments; i++) {
        const segW = bW * (i === 0 ? 0.7 : i === spec.segments-1 ? 0.6 : 1.0);
        const geo = new THREE.SphereGeometry(segW/2, 6, 5);
        geo.scale(segLen/segW, spec.flat ? 0.5 : 0.8, 1);
        const mesh = new THREE.Mesh(geo, bodyM);
        mesh.position.set(-bL/2 + segLen*(i+0.5), baseY, 0);
        mesh.castShadow = true;
        root.add(mesh);
    }
} else {
    // Ellipsoid body
    const geo = new THREE.SphereGeometry(bL/2, 8, 6);
    geo.scale(1, bH/bL, bW/bL);
    const mesh = new THREE.Mesh(geo, bodyM);
    mesh.position.set(0, baseY, 0);
    mesh.castShadow = true;
    root.add(mesh);
}

// Shell overlay (beetle, turtle, ladybug)
if (spec.shell) {
    const sColor = new THREE.Color(spec.shellColor || spec.color);
    const shellM = new THREE.MeshStandardMaterial({color: sColor, roughness: 0.4, metalness: 0.1});
    const sGeo = new THREE.SphereGeometry(bL*0.48, 8, 6, 0, Math.PI*2, 0, Math.PI*0.55);
    sGeo.scale(1, bH*0.9/bL, bW*1.05/(bL*0.96));
    const sMesh = new THREE.Mesh(sGeo, shellM);
    sMesh.position.set(0, baseY + bH*0.05, 0);
    sMesh.castShadow = true;
    root.add(sMesh);
    // Spots for ladybug
    if (spec.spots && !spec.spotColor) {
        const spotM = new THREE.MeshStandardMaterial({color:'#101010', roughness:0.6});
        for (let i = 0; i < 5; i++) {
            const sGeo2 = new THREE.SphereGeometry(bL*0.05, 4, 3);
            const sm = new THREE.Mesh(sGeo2, spotM);
            const sa = rnd()*Math.PI*0.8 + 0.1;
            sm.position.set(
                (rnd()-0.5)*bL*0.5, baseY + bH*0.4,
                (rnd()-0.5)*bW*0.4
            );
            root.add(sm);
        }
    }
}

// Stripes (bee)
if (spec.stripes) {
    const stripeM = new THREE.MeshStandardMaterial({color: new THREE.Color(spec.stripeColor), roughness: 0.7});
    const nStripes = 3;
    for (let i = 0; i < nStripes; i++) {
        const sx = -bL*0.2 + i * bL*0.2;
        const sGeo = new THREE.TorusGeometry(bW*0.55, bW*0.08, 6, 12);
        const sm = new THREE.Mesh(sGeo, stripeM);
        sm.position.set(sx, baseY, 0);
        sm.rotation.y = Math.PI/2;
        root.add(sm);
    }
}

// Legs
const legM = new THREE.MeshStandardMaterial({
    color: bodyColor.clone().multiplyScalar(0.8), roughness: 0.8
});
if (spec.legs > 0) {
    const pairs = Math.ceil(spec.legs / 2);
    for (let i = 0; i < pairs; i++) {
        const lx = -bL*0.3 + (i / Math.max(pairs-1, 1)) * bL*0.6;
        for (let side = -1; side <= 1; side += 2) {
            const lz = side * bW * 0.4;
            // Upper leg
            const geo = new THREE.CylinderGeometry(legR*0.7, legR, legH, 5);
            const mesh = new THREE.Mesh(geo, legM);
            mesh.position.set(lx, legH/2, lz);
            mesh.castShadow = true;
            root.add(mesh);
            // For insects, add angled segments
            if (spec.tier === 'insect' || spec.tier === 'tiny') {
                const geo2 = new THREE.CylinderGeometry(legR*0.5, legR*0.7, legH*0.7, 4);
                const m2 = new THREE.Mesh(geo2, legM);
                m2.position.set(lx + side*bW*0.1, legH*0.15, lz + side*bW*0.2);
                m2.rotation.z = side * 0.4;
                root.add(m2);
            }
        }
    }
}

// Head
const headSize = spec.head ? spec.head * sc : bW * 0.8;
const headY = baseY + (spec.tier === 'large' ? bH*0.3 : 0);
const headX = bL/2 + headSize*0.3;
const headM = new THREE.MeshStandardMaterial({color: bodyColor, roughness: 0.7});
const headGeo = new THREE.SphereGeometry(headSize/2, 7, 5);
const headMesh = new THREE.Mesh(headGeo, headM);
headMesh.position.set(headX, headY, 0);
headMesh.castShadow = true;
root.add(headMesh);

// Eyes
const eyeSize = headSize * (spec.eyes === 'bulge' ? 0.25 : 0.12);
const eyeM = new THREE.MeshStandardMaterial({color:'#101010', roughness:0.3});
const eyeWhiteM = new THREE.MeshStandardMaterial({color:'#e8e8e0', roughness:0.4});
for (let side = -1; side <= 1; side += 2) {
    if (spec.eyes === 'bulge') {
        // Frog bulging eyes
        const eGeo = new THREE.SphereGeometry(eyeSize, 6, 5);
        const em = new THREE.Mesh(eGeo, eyeWhiteM);
        em.position.set(headX + headSize*0.15, headY + headSize*0.35, side * headSize*0.25);
        root.add(em);
        const pGeo = new THREE.SphereGeometry(eyeSize*0.5, 5, 4);
        const pm = new THREE.Mesh(pGeo, eyeM);
        pm.position.set(headX + headSize*0.25, headY + headSize*0.38, side * headSize*0.25);
        root.add(pm);
    } else {
        const eGeo = new THREE.SphereGeometry(eyeSize, 5, 4);
        const em = new THREE.Mesh(eGeo, eyeM);
        em.position.set(headX + headSize*0.3, headY + headSize*0.15, side * headSize*0.25);
        root.add(em);
    }
}

// Ears
if (spec.ears) {
    const eSize = (spec.earSize || 0.03) * sc;
    const earM = new THREE.MeshStandardMaterial({
        color: bodyColor.clone().multiplyScalar(0.9), roughness: 0.7
    });
    for (let side = -1; side <= 1; side += 2) {
        let geo;
        if (spec.ears === 'long') {
            geo = new THREE.CylinderGeometry(eSize*0.3, eSize*0.4, eSize, 6);
        } else if (spec.ears === 'pointed') {
            geo = new THREE.ConeGeometry(eSize*0.4, eSize, 5);
        } else if (spec.ears === 'floppy') {
            geo = new THREE.SphereGeometry(eSize*0.5, 5, 4);
            geo.scale(1, 1.5, 0.5);
        } else {
            geo = new THREE.SphereGeometry(eSize*0.5, 5, 4);
        }
        const em = new THREE.Mesh(geo, earM);
        const ex = headX - headSize*0.1;
        const ey = headY + headSize*0.35;
        const ez = side * headSize*0.3;
        em.position.set(ex, ey, ez);
        if (spec.ears === 'floppy') em.rotation.z = side * 0.5;
        root.add(em);
    }
}

// Beak (chicken)
if (spec.beak) {
    const bkM = new THREE.MeshStandardMaterial({color: new THREE.Color(spec.beakColor||'#e0a020'), roughness:0.6});
    const bkGeo = new THREE.ConeGeometry(headSize*0.12, headSize*0.3, 5);
    const bk = new THREE.Mesh(bkGeo, bkM);
    bk.position.set(headX + headSize*0.4, headY - headSize*0.05, 0);
    bk.rotation.z = -Math.PI/2;
    root.add(bk);
}
if (spec.comb) {
    const combM = new THREE.MeshStandardMaterial({color:'#d02020', roughness:0.6});
    const cGeo = new THREE.SphereGeometry(headSize*0.15, 5, 4);
    cGeo.scale(0.5, 1, 1);
    const cm = new THREE.Mesh(cGeo, combM);
    cm.position.set(headX, headY + headSize*0.4, 0);
    root.add(cm);
}

// Snout (pig)
if (spec.snout) {
    const snM = new THREE.MeshStandardMaterial({color: bodyColor.clone().multiplyScalar(0.85), roughness:0.7});
    const snGeo = new THREE.CylinderGeometry(headSize*0.15, headSize*0.12, headSize*0.15, 6);
    const sn = new THREE.Mesh(snGeo, snM);
    sn.position.set(headX + headSize*0.4, headY - headSize*0.05, 0);
    sn.rotation.z = Math.PI/2;
    root.add(sn);
    // Nostrils
    const nM = new THREE.MeshStandardMaterial({color:'#303030', roughness:0.5});
    for (let s = -1; s <= 1; s += 2) {
        const nGeo = new THREE.SphereGeometry(headSize*0.03, 4, 3);
        const nm = new THREE.Mesh(nGeo, nM);
        nm.position.set(headX + headSize*0.47, headY - headSize*0.03, s*headSize*0.06);
        root.add(nm);
    }
}

// Antlers (deer)
if (spec.antlers) {
    const aM = new THREE.MeshStandardMaterial({color:'#8a7060', roughness:0.8});
    for (let side = -1; side <= 1; side += 2) {
        const aBase = new THREE.Vector3(headX - headSize*0.1, headY + headSize*0.4, side*headSize*0.2);
        const aTip = new THREE.Vector3(headX - headSize*0.3, headY + headSize*1.0, side*headSize*0.5);
        const diff = new THREE.Vector3().subVectors(aTip, aBase);
        const aLen = diff.length();
        const aGeo = new THREE.CylinderGeometry(0.008*sc, 0.015*sc, aLen, 5);
        const am = new THREE.Mesh(aGeo, aM);
        am.position.copy(aBase.clone().add(aTip).multiplyScalar(0.5));
        const q = new THREE.Quaternion().setFromUnitVectors(
            new THREE.Vector3(0,1,0), diff.normalize());
        am.quaternion.copy(q);
        root.add(am);
        // One tine
        const tGeo = new THREE.CylinderGeometry(0.005*sc, 0.01*sc, aLen*0.4, 4);
        const tm = new THREE.Mesh(tGeo, aM);
        const tBase = aBase.clone().lerp(aTip, 0.6);
        tm.position.set(tBase.x, tBase.y + aLen*0.15, tBase.z + side*0.05*sc);
        tm.rotation.z = side * 0.4;
        root.add(tm);
    }
}

// Mane (horse)
if (spec.mane) {
    const maneM = new THREE.MeshStandardMaterial({color: bodyColor.clone().multiplyScalar(0.6), roughness:0.8});
    for (let i = 0; i < 6; i++) {
        const mx = headX - headSize*0.3 - i * bL*0.06;
        const my = baseY + bH*0.45 - i*0.01;
        const mGeo = new THREE.SphereGeometry(0.03*sc, 4, 3);
        mGeo.scale(1.5, 2, 0.5);
        const mm = new THREE.Mesh(mGeo, maneM);
        mm.position.set(mx, my, 0);
        root.add(mm);
    }
}

// Tail
if (spec.tail) {
    const tailM = new THREE.MeshStandardMaterial({
        color: bodyColor.clone().multiplyScalar(0.7), roughness: 0.8
    });
    const tLen = bL * (spec.tier === 'large' ? 0.5 : 0.6);
    const tR = spec.tier === 'large' ? bW*0.06 : bW*0.1;
    const tGeo = new THREE.CylinderGeometry(tR*0.3, tR, tLen, 5);
    const tm = new THREE.Mesh(tGeo, tailM);
    tm.position.set(-bL/2 - tLen*0.3, baseY + bH*0.1, 0);
    tm.rotation.z = 0.6;
    tm.castShadow = true;
    root.add(tm);
}

// Wings (insects)
if (spec.wings && spec.wings > 0) {
    const wingM = new THREE.MeshStandardMaterial({
        color: spec.bigWings ? new THREE.Color(spec.wingColor || '#e08020')
            : new THREE.Color('#c0d0e0'),
        transparent: !spec.bigWings, opacity: spec.bigWings ? 0.85 : 0.3,
        side: THREE.DoubleSide, roughness: 0.3,
    });
    const wingSize = spec.bigWings ? bL*1.2 : bL*0.6;
    const nWings = spec.wings;
    for (let i = 0; i < nWings; i++) {
        for (let side = -1; side <= 1; side += 2) {
            let geo;
            if (spec.bigWings) {
                // Butterfly wings — rounded triangle
                const shape = new THREE.Shape();
                shape.moveTo(0, 0);
                shape.quadraticCurveTo(wingSize*0.5, wingSize*0.6, wingSize*0.1, wingSize);
                shape.quadraticCurveTo(-wingSize*0.3, wingSize*0.5, 0, 0);
                geo = new THREE.ShapeGeometry(shape);
            } else {
                geo = new THREE.PlaneGeometry(wingSize, wingSize*0.25);
            }
            const wM2 = (spec.bigWings && i === 1)
                ? new THREE.MeshStandardMaterial({
                    color: new THREE.Color(spec.wingColor2 || spec.wingColor || '#3060c0'),
                    side: THREE.DoubleSide, roughness: 0.3, opacity: 0.85, transparent: false,
                }) : wingM;
            const wm = new THREE.Mesh(geo, wM2);
            const wx = -bL*0.1 + i * bL*0.15;
            wm.position.set(wx, baseY + bH*0.4, side * bW*0.3);
            wm.rotation.set(0, side * 0.3, spec.bigWings ? side*0.2 : side * 0.5);
            root.add(wm);
        }
    }
}

// Cow spots
if (spec.spots && spec.spotColor) {
    const spotM = new THREE.MeshStandardMaterial({color: new THREE.Color(spec.spotColor), roughness:0.7});
    for (let i = 0; i < 6; i++) {
        const sGeo = new THREE.SphereGeometry(bL*0.08+rnd()*bL*0.06, 5, 4);
        sGeo.scale(1, 0.3, 1);
        const sm = new THREE.Mesh(sGeo, spotM);
        sm.position.set(
            (rnd()-0.5)*bL*0.6,
            baseY + bH*0.3 + rnd()*bH*0.2,
            (rnd()-0.5)*bW*0.6
        );
        root.add(sm);
    }
}

// Store for animation
S.built = true;
S.animal = root;
S.baseY = baseY;
S.bodyLen = bL;
S.tier = spec.tier;
S.hasWings = (spec.wings || 0) > 0;
S.bigWings = !!spec.bigWings;
"""

# ===================================================================
# 3b. ANIMAL ANIMATE SCRIPT (update)
# ===================================================================

ANIMAL_ANIM_SCRIPT = r"""
const S = ctx.state;
if (!S.built || !S.animal) return;
const t = ctx.time;
const dt = ctx.deltaTime;
const P = ctx.props;

// Movement bounds
const bounds = P.bounds || 10;
const speed = P.speed || 0.5;

// Wander
if (!S.wx) { S.wx = 0; S.wz = 0; S.targetX = 0; S.targetZ = 0; S.timer = 0; }
S.timer -= dt;
if (S.timer <= 0) {
    S.targetX = (Math.random()-0.5) * bounds * 2;
    S.targetZ = (Math.random()-0.5) * bounds * 2;
    S.timer = 2 + Math.random() * 5;
}
const dx = S.targetX - S.wx;
const dz = S.targetZ - S.wz;
const dist = Math.sqrt(dx*dx + dz*dz);
if (dist > 0.05) {
    const step = Math.min(speed * dt, dist);
    S.wx += (dx/dist) * step;
    S.wz += (dz/dist) * step;
    // Face direction of movement
    S.animal.rotation.y = Math.atan2(dx, dz);
}
S.animal.position.x = S.wx;
S.animal.position.z = S.wz;

// Bobbing walk animation
const walkPhase = t * speed * 8;
const bobAmt = S.tier === 'large' ? 0.03 : S.tier === 'pet' ? 0.01 : 0.002;
S.animal.position.y = Math.abs(Math.sin(walkPhase)) * bobAmt;

// Wing flap for flying insects
if (S.hasWings) {
    const wings = [];
    S.animal.traverse(c => {
        if (c.isMesh && c.geometry && c.geometry.type === 'ShapeGeometry') wings.push(c);
        if (c.isMesh && c.geometry && c.geometry.type === 'PlaneGeometry') wings.push(c);
    });
    const flapSpeed = S.bigWings ? 3 : 20;
    const flapAmt = S.bigWings ? 0.4 : 0.8;
    wings.forEach((w, i) => {
        const side = i % 2 === 0 ? 1 : -1;
        w.rotation.z = side * (0.3 + Math.sin(t * flapSpeed) * flapAmt);
    });
    // Tiny/insect hover
    if (S.tier === 'tiny' || S.tier === 'insect') {
        S.animal.position.y = S.baseY * 0.5 + Math.sin(t * 2) * S.bodyLen * 0.5;
    }
}
"""

# ===================================================================
# 4. NPC LOD MANAGER SCRIPT (update)
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
        animal_script = _script('Animal Builder', 'start', ANIMAL_SCRIPT,
            'Procedural animals: 4 size tiers (tiny/insect/pet/large), 22 species.')
        animal_anim = _script('Animal Animate', 'update', ANIMAL_ANIM_SCRIPT,
            'Wander + walk bob + wing flap animation for animals.')
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

        # --- Animals ---
        ANIMAL_CONFIGS = [
            ('City Pigeon', 'chicken', 5, 12, 0.15, 8),
            ('Park Dog', 'dog', 30, 30, 1.0, 12),
            ('Alley Cat', 'cat', -20, 5, 1.0, 10),
            ('Stray Cat', 'cat', 15, -15, 1.0, 8),
            ('Park Squirrel', 'mouse', 32, 36, 0.8, 6),
            ('Butterfly 1', 'butterfly', 8, 20, 1.0, 5),
            ('Butterfly 2', 'butterfly', -5, 25, 1.0, 5),
            ('Bee', 'bee', -8, 18, 1.0, 4),
        ]

        for name, sp, x, z, ascale, bounds in ANIMAL_CONFIGS:
            e = Entity.objects.create(
                world=world, name=name, primitive='box',
                primitive_color='#000000',
                pos_x=x, pos_y=0, pos_z=z,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            attachments.append(EntityScript(entity=e, script=animal_script, props={
                'species': sp, 'animalScale': ascale, 'seed': hash(name) % 10000,
            }))
            attachments.append(EntityScript(entity=e, script=animal_anim, props={
                'bounds': bounds, 'speed': round(0.2 + rng.random() * 0.6, 2),
            }))

        EntityScript.objects.bulk_create(attachments)

        total = Entity.objects.filter(world=world).count()
        n_animals = len(ANIMAL_CONFIGS)
        self.stdout.write(self.style.SUCCESS(
            f'Velour Metropolis created: {total} entities, '
            f'{len(BUILDING_CONFIGS)} buildings, {len(PLANT_CONFIGS)} plants, '
            f'{len(NAMES)} V6 NPCs, {n_animals} animals.'
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
