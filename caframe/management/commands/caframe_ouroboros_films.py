"""Render zoetrope-reel films of the ouroboros-class quines.

For each quine in the catalogue that qualifies as "ouroboros-class"
(``ga_run_length ≥ 500`` OR ``ga_distinct_levels ≥ 50``), generate
N×30-second reels — each with a different random 4-colour palette —
then ffmpeg-concat them into a single 5-minute film per quine.

Output: ``.artifacts/ouroboros_films/<pk>-<sha>.mp4``

Usage::

    manage.py caframe_ouroboros_films
    manage.py caframe_ouroboros_films --reels 10 --reel-seconds 30
    manage.py caframe_ouroboros_films --only 122 --grid 96
"""
from __future__ import annotations

import io
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    """Standard HSV→RGB.  h ∈ [0,1), s,v ∈ [0,1].  Returns 0–255 ints."""
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def _random_palette(rng: random.Random) -> list[tuple[int, int, int]]:
    """Four harmonious random colours: hue-spread quartet with random
    rotation, plus moderate saturation/value variance.  Always returns
    visually distinguishable colours suitable for K=4 cell rendering."""
    base = rng.random()
    out: list[tuple[int, int, int]] = []
    for i in range(4):
        h = (base + i * 0.25 + rng.uniform(-0.04, 0.04)) % 1.0
        s = rng.uniform(0.45, 0.95)
        v = rng.uniform(0.55, 0.95)
        out.append(_hsv_to_rgb(h, s, v))
    return out


class Command(BaseCommand):
    help = ('Render 5-minute films per ouroboros-class quine — each '
              'made of N 30-s reels with random palettes, ffmpeg-concatted.')

    def add_arguments(self, parser):
        parser.add_argument('--reels', type=int, default=10,
                              help='Reels per film (default 10).')
        parser.add_argument('--reel-seconds', type=int, default=30,
                              help='Seconds per reel (default 30).')
        parser.add_argument('--fps', type=int, default=12,
                              help='Frames per second (default 12).')
        parser.add_argument('--grid', type=int, default=96,
                              help='Grid side in cells (default 96).')
        parser.add_argument('--cell-px', type=int, default=6,
                              help='Pixels per cell in output video (default 6).')
        parser.add_argument('--only', type=int, default=None,
                              help='Render only one quine pk (default: all '
                              'ouroboros-class quines in the catalogue).')
        parser.add_argument('--palette-seed', type=int, default=0,
                              help='Seed for the palette RNG; 0 = wall time '
                              '(default = different palettes per run).')
        parser.add_argument('--out-dir', type=str, default='',
                              help='Output dir (default .artifacts/ouroboros_films/).')
        parser.add_argument('--limit', type=int, default=0,
                              help='Cap the number of quines processed.')

    def handle(self, *args, reels, reel_seconds, fps, grid, cell_px,
                 only, palette_seed, out_dir, limit, **opts):
        from caformer.models import ComponentChampion
        from caframe import render as cf_render
        from caframe import sources as cf_sources

        if not cf_sources.ffmpeg_available():
            raise CommandError(
                'ffmpeg not on PATH; install it (apt install ffmpeg) and retry')

        # Resolve target quines.
        from ouroboros.views import is_ouroboros_class, _quine_meta
        qs = ComponentChampion.objects.filter(component_slug='class4_quine')
        if only is not None:
            qs = qs.filter(pk=only)
        targets: list = []
        for c in qs.order_by('-fitness', '-pk'):
            meta = _quine_meta(c)
            if only is not None or is_ouroboros_class(meta):
                targets.append((c, meta))
            if limit and len(targets) >= limit:
                break
        if not targets:
            raise CommandError(
                'no ouroboros-class quines matched.  Run '
                'manage.py deep_chain_search to find some, or pass --only PK.')

        # Output dir.
        if out_dir:
            out_root = Path(out_dir).resolve()
        else:
            out_root = Path(settings.BASE_DIR) / '.artifacts' / 'ouroboros_films'
        out_root.mkdir(parents=True, exist_ok=True)

        frames_per_reel = reel_seconds * fps
        self.stdout.write(self.style.NOTICE(
            f'rendering {len(targets)} quine film(s): '
            f'{reels} reels × {reel_seconds}s @ {fps}fps = '
            f'{reels * reel_seconds // 60}m per film, '
            f'grid {grid}×{grid}, cell {cell_px}px'))
        self.stdout.write(f'output dir: {out_root}')

        rng_seed_root = palette_seed or int(time.time())

        for ti, (c, meta) in enumerate(targets, 1):
            seed_bytes = bytes(c.rules_blob)
            import hashlib
            sha8 = hashlib.sha1(seed_bytes).hexdigest()[:8]
            display_name = meta.get('display_name') or f'ouroboros #{c.pk}'
            out_path = out_root / f'{c.pk:04d}-{sha8}.mp4'

            self.stdout.write('')
            self.stdout.write(self.style.NOTICE(
                f'[{ti}/{len(targets)}] {display_name} (pk={c.pk}, sha {sha8})'))
            self.stdout.write(
                f'  ga_run_length={meta.get("ga_run_length", "?")} '
                f'distinct={meta.get("ga_distinct_levels", "?")} '
                f'sr={c.fitness:.3f}')
            sys.stdout.flush()

            tmpdir = Path(tempfile.mkdtemp(prefix=f'ouro-{c.pk}-'))
            try:
                reel_paths = []
                for ri in range(reels):
                    rng = random.Random(rng_seed_root + c.pk * 99991 + ri)
                    palette = _random_palette(rng)
                    init_seed = rng.randrange(0, 2**32)
                    pal_str = ' '.join(
                        f'#{r:02x}{g:02x}{b:02x}' for r, g, b in palette)
                    self.stdout.write(
                        f'  reel {ri+1}/{reels}: seed={init_seed:#010x} '
                        f'palette={pal_str}')
                    sys.stdout.flush()

                    t0 = time.time()
                    frames = list(cf_render.iter_frames(
                        rule_genome=seed_bytes,
                        seed=init_seed,
                        w=grid, h=grid,
                        n_frames=frames_per_reel,
                        shape='hex', n_colors=4))
                    mp4 = cf_sources.frames_to_mp4(
                        frames, palette=palette,
                        cell_px=cell_px, fps=fps)
                    reel_path = tmpdir / f'reel-{ri:02d}.mp4'
                    reel_path.write_bytes(mp4)
                    reel_paths.append(reel_path)
                    elapsed = time.time() - t0
                    self.stdout.write(
                        f'    → {reel_path.name} ({len(mp4)/1024:.0f} KB, '
                        f'{elapsed:.1f}s)')
                    sys.stdout.flush()

                # ffmpeg concat demuxer: needs a manifest file.
                manifest = tmpdir / 'concat.txt'
                manifest.write_text(
                    ''.join(f"file '{p.name}'\n" for p in reel_paths))
                cmd = [
                    'ffmpeg', '-y', '-loglevel', 'error',
                    '-f', 'concat', '-safe', '0',
                    '-i', str(manifest),
                    '-c', 'copy', '-movflags', '+faststart',
                    str(out_path),
                ]
                t0 = time.time()
                proc = subprocess.run(cmd, cwd=tmpdir,
                                          capture_output=True, text=True)
                if proc.returncode != 0:
                    self.stdout.write(self.style.ERROR(
                        f'  ffmpeg concat failed (rc {proc.returncode}): '
                        f'{proc.stderr.strip()}'))
                    continue
                self.stdout.write(self.style.SUCCESS(
                    f'  ✔ {out_path.name} '
                    f'({out_path.stat().st_size/1024/1024:.1f} MB, '
                    f'concat {time.time()-t0:.1f}s)'))
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'done — {len(targets)} film(s) written to {out_root}'))
