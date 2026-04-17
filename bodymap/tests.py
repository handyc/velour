"""Tests for the bodymap app.

Covers the /bodymap/api/segment/ firmware endpoint (auth, idempotency,
operator_locked override, role validation) plus smoke tests for the
list and diagram views.
"""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from experiments.models import Experiment
from nodes.models import HardwareProfile, Node

from .models import Segment


class ApiReportSegmentTests(TestCase):

    def setUp(self):
        self.profile = HardwareProfile.objects.create(
            name='Bodymap Node v1', mcu='esp32s3',
        )
        self.experiment = Experiment.objects.create(
            name='Bodymap', slug='bodymap',
        )
        self.node = Node.objects.create(
            nickname='bodymap-aabbcc',
            mac_address='AA:BB:CC:DD:EE:01',
            hardware_profile=self.profile,
            experiment=self.experiment,
        )
        self.url = reverse('bodymap:api_segment')

    def _post(self, body, token=None):
        token = self.node.api_token if token is None else token
        return self.client.post(
            self.url,
            data=json.dumps(body),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )

    def _body(self, **overrides):
        body = {
            'slug':       self.node.slug,
            'role':       'forearm_l',
            'confidence': 0.87,
        }
        body.update(overrides)
        return body

    # --- happy path ---

    def test_creates_segment_on_first_report(self):
        resp = self._post(self._body())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertFalse(data['locked'])
        self.assertEqual(data['role'], 'forearm_l')

        seg = Segment.objects.get(node=self.node)
        self.assertEqual(seg.role, 'forearm_l')
        self.assertAlmostEqual(seg.confidence, 0.87)
        self.assertEqual(seg.experiment, self.experiment)
        self.assertFalse(seg.operator_locked)

    def test_updates_existing_segment_idempotently(self):
        self._post(self._body())
        self._post(self._body(role='torso', confidence=0.95))

        self.assertEqual(Segment.objects.filter(node=self.node).count(), 1)
        seg = Segment.objects.get(node=self.node)
        self.assertEqual(seg.role, 'torso')
        self.assertAlmostEqual(seg.confidence, 0.95)

    # --- operator lock ---

    def test_operator_lock_ignores_firmware_update(self):
        Segment.objects.create(
            node=self.node, experiment=self.experiment,
            role='torso', confidence=0.9, operator_locked=True,
        )
        resp = self._post(self._body(role='forearm_l', confidence=0.8))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['locked'])
        self.assertEqual(data['role'], 'torso')  # unchanged

        seg = Segment.objects.get(node=self.node)
        self.assertEqual(seg.role, 'torso')

    # --- auth / validation ---

    def test_rejects_missing_auth(self):
        resp = self.client.post(
            self.url,
            data=json.dumps(self._body()),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)

    def test_rejects_wrong_token(self):
        resp = self._post(self._body(), token='definitely-not-the-right-token')
        self.assertEqual(resp.status_code, 401)

    def test_rejects_unknown_slug(self):
        resp = self._post(self._body(slug='not-a-real-node'))
        self.assertEqual(resp.status_code, 404)

    def test_rejects_disabled_node(self):
        self.node.enabled = False
        self.node.save(update_fields=['enabled'])
        resp = self._post(self._body())
        self.assertEqual(resp.status_code, 403)

    def test_rejects_invalid_role(self):
        resp = self._post(self._body(role='spleen'))
        self.assertEqual(resp.status_code, 400)

    def test_rejects_non_numeric_confidence(self):
        resp = self._post(self._body(confidence='very high'))
        self.assertEqual(resp.status_code, 400)

    def test_clamps_out_of_range_confidence(self):
        self._post(self._body(confidence=2.5))
        seg = Segment.objects.get(node=self.node)
        self.assertEqual(seg.confidence, 1.0)

        self._post(self._body(confidence=-0.3))
        seg.refresh_from_db()
        self.assertEqual(seg.confidence, 0.0)

    def test_rejects_bad_json(self):
        resp = self.client.post(
            self.url,
            data='not json at all',
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.node.api_token}',
        )
        self.assertEqual(resp.status_code, 400)

    def test_rejects_missing_slug(self):
        resp = self._post({'role': 'torso'})
        self.assertEqual(resp.status_code, 400)


class BodymapViewTests(TestCase):

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='op', password='pw')
        self.client.force_login(self.user)

        self.profile = HardwareProfile.objects.create(
            name='Bodymap Node v1', mcu='esp32s3',
        )
        self.experiment = Experiment.objects.create(
            name='Bodymap', slug='bodymap',
        )
        self.node = Node.objects.create(
            nickname='torso-node',
            hardware_profile=self.profile,
            experiment=self.experiment,
        )
        Segment.objects.create(
            node=self.node, experiment=self.experiment,
            role='torso', confidence=0.92,
        )

    def test_list_renders(self):
        resp = self.client.get(reverse('bodymap:list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'torso-node')
        self.assertContains(resp, 'Torso')

    def test_diagram_renders(self):
        resp = self.client.get(
            reverse('bodymap:diagram',
                    kwargs={'experiment_slug': 'bodymap'})
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'torso-node')

    def test_diagram_404_for_unknown_experiment(self):
        resp = self.client.get(
            reverse('bodymap:diagram',
                    kwargs={'experiment_slug': 'no-such-thing'})
        )
        self.assertEqual(resp.status_code, 404)

    def test_list_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse('bodymap:list'))
        # login_required redirects to /accounts/login/?next=...
        self.assertEqual(resp.status_code, 302)
