"""Tilesmith views — list, create, edit, save (JSON API), delete."""

from __future__ import annotations

import json

from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .models import TileSpec


def index(request):
    return render(request, 'tilesmith/index.html', {
        'specs':   TileSpec.objects.filter(is_preset=False),
        'presets': TileSpec.objects.filter(is_preset=True),
    })


def create(request):
    """Make a new TileSpec.  GET shows a tiny form; POST creates and
    redirects to its edit page.  Optionally clones from a preset."""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip() or 'Untitled tile'
        base_slug = slugify(name) or 'tile'
        slug = base_slug
        n = 1
        while TileSpec.objects.filter(slug=slug).exists():
            n += 1
            slug = f'{base_slug}-{n}'
        clone_from = request.POST.get('clone_from', '').strip()
        edges = [[] for _ in range(6)]
        base_w, base_h = 64, 64
        if clone_from:
            src = TileSpec.objects.filter(slug=clone_from).first()
            if src:
                edges = src.edges_json
                base_w = src.base_w
                base_h = src.base_h
        spec = TileSpec.objects.create(
            slug=slug, name=name,
            base_w=base_w, base_h=base_h,
            edges_json=edges,
        )
        return redirect('tilesmith:edit', slug=spec.slug)
    return render(request, 'tilesmith/new.html', {
        'presets': TileSpec.objects.filter(is_preset=True),
    })


def edit(request, slug):
    spec = get_object_or_404(TileSpec, slug=slug)
    return render(request, 'tilesmith/edit.html', {
        'spec':   spec,
        'edges_json': json.dumps(spec.edges_json),
        'presets': TileSpec.objects.filter(is_preset=True),
    })


@require_POST
def save(request, slug):
    """Persist edges + name + dims.  Body: JSON {name, base_w, base_h,
    edges}.  Presets reject saves to keep the starter shapes clean."""
    spec = get_object_or_404(TileSpec, slug=slug)
    if spec.is_preset:
        return JsonResponse(
            {'error': 'preset is read-only; clone via "New" first'},
            status=403)
    try:
        body = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return HttpResponseBadRequest('invalid JSON')
    if 'name' in body:
        spec.name = (body['name'] or '').strip()[:160] or spec.name
    if 'base_w' in body:
        spec.base_w = max(8, min(1024, int(body['base_w'])))
    if 'base_h' in body:
        spec.base_h = max(8, min(1024, int(body['base_h'])))
    if 'edges' in body:
        edges = body['edges']
        if not (isinstance(edges, list) and len(edges) == 6
                and all(isinstance(e, list) for e in edges)):
            return HttpResponseBadRequest('edges must be 6-element list of lists')
        clean = []
        for e in edges:
            cleaned_e = []
            for cp in e:
                if not isinstance(cp, dict): continue
                p = float(cp.get('p', 0))
                off = float(cp.get('off', 0))
                if 0 < p < 1:
                    cleaned_e.append({'p': p, 'off': off})
            cleaned_e.sort(key=lambda c: c['p'])
            clean.append(cleaned_e)
        spec.edges_json = clean
    spec.save()
    return JsonResponse({'status': 'saved', 'updated_at': spec.updated_at.isoformat()})


@require_POST
def delete(request, slug):
    spec = get_object_or_404(TileSpec, slug=slug)
    if spec.is_preset:
        return JsonResponse({'error': 'preset cannot be deleted'}, status=403)
    spec.delete()
    return redirect('tilesmith:index')
