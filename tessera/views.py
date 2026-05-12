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
from django.views.decorators.http import (
    require_GET, require_POST, require_http_methods)

from .models import TessSet
from . import render as R
from . import bake_ca as BCA


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
    # ETag from the payload + must-revalidate so browsers refresh
    # when the render code changes.  The previous `immutable` header
    # made existing browsers serve stale PNGs from before render
    # bugfixes — switching to revalidation costs one conditional GET
    # per tile but actually delivers updates.
    import hashlib
    etag = hashlib.md5(payload).hexdigest()
    resp = HttpResponse(payload, content_type='image/png')
    resp['Cache-Control'] = 'public, max-age=60, must-revalidate'
    resp['ETag'] = f'"{etag}"'
    return resp


@require_GET
def index(request):
    sets = TessSet.objects.all()
    return render(request, 'tessera/index.html', {
        'sets': sets,
        'upload_slots': list(zip('abcd', '0123')),
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
    palette_view = []
    for i in range(4):
        rgb = s.palette[i] if i < len(s.palette) else [128, 128, 128]
        palette_view.append({
            'idx': i,
            'rgb': rgb,
            'hex': '#{:02x}{:02x}{:02x}'.format(*[max(0, min(255, int(c))) for c in rgb]),
        })
    return render(request, 'tessera/detail.html', {
        'set':              s,
        'grid':             grid,
        'grid_label':       grid_label,
        'edges_per_tile':   edges_per_tile,
        'palette_json':     json.dumps(s.palette),
        'palette_view':     palette_view,
        'is_upload_method': s.method in ('upload-4', 'upload-1-palette'),
        'render_version':   R.RENDER_VERSION,
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
    # Default grid size depends on topology: hex defaults to 8×8 so
    # the offset-r tessellation is visible at a glance; square keeps
    # its long-form 6×8 default.
    default_rows = 8 if s.topology == 'hex' else 6
    default_cols = 8
    rows = int(request.GET.get('rows', default_rows))
    cols = int(request.GET.get('cols', default_cols))
    rows = max(1, min(rows, 24))
    cols = max(1, min(cols, 32))
    import random
    rng = random.Random(int(request.GET.get('seed', 0)))

    if s.topology == 'hex':
        # Pointy-top offset-r hex.  Edges are 0..5 clockwise from the
        # top (0 upper-right slope, 1 right vertical, 2 lower-right
        # slope, 3 lower-left slope, 4 left vertical, 5 upper-left
        # slope).  Wang correspondence between neighbours: edge i of
        # any tile = edge (i+3)%6 of its neighbour across that edge.
        #
        # Offset-r layout (odd rows shifted right by ROW_SHIFT).  For
        # tile (r, c) with shift = r%2, the row-above neighbours are
        # at (r-1, c-1+shift) [up-left] and (r-1, c+shift) [up-right].
        # Scan order is row by row, left to right, so already-placed
        # neighbours are: left (r, c-1), up-left, and up-right.  Edges
        # 1, 2, 3 (right vertical, lower-right slope, lower-left slope)
        # remain free — they constrain the not-yet-placed right /
        # down-right / down-left neighbours.
        grid = [[None] * cols for _ in range(rows)]
        for r in range(rows):
            shift = r % 2
            for c in range(cols):
                edges = [rng.randrange(4) for _ in range(6)]
                if c > 0:                                    # left
                    edges[4] = grid[r][c - 1][1]
                ul_c = c - 1 + shift
                if r > 0 and 0 <= ul_c < cols:               # up-left
                    edges[5] = grid[r - 1][ul_c][2]
                ur_c = c + shift
                if r > 0 and 0 <= ur_c < cols:               # up-right
                    edges[0] = grid[r - 1][ur_c][3]
                grid[r][c] = tuple(edges)
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
    placements = None
    container_w = container_h = 0
    if s.topology == 'hex':
        # Pointy-top offset-r tessellation.  Tile bounding box is
        # 64×64 with the inscribed hex centred — the template uses
        # clip-path to clip each <img> to just the hex shape, so
        # adjacent bounding boxes can safely overlap.  Step sizes are
        # slightly larger than the ideal (2·inradius ≈ 55.4, 1.5·R =
        # 48) so a ~1 px magenta seam shows through the container
        # background.
        TILE_PX = 64
        H_STEP, V_STEP, ROW_SHIFT = 56, 49, 28
        placements = []
        for r_i, row in enumerate(grid_ids):
            for c_i, tid in enumerate(row):
                x = c_i * H_STEP + (ROW_SHIFT if r_i % 2 else 0)
                y = r_i * V_STEP
                placements.append({'left': x, 'top': y, 'tid': tid})
        container_w = max(p['left'] for p in placements) + TILE_PX
        container_h = max(p['top'] for p in placements) + TILE_PX
    return render(request, 'tessera/tiling.html', {
        'set': s,
        'grid_ids': grid_ids,
        'rows': rows, 'cols': cols,
        'placements': placements,
        'container_w': container_w,
        'container_h': container_h,
        'seed': request.GET.get('seed', '0'),
        'render_version': R.RENDER_VERSION,
    })


_VALID_METHODS = {m[0] for m in TessSet.METHOD_CHOICES}


@require_http_methods(['GET', 'POST'])
def bake_ca(request):
    """Upload an RGBA image, get back a ranked catalogue of hex-flower
    CA-rule keys + averaged palettes found in the image."""
    result = None
    if request.method == 'POST':
        f = request.FILES.get('image')
        max_side = max(32, min(int(request.POST.get('max_side', 160) or 160), 320))
        top_n = max(4, min(int(request.POST.get('top_n', 36) or 36), 256))
        palette_method = (request.POST.get('palette_method') or 'median-cut').strip()
        if palette_method not in ('median-cut', 'kmeans', 'rule-centres'):
            palette_method = 'median-cut'
        if f:
            from PIL import Image
            import numpy as np
            img = Image.open(f).convert('RGBA')
            if max(img.size) > max_side:
                img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            arr = np.asarray(img, dtype=np.uint8)
            rules = BCA.bake_rules(arr)
            ranked = sorted(rules.items(), key=lambda kv: -kv[1]['count'])
            top = []
            for key, info in ranked[:top_n]:
                pal = info['palette']
                neighbour_rgbas = [pal[lab] for lab in key]
                svg = BCA.hex_flower_svg(pal[0], neighbour_rgbas, labels=key)
                top.append({
                    'key_str':     ''.join(str(l) for l in key),
                    'count':       info['count'],
                    'svg':         svg,
                    'palette_hex': ['#{:02x}{:02x}{:02x}'.format(
                                        *pal[i, :3]) for i in range(4)],
                })
            total_pixels = (arr.shape[0] - 2) * (arr.shape[1] - 2)
            # The "Wang as bone, CA as breath" payload — the same
            # baked rules collapsed into one global 4-colour palette
            # and a complete 4096-entry CA table (Hamming-nearest
            # fill for 6-tuples the image never produced).
            # Palette source: by default extract directly from the
            # image (median-cut), which matches what the viewer's eye
            # picks as the dominant colours.  Fallback: the legacy
            # k-means-on-rule-centres method, which clusters in rule
            # space rather than image space (over-represents textured
            # regions, under-represents flat dominant colour).
            if palette_method in ('median-cut', 'kmeans'):
                palette_override = BCA.palette_from_image(
                    img, k=4, method=palette_method)
                # Force alpha=255 so downstream uses a clean (k,4) RGBA.
            else:
                palette_override = None
            gp, table = BCA.build_global_palette_and_table(
                rules, k=4, palette_override=palette_override)
            # Quantise the input image down to the CA's grid resolution
            # and label each pixel with the nearest global-palette entry.
            # This gives the canvas a meaningful starting state — the
            # image itself — so we can watch the rule preserve or
            # dissolve it rather than starting from random noise.
            GRID = 64
            small = img.resize((GRID, GRID), Image.Resampling.LANCZOS)
            small_arr = np.asarray(small.convert('RGBA'),
                                   dtype=np.uint8)
            diffs = (small_arr[:, :, None, :].astype(np.int32)
                     - gp[None, None, :, :].astype(np.int32))
            qdists = np.sum(diffs ** 2, axis=-1)        # (G, G, 4)
            image_state = np.argmin(qdists, axis=-1)    # (G, G)
            import json
            ca_payload = {
                'palette': [[int(c) for c in gp[i, :3]] for i in range(4)],
                'table':   [int(v) for v in table.tolist()],
                'grid':    GRID,
                'image_state': [int(v) for v in image_state.ravel().tolist()],
            }
            result = {
                'top':          top,
                'total_rules':  len(rules),
                'total_pixels': total_pixels,
                'image_size':   f'{img.width}×{img.height}',
                'top_n':        top_n,
                'max_side':     max_side,
                'palette_method': palette_method,
                'ca_payload':   json.dumps(ca_payload),
                'ca_palette_hex': ['#{:02x}{:02x}{:02x}'.format(*gp[i, :3])
                                   for i in range(4)],
            }
    return render(request, 'tessera/bake_ca.html', {'result': result})


@require_POST
def swap_source(request, slug, color_idx):
    """Replace one colour's source image with an uploaded file.
    Only meaningful for upload-* methods; for procedural methods,
    use swap_palette instead."""
    s = get_object_or_404(TessSet, slug=slug)
    if color_idx < 0 or color_idx > 3:
        raise Http404('color_idx out of range')
    f = request.FILES.get('file')
    if not f:
        return HttpResponseRedirect(reverse('tessera:detail', args=[s.slug]))
    if s.method == 'upload-1-palette' and color_idx != 0:
        # Sources 1..3 are derived; swapping them doesn't make sense.
        return HttpResponseRedirect(reverse('tessera:detail', args=[s.slug]))
    slot_letter = 'abcd'[color_idx]
    setattr(s, f'upload_{slot_letter}', f)
    s.save()
    return HttpResponseRedirect(reverse('tessera:detail', args=[s.slug]))


@require_POST
def swap_palette(request, slug, color_idx):
    """Update one palette anchor RGB.  Only meaningful for procedural
    methods (fbm-tileable, domain-warp, hex-ca); upload methods
    ignore the palette."""
    s = get_object_or_404(TessSet, slug=slug)
    if color_idx < 0 or color_idx > 3:
        raise Http404('color_idx out of range')
    rgb = (request.POST.get('rgb') or '').strip()
    # Expect "#rrggbb" from <input type="color">.
    if len(rgb) == 7 and rgb.startswith('#'):
        try:
            r = int(rgb[1:3], 16); g = int(rgb[3:5], 16); b = int(rgb[5:7], 16)
        except ValueError:
            return HttpResponseRedirect(reverse('tessera:detail', args=[s.slug]))
        palette = list(s.palette)
        # Pad to 4 entries if for some reason it's short.
        while len(palette) < 4:
            palette.append([128, 128, 128])
        palette[color_idx] = [r, g, b]
        s.palette = palette
        s.save()
    return HttpResponseRedirect(reverse('tessera:detail', args=[s.slug]))


@require_POST
def create_set(request):
    """Bare-bones create.  Accepts name + seed + method + topology +
    blend_method, plus optional file uploads for the upload-* methods.
    Anything missing or unknown falls back to defaults (square IDW
    fbm-tileable)."""
    name   = (request.POST.get('name') or '').strip()
    seed_s = (request.POST.get('seed') or '0').strip()
    method = (request.POST.get('method') or 'fbm-tileable').strip()
    topology = (request.POST.get('topology') or 'square').strip()
    blend_method = (request.POST.get('blend_method') or 'idw').strip()
    if method not in _VALID_METHODS:
        method = 'fbm-tileable'
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
    obj = TessSet(
        name=name, slug=slug, seed=seed, method=method,
        topology=topology, blend_method=blend_method)
    # File uploads — only attach when the chosen method actually
    # consumes them so we don't litter MEDIA_ROOT with orphans.
    if method == 'upload-4':
        # Prefer the bulk multi-select field; fall back to per-slot
        # legacy fields for backward-compat.
        bulk = request.FILES.getlist('upload_files')[:4]
        for i, letter in enumerate(('a', 'b', 'c', 'd')):
            f = bulk[i] if i < len(bulk) else request.FILES.get(f'upload_{letter}')
            if f:
                setattr(obj, f'upload_{letter}', f)
    elif method == 'upload-1-palette':
        f = request.FILES.get('upload_a')
        if f:
            obj.upload_a = f
    obj.save()
    return HttpResponseRedirect(reverse('tessera:detail', args=[obj.slug]))
