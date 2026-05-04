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

from .score import score_circuit


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
    # The mutation rate bumps to `restart_mutation_rate` for the next
    # `restart_burst` generations. Set stagnation_limit=0 to disable.
    #
    # 20 gens of stalling is the empirical sweet spot — short enough
    # to escape local optima, long enough that crossover gets to
    # explore around a good solution before the kick.
    stagnation_limit: int = 20
    restart_mutation_rate: float = 0.08
    restart_burst: int = 4


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


def random_individual(rng: random.Random, h: int, w: int,
                      density: float,
                      ports: list[dict[str, Any]]) -> list[list[int]]:
    g = _empty_grid(h, w)
    for y in range(h):
        for x in range(w):
            g[y][x] = 1 if rng.random() < density else 0
    _force_port_wires(g, ports)
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
                             hyper.init_density, ports)
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
                    rng, height, width, d, ports))
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
