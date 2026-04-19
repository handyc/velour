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

from django.db.models import Count, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone as djtz

from . import translator
from .models import FlashCard, Language, TranslationCache, UserLanguagePreference


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
def flashcards(request):
    """Deck index: per-language totals, due counts, and a Start button."""
    decks = (FlashCard.objects
             .filter(user=request.user)
             .values('language__code', 'language__name')
             .annotate(
                 total=Count('id'),
                 due=Count('id', filter=Q(due_at__lte=djtz.now())),
             )
             .order_by('language__name'))
    return render(request, 'lingua/flashcards.html', {'decks': list(decks)})


@login_required
def study(request, lang):
    """Pick the most-overdue due card for this user + language and
    render the flip-card. Grading happens via the `grade` POST endpoint
    which redirects back here."""
    language = get_object_or_404(Language, code=lang)
    now = djtz.now()
    # Overdue first, then new cards by frequency rank.
    card = (FlashCard.objects
            .filter(user=request.user, language=language, due_at__lte=now)
            .order_by('due_at', 'freq_rank', 'id')
            .first())

    total = FlashCard.objects.filter(user=request.user, language=language).count()
    due_count = (FlashCard.objects
                 .filter(user=request.user, language=language, due_at__lte=now)
                 .count())

    return render(request, 'lingua/study.html', {
        'card':       card,
        'language':   language,
        'total':      total,
        'due_count':  due_count,
    })


@csrf_exempt
@require_http_methods(['POST'])
@login_required
def grade(request):
    """Mark a card right/wrong and advance its Leitner box.

    Body (JSON or form): card_id, grade ('good' | 'again').
    Responds JSON {next_due_in_days, leitner_box} for the UI.
    """
    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body.decode('utf-8') or '{}')
        else:
            data = request.POST
        card_id = int(data.get('card_id'))
        g = (data.get('grade') or '').strip()
    except (TypeError, ValueError, json.JSONDecodeError):
        return HttpResponseBadRequest('bad request')

    card = get_object_or_404(FlashCard, pk=card_id, user=request.user)
    if g == 'good':
        card.promote()
    elif g == 'again':
        card.demote()
    else:
        return HttpResponseBadRequest('grade must be "good" or "again"')
    card.save()

    from .models import LEITNER_INTERVAL_DAYS
    return JsonResponse({
        'leitner_box':     card.leitner_box,
        'next_due_in_days': LEITNER_INTERVAL_DAYS[card.leitner_box],
    })


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
