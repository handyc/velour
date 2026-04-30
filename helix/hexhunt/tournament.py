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


@dataclass
class GenLog:
    gen: int
    best: float
    mean: float
    elapsed_s: float
    # Discriminator-only — None for single-corpus runs.
    pos_mean: Optional[float] = None
    neg_mean: Optional[float] = None


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
                   k: int) -> List[np.ndarray]:
    """Pick k windows and turn them into boards.

    Each window seed is its index in the corpus, so a given window's
    random-fill mask is stable across generations even though we
    sample different subsets per generation.
    """
    if k >= len(corpus_sequences):
        chosen = list(range(len(corpus_sequences)))
    else:
        chosen = rng.sample(range(len(corpus_sequences)), k)
    return [dna_to_board(corpus_sequences[i], seed=i) for i in chosen]


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
        pos_boards = _sample_boards(corpus_sequences, rng, p.windows_per_gen)
        unpacked = [engine.unpack_rule(r) for r in population]
        pos_scores = [_score_rule(u, pos_boards, p) for u in unpacked]
        if discriminator:
            neg_boards = _sample_boards(
                neg_corpus_sequences, rng, p.windows_per_gen,
            )
            neg_scores = [_score_rule(u, neg_boards, p) for u in unpacked]
            scores = [pos_scores[i] - neg_scores[i]
                      for i in range(p.population_size)]
        else:
            neg_scores = None
            scores = pos_scores

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
