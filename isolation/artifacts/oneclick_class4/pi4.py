#!/usr/bin/env python3
"""One-click hex-CA Class-4 hunt — standalone Python.

Zero dependencies outside the stdlib. Port of
det.pipeline.run_oneclick_pipeline + automaton.packed.PackedRuleset.

The whole pipeline — seed → mutate → GA → tournament → print top
winners — lives in this file. A complete 4-colour, 7-slot ruleset
is encoded as a packed 4,096-byte ``bytearray`` (16,384 situations ×
2 bits each, aligned to byte boundaries).

Runtime: on a Pi 4, the default parameters (25 agents × 12 gens ×
14×14 × 25-tick horizon) finish in a few seconds. On a laptop this
is <1 s per hunt.

Usage:
    python3 pi4.py                  # default run, prints top 3
    python3 pi4.py --seed 42
    python3 pi4.py --population 40 --generations 20
"""
from __future__ import annotations

import argparse
import hashlib
import random
import sys
import time


# ── Constants ─────────────────────────────────────────────────────────

K = 4                           # colours
BITS_PER_CELL = 2
NSIT = K ** 7                   # 16 384 situations per ruleset
GBYTES = (NSIT * BITS_PER_CELL + 7) // 8   # 4096 bytes


# ── Packed-ruleset primitives ─────────────────────────────────────────

def new_random(rng: random.Random) -> bytearray:
    return bytearray(rng.randrange(256) for _ in range(GBYTES))


def get_out(g: bytearray, idx: int) -> int:
    return (g[idx >> 2] >> ((idx & 3) * BITS_PER_CELL)) & 0b11


def set_out(g: bytearray, idx: int, v: int) -> None:
    b, o = idx >> 2, (idx & 3) * BITS_PER_CELL
    g[b] = (g[b] & ~(0b11 << o)) | ((v & 0b11) << o)


# Powers of K used for base-K situation index (self × K⁶ + n0 × K⁵ + … + n5).
_W6, _W5, _W4, _W3, _W2, _W1 = K**6, K**5, K**4, K**3, K**2, K**1


def sit_index(self_c: int, nbs: tuple[int, int, int, int, int, int]) -> int:
    return (self_c * _W6
            + nbs[0] * _W5 + nbs[1] * _W4 + nbs[2] * _W3
            + nbs[3] * _W2 + nbs[4] * _W1 + nbs[5])


# ── Hex grid + step ───────────────────────────────────────────────────

def seeded_grid(W: int, H: int, seed: int) -> list[list[int]]:
    r = random.Random(seed)
    return [[r.randrange(K) for _ in range(W)] for _ in range(H)]


def _neighbours(grid, r, c, W, H):
    even = (c % 2) == 0
    pos = (
        (r - 1, c),
        (r - 1 if even else r, c + 1),
        (r if even else r + 1, c + 1),
        (r + 1, c),
        (r if even else r + 1, c - 1),
        (r - 1 if even else r, c - 1),
    )
    return tuple(grid[nr][nc] if 0 <= nr < H and 0 <= nc < W else 0
                 for (nr, nc) in pos)


def step(grid, W, H, genome) -> list[list[int]]:
    out = [[0] * W for _ in range(H)]
    for r in range(H):
        for c in range(W):
            self_c = grid[r][c]
            nbs = _neighbours(grid, r, c, W, H)
            out[r][c] = get_out(genome, sit_index(self_c, nbs))
    return out


# ── Class-4 scoring ───────────────────────────────────────────────────

def score(genome: bytearray, seed: int,
          W: int = 14, H: int = 14, horizon: int = 25) -> float:
    grid = seeded_grid(W, H, seed)
    prev = grid
    changed = []
    for _ in range(horizon):
        nxt = step(grid, W, H, genome)
        changed.append(sum(1 for r in range(H) for c in range(W)
                           if prev[r][c] != nxt[r][c]) / (W * H))
        prev, grid = grid, nxt
    # Reward activity_tail in the edge-of-chaos band.
    tail_n = max(1, len(changed) // 3)
    tail_avg = sum(changed[-tail_n:]) / tail_n
    if not (0.03 <= tail_avg <= 0.30):
        return 0.0
    return 2.0 * (1.0 - abs(tail_avg - 0.12) / 0.18)


# ── GA operators ──────────────────────────────────────────────────────

def mutate(g: bytearray, rate: float, rng: random.Random) -> bytearray:
    c = bytearray(g)
    for i in range(NSIT):
        if rng.random() < rate:
            set_out(c, i, rng.randrange(K))
    return c


def crossover(a: bytearray, b: bytearray, rng: random.Random) -> bytearray:
    cut = rng.randrange(1, GBYTES)
    return bytearray(a[:cut] + b[cut:])


# ── Hunt ──────────────────────────────────────────────────────────────

def hunt(*, seed_candidates=15, population=25, generations=12,
        tournament_seeds=5, winners=3, grid_seed=42,
        rng=None) -> list[dict]:
    rng = rng or random.Random()

    # 1. Seed — best of N random genomes
    best, best_s = None, -1.0
    for _ in range(seed_candidates):
        g = new_random(rng)
        s = score(g, grid_seed)
        if s > best_s:
            best, best_s = g, s

    # 2. Populate — seed + mutants
    pool = [best] + [mutate(best, 0.02, rng) for _ in range(population - 1)]

    # 3. GA
    for gen in range(generations):
        scored = sorted(((score(g, grid_seed), g) for g in pool),
                        key=lambda p: -p[0])
        survivors = [g for _, g in scored[:max(2, population // 2)]]
        new_pool = survivors[:1]  # elitism
        while len(new_pool) < population:
            a = rng.choice(survivors)
            b = rng.choice(survivors)
            new_pool.append(mutate(crossover(a, b, rng), 0.005, rng))
        pool = new_pool
        print(f'  gen {gen+1:2d}: best={scored[0][0]:.2f} '
              f'mean={sum(s for s, _ in scored) / len(scored):.2f}',
              file=sys.stderr)

    # 4. Final scoring + tournament
    final = sorted(((score(g, grid_seed), g) for g in pool), key=lambda p: -p[0])
    top = final[:max(winners, 8)]
    seeds = [100 + i for i in range(tournament_seeds)]
    ranked = []
    for ga_score, g in top:
        per = [score(g, s) for s in seeds]
        ranked.append({
            'ga_score':     round(ga_score, 3),
            'tourney_avg':  round(sum(per) / len(per), 3),
            'per_seed':     [round(x, 3) for x in per],
            'hex':          g.hex(),
        })
    ranked.sort(key=lambda r: -r['tourney_avg'])
    return ranked[:winners]


# ── CLI ───────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description='One-click hex-CA class-4 hunt')
    ap.add_argument('--seed', type=int, default=None,
                    help='RNG seed. None = system random.')
    ap.add_argument('--population', type=int, default=25)
    ap.add_argument('--generations', type=int, default=12)
    ap.add_argument('--seed-candidates', type=int, default=15)
    ap.add_argument('--tournament-seeds', type=int, default=5)
    ap.add_argument('--winners', type=int, default=3)
    args = ap.parse_args()

    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    t0 = time.time()
    winners = hunt(
        seed_candidates=args.seed_candidates,
        population=args.population,
        generations=args.generations,
        tournament_seeds=args.tournament_seeds,
        winners=args.winners,
        rng=rng,
    )
    elapsed = time.time() - t0

    print()
    print(f'Done in {elapsed:.1f}s — top {len(winners)} winners:')
    for i, w in enumerate(winners, 1):
        sha = hashlib.sha1(bytes.fromhex(w['hex'])).hexdigest()[:10]
        print(f'  #{i}  ga={w["ga_score"]:.2f}  '
              f'tourney_avg={w["tourney_avg"]:.2f}  sha1={sha}…  '
              f'per_seed={w["per_seed"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
