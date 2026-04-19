"""Scoring for a Room's layout against its active Constraints.

Each scorer reads the Room's features (doors, windows, outlets, …) and
placements (furniture) and returns a list of Violation dicts. A higher
total score is worse.

Violations are serialisable dicts so the view can hand them straight to
JSON and the editor can draw red overlays from the geometry.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple


# ---- rectangles (cm) --------------------------------------------------


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int
    label: str = ''

    @property
    def x2(self) -> int: return self.x + self.w
    @property
    def y2(self) -> int: return self.y + self.h
    @property
    def cx(self) -> float: return self.x + self.w / 2
    @property
    def cy(self) -> float: return self.y + self.h / 2


def _rect_from_placement(p) -> Rect:
    w, h = p.footprint_cm
    return Rect(p.x_cm, p.y_cm, w, h, label=p.label or p.piece.name)


def _rect_from_feature(f) -> Rect:
    return Rect(f.x_cm, f.y_cm, f.width_cm, f.depth_cm,
                label=f.label or f.get_kind_display())


def _rect_gap(a: Rect, b: Rect) -> float:
    """Shortest edge-to-edge distance between two AABBs (0 if overlapping)."""
    dx = max(0, max(a.x - b.x2, b.x - a.x2))
    dy = max(0, max(a.y - b.y2, b.y - a.y2))
    if dx == 0 and dy == 0:
        return 0.0
    return (dx * dx + dy * dy) ** 0.5


def _rect_inflate(r: Rect, by: int) -> Rect:
    """Grow a rect by `by` cm on each side (useful for clearance zones)."""
    return Rect(r.x - by, r.y - by, r.w + 2 * by, r.h + 2 * by, r.label)


def _rect_centre_distance(a: Rect, b: Rect) -> float:
    dx = a.cx - b.cx
    dy = a.cy - b.cy
    return (dx * dx + dy * dy) ** 0.5


# ---- violation dataclass ---------------------------------------------


@dataclass
class Violation:
    constraint_id: Optional[int]
    kind: str
    severity: int            # 1 = info, 2 = warn, 3 = blocker
    message: str
    zone: Optional[dict] = None      # {'x','y','w','h'} in cm, optional
    subjects: List[str] = field(default_factory=list)  # labels involved

    def to_dict(self):
        return asdict(self)


# ---- individual scorers ----------------------------------------------


def _score_egress(room, constraint, features, placements):
    """No placement may sit within `min_clearance_cm` of a door feature."""
    min_cm = int(constraint.value_json.get('min_clearance_cm', 80))
    door_kind = constraint.value_json.get('door_feature_kind', 'door')

    doors = [f for f in features if f.kind == door_kind]
    if not doors:
        return []

    out: List[Violation] = []
    for door in doors:
        d = _rect_from_feature(door)
        zone = _rect_inflate(d, min_cm)
        for p in placements:
            r = _rect_from_placement(p)
            if _rect_gap(r, d) < min_cm:
                out.append(Violation(
                    constraint_id=constraint.id, kind=constraint.kind,
                    severity=3,
                    message=(
                        f"'{r.label}' sits inside the {min_cm} cm egress zone "
                        f"for door '{d.label}'."
                    ),
                    zone={'x': zone.x, 'y': zone.y, 'w': zone.w, 'h': zone.h},
                    subjects=[r.label, d.label],
                ))
    return out


def _score_heat_spacing(room, constraint, features, placements):
    """Heat-producing pieces must sit ≥min_spacing_cm from flammable shelves."""
    min_cm = int(constraint.value_json.get('min_spacing_cm', 30))
    # Heat source kinds default to aquarium + lightbox + rack; flammable
    # targets default to shelf + cabinet (wooden furniture).
    src_kinds = set(constraint.value_json.get(
        'source_kinds', ['aquarium', 'lightbox', 'rack'],
    ))
    tgt_kinds = set(constraint.value_json.get(
        'target_kinds', ['shelf', 'cabinet'],
    ))

    sources = [p for p in placements
               if p.piece.heat_watts > 0 or p.piece.kind in src_kinds]
    targets = [p for p in placements if p.piece.kind in tgt_kinds]

    out: List[Violation] = []
    for s in sources:
        sr = _rect_from_placement(s)
        for t in targets:
            if t.id == s.id:
                continue
            tr = _rect_from_placement(t)
            gap = _rect_gap(sr, tr)
            if gap < min_cm:
                out.append(Violation(
                    constraint_id=constraint.id, kind=constraint.kind,
                    severity=2,
                    message=(
                        f"'{sr.label}' ({s.piece.heat_watts} W heat source) "
                        f"is {gap:.0f} cm from '{tr.label}' — need ≥{min_cm} cm."
                    ),
                    subjects=[sr.label, tr.label],
                ))
    return out


def _score_outlet_near(room, constraint, features, placements):
    """Powered pieces must be within max_cable_cm of any outlet feature."""
    max_cm = int(constraint.value_json.get('max_cable_cm', 200))
    outlets = [f for f in features if f.kind == 'outlet']
    if not outlets:
        return []

    outlet_rects = [_rect_from_feature(o) for o in outlets]
    out: List[Violation] = []
    for p in placements:
        if not p.piece.needs_outlet:
            continue
        r = _rect_from_placement(p)
        # centre-to-centre to the nearest outlet — rough cable estimate
        nearest = min(_rect_centre_distance(r, o) for o in outlet_rects)
        if nearest > max_cm:
            out.append(Violation(
                constraint_id=constraint.id, kind=constraint.kind,
                severity=2,
                message=(
                    f"'{r.label}' needs power; nearest outlet is "
                    f"{nearest:.0f} cm away (limit {max_cm} cm)."
                ),
                subjects=[r.label],
            ))
    return out


def _score_walkway(room, constraint, features, placements):
    """Any two adjacent (within 5*min_cm) placements must have ≥min_cm gap."""
    min_cm = int(constraint.value_json.get('min_cm', 90))
    neighbour_cutoff = 5 * min_cm

    out: List[Violation] = []
    seen = set()
    for i, p in enumerate(placements):
        for q in placements[i + 1:]:
            pr = _rect_from_placement(p)
            qr = _rect_from_placement(q)
            centre = _rect_centre_distance(pr, qr)
            if centre > neighbour_cutoff:
                continue
            gap = _rect_gap(pr, qr)
            if 0 < gap < min_cm:
                key = tuple(sorted([pr.label, qr.label]))
                if key in seen:
                    continue
                seen.add(key)
                out.append(Violation(
                    constraint_id=constraint.id, kind=constraint.kind,
                    severity=1,
                    message=(
                        f"walkway between '{pr.label}' and '{qr.label}' is "
                        f"only {gap:.0f} cm — want ≥{min_cm} cm."
                    ),
                    subjects=[pr.label, qr.label],
                ))
    return out


def _score_wall_clearance(room, constraint, features, placements):
    """Keep a clearance band in front of e.g. a radiator feature."""
    min_cm = int(constraint.value_json.get('min_clearance_cm', 20))
    src_kind = constraint.value_json.get('source_feature_kind', 'radiator')

    sources = [f for f in features if f.kind == src_kind]
    if not sources:
        return []

    out: List[Violation] = []
    for f in sources:
        fr = _rect_from_feature(f)
        zone = _rect_inflate(fr, min_cm)
        for p in placements:
            r = _rect_from_placement(p)
            if _rect_gap(r, fr) < min_cm:
                out.append(Violation(
                    constraint_id=constraint.id, kind=constraint.kind,
                    severity=2,
                    message=(
                        f"'{r.label}' blocks clearance in front of "
                        f"'{fr.label}' ({src_kind})."
                    ),
                    zone={'x': zone.x, 'y': zone.y, 'w': zone.w, 'h': zone.h},
                    subjects=[r.label, fr.label],
                ))
    return out


SCORERS = {
    'egress':         _score_egress,
    'heat_spacing':   _score_heat_spacing,
    'outlet_near':    _score_outlet_near,
    'walkway':        _score_walkway,
    'wall_clearance': _score_wall_clearance,
}


# ---- top-level -------------------------------------------------------


def score_placements(room, features, placements, constraints) -> dict:
    """Score an arbitrary set of placements (real or duck-typed) against
    the given features + constraints. The GA calls this directly on
    in-memory candidates without touching the DB."""
    all_violations: List[Violation] = []
    per_constraint = []

    for c in constraints:
        fn = SCORERS.get(c.kind)
        if fn is None:
            per_constraint.append({
                'id': c.id, 'kind': c.kind, 'description': c.description,
                'violations': 0, 'note': 'no scorer for this kind',
            })
            continue
        vs = fn(room, c, features, placements)
        all_violations.extend(vs)
        per_constraint.append({
            'id': c.id, 'kind': c.kind, 'description': c.description,
            'violations': len(vs),
        })

    total = sum(v.severity for v in all_violations)
    verdict = (
        'clean'         if total == 0 else
        'minor issues'  if total < 4  else
        'needs work'    if total < 10 else
        'unsafe'
    )
    return {
        'total':        total,
        'verdict':      verdict,
        'violations':   [v.to_dict() for v in all_violations],
        'per_constraint': per_constraint,
    }


def score_room(room) -> dict:
    return score_placements(
        room,
        features=list(room.features.all()),
        placements=list(room.placements.select_related('piece').all()),
        constraints=list(room.constraints.filter(active=True)),
    )


# ---- helpers the GA needs too ---------------------------------------

def any_overlap(placements) -> bool:
    """True if any two placement AABBs overlap (positive-area intersection).
    Touching edges don't count. Used by the GA to reject impossible layouts."""
    rects = [(_rect_from_placement(p), p) for p in placements]
    for i, (a, _) in enumerate(rects):
        for b, _ in rects[i + 1:]:
            dx = min(a.x2, b.x2) - max(a.x, b.x)
            dy = min(a.y2, b.y2) - max(a.y, b.y)
            if dx > 0 and dy > 0:
                return True
    return False
