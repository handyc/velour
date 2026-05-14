"""Render a saved loupe Walk as an escher motif.

Each tile in the wallpaper-group orbit becomes a small Mandelbrot
image of the walk's chosen step.  The motif SVG references the
already-existing /loupe/w/<slug>/render.png endpoint so the same
image is shared across every <use href="#motif"/> in the tiling.

(References-as-URL rather than inlined base64 for the same reason
the bitmap-upload motif uses MEDIA_URL: some browsers refuse
<image href="data:..."> when the SVG is loaded inside an iframe.)
"""

from __future__ import annotations

from django.urls import reverse


def loupe_walk_motif(walk_slug: str, *, step: int | None = None,
                     resolution: int = 384,
                     inset: float = 0.02) -> str:
    """Return an SVG body fragment that paints a saved loupe Walk's
    final (or chosen step) viewport inside the [0, 1]² motif box.

    The image source URL is the standard ``loupe:walk_png`` endpoint;
    that view 404s on a missing slug, which produces a broken
    ``<image>`` in the SVG.  We pre-check the Walk so the motif
    instead shows a labelled error placeholder when the slug is bad.
    """
    from loupe.models import Walk

    walk = Walk.objects.filter(slug=walk_slug).first()
    if walk is None:
        return _placeholder(f'walk "{walk_slug}" not found')
    gene = walk.gene_json or []
    if not gene:
        return _placeholder(f'walk "{walk_slug}" has empty gene')

    href = reverse('loupe:walk_png', kwargs={'slug': walk_slug})
    qs = [f'w={resolution}', f'h={resolution}']
    if step is not None and 0 <= int(step) < len(gene):
        qs.append(f'step={int(step)}')
    href += '?' + '&'.join(qs)

    # The Mandelbrot render is always square, so fit it square into
    # [inset, 1-inset]² with the same xMidYMid-meet preservation we
    # use elsewhere.
    avail = 1.0 - 2.0 * inset
    return (
        f'<image href="{href}" x="{inset:.4f}" y="{inset:.4f}" '
        f'width="{avail:.4f}" height="{avail:.4f}" '
        f'preserveAspectRatio="xMidYMid meet" />'
    )


def _placeholder(msg: str) -> str:
    import html
    return (
        '<rect x="0" y="0" width="1" height="1" '
        'fill="#fee" stroke="#c44" stroke-width="0.01" />'
        '<text x="0.05" y="0.5" '
        'font-family="ui-monospace,monospace" font-size="0.05" '
        f'fill="#a22">{html.escape(msg)}</text>'
    )
