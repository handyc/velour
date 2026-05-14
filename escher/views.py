"""escher views.

The two interesting endpoints:

* ``render.svg`` — fully parameterised SVG generator.  Query string:

    ?group=p4m                              one of the 17 IUC slugs
    ?motif=stock&motif_slug=comma           stock motif by slug
    ?motif=spoeqi_component                 CA-frame motif
       &pact=<spoeqi-slug>&component=K&gen=N
    ?tile=30                                lattice spacing in mm
    ?w=210&h=297                            page size in mm
    ?margin=10                              page margin in mm
    ?cells=1                                overlay unit cells
    ?orbit=1                                highlight one full orbit
    ?embed=1                                drop the mm sizing for iframes

* ``groups.svg`` — compact 17-thumbnail reference sheet baked into
  one SVG for fast loading on /escher/.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, Http404
from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_sameorigin

from . import groups, motifs, svg, ca_motif, tilesmith_motif


# ─── helpers ─────────────────────────────────────────────────────────

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


def _resolve_motif(request) -> str:
    """Return the inner SVG body for the requested motif.  Falls back
    to the default stock motif if anything is unspecified or invalid.
    """
    kind = (request.GET.get('motif') or 'stock').strip()
    if kind == 'spoeqi_component':
        pact = (request.GET.get('pact') or '').strip()
        comp = _int(request, 'component', 0, lo=0, hi=63)
        gen  = _int(request, 'gen', 0, lo=0, hi=2000)
        if not pact:
            return ca_motif._placeholder_text('missing ?pact=<slug>')
        return ca_motif.spoeqi_component_motif(pact, comp, gen)
    if kind == 'tilesmith_tile':
        tile = (request.GET.get('tile_slug') or '').strip()
        if not tile:
            return tilesmith_motif._placeholder('missing ?tile_slug=<slug>')
        return tilesmith_motif.tilesmith_tile_motif(tile)
    # Stock — default branch.
    slug = (request.GET.get('motif_slug') or motifs.DEFAULT_MOTIF).strip()
    try:
        return motifs.get(slug).svg_body
    except KeyError:
        return motifs.get(motifs.DEFAULT_MOTIF).svg_body


# ─── views ───────────────────────────────────────────────────────────

@login_required
def index(request):
    """Reference page: a card for each of the 17 groups with a
    thumbnail rendered via groups.svg."""
    return render(request, 'escher/index.html', {
        'groups':  groups.GROUPS,
        'motifs':  list(motifs.STOCK.values()),
        'default_motif': motifs.DEFAULT_MOTIF,
    })


@login_required
@xframe_options_sameorigin
def groups_grid(request):
    """A single SVG containing thumbnails for all 17 groups laid out
    in a 5×4 grid.  Used as the index page's reference sheet.

    Query: ?motif=stock&motif_slug=<slug>  (same as render.svg)
    """
    body = _resolve_motif(request)
    cols = 5
    cell = 70.0
    label_h = 8.0
    gap = 4.0
    rows = (len(groups.GROUPS) + cols - 1) // cols

    parts = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {cols * (cell + gap) + gap} '
        f'{rows * (cell + label_h + gap) + gap}" '
        f'preserveAspectRatio="xMidYMid meet">'
        f'<rect x="0" y="0" width="100%" height="100%" fill="#0d1117" />'
    )
    # Inline symbol with the motif body — referenced once per group via use.
    parts.append(f'<defs><symbol id="motif" overflow="visible">{body}</symbol></defs>')

    for k, g in enumerate(groups.GROUPS):
        col = k % cols
        row = k // cols
        x = gap + col * (cell + gap)
        y = gap + row * (cell + label_h + gap)
        # Render the group's tiling directly (without using the symbol —
        # easier than nesting symbols within symbols across browsers).
        thumb = svg.render_thumbnail(g, body, size_mm=cell, tile_mm=cell / 4.0)
        # Strip the outer <svg ...> wrapper to nest as a <g> at (x, y).
        # The thumbnail uses viewBox 0 0 cell cell; we wrap in a translated <g>.
        inner = _strip_svg_root(thumb)
        parts.append(f'<g transform="translate({x}, {y})">{inner}</g>')
        parts.append(
            f'<text x="{x + cell / 2}" y="{y + cell + label_h - 1}" '
            f'font-family="ui-monospace,monospace" font-size="6" '
            f'fill="#cfa" text-anchor="middle">{g.slug}</text>'
        )

    parts.append('</svg>')
    return HttpResponse(''.join(parts),
                          content_type='image/svg+xml; charset=utf-8')


def _strip_svg_root(svg_text: str) -> str:
    """Remove the outer <svg…>…</svg> wrapping, keeping inner content.
    A minimal regex would be brittle; we use the substring positions
    of the first '>' after '<svg' and the final '</svg>'.
    """
    start = svg_text.find('<svg')
    if start < 0:
        return svg_text
    open_end = svg_text.find('>', start)
    close = svg_text.rfind('</svg>')
    if open_end < 0 or close < 0:
        return svg_text
    return svg_text[open_end + 1 : close]


@login_required
@xframe_options_sameorigin
def render_svg(request):
    """Fully-parameterised tiling endpoint."""
    slug = (request.GET.get('group') or 'p4m').strip()
    try:
        g = groups.get(slug)
    except KeyError:
        raise Http404(f'unknown wallpaper group: {slug}')

    landscape = request.GET.get('landscape') == '1'
    w_mm = _float(request, 'w', 297.0 if landscape else 210.0,
                    lo=20.0, hi=2000.0)
    h_mm = _float(request, 'h', 210.0 if landscape else 297.0,
                    lo=20.0, hi=2000.0)
    margin = _float(request, 'margin', 10.0, lo=0.0, hi=80.0)
    tile = _float(request, 'tile', 30.0, lo=4.0, hi=400.0)
    show_cells = request.GET.get('cells') == '1'
    show_orbit = request.GET.get('orbit') == '1'
    embed = request.GET.get('embed') == '1'

    cfg = svg.RenderConfig(
        tile_mm=tile, viewport_w_mm=w_mm, viewport_h_mm=h_mm,
        margin_mm=margin,
        show_unit_cell=show_cells, show_orbit=show_orbit,
    )
    motif_body = _resolve_motif(request)
    body = svg.render(g, motif_body, cfg, embed=embed)

    resp = HttpResponse(body, content_type='image/svg+xml; charset=utf-8')
    if request.GET.get('download') == '1':
        resp['Content-Disposition'] = (
            f'attachment; filename="escher-{g.slug}.svg"'
        )
    return resp


@login_required
def group_detail(request, slug):
    """Per-group page with the live preview iframe + controls."""
    try:
        g = groups.get(slug)
    except KeyError:
        raise Http404(f'unknown wallpaper group: {slug}')
    return render(request, 'escher/group_detail.html', {
        'group':   g,
        'groups':  groups.GROUPS,
        'motifs':  list(motifs.STOCK.values()),
        'default_motif': motifs.DEFAULT_MOTIF,
    })
