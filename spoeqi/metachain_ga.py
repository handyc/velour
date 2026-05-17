"""spoeqi/metachain_ga — evolve seed_states for deep class-4 chains
that bottom out as a working CAformer.

Genome = the 16,384-byte seed_state. Mutation = byte-level flips.
Crossover = swap small windows. Fitness blends:
  (a) sum of class-4-ness across chain levels  (interestingness all the way down)
  (b) caformer next-byte log-prob on a tiny probe text  (leaf actually works)

The user picked "cheap and interesting": cheap classifier (~10 ms/rule)
and weights leaning toward leaf-quality (β=0.7) so a chain that hits
a useful model is preferred over a "pretty but pointless" all-class-4
chain.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import numpy as np

from .metachain import (
    metachain_expand, caformer_kwargs_from_chain, RULE_SIZE,
    self_reproduce_score,
)


@dataclass
class MetaGAConfig:
    pop_size:        int   = 8
    generations:     int   = 12
    tournament_k:    int   = 3
    elite_n:         int   = 1
    mutation_rate:   float = 0.002    # per-byte flip probability
    crossover_window:int   = 1024     # size of swap window
    seed:            int   = 0xCAB00B5
    depth:           int   = 10
    chain_ticks:     int   = 24
    # Fitness weights (sum doesn't need to be 1).
    w_chain:   float = 0.3            # chain_quality scaled to [0,1]
    w_leaf:    float = 0.7            # leaf logprob → sigmoid → [0,1]
    # Self-reproduction: hamming similarity of rule-applied-to-itself
    # after `sr_ticks`.  A seed_state that reproduces itself produces
    # a stable metachain — every level is the seed.  Default w_sr=0
    # keeps the original two-term fitness; set > 0 to pursue stable
    # metapacts.
    w_sr:      float = 0.0
    sr_ticks:  int   = 64


@dataclass
class MetaGAResult:
    best_seed: bytes
    best_fitness: float
    best_chain_quality: float
    best_leaf_fitness: float
    best_self_reproduce: float = 0.0
    history: List[Tuple[float, float, float]] = field(default_factory=list)
    # history[i] = (best, mean, worst) fitness at generation i.


def _make_leaf_fitness(corpus: str, *, n_windows: int = 4,
                        window_len: int = 8):
    """Build a *very cheap* next-byte log-prob fitness on `corpus`.
    Used as the leaf-quality signal inside the metachain GA — cheap
    because the GA calls it once per genome × generation."""
    from caformer.ga import make_text_fitness
    return make_text_fitness(corpus, vocab_size=256, n_blocks=1,
                                n_windows=n_windows, window_len=window_len)


def _composite_fitness(seed_state: bytes, *, cfg: MetaGAConfig,
                         leaf_fn) -> Tuple[float, float, float, float]:
    """Returns (composite, chain_quality_normalised, leaf_logprob,
    self_reproduce_score).

    The optional ``w_sr`` term turns this into a ruleset-quine fitness:
    a seed that reproduces itself produces an identical metachain at
    every level (so every level is trivially class-4 if the seed is).
    """
    chain = metachain_expand(seed_state, depth=cfg.depth,
                               chain_ticks=cfg.chain_ticks)
    chain_q = chain.chain_quality / max(1, cfg.depth)   # → [0, 1]
    # Leaf: build a caformer genome from chain levels and score it.
    # Skip when leaf weight is 0 (saves the caformer forward pass).
    if cfg.w_leaf > 0:
        kw = caformer_kwargs_from_chain(chain, n_blocks=1)
        leaf_logprob = leaf_fn({
            'q': kw['block_rules'][0]['q'], 'k': kw['block_rules'][0]['k'],
            'v': kw['block_rules'][0]['v'], 'score': kw['block_rules'][0]['score'],
            'mix': kw['block_rules'][0]['mix'], 'merge': kw['block_rules'][0]['merge'],
            'mlp': kw['block_rules'][0]['mlp'], 'norm': kw['norm_rule'],
            'output': kw['output_rule'], 'embed': kw['embed_rule'],
        })
        # logprob → sigmoid [0, 1].  Uniform baseline is -log(256) ≈
        # -5.545, so sigmoid((logprob - (-6)) / 2) → ~0.5 at uniform.
        leaf_norm = float(1.0 / (1.0 + np.exp(-(leaf_logprob + 6.0) / 2.0)))
    else:
        leaf_logprob = 0.0
        leaf_norm = 0.0
    # Self-reproduction: rule applied to its own LUT-as-image ≈ itself.
    # A seed that scores high here is a ruleset quine — its metachain
    # is stable at every level by construction.
    if cfg.w_sr > 0:
        sr = self_reproduce_score(seed_state, ticks=cfg.sr_ticks)
    else:
        sr = 0.0
    composite = (cfg.w_chain * chain_q
                   + cfg.w_leaf  * leaf_norm
                   + cfg.w_sr    * sr)
    return composite, chain_q, leaf_logprob, sr


def _seed_pop(template_seed: bytes, n: int, base: int) -> List[bytes]:
    """Make `n` jittered copies of `template_seed` — first one is the
    template itself, the rest are perturbed via per-byte XOR with an
    LCG byte stream so the GA doesn't start from a single point."""
    rng = np.random.default_rng(base)
    out = [template_seed]
    template_arr = np.frombuffer(template_seed, dtype=np.uint8)
    for i in range(1, n):
        noise = rng.integers(0, 4, size=RULE_SIZE, dtype=np.uint8)
        out.append(bytes(((template_arr ^ noise) & 3).astype(np.uint8)))
    return out


def _tournament(scored, k, rng):
    idxs = rng.integers(0, len(scored), size=k)
    return max((scored[i] for i in idxs), key=lambda sg: sg[0])[1]


def _crossover(a: bytes, b: bytes, rng) -> bytes:
    """Swap a contiguous window from b into a copy of a."""
    win = 1024
    size = len(a)
    start = int(rng.integers(0, size - win + 1))
    arr = bytearray(a)
    arr[start:start + win] = b[start:start + win]
    return bytes(arr)


def _mutate(seed_state: bytes, rate: float, rng) -> bytes:
    arr = np.frombuffer(seed_state, dtype=np.uint8).copy()
    flips = rng.random(arr.size) < rate
    if flips.any():
        new_bytes = rng.integers(0, 4, size=int(flips.sum()), dtype=np.uint8)
        arr[flips] = new_bytes
    return bytes((arr & 3).astype(np.uint8))


def evolve_metapact(*, corpus: str,
                     template_seed: Optional[bytes] = None,
                     cfg: Optional[MetaGAConfig] = None,
                     on_individual: Optional[Callable] = None,
                     on_generation: Optional[Callable] = None
                     ) -> MetaGAResult:
    """Run the metapact GA.  Returns the best seed_state + its scores.

    ``template_seed`` lets a caller bootstrap from a known-good seed
    (e.g. a previously-evolved Metapact's seed) for warm-start; None
    means start from a random base.  ``corpus`` is the probe text the
    leaf caformer is scored against.
    """
    cfg = cfg or MetaGAConfig()
    rng = np.random.default_rng(cfg.seed)
    if template_seed is None:
        template_seed = bytes(
            rng.integers(0, 4, size=RULE_SIZE, dtype=np.uint8))
    if len(template_seed) != RULE_SIZE:
        raise ValueError(
            f'template_seed must be {RULE_SIZE} bytes; got {len(template_seed)}')

    leaf_fn = _make_leaf_fitness(corpus)
    pop = _seed_pop(template_seed, cfg.pop_size, cfg.seed + 1)

    history: List[Tuple[float, float, float]] = []
    # best_ever fields: (fitness, chain_q, leaf, sr, seed_bytes)
    best_ever: Tuple[float, float, float, float, bytes] = (
        -1e9, 0.0, 0.0, 0.0, b'')

    for gen in range(cfg.generations):
        scored = []
        for i, g in enumerate(pop):
            comp, cq, lf, sr = _composite_fitness(g, cfg=cfg, leaf_fn=leaf_fn)
            scored.append((comp, g, cq, lf, sr))
            if on_individual is not None:
                on_individual(gen, i, comp, cq, lf, sr)
        scored.sort(key=lambda sg: -sg[0])
        if scored[0][0] > best_ever[0]:
            best_ever = (scored[0][0], scored[0][2], scored[0][3],
                            scored[0][4], scored[0][1])
        ss = [s[0] for s in scored]
        history.append((ss[0], float(np.mean(ss)), ss[-1]))
        if on_generation is not None:
            on_generation(gen, ss[0], float(np.mean(ss)), ss[-1])

        # Breed: elite (incl. hall-of-fame) + tournament-mutated kids.
        next_pop: List[bytes] = [best_ever[4]]
        for s in scored[:cfg.elite_n]:
            if len(next_pop) >= cfg.elite_n + 1:
                break
            next_pop.append(s[1])
        # Strip non-genome fields from `scored` for tournament.
        scored_for_t = [(s[0], s[1]) for s in scored]
        while len(next_pop) < cfg.pop_size:
            a = _tournament(scored_for_t, cfg.tournament_k, rng)
            b = _tournament(scored_for_t, cfg.tournament_k, rng)
            kid = _crossover(a, b, rng)
            kid = _mutate(kid, cfg.mutation_rate, rng)
            next_pop.append(kid)
        pop = next_pop

    return MetaGAResult(
        best_seed=best_ever[4], best_fitness=best_ever[0],
        best_chain_quality=best_ever[1], best_leaf_fitness=best_ever[2],
        best_self_reproduce=best_ever[3],
        history=history,
    )
