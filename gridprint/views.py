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
        ?fper=128                  (flowers per page, 1..1024)
        ?fcentre=0..3              (filter to one centre colour)
    """
    if (request.GET.get('mode') or '').strip() == 'flowers':
        return _flowers_svg(request)

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


# ─── Flower-dump mode ──────────────────────────────────────────────

def _load_rule_and_palette(request) -> tuple[bytes, list, dict] | None:
    """Resolve a (rule_bytes, palette, meta) triple from the query.
    Returns None if no source was specified; raises ValueError on bad
    inputs.

    Sources:
      ?from_spoeqi=<slug>    — pull rule_snapshot + palette from the Pact
      ?rule_hex=<hex>        — explicit 32,768-char hex; palette default
    """
    slug = (request.GET.get('from_spoeqi') or '').strip()
    rule_hex = (request.GET.get('rule_hex') or '').strip()
    if slug:
        from spoeqi.models import Pact
        pact = Pact.objects.filter(slug=slug).first()
        if pact is None:
            raise ValueError(f'spoeqi pact "{slug}" not found')
        rule = bytes(pact.rule_snapshot)
        palette = [f'rgb({r},{g},{b})' for r, g, b in pact.palette]
        return rule, palette, {'source': 'spoeqi', 'slug': pact.slug,
                                'name': pact.name}
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
    grid_svg via ?mode=flowers."""
    landscape = request.GET.get('landscape') == '1'
    margin = _float(request, 'margin', 10.0, lo=0.0, hi=40.0)
    page_w = svg.A4_H if landscape else svg.A4_W
    page_h = svg.A4_W if landscape else svg.A4_H

    fpage = _int(request, 'fpage', 0, lo=0, hi=64)
    fper  = _int(request, 'fper', hex_flowers.DEFAULT_FLOWERS_PER_PAGE,
                  lo=1, hi=1024)
    fcentre_raw = (request.GET.get('fcentre') or '').strip()
    fcentre = None
    if fcentre_raw:
        try:
            v = int(fcentre_raw)
            if 0 <= v <= 3:
                fcentre = v
        except ValueError:
            pass

    title = None
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
    if meta['source'] == 'spoeqi':
        title = f'spoeqi pact: {meta["name"]} ({meta["slug"]})'

    body, summary = hex_flowers.render_flowers_svg(
        rule, palette=palette,
        page_w_mm=page_w, page_h_mm=page_h,
        margin_mm=margin,
        flowers_per_page=fper,
        page_index=fpage,
        center_filter=fcentre,
        title_text=title,
    )
    out = hex_flowers.wrap_page(body, page_w, page_h)
    resp = HttpResponse(out, content_type='image/svg+xml; charset=utf-8')
    if request.GET.get('download') == '1':
        resp['Content-Disposition'] = (
            f'attachment; filename="flowers-{summary.rule_hash_short}-p{fpage}.svg"')
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
