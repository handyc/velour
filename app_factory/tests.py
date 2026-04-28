"""Tests for the App Factory clone-skip invariants.

The clone flow's most important property is that it does NOT copy
secrets. A clone tree that inherits the originating install's
``secret_key.txt`` or any of the ``*_token.txt`` files means
compromise of one install is compromise of both. This module exists
to make that invariant a test, not a comment.

Run via:
    venv/bin/python manage.py test app_factory
"""

from django.test import SimpleTestCase

from app_factory.views import CLONE_SKIP_TOPLEVEL, CLONE_SKIP_PATTERNS


class CloneSecretSkipTests(SimpleTestCase):
    """Lock in that every secret-file-protocol entry is on the skip list."""

    SECRET_FILES = (
        'secret_key.txt',
        'health_token.txt',
        'mail_relay_token.txt',
        'provisioning_secret.txt',
    )

    def test_every_named_secret_is_in_toplevel_skip(self):
        for name in self.SECRET_FILES:
            with self.subTest(secret=name):
                self.assertIn(
                    name, CLONE_SKIP_TOPLEVEL,
                    f'Secret file {name!r} would leak into a clone tree. '
                    f'Add it to CLONE_SKIP_TOPLEVEL in app_factory/views.py.',
                )

    def test_token_glob_in_recursive_patterns(self):
        # Future *.token files (per the secret-file protocol) must be
        # caught by the recursive ignore_patterns so they're stripped
        # even from subdirectories of the clone tree.
        self.assertIn('*.token', CLONE_SKIP_PATTERNS)

    def test_llm_key_globs_in_recursive_patterns(self):
        self.assertIn('llm_*.key', CLONE_SKIP_PATTERNS)
        self.assertIn('*_api_key.txt', CLONE_SKIP_PATTERNS)

    def test_platformio_secrets_in_recursive_patterns(self):
        # gary_test/secrets.ini is the canonical example; ignore_patterns
        # matches by basename so this catches any per-board secrets.ini.
        self.assertIn('secrets.ini', CLONE_SKIP_PATTERNS)


class CloneCruftSkipTests(SimpleTestCase):
    """Sanity checks on the non-secret entries — these are about
    cleanliness rather than security, but a clone that ships a 146 MB
    db.sqlite3 or the entire .git tree is a bad clone."""

    NEVER_COPY_TOPLEVEL = (
        '.git',          # source-level git history; clone gets its own
        'db.sqlite3',    # current install's data
        'venv',          # built per clone
        'staticfiles',   # collectstatic output
        'velour_port.txt',  # runtime state
        'outputs',       # per-app scratch
        'media',         # uploaded files
        '.claude',       # harness state
        'memory',        # harness memory
    )

    def test_never_copy_entries_present(self):
        for name in self.NEVER_COPY_TOPLEVEL:
            with self.subTest(entry=name):
                self.assertIn(name, CLONE_SKIP_TOPLEVEL)
