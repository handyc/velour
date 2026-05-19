"""Per-position training of every pair at a chosen multires tier.

Empirical experiment: train each QRPair's response chain from scratch
at a small tier side (8, 16, 32, 64) and measure how many pairs go
byte-exact at that resolution, plus total wall time.

If a small tier reaches the same EXACT rate as board128 in a fraction
of the compute, the multires architecture justifies itself: smaller
chains for cheap fallbacks AND for fast training when only one byte
is wrong (the corrector use case).

Usage:
  manage.py caformer_train_tier --side 16 --per-pos-seconds 5
  manage.py caformer_train_tier --side 8  --pair-ids 14,21,24,33

Persists each trained chain into the matching QRPair blob field
(b008_rules_blob, b016_rules_blob, etc.).
"""
from __future__ import annotations

import sys
import time

import numpy as np
from django.core.management.base import BaseCommand


TIER_FIELD = {8: 'b008_rules_blob',
                16: 'b016_rules_blob',
                32: 'b032_rules_blob',
                64: 'b064_rules_blob'}


class Command(BaseCommand):
    help = ('Train every pair\'s response chain from scratch at a '
            'small multires tier; persist + report EXACT rate + wall.')

    def add_arguments(self, parser):
        parser.add_argument('--side',  type=int, default=16,
                              choices=[8, 16, 32, 64])
        parser.add_argument('--per-pos-seconds', type=float, default=5.0,
                              help='per-position budget')
        parser.add_argument('--pair-ids', type=str, default='',
                              help='comma-separated subset; default = all')
        parser.add_argument('--seed', type=int, default=0xB04A)
        parser.add_argument('--persist', action='store_true', default=True,
                              help='save rules to QRPair blob field')

    def handle(self, *, side, per_pos_seconds, pair_ids, seed, persist,
                 **opts):
        from caformer.board_multires import (tier_geometry,
                                                    train_position_tier)
        from caformer.models import QRPair

        if pair_ids.strip():
            ids = [int(x) for x in pair_ids.split(',') if x.strip()]
            pairs = list(QRPair.objects.filter(pk__in=ids).order_by('pk'))
        else:
            pairs = list(QRPair.objects.all().order_by('pk'))

        cap = tier_geometry(side)['response_bytes_max']
        field = TIER_FIELD[side]

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        log(f'=== train tier side={side} ({cap}-byte response cap) ===')
        log(f'  pairs:           {len(pairs)}')
        log(f'  budget per pos:  {per_pos_seconds}s')
        log(f'  persist to:      QRPair.{field}')

        grand_t0 = time.time()
        n_exact = 0
        n_skipped = 0
        n_oversized = 0
        records = []
        for pair in pairs:
            target_bytes = pair.expected.encode('utf-8')
            n_pos = len(target_bytes)
            if n_pos > cap:
                log(f'  skip pk={pair.pk}: response {n_pos}B > '
                    f'tier cap {cap}B')
                n_oversized += 1
                n_skipped += 1
                continue
            t0 = time.time()
            rules = []
            matches = []
            for pos, tb in enumerate(target_bytes):
                r = train_position_tier(
                    pair.prompt, tb, pos, side,
                    max_seconds=per_pos_seconds,
                    seed=seed ^ (pair.pk * 311) ^ (pos * 4099))
                rules.append(r['rule_table'].astype(np.uint8))
                matches.append(bool(r['byte_match']))
            wall = time.time() - t0
            exact = all(matches)
            if exact:
                n_exact += 1
            n_match = sum(matches)
            records.append((pair.pk, n_match, n_pos, exact, wall))
            mark = '✓' if exact else '✗'
            log(f'  pk={pair.pk:>3} {mark} '
                f'{n_match}/{n_pos} bytes  ({wall:.1f}s)  '
                f'expected={pair.expected!r}')
            if persist:
                blob = b''.join(bytes(r) for r in rules)
                setattr(pair, field, blob)
                pair.save(update_fields=[field])

        grand = time.time() - grand_t0
        n_attempted = len(pairs) - n_skipped
        log(f'\n=== tier {side}×{side} summary ===')
        log(f'  pairs attempted: {n_attempted}')
        log(f'  pairs oversized: {n_oversized}')
        log(f'  EXACT:           {n_exact}/{n_attempted} '
            f'({100*n_exact/max(1,n_attempted):.1f}%)')
        log(f'  wall:            {grand:.0f}s')
        # Compare with board128 for context.
        n_b128_exact = QRPair.objects.filter(board128_exact=True).count()
        log(f'  board128 EXACT:  {n_b128_exact}/71 (for reference)')
