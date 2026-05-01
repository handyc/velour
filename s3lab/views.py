from django.http import Http404
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie


# Registered sublabs. Add a new entry here when you drop a new
# sublab module under static/s3lab/js/sublabs/.
#
#   slug      URL segment after /s3lab/
#   module    filename (without extension) under static/s3lab/js/sublabs/
#   template  Django template path for the body partial — included
#             from index.html via {% include active_sublab.template %}
#   name      label shown on the tab strip
#   blurb     one-line hover hint; appears as the tab `title`
SUBLABS = [
    {
        'slug':     'classic',
        'module':   'classic',
        'template': 's3lab/sublabs/classic_body.html',
        'name':     'Classic',
        'blurb':    'The original /s3lab/ bench: hunt + GPIO + TFT + '
                    'timing diagram. The base frame the other sublabs '
                    'extend.',
    },
    {
        'slug':     'filmstrip',
        'module':   'filmstrip',
        'template': 's3lab/sublabs/filmstrip_body.html',
        'name':     'Filmstrip',
        'blurb':    'A scrolling strip of recent CA refinements. Each '
                    'frame is one past genome; on every refine the '
                    'strip shifts left and a new live tile appears.',
    },
    {
        'slug':     'cellular',
        'module':   'cellular',
        'template': 's3lab/sublabs/cellular_body.html',
        'name':     'Cellular',
        'blurb':    'Tiles-are-population spatial GA on a pointy-top '
                    'hex tiling. 256 cells, 6-neighbour tournament '
                    'selection. Watch good rules sweep regions.',
    },
    {
        'slug':     'stratum',
        'module':   'stratum',
        'template': 's3lab/sublabs/stratum_body.html',
        'name':     'Stratum',
        'blurb':    'Two-layer hex CA: 64-entry library of K=64 HexNN '
                    'rules + a 16×16 meta-CA whose states index the '
                    'library. The elite library entry drives the meta-CA. '
                    'One rule playing two scales of itself.',
    },
    # Future sublabs land here. Keep entries small.
]
SUBLABS_BY_SLUG = {s['slug']: s for s in SUBLABS}
DEFAULT_SUBLAB = 'classic'


def _render_sublab(request, sublab_slug):
    active = SUBLABS_BY_SLUG.get(sublab_slug)
    if not active:
        raise Http404(f'unknown s3lab sublab: {sublab_slug!r}')
    return render(request, 's3lab/index.html', {
        'sublabs':       SUBLABS,
        'active_sublab': active,
    })


@ensure_csrf_cookie
@login_required
def index(request):
    """Default S3 Lab view — Classic sublab.

    All compute (engine, GA, render, GPIO) runs in the browser. The
    Django side just serves the page + static assets and tracks which
    sublab module to load. The ``ensure_csrf_cookie`` decorator makes
    the "→ Automaton" export button work — without it Django never
    writes the csrftoken cookie on this page (no form), so the
    JS-side X-CSRFToken header is empty and the POST to
    /automaton/import-from-s3lab/ 403s.
    """
    return _render_sublab(request, DEFAULT_SUBLAB)


@ensure_csrf_cookie
@login_required
def sublab(request, slug):
    """Named sublab — same chrome as /s3lab/, different module."""
    return _render_sublab(request, slug)
