"""Take a real-browser screenshot of a URL for visual verification.

    python manage.py browsershot https://example.com \\
        --out /tmp/example.png \\
        [--width 1280] [--height 800] \\
        [--viewport-only] \\
        [--wait load|domcontentloaded|networkidle|commit] \\
        [--timeout 15000]

Useful for verifying that a datalifted Django site matches the
original visually — take one shot of the legacy URL, one of the
ported one, eyeball or diff the two PNGs.

Backed by Playwright + Chromium. See :mod:`datalift.browsershot`.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from datalift.browsershot import shoot


class Command(BaseCommand):
    help = 'Take a headless-browser PNG screenshot of a URL.'

    def add_arguments(self, parser):
        parser.add_argument('url', help='URL to navigate to.')
        parser.add_argument(
            '--out', required=True,
            help='Path where the PNG should be written.',
        )
        parser.add_argument(
            '--width', type=int, default=1280,
            help='Viewport width in CSS pixels (default 1280).',
        )
        parser.add_argument(
            '--height', type=int, default=800,
            help='Viewport height in CSS pixels (default 800).',
        )
        parser.add_argument(
            '--viewport-only', action='store_true',
            help='Capture only the viewport (default: full page).',
        )
        parser.add_argument(
            '--wait', default='networkidle',
            choices=['load', 'domcontentloaded', 'networkidle', 'commit'],
            help='Page-load wait condition (default: networkidle).',
        )
        parser.add_argument(
            '--timeout', type=int, default=15000,
            help='Navigation timeout in milliseconds (default 15000).',
        )

    def handle(self, *args, **opts):
        try:
            result = shoot(
                opts['url'],
                Path(opts['out']),
                width=opts['width'],
                height=opts['height'],
                full_page=not opts['viewport_only'],
                wait_until=opts['wait'],
                timeout_ms=opts['timeout'],
            )
        except Exception as e:
            raise CommandError(f'screenshot failed: {type(e).__name__}: {e}')

        self.stdout.write(self.style.SUCCESS(
            f'shot → {result.out_path}\n'
            f'  url:    {result.url}\n'
            f'  title:  {result.title!r}\n'
            f'  size:   {result.width}×{result.height} '
            f'({"full-page" if result.full_page else "viewport-only"})\n'
            f'  bytes:  {result.bytes_written}'
        ))
