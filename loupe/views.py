"""loupe views — interactive Mandelbrot zoom + agent-walk library.

The renderer runs entirely in the browser (canvas + JS).  The server
persists Walks (manual single-step saves or full agent gene
sequences) and serves the catalogue.
"""

from __future__ import annotations

import json
import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .models import Walk
from . import render as renderer


# ─── interactive viewer ──────────────────────────────────────────────

@login_required
def index(request):
    """Live Mandelbrot zoomer with save-view + spawn-population controls."""
    return render(request, 'loupe/index.html', {
        'recent_walks':  Walk.objects.all()[:12],
    })


# ─── library ─────────────────────────────────────────────────────────

@login_required
def walks_list(request):
    method = (request.GET.get('method') or '').strip()
    population = (request.GET.get('population') or '').strip()
    qs = Walk.objects.all()
    if method in {'manual', 'agent', 'replay'}:
        qs = qs.filter(method=method)
    if population:
        qs = qs.filter(population_id=population)
    return render(request, 'loupe/walks.html', {
        'walks':       qs[:300],
        'method':      method,
        'population':  population,
        'populations': (Walk.objects
                          .exclude(population_id='')
                          .values_list('population_id', flat=True)
                          .distinct()[:50]),
    })


@login_required
def walk_detail(request, slug):
    walk = get_object_or_404(Walk, slug=slug)
    return render(request, 'loupe/walk_detail.html', {
        'walk':      walk,
        'gene_json': json.dumps(walk.gene_json),
    })


# ─── save endpoints ──────────────────────────────────────────────────

def _summarise_gene(gene: list) -> dict:
    """Pull the denormalised summary fields off a gene list.  Tolerant
    of missing keys so a single-step manual save still works."""
    if not isinstance(gene, list) or not gene:
        return {'n_steps': 0, 'fitness_final': 0.0,
                 'fitness_max': 0.0, 'fitness_mean': 0.0,
                 'end_cx': -0.5, 'end_cy': 0.0, 'end_span': 3.0,
                 'end_iter': 192}
    fitnesses = [float(s.get('fitness', 0.0)) for s in gene]
    last = gene[-1]
    return {
        'n_steps':        max(0, len(gene) - 1),
        'fitness_final':  fitnesses[-1] if fitnesses else 0.0,
        'fitness_max':    max(fitnesses) if fitnesses else 0.0,
        'fitness_mean':   sum(fitnesses) / len(fitnesses) if fitnesses else 0.0,
        'end_cx':         float(last.get('cx', -0.5)),
        'end_cy':         float(last.get('cy', 0.0)),
        'end_span':       float(last.get('span', 3.0)),
        'end_iter':       int(last.get('iter', 192)),
    }


def _make_slug(base: str) -> str:
    s = slugify(base) or 'walk'
    out = s
    n = 1
    while Walk.objects.filter(slug=out).exists():
        n += 1
        out = f'{s}-{n}'
    return out


@require_POST
@login_required
def save_walk(request):
    """Persist a single walk.  Body: JSON {name, gene, thumbnail_b64,
    method, parent_slug, population_id, notes}."""
    try:
        body = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'invalid JSON'}, status=400)
    gene = body.get('gene') or []
    if not isinstance(gene, list) or not gene:
        return JsonResponse({'error': 'gene must be a non-empty list'},
                              status=400)
    name = (body.get('name') or '').strip()[:160]
    summary = _summarise_gene(gene)
    walk = Walk.objects.create(
        slug=_make_slug(name or 'walk'),
        name=name,
        notes=(body.get('notes') or '').strip()[:1000],
        gene_json=gene,
        method=(body.get('method') or 'manual')
                 if body.get('method') in ('manual', 'agent', 'replay')
                 else 'manual',
        population_id=(body.get('population_id') or '').strip()[:24],
        parent_slug=(body.get('parent_slug') or '').strip()[:80],
        thumbnail_b64=(body.get('thumbnail_b64') or '')[:1_000_000],
        thumbnail_w=int(body.get('thumbnail_w') or 128),
        thumbnail_h=int(body.get('thumbnail_h') or 128),
        **summary,
    )
    return JsonResponse({'slug': walk.slug,
                          'url': f'/loupe/w/{walk.slug}/'})


@require_POST
@login_required
def save_walks(request):
    """Persist a batch of agent walks generated in one population.

    Body: JSON {population_id?, name_prefix?, walks: [walk, ...]}
    where each walk has the same shape as save_walk's body.
    """
    try:
        body = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'invalid JSON'}, status=400)
    walks_in = body.get('walks') or []
    if not isinstance(walks_in, list) or not walks_in:
        return JsonResponse({'error': 'walks must be a non-empty list'},
                              status=400)
    pop_id = (body.get('population_id')
                or 'pop-' + secrets.token_hex(4))[:24]
    name_prefix = (body.get('name_prefix') or 'agent').strip()[:120]
    created = []
    for i, w in enumerate(walks_in):
        gene = w.get('gene') or []
        if not isinstance(gene, list) or not gene:
            continue
        summary = _summarise_gene(gene)
        walk = Walk.objects.create(
            slug=_make_slug(f'{name_prefix}-{pop_id}-{i:03d}'),
            name=w.get('name') or f'{name_prefix} #{i}',
            gene_json=gene,
            method='agent',
            population_id=pop_id,
            parent_slug=(w.get('parent_slug') or '').strip()[:80],
            thumbnail_b64=(w.get('thumbnail_b64') or '')[:1_000_000],
            thumbnail_w=int(w.get('thumbnail_w') or 128),
            thumbnail_h=int(w.get('thumbnail_h') or 128),
            **summary,
        )
        created.append(walk.slug)
    return JsonResponse({
        'population_id': pop_id,
        'created':       created,
        'url':           f'/loupe/walks/?population={pop_id}',
    })


@require_POST
@login_required
def walk_delete(request, slug):
    walk = get_object_or_404(Walk, slug=slug)
    walk.delete()
    return redirect('loupe:walks')


# ─── server-side PNG rendering ───────────────────────────────────────

def _float(req, name, default, lo=None, hi=None):
    try:
        v = float(req.GET.get(name, default))
    except (TypeError, ValueError):
        v = default
    if lo is not None: v = max(lo, v)
    if hi is not None: v = min(hi, v)
    return v


def _int(req, name, default, lo=None, hi=None):
    try:
        v = int(req.GET.get(name, default))
    except (TypeError, ValueError):
        v = default
    if lo is not None: v = max(lo, v)
    if hi is not None: v = min(hi, v)
    return v


@login_required
def mandelbrot_png(request):
    """Standalone Mandelbrot PNG.  Query: ?cx&cy&span&w&h&iter."""
    cx = _float(request, 'cx', -0.5, lo=-2.5, hi=2.0)
    cy = _float(request, 'cy', 0.0,  lo=-2.0, hi=2.0)
    span = _float(request, 'span', 3.0, lo=1e-12, hi=8.0)
    w = _int(request, 'w', 1024, lo=16, hi=2000)
    h = _int(request, 'h', 1024, lo=16, hi=2000)
    iter_cap = _int(request, 'iter', 0, lo=0, hi=8192)
    iter_cap = iter_cap or renderer.auto_iter(span)
    png = renderer.render_mandelbrot_png(cx, cy, span, w, h,
                                            iter_cap=iter_cap)
    resp = HttpResponse(png, content_type='image/png')
    resp['Cache-Control'] = 'public, max-age=3600'
    return resp


@login_required
def spoeqi_palette(request, slug):
    """JSON {palette: [[r,g,b],...]} from a spoeqi Pact.

    Pacts carry a 4-RGB palette (shared) or 64 per-component
    palettes (when rule_diversity='fleet' or per-component colours
    were assigned).  Optional ``?component=N`` selects one when the
    pact is per-component; otherwise the shared palette is used.

    The first entry returned is always pure black so callers can
    drop it straight into LoupeEngine.palette without rebuilding.
    """
    from spoeqi.models import Pact, is_per_component_palette, COMPONENTS

    pact = Pact.objects.filter(slug=slug).first()
    if pact is None:
        return JsonResponse({'error': f'pact "{slug}" not found'},
                              status=404)
    palette = pact.palette
    if not palette:
        return JsonResponse({'error': 'pact has no palette'}, status=400)

    if is_per_component_palette(palette):
        comp = _int(request, 'component', 0, lo=0, hi=COMPONENTS - 1)
        rgbs = palette[comp]
        source = f'spoeqi:{slug}/component:{comp}'
    else:
        rgbs = palette
        source = f'spoeqi:{slug}'

    # Cast to int + dedupe so the engine palette is a clean list of
    # length 1 + len(rgbs).
    cleaned = [[int(r), int(g), int(b)] for r, g, b in rgbs]
    engine_palette = [[0, 0, 0]] + cleaned
    return JsonResponse({
        'palette': engine_palette,
        'source':  source,
    })


@login_required
def walk_png(request, slug):
    """Render a saved walk at a chosen step at high resolution.

    Query: ?step=N (default = last), ?w=, ?h= (default 1024).  The
    walk's gene supplies (cx, cy, span); iter is auto-tuned from
    span unless ?iter= is provided.
    """
    walk = get_object_or_404(Walk, slug=slug)
    gene = walk.gene_json or []
    if not gene:
        return HttpResponse('walk gene empty', status=400)
    step = _int(request, 'step', len(gene) - 1, lo=0, hi=len(gene) - 1)
    g = gene[step]
    w = _int(request, 'w', 1024, lo=16, hi=2000)
    h = _int(request, 'h', 1024, lo=16, hi=2000)
    iter_cap = _int(request, 'iter', 0, lo=0, hi=8192)
    iter_cap = iter_cap or int(g.get('iter') or renderer.auto_iter(g['span']))
    png = renderer.render_mandelbrot_png(
        float(g['cx']), float(g['cy']), float(g['span']),
        w, h, iter_cap=iter_cap,
    )
    resp = HttpResponse(png, content_type='image/png')
    resp['Cache-Control'] = 'public, max-age=86400'
    return resp
