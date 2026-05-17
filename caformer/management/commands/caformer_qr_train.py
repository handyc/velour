"""manage.py caformer_qr_train — long-running Q→R trainer.

Targets a single QRPair (or all not-yet-exact pairs in round-robin)
and evolves the CAformer to produce ``expected`` byte-for-byte from
``prompt``.

Designed for hours-long background runs under supervisor / nohup.
Every improvement persists the best genome straight to the QRPair row
so you can chat with the in-progress weights from any browser tab.

  manage.py caformer_qr_train --pair-id 1 --hours 1
  manage.py caformer_qr_train --pair-slug hi-hello --hours 4 --pop 32
  manage.py caformer_qr_train --all-pending --hours 8

Exit when the budget elapses OR (single-pair mode) the pair reaches
exact-match.
"""
from __future__ import annotations
import time

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ('Long-running Q→R trainer. Persists checkpoints to the '
            'QRPair row on every improvement so you can chat with the '
            'in-progress weights any time.')

    def add_arguments(self, parser):
        parser.add_argument('--pair-id',     type=int, default=None,
                            help='train this specific QRPair (by pk)')
        parser.add_argument('--prompt',      type=str, default=None,
                            help='create-and-train: train the pair with '
                                 'this prompt + --expected, creating it '
                                 'if it doesn\'t exist')
        parser.add_argument('--expected',    type=str, default=None,
                            help='expected response for --prompt (only '
                                 'meaningful with --prompt)')
        parser.add_argument('--n-blocks',    type=int, default=1,
                            help='caformer block count for new pairs')
        parser.add_argument('--all-pending', action='store_true',
                            help='round-robin every QRPair where '
                                 'best_exact=False until budget expires')
        parser.add_argument('--hours',       type=float, default=1.0,
                            help='wall-clock budget')
        parser.add_argument('--pop',         type=int, default=24)
        parser.add_argument('--gens',        type=int, default=24,
                            help='GA generations per burst')
        parser.add_argument('--mutation',    type=float, default=0.012)
        parser.add_argument('--polish',      type=int, default=150,
                            help='polish trials per burst')
        parser.add_argument('--bonus',       type=float, default=4.0,
                            help='argmax-match bonus per byte')
        parser.add_argument('--stall',       type=int, default=3,
                            help='non-improving bursts → random restart')
        parser.add_argument('--seed',        type=int, default=0xCAFEBABE)
        parser.add_argument('--label',       type=str, default='cli')
        parser.add_argument('--positional',  action='store_true',
                            help='Per-position output rules: random fixed '
                                 'base + N evolved output rules (one per '
                                 'target byte). Tractable on multi-byte '
                                 'targets — each phase is a single-byte '
                                 'problem the GA can crack in seconds.')

    def handle(self, **opts):
        from caformer.models import QRPair
        from caformer.qr_trainer import (TrainConfig, train_pair,
                                            PositionalTrainConfig,
                                            train_pair_positional)

        # Resolve which pair(s) to train.
        pairs = []
        if opts['pair_id']:
            pair = QRPair.objects.filter(pk=opts['pair_id']).first()
            if pair is None:
                raise CommandError(f'no QRPair pk={opts["pair_id"]}')
            pairs.append(pair)
        elif opts['prompt'] and opts['expected'] is not None:
            pair = QRPair.objects.filter(
                prompt=opts['prompt'],
                expected=opts['expected']).first()
            if pair is None:
                pair = QRPair.objects.create(
                    prompt=opts['prompt'],
                    expected=opts['expected'],
                    n_blocks=opts['n_blocks'],
                    label=opts['label'])
                self.stdout.write(self.style.SUCCESS(
                    f'created QRPair pk={pair.pk} {pair.prompt!r} → '
                    f'{pair.expected!r}'))
            pairs.append(pair)
        elif opts['all_pending']:
            pairs = list(QRPair.objects.filter(best_exact=False))
            if not pairs:
                self.stdout.write('no pending QRPair rows (best_exact=False); '
                                    'either add some with --prompt/--expected '
                                    'or via the /caformer/qr/ UI')
                return
        else:
            raise CommandError('need one of --pair-id, --prompt+--expected, or --all-pending')

        budget = opts['hours'] * 3600.0
        t_start = time.time()
        per_pair_budget = budget / max(1, len(pairs))

        def _event(kind, payload):
            elapsed = payload.get('elapsed_s', 0)
            if kind == 'start':
                self.stdout.write(self.style.SUCCESS(
                    f'\n→ pair {payload["pair_id"]} '
                    f'{payload["prompt"]!r} → {payload["expected"]!r}  '
                    f'init fit={payload["initial_fitness"]:+.3f}  '
                    f'budget={payload["max_seconds"]:.0f}s'))
            elif kind == 'burst_begin':
                self.stdout.write(
                    f'  burst {payload["burst"]} '
                    f'(restart {payload["restarts"]}) · '
                    f'template fit={payload["template_fitness"]:+.3f}')
            elif kind == 'improved':
                self.stdout.write(self.style.SUCCESS(
                    f'  [{elapsed:6.1f}s] {payload["phase"]:7s} '
                    f'improved → fit={payload["fitness"]:+.4f}  '
                    f'out={payload["output"]!r}  '
                    f'{"✓ EXACT" if payload["exact"] else ""}'))
            elif kind == 'polish_end':
                self.stdout.write(
                    f'  polish: {payload["n_improvements"]} '
                    f'flips, fit={payload["fitness"]:+.4f}')
            elif kind == 'restart':
                self.stdout.write(self.style.WARNING(
                    f'  RESTART #{payload["restart_idx"]} (stall) · '
                    f'best so far: {payload["overall_best_fitness"]:+.4f}'))
            elif kind == 'done':
                tag = '✓ EXACT' if payload['exact'] else '(budget out)'
                self.stdout.write(self.style.SUCCESS(
                    f'  DONE pair {payload["pair_id"]}: {tag}  '
                    f'fit={payload["overall_best_fitness"]:+.4f}  '
                    f'bursts={payload["bursts"]}  '
                    f'restarts={payload["restarts"]}  '
                    f'final out={payload["final_output"]!r}  '
                    f'({elapsed:.1f}s)'))

        # Positional event handlers (only used in --positional mode).
        def _pevent(kind, payload):
            es = payload.get('elapsed_s', 0)
            if kind == 'positional_start':
                self.stdout.write(self.style.SUCCESS(
                    f'\n→ POSITIONAL pair {payload["pair_id"]} '
                    f'{payload["prompt"]!r} → {payload["expected"]!r}  '
                    f'{payload["n_positions"]} positions  '
                    f'budget={payload["budget_s"]:.0f}s'))
            elif kind == 'phase_begin':
                self.stdout.write(
                    f'  [{es:6.1f}s] pos {payload["pos"]} '
                    f'target={payload["target_char"]!r}')
            elif kind == 'phase_end':
                mark = '✓' if payload['match'] else '✗'
                self.stdout.write(self.style.SUCCESS(
                    f'  [{es:6.1f}s]   pos {payload["pos"]} '
                    f'argmax={payload["argmax_char"]!r:8s} '
                    f'fit={payload["fitness"]:+.3f} {mark}  '
                    f'({payload["phase_s"]:.1f}s)'))
            elif kind == 'phase_failed':
                self.stdout.write(self.style.WARNING(
                    f'  ! pos {payload["pos"]} did not converge: '
                    f'{payload["note"]}'))
            elif kind == 'positional_done':
                tag = ('✓ EXACT MATCH' if payload.get('exact')
                        else '(partial / budget out)')
                self.stdout.write(self.style.SUCCESS(
                    f'  DONE  {tag}  sampled='
                    f'{payload.get("sampled", "?")!r}  '
                    f'target={payload.get("target", "?")!r}  '
                    f'({es:.1f}s)'))

        # Round-robin training across pairs.
        if opts['positional']:
            pcfg_kwargs = dict(
                pop_size=opts['pop'], gens_per_phase=opts['gens'],
                polish_trials=opts['polish'],
                mutation_rate=opts['mutation'],
                argmax_bonus=opts['bonus'],
                base_seed=opts['seed'],
                out_seed=opts['seed'] ^ 0xC0FFEE,
            )
            for pair in pairs:
                if time.time() - t_start >= budget:
                    break
                remaining = budget - (time.time() - t_start)
                this_budget = min(per_pair_budget, remaining)
                cfg = PositionalTrainConfig(max_seconds=this_budget,
                                              **pcfg_kwargs)
                train_pair_positional(pair.pk, cfg=cfg, on_event=_pevent)
        else:
            cfg_kwargs = dict(
                pop_size=opts['pop'], gens_per_burst=opts['gens'],
                mutation_rate=opts['mutation'], polish_trials=opts['polish'],
                argmax_bonus=opts['bonus'], stall_patience=opts['stall'],
                base_seed=opts['seed'],
            )
            for pair in pairs:
                if time.time() - t_start >= budget:
                    break
                remaining = budget - (time.time() - t_start)
                this_budget = min(per_pair_budget, remaining)
                cfg = TrainConfig(max_seconds=this_budget, **cfg_kwargs)
                train_pair(pair.pk, cfg=cfg, on_event=_event)

        self.stdout.write(self.style.SUCCESS(
            f'\nall done in {time.time() - t_start:.1f}s'))
