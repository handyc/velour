"""Tessera views — landing, detail (16×16 tile grid), tile + source
PNG endpoints, and a tiling-test view that lays out a Wang-legal
patch so the seamless edges can be inspected against each other.

PNGs are content-cached: the browser-side cache headers are the
"infinite" form (immutable; output is fully determined by URL +
TessSet content) so reloading the detail page never re-pays the
4×128² × 256 source/composite cost.  In-process Source cache lives
in render.get_sources_for; per-tile output is regenerated on each
hit (cheap, <30 ms) and could be disk-cached if needed later.
"""
from __future__ import annotations

import json

from django.http import HttpResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST

from .models import TessSet
from . import render as R


def _decode_tile_id(tile_id: str) -> tuple[int, int, int, int]:
    """Tiles are addressed as 4-digit base-4 strings 'nesw' so URLs
    are short + sortable.  Returns (n, e, s, w) ints in [0, 3]."""
    if len(tile_id) != 4 or any(ch not in '0123' for ch in tile_id):
        raise Http404('tile id must be 4 base-4 digits, e.g. 0123')
    return tuple(int(ch) for ch in tile_id)   # type: ignore[return-value]


def _png_response(payload: bytes) -> HttpResponse:
    resp = HttpResponse(payload, content_type='image/png')
    resp['Cache-Control'] = 'public, max-age=86400, immutable'
    return resp


@require_GET
def index(request):
    sets = TessSet.objects.all()
    return render(request, 'tessera/index.html', {
        'sets': sets,
    })


@require_GET
def detail(request, slug):
    s = get_object_or_404(TessSet, slug=slug)
    # All 256 tiles addressed as base-4 'nesw' strings, ordered so
    # the 16×16 grid groups by (n, e) in rows and (s, w) in columns.
    tiles = []
    for n in range(4):
        for e in range(4):
            row = []
            for s_ in range(4):
                for w in range(4):
                    row.append(f'{n}{e}{s_}{w}')
            tiles.append(row)
    # NOTE: that's 4 rows × 16 cols.  We want a 16×16, so flatten
    # differently: row index = (n * 4 + e), col index = (s * 4 + w).
    grid = [['' for _ in range(16)] for _ in range(16)]
    for n in range(4):
        for e in range(4):
            for s_ in range(4):
                for w in range(4):
                    grid[n * 4 + e][s_ * 4 + w] = f'{n}{e}{s_}{w}'
    return render(request, 'tessera/detail.html', {
        'set': s,
        'grid': grid,
        'palette_json': json.dumps(s.palette),
    })


@require_GET
def source_png(request, slug, color_idx: int):
    s = get_object_or_404(TessSet, slug=slug)
    if color_idx < 0 or color_idx > 3:
        raise Http404('color_idx out of range')
    sources = R.get_sources_for(s)
    return _png_response(R.png_bytes(sources[color_idx]))


@require_GET
def tile_png(request, slug, tile_id: str):
    s = get_object_or_404(TessSet, slug=slug)
    n, e, s_, w = _decode_tile_id(tile_id)
    sources = R.get_sources_for(s)
    arr = R.composite_tile(sources, n, e, s_, w,
                           power=s.blend_power,
                           blur_sigma=s.blur_sigma)
    return _png_response(R.png_bytes(arr))


@require_GET
def tiling_test(request, slug):
    """Lay out a Wang-legal patch (greedy left-to-right, top-to-
    bottom: each placement matches its top + left neighbour) so the
    seam-free claim can be eyeballed against real adjacencies."""
    s = get_object_or_404(TessSet, slug=slug)
    rows = int(request.GET.get('rows', 6))
    cols = int(request.GET.get('cols', 8))
    rows = max(1, min(rows, 24))
    cols = max(1, min(cols, 32))
    # Pick a starting tile by request seed so the layout is shareable
    # by URL.
    import random
    rng = random.Random(int(request.GET.get('seed', 0)))
    grid = [[None] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            n_req = grid[r - 1][c][2] if r > 0 else rng.randrange(4)
            w_req = grid[r][c - 1][1] if c > 0 else rng.randrange(4)
            # Free choice for remaining edges.
            e = rng.randrange(4)
            s_ = rng.randrange(4)
            grid[r][c] = (n_req, e, s_, w_req)
    grid_ids = [
        [f'{t[0]}{t[1]}{t[2]}{t[3]}' for t in row]
        for row in grid
    ]
    return render(request, 'tessera/tiling.html', {
        'set': s,
        'grid_ids': grid_ids,
        'rows': rows, 'cols': cols,
    })


@require_POST
def create_set(request):
    """Bare-bones create: accepts a name + seed (and optional
    method) and slugifies on save."""
    name   = (request.POST.get('name') or '').strip()
    seed_s = (request.POST.get('seed') or '0').strip()
    method = (request.POST.get('method') or 'fbm-tileable').strip()
    if not name:
        return HttpResponseRedirect(reverse('tessera:index'))
    try:
        seed = int(seed_s)
    except ValueError:
        seed = 0
    slug = slugify(name)[:80] or f'set-{TessSet.objects.count() + 1}'
    # Allow re-use of slug → bump.
    base = slug
    n = 1
    while TessSet.objects.filter(slug=slug).exists():
        n += 1
        slug = f'{base}-{n}'
    obj = TessSet.objects.create(
        name=name, slug=slug, seed=seed, method=method)
    return HttpResponseRedirect(reverse('tessera:detail', args=[obj.slug]))
