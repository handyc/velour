"""L0 fixed-point class-4 quine search.

Different from deep_chain_search.py — here we want a single rule R
such that BOTH:

    1) sr_strict(R, ticks=16) == 1.0   (CA^16 applied to R's LUT-as-
                                          image gives back R's LUT
                                          byte-for-byte: a true
                                          metachain fixed point at L0)
    2) classify_rule(R)[0] == 4         (R is itself class-4)

If found, R generates a chain of length 1 (it maps to itself); the
chain is class-4 at every level by construction, so it has infinite
chain depth in the most literal possible way.

Algorithm:

    - Phase A: scan every level of every known saved quine's chain
      for the (sr_strict=1.0, class=4) pair.  This is cheap and might
      already discover the answer in #122's deep chain (which is known
      to converge to a self-mapping rule at L130).

    - Phase B: directed (μ + λ) ES.  Fitness combines sr_strict and
      class4_score multiplicatively, with a large bonus when both
      cross threshold.  Mutation operator is biased toward small
      single-byte flips (we are near-quine: we want gentle moves on
      the manifold).

      Seeds: every L of every saved quine's chain with sr_strict ≥ 0.95
      (these are the "near-fixed-points" — the search starts from the
      closest known approximation to the target).
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple


# ─── Fitness ──────────────────────────────────────────────────────────

def l0_fitness(rule_bytes: bytes,
                *,
                ticks: int = 16) -> dict:
    """Composite fitness for L0-fixed-point class-4 hunting.

    We want sr_strict → 1.0 AND cls == 4 simultaneously.  Pure
    multiplicative `sr * c4_score` rewards both, but a hard cls==4
    gate is the actual success criterion.

    Returns:
        {
            'sr_strict': float,
            'cls':       int,
            'c4_score':  float,
            'act':       float,
            'fitness':   float,    # the composite
            'is_l0_fp_c4': bool,   # the actual win condition
        }
    """
    from .metachain import (classify_rule, probe_activity,
                              self_reproduce_score)
    sr = self_reproduce_score(rule_bytes, ticks=ticks)
    cls, c4 = classify_rule(rule_bytes, probe_ticks=16)
    act = probe_activity(rule_bytes, ticks=12)

    # Composite: heavy weight on sr_strict (the harder term to
    # satisfy), with c4_score as a tie-break direction; explicit
    # cls==4 bonus past the gate.
    base = 0.7 * sr + 0.3 * c4
    bonus = 0.0
    if cls == 4:
        bonus += 0.1
    if sr >= 0.95 and cls == 4:
        bonus += 0.3
    if sr >= 0.999 and cls == 4:
        bonus += 1.0   # found it
    return {
        'sr_strict':    float(sr),
        'cls':          int(cls),
        'c4_score':     float(c4),
        'act':          float(act),
        'fitness':      float(base + bonus),
        'is_l0_fp_c4':  bool(sr >= 0.9999 and cls == 4),
    }


# ─── Phase A: scan existing chains for an already-existing answer ────

def scan_known_chains_for_l0_fp(*, max_depth: int = 200,
                                  log: Callable[[str], None] = print
                                  ) -> List[dict]:
    """Walk every saved quine's chain up to ``max_depth`` and return
    every level R where sr_strict(R)==1.0 AND cls==4.

    Each hit is:
      {'parent_pk': int, 'level': int, 'rule': bytes,
       'sha': str, 'sr_strict': float, 'cls': int, 'c4_score': float}
    """
    from caformer.models import ComponentChampion
    from .metachain import hex_ca_step
    import numpy as np
    qs = (ComponentChampion.objects
          .filter(component_slug='class4_quine')
          .order_by('-fitness'))
    log(f'scanning {qs.count()} saved quines, depth={max_depth}...')
    hits: List[dict] = []
    for q in qs:
        rule_arr = np.frombuffer(bytes(q.rules_blob), dtype=np.uint8).copy() & 3
        current = rule_arr
        for level in range(max_depth):
            cur_bytes = bytes(current.tobytes())
            f = l0_fitness(cur_bytes, ticks=16)
            if f['is_l0_fp_c4']:
                sha = hashlib.sha1(cur_bytes).hexdigest()[:8]
                hit = {
                    'parent_pk': q.pk,
                    'level':     level,
                    'rule':      cur_bytes,
                    'sha':       sha,
                    'sr_strict': f['sr_strict'],
                    'cls':       f['cls'],
                    'c4_score':  f['c4_score'],
                    'act':       f['act'],
                }
                hits.append(hit)
                log(f'  HIT! pk #{q.pk} L{level} sha={sha}  '
                    f'sr={f["sr_strict"]:.4f} cls={f["cls"]} '
                    f'c4={f["c4_score"]:.3f}')
            # Step the chain
            grid = current.reshape(128, 128).copy()
            state = grid
            for _ in range(16):
                state = hex_ca_step(state, current)
            current = state.flatten() & 3
        if (q.pk % 10) == 0:
            log(f'  scanned #{q.pk} ({len(hits)} hits so far)')
    return hits


def gather_near_quine_seeds(*, sr_min: float = 0.90,
                              max_depth: int = 200,
                              top_n: int = 32,
                              log: Callable[[str], None] = print
                              ) -> List[Tuple[bytes, str, dict]]:
    """Collect (rule_bytes, origin, metrics) for every chain-level
    across saved quines where sr_strict >= sr_min.  These are the
    seeds for Phase B — points already close to the L0 fixed-point
    manifold.  Returns the top-N by sr_strict, deduped on rule sha."""
    from caformer.models import ComponentChampion
    from .metachain import hex_ca_step
    import numpy as np
    qs = (ComponentChampion.objects
          .filter(component_slug='class4_quine')
          .order_by('-fitness'))
    seeds: dict[str, Tuple[bytes, str, dict]] = {}
    for q in qs:
        rule_arr = np.frombuffer(bytes(q.rules_blob), dtype=np.uint8).copy() & 3
        current = rule_arr
        for level in range(max_depth):
            cur_bytes = bytes(current.tobytes())
            f = l0_fitness(cur_bytes, ticks=16)
            if f['sr_strict'] >= sr_min:
                sha = hashlib.sha1(cur_bytes).hexdigest()[:8]
                if sha not in seeds or seeds[sha][2]['sr_strict'] < f['sr_strict']:
                    origin = f'#{q.pk} L{level}'
                    seeds[sha] = (cur_bytes, origin, f)
            # Step
            grid = current.reshape(128, 128).copy()
            state = grid
            for _ in range(16):
                state = hex_ca_step(state, current)
            current = state.flatten() & 3
    ranked = sorted(seeds.values(),
                      key=lambda t: -t[2]['sr_strict'])
    log(f'gathered {len(ranked)} near-quine seeds (sr_strict >= {sr_min}); '
        f'keeping top {top_n}')
    for r, origin, m in ranked[:8]:
        log(f'  seed {origin}: sr={m["sr_strict"]:.4f} '
            f'cls={m["cls"]} c4={m["c4_score"]:.3f}')
    return ranked[:top_n]


# ─── Mutation ─────────────────────────────────────────────────────────

def mutate_near_quine(rule_bytes: bytes, n_flips: int,
                         rng: random.Random) -> bytes:
    """Gentle mutation: single-byte flips with small n_flips bias.

    Unlike deep_chain_search's block-flip operator, we are already
    near the L0 fixed-point manifold.  Large mutations destroy the
    near-quine structure; small flips keep us on the manifold while
    nudging toward true fixed-point + class-4."""
    rule = bytearray(rule_bytes)
    for _ in range(n_flips):
        i = rng.randrange(len(rule))
        old = rule[i]
        new = old
        while new == old:
            new = rng.randrange(4)
        rule[i] = new
    return bytes(rule)


# ─── Candidate + GA ───────────────────────────────────────────────────

@dataclass
class Candidate:
    rule:        bytes
    fitness:     float = 0.0
    sr_strict:   float = 0.0
    cls:         int = 0
    c4_score:    float = 0.0
    act:         float = 0.0
    parent_id:   str = ''
    origin:      str = ''

    def short(self) -> str:
        return hashlib.sha1(self.rule).hexdigest()[:8]


@dataclass
class L0GAConfig:
    mu:              int = 8
    lam:             int = 24
    n_generations:   int = 1000
    mutation_min:    int = 1
    mutation_max:    int = 8
    seed_top_n:      int = 32
    seed_sr_min:     float = 0.85
    rng_seed:        int = 0
    save_threshold_sr: float = 0.98   # save anything with sr_strict ≥ 0.98 + cls==4
    progress_every:  int = 5


@dataclass
class L0GAResult:
    best_history: List[float] = field(default_factory=list)
    best_sr_history: List[float] = field(default_factory=list)
    found_rules: List[dict] = field(default_factory=list)
    persisted_pks: List[int] = field(default_factory=list)


def run_l0_fp_search(cfg: L0GAConfig,
                     log: Callable[[str], None] = print,
                     save: bool = True) -> L0GAResult:
    rng = random.Random(cfg.rng_seed or int(time.time()))
    result = L0GAResult()

    # Phase A: scan-first
    log('=== Phase A: scan known chains ===')
    hits = scan_known_chains_for_l0_fp(max_depth=200, log=log)
    if hits:
        log(f'Phase A: found {len(hits)} L0 fixed-point class-4 quines '
            'already present in saved chains!')
        for h in hits[:5]:
            log(f'  #{h["parent_pk"]} L{h["level"]} sha={h["sha"]}  '
                f'sr={h["sr_strict"]:.4f}')
        result.found_rules.extend(hits)
        if save:
            for h in hits:
                pk = _persist_l0_fp(h['rule'],
                                      origin=f'phase-A scan of #{h["parent_pk"]} L{h["level"]}',
                                      parent_sha=f'#{h["parent_pk"]}-L{h["level"]}',
                                      log=log)
                if pk:
                    result.persisted_pks.append(pk)
        # Still proceed to Phase B — more solutions are valuable.

    # Phase B: directed search
    log('')
    log('=== Phase B: directed (μ+λ) ES ===')
    raw_seeds = gather_near_quine_seeds(sr_min=cfg.seed_sr_min,
                                            max_depth=200,
                                            top_n=cfg.seed_top_n,
                                            log=log)
    if not raw_seeds:
        log('no seeds at sr_min={cfg.seed_sr_min}; widening to 0.5')
        raw_seeds = gather_near_quine_seeds(sr_min=0.5,
                                                max_depth=200,
                                                top_n=cfg.seed_top_n,
                                                log=log)
    if not raw_seeds:
        log('Phase B aborted: no near-quine seeds available')
        return result

    pop: List[Candidate] = []
    for rule_b, origin, m in raw_seeds:
        c = Candidate(rule=rule_b, origin=origin,
                        sr_strict=m['sr_strict'], cls=m['cls'],
                        c4_score=m['c4_score'], act=m['act'],
                        fitness=m['fitness'])
        pop.append(c)
    log(f'initial population: {len(pop)}')
    pop.sort(key=lambda c: -c.fitness)
    for c in pop[:5]:
        log(f'  {c.short()}  fit={c.fitness:.3f}  sr={c.sr_strict:.4f}  '
            f'cls={c.cls}  c4={c.c4_score:.3f}  {c.origin}')

    parents = pop[:cfg.mu]
    saved_shas: set[str] = set()
    plateau = 0
    last_best_fit = -1.0

    for gen in range(cfg.n_generations):
        children: List[Candidate] = []
        per_parent = max(1, cfg.lam // max(len(parents), 1))
        for p in parents:
            for _ in range(per_parent):
                n_flips = rng.randint(cfg.mutation_min, cfg.mutation_max)
                child_rule = mutate_near_quine(p.rule, n_flips, rng)
                children.append(Candidate(
                    rule=child_rule, parent_id=p.short(),
                    origin=f'mut(n={n_flips}) of {p.short()}',
                ))
        # Evaluate
        for c in children:
            f = l0_fitness(c.rule, ticks=16)
            c.fitness = f['fitness']
            c.sr_strict = f['sr_strict']
            c.cls = f['cls']
            c.c4_score = f['c4_score']
            c.act = f['act']

        combined = sorted(parents + children, key=lambda c: -c.fitness)
        parents = combined[:cfg.mu]
        best = parents[0]
        result.best_history.append(best.fitness)
        result.best_sr_history.append(best.sr_strict)

        if (gen % cfg.progress_every) == 0 or best.fitness >= 1.0:
            log(f'gen {gen:>4}  best  sha={best.short()}  '
                f'fit={best.fitness:.3f}  sr={best.sr_strict:.4f}  '
                f'cls={best.cls}  c4={best.c4_score:.3f}  '
                f'origin={best.origin}')

        # Check for L0 fixed-point class-4 hits in the elite pool
        for c in parents:
            if c.sr_strict >= cfg.save_threshold_sr and c.cls == 4:
                sha = c.short()
                if sha in saved_shas:
                    continue
                saved_shas.add(sha)
                hit = {
                    'rule': c.rule, 'sha': sha,
                    'sr_strict': c.sr_strict, 'cls': c.cls,
                    'c4_score': c.c4_score, 'act': c.act,
                    'origin': c.origin,
                }
                result.found_rules.append(hit)
                log(f'  ★ candidate  sha={sha}  sr={c.sr_strict:.4f}  '
                    f'cls={c.cls}  origin={c.origin}')
                if save and c.sr_strict >= 0.9999:
                    pk = _persist_l0_fp(c.rule, origin=f'phase-B GA gen {gen}',
                                           parent_sha=c.parent_id, log=log)
                    if pk:
                        result.persisted_pks.append(pk)

        # Plateau detection
        if abs(best.fitness - last_best_fit) < 1e-6:
            plateau += 1
        else:
            plateau = 0
            last_best_fit = best.fitness
        if plateau >= 100:
            log(f'plateau at fit={best.fitness:.3f} for {plateau} gens; '
                f'shuffling: large mutation kick on bottom half')
            # Inject diversity: replace bottom half of parents with
            # heavily-mutated versions of the top
            for i in range(len(parents) // 2, len(parents)):
                kick = mutate_near_quine(parents[0].rule, 32, rng)
                f = l0_fitness(kick, ticks=16)
                parents[i] = Candidate(
                    rule=kick, parent_id=parents[0].short(),
                    origin=f'diversity-kick of {parents[0].short()}',
                    fitness=f['fitness'], sr_strict=f['sr_strict'],
                    cls=f['cls'], c4_score=f['c4_score'], act=f['act'],
                )
            plateau = 0
            last_best_fit = -1.0

    log('')
    log(f'L0 search done. best_sr={parents[0].sr_strict:.4f} '
        f'cls={parents[0].cls} found={len(result.found_rules)} '
        f'persisted={len(result.persisted_pks)}')
    return result


# ─── Persistence ──────────────────────────────────────────────────────

def _persist_l0_fp(rule: bytes, *, origin: str, parent_sha: str,
                     log: Callable[[str], None] = print) -> Optional[int]:
    """Save an L0 fixed-point class-4 quine as a ComponentChampion
    with component_slug='class4_quine' and an extra meta flag."""
    from caformer.models import ComponentChampion
    from .metachain import (classify_rule, probe_activity,
                              sr_arbitrary_sigma, self_reproduce_score,
                              walk_chain)
    existing = ComponentChampion.objects.filter(
        component_slug='class4_quine', rules_blob=rule).first()
    if existing:
        log(f'  (already saved as #{existing.pk})')
        return None
    cls, c4 = classify_rule(rule, probe_ticks=24)
    if cls != 4:
        log(f'  skip persist: cls={cls} != 4')
        return None
    sr = self_reproduce_score(rule, ticks=16)
    if sr < 0.9999:
        log(f'  skip persist: sr_strict={sr:.4f} < 0.9999')
        return None
    act = probe_activity(rule, ticks=12)
    sr_arbs = sr_arbitrary_sigma(rule, ticks=16)
    chain = walk_chain(rule, depth=8)
    meta = {
        'origin':              'l0-fp-class4',
        'l0_fp_source':        origin,
        'sr':                  float(sr),
        'c4':                  float(c4),
        'act':                 float(act),
        'arbsigma':            float(sr_arbs),
        'class4_run_length':   int(chain['class4_run_length']),
        'l0_fp_class4':        True,
        'ga_parent':           parent_sha or '',
    }
    obj = ComponentChampion.objects.create(
        component_slug='class4_quine',
        rules_blob=rule,
        rule_names_csv='l0-fp-class4',
        fitness=float(sr),
        generation=0,
        run_label='l0-fp-class4',
        ga_pop_size=0, ga_generations=0,
        eval_count=0,
        notes=json.dumps(meta),
    )
    log(f'  ✔ persisted L0-FP class-4 quine as ComponentChampion #{obj.pk} '
        f'(sr={sr:.4f}, cls={cls}, c4={c4:.3f})')
    return obj.pk
