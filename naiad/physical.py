"""Physical layout for a Naiad System.

Each StageType has a (width_mm, depth_mm, height_mm) bounding box.
This module sums the per-stage volumes and shelf-packs them into
the inside of a 1 m³ cube using the same algorithm `nodes` uses
for the ESP carrying-case insert. The two questions the GA cares
about — "what's the total volume?" and "does it fit?" — fall out
of one pass.
"""

from __future__ import annotations

from dataclasses import dataclass

from nodes.carrying_case import pack_fleet


CUBE_MM = 1000  # default 1 m × 1 m × 1 m bounding cube
CUBE_LITRES = (CUBE_MM ** 3) / 1e6  # 1000 L for a 1 m³ cube


@dataclass
class _PackItem:
    label: str
    w: int
    d: int
    h: int


def chain_volume_litres(stage_types) -> float:
    """Bounding-box volume sum, in litres. The GA's volume metric:
    smaller is better, regardless of how a real assembly is packed."""
    return sum(st.volume_litres for st in stage_types)


def fits_in_cube(stage_types, cube_mm: int = CUBE_MM) -> bool:
    """True iff sum-of-bounding-box-volumes is below the cube's. A
    necessary but not sufficient condition — actual placement may
    still need clever stacking — but it's the right cap for scoring."""
    cube_l = (cube_mm ** 3) / 1e6
    return chain_volume_litres(stage_types) <= cube_l


def pack_chain(stage_types, cube_mm: int = CUBE_MM):
    """Shelf-pack `stage_types` into one floor of a cube_mm³ box.
    Items that don't fit on the single floor go into `.overflow` —
    in real life they'd be stacked on a second tier. Returns the
    PackResult from nodes.carrying_case.pack_fleet.
    """
    items = []
    for i, st in enumerate(stage_types):
        # Position prefix disambiguates repeated stages; templates
        # can strip it for display.
        items.append(_PackItem(
            label=f'{i:02d}:{st.slug}',
            w=int(st.width_mm or 0),
            d=int(st.depth_mm or 0),
            h=int(st.height_mm or 0),
        ))
    return pack_fleet(
        items, case_w_mm=cube_mm, case_d_mm=cube_mm, case_h_mm=cube_mm,
    )
