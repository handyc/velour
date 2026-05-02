#!/usr/bin/env python3
"""cellular.py — Python port of the s3lab Cellular sublab.

SOURCE  : static/s3lab/js/sublabs/cellular.mjs (438 LOC)
          + static/s3lab/js/engine.mjs (276 LOC)
          + isolation/artifacts/cellular/c/cellular_c.c (Phase 1)
TARGET  : Python 3.8+, stdlib only — no numpy, no Cython.
PARITY  : algorithm + scoring identical to the JS reference at the
          same seed.

Run:
    ./cellular.py                   # 200 rounds, seed from time
    ./cellular.py -r 100 -s 42 -p 25
    ./cellular.py --quiet           # no per-render output, just final stats

Phase 4 of the cellular multi-platform port. Designed to plug back
into Velour's existing Python ecosystem — taxon's metric registry,
condenser's distillers, and the slot pre-flight validator can all
import the step / fitness / mutate functions from this module.
"""
from __future__ import annotations

import argparse
import sys
import time
from array import array
from dataclasses import dataclass, field

# ── compile-time constants ─────────────────────────────────────────

K          = 4
NSIT       = 16384      # K^7
GBYTES     = 4096       # NSIT * 2 / 8
PAL_BYTES  = K
CA_W       = 16
CA_H       = 16
HORIZON    = 25

GRID_COLS  = 16
GRID_ROWS  = 16
N_CELLS    = GRID_COLS * GRID_ROWS

# hex offset deltas — match engine.mjs
DY  = (-1, -1,  0,  0,  1,  1)
DXE = ( 0,  1, -1,  1, -1,  0)
DXO = (-1,  0, -1,  1,  0,  1)

# toroidal pop neighbours (mirror engine.mjs::neighbourIdx)
NB_DC_EVEN = (-1, +1, -1,  0, -1,  0)
NB_DC_ODD  = (-1, +1,  0, +1,  0, +1)
NB_DR      = ( 0,  0, -1, -1, +1, +1)


# ── PRNG: xorshift32 (matches engine.mjs::prng exactly) ────────────

_MASK32 = 0xFFFFFFFF
_prng_state = 0x9E3779B9


def seed_prng(s: int) -> None:
    global _prng_state
    _prng_state = (s & _MASK32) or 1


def prng() -> int:
    global _prng_state
    x = _prng_state
    x ^= (x << 13) & _MASK32
    x ^= (x >> 17)
    x ^= (x << 5)  & _MASK32
    _prng_state = x & _MASK32
    return _prng_state


def prng_unit() -> float:
    return prng() / 4294967296.0


# Park-Miller LCG for grid seeding (mirror engine.mjs::lcg)
_lcg_state = 0


def _lcg_seed(s: int) -> None:
    global _lcg_state
    _lcg_state = (s & _MASK32) or 1


def _lcg_step() -> int:
    global _lcg_state
    _lcg_state = (_lcg_state * 1103515245 + 12345) & _MASK32
    return _lcg_state >> 16


# ── packed-genome accessors ────────────────────────────────────────

def g_get(g: bytearray, idx: int) -> int:
    return (g[idx >> 2] >> ((idx & 3) * 2)) & 3


def g_set(g: bytearray, idx: int, v: int) -> None:
    b = idx >> 2
    o = (idx & 3) * 2
    g[b] = (g[b] & ~(3 << o) & 0xFF) | ((v & 3) << o)


def sit_idx(self_c: int, n: list[int]) -> int:
    i = self_c
    for k in range(6):
        i = i * K + n[k]
    return i


# ── grid stepping ──────────────────────────────────────────────────

def seed_grid_at(g: bytearray, s: int) -> None:
    _lcg_seed(s)
    for i in range(CA_W * CA_H):
        g[i] = _lcg_step() & 3


def step_grid(genome: bytearray, in_g: bytearray, out_g: bytearray) -> None:
    n = [0, 0, 0, 0, 0, 0]
    for y in range(CA_H):
        dx = DXO if (y & 1) else DXE
        for x in range(CA_W):
            self_c = in_g[y * CA_W + x]
            for k in range(6):
                yy = y + DY[k]
                xx = x + dx[k]
                n[k] = (in_g[yy * CA_W + xx]
                        if 0 <= yy < CA_H and 0 <= xx < CA_W else 0)
            out_g[y * CA_W + x] = g_get(genome, sit_idx(self_c, n))


# ── fitness (mirror engine.mjs::fitness exactly) ───────────────────

_fit_a = bytearray(CA_W * CA_H)
_fit_b = bytearray(CA_W * CA_H)


def fitness(genome: bytearray, grid_seed: int) -> float:
    seed_grid_at(_fit_a, grid_seed)
    act = [0.0] * HORIZON
    for t in range(HORIZON):
        step_grid(genome, _fit_a, _fit_b)
        changed = sum(1 for i in range(CA_W * CA_H)
                      if _fit_a[i] != _fit_b[i])
        act[t] = changed / (CA_W * CA_H)
        _fit_a[:] = _fit_b
    uniform = all(_fit_a[i] == _fit_a[0] for i in range(1, CA_W * CA_H))
    counts = [0] * K
    for v in _fit_a:
        counts[v] += 1
    diversity = sum(1 for c in range(K)
                    if counts[c] * 100 >= CA_W * CA_H)
    tail_n = max(1, HORIZON // 3)
    avg = sum(act[i] for i in range(HORIZON - tail_n, HORIZON)) / tail_n
    score = 0.0
    if not uniform:
        score += 1.0
    if any(act[i] > 0.001 for i in range(HORIZON - tail_n, HORIZON)):
        score += 1.5
    reward = avg / 0.12 if avg <= 0.12 else (0.75 - avg) / 0.63
    if reward < 0:
        reward = 0
    score += 2.0 * reward
    if diversity >= 2:
        score += 0.25 * min(diversity, K)
    return score


# ── GA ops ─────────────────────────────────────────────────────────

def random_genome_into(g: bytearray) -> None:
    for i in range(GBYTES):
        g[i] = prng() & 0xFF


def invent_palette_into(pal: bytearray) -> None:
    n = 0
    while n < K:
        c = (16 + (prng() % 216)) if (prng() % 10) < 9 else (232 + (prng() % 24))
        if not any(pal[j] == c for j in range(n)):
            pal[n] = c
            n += 1


def mutate_into(dst: bytearray, src: bytearray, rate: float) -> None:
    dst[:] = src
    for i in range(NSIT):
        if prng_unit() < rate:
            g_set(dst, i, prng() & 3)


def palette_inherit_into(dst: bytearray, a: bytearray, b: bytearray) -> None:
    src = a if (prng() & 1) else b
    dst[:] = src
    if (prng() % 100) < 8:
        slot = prng() % K
        c = (16 + (prng() % 216)) if (prng() % 10) < 9 else (232 + (prng() % 24))
        dst[slot] = c


# ── topology: toroidal pointy-top hex ──────────────────────────────

def neighbour_idx(i: int, dir_: int) -> int:
    r, c = divmod(i, GRID_COLS)
    dc = NB_DC_ODD[dir_] if (r & 1) else NB_DC_EVEN[dir_]
    dr = NB_DR[dir_]
    nr = (r + dr) % GRID_ROWS
    nc = (c + dc) % GRID_COLS
    return nr * GRID_COLS + nc


# ── population state ───────────────────────────────────────────────

@dataclass
class Cell:
    genome:    bytearray = field(default_factory=lambda: bytearray(GBYTES))
    palette:   bytearray = field(default_factory=lambda: bytearray(PAL_BYTES))
    grid_a:    bytearray = field(default_factory=lambda: bytearray(CA_W * CA_H))
    grid_b:    bytearray = field(default_factory=lambda: bytearray(CA_W * CA_H))
    score:     float = 0.0
    refined_at: int  = 0


pop: list[Cell] = [Cell() for _ in range(N_CELLS)]


def bootstrap_pop(master_seed: int) -> None:
    seed_prng(master_seed)
    for i in range(N_CELLS):
        per_seed = (master_seed ^ (i * 2654435761)) & _MASK32
        seed_prng(per_seed or 1)
        random_genome_into(pop[i].genome)
        invent_palette_into(pop[i].palette)
        seed_grid_at(pop[i].grid_a, prng())
        for j in range(CA_W * CA_H):
            pop[i].grid_b[j] = 0
        pop[i].score = 0.0
        pop[i].refined_at = 0
    seed_prng(master_seed ^ 0xDEADBEEF)


# ── tick + round ───────────────────────────────────────────────────

def tick_all() -> None:
    for c in pop:
        step_grid(c.genome, c.grid_a, c.grid_b)
        c.grid_a, c.grid_b = c.grid_b, c.grid_a


_g_rounds = 0
_last_winner = -1
_last_loser  = -1


def run_round(mut_rate: float) -> None:
    global _g_rounds, _last_winner, _last_loser
    ci = prng() % N_CELLS
    dir_ = prng() % 6
    ni = neighbour_idx(ci, dir_)
    if ci == ni:
        return
    shared_seed = prng()
    fc = fitness(pop[ci].genome, shared_seed)
    fn = fitness(pop[ni].genome, shared_seed)
    pop[ci].score = fc
    pop[ni].score = fn
    winner = ci if fc >= fn else ni
    loser  = ni if winner == ci else ci
    W, L = pop[winner], pop[loser]
    mutate_into(L.genome, W.genome, mut_rate)
    palette_inherit_into(L.palette, W.palette, W.palette)
    L.score = W.score
    L.refined_at = _g_rounds
    seed_grid_at(L.grid_a, prng())
    _last_winner, _last_loser = winner, loser
    _g_rounds += 1


# ── ANSI-256 render ────────────────────────────────────────────────

def dominant_palette_idx(c: Cell) -> int:
    counts = [0] * K
    for v in c.grid_a:
        counts[v] += 1
    best = max(range(K), key=lambda i: counts[i])
    return c.palette[best]


def render() -> None:
    sys.stdout.write('\x1b[H\x1b[2J')
    for r in range(GRID_ROWS):
        if r & 1:
            sys.stdout.write(' ')
        for c in range(GRID_COLS):
            ansi = dominant_palette_idx(pop[r * GRID_COLS + c])
            sys.stdout.write(f'\x1b[48;5;{ansi}m  \x1b[0m')
        sys.stdout.write('\n')
    sys.stdout.write(f'round {_g_rounds}  pop={GRID_COLS}x{GRID_ROWS}  '
                     f'win={_last_winner} loser={_last_loser}\n')
    sys.stdout.flush()


# ── main ───────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('-r', '--rounds', type=int, default=200)
    p.add_argument('-m', '--mut-rate', type=float, default=0.005)
    p.add_argument('-s', '--seed', type=int, default=0,
                   help='0 means derive from time(NULL)')
    p.add_argument('-p', '--render-every', type=int, default=25,
                   help='render every Nth round; 0 to disable')
    p.add_argument('--quiet', action='store_true',
                   help='suppress all output except final stats')
    args = p.parse_args()

    seed = args.seed or int(time.time())
    print(f'cellular-py: seed={seed}  pop={GRID_COLS}x{GRID_ROWS}  '
          f'rounds={args.rounds}  mut={args.mut_rate}',
          file=sys.stderr)
    bootstrap_pop(seed)

    t0 = time.monotonic()
    for _ in range(args.rounds):
        tick_all()
        run_round(args.mut_rate)
        if (not args.quiet
                and args.render_every > 0
                and _g_rounds % args.render_every == 0):
            render()
    elapsed = time.monotonic() - t0

    if not args.quiet:
        render()
    print(f'cellular-py: {_g_rounds} rounds in {elapsed:.2f} s '
          f'({_g_rounds / elapsed:.1f} rounds/s)',
          file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
