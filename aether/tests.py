from django.test import TestCase
from django.urls import reverse

from aether.models import World


class VisorJSONTests(TestCase):
    """Wire-protocol contract for the bodymap visor's manifest fetch.
    A C side that reads this protocol can rely on the field shape,
    so changes here should bump the version note in
    bodymap_visor/README.md."""

    def setUp(self):
        self.world = World.objects.create(
            slug='visor-test',
            title='Visor Test',
            published=True,
            spawn_x=1.0, spawn_y=1.6, spawn_z=2.0,
            sky_color='#87ceeb',
            ground_color='#3a7d44',
            ground_size=200.0,
        )

    def test_visor_manifest_returns_world_block(self):
        resp = self.client.get(
            reverse('aether:world_visor_json',
                    args=[self.world.slug]))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['world']['slug'], 'visor-test')
        self.assertEqual(data['world']['title'], 'Visor Test')
        self.assertEqual(data['spawn'], [1.0, 1.6, 2.0])
        self.assertIn('entities', data)
        self.assertIn('portals', data)

    def test_stereo_block_defaults(self):
        resp = self.client.get(
            reverse('aether:world_visor_json',
                    args=[self.world.slug]))
        s = resp.json()['stereo']
        self.assertFalse(s['enabled'])
        self.assertEqual(s['ipd_m'], 0.063)
        self.assertEqual(s['fov_deg'], 90.0)
        self.assertEqual(s['eye_width_px'], 1920)
        self.assertEqual(s['eye_height_px'], 1080)
        self.assertEqual(s['clip_near_m'], 0.05)
        self.assertEqual(s['clip_far_m'], 200.0)

    def test_stereo_query_overrides(self):
        resp = self.client.get(
            reverse('aether:world_visor_json', args=[self.world.slug])
            + '?stereo=1&ipd=0.058&fov=110&w=2160&h=1200')
        s = resp.json()['stereo']
        self.assertTrue(s['enabled'])
        self.assertAlmostEqual(s['ipd_m'], 0.058)
        self.assertAlmostEqual(s['fov_deg'], 110.0)
        self.assertEqual(s['eye_width_px'], 2160)
        self.assertEqual(s['eye_height_px'], 1200)

    def test_unpublished_world_404s_for_anon(self):
        self.world.published = False
        self.world.save()
        resp = self.client.get(
            reverse('aether:world_visor_json',
                    args=[self.world.slug]))
        self.assertEqual(resp.status_code, 404)
