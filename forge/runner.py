"""Threaded GA runner — starts a daemon thread that updates an
EvolutionRun row generation-by-generation.

The view kicks the thread off and returns immediately; the page polls
/forge/<slug>/evolve/<run_id>/status.json for fitness curve + status.
This keeps long runs out of the request cycle so 30s timeouts don't
matter, and it lets the user start a run, navigate away, and come
back to see progress.

Threading model: one thread per EvolutionRun. The thread closes its
own DB connection at exit (Django doesn't auto-clean threaded
connections). Simple Lock guards the in-memory job table. Suitable
for runserver / single gunicorn worker; would need a queue if we
ever scale to multiple workers.
"""
from __future__ import annotations

import threading
import traceback
from typing import Any

from django.db import close_old_connections
from django.utils import timezone

from .ga import Hyper, fitness, mutate, crossover, random_individual, tournament


_lock = threading.Lock()
_jobs: dict[int, threading.Thread] = {}


def _worker(run_id: int) -> None:
    """Body of the GA thread. Updates the EvolutionRun row each gen."""
    from .models import EvolutionRun
    import random

    try:
        run = EvolutionRun.objects.select_related('circuit').get(pk=run_id)
    except EvolutionRun.DoesNotExist:
        return

    try:
        run.status = 'running'
        run.save(update_fields=['status'])

        circuit = run.circuit
        ports = list(circuit.ports or [])
        target = dict(run.target or {})

        rng = random.Random(run.seed)
        h, w = circuit.height, circuit.width
        hyper = Hyper(
            pop_size=run.pop_size, generations=run.generations,
            mutation_rate=run.mutation_rate,
            crossover_rate=run.crossover_rate,
            tournament_k=run.tournament_k,
            init_density=run.init_density,
            seed=run.seed, elite=1,
        )

        pop = [random_individual(rng, h, w, hyper.init_density, ports)
               for _ in range(hyper.pop_size)]
        history: list[dict[str, Any]] = []
        best_grid = pop[0]
        best_fit = -1.0

        for gen in range(hyper.generations):
            scored = [(fitness(g, ports, w, h, target), g) for g in pop]
            scored.sort(key=lambda t: -t[0])
            gen_best = scored[0][0]
            mean = sum(f for f, _ in scored) / len(scored)
            if gen_best > best_fit:
                best_fit = gen_best
                best_grid = [row.copy() for row in scored[0][1]]
            history.append({
                'gen': gen, 'best': gen_best, 'mean': mean,
                'min': scored[-1][0],
            })

            # Persist every generation so the page polling sees progress.
            run.current_gen = gen
            run.fitness_history = history
            run.best_grid = best_grid
            run.best_fitness = best_fit
            run.save(update_fields=[
                'current_gen', 'fitness_history',
                'best_grid', 'best_fitness',
            ])

            if best_fit >= 1.0 - 1e-9:
                break

            new_pop = []
            for i in range(hyper.elite):
                new_pop.append([row.copy() for row in scored[i][1]])
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

        run.status = 'done'
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'finished_at'])

    except Exception as exc:        # pragma: no cover
        try:
            run.status = 'failed'
            run.error = f'{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}'
            run.finished_at = timezone.now()
            run.save(update_fields=['status', 'error', 'finished_at'])
        except Exception:
            pass
    finally:
        close_old_connections()
        with _lock:
            _jobs.pop(run_id, None)


def start_run(run_id: int) -> None:
    """Spawn a daemon thread for the given EvolutionRun id."""
    with _lock:
        if run_id in _jobs:
            return
        t = threading.Thread(target=_worker, args=(run_id,),
                             daemon=True, name=f'forge-ga-{run_id}')
        _jobs[run_id] = t
        t.start()


def is_running(run_id: int) -> bool:
    with _lock:
        t = _jobs.get(run_id)
        return bool(t and t.is_alive())
