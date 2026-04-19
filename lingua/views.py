"""Lingua views.

- `home`        — user-facing prefs page (pick priority languages, toggle auto-translate).
- `translate`   — JSON endpoint hit by the hover tooltip JS.
- `bootstrap`   — tiny JSON document the page includes for JS state.
"""

from __future__ import annotations

import io
import json
import subprocess
import threading
import wave
from pathlib import Path

from django.conf import settings
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


# Map Velour language codes to espeak-ng voice names. Classical
# languages without their own voices borrow a modern relative.
ESPEAK_VOICE = {
    'en':      'en-us',
    'nl':      'nl',
    'fr':      'fr-fr',
    'es':      'es',
    'ja':      'ja',
    'ko':      'ko',
    'he':      'he',
    'zh':      'cmn',
    'zh-Hans': 'cmn',
    'zh-Hant': 'cmn',
    'grc':     'grc',
    'la':      'la',
    'san':     'hi',
    'sa':      'hi',
}

# Piper is the quality upgrade path. A language is piper-eligible only
# when a .onnx model sits next to this package; otherwise we fall back
# to espeak-ng. Models are big (~60 MB each) so they live outside git.
PIPER_VOICE = {
    'fr':      'fr_FR-siwis-medium',
    'zh':      'zh_CN-huayan-medium',
    'zh-Hans': 'zh_CN-huayan-medium',
    'zh-Hant': 'zh_CN-huayan-medium',
}

_piper_dir = Path(settings.BASE_DIR) / 'lingua' / 'data' / 'piper_voices'
_piper_cache: dict = {}
_piper_lock = threading.Lock()


def _piper_wav(text: str, lang: str):
    """Return WAV bytes synthesized by piper, or None if not available
    for this lang. Voice instances are cached per process — the first
    request pays ~1 s of onnxruntime warm-up, the rest are fast."""
    key = PIPER_VOICE.get(lang) or PIPER_VOICE.get(lang.split('-')[0])
    if not key:
        return None
    model_path = _piper_dir / (key + '.onnx')
    config_path = _piper_dir / (key + '.onnx.json')
    if not model_path.exists() or not config_path.exists():
        return None
    try:
        from piper import PiperVoice  # lazy: tolerate missing dep
    except ImportError:
        return None
    with _piper_lock:
        voice = _piper_cache.get(key)
        if voice is None:
            voice = PiperVoice.load(str(model_path), config_path=str(config_path))
            _piper_cache[key] = voice
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            voice.synthesize_wav(text, wf)
        return buf.getvalue()


def _espeak_wav(text: str, lang: str):
    """Return WAV bytes from espeak-ng, or raise the exception to caller."""
    voice = ESPEAK_VOICE.get(lang) or ESPEAK_VOICE.get(lang.split('-')[0]) or 'en-us'
    proc = subprocess.run(
        ['espeak-ng', '-v', voice, '-s', '150', '--stdout', text],
        capture_output=True, timeout=8, check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(proc.stderr.decode('utf-8', 'replace') or 'espeak failed')
    return proc.stdout


@login_required
@require_http_methods(['GET'])
def speak(request):
    """Server-side TTS. Prefers piper when a model is available for the
    language; otherwise falls back to espeak-ng. Exists because Firefox
    on Windows exposes almost no Web Speech voices, making in-browser
    TTS unreliable for foreign-language drilling."""
    text = (request.GET.get('text') or '').strip()
    lang = (request.GET.get('lang') or 'en').strip()
    if not text:
        return HttpResponseBadRequest('missing text')
    if len(text) > 500:
        return HttpResponseBadRequest('text too long')

    backend = 'piper'
    try:
        wav = _piper_wav(text, lang)
        if wav is None:
            backend = 'espeak-ng'
            wav = _espeak_wav(text, lang)
    except FileNotFoundError:
        return HttpResponse('espeak-ng not installed', status=503,
                            content_type='text/plain')
    except subprocess.TimeoutExpired:
        return HttpResponse('tts timed out', status=504, content_type='text/plain')
    except Exception as exc:
        return HttpResponse('tts failed: ' + str(exc), status=500,
                            content_type='text/plain')

    resp = HttpResponse(wav, content_type='audio/wav')
    resp['Cache-Control'] = 'private, max-age=3600'
    resp['Content-Length'] = str(len(wav))
    resp['X-Lingua-TTS'] = backend
    return resp


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
