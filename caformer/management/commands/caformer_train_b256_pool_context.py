"""Train a cell8+256 rule that produces a target byte invariant to
which class-4 LUT is painted into the board's context region.

Phase 2 of the pool-as-context architecture.  Validates the
substrate: can the GA find a cell8 rule whose output at a target
position is the SAME byte regardless of what class-4 prior is
seeded into 16,384 cells of the initial board state?

  manage.py caformer_train_b256_pool_context \\
      --pair-pk 2 --position 0 \\
      --pool-dir .artifacts/loupe_rules --pool-k 2 \\
      --max-seconds 600 \\
      --warm-start-from-board128

If the GA succeeds, the saved rule plus N untrained class-4 LUTs
will all produce the same target byte at the target position
(verified by the report at the end).  If it plateaus, we learn
that K=2 is too many constraints to satisfy at once and back off
to per-context training.

Phase 3 (training rules where DIFFERENT pool members produce
DIFFERENT bytes) is the next step after this validates.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ('Train a cell8+256 rule to be context-invariant across '
            'K class-4 priors painted into the board init state.')

    def add_arguments(self, parser):
        parser.add_argument('--pair-pk', type=int, required=True)
        parser.add_argument('--position', type=int, default=0,
                              help='which response byte position to target')
        parser.add_argument('--pool-dir', type=str,
                              default='.artifacts/loupe_rules',
                              help='directory of .lut class-4 candidates')
        parser.add_argument('--pool-k', type=int, default=2,
                              help='how many pool members to train on '
                                     'simultaneously (cost scales linearly)')
        parser.add_argument('--max-seconds', type=float, default=600.0)
        parser.add_argument('--n-ticks', type=int, default=256)
        parser.add_argument('--warm-start-from-board128', action='store_true')
        parser.add_argument('--seed', type=int, default=0xC02E7E47)
        parser.add_argument('--out', type=str, default='',
                              help='if set, append the trained rule to this '
                                     '.rules file')
        parser.add_argument('--verify-extra', type=int, default=8,
                              help='at the end, verify against N additional '
                                     'pool members the rule was NOT trained on '
                                     '(generalization test)')

    def handle(self, *, pair_pk, position, pool_dir, pool_k, max_seconds,
                 n_ticks, warm_start_from_board128, seed, out, verify_extra,
                 **opts):
        from caformer.models import QRPair
        from caformer.board256 import (train_position_b256_pool_context,
                                              forward_byte_with_context,
                                              CONTEXT_LEN_256)
        from caformer.io.rule_blob import (RuleRecord, append_records,
                                                   SHAPE_CELL8)

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        pair = QRPair.objects.filter(pk=pair_pk).first()
        if pair is None:
            raise CommandError(f'pair pk={pair_pk} not found')
        tgt_bytes = pair.expected.encode('utf-8')
        if position >= len(tgt_bytes):
            raise CommandError(
                f'position {position} out of range for pair (expected '
                f'len={len(tgt_bytes)})')
        target_byte = tgt_bytes[position]
        ch = chr(target_byte) if 32 <= target_byte < 127 else f'\\x{target_byte:02x}'

        # Load pool.
        pool_p = Path(pool_dir)
        if not pool_p.is_dir():
            raise CommandError(f'pool dir not found: {pool_dir}')
        all_luts = sorted(pool_p.glob('*.lut'))
        if len(all_luts) < pool_k + verify_extra:
            raise CommandError(
                f'pool has {len(all_luts)} .lut files; need at least '
                f'{pool_k + verify_extra} for train + verify')

        train_pool = []
        for p in all_luts[:pool_k]:
            blob = p.read_bytes()
            if len(blob) < CONTEXT_LEN_256:
                log(f'  skip {p.name}: {len(blob)}B < {CONTEXT_LEN_256}')
                continue
            train_pool.append((p.name, blob))
        verify_pool = []
        for p in all_luts[pool_k:pool_k + verify_extra]:
            blob = p.read_bytes()
            if len(blob) < CONTEXT_LEN_256:
                continue
            verify_pool.append((p.name, blob))

        log(f'=== caformer_train_b256_pool_context ===')
        log(f'  pair {pair_pk}: {pair.prompt!r} → {pair.expected!r}')
        log(f'  position {position}, target byte {target_byte} ({ch!r})')
        log(f'  train pool: {len(train_pool)} class-4 LUTs')
        for n, _ in train_pool:
            log(f'    + {n}')
        log(f'  verify pool: {len(verify_pool)} held-out LUTs')
        log(f'  budget: {max_seconds:.0f}s  n_ticks={n_ticks}')
        log(f'  warm-start: {warm_start_from_board128}\n')

        warm = None
        if warm_start_from_board128 and pair.board128_rules_blob:
            blob = bytes(pair.board128_rules_blob)
            expected_len = len(tgt_bytes) * 16_384
            if len(blob) == expected_len:
                warm = blob[position*16384:(position+1)*16384]
                log(f'  warm-start: position {position}\'s board128 rule '
                    f'({len(warm)}B)\n')

        def on_event(k, p):
            keep = ('init', 'improved')
            if k in keep:
                el = p.get('elapsed_s', 0)
                bf = p.get('best_fit', '?')
                m  = p.get('matched', '?')
                mc = p.get('miss_ctx', '?')
                log(f'  [{el:6.1f}s] {k:10s} fit={bf}  matched_all={m}  miss_ctx={mc}')

        t0 = time.time()
        r = train_position_b256_pool_context(
            pair.prompt, target_byte, position,
            context_pool=[blob for _, blob in train_pool],
            n_ticks=n_ticks,
            max_seconds=max_seconds,
            seed_rule=warm,
            seed=seed)
        wall = time.time() - t0
        log(f'\n=== training result ({wall:.1f}s) ===')
        log(f'  matched all training contexts: {r["byte_match_all"]}')
        log(f'  phase: {r["phase"]}')

        rule = r['rule_table']

        # Verify on training pool.
        log(f'\n=== verify on training pool ===')
        train_ok = 0
        for name, blob in train_pool:
            b = forward_byte_with_context(pair.prompt, rule, blob, position,
                                                  n_ticks=n_ticks)
            tag = '✓' if b == target_byte else '✗'
            log(f'  {tag} {name:60s} → byte {b} '
                f'({chr(b) if 32<=b<127 else f"\\x{b:02x}"!r})')
            if b == target_byte:
                train_ok += 1
        log(f'  {train_ok}/{len(train_pool)} training contexts matched\n')

        # Verify on held-out pool.
        log(f'=== verify on held-out pool (generalization) ===')
        verify_ok = 0
        verify_byte_dist = {}
        for name, blob in verify_pool:
            b = forward_byte_with_context(pair.prompt, rule, blob, position,
                                                  n_ticks=n_ticks)
            verify_byte_dist[b] = verify_byte_dist.get(b, 0) + 1
            tag = '✓' if b == target_byte else '✗'
            log(f'  {tag} {name:60s} → byte {b} '
                f'({chr(b) if 32<=b<127 else f"\\x{b:02x}"!r})')
            if b == target_byte:
                verify_ok += 1
        log(f'  {verify_ok}/{len(verify_pool)} held-out contexts matched')
        log(f'  byte distribution on held-out: {dict(sorted(verify_byte_dist.items()))}')

        # Optional save.
        if out:
            out_p = Path(out)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            rec = RuleRecord(
                pair_pk=pair_pk, position=position,
                n_ticks=n_ticks,
                port_src='pool_context' if False else 'off',
                rule_shape=SHAPE_CELL8,
                rule_blob=bytes(rule))
            # port_src enum doesn't have 'pool_context' yet — leave at 'off'
            # for now; the context-injection is via initial state, not port.
            append_records(out_p, [rec])
            log(f'\n  appended rule to {out_p} ({out_p.stat().st_size} B)')
