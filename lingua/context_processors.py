"""Exposes the current user's lingua prefs to every template.

`lingua_cfg` is `None` when the user is anonymous, has no prefs, or
has auto_translate disabled. base.html skips the script tag in that
case — no runtime cost for the unconfigured majority.
"""

from __future__ import annotations


def lingua(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {'lingua_cfg': None}

    # Lazy import — context processors run early in template
    # rendering, before apps are fully ready in some edge cases.
    try:
        from .models import UserLanguagePreference
    except Exception:
        return {'lingua_cfg': None}

    try:
        pref = UserLanguagePreference.objects.filter(user=user).first()
    except Exception:
        return {'lingua_cfg': None}

    if not pref or not pref.auto_translate or not pref.priority_codes:
        return {'lingua_cfg': None}

    return {'lingua_cfg': {
        'active':         True,
        'primary':        pref.primary_code(),
        'priority':       pref.priority_codes,
        'hover_modifier': pref.hover_modifier,
    }}
