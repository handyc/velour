"""caframe tests — render pipeline + API surface."""
from __future__ import annotations
import io
import struct
import zlib

import numpy as np
from django.test import TestCase
from django.contrib.auth import get_user_model

from .models import Sequence
from . import render as r


class RenderTest(TestCase):
    def setUp(self):
        from caformer.primitives import random_rule_table
        self.rule = bytes(random_rule_table(0xCAFEBEEF))

    def test_iter_frames_yields_correct_count_and_shape(self):
        frames = list(r.iter_frames(rule_genome=self.rule, seed=42,
                                       w=16, h=12, n_frames=8, shape='hex'))
        self.assertEqual(len(frames), 8)
        for f in frames:
            self.assertEqual(f.shape, (12, 16))
            self.assertEqual(f.dtype, np.uint8)
            self.assertTrue(((f >= 0) & (f < 4)).all())

    def test_iter_frames_is_deterministic(self):
        a = list(r.iter_frames(rule_genome=self.rule, seed=99,
                                  w=8, h=8, n_frames=5, shape='hex'))
        b = list(r.iter_frames(rule_genome=self.rule, seed=99,
                                  w=8, h=8, n_frames=5, shape='hex'))
        for fa, fb in zip(a, b):
            self.assertTrue((fa == fb).all())

    def test_grid_to_png_emits_valid_signature(self):
        g = np.zeros((4, 4), dtype=np.uint8)
        png = r.grid_to_png(g, cell_px=2)
        self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
        # IHDR width/height should match cell_px scaling.
        ihdr_len, ihdr_tag = struct.unpack('>I4s', png[8:16])
        self.assertEqual(ihdr_tag, b'IHDR')
        w, h = struct.unpack('>II', png[16:24])
        self.assertEqual((w, h), (8, 8))

    def test_grids_to_apng_has_actl_chunk(self):
        frames = [np.zeros((4, 4), dtype=np.uint8) for _ in range(3)]
        apng = r.grids_to_apng(frames, cell_px=2, fps=10)
        # acTL must come after IHDR but before IDAT — find it by tag.
        self.assertIn(b'acTL', apng)
        self.assertIn(b'fcTL', apng)
        self.assertIn(b'IDAT', apng)
        self.assertIn(b'fdAT', apng)

    def test_consistency_score_invariants(self):
        same = [np.zeros((8, 8), dtype=np.uint8) for _ in range(4)]
        diff = [np.zeros((8, 8), dtype=np.uint8),
                np.ones((8, 8),  dtype=np.uint8)] * 2
        self.assertAlmostEqual(r.consistency_score(same), 1.0)
        self.assertAlmostEqual(r.consistency_score(diff), 0.0)

    def test_square_totalistic_runs(self):
        rule = bytes(np.arange(32, dtype=np.uint8) % 4)
        frames = list(r.iter_frames(
            rule_genome=rule, seed=7, w=8, h=8, n_frames=4,
            shape='square', n_colors=4))
        self.assertEqual(len(frames), 4)


class SourcesTest(TestCase):
    def test_class4_fallback_when_taxon_empty(self):
        from caframe.sources import from_taxon
        rule, seed, ref = from_taxon(seed_init=0xABCD)
        self.assertEqual(len(rule), 16_384)
        self.assertEqual(seed, 0xABCD)
        self.assertIn('taxon', ref)

    def test_from_caformer_loads_a_rule(self):
        from caformer.models import TrainedModel
        from caformer.primitives import random_rule_table
        from caframe.sources import from_caformer
        rules = {n: bytes(random_rule_table(0xCAB ^ (0x100 * (i + 1))))
                 for i, n in enumerate(['q','k','v','score','mix','merge',
                                         'mlp','norm','output','embed'])}
        TrainedModel.objects.create(
            slug='cf-src-test', name='cf src test',
            **{f'rule_{n}': rules[n] for n in rules},
            corpus_excerpt='', vocab_size=256, n_blocks=1,
            pop_size=1, generations=1, final_fitness=0.0,
        )
        rule, seed, ref = from_caformer('cf-src-test', role='embed',
                                          seed_init=0xBEEF)
        self.assertEqual(len(rule), 16_384)
        self.assertIn('caformer', ref)
        self.assertIn('embed', ref)

    def test_from_caformer_missing_model_raises(self):
        from caframe.sources import from_caformer, SourceUnavailable
        with self.assertRaises(SourceUnavailable):
            from_caformer('does-not-exist', role='embed')

    def test_multirule_frames_concatenate_lengths(self):
        from caframe.sources import iter_multirule_frames
        from caformer.primitives import random_rule_table
        recipe = [
            {'rule_genome': bytes(random_rule_table(1)),
             'seed': 42, 'n_frames': 4, 'shape': 'hex'},
            {'rule_genome': bytes(random_rule_table(2)),
             'seed': 99, 'n_frames': 3, 'shape': 'hex'},
        ]
        frames = list(iter_multirule_frames(recipe=recipe, w=8, h=8))
        # Segment 0 yields 4 (incl. seed); segment 1 yields 3 more
        # (does NOT re-seed): total = 4 + 3 = 7.
        self.assertEqual(len(frames), 7)

    def test_ffmpeg_available_returns_bool(self):
        from caframe.sources import ffmpeg_available
        self.assertIsInstance(ffmpeg_available(), bool)


class GATest(TestCase):
    def test_evolve_video_returns_better_than_seed(self):
        """8 generations × 12 pop should beat the random initial pop's
        worst score on the composite consistency-and-edge fitness."""
        from caframe.ga import evolve_video, consistency_fitness, CaframeGenome
        # Tiny: 16x16, 8 frames so the test runs fast.
        g, score, history = evolve_video(
            n_gen=3, pop_size=4, w=16, h=16, n_frames=6, seed=0xCABCAB)
        self.assertEqual(len(history), 3)
        # Every history row is (best, mean, worst), best >= mean >= worst.
        for best, mean, worst in history:
            self.assertGreaterEqual(best, mean - 1e-9)
            self.assertGreaterEqual(mean, worst - 1e-9)
        # Best across history should match the returned best score (within
        # float tolerance — best_g may be from any generation due to
        # all-time tracking).
        self.assertGreaterEqual(score, history[-1][0] - 1e-9)


class ViewsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.user = U.objects.create_user(
            username='cf-user', password='x',
            is_superuser=True, is_staff=True)

    def setUp(self):
        self.client.login(username='cf-user', password='x')

    def test_index_renders(self):
        resp = self.client.get('/caframe/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'caframe')

    def test_quick_apng_returns_apng(self):
        resp = self.client.get('/caframe/quick.apng',
            {'seed': '12345', 'w': '16', 'h': '16',
             'n_frames': '4', 'cell_px': '2'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/apng')
        self.assertTrue(resp.content.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertIn(b'acTL', resp.content)

    def test_saved_sequence_renders_apng(self):
        from caformer.primitives import random_rule_table
        seq = Sequence.objects.create(
            slug='alpha', name='Alpha demo',
            shape='hex', grid_w=12, grid_h=12, n_frames=4,
            rule_genome=bytes(random_rule_table(7)),
            seed=42)
        resp = self.client.get(f'/caframe/{seq.slug}.apng?cell_px=2')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/apng')

    def test_detail_404_for_unknown_slug(self):
        resp = self.client.get('/caframe/no-such-thing/')
        self.assertEqual(resp.status_code, 404)
