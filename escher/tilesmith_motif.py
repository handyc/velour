"""Render a Tilesmith TileSpec as an escher motif.

The motif is the tile's deformed-rectangle boundary, scaled and
translated to fit the [0, 1]×[0, 1] motif box with a small inset.
We reuse gridprint's existing trace function so a tile that has
been verified to tessellate in offset-hex looks identical when
placed into one of the 17 wallpaper-group orbits.

What you get visually: the tile's silhouette repeated under the
chosen group's symmetry — interesting because a TileSpec is
designed to tile *offset-hex*, but the wallpaper group can apply
any of 17 different symmetries on top.
"""

from __future__ import annotations

from typing import List


def tilesmith_tile_motif(tile_slug: str,
                          *, fill: str = '#3a7eec',
                          stroke: str = '#1a3e7a',
                          stroke_width: float = 0.02,
                          inset: float = 0.04) -> str:
    """Return an SVG body fragment whose only element is the
    tilesmith tile's outline polygon, fitted into [0,1]² with
    ``inset`` margin on each side.
    """
    from tilesmith.models import TileSpec
    from gridprint.svg import _tilesmith_trace

    spec = TileSpec.objects.filter(slug=tile_slug).first()
    if spec is None:
        return _placeholder(f'tilesmith tile "{tile_slug}" not found')

    base_w = max(1.0, float(spec.base_w or 64))
    base_h = max(1.0, float(spec.base_h or 64))

    # Trace the tile boundary in *tile-unit* space (tile_w = tile_h = 1).
    # This places the un-deformed rectangle at [0,1]² with bumps pushing
    # outward into negative coordinates / past 1.0.
    pts = _tilesmith_trace(spec.edges_json or [[], [], [], [], [], []],
                            origin_x=0.0, origin_y=0.0,
                            tile_w=1.0, tile_h=1.0,
                            base_w=base_w, base_h=base_h)
    if not pts:
        return _placeholder('empty tile trace')

    # Bounding box → uniform scale into [inset, 1-inset]² while keeping
    # the tile's intended aspect ratio (base_h / base_w).
    xs = [x for (x, _y) in pts]
    ys = [y for (_x, y) in pts]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    src_w = max(1e-6, x_max - x_min)
    src_h = max(1e-6, y_max - y_min)
    avail = 1.0 - 2.0 * inset
    scale = min(avail / src_w, avail / src_h)
    # Centre the scaled bounds inside [inset, 1-inset]².
    ox = inset + (avail - src_w * scale) / 2.0
    oy = inset + (avail - src_h * scale) / 2.0

    out_pts: List[str] = []
    for (x, y) in pts:
        nx = ox + (x - x_min) * scale
        ny = oy + (y - y_min) * scale
        out_pts.append(f'{nx:.4f},{ny:.4f}')

    return (
        f'<polygon points="{" ".join(out_pts)}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}" '
        f'stroke-linejoin="round" />'
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
