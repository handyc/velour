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

import hashlib

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.files.base import ContentFile
from django.http import HttpResponse, Http404, JsonResponse
from django.shortcuts import render, redirect
from django.utils.text import slugify
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from . import groups, motifs, svg, ca_motif, tilesmith_motif, uploads as uploads_mod


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
    if kind == 'upload':
        slug = (request.GET.get('upload_slug') or '').strip()
        if not slug:
            return uploads_mod._placeholder('missing ?upload_slug=<slug>')
        return uploads_mod.upload_motif(slug)
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
def upload_list(request):
    """Index of uploaded motifs.  POST = upload a new image.  GET = browse."""
    from .models import UploadedMotif
    if request.method == 'POST':
        return _handle_upload(request)
    return render(request, 'escher/uploads.html', {
        'uploads': UploadedMotif.objects.all()[:200],
        'groups':  groups.GROUPS,
    })


@require_POST
@login_required
def _handle_upload(request):
    from .models import UploadedMotif
    f = request.FILES.get('image')
    if f is None:
        messages.error(request, 'no image file selected')
        return redirect('escher:uploads')
    raw = f.read()
    if not raw:
        messages.error(request, 'uploaded file is empty')
        return redirect('escher:uploads')
    if len(raw) > 8 * 1024 * 1024:
        messages.error(request, 'upload exceeds 8 MB limit')
        return redirect('escher:uploads')
    sha = hashlib.sha256(raw).hexdigest()
    existing = UploadedMotif.objects.filter(content_hash=sha).first()
    if existing is not None:
        messages.info(request, f'dedup: same content already uploaded as '
                                f'"{existing.slug}".')
        return redirect('escher:uploads')

    # Try to read dimensions via PIL.  PIL is already a Velour dep
    # (spoeqi/album.py imports it).  Fall back to 0×0 — the renderer
    # treats that as a 1:1 square.
    width = height = 0
    content_type = (f.content_type or 'image/png')
    try:
        from PIL import Image
        from io import BytesIO
        with Image.open(BytesIO(raw)) as im:
            width, height = im.size
    except Exception:
        pass

    base = slugify(f.name.rsplit('.', 1)[0]) or 'image'
    slug = base
    n = 1
    while UploadedMotif.objects.filter(slug=slug).exists():
        n += 1
        slug = f'{base}-{n}'
    rec = UploadedMotif(
        slug=slug,
        original_name=f.name[:200],
        content_hash=sha,
        content_type=content_type,
        width=width, height=height,
    )
    ext = (f.name.rsplit('.', 1)[-1] if '.' in f.name else 'bin').lower()
    rec.file.save(f'{sha}.{ext}', ContentFile(raw), save=False)
    rec.save()
    messages.success(request, f'uploaded "{rec.slug}" '
                              f'({width}×{height}, {len(raw):,} bytes)')
    return redirect('escher:uploads')


@login_required
def group_detail(request, slug):
    """Per-group page with the live preview iframe + controls."""
    try:
        g = groups.get(slug)
    except KeyError:
        raise Http404(f'unknown wallpaper group: {slug}')
    return _render_group_page(request, g, composition=None)


def _render_group_page(request, group, *, composition):
    """Common renderer for the per-group editor.  When ``composition``
    is set, its stored settings are injected as the initial form
    values via a JSON blob the template's JS reads on load."""
    from .models import UploadedMotif
    import json as _json
    initial = {}
    if composition is not None:
        s = composition.motif_spec or {}
        initial = {
            'group':         composition.group_slug,
            'motif':         composition.motif_kind,
            'motif_slug':    s.get('slug', ''),
            'pact':          s.get('pact', ''),
            'component':     s.get('component', ''),
            'gen':           s.get('generation', ''),
            'tile_slug':     s.get('tile_slug', ''),
            'upload_slug':   s.get('upload_slug', ''),
            'tile':          composition.tile_mm,
            'landscape':     '1' if composition.landscape else '',
        }
    return render(request, 'escher/group_detail.html', {
        'group':   group,
        'groups':  groups.GROUPS,
        'motifs':  list(motifs.STOCK.values()),
        'default_motif': motifs.DEFAULT_MOTIF,
        'uploads': UploadedMotif.objects.all()[:200],
        'composition': composition,
        'initial_json': _json.dumps(initial),
    })


# ─── Persisted compositions ──────────────────────────────────────────

def _spec_from_request(request) -> dict:
    """Build the JSONField spec for a Composition from the current
    POST/GET params.  Different motif kinds carry different keys."""
    kind = (request.POST.get('motif') or request.GET.get('motif')
            or 'stock').strip()
    g = request.POST.get if request.method == 'POST' else request.GET.get
    if kind == 'spoeqi_component':
        return {
            'pact':       (g('pact') or '').strip(),
            'component':  int(g('component') or 0),
            'generation': int(g('gen') or 0),
        }
    if kind == 'tilesmith_tile':
        return {'tile_slug': (g('tile_slug') or '').strip()}
    if kind == 'upload':
        return {'upload_slug': (g('upload_slug') or '').strip()}
    return {'slug': (g('motif_slug') or motifs.DEFAULT_MOTIF).strip()}


@login_required
def composition_list(request):
    from .models import Composition
    return render(request, 'escher/composition_list.html', {
        'compositions': Composition.objects.all()[:200],
        'groups': groups.GROUPS,
    })


@require_POST
@login_required
def composition_save(request):
    from .models import Composition
    name = (request.POST.get('name') or '').strip()
    if not name:
        messages.error(request, 'composition name required')
        return redirect(request.META.get('HTTP_REFERER',
                                          reverse('escher:index')))
    group_slug = (request.POST.get('group') or 'p4m').strip()
    try:
        groups.get(group_slug)
    except KeyError:
        messages.error(request, f'unknown group: {group_slug}')
        return redirect(request.META.get('HTTP_REFERER',
                                          reverse('escher:index')))
    motif_kind = (request.POST.get('motif') or 'stock').strip()
    try:
        tile_mm = float(request.POST.get('tile') or 30.0)
    except (TypeError, ValueError):
        tile_mm = 30.0
    landscape = request.POST.get('landscape') == '1'

    base = slugify(name) or 'composition'
    slug = base
    n = 1
    while Composition.objects.filter(slug=slug).exists():
        n += 1
        slug = f'{base}-{n}'
    comp = Composition(
        slug=slug, name=name[:160],
        group_slug=group_slug, motif_kind=motif_kind,
        motif_spec=_spec_from_request(request),
        tile_mm=max(4.0, min(400.0, tile_mm)),
        landscape=landscape,
    )
    comp.save()
    messages.success(request, f'saved composition "{comp.slug}"')
    return redirect('escher:composition_detail', slug=comp.slug)


@login_required
def composition_detail(request, slug):
    from .models import Composition
    comp = Composition.objects.filter(slug=slug).first()
    if comp is None:
        raise Http404(f'composition not found: {slug}')
    try:
        g = groups.get(comp.group_slug)
    except KeyError:
        raise Http404(f'composition references unknown group: '
                       f'{comp.group_slug}')
    return _render_group_page(request, g, composition=comp)


@require_POST
@login_required
def composition_delete(request, slug):
    from .models import Composition
    comp = Composition.objects.filter(slug=slug).first()
    if comp is not None:
        comp.delete()
        messages.success(request, f'deleted composition "{slug}"')
    return redirect('escher:composition_list')


# Need reverse() in composition_save; import here to avoid a top-level
# circular issue with messages flush.
from django.urls import reverse
