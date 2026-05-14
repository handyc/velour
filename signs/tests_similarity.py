"""Tests for the sign-similarity surface.

Synthetic poses + signatures only — no actual corpus data is
required, and these tests don't touch the keystream cache or the
imports directory.
"""

import math

from django.test import TestCase, Client
from django.urls import reverse

from signs.models import Language, Variety, Lemma, Sign, Frame
from signs import similarity


def _make_pose(value: float):
    """30 cylinders all set to [0, 0, value]. A degenerate but
    well-defined sign frame; useful for distance arithmetic."""
    return [[0.0, 0.0, value] for _ in range(30)]


class FlattenAndKeyframesTest(TestCase):
    def test_flatten_pads_short_triples(self):
        out = similarity._flatten_pose([[0.1], [0.2, 0.3], [0.4, 0.5, 0.6]])
        # 90 floats expected: first triple is rx=0.1, ry=0, rz=0; rest pad zeros.
        self.assertEqual(len(out), 90)
        self.assertAlmostEqual(out[0], 0.1)
        self.assertAlmostEqual(out[1], 0.0)
        self.assertAlmostEqual(out[3], 0.2)
        self.assertAlmostEqual(out[4], 0.3)
        self.assertAlmostEqual(out[6], 0.4)
        self.assertAlmostEqual(out[7], 0.5)
        self.assertAlmostEqual(out[8], 0.6)
        # Tail is zero.
        self.assertEqual(out[9], 0.0)
        self.assertEqual(out[-1], 0.0)

    def test_keyframes_evenly_spaced(self):
        idx = similarity._pick_keyframe_indices(100, k=8)
        # First is 0, last is n-1 = 99, and roughly evenly spaced.
        self.assertEqual(idx[0], 0)
        self.assertEqual(idx[-1], 99)
        self.assertEqual(len(idx), 8)

    def test_keyframes_for_single_frame(self):
        idx = similarity._pick_keyframe_indices(1, k=4)
        self.assertEqual(idx, [0, 0, 0, 0])

    def test_keyframes_for_empty(self):
        self.assertEqual(similarity._pick_keyframe_indices(0, k=4), [])


class SignatureTest(TestCase):
    def test_signature_is_unit_length(self):
        frames = [_make_pose(v) for v in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0)]
        sig = similarity.compute_signature(frames, k=8)
        self.assertEqual(len(sig), 720)
        # L2 norm ≈ 1
        n = math.sqrt(sum(v * v for v in sig))
        self.assertAlmostEqual(n, 1.0, places=6)

    def test_empty_signature_for_no_frames(self):
        self.assertEqual(similarity.compute_signature([]), [])

    def test_zero_pose_signature_is_all_zero(self):
        frames = [_make_pose(0.0) for _ in range(10)]
        sig = similarity.compute_signature(frames, k=8)
        # All-zero signature normalises to all-zero (not unit).
        self.assertEqual(sig, [0.0] * 720)


class DistanceTest(TestCase):
    def test_identical_signatures_distance_zero(self):
        a = similarity.compute_signature(
            [_make_pose(v) for v in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0)])
        self.assertAlmostEqual(similarity.distance(a, a), 0.0, places=9)

    def test_orthogonal_signatures_distance_sqrt2(self):
        # Two unit vectors pointing along disjoint axes.
        a = [1.0] + [0.0] * 719
        b = [0.0, 1.0] + [0.0] * 718
        self.assertAlmostEqual(similarity.distance(a, b),
                               math.sqrt(2.0), places=6)

    def test_empty_signature_yields_inf(self):
        self.assertEqual(similarity.distance([], [0.0] * 720), float('inf'))
        self.assertEqual(similarity.distance([0.0] * 720, []), float('inf'))
        self.assertEqual(similarity.distance([0.0] * 10, [0.0] * 720),
                         float('inf'))


class NearestTest(TestCase):
    def test_nearest_ranks_ascending(self):
        q = [1.0] + [0.0] * 719
        cands = [
            (10, [1.0] + [0.0] * 719),          # same → distance 0
            (20, [0.0, 1.0] + [0.0] * 718),     # orthogonal → sqrt(2)
            (30, [0.5, 0.5] + [0.0] * 718),     # not normalised; mid distance
        ]
        top = similarity.nearest(q, cands, n=3)
        self.assertEqual(top[0][0], 10)
        # Order: 10 < 30 < 20 (by computed distance)
        self.assertLess(top[0][1], top[1][1])
        self.assertLess(top[1][1], top[2][1])

    def test_truncates_to_n(self):
        q = [1.0] + [0.0] * 719
        cands = [(i, [float(i % 7) / 10] + [0.0] * 719) for i in range(20)]
        top = similarity.nearest(q, cands, n=5)
        self.assertEqual(len(top), 5)


class DetailPageNeighborsTest(TestCase):
    """End-to-end: the /signs/<slug>/ detail page should surface
    similarity rankings when signatures exist."""

    def setUp(self):
        lang = Language.objects.create(name='Test SL')
        v = Variety.objects.create(language=lang, name='v1')
        self.query  = self._make_sign(v, 'QUERY',  0.5)
        self.close  = self._make_sign(v, 'CLOSE',  0.4)
        self.far    = self._make_sign(v, 'FAR',    5.0)
        self.empty  = self._make_sign(v, 'NOSIG', None)

    def _make_sign(self, v, gloss, value):
        s = Sign.objects.create(lemma=Lemma.objects.create(gloss=gloss),
                                variety=v)
        if value is not None:
            for i in range(4):
                Frame.objects.create(sign=s, index=i,
                                     cylinder_rotations=_make_pose(value))
            s.signature = similarity.compute_signature(
                list(s.frames.order_by('index').values_list(
                    'cylinder_rotations', flat=True)))
            s.save(update_fields=['signature'])
        return s

    def test_detail_page_orders_neighbors_by_distance(self):
        r = Client().get(reverse('signs:detail', args=[self.query.slug]))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # Both neighbours appear; CLOSE before FAR.
        i_close = body.find('CLOSE')
        i_far   = body.find('FAR')
        self.assertNotEqual(i_close, -1)
        self.assertNotEqual(i_far,   -1)
        self.assertLess(i_close, i_far)

    def test_signless_sign_renders_with_no_neighbors(self):
        r = Client().get(reverse('signs:detail', args=[self.empty.slug]))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # The "no signature yet" hint shows up.
        self.assertIn('no signature yet', body)
