"""Gridprint views — render an A4 SVG of tessellated graph paper.

The page itself is a small form + an iframe pointing at /gridprint/grid.svg
with the form values as query params. Print + Download SVG actions both
just hit the same SVG URL.
"""
from __future__ import annotations

import math

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_sameorigin

from . import ca_fill, hex_flowers, svg


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

        Flower-dump mode (renders a hex-CA rule as 7→1 flowers, one
        configuration per cell, paged for A4):
        ?mode=flowers&from_spoeqi=<slug>
        ?mode=flowers&rule_hex=<32768-char-hex>
        ?fpage=0                   (page index, 0-based)
        ?fper=                     (flowers per page; omit to fill the page)
        ?fcentre=0..3              (filter to one centre colour)
    """
    if (request.GET.get('mode') or '').strip() == 'flowers':
        return _flowers_svg(request)

    pattern = (request.GET.get('pattern') or 'hex_pointy').strip()

    # Loupe mode: a saved Walk drives the pattern.  Triggered by
    # ?pattern=loupe or ?from_loupe=<walk_slug>.
    loupe_slug = (request.GET.get('from_loupe') or '').strip()
    if loupe_slug or pattern == 'loupe':
        return _loupe_svg(request, loupe_slug)

    # Escher mode: a wallpaper-group composition drives the pattern.
    # Triggered by ?pattern=escher or by ?from_escher=<group_slug>.
    # Checked first so its numeric ?tile= mm parameter doesn't get
    # mistaken for a tilesmith slug.
    escher_slug = (request.GET.get('from_escher') or '').strip()
    if escher_slug or pattern == 'escher':
        return _escher_svg(request, escher_slug)

    # Tilesmith mode: a TileSpec drives the pattern.  Triggered by
    # ?pattern=tilesmith or ?from_tilesmith=<slug>.
    tilesmith_slug = (request.GET.get('from_tilesmith') or '').strip()
    if tilesmith_slug or pattern == 'tilesmith':
        return _tilesmith_svg(request, tilesmith_slug)

    # Optikon mode: an optical-illusion slug drives the fill.
    # Triggered by ?pattern=optikon or ?from_optikon=<illusion_slug>.
    # The illusion's params travel as ordinary query string params
    # (the same names the optikon playground form uses).
    optikon_slug = (request.GET.get('from_optikon') or '').strip()
    if optikon_slug or pattern == 'optikon':
        return _optikon_svg(request, optikon_slug)

    if pattern not in svg.PATTERNS or pattern in ('tilesmith', 'escher',
                                                     'loupe'):
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

    embed = request.GET.get('embed') == '1'
    body = svg.render(pattern, page=page, cell_mm=cell, style=style,
                      fill=fill, with_dimensions=not embed)
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


# ─── Tilesmith mode ────────────────────────────────────────────────

def _tilesmith_svg(request, slug: str):
    """Render a Tilesmith tile tessellated across the page.

    Query knobs (in addition to the standard cell/margin/color/...):
      ``from_tilesmith=<slug>`` (or ``pattern=tilesmith&tile=<slug>``)
                            — required, picks the TileSpec
      ``lattice=offset-hex|square``
                            — override TileSpec.lattice for the print
    """
    from tilesmith.models import TileSpec

    landscape = request.GET.get('landscape') == '1'
    margin = _float(request, 'margin', 10.0, lo=0.0, hi=40.0)
    cell = _float(request, 'cell', 24.0, lo=4.0, hi=160.0)
    width = _float(request, 'width', 0.30, lo=0.05, hi=2.5)
    color = (request.GET.get('color') or '#333333').strip() or '#333333'
    alpha = _float(request, 'alpha', 1.0, lo=0.0, hi=1.0)
    fill_alpha = _float(request, 'fill_alpha', 0.85, lo=0.0, hi=1.0)
    border = request.GET.get('border') == '1'

    page_w = svg.A4_H if landscape else svg.A4_W
    page_h = svg.A4_W if landscape else svg.A4_H
    page = svg.Page(w_mm=page_w, h_mm=page_h, margin_mm=margin)
    style = svg.Style(color=color, width_mm=width, alpha=alpha,
                       fill_alpha=fill_alpha)
    embed = request.GET.get('embed') == '1'

    def _err(msg: str) -> HttpResponse:
        import html
        body = (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {page_w} {page_h}" '
            f'preserveAspectRatio="xMidYMid meet">'
            f'<text x="{margin}" y="{margin + 6}" '
            f'font-family="ui-monospace,monospace" font-size="4" '
            f'fill="#c04a4a">tilesmith: {html.escape(msg)}</text></svg>'
        )
        return HttpResponse(body,
                             content_type='image/svg+xml; charset=utf-8')

    if not slug:
        return _err('provide ?from_tilesmith=<slug>')
    spec = TileSpec.objects.filter(slug=slug).first()
    if spec is None:
        return _err(f'tile "{slug}" not found')

    lattice = (request.GET.get('lattice') or spec.lattice or 'offset-hex').strip()
    if lattice not in ('offset-hex', 'square'):
        lattice = 'offset-hex'

    body = svg.render(
        'tilesmith', page=page, cell_mm=cell, style=style,
        tile={
            'edges':   spec.edges_json,
            'base_w':  spec.base_w,
            'base_h':  spec.base_h,
            'lattice': lattice,
        },
        with_dimensions=not embed)

    if border:
        body = body.replace(
            '</svg>',
            f'<rect x="{page.left}" y="{page.top}" '
            f'width="{page.inner_w}" height="{page.inner_h}" '
            f'fill="none" stroke="#cccccc" stroke-width="0.1" '
            f'stroke-dasharray="0.6 0.6" /></svg>',
        )
    # Footer: tile name + lattice + cell size.
    footer = (
        f'<text x="{margin:.2f}" y="{page_h - 2:.2f}" '
        f'font-family="ui-monospace,monospace" font-size="2.4" '
        f'fill="#888">'
        f'tilesmith · {spec.name} ({spec.slug}) · {lattice} · '
        f'{cell:.1f}mm wide'
        f'</text>'
    )
    body = body.replace('</svg>', footer + '</svg>')

    resp = HttpResponse(body, content_type='image/svg+xml; charset=utf-8')
    if request.GET.get('download') == '1':
        resp['Content-Disposition'] = (
            f'attachment; filename="tilesmith-{spec.slug}.svg"')
    return resp


# ─── Loupe mode ────────────────────────────────────────────────────

def _loupe_svg(request, slug: str):
    """Render a saved loupe Walk at A4 (or chosen page size) via the
    server-side numpy Mandelbrot renderer.  The result is wrapped in
    an SVG so gridprint's existing Print / Download buttons keep
    working.

    Query knobs:
      ``from_loupe=<walk_slug>`` — required
      ``step=N`` (default = last)
      ``res=1024`` — PNG resolution along the longer axis
      ``landscape=1``
      ``margin=10``
    """
    import base64
    from loupe.models import Walk
    from loupe import render as renderer

    landscape = request.GET.get('landscape') == '1'
    margin = _float(request, 'margin', 10.0, lo=0.0, hi=40.0)
    page_w = svg.A4_H if landscape else svg.A4_W
    page_h = svg.A4_W if landscape else svg.A4_H

    def _err(msg: str) -> HttpResponse:
        import html
        body = (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {page_w} {page_h}" '
            f'preserveAspectRatio="xMidYMid meet">'
            f'<text x="{margin}" y="{margin + 6}" '
            f'font-family="ui-monospace,monospace" font-size="4" '
            f'fill="#c04a4a">loupe: {html.escape(msg)}</text></svg>'
        )
        return HttpResponse(body, content_type='image/svg+xml; charset=utf-8')

    if not slug:
        return _err('provide ?from_loupe=<walk_slug>')
    walk = Walk.objects.filter(slug=slug).first()
    if walk is None:
        return _err(f'walk "{slug}" not found')
    gene = walk.gene_json or []
    if not gene:
        return _err('walk has empty gene')
    step = _int(request, 'step', len(gene) - 1, lo=0, hi=len(gene) - 1)
    g = gene[step]
    res = _int(request, 'res', 1024, lo=128, hi=2000)
    # Figure out a square-fit PNG resolution that matches the printable
    # area's aspect ratio: portrait → taller, landscape → wider.
    inner_w_mm = page_w - 2 * margin
    inner_h_mm = page_h - 2 * margin
    if inner_w_mm >= inner_h_mm:
        png_w = res
        png_h = max(16, int(res * inner_h_mm / inner_w_mm))
    else:
        png_h = res
        png_w = max(16, int(res * inner_w_mm / inner_h_mm))
    iter_cap = int(g.get('iter') or renderer.auto_iter(g['span']))
    png = renderer.render_mandelbrot_png(
        float(g['cx']), float(g['cy']), float(g['span']),
        png_w, png_h, iter_cap=iter_cap,
    )
    b64 = base64.b64encode(png).decode('ascii')

    body = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{page_w}mm" height="{page_h}mm" '
        f'viewBox="0 0 {page_w} {page_h}" '
        f'preserveAspectRatio="xMidYMid meet">'
        f'<rect x="0" y="0" width="{page_w}" height="{page_h}" fill="#fff" />'
        f'<image href="data:image/png;base64,{b64}" '
        f'x="{margin}" y="{margin}" '
        f'width="{inner_w_mm}" height="{inner_h_mm}" '
        f'preserveAspectRatio="xMidYMid meet" />'
        f'<text x="{margin:.2f}" y="{page_h - 2:.2f}" '
        f'font-family="ui-monospace,monospace" font-size="2.4" '
        f'fill="#888">'
        f'loupe · {walk.slug} · step {step + 1}/{len(gene)} · '
        f'cx={g["cx"]:.6g} cy={g["cy"]:.6g} span={g["span"]:.3e}'
        f'</text>'
        f'</svg>'
    )
    resp = HttpResponse(body, content_type='image/svg+xml; charset=utf-8')
    if request.GET.get('download') == '1':
        resp['Content-Disposition'] = (
            f'attachment; filename="loupe-{walk.slug}-step{step}.svg"')
    return resp


# ─── Escher mode ───────────────────────────────────────────────────

def _escher_svg(request, slug: str):
    """Render a wallpaper-group composition through gridprint's
    print pipeline.

    Query knobs (besides the standard cell/margin/color/...):
      ``from_escher=<group_slug>`` — required, one of the 17 IUC slugs
      ``motif=stock|spoeqi_component``
      ``motif_slug=<stock-slug>``   (when motif=stock)
      ``pact=<slug>&component=K&gen=N``  (when motif=spoeqi_component)
      ``tile=30``                   tile spacing in mm
      ``cells=1``                   overlay unit cells
      ``orbit=1``                   highlight one orbit
    """
    from escher import groups as eg
    from escher import svg as esvg
    from escher.views import _resolve_motif

    landscape = request.GET.get('landscape') == '1'
    margin = _float(request, 'margin', 10.0, lo=0.0, hi=40.0)
    tile = _float(request, 'tile', 30.0, lo=4.0, hi=400.0)
    page_w = svg.A4_H if landscape else svg.A4_W
    page_h = svg.A4_W if landscape else svg.A4_H

    def _err(msg: str) -> HttpResponse:
        import html
        body = (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {page_w} {page_h}" '
            f'preserveAspectRatio="xMidYMid meet">'
            f'<text x="{margin}" y="{margin + 6}" '
            f'font-family="ui-monospace,monospace" font-size="4" '
            f'fill="#c04a4a">escher: {html.escape(msg)}</text></svg>'
        )
        return HttpResponse(body,
                             content_type='image/svg+xml; charset=utf-8')

    if not slug:
        return _err('provide ?from_escher=<group_slug>')
    try:
        group = eg.get(slug)
    except KeyError:
        return _err(f'unknown wallpaper group "{slug}"')

    motif_body = _resolve_motif(request)
    embed = request.GET.get('embed') == '1'

    cfg = esvg.RenderConfig(
        tile_mm=tile,
        viewport_w_mm=page_w,
        viewport_h_mm=page_h,
        margin_mm=margin,
        show_unit_cell=request.GET.get('cells') == '1',
        show_orbit=request.GET.get('orbit') == '1',
    )
    body = esvg.render(group, motif_body, cfg, embed=embed)

    # Footer line — name + lattice + tile size — mirroring the
    # tilesmith branch.  Inserted just before the closing </svg>.
    motif_kind = (request.GET.get('motif') or 'stock').strip()
    if motif_kind == 'spoeqi_component':
        motif_label = (f'spoeqi {request.GET.get("pact") or "?"} '
                        f'· cmp {request.GET.get("component") or "0"} '
                        f'· gen {request.GET.get("gen") or "0"}')
    elif motif_kind == 'tilesmith_tile':
        motif_label = f'tilesmith {request.GET.get("tile_slug") or "?"}'
    elif motif_kind == 'upload':
        motif_label = f'upload {request.GET.get("upload_slug") or "?"}'
    elif motif_kind == 'loupe_walk':
        ls = request.GET.get('loupe_slug') or '?'
        st = request.GET.get('loupe_step') or 'final'
        motif_label = f'loupe {ls} step {st}'
    else:
        motif_label = (request.GET.get('motif_slug') or 'comma').strip()
    footer = (
        f'<text x="{margin:.2f}" y="{page_h - 2:.2f}" '
        f'font-family="ui-monospace,monospace" font-size="2.4" '
        f'fill="#888">'
        f'escher · {group.slug} ({group.note}) · motif {motif_label} · '
        f'tile {tile:.1f}mm · orbit ×{group.orbit_size}'
        f'</text>'
    )
    body = body.replace('</svg>', footer + '</svg>')

    resp = HttpResponse(body, content_type='image/svg+xml; charset=utf-8')
    if request.GET.get('download') == '1':
        resp['Content-Disposition'] = (
            f'attachment; filename="escher-{group.slug}.svg"')
    return resp


# ─── Optikon mode ──────────────────────────────────────────────────

def _optikon_svg(request, slug: str):
    """Render an optikon optical illusion at A4 by computing its
    color-index grid through the optikon library and feeding the
    fill array to gridprint's standard hex_grid().

    Query knobs (in addition to the usual cell/margin/landscape):
      ``from_optikon=<illusion_slug>`` — required
      ``cell=<mm>``                    — hex side in mm (default 4)
      ``margin=<mm>``                  — page margin (default 10)
      ``landscape=1``
      ``border=1``
      ``download=1``                   — content-disposition attachment
      <illusion-specific params>       — same names as the optikon form
    """
    import html
    from optikon import illusions as ill

    landscape = request.GET.get('landscape') == '1'
    margin    = _float(request, 'margin', 10.0, lo=0.0, hi=40.0)
    cell      = _float(request, 'cell',    4.0, lo=2.0, hi=20.0)
    border    = request.GET.get('border') == '1'
    page_w    = svg.A4_H if landscape else svg.A4_W
    page_h    = svg.A4_W if landscape else svg.A4_H

    def _err(msg: str):
        body = (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {page_w} {page_h}" '
            f'preserveAspectRatio="xMidYMid meet">'
            f'<text x="{margin}" y="{margin + 6}" '
            f'font-family="ui-monospace,monospace" font-size="4" '
            f'fill="#c04a4a">optikon: {html.escape(msg)}</text></svg>'
        )
        return HttpResponse(body, content_type='image/svg+xml; charset=utf-8')

    if not slug: return _err('provide ?from_optikon=<illusion_slug>')
    illusion = ill.get(slug)
    if illusion is None: return _err(f'unknown illusion {slug!r}')

    raw = {p.key: request.GET[p.key]
           for p in illusion.PARAMS if p.key in request.GET}
    params = ill.parse_params(illusion.PARAMS, raw)

    page = svg.Page(w_mm=page_w, h_mm=page_h, margin_mm=margin)
    # Fill the printable area at the requested hex side.
    sqrt3 = math.sqrt(3)
    grid_w = max(8, int(page.inner_w / (cell * sqrt3)) + 2)
    grid_h = max(8, int(page.inner_h / (cell * 1.5))   + 2)

    indices = illusion.render(grid_w, grid_h, params)
    palette = illusion.PALETTE
    fill = [
        [palette[ix % len(palette)] for ix in row]
        for row in indices
    ]
    style = svg.Style(color='#222222', width_mm=0.05, alpha=1.0)
    body  = svg.hex_grid(page=page, side_mm=cell, style=style,
                          pointy_top=True, fill=fill,
                          with_dimensions=False)

    if border:
        body = body.replace(
            '</svg>',
            f'<rect x="{page.left}" y="{page.top}" '
            f'width="{page.inner_w}" height="{page.inner_h}" '
            f'fill="none" stroke="#cccccc" stroke-width="0.1" '
            f'stroke-dasharray="0.6 0.6" /></svg>',
        )

    resp = HttpResponse(body, content_type='image/svg+xml; charset=utf-8')
    if request.GET.get('download') == '1':
        resp['Content-Disposition'] = (
            f'attachment; filename="optikon-{slug}.svg"')
    return resp


# ─── Flower-dump mode ──────────────────────────────────────────────

def _load_rule_and_palette(request) -> tuple[bytes, list, dict] | None:
    """Resolve a (rule_bytes, palette, meta) triple from the query.
    Returns None if no source was specified; raises ValueError on bad
    inputs.

    Sources:
      ?from_spoeqi=<slug>             — pull rule_snapshot + palette from the Pact
      ?from_spoeqi=<slug>&component=K — slice the per-component rule + palette
      ?rule_hex=<hex>                 — explicit 32,768-char hex; palette default
    """
    slug = (request.GET.get('from_spoeqi') or '').strip()
    rule_hex = (request.GET.get('rule_hex') or '').strip()
    comp_raw = (request.GET.get('component') or '').strip()
    if slug:
        from spoeqi.models import Pact
        from spoeqi.models import COMPONENTS as N_COMPONENTS
        pact = Pact.objects.filter(slug=slug).first()
        if pact is None:
            raise ValueError(f'spoeqi pact "{slug}" not found')
        component = None
        if comp_raw:
            try:
                component = int(comp_raw)
            except ValueError:
                raise ValueError(f'component must be 0..{N_COMPONENTS - 1}; '
                                  f'got {comp_raw!r}')
            if not 0 <= component < N_COMPONENTS:
                raise ValueError(f'component must be 0..{N_COMPONENTS - 1}; '
                                  f'got {component}')
        if component is None:
            rule = bytes(pact.rule_snapshot)
        else:
            base = component * hex_flowers.RULE_TABLE_SIZE
            rule = pact.per_component_rules()[
                base : base + hex_flowers.RULE_TABLE_SIZE]
        # Palette: per-component when the pact has one, otherwise the shared.
        palette_raw = pact.palette or []
        if component is not None and palette_raw and isinstance(palette_raw[0][0], list):
            pal_rgb = palette_raw[component]
        elif palette_raw and isinstance(palette_raw[0][0], list):
            pal_rgb = palette_raw[0]   # shared-default to first when caller
                                        # didn't pick a component
        else:
            pal_rgb = palette_raw
        palette = [f'rgb({r},{g},{b})' for r, g, b in pal_rgb]
        meta = {'source': 'spoeqi', 'slug': pact.slug, 'name': pact.name}
        if component is not None:
            meta['component'] = component
        return rule, palette, meta
    if rule_hex:
        try:
            rule = bytes.fromhex(rule_hex)
        except ValueError as e:
            raise ValueError(f'bad rule_hex: {e}')
        if len(rule) != hex_flowers.RULE_TABLE_SIZE:
            raise ValueError(
                f'rule_hex decoded to {len(rule)} bytes; '
                f'expected exactly {hex_flowers.RULE_TABLE_SIZE}')
        palette = ['#dddddd', '#ec5b3a', '#3a7eec', '#3aec74']
        return rule, palette, {'source': 'hex'}
    return None


def _flowers_svg(request):
    """Render a flower-dump page from a hex-CA rule.  Branched off
    grid_svg via ?mode=flowers.

    Three sub-views selectable via ``?fview=``:

    * ``catalog`` (default) — the genuine 7→1 flower display: each
      widget shows a centre hex + 6 neighbours pointing via an
      arrow to the rule's single-cell output.  One widget per
      neighbourhood configuration in the rule's 16,384-entry table.
    * ``fill`` — opt-in alternative: paint each cell of the regular
      hex tessellation with ``rule[cell_index] & 3`` row-major.
      Visualises the rule's *output distribution* across all
      configurations, but has no spatial CA meaning.
    * ``run`` — actually simulate the CA: take the pact's seed +
      rule, advance ``?ticks=N`` generations on the chosen
      component, and tile the resulting 16×16 grid across the page.
      Requires ``?from_spoeqi=<slug>`` (the seed lives on the Pact).
    """
    landscape = request.GET.get('landscape') == '1'
    margin = _float(request, 'margin', 10.0, lo=0.0, hi=40.0)
    page_w = svg.A4_H if landscape else svg.A4_W
    page_h = svg.A4_W if landscape else svg.A4_H
    fview = (request.GET.get('fview') or 'catalog').strip()

    # Common: resolve the rule source.
    try:
        rule_palette = _load_rule_and_palette(request)
    except ValueError as exc:
        body = (
            f'<text x="{margin}" y="{margin + 6}" '
            f'font-family="ui-monospace,monospace" font-size="4" '
            f'fill="#c04a4a">flowers: {exc}</text>'
        )
        return HttpResponse(
            hex_flowers.wrap_page(body, page_w, page_h),
            content_type='image/svg+xml; charset=utf-8')
    if rule_palette is None:
        body = (
            f'<text x="{margin}" y="{margin + 6}" '
            f'font-family="ui-monospace,monospace" font-size="3.4" '
            f'fill="#888">flowers mode: provide '
            f'<tspan font-weight="bold">?from_spoeqi=&lt;slug&gt;</tspan> '
            f'or <tspan font-weight="bold">?rule_hex=&lt;…&gt;</tspan></text>'
        )
        return HttpResponse(
            hex_flowers.wrap_page(body, page_w, page_h),
            content_type='image/svg+xml; charset=utf-8')
    rule, palette, meta = rule_palette

    title_bits = []
    if meta.get('source') == 'spoeqi':
        title_bits.append(f'{meta["name"]} ({meta["slug"]})')
        if 'component' in meta:
            title_bits.append(f'component {meta["component"]}')

    # ─── CA-run view (?fview=run): actually simulate the CA ────
    if fview == 'run':
        return _flowers_run_svg(request, rule, palette, meta,
                                  title_bits, page_w, page_h, margin)

    # ─── Fill view (?fview=fill): colour the print grid by rule ─
    if fview == 'fill':
        return _flowers_fill_svg(request, rule, palette, title_bits,
                                   page_w, page_h, margin)

    # ─── Catalog (default — genuine 7→1 flower widgets) ─────────
    fpage = _int(request, 'fpage', 0, lo=0, hi=512)
    # fsize picks a named density preset; fscale overrides directly.
    fsize_name = (request.GET.get('fsize')
                   or hex_flowers.DEFAULT_SIZE).strip().lower()
    size_scale = hex_flowers.SIZE_SCALES.get(
        fsize_name, hex_flowers.SIZE_SCALES[hex_flowers.DEFAULT_SIZE])
    try:
        size_scale = max(0.1, min(3.0, float(request.GET.get('fscale',
                                                                 size_scale))))
    except (TypeError, ValueError):
        pass
    # fper defaults to "whatever fits at this size" (None signals
    # auto-fit inside render_flowers_svg).
    fper_raw = (request.GET.get('fper') or '').strip()
    fper = None
    if fper_raw:
        try:
            fper = max(1, min(4096, int(fper_raw)))
        except ValueError:
            fper = None
    fcentre_raw = (request.GET.get('fcentre') or '').strip()
    fcentre = None
    if fcentre_raw:
        try:
            v = int(fcentre_raw)
            if 0 <= v <= 3:
                fcentre = v
        except ValueError:
            pass
    body, summary = hex_flowers.render_flowers_svg(
        rule, palette=palette,
        page_w_mm=page_w, page_h_mm=page_h,
        margin_mm=margin,
        flowers_per_page=fper,
        page_index=fpage,
        center_filter=fcentre,
        size_scale=size_scale,
        title_text=' · '.join(title_bits) if title_bits else None,
    )
    out = hex_flowers.wrap_page(body, page_w, page_h)
    resp = HttpResponse(out, content_type='image/svg+xml; charset=utf-8')
    if request.GET.get('download') == '1':
        resp['Content-Disposition'] = (
            f'attachment; filename="flowers-{summary.rule_hash_short}-p{fpage}.svg"')
    return resp


def _flowers_fill_svg(request, rule, palette, title_bits,
                       page_w, page_h, margin):
    """Rule-output fill view (formerly the default).  Each hex cell
    in the print tessellation gets ``palette[rule[i] & 3]`` with
    ``i`` walking the 16,384-byte rule row-major across pages."""
    pattern = (request.GET.get('pattern') or 'hex_pointy').strip()
    if pattern not in ('hex_pointy', 'hex_flat'):
        pattern = 'hex_pointy'
    cell = _float(request, 'cell', 5.0, lo=0.8, hi=80.0)
    width = _float(request, 'width', 0.20, lo=0.05, hi=2.5)
    color = (request.GET.get('color') or '#888888').strip() or '#888888'
    alpha = _float(request, 'alpha', 1.0, lo=0.0, hi=1.0)
    fill_alpha = _float(request, 'fill_alpha', 0.95, lo=0.0, hi=1.0)
    fpage = _int(request, 'fpage', 0, lo=0, hi=255)

    page = svg.Page(w_mm=page_w, h_mm=page_h, margin_mm=margin)
    style = svg.Style(color=color, width_mm=width, alpha=alpha,
                       fill_alpha=fill_alpha)

    rows, cols = hex_flowers.natural_hex_dims(
        page_w, page_h, margin, cell,
        pointy_top=(pattern == 'hex_pointy'))
    cells_per_page = rows * cols
    start = fpage * cells_per_page
    fill = hex_flowers.fill_grid_from_rule(rule, palette, rows, cols,
                                            start_index=start)

    embed = request.GET.get('embed') == '1'
    body = svg.render(pattern, page=page, cell_mm=cell, style=style,
                       fill=fill, with_dimensions=not embed)

    # Footer: rule fingerprint + page counter, like the catalog view
    # had.  Glued onto the SVG by replacing the closing </svg>.
    import hashlib
    rule_hash = hashlib.sha256(rule).hexdigest()[:16]
    n_pages = (hex_flowers.RULE_TABLE_SIZE + cells_per_page - 1) // cells_per_page
    title_str = ' · '.join(title_bits)
    last_idx = min(hex_flowers.RULE_TABLE_SIZE - 1, start + cells_per_page - 1)
    footer = (
        f'<g><text x="{margin:.2f}" y="{margin - 1.5:.2f}" '
        f'font-family="ui-monospace,monospace" font-size="2.6" '
        f'fill="#666">{title_str}</text>'
        f'<text x="{margin:.2f}" y="{page_h - 2:.2f}" '
        f'font-family="ui-monospace,monospace" font-size="2.4" '
        f'fill="#888">'
        f'rule {rule_hash}…   page {fpage + 1}/{n_pages}   '
        f'entries {start}..{last_idx} of {hex_flowers.RULE_TABLE_SIZE}   '
        f'grid {cols}×{rows} @ {cell:.1f}mm'
        f'</text></g>'
    )
    body = body.replace('</svg>', footer + '</svg>')

    resp = HttpResponse(body, content_type='image/svg+xml; charset=utf-8')
    if request.GET.get('download') == '1':
        resp['Content-Disposition'] = (
            f'attachment; filename="flowers-fill-{rule_hash}-p{fpage}.svg"')
    return resp


def _flowers_run_svg(request, rule, palette, meta, title_bits,
                       page_w, page_h, margin):
    """Actually-simulate-the-CA view (?fview=run).

    Requires a Pact source (we need the seed_matrix).  Steps the
    pact's chosen component forward ?ticks=N generations and tiles
    the resulting 16×16 grid across the page so adjacent print
    cells share local CA neighbourhoods.
    """
    if meta.get('source') != 'spoeqi':
        body = (
            f'<text x="{margin}" y="{margin + 6}" '
            f'font-family="ui-monospace,monospace" font-size="3.4" '
            f'fill="#888">flowers · fview=run needs '
            f'<tspan font-weight="bold">?from_spoeqi=&lt;slug&gt;</tspan> '
            f'(the seed lives on the Pact).</text>'
        )
        return HttpResponse(
            hex_flowers.wrap_page(body, page_w, page_h),
            content_type='image/svg+xml; charset=utf-8')

    from spoeqi import keystream
    from spoeqi.models import Pact, COMPONENTS

    pact = Pact.objects.filter(slug=meta['slug']).first()
    if pact is None:
        body = (
            f'<text x="{margin}" y="{margin + 6}" '
            f'font-family="ui-monospace,monospace" font-size="4" '
            f'fill="#c04a4a">flowers · pact "{meta["slug"]}" not found</text>'
        )
        return HttpResponse(
            hex_flowers.wrap_page(body, page_w, page_h),
            content_type='image/svg+xml; charset=utf-8')

    ticks = _int(request, 'ticks', 32, lo=0, hi=2000)
    component = int(meta.get('component', 0))
    if not 0 <= component < COMPONENTS:
        component = 0
    side = pact.component_grid

    # Step the whole pact forward (keystream.advance operates on the
    # 64-component state in lockstep) and slice out the component the
    # caller chose.  Up to 2k ticks at 16×16 stays under a second in
    # pure Python.
    state = keystream.initial_multi_grid(pact)
    state = keystream.advance(state, ticks, pact)
    base = component * side * side
    comp_state = state[base : base + side * side]

    pattern = (request.GET.get('pattern') or 'hex_pointy').strip()
    if pattern not in ('hex_pointy', 'hex_flat'):
        pattern = 'hex_pointy'
    cell = _float(request, 'cell', 5.0, lo=0.8, hi=80.0)
    width = _float(request, 'width', 0.20, lo=0.05, hi=2.5)
    color = (request.GET.get('color') or '#888888').strip() or '#888888'
    alpha = _float(request, 'alpha', 1.0, lo=0.0, hi=1.0)
    fill_alpha = _float(request, 'fill_alpha', 0.95, lo=0.0, hi=1.0)

    page = svg.Page(w_mm=page_w, h_mm=page_h, margin_mm=margin)
    style = svg.Style(color=color, width_mm=width, alpha=alpha,
                       fill_alpha=fill_alpha)
    rows, cols = hex_flowers.natural_hex_dims(
        page_w, page_h, margin, cell,
        pointy_top=(pattern == 'hex_pointy'))
    fill = hex_flowers.fill_grid_from_ca_state(comp_state, palette,
                                                  side, rows, cols)

    embed = request.GET.get('embed') == '1'
    body = svg.render(pattern, page=page, cell_mm=cell, style=style,
                       fill=fill, with_dimensions=not embed)

    import hashlib
    rule_hash = hashlib.sha256(rule).hexdigest()[:16]
    title_str = ' · '.join(title_bits)
    footer = (
        f'<g><text x="{margin:.2f}" y="{margin - 1.5:.2f}" '
        f'font-family="ui-monospace,monospace" font-size="2.6" '
        f'fill="#666">{title_str}</text>'
        f'<text x="{margin:.2f}" y="{page_h - 2:.2f}" '
        f'font-family="ui-monospace,monospace" font-size="2.4" '
        f'fill="#888">'
        f'rule {rule_hash}…   CA run · component {component} · '
        f'gen {ticks}   '
        f'grid {cols}×{rows} @ {cell:.1f}mm (tiles {side}×{side} pact cell)'
        f'</text></g>'
    )
    body = body.replace('</svg>', footer + '</svg>')

    resp = HttpResponse(body, content_type='image/svg+xml; charset=utf-8')
    if request.GET.get('download') == '1':
        resp['Content-Disposition'] = (
            f'attachment; filename="flowers-run-{rule_hash}-c{component}-t{ticks}.svg"')
    return resp


@login_required
def print_view(request):
    """Tiny HTML wrapper around the SVG that auto-fires window.print() on
    load. Print button on /gridprint/ opens this in a new window so the
    browser's print pipeline runs against real HTML (not raw SVG mime,
    which Firefox can't print from)."""
    # Reuse grid_svg's logic by calling the function directly. Strip the
    # ?download=1 flag so we don't get a Content-Disposition.
    from django.http import QueryDict
    q = request.GET.copy()
    q.pop('download', None)
    request.GET = q
    svg_resp = grid_svg(request)
    svg_body = svg_resp.content.decode('utf-8', errors='replace')

    landscape = request.GET.get('landscape') == '1'
    page_size = 'A4 landscape' if landscape else 'A4 portrait'

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Gridprint — print</title>
<style>
  @page {{ size: {page_size}; margin: 0; }}
  html, body {{ margin: 0; padding: 0; background: #fff; }}
  svg {{ display: block; width: 100vw; height: 100vh; }}
  @media screen {{
    body {{ background: #222; padding: 1rem; box-sizing: border-box; }}
    svg {{ box-shadow: 0 0 0 1px #444; max-width: calc(100vw - 2rem);
           max-height: calc(100vh - 6rem); width: auto; height: auto;
           background: #fff; margin: 0 auto; }}
    .help {{ color: #aaa; font: 13px ui-monospace, monospace;
             text-align: center; margin: 0 0 0.6rem 0; }}
    .help button {{ background:#1f6feb;color:#fff;border:0;
                    padding:0.3rem 0.8rem;border-radius:3px;
                    cursor:pointer;font: inherit; }}
  }}
  @media print {{
    .help {{ display: none !important; }}
  }}
</style></head>
<body>
<p class="help">If the dialog didn't open, click
  <button onclick="window.print()">Print again</button>.
</p>
{svg_body}
<script>
  // Wait one frame so the SVG is laid out, then fire the dialog. Some
  // browsers ignore print() called too early (during DOMContentLoaded).
  window.addEventListener('load', () => {{
    requestAnimationFrame(() => window.print());
  }});
</script>
</body></html>
"""
    return HttpResponse(html, content_type='text/html; charset=utf-8')
