"""Tests for the escher → gridprint print bridge."""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model


class EscherBridgeViewTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='gp-escher',
                                              password='x')
        self.client.force_login(self.user)

    def test_from_escher_p4m_renders(self):
        r = self.client.get(reverse('gridprint:grid_svg'),
                              {'from_escher': 'p4m', 'tile': '24'})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # The escher renderer emits one <use href="#motif" .../> per
        # (lattice cell × orbit element).  For p4m on A4 at tile=24
        # we expect a substantial count.
        self.assertGreater(body.count('<use href="#motif"'), 100)
        self.assertIn('escher · p4m', body)

    def test_from_escher_with_spoeqi_motif(self):
        from spoeqi.models import Pact, RULE_TABLE_SIZE
        pact = Pact(name='escher-bridge-test',
                     rule_snapshot=bytes([0] * RULE_TABLE_SIZE))
        pact.save()
        r = self.client.get(reverse('gridprint:grid_svg'), {
            'from_escher': 'p3', 'motif': 'spoeqi_component',
            'pact': pact.slug, 'component': '0', 'gen': '0',
            'tile': '30',
        })
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # CA-frame motif emits many hex polygons inside the <symbol>.
        self.assertIn('<symbol id="motif"', body)
        self.assertGreater(body.count('<polygon'), 50)

    def test_unknown_group_returns_error_svg(self):
        r = self.client.get(reverse('gridprint:grid_svg'),
                              {'from_escher': 'no-such-group'})
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'unknown', r.content)

    def test_pattern_escher_without_slug_prompts(self):
        r = self.client.get(reverse('gridprint:grid_svg'),
                              {'pattern': 'escher'})
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'from_escher', r.content)

    def test_landscape_swaps_page_dims(self):
        r = self.client.get(reverse('gridprint:grid_svg'),
                              {'from_escher': 'p6m', 'landscape': '1',
                               'tile': '40'})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # Landscape A4 viewBox is 297 × 210.
        self.assertIn('viewBox="0 0 297.0 210.0"', body)

    def test_download_sets_content_disposition(self):
        r = self.client.get(reverse('gridprint:grid_svg'),
                              {'from_escher': 'p4', 'download': '1'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('attachment', r.headers.get('Content-Disposition', ''))
        self.assertIn('escher-p4', r.headers.get('Content-Disposition', ''))

    def test_motif_placeholder_is_well_formed_xml(self):
        """When a required motif arg is missing, the placeholder text
        inside the <symbol id="motif"> must not contain raw ``<`` /
        ``>`` characters — those leaked into the SVG and Firefox
        refused to render the page (regression report 2026-05-14)."""
        import xml.etree.ElementTree as ET
        r = self.client.get(reverse('gridprint:grid_svg'), {
            'from_escher': 'p2', 'motif': 'spoeqi_component',
            # No `pact=` → escher._resolve_motif emits a placeholder.
        })
        self.assertEqual(r.status_code, 200)
        # Parsing must succeed; raw `<slug>` inside <text> used to fail.
        try:
            ET.fromstring(r.content)
        except ET.ParseError as exc:
            self.fail(f'placeholder SVG is not well-formed XML: {exc}')

    def test_print_endpoint_wraps_html(self):
        """gridprint's /print/ endpoint should serve an HTML wrapper
        that includes the escher SVG body and auto-fires
        window.print()."""
        r = self.client.get(reverse('gridprint:print'),
                              {'from_escher': 'pmm', 'tile': '24'})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('<!doctype html>', body)
        self.assertIn('window.print()', body)
        self.assertIn('<use href="#motif"', body)
