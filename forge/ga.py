"""GA over forge circuit configurations.

Genome: a binary mask (wire vs empty) for the H×W grid. Heads/tails
are transient state that the simulator manages — they aren't part of
the genome. Port positions and target truth table are *fixed* across
the population.

  - Initial population: random binary masks at low density (~0.20).
  - Mutation: each cell flips with probability `mutation_rate`.
  - Crossover: 1-point row split (top from parent A, bottom from B).
  - Selection: tournament of size `tournament_k`.
  - Elitism: the best individual carries over unchanged each generation.

Fitness is the truth-table score from forge.score.score_circuit. Cells
where a port lives are forced to wire (1) so a port never sits on a
dead cell — otherwise random init guarantees most individuals couldn't
even receive an input pulse.

Returns a `Result` dict-like that the view can persist as an
EvolutionRun row.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from .glyph import score_circuit_glyph
from .score import score_circuit, score_circuit_analog


@dataclass
class Hyper:
    pop_size: int = 32
    generations: int = 30
    mutation_rate: float = 0.03
    crossover_rate: float = 0.85
    tournament_k: int = 3
    init_density: float = 0.20
    seed: int = 7
    elite: int = 1                # carry top-N over unchanged
    # Plateau-breaking — when the best fitness hasn't improved in
    # `stagnation_limit` gens, replace the non-elite portion of the
    # population with fresh random individuals at varied densities.
    stagnation_limit: int = 20
    restart_mutation_rate: float = 0.08
    restart_burst: int = 4
    # Smart-init — with `spine_prob`, each new random individual gets
    # a wire spine (color 1) along a hex shortest-path between one
    # random input port and one random output port. The intent was to
    # boost baseline connectivity, but empirically the shared spine
    # collapses population diversity faster than crossover can mix it
    # back, and benchmarks across AND/NAND/XOR/HALF_ADDER showed it
    # *hurt* convergence at 0.7. Default off; available as a knob for
    # experimentation. 0.2-0.3 might still be useful — the "some get
    # paths, most stay diverse" sweet spot.
    spine_prob: float = 0.0


def _empty_grid(h: int, w: int) -> list[list[int]]:
    return [[0] * w for _ in range(h)]


def _force_port_wires(grid: list[list[int]],
                      ports: list[dict[str, Any]]) -> None:
    """Mutate `grid` in place so every port cell is a wire (1)."""
    for p in ports:
        x, y = p['x'], p['y']
        if 0 <= y < len(grid) and 0 <= x < len(grid[0]):
            if grid[y][x] != 1:
                grid[y][x] = 1


# Hex neighbour offsets for the simulator's flat-top / offset-columns
# topology — must stay in lockstep with taxon.engine and forge/sim.py.
# Each tuple is (dr, dc); the order matches (N, NE, SE, S, SW, NW).
_HEX_NBRS_EVEN = [(-1, 0), (-1,  1), ( 0,  1), ( 1, 0), ( 0, -1), (-1, -1)]
_HEX_NBRS_ODD  = [(-1, 0), ( 0,  1), ( 1,  1), ( 1, 0), ( 1, -1), ( 0, -1)]


def hex_shortest_path(start_xy: tuple[int, int],
                      end_xy: tuple[int, int],
                      h: int, w: int) -> list[tuple[int, int]]:
    """BFS in the hex topology used by the simulator. start/end are
    (x, y) (column, row). Returns the path as a list of (x, y) cells
    including both endpoints, or [] if unreachable. The neighbour
    offsets match `forge/sim.py`'s convention exactly so a wire laid
    along this path actually conducts under the wireworld rule.
    """
    sx, sy = start_xy
    ex, ey = end_xy
    if not (0 <= sx < w and 0 <= sy < h
            and 0 <= ex < w and 0 <= ey < h):
        return []
    if (sx, sy) == (ex, ey):
        return [(sx, sy)]
    visited: dict[tuple[int, int], tuple[int, int] | None] = {(sy, sx): None}
    frontier: list[tuple[int, int]] = [(sy, sx)]
    while frontier:
        nxt: list[tuple[int, int]] = []
        for r, c in frontier:
            offs = _HEX_NBRS_EVEN if (c % 2 == 0) else _HEX_NBRS_ODD
            for dr, dc in offs:
                nr, nc = r + dr, c + dc
                if 0 <= nr < h and 0 <= nc < w and (nr, nc) not in visited:
                    visited[(nr, nc)] = (r, c)
                    if (nr, nc) == (ey, ex):
                        path = [(nc, nr)]
                        cur = visited[(nr, nc)]
                        while cur is not None:
                            path.append((cur[1], cur[0]))
                            cur = visited[cur]
                        return list(reversed(path))
                    nxt.append((nr, nc))
        frontier = nxt
    return []


def random_individual(rng: random.Random, h: int, w: int,
                      density: float,
                      ports: list[dict[str, Any]],
                      *, spine_prob: float = 0.0) -> list[list[int]]:
    g = _empty_grid(h, w)
    for y in range(h):
        for x in range(w):
            g[y][x] = 1 if rng.random() < density else 0
    _force_port_wires(g, ports)

    if spine_prob > 0 and rng.random() < spine_prob:
        inputs = [p for p in ports if p.get('role') == 'input']
        outputs = [p for p in ports if p.get('role') == 'output']
        if inputs and outputs:
            ip = rng.choice(inputs)
            op = rng.choice(outputs)
            path = hex_shortest_path((ip['x'], ip['y']),
                                     (op['x'], op['y']), h, w)
            for px, py in path:
                g[py][px] = 1
    return g


def mutate(rng: random.Random, grid: list[list[int]],
           rate: float, ports: list[dict[str, Any]]) -> list[list[int]]:
    h = len(grid)
    w = len(grid[0]) if h else 0
    out = [row.copy() for row in grid]
    for y in range(h):
        for x in range(w):
            if rng.random() < rate:
                out[y][x] = 1 - (out[y][x] & 1)
    _force_port_wires(out, ports)
    return out


def crossover(rng: random.Random,
              a: list[list[int]], b: list[list[int]],
              ports: list[dict[str, Any]]) -> list[list[int]]:
    h = len(a)
    if h <= 1:
        return [row.copy() for row in a]
    cut = rng.randint(1, h - 1)
    out = [row.copy() for row in a[:cut]] + [row.copy() for row in b[cut:]]
    _force_port_wires(out, ports)
    return out


def tournament(rng: random.Random,
               scored: list[tuple[float, list[list[int]]]],
               k: int) -> list[list[int]]:
    picks = rng.sample(scored, min(k, len(scored)))
    picks.sort(key=lambda t: -t[0])
    return picks[0][1]


def fitness(grid: list[list[int]], ports: list[dict[str, Any]],
            width: int, height: int, target: dict[str, Any]) -> float:
    """Dispatch to the right scorer based on target.kind.

    - logic   : truth-table evaluation (default for backward-compat).
    - analog  : rate-coded inputs/outputs, per-row absolute-error fitness.
    - glyph   : static Chamfer-distance match against a target letter
                from forge.glyph.GLYPH_GRIDS. Wireworld dynamics not
                run; the candidate's wire layout itself is the ink.
    """
    kind = (target.get('kind') or 'logic').lower()
    if kind == 'analog':
        res = score_circuit_analog(grid=grid, ports=ports,
                                   width=width, height=height, target=target)
    elif kind == 'glyph':
        res = score_circuit_glyph(grid=grid, ports=ports,
                                  width=width, height=height, target=target)
    else:
        res = score_circuit(grid=grid, ports=ports,
                            width=width, height=height, target=target)
    if not res.get('ok'):
        return 0.0
    return float(res.get('fitness', 0.0))


@dataclass
class Result:
    history: list[dict] = field(default_factory=list)   # per-gen stats
    best_grid: list[list[int]] = field(default_factory=list)
    best_fitness: float = 0.0
    final_pop_fitness: list[float] = field(default_factory=list)
    hyper: Hyper = field(default_factory=Hyper)


def run_ga(*, width: int, height: int,
           ports: list[dict[str, Any]],
           target: dict[str, Any],
           hyper: Hyper) -> Result:
    """Run the GA. Synchronous; expects to complete in a few seconds for
    16×16 / pop=32 / generations=30."""
    rng = random.Random(hyper.seed)

    # init pop
    pop = [random_individual(rng, height, width,
                             hyper.init_density, ports,
                             spine_prob=hyper.spine_prob)
           for _ in range(hyper.pop_size)]

    history: list[dict] = []
    overall_best_grid = pop[0]
    overall_best_fit = -1.0
    stagnation = 0
    burst_left = 0

    for gen in range(hyper.generations):
        scored = [(fitness(g, ports, width, height, target), g) for g in pop]
        scored.sort(key=lambda t: -t[0])
        best_fit = scored[0][0]
        mean_fit = sum(f for f, _ in scored) / len(scored)
        improved = best_fit > overall_best_fit + 1e-9
        if improved:
            overall_best_fit = best_fit
            overall_best_grid = [row.copy() for row in scored[0][1]]
            stagnation = 0
        else:
            stagnation += 1

        # Decide whether to fire a restart this generation.
        do_restart = (hyper.stagnation_limit > 0
                      and stagnation >= hyper.stagnation_limit
                      and overall_best_fit < 1.0 - 1e-9)

        history.append({
            'gen': gen, 'best': best_fit, 'mean': mean_fit,
            'min': scored[-1][0],
            'stagnation': stagnation,
            'restart': do_restart,
        })
        # Early stop on perfect score
        if overall_best_fit >= 1.0 - 1e-9:
            break

        # Effective mutation rate: bumped during the restart burst.
        cur_mut = (hyper.restart_mutation_rate
                   if (burst_left > 0 or do_restart)
                   else hyper.mutation_rate)
        if burst_left > 0:
            burst_left -= 1
        if do_restart:
            burst_left = hyper.restart_burst
            stagnation = 0

        new_pop: list[list[list[int]]] = []
        # Elitism: top `elite` always carry over (also seeds the restart).
        for i in range(min(hyper.elite, hyper.pop_size)):
            new_pop.append([row.copy() for row in scored[i][1]])

        if do_restart:
            # Replace the rest with fresh random individuals at varied
            # densities so the new pool spans high-wire and low-wire
            # individuals — the original init_density is kept for the
            # middle band.
            densities = [hyper.init_density * 0.5,
                         hyper.init_density,
                         hyper.init_density * 1.5,
                         min(0.5, hyper.init_density * 2.0)]
            d_i = 0
            while len(new_pop) < hyper.pop_size:
                d = densities[d_i % len(densities)]
                d_i += 1
                new_pop.append(random_individual(
                    rng, height, width, d, ports,
                    spine_prob=hyper.spine_prob))
        else:
            while len(new_pop) < hyper.pop_size:
                p1 = tournament(rng, scored, hyper.tournament_k)
                if rng.random() < hyper.crossover_rate:
                    p2 = tournament(rng, scored, hyper.tournament_k)
                    child = crossover(rng, p1, p2, ports)
                else:
                    child = [row.copy() for row in p1]
                child = mutate(rng, child, cur_mut, ports)
                new_pop.append(child)
        pop = new_pop

    final_fit = [fitness(g, ports, width, height, target) for g in pop]

    return Result(
        history=history,
        best_grid=overall_best_grid,
        best_fitness=overall_best_fit,
        final_pop_fitness=final_fit,
        hyper=hyper,
    )
