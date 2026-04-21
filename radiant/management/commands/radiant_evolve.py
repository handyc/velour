"""Headless GA runner for Radiant's purchase-bundle evolution.

Same engine as the /radiant/evolve/ page — just driven from the CLI so
long runs don't tie up a browser tab, and so batches are reproducible
with --seed.

    manage.py radiant_evolve mixed-isolated --gens 50
    manage.py radiant_evolve cheap-strong --pop 48 --gens 120 --seed 7
    manage.py radiant_evolve mixed-isolated --gens 20 --min-boxes 2
    manage.py radiant_evolve mixed-isolated --list

Populations are persisted by name. Re-running with the same name
continues from where the last run left off, unless --reset is passed.
"""

from __future__ import annotations

import random

from django.core.management.base import BaseCommand, CommandError

from radiant.evolution import run_evolution, seed_population
from radiant.models import Candidate, EvoPopulation


def _fmt_genome(genome_ids, cmap):
    from collections import Counter
    names = [cmap.get(cid, f'#{cid}') for cid in genome_ids]
    counts = Counter(names)
    return ', '.join(f'{n}×{k}' if n > 1 else k for k, n in counts.items())


class Command(BaseCommand):
    help = 'Evolve a Radiant purchase-bundle population headlessly.'

    def add_arguments(self, parser):
        parser.add_argument('name', nargs='?',
            help='Population name. Reused across runs unless --reset.')
        parser.add_argument('--list', action='store_true',
            help='List existing populations and exit.')
        parser.add_argument('--gens', type=int, default=30,
            help='Generations to run this invocation (default: 30).')
        parser.add_argument('--pop', type=int, default=32,
            help='Population size on first creation (default: 32).')
        parser.add_argument('--min-boxes', type=int, default=1)
        parser.add_argument('--max-boxes', type=int, default=5)
        parser.add_argument('--mutation-rate', type=float, default=0.3)
        parser.add_argument('--elitism', type=int, default=2)
        parser.add_argument('--seed', type=int,
            help='Seed Python random. Re-runs deterministic (same pop, '
                 'same seed, same gens, same weights) up to DB ordering.')
        parser.add_argument('--reset', action='store_true',
            help='Clear existing individuals and reseed from scratch.')
        parser.add_argument('--top', type=int, default=5,
            help='Print this many leaders at the end (default: 5).')

    def handle(self, *args, **opts):
        if opts['list']:
            self._list_populations()
            return

        name = opts['name']
        if not name:
            raise CommandError(
                'A population name is required (or use --list).')

        if Candidate.objects.count() == 0:
            raise CommandError(
                'No Candidates in the library — seed radiant first.')

        if opts.get('seed') is not None:
            random.seed(opts['seed'])

        pop, created = EvoPopulation.objects.get_or_create(
            name=name,
            defaults={
                'population_size': opts['pop'],
                'min_boxes':       opts['min_boxes'],
                'max_boxes':       opts['max_boxes'],
                'mutation_rate':   opts['mutation_rate'],
                'elitism':         opts['elitism'],
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(
                f'+ created population "{pop.name}" '
                f'(size={pop.population_size}, boxes={pop.min_boxes}..'
                f'{pop.max_boxes}, mut={pop.mutation_rate})'))
            seed_population(pop)
        elif opts['reset']:
            self.stdout.write(
                f'~ resetting "{pop.name}" — dropping {pop.individuals.count()} '
                f'individuals, reseeding')
            seed_population(pop)
        else:
            self.stdout.write(
                f'~ continuing "{pop.name}" at generation {pop.generation} '
                f'(best so far = {pop.best_fitness:.3f})')

        gens = opts['gens']
        self.stdout.write(f'  running {gens} generation{"s" if gens != 1 else ""} …')
        result = run_evolution(pop, generations=gens)
        if not result.get('ok'):
            raise CommandError(result.get('error', 'evolution failed'))

        # Trajectory (one line per 10 gens, or every gen for small N)
        history = result['history']
        step = 1 if len(history) <= 12 else max(1, len(history) // 12)
        self.stdout.write('')
        self.stdout.write('  gen    best_fitness')
        for i, h in enumerate(history):
            if i % step == 0 or i == len(history) - 1:
                self.stdout.write(
                    f'  {h["generation"]:>4}   {h["best_fitness"]:>10.3f}')

        # Leaderboard
        cmap = {c.pk: c.name for c in Candidate.objects.all()}
        leaders = pop.individuals.order_by('-fitness')[:opts['top']]
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Top {len(leaders)} at gen {pop.generation}:'))
        for i, ind in enumerate(leaders, start=1):
            b = ind.breakdown or {}
            life = b.get('lifetime_years', '?')
            tco = b.get('tco_eur', 0)
            nb = b.get('n_boxes', len(ind.genome_ids))
            self.stdout.write(
                f'  {i}. fitness={ind.fitness:.3f}  '
                f'life={life}y  tco=€{tco:.0f}  n={nb}')
            self.stdout.write(
                f'      {_fmt_genome(ind.genome_ids, cmap)}')

    def _list_populations(self):
        qs = EvoPopulation.objects.all()
        if not qs.exists():
            self.stdout.write('(no populations yet)')
            return
        self.stdout.write('  name                              gen    best     size')
        for p in qs:
            self.stdout.write(
                f'  {p.name[:32]:<32}  {p.generation:>4}  '
                f'{p.best_fitness:>7.2f}  {p.population_size:>4}')
