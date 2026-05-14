"""7→1 hex-flower dump of a hex-CA rule.

A 4-state hex CA with 6 neighbours + self consumes a 7-cell input
and emits one 4-state output, so the rule is a function from the
14-bit key

    (self << 12) | (n0 << 10) | (n1 << 8) | (n2 << 6)
                 | (n3 << 4)  | (n4 << 2) |  n5

to a 2-bit value, packed as a 16,384-byte table.  That's a lot of
flowers; this module lays them out in a regular grid on A4 with one
*hex flower of 7 small hexes* + one larger *result hex* per
configuration.

Neighbour order matches the Velour offset-r convention used
throughout spoeqi / det / automaton:

    n5    n0
      \\  /
   n4-- C --n1
      /  \\
    n3    n2

i.e. {TL, TR, R, BR, BL, L} at angles {120°, 60°, 0°, -60°, -120°, 180°}.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Sequence


# Default A4 layout — flowers are small enough that a portrait page fits
# ~120 of them comfortably with room for a key label under each.
DEFAULT_FLOWERS_PER_PAGE = 128
RULE_TABLE_SIZE         = 16384       # 4^7
N_STATES                = 4


# ─── Geometry helpers ──────────────────────────────────────────────

def _hex_vertices(cx: float, cy: float, r: float,
                   pointy_top: bool = True) -> List[tuple[float, float]]:
    """Six vertices of a hex centred at (cx, cy) with circumradius r.
    Pointy-top by default (matches gridprint's hex_pointy)."""
    if pointy_top:
        # vertices at 30°, 90°, 150°, 210°, 270°, 330°
        angles = [math.pi / 2 + i * math.pi / 3 for i in range(6)]
    else:
        # flat-top: vertices at 0°, 60°, 120°, …
        angles = [i * math.pi / 3 for i in range(6)]
    return [(cx + r * math.cos(a), cy - r * math.sin(a)) for a in angles]


# Neighbour direction angles (degrees → radians) in offset-r order:
# n0=TR, n1=R, n2=BR, n3=BL, n4=L, n5=TL.
_NEIGHBOUR_ANGLES_DEG = (60, 0, -60, -120, 180, 120)


def _neighbour_offset(r_hex: float, idx: int) -> tuple[float, float]:
    """Return (dx, dy) — in pixel space, y pointing *down* — for
    neighbour ``idx`` in the offset-r flower layout."""
    a = math.radians(_NEIGHBOUR_ANGLES_DEG[idx])
    # In a flower of pointy-top hexes the neighbour-to-neighbour spacing
    # is r * sqrt(3).  But for a *visual* flower we want the neighbours
    # snug against the centre — share an edge — which means each
    # neighbour's centre lies on a circle of radius r * sqrt(3).
    d = r_hex * math.sqrt(3)
    return (d * math.cos(a), -d * math.sin(a))


# ─── Rule iteration ────────────────────────────────────────────────

def unpack_key(k: int) -> tuple[int, int, int, int, int, int, int]:
    """14-bit key → (self, n0, n1, n2, n3, n4, n5)."""
    return (
        (k >> 12) & 3,
        (k >> 10) & 3,
        (k >>  8) & 3,
        (k >>  6) & 3,
        (k >>  4) & 3,
        (k >>  2) & 3,
         k        & 3,
    )


def pack_key(self_: int, n: Sequence[int]) -> int:
    """Inverse of unpack_key; ``n`` is the 6-tuple (n0..n5)."""
    if len(n) != 6:
        raise ValueError('neighbour tuple must have 6 entries')
    k = (self_ & 3) << 12
    for i, v in enumerate(n):
        k |= (v & 3) << (10 - 2 * i)
    return k


# ─── SVG render ────────────────────────────────────────────────────

@dataclass
class FlowerStyle:
    palette: List[str]      # 4 CSS colour strings indexed by state
    border_color: str = '#444444'
    border_width: float = 0.10        # mm
    cell_r: float = 1.6               # mm — input hex circumradius
    result_r: float = 2.4             # mm — output hex circumradius
    show_key: bool = True
    key_font_size: float = 1.6        # mm
    label_color: str = '#888888'


@dataclass(frozen=True)
class FlowerLayout:
    cell_w_mm: float           # one flower's bounding box width
    cell_h_mm: float           # ...height
    inner_gap_mm: float        # gap between flower and result inside one cell
    cell_padding_mm: float     # margin between flower cells in the grid


def default_layout() -> FlowerLayout:
    return FlowerLayout(
        cell_w_mm=22.0, cell_h_mm=14.0,
        inner_gap_mm=2.0, cell_padding_mm=1.0)


def _hex_svg(cx: float, cy: float, r: float, fill: str,
              border: str, border_w: float,
              pointy_top: bool = True) -> str:
    pts = _hex_vertices(cx, cy, r, pointy_top=pointy_top)
    d = ' '.join(f'{x:.3f},{y:.3f}' for x, y in pts)
    return (f'<polygon points="{d}" fill="{fill}" '
            f'stroke="{border}" stroke-width="{border_w:.3f}" '
            f'stroke-linejoin="round" />')


def _flower_svg(x: float, y: float, key: int, output: int,
                 style: FlowerStyle, layout: FlowerLayout) -> str:
    """Render one flower cell at (x, y) top-left.  Lays the input
    flower on the left half and the result hex on the right."""
    self_, *neighbours = unpack_key(key)
    # Centre of the input flower — left half of the cell.
    flower_cx = x + 5.0
    flower_cy = y + layout.cell_h_mm / 2
    # Result hex sits to the right.
    result_cx = x + layout.cell_w_mm - layout.result_r if False else \
                x + 15.0
    result_cy = flower_cy
    pieces: list[str] = []
    # Centre cell first (under the neighbours visually).
    pieces.append(_hex_svg(flower_cx, flower_cy, style.cell_r,
                            fill=style.palette[self_],
                            border=style.border_color,
                            border_w=style.border_width))
    # 6 neighbours.
    for i, v in enumerate(neighbours):
        dx, dy = _neighbour_offset(style.cell_r, i)
        pieces.append(_hex_svg(flower_cx + dx, flower_cy + dy,
                                style.cell_r,
                                fill=style.palette[v],
                                border=style.border_color,
                                border_w=style.border_width))
    # Arrow → between flower and result.
    arrow_x1 = flower_cx + 4.5
    arrow_x2 = result_cx - style.result_r - 0.6
    pieces.append(
        f'<line x1="{arrow_x1:.3f}" y1="{flower_cy:.3f}" '
        f'x2="{arrow_x2:.3f}" y2="{flower_cy:.3f}" '
        f'stroke="#888888" stroke-width="0.20" '
        f'marker-end="url(#arrow)" />')
    # Result hex.
    pieces.append(_hex_svg(result_cx, result_cy, style.result_r,
                            fill=style.palette[output],
                            border=style.border_color,
                            border_w=style.border_width))
    # Key label under the flower (optional).
    if style.show_key:
        label = f'{key:04x}'
        pieces.append(
            f'<text x="{x + layout.cell_w_mm / 2:.3f}" '
            f'y="{y + layout.cell_h_mm - 0.5:.3f}" '
            f'font-family="ui-monospace,monospace" '
            f'font-size="{style.key_font_size:.2f}" fill="{style.label_color}" '
            f'text-anchor="middle">{label}</text>')
    return ''.join(pieces)


@dataclass
class PageSummary:
    page_index:        int
    flowers_per_page:  int
    total_flowers:     int    # after filtering
    first_key:         int
    last_key:          int
    rule_hash_short:   str    # first 16 hex chars of SHA-256(rule_bytes), for the footer


def render_flowers_svg(rule_bytes: bytes, *,
                        palette: List[str],
                        page_w_mm: float, page_h_mm: float,
                        margin_mm: float = 10.0,
                        flowers_per_page: int = DEFAULT_FLOWERS_PER_PAGE,
                        page_index: int = 0,
                        center_filter: int | None = None,
                        style: FlowerStyle | None = None,
                        layout: FlowerLayout | None = None,
                        title_text: str | None = None
                        ) -> tuple[str, PageSummary]:
    """Render one A4 page of flowers from a hex-CA rule.

    rule_bytes: 16,384 bytes; rule_bytes[key] is the output (0..3) for
                that neighbourhood configuration.  Bytes outside 0..3
                are masked.
    palette:    4-entry list of CSS colour strings.
    center_filter: if 0..3, only show configurations where self_==K.

    Returns (svg_body, summary).  The caller wraps it in an outer
    <svg> envelope (see views.grid_svg).
    """
    if len(rule_bytes) != RULE_TABLE_SIZE:
        raise ValueError(
            f'rule_bytes must be exactly {RULE_TABLE_SIZE} bytes; '
            f'got {len(rule_bytes)}')
    if len(palette) != N_STATES:
        raise ValueError(f'palette must have {N_STATES} entries; '
                         f'got {len(palette)}')
    if not 1 <= flowers_per_page <= 1024:
        raise ValueError('flowers_per_page must be 1..1024')
    if center_filter is not None and not 0 <= center_filter <= 3:
        raise ValueError('center_filter must be in 0..3 or None')

    style = style or FlowerStyle(palette=palette)
    style.palette = palette
    layout = layout or default_layout()

    # Filter keys by centre colour if requested.
    if center_filter is None:
        keys = range(RULE_TABLE_SIZE)
    else:
        # Keys whose top 2 bits are center_filter — block of 4096.
        base = center_filter << 12
        keys = range(base, base + 4096)
    keys = list(keys)
    total = len(keys)
    start = page_index * flowers_per_page
    if start >= total:
        start = max(0, total - flowers_per_page)
    end = min(total, start + flowers_per_page)
    page_keys = keys[start:end]

    # Grid layout of cells inside the printable area.
    inner_w = page_w_mm - 2 * margin_mm
    inner_h = page_h_mm - 2 * margin_mm
    cw = layout.cell_w_mm + layout.cell_padding_mm
    ch = layout.cell_h_mm + layout.cell_padding_mm
    cols = max(1, int(inner_w // cw))
    rows = max(1, int(inner_h // ch))
    capacity = cols * rows
    if len(page_keys) > capacity:
        page_keys = page_keys[:capacity]

    # Define the arrowhead marker once at the top of the body.
    defs = (
        '<defs>'
        '<marker id="arrow" viewBox="0 0 6 6" refX="5" refY="3" '
        'markerWidth="3" markerHeight="3" orient="auto">'
        '<path d="M 0 0 L 6 3 L 0 6 z" fill="#888888" />'
        '</marker>'
        '</defs>'
    )
    pieces: List[str] = [defs]

    if title_text:
        pieces.append(
            f'<text x="{margin_mm:.2f}" y="{margin_mm - 2:.2f}" '
            f'font-family="ui-monospace,monospace" font-size="3" '
            f'fill="#555">{title_text}</text>')

    # Lay out flowers.
    for i, k in enumerate(page_keys):
        row = i // cols
        col = i % cols
        x = margin_mm + col * cw
        y = margin_mm + row * ch
        out = rule_bytes[k] & 3
        pieces.append(_flower_svg(x, y, k, out, style, layout))

    # Footer: rule fingerprint + page counter so the page can be
    # cross-referenced with a pact / det candidate.
    import hashlib
    rule_hash = hashlib.sha256(rule_bytes).hexdigest()[:16]
    n_pages = math.ceil(total / flowers_per_page) if total else 1
    footer = (
        f'<text x="{margin_mm:.2f}" y="{page_h_mm - 2:.2f}" '
        f'font-family="ui-monospace,monospace" font-size="2.4" '
        f'fill="#888">'
        f'rule {rule_hash}…   '
        f'page {page_index + 1}/{n_pages}   '
        f'flowers {start}..{end - 1} of {total}'
        + (f'   centre={center_filter}' if center_filter is not None else '')
        + '</text>'
    )
    pieces.append(footer)

    summary = PageSummary(
        page_index=page_index,
        flowers_per_page=flowers_per_page,
        total_flowers=total,
        first_key=page_keys[0] if page_keys else 0,
        last_key=page_keys[-1] if page_keys else 0,
        rule_hash_short=rule_hash,
    )
    return ''.join(pieces), summary


def wrap_page(body: str, page_w_mm: float, page_h_mm: float,
              with_dimensions: bool = True) -> str:
    dims = (f' width="{page_w_mm}mm" height="{page_h_mm}mm"'
            if with_dimensions else '')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f'{dims}'
        f' viewBox="0 0 {page_w_mm} {page_h_mm}"'
        f' preserveAspectRatio="xMidYMid meet">'
        f'<title>Hex flower dump</title>'
        f'{body}'
        f'</svg>'
    )
