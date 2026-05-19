"""Mass-scale fractal quine hunt — officemandel + hexhunter, fused.

Generates Mandelbrot regions across random walks through fractal
coordinate space, posterises each to K=4, treats as a 128×128 hex CA
LUT, classifies for class-4 + self-reproduction, saves filtered
candidates.  Designed for hours-long unattended runs producing
thousands of candidates.

Coordinate generation strategies:

  - random:     uniform-random (cx, cy, span) in a sensible window;
                fast but unstructured.
  - walks:      random walks zooming into interesting regions
                (high-escape-variance heuristic) — like loupe's agents
                without the GA persistence overhead.
  - grid:       deterministic grid sweep at fixed depths.  Useful
                for reproducible runs.

Output goes to ``--out-dir`` (default .artifacts/mandelhunt_pool/):
  * one LUT file per accepted candidate (named with rank + scores)
  * leaderboard.json updated periodically with all-time best
  * scan.log with one line per accept

Usage:
  manage.py caformer_mandelhunt --hours 4
  manage.py caformer_mandelhunt --hours 8 --workers 4 --min-sr 0.6 --min-c4 0.4
"""
from __future__ import annotations

import json
import multiprocessing
import os
import random
import signal
import sys
import time
from pathlib import Path

import numpy as np
from django.core.management.base import BaseCommand


SIDE = 128
TICKS = 16


# ── Worker function (top-level for pickling) ──────────────────────

def _worker(args):
    """One frame: generate a Mandelbrot region at (cx, cy, span),
    posterise to K=4, classify.  Returns a dict or None on error."""
    cx, cy, span = args
    try:
        # Import inside worker so each process bootstraps cleanly.
        from loupe.render import mandelbrot_buckets
        from spoeqi.metachain import (classify_rule, probe_activity,
                                          self_reproduce_score)
        buckets = mandelbrot_buckets(cx, cy, span, SIDE, SIDE,
                                          iter_cap=None)
        lut_bytes = bytes(buckets.ravel().astype(np.uint8))
        sr = self_reproduce_score(lut_bytes, ticks=TICKS)
        cls, c4 = classify_rule(lut_bytes, probe_ticks=16)
        act = probe_activity(lut_bytes, ticks=12)
        return {
            'cx': cx, 'cy': cy, 'span': span,
            'sr_strict': sr, 'class': cls,
            'c4_score': c4, 'activity': act,
            'lut_bytes': lut_bytes,
        }
    except Exception:
        return None


# ── Coordinate generators ─────────────────────────────────────────

def _gen_random(rng, n):
    """Random (cx, cy, span) tuples in the Mandelbrot bounding box.
    Sample log-uniform on span so deep zooms get reasonable weight."""
    for _ in range(n):
        cx = rng.uniform(-2.0, 0.5)
        cy = rng.uniform(-1.25, 1.25)
        # Log-uniform span between 1e-6 and 4.0 (covers the famous
        # bulbs down to deep self-similar zooms).
        log_span = rng.uniform(-6, 0.6)    # → 1e-6 .. ~4
        span = 10.0 ** log_span
        yield (cx, cy, span)


def _gen_walks(rng, n, seed_coords=None):
    """Random walks that ZOOM IN from each starting region, similar
    to loupe's agent walks.  Each walk produces ~25 frames."""
    if seed_coords is None:
        seed_coords = [(-0.5, 0.0, 3.0),                # main view
                        (-0.745, 0.113, 0.05),          # spiral
                        (-1.25, 0.0, 0.1),              # left bulb
                        (-0.16, 1.04, 0.04),            # elephant valley
                        (0.272, 0.005, 0.01)]           # seahorse valley
    produced = 0
    while produced < n:
        cx, cy, span = rng.choice(seed_coords)
        steps_in_walk = rng.randint(15, 30)
        for _ in range(steps_in_walk):
            if produced >= n:
                return
            yield (cx, cy, span)
            produced += 1
            # Step: small offset + zoom in.
            cx += rng.uniform(-0.4, 0.4) * span
            cy += rng.uniform(-0.4, 0.4) * span
            span *= rng.uniform(0.6, 0.95)


# ── Aggregator ─────────────────────────────────────────────────────

class Command(BaseCommand):
    help = ('Hunt class-4 + quine-candidate hex CA rule LUTs by '
            'mass-sampling Mandelbrot regions.  officemandel + '
            'hexhunter, fused for high-throughput discovery.')

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=float, default=2.0)
        parser.add_argument('--workers', type=int, default=4,
                              help='parallel workers (half-CPU cap is 4 '
                                     'on the dev laptop)')
        parser.add_argument('--strategy', type=str, default='walks',
                              choices=['random', 'walks', 'mixed'])
        parser.add_argument('--min-sr', type=float, default=0.4,
                              help='only save candidates with SR strict ≥')
        parser.add_argument('--min-c4', type=float, default=0.2,
                              help='only save candidates with c4 ≥')
        parser.add_argument('--require-class4', action='store_true',
                              default=True,
                              help='filter to Wolfram class 4 only')
        parser.add_argument('--batch-size', type=int, default=64,
                              help='frames submitted per pool dispatch')
        parser.add_argument('--out-dir', type=str,
                              default='.artifacts/mandelhunt_pool')
        parser.add_argument('--rng-seed', type=int,
                              default=int(time.time()))
        parser.add_argument('--report-every', type=int, default=200,
                              help='log + leaderboard update interval '
                                     '(frames)')

    def handle(self, *, hours, workers, strategy, min_sr, min_c4,
                 require_class4, batch_size, out_dir, rng_seed,
                 report_every, **opts):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        scan_log = open(out / 'scan.log', 'a')
        scan_log.write(f'\n=== mandelhunt start {time.ctime()} '
                          f'strategy={strategy} workers={workers} '
                          f'hours={hours} min_sr={min_sr} '
                          f'min_c4={min_c4} ===\n')
        scan_log.flush()

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()
            scan_log.write(msg + '\n'); scan_log.flush()

        budget = hours * 3600.0
        t_start = time.time()
        rng = random.Random(rng_seed)

        # Build coordinate generator.
        # Use a big enough source that we don't run out before the
        # time budget expires.
        per_strategy = int(budget / 0.05 * 2)  # ~20 frames/sec/worker × workers
        if strategy == 'random':
            coord_gen = _gen_random(rng, per_strategy * workers)
        elif strategy == 'walks':
            coord_gen = _gen_walks(rng, per_strategy * workers)
        else:  # mixed
            def _mixed():
                ga = _gen_random(rng, per_strategy * workers // 2)
                gb = _gen_walks(rng, per_strategy * workers // 2)
                # interleave
                while True:
                    try:
                        yield next(ga); yield next(gb)
                    except StopIteration:
                        return
            coord_gen = _mixed()

        # Process pool — each worker is one process.
        ctx = multiprocessing.get_context('spawn')
        pool = ctx.Pool(processes=workers,
                          initializer=_pool_init_one_thread)

        # Stats.
        n_scanned = 0
        n_saved   = 0
        best_combined = -1.0
        best_record   = None
        all_class4_count = 0
        last_report = 0

        # Graceful shutdown on SIGTERM/SIGINT — finish current batch.
        stop_requested = {'v': False}
        def _sig_handler(signum, frame):
            stop_requested['v'] = True
            log(f'  ! signal {signum} received — finishing current batch')
        signal.signal(signal.SIGTERM, _sig_handler)
        signal.signal(signal.SIGINT,  _sig_handler)

        # Main loop: submit batches, drain, accumulate.
        try:
            while time.time() - t_start < budget and not stop_requested['v']:
                batch = []
                for _ in range(batch_size):
                    try:
                        batch.append(next(coord_gen))
                    except StopIteration:
                        break
                if not batch:
                    log('  coordinate generator exhausted — refreshing')
                    coord_gen = _gen_walks(rng, per_strategy * workers)
                    continue
                results = pool.map(_worker, batch)
                for r in results:
                    if r is None:
                        continue
                    n_scanned += 1
                    if r['class'] == 4:
                        all_class4_count += 1
                    # Accept criteria.
                    if require_class4 and r['class'] != 4:
                        continue
                    if r['sr_strict'] < min_sr:
                        continue
                    if r['c4_score'] < min_c4:
                        continue
                    # Combined ranking metric — same as the leaderboard
                    # display in the ruleset zoo.
                    combined = r['sr_strict'] * (0.3 + r['c4_score'])
                    n_saved += 1
                    name = (f'mh_n{n_saved:06d}_'
                            f'sr{r["sr_strict"]:.3f}_'
                            f'c4{r["c4_score"]:.3f}.lut')
                    (out / name).write_bytes(r['lut_bytes'])
                    if combined > best_combined:
                        best_combined = combined
                        best_record = {k: v for k, v in r.items()
                                          if k != 'lut_bytes'}
                        best_record['saved_name'] = name
                # Periodic report.
                if n_scanned - last_report >= report_every:
                    elapsed = time.time() - t_start
                    rate = n_scanned / max(1e-3, elapsed)
                    rem = budget - elapsed
                    eta_total = int(rate * rem) + n_scanned
                    log(f'  [{elapsed/60:5.1f}m] scanned={n_scanned:7d} '
                        f'(rate {rate:5.0f}/s) '
                        f'class4={all_class4_count} '
                        f'saved={n_saved} best_combined={best_combined:.3f} '
                        f'ETA total={eta_total}')
                    # Live leaderboard dump.
                    (out / 'leaderboard.json').write_text(json.dumps({
                        'elapsed_seconds': elapsed,
                        'n_scanned':       n_scanned,
                        'n_class4':        all_class4_count,
                        'n_saved':         n_saved,
                        'best_combined':   best_combined,
                        'best_record':     best_record,
                        'budget_seconds':  budget,
                    }, indent=2))
                    last_report = n_scanned
        finally:
            pool.close()
            pool.join()

        wall = time.time() - t_start
        log('')
        log(f'=== mandelhunt done ===')
        log(f'  scanned:        {n_scanned}')
        log(f'  class-4 frames: {all_class4_count} '
            f'({100*all_class4_count/max(1,n_scanned):.1f}%)')
        log(f'  saved:          {n_saved}')
        log(f'  rate:           {n_scanned/wall:.0f} frames/sec')
        log(f'  best combined:  {best_combined:.4f}')
        if best_record:
            log(f'  best record:    {best_record}')
        log(f'  wall:           {wall:.0f}s')
        log(f'  output dir:     {out}')
        scan_log.close()


def _pool_init_one_thread():
    """Pin numpy/BLAS to one thread per worker process so N workers
    don't oversubscribe N×8 BLAS threads on a typical box."""
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    os.environ['MKL_NUM_THREADS']      = '1'
    os.environ['OMP_NUM_THREADS']      = '1'
    os.environ['NUMEXPR_NUM_THREADS']  = '1'
