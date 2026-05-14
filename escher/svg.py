"""SVG rendering of a (wallpaper group, motif) composition.

The renderer takes:

  * an SVG snippet (the "motif", drawn in [0, 1]×[0, 1] motif units),
  * one of the 17 ``WallpaperGroup`` definitions,
  * a physical *tile size* (mm) — one lattice spacing along the
    group's first basis vector,
  * a viewport size (mm) — the page or preview box to fill.

It emits a self-contained SVG that tiles the motif according to the
group's orbit and lattice across the viewport.  The page is sized
in mm so the same output can drop into gridprint or be saved for
print at physical scale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List

from .groups import WallpaperGroup, Transform


@dataclass(frozen=True)
class RenderConfig:
    tile_mm: float = 30.0            # one motif unit in millimetres
    viewport_w_mm: float = 210.0
    viewport_h_mm: float = 297.0
    margin_mm: float = 10.0
    show_unit_cell: bool = False
    show_orbit: bool = False         # outline one full orbit
    background: str = '#ffffff'
    cell_stroke: str = '#cccccc'
    cell_dasharray: str = '0.5 0.5'


def _matrix_str(M, t, scale: float, ox: float, oy: float) -> str:
    """Compose the in-cell transform with a final mm scale + screen
    origin offset and emit an SVG ``matrix(...)`` string.  SVG
    matrices use ``(a, b, c, d, e, f)`` for the 2×3 affine

         | a c e |
         | b d f |

    applied as ``(x', y') = (a·x + c·y + e, b·x + d·y + f)``.  Note
    SVG's y axis points down; our motif y also points down, so we
    pass the matrix as-is without flipping.
    """
    a, b, c, d = M
    tx, ty = t
    # First apply the motif → in-cell affine (M, t), then scale by
    # ``tile_mm`` and shift by the screen origin.
    a *= scale; b *= scale; c *= scale; d *= scale
    tx_mm = tx * scale + ox
    ty_mm = ty * scale + oy
    return (f'matrix({a:.5f},{b:.5f},{c:.5f},{d:.5f},'
            f'{tx_mm:.5f},{ty_mm:.5f})')


def _lattice_extent(group: WallpaperGroup, *,
                     tile_mm: float,
                     w_mm: float, h_mm: float) -> List[tuple]:
    """Compute the integer lattice index pairs ``(i, j)`` such that
    ``i·a + j·b`` (scaled by ``tile_mm``) lands inside an inflated
    viewport box.  Inflation guards against rotated/reflected copies
    near the edge being cropped before SVG's clip-path catches them.
    """
    ax, ay = group.a
    bx, by = group.b
    # In mm:
    Ax, Ay = ax * tile_mm, ay * tile_mm
    Bx, By = bx * tile_mm, by * tile_mm
    # The lattice grid we need to enumerate must cover [-pad, w+pad] ×
    # [-pad, h+pad].  Find the corner (i, j) ranges by inverting the
    # 2×2 lattice matrix.
    det = Ax * By - Ay * Bx
    if abs(det) < 1e-9:
        # Degenerate basis (shouldn't happen for the 17 groups).
        return [(0, 0)]
    inv_a = (By, -Bx, -Ay, Ax)  # 1/det × this
    pad = tile_mm * 1.5
    corners = [(-pad, -pad), (w_mm + pad, -pad),
                (w_mm + pad, h_mm + pad), (-pad, h_mm + pad)]
    i_min = j_min =  10_000
    i_max = j_max = -10_000
    for cx, cy in corners:
        i = (inv_a[0] * cx + inv_a[1] * cy) / det
        j = (inv_a[2] * cx + inv_a[3] * cy) / det
        if i < i_min: i_min = int(math.floor(i)) - 1
        if i > i_max: i_max = int(math.ceil(i))  + 1
        if j < j_min: j_min = int(math.floor(j)) - 1
        if j > j_max: j_max = int(math.ceil(j))  + 1
    out = []
    for i in range(i_min, i_max + 1):
        for j in range(j_min, j_max + 1):
            out.append((i, j))
    return out


def render(group: WallpaperGroup, motif_svg: str,
            cfg: RenderConfig = RenderConfig(),
            *, embed: bool = False) -> str:
    """Render ``motif_svg`` tiled by ``group`` onto a page.

    Returns the full SVG document as a string.  When ``embed=True``
    the root element omits mm width/height so the SVG scales freely
    in whatever container hosts it (used by the live preview iframe).
    """
    w_mm = cfg.viewport_w_mm
    h_mm = cfg.viewport_h_mm
    margin = cfg.margin_mm
    tile = cfg.tile_mm

    # Each lattice point ``(i, j)`` produces ``len(group.orbit)`` motif
    # copies; we emit one ``<use href="#motif" transform="…"/>`` per copy.
    parts: List[str] = []
    parts.append(
        f'<rect x="0" y="0" width="{w_mm}" height="{h_mm}" '
        f'fill="{cfg.background}" />'
    )
    # Clip to the printable area minus the margin so motif copies that
    # spill outside the page edge are trimmed cleanly.
    parts.append(
        f'<defs><clipPath id="page-clip">'
        f'<rect x="{margin}" y="{margin}" '
        f'width="{w_mm - 2 * margin}" height="{h_mm - 2 * margin}" />'
        f'</clipPath>'
        f'<symbol id="motif" overflow="visible">{motif_svg}</symbol>'
        f'</defs>'
    )
    parts.append('<g clip-path="url(#page-clip)">')

    # The lattice grid sits with its origin at the top-left of the
    # printable area; users move the centre by editing margins.
    ox0 = margin
    oy0 = margin
    ax, ay = group.a
    bx, by = group.b
    indices = _lattice_extent(group, tile_mm=tile,
                                w_mm=w_mm, h_mm=h_mm)
    for i, j in indices:
        # World position of this unit cell's "origin" point.
        cell_ox = ox0 + (i * ax + j * bx) * tile
        cell_oy = oy0 + (i * ay + j * by) * tile
        for k, (M, t) in enumerate(group.orbit):
            mat = _matrix_str(M, t, tile, cell_ox, cell_oy)
            # Highlight one orbit (the centre cell) when requested.
            cls = ''
            if cfg.show_orbit and i == 0 and j == 0:
                cls = f' class="orbit-elem orbit-{k}"'
            parts.append(f'<use href="#motif" transform="{mat}"{cls} />')

    if cfg.show_unit_cell:
        parts.append('<g fill="none" stroke="' + cfg.cell_stroke +
                     '" stroke-width="0.2" stroke-dasharray="' +
                     cfg.cell_dasharray + '" '
                     'vector-effect="non-scaling-stroke">')
        # Draw the unit cells we enumerated.
        for i, j in indices:
            cell_ox = ox0 + (i * ax + j * bx) * tile
            cell_oy = oy0 + (i * ay + j * by) * tile
            # Polygon (0,0) → a → a+b → b → (0,0)
            p1 = (cell_ox, cell_oy)
            p2 = (cell_ox + ax * tile, cell_oy + ay * tile)
            p3 = (cell_ox + (ax + bx) * tile, cell_oy + (ay + by) * tile)
            p4 = (cell_ox + bx * tile, cell_oy + by * tile)
            parts.append(
                f'<polygon points="{p1[0]:.3f},{p1[1]:.3f} '
                f'{p2[0]:.3f},{p2[1]:.3f} '
                f'{p3[0]:.3f},{p3[1]:.3f} '
                f'{p4[0]:.3f},{p4[1]:.3f}" />'
            )
        parts.append('</g>')

    parts.append('</g>')

    dim_attr = '' if embed else f' width="{w_mm}mm" height="{h_mm}mm"'
    title = f'escher · {group.slug} · {group.note}'
    return (
        '<svg xmlns="http://www.w3.org/2000/svg"'
        f'{dim_attr}'
        f' viewBox="0 0 {w_mm} {h_mm}"'
        f' preserveAspectRatio="xMidYMid meet">'
        f'<title>{title}</title>'
        + ''.join(parts) +
        '</svg>'
    )


def render_thumbnail(group: WallpaperGroup, motif_svg: str,
                      *, size_mm: float = 60.0, tile_mm: float = 12.0) -> str:
    """A compact square preview used by the 17-group reference grid."""
    cfg = RenderConfig(
        tile_mm=tile_mm,
        viewport_w_mm=size_mm,
        viewport_h_mm=size_mm,
        margin_mm=1.0,
        show_unit_cell=False,
        background='#fafafa',
    )
    return render(group, motif_svg, cfg, embed=True)
