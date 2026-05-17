"""Generate an ALICE bundle for the metapact GA scale-up.

Usage:
    manage.py alice_bundle_metapact [--slug NAME] [--replicates N] \
        [--generations N] [--pop-size N] [--depth N] [--chain-ticks N] \
        [--mutation-rate F] [--w-chain F] [--w-leaf F] [--seed-base HEX] \
        [--corpus-bytes N] [--time-limit HH:MM:SS] [--mem 2G] \
        [--ssh-user U] [--ssh-host H] [--remote-dir P]

Defaults are intentionally small + safe (16 replicates × 50 gen × 32 pop,
~7 min/task) so the first bundle is a low-stakes pipeline shakedown
rather than a maximal scale-up.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from conduit.alice import metapact_ga as mpga


class Command(BaseCommand):
    help = 'Generate an ALICE HPC bundle for the metapact GA.'

    def add_arguments(self, parser):
        add = parser.add_argument
        add('--slug', default=None,
            help='Bundle slug. Defaults to metapact-ga-YYYYMMDD-HHMM.')
        add('--replicates', type=int, default=mpga.BundleParams.replicates)
        add('--generations', type=int, default=mpga.BundleParams.generations)
        add('--pop-size', type=int, default=mpga.BundleParams.pop_size)
        add('--depth', type=int, default=mpga.BundleParams.depth)
        add('--chain-ticks', type=int, default=mpga.BundleParams.chain_ticks)
        add('--mutation-rate', type=float,
            default=mpga.BundleParams.mutation_rate)
        add('--w-chain', type=float, default=mpga.BundleParams.w_chain)
        add('--w-leaf',  type=float, default=mpga.BundleParams.w_leaf)
        add('--seed-base', default=hex(mpga.BundleParams.seed_base),
            help='Hex int, XORed with task id for per-task seed.')
        add('--corpus-bytes', type=int,
            default=mpga.BundleParams.corpus_bytes)
        add('--time-limit',  default=mpga.BundleParams.time_limit)
        add('--mem',         default=mpga.BundleParams.mem_per_task)
        add('--cpus-per-task', type=int,
            default=mpga.BundleParams.cpus_per_task)
        add('--ssh-user', default=mpga.BundleParams.ssh_user)
        add('--ssh-host', default=mpga.BundleParams.ssh_host)
        add('--remote-dir', default=mpga.BundleParams.remote_dir)

    def handle(self, *args, **opts):
        slug = opts['slug'] or (
            'metapact-ga-' + dt.datetime.now().strftime('%Y%m%d-%H%M'))
        try:
            seed_base = int(opts['seed_base'], 0)
        except ValueError as exc:
            raise CommandError(f'bad --seed-base: {exc}')

        params = mpga.BundleParams(
            slug=slug,
            replicates=opts['replicates'],
            generations=opts['generations'],
            pop_size=opts['pop_size'],
            depth=opts['depth'],
            chain_ticks=opts['chain_ticks'],
            mutation_rate=opts['mutation_rate'],
            w_chain=opts['w_chain'],
            w_leaf=opts['w_leaf'],
            seed_base=seed_base,
            corpus_bytes=opts['corpus_bytes'],
            time_limit=opts['time_limit'],
            mem_per_task=opts['mem'],
            cpus_per_task=opts['cpus_per_task'],
            ssh_user=opts['ssh_user'],
            ssh_host=opts['ssh_host'],
            remote_dir=opts['remote_dir'],
        )

        bundles_root = Path(settings.BASE_DIR) / 'conduit' / 'alice' / 'bundles'
        bundles_root.mkdir(parents=True, exist_ok=True)
        out_dir = bundles_root / slug

        try:
            mpga.generate_bundle(out_dir, params)
        except FileExistsError as exc:
            raise CommandError(str(exc))

        self.stdout.write(self.style.SUCCESS(
            f'Bundle written to {out_dir}'))
        self.stdout.write('')
        self.stdout.write('Operator steps:')
        self.stdout.write(f'  1. Review:  cat {out_dir}/README.md')
        self.stdout.write(f'  2. Push:    bash {out_dir}/push.sh')
        self.stdout.write(f'  3. SSH + sbatch on ALICE')
        self.stdout.write(f'  4. Pull:    bash {out_dir}/pull.sh')
        self.stdout.write(f'  5. Analyse: manage.py alice_analyze_metapact {slug}')
