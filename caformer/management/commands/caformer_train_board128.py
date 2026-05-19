"""Train a single rule for a (prompt, expected) pair on a 128×128 board.

Architecture pivot from the per-position chains: one CA rule, run for
N ticks on the embedded prompt, produces the entire response from a
designated region of the final board.  O(1) in response length.

Usage:
  manage.py caformer_train_board128 --pair-id 25
  manage.py caformer_train_board128 --prompt 'hi' --expected 'hello' --hours 0.1
"""
from __future__ import annotations

import sys
import time

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ('Train a 128×128 single-board CA rule for one (prompt, '
            'expected) pair.')

    def add_arguments(self, parser):
        parser.add_argument('--pair-id',   type=int, default=None)
        parser.add_argument('--prompt',    type=str, default=None)
        parser.add_argument('--expected',  type=str, default=None)
        parser.add_argument('--ticks',     type=int, default=128)
        parser.add_argument('--pop',       type=int, default=8)
        parser.add_argument('--gens-per-burst', type=int, default=8)
        parser.add_argument('--polish',    type=int, default=60)
        parser.add_argument('--mutation',  type=float, default=0.01)
        parser.add_argument('--hours',     type=float, default=0.1,
                              help='wall-clock budget per pair')
        parser.add_argument('--seed',      type=int, default=0xB128A1E)
        parser.add_argument('--save-to',   type=str, default='',
                              help='write the winning rule (16384B) to '
                                     'this path')
        parser.add_argument('--positional', action='store_true',
                              help='Per-position mode: train one rule '
                                     'per byte of the expected response. '
                                     'Each position is an independent '
                                     'single-byte problem (trivially '
                                     'solvable) — combines 128×128 '
                                     'bandwidth with per-position '
                                     'tractability.')
        parser.add_argument('--per-pos-seconds', type=float, default=60.0,
                              help='budget per position when --positional')

    def handle(self, *, pair_id, prompt, expected, ticks, pop,
                 gens_per_burst, polish, mutation, hours, seed, save_to,
                 positional, per_pos_seconds,
                 **opts):
        from caformer.board128 import (train_pair_board128,
                                          train_pair_board128_positional)
        if pair_id:
            from caformer.models import QRPair
            pair = QRPair.objects.filter(pk=pair_id).first()
            if pair is None:
                raise CommandError(f'no QRPair pk={pair_id}')
            prompt   = pair.prompt
            expected = pair.expected
        if not prompt or not expected:
            raise CommandError('need --pair-id OR --prompt + --expected')

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        def _event(kind, payload):
            es = payload.get('elapsed_s', 0)
            if kind == 'init_done':
                log(f'  [{es:6.1f}s] init  best_fit={payload["best_fit"]:+.3f}  '
                    f'bytes={payload["best_bytes"]}/{payload["n_target"]}')
            elif kind == 'burst_begin':
                log(f'  [{es:6.1f}s] burst {payload["burst"]} '
                    f'mask={payload["mask_size"]}/16384 '
                    f'({100*payload["mask_frac"]:.1f}%)')
            elif kind == 'improved':
                log(f'  [{es:6.1f}s]   ↗ ga    fit={payload["best_fit"]:+.3f}  '
                    f'bytes={payload["best_bytes"]}/{payload["n_target"]}')
            elif kind == 'polish_improved':
                log(f'  [{es:6.1f}s]   ↗ polish fit={payload["best_fit"]:+.3f}  '
                    f'bytes={payload["best_bytes"]}/{payload["n_target"]}  '
                    f'({payload["n_improvements"]} imp)')
            elif kind == 'done':
                tag = '✓ EXACT' if payload['exact'] else '(partial)'
                log(f'\n  DONE  {tag}  sampled={payload["sampled"]!r}  '
                    f'target={payload["target"]!r}  '
                    f'bytes={payload["best_bytes"]}/{payload["n_target"]}  '
                    f'({es:.1f}s)')

        log(f'\n=== board128 train ===')
        log(f'  prompt:   {prompt!r}')
        log(f'  expected: {expected!r}')
        if positional:
            log(f'  mode=positional  ticks={ticks}  '
                f'per-pos={per_pos_seconds:.0f}s')
            def _pevent(kind, payload):
                es = payload.get('elapsed_s', 0)
                if kind == 'position_start':
                    log(f'  [{es:6.1f}s] pos {payload["pos"]} '
                        f'target={payload["target_char"]!r}')
                elif kind == 'position_done':
                    mark = '✓' if payload['matched'] else '✗'
                    log(f'  [{es:6.1f}s]   pos {payload["pos"]} {mark}  '
                        f'phase={payload["phase"]}  '
                        f'({payload["pos_wall"]:.1f}s)')
            result = train_pair_board128_positional(
                prompt, expected,
                n_ticks=ticks, per_position_seconds=per_pos_seconds,
                seed=seed, on_event=_pevent)
            n_matched = sum(result['matches'])
            log(f'\n  byte-match:  {n_matched}/{len(result["matches"])}')
            log(f'  exact:       {result["exact"]}')
            log(f'  wall:        {result["wall"]:.1f}s')
            # Persist to QRPair: concat per-position rules into the
            # board128_rules_blob field so the live chat dispatch
            # picks them up immediately.
            if pair_id:
                from caformer.models import QRPair
                pair = QRPair.objects.get(pk=pair_id)
                pair.board128_rules_blob = b''.join(
                    bytes(r) for r in result['rules'])
                pair.board128_exact = bool(result['exact'])
                pair.board128_ticks = int(ticks)
                pair.save(update_fields=['board128_rules_blob',
                                          'board128_exact',
                                          'board128_ticks'])
                log(f'  persisted to QRPair pk={pair.pk}  '
                    f'(board128_exact={pair.board128_exact}, '
                    f'{len(result["rules"])} × 16KB rules)')
            if save_to:
                from pathlib import Path
                p = Path(save_to)
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, 'wb') as fp:
                    for r in result['rules']:
                        fp.write(bytes(r))
                log(f'  saved rules: {p} ({len(result["rules"])} × 16KB)')
            return

        log(f'  ticks={ticks}  pop={pop}  gens/burst={gens_per_burst}  '
            f'polish={polish}  mut={mutation}  budget={hours*3600:.0f}s')
        result = train_pair_board128(
            prompt, expected,
            n_ticks=ticks, pop_size=pop,
            generations_per_burst=gens_per_burst,
            polish_trials=polish, mutation_rate=mutation,
            max_seconds=hours * 3600.0, seed=seed,
            on_event=_event)
        log(f'\n  final byte-match: {result["best_bytes"]}/{result["n_target"]}')
        log(f'  exact:            {result["exact"]}')
        log(f'  wall:             {result["wall"]:.1f}s')
        if save_to:
            from pathlib import Path
            p = Path(save_to)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(bytes(result['rule_table']))
            log(f'  saved rule:       {p}')
