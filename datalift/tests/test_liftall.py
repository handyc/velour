"""Smoke tests for the liftall orchestrator. Each underlying command
has its own deep test suite; this just confirms the chain wires
together correctly."""

from __future__ import annotations

import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase


class LiftAllArgValidationTests(SimpleTestCase):

    def test_theme_dir_requires_theme_type(self):
        with self.assertRaises(CommandError) as cm:
            call_command('liftall',
                         dump='/nonexistent.sql', app='datalift',
                         theme_dir='/tmp')
        self.assertIn('theme-type', str(cm.exception))

    def test_ingest_requires_migrate(self):
        # Requires a real-looking dump path so we hit the post-validation check.
        with tempfile.NamedTemporaryFile(suffix='.sql', delete=False) as f:
            f.write(b'-- empty')
            dump = f.name
        with self.assertRaises(CommandError) as cm:
            call_command('liftall', dump=dump, app='datalift', ingest=True)
        self.assertIn('migrate', str(cm.exception))

    def test_missing_dump(self):
        with self.assertRaises(CommandError):
            call_command('liftall', dump='/no/such/file.sql', app='datalift')


class LiftAllDispatchTests(SimpleTestCase):

    def test_theme_type_picks_right_command(self):
        from datalift.management.commands.liftall import THEME_TYPE_TO_COMMAND
        self.assertEqual(THEME_TYPE_TO_COMMAND['wp'], 'liftwp')
        self.assertEqual(THEME_TYPE_TO_COMMAND['smarty'], 'liftsmarty')
        self.assertEqual(THEME_TYPE_TO_COMMAND['twig'], 'liftwig')
