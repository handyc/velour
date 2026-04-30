"""Run a hex-CA tournament against a HuntCorpus, persist the leaderboard.

Usage:
    manage.py hexhunt_run <corpus_slug> \\
        --pop 256 --gens 200 --windows 8 --score gzip --seed 1

Stores top-N rules as HuntRule rows, the run itself as a HuntRun, and
links the best rule as ``run.top_rule``.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone as djtz

from helix.hexhunt import engine
from helix.hexhunt.tournament import (
    TournamentParams, run_tournament,
)
from helix.models import HuntCorpus, HuntRule, HuntRun


class Command(BaseCommand):
    help = 'Evolve hex CA rules against a HuntCorpus.'

    def add_arguments(self, parser):
        parser.add_argument('corpus_slug')
        parser.add_argument('--pop', type=int, default=256)
        parser.add_argument('--gens', type=int, default=200)
        parser.add_argument('--windows', type=int, default=8,
                            help='Windows scored per generation.')
        parser.add_argument('--mutation', type=float, default=0.001)
        parser.add_argument('--crossover', type=float, default=0.20)
        parser.add_argument('--survivors', type=float, default=0.25)
        parser.add_argument('--score', default='edge')
        parser.add_argument('--steps', type=int, default=engine.TOTAL_STEPS)
        parser.add_argument('--seed', type=int, default=0)
        parser.add_argument('--keep-top', type=int, default=10,
                            help='How many top rules to persist as HuntRule.')
        parser.add_argument('--neg-corpus', default='',
                            help='Slug of a negative corpus. When set, '
                                 'fitness becomes mean(pos) - mean(neg) — '
                                 'the discriminator mode.')

    def handle(self, *args, **opts):
        try:
            corpus = HuntCorpus.objects.get(slug=opts['corpus_slug'])
        except HuntCorpus.DoesNotExist:
            raise CommandError(f'no HuntCorpus with slug={opts["corpus_slug"]!r}')

        windows = list(corpus.windows.select_related('record').order_by('idx'))
        if not windows:
            raise CommandError(f'corpus {corpus.slug!r} has no windows')
        seqs = [w.sequence() for w in windows]

        neg_corpus = None
        neg_seqs = None
        if opts['neg_corpus']:
            try:
                neg_corpus = HuntCorpus.objects.get(slug=opts['neg_corpus'])
            except HuntCorpus.DoesNotExist:
                raise CommandError(
                    f'no negative HuntCorpus with slug={opts["neg_corpus"]!r}'
                )
            neg_windows = list(
                neg_corpus.windows.select_related('record').order_by('idx')
            )
            if not neg_windows:
                raise CommandError(f'negative corpus {neg_corpus.slug!r} has no windows')
            neg_seqs = [w.sequence() for w in neg_windows]
            min_windows = min(len(seqs), len(neg_seqs))
        else:
            min_windows = len(seqs)

        params = TournamentParams(
            population_size=opts['pop'],
            generations=opts['gens'],
            windows_per_gen=min(opts['windows'], min_windows),
            mutation_rate=opts['mutation'],
            crossover_fraction=opts['crossover'],
            survivor_fraction=opts['survivors'],
            scoring_fn=opts['score'],
            steps=opts['steps'],
            rng_seed=opts['seed'],
        )

        params_dict = dict(params.__dict__)
        if neg_corpus:
            params_dict['neg_corpus'] = neg_corpus.slug
            params_dict['mode'] = 'discriminator'
        else:
            params_dict['mode'] = 'single'

        run = HuntRun.objects.create(
            slug=HuntRun.make_slug(),
            corpus=corpus,
            params_json=params_dict,
            status='running',
            started_at=djtz.now(),
        )

        self.stdout.write(
            f'Run {run.slug}: {params.population_size} pop × '
            f'{params.generations} gens × {params.windows_per_gen} windows '
            f'(score={params.scoring_fn}, steps={params.steps}, seed={params.rng_seed})'
        )
        if neg_corpus:
            self.stdout.write(
                f'  discriminator mode: pos={corpus.slug} ({len(seqs)} windows) '
                f'vs neg={neg_corpus.slug} ({len(neg_seqs)} windows). '
                f'Fitness = mean(pos) - mean(neg).'
            )

        try:
            def progress(g):
                if g.pos_mean is not None:
                    self.stdout.write(
                        f'  gen {g.gen:>4d}: fit={g.best:+.4f} '
                        f'mean={g.mean:+.4f} pos={g.pos_mean:.4f} '
                        f'neg={g.neg_mean:.4f}  ({g.elapsed_s*1000:.0f} ms)'
                    )
                else:
                    self.stdout.write(
                        f'  gen {g.gen:>4d}: best={g.best:.4f} '
                        f'mean={g.mean:.4f}  ({g.elapsed_s*1000:.0f} ms)'
                    )

            result = run_tournament(
                seqs, params,
                on_generation=progress,
                neg_corpus_sequences=neg_seqs,
            )
        except Exception as e:
            run.status = 'failed'
            run.notes = f'{type(e).__name__}: {e}'
            run.finished_at = djtz.now()
            run.save()
            raise

        # Persist top-K rules as HuntRule rows; link best as top_rule.
        keep = min(opts['keep_top'], len(result.final_population))
        is_disc = bool(neg_corpus)
        with transaction.atomic():
            top_rule_obj = None
            scoreboard = []
            for rank in range(keep):
                pr = result.final_population[rank]
                score = result.final_scores[rank]
                provenance = {
                    'origin':    'tournament_winner',
                    'run_slug':  run.slug,
                    'corpus':    corpus.slug,
                    'rank':      rank + 1,
                    'score':     score,
                    'scoring':   params.scoring_fn,
                }
                row = {
                    'rank':      rank + 1,
                    'score':     score,
                }
                if is_disc:
                    pos = result.final_pos_scores[rank]
                    neg = result.final_neg_scores[rank]
                    provenance['mode'] = 'discriminator'
                    provenance['neg_corpus'] = neg_corpus.slug
                    provenance['pos_score'] = pos
                    provenance['neg_score'] = neg
                    row['pos'] = pos
                    row['neg'] = neg
                rule = HuntRule.objects.create(
                    slug=HuntRule.make_slug(),
                    table=bytes(pr.data),
                    name=f'{run.slug}#{rank+1:02d}',
                    provenance_json=provenance,
                )
                row['rule_slug'] = rule.slug
                if rank == 0:
                    top_rule_obj = rule
                scoreboard.append(row)

            run.top_rule = top_rule_obj
            run.scoreboard_json = scoreboard
            run.generation_log_json = [
                {
                    'gen': g.gen, 'best': g.best, 'mean': g.mean,
                    'elapsed_s': g.elapsed_s,
                    **({'pos_mean': g.pos_mean, 'neg_mean': g.neg_mean}
                       if g.pos_mean is not None else {}),
                }
                for g in result.log
            ]
            run.status = 'done'
            run.finished_at = djtz.now()
            run.save()

        self.stdout.write(self.style.SUCCESS(
            f'Run {run.slug} done. Top score {scoreboard[0]["score"]:.4f}, '
            f'kept {keep} rules.'
        ))
