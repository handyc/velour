"""Resume-aware patch trainer for board128 positional pairs.

Loads an existing pair's board128_rules_blob, validates each position,
and retrains ONLY the positions whose stored rule no longer produces
the right byte.  Cheap recovery for partials — most pairs have just
1-2 failing positions out of N, so we skip retraining the EXACT ones
entirely.

Each failing position is retried with multiple seeds at a configurable
per-position budget; the first seed that EXACTs wins.  If no seed
works within the budget the position's rule is left untouched so the
blob stays consistent with whatever the previous trainer produced.

Usage:
  manage.py caformer_patch_board128 --pair-id 9 --per-pos-seconds 240
  manage.py caformer_patch_board128 --pair-ids 9,11,17,38,43,45,46,49,53,61,14
"""
from __future__ import annotations

import sys
import time

import numpy as np
from django.core.management.base import BaseCommand, CommandError


RULE_BYTES = 16384


class Command(BaseCommand):
    help = ('Retrain just the failing positions of a board128 pair.  '
            'Reads board128_rules_blob from the QRPair, validates per-'
            'position, and only redoes positions that miss.')

    def add_arguments(self, parser):
        parser.add_argument('--pair-id',  type=int, default=None)
        parser.add_argument('--pair-ids', type=str, default='',
                              help='comma-separated pair IDs (overrides --pair-id)')
        parser.add_argument('--ticks',    type=int, default=128)
        parser.add_argument('--per-pos-seconds', type=float, default=240.0,
                              help='per-position budget per seed attempt')
        parser.add_argument('--seed-attempts', type=int, default=3,
                              help='how many fresh seeds to try per failing position')
        parser.add_argument('--base-seed', type=int, default=0xB128A1E,
                              help='base seed; per-attempt seed is base ^ pos*4099 ^ attempt*7919')

    def handle(self, *, pair_id, pair_ids, ticks, per_pos_seconds,
                 seed_attempts, base_seed, **opts):
        from caformer.models import QRPair
        from caformer.board128 import (RESPONSE_BYTES_MAX,
                                              decode_byte_at_position,
                                              embed_prompt, hex_ca_step,
                                              train_position_board128)

        ids = []
        if pair_ids.strip():
            ids = [int(x) for x in pair_ids.split(',') if x.strip()]
        elif pair_id is not None:
            ids = [pair_id]
        else:
            raise CommandError('need --pair-id or --pair-ids')

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        def _validate(prompt, rule, position, target_byte):
            state = embed_prompt(prompt)
            for _ in range(ticks):
                state = hex_ca_step(state, rule)
            return decode_byte_at_position(state, position) == target_byte

        grand_t0 = time.time()
        total_fixed = 0
        total_residual = 0
        for pid in ids:
            t0 = time.time()
            try:
                pair = QRPair.objects.get(pk=pid)
            except QRPair.DoesNotExist:
                log(f'\n--- pair {pid}: NOT FOUND ---')
                continue
            blob = pair.board128_rules_blob or b''
            if len(blob) < RULE_BYTES:
                log(f'\n--- pair {pid}: no board128 blob, skipping ---')
                continue
            n_rules = len(blob) // RULE_BYTES
            target_bytes = pair.expected.encode('utf-8')[:RESPONSE_BYTES_MAX]
            if n_rules != len(target_bytes):
                log(f'\n--- pair {pid}: rule count {n_rules} != target len '
                    f'{len(target_bytes)}, skipping ---')
                continue

            # Slice blob into per-position rules.
            rules = [np.frombuffer(blob[i * RULE_BYTES:(i + 1) * RULE_BYTES],
                                          dtype=np.uint8).copy()
                       for i in range(n_rules)]

            # Validate each position.
            misses = []
            for pos, tb in enumerate(target_bytes):
                if not _validate(pair.prompt, rules[pos], pos, tb):
                    misses.append(pos)

            log(f'\n=== pair {pid} ({n_rules} positions, '
                f'{len(misses)} miss) ===')
            log(f'  prompt:   {pair.prompt!r}')
            log(f'  expected: {pair.expected!r}')
            if not misses:
                log(f'  already EXACT — nothing to patch')
                continue
            log(f'  miss positions: {misses}')
            log(f'  targets:        {[chr(target_bytes[p]) if 32 <= target_bytes[p] < 127 else f"\\x{target_bytes[p]:02x}" for p in misses]}')

            # Retrain failing positions.
            fixed_here = 0
            for pos in misses:
                tb = target_bytes[pos]
                target_char = (chr(tb) if 32 <= tb < 127
                                  else f'\\x{tb:02x}')
                matched = False
                for attempt in range(seed_attempts):
                    seed = base_seed ^ (pos * 4099) ^ (attempt * 7919)
                    t_pos = time.time()
                    result = train_position_board128(
                        pair.prompt, tb, pos,
                        n_ticks=ticks,
                        max_seconds=per_pos_seconds,
                        seed=seed)
                    wall = time.time() - t_pos
                    if result['byte_match']:
                        rules[pos] = result['rule_table'].astype(np.uint8)
                        matched = True
                        log(f'  pos {pos} target={target_char!r} ✓ '
                            f'attempt {attempt + 1}/{seed_attempts} '
                            f'({wall:.1f}s, phase={result["phase"]})')
                        fixed_here += 1
                        break
                    else:
                        log(f'  pos {pos} target={target_char!r} ✗ '
                            f'attempt {attempt + 1}/{seed_attempts} '
                            f'({wall:.1f}s, phase={result["phase"]})')
                if not matched:
                    log(f'  pos {pos} target={target_char!r} STILL FAILING after '
                        f'{seed_attempts} attempts')

            # Re-validate every position before saving (we only touched
            # the misses but check all so we know the post-patch truth).
            re_misses = []
            for pos, tb in enumerate(target_bytes):
                if not _validate(pair.prompt, rules[pos], pos, tb):
                    re_misses.append(pos)
            exact_now = (len(re_misses) == 0)

            # Persist.
            new_blob = b''.join(bytes(r) for r in rules)
            pair.board128_rules_blob = new_blob
            pair.board128_exact = exact_now
            pair.board128_ticks = int(ticks)
            pair.save(update_fields=['board128_rules_blob',
                                          'board128_exact',
                                          'board128_ticks'])
            wall = time.time() - t0
            total_fixed += fixed_here
            total_residual += len(re_misses)
            log(f'  fixed {fixed_here}/{len(misses)} positions in {wall:.0f}s')
            log(f'  pair {pid} now: EXACT={exact_now}  remaining miss={re_misses}')

        grand = time.time() - grand_t0
        log(f'\n=== patch run done ===')
        log(f'  pairs:           {len(ids)}')
        log(f'  positions fixed: {total_fixed}')
        log(f'  still failing:   {total_residual}')
        log(f'  wall:            {grand:.0f}s')
