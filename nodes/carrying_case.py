"""Pack the ESP fleet into a carry-on cardboard insert.

The user's backlog: design a folded-cardboard insert with one
pocket per board so the whole fleet fits inside carry-on luggage.
This module is the layout half — given the case's interior
dimensions and the fleet's per-board dimensions, place each
pocket so they fit in a 2D grid with a small breathing-room
margin and the case's depth easily accommodates each board's
height.

The packing is intentionally simple: shelf-pack with rows.
Sort boards tallest-first by depth_mm, fill rows left-to-right
until the row would overflow the case width, then start a new
row at the previous row's bottom + the previous row's tallest
depth + margin. Same algorithm Knuth used in TeX for word
boxes, scaled down to a piece of cardboard.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MARGIN_MM = 5  # breathing room between pockets


@dataclass
class Pocket:
    label: str
    x_mm: int
    y_mm: int
    w_mm: int
    d_mm: int
    h_mm: int


@dataclass
class PackResult:
    case_w_mm: int
    case_d_mm: int
    case_h_mm: int
    pockets: list[Pocket]
    overflow: list[str]   # nicknames that didn't fit
    used_w_mm: int
    used_d_mm: int

    @property
    def fits(self) -> bool:
        return not self.overflow


def pack_fleet(items, case_w_mm: int, case_d_mm: int, case_h_mm: int,
               margin_mm: int = DEFAULT_MARGIN_MM) -> PackResult:
    """Lay out `items` (each must expose .label, .w, .d, .h in mm)
    into a case of given inside dimensions. Returns a PackResult
    with pocket positions + the list of items that overflowed."""
    # Sort by depth descending so each row's height is set by its
    # tallest board, minimising wasted vertical space.
    sorted_items = sorted(items, key=lambda i: (-i.d, -i.w))

    pockets: list[Pocket] = []
    overflow: list[str] = []
    cursor_x = margin_mm
    cursor_y = margin_mm
    row_max_d = 0
    used_w = 0

    for it in sorted_items:
        # Skip too-tall pockets (height = vertical depth into case).
        if it.h > case_h_mm:
            overflow.append(it.label)
            continue
        # Wrap to next row if this pocket would overflow case width.
        if cursor_x + it.w + margin_mm > case_w_mm and cursor_x > margin_mm:
            cursor_y += row_max_d + margin_mm
            cursor_x = margin_mm
            row_max_d = 0
        # Vertical overflow → can't fit at all.
        if cursor_y + it.d + margin_mm > case_d_mm:
            overflow.append(it.label)
            continue
        pockets.append(Pocket(
            label=it.label,
            x_mm=cursor_x, y_mm=cursor_y,
            w_mm=it.w, d_mm=it.d, h_mm=it.h,
        ))
        cursor_x += it.w + margin_mm
        if it.d > row_max_d:
            row_max_d = it.d
        if cursor_x > used_w:
            used_w = cursor_x

    used_d = (cursor_y + row_max_d) if pockets else 0
    return PackResult(
        case_w_mm=case_w_mm, case_d_mm=case_d_mm, case_h_mm=case_h_mm,
        pockets=pockets, overflow=overflow,
        used_w_mm=used_w, used_d_mm=used_d,
    )


def fleet_items(nodes):
    """Convert a queryset of Node rows into pack-ready items.
    Falls back to HardwareProfile defaults when the node carries
    no explicit dimensions."""
    @dataclass
    class _Item:
        label: str
        w: int
        d: int
        h: int

    items = []
    for n in nodes:
        hp = n.hardware_profile
        if hp is None:
            w, d, h = 28, 55, 15
        else:
            w, d, h = hp.width_mm, hp.depth_mm, hp.height_mm
        items.append(_Item(label=n.nickname or n.slug,
                           w=w, d=d, h=h))
    return items
