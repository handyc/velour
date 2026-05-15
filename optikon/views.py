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
    palette = illusion.PALETTE
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
    # Preview parameters: a screen-friendly grid size (smaller than
    # A4 so it loads fast and reads well in a browser).
    grid_w = max(8, min(int(request.GET.get('grid_w', 28)), 80))
    grid_h = max(8, min(int(request.GET.get('grid_h', 22)), 80))
    side_mm = float(request.GET.get('side_mm', 6.0))
    page = gp_svg.Page(w_mm=grid_w * side_mm * 2.0,
                       h_mm=grid_h * side_mm * 1.6,
                       margin_mm=2.0)
    svg_str = _render_illusion_svg(illusion, params,
                                    grid_w=grid_w, grid_h=grid_h,
                                    page=page, side_mm=side_mm)
    # Hand-off to gridprint: same illusion params + a hex side in mm
    # that's smaller than the on-screen preview so the printed page
    # fills with rich detail.
    print_qs = urlencode({'from_optikon': illusion.SLUG,
                           'cell':         4.0,
                           **params})
    raw_qs = urlencode({**params, 'side_mm': 6.0})
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
    qs = urlencode({'pattern': 'optikon',
                     'from_optikon': illusion.SLUG,
                     'cell': request.GET.get('cell', 4.0),
                     **params})
    from django.shortcuts import redirect
    return redirect(f'/gridprint/print/?{qs}')
