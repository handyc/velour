"""manage.py chain_topology — what shape does a quine's chain have?

For a saved class-4 quine, walks its chain and categorises the end:

  - "class-4 cycle"     — chain re-enters a class-4 state cycle (effectively
                          infinite depth)
  - "class-4 then cycle"— chain leaves class-4 territory and then cycles
  - "fixed point"       — chain hits a self-mapping rule (cycle period 1)
  - "class-1 attractor" — collapses to homogeneous output
  - "class-3 drift"     — degenerates to noise without cycling
  - "open"              — still class-4 at the walk depth (didn't terminate)

Usage:

    manage.py chain_topology <pk>
    manage.py chain_topology <pk> --depth 4096
    manage.py chain_topology --all --output .artifacts/topology.txt
"""
from __future__ import annotations

import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Classify the chain topology of saved class-4 quines.'

    def add_arguments(self, parser):
        parser.add_argument('pk', type=int, nargs='?', default=None)
        parser.add_argument('--all', action='store_true',
                                help='Run against every saved quine.')
        parser.add_argument('--depth', type=int, default=2048)
        parser.add_argument('--output')
        parser.add_argument('--act-hi', type=float, default=0.85)
        parser.add_argument('--sr-threshold', type=float, default=0.85)

    def handle(self, *args, **opts):
        from caformer.models import ComponentChampion

        if opts['all']:
            qs = ComponentChampion.objects.filter(
                component_slug='class4_quine').order_by('-fitness')
        elif opts['pk'] is not None:
            qs = ComponentChampion.objects.filter(
                pk=opts['pk'], component_slug='class4_quine')
        else:
            raise CommandError('pass <pk> or --all')

        lines: list[str] = []
        def emit(s: str = ''):
            self.stdout.write(s)
            lines.append(s)

        emit(f'CHAIN TOPOLOGY ANALYSIS  (depth_cap={opts["depth"]}, '
             f'act_band=(0.05,{opts["act_hi"]}), sr>={opts["sr_threshold"]})')
        emit('═' * 72)
        emit(f'  {"pk":>4s}  {"sr":>5s}  {"verdict":<24s}  '
             f'{"streak":>8s}  {"cycle":>8s}  {"distinct":>9s}  notes')
        emit('  ' + '─' * 88)

        for q in qs:
            seed = bytes(q.rules_blob)
            verdict, info = self._analyze(seed, opts['depth'],
                                              opts['act_hi'],
                                              opts['sr_threshold'])
            cycle_str = (f'{info["cycle_period"]}@L{info["cycle_at"]-info["cycle_period"]}'
                          if info['cycle_period'] else '—')
            emit(f'  {q.pk:>4d}  {q.fitness:>5.3f}  '
                 f'{verdict:<24s}  {info["streak"]:>8d}  '
                 f'{cycle_str:>8s}  {info["distinct"]:>9d}  {info["note"]}')

        if opts.get('output'):
            Path(opts['output']).write_text('\n'.join(lines))
            self.stdout.write(self.style.SUCCESS(
                f'topology report → {opts["output"]}'))

    # ─── analyzer ────────────────────────────────────────────────

    def _analyze(self, seed: bytes, depth: int,
                   act_hi: float, sr_th: float) -> tuple[str, dict]:
        from spoeqi.metachain import (
            classify_rule, probe_activity, sr_arbitrary_sigma, hex_ca_step)
        import numpy as np

        rule_arr = np.frombuffer(seed, dtype=np.uint8).copy() & 3
        seen: dict[bytes, int] = {bytes(rule_arr.tobytes()): 0}
        oks: list[bool] = []
        classes: list[int] = []
        activities: list[float] = []
        cycle_at = None
        cycle_period = None

        current = rule_arr
        for level in range(depth):
            cur_bytes = bytes(current.tobytes())
            cls, _ = classify_rule(cur_bytes, probe_ticks=16)
            act = probe_activity(cur_bytes, ticks=12)
            sr = sr_arbitrary_sigma(cur_bytes, ticks=16)
            ok = (cls == 4 and 0.05 <= act <= act_hi and sr >= sr_th)
            oks.append(ok)
            classes.append(cls)
            activities.append(act)

            state = current.reshape(128, 128).copy()
            for _ in range(16):
                state = hex_ca_step(state, current)
            nxt = state.flatten() & 3
            nb = bytes(nxt.tobytes())
            if nb in seen:
                cycle_at = level + 1
                cycle_period = cycle_at - seen[nb]
                break
            seen[nb] = level + 1
            current = nxt

        # Compute longest run
        streak = 0
        cur = 0
        for v in oks:
            if v:
                cur += 1
                streak = max(streak, cur)
            else:
                cur = 0
        distinct = len(seen)

        # Classify the end
        note = ''
        if cycle_period == 1:
            # The fixed point is at level (cycle_at - 1).  Check if
            # that level was class-4.
            fp_level = cycle_at - 1
            fp_was_class4 = oks[fp_level] if fp_level < len(oks) else False
            if fp_was_class4:
                verdict = 'class-4 fixed point'
                note = (f'rule {fp_level} maps to itself AND is class-4 '
                       f'→ ∞ class-4 depth')
            else:
                verdict = 'fixed point'
                note = (f'rule {fp_level} maps to itself; not class-4 '
                       f'(streak ended at L{streak})')
        elif cycle_period:
            # Was the cycle's entirety class-4?
            cycle_oks = oks[cycle_at - cycle_period:cycle_at]
            if all(cycle_oks):
                verdict = 'class-4 cycle'
                note = f'period {cycle_period}; all class-4 → ∞ depth'
            else:
                verdict = 'class-4 then cycle'
                cls_in_cycle = classes[cycle_at - cycle_period:cycle_at]
                final_cls = max(set(cls_in_cycle),
                                  key=cls_in_cycle.count)
                note = (f'period {cycle_period}; cycle is class-{final_cls} '
                       f'(streak ended at L{streak})')
        elif len(oks) >= depth:
            verdict = 'open'
            note = f'still class-4 at walk depth {depth}'
        else:
            # Walked but didn't cycle and didn't hit depth — early term?
            # Actually this branch shouldn't happen given our loop.
            verdict = 'unknown'
            note = ''

        # Refine class-1/3 if no cycle
        if cycle_period is None and len(oks) > streak + 5:
            # Chain broke and walked some non-class-4 levels
            tail_cls = classes[-3:]
            if any(c == 1 for c in tail_cls):
                verdict = 'class-1 attractor'
                note = f'streak ended at L{streak}, then class-1 takeover'
            elif any(c == 3 for c in tail_cls):
                verdict = 'class-3 drift'
                note = f'streak ended at L{streak}, then class-3 noise'

        return verdict, {
            'streak':       streak,
            'cycle_at':     cycle_at,
            'cycle_period': cycle_period,
            'distinct':     distinct,
            'note':         note,
        }
