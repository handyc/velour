"""Per-app access gating for multi-user Velour deployments.

Today (single-user dev): every authenticated user can hit every app.
Tomorrow (VPS multi-user): admins assign limited users to a subset of
apps via Django groups named ``app:<slug>``. Superusers always
bypass. The check lives in middleware (``AppAccessMiddleware``) so
every URL inside an app's prefix is gated without per-view decorator
churn.

Enforcement is opt-in via ``settings.VELOUR_PER_APP_ACCESS_ENFORCED``
(default False). With enforcement off, this module's helpers behave
as if every user has access to every app — preserves the existing
single-user behaviour bit-for-bit.

Convention: one Django Group per app, named ``app:<slug>`` (e.g.
``app:taxon``, ``app:s3lab``). Use the ``grant_app_access`` management
command to assign / revoke; or assign through the standard
django.contrib.admin Group editor.
"""
from __future__ import annotations

from importlib import import_module
from typing import Iterable

from django.conf import settings
from django.urls import URLResolver


# ── Configuration ──────────────────────────────────────────────────

# URL prefixes that NEVER route through app gating, regardless of
# enforcement. These are infrastructure / cross-cutting endpoints.
ALWAYS_OPEN_PREFIXES = (
    '/',                      # landing page
    '/static/',
    '/media/',
    '/admin/',                # gated separately by is_staff
    '/accounts/',             # login / logout / password reset
    '/dashboard/',            # always shown; cards filter themselves
    '/api/',                  # token-authed device endpoints
)

GROUP_PREFIX = 'app:'


def is_enforced() -> bool:
    """True iff per-app access checks should bite. Defaults to False
    so existing single-user dev installs aren't disturbed."""
    return bool(getattr(settings, 'VELOUR_PER_APP_ACCESS_ENFORCED', False))


# ── URL prefix → app slug map (built once, cached) ────────────────

_PREFIX_TO_SLUG: dict[str, str] | None = None


def _walk_root_urlconf() -> dict[str, str]:
    """Inspect velour/urls.py at module load and build a mapping from
    top-level URL prefix (e.g. 'taxon') to installed-app slug (e.g.
    'taxon'). Most prefixes match the slug; a handful diverge —
    'news' → 'landingpage', 'windows' → 'winctl', 'apps' → app_factory,
    'gubi' → 'screen_gubi', 'grammar' → 'grammar_engine'.
    """
    root = import_module(settings.ROOT_URLCONF)
    out: dict[str, str] = {}
    for pat in root.urlpatterns:
        if not isinstance(pat, URLResolver):
            continue
        prefix_str = str(pat.pattern).strip('^').rstrip('/')
        if not prefix_str or '/' in prefix_str:
            continue
        # The included urlconf's module name reveals the app.
        try:
            urlconf_name = pat.urlconf_module.__name__
        except AttributeError:
            try:
                urlconf_name = pat.urlconf_name
            except Exception:
                continue
            if not isinstance(urlconf_name, str):
                continue
        # 'taxon.urls' → 'taxon'; 'screen_gubi.urls' → 'screen_gubi'
        app_slug = urlconf_name.split('.')[0]
        out[prefix_str] = app_slug
    return out


def prefix_to_slug() -> dict[str, str]:
    global _PREFIX_TO_SLUG
    if _PREFIX_TO_SLUG is None:
        _PREFIX_TO_SLUG = _walk_root_urlconf()
    return _PREFIX_TO_SLUG


def app_slug_for_path(path: str) -> str | None:
    """Return the app slug a request path belongs to, or None for
    paths in ``ALWAYS_OPEN_PREFIXES`` / unknown prefixes."""
    if not path or not path.startswith('/'):
        return None
    for ap in ALWAYS_OPEN_PREFIXES:
        if path == ap or (ap != '/' and path.startswith(ap)):
            return None
    if path == '/':
        return None
    first = path.lstrip('/').split('/', 1)[0]
    return prefix_to_slug().get(first)


# ── User → accessible app slugs ────────────────────────────────────

def user_can_access(user, slug: str) -> bool:
    """Check whether ``user`` has access to the app named by ``slug``.

    Rules:
      - Enforcement off → True (back-compat).
      - Anonymous → False (login_required wraps still gate auth-needed
        views; this only protects against authenticated-but-unprivileged).
      - Superuser → True.
      - Staff → True (matches Django convention; admins curate apps).
      - Otherwise → True iff user is in group ``app:<slug>``.
    """
    if not is_enforced():
        return True
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(name=f'{GROUP_PREFIX}{slug}').exists()


def apps_accessible_to(user) -> frozenset[str]:
    """Set of app slugs the user can see in nav / dashboard."""
    all_slugs = frozenset(prefix_to_slug().values())
    if not is_enforced():
        return all_slugs
    if user is None or not getattr(user, 'is_authenticated', False):
        return frozenset()
    if user.is_superuser or user.is_staff:
        return all_slugs
    user_groups = set(user.groups.values_list('name', flat=True))
    return frozenset(
        slug for slug in all_slugs
        if f'{GROUP_PREFIX}{slug}' in user_groups
    )


def grant(user, slugs: Iterable[str]) -> int:
    """Add the user to one Group per slug. Creates groups on demand.
    Returns number of groups added (existing memberships skipped)."""
    from django.contrib.auth.models import Group
    added = 0
    for slug in slugs:
        group, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}{slug}')
        if not user.groups.filter(pk=group.pk).exists():
            user.groups.add(group)
            added += 1
    return added


def revoke(user, slugs: Iterable[str]) -> int:
    """Remove the user from one Group per slug. Returns number removed."""
    from django.contrib.auth.models import Group
    removed = 0
    for slug in slugs:
        group = Group.objects.filter(name=f'{GROUP_PREFIX}{slug}').first()
        if group and user.groups.filter(pk=group.pk).exists():
            user.groups.remove(group)
            removed += 1
    return removed
