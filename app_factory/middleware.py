"""Middleware for per-app access gating.

Drop into ``MIDDLEWARE`` after ``AuthenticationMiddleware``. With
``settings.VELOUR_PER_APP_ACCESS_ENFORCED = False`` (the default for
single-user dev) it's a no-op. With it True:

  - Requests to paths inside an app prefix are checked against the
    user's group membership (``app:<slug>``).
  - Anonymous users are redirected to login (preserves the existing
    @login_required UX).
  - Authenticated users without the relevant group get a friendly
    403 page that lists the apps they CAN access, instead of a bare
    PermissionDenied.
  - Superusers / staff bypass.
  - Allowlisted prefixes (``/``, ``/admin/``, ``/api/``, ``/dashboard/``,
    ``/static/``, ``/media/``, ``/accounts/``) always pass.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .access import (
    app_slug_for_path, apps_accessible_to, is_enforced, user_can_access,
)


class AppAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not is_enforced():
            return self.get_response(request)

        slug = app_slug_for_path(request.path)
        if slug is None:
            return self.get_response(request)

        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            # Match @login_required's behaviour — redirect to LOGIN_URL.
            return login_required(self.get_response)(request)

        if user_can_access(user, slug):
            return self.get_response(request)

        # Authenticated but not permitted — render a friendly 403 page
        # listing what they CAN reach so they're not stranded.
        accessible = sorted(apps_accessible_to(user))
        return render(request, '403_app_access.html', {
            'attempted_app': slug,
            'attempted_path': request.path,
            'accessible_apps': accessible,
        }, status=403)
