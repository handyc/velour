"""Diff two PNG screenshots and emit an overlay highlighting the changes.

    python manage.py shotdiff before.png after.png \\
        --out diff.png \\
        [--threshold 16]

Useful next to ``browsershot``: snap a legacy URL and its datalifted
port, then diff to see where the rendered output differs. The overlay
PNG shows ``before`` desaturated with all pixels whose channel-wise
delta exceeds ``--threshold`` painted bright red.

Backed by Pillow (already in the velour venv).
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Visual diff of two PNG screenshots; writes an overlay PNG.'

    def add_arguments(self, parser):
        parser.add_argument('before', help='Reference PNG (e.g. legacy site).')
        parser.add_argument('after', help='Comparison PNG (e.g. lifted port).')
        parser.add_argument(
            '--out', required=True,
            help='Where to write the overlay PNG.',
        )
        parser.add_argument(
            '--threshold', type=int, default=16,
            help='Per-channel delta below which pixels are treated as identical.',
        )

    def handle(self, *args, **opts):
        try:
            from PIL import Image, ImageChops, ImageOps
        except ImportError:
            raise CommandError(
                'Pillow is not installed. `pip install pillow` and try again.'
            )
        a = Path(opts['before'])
        b = Path(opts['after'])
        out = Path(opts['out'])
        if not a.is_file():
            raise CommandError(f'before not found: {a}')
        if not b.is_file():
            raise CommandError(f'after not found: {b}')

        img_a = Image.open(a).convert('RGBA')
        img_b = Image.open(b).convert('RGBA')

        # Pad smaller image to the larger size so unequal sizes still compare.
        w = max(img_a.width, img_b.width)
        h = max(img_a.height, img_b.height)
        canvas_a = Image.new('RGBA', (w, h), (255, 255, 255, 255))
        canvas_a.paste(img_a, (0, 0))
        canvas_b = Image.new('RGBA', (w, h), (255, 255, 255, 255))
        canvas_b.paste(img_b, (0, 0))

        diff = ImageChops.difference(canvas_a.convert('RGB'),
                                     canvas_b.convert('RGB'))
        # Mask: 1 where any channel delta exceeds threshold
        threshold = opts['threshold']
        bands = diff.split()
        mask = bands[0].point(lambda p: 255 if p > threshold else 0)
        for band in bands[1:]:
            mask = ImageChops.lighter(
                mask, band.point(lambda p: 255 if p > threshold else 0))

        # Build the overlay: desaturate `after` then paint diff pixels red.
        base = ImageOps.grayscale(canvas_b.convert('RGB')).convert('RGB')
        red = Image.new('RGB', (w, h), (220, 30, 30))
        overlay = Image.composite(red, base, mask)

        out.parent.mkdir(parents=True, exist_ok=True)
        overlay.save(out, format='PNG')

        total_pixels = w * h
        diff_pixels = sum(1 for p in mask.getdata() if p)
        pct = 100.0 * diff_pixels / total_pixels if total_pixels else 0.0
        max_delta = max(diff.getextrema(), key=lambda r: r[1])[1]

        self.stdout.write(self.style.SUCCESS(
            f'shotdiff → {out}\n'
            f'  before:    {a} ({img_a.width}×{img_a.height})\n'
            f'  after:     {b} ({img_b.width}×{img_b.height})\n'
            f'  size:      {w}×{h} (overlay)\n'
            f'  diff:      {diff_pixels}/{total_pixels} pixels '
            f'({pct:.2f}%) above threshold {threshold}\n'
            f'  max-delta: {max_delta} (per channel, 0-255)'
        ))
