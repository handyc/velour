from django.test import TestCase

from aether.models import Entity, EntityScript, Script
from .models import Building, Floor, Room, FurniturePiece, Placement
from .aether_export import export_room


class WireframeGeometryTests(TestCase):
    """Phase 2 of the editable-3D-objects backlog: a FurniturePiece
    can carry a `geometry` payload of type 'wireframe' (vertices +
    edges) and the Aether export attaches the
    piece-wireframe-render script with the right props instead of
    falling back to a plain box."""

    def setUp(self):
        # Seed the wireframe script the export looks up by slug.
        Script.objects.get_or_create(
            slug='piece-wireframe-render',
            defaults={'name': 'Wireframe', 'event': 'start',
                      'code': '// stub', 'is_builtin': True},
        )
        # Also the mesh script (export looks both up).
        Script.objects.get_or_create(
            slug='piece-mesh-render',
            defaults={'name': 'Mesh', 'event': 'start',
                      'code': '// stub', 'is_builtin': True},
        )

        b = Building.objects.create(slug='b', name='B')
        f = Floor.objects.create(building=b, level=0,
                                 name='Ground', height_cm=300)
        self.room = Room.objects.create(
            slug='r', name='R', floor=f,
            width_cm=400, length_cm=400)

    def test_wireframe_piece_attaches_wireframe_script(self):
        piece = FurniturePiece.objects.create(
            slug='chair-frame', name='Chair frame',
            kind='chair',
            width_cm=50, depth_cm=50, height_cm=90,
            geometry={
                'type': 'wireframe',
                'vertices': [[0, 0, 0], [50, 0, 0], [50, 0, 50],
                             [0, 0, 50], [0, 90, 0], [50, 90, 0]],
                'edges': [[0, 1], [1, 2], [2, 3], [3, 0],
                          [0, 4], [1, 5]],
            })
        Placement.objects.create(
            room=self.room, piece=piece,
            x_cm=100, y_cm=100, rotation_deg=0)
        world = export_room(self.room)
        # Should have created an Entity for the piece + an
        # EntityScript pointing at piece-wireframe-render.
        piece_ent = Entity.objects.filter(
            world=world, name__contains='piece-').first()
        self.assertIsNotNone(piece_ent)
        es = EntityScript.objects.filter(entity=piece_ent).first()
        self.assertIsNotNone(es)
        self.assertEqual(es.script.slug, 'piece-wireframe-render')
        self.assertIn('vertices', es.props)
        self.assertIn('edges', es.props)
        self.assertEqual(len(es.props['vertices']), 6)
        self.assertEqual(len(es.props['edges']), 6)

    def test_extrusion_piece_still_uses_mesh_script(self):
        piece = FurniturePiece.objects.create(
            slug='ldesk', name='L-desk',
            kind='desk',
            width_cm=120, depth_cm=120, height_cm=75,
            geometry={
                'type': 'extrusion',
                'polygon': [[0, 0], [120, 0], [120, 60],
                            [60, 60], [60, 120], [0, 120]],
                'height_cm': 75,
            })
        Placement.objects.create(
            room=self.room, piece=piece,
            x_cm=200, y_cm=50, rotation_deg=0)
        world = export_room(self.room)
        piece_ent = Entity.objects.filter(
            world=world, name__contains='piece-').first()
        es = EntityScript.objects.filter(entity=piece_ent).first()
        self.assertIsNotNone(es)
        self.assertEqual(es.script.slug, 'piece-mesh-render')

    def test_no_geometry_falls_back_to_plain_box(self):
        piece = FurniturePiece.objects.create(
            slug='plain', name='Plain',
            kind='other',
            width_cm=50, depth_cm=50, height_cm=80,
            geometry={})
        Placement.objects.create(
            room=self.room, piece=piece,
            x_cm=100, y_cm=100, rotation_deg=0)
        world = export_room(self.room)
        piece_ent = Entity.objects.filter(
            world=world, name__contains='piece-').first()
        self.assertIsNotNone(piece_ent)
        # No EntityScript for plain-box pieces.
        self.assertEqual(
            EntityScript.objects.filter(entity=piece_ent).count(), 0)
