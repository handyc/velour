"""Resume-aware patch trainer for cell8 multires pairs.

Loads an existing pair's cell8_b<SIDE>_rules_blob, validates each
position via forward inference, and retrains ONLY the positions
whose stored rule no longer produces the target byte.  Cheap
recovery for partials — typical pair has 1-2 failing positions
out of N, so we skip the EXACT ones entirely.

Each failing position is retried with multiple seeds at the
configured budget; the first seed that EXACTs wins, otherwise
the original rule stays.

  manage.py caformer_patch_cell8 --pair-id 2 --tier b256
  manage.py caformer_patch_cell8 --pair-ids 2,7,8 --tier b008 \\
      --per-pos-seconds 60 --seed-attempts 3
"""
from __future__ import annotations

import sys
import time

import numpy as np
from django.core.management.base import BaseCommand, CommandError


RULE_BYTES = 65_536

TIER_SIDES = {'b008': 8, 'b016': 16, 'b032': 32, 'b064': 64,
                  'b128': 128, 'b256': 256}


class Command(BaseCommand):
    help = ('Retrain just the failing positions of a cell8 pair at '
            'the named tier.  Reads cell8_bN_rules_blob, validates '
            'per-position, and only redoes positions that miss.')

    def add_arguments(self, parser):
        parser.add_argument('--pair-id',  type=int, default=None)
        parser.add_argument('--pair-ids', type=str, default='')
        parser.add_argument('--tier', type=str, default='b256',
                              choices=list(TIER_SIDES.keys()),
                              help='which cell8 tier to patch')
        parser.add_argument('--per-pos-seconds', type=float, default=180.0)
        parser.add_argument('--seed-attempts', type=int, default=3,
                              help='fresh seeds per failing position')
        parser.add_argument('--base-seed', type=int, default=0xC81E5A8,
                              help='base seed for the patch attempts')
        parser.add_argument('--warm-start-from-stored', action='store_true',
                              help='use the existing-but-wrong stored rule '
                                     'as warm-start (faster than random init '
                                     'when the existing rule is close)')
        parser.add_argument('--port-value', type=int, default=0)

    def handle(self, *, pair_id, pair_ids, tier, per_pos_seconds,
                 seed_attempts, base_seed, warm_start_from_stored,
                 port_value, **opts):
        from caformer.models import QRPair
        from caformer.cell8_multires import (train_position_cell8_at_side,
                                                    forward_byte_cell8_at_side,
                                                    cell8_tier_geometry)
        # b256 lives in board256, not cell8_multires.
        from caformer.board256 import (train_position_board256,
                                                 embed_prompt_256,
                                                 decode_byte_at_position_256,
                                                 DEFAULT_N_TICKS_256,
                                                 BOARD_SIDE_256)
        from caformer.cell8 import hex_ca_step_cell8, broadcast_input

        ids = []
        if pair_ids.strip():
            ids = [int(x) for x in pair_ids.split(',') if x.strip()]
        elif pair_id is not None:
            ids = [pair_id]
        if not ids:
            raise CommandError('provide --pair-id or --pair-ids')

        side = TIER_SIDES[tier]
        field = f'cell8_{tier}_rules_blob'
        exact_field = f'cell8_{tier}_exact'

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        log(f'=== caformer_patch_cell8  tier={tier} (side={side}) ===')
        log(f'  pairs: {ids}\n')

        grand_t0 = time.time()
        grand_recovered = 0
        grand_stillbad  = 0

        for pk in ids:
            pair = QRPair.objects.filter(pk=pk).first()
            if pair is None:
                log(f'  pair pk={pk}: not found'); continue
            blob = getattr(pair, field)
            if not blob or len(bytes(blob)) < RULE_BYTES:
                log(f'  pair pk={pk}: no cell8_{tier} rules stored'); continue
            blob = bytearray(bytes(blob))
            target_bytes = pair.expected.encode('utf-8')
            n_pos = len(blob) // RULE_BYTES
            log(f'-- pair pk={pk} {pair.prompt!r} → {pair.expected!r} ({n_pos} pos) --')

            # Per-position validation.
            n_ticks = side if tier != 'b256' else DEFAULT_N_TICKS_256
            failing = []
            for pos in range(n_pos):
                rule = np.frombuffer(
                    bytes(blob[pos*RULE_BYTES:(pos+1)*RULE_BYTES]),
                    dtype=np.uint8).copy() & 3
                if tier == 'b256':
                    state = embed_prompt_256(pair.prompt)
                    inp = broadcast_input(BOARD_SIDE_256, port_value)
                    for _ in range(n_ticks):
                        state = hex_ca_step_cell8(state, inp, rule)
                    b = decode_byte_at_position_256(state, pos)
                else:
                    b = forward_byte_cell8_at_side(
                        pair.prompt, rule, pos, side,
                        n_ticks=n_ticks, port_value=port_value)
                target = target_bytes[pos] if pos < len(target_bytes) else 0
                ok = (b == target)
                mark = '✓' if ok else '✗'
                log(f'  pos {pos:2d} target=0x{target:02x} stored={mark} '
                    f'produced=0x{b:02x}')
                if not ok:
                    failing.append((pos, target, rule))

            if not failing:
                log(f'  pair pk={pk}: all {n_pos} positions already match — '
                    f'no patch needed')
                continue
            log(f'  patching {len(failing)} failing position(s)...')

            # Retry each failing position.
            pair_recovered = 0
            for pos, target, stored_rule in failing:
                ch = chr(target) if 32 <= target < 127 else f'\\x{target:02x}'
                warm = bytes(stored_rule) if warm_start_from_stored else None
                fixed = None
                for attempt in range(seed_attempts):
                    seed = (base_seed
                            ^ (pk * 19937)
                            ^ (pos * 4099)
                            ^ (attempt * 7919)) & 0xFFFFFFFF
                    t0 = time.time()
                    if tier == 'b256':
                        r = train_position_board256(
                            pair.prompt, target, pos,
                            n_ticks=n_ticks,
                            max_seconds=per_pos_seconds,
                            seed=seed, seed_rule=warm,
                            port_value=port_value)
                    else:
                        r = train_position_cell8_at_side(
                            pair.prompt, target, pos, side,
                            n_ticks=n_ticks,
                            max_seconds=per_pos_seconds,
                            seed=seed, seed_rule=warm,
                            port_value=port_value)
                    wall = time.time() - t0
                    matched = bool(r['byte_match'])
                    mark = '✓' if matched else '✗'
                    log(f'    pos {pos:2d} target={ch!r} attempt {attempt+1}: '
                        f'{mark} {r["phase"]:11s} {wall:.1f}s')
                    if matched:
                        fixed = bytes(r['rule_table'])
                        break
                if fixed is not None:
                    blob[pos*RULE_BYTES:(pos+1)*RULE_BYTES] = fixed
                    pair_recovered += 1
                    grand_recovered += 1
                else:
                    grand_stillbad += 1

            if pair_recovered > 0:
                # Persist the patched blob.
                setattr(pair, field, bytes(blob))
                # Re-validate everything; set exact flag accordingly.
                all_ok = True
                for pos in range(n_pos):
                    rule = np.frombuffer(
                        bytes(blob[pos*RULE_BYTES:(pos+1)*RULE_BYTES]),
                        dtype=np.uint8).copy() & 3
                    target = target_bytes[pos] if pos < len(target_bytes) else 0
                    if tier == 'b256':
                        state = embed_prompt_256(pair.prompt)
                        inp = broadcast_input(BOARD_SIDE_256, port_value)
                        for _ in range(n_ticks):
                            state = hex_ca_step_cell8(state, inp, rule)
                        b = decode_byte_at_position_256(state, pos)
                    else:
                        b = forward_byte_cell8_at_side(
                            pair.prompt, rule, pos, side,
                            n_ticks=n_ticks, port_value=port_value)
                    if b != target:
                        all_ok = False
                        break
                setattr(pair, exact_field, all_ok)
                pair.save(update_fields=[field, exact_field])
                log(f'  pair pk={pk}: recovered {pair_recovered}/{len(failing)}, '
                    f'{exact_field}={all_ok}, saved')
            else:
                log(f'  pair pk={pk}: recovered 0/{len(failing)} — no save')

        log(f'\n=== done in {time.time()-grand_t0:.1f}s ===')
        log(f'  total recovered: {grand_recovered}')
        log(f'  still failing:   {grand_stillbad}')
