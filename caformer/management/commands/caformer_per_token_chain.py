"""Benchmark per-token quine-chain training vs joint/positional baseline.

Usage::

    venv/bin/python manage.py caformer_per_token_chain --pair 11
    venv/bin/python manage.py caformer_per_token_chain --pair 11 --depth 32

Per-token chain trainer assigns each unique target byte a distinct
class-4 L0 fixed-point quine origin, builds its 64-deep metachain by
self-application, and picks the best chain level as the output rule
at each position.  No GA — just a scan of the chain.

Reports total fitness, argmax matches, and storage delta vs the
QRPair's stored ``best_fitness`` / joint genome size.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from caformer.per_token_chain import ChainTrainConfig, train_per_token_chain


class Command(BaseCommand):
    help = 'Benchmark per-token quine-chain genome on a QRPair.'

    def add_arguments(self, parser):
        parser.add_argument('--pair', type=int, required=True,
                              help='QRPair pk to benchmark')
        parser.add_argument('--depth', type=int, default=64,
                              help='metachain depth (levels to scan)')
        parser.add_argument('--ticks', type=int, default=16,
                              help='ticks per metachain level')
        parser.add_argument('--bonus', type=float, default=5.0,
                              help='argmax bonus (match qr_trainer default)')
        parser.add_argument('--mode', choices=['ca_evolution', 'metachain'],
                              default='ca_evolution',
                              help='how to derive chain levels from origin '
                              '(metachain collapses on fixed-point quines)')
        parser.add_argument('--no-select', action='store_true',
                              help='skip per-token origin selection (faster, '
                              'untrained baseline)')
        parser.add_argument('--select-n', type=int, default=32,
                              help='candidates evaluated per token when selecting')
        parser.add_argument('--refine', type=int, default=0,
                              help='post-selection hill-climb flips per token '
                              '(0 = pure selection)')
        parser.add_argument('--refine-sample', type=int, default=64,
                              help='LUT positions sampled per hill-climb pass')
        parser.add_argument('--ga-gens', type=int, default=0,
                              help='per-token (μ+λ) ES generations (0 = skip)')
        parser.add_argument('--ga-mu', type=int, default=4)
        parser.add_argument('--ga-lam', type=int, default=8)
        parser.add_argument('--ga-mut-min', type=int, default=8)
        parser.add_argument('--ga-mut-max', type=int, default=64)

    def handle(self, *args, pair, depth, ticks, bonus, mode,
                 no_select, select_n, refine, refine_sample,
                 ga_gens, ga_mu, ga_lam, ga_mut_min, ga_mut_max, **opts):
        import sys
        from caformer.models import QRPair
        try:
            pr = QRPair.objects.get(pk=pair)
        except QRPair.DoesNotExist:
            raise CommandError(f'QRPair #{pair} not found')

        def _log(msg: str) -> None:
            sys.stdout.write(str(msg) + '\n')
            sys.stdout.flush()

        cfg = ChainTrainConfig(
            chain_depth=depth, ticks_per_level=ticks,
            chain_mode=mode, argmax_bonus=bonus,
            select_origins=not no_select, select_n=select_n,
            refine_flips=refine, refine_sample=refine_sample,
            ga_generations=ga_gens, ga_mu=ga_mu, ga_lam=ga_lam,
            ga_mut_min=ga_mut_min, ga_mut_max=ga_mut_max,
            log=_log,
        )

        self.stdout.write(self.style.NOTICE(
            f'\n=== per-token chain bench: pair #{pair} ==='))
        self.stdout.write(
            f'prompt:   {pr.prompt!r}\nexpected: {pr.expected!r}\n'
            f'n_blocks: {pr.n_blocks}   stored_best_fitness: {pr.best_fitness}\n')

        result = train_per_token_chain(pair, cfg=cfg)

        self.stdout.write('')
        self.stdout.write(self.style.NOTICE('--- summary ---'))
        self.stdout.write(
            f'total_fitness    : {result.total_fitness:+.3f}\n'
            f'argmax_matches   : {result.matches} / {len(result.positions)}\n'
            f'unique_tokens    : {result.n_unique_tokens}\n'
            f'stored joint fit : {pr.best_fitness}\n'
        )

        storage = result.storage_bytes()
        self.stdout.write(self.style.NOTICE('--- storage (bytes) ---'))
        self.stdout.write(
            f'per-token origins (packed) : {storage["per_token_origins_packed"]:>8,}\n'
            f'  + base rules (packed)    : {storage["base_rules_packed"]:>8,} (shared across pairs)\n'
            f'joint genome (raw)         : {storage["joint_genome_raw"]:>8,} (per-pair baseline)\n'
            f'per-position outputs (raw) : {storage["per_position_outputs_raw"]:>8,} (per-pair positional baseline)\n'
        )

        marginal = storage['per_token_origins_packed']
        positional = storage['per_position_outputs_raw']
        if positional > 0:
            self.stdout.write(
                f'\nmarginal per-pair: {marginal:,} B  '
                f'(positional baseline: {positional:,} B  → '
                f'{positional / max(marginal, 1):.1f}× smaller)')
