"""caformer/ga.py — special-purpose GA for evolving CA primitive rules.

Every primitive in caformer/primitives.py is a CA rule table (16,384
bytes of `next_colour` for each 7-cell K=4 hex neighbourhood
configuration).  This module evolves those tables.  Selection is
tournament; reproduction is per-rule-table crossover with byte-level
mutation; elites carry through unchanged.

Two flavours of evolution:

  * ``evolve_primitive``  — fix one primitive (norm, attention,
    output, mlp) and evolve its rule(s) against a per-primitive
    fitness function (e.g. histogram-balance for norm, pair
    sensitivity for attention).  Cheapest: each generation only
    runs that primitive on test inputs.

  * ``evolve_full_stack`` — evolve every rule in
    ``ca_forward_qkv`` jointly against a corpus-prediction
    fitness.  Slow but tests primitives in their actual context.

Run any time:

    >>> from caformer.ga import evolve_primitive, NORM_FITNESS
    >>> result = evolve_primitive('norm', NORM_FITNESS,
    ...                            pop_size=24, generations=20)
    >>> result.best_rule        # 16,384-byte rule table
    >>> result.best_fitness     # final score
    >>> result.history          # per-gen (best, mean, worst)

Fitness functions live as module-level constants so the user can
swap them out (or define their own) without touching the GA loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .primitives import (
    hex_ca_step, lcg_bytes, random_rule_table,
    ca_qkv_project, ca_attention_score, ca_self_attention,
    ca_residual_merge, ca_layer_norm_iterative,
    ca_output_head_iterative,
)


# ──────────────────────────────────────────────────────────────────
# A genome = one or more named rule tables.  We use a dict so the
# same GA loop can evolve a single rule (norm) or a full bundle
# (Q/K/V/score/mix/merge/MLP/norm/output) without code changes.
# ──────────────────────────────────────────────────────────────────

Genome = Dict[str, np.ndarray]            # name → 16,384-byte rule table
FitnessFn = Callable[[Genome], float]     # higher = better


@dataclass
class GAConfig:
    pop_size:       int   = 24
    generations:    int   = 20
    tournament_k:   int   = 3
    elite_n:        int   = 2
    mutation_rate:  float = 0.005       # per-byte flip probability
    crossover_p:    float = 0.5         # bias toward parent A
    seed:           int   = 0xCAB00B5
    # When >0, with this probability per rule we splice the two parents
    # by swapping a small contiguous window (~5% of the LUT) instead of
    # swapping the whole table. Off by default — A/B over short runs
    # showed it can hurt; helps once the population converges and you
    # need finer-grained recombination. Opt in via `intra_table_p=0.3`.
    intra_table_p:  float = 0.0
    # When <1.0, mutation rate decays linearly from `mutation_rate`
    # (gen 0) to `mutation_rate * mutation_floor_frac` (last gen).
    # Early generations explore, late generations fine-tune. Helpful
    # at high generation counts (20+); hurts shorter runs because the
    # late-gen exploit phase doesn't have enough generations to use.
    # Default 1.0 = constant rate (no anneal).
    mutation_floor_frac: float = 1.0
    # When >1, fitness evaluations within a generation are scattered
    # across N worker threads. Default 0 means: pick automatically —
    # half the CPU cores (per the user's "never burn more than half
    # the CPU" rule). 1 forces sequential.
    #
    # CAVEAT: smoke-tested 2026-05-16 found ThreadPool actually 12×
    # SLOWER than sequential for caformer's small-grid workload —
    # numpy doesn't release the GIL well on the 16×16 ops in the
    # hot path, and thread contention overwhelms any parallelism
    # gain. The knob ships as a no-op-or-worse default; real
    # parallelism needs ProcessPool, which requires a picklable
    # fitness function (current closures aren't). Future work.
    parallel_workers: int = 0
    # Diversity regulariser: when >0, subtract
    #   weight * max(0, mean_pairwise_byte_equality - 0.25)
    # from each individual's fitness during selection.  Penalises
    # whole-stack solutions where multiple rule slots collapse into
    # byte-identical LUTs.  0.25 is the K=4 random baseline; any
    # excess pairwise match counts as "two slots are the same rule".
    # Useful range: 1.0–5.0 when base fitness is normalised to [0, 1].
    # 0 (default) disables the regulariser entirely.
    diversity_weight: float = 0.0
    # Fire-mask-restricted mutation: when provided, mutations only
    # touch LUT indices marked True in this 16384-bool array.  The
    # mask is the union of LUT entries actually queried during one
    # CA evaluation of the rule on the training input — typically <5%
    # of entries at 128×128.  Mutating only those entries turns the
    # intractable 16384-entry search into a manageable few-hundred-
    # entry search, which is the gating step for board sizes ≥64.
    # Build with caformer.primitives.compute_fire_mask().  When None
    # (default), mutation runs over the full LUT as before.
    fire_mask: object = None    # Optional[np.ndarray], 16384 bool


@dataclass
class GAResult:
    best_genome:  Genome
    best_fitness: float
    history:      List[Tuple[float, float, float]]   # (best, mean, worst) per gen


# ──────────────────────────────────────────────────────────────────
# Selection / crossover / mutation primitives.  Generic over the
# Genome shape — reused by both evolve_primitive and evolve_full_stack.
# ──────────────────────────────────────────────────────────────────

def _tournament(scored: List[Tuple[float, Genome]], k: int,
                rng: np.random.Generator) -> Genome:
    """Sample k individuals, return the highest-fitness one."""
    idxs = rng.integers(0, len(scored), size=k)
    best = max((scored[i] for i in idxs), key=lambda sg: sg[0])
    return best[1]


def _crossover(a: Genome, b: Genome, rng: np.random.Generator,
               crossover_p: float, intra_table_p: float = 0.0) -> Genome:
    """Per-rule-table coin flip: each named rule comes from parent A
    (with probability crossover_p) or parent B.  Single-table genomes
    fall back to byte-level mask crossover so we still get *some*
    mixing — without it a 1-rule GA would just shuffle parents.

    When ``intra_table_p > 0``, with that probability per rule we
    instead splice the two parents at a single random index inside the
    rule table (single-point crossover within the 16,384-byte LUT).
    This finds gains that whole-table swap can't — most of GPT's
    behaviour lives in narrow windows of the LUT, and per-table swap
    can only ever pick "all of A's window" or "all of B's window"."""
    out: Genome = {}
    if len(a) > 1:
        for name in a:
            if intra_table_p > 0 and rng.random() < intra_table_p:
                # Swap a small contiguous window (~5% of LUT) from b
                # into a copy of a. Single-point cut at random index
                # was too disruptive (half the table at once); a
                # narrow window lets each cross test a localised
                # change without destroying the rest of the rule.
                size = a[name].size
                win = max(8, size // 20)
                start = int(rng.integers(0, size - win + 1))
                out[name] = a[name].copy()
                out[name][start:start + win] = b[name][start:start + win]
                out[name] &= 3
            else:
                out[name] = a[name].copy() if rng.random() < crossover_p \
                                           else b[name].copy()
        return out
    name = next(iter(a))
    mask = rng.integers(0, 2, size=a[name].size, dtype=np.uint8).astype(bool)
    blended = np.where(mask, a[name], b[name])
    out[name] = blended.astype(np.uint8) & 3
    return out


def _mutate(g: Genome, rng: np.random.Generator,
            rate: float, *,
            fire_mask: Optional[np.ndarray] = None) -> Genome:
    """Flip ~rate fraction of bytes per rule to a fresh random colour.

    When ``fire_mask`` is provided (a 16384-bool array), mutations only
    touch indices where the mask is True — i.e. LUT entries that were
    actually queried during the rule's most recent CA evaluation.  At
    128×128 this typically restricts mutation to ~few-hundred indices
    instead of the full 16384, turning an intractable search into a
    tractable one.  ``rate`` is interpreted relative to the *mask
    size*, not the full LUT, so the absolute mutation count stays
    similar to the unrestricted case.
    """
    if fire_mask is not None:
        mask_size = int(fire_mask.sum())
        if mask_size == 0:
            return g    # nothing fired; mutation would be no-op anyway
    for name in g:
        if fire_mask is not None and g[name].size == fire_mask.size:
            # Restricted mutation: only flip indices in the fire mask.
            # Sample which masked indices to flip; rate is per-masked-byte.
            masked_idx = np.flatnonzero(fire_mask)
            flips_mask = rng.random(masked_idx.size) < rate
            if flips_mask.any():
                hit_idx = masked_idx[flips_mask]
                new_bytes = rng.integers(0, 4, size=hit_idx.size,
                                          dtype=np.uint8)
                g[name] = g[name].copy()
                g[name][hit_idx] = new_bytes
        else:
            # Unrestricted (legacy): flip across the whole LUT.
            flips = rng.random(g[name].size) < rate
            if flips.any():
                new_bytes = rng.integers(0, 4, size=int(flips.sum()),
                                           dtype=np.uint8)
                g[name] = g[name].copy()
                g[name][flips] = new_bytes
    return g


def _seed_genome(template: Genome, seed: int) -> Genome:
    """Build a fresh random genome that has the same shape as `template`."""
    out: Genome = {}
    for i, name in enumerate(template):
        out[name] = random_rule_table(seed ^ (0x10000 * (i + 1)))
    return out


# ──────────────────────────────────────────────────────────────────
# The GA loop — one function used by both evolve_primitive and
# evolve_full_stack.  Pure: the fitness function is the only thing
# that distinguishes the two modes.
# ──────────────────────────────────────────────────────────────────

def _genome_diversity_penalty(g: Genome) -> float:
    """Combined diversity penalty in [0, ~1.7]:

      * ``max(0, mean_pairwise_match - 0.25)``  — catches over-similar
        rules where many bytes agree pairwise (K=4 baseline = 0.25).
      * ``(N - distinct_count) / N``            — catches byte-exact
        slot collapse (shakespeare-tiny: 4 distinct LUTs / 10 slots
        gives 0.60 here even though byte-match is below baseline).

    Sum of both, so rules can be punished for either mode of
    degeneracy.  Returns 0 when all N slots are byte-distinct AND
    pairwise-uncorrelated.
    """
    import numpy as np
    names = list(g.keys())
    if not names:
        return 0.0
    total = 0
    n_pairs = 0
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            total += int((g[names[i]] == g[names[j]]).sum())
            n_pairs += 1
    size = g[names[0]].size
    mean_match = total / (n_pairs * size) if n_pairs else 0.0
    # Count byte-distinct groups
    seen = [False] * len(names)
    n_distinct = 0
    for i in range(len(names)):
        if seen[i]:
            continue
        n_distinct += 1
        seen[i] = True
        for j in range(i + 1, len(names)):
            if not seen[j] and np.array_equal(g[names[i]], g[names[j]]):
                seen[j] = True
    return (max(0.0, mean_match - 0.25)
            + (len(names) - n_distinct) / float(len(names)))


def _evolve(template: Genome, fitness: FitnessFn,
            cfg: GAConfig, *, on_generation=None,
            on_individual=None) -> GAResult:
    """Run the GA. Optional callbacks let the caller see live progress:

      ``on_individual(gen_idx, ind_idx, score)`` — fired after every
        single fitness evaluation, so a UI can show "8/16 individuals
        scored in this gen" instead of going dark for minutes.
      ``on_generation(gen_idx, best, mean, worst)`` — fired once per
        generation after sorting, before breeding the next pop.

    Both callbacks are optional and synchronous (called in the same
    thread that runs the GA).
    """
    # Diversity regulariser: when cfg.diversity_weight > 0, wrap the
    # base fitness with a penalty for rule-slot collapse.  Done once
    # outside the per-individual loop so the wrapper closure is reused.
    if cfg.diversity_weight > 0:
        _base_fitness = fitness

        def _fitness_with_diversity(g: Genome) -> float:
            return _base_fitness(g) - cfg.diversity_weight * \
                       _genome_diversity_penalty(g)
        fitness = _fitness_with_diversity
    rng = np.random.default_rng(cfg.seed)
    pop: List[Genome] = [_seed_genome(template, cfg.seed + i)
                          for i in range(cfg.pop_size)]
    history: List[Tuple[float, float, float]] = []
    # Resolve parallel_workers: 0 → auto = half the CPU cores (rounded
    # down, min 1). User constraint: never use more than nproc//2.
    import os
    if cfg.parallel_workers == 0:
        n_workers = max(1, (os.cpu_count() or 2) // 2)
    else:
        n_workers = max(1, int(cfg.parallel_workers))
    # ThreadPool only — fitness functions are closures over the corpus
    # and aren't picklable for ProcessPool. numpy releases the GIL on
    # most array ops, so threading does buy us real parallelism.
    pool = None
    if n_workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        pool = ThreadPoolExecutor(max_workers=n_workers)
    # Hall-of-fame: never lose the all-time-best genome to mutation. A
    # high-fitness elite can be wiped out if every breeding pair
    # mutates it apart; this guards against that. Re-injected as one
    # of the elites every generation regardless of current standing.
    best_ever_g: Optional[Genome] = None
    best_ever_s: float = -float('inf')
    G = max(1, cfg.generations)
    for gen_idx in range(cfg.generations):
        scored = []
        if pool is None:
            for ind_idx, g in enumerate(pop):
                s = fitness(g)
                scored.append((s, g))
                if on_individual is not None:
                    on_individual(gen_idx, ind_idx, s)
        else:
            # Submit all genomes to the pool; collect in submission
            # order so on_individual fires deterministically (callback
            # contract: ind_idx matches the population index).
            futs = [pool.submit(fitness, g) for g in pop]
            for ind_idx, fut in enumerate(futs):
                s = fut.result()
                scored.append((s, pop[ind_idx]))
                if on_individual is not None:
                    on_individual(gen_idx, ind_idx, s)
        scored.sort(key=lambda sg: -sg[0])
        if scored[0][0] > best_ever_s:
            best_ever_s = scored[0][0]
            best_ever_g = {k: v.copy() for k, v in scored[0][1].items()}
        scores = [s for s, _ in scored]
        history.append((scores[0], float(np.mean(scores)), scores[-1]))
        if on_generation is not None:
            on_generation(gen_idx, scores[0], float(np.mean(scores)),
                            scores[-1])
        # Linear mutation anneal: high early (explore), low late
        # (exploit). At generation 0 use cfg.mutation_rate; at the
        # final generation use cfg.mutation_rate * mutation_floor_frac.
        if cfg.mutation_floor_frac > 0 and G > 1:
            t = gen_idx / (G - 1)
            mut_rate = cfg.mutation_rate * (
                1.0 + t * (cfg.mutation_floor_frac - 1.0))
        else:
            mut_rate = cfg.mutation_rate
        # Elites pass through untouched. Always include the all-time
        # best as the first elite so a mutation regression can't lose
        # the whole run's progress.
        next_pop: List[Genome] = []
        if best_ever_g is not None:
            next_pop.append({k: v.copy() for k, v in best_ever_g.items()})
        for _, g in scored[:cfg.elite_n]:
            if len(next_pop) >= cfg.elite_n + 1:
                break
            next_pop.append(g)
        # Fill the rest with tournament-selected, crossed, mutated kids.
        while len(next_pop) < cfg.pop_size:
            a = _tournament(scored, cfg.tournament_k, rng)
            b = _tournament(scored, cfg.tournament_k, rng)
            kid = _crossover(a, b, rng, cfg.crossover_p,
                              intra_table_p=cfg.intra_table_p)
            kid = _mutate(kid, rng, mut_rate, fire_mask=cfg.fire_mask)
            next_pop.append(kid)
        pop = next_pop
    # Final scoring on the post-mutation population to surface the winner.
    try:
        if pool is None:
            final_scored = [(fitness(g), g) for g in pop]
        else:
            final_futs = [pool.submit(fitness, g) for g in pop]
            final_scored = [(f.result(), g) for f, g in zip(final_futs, pop)]
    finally:
        # ALWAYS shut down — even on exception or KeyboardInterrupt.
        # Without this, a GA failure leaves the pool's workers alive,
        # and the autotournament loop creates a new pool every cycle,
        # so worker threads compound until daphne hits 'cannot schedule
        # new futures after shutdown'.
        if pool is not None:
            pool.shutdown(wait=False)
    final = sorted(final_scored, key=lambda sg: -sg[0])
    if best_ever_g is not None and best_ever_s > final[0][0]:
        # Hall-of-fame still beats the post-final-mutation pool.
        return GAResult(best_genome=best_ever_g, best_fitness=best_ever_s,
                          history=history)
    return GAResult(best_genome=final[0][1],
                    best_fitness=final[0][0], history=history)


# ──────────────────────────────────────────────────────────────────
# Per-primitive fitness functions.  Each one tests ONE primitive
# against many random inputs and returns a higher-is-better scalar.
#
# Keep them deterministic (seeded RNG) so successive evolutions are
# comparable across runs.
# ──────────────────────────────────────────────────────────────────

_FITNESS_RNG_SEED = 0xF17BE55          # shared RNG for all fitness fns


def _rand_state(seed: int, side: int = 16) -> np.ndarray:
    """One deterministic K=4 hex grid for fitness testing."""
    return (lcg_bytes(seed, side * side) & 3).reshape(side, side)


def NORM_FITNESS(g: Genome) -> float:
    """A norm rule is good when iterating it on an unbalanced input
    drives the colour histogram toward uniform.  Score = (16 - sum |c_i
    - target|) summed across 8 random unbalanced inputs.

    Higher = closer to uniform after `k_ticks` of the candidate rule."""
    rule = g['norm']
    rng = np.random.default_rng(_FITNESS_RNG_SEED)
    total = 0.0
    target = 64.0      # 256 cells / 4 colours = 64 each on a 16×16 grid
    for trial in range(8):
        # Build a deliberately unbalanced state: dominant colour + a
        # sprinkle of others.  The norm rule has to undo this skew.
        state = np.full((16, 16), trial & 3, dtype=np.uint8)
        n_pert = rng.integers(8, 32)
        idxs = rng.integers(0, 256, size=n_pert)
        cols = rng.integers(0, 4, size=n_pert, dtype=np.uint8)
        flat = state.flatten()
        flat[idxs] = cols
        state = flat.reshape(16, 16)
        for _ in range(4):
            state = hex_ca_step(state, rule)
        counts = np.bincount(state.flatten(), minlength=4).astype(np.float64)
        total -= float(np.abs(counts - target).sum())
    return total


def ATTENTION_SCORE_FITNESS(g: Genome) -> float:
    """A score rule is good when ca_attention_score(Q, K) is meaningfully
    different for different Ks — i.e. the rule actually varies its
    output with the K input rather than being almost-constant.

    Score = stddev(scores) over a panel of (Q, K_j) pairs minus a small
    penalty if any pair-score is degenerate (== 0)."""
    rule = g['score']
    rng = np.random.default_rng(_FITNESS_RNG_SEED + 1)
    Q = (rng.integers(0, 4, size=(16, 16))).astype(np.uint8)
    Ks = [(rng.integers(0, 4, size=(16, 16))).astype(np.uint8)
           for _ in range(8)]
    scores = np.array([ca_attention_score(Q, K, rule) for K in Ks],
                       dtype=np.float64)
    return float(scores.std()) - 0.5 * float((scores == 0).sum())


def OUTPUT_HEAD_FITNESS(g: Genome) -> float:
    """An output-head rule is good when the resulting logits are
    *peaked* (some vocab indices are clearly preferred over others)
    AND *responsive* (different inputs produce different argmax tokens).

    Score = (mean argmax-distinctness across 4 inputs)
            + (mean logit max minus logit median)."""
    rule = g['output']
    rng = np.random.default_rng(_FITNESS_RNG_SEED + 2)
    states = [(rng.integers(0, 4, size=(16, 16))).astype(np.uint8)
               for _ in range(4)]
    logits_set = [
        ca_output_head_iterative(s, output_rule=rule, vocab_size=64,
                                   k_ticks=2)
        for s in states
    ]
    argmaxes = {int(L.argmax()) for L in logits_set}
    distinctness = len(argmaxes) / len(states)
    peakedness = float(np.mean([L.max() - np.median(L) for L in logits_set]))
    return distinctness + 0.1 * peakedness


def MLP_FITNESS(g: Genome) -> float:
    """An MLP rule is good when iterating it on an input changes the
    state without collapsing it to a single colour.

    Score = (cell-change ratio after 2 ticks) - (penalty if state
    becomes mono-colour after 4 ticks).  Encourages rich nonlinearity
    without runaway saturation."""
    rule = g['mlp']
    rng = np.random.default_rng(_FITNESS_RNG_SEED + 3)
    total = 0.0
    for trial in range(4):
        s0 = (rng.integers(0, 4, size=(16, 16))).astype(np.uint8)
        s2 = s0.copy()
        for _ in range(2):
            s2 = hex_ca_step(s2, rule)
        change = float((s0 != s2).mean())
        s4 = s2.copy()
        for _ in range(2):
            s4 = hex_ca_step(s4, rule)
        unique = len(np.unique(s4))
        collapse_penalty = 0.0 if unique >= 3 else (3 - unique)
        total += change - collapse_penalty
    return total / 4.0


# Catalogue so the user can list them.
PRIMITIVE_FITNESS: Dict[str, FitnessFn] = {
    'norm':      NORM_FITNESS,
    'score':     ATTENTION_SCORE_FITNESS,
    'output':    OUTPUT_HEAD_FITNESS,
    'mlp':       MLP_FITNESS,
}


def evolve_primitive(name: str, fitness: Optional[FitnessFn] = None,
                      *, pop_size: int = 24, generations: int = 20,
                      seed: int = 0xCAB00B5,
                      tournament_k: int = 3, elite_n: int = 2,
                      mutation_rate: float = 0.005) -> GAResult:
    """Evolve a single rule table by name.  `name` ∈ {norm, score,
    output, mlp}; defaults to the matching PRIMITIVE_FITNESS entry
    if `fitness` is None."""
    if name not in PRIMITIVE_FITNESS:
        raise ValueError(
            f'unknown primitive {name!r}; '
            f'choose from {sorted(PRIMITIVE_FITNESS)}')
    fn = fitness or PRIMITIVE_FITNESS[name]
    cfg = GAConfig(pop_size=pop_size, generations=generations,
                    tournament_k=tournament_k, elite_n=elite_n,
                    mutation_rate=mutation_rate, seed=seed)
    template: Genome = {name: random_rule_table(seed)}
    return _evolve(template, fn, cfg)


# ──────────────────────────────────────────────────────────────────
# Full-stack evolution — every rule table in a forward pass evolved
# together against a corpus-prediction fitness.  This is the slow path
# but it tests primitives in their actual context.
# ──────────────────────────────────────────────────────────────────

FULL_STACK_NAMES = ('q', 'k', 'v', 'score', 'mix', 'merge', 'mlp',
                     'norm', 'output', 'embed')


def make_corpus_fitness(corpus_seed: int = 42, *,
                         vocab_size: int = 64,
                         n_seq: int = 8, seq_len: int = 12,
                         n_blocks: int = 2) -> FitnessFn:
    """Build a fitness function that scores a full-stack genome by how
    well it predicts the next token in a CA-generated corpus.  Higher
    score = more correct argmax predictions on held-out positions."""
    from .data import ca_corpus_tokenised
    from .transformer import ca_forward_qkv
    corpus = ca_corpus_tokenised(corpus_seed,
                                  vocab_size=vocab_size,
                                  n_seq=n_seq, seq_len=seq_len)

    def _f(g: Genome) -> float:
        block_rules = [{
            'q':     g['q'],     'k':     g['k'],
            'v':     g['v'],     'score': g['score'],
            'mix':   g['mix'],   'merge': g['merge'],
            'mlp':   g['mlp'],
        }] * n_blocks
        correct = 0
        total = 0
        for seq in corpus:
            for end in range(2, seq_len - 1):
                logits = ca_forward_qkv(
                    seq[:end].tolist(),
                    n_blocks=n_blocks,
                    embed_rule=g['embed'],
                    block_rules=block_rules,
                    norm_rule=g['norm'],
                    output_rule=g['output'],
                    vocab_size=vocab_size)
                if int(logits.argmax()) == int(seq[end]):
                    correct += 1
                total += 1
        return correct / max(1, total)
    return _f


def make_text_fitness(text: str, *, vocab_size: int = 256,
                       n_blocks: int = 2, n_windows: int = 16,
                       window_len: int = 12,
                       mode: str = 'logprob') -> FitnessFn:
    """Fitness for training the chat on real natural-language text.

    Treats every byte of the input as a token (vocab_size = 256 by
    default, matching what the chat endpoint uses). Slices the
    corpus into ``n_windows`` random fixed-length windows and scores
    a genome by its predictions at the *last* position across those
    windows.

    Two scoring modes (``mode=``):

      ``'logprob'`` (default, recommended) — mean log-probability of
        the true next byte under softmax(logits). Continuous signal in
        ``(-log V, 0]``; even genomes whose argmax is wrong get a
        gradient toward the truth. This is what unblocks the GA from
        the all-zeros plateau that argmax-accuracy lands on with
        256-byte vocab and random rules.

      ``'argmax'`` (legacy) — fraction of windows where argmax matches
        the true next byte. Bounded ``[0, 1]`` but flat near zero for
        random initialisations; kept for backwards compat / sanity.

    Stable seeded sampling so fitness is reproducible across GA runs
    against the same corpus.
    """
    import random as _random
    from .transformer import ca_forward_qkv

    if mode not in ('logprob', 'argmax'):
        raise ValueError(f'mode must be logprob|argmax, got {mode!r}')
    raw = text.encode('utf-8') if isinstance(text, str) else bytes(text)
    if len(raw) < window_len + 2:
        raise ValueError(f'corpus too short: {len(raw)} bytes; '
                          f'need at least {window_len + 2}')
    rng = _random.Random(0xC0DECA)
    starts = [rng.randint(0, len(raw) - window_len - 2)
              for _ in range(n_windows)]

    def _f(g: Genome) -> float:
        block_rules = [{
            'q':     g['q'],     'k':     g['k'],
            'v':     g['v'],     'score': g['score'],
            'mix':   g['mix'],   'merge': g['merge'],
            'mlp':   g['mlp'],
        }] * n_blocks
        if mode == 'argmax':
            correct = 0
            for s in starts:
                window = list(raw[s:s + window_len])
                true_next = int(raw[s + window_len])
                logits = ca_forward_qkv(
                    window, n_blocks=n_blocks,
                    embed_rule=g['embed'], block_rules=block_rules,
                    norm_rule=g['norm'], output_rule=g['output'],
                    vocab_size=vocab_size)
                if int(logits.argmax()) == true_next:
                    correct += 1
            return correct / n_windows
        # logprob: stable softmax then log of the true byte's probability.
        total_lp = 0.0
        for s in starts:
            window = list(raw[s:s + window_len])
            true_next = int(raw[s + window_len])
            logits = ca_forward_qkv(
                window, n_blocks=n_blocks,
                embed_rule=g['embed'], block_rules=block_rules,
                norm_rule=g['norm'], output_rule=g['output'],
                vocab_size=vocab_size)
            shifted = logits - float(logits.max())
            exp = np.exp(shifted)
            denom = float(exp.sum())
            if denom <= 0.0 or not np.isfinite(denom):
                # Output head produced all -inf / NaN — score as the
                # uniform baseline so the GA still has a reference.
                total_lp += -float(np.log(vocab_size))
                continue
            p_true = float(exp[true_next] / denom)
            total_lp += float(np.log(max(p_true, 1e-30)))
        return total_lp / n_windows
    return _f


def make_qr_fitness(query: str, expected: str, *,
                      n_blocks: int = 1, max_ctx: int = 96,
                      argmax_bonus: float = 2.0,
                      autoregressive: bool = True) -> FitnessFn:
    """Targeted Q→R fitness: score the genome on producing exactly
    ``expected`` after seeing ``query`` as prompt.

    Two contributions per byte:

      * **log-prob term** — log P(target[i] | context).  Smooth signal
        that gives the GA a gradient even when no byte argmaxes.
      * **argmax bonus** — ``+argmax_bonus`` when the model's argmax
        equals target[i].  Discrete reward that the GA can lock onto;
        without this the genome converges on log-prob improvements
        that never actually flip the argmax.

    When ``autoregressive`` is True (the default), the context for
    each step is the prompt + the model's *own* argmax outputs so far
    — exactly what inference will see — instead of the teacher-forcing
    target prefix.  This eliminates the training-vs-inference gap
    that made curriculum training destabilize earlier bytes.

    Returned fitness is mean per-byte (log-prob + argmax-bonus·match);
    higher = better.  Max possible ≈ argmax_bonus when every byte
    matches exactly with prob → 1.
    """
    from .transformer import ca_forward_qkv
    prompt = list(query.encode('utf-8'))[:max_ctx]
    target = list(expected.encode('utf-8'))[:max_ctx]
    if not target:
        raise ValueError('expected response must be non-empty')

    def _f(g: Genome) -> float:
        block_rules = [{
            'q':     g['q'],     'k':     g['k'],
            'v':     g['v'],     'score': g['score'],
            'mix':   g['mix'],   'merge': g['merge'],
            'mlp':   g['mlp'],
        }] * n_blocks
        total = 0.0
        ctx = list(prompt)
        for i in range(len(target)):
            true_next = target[i]
            logits = ca_forward_qkv(
                ctx, n_blocks=n_blocks,
                embed_rule=g['embed'], block_rules=block_rules,
                norm_rule=g['norm'], output_rule=g['output'],
                vocab_size=256)
            shifted = logits - float(logits.max())
            exp = np.exp(shifted)
            denom = float(exp.sum())
            if denom <= 0.0 or not np.isfinite(denom):
                total += -float(np.log(256)); ctx.append(true_next); continue
            p_true = float(exp[true_next] / denom)
            total += float(np.log(max(p_true, 1e-30)))
            argmax = int(np.argmax(logits))
            if argmax == true_next:
                total += argmax_bonus
            # Next step's context: model's own argmax (inference-time)
            # or true byte (teacher forcing).
            ctx.append(argmax if autoregressive else true_next)
        return total / len(target)
    return _f


def polish_genome(genome: Genome, fitness: FitnessFn, *,
                    trials: int = 60, seed: int = 0,
                    on_trial: Optional[Callable] = None,
                    fire_mask: Optional[np.ndarray] = None
                    ) -> Tuple[Genome, float, int]:
    """Stochastic coordinate descent on a genome's LUT entries.

    Algorithm: for ``trials`` rounds, pick a random (rule, lut_index)
    pair and try each of the 4 possible colours; keep whichever
    maximises ``fitness``. Strictly monotone — never regresses, since
    we only commit a change if it improved the score.

    Cost: ``trials × (n_colours - 1)`` fitness evaluations. With the
    default 60 trials and 3 candidate colours that's 180 evals; at the
    typical ~150 ms/eval (4-window fitness, n_blocks=2) that's ~30 s.
    Bump ``trials`` for a longer polish; the score plateau is the
    natural stopping rule.

    ``on_trial(trial_idx, current_fitness, improved)`` fires after
    each trial — same callback shape as the GA's ``on_individual`` so
    the UI can show live progress.

    Returns: (polished_genome, best_fitness, n_improvements).
    """
    rng = np.random.default_rng(seed)
    g = {k: v.copy() for k, v in genome.items()}
    best_score = fitness(g)
    improvements = 0
    rule_names = list(g.keys())
    # Fire-mask-restricted polish: when given, the coordinate descent
    # only considers LUT indices that actually fire during evaluation.
    # Drastically narrows the search at 128×128 (mask is typically a
    # few hundred indices out of 16384).
    masked_idx = None
    if fire_mask is not None and fire_mask.any():
        masked_idx = np.flatnonzero(fire_mask)
    for trial_idx in range(trials):
        rname = rule_names[int(rng.integers(0, len(rule_names)))]
        if (masked_idx is not None and
                g[rname].size == fire_mask.size and
                masked_idx.size > 0):
            idx = int(masked_idx[int(rng.integers(0, masked_idx.size))])
        else:
            idx = int(rng.integers(0, g[rname].size))
        original = int(g[rname][idx])
        round_improved = False
        for v in range(4):
            if v == original:
                continue
            g[rname][idx] = np.uint8(v)
            s = fitness(g)
            if s > best_score:
                best_score = s
                original = v          # accept and continue searching
                round_improved = True
            else:
                g[rname][idx] = np.uint8(original)
        if round_improved:
            improvements += 1
        if on_trial is not None:
            on_trial(trial_idx, best_score, round_improved)
    return g, best_score, improvements


def save_genome_as_model(genome: Genome, *, name: str, slug: str,
                          notes: str = '', corpus_excerpt: str = '',
                          vocab_size: int = 256, n_blocks: int = 2,
                          pop_size: int = 8, generations: int = 6,
                          final_fitness: float = 0.0,
                          history: Optional[list] = None):
    """Persist a GA winner as a ``caformer.models.TrainedModel`` row.
    The ten rule tables are stored verbatim as 16,384-byte BinaryFields
    so the chat / DMN endpoints can load them with one query."""
    from .models import TrainedModel
    obj, _ = TrainedModel.objects.update_or_create(
        slug=slug, defaults=dict(
            name=name, notes=notes,
            rule_q     =bytes(genome['q']),
            rule_k     =bytes(genome['k']),
            rule_v     =bytes(genome['v']),
            rule_score =bytes(genome['score']),
            rule_mix   =bytes(genome['mix']),
            rule_merge =bytes(genome['merge']),
            rule_mlp   =bytes(genome['mlp']),
            rule_norm  =bytes(genome['norm']),
            rule_output=bytes(genome['output']),
            rule_embed =bytes(genome['embed']),
            corpus_excerpt=corpus_excerpt[:500],
            vocab_size=vocab_size, n_blocks=n_blocks,
            pop_size=pop_size, generations=generations,
            final_fitness=final_fitness,
            history_json=history or [],
        ))
    return obj


def evolve_full_stack(*, pop_size: int = 8, generations: int = 6,
                       seed: int = 0xCAB00B5,
                       fitness: Optional[FitnessFn] = None) -> GAResult:
    """Evolve every rule table in ca_forward_qkv jointly.  Default
    fitness is corpus-prediction accuracy.  Default scale is small
    (8 individuals × 6 generations) because each fitness call is
    O(n_seq × seq_len) full forward passes — see make_corpus_fitness
    if you want to tune."""
    fn = fitness or make_corpus_fitness()
    cfg = GAConfig(pop_size=pop_size, generations=generations,
                    tournament_k=3, elite_n=1,
                    mutation_rate=0.003, seed=seed)
    template: Genome = {n: random_rule_table(seed ^ (0x100 * (i + 1)))
                          for i, n in enumerate(FULL_STACK_NAMES)}
    return _evolve(template, fn, cfg)
