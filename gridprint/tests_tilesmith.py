"""Tests for the Tilesmith→Gridprint print bridge."""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from gridprint import svg
from tilesmith.models import TileSpec


class TilesmithGridRenderTest(TestCase):
    def test_rectangle_tiles_have_4_vertices_each(self):
        """A blank TileSpec (no CPs) is just a rectangle.  Trace one
        tile and check the polyline has exactly the 6 corner stops we
        walk through (top-left → mid-top → top-right → bottom-right →
        mid-bottom → bottom-left)."""
        edges = [[], [], [], [], [], []]
        pts = svg._tilesmith_trace(edges, 0.0, 0.0, 10.0, 10.0, 64, 64)
        self.assertEqual(len(pts), 6)
        # First point is the END of edge 0 (mid-top).
        self.assertAlmostEqual(pts[0][0], 5.0)
        self.assertAlmostEqual(pts[0][1], 0.0)

    def test_outward_cp_displaces_polygon(self):
        """A single CP on edge 0 with off=+16 (≈¼ of base_w) should push
        that point out past the tile rectangle.  Edge 0 is the top-left
        half; its outward direction is -y, so the point's y goes
        negative by `off * tile_h / base_h = 16 * 64 / 64 = 16 mm`."""
        edges = [[{'p': 0.5, 'off': 16}], [], [], [], [], []]
        pts = svg._tilesmith_trace(edges, 0.0, 0.0, 64.0, 64.0, 64, 64)
        # First emitted point is the CP itself: tx=0.25 (mid of 0..0.5),
        # ty=0; dy = -16 (outward = up = negative y in screen coords).
        self.assertEqual(pts[0], (16.0, -16.0))

    def test_tilesmith_grid_emits_many_tiles(self):
        page = svg.Page(w_mm=svg.A4_W, h_mm=svg.A4_H, margin_mm=10)
        style = svg.Style()
        body = svg.tilesmith_grid(
            page=page, cell_mm=30.0, style=style,
            edges=[[], [], [], [], [], []],
            base_w=64, base_h=64, lattice='offset-hex')
        # A4-portrait with 30 mm tiles ~ 7 cols × 10 rows + slop = ~70+ tiles.
        self.assertGreater(body.count('<polygon'), 40)
        self.assertIn('viewBox', body)

    def test_dispatcher_requires_tile_for_tilesmith(self):
        page = svg.Page()
        with self.assertRaises(ValueError):
            svg.render('tilesmith', page=page, cell_mm=10.0,
                        style=svg.Style())

    def test_dispatcher_accepts_tile_dict(self):
        page = svg.Page()
        body = svg.render('tilesmith', page=page, cell_mm=20.0,
                          style=svg.Style(),
                          tile={'edges': [[], [], [], [], [], []],
                                'base_w': 64, 'base_h': 64,
                                'lattice': 'offset-hex'})
        self.assertIn('<polygon', body)


class TilesmithViewTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='ts-test', password='x')
        self.client.force_login(self.user)
        self.spec = TileSpec.objects.create(
            slug='bump-tile', name='Bump tile',
            base_w=64, base_h=64,
            edges_json=[[{'p': 0.5, 'off': 12}], [], [], [], [], []],
        )

    def test_from_tilesmith_renders_polygons(self):
        r = self.client.get(reverse('gridprint:grid_svg'),
                              {'from_tilesmith': self.spec.slug,
                               'cell': '30'})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertGreater(body.count('<polygon'), 40)
        self.assertIn('tilesmith', body)
        self.assertIn(self.spec.name, body)

    def test_unknown_slug_returns_error_svg(self):
        r = self.client.get(reverse('gridprint:grid_svg'),
                              {'from_tilesmith': 'no-such-tile'})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('not found', body)

    def test_pattern_tilesmith_without_slug_prompts(self):
        r = self.client.get(reverse('gridprint:grid_svg'),
                              {'pattern': 'tilesmith'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('from_tilesmith', r.content.decode())

    def test_lattice_override(self):
        r = self.client.get(reverse('gridprint:grid_svg'),
                              {'from_tilesmith': self.spec.slug,
                               'lattice': 'square', 'cell': '40'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('square', r.content.decode())
