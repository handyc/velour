"""Scan loupe Mandelbrot regions as candidate K=4 hex CA rules.

Same pipeline as the spoeqi famous-artwork scan, but the image source
is a Mandelbrot region (or every frame of a saved agent walk) instead
of a curated art-history image.  Hypothesis: fractal self-similarity
correlates with class-4 + quine-friendly LUT structure, because both
properties involve scale-invariant local patterning.

Usage:

  # Single coordinate test (default Mandelbrot view):
  manage.py caformer_loupe_as_rules

  # Specific coordinate:
  manage.py caformer_loupe_as_rules --cx -0.75 --cy 0.1 --span 0.5

  # Every frame of a saved loupe walk:
  manage.py caformer_loupe_as_rules --walk <slug>

  # Save candidates above a threshold to disk:
  manage.py caformer_loupe_as_rules --walk <slug> \\
      --save-dir .artifacts/loupe_rules --sr-min 0.4
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from django.core.management.base import BaseCommand, CommandError


SIDE = 128            # 7→1 LUT-as-image natural board side
LUT_CELLS = SIDE * SIDE   # 16,384


class Command(BaseCommand):
    help = ('Take Mandelbrot regions (or every frame of a loupe '
            'agent walk), posterise to K=4, treat as 16,384-byte '
            'hex CA rule tables, and classify for class-4 / quine '
            'properties.')

    def add_arguments(self, parser):
        parser.add_argument('--cx',   type=float, default=-0.5)
        parser.add_argument('--cy',   type=float, default=0.0)
        parser.add_argument('--span', type=float, default=3.0)
        parser.add_argument('--iter-cap', type=int, default=None,
                              help='Mandelbrot iteration cap (None = auto)')
        parser.add_argument('--walk', type=str, default='',
                              help='loupe Walk slug; scan every gene step')
        parser.add_argument('--sr-min', type=float, default=0.0,
                              help='only report frames with strict SR ≥ this')
        parser.add_argument('--cls', type=int, default=0,
                              choices=[0, 1, 2, 3, 4],
                              help='filter to Wolfram class (0 = any)')
        parser.add_argument('--save-dir', type=str, default='',
                              help='write the LUT of every reported frame '
                                     'here (.lut + .json sidecar)')
        parser.add_argument('--ticks', type=int, default=16,
                              help='ticks for self-reproduction score')
        parser.add_argument('--limit', type=int, default=0,
                              help='cap how many walk frames to test '
                                     '(0 = all)')

    def handle(self, *, cx, cy, span, iter_cap, walk, sr_min, cls,
                 save_dir, ticks, limit, **opts):
        from loupe.render import mandelbrot_buckets
        from spoeqi.metachain import (classify_rule, probe_activity,
                                          self_reproduce_score)

        def _log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        out_dir = Path(save_dir) if save_dir else None
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)

        # Build the list of frames to test.
        frames = []
        if walk:
            from loupe.models import Walk
            w = Walk.objects.filter(slug=walk).first()
            if w is None:
                raise CommandError(f'no loupe Walk with slug={walk!r}')
            gene = w.gene_json or []
            if limit > 0:
                gene = gene[:limit]
            _log(f'=== scanning walk {walk!r} ({len(gene)} frames) ===')
            for i, step in enumerate(gene):
                step_cx   = float(step.get('cx',   -0.5))
                step_cy   = float(step.get('cy',   0.0))
                step_span = float(step.get('span', 3.0))
                step_ic   = step.get('iter', iter_cap)
                frames.append((f'step{i:04d}', step_cx, step_cy,
                                  step_span, step_ic))
        else:
            frames.append(('single', cx, cy, span, iter_cap))

        # Test each frame.
        results = []
        t0 = time.time()
        for name, fcx, fcy, fspan, fic in frames:
            # Render the K=4 bucket array directly (no PNG roundtrip).
            buckets = mandelbrot_buckets(fcx, fcy, fspan, SIDE, SIDE,
                                              iter_cap=fic)
            # 128×128 ⇒ 16,384 K=4 cells ⇒ one full LUT.
            lut_bytes = bytes(buckets.ravel().astype(np.uint8))
            # Classify.
            sr     = self_reproduce_score(lut_bytes, ticks=ticks)
            class_, c4 = classify_rule(lut_bytes, probe_ticks=16)
            act    = probe_activity(lut_bytes, ticks=12)
            row = {
                'frame':     name,
                'cx':        fcx,
                'cy':        fcy,
                'span':      fspan,
                'sr_strict': sr,
                'class':     class_,
                'c4_score':  c4,
                'activity':  act,
            }
            results.append(row)
            # Tight one-line log.
            _log(f'  {name}  cx={fcx:+.6f} cy={fcy:+.6f} '
                 f'span={fspan:.3g}  cls={class_} c4={c4:.3f} '
                 f'SR={sr:.3f} act={act:.3f}')
            # Optional save when filters pass.
            if out_dir and sr >= sr_min and (cls == 0 or class_ == cls):
                lut_path = out_dir / f'{name}_sr{sr:.3f}_cls{class_}.lut'
                lut_path.write_bytes(lut_bytes)
                (out_dir / (lut_path.stem + '.json')).write_text(
                    json.dumps(row, indent=2))

        wall = time.time() - t0
        _log('')
        _log(f'=== {len(results)} frames tested in {wall:.1f}s ===')

        # Summary leaderboards.
        if results:
            top_sr = sorted(results, key=lambda r: -r['sr_strict'])[:5]
            _log('')
            _log('Top 5 by strict self-reproduction:')
            for r in top_sr:
                _log(f'  SR={r["sr_strict"]:.4f}  cls={r["class"]}  '
                     f'c4={r["c4_score"]:.3f}  cx={r["cx"]:+.6f} '
                     f'cy={r["cy"]:+.6f} span={r["span"]:.3g}')
            n_class4 = sum(1 for r in results if r['class'] == 4)
            n_quine_candidate = sum(1 for r in results
                                       if r['sr_strict'] > 0.5
                                       and r['class'] == 4)
            _log('')
            _log(f'  class-4 frames:           {n_class4}/{len(results)}')
            _log(f'  quine-candidate frames:   {n_quine_candidate}/{len(results)}'
                 ' (cls=4 + SR>0.5)')

        # Always write a JSON report.
        if out_dir:
            (out_dir / 'scan_report.json').write_text(
                json.dumps({
                    'wall_seconds': wall,
                    'walk':         walk,
                    'frames':       results,
                }, indent=2))
            _log(f'  wrote {out_dir / "scan_report.json"}')
