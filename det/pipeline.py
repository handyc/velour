"""One-click Det pipeline: raw seed → population → GA → tournament →
meta-tournament → promoted Automaton rulesets.

All stages use the dense packed representation
(automaton.packed.PackedRuleset + step_packed) so the whole sweep
finishes in seconds on a commodity CPU.

Pipeline stages:

  1. SEED — generate ``seed_candidates`` full 16,384-rule packed
     rulesets at random, score each once, pick the highest-scoring
     as the founding genome.

  2. POPULATE — mutate the founder ``population_size`` times at a
     moderate rate to produce the initial GA population.

  3. GENERATIONS — for ``generations`` rounds: score every agent on
     the same substrate (one grid seed, same W/H/horizon), keep the
     top half, breed survivors via crossover + per-child mutation
     to refill the population.

  4. TOURNAMENT — take the top K from the final GA population, score
     each on ``tournament_seeds`` *different* grid seeds, rank by the
     aggregate. This strips out lucky-seed wins.

  5. META — if the run is part of an ongoing sweep, combine these
     tournament winners with winners from previous sweeps and re-
     score across a shared seed set. Currently a stub that just
     marks the winners for a future meta-tournament collector.

  6. PROMOTE — serialise the top ``final_winners`` into
     ``automaton.RuleSet`` + ``automaton.ExactRule`` records so the
     operator can drive them from /automaton/.

The pipeline logs each stage through ``progress_cb`` if provided —
suitable for hooking a view's streaming response or a management
command's stdout.
"""

from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from automaton.detector import step_packed
from automaton.packed import PackedRuleset
from det import engine
from det.search import _score as det_score


# ═════════════════════════════════════════════════════════════════════
# Stage helpers
# ═════════════════════════════════════════════════════════════════════

def _simulate_packed(packed: PackedRuleset, W: int, H: int,
                     n_colors: int, horizon: int, grid_seed: str) -> dict:
    """Same shape as det.search._step_and_measure's analysis dict."""
    grid = engine.seeded_random_grid(W, H, n_colors, grid_seed)
    history = [grid]
    activity = []
    period = None
    entered_at = None
    for t in range(1, horizon + 1):
        nxt = step_packed(grid, W, H, packed)
        activity.append(engine.activity_rate(grid, nxt))
        history.append(nxt)
        grid = nxt
        if t >= 4 and t % 2 == 0:
            p, ea = engine.detect_cycle(history, max_period=16)
            if p is not None:
                period, entered_at = p, ea
                break

    uniform = engine.is_uniform(grid)
    be = engine.block_entropy_grid(grid, k=2)
    dens = engine.density_profile(grid, n_colors)
    color_diversity = sum(1 for d in dens if d > 0.01)
    tail = activity[-max(1, len(activity) // 3):]
    activity_tail = sum(tail) / len(tail) if tail else 0.0
    return {
        'uniform':         uniform,
        'period':          period,
        'entered_at':      entered_at,
        'ended_at_tick':   len(history) - 1,
        'activity_tail':   round(activity_tail, 4),
        'block_entropy':   round(be, 4),
        'density_profile': [round(d, 4) for d in dens],
        'color_diversity': color_diversity,
    }


def _score_packed(packed: PackedRuleset, W: int, H: int,
                  n_colors: int, horizon: int, grid_seed: str) -> tuple[float, dict]:
    analysis = _simulate_packed(packed, W, H, n_colors, horizon, grid_seed)
    score, _breakdown = det_score(analysis, n_colors)
    return score, analysis


# ═════════════════════════════════════════════════════════════════════
# Genome ops (thin wrappers — PackedRuleset already has all of these)
# ═════════════════════════════════════════════════════════════════════

def _breed(parents: List[tuple[float, PackedRuleset]],
           target_size: int,
           mutation_rate: float,
           rng: random.Random) -> List[PackedRuleset]:
    """Tournament-2 selection + crossover + mutation."""
    children: List[PackedRuleset] = []
    sorted_parents = [p for _, p in sorted(parents, key=lambda pr: -pr[0])]
    # Keep the top survivor as-is (elitism)
    if sorted_parents:
        children.append(sorted_parents[0])
    while len(children) < target_size:
        # Tournament of 2: pick two random parents, keep the fitter
        a, b = rng.sample(range(len(parents)), 2) if len(parents) >= 2 \
            else (0, 0)
        p1 = parents[a][1] if parents[a][0] >= parents[b][0] else parents[b][1]
        c, d = rng.sample(range(len(parents)), 2) if len(parents) >= 2 \
            else (0, 0)
        p2 = parents[c][1] if parents[c][0] >= parents[d][0] else parents[d][1]
        child = p1.crossover(p2, rng=rng).mutate(mutation_rate, rng=rng)
        children.append(child)
    return children


# ═════════════════════════════════════════════════════════════════════
# Progress reporting
# ═════════════════════════════════════════════════════════════════════

@dataclass
class StageReport:
    name: str
    detail: str
    elapsed_s: float


@dataclass
class PipelineResult:
    seed_score: float
    seed_hex: str
    final_generation_best: float
    final_generation_mean: float
    tournament_ranking: List[dict]  # sorted by aggregate
    promoted_ruleset_ids: List[int]
    stages: List[StageReport] = field(default_factory=list)


def _report(cb: Optional[Callable[[str], None]], msg: str) -> None:
    if cb:
        cb(msg)


# ═════════════════════════════════════════════════════════════════════
# Main pipeline
# ═════════════════════════════════════════════════════════════════════

def run_oneclick_pipeline(
        *,
        n_colors: int = 4,
        seed_candidates: int = 15,
        population_size: int = 25,
        generations: int = 12,
        grid_W: int = 18,
        grid_H: int = 18,
        horizon: int = 30,
        mutation_rate: float = 0.005,
        tournament_seeds: int = 5,
        final_winners: int = 3,
        ga_grid_seed: str = 'det-oneclick-ga',
        tournament_seed_base: str = 'det-oneclick-tourney',
        rng_seed: Optional[int] = None,
        progress_cb: Optional[Callable[[str], None]] = None,
) -> PipelineResult:
    """Run the complete seed → GA → tournament → promote sweep."""

    rng = random.Random(rng_seed)
    if rng_seed is None:
        # Randomise so repeated runs produce different outcomes
        rng.seed(int(time.time() * 1000) & 0xFFFFFFFF)

    stages: List[StageReport] = []

    # ── Stage 1: SEED ─────────────────────────────────────────────────
    t0 = time.time()
    _report(progress_cb, f'1/6 SEED — trying {seed_candidates} random packed rulesets…')
    best_seed: Optional[PackedRuleset] = None
    best_seed_score = -1.0
    for i in range(seed_candidates):
        cand = PackedRuleset.random(n_colors, rng=rng)
        score, _ = _score_packed(cand, grid_W, grid_H, n_colors,
                                 horizon, ga_grid_seed)
        if score > best_seed_score:
            best_seed_score, best_seed = score, cand
    assert best_seed is not None
    stages.append(StageReport(
        'seed',
        f'best of {seed_candidates} random: score={best_seed_score:.2f}',
        time.time() - t0,
    ))
    _report(progress_cb, f'  → seed score {best_seed_score:.2f}')

    # ── Stage 2: POPULATE ─────────────────────────────────────────────
    t0 = time.time()
    _report(progress_cb, f'2/6 POPULATE — mutating seed {population_size} times…')
    # Higher mutation for the initial scatter — we want diversity
    population = [best_seed.mutate(0.02, rng=rng)
                  for _ in range(population_size - 1)]
    population.insert(0, best_seed)  # keep the pristine seed as one member
    stages.append(StageReport(
        'populate',
        f'{population_size} agents (seed + {population_size - 1} mutants)',
        time.time() - t0,
    ))

    # ── Stage 3: GENERATIONS ──────────────────────────────────────────
    t0 = time.time()
    _report(progress_cb, f'3/6 GA — {generations} generations @ pop {population_size}…')
    fitness_history: List[tuple[float, float]] = []  # (best, mean) per generation
    for gen in range(generations):
        pairs = []
        for agent in population:
            s, _an = _score_packed(agent, grid_W, grid_H, n_colors,
                                    horizon, ga_grid_seed)
            pairs.append((s, agent))
        best = max(s for s, _ in pairs)
        mean = sum(s for s, _ in pairs) / len(pairs)
        fitness_history.append((best, mean))
        _report(progress_cb,
                f'  gen {gen + 1:2d}: best={best:.2f} mean={mean:.2f}')
        # Breed next generation
        population = _breed(pairs, population_size, mutation_rate, rng)

    # Final scoring after the last breed step
    final_scored = []
    for agent in population:
        s, an = _score_packed(agent, grid_W, grid_H, n_colors,
                               horizon, ga_grid_seed)
        final_scored.append((s, an, agent))
    final_scored.sort(key=lambda t: -t[0])
    stages.append(StageReport(
        'generations',
        f'final best={final_scored[0][0]:.2f} mean={fitness_history[-1][1]:.2f}',
        time.time() - t0,
    ))

    # ── Stage 4: TOURNAMENT ───────────────────────────────────────────
    t0 = time.time()
    k_for_tournament = min(8, len(final_scored))
    _report(progress_cb,
            f'4/6 TOURNAMENT — top {k_for_tournament} × {tournament_seeds} seeds…')
    # Ping each finalist on every seed grid, average their scores
    seeds = [f'{tournament_seed_base}-{i}' for i in range(tournament_seeds)]
    entries = []
    for rank, (base_score, _an, agent) in enumerate(final_scored[:k_for_tournament]):
        per_seed = []
        for s in seeds:
            sc, an = _score_packed(agent, grid_W, grid_H, n_colors, horizon, s)
            per_seed.append({'seed': s, 'score': round(sc, 3),
                             'period': an['period'],
                             'activity_tail': an['activity_tail']})
        avg = sum(e['score'] for e in per_seed) / len(per_seed)
        entries.append({
            'rank': rank + 1,
            'ga_score': round(base_score, 3),
            'tournament_score_avg': round(avg, 3),
            'per_seed': per_seed,
            'agent': agent,
        })
    entries.sort(key=lambda e: -e['tournament_score_avg'])
    stages.append(StageReport(
        'tournament',
        f'top by avg: {entries[0]["tournament_score_avg"]:.2f} '
        f'(was GA rank {entries[0]["rank"]})',
        time.time() - t0,
    ))
    _report(progress_cb,
            f'  → tournament winner avg {entries[0]["tournament_score_avg"]:.2f}')

    # ── Stage 5: META ─────────────────────────────────────────────────
    # No persistent store of past sweeps yet — for v1, META is a no-op.
    # The meta-tournament collector lives in det.tournament already and
    # can be invoked separately to merge multiple oneclick sweeps.
    t0 = time.time()
    _report(progress_cb, '5/6 META — skipped (single-sweep run)')
    stages.append(StageReport('meta', 'skipped (single-sweep run)',
                              time.time() - t0))

    # ── Stage 6: PROMOTE ──────────────────────────────────────────────
    t0 = time.time()
    _report(progress_cb,
            f'6/6 PROMOTE — top {final_winners} → automaton.RuleSet…')
    promoted_ids = _promote_to_automaton(
        entries[:final_winners],
        n_colors=n_colors, W=grid_W, H=grid_H,
        horizon=horizon, ga_grid_seed=ga_grid_seed,
        seed_score=best_seed_score,
    )
    stages.append(StageReport(
        'promote',
        f'{len(promoted_ids)} RuleSet(s) saved: {promoted_ids}',
        time.time() - t0,
    ))
    _report(progress_cb, f'  → saved RuleSet ids {promoted_ids}')

    return PipelineResult(
        seed_score=best_seed_score,
        seed_hex=best_seed.to_hex()[:32] + '…',  # just a fingerprint
        final_generation_best=fitness_history[-1][0] if fitness_history else 0.0,
        final_generation_mean=fitness_history[-1][1] if fitness_history else 0.0,
        tournament_ranking=[
            {k: v for k, v in e.items() if k != 'agent'} for e in entries
        ],
        promoted_ruleset_ids=promoted_ids,
        stages=stages,
    )


# ═════════════════════════════════════════════════════════════════════
# Automaton promotion
# ═════════════════════════════════════════════════════════════════════

def _promote_to_automaton(winners: List[dict], *, n_colors: int,
                          W: int, H: int, horizon: int,
                          ga_grid_seed: str,
                          seed_score: float) -> List[int]:
    """Save each winner's packed ruleset as a full automaton.RuleSet +
    ExactRule set + a seeded Simulation so the operator can run it
    from /automaton/."""
    from automaton.models import ExactRule, RuleSet, Simulation

    created: List[int] = []
    for i, w in enumerate(winners):
        agent: PackedRuleset = w['agent']
        name = (f'Det oneclick #{i + 1}: tournament='
                f'{w["tournament_score_avg"]:.2f} '
                f'(seed-of-pop {seed_score:.2f})')
        rs = RuleSet.objects.create(
            name=name,
            n_colors=n_colors,
            source='seed',
            description=(
                'Promoted from det.pipeline.run_oneclick_pipeline. '
                f'Seed ruleset was the best of the initial random batch '
                f'(score {seed_score:.2f}). GA, tournament across '
                f'{len(w["per_seed"])} seeds, avg tournament score '
                f'{w["tournament_score_avg"]:.2f}.'
            ),
            source_metadata={
                'pipeline':          'oneclick',
                'seed_score':        seed_score,
                'ga_score':          w['ga_score'],
                'tournament_avg':    w['tournament_score_avg'],
                'per_seed':          w['per_seed'],
                'packed_hex':        agent.to_hex(),
            },
        )
        # Materialise to explicit rules (compressed — skip identity
        # mappings). For a full 4-colour ruleset that's typically
        # ~12,000 rules kept, rest being identity passthrough.
        rules = agent.to_explicit(skip_identity=True)
        ExactRule.objects.bulk_create([
            ExactRule(
                ruleset=rs,
                self_color=r['s'],
                n0_color=r['n'][0], n1_color=r['n'][1], n2_color=r['n'][2],
                n3_color=r['n'][3], n4_color=r['n'][4], n5_color=r['n'][5],
                result_color=r['r'],
            ) for r in rules
        ])
        # Companion simulation so /automaton/ has a visual right away.
        # Fill grid_state from a seeded random board so the first tick
        # on the automaton run page picks up where the GA scored.
        initial_grid = engine.seeded_random_grid(W, H, n_colors, ga_grid_seed)
        Simulation.objects.create(
            ruleset=rs,
            name=f'Oneclick #{i + 1} preview',
            width=W, height=H,
            grid_state=initial_grid,
            notes=(
                f'Initial grid reused from the GA substrate '
                f'({W}×{H}, seed "{ga_grid_seed}").'
            ),
        )
        created.append(rs.pk)
    return created
