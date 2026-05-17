"""Tests for hanbprint — 61-hex hanb packing."""
from __future__ import annotations

import math
import re

from django.test import TestCase
from django.contrib.auth import get_user_model

from gridprint import hanb, svg as gp_svg


class HanbGeometryTest(TestCase):
    def test_cells_count_is_61(self):
        cells = list(hanb.hanb_cells())
        self.assertEqual(len(cells), hanb.N_CELLS)
        self.assertEqual(len(cells), 61)

    def test_cells_have_six_fold_symmetry(self):
        """Every cell (q, r) has its 60° rotation (-r, q+r) also present."""
        cells = set(hanb.hanb_cells())
        for (q, r) in cells:
            self.assertIn((-r, q + r), cells,
                f'rotation of ({q},{r}) missing')

    def test_no_cell_exceeds_axial_radius_4(self):
        for (q, r) in hanb.hanb_cells():
            s = -q - r
            self.assertLessEqual(max(abs(q), abs(r), abs(s)), 4)

    def test_hanb_flat_to_flat_is_14x_cell(self):
        # flat-top hanb's flat-to-flat (vertical dim) = sqrt(3) * R_hanb
        # = sqrt(3) * (14*sqrt(3)/3) * R_cell = 14 * R_cell.
        w, h = hanb.hanb_size_mm(R_cell_mm=4.0)
        self.assertAlmostEqual(h, 14.0 * 4.0, places=6)
        # width = 2 * R_hanb = (28*sqrt(3)/3) * R_cell
        expected_w = 2 * (14 * math.sqrt(3) / 3) * 4.0
        self.assertAlmostEqual(w, expected_w, places=6)


class HanbLayoutTest(TestCase):
    def test_centres_fit_in_printable_area(self):
        page = gp_svg.Page(w_mm=210.0, h_mm=297.0, margin_mm=10.0)
        centres = hanb.hanb_centres(page, R_cell=4.0, gap_mm=3.0)
        self.assertGreater(len(centres), 0)
        R_hanb = 4.0 * hanb.R_HANB_OVER_R_CELL
        half_w = R_hanb
        half_h = R_hanb * math.sqrt(3) / 2
        for (cx, cy) in centres:
            self.assertGreaterEqual(cx - half_w, page.left - 1e-3)
            self.assertLessEqual(cx + half_w, page.right + 1e-3)
            self.assertGreaterEqual(cy - half_h, page.top - 1e-3)
            self.assertLessEqual(cy + half_h, page.bottom + 1e-3)

    def test_neighbours_separated_by_gap(self):
        """The minimum centre-to-centre distance equals R_hanb*sqrt(3) + gap
        (within float tolerance) — i.e. every adjacent pair has exactly the
        requested gap between flat edges."""
        page = gp_svg.Page(w_mm=210.0, h_mm=297.0, margin_mm=10.0)
        R_cell = 4.0
        gap = 3.0
        centres = hanb.hanb_centres(page, R_cell=R_cell, gap_mm=gap)
        R_hanb = R_cell * hanb.R_HANB_OVER_R_CELL
        expected = R_hanb * math.sqrt(3) + gap
        # Compute the minimum distance between any two centres.
        min_d = min(
            math.hypot(a[0] - b[0], a[1] - b[1])
            for i, a in enumerate(centres) for b in centres[i + 1:]
        )
        self.assertAlmostEqual(min_d, expected, places=3)

    def test_smaller_cells_pack_more_hanbs(self):
        page = gp_svg.Page(w_mm=210.0, h_mm=297.0, margin_mm=10.0)
        n_big = len(hanb.hanb_centres(page, R_cell=8.0, gap_mm=3.0))
        n_small = len(hanb.hanb_centres(page, R_cell=3.0, gap_mm=3.0))
        self.assertGreater(n_small, n_big)


class HanbSvgTest(TestCase):
    def test_draw_hanb_emits_62_polygons(self):
        """61 inner cells + 1 outer outline = 62 polygons per hanb."""
        cell_style = gp_svg.Style(color='#888', width_mm=0.2, alpha=1.0)
        svg_str = hanb.draw_hanb(100.0, 150.0, R_cell=4.0,
                                    cell_style=cell_style)
        self.assertEqual(svg_str.count('<polygon'), 62)

    def test_render_hanbs_svg_returns_body_and_count(self):
        page = gp_svg.Page(w_mm=210.0, h_mm=297.0, margin_mm=10.0)
        cell_style = gp_svg.Style(color='#888', width_mm=0.2, alpha=1.0)
        body, n = hanb.render_hanbs_svg(
            page=page, R_cell=4.0, gap_mm=3.0, cell_style=cell_style)
        self.assertGreater(n, 0)
        # 62 polygons per hanb
        self.assertEqual(body.count('<polygon'), 62 * n)


class HanbprintViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.user = U.objects.create_user(
            username='hanb-test', password='x',
            is_staff=True, is_superuser=True)

    def setUp(self):
        self.client.login(username='hanb-test', password='x')

    def test_endpoint_returns_svg(self):
        r = self.client.get('/gridprint/grid.svg?mode=hanbprint')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'],
                          'image/svg+xml; charset=utf-8')
        self.assertIn(b'<polygon', r.content)
        self.assertIn(b'hanbprint', r.content)

    def test_custom_cell_size_changes_layout(self):
        big = self.client.get(
            '/gridprint/grid.svg?mode=hanbprint&cell=8&gap=3').content
        small = self.client.get(
            '/gridprint/grid.svg?mode=hanbprint&cell=3&gap=3').content
        # Footer reports hanb count — smaller cells = more hanbs.
        def count_from_footer(blob: bytes) -> int:
            m = re.search(rb'hanbprint \xc2\xb7 (\d+) hanbs', blob)
            self.assertIsNotNone(m, f'no footer match in {blob[-300:]!r}')
            return int(m.group(1))
        self.assertGreater(count_from_footer(small),
                           count_from_footer(big))

    def test_landscape_orientation(self):
        r = self.client.get(
            '/gridprint/grid.svg?mode=hanbprint&landscape=1')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'viewBox="0 0 297.0 210.0"', r.content)

    def test_download_sets_content_disposition(self):
        r = self.client.get(
            '/gridprint/grid.svg?mode=hanbprint&download=1')
        self.assertEqual(r.status_code, 200)
        self.assertIn('attachment', r.get('Content-Disposition', ''))
        self.assertIn('hanbprint', r.get('Content-Disposition', ''))

    def test_zero_gap_is_allowed(self):
        r = self.client.get(
            '/gridprint/grid.svg?mode=hanbprint&gap=0')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'hanbprint', r.content)
