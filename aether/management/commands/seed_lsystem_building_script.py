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
const S = ctx.state;
const P = ctx.props;
const iterations = Math.min(P.iterations || 3, 4);
const scale = P.scale || 1.0;

if (ctx.entity.isMesh) {
    ctx.entity.material.visible = false;
    ctx.entity.castShadow = false;
}

let rngState = (P.seed || 42) * 127.1;
function rnd() { rngState = (rngState * 16807 + 0.5) % 2147483647; return rngState / 2147483647; }

// Parse rules — support both "F=FF[+F]" strings and [{F:'FF'}] lists.
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
const angle = (P.angle || 90) * Math.PI / 180;
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

const stack = [];
let pos = new THREE.Vector3(0, 0, 0);
let dir = new THREE.Vector3(0, 1, 0);
let right = new THREE.Vector3(1, 0, 0);
let len = startLen * floorH;
let width = wallW;
let depth = 0;

const maxSegs = 600;
let segCount = 0;

function addWallSegment(from, to, w) {
    if (segCount >= maxSegs) return;
    const diff = new THREE.Vector3().subVectors(to, from);
    const length = diff.length();
    if (length < 0.05) return;
    const geo = new THREE.BoxGeometry(w, length, w);
    const mat = (depth % 2 === 0) ? wallM : wallM2;
    const mesh = new THREE.Mesh(geo, mat);
    mesh.castShadow = true; mesh.receiveShadow = true;
    const mid = new THREE.Vector3().addVectors(from, to).multiplyScalar(0.5);
    mesh.position.copy(mid);
    const axis = new THREE.Vector3(0, 1, 0);
    const q = new THREE.Quaternion().setFromUnitVectors(axis, diff.clone().normalize());
    mesh.quaternion.copy(q);
    root.add(mesh);
    segCount++;

    // Windows on the four side faces (perpendicular to the segment axis).
    if (hasWindows && length > 0.3) {
        // Build two perpendicular axes that are perpendicular to diff.
        const up = diff.clone().normalize();
        let ax1 = new THREE.Vector3(1, 0, 0);
        if (Math.abs(ax1.dot(up)) > 0.9) ax1.set(0, 0, 1);
        ax1 = ax1.sub(up.clone().multiplyScalar(ax1.dot(up))).normalize();
        const ax2 = new THREE.Vector3().crossVectors(up, ax1).normalize();

        const nWin = Math.max(1, Math.floor(length / (floorH * 0.95)));
        for (let i = 0; i < nWin; i++) {
            for (const [axis2, sign] of [[ax1, 1], [ax1, -1], [ax2, 1], [ax2, -1]]) {
                if (rnd() > winDensity) continue;
                if (segCount >= maxSegs) return;
                const t = (i + 0.5) / nWin;
                const along = new THREE.Vector3().lerpVectors(from, to, t);
                const out = axis2.clone().multiplyScalar(sign * (w / 2 + 0.02));
                const winW = w * 0.45;
                const winH = (length / nWin) * 0.55;
                const wGeo = new THREE.BoxGeometry(winW, winH, 0.05);
                const wm = new THREE.Mesh(wGeo, winM);
                wm.position.copy(along).add(out);
                wm.lookAt(along.clone().add(axis2.clone().multiplyScalar(sign * 2)));
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

for (const ch of str) {
    if (segCount >= maxSegs) break;
    if (ch === 'F') {
        const end = pos.clone().add(dir.clone().multiplyScalar(len));
        addWallSegment(pos, end, width);
        pos.copy(end);
    } else if (ch === '+') {
        const rotAxis = new THREE.Vector3().crossVectors(dir, right).normalize();
        if (rotAxis.length() < 0.01) rotAxis.set(0, 0, 1);
        const q = new THREE.Quaternion().setFromAxisAngle(rotAxis, angle);
        dir.applyQuaternion(q).normalize();
    } else if (ch === '-') {
        const rotAxis = new THREE.Vector3().crossVectors(dir, right).normalize();
        if (rotAxis.length() < 0.01) rotAxis.set(0, 0, 1);
        const q = new THREE.Quaternion().setFromAxisAngle(rotAxis, -angle);
        dir.applyQuaternion(q).normalize();
    } else if (ch === '[') {
        stack.push({
            pos: pos.clone(), dir: dir.clone(), right: right.clone(),
            len, width, depth
        });
        len *= lengthFactor;
        width *= taper;
        depth++;
        // Small twist so branches don't all align
        const twist = new THREE.Quaternion().setFromAxisAngle(dir, (rnd()-0.5) * Math.PI * 0.25);
        right.applyQuaternion(twist).normalize();
    } else if (ch === ']') {
        if (stack.length > 0) {
            addRoofCap(pos, width, roofStyle);
            const s = stack.pop();
            pos.copy(s.pos); dir.copy(s.dir); right.copy(s.right);
            len = s.len; width = s.width; depth = s.depth;
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
