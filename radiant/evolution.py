"""Radiant Evolution — genetic algorithm over purchase bundles.

A *genome* is a list of ``Candidate.pk`` values. Duplicates allowed
(buying two identical boxes is a valid strategy), order doesn't matter
for scoring. Fitness has five components:

  1. **Lifetime years** — how long until the forecast's peak RAM,
     storage, or CPU exceeds the bundle's capacity. Clamped at 10 yr;
     anything past that is noise anyway.
  2. **TCO penalty** — 5-year total cost of ownership, in 1,000 EUR
     units. Cheaper wins.
  3. **Isolation bonus** — bundles that span three distinct purposes
     (production / wordpress / experimental) get a flat reward, because
     that's the isolation the operator explicitly wanted.
  4. **Simplicity bonus** — fewer boxes == fewer things to admin.
  5. **Headroom bonus** — if the bundle's RAM is >= 1.5× the 5-yr peak,
     award a small bonus; the operator explicitly sizes for that.

The GA is pure Python; no numpy. It runs in-request (a single
generation on a 32-pop is sub-second) but can also be driven from a
management command for long stretches.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from django.db import transaction

from .forecast import _current_forecast_rows, cpu_cores_needed  # noqa: E402
from .models import (Candidate, EvoIndividual, EvoPopulation, EvoTournament,
                     EvoMetaTournament)


# ---------------------------------------------------------------------
# Genome evaluation
# ---------------------------------------------------------------------

@dataclass
class GenomeScore:
    fitness: float
    breakdown: Dict[str, float]

    def to_json(self) -> Dict:
        return {'fitness': self.fitness, **self.breakdown}


def _candidate_map() -> Dict[int, Candidate]:
    """Cache-friendly dict of all Candidates keyed by pk."""
    return {c.pk: c for c in Candidate.objects.all()}


def _totals_for_genome(genome: Iterable[int],
                       cmap: Dict[int, Candidate]) -> Dict[str, float]:
    ram = storage = cores = upfront = monthly = 0
    purposes = set()
    n = 0
    for cid in genome:
        c = cmap.get(cid)
        if c is None:
            continue
        ram += c.ram_gb
        storage += c.storage_gb
        cores += c.cpu_cores
        upfront += c.approximate_cost_eur
        monthly += c.monthly_cost_eur
        purposes.add(c.purpose)
        n += 1
    return {
        'ram_gb': ram, 'storage_gb': storage, 'cpu_cores': cores,
        'upfront_eur': upfront, 'monthly_eur': monthly,
        'tco_eur': upfront + monthly * 60,
        'n_boxes': n, 'purposes': purposes,
    }


def _lifetime_years(totals, rows) -> Optional[float]:
    """First horizon where any capacity is exceeded. None = never."""
    for r in rows:
        if (r['total_ram_peak_gb'] > totals['ram_gb']
                or r['total_storage_gb'] > totals['storage_gb']
                or r['total_cpu_cores'] > totals['cpu_cores']):
            return r['years']
    return None


def score_genome(genome: List[int],
                 rows: List[Dict],
                 weights: Dict[str, float],
                 cmap: Optional[Dict[int, Candidate]] = None) -> GenomeScore:
    cmap = cmap if cmap is not None else _candidate_map()
    totals = _totals_for_genome(genome, cmap)

    if totals['n_boxes'] == 0:
        return GenomeScore(fitness=-1e6, breakdown={
            'reason': 'empty genome', 'lifetime_years': 0,
            'tco_eur': 0, 'n_boxes': 0,
        })
    if totals['ram_gb'] == 0 or totals['storage_gb'] == 0 or totals['cpu_cores'] == 0:
        # A bundle of pure add-ons with no base box is infeasible.
        return GenomeScore(fitness=-1e5, breakdown={
            'reason': 'no base capacity', **{k: v for k, v in totals.items()
                                             if k != 'purposes'},
        })

    life_raw = _lifetime_years(totals, rows)
    lifetime_capped = min(10.0, float(life_raw)) if life_raw is not None else 10.0

    # 5-year row basis
    row_5y = next((r for r in rows if r['years'] == 5), rows[-1])
    peak_5y = row_5y['total_ram_peak_gb']

    headroom_ratio = totals['ram_gb'] / peak_5y if peak_5y > 0 else 10.0
    headroom_bonus = 1.0 if headroom_ratio >= 1.5 else max(0.0,
                                                           (headroom_ratio - 1.0) * 2.0)

    real_purposes = totals['purposes'] - {'unified'}
    isolation_bonus = 1.0 if len(real_purposes) >= 3 else len(real_purposes) / 3.0

    # Simplicity penalises both explosion and under-specifying: sweet spot
    # 2-3 boxes. n=1 unified is fine; n>5 starts looking like zoo-keeping.
    n = totals['n_boxes']
    if n <= 3:
        simplicity_bonus = 1.0
    elif n <= 5:
        simplicity_bonus = 0.7
    else:
        simplicity_bonus = max(0.0, 1.0 - (n - 5) * 0.2)

    tco_k = totals['tco_eur'] / 1000.0

    fitness = (
        weights.get('weight_lifetime', 1.0) * lifetime_capped
        - weights.get('weight_tco', 0.5) * tco_k
        + weights.get('weight_isolation', 2.0) * isolation_bonus
        + weights.get('weight_simplicity', 0.3) * simplicity_bonus
        + weights.get('weight_headroom', 1.0) * headroom_bonus
    )

    return GenomeScore(fitness=fitness, breakdown={
        'lifetime_years': life_raw if life_raw is not None else 9999,
        'lifetime_capped': lifetime_capped,
        'tco_eur': totals['tco_eur'],
        'upfront_eur': totals['upfront_eur'],
        'monthly_eur': totals['monthly_eur'],
        'ram_gb': totals['ram_gb'],
        'storage_gb': totals['storage_gb'],
        'cpu_cores': totals['cpu_cores'],
        'n_boxes': n,
        'isolation_bonus': isolation_bonus,
        'simplicity_bonus': simplicity_bonus,
        'headroom_bonus': headroom_bonus,
        'tco_k': tco_k,
    })


# ---------------------------------------------------------------------
# Genetic operators
# ---------------------------------------------------------------------

def random_genome(candidate_ids: List[int],
                  min_boxes: int, max_boxes: int,
                  rng: random.Random) -> List[int]:
    n = rng.randint(max(1, min_boxes), max(min_boxes, max_boxes))
    return [rng.choice(candidate_ids) for _ in range(n)]


def mutate(genome: List[int], candidate_ids: List[int],
           min_boxes: int, max_boxes: int,
           rate: float, rng: random.Random) -> List[int]:
    """Three mutation operators chosen uniformly per mutation event:
       swap a gene, add a gene, drop a gene."""
    new = list(genome)
    if rng.random() < rate:
        op = rng.choice(('swap', 'add', 'drop'))
        if op == 'swap' and new:
            i = rng.randrange(len(new))
            new[i] = rng.choice(candidate_ids)
        elif op == 'add' and len(new) < max_boxes:
            new.append(rng.choice(candidate_ids))
        elif op == 'drop' and len(new) > min_boxes:
            i = rng.randrange(len(new))
            new.pop(i)
    # Light second-pass swap — keeps populations diverse on small genomes.
    if new and rng.random() < rate * 0.5:
        i = rng.randrange(len(new))
        new[i] = rng.choice(candidate_ids)
    return new or [rng.choice(candidate_ids)]


def crossover(a: List[int], b: List[int],
              min_boxes: int, max_boxes: int,
              rng: random.Random) -> List[int]:
    """Uniform multiset crossover: pool the two genomes, pick a
    length between their lengths, sample that many boxes uniformly.
    """
    pool = list(a) + list(b)
    if not pool:
        return []
    length_lo = max(min_boxes, min(len(a), len(b)))
    length_hi = min(max_boxes, max(len(a), len(b)))
    if length_hi < length_lo:
        length_hi = length_lo
    length = rng.randint(length_lo, length_hi)
    return [rng.choice(pool) for _ in range(length)]


def tournament_select(scored: List[tuple], k: int,
                      rng: random.Random) -> List[int]:
    """k-way tournament; returns the genome of the winner."""
    contenders = rng.sample(scored, min(k, len(scored)))
    contenders.sort(key=lambda t: t[1].fitness, reverse=True)
    return list(contenders[0][0])


# ---------------------------------------------------------------------
# Population runners
# ---------------------------------------------------------------------

def weights_from_population(p: EvoPopulation) -> Dict[str, float]:
    return {
        'weight_lifetime': p.weight_lifetime,
        'weight_tco': p.weight_tco,
        'weight_isolation': p.weight_isolation,
        'weight_simplicity': p.weight_simplicity,
        'weight_headroom': p.weight_headroom,
    }


def seed_population(pop: EvoPopulation, seed_genomes: Optional[List[List[int]]] = None):
    """Fill a fresh population with random genomes (plus any seeds)."""
    cids = list(Candidate.objects.values_list('pk', flat=True))
    if not cids:
        return []
    rng = random.Random()
    rows = _current_forecast_rows()
    weights = weights_from_population(pop)
    cmap = _candidate_map()

    with transaction.atomic():
        pop.individuals.all().delete()
        pop.generation = 0
        genomes = list(seed_genomes or [])
        while len(genomes) < pop.population_size:
            genomes.append(random_genome(cids, pop.min_boxes, pop.max_boxes, rng))
        created = []
        best = -1e9
        for g in genomes[:pop.population_size]:
            s = score_genome(g, rows, weights, cmap=cmap)
            ind = EvoIndividual.objects.create(
                population=pop, generation=0, genome_ids=g,
                fitness=s.fitness, breakdown=s.breakdown,
            )
            best = max(best, s.fitness)
            created.append(ind)
        pop.best_fitness = best
        pop.save(update_fields=['generation', 'best_fitness', 'modified_at'])
    return created


def step_generation(pop: EvoPopulation) -> Dict:
    """Run one generation. Returns summary dict for UI."""
    cids = list(Candidate.objects.values_list('pk', flat=True))
    if not cids:
        return {'ok': False, 'error': 'No Candidates in library.'}
    rng = random.Random()
    rows = _current_forecast_rows()
    weights = weights_from_population(pop)
    cmap = _candidate_map()

    current = list(pop.individuals.all().order_by('-fitness'))
    if not current:
        seed_population(pop)
        current = list(pop.individuals.all().order_by('-fitness'))

    scored = [(ind.genome_ids, _rescore(ind, rows, weights, cmap))
              for ind in current]

    next_generation_number = pop.generation + 1
    elite_n = min(pop.elitism, len(scored))
    new_genomes: List[List[int]] = [list(g) for g, _ in scored[:elite_n]]

    while len(new_genomes) < pop.population_size:
        parent_a = tournament_select(scored, 3, rng)
        parent_b = tournament_select(scored, 3, rng)
        child = crossover(parent_a, parent_b, pop.min_boxes, pop.max_boxes, rng)
        child = mutate(child, cids, pop.min_boxes, pop.max_boxes,
                       pop.mutation_rate, rng)
        new_genomes.append(child)

    with transaction.atomic():
        pop.individuals.all().delete()
        best_fitness = -1e9
        best_genome = None
        for g in new_genomes:
            s = score_genome(g, rows, weights, cmap=cmap)
            EvoIndividual.objects.create(
                population=pop, generation=next_generation_number,
                genome_ids=g, fitness=s.fitness, breakdown=s.breakdown,
            )
            if s.fitness > best_fitness:
                best_fitness = s.fitness
                best_genome = g
        pop.generation = next_generation_number
        pop.best_fitness = best_fitness
        pop.save(update_fields=['generation', 'best_fitness', 'modified_at'])

    return {'ok': True, 'generation': pop.generation,
            'best_fitness': pop.best_fitness,
            'best_genome_ids': best_genome}


def _rescore(ind: EvoIndividual, rows, weights, cmap) -> GenomeScore:
    """Cheap re-evaluation so elite selection always uses current weights
    and current forecast rows."""
    return score_genome(ind.genome_ids, rows, weights, cmap=cmap)


def run_evolution(pop: EvoPopulation, generations: int) -> Dict:
    """Step through `generations` rounds server-side. Keep modest."""
    history = []
    for _ in range(max(1, int(generations))):
        res = step_generation(pop)
        if not res.get('ok'):
            return {'ok': False, 'error': res.get('error')}
        history.append({'generation': res['generation'],
                        'best_fitness': res['best_fitness']})
    return {'ok': True, 'history': history,
            'final_generation': pop.generation,
            'best_fitness': pop.best_fitness}


# ---------------------------------------------------------------------
# Tournaments
# ---------------------------------------------------------------------

def _candidate_display(cmap, cid):
    c = cmap.get(cid)
    return c.name if c else f'#{cid}'


def _summarise_genome(genome, cmap):
    names = [_candidate_display(cmap, cid) for cid in genome]
    # Collapse duplicates for readability.
    from collections import Counter
    counts = Counter(names)
    return ', '.join(f'{n}×{k}' if n > 1 else k for k, n in counts.items())


def run_tournament(tournament: EvoTournament,
                   weights: Optional[Dict[str, float]] = None,
                   base_pop_size: Optional[int] = None) -> Dict:
    """Spin up `rounds` fresh populations, evolve each, record winners."""
    cids = list(Candidate.objects.values_list('pk', flat=True))
    if not cids:
        return {'ok': False, 'error': 'No Candidates in library.'}
    cmap = _candidate_map()
    rows = _current_forecast_rows()

    weights = weights or tournament.weights_json or {
        'weight_lifetime': 1.0, 'weight_tco': 0.5, 'weight_isolation': 2.0,
        'weight_simplicity': 0.3, 'weight_headroom': 1.0,
    }
    tournament.weights_json = weights

    pop_size = base_pop_size or tournament.population_size

    board = []
    for i in range(tournament.rounds):
        rng = random.Random()
        # Fresh population
        population = [random_genome(cids, 1, 5, rng) for _ in range(pop_size)]
        scored = [(g, score_genome(g, rows, weights, cmap=cmap)) for g in population]
        for _ in range(max(1, tournament.generations)):
            scored.sort(key=lambda t: t[1].fitness, reverse=True)
            elites = [list(g) for g, _ in scored[:2]]
            next_gen = list(elites)
            while len(next_gen) < pop_size:
                a = tournament_select(scored, 3, rng)
                b = tournament_select(scored, 3, rng)
                child = crossover(a, b, 1, 5, rng)
                child = mutate(child, cids, 1, 5, tournament.mutation_rate, rng)
                next_gen.append(child)
            scored = [(g, score_genome(g, rows, weights, cmap=cmap)) for g in next_gen]
        scored.sort(key=lambda t: t[1].fitness, reverse=True)
        best_g, best_s = scored[0]
        board.append({
            'round': i + 1,
            'fitness': best_s.fitness,
            'genome_ids': list(best_g),
            'summary': _summarise_genome(best_g, cmap),
            'breakdown': best_s.breakdown,
        })

    board.sort(key=lambda r: r['fitness'], reverse=True)
    tournament.leaderboard = board
    champ = board[0]
    tournament.champion_genome_ids = champ['genome_ids']
    tournament.champion_fitness = champ['fitness']
    tournament.save()
    return {'ok': True, 'champion': champ, 'leaderboard': board}


def _jitter_weights(base: Dict[str, float], jitter: float,
                    rng: random.Random) -> Dict[str, float]:
    out = {}
    for k, v in base.items():
        j = 1.0 + rng.uniform(-jitter, jitter)
        out[k] = max(0.0, v * j)
    return out


def run_meta_tournament(meta: EvoMetaTournament) -> Dict:
    """Run `rounds` internal tournaments, each with jittered weights, and
    promote the best champion as the meta-champion."""
    if not Candidate.objects.exists():
        return {'ok': False, 'error': 'No Candidates in library.'}
    cmap = _candidate_map()
    rng = random.Random()
    base_weights = {
        'weight_lifetime': 1.0, 'weight_tco': 0.5, 'weight_isolation': 2.0,
        'weight_simplicity': 0.3, 'weight_headroom': 1.0,
    }
    board = []
    for i in range(meta.rounds):
        w = _jitter_weights(base_weights, meta.weight_jitter, rng)
        # Synthesise an ephemeral tournament
        t = EvoTournament(
            name=f'{meta.name}::inner-{i + 1}',
            rounds=meta.tournament_rounds,
            generations=meta.generations,
            population_size=meta.population_size,
            mutation_rate=0.3,
            weights_json=w,
        )
        # Don't persist the inner tournament; we only want the champion.
        res = run_tournament(t, weights=w)
        if not res.get('ok'):
            continue
        champ = res['champion']
        board.append({
            'round': i + 1,
            'weights': w,
            'fitness': champ['fitness'],
            'genome_ids': champ['genome_ids'],
            'summary': champ['summary'],
            'breakdown': champ['breakdown'],
        })
    board.sort(key=lambda r: r['fitness'], reverse=True)
    if not board:
        return {'ok': False, 'error': 'No rounds produced a champion.'}
    meta.leaderboard = board
    meta.champion_genome_ids = board[0]['genome_ids']
    meta.champion_fitness = board[0]['fitness']
    meta.save()
    return {'ok': True, 'champion': board[0], 'leaderboard': board}
