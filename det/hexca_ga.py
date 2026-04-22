"""Hex-CA GA — evolutionary search for Class-4 hex-cellular-automaton
rulesets.

This is the headless counterpart to the (planned) ``hexca`` gene handler
in ``evolution/static/evolution/engine.mjs``. The JS port will mirror
the operator names here: ``hexca_random``, ``hexca_mutate``, ``hexca_work``.
Keeping them in one module makes the parity check straightforward.

Gene shape
----------
``{'rules': [{s, n: [6], r}, ...], 'n_colors': int}``. Rule priority is
position in the list — first-match-wins, mirroring
``automaton.detector.step_exact``. All color codes are ints; -1 means
wildcard on self or any neighbor slot.

Fitness
-------
A gene is scored by running ``step_exact`` for ``horizon`` ticks on a
deterministically seeded grid and applying ``det.search._score``. The
same scorer Det's random sweep uses, so genes and Det Candidates share
a fitness landscape.

The module exposes :func:`run_ga` which returns the full trajectory so
the CLI can print progress; the per-gene work is pure and picklable
for future parallelisation.
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional

from automaton.detector import step_exact

from . import engine as _det_engine
from .search import _classify, _generate_rules, _rules_hash, _score


def random_gene(n_rules: int, n_colors: int, wildcard_pct: int,
                rng: random.Random) -> Dict:
    return {
        'rules': _generate_rules(n_rules, n_colors, wildcard_pct, rng),
        'n_colors': n_colors,
    }


def _random_rule(n_colors: int, wildcard_pct: int,
                 rng: random.Random) -> Dict:
    self_c = rng.randrange(n_colors)
    nbs = []
    for _ in range(6):
        if rng.randrange(100) < wildcard_pct:
            nbs.append(-1)
        else:
            nbs.append(rng.randrange(n_colors))
    result = rng.randrange(n_colors)
    return {'s': self_c, 'n': nbs, 'r': result}


def mutate(gene: Dict, rate: float, wildcard_pct: int,
           min_rules: int, max_rules: int,
           rng: random.Random) -> Dict:
    """One mutation event chosen uniformly from six operators; an extra
    light pass with half the rate gives a gentle second touch so small
    rulesets still see diversity. Mirrors the planned JS hexca_mutate."""
    rules = [dict(r, n=list(r['n'])) for r in gene['rules']]
    n_colors = int(gene['n_colors'])

    def _flip_result():
        if not rules:
            return
        i = rng.randrange(len(rules))
        old = rules[i]['r']
        choices = [c for c in range(n_colors) if c != old]
        if choices:
            rules[i]['r'] = rng.choice(choices)

    def _flip_neighbor():
        if not rules:
            return
        i = rng.randrange(len(rules))
        j = rng.randrange(6)
        # 20% chance to toggle wildcard vs. concrete; otherwise change color.
        if rng.random() < 0.2:
            rules[i]['n'][j] = -1 if rules[i]['n'][j] != -1 else rng.randrange(n_colors)
        else:
            old = rules[i]['n'][j]
            choices = [c for c in range(n_colors) if c != old]
            if not choices:
                choices = [-1]
            rules[i]['n'][j] = rng.choice(choices)

    def _flip_self():
        if not rules:
            return
        i = rng.randrange(len(rules))
        old = rules[i]['s']
        pool = [c for c in range(n_colors) if c != old]
        if rng.random() < 0.15:
            pool.append(-1)
        if pool:
            rules[i]['s'] = rng.choice(pool)

    def _add_rule():
        if len(rules) >= max_rules:
            return
        rules.append(_random_rule(n_colors, wildcard_pct, rng))

    def _drop_rule():
        if len(rules) <= min_rules:
            return
        i = rng.randrange(len(rules))
        rules.pop(i)

    def _swap_priority():
        if len(rules) < 2:
            return
        i = rng.randrange(len(rules))
        j = rng.randrange(len(rules))
        if i != j:
            rules[i], rules[j] = rules[j], rules[i]

    ops = (_flip_result, _flip_neighbor, _flip_self,
           _add_rule, _drop_rule, _swap_priority)

    if rng.random() < rate:
        rng.choice(ops)()
    if rng.random() < rate * 0.5:
        rng.choice(ops)()

    return {'rules': rules, 'n_colors': n_colors}


def crossover(a: Dict, b: Dict, min_rules: int, max_rules: int,
              rng: random.Random) -> Dict:
    """Two-parent splice: concatenate prefix(a) + suffix(b), trim to a
    target length in [min_rules, max_rules]. Rule priority (position)
    matters for first-match-wins, so we preserve contiguous chunks."""
    n_colors = int(a.get('n_colors', b.get('n_colors', 2)))
    ra = a['rules']
    rb = b['rules']
    if not ra and not rb:
        return {'rules': [], 'n_colors': n_colors}
    if not ra:
        return {'rules': [dict(r, n=list(r['n'])) for r in rb], 'n_colors': n_colors}
    if not rb:
        return {'rules': [dict(r, n=list(r['n'])) for r in ra], 'n_colors': n_colors}

    cut_a = rng.randint(0, len(ra))
    cut_b = rng.randint(0, len(rb))
    merged = [dict(r, n=list(r['n'])) for r in (ra[:cut_a] + rb[cut_b:])]

    # Keep length in bounds: truncate tail or pad with a random rule.
    while len(merged) > max_rules:
        merged.pop()
    while len(merged) < min_rules:
        merged.append(_random_rule(n_colors, 25, rng))

    return {'rules': merged, 'n_colors': n_colors}


def score_gene(gene: Dict, W: int, H: int, horizon: int,
               grid_seed: str) -> Dict:
    """Work — step the ruleset forward and apply Det's Class-4 scorer.
    Returns a dict matching ``det.search._score_one`` shape so the CLI
    and any future JS port speak the same language."""
    n_colors = int(gene['n_colors'])
    rules = gene['rules']
    grid = _det_engine.seeded_random_grid(W, H, n_colors, grid_seed)
    history = [grid]
    activity = []
    period = None
    entered_at = None
    for t in range(1, horizon + 1):
        nxt = step_exact(grid, W, H, rules)
        activity.append(_det_engine.activity_rate(grid, nxt))
        history.append(nxt)
        grid = nxt
        if t >= 4 and t % 2 == 0:
            p, ea = _det_engine.detect_cycle(history, max_period=16)
            if p is not None:
                period, entered_at = p, ea
                break

    uniform = _det_engine.is_uniform(grid)
    block_ent = _det_engine.block_entropy_grid(grid, k=2)
    dens = _det_engine.density_profile(grid, n_colors)
    color_diversity = sum(1 for d in dens if d > 0.01)
    tail_slice = activity[-max(1, len(activity) // 3):]
    activity_tail = sum(tail_slice) / len(tail_slice) if tail_slice else 0.0

    analysis = {
        'uniform':         uniform,
        'period':          period,
        'entered_at':      entered_at,
        'ended_at_tick':   len(history) - 1,
        'activity_tail':   round(activity_tail, 4),
        'block_entropy':   round(block_ent, 4),
        'density_profile': [round(d, 4) for d in dens],
        'color_diversity': color_diversity,
        'grid_seed':       grid_seed,
    }
    score, breakdown = _score(analysis, n_colors)
    analysis['score_breakdown'] = breakdown
    return {
        'score': score,
        'est_class': _classify(analysis, score, n_colors),
        'analysis': analysis,
        'rules_hash': _rules_hash(rules),
    }


def _tournament_pick(scored, k, rng):
    contenders = rng.sample(scored, min(k, len(scored)))
    contenders.sort(key=lambda t: t[1]['score'], reverse=True)
    return contenders[0][0]


def run_ga(*, n_colors: int, n_rules: int, wildcard_pct: int,
           W: int, H: int, horizon: int,
           population: int, generations: int,
           mutation_rate: float, tournament_k: int,
           min_rules: int, max_rules: int,
           grid_seed: str, seed_genes: Optional[List[Dict]] = None,
           progress=None, rng: Optional[random.Random] = None) -> Dict:
    """Evolve a population toward higher Class-4 scores.

    Returns a dict with the best gene + its result, plus a per-generation
    history so callers can chart convergence.

    The grid_seed is shared across every gene in every generation, so
    fitness differences reflect the ruleset and not a different trajectory.
    """
    rng = rng or random.Random()
    pop: List[Dict] = []
    seeds = list(seed_genes or [])
    for _ in range(population):
        if seeds:
            pop.append(seeds.pop(0))
        else:
            pop.append(random_gene(n_rules, n_colors, wildcard_pct, rng))

    scored = [(g, score_gene(g, W, H, horizon, grid_seed)) for g in pop]
    best_gene, best_res = max(scored, key=lambda t: t[1]['score'])
    history = [{'gen': 0, 'best': best_res['score']}]

    for gen in range(1, generations + 1):
        scored.sort(key=lambda t: t[1]['score'], reverse=True)
        # One elite, then fill with children.
        nxt_pop = [scored[0][0]]
        while len(nxt_pop) < population:
            pa = _tournament_pick(scored, tournament_k, rng)
            pb = _tournament_pick(scored, tournament_k, rng)
            child = crossover(pa, pb, min_rules, max_rules, rng)
            child = mutate(child, mutation_rate, wildcard_pct,
                           min_rules, max_rules, rng)
            nxt_pop.append(child)
        scored = [(g, score_gene(g, W, H, horizon, grid_seed))
                  for g in nxt_pop]
        gen_best_gene, gen_best_res = max(scored, key=lambda t: t[1]['score'])
        if gen_best_res['score'] > best_res['score']:
            best_gene, best_res = gen_best_gene, gen_best_res
        history.append({'gen': gen, 'best': best_res['score']})
        if progress:
            progress(gen, generations, best_res['score'])

    return {
        'best_gene': best_gene,
        'best_result': best_res,
        'history': history,
        'final_population': scored,
    }
