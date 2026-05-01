#!/usr/bin/env python3
"""HexNN class-4 hunt — standalone Python reference (no Django).

Mirrors the in-browser bench at /hexnn/: random nearest-neighbour CA
genome (16,384 prototypes by default), Hunt + Refine GA, edge-of-chaos
fitness on the K=4-quantized change rate. Run on a Pi 4 (or any host
with Python 3.10+ and numpy) to verify the algorithm before flashing
the same logic to the ESP32-S3 sketch in esp32_s3/.

Usage:

    ./pi4.py --k 4 --n-log2 14 --grid 16 --pop 16 --gens 60
    ./pi4.py --refine prev_winner.json     # narrow improvement
    ./pi4.py --hunt --output winner.json   # broad search

The genome JSON it writes is byte-shape-identical to the browser
bench's "Download JSON" output, so the same file round-trips into the
HexNN page for visual sanity-checking.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np


# ── PRNG: mulberry32, byte-identical to the browser bench ───────────

def mulberry32(seed: int):
    a = seed & 0xFFFFFFFF
    def gen():
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = a
        t = (t ^ (t >> 15)) * (t | 1) & 0xFFFFFFFF
        t = (t ^ (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF))) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return gen


# ── Genome representation ───────────────────────────────────────────

@dataclass
class Genome:
    K: int
    keys:    np.ndarray   # uint8[N, 7]
    outs:    np.ndarray   # uint8[N]

    @property
    def n_entries(self) -> int:
        return self.outs.shape[0]


def make_genome(K: int, n_log2: int, seed: int) -> Genome:
    rng = mulberry32(seed)
    n = 1 << n_log2
    keys = np.zeros((n, 7), dtype=np.uint8)
    outs = np.zeros(n, dtype=np.uint8)
    for i in range(n):
        for j in range(7):
            keys[i, j] = int(rng() * K) % K
        outs[i] = int(rng() * K) % K
    return Genome(K=K, keys=keys, outs=outs)


# ── Bin build + step ────────────────────────────────────────────────

def build_bins(g: Genome) -> List[Tuple[np.ndarray, np.ndarray]]:
    bins = []
    for s in range(g.K):
        mask = g.keys[:, 0] == s
        bins.append((g.keys[mask, 1:].copy(), g.outs[mask].copy()))
    return bins


def step(grid: np.ndarray, g: Genome,
         bins: List[Tuple[np.ndarray, np.ndarray]] | None = None) -> np.ndarray:
    if bins is None:
        bins = build_bins(g)
    H, W = grid.shape
    out = np.empty_like(grid)
    for y in range(H):
        for x in range(W):
            self_c = int(grid[y, x])
            even = (x & 1) == 0
            yN, yS = y - 1, y + 1
            yNE = y - 1 if even else y
            ySE = y     if even else y + 1
            ySW = y     if even else y + 1
            yNW = y - 1 if even else y
            n0 = grid[yN, x]                       if yN >= 0 else 0
            n1 = grid[yNE, x + 1]                  if 0 <= yNE < H and x + 1 < W else 0
            n2 = grid[ySE, x + 1]                  if 0 <= ySE < H and x + 1 < W else 0
            n3 = grid[yS, x]                       if yS < H else 0
            n4 = grid[ySW, x - 1]                  if 0 <= ySW < H and x - 1 >= 0 else 0
            n5 = grid[yNW, x - 1]                  if 0 <= yNW < H and x - 1 >= 0 else 0
            nbs, outs = bins[self_c]
            if nbs.shape[0] == 0:
                out[y, x] = self_c
                continue
            target = np.array([n0, n1, n2, n3, n4, n5], dtype=np.int16)
            diff = nbs.astype(np.int16) - target
            d2 = (diff * diff).sum(axis=1)
            best = int(d2.argmin())
            out[y, x] = int(outs[best])
    return out


# ── Score: edge-of-chaos parabola on K=4-quantized change rate ───────

def quantize4(arr: np.ndarray, K: int) -> np.ndarray:
    return (arr.astype(np.int32) * 4 // K).astype(np.uint8)


def score(g: Genome, W: int, steps: int, burn_in: int,
          grid_seed: int) -> Tuple[float, float]:
    """Score a genome on a fresh grid seeded from ``grid_seed``.

    No external RNG dependency — same ``grid_seed`` always produces the
    same trajectory, so this function is picklable and safe to dispatch
    across processes / nodes.
    """
    bins = build_bins(g)
    grid_rng = mulberry32(grid_seed)
    grid = np.zeros((W, W), dtype=np.uint8)
    for y in range(W):
        for x in range(W):
            grid[y, x] = int(grid_rng() * g.K) % g.K
    for _ in range(burn_in):
        grid = step(grid, g, bins)
    total = 0
    counted = 0
    for _ in range(steps - burn_in):
        nxt = step(grid, g, bins)
        ch = int((quantize4(grid, g.K) != quantize4(nxt, g.K)).sum())
        total += ch
        counted += 1
        grid = nxt
    r = total / max(1, counted * W * W)
    return 4.0 * r * (1.0 - r), r


# Picklable top-level scorer for multiprocessing / MPI workers. Takes
# a flat dict so the worker side has no Genome-class import dependency
# beyond numpy.
def score_one(payload: dict) -> Tuple[int, float, float]:
    g = Genome(
        K=int(payload['K']),
        keys=np.frombuffer(payload['keys_bytes'], dtype=np.uint8).reshape(-1, 7).copy(),
        outs=np.frombuffer(payload['outs_bytes'], dtype=np.uint8).copy(),
    )
    f, r = score(g, int(payload['W']), int(payload['steps']),
                 int(payload['burn_in']), int(payload['grid_seed']))
    return int(payload['idx']), float(f), float(r)


# ── GA: hunt + refine ────────────────────────────────────────────────

def mutate(src: Genome, rate: float, rng_unit) -> Genome:
    keys = src.keys.copy()
    outs = src.outs.copy()
    n = src.n_entries
    K = src.K
    for i in range(n):
        if rng_unit() < rate:
            outs[i] = int(rng_unit() * K) % K
    key_muts = max(1, int(round(n * 7 * rate)))
    for _ in range(key_muts):
        i = int(rng_unit() * n) % n
        j = int(rng_unit() * 7) % 7
        delta = -1 if rng_unit() < 0.5 else 1
        v = int(keys[i, j]) + delta
        keys[i, j] = max(0, min(K - 1, v))
    return Genome(K=K, keys=keys, outs=outs)


def crossover(a: Genome, b: Genome, rng_unit) -> Genome:
    n = a.n_entries
    cut = 1 + int(rng_unit() * (n - 1)) % (n - 1)
    keys = np.where(np.arange(n)[:, None] < cut, a.keys, b.keys)
    outs = np.where(np.arange(n) < cut, a.outs, b.outs)
    return Genome(K=a.K, keys=keys.astype(np.uint8), outs=outs.astype(np.uint8))


def run_ga(seed: Genome, *, mode: str, pop_size: int, gens: int,
           steps: int, burn_in: int, rate: float, W: int,
           hunt_seed: int, log=print) -> Tuple[Genome, float, float]:
    rng = mulberry32(hunt_seed)
    pop: List[Genome] = [seed]
    if mode == 'refine':
        while len(pop) < pop_size:
            pop.append(mutate(seed, rate, rng))
    else:
        for _ in range(1, pop_size // 2):
            pop.append(mutate(seed, rate * 4, rng))
        while len(pop) < pop_size:
            pop.append(make_genome(seed.K, int(np.log2(seed.n_entries)),
                                   (hunt_seed + len(pop) * 1009) & 0xFFFFFFFF))

    best_g, best_f, best_r = seed, -1.0, 0.0
    for gen in range(gens):
        scored = []
        # Each gen gets its own grid_seed so trajectories don't lock-step
        # across generations. Reproducible: same hunt_seed → same hunt.
        grid_seed = (hunt_seed + 0xA5A5 + gen) & 0xFFFFFFFF
        for i, ind in enumerate(pop):
            f, r = score(ind, W, steps, burn_in, grid_seed)
            scored.append((f, r, ind))
            if f > best_f:
                best_g, best_f, best_r = ind, f, r
        scored.sort(key=lambda x: -x[0])
        log(f'  [{mode}] gen {gen + 1}/{gens} best {best_f:.4f} r={best_r:.3f}')
        survivors = [s[2] for s in scored[:max(2, pop_size // 4)]]
        next_pop = [survivors[0]]
        while len(next_pop) < pop_size:
            a = survivors[int(rng() * len(survivors)) % len(survivors)]
            b = survivors[int(rng() * len(survivors)) % len(survivors)]
            next_pop.append(mutate(crossover(a, b, rng), rate, rng))
        pop = next_pop
    return best_g, best_f, best_r


# ── JSON I/O (matches the browser export shape) ─────────────────────

def fnv1a(buf: bytes) -> str:
    h = 0x811c9dc5
    for b in buf:
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return f'{h:08x}'


def save_genome(g: Genome, palette: List[str], palette_name: str,
                path: str) -> None:
    fp = fnv1a(g.keys.tobytes() + g.outs.tobytes())
    payload = {
        'format':       'hexnn-genome-v1',
        'K':            int(g.K),
        'n_entries':    int(g.n_entries),
        'palette':      palette,
        'palette_name': palette_name,
        'fingerprint':  fp,
        'exported_at':  time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'keys':    g.keys.tolist(),
        'outputs': g.outs.tolist(),
    }
    with open(path, 'w') as fh:
        json.dump(payload, fh)
    sys.stderr.write(f'wrote {path} ({fp})\n')


def load_genome(path: str) -> Genome:
    with open(path) as fh:
        d = json.load(fh)
    return Genome(
        K=int(d['K']),
        keys=np.array(d['keys'], dtype=np.uint8),
        outs=np.array(d['outputs'], dtype=np.uint8),
    )


# ── CLI ─────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--k',       type=int, default=4,    help='colours (2..256)')
    p.add_argument('--n-log2',  type=int, default=14,   help='log2(prototypes); 14 = 16384')
    p.add_argument('--grid',    type=int, default=16,   help='grid edge')
    p.add_argument('--steps',   type=int, default=80,   help='fitness horizon')
    p.add_argument('--burn-in', type=int, default=20)
    p.add_argument('--pop',     type=int, default=16)
    p.add_argument('--gens',    type=int, default=60)
    p.add_argument('--rate',    type=float, default=0.0005)
    p.add_argument('--seed',    type=int, default=1)
    p.add_argument('--hunt',    action='store_true', help='start with broad hunt')
    p.add_argument('--refine',  action='store_true', help='start with narrow refine')
    p.add_argument('--input',   help='load seed genome from JSON')
    p.add_argument('--output',  default='hexnn_winner.json',
                   help='where to save the winner')
    args = p.parse_args()

    if args.input:
        seed = load_genome(args.input)
        sys.stderr.write(f'loaded seed K={seed.K} N={seed.n_entries} from {args.input}\n')
    else:
        seed = make_genome(args.k, args.n_log2, args.seed)

    if not (args.hunt or args.refine):
        # Default: hunt then refine — mirrors the browser "Auto" button.
        args.hunt = True
        args.refine = True

    g = seed
    fit = r = 0.0
    if args.hunt:
        g, fit, r = run_ga(g, mode='hunt', pop_size=args.pop, gens=args.gens,
                            steps=args.steps, burn_in=args.burn_in, rate=args.rate,
                            W=args.grid, hunt_seed=args.seed * 31 + 17)
    if args.refine:
        g, fit, r = run_ga(g, mode='refine', pop_size=args.pop, gens=args.gens,
                            steps=args.steps, burn_in=args.burn_in, rate=args.rate,
                            W=args.grid, hunt_seed=args.seed * 31 + 113)

    palette = [f'#{((i * 73) & 0xFF):02x}{((i * 137) & 0xFF):02x}{((i * 211) & 0xFF):02x}'
               for i in range(g.K)]
    save_genome(g, palette, 'pi4-default', args.output)
    print(f'best fitness {fit:.4f} (r={r:.3f}) — {args.output}')


if __name__ == '__main__':
    main()
