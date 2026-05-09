"""manage.py decode_ansi <path> — read an ANSI byte stream from
disk (or stdin with `-`) and emit a luminance-shaded ASCII rendering
plus a colour-pair tally.  The command exists so a non-terminal
caller (a Claude session, a CI job, a code review thread) can
inspect what was on a terminal without needing to actually run
one.

Generalises beyond officerpg: any program's screen capture works
— `script` typescripts, asciicast bodies, captured CI logs, etc.
"""
from __future__ import annotations

import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from terminalshot import decoder as D


class Command(BaseCommand):
    help = ('Decode an ANSI byte stream into a shaded ASCII '
            'rendering + colour-pair summary.')

    def add_arguments(self, parser):
        parser.add_argument(
            'path',
            help='Path to the ANSI capture, or "-" for stdin.')
        parser.add_argument(
            '--cols', type=int, default=80,
            help='Terminal width to emulate (default 80).')
        parser.add_argument(
            '--rows', type=int, default=24,
            help='Terminal height to emulate (default 24).')
        parser.add_argument(
            '--no-palette', action='store_true',
            help='Skip the colour-pair summary at the end.')
        parser.add_argument(
            '--show-bytes', type=int, default=0,
            help='If >0, print the first N raw bytes (hex) before '
                 'decoding — useful for sanity-checking the file.')

    def handle(self, *args, **opts):
        path = opts['path']
        if path == '-':
            blob = sys.stdin.buffer.read()
        else:
            p = Path(path)
            if not p.is_file():
                raise CommandError(f'No such file: {p}')
            blob = p.read_bytes()
        if opts['show_bytes']:
            n = min(opts['show_bytes'], len(blob))
            self.stdout.write(self.style.NOTICE(
                f'first {n} bytes (hex):'))
            self.stdout.write('  ' + ' '.join(
                f'{b:02x}' for b in blob[:n]))
        grid = D.parse(blob, cols=opts['cols'], rows=opts['rows'])
        self.stdout.write(self.style.NOTICE(
            f'== shaded {opts["cols"]}×{opts["rows"]} (cells '
            f'with chars keep them; spaces map to luminance shade) =='))
        self.stdout.write(D.render_shaded(grid))
        if not opts['no_palette']:
            self.stdout.write('')
            self.stdout.write(self.style.NOTICE('== palette =='))
            self.stdout.write(D.color_summary(grid))
