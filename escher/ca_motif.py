"""Render a CA frame as an escher motif.

Currently supports one source:

* ``spoeqi_component`` — sample one component of a spoeqi Pact at a
  chosen generation and emit a hex-grid SVG fragment that fits the
  [0, 1]×[0, 1] motif box.

The output is just the inner SVG body (no <svg> wrapper); the
escher renderer wraps it in a <symbol id="motif"> for tiling.
"""

from __future__ import annotations

import math
from typing import List, Tuple


def spoeqi_component_motif(pact_slug: str, component: int,
                            generation: int = 0,
                            *, padding: float = 0.04) -> str:
    """Return an SVG body fragment with the component's CA grid drawn
    as filled hex cells in offset-r layout, scaled to fit a square
    of side 1.0 centred in [0, 1]×[0, 1].

    The grid is read at gen ``generation`` from the keystream module
    (so generation > 0 forces a full advance — fine for small N).
    """
    from spoeqi.models import Pact, COMPONENTS
    from spoeqi import keystream

    pact = Pact.objects.filter(slug=pact_slug).first()
    if pact is None:
        return _placeholder_text(f'pact "{pact_slug}" not found')
    if not 0 <= component < COMPONENTS:
        return _placeholder_text(
            f'component must be 0..{COMPONENTS - 1}, got {component}')

    side = pact.component_grid
    state = keystream.initial_multi_grid(pact)
    if generation > 0:
        state = keystream.advance(state, generation, pact)
    area = side * side
    base = component * area
    grid = state[base : base + area]

    # Per-component palette where available, else shared palette.
    palette = pact.palette
    pal = None
    if palette:
        # Per-component palette: list of 64 lists of 4 RGB triplets.
        try:
            first_inner = palette[0]
            if (isinstance(first_inner, (list, tuple))
                    and len(first_inner) > 0
                    and isinstance(first_inner[0], (list, tuple))
                    and len(first_inner[0]) == 3):
                pal = palette[component]
        except (IndexError, TypeError):
            pal = None
        if pal is None:
            pal = palette
    if not pal:
        pal = [[221, 221, 221], [236, 91, 58], [58, 126, 236], [58, 236, 116]]

    def rgb(c: int) -> str:
        r, g, b = pal[c & 3]
        return f'rgb({int(r)},{int(g)},{int(b)})'

    # Hex layout: pointy-top, offset-r.  Fit side×side cells in a
    # box of (1 - 2*padding) on each side, then translate to centre.
    box = 1.0 - 2 * padding
    # For pointy-top: hex radius R, column step = R·√3, row step = 1.5·R.
    # Total width  = side · R · √3 + R · √3 / 2 (odd-row shift).
    # Total height = (side - 1) · 1.5R + 2R.
    sqrt3 = math.sqrt(3.0)
    R = box / max(side * sqrt3 + sqrt3 / 2, (side - 1) * 1.5 + 2)
    col_step = R * sqrt3
    row_step = 1.5 * R
    total_w = side * col_step + col_step / 2
    total_h = (side - 1) * row_step + 2 * R
    origin_x = padding + (box - total_w) / 2 + col_step / 2
    origin_y = padding + (box - total_h) / 2 + R

    parts: List[str] = []
    parts.append(f'<g stroke="#0000" stroke-width="0.001">')
    for r in range(side):
        shift = (r & 1) * (col_step / 2)
        for c in range(side):
            cx = origin_x + c * col_step + shift
            cy = origin_y + r * row_step
            v = grid[r * side + c]
            color = rgb(int(v))
            # Pointy-top hex vertices clockwise from top.
            s32 = sqrt3 / 2.0
            pts = (
                (cx,             cy - R),
                (cx + R * s32,   cy - R / 2),
                (cx + R * s32,   cy + R / 2),
                (cx,             cy + R),
                (cx - R * s32,   cy + R / 2),
                (cx - R * s32,   cy - R / 2),
            )
            pts_str = ' '.join(f'{x:.4f},{y:.4f}' for (x, y) in pts)
            parts.append(f'<polygon points="{pts_str}" fill="{color}" />')
    parts.append('</g>')
    return ''.join(parts)


def _placeholder_text(msg: str) -> str:
    """Render an error placeholder inside the motif box so the user
    sees what went wrong without breaking the page.

    ``msg`` is HTML-escaped before insertion so any ``<``/``>`` /
    ``&`` characters in it (e.g. the literal text ``<slug>``) don't
    break SVG/XML parsers that consume this fragment.
    """
    import html
    return (
        '<rect x="0" y="0" width="1" height="1" '
        'fill="#fee" stroke="#c44" stroke-width="0.01" />'
        '<text x="0.05" y="0.5" '
        'font-family="ui-monospace,monospace" font-size="0.05" '
        f'fill="#a22">{html.escape(msg)}</text>'
    )
