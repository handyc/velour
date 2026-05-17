"""Optikon views — illusion catalogue + per-illusion playground.

The playground page renders the illusion as an inline SVG using
gridprint's hex_grid() with a fill array.  Print handoff calls the
same render at A4 dimensions.
"""

from __future__ import annotations
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, Http404
from django.shortcuts import render

from gridprint import svg as gp_svg

from . import illusions as ill


def _resolve_params(illusion, request):
    raw = {}
    for p in illusion.PARAMS:
        if p.key in request.GET:
            raw[p.key] = request.GET[p.key]
    return ill.parse_params(illusion.PARAMS, raw)


def _render_illusion_svg(illusion, params, *,
                          grid_w: int, grid_h: int,
                          page: gp_svg.Page,
                          side_mm: float) -> str:
    """Run the illusion → 2D color-index array → CSS-color array →
    gridprint hex_grid SVG.  Pure: same inputs always → same SVG."""
    indices = illusion.render(grid_w, grid_h, params)
    palette = (illusion.get_palette(params)
               if hasattr(illusion, 'get_palette')
               else illusion.PALETTE)
    fill = [
        [palette[ix % len(palette)] for ix in row]
        for row in indices
    ]
    style = gp_svg.Style(color='#222222', width_mm=0.05, alpha=1.0)
    return gp_svg.hex_grid(page=page, side_mm=side_mm, style=style,
                            pointy_top=True, fill=fill,
                            with_dimensions=False)


@login_required
def index(request):
    return render(request, 'optikon/index.html', {
        'illusions': ill.all_illusions(),
    })


@login_required
def detail(request, slug):
    illusion = ill.get(slug)
    if illusion is None: raise Http404(f'unknown illusion {slug!r}')
    params = _resolve_params(illusion, request)
    # Per-illusion defaults: an autostereogram needs many small
    # cells; a Café-wall reads better at 6 mm hexes.
    def_cell = float(getattr(illusion, 'DEFAULT_CELL_MM', 6.0))
    def_gw   = int(getattr(illusion, 'DEFAULT_GRID_W', 28))
    def_gh   = int(getattr(illusion, 'DEFAULT_GRID_H', 22))
    grid_w   = max(8, min(int(request.GET.get('grid_w', def_gw)), 200))
    grid_h   = max(8, min(int(request.GET.get('grid_h', def_gh)), 200))
    side_mm  = float(request.GET.get('side_mm', def_cell))
    page = gp_svg.Page(w_mm=grid_w * side_mm * 2.0,
                       h_mm=grid_h * side_mm * 1.6,
                       margin_mm=2.0)
    svg_str = _render_illusion_svg(illusion, params,
                                    grid_w=grid_w, grid_h=grid_h,
                                    page=page, side_mm=side_mm)
    # Hand-off to gridprint: pass the illusion's small print default
    # so the A4 fills with detail without the user having to retype it.
    print_cell = float(getattr(illusion, 'DEFAULT_CELL_MM', 4.0))
    print_qs = urlencode({'from_optikon': illusion.SLUG,
                           'cell':         print_cell,
                           **params})
    raw_qs = urlencode({**params, 'side_mm': side_mm})
    field_rows = []
    for p in illusion.PARAMS:
        field_rows.append({**p.as_dict(), 'value': params.get(p.key, p.default)})
    return render(request, 'optikon/detail.html', {
        'illusion':   illusion,
        'params':     params,
        'field_rows': field_rows,
        'grid_w':     grid_w,
        'grid_h':     grid_h,
        'side_mm':    side_mm,
        'svg':        svg_str,
        'print_qs':   print_qs,
        'raw_qs':     raw_qs,
    })


@login_required
def svg(request, slug):
    """Serve just the SVG (useful for embedding / debugging)."""
    illusion = ill.get(slug)
    if illusion is None: raise Http404(f'unknown illusion {slug!r}')
    params = _resolve_params(illusion, request)
    grid_w = max(8, min(int(request.GET.get('grid_w', 28)), 80))
    grid_h = max(8, min(int(request.GET.get('grid_h', 22)), 80))
    side_mm = float(request.GET.get('side_mm', 6.0))
    page = gp_svg.Page(w_mm=grid_w * side_mm * 2.0,
                       h_mm=grid_h * side_mm * 1.6,
                       margin_mm=2.0)
    body = _render_illusion_svg(illusion, params,
                                 grid_w=grid_w, grid_h=grid_h,
                                 page=page, side_mm=side_mm)
    return HttpResponse(body, content_type='image/svg+xml')


from django.views.decorators.http import require_POST
from django.http import JsonResponse
from . import depth_cache


@login_required
def autostereogram_decode(request):
    """Upload an autostereogram raster (PNG/JPEG) and recover the
    depth map driving it.  Works on stereograms exported by this
    program or anywhere else, since the algorithm is the standard
    autocorrelation-based SIRDS decode.

    GET: render the upload form (with last-decoded result if cached).
    POST: decode the uploaded image, store the result PNGs as base64
    in the session, redirect back to GET so a refresh doesn't repost.
    """
    import base64
    from .illusions.autostereogram import decode_depth

    if request.method == 'POST':
        f = request.FILES.get('image')
        if not f:
            return render(request, 'optikon/autostereogram_decode.html',
                            {'error': 'no image file uploaded'})
        if f.size > 16 * 1024 * 1024:
            return render(request, 'optikon/autostereogram_decode.html',
                            {'error': 'image too large (>16 MB)'})
        try:
            max_dim = max(64, min(1024,
                                      int(request.POST.get('max_dim', 640))))
        except (TypeError, ValueError):
            max_dim = 640
        smooth = request.POST.get('smooth', '1') == '1'

        try:
            result = decode_depth(f.read(), max_dim=max_dim, smooth=smooth)
        except Exception as exc:  # noqa: BLE001
            return render(request, 'optikon/autostereogram_decode.html', {
                'error': f'{type(exc).__name__}: {exc}',
            })

        ctx = {
            'depth_b64':  base64.b64encode(result['depth_png']).decode('ascii'),
            'orig_b64':   base64.b64encode(result['orig_png']).decode('ascii'),
            'period':     result['period'],
            'max_shift':  result['max_shift'],
            'width':      result['width'],
            'height':     result['height'],
            'depth_min':  result['depth_min'],
            'depth_max':  result['depth_max'],
            'max_dim':    max_dim,
            'smooth':     smooth,
            'filename':   f.name,
        }
        return render(request, 'optikon/autostereogram_decode.html', ctx)

    return render(request, 'optikon/autostereogram_decode.html', {})


@login_required
@require_POST
def depth_upload(request):
    """Accept an image file, convert to a discretised depth map,
    cache it under MEDIA_ROOT/optikon/depth/<sha>.json, return the
    sha so the caller can pass ?depth_image_hash=<sha> in subsequent
    render URLs.

    Form fields:
      image      — the file (jpg/png/gif/webp/anything PIL handles)
      n_levels   — how many distinct depth levels (2..8, default 4)
      invert     — '1' to flip light/dark
      max_dim    — max greyscale dimension (default 128, capped at 256)
    """
    f = request.FILES.get('image')
    if not f:
        return JsonResponse({'ok': False, 'error': 'no image file'},
                             status=400)
    if f.size > 8 * 1024 * 1024:
        return JsonResponse({'ok': False, 'error': 'image too large (>8 MB)'},
                             status=400)
    try:
        n_levels = int(request.POST.get('n_levels', 4))
    except ValueError:
        n_levels = 4
    try:
        max_dim  = int(request.POST.get('max_dim',  128))
    except ValueError:
        max_dim = 128
    max_dim = max(16, min(256, max_dim))
    invert   = request.POST.get('invert') == '1'

    try:
        meta = depth_cache.store(f.read(),
                                  max_dim=max_dim,
                                  n_levels=n_levels,
                                  invert=invert)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({'ok': False,
                              'error': f'{type(exc).__name__}: {exc}'},
                             status=400)
    return JsonResponse({'ok': True, **meta})


@login_required
def print_view(request, slug):
    """Hand off to gridprint's standard print flow, which renders the
    illusion at A4 by calling back into optikon via from_optikon=...
    and reuses gridprint's iframe-based Print + Download SVG buttons.

    Kept as a redirect so old bookmarks of /optikon/<slug>/print keep
    working; new links go straight to /gridprint/print/.
    """
    illusion = ill.get(slug)
    if illusion is None: raise Http404(f'unknown illusion {slug!r}')
    params = _resolve_params(illusion, request)
    cell = request.GET.get('cell',
                            getattr(illusion, 'DEFAULT_CELL_MM', 4.0))
    handoff = {'pattern': 'optikon',
                'from_optikon': illusion.SLUG,
                'cell': cell,
                **params}
    # Per-illusion landscape default — the autostereogram needs a wide
    # page so the eye-divergence period has room to repeat across A4.
    if getattr(illusion, 'DEFAULT_PRINT_LANDSCAPE', False) \
            and 'landscape' not in request.GET:
        handoff['landscape'] = '1'
    qs = urlencode(handoff)
    from django.shortcuts import redirect
    return redirect(f'/gridprint/print/?{qs}')
