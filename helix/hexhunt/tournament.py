"""Tournament — evolve hex CA rules against a HuntCorpus.

One generation:
  1. Score every rule by the mean of its scoring-fn output across N
     windows sampled from the corpus.
  2. Sort, keep the top fraction (truncation selection), copy the
     single best as untouched elite.
  3. Refill the population with mutated copies of survivors, plus a
     fraction of fresh uniform-crossover children.

Random seeds: a fixed RNG seed is recorded in HuntRun.params_json so
re-running with the same seed against the same corpus produces an
identical leaderboard.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import numpy as np

from automaton.packed import PackedRuleset

from . import engine
from .mapping import dna_to_board, WINDOW_SIZE


@dataclass
class TournamentParams:
    population_size: int = 256
    generations: int = 200
    elite: int = 1
    survivor_fraction: float = 0.25
    mutation_rate: float = 0.001
    crossover_fraction: float = 0.20
    windows_per_gen: int = 8
    scoring_fn: str = 'edge'
    steps: int = engine.TOTAL_STEPS
    rng_seed: int = 0
    progress_every: int = 1
    init_from_identity: bool = True
    init_mutation_rate: float = 0.05
    # Board side length for fitness evaluation.  16 (the default) gives
    # a 16×16 board — fits ``WINDOW_SIZE`` exactly so corpus windows map
    # 1:1.  Larger sides give more cells per eval = lower-noise class-4
    # signal at quadratic cost (32 = 4×, 64 = 16×, 128 = 64× the per-step
    # work).  Useful when hunting for rules whose class-4 character only
    # becomes visible at scale.
    board_side: int = 16

    # Self-reproduction validation: every ``validation_every`` gens,
    # take the top ``validation_elite_n`` rules and test whether each
    # one reproduces itself.  The 16,384-entry LUT is laid out as a
    # 128×128 hex grid; that grid is used as the initial state; the
    # rule is run for ``validation_steps`` ticks; fitness = hamming
    # similarity (matched cells / 16,384) between the final grid and
    # the original LUT-as-image.  Higher = more self-reproducing.
    # Direct test of meta-evolution: a class-4 rule that re-produces
    # itself is, by construction, a class-4 generator of a class-4.
    # Replaces the elites' GA fitness for this gen's selection.
    # Default disabled (validation_every = 0).
    validation_every: int = 0
    validation_elite_n: int = 8
    validation_steps: int = 64


@dataclass
class GenLog:
    gen: int
    best: float
    mean: float
    elapsed_s: float
    # Discriminator-only — None for single-corpus runs.
    pos_mean: Optional[float] = None
    neg_mean: Optional[float] = None
    # Self-reproduction validation: populated on the gens where the
    # elite set was re-scored.  ``self_reproduce_scores`` is a list of
    # (population_index, hamming_similarity_0_to_1) tuples for each
    # elite tested this gen; the scores have already been written
    # back to the elites' fitness for selection.
    self_reproduce_scores: Optional[List] = None


@dataclass
class TournamentResult:
    final_population: List[PackedRuleset]
    final_scores: List[float]
    log: List[GenLog] = field(default_factory=list)
    params: TournamentParams = field(default_factory=TournamentParams)
    # Per-rule pos/neg breakdown for the final population — only set
    # in discriminator mode so the management command can persist it.
    final_pos_scores: List[float] = field(default_factory=list)
    final_neg_scores: List[float] = field(default_factory=list)


def _score_rule(rule_table: np.ndarray,
                boards: List[np.ndarray],
                params: TournamentParams) -> float:
    total = 0.0
    for board in boards:
        st = engine.evolve(board, rule_table, steps=params.steps)
        total += engine.score(st, params.scoring_fn)
    return total / max(1, len(boards))


def _sample_boards(corpus_sequences: List[str],
                   rng: random.Random,
                   k: int,
                   board_side: int = 16) -> List[np.ndarray]:
    """Pick k windows and turn them into boards.

    Each window seed is its index in the corpus, so a given window's
    random-fill mask is stable across generations even though we
    sample different subsets per generation.

    When ``board_side != 16``, the 16×16 DNA window is tiled across the
    larger board so the corpus seed still shapes initial state but the
    extra cells are filled with seeded random colour — gives class-4
    mutations a bigger canvas to express without losing the corpus
    correlation that the discriminator path relies on.
    """
    if k >= len(corpus_sequences):
        chosen = list(range(len(corpus_sequences)))
    else:
        chosen = rng.sample(range(len(corpus_sequences)), k)
    boards = []
    for i in chosen:
        base = dna_to_board(corpus_sequences[i], seed=i)
        if board_side == base.shape[0]:
            boards.append(base)
            continue
        big = np.empty((board_side, board_side), dtype=base.dtype)
        # Seeded random fill so the same window gives the same big
        # board every generation.
        r = np.random.default_rng(i ^ 0xC1A554 ^ board_side)
        big[:] = r.integers(0, 4, size=(board_side, board_side),
                              dtype=base.dtype)
        # Stamp the DNA window into the top-left corner so corpus
        # signal still drives the initial state.
        h = min(board_side, base.shape[0])
        w = min(board_side, base.shape[1])
        big[:h, :w] = base[:h, :w]
        boards.append(big)
    return boards


def _self_reproduce_score(rule_table: np.ndarray, steps: int) -> float:
    """Score how closely a rule reproduces its own LUT.

    The 16,384-entry rule table is laid out as a 128×128 hex grid;
    that grid is used as the initial state; the rule is run for
    ``steps`` ticks; returns the fraction of cells in the final grid
    that match the initial grid.  1.0 = perfect fixed point.

    Since 4^7 = 16,384 = 128², the LUT maps cleanly onto the grid
    with no padding or truncation — every rule entry is one cell.
    """
    init = rule_table.reshape(128, 128).astype(np.int8)
    spacetime = engine.evolve(init, rule_table, steps=steps)
    final = spacetime[-1]
    return float((final == init).sum() / float(init.size))


def _validate_elites_self_reproduce(*,
                                      unpacked: List[np.ndarray],
                                      scores: List[float],
                                      params: 'TournamentParams') -> dict:
    """Re-score the top ``params.validation_elite_n`` rules by how well
    each one reproduces its own LUT-as-image after a short CA run.
    Replaces the elites' GA fitness for the next selection step.

    Returns:
        {
          'composite_by_index': {idx: float} self-reproduction score per
                                 elite (matched cells / 16,384),
          'composite_list':     [(idx, score), ...] sorted by idx for
                                 stable JSON encoding of the GenLog.
        }
    """
    elite_k = min(params.validation_elite_n, len(scores))
    if elite_k <= 0:
        return {'composite_by_index': {}, 'composite_list': []}
    elite_indices = sorted(range(len(scores)),
                              key=lambda i: -scores[i])[:elite_k]
    composite_by_index: dict = {}
    for i in elite_indices:
        composite_by_index[i] = _self_reproduce_score(
            unpacked[i], steps=params.validation_steps)
    composite_list = sorted(composite_by_index.items(), key=lambda kv: kv[0])
    return {
        'composite_by_index': composite_by_index,
        'composite_list':     composite_list,
    }


def run_tournament(corpus_sequences: List[str],
                   params: Optional[TournamentParams] = None,
                   on_generation: Optional[Callable[[GenLog], None]] = None,
                   neg_corpus_sequences: Optional[List[str]] = None,
                   ) -> TournamentResult:
    """Evolve a population of K=4 hex rules against the corpus.

    ``corpus_sequences`` is a list of 256-base strings. The function is
    pure — no DB access — so it can be unit-tested cheaply and the
    management command takes care of persistence.

    If ``neg_corpus_sequences`` is provided, switch to discriminator
    mode: fitness becomes ``mean(score on positive) - mean(score on
    negative)`` per generation. This selects for *contrastive*
    richness — rules that produce different behaviour on the two
    feature classes — which the single-corpus mean-fitness path
    structurally cannot do.
    """
    p = params or TournamentParams()
    rng = random.Random(p.rng_seed)

    if p.init_from_identity:
        # Sparse init: identity rule + 5% mutation. Random K=4 rules
        # land in Class III chaos with very low score variance, so
        # selection cannot bite. Sparse init starts the population
        # in Class I/II territory and lets evolution discover Class
        # IV from the quiet end.
        identity = PackedRuleset.identity(4)
        population: List[PackedRuleset] = [
            identity.mutate(p.init_mutation_rate, rng)
            for _ in range(p.population_size)
        ]
    else:
        population = [
            PackedRuleset.random(4, rng) for _ in range(p.population_size)
        ]
    result = TournamentResult(final_population=[], final_scores=[], params=p)

    discriminator = neg_corpus_sequences is not None and len(neg_corpus_sequences) > 0

    for gen in range(p.generations):
        t0 = time.time()
        pos_boards = _sample_boards(corpus_sequences, rng, p.windows_per_gen,
                                       board_side=p.board_side)
        unpacked = [engine.unpack_rule(r) for r in population]
        pos_scores = [_score_rule(u, pos_boards, p) for u in unpacked]
        if discriminator:
            neg_boards = _sample_boards(
                neg_corpus_sequences, rng, p.windows_per_gen,
                board_side=p.board_side,
            )
            neg_scores = [_score_rule(u, neg_boards, p) for u in unpacked]
            scores = [pos_scores[i] - neg_scores[i]
                      for i in range(p.population_size)]
        else:
            neg_scores = None
            scores = pos_scores

        # Self-reproduction validation: every Nth gen, re-score the top
        # elites by how closely each reproduces its own LUT-as-image
        # under its own CA, and replace their fitness with that score.
        # Direct test of meta-evolution — a rule that reproduces itself
        # is a class-4 generator of a class-4.
        sr_validation = None
        if (p.validation_every > 0
                and ((gen + 1) % p.validation_every == 0)):
            sr_validation = _validate_elites_self_reproduce(
                unpacked=unpacked, scores=scores, params=p,
            )
            # Overwrite elites' fitness with the self-reproduction score
            # so this gen's selection pursues self-reproducing rules.
            for idx, sr_score in sr_validation['composite_by_index'].items():
                scores[idx] = sr_score

        order = sorted(range(p.population_size), key=lambda i: -scores[i])
        ranked = [population[i] for i in order]
        ranked_scores = [scores[i] for i in order]
        ranked_pos = [pos_scores[i] for i in order] if discriminator else None
        ranked_neg = [neg_scores[i] for i in order] if discriminator else None

        n_survivors = max(2, int(p.population_size * p.survivor_fraction))
        survivors = ranked[:n_survivors]

        log = GenLog(
            gen=gen,
            best=ranked_scores[0],
            mean=float(np.mean(scores)),
            elapsed_s=time.time() - t0,
            pos_mean=float(np.mean(pos_scores)) if discriminator else None,
            neg_mean=float(np.mean(neg_scores)) if discriminator else None,
            self_reproduce_scores=(sr_validation['composite_list']
                                       if sr_validation else None),
        )
        result.log.append(log)
        if on_generation and (gen % p.progress_every == 0):
            on_generation(log)

        if gen == p.generations - 1:
            result.final_population = ranked
            result.final_scores = ranked_scores
            if discriminator:
                result.final_pos_scores = ranked_pos
                result.final_neg_scores = ranked_neg
            break

        # Reproduction: keep the elite untouched, fill rest with
        # mutated survivors + a fraction of crossovers.
        next_pop: List[PackedRuleset] = list(ranked[:p.elite])
        n_cross = int((p.population_size - p.elite) * p.crossover_fraction)
        n_mut = p.population_size - p.elite - n_cross

        for _ in range(n_cross):
            a, b = rng.sample(survivors, 2)
            child = a.crossover(b, rng).mutate(p.mutation_rate, rng)
            next_pop.append(child)
        for _ in range(n_mut):
            parent = rng.choice(survivors)
            next_pop.append(parent.mutate(p.mutation_rate, rng))

        population = next_pop

    return result
