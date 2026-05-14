"""Tests for the 7→1 hex flower dump."""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from gridprint import hex_flowers


_PALETTE = ['#dddddd', '#ec5b3a', '#3a7eec', '#3aec74']


class KeyPackingTest(TestCase):
    def test_round_trip(self):
        for k in (0, 1, 0x1234, 0x3fff):
            unpacked = hex_flowers.unpack_key(k)
            self_, *n = unpacked
            self.assertEqual(hex_flowers.pack_key(self_, n), k)

    def test_unpack_extracts_self_first(self):
        self_, *_ = hex_flowers.unpack_key((2 << 12) | 0xabc)
        self.assertEqual(self_, 2)


class RenderTest(TestCase):
    def _make_rule(self, fill: int = 0) -> bytes:
        """Trivial rule: every entry returns ``fill``.  Used for size /
        shape checks where contents don't matter."""
        return bytes([fill & 3]) * hex_flowers.RULE_TABLE_SIZE

    def test_render_returns_svg_body_and_summary(self):
        rule = self._make_rule(1)
        body, summary = hex_flowers.render_flowers_svg(
            rule, palette=_PALETTE,
            page_w_mm=210, page_h_mm=297,
            page_index=0, flowers_per_page=64)
        self.assertGreater(len(body), 1000)
        self.assertEqual(summary.page_index, 0)
        self.assertEqual(summary.flowers_per_page, 64)
        self.assertEqual(summary.total_flowers, hex_flowers.RULE_TABLE_SIZE)
        # Polygons: 7 inputs + 1 output × N flowers
        self.assertGreaterEqual(body.count('<polygon'), 8 * 64)
        # Marker definition appears.
        self.assertIn('<marker id="arrow"', body)

    def test_pagination_advances_keys(self):
        rule = self._make_rule(1)
        _, s0 = hex_flowers.render_flowers_svg(
            rule, palette=_PALETTE, page_w_mm=210, page_h_mm=297,
            page_index=0, flowers_per_page=128)
        _, s1 = hex_flowers.render_flowers_svg(
            rule, palette=_PALETTE, page_w_mm=210, page_h_mm=297,
            page_index=1, flowers_per_page=128)
        # Page 1 must start where page 0 ended (give or take 1).
        self.assertGreater(s1.first_key, s0.last_key)

    def test_center_filter_narrows_total(self):
        rule = self._make_rule(0)
        _, s = hex_flowers.render_flowers_svg(
            rule, palette=_PALETTE, page_w_mm=210, page_h_mm=297,
            page_index=0, flowers_per_page=64, center_filter=2)
        self.assertEqual(s.total_flowers, 4096)
        self.assertGreaterEqual(s.first_key, 2 << 12)
        self.assertLess(s.last_key, 3 << 12)

    def test_rejects_wrong_rule_size(self):
        with self.assertRaises(ValueError):
            hex_flowers.render_flowers_svg(
                b'\x00' * 100, palette=_PALETTE,
                page_w_mm=210, page_h_mm=297)

    def test_rejects_wrong_palette_size(self):
        with self.assertRaises(ValueError):
            hex_flowers.render_flowers_svg(
                self._make_rule(), palette=['#fff', '#000'],
                page_w_mm=210, page_h_mm=297)

    def test_rejects_bad_center_filter(self):
        with self.assertRaises(ValueError):
            hex_flowers.render_flowers_svg(
                self._make_rule(), palette=_PALETTE,
                page_w_mm=210, page_h_mm=297, center_filter=4)


class ViewTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='flower-test', password='x')
        self.client.force_login(self.user)

    def test_no_source_prompts(self):
        r = self.client.get(reverse('gridprint:grid_svg'), {'mode': 'flowers'})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('from_spoeqi', body)

    def test_bad_spoeqi_slug_reports_error(self):
        r = self.client.get(reverse('gridprint:grid_svg'),
                             {'mode': 'flowers', 'from_spoeqi': 'no-such'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('not found', r.content.decode())

    def test_rule_hex_path(self):
        rule_hex = ('00' * hex_flowers.RULE_TABLE_SIZE)   # all-zero rule
        r = self.client.get(reverse('gridprint:grid_svg'),
                             {'mode': 'flowers', 'rule_hex': rule_hex,
                              'fpage': '0', 'fper': '64'})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertGreater(body.count('<polygon'), 64 * 7)

    def test_rule_hex_wrong_length_reports_error(self):
        r = self.client.get(reverse('gridprint:grid_svg'),
                             {'mode': 'flowers', 'rule_hex': 'deadbeef'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('expected exactly', r.content.decode())

    def test_spoeqi_per_component_slice_changes_rule(self):
        """Component-sliced flowers must use bytes specific to that
        component, not the pact's broadcast rule_snapshot.  Build a
        pact with rule_diversity='fleet' so different components have
        different rules, then confirm components 0 and 3 produce
        different rule fingerprints in the rendered SVG."""
        from spoeqi.models import Pact, RULE_TABLE_SIZE, COMPONENTS
        # Fleet diversity needs a rules_snapshot blob.  Stuff each
        # component with a distinctive bit-pattern; mask to 4-state.
        per_comp = bytearray()
        for c in range(COMPONENTS):
            tile = bytes([(c + i) & 3 for i in range(RULE_TABLE_SIZE)])
            per_comp.extend(tile)
        pact = Pact(name='fleet-test', rule_diversity='fleet',
                     rules_snapshot=bytes(per_comp),
                     rule_snapshot=bytes([0] * RULE_TABLE_SIZE))
        pact.save()
        # Render flowers for component 0 and component 3.
        r0 = self.client.get(reverse('gridprint:grid_svg'), {
            'mode': 'flowers', 'from_spoeqi': pact.slug, 'component': '0'})
        r3 = self.client.get(reverse('gridprint:grid_svg'), {
            'mode': 'flowers', 'from_spoeqi': pact.slug, 'component': '3'})
        self.assertEqual(r0.status_code, 200)
        self.assertEqual(r3.status_code, 200)
        # Extract the "rule ..." footer fingerprint from each.
        import re
        m0 = re.search(r'rule ([0-9a-f]+)', r0.content.decode())
        m3 = re.search(r'rule ([0-9a-f]+)', r3.content.decode())
        self.assertIsNotNone(m0)
        self.assertIsNotNone(m3)
        self.assertNotEqual(m0.group(1), m3.group(1),
                              'components 0 and 3 produced the same rule '
                              'fingerprint despite fleet-mode pact')

    def test_bad_component_rejected(self):
        from spoeqi.models import Pact, RULE_TABLE_SIZE
        pact = Pact(name='comp-bound-test',
                     rule_snapshot=bytes([0] * RULE_TABLE_SIZE))
        pact.save()
        r = self.client.get(reverse('gridprint:grid_svg'), {
            'mode': 'flowers', 'from_spoeqi': pact.slug, 'component': '999'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('component must be', r.content.decode())
