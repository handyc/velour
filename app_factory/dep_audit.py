"""Cross-app import auditor for the App Factory app registry.

Scans every project app's ``.py`` files for inter-app imports
(``from <other_app>...``) and compares the result against the
``depends_on`` declarations in ``app_registry.OPTIONAL_APPS``.

Used by:
- The ``audit_app_deps`` management command (operator-facing tool)
- A test in ``app_factory/tests.py`` that locks in zero drift, so a
  PR that adds a new inter-app import without updating the registry
  fails loudly in CI.
"""

import re
from pathlib import Path

from django.conf import settings

from .app_registry import CORE_APPS, OPTIONAL_BY_SLUG


# Module-level imports of the form `from foo.bar import X` or
# `import foo.bar` — also catches function-body imports because the
# regex is line-anchored, not block-aware.
_IMPORT_RE = re.compile(
    r'^\s*(?:from|import)\s+([a-z_][a-z_0-9]*)(?:\.[a-z_0-9.]+)?',
    re.MULTILINE,
)


# Subdirectories whose imports are NOT counted toward the runtime
# dep graph. Management commands and migrations only fail if their
# specific command is run / their specific migration is replayed —
# they're per-feature, not per-boot. A stripped clone where chronos
# is included but aether is not will boot fine, just `seed_aether_sky`
# would fail.
_AUDIT_SKIP_SUBDIRS = ('management/', 'migrations/', 'tests/', 'fixtures/')


def _path_is_runtime(path):
    parts = str(path).split('/')
    return not any(skip.rstrip('/') in parts for skip in _AUDIT_SKIP_SUBDIRS)


def scan_app_imports(*, runtime_only=True):
    """Walk each project app dir under BASE_DIR; for each ``.py`` file,
    extract inter-app imports. Returns ``{app_slug: set(other_app_slugs)}``.
    Self-imports and non-app imports are filtered out.

    When ``runtime_only=True`` (default), management commands,
    migrations, tests, and fixtures are excluded from the scan —
    those are per-feature failures, not per-boot. Pass False to see
    the full graph including soft/optional dependencies.
    """
    base = Path(settings.BASE_DIR)
    all_apps = set(CORE_APPS) | set(OPTIONAL_BY_SLUG)
    results = {}
    for app in all_apps:
        app_dir = base / app
        if not app_dir.is_dir():
            continue
        deps = set()
        for py in app_dir.rglob('*.py'):
            if '__pycache__' in str(py):
                continue
            if runtime_only and not _path_is_runtime(py):
                continue
            try:
                text = py.read_text()
            except OSError:
                continue
            for m in _IMPORT_RE.finditer(text):
                target = m.group(1)
                if target in all_apps and target != app:
                    deps.add(target)
        if deps:
            results[app] = deps
    return results


def audit_optional_app_deps():
    """Compare scanned imports against the registry. Returns a dict:

        {
          'missing': {app: set(missing_optional_deps)},
          'stale':   {app: set(stale_registry_entries)},
        }

    'missing' = imports detected in code but not declared in the
    registry's ``depends_on`` (the dangerous half — a stripped clone
    will crash).

    'stale' = registry entries that the scan didn't find (the safe
    half — it just means the declaration is over-cautious).

    CORE apps are always implicitly available, so a dependency on a
    CORE app is never reported as missing.
    """
    scan = scan_app_imports()
    missing, stale = {}, {}
    for slug, app in OPTIONAL_BY_SLUG.items():
        declared = set(app.get('depends_on', []))
        scanned = scan.get(slug, set())
        scanned_optional = scanned - set(CORE_APPS)
        miss = scanned_optional - declared
        stl = declared - scanned
        if miss:
            missing[slug] = miss
        if stl:
            stale[slug] = stl
    return {'missing': missing, 'stale': stale}
