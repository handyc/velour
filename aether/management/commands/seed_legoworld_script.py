"""Register the legoworld-render Aether script.

Reads `ctx.props.bricks` — a flat list of
[w, d, plates, color_hex, x, y, z, studs?] tuples produced by Legolith's
`world_to_bricks()` — and builds the matching three.js geometry: one
BoxGeometry mesh per brick body, one InstancedMesh per stud color for
the studs. LDraw-canonical ratios are preserved exactly; only the
absolute size depends on `ctx.props.scale` (meters per stud).

    venv/bin/python manage.py seed_legoworld_script

Idempotent — re-running upserts the script code.
"""

from django.core.management.base import BaseCommand

from aether.models import Script


SCRIPT_CODE = r"""
// Legolith brick payload renderer for Aether.
//
// Coordinate convention:
//   Legolith uses (x=stud, y=stud, z=plate-height) with z pointing up.
//   Three.js uses (x, y=up, z) so we map legolith.y -> three.z and
//   legolith.z -> three.y. The 32-stud baseplate is centered on the
//   world origin via `center` (default 16 = half a baseplate).
//
// LDraw ratios (preserved exactly; do not retune without a real reason):
//   1 plate  = 0.4 stud-units tall
//   stud R   = 0.30 stud-units
//   stud H   = 0.20 stud-units
const P = ctx.props || {};
const SCALE = P.scale || 0.4;            // meters per stud
const SHOW_STUDS = P.showStuds !== false;
const CENTER = (P.center != null) ? P.center : 16;
const PLATE_H = 0.4;
const STUD_R = 0.30;
const STUD_H = 0.20;
const STUD_SEGMENTS = P.studSegments || 10;

const bricks = P.bricks || [];
if (!bricks.length) return;

if (ctx.entity.isMesh) {
    ctx.entity.material.visible = false;
    ctx.entity.castShadow = false;
}

const matCache = {};
function mat(color) {
    if (!matCache[color]) {
        matCache[color] = new THREE.MeshStandardMaterial({
            color: color, roughness: 0.5, metalness: 0.0,
        });
    }
    return matCache[color];
}

// One BoxGeometry per (w,d,plates) combo, shared across bricks.
const bodyGeoCache = {};
function bodyGeo(w, d, plates) {
    const k = w + 'x' + d + 'x' + plates;
    if (!bodyGeoCache[k]) {
        bodyGeoCache[k] = new THREE.BoxGeometry(
            w * SCALE, plates * PLATE_H * SCALE, d * SCALE,
        );
    }
    return bodyGeoCache[k];
}

const studsByColor = {};
function pushStud(color, sx, sy, sz) {
    if (!studsByColor[color]) studsByColor[color] = [];
    studsByColor[color].push([sx, sy, sz]);
}

const root = new THREE.Group();
root.name = 'legoworld';

let bodyCount = 0;
for (let bi = 0; bi < bricks.length; bi++) {
    const b = bricks[bi];
    const w = b[0], d = b[1], plates = b[2], color = b[3];
    const lx = b[4], ly = b[5], lz = b[6];
    const wantStuds = (b.length > 7) ? !!b[7] : true;
    const h = plates * PLATE_H;

    const cx = (lx + w / 2 - CENTER) * SCALE;
    const cz = (ly + d / 2 - CENTER) * SCALE;
    const cy = (lz + h / 2) * SCALE;

    const mesh = new THREE.Mesh(bodyGeo(w, d, plates), mat(color));
    mesh.position.set(cx, cy, cz);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    root.add(mesh);
    bodyCount++;

    if (SHOW_STUDS && wantStuds) {
        const studTopY = (lz + h) * SCALE;
        const studHm = STUD_H * SCALE;
        for (let i = 0; i < w; i++) {
            for (let j = 0; j < d; j++) {
                const sx = (lx + i + 0.5 - CENTER) * SCALE;
                const sz = (ly + j + 0.5 - CENTER) * SCALE;
                const sy = studTopY + studHm / 2;
                pushStud(color, sx, sy, sz);
            }
        }
    }
}

// One InstancedMesh per stud color — single draw call per color.
const studGeo = new THREE.CylinderGeometry(
    STUD_R * SCALE, STUD_R * SCALE, STUD_H * SCALE, STUD_SEGMENTS,
);
const dummy = new THREE.Object3D();
let studCount = 0;
for (const color in studsByColor) {
    const list = studsByColor[color];
    if (!list.length) continue;
    const im = new THREE.InstancedMesh(studGeo, mat(color), list.length);
    for (let i = 0; i < list.length; i++) {
        const s = list[i];
        dummy.position.set(s[0], s[1], s[2]);
        dummy.rotation.set(0, 0, 0);
        dummy.scale.set(1, 1, 1);
        dummy.updateMatrix();
        im.setMatrixAt(i, dummy.matrix);
    }
    im.instanceMatrix.needsUpdate = true;
    im.castShadow = true;
    im.receiveShadow = true;
    root.add(im);
    studCount += list.length;
}

ctx.state.legoworldStats = {
    bricks: bodyCount, studs: studCount,
    colors: Object.keys(studsByColor).length,
};

ctx.entity.add(root);
"""  # noqa: E501


class Command(BaseCommand):
    help = 'Register / update the legoworld-render Aether script.'

    def handle(self, *args, **opts):
        s, created = Script.objects.get_or_create(
            slug='legoworld-render',
            defaults={
                'name': 'Legoworld Brick Renderer',
                'event': 'start',
                'code': SCRIPT_CODE,
                'is_builtin': True,
                'description': (
                    'Renders a Legolith brick payload as proper studded '
                    'bricks in three.js. Accepts ctx.props.bricks (list of '
                    '[w,d,plates,color,x,y,z,studs?]) plus ctx.props.scale '
                    '(meters per stud, default 0.4). LDraw ratios preserved.'
                ),
            },
        )
        if not created and s.code != SCRIPT_CODE:
            s.code = SCRIPT_CODE
            s.event = 'start'
            s.save()
            self.stdout.write(self.style.SUCCESS(
                'Updated legoworld-render script.'))
        elif created:
            self.stdout.write(self.style.SUCCESS(
                'Created legoworld-render script.'))
        else:
            self.stdout.write('legoworld-render script unchanged.')
        self.stdout.write(f'  code length: {len(s.code)} chars')
