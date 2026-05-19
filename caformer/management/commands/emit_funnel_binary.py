"""Emit a standalone C source for the funnel CA-LLM and optionally compile.

The C program embeds:
- the trained per-(slot, pos, cell) LUTs (each 16,384 bytes)
- the vocab string table
- a hex K=4 step function identical to caformer.primitives.hex_ca_step

Output is byte-identical to the live /caformer/funnel-chat/?layer=word2.

Usage::

    manage.py emit_funnel_binary --out /tmp/funnel-cli
    manage.py emit_funnel_binary --out /tmp/funnel-cli --source-only
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from caformer.funnel_emit_c import emit_word_binder_v2_c


class Command(BaseCommand):
    help = ('Emit and compile a standalone C binary that runs the trained '
              'funnel CA-LLM pipeline (word_binder_v2).')

    def add_arguments(self, parser):
        parser.add_argument('--model-dir', type=str,
                              default='.artifacts/word_binder_v2')
        parser.add_argument('--out', type=str, default='funnel-cli',
                              help='output path; .c source written next to it')
        parser.add_argument('--source-only', action='store_true',
                              help='skip compilation, only write .c')
        parser.add_argument('--cc', type=str, default='cc',
                              help='C compiler (cc | gcc | clang)')

    def handle(self, *, model_dir, out, source_only, cc, **opts):
        md = Path(settings.BASE_DIR) / model_dir if not Path(model_dir).is_absolute() else Path(model_dir)
        if not (md / 'vocab.json').exists():
            raise CommandError(
                f'no vocab.json in {md} — train word_binder_v2 first')

        out_bin = Path(out).resolve()
        out_src = out_bin.with_suffix('.c')
        out_src.parent.mkdir(parents=True, exist_ok=True)

        src = emit_word_binder_v2_c(md)
        out_src.write_text(src)
        size_kb = len(src) / 1024
        self.stdout.write(self.style.SUCCESS(
            f'wrote {out_src} ({size_kb:.0f} KB source)'))

        if source_only:
            return

        # Compile.
        cmd = [cc, '-O2', '-Wall', '-o', str(out_bin), str(out_src)]
        self.stdout.write(' '.join(cmd))
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            self.stdout.write(self.style.ERROR('compile failed:'))
            self.stdout.write(r.stdout)
            self.stdout.write(r.stderr)
            raise CommandError(f'{cc} returned {r.returncode}')
        bin_size_kb = out_bin.stat().st_size / 1024
        self.stdout.write(self.style.SUCCESS(
            f'compiled {out_bin} ({bin_size_kb:.0f} KB binary)'))
        self.stdout.write('')
        self.stdout.write(self.style.NOTICE(
            f'try it:  {out_bin} "look up cats"'))
