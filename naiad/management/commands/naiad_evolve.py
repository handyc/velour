"""Server-side GA over a Naiad System's stage chain.

Mirrors the JS evolution engine (evolution/static/evolution/engine.mjs
`naiadWork`) so a run from the CLI produces the same scoring landscape
as the /naiad/<slug>/evolve/ lab page. Useful for batch experiments,
reproducibility (via --seed), and headless probing of whether a given
target is reachable with the current stage catalog.

Usage:
    manage.py naiad_evolve urine-to-drinking --pop 60 --gens 120
    manage.py naiad_evolve urine-to-drinking --seed 42 --save urine-v2
    manage.py naiad_evolve urine-to-drinking --via-conduit local-shell
    manage.py naiad_evolve urine-to-drinking --gens 400 \\
        --via-conduit alice-manual

With --via-conduit, the GA does NOT run in this process. Instead we
package the same invocation (minus --via-conduit) into a Conduit Job
aimed at the named JobTarget: a `shell` job for local/vps, a
`slurm_script` job (sbatch) for slurm/slurm_manual. ALICE prohibits
automated sbatch, so an alice-manual dispatch materialises a
JobHandoff the user hand-submits. Remote runs operate on the remote
machine's velour checkout + its own SQLite; --save there persists
only remotely (round-tripping results is a later-phase concern).
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from naiad.evolve_dispatch import DispatchError, dispatch_via_conduit
from naiad.models import Stage, StageType, System


@dataclass
class Ctx:
    source: dict
    target: dict
    types:  dict   # slug -> StageType
    slugs:  list
    # Weights match the JS defaults.
    cost_cap:   float = 300.0
    watt_cap:   float = 200.0
    length_cap: float = 12.0
    maint_cap:  float = 0.1
    w_cost:     float = 0.40
    w_watt:     float = 0.25
    w_length:   float = 0.20
    w_maint:    float = 0.15
    detection_eps: float = 1e-6


def simulate(stages: list[str], ctx: Ctx) -> dict:
    current = dict(ctx.source)
    for slug in stages:
        st = ctx.types.get(slug)
        if st is None:
            continue
        for key, value in list(current.items()):
            frac = float((st.removal or {}).get(key, 0.0) or 0.0)
            if frac <= 0:
                continue
            frac = min(max(frac, 0.0), 1.0)
            current[key] = value * (1.0 - frac)
    return current


def score(stages: list[str], ctx: Ctx) -> tuple[float, bool, list[str], dict]:
    output = simulate(stages, ctx)
    all_pass = True
    failures: list[str] = []
    ratio_product = 1.0
    ratio_count = 0
    for key, lim_raw in ctx.target.items():
        try:
            lim = float(lim_raw)
        except (TypeError, ValueError):
            continue
        if key not in output:
            continue
        if lim <= 0:
            lim = ctx.detection_eps
        out = output[key]
        if out <= lim:
            continue
        all_pass = False
        failures.append(key)
        ratio = lim / max(out, lim * 1e-12)
        ratio_product *= max(1e-6, min(1.0, ratio))
        ratio_count += 1

    total_cost = total_watts = maint_load = 0.0
    for slug in stages:
        st = ctx.types.get(slug)
        if st is None:
            continue
        total_cost  += float(st.cost_eur or 0)
        total_watts += float(st.energy_watts or 0)
        days = max(1.0, float(st.maintenance_days or 365))
        maint_load += 1.0 / days

    cost_pen  = min(1.0, total_cost  / ctx.cost_cap)
    watt_pen  = min(1.0, total_watts / ctx.watt_cap)
    len_pen   = min(1.0, len(stages) / ctx.length_cap)
    maint_pen = min(1.0, maint_load  / ctx.maint_cap)
    penalty = (ctx.w_cost   * cost_pen  + ctx.w_watt   * watt_pen +
               ctx.w_length * len_pen   + ctx.w_maint  * maint_pen)

    if all_pass:
        s = 0.5 + 0.5 * (1 - penalty)
    else:
        geo = (ratio_product ** (1.0 / ratio_count)) if ratio_count else 0.0
        s = 0.5 * geo

    stats = {
        'cost': total_cost, 'watts': total_watts,
        'length': len(stages), 'maint_load': maint_load,
        'output': output,
    }
    return max(0.0, min(1.0, s)), all_pass, failures, stats


# ── GA operators ────────────────────────────────────────────────────
def random_gene(rng: random.Random, ctx: Ctx) -> list[str]:
    n = rng.randint(2, 6)
    return [rng.choice(ctx.slugs) for _ in range(n)]


def mutate(gene: list[str], rng: random.Random, rate: float, ctx: Ctx) -> list[str]:
    g = list(gene)
    # substitute
    for i in range(len(g)):
        if rng.random() < rate:
            g[i] = rng.choice(ctx.slugs)
    # insert
    if rng.random() < rate and len(g) < ctx.length_cap:
        g.insert(rng.randrange(len(g) + 1), rng.choice(ctx.slugs))
    # delete
    if rng.random() < rate and len(g) > 1:
        g.pop(rng.randrange(len(g)))
    # swap-adjacent
    if rng.random() < rate and len(g) >= 2:
        i = rng.randrange(len(g) - 1)
        g[i], g[i + 1] = g[i + 1], g[i]
    return g


def crossover(a: list[str], b: list[str], rng: random.Random) -> list[str]:
    if not a: return list(b)
    if not b: return list(a)
    pa = 1 + rng.randrange(max(1, len(a) - 1))
    pb = 1 + rng.randrange(max(1, len(b) - 1))
    return a[:pa] + b[pb:]


def tournament(pop, fitness, rng, k=3):
    idxs = [rng.randrange(len(pop)) for _ in range(k)]
    best = idxs[0]
    for i in idxs[1:]:
        if fitness[i] > fitness[best]:
            best = i
    return pop[best]


class Command(BaseCommand):
    help = 'Run the Naiad gene-evolution GA on a System, server-side.'

    def add_arguments(self, parser):
        parser.add_argument('system_slug')
        parser.add_argument('--pop', type=int, default=60)
        parser.add_argument('--gens', type=int, default=120)
        parser.add_argument('--rate', type=float, default=0.25,
                            help='Mutation rate per position.')
        parser.add_argument('--crossover', type=float, default=0.7,
                            help='Crossover probability per child.')
        parser.add_argument('--elite', type=int, default=2,
                            help='Carry top-N unchanged each generation.')
        parser.add_argument('--seed', type=int, default=None)
        parser.add_argument('--every', type=int, default=10,
                            help='Print stats every N generations.')
        parser.add_argument('--save', default=None,
                            help='If set, save the winner as a new System '
                                 'with this slug.')
        parser.add_argument('--via-conduit', metavar='TARGET_SLUG',
                            dest='via_conduit', default=None,
                            help='Dispatch this run through Conduit on the '
                                 'given JobTarget (e.g. local-shell, '
                                 'alice-manual) instead of executing '
                                 'inline.')

    def handle(self, *args, **opts):
        slug = opts['system_slug']
        try:
            system = System.objects.select_related(
                'source', 'target').get(slug=slug)
        except System.DoesNotExist:
            raise CommandError(f'No System with slug {slug!r}')
        if not system.target:
            raise CommandError(
                f'System {slug!r} has no target profile — nothing to '
                f'score against.')

        if opts.get('via_conduit'):
            self._dispatch_via_conduit(
                system, target_slug=opts['via_conduit'], opts=opts)
            return

        types = {st.slug: st for st in StageType.objects.all()}
        ctx = Ctx(
            source = dict(system.source.values or {}),
            target = dict(system.target.values or {}),
            types  = types,
            slugs  = sorted(types.keys()),
        )

        rng = random.Random(opts['seed'])
        pop = [random_gene(rng, ctx) for _ in range(opts['pop'])]
        fit_scores = [score(g, ctx) for g in pop]
        best_gene: list[str] = []
        best_score = -1.0
        best_meta = None

        self.stdout.write(
            f'Evolving {system.name}  ({len(ctx.slugs)} stage types, '
            f'pop={opts["pop"]}, gens={opts["gens"]}, '
            f'seed={opts["seed"]})')
        self.stdout.write(f'Source : {system.source.slug}')
        self.stdout.write(f'Target : {system.target.slug}')
        self.stdout.write('')

        for gen in range(opts['gens']):
            # rank
            order = sorted(range(len(pop)),
                           key=lambda i: fit_scores[i][0], reverse=True)
            ranked_pop = [pop[i] for i in order]
            ranked_fit = [fit_scores[i][0] for i in order]
            ranked_meta = [fit_scores[i] for i in order]

            if ranked_fit[0] > best_score:
                best_score = ranked_fit[0]
                best_gene = list(ranked_pop[0])
                best_meta = ranked_meta[0]

            mean = sum(ranked_fit) / len(ranked_fit)
            if gen % opts['every'] == 0 or gen == opts['gens'] - 1:
                passed_n = sum(1 for m in ranked_meta if m[1])
                self.stdout.write(
                    f'gen {gen:4d}  best={ranked_fit[0]:.4f}  '
                    f'mean={mean:.4f}  passing={passed_n}/{len(pop)}  '
                    f'best_len={len(ranked_pop[0])}')

            # breed
            new_pop = [list(ranked_pop[i]) for i in range(opts['elite'])]
            while len(new_pop) < opts['pop']:
                pa = tournament(ranked_pop, ranked_fit, rng)
                pb = tournament(ranked_pop, ranked_fit, rng)
                child = (crossover(pa, pb, rng)
                         if rng.random() < opts['crossover'] else list(pa))
                child = mutate(child, rng, opts['rate'], ctx)
                if not child:
                    child = [rng.choice(ctx.slugs)]
                new_pop.append(child)
            pop = new_pop
            fit_scores = [score(g, ctx) for g in pop]

        # final
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('── Best chain found ──'))
        _, passed, failures, stats = best_meta
        self.stdout.write(f'score   : {best_score:.4f}')
        self.stdout.write(f'passes  : {passed}')
        if failures:
            self.stdout.write(f'fails   : {", ".join(failures)}')
        self.stdout.write(f'length  : {stats["length"]}')
        self.stdout.write(f'cost    : €{stats["cost"]:.0f}')
        self.stdout.write(f'power   : {stats["watts"]:.0f} W')
        self.stdout.write('stages  :')
        for i, slug in enumerate(best_gene):
            self.stdout.write(f'  {i:2d}. {slug}')

        # output per contaminant vs target
        self.stdout.write('')
        self.stdout.write('output vs target:')
        for key in sorted(ctx.target.keys()):
            if key not in stats['output']:
                continue
            out = stats['output'][key]
            lim = ctx.target[key]
            flag = '' if out <= max(lim, ctx.detection_eps) else '  ← fail'
            self.stdout.write(f'  {key:12s} {out:>14.4g}   '
                              f'(limit {lim}){flag}')

        if opts['save']:
            self._save(system, best_gene, opts['save'], best_score, passed)

    # ── Conduit dispatch ──────────────────────────────────────────
    def _dispatch_via_conduit(self, system: System, target_slug: str,
                              opts: dict) -> None:
        """Package this run as a Conduit Job, dispatch, and block
        until terminal — the _local_shell executor runs in a daemon
        thread that would otherwise die at CLI exit (fine under
        gunicorn, broken here)."""
        try:
            job = dispatch_via_conduit(system, target_slug, opts)
        except DispatchError as exc:
            raise CommandError(str(exc))

        self.stdout.write(self.style.SUCCESS(
            f'dispatched Conduit job {job.slug}'))
        self.stdout.write(
            f'  target: {job.target.name} '
            f'({job.target.get_kind_display()})')
        self.stdout.write(f'  watch : /conduit/jobs/{job.slug}/')

        terminal = {'done', 'failed', 'cancelled', 'handoff'}
        if job.status not in terminal:
            last_status = None
            while job.status not in terminal:
                time.sleep(1.0)
                job.refresh_from_db()
                if job.status != last_status:
                    self.stdout.write(
                        f'  status: {job.get_status_display()}')
                    last_status = job.status

        self.stdout.write(f'  final : {job.get_status_display()}')
        if job.status == 'handoff':
            self.stdout.write(
                '  next  : open /conduit/handoffs/ to submit on '
                'the cluster.')
        else:
            if job.stdout:
                self.stdout.write('── job stdout ──')
                self.stdout.write(job.stdout)
            if job.stderr:
                self.stdout.write('── job stderr ──')
                self.stdout.write(job.stderr)

    @transaction.atomic
    def _save(self, parent: System, stages: list[str],
              new_slug: str, best_score: float, passed: bool):
        new_slug = slugify(new_slug)
        if System.objects.filter(slug=new_slug).exists():
            raise CommandError(f'Slug {new_slug!r} already taken.')
        label = 'passing' if passed else 'failing'
        evolved = System.objects.create(
            slug=new_slug,
            name=f'{parent.name} (evolved)',
            description=f'GA offspring of {parent.slug}, '
                        f'score={best_score:.4f} ({label}).',
            source=parent.source,
            target=parent.target,
        )
        for i, slug in enumerate(stages):
            st = StageType.objects.get(slug=slug)
            Stage.objects.create(system=evolved, stage_type=st, position=i)
        self.stdout.write(self.style.SUCCESS(
            f'saved as /naiad/{new_slug}/'))
