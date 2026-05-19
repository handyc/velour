"""Benchmark the small-board trainer at every tier of the multires
ladder.  For one (prompt, target_byte, position) task, train fresh
rules at sides 128, 64, 32, 16, 8 and report:

  - wall time to EXACT (or budget_out)
  - generations to EXACT
  - storage cost (always 16,384 B per rule — the LUT size doesn't
    shrink across tiers, only the board does)

This measures whether the corrector concept ("small boards train
faster for single-byte targets") actually holds empirically.

Usage:
  manage.py caformer_corrector_bench --prompt 'hi' --byte h --position 0
  manage.py caformer_corrector_bench --pair-id 14 --position 2
"""
from __future__ import annotations

import sys
import time

from django.core.management.base import BaseCommand, CommandError


LADDER_SIDES = (128, 64, 32, 16, 8)


class Command(BaseCommand):
    help = ('Train a single-byte target at every tier of the multires '
            'ladder; report wall, generations, EXACT-or-not.')

    def add_arguments(self, parser):
        parser.add_argument('--prompt',   type=str, default=None)
        parser.add_argument('--byte',     type=str, default=None,
                              help='single character target byte')
        parser.add_argument('--position', type=int, default=0)
        parser.add_argument('--pair-id',  type=int, default=None,
                              help='use pair\'s prompt + expected[position]')
        parser.add_argument('--tiers',    type=str,
                              default=','.join(str(s) for s in LADDER_SIDES),
                              help='comma-separated sides to benchmark')
        parser.add_argument('--per-tier-seconds', type=float, default=60.0)
        parser.add_argument('--seed',     type=int, default=0xB04A)

    def handle(self, *, prompt, byte, position, pair_id, tiers,
                 per_tier_seconds, seed, **opts):
        from caformer.board_multires import train_position_tier

        # Resolve target.
        if pair_id is not None:
            from caformer.models import QRPair
            try:
                pair = QRPair.objects.get(pk=pair_id)
            except QRPair.DoesNotExist:
                raise CommandError(f'pair {pair_id} not found')
            prompt = prompt or pair.prompt
            if byte is None:
                target_bytes = pair.expected.encode('utf-8')
                if position >= len(target_bytes):
                    raise CommandError(
                        f'position {position} out of range for expected '
                        f'len={len(target_bytes)}')
                byte = chr(target_bytes[position])
        if not prompt or not byte:
            raise CommandError('need --prompt + --byte, or --pair-id')

        target_byte = ord(byte) if len(byte) == 1 else int(byte, 0)
        tier_list = [int(x) for x in tiers.split(',') if x.strip()]

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        log(f'=== corrector bench ===')
        log(f'  prompt:   {prompt!r}')
        log(f'  target:   byte={target_byte:#04x} char={chr(target_byte)!r}')
        log(f'  position: {position}')
        log(f'  tiers:    {tier_list}')
        log(f'  budget:   {per_tier_seconds}s per tier')
        log('')
        log(f'  {"tier":>5} {"side":>5} {"wall_s":>7} {"gens":>6} {"phase":>10} {"speedup_vs_128":>14}')

        from caformer.board_multires import tier_geometry

        results = []
        for side in tier_list:
            cap = tier_geometry(side)['response_bytes_max']
            if position >= cap:
                log(f'  {side:>5} {side:>5}     ---      --- skipped   '
                    f'(response cap {cap}; pos {position} out of range)')
                continue
            t0 = time.time()
            r = train_position_tier(
                prompt, target_byte, position, side,
                max_seconds=per_tier_seconds,
                seed=seed)
            wall = time.time() - t0
            results.append((side, wall, r))
            log(f'  {side:>5} {side:>5} {wall:>7.2f} '
                f'{r["generations"]:>6} {r["phase"]:>10}')

        # Speedup ratio vs the 128 tier (if both EXACT-converged).
        log('')
        baseline = next((r for r in results if r[0] == 128
                            and r[2]['phase'] in ('init', 'matched')), None)
        if baseline:
            log(f'  speedup-to-EXACT vs board128:')
            for side, wall, r in results:
                if r['phase'] in ('init', 'matched'):
                    speedup = baseline[1] / max(wall, 1e-3)
                    log(f'    side={side:>3}: {speedup:>6.1f}×  '
                        f'(wall {wall:.2f}s)')
                else:
                    log(f'    side={side:>3}: did not converge '
                        f'({r["phase"]} at {wall:.2f}s)')
        log('')
        log(f'  storage per rule: 16,384 B (constant across tiers — '
            f'LUT size is fixed, only the board shrinks)')
