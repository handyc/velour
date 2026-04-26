import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.test.utils import override_settings

from backups.models import Snapshot


class MakeBackupTests(TestCase):
    """make_backup walks BASE_DIR for the candidate files,
    tars them up, and records a Snapshot row."""

    def setUp(self):
        # Pretend a fresh BASE_DIR with nothing in it but a fake DB.
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base / 'db.sqlite3').write_bytes(b'fake-db-bytes')
        (self.base / 'secret_key.txt').write_text('fake-secret')

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, **kwargs):
        with override_settings(BASE_DIR=str(self.base)):
            call_command('make_backup', **kwargs)

    def test_make_backup_creates_tarball_and_row(self):
        self._run(retention='manual')
        self.assertEqual(Snapshot.objects.count(), 1)
        snap = Snapshot.objects.first()
        self.assertTrue(Path(snap.path).exists())
        self.assertGreater(snap.size_bytes, 0)
        self.assertEqual(len(snap.sha256), 64)
        self.assertIn('db.sqlite3', snap.contents_summary)

    def test_dry_run_does_not_write_or_log(self):
        self._run(retention='manual', dry_run=True)
        self.assertEqual(Snapshot.objects.count(), 0)
        self.assertEqual(
            list((self.base / 'backups' / 'snapshots').glob('*.tar.gz'))
            if (self.base / 'backups' / 'snapshots').exists() else [],
            [])

    def test_daily_retention_prunes_past_window(self):
        # Make 9 daily snapshots; window is 7, so 2 should prune.
        for _ in range(9):
            self._run(retention='daily')
        self.assertEqual(Snapshot.objects.filter(retention='daily').count(), 7)

    def test_manual_retention_never_prunes(self):
        for _ in range(10):
            self._run(retention='manual')
        self.assertEqual(Snapshot.objects.filter(retention='manual').count(), 10)
