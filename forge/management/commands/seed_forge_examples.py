"""Seed pre-evolved example circuits into Forge.

Runs the GA against AND, OR, XOR, NAND on a 16x16 grid and saves
each result as a Circuit with the target persisted and the
EvolutionRun row for traceability. Idempotent — circuits with the
matching `slug` are skipped (so re-running doesn't double-populate).

    venv/bin/python manage.py seed_forge_examples [--force]
        --force re-seeds even if the slug already exists
"""
from __future__ import annotations

import random
import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from forge.ga import (
    Hyper, fitness, mutate, crossover, random_individual, tournament,
)
from forge.models import Circuit, EvolutionRun
from forge.score import analog_preset_rows, preset_truth_table
from forge.wireworld import WIREWORLD_NAME, WIREWORLD_PALETTE


PRESETS = [
    # (preset, slug, kind, ports, hyper-overrides, target-overrides)
    ('AND', 'example-and-16', 'logic',
     [{'role':'input',  'name':'A', 'x':2,  'y':4},
      {'role':'input',  'name':'B', 'x':2,  'y':11},
      {'role':'output', 'name':'Q', 'x':13, 'y':8}],
     dict(pop_size=64, generations=80, mutation_rate=0.04, seed=11),
     {}),
    ('OR', 'example-or-16', 'logic',
     [{'role':'input',  'name':'A', 'x':2,  'y':4},
      {'role':'input',  'name':'B', 'x':2,  'y':11},
      {'role':'output', 'name':'Q', 'x':13, 'y':8}],
     dict(pop_size=64, generations=80, mutation_rate=0.04, seed=1),
     {}),
    ('XOR', 'example-xor-16', 'logic',
     [{'role':'input',  'name':'A', 'x':2,  'y':4},
      {'role':'input',  'name':'B', 'x':2,  'y':11},
      {'role':'output', 'name':'Q', 'x':13, 'y':8}],
     dict(pop_size=64, generations=120, mutation_rate=0.04, seed=2),
     {}),
    ('NAND', 'example-nand-16', 'logic',
     [{'role':'input',  'name':'A', 'x':2,  'y':4},
      {'role':'input',  'name':'B', 'x':2,  'y':11},
      {'role':'output', 'name':'Q', 'x':13, 'y':8}],
     dict(pop_size=64, generations=120, mutation_rate=0.04, seed=4),
     {}),
    ('PASSTHROUGH', 'example-analog-passthrough-16', 'analog',
     [{'role':'input',  'name':'A', 'x':2,  'y':8},
      {'role':'output', 'name':'Q', 'x':13, 'y':8}],
     dict(pop_size=32, generations=40, mutation_rate=0.04, seed=2),
     {'ticks': 60, 'eval_window': [15, 60]}),
    ('HIGHPASS_05', 'example-analog-highpass-16', 'analog',
     [{'role':'input',  'name':'A', 'x':2,  'y':8},
      {'role':'output', 'name':'Q', 'x':13, 'y':8}],
     dict(pop_size=32, generations=40, mutation_rate=0.04, seed=1),
     {'ticks': 60, 'eval_window': [15, 60]}),
]


def evolve_until_perfect(*, width, height, ports, target, hyper, max_seeds=4):
    """Run the GA from up to `max_seeds` different seeds, returning the
    first perfect (fitness=1.0) result. Falls back to best-of-runs."""
    best_overall_grid = None
    best_overall_fit = -1.0
    for attempt in range(max_seeds):
        seed = (hyper.seed + attempt * 1000) & 0x7fffffff
        rng = random.Random(seed)
        pop = [random_individual(rng, height, width,
                                 hyper.init_density, ports)
               for _ in range(hyper.pop_size)]
        best_grid = pop[0]
        best_fit = -1.0

        for gen in range(hyper.generations):
            scored = [(fitness(g, ports, width, height, target), g)
                      for g in pop]
            scored.sort(key=lambda t: -t[0])
            if scored[0][0] > best_fit:
                best_fit = scored[0][0]
                best_grid = [row.copy() for row in scored[0][1]]
            if best_fit >= 1.0 - 1e-9:
                break
            new_pop = [[row.copy() for row in scored[0][1]]]
            while len(new_pop) < hyper.pop_size:
                p1 = tournament(rng, scored, hyper.tournament_k)
                if rng.random() < hyper.crossover_rate:
                    p2 = tournament(rng, scored, hyper.tournament_k)
                    child = crossover(rng, p1, p2, ports)
                else:
                    child = [row.copy() for row in p1]
                child = mutate(rng, child, hyper.mutation_rate, ports)
                new_pop.append(child)
            pop = new_pop

        if best_fit > best_overall_fit:
            best_overall_fit = best_fit
            best_overall_grid = best_grid
        if best_overall_fit >= 1.0 - 1e-9:
            break
    return best_overall_grid, best_overall_fit


class Command(BaseCommand):
    help = 'Seed Forge with pre-evolved AND/OR/XOR/NAND example circuits.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true',
                            help='Re-evolve even if the slug exists.')

    def handle(self, *args, **opts):
        force = opts['force']
        for preset, slug, kind, ports, hyper_kwargs, target_overrides in PRESETS:
            existing = Circuit.objects.filter(slug=slug).first()
            if existing and not force:
                self.stdout.write(self.style.NOTICE(
                    f'  [keep] {slug} (exists; use --force to re-evolve)'))
                continue

            in_names = sorted({p['name'] for p in ports if p['role']=='input'})
            out_names = sorted({p['name'] for p in ports if p['role']=='output'})
            rows = (analog_preset_rows(preset) if kind == 'analog'
                    else preset_truth_table(preset))
            target = {
                'preset':  preset,
                'kind':    kind,
                'inputs':  in_names,
                'outputs': out_names,
                'rows':    rows,
                'ticks':   target_overrides.get('ticks', 30),
                'eval_window': target_overrides.get('eval_window', [1, 30]),
            }
            hyper = Hyper(**hyper_kwargs)
            self.stdout.write(f'  [evolving] {slug} ({preset})…')
            t0 = time.monotonic()
            best_grid, best_fit = evolve_until_perfect(
                width=16, height=16, ports=ports, target=target,
                hyper=hyper, max_seeds=4,
            )
            dt = time.monotonic() - t0
            self.stdout.write(
                f'      → best fitness {best_fit:.3f} in {dt:.1f}s')

            if existing and force:
                existing.delete()
            ckt = Circuit.objects.create(
                name=f'Example {preset} (16×16)',
                slug=slug,
                description=(f'Pre-evolved {preset} gate, hex K=4 wireworld. '
                             f'Best fitness {best_fit:.2f}. Open in Forge to '
                             f'inspect, run, or use as a starting template.'),
                width=16, height=16,
                palette=list(WIREWORLD_PALETTE),
                grid=best_grid,
                ports=ports,
                rule_name=WIREWORLD_NAME,
                target=target,
            )
            # Record an EvolutionRun so the gate catalog finds it.
            EvolutionRun.objects.create(
                circuit=ckt, status='done',
                pop_size=hyper.pop_size, generations=hyper.generations,
                mutation_rate=hyper.mutation_rate,
                crossover_rate=hyper.crossover_rate,
                tournament_k=hyper.tournament_k,
                init_density=hyper.init_density,
                seed=hyper.seed, target=target,
                current_gen=hyper.generations,
                best_grid=best_grid, best_fitness=best_fit,
                finished_at=timezone.now(),
            )
            self.stdout.write(self.style.SUCCESS(f'  [created] /{ckt.slug}/'))
        self.stdout.write(self.style.SUCCESS('Done.'))
