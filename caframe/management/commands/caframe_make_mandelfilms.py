"""Batch-create caframe Sequence rows from a mandelhunt LUT pool.

For each .lut file in the pool, persists a Sequence row pointing at
that rule and pre-renders an APNG so /caframe/<slug>/ shows real
frames immediately.  Designed to bulk-populate a "mandelfilms" pool
for browsing, comparing, or eventually feeding to Zoetrope's
ReelTournament.

Usage:
  manage.py caframe_make_mandelfilms                # default pool
  manage.py caframe_make_mandelfilms \\
      --pool .artifacts/mandelhunt_pool --n-frames 60 --w 64 --h 64 \\
      --max-films 50
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils.text import slugify


SR_RE = re.compile(r'sr(\d+\.\d+)')


class Command(BaseCommand):
    help = ('Walk a mandelhunt LUT pool and create a caframe Sequence + '
            'pre-rendered APNG for each.  Films appear at /caframe/<slug>/.')

    def add_arguments(self, parser):
        parser.add_argument('--pool', type=str,
                              default='.artifacts/loupe_rules')
        parser.add_argument('--n-frames', type=int, default=48)
        parser.add_argument('--w', type=int, default=64)
        parser.add_argument('--h', type=int, default=64)
        parser.add_argument('--seed', type=int, default=0xCAFEBABE,
                              help='LCG seed for the initial grid')
        parser.add_argument('--max-films', type=int, default=20,
                              help='cap on how many to create this run')
        parser.add_argument('--min-sr', type=float, default=0.5,
                              help='skip LUTs whose filename sr is below this')
        parser.add_argument('--prefix', type=str, default='mh',
                              help='slug prefix for created Sequences')

    def handle(self, *, pool, n_frames, w, h, seed, max_films, min_sr,
                 prefix, **opts):
        from caframe.models import Sequence
        from caframe import sources as src
        from caframe.render import iter_frames, grids_to_apng

        pool_p = Path(pool)
        if not pool_p.is_dir():
            sys.stdout.write(f'pool dir not found: {pool_p}\n')
            return
        luts = sorted(pool_p.glob('*.lut'))
        # Sort by sr descending, filter by min_sr.
        scored = []
        for p in luts:
            m = SR_RE.search(p.name)
            sr = float(m.group(1)) if m else 0.0
            if sr >= min_sr:
                scored.append((sr, p))
        scored.sort(key=lambda x: -x[0])
        scored = scored[:max_films]

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        log(f'=== caframe_make_mandelfilms ===')
        log(f'  pool:    {pool_p}')
        log(f'  films:   {len(scored)} (cap {max_films}, min_sr {min_sr})')
        log(f'  shape:   {w}×{h} × {n_frames} frames')
        log(f'  seed:    0x{seed:08x}\n')

        t0 = time.time()
        n_made = 0
        n_skipped = 0
        for sr, path in scored:
            try:
                rule, init, label = src.from_mandelhunt(
                    path.name, seed_init=seed, pool_dir=str(pool_p))
            except src.SourceUnavailable as e:
                log(f'  skip {path.name}: {e}')
                n_skipped += 1
                continue
            slug = slugify(f'{prefix}-{path.stem}')[:80]
            seq, created = Sequence.objects.update_or_create(
                slug=slug, defaults={
                    'name':        f'{prefix}: {path.stem}',
                    'shape':       Sequence.SHAPE_HEX,
                    'grid_w':      w, 'grid_h': h,
                    'n_colors':    4, 'n_frames': n_frames,
                    'rule_genome': rule, 'seed': init,
                    'source_app':  'caframe.import.mandelhunt',
                    'source_ref':  label,
                })
            # Pre-render an APNG so the detail page shows real frames.
            frames = list(iter_frames(
                rule_genome=rule, seed=init, w=w, h=h,
                n_colors=4, n_frames=n_frames))
            apng = grids_to_apng(frames, cell_px=4)
            apng_path = pool_p / f'{slug}.apng'
            apng_path.write_bytes(apng)
            n_made += 1
            mark = '+' if created else 'u'
            log(f'  {mark} {slug:42s} sr={sr:.3f} '
                f'apng={len(apng):>6}B  → /caframe/{slug}/')

        log(f'\ndone — {n_made} films created, {n_skipped} skipped, '
            f'wall {time.time()-t0:.1f}s')
        log(f'  view at: http://127.0.0.1:7777/caframe/')
        log(f'  APNGs:   {pool_p}/<slug>.apng')
