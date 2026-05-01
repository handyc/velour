#!/usr/bin/env python3
"""HexNN class-4 hunt — multi-CPU HPC variant (multiprocessing.Pool).

Same Hunt + Refine GA as ../pi4.py, but the per-generation scoring step
runs in parallel: each genome in the population is dispatched to a
worker process, and the main process gathers fitnesses, breeds, and
loops. The breeding step itself is cheap (a few mutations and a
crossover per genome) so it stays sequential.

Designed for ALICE — the Leiden HPC cluster prohibits automated
sbatch, so the companion ``cpu.sbatch`` template is written for human
copy-paste via Velour's Conduit handoff queue.

Usage (single node, N workers):
    ./cpu.py --workers 32 --pop 128 --gens 80 --output winner.json

When pop_size is much larger than worker count, the parallelism is
linear in workers up to pop_size. When pop_size <= workers, scoring
finishes on a single wave per generation and the wall-clock floor is
the slowest individual genome (~steps * grid_area per-gen).

For multi-node scaling beyond 64-96 cores, swap ``multiprocessing.Pool``
for ``mpi4py`` — the inner loop and ``score_one()`` payload are
unchanged. See ``../README_hpc.md`` for the rationale.

This script imports the algorithm primitives from ``../pi4.py``. Keep
that file the canonical reference.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path
from typing import List, Tuple

import numpy as np

# Make the sibling pi4.py importable regardless of CWD. ALICE jobs run
# from $SLURM_SUBMIT_DIR which we don't control.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import pi4  # noqa: E402  — sibling import after sys.path tweak


# ── Parallel scoring helper ─────────────────────────────────────────

def _payloads_for_population(pop: List[pi4.Genome], *, W: int, steps: int,
                              burn_in: int, grid_seed: int) -> list:
    """Convert the population to flat dicts that pickle cleanly across
    process boundaries. Bytes-per-task is ~N×8 — at N_LOG2=14 that's
    128 KB × pop_size. multiprocessing pickles via fork+queue on Linux,
    so the pickle round-trip is the limiting factor at high pop_size."""
    out = []
    for idx, g in enumerate(pop):
        out.append({
            'idx':        idx,
            'K':          int(g.K),
            'keys_bytes': g.keys.tobytes(),
            'outs_bytes': g.outs.tobytes(),
            'W':          int(W),
            'steps':      int(steps),
            'burn_in':    int(burn_in),
            'grid_seed':  int(grid_seed),
        })
    return out


def parallel_score(pop: List[pi4.Genome], *, W: int, steps: int,
                    burn_in: int, grid_seed: int,
                    pool: mp.Pool) -> List[Tuple[float, float]]:
    """Score each genome in ``pop``. Returns ``[(fitness, r), ...]`` in
    the same order as ``pop``."""
    payloads = _payloads_for_population(
        pop, W=W, steps=steps, burn_in=burn_in, grid_seed=grid_seed)
    results = pool.map(pi4.score_one, payloads)
    # ``score_one`` returns (idx, f, r); preserve order by sorting on idx.
    results.sort(key=lambda t: t[0])
    return [(f, r) for (_, f, r) in results]


# ── Driver ──────────────────────────────────────────────────────────

def run_ga_parallel(seed: pi4.Genome, *, mode: str, pop_size: int,
                     gens: int, steps: int, burn_in: int, rate: float,
                     W: int, hunt_seed: int, pool: mp.Pool,
                     log=print) -> Tuple[pi4.Genome, float, float]:
    rng = pi4.mulberry32(hunt_seed)
    pop: List[pi4.Genome] = [seed]
    if mode == 'refine':
        while len(pop) < pop_size:
            pop.append(pi4.mutate(seed, rate, rng))
    else:
        for _ in range(1, pop_size // 2):
            pop.append(pi4.mutate(seed, rate * 4, rng))
        while len(pop) < pop_size:
            pop.append(pi4.make_genome(
                seed.K, int(np.log2(seed.n_entries)),
                (hunt_seed + len(pop) * 1009) & 0xFFFFFFFF))

    best_g, best_f, best_r = seed, -1.0, 0.0
    for gen in range(gens):
        grid_seed = (hunt_seed + 0xA5A5 + gen) & 0xFFFFFFFF
        t0 = time.time()
        results = parallel_score(pop, W=W, steps=steps, burn_in=burn_in,
                                  grid_seed=grid_seed, pool=pool)
        dt = time.time() - t0
        scored = list(zip([r[0] for r in results],
                           [r[1] for r in results], pop))
        for f, r, ind in scored:
            if f > best_f:
                best_g, best_f, best_r = ind, f, r
        scored.sort(key=lambda x: -x[0])
        log(f'  [{mode}] gen {gen + 1}/{gens} best {best_f:.4f} '
            f'r={best_r:.3f} score-wave {dt:.2f}s')

        survivors = [s[2] for s in scored[:max(2, pop_size // 4)]]
        next_pop = [survivors[0]]
        while len(next_pop) < pop_size:
            a = survivors[int(rng() * len(survivors)) % len(survivors)]
            b = survivors[int(rng() * len(survivors)) % len(survivors)]
            next_pop.append(pi4.mutate(pi4.crossover(a, b, rng), rate, rng))
        pop = next_pop
    return best_g, best_f, best_r


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--k',       type=int, default=4)
    p.add_argument('--n-log2',  type=int, default=14,
                   help='log2(prototypes); 14 = 16384 (browser default)')
    p.add_argument('--grid',    type=int, default=16)
    p.add_argument('--steps',   type=int, default=80)
    p.add_argument('--burn-in', type=int, default=20)
    p.add_argument('--pop',     type=int, default=64,
                   help='Population size. Should be ≥ workers to keep '
                        'all cores busy.')
    p.add_argument('--gens',    type=int, default=40)
    p.add_argument('--rate',    type=float, default=0.0005)
    p.add_argument('--seed',    type=int, default=1)
    p.add_argument('--workers', type=int,
                   default=int(os.environ.get('SLURM_CPUS_PER_TASK',
                                              str(os.cpu_count() or 4))),
                   help='Number of worker processes; defaults to '
                        '$SLURM_CPUS_PER_TASK or os.cpu_count().')
    p.add_argument('--input',   help='Load seed genome from JSON.')
    p.add_argument('--output',  default='hexnn_winner.json')
    p.add_argument('--mode',    choices=('hunt-refine', 'hunt', 'refine'),
                   default='hunt-refine')
    args = p.parse_args()

    if args.input:
        seed = pi4.load_genome(args.input)
        print(f'[seed] loaded K={seed.K} N={seed.n_entries} from {args.input}',
              file=sys.stderr)
    else:
        seed = pi4.make_genome(args.k, args.n_log2, args.seed)
        print(f'[seed] fresh K={args.k} N=2^{args.n_log2}',
              file=sys.stderr)

    print(f'[hpc] workers={args.workers} pop={args.pop} '
          f'gens={args.gens} grid={args.grid}x{args.grid}',
          file=sys.stderr)

    g = seed
    fit = r = 0.0
    t_start = time.time()
    with mp.Pool(processes=args.workers) as pool:
        if args.mode in ('hunt-refine', 'hunt'):
            g, fit, r = run_ga_parallel(
                g, mode='hunt', pop_size=args.pop, gens=args.gens,
                steps=args.steps, burn_in=args.burn_in, rate=args.rate,
                W=args.grid, hunt_seed=args.seed * 31 + 17, pool=pool)
        if args.mode in ('hunt-refine', 'refine'):
            g, fit, r = run_ga_parallel(
                g, mode='refine', pop_size=args.pop, gens=args.gens,
                steps=args.steps, burn_in=args.burn_in, rate=args.rate,
                W=args.grid, hunt_seed=args.seed * 31 + 113, pool=pool)
    total_dt = time.time() - t_start

    palette = [f'#{((i * 73) & 0xFF):02x}{((i * 137) & 0xFF):02x}{((i * 211) & 0xFF):02x}'
               for i in range(g.K)]
    pi4.save_genome(g, palette, 'hpc-cpu', args.output)

    summary = {
        'fitness':     fit,
        'r':           r,
        'workers':     args.workers,
        'pop':         args.pop,
        'gens':        args.gens,
        'mode':        args.mode,
        'total_seconds': round(total_dt, 2),
        'output':      args.output,
        'host':        os.environ.get('SLURMD_NODENAME', os.uname().nodename),
        'job_id':      os.environ.get('SLURM_JOB_ID', ''),
    }
    print(json.dumps(summary))
    print(f'best fitness {fit:.4f} (r={r:.3f}) — {args.output} '
          f'· {total_dt:.1f}s wall · {args.workers} workers',
          file=sys.stderr)


if __name__ == '__main__':
    main()
