"""Lingua views.

- `home`        — user-facing prefs page (pick priority languages, toggle auto-translate).
- `translate`   — JSON endpoint hit by the hover tooltip JS.
- `bootstrap`   — tiny JSON document the page includes for JS state.
"""

from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import translator
from .models import Language, TranslationCache, UserLanguagePreference


def _pref_for(user):
    if not user.is_authenticated:
        return None
    pref, _ = UserLanguagePreference.objects.get_or_create(user=user)
    return pref


@login_required
def home(request):
    pref = _pref_for(request.user)
    languages = list(Language.objects.all())

    if request.method == 'POST':
        codes = request.POST.getlist('priority')
        codes = [c for c in codes if c]
        known = {l.code for l in languages}
        pref.priority_codes = [c for c in codes if c in known]
        pref.auto_translate = request.POST.get('auto_translate') == 'on'
        pref.hover_modifier = request.POST.get('hover_modifier') or 'alt'
        pref.save()
        return redirect('lingua:home')

    cache_stats = {
        'rows':   TranslationCache.objects.count(),
        'by_lang': list(TranslationCache.objects.values('target_lang')
                        .order_by('target_lang').distinct()),
    }

    slots = []
    for i in range(6):
        current = pref.priority_codes[i] if i < len(pref.priority_codes) else ''
        slots.append({'num': i + 1, 'current': current})

    return render(request, 'lingua/home.html', {
        'pref':       pref,
        'languages':  languages,
        'slots':      slots,
        'cache_stats': cache_stats,
    })


@csrf_exempt
@require_http_methods(['POST'])
@login_required
def translate(request):
    """Translate one short string. Returns {translation, cached, backend}.

    Body: JSON {text: str, target_lang?: str, source_lang?: str}.
    If target_lang is omitted we use the user's primary preference.
    """
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'bad JSON'}, status=400)

    text = (data.get('text') or '').strip()
    if not text:
        return JsonResponse({'error': 'empty text'}, status=400)

    pref = _pref_for(request.user)
    target_lang = data.get('target_lang') or (pref.primary_code() if pref else '')
    if not target_lang:
        return JsonResponse({'error': 'no target_lang and no user primary'},
                            status=400)

    source_lang = data.get('source_lang') or 'en'

    result = translator.translate(text, target_lang, source_lang=source_lang)
    status = 200 if not result['error'] else 503
    return JsonResponse(result, status=status)


@login_required
def bootstrap(request):
    """Small JSON doc for base.html to decide whether to load the
    hover script and what settings to pass to it."""
    pref = _pref_for(request.user)
    if not pref or not pref.priority_codes:
        return JsonResponse({'active': False})
    return JsonResponse({
        'active':         bool(pref.auto_translate),
        'primary':        pref.primary_code(),
        'priority':       pref.priority_codes,
        'hover_modifier': pref.hover_modifier,
    })
