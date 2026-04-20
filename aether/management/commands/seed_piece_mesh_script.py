"""Register the piece-mesh-render Aether script.

Renders a Room Planner piece as real extruded geometry instead of
the default box primitive. Reads:

    ctx.props.polygon     list of [x_cm, y_cm] vertices, (0,0) at the
                          piece's SW corner (matches the roomplanner
                          placement convention)
    ctx.props.heightCm    extrusion depth in cm
    ctx.props.color       hex color for the mesh

The script centres the polygon on the entity origin so the entity's
own pos_x/pos_y/pos_z and rot_y still place and orient the piece
exactly like the box path did.

    venv/bin/python manage.py seed_piece_mesh_script

Idempotent — re-running upserts the script code.
"""

from django.core.management.base import BaseCommand

from aether.models import Script


SCRIPT_CODE = r"""
// Room Planner piece extrusion renderer.
//
// Turns a 2D polygon + height into a real three.js ExtrudeGeometry so
// L-shaped desks, round tables, corner shelves etc. show up in Aether
// with their actual footprint instead of the plan's bounding box.
//
// Coordinate convention:
//   polygon is cm in the XZ plane with (0,0) at the piece's SW corner.
//   heightCm extrudes along +Y.
//   We centre on the bounding box so the entity's pos_* places the
//   piece's centre — same anchor the box path uses.
const P = ctx.props || {};
const polyCm = P.polygon || [];
if (polyCm.length < 3) return;

const hCm = P.heightCm || 0;
if (hCm <= 0) return;

const color = P.color || '#808080';

// Bounding box → centre offset, in cm.
let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
for (let i = 0; i < polyCm.length; i++) {
    const v = polyCm[i];
    if (v[0] < minX) minX = v[0];
    if (v[0] > maxX) maxX = v[0];
    if (v[1] < minY) minY = v[1];
    if (v[1] > maxY) maxY = v[1];
}
const cxCm = (minX + maxX) / 2;
const cyCm = (minY + maxY) / 2;

const shape = new THREE.Shape();
for (let i = 0; i < polyCm.length; i++) {
    const x = (polyCm[i][0] - cxCm) / 100;          // cm -> m, centred
    const y = (polyCm[i][1] - cyCm) / 100;
    if (i === 0) shape.moveTo(x, y);
    else         shape.lineTo(x, y);
}
shape.closePath();

const geom = new THREE.ExtrudeGeometry(shape, {
    depth: hCm / 100, bevelEnabled: false, curveSegments: 12,
});
// ExtrudeGeometry builds in the XY plane and extrudes along +Z.
// Rotate so the footprint lies on XZ (ground plane) and the
// extrusion direction becomes +Y — same orientation a plain
// BoxGeometry would have.
geom.rotateX(-Math.PI / 2);
// Centre the mesh on its own origin via the bounding box. This is
// robust to either three.js extrude direction (prior comment assumed
// the wrong one and left the mesh floating half its height above
// the floor). Entity pos_y = base_y + height/2 then puts the bottom
// on the floor — matching the plain box path.
geom.computeBoundingBox();
const bb = geom.boundingBox;
geom.translate(0, -(bb.min.y + bb.max.y) / 2, 0);

const mat = new THREE.MeshStandardMaterial({
    color: color, roughness: 0.6, metalness: 0.0,
});

const mesh = new THREE.Mesh(geom, mat);
mesh.castShadow = true;
mesh.receiveShadow = true;

if (ctx.entity.isMesh) {
    ctx.entity.material.visible = false;
    ctx.entity.castShadow = false;
}
ctx.entity.add(mesh);
"""


class Command(BaseCommand):
    help = 'Register / update the piece-mesh-render Aether script.'

    def handle(self, *args, **opts):
        s, created = Script.objects.get_or_create(
            slug='piece-mesh-render',
            defaults={
                'name': 'Room Planner Piece Mesh',
                'event': 'start',
                'code': SCRIPT_CODE,
                'is_builtin': True,
                'description': (
                    'Renders a Room Planner FurniturePiece as real '
                    'extruded geometry. Props: polygon (list of '
                    '[x_cm, y_cm]), heightCm, color. Centres on '
                    'bounding box so the entity transform still '
                    'places the piece correctly.'
                ),
            },
        )
        if not created and s.code != SCRIPT_CODE:
            s.code = SCRIPT_CODE
            s.event = 'start'
            s.save()
            self.stdout.write(self.style.SUCCESS(
                'Updated piece-mesh-render script.'))
        elif created:
            self.stdout.write(self.style.SUCCESS(
                'Created piece-mesh-render script.'))
        else:
            self.stdout.write('piece-mesh-render script unchanged.')
        self.stdout.write(f'  code length: {len(s.code)} chars')
