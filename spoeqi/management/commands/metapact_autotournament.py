"""manage.py metapact_autotournament — multi-round tournament with
sensible defaults that actually produce results.

Auto-includes existing Metapacts as contestants (use --no-include to
disable). Saves each round's champion as a new Metapact, with
``parent_seed`` pointing back so the lineage is preserved.

  manage.py metapact_autotournament
      # 4 rounds, 6 contestants, depth=6, chain_ticks=16, ~2-4 min

  manage.py metapact_autotournament --rounds 6 --contestants 8
      # bigger run

  manage.py metapact_autotournament --corpus path/to/probe.txt --label v3
      # custom probe corpus + custom run-label for save slugs
"""
from __future__ import annotations
from pathlib import Path

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Run a metapact tournament. Defaults pick a quick configuration '
            'that produces visible improvement; each round winner is saved '
            'as a new Metapact row.')

    def add_arguments(self, parser):
        parser.add_argument('--rounds',       type=int, default=4)
        parser.add_argument('--contestants',  type=int, default=6)
        parser.add_argument('--survivors',    type=int, default=2,
                            help='top-K per round that advance and get refined')
        parser.add_argument('--refine-gens',  type=int, default=5)
        parser.add_argument('--refine-pop',   type=int, default=6)
        parser.add_argument('--depth',        type=int, default=6)
        parser.add_argument('--chain-ticks',  type=int, default=16)
        parser.add_argument('--mutation-rate', type=float, default=0.003)
        parser.add_argument('--seed',         type=int, default=0xCAFE_7E)
        parser.add_argument('--corpus',       type=str, default='',
                            help='path to a .txt corpus; defaults to the '
                                 'built-in Hitchhiker+fox+Shakespeare blend')
        parser.add_argument('--label',        type=str, default='auto',
                            help='run label for save slugs '
                                 '(tournament-<label>-<round-tag>)')
        parser.add_argument('--no-include',   action='store_true',
                            help='start from random seeds — do not include '
                                 'existing Metapacts as contestants')
        parser.add_argument('--no-save',      action='store_true',
                            help='dry-run: do not save any new Metapact rows')
        parser.add_argument('--limit-include', type=int, default=6,
                            help='cap on existing Metapacts pulled in as seeds')

    def handle(self, **opts):
        from spoeqi.metapact_tournament import (
            TournamentConfig, run_tournament, save_round_winner,
        )
        from spoeqi.models import Metapact

        if opts['corpus']:
            corpus = Path(opts['corpus']).read_text(encoding='utf-8',
                                                       errors='replace')
        else:
            corpus = ''

        cfg = TournamentConfig(
            n_contestants=opts['contestants'],
            rounds=opts['rounds'],
            survivors_per_round=opts['survivors'],
            refine_generations=opts['refine_gens'],
            refine_pop=opts['refine_pop'],
            mutation_rate=opts['mutation_rate'],
            depth=opts['depth'],
            chain_ticks=opts['chain_ticks'],
            seed=opts['seed'],
            corpus=corpus,
            run_label=opts['label'],
            save_winners=not opts['no_save'],
        )

        contestants = []
        if not opts['no_include']:
            seeds = list(
                Metapact.objects.order_by('-final_leaf_fitness',
                                              '-final_chain_quality',
                                              '-created_at')
                                 [:opts['limit_include']]
                                 .values_list('seed_state', 'slug'))
            contestants = [bytes(s) for s, _ in seeds]
            slugs = [sl for _, sl in seeds]
            self.stdout.write(self.style.SUCCESS(
                f'seeding from {len(contestants)} existing metapact(s): '
                + ', '.join(slugs)))
        else:
            self.stdout.write('no-include: starting from random seeds')

        self.stdout.write(
            f'config: rounds={cfg.rounds} contestants={cfg.n_contestants} '
            f'survivors={cfg.survivors_per_round} '
            f'refine={cfg.refine_pop}p×{cfg.refine_generations}g '
            f'depth={cfg.depth} ticks={cfg.chain_ticks}')

        # ── Streaming progress to stdout ─────────────────────────
        prev_champion_seed = None  # for parent_seed lineage

        def _print_event(kind, payload):
            elapsed = payload.get('elapsed_ms', 0) / 1000.0
            if kind == 'tournament_begin':
                self.stdout.write(
                    f'[{elapsed:6.1f}s] tournament begin · {payload!r}')
            elif kind == 'round_begin':
                self.stdout.write(
                    f'[{elapsed:6.1f}s] ── round {payload["round"]} '
                    f'({payload["tag"]}) · {payload["contestants"]} contestants')
            elif kind == 'score':
                self.stdout.write(
                    f'[{elapsed:6.1f}s]   score r{payload["round"]} '
                    f'#{payload["idx"]}: '
                    f'fit={payload["fitness"]:.4f} '
                    f'(chain {payload["chain_q"]:.3f}, '
                    f'leaf {payload["leaf_logprob"]:+.3f})')
            elif kind == 'round_end':
                self.stdout.write(self.style.SUCCESS(
                    f'[{elapsed:6.1f}s] ✓ round {payload["round"]} champion '
                    f'fit={payload["champion_fitness"]:.4f} '
                    f'(chain {payload["champion_chain_q"]:.3f}, '
                    f'leaf {payload["champion_leaf_logprob"]:+.3f}, '
                    f'mean {payload["mean_fitness"]:.4f})'))
            elif kind == 'refine_begin':
                self.stdout.write(
                    f'[{elapsed:6.1f}s]   refine r{payload["round"]} '
                    f'survivor {payload["survivor"]} · '
                    f'{cfg.refine_pop}p × {cfg.refine_generations}g')
            elif kind == 'refine_progress':
                self.stdout.write(
                    f'[{elapsed:6.1f}s]     gen {payload["gen"]} '
                    f'best={payload["best"]:.4f} '
                    f'mean={payload["mean"]:.4f}')
            elif kind == 'refine_end':
                self.stdout.write(
                    f'[{elapsed:6.1f}s]   refine done: '
                    f'best={payload["refined_fitness"]:.4f}')
            elif kind == 'tournament_end':
                self.stdout.write(self.style.SUCCESS(
                    f'[{elapsed:6.1f}s] ★ tournament end · '
                    f'winner fit={payload["winner_fitness"]:.4f} '
                    f'(chain {payload["winner_chain_q"]:.3f}, '
                    f'leaf {payload["winner_leaf_logprob"]:+.3f})'))

        saved_slugs = []

        def _save(round_idx, report):
            nonlocal prev_champion_seed
            try:
                m = save_round_winner(
                    report, cfg=cfg, run_label=opts['label'],
                    prior_champion_seed=prev_champion_seed)
            except Exception as e:
                self.stderr.write(
                    self.style.ERROR(f'save failed: {e!r}'))
                return
            saved_slugs.append(m.slug)
            prev_champion_seed = report.champion_seed
            self.stdout.write(
                self.style.SUCCESS(
                    f'    saved round {round_idx} champion as Metapact '
                    f'slug={m.slug!r} (class4_depth={m.final_class4_depth})'))

        result = run_tournament(
            cfg=cfg, contestants=contestants,
            on_event=_print_event,
            on_save_winner=_save if cfg.save_winners else None,
        )

        self.stdout.write(self.style.SUCCESS(
            '\nDONE — '
            f'overall winner fit={result.winner_fitness:.4f} · '
            f'elapsed {result.elapsed_seconds:.1f}s · '
            f'{len(saved_slugs)} winner(s) saved'))
        if saved_slugs:
            self.stdout.write('  ' + ' → '.join(saved_slugs))
