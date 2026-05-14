"""The 17 plane symmetry groups (wallpaper groups).

Each ``WallpaperGroup`` carries:

* ``slug`` / ``name`` — the conventional IUC label (p1, p4m, …) and a
  short human description.
* ``lattice`` — the kind of unit cell: ``'parallelogram'``,
  ``'rectangle'``, ``'rhombus'``, ``'square'``, or ``'hex'``.
* ``a``, ``b`` — basis vectors (in motif units) that span the unit cell.
* ``orbit`` — the list of in-cell affine transforms applied to the
  motif to fill one unit cell.  When the renderer tiles the plane it
  translates each orbit element by every lattice point ``(i·a + j·b)``.

Each affine transform is a 3-tuple ``(M, t)`` where ``M`` is a 2×2
matrix (rotation / reflection / shear) and ``t`` is the in-cell
translation, all in *motif units* — the motif lives in [0, 1]×[0, 1]
of its fundamental domain.  The renderer composes these with the
lattice translation and the chosen physical tile size in mm.

Reference for the orbit lists: Coxeter & Moser, *Generators and
Relations for Discrete Groups* — the listed transforms below are the
standard right-coset representatives of each group's translation
lattice.  Compact orbit sizes by lattice kind:

* p1 (1), p2 (2), pm (2), pg (2), cm (2), pmm (4), pmg (4), pgg (4),
  cmm (4), p4 (4), p4m (8), p4g (8), p3 (3), p3m1 (6), p31m (6),
  p6 (6), p6m (12).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

Mat = Tuple[float, float, float, float]   # (a, b, c, d) for [[a,b],[c,d]]
Vec = Tuple[float, float]


def _id() -> Mat:           return (1.0, 0.0, 0.0, 1.0)
def _rot(deg: float) -> Mat:
    th = math.radians(deg)
    c, s = math.cos(th), math.sin(th)
    return (c, -s, s, c)
def _flip_x() -> Mat:       return (-1.0, 0.0, 0.0, 1.0)   # mirror across x-axis (in plane: flip x → -x, keep y)
def _flip_y() -> Mat:       return (1.0, 0.0, 0.0, -1.0)
def _flip_xy() -> Mat:      return (0.0, 1.0, 1.0, 0.0)    # mirror across y=x
def _flip_nxy() -> Mat:     return (0.0, -1.0, -1.0, 0.0)  # mirror across y=-x


def _mm(M: Mat, N: Mat) -> Mat:
    a, b, c, d = M
    e, f, g, h = N
    return (a*e + b*g, a*f + b*h,
            c*e + d*g, c*f + d*h)


# An "in-cell transform" pairs a 2×2 matrix with a translation that
# returns the transformed motif back inside the unit cell [0,1]².
# Together, the orbit lists below produce exactly one unit cell of
# the tiling when applied to a motif drawn in the fundamental domain.
Transform = Tuple[Mat, Vec]


@dataclass(frozen=True)
class WallpaperGroup:
    slug: str
    name: str
    note: str                 # one-line description of the symmetry
    lattice: str
    a: Vec
    b: Vec
    orbit: List[Transform]

    @property
    def orbit_size(self) -> int:
        return len(self.orbit)


# Shorthands for unit-cell offsets.
_h = (0.5, 0.0)
_v = (0.0, 0.5)
_hv = (0.5, 0.5)


# ─── Oblique lattice (p1, p2) ────────────────────────────────────────

P1 = WallpaperGroup(
    slug='p1', name='p1', note='translation only',
    lattice='parallelogram',
    a=(1.0, 0.0), b=(0.25, 1.0),
    orbit=[(_id(), (0.0, 0.0))],
)

P2 = WallpaperGroup(
    slug='p2', name='p2', note='180° rotation centres',
    lattice='parallelogram',
    a=(1.0, 0.0), b=(0.25, 1.0),
    orbit=[
        (_id(),       (0.0, 0.0)),
        (_rot(180),   (1.25, 1.0)),     # rotation centre at mid of unit cell
    ],
)


# ─── Rectangular lattice (pm, pg, pmm, pmg, pgg) ─────────────────────

PM = WallpaperGroup(
    slug='pm', name='pm', note='parallel mirror lines',
    lattice='rectangle',
    a=(1.0, 0.0), b=(0.0, 1.0),
    orbit=[
        (_id(),    (0.0, 0.0)),
        (_flip_x(),(1.0, 0.0)),         # mirror across the vertical axis x=0.5
    ],
)

PG = WallpaperGroup(
    slug='pg', name='pg', note='parallel glide reflections',
    lattice='rectangle',
    a=(1.0, 0.0), b=(0.0, 1.0),
    orbit=[
        (_id(),     (0.0, 0.0)),
        (_flip_x(), (1.0, 0.5)),        # glide: flip + translate half-period in y
    ],
)

PMM = WallpaperGroup(
    slug='pmm', name='pmm', note='two perpendicular mirror lines',
    lattice='rectangle',
    a=(1.0, 0.0), b=(0.0, 1.0),
    orbit=[
        (_id(),       (0.0, 0.0)),
        (_flip_x(),   (1.0, 0.0)),
        (_flip_y(),   (0.0, 1.0)),
        (_rot(180),   (1.0, 1.0)),
    ],
)

PMG = WallpaperGroup(
    slug='pmg', name='pmg', note='mirror + perpendicular glide',
    lattice='rectangle',
    a=(1.0, 0.0), b=(0.0, 1.0),
    orbit=[
        (_id(),       (0.0, 0.0)),
        (_flip_x(),   (1.0, 0.0)),
        (_rot(180),   (1.0, 0.5)),      # half-cell rotation centre
        (_flip_y(),   (0.0, 0.5)),
    ],
)

PGG = WallpaperGroup(
    slug='pgg', name='pgg', note='two perpendicular glide axes',
    lattice='rectangle',
    a=(1.0, 0.0), b=(0.0, 1.0),
    orbit=[
        (_id(),       (0.0, 0.0)),
        (_rot(180),   (1.0, 1.0)),
        (_flip_x(),   (1.0, 0.5)),
        (_flip_y(),   (0.5, 1.0)),
    ],
)


# ─── Rhombic / centred lattice (cm, cmm) ─────────────────────────────
# Conventionally drawn with basis (1,0) and (1/2, h); the centred
# rectangle of size 1×2h is the conventional cell.

CM_H = 1.0
CM = WallpaperGroup(
    slug='cm', name='cm', note='mirror + parallel glide (centred)',
    lattice='rhombus',
    a=(1.0, 0.0), b=(0.5, CM_H),
    orbit=[
        (_id(),     (0.0, 0.0)),
        (_flip_x(), (1.0, 0.0)),
    ],
)

CMM = WallpaperGroup(
    slug='cmm', name='cmm', note='two mirrors meeting at 90° (centred)',
    lattice='rhombus',
    a=(1.0, 0.0), b=(0.5, CM_H),
    orbit=[
        (_id(),       (0.0, 0.0)),
        (_flip_x(),   (1.0, 0.0)),
        (_flip_y(),   (0.0, CM_H)),
        (_rot(180),   (1.0, CM_H)),
    ],
)


# ─── Square lattice (p4, p4m, p4g) ───────────────────────────────────

P4 = WallpaperGroup(
    slug='p4', name='p4', note='90° rotation centres',
    lattice='square',
    a=(1.0, 0.0), b=(0.0, 1.0),
    orbit=[
        (_id(),     (0.0, 0.0)),
        (_rot(90),  (1.0, 0.0)),
        (_rot(180), (1.0, 1.0)),
        (_rot(270), (0.0, 1.0)),
    ],
)

P4M = WallpaperGroup(
    slug='p4m', name='p4m', note='90° rotations + mirrors',
    lattice='square',
    a=(1.0, 0.0), b=(0.0, 1.0),
    orbit=[
        (_id(),                          (0.0, 0.0)),
        (_flip_xy(),                     (0.0, 0.0)),
        (_rot(90),                       (1.0, 0.0)),
        (_mm(_rot(90),   _flip_xy()),    (1.0, 0.0)),
        (_rot(180),                      (1.0, 1.0)),
        (_mm(_rot(180),  _flip_xy()),    (1.0, 1.0)),
        (_rot(270),                      (0.0, 1.0)),
        (_mm(_rot(270),  _flip_xy()),    (0.0, 1.0)),
    ],
)

P4G = WallpaperGroup(
    slug='p4g', name='p4g', note='90° rotations + glide diagonals',
    lattice='square',
    a=(1.0, 0.0), b=(0.0, 1.0),
    orbit=[
        (_id(),                       (0.0, 0.0)),
        (_rot(90),                    (1.0, 0.0)),
        (_rot(180),                   (1.0, 1.0)),
        (_rot(270),                   (0.0, 1.0)),
        (_flip_xy(),                  (0.5, 0.5)),         # diagonal mirror centred
        (_mm(_rot(90), _flip_xy()),   (1.5, 0.5)),
        (_mm(_rot(180), _flip_xy()),  (1.5, 1.5)),
        (_mm(_rot(270), _flip_xy()),  (0.5, 1.5)),
    ],
)


# ─── Hexagonal lattice (p3, p3m1, p31m, p6, p6m) ─────────────────────
# Conventional basis: a = (1, 0), b = (1/2, √3/2) so the rhombic unit
# cell contains 2 triangles.

_HEX_H = math.sqrt(3) / 2.0

P3 = WallpaperGroup(
    slug='p3', name='p3', note='120° rotation centres',
    lattice='hex',
    a=(1.0, 0.0), b=(0.5, _HEX_H),
    orbit=[
        (_id(),     (0.0, 0.0)),
        (_rot(120), (1.0, 0.0)),
        (_rot(240), (1.5, _HEX_H)),
    ],
)

P3M1 = WallpaperGroup(
    slug='p3m1', name='p3m1', note='120° + mirrors through rotation centres',
    lattice='hex',
    a=(1.0, 0.0), b=(0.5, _HEX_H),
    orbit=[
        (_id(),                       (0.0, 0.0)),
        (_rot(120),                   (1.0, 0.0)),
        (_rot(240),                   (1.5, _HEX_H)),
        (_flip_y(),                   (0.0, _HEX_H)),
        (_mm(_rot(120),  _flip_y()),  (1.0, _HEX_H)),
        (_mm(_rot(240),  _flip_y()),  (1.5, 2 * _HEX_H)),
    ],
)

P31M = WallpaperGroup(
    slug='p31m', name='p31m', note='120° + mirrors between rotation centres',
    lattice='hex',
    a=(1.0, 0.0), b=(0.5, _HEX_H),
    orbit=[
        (_id(),                         (0.0, 0.0)),
        (_rot(120),                     (1.0, 0.0)),
        (_rot(240),                     (1.5, _HEX_H)),
        (_flip_xy(),                    (0.0, 0.0)),
        (_mm(_rot(120),  _flip_xy()),   (1.0, 0.0)),
        (_mm(_rot(240),  _flip_xy()),   (1.5, _HEX_H)),
    ],
)

P6 = WallpaperGroup(
    slug='p6', name='p6', note='60° rotation centres',
    lattice='hex',
    a=(1.0, 0.0), b=(0.5, _HEX_H),
    orbit=[
        (_id(),     (0.0, 0.0)),
        (_rot(60),  (1.0, 0.0)),
        (_rot(120), (1.0, 0.0)),
        (_rot(180), (1.5, _HEX_H)),
        (_rot(240), (1.5, _HEX_H)),
        (_rot(300), (0.5, _HEX_H)),
    ],
)

P6M = WallpaperGroup(
    slug='p6m', name='p6m', note='60° rotations + mirrors (full hex symmetry)',
    lattice='hex',
    a=(1.0, 0.0), b=(0.5, _HEX_H),
    orbit=[
        (_id(),                          (0.0, 0.0)),
        (_rot(60),                       (1.0, 0.0)),
        (_rot(120),                      (1.0, 0.0)),
        (_rot(180),                      (1.5, _HEX_H)),
        (_rot(240),                      (1.5, _HEX_H)),
        (_rot(300),                      (0.5, _HEX_H)),
        (_flip_xy(),                     (0.0, 0.0)),
        (_mm(_rot(60),  _flip_xy()),     (1.0, 0.0)),
        (_mm(_rot(120), _flip_xy()),     (1.0, 0.0)),
        (_mm(_rot(180), _flip_xy()),     (1.5, _HEX_H)),
        (_mm(_rot(240), _flip_xy()),     (1.5, _HEX_H)),
        (_mm(_rot(300), _flip_xy()),     (0.5, _HEX_H)),
    ],
)


# Canonical order used by the index page and tests.
GROUPS: List[WallpaperGroup] = [
    P1, P2, PM, PG, CM, PMM, PMG, PGG, CMM,
    P4, P4M, P4G,
    P3, P3M1, P31M, P6, P6M,
]
GROUPS_BY_SLUG = {g.slug: g for g in GROUPS}


def get(slug: str) -> WallpaperGroup:
    """Return a group by slug.  Raises ``KeyError`` for unknown slugs."""
    return GROUPS_BY_SLUG[slug]
