"""Genetic algorithm over textmask head ensembles.

A *head* is a tiny data record naming a single textmask transform:
``(mode, table_name, component, generation)``.  An *ensemble* is K
heads applied together to one input string; the per-head outputs
stack and concatenate into the ensemble's output.  The GA evolves
a population of M ensembles by tournament selection + crossover +
per-head mutation.

Fitness is pluggable.  The default (``lexical_diversity``) is a
cheap heuristic so the substrate is exercisable without an LLM in
the loop: it rewards ensembles whose stacked outputs cover many
distinct tokens *and* whose per-head outputs differ from one another
(so heads aren't redundant).  Swap in an LLM-perplexity callable
when you're ready to spend tokens — the cache below already keys on
``(heads, input-hash)`` so re-evaluations are free.

Determinism: ``rng_seed`` defaults to ``int.from_bytes(pact.seed_matrix[8:16])``
so the same pact gives the same trajectory.  Bytes 8..16 keep us
out of the keystream's primary expansion window.

Skipped on purpose: the *attention* mode produces a float matrix,
not text; it can't ensemble with char/token outputs without a
matrix-aware fitness, so we limit the GA's mode pool to char+token.
"""

from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Callable, Dict, List, Sequence, Tuple
import hashlib
import random

from .models import Pact, COMPONENTS
from . import textmask as tm


_MODES_WITH_TABLES: Dict[str, Dict] = {
    'char':  tm.MAPPING_TABLES,
    'token': tm.TOKEN_MAPPING_TABLES,
}


@dataclass(frozen=True)
class Head:
    mode:        str   # 'char' | 'token'
    table_name:  str
    component:   int
    generation:  int

    def as_tuple(self) -> Tuple[str, str, int, int]:
        return (self.mode, self.table_name, self.component, self.generation)


def _modes(modes: Sequence[str] | None) -> List[str]:
    if not modes:
        return ['char', 'token']
    out = [m for m in modes if m in _MODES_WITH_TABLES]
    if not out:
        raise ValueError(f'no usable modes in {modes!r}')
    return list(out)


def random_head(rng: random.Random, *,
                gen_window: Tuple[int, int] = (0, 16),
                modes: Sequence[str] | None = None) -> Head:
    ms = _modes(modes)
    mode = rng.choice(ms)
    table_name = rng.choice(list(_MODES_WITH_TABLES[mode].keys()))
    component = rng.randrange(COMPONENTS)
    gen = rng.randint(gen_window[0], gen_window[1])
    return Head(mode=mode, table_name=table_name,
                component=component, generation=gen)


def mutate_head(h: Head, rng: random.Random, *,
                gen_window: Tuple[int, int] = (0, 16),
                modes: Sequence[str] | None = None) -> Head:
    """Resample exactly one field of the head.  When the picked field
    has only one valid value (e.g. modes is locked to one), the head
    is returned unchanged."""
    ms = _modes(modes)
    field = rng.choice(('mode', 'table_name', 'component', 'generation'))
    if field == 'mode':
        opts = [m for m in ms if m != h.mode]
        if not opts:
            return h
        new_mode = rng.choice(opts)
        new_table = rng.choice(list(_MODES_WITH_TABLES[new_mode].keys()))
        return replace(h, mode=new_mode, table_name=new_table)
    if field == 'table_name':
        opts = [t for t in _MODES_WITH_TABLES[h.mode].keys()
                if t != h.table_name]
        if not opts:
            return h
        return replace(h, table_name=rng.choice(opts))
    if field == 'component':
        return replace(h, component=rng.randrange(COMPONENTS))
    # generation
    return replace(h, generation=rng.randint(gen_window[0], gen_window[1]))


# ────────────────────── Application ────────────────────────────────

@dataclass
class HeadResult:
    head:        Head
    output_text: str


@dataclass
class EnsembleResult:
    heads:    List[Head]
    per_head: List[HeadResult]
    concat:   str         # outputs joined by SEP
    stack:    List[str]   # raw per-head outputs


SEP = ' | '


def apply_head(pact: Pact, head: Head, text: str) -> HeadResult:
    if head.mode == 'char':
        r = tm.apply(pact, text=text, component=head.component,
                     generation=head.generation, mapping=head.table_name)
    elif head.mode == 'token':
        r = tm.apply_tokens(pact, text=text, component=head.component,
                            generation=head.generation, mapping=head.table_name)
    else:
        raise ValueError(f'unsupported mode for ensemble: {head.mode!r}')
    return HeadResult(head=head, output_text=r.output_text)


def apply_ensemble(pact: Pact, heads: Sequence[Head],
                   text: str) -> EnsembleResult:
    per_head = [apply_head(pact, h, text) for h in heads]
    stack = [p.output_text for p in per_head]
    return EnsembleResult(heads=list(heads), per_head=per_head,
                          concat=SEP.join(stack), stack=stack)


# ───────────────────────── Fitness ─────────────────────────────────
#
# Signature: callable(pact, results: List[EnsembleResult],
#                     inputs: List[str]) -> float
# Larger = better.  Must be pure / deterministic so the score cache
# is correct.

def lexical_diversity(_pact, results, _inputs) -> float:
    """Mean of (unique-token ratio, per-head dissimilarity), averaged
    over inputs.  Rewards ensembles whose heads each contribute new
    vocabulary."""
    if not results:
        return 0.0
    total = 0.0
    for r in results:
        toks = ' '.join(r.stack).split()
        if not toks:
            continue
        unique_ratio = len(set(toks)) / len(toks)
        sets = [set(s.split()) for s in r.stack]
        if len(sets) > 1:
            jaccs: List[float] = []
            for i in range(len(sets)):
                for j in range(i + 1, len(sets)):
                    u = sets[i] | sets[j]
                    jaccs.append((len(sets[i] & sets[j]) / len(u))
                                  if u else 1.0)
            mean_jacc = sum(jaccs) / len(jaccs) if jaccs else 0.0
            dissim = 1.0 - mean_jacc
        else:
            dissim = 0.0
        total += 0.5 * unique_ratio + 0.5 * dissim
    return total / len(results)


def length_target(target_chars: int) -> Callable:
    """Negative |concat-length − target|, normalised by target.  Useful
    smoke-test fitness — easy to hill-climb so you can verify the GA
    plumbing converges before swapping in the real scorer."""
    def _f(_pact, results, _inputs) -> float:
        if not results:
            return 0.0
        s = 0.0
        for r in results:
            s -= abs(len(r.concat) - target_chars) / max(1, target_chars)
        return s / len(results)
    return _f


FITNESS_REGISTRY: Dict[str, Callable] = {
    'lexical_diversity':  lexical_diversity,
    'length_120':         length_target(120),
    'length_400':         length_target(400),
}


# ──────────────────────────── GA ───────────────────────────────────

def _ensemble_key(heads: Sequence[Head], input_hash: str) -> str:
    payload = '|'.join(','.join(map(str, h.as_tuple())) for h in heads)
    return f'{input_hash}::{payload}'


def _input_hash(inputs: Sequence[str]) -> str:
    h = hashlib.sha256()
    for s in inputs:
        h.update(s.encode('utf-8'))
        h.update(b'\0')
    return h.hexdigest()[:16]


@dataclass
class GAGeneration:
    gen:                 int
    best_score:          float
    mean_score:          float
    best_heads:          List[Head]
    best_sample_concat:  str    # ensemble output on inputs[0]


@dataclass
class GAResult:
    final_population:  List[List[Head]]
    final_scores:      List[float]
    final_sample_concats: List[str]   # parallel to final_population, on inputs[0]
    history:           List[GAGeneration]
    inputs:            List[str]
    cache_hits:        int
    cache_misses:      int
    rng_seed:          int


def evolve(pact: Pact, *,
           inputs: Sequence[str],
           ensemble_size: int = 4,
           n_population: int = 8,
           n_generations: int = 8,
           mutation_rate: float = 0.25,
           crossover_rate: float = 0.5,
           n_elite: int = 1,
           tournament_k: int = 3,
           gen_window: Tuple[int, int] = (0, 16),
           fitness: Callable = lexical_diversity,
           rng_seed: int | None = None,
           ) -> GAResult:
    if not inputs:
        raise ValueError('need at least one input string')
    if ensemble_size < 1:
        raise ValueError('ensemble_size must be >= 1')
    if n_population < 2:
        raise ValueError('n_population must be >= 2')
    if n_generations < 1:
        raise ValueError('n_generations must be >= 1')
    if not (0 <= mutation_rate <= 1):
        raise ValueError('mutation_rate must be in [0,1]')
    if not (0 <= crossover_rate <= 1):
        raise ValueError('crossover_rate must be in [0,1]')
    if n_elite < 0 or n_elite > n_population:
        raise ValueError('n_elite must be in [0, n_population]')
    if gen_window[0] < 0 or gen_window[1] < gen_window[0]:
        raise ValueError('gen_window must be (lo>=0, hi>=lo)')

    if rng_seed is None:
        rng_seed = int.from_bytes(pact.seed_matrix[8:16], 'big')
    rng = random.Random(rng_seed)

    pop: List[List[Head]] = [
        [random_head(rng, gen_window=gen_window) for _ in range(ensemble_size)]
        for _ in range(n_population)]

    in_hash = _input_hash(inputs)
    cache: Dict[str, Tuple[float, List[EnsembleResult]]] = {}
    cache_hits = 0
    cache_misses = 0

    def _score(heads: List[Head]) -> Tuple[float, List[EnsembleResult]]:
        nonlocal cache_hits, cache_misses
        k = _ensemble_key(heads, in_hash)
        hit = cache.get(k)
        if hit is not None:
            cache_hits += 1
            return hit
        results = [apply_ensemble(pact, heads, t) for t in inputs]
        s = float(fitness(pact, results, list(inputs)))
        cache[k] = (s, results)
        cache_misses += 1
        return cache[k]

    history: List[GAGeneration] = []
    for gen in range(n_generations):
        scored = [(*_score(p), p) for p in pop]
        scored.sort(key=lambda t: t[0], reverse=True)
        best_s, best_results, best_heads = scored[0]
        mean_s = sum(s for s, _, _ in scored) / len(scored)
        history.append(GAGeneration(
            gen=gen, best_score=best_s, mean_score=mean_s,
            best_heads=list(best_heads),
            best_sample_concat=best_results[0].concat))

        next_pop: List[List[Head]] = [list(p) for _, _, p in scored[:n_elite]]
        while len(next_pop) < n_population:
            ka = min(tournament_k, len(scored))
            kb = min(tournament_k, len(scored))
            a = max(rng.sample(scored, k=ka), key=lambda t: t[0])[2]
            b = max(rng.sample(scored, k=kb), key=lambda t: t[0])[2]
            if rng.random() < crossover_rate:
                child = [rng.choice([a[i], b[i]]) for i in range(ensemble_size)]
            else:
                child = list(a)
            child = [mutate_head(h, rng, gen_window=gen_window)
                      if rng.random() < mutation_rate else h
                      for h in child]
            next_pop.append(child)
        pop = next_pop

    final_scored = [(*_score(p), p) for p in pop]
    final_scored.sort(key=lambda t: t[0], reverse=True)
    return GAResult(
        final_population=[list(p) for _, _, p in final_scored],
        final_scores=[s for s, _, _ in final_scored],
        final_sample_concats=[r[0].concat for _, r, _ in final_scored],
        history=history, inputs=list(inputs),
        cache_hits=cache_hits, cache_misses=cache_misses,
        rng_seed=rng_seed)
