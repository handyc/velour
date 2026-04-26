"""Register the piece-wireframe-render Aether script.

Renders a Room Planner piece as a 3D wireframe — a graph of
vertices connected by edges. Useful for furniture whose true
shape is a structural skeleton (a chair: legs + back + seat
edge), not a solid extrusion.

    ctx.props.vertices  list of [x_cm, y_cm, z_cm], (0,0,0) at
                        the piece's bottom-SW corner. y is up.
    ctx.props.edges     list of [i, j] — pairs of vertex indices
                        forming line segments.
    ctx.props.color     hex color for the lines.
    ctx.props.lineWidth pixel width of the lines (default 2).

The script centres the wireframe on its bounding-box origin so
the entity's pos_x/pos_y/pos_z places the centre, exactly like
piece-mesh-render does.

    venv/bin/python manage.py seed_piece_wireframe_script

Idempotent — re-running upserts the script code.
"""

from django.core.management.base import BaseCommand

from aether.models import Script


SCRIPT_CODE = r"""
// Room Planner piece wireframe renderer.
// Vertices in cm with (0,0,0) at the piece's SW-bottom corner.
// Edges are pairs of indices into the vertex list.
const P = ctx.props || {};
const verts = P.vertices || [];
const edges = P.edges || [];
if (verts.length < 2 || edges.length < 1) return;

const color = P.color || '#aaaaaa';
const lineWidth = P.lineWidth || 2;

let minX = Infinity, maxX = -Infinity;
let minY = Infinity, maxY = -Infinity;
let minZ = Infinity, maxZ = -Infinity;
for (let i = 0; i < verts.length; i++) {
    const v = verts[i];
    if (v[0] < minX) minX = v[0]; if (v[0] > maxX) maxX = v[0];
    if (v[1] < minY) minY = v[1]; if (v[1] > maxY) maxY = v[1];
    if (v[2] < minZ) minZ = v[2]; if (v[2] > maxZ) maxZ = v[2];
}
const cx = (minX + maxX) / 2;
const cz = (minZ + maxZ) / 2;
// y stays anchored at min (we place pos_y at base + height/2 so
// the bottom sits on the floor — same convention as the box path).

const positions = [];
for (let k = 0; k < edges.length; k++) {
    const e = edges[k];
    const a = verts[e[0]];
    const b = verts[e[1]];
    if (!a || !b) continue;
    const ay = (a[1] - minY);
    const by = (b[1] - minY);
    positions.push(
        (a[0] - cx) / 100, (ay - (maxY - minY) / 2) / 100, (a[2] - cz) / 100,
        (b[0] - cx) / 100, (by - (maxY - minY) / 2) / 100, (b[2] - cz) / 100
    );
}

const geom = new THREE.BufferGeometry();
geom.setAttribute('position',
    new THREE.Float32BufferAttribute(positions, 3));

const mat = new THREE.LineBasicMaterial({
    color: color, linewidth: lineWidth,
});
const lines = new THREE.LineSegments(geom, mat);

if (ctx.entity.isMesh) {
    ctx.entity.material.visible = false;
    ctx.entity.castShadow = false;
}
ctx.entity.add(lines);
"""


class Command(BaseCommand):
    help = 'Register / update the piece-wireframe-render Aether script.'

    def handle(self, *args, **opts):
        s, created = Script.objects.get_or_create(
            slug='piece-wireframe-render',
            defaults={
                'name': 'Room Planner Piece Wireframe',
                'event': 'start',
                'code': SCRIPT_CODE,
                'is_builtin': True,
                'description': (
                    'Renders a Room Planner FurniturePiece as a '
                    'three.js LineSegments wireframe from a '
                    'vertices+edges graph. Props: vertices (list of '
                    '[x_cm, y_cm, z_cm]), edges (list of [i, j]), '
                    'color, lineWidth.'),
            },
        )
        if not created:
            s.code = SCRIPT_CODE
            s.save(update_fields=['code'])
        self.stdout.write(self.style.SUCCESS(
            f'piece-wireframe-render script {"created" if created else "updated"}'))
