"""chain_evolution.py — GA over per-component chain genes.

A *chain gene* is a list of `COMPONENTS` `(mode, mapping)` tasks; gene
position K is the task component K runs in a sequential chain (output
of K → input of K+1).  See `spoeqi.textmask.derive_chain_gene` for the
deterministic derivation; this module *evolves* alternative genes that
score higher on a user-picked weighted sum of fitness metrics.

Determinism contract:
- Same (pact, input, fitness weights, rng_seed) → same final population.
- The default rng_seed is derived from `pact.seed_matrix[8:16]` so the
  same pact reproduces the same evolution without persisting state.
"""

from __future__ import annotations

import gzip
import hashlib
import math
import random
from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence, Tuple

from .models import COMPONENTS, Pact
from . import textmask as tm


# ───────────────────────── gene representation ─────────────────────

# Gene element = (mode, mapping_name).  We pin component to its position
# in the chain and generation to a single GA-time parameter so the gene
# encodes *what each slot does*, decoupled from *what state it draws from*.
GeneElem = Tuple[str, str]
Gene = List[GeneElem]


def _registries() -> Tuple[List[str], List[str]]:
    return list(tm.MAPPING_TABLES.keys()), list(tm.TOKEN_MAPPING_TABLES.keys())


def random_gene_elem(rng: random.Random) -> GeneElem:
    char_names, token_names = _registries()
    if rng.random() < 0.5:
        return ('char',  rng.choice(char_names))
    return ('token', rng.choice(token_names))


def random_gene(rng: random.Random, length: int = COMPONENTS) -> Gene:
    return [random_gene_elem(rng) for _ in range(length)]


def mutate_gene(gene: Gene, rng: random.Random, rate: float = 0.1) -> Gene:
    """Per-position mutation: replace each elem with a fresh random one
    with probability ``rate``.  Returns a new list."""
    return [random_gene_elem(rng) if rng.random() < rate else g for g in gene]


def crossover(g1: Gene, g2: Gene, rng: random.Random) -> Gene:
    """Uniform crossover — each position independently picks from g1 or g2."""
    n = min(len(g1), len(g2))
    return [g1[i] if rng.random() < 0.5 else g2[i] for i in range(n)]


def gene_to_stages(gene: Gene, generation: int) -> List[tm.ChainStage]:
    return [tm.ChainStage(mode=m, mapping=mp, component=i, generation=generation)
            for i, (m, mp) in enumerate(gene)]


def seed_gene_from_pact(pact: Pact, generation: int = 0) -> Gene:
    """Pull the deterministic gene that `derive_chain_gene` would emit,
    so the GA can start from the pact-native gene and mutate from there."""
    stages = tm.derive_chain_gene(pact, generation=generation)
    return [(s.mode, s.mapping) for s in stages]


# ───────────────────────── fitness metrics ─────────────────────────
#
# Signature: f(input_text, output_text, stage_results) -> float in [0, 1].
# Larger = better.  Every metric returns roughly [0, 1] so they're
# comparable when weighted.

_ENGLISH_FREQ = frozenset((
    'the and for are but not you all any can had her was one our out '
    'day get has him his how man new now old see two way who its had '
    'oil sit set run eat far sea eye ago gun bad lot top arm dog box '
    'bed leg car bus bag map ear ten cup six god boy kid law sky tea '
    'cat tax bit tip end sea say way and the but for not you have '
    'this that with from they will what your when about which their '
    'would there been more some time only over also into very then '
    'these many such most these life over thinks think makes find '
    'a i o e is it of in my by on so as we be do up if go no he me '
    'us am an at to or). attention need quick brown fox jumps lazy dog '
    'rose by other smell sweet name'
).split())


def _tokens(text: str) -> List[str]:
    out: List[str] = []
    cur: List[str] = []
    for ch in text:
        if ch.isalnum():
            cur.append(ch.lower())
        else:
            if cur:
                out.append(''.join(cur))
                cur = []
    if cur:
        out.append(''.join(cur))
    return out


def m_lexical_diversity(_inp: str, out: str, _stages) -> float:
    toks = _tokens(out)
    if not toks:
        return 0.0
    return len(set(toks)) / len(toks)


def m_length_preservation(inp: str, out: str, _stages) -> float:
    """1.0 when len(out)==len(inp); 0.0 when out is empty or 5× inp."""
    n_in = max(1, len(inp))
    ratio = len(out) / n_in
    # Triangular peak at 1.0; clamps below 0.2 and above 5.0.
    if ratio <= 0.2 or ratio >= 5.0:
        return 0.0
    if ratio <= 1.0:
        return (ratio - 0.2) / 0.8
    return max(0.0, 1.0 - (ratio - 1.0) / 4.0)


def m_shannon_entropy(_inp: str, out: str, _stages) -> float:
    """Per-byte Shannon entropy normalised to [0, 1] by max log2(256)=8."""
    if not out:
        return 0.0
    counts: Dict[int, int] = {}
    b = out.encode('utf-8', errors='replace')
    for x in b:
        counts[x] = counts.get(x, 0) + 1
    n = len(b)
    H = 0.0
    for c in counts.values():
        p = c / n
        H -= p * math.log2(p)
    return min(1.0, H / 8.0)


def m_compression_resistance(_inp: str, out: str, _stages) -> float:
    """1 − (gzip(out) / out).  Higher when output resists compression
    (more 'novel'/random-looking).  Empty → 0."""
    if not out:
        return 0.0
    raw = out.encode('utf-8', errors='replace')
    if len(raw) < 8:
        return 0.0
    comp = gzip.compress(raw, compresslevel=6)
    # gzip header overhead inflates short strings; clamp to [0, 1].
    return max(0.0, min(1.0, len(comp) / max(1, len(raw))))


def m_stage_variance(_inp: str, _out: str, stages) -> float:
    """Fraction of stages that *change* the text from one step to the
    next.  Penalises chains that no-op for most of their length."""
    if not stages:
        return 0.0
    changed = 0
    for r in stages:
        if r.input_text != r.output_text:
            changed += 1
    return changed / len(stages)


def m_english_coverage(_inp: str, out: str, _stages) -> float:
    """Fraction of output tokens that appear in a small frequent-English
    word list.  Rewards chains that recover/preserve real words."""
    toks = _tokens(out)
    if not toks:
        return 0.0
    return sum(1 for t in toks if t in _ENGLISH_FREQ) / len(toks)


# ── LLM-prep oriented metrics ──────────────────────────────────────
#
# The chain's downstream consumer is an LLM.  These metrics reward the
# kinds of transformations that make a typical Transformer's life easier:
# denser content (less filler), preserved entities/numbers, stable
# vocabulary grounded in the input, sentence structure intact.

_STOPWORDS = frozenset((
    'a an the and or but if of in on at to for from with by as is are '
    'was were be been being am do does did doing have has had having '
    'this that these those it its he she we they i you me my our your '
    'their his her them us so not no yes can will would could should '
    'than then them there here when where why how which what who whom'
).split())


def m_stopword_density(_inp: str, out: str, _stages) -> float:
    """1.0 means *zero* stopwords in output (maximum content density);
    0.0 means everything is a stopword.  LLMs benefit from less filler
    when the chain is being used as a prompt preprocessor."""
    toks = _tokens(out)
    if not toks:
        return 0.0
    stop = sum(1 for t in toks if t in _STOPWORDS)
    return 1.0 - (stop / len(toks))


def _entities(text: str) -> set:
    """Tokens that look like proper nouns or numbers — uppercase-initial
    in mid-sentence, or all-numeric.  Heuristic but cheap."""
    out = set()
    for raw in text.split():
        s = raw.strip('.,;:!?"\'()[]{}')
        if not s:
            continue
        if s.isdigit():
            out.add(s)
        elif s[0].isupper() and any(c.islower() for c in s[1:]):
            out.add(s.lower())
    return out


def m_entity_preservation(inp: str, out: str, _stages) -> float:
    """Fraction of input entities that survive in the output (case-
    insensitive).  No entities in input → 1.0 (no penalty)."""
    e_in = _entities(inp)
    if not e_in:
        return 1.0
    e_out_lower = {t for t in _tokens(out)}
    return sum(1 for e in e_in if e in e_out_lower) / len(e_in)


def m_bigram_diversity(_inp: str, out: str, _stages) -> float:
    """Unique-bigram / total-bigram ratio over output tokens.  Low when
    the chain collapses to repeated word pairs ('attent need attent
    need …')."""
    toks = _tokens(out)
    if len(toks) < 2:
        return 0.0
    bigrams = list(zip(toks, toks[1:]))
    return len(set(bigrams)) / len(bigrams)


def m_input_recall(inp: str, out: str, _stages) -> float:
    """Fraction of *unique* input tokens that survive in the output.
    High recall = the chain doesn't lose the source material."""
    in_toks = set(_tokens(inp))
    if not in_toks:
        return 1.0
    out_toks = set(_tokens(out))
    return len(in_toks & out_toks) / len(in_toks)


def m_input_precision(inp: str, out: str, _stages) -> float:
    """Fraction of *unique* output tokens that came from the input.
    High precision = the chain stays grounded; doesn't hallucinate
    garbled new tokens.  Empty output → 0."""
    out_toks = set(_tokens(out))
    if not out_toks:
        return 0.0
    in_toks = set(_tokens(inp))
    return len(in_toks & out_toks) / len(out_toks)


def m_structure_preservation(inp: str, out: str, _stages) -> float:
    """Reward chains whose output has a similar sentence count to the
    input.  Counted by .!? terminators; a triangular peak at 1:1."""
    n_in  = max(1, sum(1 for ch in inp if ch in '.!?'))
    n_out = sum(1 for ch in out if ch in '.!?')
    ratio = n_out / n_in
    if ratio >= 3.0:
        return 0.0
    if ratio <= 1.0:
        return ratio
    return max(0.0, 1.0 - (ratio - 1.0) / 2.0)


def m_avg_word_length_target(_inp: str, out: str, _stages) -> float:
    """Reward outputs whose avg word length sits in [3.5, 6.5] — typical
    English range.  Filters chains that produce single-character soup
    ('· · ·') or runaway concatenations."""
    toks = _tokens(out)
    if not toks:
        return 0.0
    avg = sum(len(t) for t in toks) / len(toks)
    if avg <= 1.5 or avg >= 12.0:
        return 0.0
    if 3.5 <= avg <= 6.5:
        return 1.0
    if avg < 3.5:
        return (avg - 1.5) / 2.0
    return max(0.0, (12.0 - avg) / 5.5)


def m_punctuation_balance(_inp: str, out: str, _stages) -> float:
    """Punctuation density in [3 %, 18 %] of chars rewarded — stays in
    the natural-prose range.  Outside that band drops off linearly."""
    if not out:
        return 0.0
    n = len(out)
    p = sum(1 for ch in out if ch in '.,;:!?"\'()[]{}-')
    pct = p / n
    if pct <= 0.0 or pct >= 0.4:
        return 0.0
    if 0.03 <= pct <= 0.18:
        return 1.0
    if pct < 0.03:
        return pct / 0.03
    return max(0.0, (0.4 - pct) / (0.4 - 0.18))


def m_chain_convergence(_inp: str, _out: str, stages) -> float:
    """1.0 when the chain reaches a *stable* output by the end (last
    stage's input == output → fixed point); 0.0 when every stage
    keeps churning.  Chains that converge are predictable; chains that
    don't are 'still working'.  Both can be useful, so this is a
    *signed* metric the user might invert (weight negatively)."""
    if not stages:
        return 0.0
    tail = stages[-min(8, len(stages)):]
    stable = sum(1 for r in tail if r.input_text == r.output_text)
    return stable / len(tail)


def m_token_compression(inp: str, out: str, _stages) -> float:
    """Reward outputs that are *shorter in tokens but rich in content*
    — `output_unique_tokens / input_total_tokens`.  Sweet spot for an
    LLM prompt: distil without losing concepts."""
    in_toks = _tokens(inp)
    out_toks = _tokens(out)
    if not in_toks or not out_toks:
        return 0.0
    # Unique output tokens vs total input tokens — peaks when the chain
    # collapses repetition while retaining vocabulary breadth.
    ratio = len(set(out_toks)) / len(in_toks)
    # Triangular peak at 0.5: half the input's worth of unique content.
    if ratio <= 0.0 or ratio >= 1.5:
        return 0.0
    if ratio <= 0.5:
        return ratio / 0.5
    return max(0.0, 1.0 - (ratio - 0.5))


def m_alpha_ratio(_inp: str, out: str, _stages) -> float:
    """Fraction of output characters that are letters (incl. unicode).
    Penalises chains that produce mostly punctuation or `·` masks."""
    if not out:
        return 0.0
    return sum(1 for ch in out if ch.isalpha() or ch == ' ') / len(out)


def m_information_density(_inp: str, out: str, _stages) -> float:
    """Information *per character*: Shannon entropy × alpha ratio,
    normalised.  Distinguishes "informative" outputs (varied letters)
    from "noisy" outputs (varied punctuation/masks).  Concretely, a
    chain that converges to `··· ··· ···` scores 0 on this even though
    it has nonzero entropy."""
    return 0.5 * m_shannon_entropy(_inp, out, _stages) + 0.5 * m_alpha_ratio(_inp, out, _stages)


def m_type_token_ratio_at_30(_inp: str, out: str, _stages) -> float:
    """TTR computed over the first 30 tokens of the output — comparable
    across outputs of different length (raw TTR is biased toward
    shorter texts).  Returns 0 when output has < 5 tokens."""
    toks = _tokens(out)
    if len(toks) < 5:
        return 0.0
    window = toks[:30]
    return len(set(window)) / len(window)


# ── Reference-output match: GA toward a known target ─────────────
#
# The user provides a *gold-standard* output they'd want the chain to
# produce.  The fitness rewards genes whose output approaches it.  This
# turns the chain into a learnable text preprocessor: pick a target
# (e.g., the input with stopwords removed) and the GA finds a 64-stage
# composition that approximates the target.

def reference_match(reference: str) -> Callable:
    """Fitness factory: returns a metric callable that scores chain
    output against ``reference`` using a cheap composite of token-level
    Jaccard similarity and edit-distance proxy.  Larger = more similar.

    Composition:
      0.6 × (Jaccard over token sets)         — what's there
      0.4 × (1 − normalised char-length-diff) — how close in size
    """
    ref_tokens = set(_tokens(reference))
    ref_len = max(1, len(reference))

    def _f(_inp: str, out: str, _stages) -> float:
        out_tokens = set(_tokens(out))
        if not out_tokens and not ref_tokens:
            return 1.0
        if not out_tokens or not ref_tokens:
            return 0.0
        union = ref_tokens | out_tokens
        jacc  = len(ref_tokens & out_tokens) / len(union)
        len_diff = abs(len(out) - ref_len) / ref_len
        len_score = max(0.0, 1.0 - min(1.0, len_diff))
        return 0.6 * jacc + 0.4 * len_score
    return _f


METRIC_REGISTRY: Dict[str, Tuple[str, Callable]] = {
    # General output quality
    'lexical_diversity':     ('Unique-token ratio of output',                       m_lexical_diversity),
    'length_preservation':   ('Output length ≈ input length',                       m_length_preservation),
    'shannon_entropy':       ('Per-byte Shannon entropy (informativeness)',         m_shannon_entropy),
    'compression_resistance':('Output resists gzip (non-repetitive)',               m_compression_resistance),
    'stage_variance':        ('Fraction of stages that change the text',           m_stage_variance),
    'english_coverage':      ('Fraction of output tokens in frequent-English list', m_english_coverage),
    'alpha_ratio':           ('Output is mostly letters, not punctuation/masks',    m_alpha_ratio),

    # LLM-prep oriented
    'stopword_density':      ('Fewer stopwords = denser content for the LM',        m_stopword_density),
    'entity_preservation':   ('Input proper-nouns/numbers survive into output',     m_entity_preservation),
    'bigram_diversity':      ('Unique bigrams / total — penalise loops',           m_bigram_diversity),
    'input_recall':          ('Fraction of input vocab the output retains',         m_input_recall),
    'input_precision':       ('Fraction of output vocab grounded in input',         m_input_precision),
    'structure_preservation':('Sentence-terminator count close to input',           m_structure_preservation),
    'avg_word_length':       ('Avg word length in natural-prose range',             m_avg_word_length_target),
    'punctuation_balance':   ('Punctuation density in natural-prose range',         m_punctuation_balance),
    'chain_convergence':     ('Chain reaches a stable fixed point (set neg. to penalise)', m_chain_convergence),
    'token_compression':     ('Distil input vocabulary without total collapse',     m_token_compression),
}


def weighted_fitness(weights: Dict[str, float]) -> Callable:
    """Return a fitness callable summing the named metrics with weights.
    Unknown names raise; zero weights are dropped from the loop."""
    active = []
    for name, w in weights.items():
        if name not in METRIC_REGISTRY:
            raise ValueError(f'unknown metric {name!r}')
        if w == 0.0:
            continue
        active.append((w, METRIC_REGISTRY[name][1]))
    total_w = sum(w for w, _ in active) or 1.0

    def _f(inp: str, out: str, stages) -> float:
        if not active:
            return 0.0
        s = 0.0
        for w, fn in active:
            s += w * fn(inp, out, stages)
        return s / total_w     # normalise so the weighted sum stays in ~[0, 1]
    return _f


# ───────────────────────── GA loop ────────────────────────────────

@dataclass
class ChainEvolveGeneration:
    gen:               int
    best_score:        float
    mean_score:        float
    best_gene:         Gene
    best_output:       str


@dataclass
class ChainEvolveResult:
    final_population:  List[Gene]
    final_scores:      List[float]
    final_outputs:     List[str]
    history:           List[ChainEvolveGeneration]
    input_text:        str
    cache_hits:        int
    rng_seed:          int


def _gene_key(g: Gene) -> str:
    return '|'.join(f'{m}/{mp}' for m, mp in g)


def evolve(pact: Pact, *,
            input_text: str,
            fitness: Callable,
            n_population: int = 12,
            n_generations: int = 8,
            mutation_rate: float = 0.10,
            crossover_rate: float = 0.6,
            n_elite: int = 1,
            tournament_k: int = 3,
            generation: int = 0,
            seed_with_pact_gene: bool = True,
            rng_seed: int | None = None,
            ) -> ChainEvolveResult:
    if not input_text:
        raise ValueError('need a non-empty input_text')
    if n_population < 2:
        raise ValueError('n_population must be >= 2')
    if n_generations < 1:
        raise ValueError('n_generations must be >= 1')
    if rng_seed is None:
        rng_seed = int.from_bytes(bytes(pact.seed_matrix)[8:16], 'big')
    rng = random.Random(rng_seed)

    # Seed: optionally start from the pact-native gene, then fill with
    # random genes.  Mixing both keeps the GA from getting locked into
    # the deterministic origin.
    pop: List[Gene] = []
    if seed_with_pact_gene:
        pop.append(seed_gene_from_pact(pact, generation=generation))
    while len(pop) < n_population:
        pop.append(random_gene(rng))

    cache: Dict[str, Tuple[float, str]] = {}
    cache_hits = 0

    def _score(g: Gene) -> Tuple[float, str]:
        nonlocal cache_hits
        k = _gene_key(g)
        hit = cache.get(k)
        if hit is not None:
            cache_hits += 1
            return hit
        stages = gene_to_stages(g, generation)
        results = tm.apply_chain(pact, stages, input_text)
        out = results[-1].output_text if results else ''
        s = float(fitness(input_text, out, results))
        cache[k] = (s, out)
        return cache[k]

    history: List[ChainEvolveGeneration] = []
    for gn in range(n_generations):
        scored = [(*_score(g), g) for g in pop]
        scored.sort(key=lambda t: t[0], reverse=True)
        best_s, best_out, best_g = scored[0]
        mean_s = sum(s for s, _, _ in scored) / len(scored)
        history.append(ChainEvolveGeneration(
            gen=gn, best_score=best_s, mean_score=mean_s,
            best_gene=list(best_g), best_output=best_out))

        next_pop: List[Gene] = [list(g) for _, _, g in scored[:n_elite]]
        while len(next_pop) < n_population:
            ka = min(tournament_k, len(scored))
            kb = min(tournament_k, len(scored))
            a = max(rng.sample(scored, k=ka), key=lambda t: t[0])[2]
            b = max(rng.sample(scored, k=kb), key=lambda t: t[0])[2]
            child = crossover(a, b, rng) if rng.random() < crossover_rate else list(a)
            child = mutate_gene(child, rng, rate=mutation_rate)
            next_pop.append(child)
        pop = next_pop

    final_scored = [(*_score(g), g) for g in pop]
    final_scored.sort(key=lambda t: t[0], reverse=True)
    return ChainEvolveResult(
        final_population=[list(g) for _, _, g in final_scored],
        final_scores=[s for s, _, _ in final_scored],
        final_outputs=[o for _, o, _ in final_scored],
        history=history, input_text=input_text,
        cache_hits=cache_hits, rng_seed=rng_seed)
