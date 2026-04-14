"""Register the l-system-building Aether script.

This is the real L-system architecture renderer: it actually runs the
grammar (axiom, rules, iterations, angle) and produces recursive box-
based geometry — walls grow from F tokens, branches become side-wings,
and roof caps land on every branch tip according to the species'
roof_style.

    venv/bin/python manage.py seed_lsystem_building_script

Idempotent — re-running upserts the script code.
"""

from django.core.management.base import BaseCommand

from aether.models import Script


SCRIPT_CODE = r"""
// Architecture interpretation of an L-system grammar. Unlike plants,
// buildings stay VERTICAL — the `F` token always grows up. `+` and `-`
// rotate a horizontal `right` vector in the XZ plane. On entering a
// branch (`[`), the branch anchors at the current trunk height and the
// next `F` shifts laterally by (parentW + childW)/2 in the `right`
// direction before rising vertically — producing an attached wing, not
// an angled tree branch.

const S = ctx.state;
const P = ctx.props;
const iterations = Math.min(P.iterations || 3, 3);
const scale = P.scale || 1.0;

if (ctx.entity.isMesh) {
    ctx.entity.material.visible = false;
    ctx.entity.castShadow = false;
}

let rngState = (P.seed || 42) * 127.1;
function rnd() { rngState = (rngState * 16807 + 0.5) % 2147483647; return rngState / 2147483647; }

function parseRules(r) {
    if (!r) return [{F: 'F'}];
    if (typeof r === 'string') {
        const parts = r.split(/[,\n;]+/).map(s => s.trim()).filter(Boolean);
        const dict = {};
        for (const p of parts) {
            const eq = p.indexOf('=');
            if (eq > 0) dict[p.slice(0, eq).trim()] = p.slice(eq + 1).trim();
        }
        return [dict];
    }
    if (Array.isArray(r)) return r.length ? r : [{F: 'F'}];
    return [{F: 'F'}];
}

const axiom = P.axiom || 'F';
const ruleSets = parseRules(P.rules);
const lengthFactor = P.lengthFactor || 0.65;
const startLen = P.startLength || 0.8;
const taper = P.trunkTaper || 0.7;

const wallW = (P.wallWidth || 1.0) * scale;
const floorH = (P.floorHeight || 1.5) * scale;
const wallC = new THREE.Color(P.wallColor || P.color || '#a08870');
const wallC2 = new THREE.Color(P.wallColor2 || '#8a7860');
const roofC = new THREE.Color(P.roofColor || P.roof || '#6a3020');
const winC = new THREE.Color(P.windowColor || '#ffe880');
const doorC = new THREE.Color(P.doorColor || '#4a3520');
const hasWindows = P.hasWindows !== false;
const winDensity = P.windowDensity != null ? P.windowDensity : 0.5;
const roofStyle = P.roofStyle || 'gable';
const hasChimney = !!P.hasChimney;
const hasBalcony = !!P.hasBalcony;
const hasColumns = !!P.hasColumns;

function rewrite(str) {
    const rules = ruleSets[Math.floor(rnd() * ruleSets.length)];
    let out = '';
    for (const ch of str) out += (rules[ch] !== undefined ? rules[ch] : ch);
    return out;
}
let str = axiom;
for (let i = 0; i < iterations; i++) str = rewrite(str);

const wallM  = new THREE.MeshStandardMaterial({color: wallC,  roughness: 0.85});
const wallM2 = new THREE.MeshStandardMaterial({color: wallC2, roughness: 0.85});
const roofM  = new THREE.MeshStandardMaterial({color: roofC,  roughness: 0.75});
const winM   = new THREE.MeshStandardMaterial({
    color: winC, emissive: winC, emissiveIntensity: 0.35, roughness: 0.2
});
const doorM  = new THREE.MeshStandardMaterial({color: doorC, roughness: 0.8});

const root = new THREE.Group();
ctx.entity.add(root);
S.building = root;

// Turtle state. `dir` is always (0,1,0) in this interpretation —
// buildings rise. `right` is a horizontal unit vector that `+`/`-`
// rotate around Y, used for wing offsets.
const stack = [];
let pos = new THREE.Vector3(0, 0, 0);
let right = new THREE.Vector3(1, 0, 0);
let len = startLen * floorH;
let width = wallW;
let parentWidth = wallW;
let depth = 0;
// Set to true after `[`; the first F in a branch applies a lateral
// offset before drawing. Subsequent F's in the branch rise directly.
let branchFresh = false;

const maxSegs = 300;
let segCount = 0;

function addWallSegment(basePos, h, w) {
    if (segCount >= maxSegs) return;
    if (h < 0.05) return;
    const geo = new THREE.BoxGeometry(w, h, w);
    const mat = (depth % 2 === 0) ? wallM : wallM2;
    const mesh = new THREE.Mesh(geo, mat);
    mesh.castShadow = true; mesh.receiveShadow = true;
    mesh.position.set(basePos.x, basePos.y + h / 2, basePos.z);
    root.add(mesh);
    segCount++;

    if (hasWindows && h > 0.3) {
        const nFloors = Math.max(1, Math.floor(h / Math.max(0.9, floorH * 0.9)));
        const half = w / 2 + 0.02;
        const faces = [
            {axis: new THREE.Vector3( 1, 0, 0), sign:  1},
            {axis: new THREE.Vector3( 1, 0, 0), sign: -1},
            {axis: new THREE.Vector3( 0, 0, 1), sign:  1},
            {axis: new THREE.Vector3( 0, 0, 1), sign: -1},
        ];
        for (let f = 0; f < nFloors; f++) {
            const yMid = basePos.y + (f + 0.5) * (h / nFloors);
            for (const face of faces) {
                if (rnd() > winDensity) continue;
                if (segCount >= maxSegs) return;
                const winW = w * 0.45;
                const winH = (h / nFloors) * 0.55;
                const wGeo = new THREE.BoxGeometry(winW, winH, 0.05);
                const wm = new THREE.Mesh(wGeo, winM);
                wm.position.set(
                    basePos.x + face.axis.x * face.sign * half,
                    yMid,
                    basePos.z + face.axis.z * face.sign * half,
                );
                if (face.axis.x !== 0) wm.rotation.y = Math.PI / 2;
                root.add(wm);
                segCount++;
            }
        }
    }
}

function addRoofCap(p, w, style) {
    if (segCount >= maxSegs) return;
    if (!style || style === 'none' || style === 'flat') return;
    let geo, h;
    if (style === 'spire') {
        h = w * 2.6; geo = new THREE.ConeGeometry(w * 0.6, h, 6);
    } else if (style === 'dome') {
        h = w * 0.7; geo = new THREE.SphereGeometry(w * 0.75, 10, 6, 0, Math.PI*2, 0, Math.PI/2);
    } else if (style === 'hip') {
        h = w * 0.8; geo = new THREE.ConeGeometry(w * 0.85, h, 4);
    } else { // gable
        h = w * 0.9; geo = new THREE.ConeGeometry(w * 0.85, h, 4);
    }
    const mesh = new THREE.Mesh(geo, roofM);
    mesh.castShadow = true; mesh.receiveShadow = true;
    mesh.position.copy(p);
    mesh.position.y += (style === 'dome') ? 0 : h / 2;
    if (style === 'gable') mesh.rotation.y = Math.PI / 4;
    root.add(mesh);
    segCount++;
}

function rotRight(sign) {
    // Rotate `right` 90° around Y (horizontal plane) — architecture
    // angles are always right-angles regardless of species `angle`.
    const c = 0, s = sign;
    const nx = right.x * c - right.z * s;
    const nz = right.x * s + right.z * c;
    right.set(nx, 0, nz).normalize();
}

for (const ch of str) {
    if (segCount >= maxSegs) break;
    if (ch === 'F') {
        if (branchFresh) {
            const off = (parentWidth + width) / 2;
            pos.x += right.x * off;
            pos.z += right.z * off;
            branchFresh = false;
        }
        addWallSegment(pos, len, width);
        pos.y += len;
    } else if (ch === '+') {
        rotRight(+1);
    } else if (ch === '-') {
        rotRight(-1);
    } else if (ch === '[') {
        stack.push({
            pos: pos.clone(), right: right.clone(),
            len, width, parentWidth, depth, branchFresh,
        });
        parentWidth = width;
        len *= lengthFactor;
        width *= taper;
        depth++;
        branchFresh = true;
    } else if (ch === ']') {
        if (stack.length > 0) {
            addRoofCap(pos, width, roofStyle);
            const s = stack.pop();
            pos.copy(s.pos); right.copy(s.right);
            len = s.len; width = s.width;
            parentWidth = s.parentWidth;
            depth = s.depth; branchFresh = s.branchFresh;
        }
    }
}
addRoofCap(pos, width, roofStyle);

// Door at initial trunk base, z+ face
{
    const dw = Math.min(wallW * 0.55, 1.4);
    const dh = Math.min(floorH * 0.95, 2.4);
    const dGeo = new THREE.BoxGeometry(dw, dh, 0.1);
    const door = new THREE.Mesh(dGeo, doorM);
    door.position.set(0, dh / 2, wallW / 2 + 0.06);
    root.add(door);
}

// Chimney: small box attached to the side of the main trunk, low level.
if (hasChimney && segCount < maxSegs) {
    const chm = new THREE.Mesh(
        new THREE.BoxGeometry(wallW * 0.3, floorH * 0.9, wallW * 0.3),
        new THREE.MeshStandardMaterial({color: '#4a3020', roughness: 0.85})
    );
    chm.position.set(wallW * 0.35, floorH * 1.2, wallW * 0.35);
    chm.castShadow = true;
    root.add(chm);
    segCount++;
}

// Classical columns flanking the entrance
if (hasColumns) {
    for (const xOff of [-wallW * 0.75, wallW * 0.75]) {
        if (segCount >= maxSegs) break;
        const col = new THREE.Mesh(
            new THREE.CylinderGeometry(wallW * 0.12, wallW * 0.15, floorH * 1.6, 10),
            wallM
        );
        col.position.set(xOff, floorH * 0.8, wallW * 0.55);
        col.castShadow = true;
        root.add(col);
        segCount++;
    }
}

// Balcony: a thin slab halfway up the trunk, jutting out front
if (hasBalcony && segCount < maxSegs) {
    const b = new THREE.Mesh(
        new THREE.BoxGeometry(wallW * 1.3, 0.15, wallW * 0.6),
        wallM2
    );
    b.position.set(0, floorH * 1.8, wallW * 0.7);
    b.castShadow = true;
    root.add(b);
    segCount++;
}
"""  # noqa: E501


class Command(BaseCommand):
    help = 'Register / update the l-system-building Aether script.'

    def handle(self, *args, **opts):
        s, created = Script.objects.get_or_create(
            slug='l-system-building',
            defaults={
                'name': 'L-System Building',
                'event': 'start',
                'code': SCRIPT_CODE,
                'description': (
                    'Real L-system architecture renderer. Runs the species '
                    'grammar (axiom/rules/iterations/angle) and produces '
                    'recursive box-based geometry: F=wall segment, []=wings, '
                    '+/-=rotations, tips=roof caps, window boxes on side '
                    'faces. Driven entirely by PlantSpecies.to_aether_props().'
                ),
            },
        )
        if not created and s.code != SCRIPT_CODE:
            s.code = SCRIPT_CODE
            s.event = 'start'
            s.save()
            self.stdout.write(self.style.SUCCESS(
                'Updated existing l-system-building script.'))
        elif created:
            self.stdout.write(self.style.SUCCESS(
                'Created l-system-building script.'))
        else:
            self.stdout.write('l-system-building script unchanged.')
        self.stdout.write(f'  code length: {len(s.code)} chars')
