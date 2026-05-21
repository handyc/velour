"""Generate an ALICE bundle for cell8+256 corpus retraining.

  manage.py alice_bundle_cell8 --slug cell8-batch-A --pair-pks 1-35
  manage.py alice_bundle_cell8 --slug full-corpus --pair-pks all \\
      --array-size 32 --max-seconds-per-pos 180
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


def parse_pks(spec, qs):
    """'1-35,42' or 'all' or 'exact' → list of pks."""
    spec = (spec or '').strip().lower()
    if spec in ('all',):
        return list(qs.values_list('pk', flat=True).order_by('pk'))
    if spec in ('exact',):
        return list(qs.filter(board128_exact=True)
                       .values_list('pk', flat=True).order_by('pk'))
    out = []
    for tok in spec.split(','):
        tok = tok.strip()
        if not tok:
            continue
        if '-' in tok:
            a, b = tok.split('-', 1)
            lo, hi = int(a), int(b)
            if lo > hi: lo, hi = hi, lo
            out.extend(range(lo, hi + 1))
        else:
            out.append(int(tok))
    seen, dedup = set(), []
    for pk in out:
        if pk not in seen:
            seen.add(pk); dedup.append(pk)
    return dedup


class Command(BaseCommand):
    help = ('Generate a self-contained ALICE bundle for cell8+256 '
            'training across an sbatch array.')

    def add_arguments(self, parser):
        parser.add_argument('--slug', type=str, required=True)
        parser.add_argument('--pair-pks', type=str, required=True,
                              help="'1-35,42' | 'all' | 'exact'")
        parser.add_argument('--array-size', type=int, default=32,
                              help='legacy pair-slicing mode: number of '
                                     'array tasks (ignored when '
                                     '--positions-per-task > 0)')
        parser.add_argument('--positions-per-task', type=int, default=0,
                              help='if >0, slice the corpus into chunks of '
                                     'this many independent (pair, position) '
                                     'items per array task.  Use when each '
                                     'task must fit a short-queue walltime '
                                     '(e.g. cpu-short / 4 h on ALICE).')
        parser.add_argument('--max-seconds-per-pos', type=float, default=180.0)
        parser.add_argument('--n-ticks', type=int, default=256)
        parser.add_argument('--no-warm-start', action='store_true')
        parser.add_argument('--time-limit', type=str, default='04:00:00')
        parser.add_argument('--mem-per-task', type=str, default='4G')
        parser.add_argument('--ssh-host', type=str,
                              default='alice')
        parser.add_argument('--ssh-user', type=str, default='handyca')

    def handle(self, *, slug, pair_pks, array_size, positions_per_task,
                 max_seconds_per_pos, n_ticks, no_warm_start, time_limit,
                 mem_per_task, ssh_host, ssh_user, **opts):
        from caformer.models import QRPair
        from conduit.alice.caformer_cell8 import (BundleParams,
                                                          export_pairs_for_bundle,
                                                          generate_bundle)
        pks = parse_pks(pair_pks, QRPair.objects)
        if not pks:
            raise CommandError(f'no pair pks matched {pair_pks!r}')
        pairs = export_pairs_for_bundle(pks, warm_start=not no_warm_start)
        if not pairs:
            raise CommandError(f'no usable QRPair rows for pks={pks}')

        params = BundleParams(
            slug=slug, pair_pks=pks, pairs=pairs,
            array_size=array_size,
            positions_per_task=positions_per_task,
            max_seconds_per_pos=max_seconds_per_pos,
            n_ticks=n_ticks,
            warm_start=not no_warm_start,
            time_limit=time_limit, mem_per_task=mem_per_task,
            ssh_host=ssh_host, ssh_user=ssh_user)

        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        bundle_dir = repo_root / 'conduit' / 'alice' / 'bundles' / slug
        generate_bundle(bundle_dir, params)

        total_positions = sum(len(p['expected'].encode('utf-8'))
                              for p in pairs)
        if positions_per_task > 0:
            n_array = (total_positions + positions_per_task - 1) // positions_per_task
            per_task_walltime = positions_per_task * max_seconds_per_pos
            print(f'\n=== bundle written: {bundle_dir} ===')
            print(f'  {len(pairs)} pairs, {total_positions} positions, '
                  f'positions_per_task={positions_per_task}, '
                  f'array_size={n_array}')
            print(f'  per-task walltime ≈ {per_task_walltime/3600:.2f} h '
                  f'(of {time_limit} SLURM limit)')
            print(f'  total CPU ≈ {(total_positions * max_seconds_per_pos)/3600:.1f} CPU-hr')
        else:
            print(f'\n=== bundle written: {bundle_dir} ===')
            print(f'  {len(pairs)} pairs, array_size={array_size}, '
                  f'~{((len(pairs) * 5 * max_seconds_per_pos) / 3600):.1f} CPU-hr total')
        print(f'\n  Next steps:')
        print(f'    bash {bundle_dir}/push.sh')
        print(f'    ssh {ssh_user}@{ssh_host}; cd ~/velour-dev/.alice_bundles/{slug}; sbatch submit.sh')
        print(f'    bash {bundle_dir}/pull.sh')
        print(f'    manage.py alice_ingest_cell8 {slug}')
