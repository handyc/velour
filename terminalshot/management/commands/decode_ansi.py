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
        parser.add_argument(
            '--frames', action='store_true',
            help='Split the stream by DECSET 2026 sync markers and '
                 'render each frame independently with a divider — '
                 'useful for animated sessions like the saver.')
        parser.add_argument(
            '--frame', type=int, default=None,
            help='With --frames, render only the Nth frame (0-based; '
                 'negative indices count from the end).')
        parser.add_argument(
            '--frame-count', action='store_true',
            help='Print only the number of detected frames.')

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

        if opts['frame_count']:
            slices = D.split_frames(blob)
            self.stdout.write(f'{len(slices)} frame(s)')
            return

        if opts['frames'] or opts['frame'] is not None:
            grids = D.parse_frames(blob,
                                   cols=opts['cols'], rows=opts['rows'])
            if opts['frame'] is not None:
                idx = opts['frame']
                if idx < 0: idx += len(grids)
                if idx < 0 or idx >= len(grids):
                    raise CommandError(
                        f'frame {opts["frame"]} out of range '
                        f'(stream has {len(grids)} frames)')
                grids = [(idx, grids[idx])]
            else:
                grids = list(enumerate(grids))
            for n_, grid in grids:
                self.stdout.write(self.style.NOTICE(
                    f'== frame {n_} ({opts["cols"]}×{opts["rows"]}) =='))
                self.stdout.write(D.render_shaded(grid))
                self.stdout.write('')
            if not opts['no_palette']:
                self.stdout.write(self.style.NOTICE('== final-frame palette =='))
                self.stdout.write(D.color_summary(grids[-1][1]))
            return

        grid = D.parse(blob, cols=opts['cols'], rows=opts['rows'])
        self.stdout.write(self.style.NOTICE(
            f'== shaded {opts["cols"]}×{opts["rows"]} (cells '
            f'with chars keep them; spaces map to luminance shade) =='))
        self.stdout.write(D.render_shaded(grid))
        if not opts['no_palette']:
            self.stdout.write('')
            self.stdout.write(self.style.NOTICE('== palette =='))
            self.stdout.write(D.color_summary(grid))
