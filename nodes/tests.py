"""Tests for the self-registration endpoint.

Velour's existing API is admin-provisioned: every Node row is created by an
operator in the Django UI, and the firmware bakes in its matching slug+token
at compile time. This test file covers the /api/nodes/register endpoint,
which lets identical-firmware fleets (starting with bodymap) self-register
over HTTP using a shared provisioning secret.
"""

import json

from django.test import TestCase, override_settings
from django.urls import reverse

from experiments.models import Experiment

from .models import HardwareProfile, Node


PROVISIONING_SECRET = 'test-provisioning-secret-abc123'


@override_settings(VELOUR_PROVISIONING_SECRET=PROVISIONING_SECRET)
class ApiRegisterTests(TestCase):

    def setUp(self):
        self.profile = HardwareProfile.objects.create(
            name='Bodymap Node v1',
            mcu='esp32c3',
            flash_mb=4,
            ram_kb=400,
        )
        self.url = reverse('nodes_api:register')

    def _post(self, body):
        return self.client.post(
            self.url, data=json.dumps(body), content_type='application/json',
        )

    def _valid_body(self, **overrides):
        body = {
            'provisioning_secret': PROVISIONING_SECRET,
            'mac':                 'AA:BB:CC:DD:EE:01',
            'hardware_profile':    'Bodymap Node v1',
            'fleet':               'bodymap',
            'firmware_version':    'bodymap-0.1.0',
        }
        body.update(overrides)
        return body

    # --- happy path ------------------------------------------------

    def test_creates_new_node_with_mac_derived_slug(self):
        resp = self._post(self._valid_body())
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data['registered'])
        # last 6 hex of AA:BB:CC:DD:EE:01 is 'ddee01'
        self.assertEqual(data['slug'], 'bodymap-ddee01')
        self.assertEqual(data['mac'], 'AA:BB:CC:DD:EE:01')
        self.assertEqual(len(data['api_token']), 48)

        node = Node.objects.get(slug='bodymap-ddee01')
        self.assertTrue(node.self_registered)
        self.assertTrue(node.enabled)
        self.assertEqual(node.mac_address, 'AA:BB:CC:DD:EE:01')
        self.assertEqual(node.hardware_profile, self.profile)
        self.assertEqual(node.firmware_version, 'bodymap-0.1.0')

    def test_slug_fallback_when_no_fleet(self):
        resp = self._post(self._valid_body(fleet=''))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['slug'], 'node-ddee01')

    def test_attaches_to_matching_experiment(self):
        exp = Experiment.objects.create(name='bodymap')
        resp = self._post(self._valid_body())
        self.assertEqual(resp.status_code, 201)
        node = Node.objects.get(slug=resp.json()['slug'])
        self.assertEqual(node.experiment, exp)

    def test_no_experiment_when_fleet_has_no_matching_slug(self):
        resp = self._post(self._valid_body(fleet='nonexistent-fleet'))
        self.assertEqual(resp.status_code, 201)
        node = Node.objects.get(slug=resp.json()['slug'])
        self.assertIsNone(node.experiment)

    def test_hardware_profile_case_insensitive(self):
        resp = self._post(self._valid_body(hardware_profile='bodymap node v1'))
        self.assertEqual(resp.status_code, 201)
        node = Node.objects.get(slug=resp.json()['slug'])
        self.assertEqual(node.hardware_profile, self.profile)

    # --- idempotency ----------------------------------------------

    def test_repeat_registration_returns_same_credentials(self):
        first = self._post(self._valid_body())
        second = self._post(self._valid_body())
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()['registered'])
        self.assertEqual(first.json()['slug'], second.json()['slug'])
        self.assertEqual(first.json()['api_token'], second.json()['api_token'])
        self.assertEqual(Node.objects.count(), 1)

    def test_repeat_registration_updates_firmware_version(self):
        self._post(self._valid_body(firmware_version='bodymap-0.1.0'))
        self._post(self._valid_body(firmware_version='bodymap-0.2.0'))
        node = Node.objects.get()
        self.assertEqual(node.firmware_version, 'bodymap-0.2.0')

    def test_mac_normalized_to_uppercase(self):
        resp = self._post(self._valid_body(mac='aa:bb:cc:dd:ee:02'))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['mac'], 'AA:BB:CC:DD:EE:02')

    # --- slug collision -------------------------------------------

    def test_slug_collision_gets_suffix(self):
        """Two different MACs whose last-6-hex happen to match fleet suffix
        get different slugs — the second is suffixed with -2."""
        self._post(self._valid_body(mac='AA:BB:CC:DD:EE:01'))
        # Fabricate a MAC with the same last 6 hex chars (different vendor).
        resp = self._post(self._valid_body(mac='99:88:77:DD:EE:01'))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['slug'], 'bodymap-ddee01-2')

    # --- auth / validation failures -------------------------------

    def test_wrong_provisioning_secret_rejected(self):
        resp = self._post(self._valid_body(provisioning_secret='wrong'))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Node.objects.count(), 0)

    def test_missing_provisioning_secret_rejected(self):
        body = self._valid_body()
        body.pop('provisioning_secret')
        resp = self._post(body)
        self.assertEqual(resp.status_code, 403)

    def test_malformed_mac_rejected(self):
        for bad in ('not-a-mac', 'AA:BB:CC:DD:EE', 'AABBCCDDEEFF', ''):
            with self.subTest(mac=bad):
                resp = self._post(self._valid_body(mac=bad))
                self.assertEqual(resp.status_code, 400)

    def test_unknown_hardware_profile_rejected(self):
        resp = self._post(self._valid_body(hardware_profile='Made Up Board'))
        self.assertEqual(resp.status_code, 400)

    def test_missing_hardware_profile_rejected(self):
        resp = self._post(self._valid_body(hardware_profile=''))
        self.assertEqual(resp.status_code, 400)

    def test_invalid_json_body_rejected(self):
        resp = self.client.post(
            self.url, data='not json', content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_non_object_json_rejected(self):
        resp = self.client.post(
            self.url, data=json.dumps([]), content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_get_not_allowed(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)


class ApiRegisterDisabledTests(TestCase):
    """When VELOUR_PROVISIONING_SECRET is empty the endpoint is disabled —
    that's the default for existing deployments so that the new endpoint
    doesn't open a registration path without the operator noticing."""

    @override_settings(VELOUR_PROVISIONING_SECRET='')
    def test_returns_503_when_secret_unset(self):
        url = reverse('nodes_api:register')
        resp = self.client.post(
            url,
            data=json.dumps({'provisioning_secret': 'anything'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 503)


from dataclasses import dataclass

from .carrying_case import pack_fleet


@dataclass
class _Item:
    label: str
    w: int
    d: int
    h: int


class CarryingCasePackerTests(TestCase):
    """The cardboard-insert packer takes a list of (label, w, d, h)
    items and a case interior size in mm, and lays out 2D pockets
    using a tallest-first shelf-pack."""

    def test_single_item_fits(self):
        result = pack_fleet([_Item('a', 30, 50, 15)],
                            case_w_mm=100, case_d_mm=100, case_h_mm=20)
        self.assertEqual(len(result.pockets), 1)
        self.assertEqual(result.pockets[0].label, 'a')
        self.assertEqual(result.overflow, [])

    def test_overflow_when_too_many_items(self):
        items = [_Item(f'i{i}', 60, 60, 15) for i in range(20)]
        result = pack_fleet(items, case_w_mm=100, case_d_mm=100,
                             case_h_mm=20)
        self.assertEqual(len(result.pockets), 1)
        self.assertEqual(len(result.overflow), 19)
        self.assertFalse(result.fits)

    def test_height_overflow_skipped(self):
        # Items taller than case_h_mm are dropped to overflow even
        # if their footprint fits.
        items = [_Item('tall', 20, 20, 100)]
        result = pack_fleet(items, case_w_mm=100, case_d_mm=100,
                             case_h_mm=10)
        self.assertEqual(len(result.pockets), 0)
        self.assertEqual(result.overflow, ['tall'])

    def test_row_wrap(self):
        # 4 items 30 wide each, case 80 wide, margin 5:
        # cursor 5 → 40 → 75 (third needs 75+30+5=110 > 80, wraps).
        # Two per row → two rows.
        items = [_Item(f'i{i}', 30, 30, 10) for i in range(4)]
        result = pack_fleet(items, case_w_mm=80, case_d_mm=200,
                             case_h_mm=20, margin_mm=5)
        self.assertEqual(len(result.pockets), 4)
        ys = sorted({p.y_mm for p in result.pockets})
        self.assertEqual(len(ys), 2)
