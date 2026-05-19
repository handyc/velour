"""cell8 Phase 1: DMN heartbeat → input port modulation MVP.

Trains a single 8→1 rule per output byte such that the *same* prompt
produces *two different responses* depending on the value broadcast
into the cell8 input port:

  - port = 0  →  expected_base response
  - port = 1  →  expected_alt  response

This is the concrete demonstration that the cell8 input port can
carry useful signal — once integrated, the DMN heartbeat parity bit
becomes a per-tick modulator on the caformer's response.

Usage:
  manage.py caformer_cell8_phase1 --prompt 'hi' \
                                   --base 'hello' --alt 'world' \
                                   --per-pos-seconds 90
  manage.py caformer_cell8_phase1 --pair-id 2 \
                                   --alt 'world' --per-pos-seconds 90

When --pair-id is supplied, the base response is the pair's expected
field.  --alt is always required.
"""
from __future__ import annotations

import sys
import time

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ('Train an 8→1 rule per response byte where the cell8 input '
            'port broadcasts 0 → base response, 1 → alt response.  '
            'The Phase 1 demo of cell8 integration.')

    def add_arguments(self, parser):
        parser.add_argument('--pair-id', type=int, default=None)
        parser.add_argument('--prompt',  type=str, default=None)
        parser.add_argument('--base',    type=str, default=None,
                              help='response when port=0 (or use --pair-id\'s expected)')
        parser.add_argument('--alt',     type=str, required=True,
                              help='response when port=1')
        parser.add_argument('--ticks',   type=int, default=128)
        parser.add_argument('--per-pos-seconds', type=float, default=120.0)
        parser.add_argument('--positions', type=str, default='',
                              help='comma-separated position indices; '
                                     'default = train all positions of the pair')
        parser.add_argument('--seed',    type=int, default=0xCE118A1E)
        parser.add_argument('--warm-start-pair-id', type=int, default=None,
                              help='copy this pair\'s board128 rule into the '
                                     'port=0 quarter of every cell8 LUT, then '
                                     'only evolve the port=1 quarter')
        parser.add_argument('--freeze-port0', action='store_true',
                              help='restrict mutations to the port=1 quarter')

    def handle(self, *, pair_id, prompt, base, alt, ticks,
                 per_pos_seconds, positions, seed,
                 warm_start_pair_id, freeze_port0, **opts):
        from caformer.cell8_trainer import (train_pair_cell8_modulated,
                                                   train_position_cell8_modulated)
        from caformer.multires import split_blob

        # Resolve prompt + base from pair_id when given.
        if pair_id is not None:
            from caformer.models import QRPair
            try:
                pair = QRPair.objects.get(pk=pair_id)
            except QRPair.DoesNotExist:
                raise CommandError(f'pair {pair_id} not found')
            prompt = prompt or pair.prompt
            base   = base   or pair.expected
        if not prompt or not base:
            raise CommandError('need --prompt + --base, or --pair-id')

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        # Load warm-start rules if requested.
        warm_rules = None
        if warm_start_pair_id is not None:
            from caformer.models import QRPair
            wp = QRPair.objects.get(pk=warm_start_pair_id)
            warm_rules = split_blob(bytes(wp.board128_rules_blob or b''), 128)
            if not warm_rules:
                raise CommandError(
                    f'warm-start pair {warm_start_pair_id} has no board128 blob')

        log(f'=== cell8 phase 1: DMN-modulated rule training ===')
        log(f'  prompt:        {prompt!r}')
        log(f'  base (port=0): {base!r}')
        log(f'  alt  (port=1): {alt!r}')
        log(f'  ticks:         {ticks}')
        log(f'  per-pos sec:   {per_pos_seconds}')
        log(f'  warm-start:    {f"pair {warm_start_pair_id} ({len(warm_rules)} rules)" if warm_rules else "none"}')
        log(f'  freeze port0:  {freeze_port0}')

        # Subset training (one or a few positions) vs whole pair.
        if positions.strip():
            pos_list = [int(x) for x in positions.split(',') if x.strip()]
            base_bytes = base.encode('utf-8')
            alt_bytes  = alt.encode('utf-8')
            n = max(len(base_bytes), len(alt_bytes))
            base_bytes = base_bytes.ljust(n, b'\x00')
            alt_bytes  = alt_bytes.ljust(n, b'\x00')
            log(f'  positions:     {pos_list} of {n}')
            results = []
            for pos in pos_list:
                t0 = time.time()
                tb = base_bytes[pos]
                ta = alt_bytes[pos]
                log(f'\n--- pos {pos}: base={chr(tb) if 32 <= tb < 127 else f"\\x{tb:02x}"!r}'
                    f' / alt={chr(ta) if 32 <= ta < 127 else f"\\x{ta:02x}"!r} ---')
                wsb = None
                if warm_rules and pos < len(warm_rules):
                    wsb = warm_rules[pos]
                r = train_position_cell8_modulated(
                    prompt, tb, ta, pos,
                    n_ticks=ticks,
                    max_seconds=per_pos_seconds,
                    warm_start_base=wsb,
                    freeze_port0=freeze_port0,
                    seed=seed ^ (pos * 4099))
                wall = time.time() - t0
                m_b, m_a = r['matches']
                log(f'  result: base={"✓" if m_b else "✗"} '
                    f'alt={"✓" if m_a else "✗"} '
                    f'phase={r["phase"]} ({wall:.1f}s)')
                results.append((pos, m_b, m_a, wall))
            n_both = sum(1 for _, b, a, _ in results if b and a)
            log(f'\nsummary: {n_both}/{len(results)} positions matched BOTH targets')
            return

        # Whole-pair training.
        log(f'  mode: full pair training')
        def _evt(kind, payload):
            es = payload.get('elapsed_s', 0)
            if kind == 'position_start':
                tb = payload['target_base']
                ta = payload['target_alt']
                cb = chr(tb) if 32 <= tb < 127 else f'\\x{tb:02x}'
                ca = chr(ta) if 32 <= ta < 127 else f'\\x{ta:02x}'
                log(f'  [{es:6.1f}s] pos {payload["pos"]} '
                    f'base={cb!r} alt={ca!r}')
            elif kind == 'position_done':
                m_b, m_a = payload['matches']
                marks = ('✓' if m_b else '✗', '✓' if m_a else '✗')
                log(f'  [{es:6.1f}s]   pos {payload["pos"]} '
                    f'base={marks[0]} alt={marks[1]}  '
                    f'phase={payload["phase"]}  '
                    f'({payload["pos_wall"]:.1f}s)')
        result = train_pair_cell8_modulated(
            prompt, base, alt,
            n_ticks=ticks,
            per_position_seconds=per_pos_seconds,
            warm_start_rules=warm_rules,
            freeze_port0=freeze_port0,
            seed=seed, on_event=_evt)
        n_pos = len(result['matches_base'])
        n_both = sum(1 for b, a in zip(result['matches_base'], result['matches_alt'])
                       if b and a)
        log(f'\n=== done ===')
        log(f'  positions:     {n_pos}')
        log(f'  both-target:   {n_both}/{n_pos}')
        log(f'  base exact:    {result["exact_base"]}')
        log(f'  alt  exact:    {result["exact_alt"]}')
        log(f'  wall:          {result["wall"]:.0f}s')
