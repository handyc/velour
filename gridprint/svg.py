"""Pure SVG generators for tessellated graph paper.

Every public function returns an SVG string sized to one A4 sheet
(210 × 297 mm) and clipped to a printable area inset by the margin.
Designed so the same code path covers the unfilled "graph paper"
case and the cell-fill case (e.g. a 16×16 hex CA snapshot).

Coordinate system: SVG userspace mm. y points down. All sizes
expressed in millimeters so the page prints at physical scale on
any DPI.

The generator's contract: outline strokes always hit the same edges
across adjacent cells. To keep alpha-stacked edges from showing as
double-darkened, prefer fully-opaque strokes (ALPHA defaults to 1.0
and the user adjusts the colour itself for "50% gray").
"""
from __future__ import annotations

import math
from dataclasses import dataclass


# A4 portrait dimensions in millimeters
A4_W = 210.0
A4_H = 297.0


@dataclass(frozen=True)
class Style:
    color: str = '#888888'   # 50% gray default
    width_mm: float = 0.20   # 0.2mm = a thin pen line at 100% scale
    alpha: float = 1.0
    fill_alpha: float = 0.85   # used only when filling cells from a CA

    def stroke_attrs(self) -> str:
        return (f'stroke="{self.color}" '
                f'stroke-width="{self.width_mm:.3f}" '
                f'stroke-opacity="{self.alpha:.3f}" '
                f'fill="none" '
                f'stroke-linecap="round" '
                f'stroke-linejoin="round" '
                f'vector-effect="non-scaling-stroke"')


@dataclass(frozen=True)
class Page:
    w_mm: float = A4_W
    h_mm: float = A4_H
    margin_mm: float = 10.0

    @property
    def left(self) -> float:    return self.margin_mm
    @property
    def right(self) -> float:   return self.w_mm - self.margin_mm
    @property
    def top(self) -> float:     return self.margin_mm
    @property
    def bottom(self) -> float:  return self.h_mm - self.margin_mm
    @property
    def inner_w(self) -> float: return self.right - self.left
    @property
    def inner_h(self) -> float: return self.bottom - self.top


def _wrap(body: str, page: Page, *, title: str = '',
          show_border: bool = False,
          with_dimensions: bool = True) -> str:
    """Wrap a body of SVG elements in the A4 envelope, clipped to the
    printable area.

    When ``with_dimensions`` is True the root <svg> carries explicit
    mm width/height so it prints at physical scale. When False, only
    the viewBox is set so the SVG scales freely to whatever container
    embeds it — what we want for the in-page preview iframe.
    """
    border = (
        f'<rect x="{page.left}" y="{page.top}" '
        f'width="{page.inner_w}" height="{page.inner_h}" '
        f'fill="none" stroke="#cccccc" stroke-width="0.1" '
        f'stroke-dasharray="0.6 0.6" />'
    ) if show_border else ''
    dims = (f' width="{page.w_mm}mm" height="{page.h_mm}mm"'
            if with_dimensions else '')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f'{dims}'
        f' viewBox="0 0 {page.w_mm} {page.h_mm}"'
        f' preserveAspectRatio="xMidYMid meet">'
        f'<title>{title}</title>'
        f'<defs><clipPath id="page-area">'
        f'<rect x="{page.left}" y="{page.top}" '
        f'width="{page.inner_w}" height="{page.inner_h}" />'
        f'</clipPath></defs>'
        f'<g clip-path="url(#page-area)">{body}</g>'
        f'{border}'
        f'</svg>'
    )


def _polygon(points, fill: str | None, style: Style) -> str:
    pts = ' '.join(f'{x:.3f},{y:.3f}' for (x, y) in points)
    if fill:
        return (f'<polygon points="{pts}" '
                f'fill="{fill}" fill-opacity="{style.fill_alpha:.3f}" '
                f'stroke="{style.color}" '
                f'stroke-width="{style.width_mm:.3f}" '
                f'stroke-opacity="{style.alpha:.3f}" '
                f'stroke-linejoin="round" '
                f'vector-effect="non-scaling-stroke" />')
    return (f'<polygon points="{pts}" {style.stroke_attrs()} />')


def _line(x1, y1, x2, y2, style: Style) -> str:
    return (f'<line x1="{x1:.3f}" y1="{y1:.3f}" '
            f'x2="{x2:.3f}" y2="{y2:.3f}" {style.stroke_attrs()} />')


# ---------------------------------------------------------------------------
# Square grid
# ---------------------------------------------------------------------------

def square_grid(*, page: Page, cell_mm: float, style: Style,
                fill: list[list[str]] | None = None,
                with_dimensions: bool = True) -> str:
    """Square grid lines. If `fill` is given (rows of rgb/hex strings),
    paints each cell first. Empty string in `fill` means "leave blank"."""
    pieces: list[str] = []
    if fill:
        rows = len(fill)
        cols = max(len(r) for r in fill) if fill else 0
        ox = page.left + (page.inner_w - cols * cell_mm) / 2.0
        oy = page.top + (page.inner_h - rows * cell_mm) / 2.0
        for r, row in enumerate(fill):
            for c, color in enumerate(row):
                if not color:
                    continue
                x = ox + c * cell_mm
                y = oy + r * cell_mm
                pieces.append(
                    f'<rect x="{x:.3f}" y="{y:.3f}" '
                    f'width="{cell_mm:.3f}" height="{cell_mm:.3f}" '
                    f'fill="{color}" '
                    f'fill-opacity="{style.fill_alpha:.3f}" '
                    f'stroke="none" />'
                )
    # Vertical lines spanning the printable height
    x = page.left
    while x <= page.right + 1e-6:
        pieces.append(_line(x, page.top, x, page.bottom, style))
        x += cell_mm
    # Horizontal lines spanning the printable width
    y = page.top
    while y <= page.bottom + 1e-6:
        pieces.append(_line(page.left, y, page.right, y, style))
        y += cell_mm
    return _wrap(''.join(pieces), page, title='Square grid',
                 with_dimensions=with_dimensions)


# ---------------------------------------------------------------------------
# Hex grid (pointy-top + flat-top)
# ---------------------------------------------------------------------------

def _pointy_hex_vertices(cx: float, cy: float, R: float) -> list[tuple]:
    """Pointy-top hex: vertex at top + bottom; angles 30,90,150,210,270,330.
    Returns the 6 vertices in clockwise order starting from the top."""
    sqrt3_2 = math.sqrt(3) / 2
    return [
        (cx,            cy - R),
        (cx + R*sqrt3_2, cy - R/2),
        (cx + R*sqrt3_2, cy + R/2),
        (cx,            cy + R),
        (cx - R*sqrt3_2, cy + R/2),
        (cx - R*sqrt3_2, cy - R/2),
    ]


def _flat_hex_vertices(cx: float, cy: float, R: float) -> list[tuple]:
    """Flat-top hex: vertex on the left + right; angles 0,60,120,180,240,300."""
    sqrt3_2 = math.sqrt(3) / 2
    return [
        (cx + R,        cy),
        (cx + R/2,      cy + R*sqrt3_2),
        (cx - R/2,      cy + R*sqrt3_2),
        (cx - R,        cy),
        (cx - R/2,      cy - R*sqrt3_2),
        (cx + R/2,      cy - R*sqrt3_2),
    ]


def hex_grid(*, page: Page, side_mm: float, style: Style,
             pointy_top: bool = True,
             fill: list[list[str]] | None = None,
             with_dimensions: bool = True) -> str:
    """Hex tessellation. `side_mm` is the hex circumradius (= side length).

    fill, if given, is a 2D array of CSS colour strings (or '' for blank).
    Pointy-top fill: rows index varies fastest along the row axis.
    Flat-top fill: rows index along columns. The fill is centered on the
    printable area; grid lines extend across the full printable area.
    """
    R = side_mm
    sqrt3 = math.sqrt(3)

    if pointy_top:
        # Adjacent column step: R*sqrt3 horizontal; row step: 1.5R vertical;
        # odd rows offset by R*sqrt3/2 horizontally.
        col_step = R * sqrt3
        row_step = 1.5 * R
        # First, compute the full grid of hex centers that intersect the
        # printable area (including a margin so partial hexes still render
        # fully — they get clipped by the SVG clip path).
        margin_R = R * 1.2
        first_col = math.floor((page.left  - margin_R) / col_step) - 1
        last_col  = math.ceil((page.right + margin_R) / col_step) + 1
        first_row = math.floor((page.top    - margin_R) / row_step) - 1
        last_row  = math.ceil((page.bottom + margin_R) / row_step) + 1
        centers = []
        for row in range(first_row, last_row + 1):
            for col in range(first_col, last_col + 1):
                cx = col * col_step + (row & 1) * (col_step / 2)
                cy = row * row_step
                centers.append((row, col, cx, cy))
    else:
        # Flat-top: column step = 1.5R; row step = R*sqrt3; odd cols
        # offset by R*sqrt3/2 vertically.
        col_step = 1.5 * R
        row_step = R * sqrt3
        margin_R = R * 1.2
        first_col = math.floor((page.left  - margin_R) / col_step) - 1
        last_col  = math.ceil((page.right + margin_R) / col_step) + 1
        first_row = math.floor((page.top    - margin_R) / row_step) - 1
        last_row  = math.ceil((page.bottom + margin_R) / row_step) + 1
        centers = []
        for col in range(first_col, last_col + 1):
            for row in range(first_row, last_row + 1):
                cx = col * col_step
                cy = row * row_step + (col & 1) * (row_step / 2)
                centers.append((row, col, cx, cy))

    pieces: list[str] = []

    # Build a fill-color map keyed on (logical_row, logical_col) when fill
    # provided. Logical coordinates are normalized so the fill block sits
    # near the page center.
    fill_map: dict[tuple[int, int], str] = {}
    if fill:
        rows = len(fill)
        cols = max(len(r) for r in fill) if fill else 0
        # Centre the fill block around the page midpoint.
        mid_cx = (page.left + page.right) / 2.0
        mid_cy = (page.top + page.bottom) / 2.0
        if pointy_top:
            block_w = cols * (R * sqrt3) + (R * sqrt3 / 2 if rows > 1 else 0)
            block_h = (rows - 1) * 1.5 * R + 2 * R
            ox = mid_cx - block_w / 2 + (R * sqrt3) / 2
            oy = mid_cy - block_h / 2 + R
        else:
            block_w = (cols - 1) * 1.5 * R + 2 * R
            block_h = rows * (R * sqrt3) + (R * sqrt3 / 2 if cols > 1 else 0)
            ox = mid_cx - block_w / 2 + R
            oy = mid_cy - block_h / 2 + (R * sqrt3) / 2
        # Find the (row, col) integer pair whose computed center is closest
        # to (ox, oy); use that as the offset for the fill grid origin.
        best = None
        best_d = 1e18
        for (r, c, cx, cy) in centers:
            d = (cx - ox) ** 2 + (cy - oy) ** 2
            if d < best_d:
                best_d, best = d, (r, c, cx, cy)
        if best is not None:
            r0, c0, _, _ = best
            for ir in range(rows):
                for ic in range(len(fill[ir])):
                    fill_map[(r0 + ir, c0 + ic)] = fill[ir][ic]

    vertex_fn = _pointy_hex_vertices if pointy_top else _flat_hex_vertices
    for (row, col, cx, cy) in centers:
        verts = vertex_fn(cx, cy, R)
        color = fill_map.get((row, col), '')
        pieces.append(_polygon(verts, color or None, style))

    return _wrap(''.join(pieces), page,
                 title='Hex grid (pointy-top)' if pointy_top
                 else 'Hex grid (flat-top)',
                 with_dimensions=with_dimensions)


# ---------------------------------------------------------------------------
# Triangle grid (equilateral)
# ---------------------------------------------------------------------------

def triangle_grid(*, page: Page, side_mm: float, style: Style,
                  with_dimensions: bool = True) -> str:
    """Equilateral triangle grid drawn as 3 sets of parallel lines.

    Lines are emitted long and clipped by the page area's clipPath so we
    don't have to compute exact line/rect intersections."""
    sqrt3 = math.sqrt(3)
    h = side_mm * sqrt3 / 2     # row height

    pieces: list[str] = []
    # Stretch line endpoints well beyond the printable area so the
    # clip-path handles the cropping. SVG renders are happy with this.
    far = max(page.w_mm, page.h_mm) * 2

    # Set 1: horizontal lines at y = k*h
    y = page.top - h
    while y <= page.bottom + h:
        pieces.append(_line(-far, y, far, y, style))
        y += h

    # Set 2: lines at +60° (slope = +sqrt3 in math coords, +sqrt3 down-right
    # in screen coords since y inverts sign — actually in screen coords y
    # increases downward, so a "+60° from horizontal going up-right" line
    # has slope dy/dx = -tan(60°) = -sqrt3. We want a family of parallel
    # lines spaced `side_mm` apart along the x-axis at fixed y.
    # Parametrise as x = x0 + y/sqrt3 (slope dx/dy = 1/sqrt3), every x0.
    x0 = page.left - page.inner_h / sqrt3 - side_mm
    x0_end = page.right + side_mm
    while x0 <= x0_end:
        pieces.append(_line(
            x0, page.top - 1,
            x0 + (page.bottom - page.top + 2) / sqrt3,
            page.bottom + 1, style))
        x0 += side_mm

    # Set 3: lines at -60° (mirror image). x = x0 - y/sqrt3.
    x0 = page.left - side_mm
    x0_end = page.right + page.inner_h / sqrt3 + side_mm
    while x0 <= x0_end:
        pieces.append(_line(
            x0, page.top - 1,
            x0 - (page.bottom - page.top + 2) / sqrt3,
            page.bottom + 1, style))
        x0 += side_mm

    return _wrap(''.join(pieces), page, title='Triangle grid',
                 with_dimensions=with_dimensions)


# ---------------------------------------------------------------------------
# Rhombus grid (60° / 120° diamonds)
# ---------------------------------------------------------------------------

def rhombus_grid(*, page: Page, side_mm: float, style: Style,
                 with_dimensions: bool = True) -> str:
    """60° rhombus tessellation drawn as 2 sets of parallel lines:
    horizontals + 60° diagonals. Each tile is a 60°-120° rhombus."""
    sqrt3 = math.sqrt(3)
    h = side_mm * sqrt3 / 2

    pieces: list[str] = []
    # Horizontal lines
    y = page.top - h
    while y <= page.bottom + h:
        pieces.append(_line(page.left - 1, y, page.right + 1, y, style))
        y += h

    # 60° lines (steep): x = x0 + y/sqrt3, spacing side_mm in x.
    x0 = page.left - page.inner_h / sqrt3 - side_mm
    x0_end = page.right + side_mm
    while x0 <= x0_end:
        pieces.append(_line(
            x0, page.top - 1,
            x0 + (page.bottom - page.top + 2) / sqrt3,
            page.bottom + 1, style))
        x0 += side_mm

    return _wrap(''.join(pieces), page, title='Rhombus grid (60°)',
                 with_dimensions=with_dimensions)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

PATTERNS = {
    'square':        ('Square',                square_grid),
    'hex_pointy':    ('Hex (pointy-top)',      lambda **kw: hex_grid(pointy_top=True, **kw)),
    'hex_flat':      ('Hex (flat-top)',        lambda **kw: hex_grid(pointy_top=False, **kw)),
    'triangle':      ('Triangle',              triangle_grid),
    'rhombus':       ('Rhombus (60°)',         rhombus_grid),
}


def render(pattern: str, *, page: Page, cell_mm: float,
           style: Style, fill: list[list[str]] | None = None,
           with_dimensions: bool = True) -> str:
    """One-stop entry point used by the view."""
    try:
        _, fn = PATTERNS[pattern]
    except KeyError:
        raise ValueError(f'unknown pattern: {pattern}')
    common = {'page': page, 'style': style,
              'with_dimensions': with_dimensions}
    # Triangle and rhombus don't accept fill yet (no natural cell shape
    # in the line-set rendering).
    if pattern in ('triangle', 'rhombus'):
        return fn(side_mm=cell_mm, **common)
    if pattern == 'square':
        return fn(cell_mm=cell_mm, fill=fill, **common)
    return fn(side_mm=cell_mm, fill=fill, **common)
