"""Reproducible demo: 4 trained 7→1 b256 rules stacked into ONE cell8
LUT, run at all 4 port values to show 4 distinct byte-exact responses
emerging from the same rule.

Loads pickled rules from .artifacts/b256_7to1_rules/pkN_7to1_b256.pkl
(one per pair) that were produced by the train_pair_b256_7to1 trainer
(see caformer/board256.py).  Stacks the per-position rules into one
cell8 LUT per position via compose_cell8_from_quarters.  Runs CA
inference at all 4 ports on each provided prompt.

This is the "personality MoE in one cell8 LUT" demonstration from
the 2026-05-20 session.  Validated empirically that ports 0/1/2 of
a compose([pk2, pk7, pk8, *]) cell8 LUT produce 'hello', 'hey', 'hi'
respectively on prompt 'hi'.

  manage.py caformer_compose_demo
  manage.py caformer_compose_demo --pks 2,7,8,13 --prompts hi,HI
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ('Compose 4 trained 7→1 b256 rules into one cell8 LUT and '
            'run all 4 port values to demonstrate personality switching.')

    def add_arguments(self, parser):
        parser.add_argument('--pks', type=str, default='2,7,8,13',
                              help='4 QRPair pks whose b256 7→1 rules are '
                                     'in .artifacts/b256_7to1_rules/')
        parser.add_argument('--prompts', type=str, default='hi,HI',
                              help='comma-separated prompts to run')
        parser.add_argument('--rules-dir', type=str,
                              default='.artifacts/b256_7to1_rules')

    def handle(self, *, pks, prompts, rules_dir, **opts):
        from caformer.board256 import (compose_cell8_from_quarters,
                                              embed_prompt_256,
                                              decode_byte_at_position_256,
                                              BOARD_SIDE_256,
                                              DEFAULT_N_TICKS_256)
        from caformer.cell8 import hex_ca_step_cell8, broadcast_input
        from caformer.models import QRPair

        pk_list = [int(x) for x in pks.split(',') if x.strip()]
        if len(pk_list) != 4:
            raise CommandError(f'need exactly 4 pks, got {pk_list}')

        rules_dir_p = Path(rules_dir)
        pair_data = {}
        for pk in pk_list:
            pkl_path = rules_dir_p / f'pk{pk}_7to1_b256.pkl'
            if not pkl_path.exists():
                raise CommandError(
                    f'missing {pkl_path}; train it first via '
                    f'caformer.board256.train_pair_b256_7to1 and save')
            with open(pkl_path, 'rb') as f:
                d = pickle.load(f)
            # Backfill metadata from DB if pkl is missing it.
            db_pair = QRPair.objects.filter(pk=pk).first()
            d.setdefault('prompt', db_pair.prompt if db_pair else '?')
            d.setdefault('expected', db_pair.expected if db_pair else '?')
            pair_data[pk] = d

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        log(f'=== caformer_compose_demo ===')
        log(f'  pks:     {pk_list}')
        log(f'  prompts: {prompts}\n')
        for pk in pk_list:
            d = pair_data[pk]
            log(f'  pk={pk}: {d["prompt"]!r} → {d["expected"]!r}  '
                f'({len(d["rules"])} positions)')

        n_max = max(len(pair_data[pk]['rules']) for pk in pk_list)
        log(f'\n  composing {n_max} cell8 LUTs (one per output position)...')

        composed_per_pos = []
        for pos in range(n_max):
            quarters = []
            for pk in pk_list:
                rules = pair_data[pk]['rules']
                quarters.append(rules[pos] if pos < len(rules)
                                  else rules[-1])
            composed_per_pos.append(compose_cell8_from_quarters(quarters))

        prompt_list = [p.strip() for p in prompts.split(',') if p.strip()]
        for prompt in prompt_list:
            log(f'\n==== prompt={prompt!r} ====')
            for port in range(4):
                target_pk = pk_list[port]
                tp = pair_data[target_pk]
                out = bytearray()
                for pos in range(n_max):
                    state = embed_prompt_256(prompt)
                    inp = broadcast_input(BOARD_SIDE_256, port)
                    for _ in range(DEFAULT_N_TICKS_256):
                        state = hex_ca_step_cell8(state, inp,
                                                          composed_per_pos[pos])
                    out.append(decode_byte_at_position_256(state, pos))
                try:
                    text = bytes(out).decode('utf-8', errors='replace')
                except UnicodeDecodeError:
                    text = repr(bytes(out))
                target_text = tp['expected']
                text_trim = text[:len(target_text)]
                match = text_trim == target_text
                mark = '✓ match' if match else f'≠ {target_text!r}'
                log(f'  port={port} (pk={target_pk} '
                    f'{tp["prompt"]!r}→{target_text!r}):  '
                    f'produced={text!r}  trimmed={text_trim!r}  {mark}')

        log(f'\n  → personality switching via port value works when prompt '
            f'matches what the quarter was trained for.')
