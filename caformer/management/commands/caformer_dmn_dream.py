"""Continuously generate class-4 LUTs as the caformer 'dreams'.

The DMN (default-mode network) framing: when the system isn't
serving chat, it dreams up fresh class-4 CA rules by sampling
fractal regions and filtering for class-4 dynamics.  Dreams
accumulate in .artifacts/dmn_dreams/ as .lut + .png pairs that
the /caformer/dreams/ page lists.

Use as a long-running process:
  manage.py caformer_dmn_dream             # forever, 1 dream/3s
  manage.py caformer_dmn_dream --once      # single iteration
  manage.py caformer_dmn_dream --interval-sec 1.0 --max-pool 500

Backgroundable via nohup:
  nohup venv/bin/python manage.py caformer_dmn_dream \\
      > /tmp/dmn_dream.log 2>&1 &
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from django.core.management.base import BaseCommand


# Class-4 activity band: cells changed per tick should land between
# these fractions of total cells.  Below = class 1/2 (dies/fixed),
# above = class 3 (chaotic).  Loosened 2026-05-21 from [0.02, 0.55]
# to catch more genuine class-4 rules the tight band was rejecting.
ACTIVITY_MIN = 0.01
ACTIVITY_MAX = 0.65
PROBE_SIDE   = 64        # bumped from 32 — gives rules room to develop
PROBE_TICKS  = 16        # bumped from 12 — slightly longer post-transient
PROBE_TRANSIENT = 4
PROBE_SEEDS  = (0xC1A554, 0xDEADBEEF, 0xCAFEBABE)   # quorum 2/3


def _probe_one(rule_table: np.ndarray, side: int, ticks: int,
                    transient: int, seed: int) -> float:
    """Run rule_table on a random (side, side) state seeded from
    `seed`; return post-transient mean activity (fraction of cells
    changed per tick)."""
    from caformer.primitives import hex_ca_step
    rng = np.random.RandomState(seed)
    state = rng.randint(0, 4, size=(side, side)).astype(np.uint8)
    for _ in range(transient):
        state = hex_ca_step(state, rule_table)
    measured = max(1, ticks - transient)
    n_cells = side * side
    total = 0.0
    for _ in range(measured):
        new = hex_ca_step(state, rule_table)
        total += int((new != state).sum()) / n_cells
        state = new
    return total / measured


def is_class4(rule_table: np.ndarray, *,
                  side: int = PROBE_SIDE, ticks: int = PROBE_TICKS,
                  transient: int = PROBE_TRANSIENT,
                  seeds: tuple = PROBE_SEEDS,
                  quorum: int = 2) -> tuple:
    """Class-4 probe with multi-seed quorum.  Runs the rule on
    `len(seeds)` independent random initial states; accepts iff at
    least `quorum` of them land their mean activity in the band.
    Returns (is_class4: bool, mean_activity_across_seeds: float).

    Robust to a single unlucky basin: a real class-4 rule that has
    one quiet attractor among its many basins still passes."""
    activities = [_probe_one(rule_table, side, ticks, transient, s)
                       for s in seeds]
    in_band = sum(1 for a in activities
                       if ACTIVITY_MIN <= a <= ACTIVITY_MAX)
    return (in_band >= quorum, sum(activities) / len(activities))


def render_lut_png(lut: np.ndarray, out_path: Path):
    """128×128 PNG with the K=4 palette."""
    from PIL import Image
    palette = [(0,0,0), (60,150,220), (240,180,60), (250,245,240)]
    pal = np.array(palette, dtype=np.uint8)
    grid = lut.reshape(128, 128) & 3
    rgb = pal[grid]
    img = Image.fromarray(rgb, 'RGB').resize((256, 256), Image.NEAREST)
    img.save(out_path)


class Command(BaseCommand):
    help = ('Continuously generate class-4 LUTs (the caformer "dreams").'
            '  Saves to .artifacts/dmn_dreams/ as .lut + .png pairs.')

    def add_arguments(self, parser):
        parser.add_argument('--interval-sec', type=float, default=3.0,
                              help='target seconds between dreams '
                                     '(rejected candidates count too)')
        parser.add_argument('--max-pool', type=int, default=200,
                              help='cap on stored dreams; oldest get culled')
        parser.add_argument('--pool-dir', type=str,
                              default='.artifacts/dmn_dreams')
        parser.add_argument('--once', action='store_true',
                              help='generate just one dream then exit')
        parser.add_argument('--max-iterations', type=int, default=0,
                              help='quit after this many tries (0 = forever)')

    def handle(self, *, interval_sec, max_pool, pool_dir, once,
                 max_iterations, **opts):
        from caformer.lut_generators import (gen_mandelbrot, gen_julia,
                                                       gen_burning_ship,
                                                       gen_tricorn,
                                                       gen_multibrot,
                                                       gen_newton,
                                                       gen_phoenix)
        from django.conf import settings
        from datetime import datetime
        import secrets

        # Weighted by observed class-4 hit rate (caformer_generator_compare):
        # julia 73%, newton 55%, multi 48%, tricorn 47%, bship 37%,
        # phoenix 35%, mandel 18%.  Weights are integer copy-counts so
        # secrets.choice() handles the bias without needing an RNG.
        gens_with_weight = [
            ('mandel',   gen_mandelbrot,   1),
            ('julia',    gen_julia,        4),
            ('bship',    gen_burning_ship, 2),
            ('tricorn',  gen_tricorn,      3),
            ('multi',    gen_multibrot,    3),
            ('newton',   gen_newton,       3),
            ('phoenix',  gen_phoenix,      2),
        ]
        gens = [(n, fn) for n, fn, w in gens_with_weight for _ in range(w)]
        gen_names_unique = [n for n, _, _ in gens_with_weight]

        base = Path(settings.BASE_DIR)
        pool = (base / pool_dir) if not Path(pool_dir).is_absolute() \
                                          else Path(pool_dir)
        pool.mkdir(parents=True, exist_ok=True)

        def log(m): self.stdout.write(m + '\n'); self.stdout.flush()

        log(f'=== caformer_dmn_dream ===')
        log(f'  pool:        {pool}')
        log(f'  interval:    {interval_sec}s')
        log(f'  max_pool:    {max_pool}')
        log(f'  once:        {once}')
        log(f'  generators:  {gen_names_unique}')
        weights = {n: w for n, _, w in gens_with_weight}
        log(f'  weights:     {weights}')
        log(f'  band:        [{ACTIVITY_MIN}, {ACTIVITY_MAX}]')
        log(f'  probe:       {PROBE_SIDE}×{PROBE_SIDE}, {PROBE_TICKS}t '
            f'({PROBE_TRANSIENT}t transient), {len(PROBE_SEEDS)} seeds quorum 2/3\n')

        n_tries = 0
        n_kept  = 0
        n_class1or3 = 0

        while True:
            n_tries += 1
            iter_t0 = time.time()
            # Pick a generator at random.
            gen_name, gen_fn = secrets.choice(gens)
            rng = np.random.RandomState(secrets.randbits(32))
            try:
                lut = gen_fn(rng)
            except Exception as e:
                log(f'  [{n_tries}] {gen_name}: gen error {e!r}')
                lut = None
            if lut is not None:
                arr = np.asarray(lut, dtype=np.uint8).ravel() & 3
                if arr.size != 16384:
                    arr = None
                else:
                    is_c4, act = is_class4(arr)
                    if is_c4:
                        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                        sid = secrets.token_hex(2)
                        name = f'{ts}_{gen_name}_act{act:.2f}_{sid}'
                        (pool / f'{name}.lut').write_bytes(bytes(arr))
                        try:
                            render_lut_png(arr, pool / f'{name}.png')
                        except Exception as e:
                            log(f'  png render failed: {e!r}')
                        n_kept += 1
                        log(f'  [{n_tries:4d}] {gen_name:7s} '
                            f'act={act:.3f} → kept {name}.lut '
                            f'({n_kept} dreams in pool)')
                    else:
                        n_class1or3 += 1

            # Cull oldest if over cap.
            existing = sorted(pool.glob('*.lut'),
                                  key=lambda p: p.stat().st_mtime)
            while len(existing) > max_pool:
                oldest = existing.pop(0)
                try:
                    oldest.unlink()
                    (oldest.with_suffix('.png')).unlink(missing_ok=True)
                except OSError:
                    pass

            if once:
                log(f'\n  --once: exiting after 1 attempt')
                break
            if max_iterations and n_tries >= max_iterations:
                log(f'\n  reached --max-iterations={max_iterations}, exiting')
                break

            # Sleep just enough to hit interval; class-1/3 rejections
            # already cost time so this is a soft target.
            elapsed = time.time() - iter_t0
            sleep_for = max(0.0, interval_sec - elapsed)
            time.sleep(sleep_for)
