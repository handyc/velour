"""caformer/loopback — search for CA rulesets where a corpus is an
*attractor* of the iteration.

The Gödelian framing: a "Shakespeare-meaningful" genome is one where
Shakespeare-shaped input → Shakespeare-shaped output, AND that output,
fed back as input, still produces Shakespeare-shaped output, and so on.
The corpus has to be meaningful at two metalevels simultaneously: as
token sequence (the rendered text) AND as valid CA input (the bytes
themselves drive the next iteration).

We don't search for specific rulesets directly — we score candidates on
how Shakespeare-shaped their multi-iteration trajectories stay, and let
the existing GA machinery do the search.

Scoring is dynamic-n longest-match: for each output position p, find
the LONGEST substring output[p:p+k] that appears anywhere in the
corpus. Sum, normalise, apply an entropy floor so degenerate
all-same-byte outputs don't game the score. No fixed n=3,5,7.

Feedback shape is sliding-window: last ``context_len`` bytes of the
output become the next iteration's prompt. Matches existing chat code.

Multi-level fitness weights iterations [1,2,3,4,5] by default — later
iterations weighted more, so the fitness directly selects for the
loop-closure / attractor property: only genomes whose outputs STAY
Shakespeare-shaped across many iterations score high.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np


# ─── Dynamic-n longest-match scorer ──────────────────────────────────

@dataclass
class CorpusNgramIndex:
    """Cached set of every k-gram in the corpus for k in [min_k, max_k].

    Memory: O(corpus_len * max_k) in the worst case; for the bundled
    Shakespeare sonnets (~3.8 KB) and max_k=16 it's well under 1 MB.
    """
    corpus: bytes
    min_k: int = 2
    max_k: int = 16
    grams: Dict[int, set] = field(default_factory=dict)

    def __post_init__(self):
        for k in range(self.min_k, self.max_k + 1):
            self.grams[k] = {
                self.corpus[i:i + k]
                for i in range(0, max(0, len(self.corpus) - k + 1))
            }


def longest_match_at(output: bytes, pos: int,
                       index: CorpusNgramIndex) -> int:
    """Return the largest k in [min_k, max_k] such that
    output[pos:pos+k] appears in the corpus. 0 if no match at all."""
    end = min(pos + index.max_k, len(output))
    best = 0
    # Walk down from max to min so the first hit IS the longest.
    for k in range(min(index.max_k, end - pos), index.min_k - 1, -1):
        if output[pos:pos + k] in index.grams[k]:
            best = k
            break
    return best


def _byte_entropy(b: bytes) -> float:
    """Shannon entropy of byte distribution in bits, 0..8."""
    if not b:
        return 0.0
    counts = np.bincount(np.frombuffer(b, dtype=np.uint8), minlength=256)
    p = counts[counts > 0] / counts.sum()
    return float(-(p * np.log2(p)).sum())


def shakespeare_score(output: bytes, index: CorpusNgramIndex,
                        *, entropy_floor: float = 0.5) -> float:
    """Dynamic-n longest-match score, 0..1, plus an entropy floor so
    degenerate low-entropy outputs (all one byte, short repeats) can't
    game the metric by matching trivial corpus substrings.

    Algorithm:
      1. For each position p in output, find longest k such that
         output[p:p+k] is a corpus k-gram (k ∈ [min_k, max_k]).
      2. Mean longest-match length, normalised by max_k.
      3. Multiplied by min(1, H(output) / (entropy_floor * H(corpus))).

    The entropy multiplier kicks in only when the output's entropy is
    below the floor fraction of the corpus's entropy. At entropy_floor=0.5,
    an output with half the corpus's entropy is fine; quarter the corpus's
    entropy gets penalised by 0.5×; all-one-byte gets ~0×.
    """
    if len(output) < index.min_k:
        return 0.0
    matches = sum(longest_match_at(output, p, index)
                   for p in range(len(output) - index.min_k + 1))
    max_possible = (len(output) - index.min_k + 1) * index.max_k
    if max_possible == 0:
        return 0.0
    raw = matches / max_possible

    h_corpus = _byte_entropy(index.corpus)
    h_out    = _byte_entropy(output)
    if h_corpus <= 0:
        entropy_mult = 1.0
    else:
        entropy_mult = min(1.0, h_out / (entropy_floor * h_corpus))
    return float(raw * entropy_mult)


# ─── Sliding-window feedback loop ────────────────────────────────────

@dataclass
class LoopTrajectory:
    """Result of iterate_genome — full per-iteration record."""
    prompt_in:    bytes
    iterations:   List[bytes]                # one entry per iteration
    scores:       List[float]                # shakespeare_score per iter
    longest_matches: List[List[int]]         # per-iter, per-pos LMS
    total_score:  float = 0.0


def iterate_genome(generate_fn: Callable[[bytes, int], bytes],
                     prompt: bytes,
                     index: CorpusNgramIndex,
                     *,
                     n_iterations: int = 5,
                     generate_len: int = 64,
                     context_len: int = 64,
                     ) -> LoopTrajectory:
    """Feed output back as input via sliding window.

    ``generate_fn(seq_bytes, n_new) -> next_n_bytes``. We pass the
    last ``context_len`` bytes of seq as input each iteration and ask
    for ``generate_len`` new bytes back. The output becomes the next
    iteration's seq.
    """
    seq = bytes(prompt)
    iters: List[bytes] = []
    scores: List[float] = []
    lms: List[List[int]] = []
    for _ in range(n_iterations):
        ctx = seq[-context_len:] if len(seq) > context_len else seq
        new_bytes = generate_fn(ctx, generate_len)
        iters.append(new_bytes)
        scores.append(shakespeare_score(new_bytes, index))
        lms.append([longest_match_at(new_bytes, p, index)
                    for p in range(max(0, len(new_bytes) - index.min_k + 1))])
        seq = new_bytes      # sliding-window: full replace at the window
    return LoopTrajectory(
        prompt_in=prompt, iterations=iters, scores=scores,
        longest_matches=lms,
        total_score=sum(scores) / max(1, len(scores)),
    )


def multi_level_fitness(generate_fn: Callable[[bytes, int], bytes],
                          corpus: bytes,
                          *,
                          prompt: Optional[bytes] = None,
                          n_iterations: int = 5,
                          generate_len: int = 48,
                          context_len: int = 64,
                          weights: Optional[Sequence[float]] = None,
                          index: Optional[CorpusNgramIndex] = None,
                          ) -> float:
    """Run the genome through ``n_iterations`` of sliding-window
    feedback from ``prompt``, score each iteration's output against
    the corpus, return weighted-mean score.

    Defaults to weights = [1,2,3,4,5] so later iterations dominate —
    rewards the loop-closure / attractor property. Pass weights=[1]*N
    for a uniform schedule, or [5,3,2,1,1] for next-token-prediction
    flavour.

    ``prompt`` defaults to the first 32 bytes of the corpus so the
    iteration starts inside Shakespeare-space.
    """
    index = index or CorpusNgramIndex(corpus)
    weights = weights or list(range(1, n_iterations + 1))
    if len(weights) != n_iterations:
        raise ValueError(
            f'weights must have length n_iterations '
            f'({n_iterations}); got {len(weights)}')
    prompt = prompt if prompt is not None else corpus[:32]
    traj = iterate_genome(generate_fn, prompt, index,
                            n_iterations=n_iterations,
                            generate_len=generate_len,
                            context_len=context_len)
    wsum = sum(weights)
    if wsum <= 0:
        return 0.0
    return float(
        sum(w * s for w, s in zip(weights, traj.scores)) / wsum)


# ─── Bridge: genome → generate_fn the loop expects ──────────────────

def make_genome_generator(genome: Dict[str, np.ndarray],
                            *,
                            n_blocks: int = 2,
                            vocab_size: int = 256,
                            base_seed: int = 0xCAF50FE,
                            temperature: float = 0.8,
                            sample_seed: int = 0xC0FFEE,
                            ) -> Callable[[bytes, int], bytes]:
    """Build a `generate_fn(seq_bytes, n_new) -> bytes` closure that
    runs the existing ``ca_generate_qkv`` forward pass with this
    genome's rule tables. Plugs straight into ``iterate_genome``."""
    from .transformer import ca_generate_qkv
    block_rule_keys = ('q', 'k', 'v', 'score', 'mix', 'merge', 'mlp')
    block_rules = [{k: genome[k] for k in block_rule_keys}
                    for _ in range(n_blocks)]

    def _gen(seq: bytes, n_new: int) -> bytes:
        prompt_ids = list(seq[:max(1, len(seq))]) or [0]
        out_ids = ca_generate_qkv(
            prompt_ids, max_new_tokens=n_new,
            n_blocks=n_blocks, vocab_size=vocab_size,
            embed_rule=genome['embed'],
            block_rules=block_rules,
            norm_rule=genome['norm'],
            output_rule=genome['output'],
            base_seed=base_seed,
            sample_seed=sample_seed,
            temperature=temperature,
        )
        # ca_generate_qkv returns prompt + new tokens; strip the prompt.
        return bytes(out_ids[len(prompt_ids):])

    return _gen


def make_loop_fitness(corpus: bytes, *,
                         n_iterations: int = 3,
                         generate_len: int = 16,
                         context_len: int = 32,
                         weights: Optional[Sequence[float]] = None,
                         n_blocks: int = 1,
                         temperature: float = 0.8,
                         sample_seed: int = 0xC0FFEE,
                         max_k: int = 8,
                         ) -> Callable:
    """Build a FitnessFn the existing ``caformer.ga._evolve`` accepts.

    Each genome → make_genome_generator → multi_level_fitness against
    the corpus. The CorpusNgramIndex is built once and reused across
    all calls. Default parameters are tuned to keep per-eval cost
    around 1.5–3 s at n_blocks=1, so a pop=4 × gen=10 GA is ~3 min.
    """
    index = CorpusNgramIndex(corpus, min_k=2, max_k=max_k)

    def _fitness(genome: Dict[str, np.ndarray]) -> float:
        gen = make_genome_generator(
            genome, n_blocks=n_blocks, temperature=temperature,
            sample_seed=sample_seed)
        return multi_level_fitness(
            gen, corpus,
            n_iterations=n_iterations,
            generate_len=generate_len,
            context_len=context_len,
            weights=weights, index=index)
    return _fitness


def evolve_loopback(corpus: bytes,
                      *,
                      template: Optional[Dict[str, np.ndarray]] = None,
                      pop_size: int = 6,
                      generations: int = 8,
                      n_iterations: int = 3,
                      generate_len: int = 16,
                      context_len: int = 32,
                      weights: Optional[Sequence[float]] = None,
                      n_blocks: int = 1,
                      seed: int = 0xCAB00B5,
                      mutation_rate: float = 0.003,
                      on_individual=None,
                      on_generation=None,
                      ):
    """Run the GA with multi-level loopback fitness on ``corpus``.

    Returns a ``caformer.ga.GAResult``. ``template`` lets the caller
    warm-start from a known-good genome (e.g. a TrainedModel loaded
    via ``trained_model_to_genome``); None starts from random rules.

    Defaults are intentionally tiny — pop=6, gen=8 = 48 evaluations,
    a few minutes on a laptop. Scale up via the ALICE bundle later.
    """
    from .ga import FULL_STACK_NAMES, GAConfig, _evolve
    from .primitives import random_rule_table, default_norm_rule

    if template is None:
        template = {n: random_rule_table(seed ^ (0x100 * (i + 1)))
                     for i, n in enumerate(FULL_STACK_NAMES)}
        template['norm'] = default_norm_rule(seed ^ 0x8000)
    fitness = make_loop_fitness(
        corpus, n_iterations=n_iterations,
        generate_len=generate_len, context_len=context_len,
        weights=weights, n_blocks=n_blocks)
    cfg = GAConfig(pop_size=pop_size, generations=generations,
                    tournament_k=3, elite_n=1,
                    mutation_rate=mutation_rate, seed=seed)
    return _evolve(template, fitness, cfg,
                    on_individual=on_individual,
                    on_generation=on_generation)


def trained_model_to_genome(slug: str) -> Dict[str, np.ndarray]:
    """Load a saved TrainedModel and return its 10 rules as a genome
    dict ready for ``make_genome_generator``."""
    from .models import TrainedModel
    obj = TrainedModel.objects.get(slug=slug)
    return {
        'q':      np.frombuffer(obj.rule_q,      dtype=np.uint8).copy(),
        'k':      np.frombuffer(obj.rule_k,      dtype=np.uint8).copy(),
        'v':      np.frombuffer(obj.rule_v,      dtype=np.uint8).copy(),
        'score':  np.frombuffer(obj.rule_score,  dtype=np.uint8).copy(),
        'mix':    np.frombuffer(obj.rule_mix,    dtype=np.uint8).copy(),
        'merge':  np.frombuffer(obj.rule_merge,  dtype=np.uint8).copy(),
        'mlp':    np.frombuffer(obj.rule_mlp,    dtype=np.uint8).copy(),
        'norm':   np.frombuffer(obj.rule_norm,   dtype=np.uint8).copy(),
        'output': np.frombuffer(obj.rule_output, dtype=np.uint8).copy(),
        'embed':  np.frombuffer(obj.rule_embed,  dtype=np.uint8).copy(),
    }
