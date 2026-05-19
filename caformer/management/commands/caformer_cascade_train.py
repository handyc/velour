"""Cascade trainer: try the cheapest tier first, fall back upward.

For each pair, train at side=16 first (5 s/pos budget).  If that
EXACTs, we're done — we got 32× faster inference and we paid almost
no training compute.  If a position doesn't EXACT, retry just that
position at side=32 (10 s).  If still not, fall back to side=128
(60 s, the patch trainer's standard budget).

Bookkeeping: every successful tier's chain is persisted, so dispatch
can pick the smallest one that EXACTs per pair.  Position-level
mixed-tier mode (e.g. position 0..16 at tier-16, position 17 at
board128) is NOT implemented yet — for now the entire chain is
either at one tier or another.  Position-mixed dispatch is task #65
followup.

Usage:
  manage.py caformer_cascade_train               # all pairs
  manage.py caformer_cascade_train --pair-ids 61,70
"""
from __future__ import annotations

import sys
import time

import numpy as np
from django.core.management.base import BaseCommand


TIER_FIELD = {8: 'b008_rules_blob',
                16: 'b016_rules_blob',
                32: 'b032_rules_blob',
                64: 'b064_rules_blob',
                128: 'board128_rules_blob'}

# Cascade order: cheapest first.  Each entry = (side, per_pos_seconds).
DEFAULT_CASCADE = [(16, 5.0), (32, 10.0), (64, 20.0), (128, 60.0)]


class Command(BaseCommand):
    help = ('Train each pair starting at the cheapest tier; only fall '
            'back to bigger tiers for pairs that don\'t go EXACT.')

    def add_arguments(self, parser):
        parser.add_argument('--pair-ids',     type=str, default='')
        parser.add_argument('--cascade',      type=str, default='',
                              help='comma-separated side:seconds pairs '
                                     '(default: 16:5,32:10,64:20,128:60)')
        parser.add_argument('--seed',         type=int, default=0xCA5CADE)
        parser.add_argument('--stop-at-first-exact', action='store_true',
                              default=True,
                              help='stop a pair once any tier EXACTs')

    def handle(self, *, pair_ids, cascade, seed,
                 stop_at_first_exact, **opts):
        from caformer.board_multires import (tier_geometry,
                                                    train_position_tier)
        from caformer.models import QRPair

        # Parse cascade.
        if cascade.strip():
            steps = []
            for x in cascade.split(','):
                a, b = x.split(':')
                steps.append((int(a), float(b)))
        else:
            steps = DEFAULT_CASCADE

        # Pair selection.
        if pair_ids.strip():
            ids = [int(x) for x in pair_ids.split(',') if x.strip()]
            pairs = list(QRPair.objects.filter(pk__in=ids).order_by('pk'))
        else:
            pairs = list(QRPair.objects.all().order_by('pk'))

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        log(f'=== cascade train: {len(pairs)} pairs, '
            f'cascade={steps} ===\n')

        grand_t0 = time.time()
        # Tally: how many pairs ended EXACT at each tier.
        ended_at_tier = {side: 0 for side, _ in steps}
        ended_at_tier[None] = 0   # never EXACTed
        cumulative_wall = {side: 0.0 for side, _ in steps}

        for pair in pairs:
            target_bytes = pair.expected.encode('utf-8')
            n_pos = len(target_bytes)
            t_pair0 = time.time()
            best_tier_exact = None
            for tier_idx, (side, per_pos) in enumerate(steps):
                cap = tier_geometry(side)['response_bytes_max']
                if n_pos > cap:
                    log(f'  pk={pair.pk:>3} side={side:>3} '
                        f'skip (resp {n_pos}>{cap})')
                    continue
                t_tier = time.time()
                rules = []
                matches = []
                for pos, tb in enumerate(target_bytes):
                    r = train_position_tier(
                        pair.prompt, tb, pos, side,
                        max_seconds=per_pos,
                        seed=seed ^ (pair.pk * 311) ^ (pos * 4099))
                    rules.append(r['rule_table'].astype(np.uint8))
                    matches.append(bool(r['byte_match']))
                wall = time.time() - t_tier
                cumulative_wall[side] += wall
                exact = all(matches)
                blob = b''.join(bytes(r) for r in rules)
                setattr(pair, TIER_FIELD[side], blob)
                if side == 128:
                    pair.board128_exact = exact
                    pair.board128_ticks = 128
                    pair.save(update_fields=[TIER_FIELD[side],
                                                  'board128_exact',
                                                  'board128_ticks'])
                else:
                    pair.save(update_fields=[TIER_FIELD[side]])
                mark = '✓' if exact else '✗'
                log(f'  pk={pair.pk:>3} side={side:>3} {mark} '
                    f'{sum(matches)}/{n_pos} bytes '
                    f'({wall:>5.1f}s)')
                if exact:
                    best_tier_exact = side
                    if stop_at_first_exact:
                        break

            ended_at_tier[best_tier_exact] += 1
            t_pair = time.time() - t_pair0
            mark = '✓' if best_tier_exact else '✗'
            log(f'  pk={pair.pk:>3} {mark} ended at '
                f'side={best_tier_exact}  '
                f'pair_wall={t_pair:.1f}s\n')

        grand = time.time() - grand_t0
        log(f'=== cascade train done ===')
        log(f'  pairs:       {len(pairs)}')
        log(f'  wall total:  {grand:.0f}s')
        log(f'  ended-at-tier histogram:')
        for side, _ in steps:
            log(f'    side {side:>3}: {ended_at_tier[side]:>3}')
        log(f'    never EXACTed:  {ended_at_tier[None]:>3}')
        log(f'  per-tier cumulative train wall:')
        for side, _ in steps:
            log(f'    side {side:>3}: {cumulative_wall[side]:>7.1f}s')
