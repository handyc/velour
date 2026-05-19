"""Run tier_dispatch.compare_all_tiers over the whole corpus and
report a summary table: per-tier EXACT rate, mean inference wall
per pair, cell-update count.  Quantifies the multires speed-vs-
fidelity trade-off across all 71 pairs.

Usage:
  manage.py caformer_tier_compare
  manage.py caformer_tier_compare --pair-ids 2,14,21
"""
from __future__ import annotations

import statistics
import sys

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Run inference at every available tier on every pair; '
            'tally EXACT + mean wall per tier.')

    def add_arguments(self, parser):
        parser.add_argument('--pair-ids', type=str, default='')

    def handle(self, *, pair_ids, **opts):
        from caformer.models import QRPair
        from caformer.tier_dispatch import compare_all_tiers

        if pair_ids.strip():
            ids = [int(x) for x in pair_ids.split(',') if x.strip()]
            pairs = list(QRPair.objects.filter(pk__in=ids).order_by('pk'))
        else:
            pairs = list(QRPair.objects.all().order_by('pk'))

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        # Per-pair results.
        per_tier = {}  # side → list of (exact, wall, cells, byte_match, n_target)
        for pair in pairs:
            cmp = compare_all_tiers(pair)
            for r in cmp['tiers']:
                per_tier.setdefault(r['side'], []).append(
                    (r['exact'], r['wall'], r['cell_updates'],
                     r['byte_match'], r['n_target']))

        log(f'=== tier comparison over {len(pairs)} pairs ===\n')
        log(f'  {"side":>5} {"trained":>8} {"EXACT":>8} {"mean_wall":>12} '
            f'{"mean_cells":>14} {"speedup":>10}')
        # Reference baseline: 128.
        sides_sorted = sorted(per_tier.keys(), reverse=True)
        baseline_wall = None
        for side in sides_sorted:
            entries = per_tier[side]
            if not entries:
                continue
            n_exact = sum(1 for e in entries if e[0])
            mean_wall = statistics.mean(e[1] for e in entries)
            mean_cells = statistics.mean(e[2] for e in entries)
            if baseline_wall is None:
                baseline_wall = mean_wall
                speedup = '1.0×'
            else:
                speedup = f'{baseline_wall / max(mean_wall, 1e-6):.1f}×'
            log(f'  {side:>5} {len(entries):>8} {n_exact:>8} '
                f'{mean_wall * 1000:>9.2f} ms '
                f'{mean_cells:>14,.0f} {speedup:>10}')

        # Inferred storage cost per tier (constant LUT size,
        # so this is just N × 16,384 bytes per pair).
        log(f'\n  storage: every tier uses 16,384-byte LUTs.  Per pair,')
        log(f'  having ALL FIVE tiers stored = 5× one-tier storage cost.')
        log(f'  The speed-vs-fidelity trade-off is in INFERENCE wall, not')
        log(f'  disk size — tier choice picks which forward pass to run.')
