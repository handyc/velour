"""Generate an ALICE bundle for board128 training of a corpus slice.

  manage.py alice_bundle_board128 --slug sonnets-v1 \\
      --pair-pks shakespeare --array-size 24 \\
      --max-seconds-per-pos 90

  manage.py alice_bundle_board128 --slug custom \\
      --pair-pks 1-35,42,50 --array-size 16
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


def parse_pks(spec, qs):
    """'1-35,42' / 'all' / 'untrained' / 'shakespeare' / '<label-prefix>'"""
    spec = (spec or '').strip().lower()
    if spec == 'all':
        return list(qs.values_list('pk', flat=True).order_by('pk'))
    if spec in ('untrained', 'todo'):
        return list(qs.filter(board128_exact=False)
                       .values_list('pk', flat=True).order_by('pk'))
    if spec == 'exact':
        return list(qs.filter(board128_exact=True)
                       .values_list('pk', flat=True).order_by('pk'))
    if spec == 'shakespeare':
        return list(qs.filter(label__startswith='shakespeare')
                       .values_list('pk', flat=True).order_by('pk'))
    # arbitrary label prefix
    if spec and not any(c.isdigit() or c == ',' or c == '-' for c in spec):
        return list(qs.filter(label__startswith=spec)
                       .values_list('pk', flat=True).order_by('pk'))
    # otherwise treat as pk list / ranges
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
    help = ('Generate a self-contained ALICE bundle for board128 '
            'training across an sbatch array.')

    def add_arguments(self, parser):
        parser.add_argument('--slug', type=str, required=True)
        parser.add_argument('--pair-pks', type=str, required=True,
                              help="'1-35,42' | 'all' | 'untrained' | "
                                     "'shakespeare' | '<label-prefix>'")
        parser.add_argument('--array-size', type=int, default=24)
        parser.add_argument('--max-seconds-per-pos', type=float, default=90.0)
        parser.add_argument('--n-ticks', type=int, default=128)
        parser.add_argument('--time-limit', type=str, default='04:00:00')
        parser.add_argument('--mem-per-task', type=str, default='2G')
        parser.add_argument('--ssh-host', type=str,
                              default='alice')
        parser.add_argument('--ssh-user', type=str, default='handyca')

    def handle(self, *, slug, pair_pks, array_size, max_seconds_per_pos,
                 n_ticks, time_limit, mem_per_task, ssh_host, ssh_user,
                 **opts):
        from caformer.models import QRPair
        from conduit.alice.caformer_board128 import (BundleParams,
                                                            export_pairs_for_bundle,
                                                            generate_bundle)
        pks = parse_pks(pair_pks, QRPair.objects)
        if not pks:
            raise CommandError(f'no pair pks matched {pair_pks!r}')
        pairs = export_pairs_for_bundle(pks)
        if not pairs:
            raise CommandError(f'no usable QRPair rows for pks={pks}')

        params = BundleParams(
            slug=slug, pair_pks=pks, pairs=pairs,
            array_size=array_size,
            max_seconds_per_pos=max_seconds_per_pos,
            n_ticks=n_ticks,
            time_limit=time_limit, mem_per_task=mem_per_task,
            ssh_host=ssh_host, ssh_user=ssh_user)

        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        bundle_dir = repo_root / 'conduit' / 'alice' / 'bundles' / slug
        generate_bundle(bundle_dir, params)

        avg_pos = sum(p['n_positions'] for p in pairs) / len(pairs)
        est_cpu_hr = (len(pairs) * avg_pos * max_seconds_per_pos) / 3600
        print(f'\n=== bundle written: {bundle_dir} ===')
        print(f'  {len(pairs)} pairs, array_size={array_size}')
        print(f'  avg {avg_pos:.1f} positions per pair')
        print(f'  estimated total CPU: ~{est_cpu_hr:.1f} CPU-hr')
        print(f'\n  Next steps:')
        print(f'    bash {bundle_dir}/push.sh')
        print(f'    ssh {ssh_user}@{ssh_host}')
        print(f'    cd ~/velour-dev/.alice_bundles/{slug}; sbatch submit.sh')
        print(f'    bash {bundle_dir}/pull.sh')
        print(f'    manage.py alice_ingest_board128 {slug}')
