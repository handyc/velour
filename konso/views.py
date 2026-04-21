"""Konso views — list, detail, new/edit, delete, live preview.

Kept deliberately small. The tree parser + renderer live in
`konso.tree`; this module only talks to Django.
"""

from __future__ import annotations

import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .models import Sentence, SOURCE_CHOICES
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
    q = (request.GET.get('q') or '').strip()
    qs = Sentence.objects.all()
    if q:
        qs = qs.filter(konso__icontains=q) | qs.filter(
            translation__icontains=q) | qs.filter(slug__icontains=q)
        qs = qs.distinct()
    total = Sentence.objects.count()
    sentences = list(qs[:200])
    return render(request, 'konso/index.html', {
        'sentences':    sentences,
        'query':        q,
        'total':        total,
        'shown':        len(sentences),
        'source_choices': SOURCE_CHOICES,
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
    return render(request, 'konso/detail.html', {
        'sentence': s,
        'svg':      svg,
        'parse_error': err,
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
            return render(request, 'konso/edit.html', {
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
            return render(request, 'konso/edit.html', {
                'data': data, 'mode': 'create',
                'source_choices': SOURCE_CHOICES,
            })
        return redirect('konso:detail', slug=s.slug)
    return render(request, 'konso/edit.html', {
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
            return render(request, 'konso/edit.html', {
                'data': data, 'mode': 'edit', 'sentence': s,
                'source_choices': SOURCE_CHOICES,
            })
        return redirect('konso:detail', slug=s.slug)
    return render(request, 'konso/edit.html', {
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
    return redirect('konso:index')


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
