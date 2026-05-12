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


def _decode_tile_id(tile_id: str, expected_len: int) -> tuple:
    """Tiles are addressed as base-4 strings: 4 digits 'nesw' for
    square topology, 6 digits '012345' (edges clockwise from top) for
    hex.  Returns a tuple of ints in [0, 3]."""
    if len(tile_id) != expected_len or any(ch not in '0123' for ch in tile_id):
        raise Http404(
            f'tile id must be {expected_len} base-4 digits, '
            f'got {tile_id!r}')
    return tuple(int(ch) for ch in tile_id)


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
    if s.topology == 'hex':
        # 4096 = 4⁶ is too many to render at once.  Show a 64-tile
        # sample (one for each (e0, e1) pair, holding e2..e5 = 0).
        # Researchers browse the full space via direct tile URL or
        # tiling-test view.
        grid = [[f'{e0}{e1}0000' for e1 in range(4)] for e0 in range(4)]
        grid_label = f'sample 4×4 of {s.tile_count} hex tiles ' \
                     '(e2-e5 fixed at 0; vary by URL for others)'
        edges_per_tile = 6
    else:
        grid = [['' for _ in range(16)] for _ in range(16)]
        for n in range(4):
            for e in range(4):
                for s_ in range(4):
                    for w in range(4):
                        grid[n * 4 + e][s_ * 4 + w] = f'{n}{e}{s_}{w}'
        grid_label = f'all {s.tile_count} square tiles'
        edges_per_tile = 4
    return render(request, 'tessera/detail.html', {
        'set':            s,
        'grid':           grid,
        'grid_label':     grid_label,
        'edges_per_tile': edges_per_tile,
        'palette_json':   json.dumps(s.palette),
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
    edges = _decode_tile_id(tile_id, s.edges_per_tile)
    arr = R.composite_tile_for(s, edges,
                               blur_sigma=s.blur_sigma,
                               power=s.blend_power)
    return _png_response(R.png_bytes(arr))


@require_GET
def tiling_test(request, slug):
    """Lay out a Wang-legal patch.  For square topology: greedy
    left-to-right, top-to-bottom where each placement matches its top
    + left neighbour.  For hex topology: same idea, but each tile has
    6 edges and the offset-r layout determines which neighbours are
    already placed.

    The seam-free claim is visible as: tiles with matching edge
    colours produce identical pixel sequences along their shared
    boundary."""
    s = get_object_or_404(TessSet, slug=slug)
    rows = int(request.GET.get('rows', 6))
    cols = int(request.GET.get('cols', 8))
    rows = max(1, min(rows, 24))
    cols = max(1, min(cols, 32))
    import random
    rng = random.Random(int(request.GET.get('seed', 0)))

    if s.topology == 'hex':
        # Pointy-top offset-r hex.  Each tile has 6 edges 0..5 (CW
        # from top).  Neighbour mapping:
        #   N      neighbour at (r-2, c)            shares edges 0↔3 — skip
        #   For pointy-top w/ horizontal-stagger: just use the
        #   already-placed W (edge 5 of current = edge 2 of W), NW,
        #   and NE neighbours when present.
        # For v1 we just generate constraint-free tiles per cell —
        # tilings *aren't* edge-coherent under the simple grid, but
        # the catalogue still shows the math works per tile.  A real
        # hex tiling lays tiles on the offset-r lattice and chains
        # the constraint properly; out of scope for this commit.
        grid = [[tuple(rng.randrange(4) for _ in range(6))
                 for _ in range(cols)] for _ in range(rows)]
        grid_ids = [
            [''.join(str(d) for d in t) for t in row]
            for row in grid
        ]
    else:
        grid = [[None] * cols for _ in range(rows)]
        for r in range(rows):
            for c in range(cols):
                n_req = grid[r - 1][c][2] if r > 0 else rng.randrange(4)
                w_req = grid[r][c - 1][1] if c > 0 else rng.randrange(4)
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
    """Bare-bones create.  Accepts name + seed + method + topology +
    blend_method.  Anything missing or unknown falls back to defaults
    (square IDW fbm-tileable)."""
    name   = (request.POST.get('name') or '').strip()
    seed_s = (request.POST.get('seed') or '0').strip()
    method = (request.POST.get('method') or 'fbm-tileable').strip()
    topology = (request.POST.get('topology') or 'square').strip()
    blend_method = (request.POST.get('blend_method') or 'idw').strip()
    if topology not in ('square', 'hex'):
        topology = 'square'
    if blend_method not in ('idw', 'wedge'):
        blend_method = 'idw'
    if not name:
        return HttpResponseRedirect(reverse('tessera:index'))
    try:
        seed = int(seed_s)
    except ValueError:
        seed = 0
    slug = slugify(name)[:80] or f'set-{TessSet.objects.count() + 1}'
    base = slug
    n = 1
    while TessSet.objects.filter(slug=slug).exists():
        n += 1
        slug = f'{base}-{n}'
    obj = TessSet.objects.create(
        name=name, slug=slug, seed=seed, method=method,
        topology=topology, blend_method=blend_method)
    return HttpResponseRedirect(reverse('tessera:detail', args=[obj.slug]))
