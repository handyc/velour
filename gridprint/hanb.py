"""Hanb — a 'hexagon of 61 hexagons' tile (centered hexagonal number N=5).

Geometry choice:
  inner cells are pointy-top, hanb outline is a regular flat-top hex.
  R_hanb (circumradius) = (14*sqrt(3)/3) * R_cell ≈ 8.083 * R_cell
  hanb flat-to-flat (vertical for flat-top)   = 14 * R_cell
  hanb vertex-to-vertex (horizontal)          = (28*sqrt(3)/3) * R_cell

Why those numbers: the six corner cells of the 61-cell axial arrangement
(axial coords with max(|q|,|r|,|s|) ≤ 4) sit at distance 4*sqrt(3)*R_cell
from the hanb centre, at angles 0/60/120/180/240/300° — the flat-top
regular-hex vertex angles. Setting R_hanb = 14*sqrt(3)/3 * R_cell makes
the hanb's flat top/bottom edges pass through the top/bottom vertices of
the 5 outermost cells in those rows, so the outline is a tight regular
hex around the cells (with small empty wedges along the four slanted
edges — those are unavoidable when packing pointy-top cells into a
regular flat-top boundary).

Hanbs are then tiled across the page on a flat-top hex lattice, scaled
outward by k so adjacent hanbs are separated by gap_mm along every shared
flat-edge direction.
"""
from __future__ import annotations

import math
from typing import Iterator

from . import svg as gp_svg


SQRT3 = math.sqrt(3)
N = 5  # centered hex of side 5 → 1+6+12+18+24 = 61 cells
N_CELLS = 61
R_HANB_OVER_R_CELL = 14.0 * SQRT3 / 3.0  # ≈ 8.083


def hanb_cells() -> Iterator[tuple[int, int]]:
    """Yield the 61 axial (q, r) coords of the centered hex of side 5."""
    for q in range(-(N - 1), N):
        for r in range(-(N - 1), N):
            if abs(q + r) <= N - 1:
                yield (q, r)


def _pointy_cell_pixel(q: int, r: int, R: float) -> tuple[float, float]:
    """Pointy-top axial → pixel offset from hanb centre."""
    return (R * (SQRT3 * q + SQRT3 / 2.0 * r), R * 1.5 * r)


def _pointy_hex_pts(cx: float, cy: float, R: float):
    s = SQRT3 / 2.0
    return [(cx, cy - R), (cx + R * s, cy - R / 2),
            (cx + R * s, cy + R / 2), (cx, cy + R),
            (cx - R * s, cy + R / 2), (cx - R * s, cy - R / 2)]


def _flat_hex_pts(cx: float, cy: float, R: float):
    s = SQRT3 / 2.0
    return [(cx + R, cy), (cx + R / 2, cy + R * s),
            (cx - R / 2, cy + R * s), (cx - R, cy),
            (cx - R / 2, cy - R * s), (cx + R / 2, cy - R * s)]


def _poly(pts, style: gp_svg.Style) -> str:
    s = ' '.join(f'{x:.3f},{y:.3f}' for x, y in pts)
    return (f'<polygon points="{s}" fill="none" '
            f'stroke="{style.color}" '
            f'stroke-width="{style.width_mm:.3f}" '
            f'stroke-opacity="{style.alpha:.3f}" '
            f'stroke-linejoin="round" '
            f'vector-effect="non-scaling-stroke" />')


def hanb_size_mm(R_cell_mm: float) -> tuple[float, float]:
    """Return (width_mm, height_mm) of one flat-top hanb's axis-aligned
    bounding box for an inner-cell circumradius of ``R_cell_mm``."""
    R_hanb = R_cell_mm * R_HANB_OVER_R_CELL
    return (2.0 * R_hanb, R_hanb * SQRT3)


def draw_hanb(cx: float, cy: float, R_cell: float,
               cell_style: gp_svg.Style,
               outline_style: gp_svg.Style | None = None) -> str:
    """SVG fragment for one hanb centred at (cx, cy)."""
    R_hanb = R_cell * R_HANB_OVER_R_CELL
    parts: list[str] = []
    for (q, r) in hanb_cells():
        ox, oy = _pointy_cell_pixel(q, r, R_cell)
        parts.append(_poly(
            _pointy_hex_pts(cx + ox, cy + oy, R_cell), cell_style))
    parts.append(_poly(_flat_hex_pts(cx, cy, R_hanb),
                         outline_style or cell_style))
    return ''.join(parts)


def hanb_centres(page: gp_svg.Page, R_cell: float, gap_mm: float
                   ) -> list[tuple[float, float]]:
    """Return (cx, cy) centres for every flat-top hanb whose bounding box
    fully fits in the printable area, packed on a flat-top hex lattice
    with ``gap_mm`` between adjacent flat edges.

    Lattice math: standard flat-top hex lattice has col_step = 1.5*R_hanb
    and row_step = R_hanb*sqrt(3); neighbours sit at distance R_hanb*sqrt(3).
    Scaling positions by k = 1 + g/(R_hanb*sqrt(3)) keeps the hanbs the
    same size but pushes them apart by exactly ``g`` along every shared
    flat-edge axis (uniform gap on all six sides).
    """
    R_hanb = R_cell * R_HANB_OVER_R_CELL
    base_neighbour = R_hanb * SQRT3
    k = 1.0 + max(0.0, gap_mm) / max(base_neighbour, 1e-6)
    col_step = 1.5 * R_hanb * k
    row_step = R_hanb * SQRT3 * k

    cx0 = (page.left + page.right) / 2.0
    cy0 = (page.top + page.bottom) / 2.0
    half_w = R_hanb              # vertex distance horizontally (flat-top)
    half_h = R_hanb * SQRT3 / 2  # apothem vertically

    n_col = int(math.ceil((page.inner_w / 2.0 + R_hanb)
                            / max(col_step, 1e-6))) + 2
    n_row = int(math.ceil((page.inner_h / 2.0 + R_hanb)
                            / max(row_step, 1e-6))) + 2

    centres: list[tuple[float, float]] = []
    for col in range(-n_col, n_col + 1):
        for row in range(-n_row, n_row + 1):
            cx = cx0 + col * col_step
            cy = cy0 + row * row_step + (col & 1) * (row_step / 2.0)
            if (cx - half_w < page.left - 1e-6
                    or cx + half_w > page.right + 1e-6
                    or cy - half_h < page.top - 1e-6
                    or cy + half_h > page.bottom + 1e-6):
                continue
            centres.append((cx, cy))
    centres.sort(key=lambda p: (p[1], p[0]))
    return centres


def render_hanbs_svg(page: gp_svg.Page, R_cell: float, gap_mm: float,
                       cell_style: gp_svg.Style,
                       outline_style: gp_svg.Style | None = None
                       ) -> tuple[str, int]:
    """Build the SVG body for an A4 page packed with hanbs.

    Returns (svg_body_inner, n_hanbs) — wrap the body with the standard
    gridprint envelope (``svg._wrap``) to get a complete document.
    """
    centres = hanb_centres(page, R_cell, gap_mm)
    body = ''.join(draw_hanb(cx, cy, R_cell, cell_style, outline_style)
                   for (cx, cy) in centres)
    return body, len(centres)
