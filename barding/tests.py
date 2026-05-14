"""barding tests — focus on atomicity + round-tripping settings."""

from __future__ import annotations

import json
import os
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import BundlePatchWish, SettingsScope
from . import views


class AtomicWriteTests(TestCase):

    def test_atomic_write_preserves_original_on_rename_failure(self):
        """If os.replace fails, the original file must be untouched."""
        original = {'spinnerTipsEnabled': False, 'note': 'keep me'}
        with tempfile.NamedTemporaryFile('w', suffix='.json',
                                         delete=False) as fh:
            fh.write(json.dumps(original))
            path = fh.name
        try:
            with mock.patch.object(os, 'replace',
                                   side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    views._atomic_write_json(path, {'spinnerTipsEnabled': True})
            with open(path) as fh:
                data = json.loads(fh.read())
            self.assertEqual(data, original)
        finally:
            os.unlink(path)
            if os.path.exists(path + '.tmp'):
                os.unlink(path + '.tmp')

    def test_atomic_write_roundtrip(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json',
                                         delete=False) as fh:
            path = fh.name
        try:
            views._atomic_write_json(path, {'spinnerTipsEnabled': True,
                                            'extra': [1, 2, 3]})
            with open(path) as fh:
                data = json.loads(fh.read())
            self.assertEqual(data['spinnerTipsEnabled'], True)
            self.assertEqual(data['extra'], [1, 2, 3])
        finally:
            os.unlink(path)


class SettingsRoundTripTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            'tester', password='pw')
        self.client = Client()
        self.client.force_login(self.user)
        self.tmp = tempfile.NamedTemporaryFile('w', suffix='.json',
                                               delete=False)
        # Seed with one unrelated key so we can verify preservation.
        self.tmp.write(json.dumps({'model': 'claude-opus-4-7'}))
        self.tmp.close()
        self.scope = SettingsScope.objects.create(
            name='user', path=self.tmp.name, is_active=True)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_toggle_spinner_tips_enabled_roundtrip(self):
        url = reverse('barding:edit_scope', args=[self.scope.id])
        # Initially off.
        r = self.client.post(url, {'mode': 'form',
                                   'spinnerTipsEnabled': 'on'})
        self.assertEqual(r.status_code, 302)
        with open(self.tmp.name) as fh:
            data = json.loads(fh.read())
        self.assertTrue(data['spinnerTipsEnabled'])
        # Pre-existing key preserved.
        self.assertEqual(data['model'], 'claude-opus-4-7')

        # Toggle off (omitting the checkbox key).
        r = self.client.post(url, {'mode': 'form'})
        self.assertEqual(r.status_code, 302)
        with open(self.tmp.name) as fh:
            data = json.loads(fh.read())
        self.assertFalse(data['spinnerTipsEnabled'])
        self.assertEqual(data['model'], 'claude-opus-4-7')


class BundlePatchWishTests(TestCase):

    def test_defaults_applied_false(self):
        w = BundlePatchWish.objects.create(
            kind='verb', target='Pondering', replacement='Brewing')
        self.assertFalse(w.applied)

    def test_length_ok_flag(self):
        ok = BundlePatchWish(target='Pondering', replacement='Brewing')
        too_long = BundlePatchWish(target='Pondering',
                                   replacement='Ruminating-very-long')
        self.assertTrue(ok.length_ok)
        self.assertFalse(too_long.length_ok)


class IndexViewTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            'tester', password='pw')
        self.client = Client()
        self.client.force_login(self.user)

    def test_index_200_and_contains_version_info(self):
        # Mock the installed-version probe so the test doesn't depend on
        # the host having Claude Code installed.
        fake = {
            'bin_path': '/fake/claude', 'exists': True,
            'resolved': '/fake/share/claude/versions/9.9.9',
            'version': '9.9.9', 'mtime': '2026-05-14T00:00:00',
            'size': 12345,
        }
        with mock.patch.object(views, '_installed_version', return_value=fake):
            r = self.client.get(reverse('barding:index'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '9.9.9')
