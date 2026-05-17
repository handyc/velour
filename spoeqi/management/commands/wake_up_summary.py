"""manage.py wake_up_summary — single morning report from the
overnight deep-chain cascade.

Combines:
  - latest cascade log tail
  - chain-depth survey of every saved quine
  - chain-topology classification of every saved quine
  - delta vs the baseline files in .artifacts/

Usage:

    manage.py wake_up_summary
    manage.py wake_up_summary --depth 4096 --output wake.txt
"""
from __future__ import annotations

import time
from pathlib import Path

from django.core.management.base import BaseCommand


CASCADE_LOGS = [
    '.artifacts/cascade3.log',
    '.artifacts/cascade2.log',
    '.artifacts/cascade.log',
    '.artifacts/deep-chain-ga.log',
]
BASELINE_REPORT  = '.artifacts/morning-report-baseline.txt'
BASELINE_TOPOLOGY = '.artifacts/topology-baseline.txt'


class Command(BaseCommand):
    help = 'Single overnight summary of deep-chain GA progress.'

    def add_arguments(self, parser):
        parser.add_argument('--depth', type=int, default=2048)
        parser.add_argument('--output')
        parser.add_argument('--no-survey', action='store_true',
                                help='Skip the slow depth survey; just '
                                     'show the cascade log tail.')

    def handle(self, *args, **opts):
        from caformer.models import ComponentChampion
        from django.conf import settings
        from spoeqi.deep_chain_search import chain_depth_fitness

        lines: list[str] = []
        def emit(s: str = ''):
            self.stdout.write(s)
            lines.append(s)

        emit('═' * 72)
        emit('VELOUR DEEP-CHAIN QUINE OVERNIGHT REPORT')
        emit(f'  generated {time.ctime()}')
        emit('═' * 72)
        emit('')

        # 1. Cascade activity summary
        base = Path(settings.BASE_DIR)
        active_log = None
        for p in CASCADE_LOGS:
            full = base / p
            if full.exists():
                active_log = full
                break

        if active_log:
            emit(f'CASCADE LOG: {active_log}')
            emit('─' * 72)
            lines_log = active_log.read_text().splitlines()
            # Last 50 lines OR everything if shorter
            tail = lines_log[-50:]
            for line in tail:
                emit('  ' + line)
            emit('')

        # 2. ComponentChampion deltas
        emit('CHAMPIONS DISCOVERED OVERNIGHT (run_label="deep-chain-ga"):')
        emit('─' * 72)
        deep = list(ComponentChampion.objects
                    .filter(component_slug='class4_quine',
                              run_label='deep-chain-ga')
                    .order_by('-created_at'))
        if deep:
            emit(f'  {"pk":>4s}  {"fit":>5s}  {"eval_ct":>7s}  '
                 f'{"created":<19s}')
            for q in deep:
                emit(f'  {q.pk:>4d}  {q.fitness:>5.3f}  {q.eval_count:>7d}  '
                     f'{q.created_at.strftime("%Y-%m-%d %H:%M:%S")}')
        else:
            emit('  (none yet)')
        emit('')

        # 3. Depth survey
        if not opts['no_survey']:
            emit(f'DEPTH SURVEY (target_depth={opts["depth"]}, '
                 f'cls==4 AND act∈[0.05,0.85] AND sr_arbσ≥0.85):')
            emit('─' * 72)

            qs = list(ComponentChampion.objects
                      .filter(component_slug='class4_quine'))
            results = []
            t0 = time.time()
            for q in qs:
                try:
                    r = chain_depth_fitness(bytes(q.rules_blob),
                                                  target_depth=opts['depth'])
                    results.append((q, r))
                except Exception as e:
                    emit(f'  ! pk={q.pk}: {e}')

            results.sort(key=lambda kv: -kv[1]['run_length'])

            emit(f'  ({time.time() - t0:.1f}s to evaluate {len(qs)} quines)')
            emit('')
            emit(f'  {"pk":>4s}  {"label":<18s}  {"streak":>7s}  '
                 f'{"start":>5s}  {"cycle":>6s}  {"walked":>7s}')
            emit('  ' + '─' * 60)
            for q, r in results[:20]:
                cycle = r['cycle_at'] or '—'
                start = r['streak_start'] if r['streak_start'] is not None else '—'
                emit(f'  {q.pk:>4d}  '
                     f'{(q.run_label or "")[:18]:<18s}  '
                     f'{r["run_length"]:>5d}/{opts["depth"]}  '
                     f'{str(start):>5s}  {str(cycle):>6s}  '
                     f'{r["walked_levels"]:>7d}')
            emit('')

            if results:
                best_q, best_r = results[0]
                emit(f'DEEPEST CHAIN: pk={best_q.pk} with '
                     f'{best_r["run_length"]} consecutive class-4 levels')
                if best_r['run_length'] >= 65536:
                    emit('  ★★★ 65,536 LEVEL TARGET REACHED ★★★')
                elif best_r['run_length'] >= 8192:
                    emit('  ★ multi-thousand depth — substantial')
                elif best_r['run_length'] >= 1024:
                    emit('  kilo-depth — solid')
                elif best_r['run_length'] >= 256:
                    emit('  moderate — past the initial cluster')
                else:
                    emit('  shallow — needs more search')
                emit('')

                # Compare against baseline
                baseline_file = base / BASELINE_REPORT
                if baseline_file.exists():
                    baseline_text = baseline_file.read_text()
                    import re
                    m = re.search(r'DEEPEST CHAIN FOUND: pk=(\d+), '
                                       r'(\d+) consecutive', baseline_text)
                    if m:
                        old_pk = int(m.group(1))
                        old_depth = int(m.group(2))
                        delta = best_r['run_length'] - old_depth
                        sign = '+' if delta >= 0 else ''
                        emit(f'BASELINE: pk={old_pk} at {old_depth} levels '
                             f'(delta: {sign}{delta} levels)')
                        emit('')

        emit('═' * 72)
        emit('END OF REPORT')

        if opts.get('output'):
            Path(opts['output']).write_text('\n'.join(lines))
            self.stdout.write(self.style.SUCCESS(
                f'\nreport written → {opts["output"]}'))
