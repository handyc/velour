"""Round-trip + behaviour-preservation tests for caformer.multires.

For a chosen EXACT pair, downscale each of its board128 rules through
the resolution ladder (64, 32, 16, 8), upscale back to 128, and
measure:

  (a) LUT byte fidelity     — how many of the 16,384 entries survive
      the round trip identical?
  (b) Behaviour preservation — does running the upscaled rule on the
      original prompt still produce the right byte at the response
      position?

Usage:
  manage.py caformer_multires_test --pair-id 2 --positions 0,1,2
"""
from __future__ import annotations

import sys
import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Round-trip downscale/upscale a pair\'s board128 rules and '
            'report fidelity + behaviour preservation per tier.')

    def add_arguments(self, parser):
        parser.add_argument('--pair-id',   type=int, required=True)
        parser.add_argument('--positions', type=str, default='',
                              help='comma-separated position indices; '
                                     'default = all')
        parser.add_argument('--tiers',     type=str, default='64,32,16,8',
                              help='comma-separated via_side values to try')

    def handle(self, *, pair_id, positions, tiers, **opts):
        import numpy as np
        from caformer.board128 import (decode_byte_at_position,
                                              embed_prompt, hex_ca_step,
                                              RESPONSE_BYTES_MAX)
        from caformer.models import QRPair
        from caformer.multires import (downscale_rule,
                                              inflate_for_full_board,
                                              round_trip, split_blob)

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        try:
            pair = QRPair.objects.get(pk=pair_id)
        except QRPair.DoesNotExist:
            log(f'pair {pair_id} not found')
            return
        blob = pair.board128_rules_blob or b''
        if not blob:
            log(f'pair {pair_id} has no board128 blob')
            return
        rules = split_blob(blob, 128)
        n_rules = len(rules)
        target_bytes = pair.expected.encode('utf-8')[:RESPONSE_BYTES_MAX]
        if positions.strip():
            pos_list = [int(x) for x in positions.split(',') if x.strip()]
        else:
            pos_list = list(range(n_rules))
        tier_list = [int(x) for x in tiers.split(',') if x.strip()]

        log(f'=== multires round-trip on pair {pair.pk} ({pair.prompt!r}) ===')
        log(f'  expected:    {pair.expected!r}')
        log(f'  n_rules:     {n_rules}')
        log(f'  positions:   {pos_list}')
        log(f'  tiers:       {tier_list}')
        log(f'  board128_exact: {pair.board128_exact}')

        # Per-tier LUT-byte fidelity averaged over positions.
        log(f'\n--- LUT-byte round-trip fidelity (lower tier = more compression) ---')
        log(f'  tier   compr  cells_match  fidelity')
        for tier in tier_list:
            fidelities = []
            for pos in pos_list:
                rt = round_trip(rules[pos], 128, tier)
                fidelities.append(rt['fidelity'])
            mean_fid = sum(fidelities) / len(fidelities)
            log(f'  {tier:>4}   {16384 // (tier*tier):>3}×   '
                f'mean {sum(int(f * 16384) for f in fidelities) // len(fidelities):>5}/16384   '
                f'{mean_fid:6.3f}')

        # Behaviour preservation: run the inflated-from-tier rule on
        # the prompt; check the byte at each tested position.
        log(f'\n--- behaviour preservation (does the inflated rule still hit the target byte?) ---')
        log(f'  tier   bytes_match  fraction')
        for tier in tier_list:
            hits = 0
            for pos in pos_list:
                tb = target_bytes[pos]
                small = downscale_rule(rules[pos], 128, tier)
                infl  = inflate_for_full_board(small, tier)
                state = embed_prompt(pair.prompt)
                for _ in range(int(pair.board128_ticks or 128)):
                    state = hex_ca_step(state, infl)
                produced = decode_byte_at_position(state, pos)
                if produced == tb:
                    hits += 1
            log(f'  {tier:>4}   {hits:>3}/{len(pos_list):>3}        '
                f'{hits/len(pos_list):.3f}')

        # Storage cost summary at each tier.
        log(f'\n--- storage cost per pair (N positions × tier bytes) ---')
        for tier in [128] + tier_list:
            per_rule = tier * tier
            per_pair = per_rule * n_rules
            log(f'  tier {tier:>3}: {per_rule:>5} B/rule  '
                f'{per_pair:>7} B/pair  '
                f'({per_pair / (16384 * n_rules) * 100:5.2f} % of baseline)')
