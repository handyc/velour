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


_THEME_LABELS = {
    '':                'General (frequency list)',
    'body_parts':      'Body Parts',
    'animals':         'Animals',
    'food_drink':      'Food and Drink',
    'counting':        'Counting',
    'outer_space':     'Outer Space',
    'quantum_physics': 'Quantum Physics',
    'math_terms':      'Math Terms',
    'out_on_the_town': 'Out on the Town',
    'greetings':       'Greetings & Small Talk',
}


def _theme_label(slug):
    if slug in _THEME_LABELS:
        return _THEME_LABELS[slug]
    return slug.replace('_', ' ').title()


@login_required
def flashcards(request):
    """Deck index grouped by language, then by (theme, level) within each.

    One "deck" = one (language, theme, level) tuple. A user who only ran
    the old general builder will still see a single deck per language
    (theme='', level='word')."""
    now = djtz.now()
    rows = (FlashCard.objects
            .filter(user=request.user)
            .values('language__code', 'language__name',
                    'language__low_resource', 'theme', 'level')
            .annotate(
                total=Count('id'),
                due=Count('id', filter=Q(due_at__lte=now)),
            )
            .order_by('language__name', 'theme', 'level'))

    # Fold into per-language blocks for template rendering.
    level_order = {'word': 0, 'phrase': 1, 'sentence': 2}
    by_language = {}
    for r in rows:
        code = r['language__code']
        block = by_language.setdefault(code, {
            'code':          code,
            'name':          r['language__name'],
            'low_resource':  r['language__low_resource'],
            'decks':         [],
            'total':         0,
            'due':           0,
        })
        block['decks'].append({
            'theme':       r['theme'],
            'theme_label': _theme_label(r['theme']),
            'level':       r['level'],
            'total':       r['total'],
            'due':         r['due'],
        })
        block['total'] += r['total']
        block['due']   += r['due']

    languages = list(by_language.values())
    languages.sort(key=lambda b: (-b['due'], b['name']))
    for block in languages:
        block['decks'].sort(key=lambda d: (d['theme'] != '',
                                           d['theme_label'].lower(),
                                           level_order.get(d['level'], 9)))

    return render(request, 'lingua/flashcards.html', {'languages': languages})


@login_required
def study(request, lang, theme='', level=''):
    """Flip-card study view for one (language, theme, level) deck.

    `theme` and `level` are optional URL segments (defaults to "all" and
    "all"). Passing "-" as the theme segment means "no theme" (the
    general frequency deck). Omitting both studies across all decks for
    that language."""
    language = get_object_or_404(Language, code=lang)
    now = djtz.now()

    filter_kwargs = {'user': request.user, 'language': language}
    # URL convention: "-" in the theme slot means the empty-theme general
    # deck; "all" (or missing) means "don't filter on theme".
    if theme and theme != 'all':
        filter_kwargs['theme'] = '' if theme == '-' else theme
    if level and level != 'all':
        filter_kwargs['level'] = level

    card = (FlashCard.objects
            .filter(due_at__lte=now, **filter_kwargs)
            .order_by('due_at', 'freq_rank', 'id')
            .first())

    total     = FlashCard.objects.filter(**filter_kwargs).count()
    due_count = FlashCard.objects.filter(due_at__lte=now,
                                         **filter_kwargs).count()

    # Used to build the "back to deck index" and UI header labels.
    theme_slug  = filter_kwargs.get('theme', None)
    theme_label = (_theme_label(theme_slug)
                   if theme_slug is not None else 'All themes')
    level_label = (filter_kwargs.get('level', None) or 'All levels').title()

    return render(request, 'lingua/study.html', {
        'card':        card,
        'language':    language,
        'total':       total,
        'due_count':   due_count,
        'theme':       theme or 'all',
        'level':       level or 'all',
        'theme_label': theme_label,
        'level_label': level_label,
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
