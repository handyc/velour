"""Terminal-shot views — upload an ANSI byte stream, decode it,
display the result as colour-preserving HTML and as luminance-
shaded ASCII art for non-terminal readers (Claude, screen readers,
diff reviewers, etc.).
"""
from __future__ import annotations

from django.http import HttpResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.html import escape
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST

from .models import Capture
from . import decoder as D


@require_GET
def index(request):
    captures = Capture.objects.all()
    return render(request, 'terminalshot/index.html', {
        'captures': captures,
    })


@require_GET
def detail(request, slug):
    cap = get_object_or_404(Capture, slug=slug)
    grid = D.parse(bytes(cap.blob), cols=cap.cols, rows=cap.rows)
    return render(request, 'terminalshot/detail.html', {
        'cap':       cap,
        'html_grid': D.render_html(grid),
        'shaded':    D.render_shaded(grid),
        'palette':   D.color_summary(grid),
        'cols':      cap.cols,
        'rows':      cap.rows,
        'bytes':     len(cap.blob),
    })


@require_POST
def upload(request):
    name = (request.POST.get('name') or '').strip()
    cols = int(request.POST.get('cols') or 80)
    rows = int(request.POST.get('rows') or 24)
    notes = (request.POST.get('notes') or '').strip()
    cols = max(1, min(cols, 400))
    rows = max(1, min(rows, 200))
    f = request.FILES.get('file')
    blob = b''
    if f:
        blob = f.read()
    else:
        # Allow paste-in-as-text fallback for quick CLI captures.
        text = request.POST.get('blob_text')
        if text:
            blob = text.encode('utf-8', errors='replace')
    if not name or not blob:
        return HttpResponseRedirect(reverse('terminalshot:index'))
    slug = slugify(name)[:120] or f'cap-{Capture.objects.count() + 1}'
    base = slug
    n = 1
    while Capture.objects.filter(slug=slug).exists():
        n += 1
        slug = f'{base}-{n}'
    cap = Capture.objects.create(
        name=name, slug=slug, cols=cols, rows=rows,
        notes=notes, blob=blob)
    return HttpResponseRedirect(reverse('terminalshot:detail', args=[cap.slug]))
