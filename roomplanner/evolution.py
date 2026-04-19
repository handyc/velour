"""A very small genetic algorithm that searches for lower-penalty
Placement layouts in a Room.

Design:
- A genome is a list of (placement_id, x_cm, y_cm, rotation_deg) tuples.
  Fixed Features (doors/windows/outlets) are NOT mutated.
- Candidates are scored via fitness.score_placements() using duck-typed
  _PseudoPlacement objects that mirror the fields the scorers read.
- Any candidate with overlapping furniture is disqualified (infinite
  penalty) so the GA never "solves" by stacking two pieces in one spot.
- Selection is k=3 tournament with top-20 % elitism.
- Mutation picks one operator per call: jitter / rotate90 / swap /
  random_relocate. Jitter is the high-probability local search move.

The engine never writes to the DB. Callers (the view or the management
command) read `best_placements` off the result and apply it themselves.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .fitness import any_overlap, overlapping_pairs, score_placements


# ---- duck-typed placement -------------------------------------------


class _PseudoPlacement:
    """Mirrors just enough of roomplanner.models.Placement for the
    fitness scorers to work without touching the DB."""

    __slots__ = ('id', 'piece', 'label', 'x_cm', 'y_cm', 'rotation_deg')

    def __init__(self, *, id, piece, label, x_cm, y_cm, rotation_deg):
        self.id = id
        self.piece = piece
        self.label = label
        self.x_cm = x_cm
        self.y_cm = y_cm
        self.rotation_deg = rotation_deg

    @property
    def footprint_cm(self) -> Tuple[int, int]:
        if self.rotation_deg in (90, 270):
            return (self.piece.depth_cm, self.piece.width_cm)
        return (self.piece.width_cm, self.piece.depth_cm)

    def clone(self) -> '_PseudoPlacement':
        return _PseudoPlacement(
            id=self.id, piece=self.piece, label=self.label,
            x_cm=self.x_cm, y_cm=self.y_cm,
            rotation_deg=self.rotation_deg,
        )


Candidate = List[_PseudoPlacement]   # list of PseudoPlacement


def _from_db(placement) -> _PseudoPlacement:
    return _PseudoPlacement(
        id=placement.id,
        piece=placement.piece,
        label=placement.label or placement.piece.name,
        x_cm=placement.x_cm,
        y_cm=placement.y_cm,
        rotation_deg=placement.rotation_deg,
    )


def _clone(cand: Candidate) -> Candidate:
    return [p.clone() for p in cand]


# ---- geometry helpers ------------------------------------------------


def _clamp(p: _PseudoPlacement, room) -> None:
    """Keep a placement inside the room given its current footprint."""
    w, h = p.footprint_cm
    max_x = max(0, room.width_cm - w)
    max_y = max(0, room.length_cm - h)
    if p.x_cm < 0:        p.x_cm = 0
    if p.y_cm < 0:        p.y_cm = 0
    if p.x_cm > max_x:    p.x_cm = max_x
    if p.y_cm > max_y:    p.y_cm = max_y


# ---- mutation operators ---------------------------------------------


def _mut_jitter(cand: Candidate, rng: random.Random, room,
                step_cm: int = 40) -> None:
    p = rng.choice(cand)
    dx = rng.randint(-step_cm, step_cm)
    dy = rng.randint(-step_cm, step_cm)
    p.x_cm = int(p.x_cm + dx)
    p.y_cm = int(p.y_cm + dy)
    _clamp(p, room)


def _mut_rotate90(cand: Candidate, rng: random.Random, room) -> None:
    p = rng.choice(cand)
    p.rotation_deg = (p.rotation_deg + 90) % 360
    # Snap only to cardinals.
    if p.rotation_deg not in (0, 90, 180, 270):
        p.rotation_deg = 0
    _clamp(p, room)


def _mut_swap(cand: Candidate, rng: random.Random, room) -> None:
    if len(cand) < 2:
        return _mut_jitter(cand, rng, room)
    a, b = rng.sample(cand, 2)
    a.x_cm, b.x_cm = b.x_cm, a.x_cm
    a.y_cm, b.y_cm = b.y_cm, a.y_cm
    _clamp(a, room)
    _clamp(b, room)


def _mut_relocate(cand: Candidate, rng: random.Random, room) -> None:
    p = rng.choice(cand)
    w, h = p.footprint_cm
    p.x_cm = rng.randint(0, max(0, room.width_cm - w))
    p.y_cm = rng.randint(0, max(0, room.length_cm - h))


def _mut_snap_wall(cand: Candidate, rng: random.Random, room) -> None:
    """Push one placement against its nearest wall. Real furniture tends
    to live along walls; this mutation accelerates layouts toward that
    attractor instead of the GA floating things in the middle."""
    p = rng.choice(cand)
    w, h = p.footprint_cm
    dx_left    = p.x_cm
    dx_right   = room.width_cm - (p.x_cm + w)
    dy_top     = p.y_cm
    dy_bottom  = room.length_cm - (p.y_cm + h)
    nearest = min(dx_left, dx_right, dy_top, dy_bottom)
    if nearest == dx_left:
        p.x_cm = 0
    elif nearest == dx_right:
        p.x_cm = max(0, room.width_cm - w)
    elif nearest == dy_top:
        p.y_cm = 0
    else:
        p.y_cm = max(0, room.length_cm - h)


_MUTATION_TABLE = [
    (0.40, _mut_jitter),
    (0.18, _mut_rotate90),
    (0.18, _mut_snap_wall),
    (0.14, _mut_swap),
    (0.10, _mut_relocate),
]


def _mutate(parent: Candidate, rng: random.Random, room) -> Candidate:
    child = _clone(parent)
    r = rng.random()
    acc = 0.0
    for prob, op in _MUTATION_TABLE:
        acc += prob
        if r <= acc:
            op(child, rng, room)
            return child
    _mut_jitter(child, rng, room)
    return child


# ---- scoring with disqualification ----------------------------------


OVERLAP_PENALTY = 10_000
OUT_OF_BOUNDS_PENALTY = 10_000


def _in_bounds(cand: Candidate, room) -> bool:
    for p in cand:
        w, h = p.footprint_cm
        if p.x_cm < 0 or p.y_cm < 0:
            return False
        if p.x_cm + w > room.width_cm or p.y_cm + h > room.length_cm:
            return False
    return True


def _score(cand: Candidate, room, features, constraints) -> int:
    if not _in_bounds(cand, room):
        return OUT_OF_BOUNDS_PENALTY
    if any_overlap(cand):
        return OVERLAP_PENALTY
    return score_placements(
        room, features=features, placements=cand, constraints=constraints,
    )['total']


# ---- main GA loop ---------------------------------------------------


@dataclass
class EvolveResult:
    initial_score: int
    best_score: int
    improvement: int
    generations: int
    population: int
    history: List[dict]
    best: Candidate
    # Red flag: the GA *tries* to drive overlap to zero, but a tiny room
    # plus too much furniture can leave every candidate overlapping. If
    # that happens, best.overlap is non-empty and apply_result() refuses
    # to write — the layout is "incompatible with reality".
    overlap: List[dict] = None

    @property
    def incompatible_with_reality(self) -> bool:
        return bool(self.overlap)

    def as_changes(self) -> List[dict]:
        """Placement updates the caller can feed straight into Placement.save."""
        out = []
        for p in self.best:
            w, h = p.footprint_cm
            out.append({
                'id':           p.id,
                'x_cm':         p.x_cm,
                'y_cm':         p.y_cm,
                'rotation_deg': p.rotation_deg,
                'w':            w,
                'h':            h,
                'label':        p.label,
            })
        return out


def evolve(
    room, *,
    generations: int = 30,
    population: int = 20,
    seed: Optional[int] = None,
    tournament_k: int = 3,
    elite_frac: float = 0.2,
) -> EvolveResult:
    rng = random.Random(seed)

    features   = list(room.features.all())
    constraints = list(room.constraints.filter(active=True))
    initial    = [_from_db(p) for p in
                  room.placements.select_related('piece').all()]
    if not initial:
        return EvolveResult(
            initial_score=0, best_score=0, improvement=0,
            generations=0, population=0, history=[], best=[],
        )

    initial_score = _score(initial, room, features, constraints)

    # Seed population: initial + mutated variants.
    pop: List[Candidate] = [initial]
    for _ in range(population - 1):
        pop.append(_mutate(initial, rng, room))

    elite_n = max(1, int(population * elite_frac))
    history: List[dict] = []
    best_cand = initial
    best_score = initial_score

    for gen in range(generations):
        scored: List[Tuple[int, Candidate]] = [
            (_score(c, room, features, constraints), c) for c in pop
        ]
        scored.sort(key=lambda t: t[0])
        if scored[0][0] < best_score:
            best_score, best_cand = scored[0]
        history.append({
            'gen':   gen,
            'best':  scored[0][0],
            'mean':  int(sum(s for s, _ in scored) / len(scored)),
        })

        # Elitism — carry top N forward unchanged.
        next_pop: List[Candidate] = [_clone(c) for _, c in scored[:elite_n]]
        # Fill by tournament + mutation.
        while len(next_pop) < population:
            contenders = rng.sample(scored, min(tournament_k, len(scored)))
            contenders.sort(key=lambda t: t[0])
            parent = contenders[0][1]
            next_pop.append(_mutate(parent, rng, room))
        pop = next_pop

    # One final scoring pass to pick up any late improvement.
    scored: List[Tuple[int, Candidate]] = [
        (_score(c, room, features, constraints), c) for c in pop
    ]
    scored.sort(key=lambda t: t[0])
    if scored[0][0] < best_score:
        best_score, best_cand = scored[0]

    return EvolveResult(
        initial_score=initial_score,
        best_score=best_score,
        improvement=initial_score - best_score,
        generations=generations,
        population=population,
        history=history,
        best=best_cand,
        overlap=overlapping_pairs(best_cand),
    )


def apply_result(room, result: EvolveResult) -> Dict[int, dict]:
    """Persist the best candidate back to the DB. Returns a map of
    placement_id → {x, y, rot, w, h, label} for the caller to echo.

    Refuses to write if the best candidate still has overlapping
    furniture — furniture can't physically occupy the same space, so
    persisting such an arrangement would be dishonest. Callers should
    check `result.incompatible_with_reality` first."""
    if result.incompatible_with_reality:
        return {}
    from .models import Placement
    touched: Dict[int, dict] = {}
    by_id = {p.id: p for p in result.best}
    for placement in Placement.objects.filter(id__in=by_id.keys()):
        pp = by_id[placement.id]
        placement.x_cm = pp.x_cm
        placement.y_cm = pp.y_cm
        placement.rotation_deg = pp.rotation_deg
        placement.save(update_fields=['x_cm', 'y_cm', 'rotation_deg'])
        w, h = pp.footprint_cm
        touched[placement.id] = {
            'id':    placement.id,
            'x':     placement.x_cm,
            'y':     placement.y_cm,
            'rot':   placement.rotation_deg,
            'w':     w,
            'h':     h,
            'label': placement.label or placement.piece.name,
        }
    return touched
