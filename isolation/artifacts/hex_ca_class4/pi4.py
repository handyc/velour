#!/usr/bin/env python3
"""Hex-CA class-4 reference isolation — Raspberry Pi 4 target.

This single file collapses the Velour pipeline
    det (search)  →  evolution (breed)  →  automaton (render)
into the minimum feature set needed to actually *find* a Wolfram
class-4 hexagonal cellular-automaton rule and watch it run.

No external deps; pure CPython stdlib. On a Pi 4 (or any laptop) the
defaults below finish in a few seconds. This file is the yardstick:
every tinier target — ESP32 / ESP8266 / ATtiny85 / ATtiny13a / compact
C / CLI one-liner — is a compression of the code below.

Pipeline primitives
-------------------
  K = 4 colours, hex neighbourhood of 6, toroidal wrap.
  Rule table has K**7 = 16384 entries (self × 6 neighbours, each 0..3);
  each entry stores the next colour (2 bits), packed as one byte apiece
  for clarity — tinier targets pack 4 entries per byte.

Run
---
  python pi4.py               # search + evolve, print best score
  python pi4.py --render      # also animate the best ruleset
  python pi4.py --search 60 --evolve 20 --render
"""
import argparse
import random
import sys
import time

K = 4
W, H = 36, 18
GENS_PER_SCORE = 60
RULE_LEN = K ** 7

# Offset-coord neighbour deltas for axial hex on a rectangular grid.
NEI_EVEN = [(-1, -1), (-1, 0), (0, -1), (0, 1), (1, -1), (1, 0)]
NEI_ODD  = [(-1,  0), (-1, 1), (0, -1), (0, 1), (1,  0), (1, 1)]


def random_rule(seed):
    r = random.Random(seed)
    return bytes(r.randrange(K) for _ in range(RULE_LEN))


def mutate(rule, seed, rate=0.003):
    r = random.Random(seed)
    b = bytearray(rule)
    for i in range(len(b)):
        if r.random() < rate:
            b[i] = r.randrange(K)
    return bytes(b)


def step(grid, rule):
    new = [row[:] for row in grid]
    for y in range(H):
        nei = NEI_EVEN if (y & 1) == 0 else NEI_ODD
        row = grid[y]
        nrow = new[y]
        for x in range(W):
            idx = row[x]
            for (dy, dx) in nei:
                idx = idx * K + grid[(y + dy) % H][(x + dx) % W]
            nrow[x] = rule[idx]
    return new


def score(rule, seed, gens=GENS_PER_SCORE):
    """Class-4 heuristic: alive, not saturated, variance over time.

    Class 1 (freezes) and class 2 (static) → variance ~ 0.
    Class 3 (noise) → saturated, mean near K/2 forever.
    Class 4 (localised structures) → mid-density, fluctuating.
    """
    r = random.Random(seed)
    grid = [[r.randrange(K) for _ in range(W)] for _ in range(H)]
    cells = W * H
    pops = []
    for _ in range(gens):
        grid = step(grid, rule)
        pops.append(sum(1 for row in grid for c in row if c))
    avg = sum(pops) / len(pops) / cells
    if avg < 0.1 or avg > 0.85:
        return 0.0
    mean = sum(pops) / len(pops)
    var = sum((p - mean) ** 2 for p in pops) / len(pops)
    return var / (cells * cells)


def search(n, base_seed, keep=8):
    pool = []
    for i in range(n):
        rule = random_rule(base_seed + i)
        pool.append((score(rule, seed=42), rule))
    pool.sort(key=lambda t: -t[0])
    return pool[:keep]


def evolve(pool, generations, base_seed):
    for g in range(generations):
        kids = []
        for i, (_, parent) in enumerate(pool):
            child = mutate(parent, base_seed + g * 100 + i)
            kids.append((score(child, seed=42), child))
        pool = sorted(pool + kids, key=lambda t: -t[0])[:len(pool)]
    return pool


# ANSI 256-colour swatches for the 4 cell states.
PALETTE = [
    '\x1b[48;5;232m  ',   # near-black
    '\x1b[48;5;22m  ',    # deep green
    '\x1b[48;5;94m  ',    # burnt orange
    '\x1b[48;5;208m  ',   # bright amber
]
RESET = '\x1b[0m'


def render(rule, frames=300, delay=0.06, seed=42):
    r = random.Random(seed)
    grid = [[r.randrange(K) for _ in range(W)] for _ in range(H)]
    out = sys.stdout.write
    for _ in range(frames):
        out('\x1b[H\x1b[J')
        for y, row in enumerate(grid):
            if y & 1:
                out(' ')
            for c in row:
                out(PALETTE[c])
            out(RESET + '\n')
        sys.stdout.flush()
        grid = step(grid, rule)
        time.sleep(delay)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--search', type=int, default=40,
                    help='number of random rulesets to evaluate')
    ap.add_argument('--evolve', type=int, default=10,
                    help='number of GA generations')
    ap.add_argument('--render', action='store_true',
                    help='animate the winning ruleset in the terminal')
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args()

    t0 = time.time()
    pool = search(args.search, base_seed=args.seed)
    print(f'search  {args.search:>3} rules  best={pool[0][0]:.4f}  '
          f'elapsed={time.time()-t0:.1f}s', file=sys.stderr)

    t1 = time.time()
    pool = evolve(pool, args.evolve, base_seed=args.seed * 1000)
    print(f'evolve  {args.evolve:>3} gens   best={pool[0][0]:.4f}  '
          f'elapsed={time.time()-t1:.1f}s', file=sys.stderr)

    if args.render:
        render(pool[0][1])


if __name__ == '__main__':
    main()
