"""det evolve_hexca — headless port of the planned ``hexca`` gene
handler from evolution/engine.mjs.

Runs an evolutionary GA over hex-CA rulesets, scoring each candidate
with Det's Class-4 scorer (``det.search._score``). Unlike
``det_search`` — which samples random rulesets independently — this
command keeps a population and lets mutation + crossover steer
generations toward higher scores.

Typical uses:

  * ``manage.py evolve_hexca`` — 3-color sweep, 40 gens, 24 pop
  * ``manage.py evolve_hexca --from-candidate 42 --gens 80`` — seed
    from an existing Det Candidate and try to improve on it
  * ``manage.py evolve_hexca --promote`` — save the best gene back as
    a Det Candidate + an automaton.RuleSet (interactive run page)

Mirrors the interface and expected behaviour of ``evolve_lut`` and
``naiad_evolve`` so the same conventions carry across headless
runners.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from det import hexca_ga
from det.models import Candidate, SearchRun
from det.search import _rules_hash


class Command(BaseCommand):
    help = ('Evolve hex-CA rulesets toward higher Class-4 (edge-of-chaos) '
            'score. Headless port of the hexca gene-type in engine.mjs.')

    def add_arguments(self, parser):
        parser.add_argument('--n-colors', type=int, default=3,
            help='Cell colors, 2..4 (default 3).')
        parser.add_argument('--rules', type=int, default=60,
            help='Initial rules per ruleset (default 60).')
        parser.add_argument('--min-rules', type=int, default=20,
            help='Lower bound enforced by mutate/crossover (default 20).')
        parser.add_argument('--max-rules', type=int, default=140,
            help='Upper bound enforced by mutate/crossover (default 140).')
        parser.add_argument('--wildcards', type=int, default=30,
            help='Wildcard percentage for new neighbors (default 30).')
        parser.add_argument('--width',   type=int, default=18)
        parser.add_argument('--height',  type=int, default=16)
        parser.add_argument('--horizon', type=int, default=60)

        parser.add_argument('--pop', type=int, default=24,
            help='Population size (default 24).')
        parser.add_argument('--gens', type=int, default=40,
            help='Generations to run (default 40).')
        parser.add_argument('--mutation-rate', type=float, default=0.7,
            help='Probability a mutation operator fires per child '
                 '(default 0.7 — mutation is the main operator here '
                 'because each operator only changes a small number of '
                 'bits).')
        parser.add_argument('--tournament-k', type=int, default=3,
            help='Selection tournament size (default 3).')

        parser.add_argument('--seed', type=int, default=None,
            help='RNG seed for reproducibility. Drives both the '
                 'population-creation RNG and the grid_seed label.')
        parser.add_argument('--grid-seed', default=None,
            help='Explicit grid seed string. If omitted, derived from '
                 'the run start timestamp (or --seed).')
        parser.add_argument('--from-candidate', type=int, default=None,
            dest='from_candidate',
            help='Det Candidate pk to seed the initial population with. '
                 'The candidate itself is placed at index 0; the rest '
                 'of the pop is random.')
        parser.add_argument('--promote', action='store_true',
            help='After the run, save the best gene as a Det Candidate '
                 '(and a fresh SearchRun to hold it).')
        parser.add_argument('--promote-automaton', action='store_true',
            dest='promote_automaton',
            help='If --promote is set, also call det.search.promote() to '
                 'mirror the ruleset into automaton.RuleSet + '
                 'Simulation so it can be run interactively.')
        parser.add_argument('--export-json', default='',
            dest='export_json',
            help='Write the best gene + history to this path.')

    def handle(self, *args, **opts):
        if opts['seed'] is not None:
            random.seed(opts['seed'])
        rng = random.Random(opts['seed'])

        n_colors = int(opts['n_colors'])
        if not 2 <= n_colors <= 4:
            raise CommandError('--n-colors must be 2..4.')

        grid_seed = opts['grid_seed'] or (
            f'evolve-hexca-{opts["seed"]}' if opts['seed'] is not None
            else timezone.now().strftime('evolve-hexca-%Y%m%d-%H%M%S')
        )

        seed_genes = []
        seed_candidate = None
        if opts['from_candidate'] is not None:
            try:
                seed_candidate = Candidate.objects.get(pk=opts['from_candidate'])
            except Candidate.DoesNotExist:
                raise CommandError(
                    f'No Det Candidate with pk={opts["from_candidate"]}.')
            seed_genes.append({
                'rules': [dict(r, n=list(r['n'])) for r in seed_candidate.rules_json],
                'n_colors': seed_candidate.run.n_colors,
            })
            if seed_candidate.run.n_colors != n_colors:
                self.stdout.write(self.style.WARNING(
                    f'Seed candidate uses n_colors='
                    f'{seed_candidate.run.n_colors}, but --n-colors='
                    f'{n_colors}. Using the candidate\'s value for '
                    f'consistency.'
                ))
                n_colors = seed_candidate.run.n_colors

        self.stdout.write(self.style.NOTICE(
            f'evolve_hexca: n_colors={n_colors} pop={opts["pop"]} '
            f'gens={opts["gens"]} rate={opts["mutation_rate"]} '
            f'grid_seed={grid_seed!r}'
            + (f' seed_candidate=#{seed_candidate.pk}'
               if seed_candidate else '')
        ))

        def progress(gen, total, best):
            if gen == total or gen % max(1, total // 10) == 0:
                self.stdout.write(f'    gen {gen:>4}/{total}  best={best:.3f}')

        result = hexca_ga.run_ga(
            n_colors=n_colors,
            n_rules=opts['rules'],
            wildcard_pct=opts['wildcards'],
            W=opts['width'], H=opts['height'], horizon=opts['horizon'],
            population=opts['pop'],
            generations=opts['gens'],
            mutation_rate=opts['mutation_rate'],
            tournament_k=opts['tournament_k'],
            min_rules=opts['min_rules'],
            max_rules=opts['max_rules'],
            grid_seed=grid_seed,
            seed_genes=seed_genes,
            progress=progress,
            rng=rng,
        )

        best_gene = result['best_gene']
        best_res  = result['best_result']
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'done. best score={best_res["score"]:.3f}  '
            f'class={best_res["est_class"]}  '
            f'rules={len(best_gene["rules"])}  '
            f'hash={best_res["rules_hash"][:10]}'
        ))

        a = best_res['analysis']
        self.stdout.write(
            f'  activity_tail={a["activity_tail"]}  '
            f'block_entropy={a["block_entropy"]}  '
            f'period={a["period"]}  '
            f'color_diversity={a["color_diversity"]}'
        )

        if opts['promote']:
            run = SearchRun.objects.create(
                label=f'evolve_hexca {grid_seed}',
                n_colors=n_colors,
                n_candidates=1,
                n_rules_per_candidate=len(best_gene['rules']),
                wildcard_pct=opts['wildcards'],
                screen_width=opts['width'],
                screen_height=opts['height'],
                horizon=opts['horizon'],
                seed=grid_seed,
                status='finished',
            )
            run.started_at = timezone.now()
            run.finished_at = timezone.now()
            run.save()
            cand = Candidate.objects.create(
                run=run,
                rules_json=best_gene['rules'],
                n_rules=len(best_gene['rules']),
                rules_hash=_rules_hash(best_gene['rules']),
                score=best_res['score'],
                est_class=best_res['est_class'],
                analysis=best_res['analysis'],
            )
            self.stdout.write(self.style.SUCCESS(
                f'  promoted to Det Candidate #{cand.pk} '
                f'(SearchRun #{run.pk}).'
            ))
            if opts['promote_automaton']:
                from det.search import promote
                rs = promote(cand)
                self.stdout.write(self.style.SUCCESS(
                    f'  also mirrored to automaton.RuleSet "{rs.name}" '
                    f'(pk {rs.pk}).'
                ))

        if opts['export_json']:
            path = Path(opts['export_json'])
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                'generated_at': timezone.now().isoformat(),
                'params': {
                    'n_colors': n_colors,
                    'rules': opts['rules'],
                    'min_rules': opts['min_rules'],
                    'max_rules': opts['max_rules'],
                    'wildcards': opts['wildcards'],
                    'width': opts['width'], 'height': opts['height'],
                    'horizon': opts['horizon'],
                    'pop': opts['pop'], 'gens': opts['gens'],
                    'mutation_rate': opts['mutation_rate'],
                    'tournament_k': opts['tournament_k'],
                    'grid_seed': grid_seed,
                    'seed': opts['seed'],
                    'from_candidate': (seed_candidate.pk
                                       if seed_candidate else None),
                },
                'best': {
                    'gene':   best_gene,
                    'score':  best_res['score'],
                    'est_class': best_res['est_class'],
                    'analysis': best_res['analysis'],
                    'rules_hash': best_res['rules_hash'],
                },
                'history': result['history'],
            }
            path.write_text(json.dumps(payload, separators=(',', ':')))
            self.stdout.write(self.style.SUCCESS(
                f'  wrote JSON snapshot to {path}.'
            ))
