"""manage.py deep_chain_report — current snapshot of chain-depth discoveries.

Surveys every saved class-4 quine ComponentChampion and reports its
actual chain depth under the current (relaxed) criterion.  Useful as
a morning report after an overnight cascade run.

Usage:

    manage.py deep_chain_report
    manage.py deep_chain_report --top 20 --max-depth 2048
    manage.py deep_chain_report --output .artifacts/morning-report.txt
"""
from __future__ import annotations

import time
from pathlib import Path

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Survey saved class-4 quines for chain depth + report top '
              'discoveries.')

    def add_arguments(self, parser):
        parser.add_argument('--top', type=int, default=15,
                                help='Show top-N champions by depth.')
        parser.add_argument('--max-depth', type=int, default=1024,
                                help='Cap the walk at this depth per '
                                     'candidate (saves compute when '
                                     'attractors are short).')
        parser.add_argument('--act-hi', type=float, default=0.85)
        parser.add_argument('--sr-threshold', type=float, default=0.85)
        parser.add_argument('--metric', default='arbsigma',
                                choices=['arbsigma', 'strict'])
        parser.add_argument('--output',
                                help='Also write the report to this file.')

    def handle(self, *args, **opts):
        from caformer.models import ComponentChampion
        from spoeqi.deep_chain_search import chain_depth_fitness

        lines: list[str] = []
        def emit(s: str = ''):
            self.stdout.write(s)
            lines.append(s)

        emit('═' * 72)
        emit('CLASS-4 QUINE DEEP-CHAIN SURVEY')
        emit(f'  generated {time.ctime()}')
        emit(f'  criterion: cls==4 AND act in [0.05,{opts["act_hi"]}] '
             f'AND sr_{opts["metric"]} >= {opts["sr_threshold"]:.2f}')
        emit(f'  walk capped at {opts["max_depth"]} levels per candidate')
        emit('═' * 72)
        emit('')

        all_quines = list(ComponentChampion.objects
                          .filter(component_slug='class4_quine')
                          .order_by('-fitness'))
        emit(f'Total saved quines: {len(all_quines)}')

        deep_results = []
        t0 = time.time()
        emit('')
        emit('Evaluating chain depth on every saved quine '
              '(this may take a few minutes)...')
        for q in all_quines:
            seed = bytes(q.rules_blob)
            try:
                r = chain_depth_fitness(
                    seed, target_depth=opts['max_depth'],
                    act_band=(0.05, opts['act_hi']),
                    sr_threshold=opts['sr_threshold'],
                    metric=opts['metric'])
                deep_results.append({
                    'pk':          q.pk,
                    'fitness':     q.fitness,
                    'run_length':  r['run_length'],
                    'streak_start': r['streak_start'],
                    'distinct':    r['distinct_levels'],
                    'walked':      r['walked_levels'],
                    'cycle_at':    r['cycle_at'],
                    'run_label':   q.run_label or '',
                    'created':     q.created_at,
                })
            except Exception as e:
                emit(f'  ! pk={q.pk}: {e}')

        dt = time.time() - t0
        emit(f'  done in {dt:.1f}s')
        emit('')

        # Sort by run_length descending
        deep_results.sort(key=lambda r: (-r['run_length'], -r['fitness']))

        emit(f'TOP {opts["top"]} BY CHAIN DEPTH:')
        emit('')
        header = (f'  {"pk":>5s}  {"sr":>6s}  {"run":>7s}  '
                  f'{"start":>5s}  {"distinct":>8s}  {"cycle":>5s}  '
                  f'{"label":<24s}  created')
        emit(header)
        emit('  ' + '─' * 84)
        for r in deep_results[:opts['top']]:
            cycle = str(r['cycle_at']) if r['cycle_at'] else '—'
            run_str = f'{r["run_length"]}/{opts["max_depth"]}'
            emit(f'  {r["pk"]:>5d}  {r["fitness"]:>6.3f}  '
                 f'{run_str:>7s}  {str(r["streak_start"] or "—"):>5s}  '
                 f'{r["distinct"]:>8d}  {cycle:>5s}  '
                 f'{r["run_label"][:24]:<24s}  '
                 f'{r["created"].strftime("%Y-%m-%d %H:%M")}')

        # Histogram-style breakdown
        emit('')
        emit('CHAIN DEPTH DISTRIBUTION:')
        buckets = [
            ('≥ 65536', 65536), ('≥ 32768', 32768), ('≥ 16384', 16384),
            ('≥ 8192',  8192),  ('≥ 4096',  4096),  ('≥ 2048',  2048),
            ('≥ 1024',  1024),  ('≥ 512',   512),   ('≥ 256',   256),
            ('≥ 128',   128),   ('≥ 64',    64),    ('≥ 32',    32),
            ('< 32',    0),
        ]
        for label, thresh in buckets:
            count = sum(1 for r in deep_results
                        if (thresh == 0 and r['run_length'] < 32)
                        or (thresh > 0 and r['run_length'] >= thresh
                            and (thresh == 65536
                                 or r['run_length'] < (
                                     next((t for n, t in buckets
                                           if t > thresh), float('inf'))))))
            if count:
                emit(f'  {label:<10s}  {count} quine(s)')

        # Deepest discovery breakdown
        if deep_results:
            best = deep_results[0]
            emit('')
            emit(f'DEEPEST CHAIN FOUND: pk={best["pk"]}, '
                 f'{best["run_length"]} consecutive class-4 levels')
            if best["run_length"] >= 65536:
                emit('  → 65,536 LEVEL TARGET REACHED.')
            elif best["run_length"] >= 8192:
                emit('  → multi-thousand depth — substantial discovery')
            elif best["run_length"] >= 1024:
                emit('  → kilo-depth — solid progress')
            elif best["run_length"] >= 256:
                emit('  → moderate depth — past the initial cluster')
            else:
                emit('  → shallow attractor — needs more search')

        emit('')
        emit('═' * 72)

        if opts.get('output'):
            Path(opts['output']).write_text('\n'.join(lines))
            self.stdout.write(self.style.SUCCESS(
                f'report written → {opts["output"]}'))
