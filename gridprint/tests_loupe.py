"""Tests for the loupe → gridprint bridge + the loupe server-side
Mandelbrot renderer."""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from loupe.models import Walk
from loupe import render as renderer


class MandelbrotRendererTest(TestCase):
    def test_auto_iter_ramps_at_deep_zoom(self):
        self.assertEqual(renderer.auto_iter(3.0), 192)
        self.assertEqual(renderer.auto_iter(1.0), 192)
        self.assertEqual(renderer.auto_iter(0.5), 256)
        self.assertGreater(renderer.auto_iter(1e-6), 1000)

    def test_render_returns_valid_png_bytes(self):
        png = renderer.render_mandelbrot_png(-0.5, 0.0, 3.0, 64, 64,
                                                iter_cap=32)
        self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'),
                          'output must be a valid PNG signature')
        self.assertGreater(len(png), 100)

    def test_escape_classifies_center_as_in_set(self):
        """The point (0, 0) is deep in the Mandelbrot set; escape
        time at iter_cap should be exactly iter_cap (in-set)."""
        import numpy as np
        e = renderer.mandelbrot_escape(0.0, 0.0, 0.01, 4, 4, 32)
        self.assertTrue((e == 32).all(),
                          f'expected all in-set, got: {e!r}')

    def test_escape_diverges_at_far_point(self):
        """The point (5, 0) is well outside the bailout radius;
        escape time should be 0 (very first iteration diverges)."""
        e = renderer.mandelbrot_escape(5.0, 0.0, 0.01, 4, 4, 32)
        self.assertTrue((e == 0).all(),
                          f'expected immediate escape, got {e!r}')


class WalkPngEndpointTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='lp-png', password='x')
        self.client.force_login(self.user)
        self.walk = Walk.objects.create(
            slug='png-walk', name='png walk',
            gene_json=[{'cx': -0.5, 'cy': 0.0, 'span': 3.0,
                         'fitness': 1.0, 'iter': 32},
                        {'cx': -0.75, 'cy': 0.11, 'span': 0.16,
                         'fitness': 2.5, 'iter': 32}],
            method='agent', n_steps=1,
            fitness_final=2.5,
        )

    def test_walk_png_returns_png(self):
        r = self.client.get(reverse('loupe:walk_png',
                                      kwargs={'slug': 'png-walk'}),
                              {'w': 128, 'h': 128, 'iter': 32})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'image/png')
        # FileResponse-ish raw bytes test:
        b = b''.join(r.streaming_content) if hasattr(r, 'streaming_content') \
            else r.content
        self.assertTrue(b.startswith(b'\x89PNG\r\n\x1a\n'))

    def test_walk_png_404_when_missing(self):
        r = self.client.get(reverse('loupe:walk_png',
                                      kwargs={'slug': 'no-such'}))
        self.assertEqual(r.status_code, 404)

    def test_standalone_mandel_endpoint(self):
        r = self.client.get(reverse('loupe:mandel_png'),
                              {'cx': -0.5, 'cy': 0, 'span': 3.0,
                               'w': 64, 'h': 64, 'iter': 32})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'image/png')


class GridprintLoupeBridgeTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='gp-loupe', password='x')
        self.client.force_login(self.user)
        self.walk = Walk.objects.create(
            slug='bridge-walk', name='Bridge walk',
            gene_json=[{'cx': -0.5, 'cy': 0.0, 'span': 3.0,
                         'fitness': 1.0, 'iter': 32}],
            method='manual', n_steps=0,
            fitness_final=1.0,
        )

    def test_from_loupe_returns_svg_with_embedded_png(self):
        r = self.client.get(reverse('gridprint:grid_svg'),
                              {'from_loupe': 'bridge-walk', 'res': '128'})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('<svg', body)
        self.assertIn('<image href="data:image/png;base64,', body)
        # Footer footer carries the slug + step info.
        self.assertIn('loupe · bridge-walk', body)

    def test_unknown_slug_returns_error_svg(self):
        r = self.client.get(reverse('gridprint:grid_svg'),
                              {'from_loupe': 'no-such-walk'})
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'not found', r.content)

    def test_pattern_loupe_without_slug_prompts(self):
        r = self.client.get(reverse('gridprint:grid_svg'),
                              {'pattern': 'loupe'})
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'from_loupe', r.content)

    def test_download_disposition(self):
        r = self.client.get(reverse('gridprint:grid_svg'),
                              {'from_loupe': 'bridge-walk', 'res': '128',
                               'download': '1'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('attachment', r.headers.get('Content-Disposition', ''))
        self.assertIn('loupe-bridge-walk', r.headers.get('Content-Disposition', ''))
