"""spoeqi/metapact_tournament — multi-round tournament + lineage GA
for Metapacts.

Each round:

  1. Score every contestant via the shared metachain composite fitness
     (chain-class-4-depth + leaf next-byte logprob).
  2. Take the top K_advance seeds; throw the bottom away.
  3. Mini-GA-refine each survivor (warm-started from its own seed) so
     the next round's pool is "this survivor's best descendant", not
     just the same byte-identical seed.
  4. Add one or two fresh-mutation rivals for diversity, so the pool
     can break out of a local optimum.

The result is a *lineage* of Metapacts — round 0 winner → round 1
winner → … → round N winner — each linked to its parent via
``parent_seed``.  Each round's champion is meant to be persisted as a
new ``Metapact`` row so future tournaments can resume from it.

Design choices intentionally biased toward "produces results in a few
minutes on a modest box":

  - depth=6, chain_ticks=16  (lighter than the single-shot GA's 10/24)
  - 6 contestants × 4 rounds × refine_pop=6 × refine_gens=5
    → roughly O(6 + 4·6·5) = 126 composite-fitness evals
  - half-CPU cap on any parallelism: never more than nproc//2 workers
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import numpy as np

from .metachain import RULE_SIZE
from .metachain_ga import (
    MetaGAConfig, _composite_fitness, _make_leaf_fitness, evolve_metapact,
)


# ── Default corpus: a tiny, byte-rich probe that exercises both the
#    chain quality (visible structure across colours) and the leaf
#    quality (intelligible next-byte distribution). Chosen for speed
#    + density of common bigrams. ────────────────────────────────────
DEFAULT_CORPUS = (
    "In the beginning the Universe was created. This has made a lot "
    "of people very angry and been widely regarded as a bad move. "
    "The quick brown fox jumps over the lazy dog. "
    "Shall I compare thee to a summer's day? Thou art more lovely "
    "and more temperate: rough winds do shake the darling buds of May."
) * 4


# ── Names for tournament rounds (Greek letters keep slugs short and
#    won't collide with normal Metapact slugs). ───────────────────────
ROUND_TAGS = ['alpha', 'beta', 'gamma', 'delta', 'epsilon',
              'zeta', 'eta', 'theta', 'iota', 'kappa']


@dataclass
class TournamentConfig:
    """Tournament shape.  Defaults are picked to finish in a few
    minutes on a modest dev box and to *actually move the needle*."""
    n_contestants:     int   = 6
    rounds:            int   = 4
    survivors_per_round: int = 2       # top-K advance per round
    diversity_rivals:  int   = 1       # extra fresh-mutation contestants per round
    refine_generations: int  = 5       # mini-GA per survivor between rounds
    refine_pop:        int   = 6
    mutation_rate:     float = 0.003
    depth:             int   = 6       # CA-chain depth for the leaf builder
    chain_ticks:       int   = 16
    seed:              int   = 0xCAFE_7E
    w_chain:           float = 0.30    # composite fitness weights
    w_leaf:            float = 0.70
    corpus:            str   = ''      # leaf-probe text; uses DEFAULT_CORPUS if empty
    run_label:         str   = ''      # tag prepended to saved Metapact slugs
    save_winners:      bool  = True    # call on_save_winner() each round

    def normalized_corpus(self) -> str:
        return self.corpus or DEFAULT_CORPUS


@dataclass
class RoundReport:
    round_idx:        int
    contestants:      int                   # how many entered this round
    champion_seed:    bytes                 # this round's winning seed
    champion_fitness: float
    champion_chain_q: float
    champion_leaf_lp: float
    all_scored:       List[Tuple[float, float, float]] = field(default_factory=list)
    # all_scored[i] = (composite, chain_q, leaf_logprob) for each contestant


@dataclass
class TournamentResult:
    rounds:           List[RoundReport]
    winner_seed:      bytes
    winner_fitness:   float
    winner_chain_q:   float
    winner_leaf_lp:   float
    elapsed_seconds:  float


def _ga_cfg(cfg: TournamentConfig, *, seed_override: int) -> MetaGAConfig:
    return MetaGAConfig(
        pop_size=cfg.refine_pop,
        generations=cfg.refine_generations,
        mutation_rate=cfg.mutation_rate,
        seed=seed_override,
        depth=cfg.depth,
        chain_ticks=cfg.chain_ticks,
        w_chain=cfg.w_chain,
        w_leaf=cfg.w_leaf,
        w_sr=getattr(cfg, 'w_sr', 0.0),
        sr_ticks=getattr(cfg, 'sr_ticks', 64),
    )


def _random_seed(rng: np.random.Generator) -> bytes:
    return bytes(rng.integers(0, 4, size=RULE_SIZE, dtype=np.uint8))


def _mutate_seed(seed: bytes, rate: float, rng: np.random.Generator) -> bytes:
    arr = np.frombuffer(seed, dtype=np.uint8).copy()
    flips = rng.random(arr.size) < rate
    if flips.any():
        new = rng.integers(0, 4, size=int(flips.sum()), dtype=np.uint8)
        arr[flips] = new
    return bytes((arr & 3).astype(np.uint8))


def build_starting_pool(seed_pool: List[bytes],
                          n_contestants: int,
                          rng: np.random.Generator,
                          mutation_rate: float = 0.005) -> List[bytes]:
    """Pad ``seed_pool`` up to ``n_contestants`` by mutating its
    members; if it's empty, fill with pure random.

    First contestants are the original seeds (unmodified), followed by
    mutated variants, followed by fully random fillers. This guarantees
    the user's existing Metapacts compete *as-is* before any drift."""
    out: List[bytes] = list(seed_pool[:n_contestants])
    while len(out) < n_contestants:
        if seed_pool:
            parent = seed_pool[len(out) % len(seed_pool)]
            out.append(_mutate_seed(parent, mutation_rate, rng))
        else:
            out.append(_random_seed(rng))
    return out


def run_tournament(*, cfg: Optional[TournamentConfig] = None,
                     contestants: Optional[List[bytes]] = None,
                     on_event: Optional[Callable[[str, dict], None]] = None,
                     on_save_winner: Optional[Callable[[int, RoundReport], None]] = None,
                     ) -> TournamentResult:
    """Run the tournament and return its full report.

    Callbacks:
      ``on_event(kind, payload)``  — kind is one of:
         'tournament_begin', 'round_begin', 'score', 'round_end',
         'refine_begin', 'refine_progress', 'refine_end',
         'tournament_end'.
      ``on_save_winner(round_idx, report)`` — called after each round
         with the winner so the caller can persist it (e.g. write a
         new Metapact row with parent_seed pointing back).
    """
    import time
    cfg = cfg or TournamentConfig()
    rng = np.random.default_rng(cfg.seed)
    corpus = cfg.normalized_corpus()
    leaf_fn = _make_leaf_fitness(corpus)

    seed_pool = list(contestants or [])
    pool = build_starting_pool(seed_pool, cfg.n_contestants, rng)

    fire = on_event or (lambda *_a, **_kw: None)
    t0 = time.time()
    fire('tournament_begin', {
        'rounds': cfg.rounds,
        'n_contestants': cfg.n_contestants,
        'depth': cfg.depth, 'chain_ticks': cfg.chain_ticks,
        'corpus_bytes': len(corpus),
        'survivors_per_round': cfg.survivors_per_round,
    })

    reports: List[RoundReport] = []
    # (fitness, chain_q, leaf_lp, self_reproduce, seed_bytes)
    best_overall: Tuple[float, float, float, float, bytes] = (
        -1e9, 0.0, 0.0, 0.0, b'')

    for round_idx in range(cfg.rounds):
        fire('round_begin', {
            'round': round_idx, 'tag': ROUND_TAGS[round_idx % len(ROUND_TAGS)],
            'contestants': len(pool),
            'elapsed_ms': int((time.time() - t0) * 1000),
        })
        scored: List[Tuple[float, float, float, float, bytes]] = []
        for i, seed in enumerate(pool):
            comp, cq, lf, sr = _composite_fitness(
                seed, cfg=_ga_cfg(cfg, seed_override=cfg.seed + round_idx),
                leaf_fn=leaf_fn)
            scored.append((comp, cq, lf, sr, seed))
            fire('score', {
                'round': round_idx, 'idx': i,
                'fitness': float(comp), 'chain_q': float(cq),
                'leaf_logprob': float(lf),
                'self_reproduce': float(sr),
                'elapsed_ms': int((time.time() - t0) * 1000),
            })
        scored.sort(key=lambda r: -r[0])
        champion = scored[0]
        if champion[0] > best_overall[0]:
            best_overall = champion
        report = RoundReport(
            round_idx=round_idx, contestants=len(pool),
            champion_seed=champion[4],
            champion_fitness=champion[0],
            champion_chain_q=champion[1],
            champion_leaf_lp=champion[2],
            all_scored=[(s[0], s[1], s[2]) for s in scored],
        )
        report.champion_self_reproduce = champion[3]
        reports.append(report)
        fire('round_end', {
            'round': round_idx,
            'champion_fitness': champion[0],
            'champion_chain_q': champion[1],
            'champion_leaf_logprob': champion[2],
            'mean_fitness': float(np.mean([s[0] for s in scored])),
            'worst_fitness': scored[-1][0],
            'elapsed_ms': int((time.time() - t0) * 1000),
        })
        if cfg.save_winners and on_save_winner is not None:
            on_save_winner(round_idx, report)

        # Build the next round's pool from the survivors.
        if round_idx == cfg.rounds - 1:
            break
        survivors = [s[4] for s in scored[:cfg.survivors_per_round]]
        next_pool: List[bytes] = []
        for s_idx, surv in enumerate(survivors):
            fire('refine_begin', {
                'round': round_idx, 'survivor': s_idx,
                'elapsed_ms': int((time.time() - t0) * 1000),
            })
            ga_cfg = _ga_cfg(cfg,
                              seed_override=cfg.seed + 1009 * (round_idx + 1) + s_idx)

            def _gen_cb(gen_idx, best, mean, worst, _round=round_idx, _surv=s_idx):
                fire('refine_progress', {
                    'round': _round, 'survivor': _surv,
                    'gen': gen_idx, 'best': float(best), 'mean': float(mean),
                    'worst': float(worst),
                    'elapsed_ms': int((time.time() - t0) * 1000),
                })

            refined = evolve_metapact(
                corpus=corpus,
                template_seed=surv,
                cfg=ga_cfg,
                on_generation=_gen_cb,
            )
            next_pool.append(refined.best_seed)
            fire('refine_end', {
                'round': round_idx, 'survivor': s_idx,
                'refined_fitness': float(refined.best_fitness),
                'elapsed_ms': int((time.time() - t0) * 1000),
            })
        for _ in range(cfg.diversity_rivals):
            next_pool.append(_random_seed(rng))
        # Top up with fresh mutations of the best so far so the pool
        # is always exactly n_contestants.
        while len(next_pool) < cfg.n_contestants:
            next_pool.append(_mutate_seed(best_overall[4], 0.01, rng))
        pool = next_pool[:cfg.n_contestants]

    fire('tournament_end', {
        'rounds': len(reports),
        'winner_fitness': best_overall[0],
        'winner_chain_q': best_overall[1],
        'winner_leaf_logprob': best_overall[2],
        'winner_self_reproduce': best_overall[3],
        'elapsed_ms': int((time.time() - t0) * 1000),
    })
    return TournamentResult(
        rounds=reports,
        winner_seed=best_overall[4],
        winner_fitness=best_overall[0],
        winner_chain_q=best_overall[1],
        winner_leaf_lp=best_overall[2],
        elapsed_seconds=time.time() - t0,
    )


# ── Persistence helper used by both the management command and the
#    UI view: turn a RoundReport into a saved Metapact row, linking
#    via parent_seed to the prior round's champion. ──────────────────
def save_round_winner(report: 'RoundReport', *,
                        cfg: TournamentConfig,
                        run_label: str,
                        prior_champion_seed: Optional[bytes],
                        ) -> 'Metapact':
    """Persist one round's champion as a new Metapact.

    Slug shape: ``tournament-<run_label>-<round-tag>`` so multiple
    tournament runs don't collide.
    """
    from .models import Metapact
    tag = ROUND_TAGS[report.round_idx % len(ROUND_TAGS)]
    slug = f'tournament-{run_label}-{tag}'
    name = f'tournament/{run_label}/{tag} (round {report.round_idx})'
    # If a row with this slug already exists, append a counter.
    base_slug = slug
    n = 2
    while Metapact.objects.filter(slug=slug).exists():
        slug = f'{base_slug}-{n}'
        n += 1
    m = Metapact.objects.create(
        name=name[:80], slug=slug[:80],
        notes=(f'Tournament run {run_label!r}, round {report.round_idx} '
               f'({tag}). Composite fitness {report.champion_fitness:.4f} '
               f'(chain {report.champion_chain_q:.3f}, '
               f'leaf logprob {report.champion_leaf_lp:.3f}).'),
        seed_state=report.champion_seed,
        depth=cfg.depth, chain_ticks=cfg.chain_ticks,
        parent_seed=prior_champion_seed,
        ga_generations=cfg.refine_generations,
        ga_pop_size=cfg.refine_pop,
        final_chain_quality=report.champion_chain_q,
        final_leaf_fitness=report.champion_leaf_lp,
        leaf_probe=cfg.normalized_corpus()[:1024],
    )
    chain = m.expand()
    m.final_class4_depth = chain.depth_class4
    m.save(update_fields=['final_class4_depth'])
    return m
