"""(μ + λ) GA over stack genomes.

Genome shape from genome.py; fitness from fitness.py.  Mutation
only (no crossover for now — gene structure mixes integers with
tuples-of-ints, crossover is fiddly and the architecture is
exploratory enough that we want clean attribution per mutation).

Elitism: keep top `elite_n` from each generation unchanged into
the next.  The other `pop_size - elite_n` slots are children of
top-half parents.

Persistent `pool_cache` is threaded through every fitness eval
so the upcast_7to1_to_cell8 work is amortized — most mutations
touch a small subset of rule_idx entries, so re-evaluating a
mutated child mostly reuses the parent's upcasted LUTs.
"""
from __future__ import annotations

import random
import time
from typing import Dict, List

from .fitness import evaluate
from .genome import (random_genome, mutate_genome,
                          naive_pipeline_genome, echo_seed_genome)
from .population import pool_size


SEED_INIT_FNS = {
    'random':         random_genome,
    'naive_pipeline': naive_pipeline_genome,
    'echo':           echo_seed_genome,
}


def evolve_stack(*,
                     n_boards: int = 16,
                     board_side: int = 32,
                     stack_ticks: int = 4,
                     test_set: str = 'v1',
                     personality: int = 0,
                     pop_size: int = 16,
                     elite_n: int = 2,
                     generations: int = 30,
                     mutation_rate: float = 0.10,
                     seed: int = 0xB05ACE,
                     seed_init: str = 'random',
                     on_event=None) -> dict:
    """Run a (μ+λ) GA.  Returns the best genome and a per-generation
    trajectory."""
    fire = on_event or (lambda *_a, **_kw: None)
    rng = random.Random(seed)
    ps = pool_size()
    if ps == 0:
        raise RuntimeError('LUT pool is empty')

    pool_cache: Dict[int, object] = {}  # idx → upcasted cell8 LUT

    # Initial population: pop_size genomes built by the chosen
    # seed_init function.  random_genome explores wiring topology;
    # naive_pipeline_genome / echo_seed_genome give the GA a
    # structured starting point so it only has to evolve rule_idx.
    init_fn = SEED_INIT_FNS.get(seed_init)
    if init_fn is None:
        raise ValueError(f'unknown seed_init {seed_init!r}; '
                            f'pick from {list(SEED_INIT_FNS)}')
    population: List[dict] = []
    for i in range(pop_size):
        g = init_fn(n_boards=n_boards, board_side=board_side,
                       pool_size=ps, stack_ticks=stack_ticks,
                       seed=seed ^ (i * 7919))
        r = evaluate(g, test_set_id=test_set, personality=personality,
                          pool_cache=pool_cache)
        population.append({'genome': g, 'fitness': r['fitness'],
                                'byte_match': r['byte_match'],
                                'n_pairs':    r['n_pairs']})
    population.sort(key=lambda x: -x['fitness'])
    best_ever = dict(population[0])
    fire('init', {'best_fit': best_ever['fitness'],
                    'best_byte_match': best_ever['byte_match']})

    trajectory = []
    n_evals = pop_size

    for gen in range(generations):
        t0 = time.time()
        # Elitism: top elite_n survive into next gen unchanged.
        next_pop = population[:elite_n]
        # Children: parents are random picks from top half.
        top_half = max(1, pop_size // 2)
        for k in range(pop_size - elite_n):
            parent = population[rng.randrange(top_half)]['genome']
            child  = mutate_genome(parent, mutation_rate=mutation_rate,
                                            pool_size=ps,
                                            seed=seed ^ (gen * 131) ^ (k * 13))
            r = evaluate(child, test_set_id=test_set, personality=personality,
                              pool_cache=pool_cache)
            next_pop.append({'genome': child, 'fitness': r['fitness'],
                                  'byte_match': r['byte_match'],
                                  'n_pairs':    r['n_pairs']})
            n_evals += 1
        next_pop.sort(key=lambda x: -x['fitness'])
        population = next_pop
        gen_wall = time.time() - t0
        if population[0]['fitness'] > best_ever['fitness']:
            best_ever = dict(population[0])
        trajectory.append({
            'gen':       gen,
            'best_fit':  population[0]['fitness'],
            'best_byte_match': population[0]['byte_match'],
            'mean_fit':  sum(x['fitness'] for x in population) / pop_size,
            'wall':      gen_wall,
        })
        fire('gen', {'gen': gen, **trajectory[-1],
                       'best_ever_fit': best_ever['fitness'],
                       'best_ever_byte_match': best_ever['byte_match']})

    return {
        'best_genome': best_ever['genome'],
        'best_fitness': best_ever['fitness'],
        'best_byte_match': best_ever['byte_match'],
        'n_pairs':     best_ever['n_pairs'],
        'n_evals':     n_evals,
        'trajectory':  trajectory,
        'pool_cache_hits': len(pool_cache),
    }
