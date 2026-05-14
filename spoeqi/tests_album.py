"""Tests for the holiday-album image-seeded pacts."""

import io

import numpy as np
from PIL import Image

from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from spoeqi import album, keystream
from spoeqi.models import Pact, RULE_TABLE_SIZE


def _synth(rgb, size=(96, 96)):
    arr = np.full((*size[::-1], 3), rgb, dtype=np.uint8)
    # Gentle gradient so the image isn't a perfectly flat fill.
    for y in range(size[1]):
        arr[y, :, 1] = (arr[y, :, 1].astype(int) + y * 2) % 256
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format='PNG')
    return buf.getvalue()


PALETTE_HUES = [(220, 80, 40), (60, 120, 210), (80, 180, 90), (230, 200, 60)]


class LayoutTest(TestCase):
    def test_valid_sizes(self):
        for n in album.VALID_N:
            cpi, kr, kc = album.album_layout(n)
            self.assertEqual(cpi * n, 64)
            self.assertEqual(kr * kc, cpi)

    def test_invalid_size_raises(self):
        with self.assertRaises(ValueError):
            album.album_layout(3)


class QuantizeAlbumTest(TestCase):
    def test_quantize_returns_64_tiles(self):
        images = [_synth(c) for c in PALETTE_HUES]
        r = album.quantize_album(images, side=16)
        self.assertEqual(r.n_images, 4)
        self.assertEqual(r.components_per_image, 16)
        self.assertEqual(len(r.target_grids), 64)
        for t in r.target_grids:
            self.assertEqual(t.shape, (16, 16))
            self.assertGreaterEqual(t.min(), 0)
            self.assertLessEqual(t.max(), 3)

    def test_deterministic(self):
        images = [_synth(c) for c in PALETTE_HUES]
        a = album.quantize_album(images, side=16)
        b = album.quantize_album(images, side=16)
        self.assertEqual(a.album_hash, b.album_hash)
        for ga, gb in zip(a.target_grids, b.target_grids):
            self.assertTrue(np.array_equal(ga, gb))

    def test_hash_changes_with_image_order(self):
        images = [_synth(c) for c in PALETTE_HUES]
        a = album.quantize_album(images, side=16)
        b = album.quantize_album(list(reversed(images)), side=16)
        self.assertNotEqual(a.album_hash, b.album_hash)

    def test_invalid_count_raises(self):
        with self.assertRaises(ValueError):
            album.quantize_album([_synth((255, 0, 0))], side=16)   # N=1 not valid


class DeriveSeedAndRuleTest(TestCase):
    def test_lengths(self):
        seed, rule = album.derive_seed_and_rule('a' * 64)
        self.assertEqual(len(seed), 64)
        self.assertEqual(len(rule), RULE_TABLE_SIZE)

    def test_rule_bytes_are_4state(self):
        """Critical: rule entries must be 0..3 only — anything higher
        produces out-of-palette cell values after the first tick."""
        _, rule = album.derive_seed_and_rule('beef' * 16)
        self.assertEqual(max(rule), 3)
        self.assertEqual(min(rule), 0)

    def test_deterministic(self):
        s1, r1 = album.derive_seed_and_rule('cafe' * 16)
        s2, r2 = album.derive_seed_and_rule('cafe' * 16)
        self.assertEqual(s1, s2)
        self.assertEqual(r1, r2)


class InitialMultiGridTest(TestCase):
    def setUp(self):
        keystream.cache_clear()

    def test_uses_initial_grids_when_set(self):
        """When pact.initial_grids is populated, the keystream should
        ignore the seed_matrix→xoshiro expansion and use the explicit
        grids verbatim."""
        from spoeqi.models import COMPONENTS, COMPONENT_GRID
        side = COMPONENT_GRID
        explicit = [[(i + j) % 4 for j in range(side * side)]
                    for i in range(COMPONENTS)]
        pact = Pact(name='ig-test', initial_grids=explicit)
        pact.save()
        state = keystream.initial_multi_grid(pact)
        expected = bytes(v for grid in explicit for v in grid)
        self.assertEqual(state, expected)

    def test_falls_back_to_seed_when_initial_grids_none(self):
        pact = Pact(name='fallback-test')
        pact.save()
        state = keystream.initial_multi_grid(pact)
        # Just shape check — exact bytes depend on the random seed_matrix
        # which is freshly generated.
        from spoeqi.models import COMPONENTS, COMPONENT_GRID
        self.assertEqual(len(state), COMPONENTS * COMPONENT_GRID * COMPONENT_GRID)


class AlbumViewTest(TestCase):
    def test_get_renders_form(self):
        r = self.client.get(reverse('spoeqi:album_new'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('forge album pact', r.content.decode())

    def test_post_creates_pact(self):
        files = [SimpleUploadedFile(f'i{i}.png', _synth(c),
                                     content_type='image/png')
                 for i, c in enumerate(PALETTE_HUES)]
        r = self.client.post(reverse('spoeqi:album_new'), {
            'name': 'test-album', 'party_a': 'A', 'party_b': 'B',
            'n_images': '4', 'tick_ms': '180', 'clock_model': 'synced',
            'images': files,
        })
        self.assertEqual(r.status_code, 302)   # redirect to detail
        pact = Pact.objects.get(name='test-album')
        self.assertIsNotNone(pact.initial_grids)
        self.assertEqual(len(pact.initial_grids), 64)
        self.assertEqual(pact.album_n_images, 4)
        self.assertEqual(len(pact.album_hash), 64)   # SHA-256 hex
        # Rule bytes must be in CA range.
        self.assertLessEqual(max(pact.rule_snapshot), 3)

    def test_post_wrong_file_count_errors(self):
        files = [SimpleUploadedFile(f'i{i}.png', _synth(c),
                                     content_type='image/png')
                 for i, c in enumerate(PALETTE_HUES[:2])]   # only 2 files
        r = self.client.post(reverse('spoeqi:album_new'), {
            'name': 'wrong-count', 'party_a': 'A', 'party_b': 'B',
            'n_images': '4', 'tick_ms': '180', 'clock_model': 'synced',
            'images': files,
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn('expected exactly 4 images', r.content.decode())
