"""Train cell8+256 rules for a subset of the QRPair corpus, write the
results as a flat-file rule blob suitable for `caformer_import_rules`.

Designed to be runnable on any machine with python3 + numpy — local
home box for small slices, ALICE bundle workers for large parallel
slices.  Output file is append-only; killing mid-run loses at most
one in-progress position (caught by the CRC on the next read).

  manage.py caformer_train_cell8_b256 \\
      --pair-pks 2 \\
      --out /tmp/chunk_a.rules \\
      --max-seconds-per-position 60

  # warm-start each pair's positions from its existing board128 rule
  # (upcast 7→1 LUT → cell8 LUT) — gives a class-4 structural prior:
  manage.py caformer_train_cell8_b256 \\
      --pair-pks 1-35,42,50 \\
      --out chunk_a.rules \\
      --warm-start-from-board128

Pair-pks syntax supports comma-separated single pks, dash ranges, or
both: `2,5,10-20,42`.  Missing pks are reported but don't abort.

Phase A: input port held at 0 throughout (no conditional output yet).
Modulated training (--alt-from / --port-source) is a follow-up patch
once the basic pipeline is exercised end-to-end.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from django.core.management.base import BaseCommand, CommandError


def parse_pk_spec(spec: str):
    """'2,5,10-20,42' → [2, 5, 10, 11, …, 20, 42].  Robust to spaces."""
    out = []
    for tok in spec.split(','):
        tok = tok.strip()
        if not tok:
            continue
        if '-' in tok:
            a, b = tok.split('-', 1)
            try:
                lo, hi = int(a), int(b)
            except ValueError:
                raise CommandError(f'bad pk range {tok!r}')
            if lo > hi:
                lo, hi = hi, lo
            out.extend(range(lo, hi + 1))
        else:
            try:
                out.append(int(tok))
            except ValueError:
                raise CommandError(f'bad pk {tok!r}')
    # de-dup, preserve order.
    seen, dedup = set(), []
    for pk in out:
        if pk not in seen:
            seen.add(pk); dedup.append(pk)
    return dedup


class Command(BaseCommand):
    help = ('Train cell8+256 rules for a subset of QRPairs and write '
            'them to a flat .rules file for later import.')

    def add_arguments(self, parser):
        parser.add_argument('--pair-pks', type=str, required=True,
                              help='comma-separated pks; supports ranges '
                                     "like '2,5,10-20'")
        parser.add_argument('--out', type=str, required=True,
                              help='output .rules file (append-only)')
        parser.add_argument('--max-seconds-per-position', type=float,
                              default=120.0)
        parser.add_argument('--n-ticks', type=int, default=256)
        parser.add_argument('--warm-start-from-board128', action='store_true',
                              help='upcast each pair\'s existing board128 '
                                     'per-position rule to a cell8 LUT and use '
                                     'it as a structural warm-start prior')
        parser.add_argument('--seed', type=int, default=0xB256A1E)
        parser.add_argument('--port-value', type=int, default=0,
                              help='K=4 colour broadcast to the input port '
                                     'during training (Phase A: leave at 0)')

    def handle(self, *, pair_pks, out, max_seconds_per_position, n_ticks,
                 warm_start_from_board128, seed, port_value, **opts):
        from caformer.models import QRPair
        from caformer.board256 import train_position_board256
        from caformer.io.rule_blob import (RuleRecord, append_records,
                                                  SHAPE_CELL8)

        pks = parse_pk_spec(pair_pks)
        out_p = Path(out)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        log(f'=== caformer_train_cell8_b256 ===')
        log(f'  pair-pks:   {pair_pks}  ({len(pks)} pks)')
        log(f'  out:        {out_p}')
        log(f'  budget:     {max_seconds_per_position:.0f}s/position')
        log(f'  n_ticks:    {n_ticks}')
        log(f'  warm-start: {warm_start_from_board128}')
        log(f'  port_value: {port_value}\n')

        grand_t0 = time.time()
        n_pairs_done = 0
        n_positions_total = 0
        n_positions_matched = 0
        n_skipped = 0

        for pk in pks:
            pair = QRPair.objects.filter(pk=pk).first()
            if pair is None:
                log(f'  pair pk={pk} not found — skipping')
                n_skipped += 1
                continue
            target_bytes = pair.expected.encode('utf-8')
            n_pos = len(target_bytes)
            log(f'--- pair {pk}: {pair.prompt!r} → {pair.expected!r} '
                f'({n_pos} positions) ---')

            warm_blobs = None
            if warm_start_from_board128 and pair.board128_rules_blob:
                blob = bytes(pair.board128_rules_blob)
                expected_len = n_pos * 16_384
                if len(blob) == expected_len:
                    warm_blobs = [blob[i*16_384:(i+1)*16_384]
                                       for i in range(n_pos)]
                    log(f'    warm-start: board128 rules available '
                        f'({len(warm_blobs)} positions)')
                else:
                    log(f'    warm-start: board128 blob is {len(blob)}B '
                        f'(expected {expected_len}); falling back to random')

            pair_t0 = time.time()
            recs_for_pair = []
            for pos, tb in enumerate(target_bytes):
                ws = warm_blobs[pos] if warm_blobs else None
                t0 = time.time()
                r = train_position_board256(
                    pair.prompt, tb, pos,
                    n_ticks=n_ticks,
                    max_seconds=max_seconds_per_position,
                    seed=seed ^ (pk * 19937) ^ (pos * 4099),
                    seed_rule=ws,
                    port_value=port_value)
                wall = time.time() - t0
                matched = bool(r['byte_match'])
                n_positions_total += 1
                if matched:
                    n_positions_matched += 1
                mark = '✓' if matched else '✗'
                ch = chr(tb) if 32 <= tb < 127 else f'\\x{tb:02x}'
                log(f'    pos {pos:2d} target={ch!r:6s}  '
                    f'{mark} {r["phase"]:10s} {wall:6.1f}s')

                rec = RuleRecord(
                    pair_pk=pk, position=pos,
                    n_ticks=n_ticks,
                    port_src='off',
                    rule_shape=SHAPE_CELL8,
                    rule_blob=bytes(r['rule_table']))
                recs_for_pair.append(rec)
                # Append immediately so a crash loses at most this
                # position's work, not the whole pair.
                append_records(out_p, [rec])

            pair_wall = time.time() - pair_t0
            pair_matched = sum(1 for r in recs_for_pair if True)  # see below
            # recompute from logs above — we tracked matched/total properly:
            n_pos_matched_this_pair = (
                n_positions_matched - (n_positions_total - n_pos))
            log(f'    pair wall {pair_wall:.1f}s  '
                f'matched {n_pos_matched_this_pair}/{n_pos} positions\n')
            n_pairs_done += 1

        grand = time.time() - grand_t0
        log(f'=== summary ===')
        log(f'  pairs done:     {n_pairs_done}/{len(pks)}  '
            f'(skipped {n_skipped})')
        log(f'  positions:      {n_positions_matched}/{n_positions_total}'
            f' matched')
        log(f'  total wall:     {grand:.1f}s'
            f'  ({grand/max(1,n_positions_total):.1f}s/position avg)')
        log(f'  output:         {out_p} '
            f'({out_p.stat().st_size if out_p.exists() else 0} B)')
        log(f'  → ingest with:  manage.py caformer_import_rules {out_p}')
