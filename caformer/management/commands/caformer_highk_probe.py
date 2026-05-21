"""Probe high-K CA dynamics with Mandelbrot-derived rules.

  manage.py caformer_highk_probe
  manage.py caformer_highk_probe --side 1024 --grid 64 --ticks 20 \\
      --default hash --max-iter 4096

What it does:

  1. Render a Mandelbrot at the requested side x side resolution
     with K=2^32 colour depth.
  2. Build a HighKRule using that grid as the rule table.
  3. Initialize a small CA grid (default 64x64) with random uint32
     values seeded from a token corpus (the first ASCII characters
     of a sample prompt, padded to grid_size^2).
  4. Run N ticks, log per-tick diagnostics:
       distinct values, fraction of zero cells, Shannon entropy.
  5. Save:
       /tmp/highk_mandelbrot.png  — the rule grid as RGB
       /tmp/highk_state_initial.png  — initial CA state
       /tmp/highk_state_final.png    — final CA state
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'High-K Mandelbrot rule + CA dynamics probe.'

    def add_arguments(self, parser):
        parser.add_argument('--side', type=int, default=1024,
                              help='Mandelbrot rule-grid side (default 1024)')
        parser.add_argument('--grid', type=int, default=64,
                              help='CA state grid side (default 64)')
        parser.add_argument('--ticks', type=int, default=20)
        parser.add_argument('--max-iter', type=int, default=2048,
                              help='Mandelbrot iteration cap')
        parser.add_argument('--default', type=str, default='identity',
                              choices=['identity', 'zero', 'hash'])
        parser.add_argument('--seed-prompt', type=str,
                              default='to be or not to be that is the question')
        parser.add_argument('--out-dir', type=str, default='/tmp')

    def handle(self, *, side, grid, ticks, max_iter, default,
                 seed_prompt, out_dir, **opts):
        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        from caformer.highk.mandelbrot import render, render_to_png_bytes
        from caformer.highk.rules import HighKRule

        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)

        log(f'=== high-K Mandelbrot CA probe ===')
        log(f'  rule-grid: {side}x{side}  (K=2^32 colour, max_iter={max_iter})')
        log(f'  CA grid:   {grid}x{grid}')
        log(f'  ticks:     {ticks}')
        log(f'  default:   {default}')

        # 1. Render the Mandelbrot rule grid.
        log('')
        log(f'-- rendering Mandelbrot rule grid --')
        t0 = time.time()
        pix = render(side=side, max_iter=max_iter)
        log(f'  rendered in {time.time()-t0:.2f}s')
        unique_colours = int(np.unique(pix).size)
        n_in_set = int((pix == 0).sum())
        log(f'  {unique_colours:,} unique 32-bit colour values')
        log(f'  {n_in_set:,} pixels inside set (sentinel 0) = '
            f'{100*n_in_set/pix.size:.1f}%')
        (out / 'highk_mandelbrot.png').write_bytes(render_to_png_bytes(pix))
        log(f'  saved {out}/highk_mandelbrot.png')

        # 2. Wrap as a high-K rule.
        rule = HighKRule(pix, default=default)

        # 3. Seed the CA grid.
        rng = np.random.RandomState(0xCA4CA4)
        # Seed each cell with a low-K=256 (ASCII) value from the
        # seed prompt, then pack into the lowest byte of a uint32
        # plus some entropy in the upper bytes from the rng.
        ascii_bytes = (seed_prompt.encode('utf-8')
                       * ((grid * grid // len(seed_prompt)) + 1))
        ascii_bytes = ascii_bytes[: grid * grid]
        lo = np.frombuffer(ascii_bytes, dtype=np.uint8).astype(np.uint32)
        hi = rng.randint(0, 1 << 24, size=grid * grid, dtype=np.uint32)
        initial_flat = lo | (hi << 8)
        state = initial_flat.reshape(grid, grid).astype(np.uint32)
        (out / 'highk_state_initial.png').write_bytes(
            render_to_png_bytes(np.kron(state, np.ones((8, 8), dtype=np.uint32))))
        log(f'  saved {out}/highk_state_initial.png')

        # 4. Run + log.
        log('')
        log(f'-- stepping CA ({ticks} ticks) --')
        log(f'{"tick":>4}  {"distinct":>10}  {"frac_zero":>10}  '
            f'{"entropy_bits":>14}  {"max_value":>12}')
        s0 = HighKRule.stats(state)
        log(f'{"init":>4}  {s0["n_unique"]:>10,}  '
            f'{s0["frac_zero"]:>10.3f}  '
            f'{s0["entropy_bits"]:>14.4f}  {s0["max_value"]:>12,}')
        t0 = time.time()
        history = [s0]
        for t in range(1, ticks + 1):
            state = rule.step(state)
            s = HighKRule.stats(state)
            history.append(s)
            log(f'{t:>4}  {s["n_unique"]:>10,}  '
                f'{s["frac_zero"]:>10.3f}  '
                f'{s["entropy_bits"]:>14.4f}  {s["max_value"]:>12,}')
        log(f'  {ticks} ticks in {time.time()-t0:.2f}s')

        # 5. Save final state image.
        (out / 'highk_state_final.png').write_bytes(
            render_to_png_bytes(np.kron(state, np.ones((8, 8), dtype=np.uint32))))
        log(f'  saved {out}/highk_state_final.png')

        # 6. Verdict.
        log('')
        log('-- verdict --')
        h_init  = history[0]['entropy_bits']
        h_final = history[-1]['entropy_bits']
        u_init  = history[0]['n_unique']
        u_final = history[-1]['n_unique']
        z_final = history[-1]['frac_zero']
        if u_final == 1:
            log('  ✗ collapsed to a single value (rule too convergent)')
        elif z_final > 0.95:
            log('  ✗ collapsed to mostly-zero (default sentinel wins)')
        elif u_final >= u_init * 0.95 and h_final > h_init - 0.2:
            log('  ~ noise-like (entropy preserved, no structure visible)')
        elif u_final < u_init * 0.5 and h_final > h_init * 0.5:
            log('  ✓ STRUCTURED: cells consolidating into fewer values '
                'while keeping entropy — sign of attractor + diversity')
        elif u_final < u_init * 0.1:
            log('  ~ aggressive consolidation — may be useful, may be dead')
        else:
            log('  ~ in between — eyeball the PNGs to decide')

        # Token candidate count: how many distinct values appeared
        # across the full run?  (= the "active vocabulary" of this rule.)
        all_values = set()
        for s in history:
            all_values  # only summary kept, not full sets
        # Approximate: use final unique values as a proxy.
        log(f'  active vocabulary (final unique values): {u_final:,}')
