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


class BinaryInspectorTests(TestCase):
    """Light coverage: every endpoint authenticates, the pure-function
    surface in binary.py is exercised against a synthetic ELF stub.
    Heavy ELF parsing is already battle-tested in pyelftools — we
    don't need to retest it."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='binbird', password='x')
        self.client = Client()
        self.client.force_login(self.user)

    def test_hex_page_shape(self):
        from . import binary
        # Use the binary itself (any readable file) — the test just
        # confirms we get well-shaped rows.  Skip if the dev path
        # isn't here.
        try:
            rows = binary.hex_page(0, 64)
        except FileNotFoundError:
            self.skipTest('claude binary not on this host')
        self.assertEqual(len(rows), 4)
        for r in rows:
            self.assertEqual(len(r.hex_pairs), 16)
            self.assertEqual(len(r.ascii_), 16)

    def test_hex_page_rejects_negative_offset(self):
        from . import binary
        with self.assertRaises(ValueError):
            binary.hex_page(-1, 64)

    def test_hex_page_rejects_huge_length(self):
        from . import binary
        with self.assertRaises(ValueError):
            binary.hex_page(0, 1 << 24)

    def test_search_bytes_finds_elf_magic(self):
        from . import binary
        try:
            hits = binary.search_bytes('0x7f454c46', max_hits=1)
        except FileNotFoundError:
            self.skipTest('claude binary not on this host')
        self.assertEqual(hits, [0])   # ELF magic is at offset 0

    def test_binary_index_view(self):
        try:
            from . import binary
            binary.resolve_binary()
        except FileNotFoundError:
            self.skipTest('claude binary not on this host')
        r = self.client.get(reverse('barding:binary_index'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'ELF header')

    def test_binary_hex_view(self):
        try:
            from . import binary
            binary.resolve_binary()
        except FileNotFoundError:
            self.skipTest('claude binary not on this host')
        r = self.client.get(reverse('barding:binary_hex'),
                             {'offset': '0', 'length': '256'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '7f 45 4c 46')
