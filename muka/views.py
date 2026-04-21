"""Konso views — list, detail, new/edit, delete, live preview.

Kept deliberately small. The tree parser + renderer live in
`konso.tree`; this module only talks to Django.
"""

from __future__ import annotations

import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from django.db.models import Count

from . import glottolog
from .lingua_bridge import lingua_language_for
from .models import (
    Language, Sentence, FAMILY_CHOICES, SOURCE_CHOICES, GLOTTOLOG_FAMILY_SLUG,
)
from .tree import ParseError, parse_bracket, render_svg


def _unique_slug(base: str, ignore_pk: int | None = None) -> str:
    base = slugify(base) or 'sentence'
    slug = base[:70]
    i = 2
    qs = Sentence.objects.all()
    if ignore_pk:
        qs = qs.exclude(pk=ignore_pk)
    while qs.filter(slug=slug).exists():
        slug = f'{base[:66]}-{i}'
        i += 1
    return slug


@login_required
def index(request):
    """Language list grouped by family. This is the landing page now that
    the app covers African languages broadly (not just Konso)."""
    langs = (Language.objects
             .annotate(n_sent=Count('sentences'))
             .order_by('family', 'english_name'))
    family_label = dict(FAMILY_CHOICES)
    groups = {}
    for lang in langs:
        groups.setdefault(lang.family, []).append(lang)
    ordered_families = [
        (fam, family_label.get(fam, fam), groups[fam])
        for fam, _ in FAMILY_CHOICES if fam in groups
    ]
    for fam in groups:
        if fam not in dict(FAMILY_CHOICES):
            ordered_families.append((fam, fam, groups[fam]))

    # Sentences with no language (legacy rows, or new ones without a FK).
    orphan_count = Sentence.objects.filter(language__isnull=True).count()

    return render(request, 'muka/index.html', {
        'family_groups': ordered_families,
        'total_langs':   Language.objects.count(),
        'total_sent':    Sentence.objects.count(),
        'orphan_count':  orphan_count,
    })


@login_required
def language_detail(request, slug):
    lang = get_object_or_404(Language, slug=slug)
    sentences = list(Sentence.objects.filter(language=lang))
    lingua_lang = lingua_language_for(lang, create=False)
    deck_count = 0
    if lingua_lang:
        from lingua.models import FlashCard
        deck_count = FlashCard.objects.filter(
            user=request.user, language=lingua_lang, theme='muka').count()
    return render(request, 'muka/language_detail.html', {
        'lang':         lang,
        'sentences':    sentences,
        'source_choices': SOURCE_CHOICES,
        'lingua_lang':  lingua_lang,
        'deck_count':   deck_count,
    })


@login_required
def sentence_index(request):
    """Flat search across sentences — the previous `index` behaviour."""
    q = (request.GET.get('q') or '').strip()
    lang_slug = (request.GET.get('lang') or '').strip()
    qs = Sentence.objects.select_related('language').all()
    if lang_slug:
        qs = qs.filter(language__slug=lang_slug)
    if q:
        qs = qs.filter(konso__icontains=q) | qs.filter(
            translation__icontains=q) | qs.filter(slug__icontains=q)
        qs = qs.distinct()
    total = Sentence.objects.count()
    sentences = list(qs[:300])
    return render(request, 'muka/sentence_index.html', {
        'sentences':      sentences,
        'query':          q,
        'lang_slug':      lang_slug,
        'total':          total,
        'shown':          len(sentences),
        'source_choices': SOURCE_CHOICES,
        'languages':      Language.objects.order_by('english_name'),
    })


@login_required
def detail(request, slug):
    s = get_object_or_404(Sentence, slug=slug)
    svg = ''
    err = None
    try:
        node = parse_bracket(s.tree_bracket)
        svg = render_svg(node)
    except ParseError as e:
        err = str(e)
    lingua_lang = None
    in_deck = False
    if s.language:
        lingua_lang = lingua_language_for(s.language, create=False)
        if lingua_lang:
            from lingua.models import FlashCard
            in_deck = FlashCard.objects.filter(
                user=request.user, language=lingua_lang,
                gloss=s.translation[:400], theme='muka',
                level='sentence').exists()
    return render(request, 'muka/detail.html', {
        'sentence':    s,
        'svg':         svg,
        'parse_error': err,
        'lingua_lang': lingua_lang,
        'in_deck':     in_deck,
    })


def _form_payload(request):
    return {
        'konso':        (request.POST.get('konso') or '').strip(),
        'gloss':        (request.POST.get('gloss') or '').strip(),
        'translation':  (request.POST.get('translation') or '').strip(),
        'tree_bracket': (request.POST.get('tree_bracket') or '').strip(),
        'notes':        (request.POST.get('notes') or '').strip(),
        'source':       (request.POST.get('source') or 'illustrative'),
        'citation':     (request.POST.get('citation') or '').strip(),
    }


@login_required
def create(request):
    if request.method == 'POST':
        data = _form_payload(request)
        if not data['konso'] or not data['tree_bracket']:
            messages.error(request,
                'Konso text and tree bracket are both required.')
            return render(request, 'muka/edit.html', {
                'data': data, 'mode': 'create',
                'source_choices': SOURCE_CHOICES,
            })
        s = Sentence(
            slug=_unique_slug(data['konso']),
            **{k: v for k, v in data.items() if k in {
                'konso', 'gloss', 'translation', 'tree_bracket',
                'notes', 'source', 'citation'}})
        try:
            s.full_clean()
            s.save()
        except ValidationError as e:
            messages.error(request, '; '.join(
                f'{k}: {", ".join(vs)}' for k, vs in e.message_dict.items()))
            return render(request, 'muka/edit.html', {
                'data': data, 'mode': 'create',
                'source_choices': SOURCE_CHOICES,
            })
        return redirect('muka:detail', slug=s.slug)
    return render(request, 'muka/edit.html', {
        'data': {
            'konso': '', 'gloss': '', 'translation': '',
            'tree_bracket': '[S [NP ] [VP [V ]]]',
            'notes': '', 'source': 'illustrative', 'citation': '',
        },
        'mode': 'create',
        'source_choices': SOURCE_CHOICES,
    })


@login_required
def edit(request, slug):
    s = get_object_or_404(Sentence, slug=slug)
    if request.method == 'POST':
        data = _form_payload(request)
        for k, v in data.items():
            setattr(s, k, v)
        try:
            s.full_clean()
            s.save()
        except ValidationError as e:
            messages.error(request, '; '.join(
                f'{k}: {", ".join(vs)}' for k, vs in e.message_dict.items()))
            return render(request, 'muka/edit.html', {
                'data': data, 'mode': 'edit', 'sentence': s,
                'source_choices': SOURCE_CHOICES,
            })
        return redirect('muka:detail', slug=s.slug)
    return render(request, 'muka/edit.html', {
        'data': {
            'konso':        s.konso,
            'gloss':        s.gloss,
            'translation':  s.translation,
            'tree_bracket': s.tree_bracket,
            'notes':        s.notes,
            'source':       s.source,
            'citation':     s.citation,
        },
        'mode': 'edit', 'sentence': s,
        'source_choices': SOURCE_CHOICES,
    })


@login_required
@require_POST
def delete(request, slug):
    s = get_object_or_404(Sentence, slug=slug)
    s.delete()
    return redirect('muka:index')


def _make_flashcard(user, sentence, lingua_lang):
    """Create (or fetch) a Lingua FlashCard mirroring a Muka Sentence.
    Returns (card, created). theme='muka', level='sentence'.
    """
    from lingua.models import FlashCard
    defaults = {
        'lemma':         sentence.konso[:400],
        'pronunciation': (sentence.gloss or '')[:400],
        'backend':       'muka',
        'freq_rank':     None,
    }
    card, created = FlashCard.objects.get_or_create(
        user=user,
        language=lingua_lang,
        source_lang='en',
        gloss=sentence.translation[:400],
        theme='muka',
        level='sentence',
        defaults=defaults,
    )
    # Keep the mirror fresh if the sentence was edited.
    if not created:
        changed = False
        if card.lemma != defaults['lemma']:
            card.lemma = defaults['lemma']; changed = True
        if card.pronunciation != defaults['pronunciation']:
            card.pronunciation = defaults['pronunciation']; changed = True
        if changed:
            card.save(update_fields=['lemma', 'pronunciation'])
    return card, created


@login_required
@require_POST
def add_sentence_to_deck(request, slug):
    s = get_object_or_404(Sentence, slug=slug)
    if not s.language:
        messages.error(request,
            'This sentence has no language attached — cannot build a flashcard.')
        return redirect('muka:detail', slug=slug)
    lingua_lang = lingua_language_for(s.language, create=True)
    if not lingua_lang:
        messages.error(request,
            f'{s.language.english_name} has no ISO 639-3 code; cannot link '
            'to Lingua.')
        return redirect('muka:detail', slug=slug)
    _, created = _make_flashcard(request.user, s, lingua_lang)
    if created:
        messages.success(request,
            f'Added to your {lingua_lang.name} deck (Konso theme, sentence level).')
    else:
        messages.info(request,
            f'Already in your {lingua_lang.name} deck.')
    return redirect('muka:detail', slug=slug)


@login_required
@require_POST
def add_language_to_deck(request, slug):
    lang = get_object_or_404(Language, slug=slug)
    sentences = list(Sentence.objects.filter(language=lang))
    if not sentences:
        messages.warning(request,
            f'No sentences attached to {lang.english_name} yet.')
        return redirect('muka:language_detail', slug=slug)
    lingua_lang = lingua_language_for(lang, create=True)
    if not lingua_lang:
        messages.error(request,
            f'{lang.english_name} has no ISO 639-3 code; cannot link to Lingua.')
        return redirect('muka:language_detail', slug=slug)
    made, existed = 0, 0
    for s in sentences:
        _, created = _make_flashcard(request.user, s, lingua_lang)
        if created:
            made += 1
        else:
            existed += 1
    if made:
        messages.success(request,
            f'Added {made} new flashcard(s) to your {lingua_lang.name} deck.'
            + (f' ({existed} already in deck.)' if existed else ''))
    else:
        messages.info(request,
            f'All {existed} sentence(s) already in your {lingua_lang.name} deck.')
    return redirect('muka:language_detail', slug=slug)


def _language_from_glottolog(row):
    """Turn a Glottolog CSV row into a saved Language (or return the
    existing one if we already have this glottocode)."""
    code = (row.get('g') or '').strip().lower()
    if not code:
        return None, False
    existing = Language.objects.filter(glottocode=code).first()
    if existing:
        return existing, False
    name = (row.get('n') or code).strip()
    family_raw = (row.get('fam') or '').strip()
    family_slug = GLOTTOLOG_FAMILY_SLUG.get(family_raw, 'other')
    if family_raw == '' and not family_slug:
        family_slug = 'isolate'
    slug_base = slugify(name) or code
    slug = slug_base[:70]
    i = 2
    while Language.objects.filter(slug=slug).exists():
        slug = f'{slug_base[:66]}-{i}'
        i += 1
    def _float_or_none(v):
        try:
            return float(v) if v not in (None, '') else None
        except (TypeError, ValueError):
            return None
    lang = Language.objects.create(
        slug=slug,
        glottocode=code,
        name=name,
        english_name=name,
        family=family_slug,
        family_name=family_raw,
        subgroup='',
        region='',
        macroarea=(row.get('ma') or '').strip(),
        iso639_3=(row.get('iso') or '').strip(),
        speakers=0,
        word_order='unknown',
        script='',
        extinct=False,
        latitude=_float_or_none(row.get('lat')),
        longitude=_float_or_none(row.get('lon')),
        notes='Auto-added from Glottolog. Fill in typology/grammar notes.',
    )
    return lang, True


@login_required
@require_POST
def add_random_language(request):
    """Pick one random Glottolog language we don't already have and
    add it as a bare Language row (no sentences)."""
    seen = set(Language.objects.exclude(glottocode='')
               .values_list('glottocode', flat=True))
    row = glottolog.random_unseen(seen)
    if not row:
        messages.warning(request,
            'No new Glottolog languages left to add — we have them all.')
        return redirect('muka:index')
    lang, created = _language_from_glottolog(row)
    if lang is None:
        messages.error(request, 'Could not create language from Glottolog row.')
        return redirect('muka:index')
    if created:
        messages.success(request,
            f'Added {lang.english_name} ({lang.glottocode}) from Glottolog.')
    return redirect('muka:language_detail', slug=lang.slug)


@login_required
def search_glottolog(request):
    """JSON endpoint — returns up to 15 fuzzy matches for a query."""
    q = (request.GET.get('q') or '').strip()
    if not q:
        return JsonResponse({'results': []})
    have = set(Language.objects.exclude(glottocode='')
               .values_list('glottocode', flat=True))
    hits = glottolog.search(q, limit=15)
    results = [{
        'glottocode':  r['g'],
        'name':        r['n'],
        'iso':         r['iso'],
        'family':      r['fam'],
        'macroarea':   r['ma'],
        'already':     r['g'] in have,
    } for r in hits]
    return JsonResponse({'results': results})


@login_required
@require_POST
def add_by_glottocode(request, glottocode):
    row = glottolog.find_by_glottocode(glottocode)
    if not row:
        messages.error(request,
            f'No Glottolog entry for glottocode "{glottocode}".')
        return redirect('muka:index')
    lang, created = _language_from_glottolog(row)
    if lang is None:
        messages.error(request, 'Could not create language from Glottolog row.')
        return redirect('muka:index')
    if created:
        messages.success(request,
            f'Added {lang.english_name} ({lang.glottocode}) from Glottolog.')
    else:
        messages.info(request,
            f'{lang.english_name} is already in the library.')
    return redirect('muka:language_detail', slug=lang.slug)


@login_required
@require_POST
def preview(request):
    """Parse `tree_bracket` and return an SVG fragment. Used by the
    edit page's live-preview button. Plain HTML (not JSON) so it can
    be dropped into a <div> with innerHTML directly."""
    src = (request.POST.get('tree_bracket') or '').strip()
    if not src:
        return HttpResponse(
            '<p style="color:#8b949e;font-size:0.78rem">'
            'Enter a bracket tree above.</p>')
    try:
        node = parse_bracket(src)
    except ParseError as e:
        return HttpResponse(
            f'<p style="color:#f85149;font-size:0.78rem">'
            f'Parse error: {e}</p>')
    return HttpResponse(render_svg(node))
