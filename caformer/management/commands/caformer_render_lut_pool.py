"""Render a directory of 16,384-byte K=4 LUT files as PNGs.

Each .lut is interpreted as a 128×128 K=4 image (the Ouroboros view
— the LUT-as-board) and rendered with a fixed 4-colour palette.
Also produces a contact-sheet PNG showing the top-N candidates in a
grid so the visual pattern of "high-sr" rules can be inspected by
eye.

Filenames in the pool are expected to encode sr in the name
(e.g. `mh_n000016_sr0.706_c40.988.lut`).  We sort by parsed sr
descending.

Usage:
  manage.py caformer_render_lut_pool --pool .artifacts/loupe_rules
  manage.py caformer_render_lut_pool --pool .artifacts/mandelhunt_pool \\
      --top 24 --upscale 4
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
from django.core.management.base import BaseCommand, CommandError


PALETTE_K4 = [
    (  0,   0,   0),    # 0 black
    ( 60, 150, 220),    # 1 light blue
    (240, 180,  60),    # 2 amber
    (250, 245, 240),    # 3 off-white
]

SIDE = 128

# Parse "sr0.706" or similar out of a filename.
SR_RE = re.compile(r'sr(\d+\.\d+)')
C4_RE = re.compile(r'c4(\d+\.\d+)')


class Command(BaseCommand):
    help = ('Render a .lut pool as 128×128 PNGs + a contact-sheet of the '
            'top-N by sr.  For visually inspecting what successful '
            'ouroboros candidates look like.')

    def add_arguments(self, parser):
        parser.add_argument('--pool',     type=str, required=True,
                              help='directory of .lut files')
        parser.add_argument('--out',      type=str, default='',
                              help='output dir (default: <pool>/png)')
        parser.add_argument('--top',      type=int, default=16,
                              help='how many top-sr files to include in '
                                     'contact sheet (and to render '
                                     'individually)')
        parser.add_argument('--upscale',  type=int, default=4,
                              help='integer upscale factor for individual '
                                     'PNGs (default 4 → 512×512)')
        parser.add_argument('--all',      action='store_true',
                              help='render every .lut, not just --top')

    def handle(self, *, pool, out, top, upscale, all, **opts):
        from PIL import Image

        pool_p = Path(pool)
        if not pool_p.is_dir():
            raise CommandError(f'{pool} is not a directory')
        out_p = Path(out) if out else pool_p / 'png'
        out_p.mkdir(parents=True, exist_ok=True)

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        # Gather + sort by sr (descending).
        records = []
        for p in pool_p.glob('*.lut'):
            sr_m = SR_RE.search(p.name)
            c4_m = C4_RE.search(p.name)
            sr   = float(sr_m.group(1)) if sr_m else 0.0
            c4   = float(c4_m.group(1)) if c4_m else 0.0
            records.append((sr, c4, p))
        records.sort(key=lambda r: -r[0])
        log(f'pool: {pool_p}  ({len(records)} .lut files)')
        log(f'out:  {out_p}')

        # Build palette LUT for fast paste.
        pal = np.array(PALETTE_K4, dtype=np.uint8)
        # Palette image used by PIL putpalette.
        flat_palette = []
        for r, g, b in PALETTE_K4:
            flat_palette += [r, g, b]
        flat_palette += [0] * (768 - len(flat_palette))

        def render_lut(lut_bytes: bytes) -> 'Image':
            arr = np.frombuffer(lut_bytes, dtype=np.uint8)
            if arr.size != SIDE * SIDE:
                return None
            grid = arr.reshape(SIDE, SIDE) & 3
            rgb = pal[grid]
            return Image.fromarray(rgb, 'RGB')

        # Render top-N individually.
        targets = records if all else records[:top]
        for sr, c4, path in targets:
            img = render_lut(path.read_bytes())
            if img is None:
                log(f'  skip {path.name}: wrong size')
                continue
            if upscale > 1:
                img = img.resize((SIDE * upscale, SIDE * upscale),
                                    Image.NEAREST)
            out_name = path.stem + '.png'
            img.save(out_p / out_name)
        log(f'rendered {len(targets)} individual PNGs')

        # Contact sheet: top-N in a grid with labels.
        if records:
            grid_n = min(top, len(records))
            cols = 4 if grid_n >= 4 else grid_n
            rows = (grid_n + cols - 1) // cols
            tile = SIDE
            label_h = 18
            sheet = Image.new('RGB',
                              (cols * tile, rows * (tile + label_h)),
                              (10, 10, 12))
            try:
                from PIL import ImageDraw, ImageFont
                font = ImageFont.load_default()
                draw = ImageDraw.Draw(sheet)
            except Exception:
                draw = None
            for i, (sr, c4, path) in enumerate(records[:grid_n]):
                img = render_lut(path.read_bytes())
                if img is None:
                    continue
                row = i // cols
                col = i % cols
                x = col * tile
                y = row * (tile + label_h)
                sheet.paste(img, (x, y))
                if draw:
                    label = f'sr {sr:.2f}  c4 {c4:.2f}'
                    draw.text((x + 4, y + tile + 2),
                                label, fill=(220, 220, 220), font=font)
            sheet_path = out_p / f'_contact_top{grid_n}.png'
            sheet.save(sheet_path)
            log(f'contact sheet: {sheet_path}')

        log(f'\ndone — open the contact sheet to see the top-{grid_n} pattern')
