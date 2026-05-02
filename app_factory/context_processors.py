"""Expose the project's INSTALLED_APPS as a set of slugs for templates.

Lets templates guard nav links and feature references behind
``{% if 'foo' in installed_app_slugs %}…{% endif %}`` so a clone with
some apps stripped out still renders a clean nav rather than crashing
on a NoReverseMatch.

The set is computed once per process and cached at the module level —
INSTALLED_APPS doesn't change at runtime. Each request just gets a
reference to the same frozen set.
"""

from django.conf import settings


_INSTALLED_APP_SLUGS = None


def _compute_slugs():
    """Project app slugs only — strips django.contrib.* and dotted
    third-party app paths. Channels/daphne stay in because templates
    in clones may reference them by name."""
    slugs = set()
    for entry in settings.INSTALLED_APPS:
        if entry.startswith('django.'):
            continue
        # 'foo.apps.FooConfig' → 'foo'; 'foo' → 'foo'
        slugs.add(entry.split('.')[0])
    return frozenset(slugs)


def installed_app_slugs(request):
    """Backwards-compatible: ``installed_app_slugs`` is still the full
    set of installed apps; ``accessible_app_slugs`` is what the request
    user is allowed to see (intersection of installed × user's
    ``app:<slug>`` group memberships when per-app enforcement is on).
    Single-user dev mode (``VELOUR_PER_APP_ACCESS_ENFORCED=False``) keeps
    accessible == installed so existing templates don't change.
    """
    global _INSTALLED_APP_SLUGS
    if _INSTALLED_APP_SLUGS is None:
        _INSTALLED_APP_SLUGS = _compute_slugs()

    # Avoid an import loop by importing here, not at module load.
    from .access import apps_accessible_to
    user = getattr(request, 'user', None)
    accessible = apps_accessible_to(user) & _INSTALLED_APP_SLUGS

    return {
        'installed_app_slugs':  _INSTALLED_APP_SLUGS,
        'accessible_app_slugs': accessible,
    }
