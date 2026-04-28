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


# ---------------------------------------------------------------------------
# Selective-clone registry + closure
# ---------------------------------------------------------------------------

from app_factory.app_registry import (
    CORE_APPS, OPTIONAL_APPS, OPTIONAL_BY_SLUG,
    compute_closure, included_apps,
)


class AppRegistryTests(SimpleTestCase):
    """The OPTIONAL registry's depends_on graph must be self-consistent
    and the closure walk must terminate even on cycles."""

    def test_core_and_optional_are_disjoint(self):
        core = set(CORE_APPS)
        optional = set(OPTIONAL_BY_SLUG)
        overlap = core & optional
        self.assertFalse(
            overlap,
            f'These slugs are in both CORE_APPS and OPTIONAL_APPS: {overlap}',
        )

    def test_every_declared_dep_resolves_to_a_known_optional_or_core(self):
        all_known = set(CORE_APPS) | set(OPTIONAL_BY_SLUG)
        for app in OPTIONAL_APPS:
            for dep in app.get('depends_on', []):
                with self.subTest(app=app['slug'], dep=dep):
                    self.assertIn(
                        dep, all_known,
                        f'{app["slug"]!r} declares dep {dep!r} which is '
                        f'neither CORE nor OPTIONAL',
                    )

    def test_closure_includes_transitive_deps(self):
        # roomplanner → aether → grammar_engine, legolith → lsystem
        closure = compute_closure(['roomplanner'])
        for expected in ['roomplanner', 'aether', 'grammar_engine',
                         'legolith', 'lsystem']:
            self.assertIn(expected, closure)

    def test_closure_is_idempotent(self):
        once = compute_closure(['naiad'])
        twice = compute_closure(once)
        self.assertEqual(once, twice)

    def test_unknown_slugs_silently_dropped(self):
        # The registry, not the form, is the source of truth.
        self.assertEqual(compute_closure(['totally_made_up_app']), set())

    def test_included_apps_always_contains_core(self):
        result = included_apps([])  # empty selection
        for core_slug in CORE_APPS:
            self.assertIn(core_slug, result)


class CloneFilterTests(SimpleTestCase):
    """Text rewriters for INSTALLED_APPS and url includes."""

    def test_filter_installed_apps_drops_unincluded(self):
        from app_factory.clone_filter import filter_installed_apps
        src = (
            "INSTALLED_APPS = [\n"
            "    'django.contrib.admin',\n"
            "    'channels',\n"
            "    'identity',\n"
            "    'naiad',\n"
            "    'lsystem',\n"
            "]\n"
        )
        out = filter_installed_apps(src, included_slugs={'channels', 'identity', 'lsystem'})
        # django.* always kept
        self.assertIn('django.contrib.admin', out)
        # included slugs kept
        self.assertIn("'channels'", out)
        self.assertIn("'identity'", out)
        self.assertIn("'lsystem'", out)
        # unincluded dropped
        self.assertNotIn("'naiad'", out)

    def test_context_processor_returns_frozenset_of_slugs(self):
        from app_factory.context_processors import (
            installed_app_slugs, _compute_slugs,
        )
        slugs = _compute_slugs()
        # Should be project apps, not django.contrib.*
        for entry in slugs:
            self.assertFalse(entry.startswith('django.'))
        # Should contain known slugs.
        for must_have in ('dashboard', 'identity', 'codex', 'app_factory'):
            self.assertIn(must_have, slugs)
        # Context processor returns the right key shape.
        ctx = installed_app_slugs(None)
        self.assertIn('installed_app_slugs', ctx)
        # Frozen so templates can't mutate it accidentally.
        self.assertIsInstance(ctx['installed_app_slugs'], frozenset)

    def _assert_url_calls_guarded(self, text, label):
        """Helper: every ``{% url 'app:...' %}`` in the given text must be
        preceded (within 400 chars) by an if-guard naming the same slug.
        ``admin`` / ``login`` / ``logout`` are Django built-ins and don't
        need a guard."""
        import re
        BUILTIN = {'admin', 'login', 'logout'}
        for m in re.finditer(r"\{%\s*url\s*'([a-z_][a-z_0-9]*):", text):
            slug = m.group(1)
            if slug in BUILTIN:
                continue
            window = text[max(0, m.start() - 400):m.start()]
            self.assertIn(
                f"'{slug}' in installed_app_slugs", window,
                f"{label}: {{% url '{slug}:...' %}} is not guarded by "
                f"{{% if '{slug}' in installed_app_slugs %}}. A stripped "
                f"clone will 500 on this link.",
            )

    def test_base_html_nav_links_are_guarded(self):
        from django.conf import settings
        path = settings.BASE_DIR / 'templates' / 'base.html'
        text = path.read_text()
        nav_start = text.find("class=\"nav-links\"")
        nav_end = text.find("</nav>", nav_start)
        self._assert_url_calls_guarded(text[nav_start:nav_end], 'base.html nav')

    def test_dashboard_home_cards_are_guarded(self):
        from django.conf import settings
        path = settings.BASE_DIR / 'templates' / 'dashboard' / 'home.html'
        text = path.read_text()
        # Scan only the {% block content %} section, which is where the
        # cards live. Style/JS blocks have no url calls.
        content_start = text.find("{% block content %}")
        self._assert_url_calls_guarded(text[content_start:], 'dashboard/home.html')

    def test_filter_url_includes_drops_unincluded(self):
        from app_factory.clone_filter import filter_url_includes
        src = (
            "urlpatterns = [\n"
            "    path('', landing, name='landing'),\n"
            "    path('chronos/', include('chronos.urls')),\n"
            "    path('naiad/', include('naiad.urls')),\n"
            "    path('lsystem/', include('lsystem.urls')),\n"
            "]\n"
        )
        out = filter_url_includes(src, included_slugs={'chronos', 'lsystem'})
        # bare path (no include) untouched
        self.assertIn("path(''", out)
        self.assertIn("'chronos.urls'", out)
        self.assertIn("'lsystem.urls'", out)
        # naiad dropped
        self.assertNotIn("'naiad.urls'", out)
