"""caframe Phase 2 — evolve (rule, seed) toward "watchable" video.

Fitness combines two competing pressures:

  consistency  — fraction of cells unchanged frame-to-frame.
                  We want > target_min (~0.7) so the video isn't
                  pure noise.
  edge_activity — fraction of cells changed per step.
                  We want it close to target_edge (~0.15) so the
                  video isn't dead static.

Composite: maximise consistency BUT penalise distance from
target_edge. A pure static rule (0% activity) gets penalised; a
random-soup rule gets penalised harder.

The genome is just (rule_seed, init_seed) — two 32-bit ints. Tiny
search space, easy to evolve.  We don't evolve the rule_table
directly because at K=4 hex with 16,384 LUT entries the byte-mutation
rate that GA needs would be incompatible with caframe's "rule
discovered from a seed" recipe philosophy (every Sequence is a 8-byte
recipe in essence).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np


@dataclass
class CaframeGenome:
    rule_seed: int
    init_seed: int


def _genome_to_frames(g: CaframeGenome, *, w: int, h: int, n_frames: int):
    from caformer.primitives import random_rule_table
    from .render import iter_frames
    rule = bytes(random_rule_table(g.rule_seed))
    return list(iter_frames(rule_genome=rule, seed=g.init_seed,
                              w=w, h=h, n_frames=n_frames, shape='hex'))


def consistency_fitness(g: CaframeGenome, *,
                          w: int = 32, h: int = 32, n_frames: int = 16,
                          target_consistency: float = 0.85,
                          target_edge: float = 0.15,
                          edge_weight: float = 1.0) -> float:
    """Higher = better.  In [-1, 1] roughly.

    Reward consistency above target, penalise edge_activity drift
    from target.  Computed on a single (rule, seed) pair → one short
    video render.
    """
    from .render import consistency_score, edge_activity
    frames = _genome_to_frames(g, w=w, h=h, n_frames=n_frames)
    cons = consistency_score(frames)
    edge = edge_activity(frames)
    # Reward consistency monotonically, with a soft cap at target.
    cons_score = min(cons, target_consistency) / max(0.001, target_consistency)
    # Penalise distance from target_edge linearly (clipped).
    edge_pen = abs(edge - target_edge) * edge_weight
    return float(cons_score - edge_pen)


def evolve_video(*, n_gen: int = 8, pop_size: int = 12,
                  w: int = 32, h: int = 32, n_frames: int = 16,
                  seed: int = 0xCA1FA,
                  target_consistency: float = 0.85,
                  target_edge: float = 0.15,
                  on_individual=None, on_generation=None
                  ) -> Tuple[CaframeGenome, float, List[Tuple[float, float, float]]]:
    """Tiny GA over (rule_seed, init_seed) tuples for caframe.

    No crossover (the genome is too small for it to mean anything);
    pure mutation: each generation N children = small perturbation of
    a tournament-selected parent. Elite-1 carry-over.
    """
    rng = np.random.default_rng(seed)
    pop = [
        CaframeGenome(
            rule_seed=int(rng.integers(0, 1 << 31)),
            init_seed=int(rng.integers(0, 1 << 31)),
        )
        for _ in range(pop_size)
    ]
    history = []
    best_g, best_s = pop[0], -float('inf')
    for gen in range(n_gen):
        scored = []
        for i, g in enumerate(pop):
            s = consistency_fitness(g, w=w, h=h, n_frames=n_frames,
                target_consistency=target_consistency,
                target_edge=target_edge)
            scored.append((s, g))
            if s > best_s:
                best_s = s; best_g = g
            if on_individual is not None:
                on_individual(gen, i, s)
        scored.sort(key=lambda sg: -sg[0])
        scores = [s for s, _ in scored]
        history.append((scores[0], float(np.mean(scores)), scores[-1]))
        if on_generation is not None:
            on_generation(gen, scores[0], float(np.mean(scores)), scores[-1])
        # Breed: elite + tournament-selected mutants.
        next_pop = [scored[0][1]]
        while len(next_pop) < pop_size:
            tourney = [scored[int(rng.integers(0, len(scored)))]
                        for _ in range(3)]
            tourney.sort(key=lambda sg: -sg[0])
            parent = tourney[0][1]
            kid = CaframeGenome(
                rule_seed=(parent.rule_seed
                            ^ int(rng.integers(0, 1 << 16))) & 0x7FFFFFFF,
                init_seed=(parent.init_seed
                            ^ int(rng.integers(0, 1 << 16))) & 0x7FFFFFFF,
            )
            next_pop.append(kid)
        pop = next_pop
    return best_g, best_s, history
