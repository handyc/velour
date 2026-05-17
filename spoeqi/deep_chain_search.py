"""Deep-chain quine search.

Direct fitness on chain depth, not single-level SR.  Optimises:

    fitness(rule, target_depth) =
        len(longest prefix of walk_chain(rule, target_depth)
            for which each level is class-4 AND in the activity band
            AND has sr_arbsigma >= 0.85) / target_depth

i.e. fraction of the target depth the chain stays in class-4
territory (under the histogram-overlap σ-quine metric, which is the
more permissive criterion and gives more signal at depth).

Strategy:

  - (μ + λ) evolution strategy: keep the top ``mu`` candidates,
    breed each by mutation to fill ``lambda`` children, evaluate,
    take the new top μ.
  - Progressive depth promotion: start at ``target_depth = 64``;
    when the best candidate hits ≥0.95 of the target, double the
    depth and continue.  Avoids wasting compute on deep chains
    until shallow ones are saturated.
  - Per-candidate early exit: the walk aborts the moment the chain
    breaks class-4, so bad candidates cost almost nothing.
  - Seeds the initial population from the existing saved
    ComponentChampions (the existing quine library is the best
    starting point — random K=4 rules almost never reach class-4 at
    all, let alone for multiple levels).

Survivors that beat the existing depth record are persisted as
new ComponentChampions with ``run_label='deep-chain-ga'`` so the
``/spoeqi/quine/`` index picks them up automatically.
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional


# ─── Fitness ──────────────────────────────────────────────────────────

def chain_depth_fitness(rule_bytes: bytes, *,
                          target_depth: int = 64,
                          ticks_per_level: int = 16,
                          sr_threshold: float = 0.85,
                          act_band: tuple = (0.05, 0.85),
                          metric: str = 'arbsigma',
                          early_term: bool = True,
                          ) -> dict:
    """Walk the chain to ``target_depth`` and count the longest
    consecutive run of class-4 levels *starting at any depth*.

    Most class-4 quines have a "warm-up" phase: L0 is the seed
    (often not class-4 itself), and the chain enters the attractor
    by L1 or L2.  Counting the longest streak rather than the prefix
    rewards rules whose attractor is deep, regardless of warm-up.

    The walk must run to completion (no early abort) because the
    streak can start anywhere — but the walk is still cheap: at
    target_depth=64, ~3 seconds on this hardware.

    Returns:
        {
            'run_length':      int,  # longest streak anywhere
            'fitness':         float,
            'cycle_at':        Optional[int],
            'distinct_levels': int,
            'streak_start':    Optional[int],  # level the best streak begins
        }
    """
    from .metachain import (classify_rule, probe_activity,
                              sr_arbitrary_sigma, self_reproduce_score,
                              hex_ca_step)
    import numpy as np

    rule_arr = np.frombuffer(rule_bytes, dtype=np.uint8).copy() & 3
    seen: dict[bytes, int] = {bytes(rule_arr.tobytes()): 0}
    cycle_at = None
    distinct = 1

    # Track streak online so we can early-terminate when the best
    # possible remaining streak can't beat what we already have.
    best_len = 0
    best_start = None
    cur_len = 0
    cur_start = 0
    walked_count = 0

    current = rule_arr
    for level in range(target_depth):
        cur_bytes = bytes(current.tobytes())
        cls, _c4 = classify_rule(cur_bytes, probe_ticks=16)
        act = probe_activity(cur_bytes, ticks=12)
        if metric == 'arbsigma':
            sr = sr_arbitrary_sigma(cur_bytes, ticks=ticks_per_level)
        else:
            sr = self_reproduce_score(cur_bytes, ticks=ticks_per_level)
        ok = (cls == 4
                and act_band[0] <= act <= act_band[1]
                and sr >= sr_threshold)
        walked_count = level + 1

        if ok:
            if cur_len == 0:
                cur_start = level
            cur_len += 1
            if cur_len > best_len:
                best_len = cur_len
                best_start = cur_start
        else:
            cur_len = 0
            # Early termination: if the current streak has broken and
            # the remaining levels can't possibly extend best_len, stop.
            if early_term:
                remaining = target_depth - level - 1
                if remaining < best_len:
                    break

        # Next level
        grid = current.reshape(128, 128).copy()
        state = grid
        for _ in range(ticks_per_level):
            state = hex_ca_step(state, current)
        next_rule = state.flatten() & 3
        next_bytes = bytes(next_rule.tobytes())
        if next_bytes in seen:
            cycle_start_level = seen[next_bytes]
            cycle_at = level + 1
            # If we are currently inside a class-4 streak AND the cycle
            # is entirely contained within that streak, the chain stays
            # class-4 forever — effectively infinite depth.  Extrapolate
            # the current run to target_depth so this lucky topology
            # gets credit.
            if cur_len > 0 and cycle_start_level >= cur_start:
                remaining = target_depth - (level + 1)
                cur_len += remaining
                if cur_len > best_len:
                    best_len = cur_len
                    best_start = cur_start
            break
        seen[next_bytes] = level + 1
        distinct += 1
        current = next_rule

    return {
        'run_length':       best_len,
        'fitness':          best_len / float(target_depth),
        'cycle_at':         cycle_at,
        'distinct_levels':  distinct,
        'streak_start':     best_start,
        'walked_levels':    walked_count,
    }


# ─── Mutation ─────────────────────────────────────────────────────────

def mutate_lut(rule_bytes: bytes, n_flips: int,
                  rng: random.Random) -> bytes:
    """Flip ``n_flips`` random LUT entries to random K=4 values.

    Block-mode bias: with 25% probability we pick a single contiguous
    block to flip (mimics the block-flip discovery operator) instead
    of scattered single-byte flips.  Helps escape local optima."""
    rule = bytearray(rule_bytes)
    if rng.random() < 0.25 and n_flips >= 4:
        # Contiguous block
        block_size = max(4, n_flips)
        start = rng.randrange(0, len(rule) - block_size)
        for i in range(block_size):
            rule[start + i] = rng.randrange(4)
    else:
        for _ in range(n_flips):
            i = rng.randrange(len(rule))
            rule[i] = rng.randrange(4)
    return bytes(rule)


# ─── Candidate + population ───────────────────────────────────────────

@dataclass
class Candidate:
    rule:     bytes
    fitness:  float = 0.0
    run_length: int = 0
    distinct_levels: int = 0
    cycle_at: Optional[int] = None
    parent_id: str = ''
    origin:   str = ''

    def short(self) -> str:
        import hashlib
        return hashlib.sha1(self.rule).hexdigest()[:8]


@dataclass
class GAConfig:
    mu:              int = 4
    lam:             int = 6      # children per generation
    n_generations:   int = 50
    target_depth:    int = 64
    max_depth:       int = 1024
    promote_at:      float = 0.92
    mutation_min:    int = 2
    mutation_max:    int = 64
    sr_threshold:    float = 0.85
    act_band:        tuple = (0.05, 0.85)
    ticks_per_level: int = 16
    metric:          str = 'arbsigma'
    seed_top_n:      int = 8       # how many existing quines to seed from
    seed_blockflip:  int = 4       # plus N fresh block-flip-from-identity
    exclude_pks:     tuple = ()    # exclude these saved quine pks from seeding
    save_threshold_runlen: int = 50
    rng_seed:        int = 0


@dataclass
class GAResult:
    generations: List[List[Candidate]] = field(default_factory=list)
    best_history: List[float] = field(default_factory=list)
    persisted_pks: List[int] = field(default_factory=list)
    final_target_depth: int = 0


# ─── Seeding ──────────────────────────────────────────────────────────

def _identity_rule() -> bytes:
    """Identity rule: LUT[k] = (k >> 12) & 3 — output = self bits."""
    import numpy as np
    out = np.empty(16384, dtype=np.uint8)
    for k in range(16384):
        out[k] = (k >> 12) & 3
    return bytes(out)


def _block_flip_seed(rng: random.Random) -> bytes:
    """Like block_flip_search but just one trial — for population seeding."""
    rule = bytearray(_identity_rule())
    n_blocks = rng.randint(1, 4)
    block_size = rng.choice([16, 32, 64, 128])
    for _ in range(n_blocks):
        start = rng.randrange(0, len(rule) - block_size)
        for i in range(block_size):
            rule[start + i] = rng.randrange(4)
    return bytes(rule)


def _seed_population(cfg: GAConfig, rng: random.Random,
                       log: Callable[[str], None]) -> List[Candidate]:
    """Build initial population: top-N saved quines + N block-flip fresh."""
    from caformer.models import ComponentChampion
    pop: List[Candidate] = []
    excluded = set(cfg.exclude_pks or ())
    qs = (ComponentChampion.objects
          .filter(component_slug='class4_quine')
          .exclude(pk__in=excluded)
          .order_by('-fitness')[:cfg.seed_top_n])
    for q in qs:
        pop.append(Candidate(
            rule=bytes(q.rules_blob),
            origin=f'saved quine #{q.pk}',
        ))
    log(f'seeded {len(pop)} candidates from saved quines')
    for i in range(cfg.seed_blockflip):
        pop.append(Candidate(
            rule=_block_flip_seed(rng),
            origin=f'block-flip seed #{i}',
        ))
    log(f'added {cfg.seed_blockflip} block-flip seeds; '
        f'total pop={len(pop)}')
    return pop


# ─── Main search loop ─────────────────────────────────────────────────

def run_deep_chain_search(cfg: GAConfig,
                              log: Callable[[str], None] = print,
                              save: bool = True) -> GAResult:
    rng = random.Random(cfg.rng_seed or int(time.time()))
    result = GAResult()
    pop = _seed_population(cfg, rng, log)

    target = cfg.target_depth
    result.final_target_depth = target

    # Evaluate initial population at the starting depth.
    log(f'evaluating initial population at depth={target}...')
    for c in pop:
        m = chain_depth_fitness(
            c.rule, target_depth=target,
            ticks_per_level=cfg.ticks_per_level,
            sr_threshold=cfg.sr_threshold,
            act_band=cfg.act_band, metric=cfg.metric)
        c.fitness = m['fitness']
        c.run_length = m['run_length']
        c.distinct_levels = m['distinct_levels']
        c.cycle_at = m['cycle_at']
    pop.sort(key=lambda c: -c.fitness)

    for c in pop[:cfg.mu]:
        log(f'  init  {c.short()}  run={c.run_length}/{target}  '
            f'fit={c.fitness:.3f}  {c.origin}')

    # GA loop
    parents = pop[:cfg.mu]
    saved_pks = set()
    plateau_streak = 0
    last_best_run = -1

    for gen in range(cfg.n_generations):
        # Breed children: each parent makes lam/mu kids; total = lam.
        children: List[Candidate] = []
        per_parent = max(1, cfg.lam // cfg.mu)
        for p in parents:
            for _ in range(per_parent):
                n_flips = rng.randint(cfg.mutation_min, cfg.mutation_max)
                child_rule = mutate_lut(p.rule, n_flips, rng)
                children.append(Candidate(
                    rule=child_rule,
                    parent_id=p.short(),
                    origin=f'mut(n={n_flips}) of {p.short()}',
                ))

        # Evaluate children
        for c in children:
            m = chain_depth_fitness(
                c.rule, target_depth=target,
                ticks_per_level=cfg.ticks_per_level,
                sr_threshold=cfg.sr_threshold,
                act_band=cfg.act_band, metric=cfg.metric)
            c.fitness = m['fitness']
            c.run_length = m['run_length']
            c.distinct_levels = m['distinct_levels']
            c.cycle_at = m['cycle_at']

        # (μ + λ) selection: keep top μ from parents+children
        combined = sorted(parents + children, key=lambda c: -c.fitness)
        parents = combined[:cfg.mu]

        best = parents[0]
        result.best_history.append(best.fitness)
        result.generations.append([c for c in parents])
        log(f'gen {gen:>3}  best run={best.run_length}/{target} '
            f'fit={best.fitness:.3f}  mean={sum(c.fitness for c in parents)/cfg.mu:.3f}  '
            f'origin={best.origin}')

        # Persist promising survivors (beat the previous record).
        if save and best.run_length >= cfg.save_threshold_runlen:
            try:
                pk = _persist_champion(best, target=target,
                                          metric=cfg.metric)
                if pk and pk not in saved_pks:
                    result.persisted_pks.append(pk)
                    saved_pks.add(pk)
                    log(f'  → persisted as ComponentChampion #{pk}')
            except Exception as e:
                log(f'  ! persist error: {e}')

        # Early termination conditions:
        #   1. Whole pool saturated (fitness == 1.0 for ≥3 consecutive
        #      gens) and we can't promote → no point burning gens.
        #   2. Plateaued at the same best run_length for too long.
        if best.run_length == last_best_run:
            plateau_streak += 1
        else:
            plateau_streak = 0
            last_best_run = best.run_length
        all_saturated = all(c.fitness >= 0.999 for c in parents)
        if all_saturated and target >= cfg.max_depth and plateau_streak >= 2:
            log(f'  early-stop: pool saturated at fit=1.0 for '
                f'{plateau_streak+1} gens; moving on.')
            break
        if plateau_streak >= 12:
            log(f'  early-stop: best run_length plateaued for '
                f'{plateau_streak} gens; moving on.')
            break

        # Promote target depth if saturated
        if best.fitness >= cfg.promote_at and target < cfg.max_depth:
            old = target
            target = min(target * 2, cfg.max_depth)
            result.final_target_depth = target
            log(f'  ⤴ promoting depth: {old} → {target}; '
                f'reevaluating elites...')
            # Re-eval parents at the new (deeper) target so the next
            # generation is honest.
            for c in parents:
                m = chain_depth_fitness(
                    c.rule, target_depth=target,
                    ticks_per_level=cfg.ticks_per_level,
                    sr_threshold=cfg.sr_threshold,
                    act_band=cfg.act_band, metric=cfg.metric)
                c.fitness = m['fitness']
                c.run_length = m['run_length']
                c.distinct_levels = m['distinct_levels']
                c.cycle_at = m['cycle_at']

    log('search done.')
    log(f'final best: run_length={parents[0].run_length}, '
        f'fitness={parents[0].fitness:.3f}, target_depth={target}')
    log(f'persisted {len(result.persisted_pks)} new ComponentChampions')
    return result


# ─── Persistence ──────────────────────────────────────────────────────

def _persist_champion(cand: Candidate, *, target: int,
                         metric: str) -> Optional[int]:
    """Save a deep-chain candidate as a ComponentChampion.

    Returns the new pk on save, or None if the rule already exists
    (same sha) in the table at the same or higher fitness."""
    from caformer.models import ComponentChampion
    from spoeqi.metachain import (classify_rule, probe_activity,
                                       sr_arbitrary_sigma,
                                       self_reproduce_score, walk_chain)
    sha = cand.short()
    # Don't persist duplicates of already-saved seeds.
    existing = ComponentChampion.objects.filter(
        component_slug='class4_quine', rules_blob=cand.rule).first()
    if existing:
        return None
    cls, c4 = classify_rule(cand.rule, probe_ticks=16)
    act = probe_activity(cand.rule, ticks=12)
    sr = self_reproduce_score(cand.rule, ticks=16)
    sr_arbs = sr_arbitrary_sigma(cand.rule, ticks=16)
    chain = walk_chain(cand.rule, depth=min(target, 64))
    meta = {
        'origin':            'deep-chain-ga',
        'sr':                float(sr),
        'c4':                float(c4),
        'act':               float(act),
        'arbsigma':          float(sr_arbs),
        'class4_run_length': int(chain['class4_run_length']),
        'ga_target_depth':   int(target),
        'ga_run_length':     int(cand.run_length),
        'ga_metric':         metric,
        'ga_distinct_levels': int(cand.distinct_levels),
        'ga_parent':         cand.parent_id,
    }
    obj = ComponentChampion.objects.create(
        component_slug='class4_quine',
        rules_blob=cand.rule,
        rule_names_csv='deep-chain-ga',
        fitness=float(sr),
        generation=0,
        run_label='deep-chain-ga',
        ga_pop_size=0, ga_generations=0,
        eval_count=cand.run_length,
        notes=json.dumps(meta),
    )
    return obj.pk
