"""Generate an ALICE bundle for retraining pairs that are still
partial (no byte-exact cell8 tier) after the previous run.

Wraps alice_bundle_cell8 with automatic --pair-pks selection: scans
the DB for QRPairs in the requested ``--kind`` corpus that haven't
converged yet, builds a bundle for just those.  Defaults to a
bigger per-position budget so the second-chance run has a real
shot at the previously-stuck positions.

  manage.py caformer_alice_retry_partial --kind shakespeare \\
      --slug cell8-shakespeare-v3 --max-seconds-per-pos 3000

Kinds:
  shakespeare — pk 73..155 (the sonnet corpus)
  all         — every QRPair in the DB that isn't byte-exact yet

Use --dry-run to preview which pks would be retrained without
actually generating the bundle.
"""
from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand


KIND_RANGES = {
    'shakespeare': (73, 155),
    'all':         (None, None),
}


class Command(BaseCommand):
    help = ('Generate an ALICE bundle that retrains all pairs that '
            'are not yet byte-exact for the requested corpus.')

    def add_arguments(self, parser):
        parser.add_argument('--kind', choices=list(KIND_RANGES.keys()),
                              default='shakespeare')
        parser.add_argument('--slug', type=str, required=True,
                              help='bundle slug, e.g. cell8-shakespeare-v3')
        parser.add_argument('--max-seconds-per-pos', type=float, default=3000.0,
                              help='per-position training budget; '
                                     'default 3000 s (2× v2 budget) for '
                                     'pairs that already failed at 1500 s')
        parser.add_argument('--positions-per-task', type=int, default=4,
                              help='positions per array task — keep low '
                                     'so the 3000 s/pos budget still fits '
                                     'in cpu-short walltime')
        parser.add_argument('--time-limit', type=str, default='03:50:00')
        parser.add_argument('--mem-per-task', type=str, default='4G')
        parser.add_argument('--ssh-host', type=str, default='alice')
        parser.add_argument('--ssh-user', type=str, default='handyca')
        parser.add_argument('--dry-run', action='store_true',
                              help='print the partial pks but do not '
                                     'generate the bundle')

    def handle(self, *, kind, slug, max_seconds_per_pos, positions_per_task,
                 time_limit, mem_per_task, ssh_host, ssh_user, dry_run, **opts):
        from caformer.models import QRPair
        from django.db.models import Q

        exact_filter = (Q(cell8_b008_exact=True) | Q(cell8_b016_exact=True)
                        | Q(cell8_b032_exact=True) | Q(cell8_b064_exact=True)
                        | Q(cell8_b128_exact=True) | Q(cell8_b256_exact=True))

        lo, hi = KIND_RANGES[kind]
        qs = QRPair.objects.all()
        if lo is not None:
            qs = qs.filter(id__gte=lo, id__lte=hi)
        total = qs.count()
        exact_pks = set(qs.filter(exact_filter).values_list('id', flat=True))
        partial = list(qs.exclude(id__in=exact_pks)
                          .order_by('id')
                          .values_list('id', 'prompt', 'expected'))
        n_partial = len(partial)
        n_exact = total - n_partial

        # Estimate compute cost.
        total_positions = sum(len(exp.encode('utf-8'))
                              for (_pk, _p, exp) in partial)
        cpu_hours = (total_positions * max_seconds_per_pos) / 3600
        array_size = ((total_positions + positions_per_task - 1)
                      // positions_per_task)
        per_task_wall_hours = (positions_per_task * max_seconds_per_pos) / 3600

        self.stdout.write(f'=== retry-partial ({kind}) ===')
        self.stdout.write(f'  corpus pk range:    '
                          f'{lo}..{hi}' if lo is not None else '  corpus: ALL')
        self.stdout.write(f'  total pairs:        {total}')
        self.stdout.write(f'  byte-exact:         {n_exact}')
        self.stdout.write(f'  partial (to retry): {n_partial}')
        self.stdout.write(f'  total positions:    {total_positions}')
        self.stdout.write(f'  per-pos budget:     {max_seconds_per_pos:.0f} s')
        self.stdout.write(f'  positions/task:     {positions_per_task}')
        self.stdout.write(f'  array tasks:        {array_size}')
        self.stdout.write(f'  per-task wall:      {per_task_wall_hours:.2f} h '
                          f'(of {time_limit})')
        self.stdout.write(f'  total CPU:          {cpu_hours:.1f} CPU-hr')
        self.stdout.write('')

        self.stdout.write(f'partial pks (first 10):')
        for pk, prompt, expected in partial[:10]:
            self.stdout.write(
                f'  pk={pk:>4}  {prompt[:50]!r:55s} → {expected[:50]!r}')
        if n_partial > 10:
            self.stdout.write(f'  ... and {n_partial - 10} more')

        if dry_run:
            self.stdout.write('')
            self.stdout.write('(dry-run; bundle not generated)')
            return

        if n_partial == 0:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'no partial pairs in this kind — nothing to retrain'))
            return

        # Delegate to the existing bundle generator.  Pair pks as a
        # comma-joined string.
        pks_arg = ','.join(str(pk) for (pk, _p, _e) in partial)
        self.stdout.write('')
        self.stdout.write(f'invoking alice_bundle_cell8 …')
        call_command(
            'alice_bundle_cell8',
            slug=slug,
            pair_pks=pks_arg,
            positions_per_task=positions_per_task,
            max_seconds_per_pos=max_seconds_per_pos,
            time_limit=time_limit,
            mem_per_task=mem_per_task,
            ssh_host=ssh_host,
            ssh_user=ssh_user,
            # array_size is ignored when positions_per_task > 0; pass
            # something to silence the parser.
            array_size=array_size,
        )
