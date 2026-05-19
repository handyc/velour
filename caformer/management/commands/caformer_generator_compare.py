"""Apples-to-apples comparison of LUT generators on ouroboros yield.

For each generator (random, mandelbrot, banded, sparse, ltree),
generate N candidates, score each with sr_strict + L0 fixed-point
match + class-4, and report:

  - sr_strict distribution (mean, max, p95)
  - L0 match distribution (mean, max, strict count)
  - class-4 rate
  - rate of "strong" candidates (sr ≥ 0.7 AND class-4)
  - rate of "strict L0" candidates (match == 16384)

Saves top-K LUTs from each generator into separate pool dirs so the
renderer can build comparison contact sheets.

Usage:
  manage.py caformer_generator_compare --n 200
  manage.py caformer_generator_compare --n 1000 --out .artifacts/gen_bench
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from django.core.management.base import BaseCommand


GENERATOR_NAMES = ('random', 'mandelbrot', 'banded', 'sparse', 'ltree')


class Command(BaseCommand):
    help = ('Generate N LUTs from each of several generators and '
            'compare their ouroboros-yield statistics.')

    def add_arguments(self, parser):
        parser.add_argument('--n',       type=int, default=200)
        parser.add_argument('--out',     type=str,
                              default='.artifacts/gen_bench')
        parser.add_argument('--seed',    type=int, default=42)
        parser.add_argument('--top-save', type=int, default=24,
                              help='per-generator: save top-K by sr_strict')

    def handle(self, *, n, out, seed, top_save, **opts):
        from caformer.lut_generators import (gen_banded, gen_ltree,
                                                    gen_mandelbrot, gen_random,
                                                    gen_sparse_on_black)
        from spoeqi.metachain import classify_rule, self_reproduce_score
        from caformer.primitives import hex_ca_step

        gens = {
            'random':     lambda r: gen_random(r),
            'mandelbrot': lambda r: gen_mandelbrot(r),
            'banded':     lambda r: gen_banded(r),
            'sparse':     lambda r: gen_sparse_on_black(r),
            'ltree':      lambda r: gen_ltree(r),
        }

        out_p = Path(out)
        out_p.mkdir(parents=True, exist_ok=True)

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        def l0_match(lut: np.ndarray) -> int:
            """Single-tick fixed-point match count (cheapest ouroboros
            check)."""
            grid = lut.reshape(128, 128)
            stepped = hex_ca_step(grid, lut)
            return int((stepped == grid).sum())

        log(f'=== generator compare: n={n} per generator ===\n')
        grand_t0 = time.time()
        results = {}

        for name in GENERATOR_NAMES:
            log(f'--- {name} ---')
            gen_dir = out_p / name
            gen_dir.mkdir(exist_ok=True)
            rng = np.random.RandomState(seed)
            t0 = time.time()
            sr_list   = []
            l0_list   = []
            c4_list   = []
            cls_list  = []
            top_records = []
            for i in range(n):
                lut = gens[name](rng)
                if lut.dtype != np.uint8:
                    lut = lut.astype(np.uint8)
                lut_bytes = lut.tobytes()
                sr = self_reproduce_score(lut_bytes, ticks=16)
                cls, c4 = classify_rule(lut_bytes, probe_ticks=16)
                l0 = l0_match(lut)
                sr_list.append(sr)
                l0_list.append(l0)
                c4_list.append(c4)
                cls_list.append(cls)
                # Track top-K by sr.
                top_records.append((sr, l0, cls, c4, lut_bytes))
            wall = time.time() - t0
            # Save top-K to disk.
            top_records.sort(key=lambda r: -r[0])
            for k, (sr, l0, cls, c4, lut_bytes) in enumerate(
                    top_records[:top_save]):
                fn = (gen_dir /
                      f'g{name[:3]}_rank{k:03d}_sr{sr:.3f}_l0{l0}_c4{c4:.3f}_cls{cls}.lut')
                fn.write_bytes(lut_bytes)

            # Stats.
            sr_arr = np.array(sr_list)
            l0_arr = np.array(l0_list)
            n_strict_l0  = int((l0_arr == 16384).sum())
            n_near_l0    = int((l0_arr >= 16128).sum())
            n_c4         = int(sum(1 for c in cls_list if c == 4))
            n_strong     = int(sum(1 for sr_, c_ in zip(sr_list, cls_list)
                                       if sr_ >= 0.7 and c_ == 4))
            results[name] = {
                'wall':           wall,
                'n':              n,
                'sr_mean':        float(sr_arr.mean()),
                'sr_max':         float(sr_arr.max()),
                'sr_p95':         float(np.percentile(sr_arr, 95)),
                'l0_mean':        float(l0_arr.mean()),
                'l0_max':         int(l0_arr.max()),
                'n_strict_l0':    n_strict_l0,
                'n_near_l0':      n_near_l0,
                'n_c4':           n_c4,
                'n_strong':       n_strong,
            }
            log(f'  wall {wall:6.1f}s   '
                f'sr mean={results[name]["sr_mean"]:.3f}  '
                f'max={results[name]["sr_max"]:.3f}  '
                f'p95={results[name]["sr_p95"]:.3f}')
            log(f'  L0 mean={results[name]["l0_mean"]:.0f}/16384  '
                f'max={results[name]["l0_max"]}  '
                f'strict={n_strict_l0}  near≥98.4%={n_near_l0}')
            log(f'  class-4: {n_c4}/{n} ({100*n_c4/n:.1f}%)  '
                f'strong (sr≥0.7+c4): {n_strong}/{n}\n')

        grand = time.time() - grand_t0
        log(f'=== summary ===')
        log(f'{"generator":>11} {"wall":>6} {"sr_mean":>8} {"sr_max":>7} '
            f'{"l0_max":>7} {"strict":>7} {"near":>5} {"c4_%":>6} '
            f'{"strong":>7}')
        for name in GENERATOR_NAMES:
            r = results[name]
            log(f'{name:>11} {r["wall"]:>5.1f}s {r["sr_mean"]:>8.3f} '
                f'{r["sr_max"]:>7.3f} {r["l0_max"]:>7} '
                f'{r["n_strict_l0"]:>7} {r["n_near_l0"]:>5} '
                f'{100*r["n_c4"]/r["n"]:>5.1f}% {r["n_strong"]:>7}')
        log(f'\n  total wall: {grand:.0f}s')
        log(f'  pools saved under: {out_p}')
        log(f'  → run caformer_render_lut_pool --pool {out_p}/<name> '
            f'to see contact sheets')
