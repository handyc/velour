"""A/B benchmark: per-position trainer with random init vs warm-started
from mandelhunt LUTs.

For each (prompt, target_byte, position) task, runs train_position_
board128 twice:

  A) random init      — current default
  B) mandelhunt warm  — half the initial pop = perturbations of a
                        loaded mandelhunt LUT, half random

Reports wall-time-to-EXACT (or budget_out) for each, plus per-task
speedup ratio.  If warm-start is reliably faster on hard tasks, it
validates the "mandelhunt rules as priors" hypothesis (the first of
three filter-placement options).

Usage:
  manage.py caformer_warmstart_bench
  manage.py caformer_warmstart_bench --pool .artifacts/loupe_rules \\
      --tasks pair14:2,pair30:8,pair32:7,pair46:21 --per-task-seconds 120
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from django.core.management.base import BaseCommand, CommandError


# Default tasks: positions that took non-trivial time in the original
# patch trainer.  All are board128_exact now, so we re-train them
# from scratch under both inits and compare wall time.
DEFAULT_TASKS = 'pair14:2,pair30:8,pair32:7,pair46:21,pair62:11,pair70:16'


class Command(BaseCommand):
    help = ('A/B benchmark: per-position trainer with random init vs '
            'warm-started from a mandelhunt LUT.  Tests if fractal-'
            'derived rules are useful priors.')

    def add_arguments(self, parser):
        parser.add_argument('--tasks', type=str, default=DEFAULT_TASKS,
                              help='comma-separated pair<pk>:<pos> entries')
        parser.add_argument('--pool', type=str,
                              default='.artifacts/loupe_rules',
                              help='mandelhunt LUT pool for warm-start')
        parser.add_argument('--per-task-seconds', type=float, default=120.0)
        parser.add_argument('--base-seed', type=int, default=0xB128A1E,
                              help='shared seed so random init is identical '
                                     'across A/B comparisons')

    def handle(self, *, tasks, pool, per_task_seconds, base_seed, **opts):
        from caformer.board128 import train_position_board128
        from caformer.models import QRPair
        from caframe import sources as src

        # Parse tasks.
        parsed = []
        for entry in tasks.split(','):
            entry = entry.strip()
            if not entry: continue
            try:
                pk_part, pos_part = entry.split(':')
                pk  = int(pk_part.replace('pair', '').strip())
                pos = int(pos_part.strip())
            except ValueError:
                raise CommandError(f'bad task spec {entry!r}; '
                                       'use pair<pk>:<pos>')
            pair = QRPair.objects.filter(pk=pk).first()
            if not pair:
                raise CommandError(f'pair {pk} not found')
            tb = pair.expected.encode('utf-8')
            if pos >= len(tb):
                raise CommandError(
                    f'pos {pos} out of range for pair {pk} '
                    f'(response is {len(tb)}B)')
            parsed.append((pair, pos, tb[pos]))

        # Load the warm-start seed rule.
        rule_bytes, _, label = src.from_mandelhunt(
            'best', seed_init=0, pool_dir=pool)
        seed_rule = rule_bytes
        assert len(seed_rule) == 16_384

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        log(f'=== warm-start A/B bench ===')
        log(f'  seed rule:   {label}')
        log(f'  tasks:       {len(parsed)}')
        log(f'  budget:      {per_task_seconds}s per arm')
        log(f'  base seed:   0x{base_seed:08x}\n')

        results = []
        for pair, pos, target in parsed:
            ch = chr(target) if 32 <= target < 127 else f'\\x{target:02x}'
            log(f'--- pair {pair.pk} pos {pos} target={ch!r} '
                f'(prompt={pair.prompt!r}, expected={pair.expected!r}) ---')

            # Arm A — random init.
            t0 = time.time()
            r_a = train_position_board128(
                pair.prompt, target, pos,
                max_seconds=per_task_seconds,
                seed=base_seed)
            wall_a = time.time() - t0

            # Arm B — mandelhunt warm-start, SAME seed so the random
            # half of the pop is identical to arm A's random half.
            t0 = time.time()
            r_b = train_position_board128(
                pair.prompt, target, pos,
                max_seconds=per_task_seconds,
                seed=base_seed,
                seed_rule=seed_rule)
            wall_b = time.time() - t0

            ok_a = r_a['byte_match']
            ok_b = r_b['byte_match']
            speedup = wall_a / max(wall_b, 1e-3) if (ok_a and ok_b) else None
            results.append({
                'pk': pair.pk, 'pos': pos, 'target': ch,
                'wall_a': wall_a, 'wall_b': wall_b,
                'ok_a':   ok_a,   'ok_b':   ok_b,
                'phase_a': r_a['phase'], 'phase_b': r_b['phase'],
                'speedup': speedup,
            })
            sa = '✓' if ok_a else '✗'
            sb = '✓' if ok_b else '✗'
            sp = f'{speedup:.2f}×' if speedup else 'n/a'
            log(f'    A random      : {sa} {wall_a:6.1f}s  ({r_a["phase"]})')
            log(f'    B mandelhunt  : {sb} {wall_b:6.1f}s  ({r_b["phase"]})')
            log(f'    speedup B/A   : {sp}\n')

        # Summary table.
        log(f'=== summary ===')
        log(f'{"pair":>5} {"pos":>4} {"tgt":>5}  '
            f'{"A wall":>8} {"B wall":>8} {"speedup":>9}')
        n_a = sum(1 for r in results if r['ok_a'])
        n_b = sum(1 for r in results if r['ok_b'])
        speedups = [r['speedup'] for r in results if r['speedup']]
        for r in results:
            sp = f'{r["speedup"]:.2f}×' if r['speedup'] else 'n/a'
            log(f'{r["pk"]:>5} {r["pos"]:>4} {r["target"]:>5}  '
                f'{r["wall_a"]:>7.1f}s {r["wall_b"]:>7.1f}s {sp:>9}')
        log(f'\n  A converged: {n_a}/{len(results)}   '
            f'B converged: {n_b}/{len(results)}')
        if speedups:
            log(f'  mean speedup (B/A) on co-converged tasks: '
                f'{sum(speedups)/len(speedups):.2f}×')
            log(f'  (>1.0 = warm-start helps, <1.0 = random init is better)')
