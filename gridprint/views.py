"""Gridprint views — render an A4 SVG of tessellated graph paper.

The page itself is a small form + an iframe pointing at /gridprint/grid.svg
with the form values as query params. Print + Download SVG actions both
just hit the same SVG URL.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_sameorigin

from . import ca_fill, svg


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
def index(request):
    """Form + iframe SVG preview."""
    return render(request, 'gridprint/index.html', {
        'patterns':   list(svg.PATTERNS.items()),
        'a4_w':       svg.A4_W,
        'a4_h':       svg.A4_H,
    })


@login_required
@xframe_options_sameorigin
def grid_svg(request):
    """Pure SVG endpoint, parameterised by query string.

        ?pattern=hex_pointy        (square|hex_pointy|hex_flat|triangle|rhombus)
        ?cell=8.0                  (mm)
        ?color=%23888888           (CSS hex)
        ?alpha=1.0                 (0..1)
        ?width=0.20                (mm — stroke width)
        ?margin=10                 (mm)
        ?landscape=1               (portrait by default)
        ?border=1                  (faint dashed printable-area border)
        ?from_automaton=<slug>     (fill cells from a saved sim)
        ?from_taxon=<rule_slug>    (run a rule for ?ticks=N steps and fill)
        ?ticks=24                  (only used with from_taxon)
        ?fill_alpha=0.85
    """
    pattern = (request.GET.get('pattern') or 'hex_pointy').strip()
    if pattern not in svg.PATTERNS:
        pattern = 'hex_pointy'
    cell = _float(request, 'cell', 8.0, lo=2.0, hi=80.0)
    margin = _float(request, 'margin', 10.0, lo=0.0, hi=40.0)
    color = (request.GET.get('color') or '#888888').strip() or '#888888'
    alpha = _float(request, 'alpha', 1.0, lo=0.0, hi=1.0)
    width = _float(request, 'width', 0.20, lo=0.05, hi=2.5)
    fill_alpha = _float(request, 'fill_alpha', 0.85, lo=0.0, hi=1.0)
    landscape = request.GET.get('landscape') == '1'
    border = request.GET.get('border') == '1'

    page = svg.Page(
        w_mm=svg.A4_H if landscape else svg.A4_W,
        h_mm=svg.A4_W if landscape else svg.A4_H,
        margin_mm=margin,
    )
    style = svg.Style(color=color, width_mm=width, alpha=alpha,
                      fill_alpha=fill_alpha)

    fill = None
    fill_meta = {}
    sim_slug = (request.GET.get('from_automaton') or '').strip()
    rule_slug = (request.GET.get('from_taxon') or '').strip()
    try:
        if sim_slug:
            fill, fill_meta = ca_fill.from_automaton(sim_slug)
        elif rule_slug:
            ticks = _int(request, 'ticks', 24, lo=0, hi=2000)
            w = _int(request, 'fw', 16, lo=2, hi=128)
            h = _int(request, 'fh', 16, lo=2, hi=128)
            fill, fill_meta = ca_fill.from_taxon(
                rule_slug, width=w, height=h, ticks=ticks)
    except ValueError as exc:
        # Render the requested pattern without fill, surface the error
        # in a small footer text inside the SVG.
        body = svg.render(pattern, page=page, cell_mm=cell, style=style,
                          fill=None)
        body = body.replace(
            '</svg>',
            f'<text x="{margin}" y="{page.h_mm - 1}" '
            f'font-family="ui-monospace,monospace" font-size="3" '
            f'fill="#c04a4a">CA fill error: {exc}</text></svg>',
        )
        # (rebuild with border if requested)
        return HttpResponse(body, content_type='image/svg+xml; charset=utf-8')

    body = svg.render(pattern, page=page, cell_mm=cell, style=style,
                      fill=fill)
    if border:
        body = body.replace(
            '</svg>',
            f'<rect x="{page.left}" y="{page.top}" '
            f'width="{page.inner_w}" height="{page.inner_h}" '
            f'fill="none" stroke="#cccccc" stroke-width="0.1" '
            f'stroke-dasharray="0.6 0.6" /></svg>',
        )
    if fill_meta:
        label = (
            f'{fill_meta["source"]}: {fill_meta["name"]}'
            + (f'  ·  tick {fill_meta["tick"]}'
               if 'tick' in fill_meta else '')
        )
        body = body.replace(
            '</svg>',
            f'<text x="{margin}" y="{page.h_mm - 1}" '
            f'font-family="ui-monospace,monospace" font-size="2.2" '
            f'fill="#999">{label}</text></svg>',
        )

    resp = HttpResponse(body, content_type='image/svg+xml; charset=utf-8')
    if request.GET.get('download') == '1':
        resp['Content-Disposition'] = (
            f'attachment; filename="gridprint-{pattern}.svg"'
        )
    return resp
