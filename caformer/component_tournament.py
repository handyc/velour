"""caformer/component_tournament — autotournament loop that
continuously evolves each of the 8 caformer components.

One *cycle* is a single pass through ``COMPONENT_ROTATION``: for each
component, the loop:

  1. Loads the current champion (best-fitness ComponentChampion row)
     to use as the GA's warm-start template.  If no champion exists
     yet, starts from a fresh random rule table.
  2. Runs the GA for a short burst (default 6 generations × 8 pop)
     against the component's dedicated fitness function.
  3. Saves the result as a new ComponentChampion *only if* it beat
     the parent's fitness.  Ties don't save — keeps the lineage tight.

A *run* is one or more cycles back-to-back; the loop exits when the
configured budget (wall-clock seconds, cycle count, or generation
count) is exhausted.  By cycling through all 8 components rather than
spending budget on one, the autotournament keeps every component's
champion progressing in parallel.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .component_fitness import (
    COMPONENT_SPECS, COMPONENT_ROTATION, ComponentSpec,
)
from .ga import GAConfig, _evolve
from .primitives import random_rule_table


@dataclass
class ComponentTournamentConfig:
    """Knobs for the autotournament loop.  Defaults are tuned to
    produce visible improvement within ~30 seconds per cycle on a
    modest box (8 components × ~3 s each)."""
    pop_size:        int   = 8
    generations:     int   = 6
    mutation_rate:   float = 0.005
    elite_n:         int   = 2
    tournament_k:    int   = 3
    seed:            int   = 0xC0FFEE_CA
    # Budget — the loop stops when any of these is exceeded.
    max_cycles:      int   = 1
    max_seconds:     float = 0.0       # 0 = unlimited
    # Limit which components participate (empty = all).
    only_components: Tuple[str, ...] = ()
    skip_components: Tuple[str, ...] = ()
    run_label:       str   = ''
    # When True, save EVERY scored individual as a ComponentChampion
    # row (not just parent-beating ones).  Fast way to grow the library
    # toward the 65,536 target.  Adds ~pop_size · generations rows per
    # cycle per component, so cap your runs accordingly.  Saved rows
    # carry the original cycle's parent as their parent_seed, so the
    # lineage stays queryable.
    save_all_individuals: bool = False


@dataclass
class CycleReport:
    cycle_idx:        int
    component_slug:   str
    parent_fitness:   float            # the champion we started from (-inf if none)
    final_fitness:    float
    improved:         bool
    saved_pk:         Optional[int]    # ComponentChampion.pk if we saved
    elapsed_seconds:  float


@dataclass
class TournamentReport:
    cycles:           List[CycleReport] = field(default_factory=list)
    total_seconds:    float = 0.0


def _genome_to_blob(genome: Dict[str, np.ndarray],
                      rule_names: Tuple[str, ...]) -> bytes:
    """Concatenate the genome's rule tables in the order specified by
    ``rule_names``; that ordering is the on-disk format."""
    parts = []
    for n in rule_names:
        arr = genome[n].astype(np.uint8) & 3
        if arr.size != 16_384:
            raise ValueError(f'rule {n!r} is {arr.size} bytes, expected 16,384')
        parts.append(arr.tobytes())
    return b''.join(parts)


def _genome_from_champion(champ, spec: ComponentSpec) -> Dict[str, np.ndarray]:
    if champ is None:
        return {n: random_rule_table(0xCAFE_C0DE ^ hash(n) & 0xFFFFFFFF)
                for n in spec.rules}
    return champ.genome()


def _run_one_cycle(spec: ComponentSpec,
                     cfg: ComponentTournamentConfig,
                     cycle_idx: int,
                     on_event: Optional[Callable[[str, dict], None]] = None,
                     ) -> CycleReport:
    """Evolve one component for one cycle and persist the winner if
    it beat the current champion."""
    import time
    from .models import ComponentChampion

    fire = on_event or (lambda *_a, **_kw: None)
    t0 = time.time()

    parent = ComponentChampion.best_for(spec.slug)
    parent_fitness = parent.fitness if parent is not None else float('-inf')
    template = _genome_from_champion(parent, spec)

    fire('cycle_begin', {
        'cycle': cycle_idx, 'component': spec.slug,
        'parent_pk': parent.pk if parent else None,
        'parent_fitness': parent_fitness,
        'parent_generation': parent.generation if parent else 0,
        'rules': list(spec.rules),
    })

    ga_cfg = GAConfig(
        pop_size=cfg.pop_size, generations=cfg.generations,
        tournament_k=cfg.tournament_k, elite_n=cfg.elite_n,
        mutation_rate=cfg.mutation_rate,
        seed=(cfg.seed + cycle_idx * 1009
                + sum(ord(c) for c in spec.slug)),
        # Force serial: the GA's own ThreadPool is empirically 12× slower
        # on caformer's small-grid workload (noted in GAConfig), and the
        # autotournament chains many cycles, so per-cycle pool churn was
        # causing 'cannot schedule new futures after shutdown' under
        # daphne. Serial keeps Daphne responsive too.
        parallel_workers=1,
    )

    def _gen_cb(gen_idx, best, mean, worst):
        fire('generation', {
            'cycle': cycle_idx, 'component': spec.slug,
            'gen': gen_idx, 'best': float(best),
            'mean': float(mean), 'worst': float(worst),
            'elapsed_ms': int((time.time() - t0) * 1000),
        })

    # `on_individual` fires after every single fitness eval inside the
    # GA — that's pop_size × generations events per cycle, plenty of
    # signal for the UI to confirm the run is still alive even when a
    # composite component takes a few seconds per generation.
    def _ind_cb(gen_idx, ind_idx, score):
        fire('individual', {
            'cycle': cycle_idx, 'component': spec.slug,
            'gen': gen_idx, 'ind': ind_idx, 'fitness': float(score),
            'elapsed_ms': int((time.time() - t0) * 1000),
        })

    # When save_all_individuals is set, wrap the fitness function to
    # capture each scored genome (a snapshot of the LUTs) so we can
    # bulk-create ComponentChampion rows after the GA finishes.
    captured: List[dict] = []
    if cfg.save_all_individuals:
        original_fitness = spec.fitness
        def _capturing_fitness(g):
            sc = original_fitness(g)
            captured.append({
                'score':  sc,
                'genome': {k: v.copy() for k, v in g.items()},
            })
            return sc
        fitness_used = _capturing_fitness
    else:
        fitness_used = spec.fitness

    result = _evolve(template, fitness_used, ga_cfg,
                       on_generation=_gen_cb, on_individual=_ind_cb)
    final = float(result.best_fitness)
    improved = final > parent_fitness   # strict — ties don't save

    saved_pk = None
    if improved:
        blob = _genome_to_blob(result.best_genome, spec.rules)
        champ = ComponentChampion.objects.create(
            component_slug=spec.slug,
            rules_blob=blob,
            rule_names_csv=','.join(spec.rules),
            fitness=final,
            parent=parent,
            generation=((parent.generation if parent else 0) + 1),
            run_label=cfg.run_label,
            ga_pop_size=cfg.pop_size,
            ga_generations=cfg.generations,
            eval_count=cfg.pop_size * cfg.generations,
            notes=(f'autotournament cycle {cycle_idx} for {spec.slug}; '
                   f'parent fitness {parent_fitness:+.4f}, '
                   f'improved {final - parent_fitness:+.4f}.'),
        )
        saved_pk = champ.pk

    # Bulk-save every captured individual when save_all_individuals is
    # on.  Skips the cycle-winner if it was already saved as `champ`
    # above (deduped by genome hash).
    saved_all = 0
    if cfg.save_all_individuals and captured:
        rule_names_csv = ','.join(spec.rules)
        already_saved_blob = (
            _genome_to_blob(result.best_genome, spec.rules)
            if improved else None)
        rows = []
        for entry in captured:
            blob = _genome_to_blob(entry['genome'], spec.rules)
            if already_saved_blob is not None and blob == already_saved_blob:
                continue   # cycle-winner already persisted as `champ`
            rows.append(ComponentChampion(
                component_slug=spec.slug,
                rules_blob=blob,
                rule_names_csv=rule_names_csv,
                fitness=float(entry['score']),
                parent=parent,
                generation=((parent.generation if parent else 0) + 1),
                run_label=cfg.run_label,
                ga_pop_size=cfg.pop_size,
                ga_generations=cfg.generations,
                eval_count=1,
                notes=(f'autotournament cycle {cycle_idx} '
                       f'individual (save_all_individuals).'),
            ))
        if rows:
            ComponentChampion.objects.bulk_create(rows, batch_size=200)
            saved_all = len(rows)

    report = CycleReport(
        cycle_idx=cycle_idx, component_slug=spec.slug,
        parent_fitness=parent_fitness, final_fitness=final,
        improved=improved, saved_pk=saved_pk,
        elapsed_seconds=time.time() - t0,
    )
    fire('cycle_end', {
        'cycle': cycle_idx, 'component': spec.slug,
        'parent_fitness': parent_fitness, 'final_fitness': final,
        'improved': improved, 'saved_pk': saved_pk,
        'saved_all_individuals': saved_all,
        'elapsed_seconds': report.elapsed_seconds,
    })
    return report


def _components_for(cfg: ComponentTournamentConfig) -> List[ComponentSpec]:
    chosen = []
    for slug in COMPONENT_ROTATION:
        if cfg.only_components and slug not in cfg.only_components:
            continue
        if slug in cfg.skip_components:
            continue
        chosen.append(COMPONENT_SPECS[slug])
    return chosen


def compose_champions(*, seed: int = 0xC0_C0_FE) -> Tuple[dict, list]:
    """Assemble the 10 FULL_STACK rules into one genome by pulling each
    rule from the most specific available ComponentChampion.

    Per-rule resolution priority (first hit wins):

      embed   ← embedding · (random fallback)
      norm    ← layer_norm · (random)
      q       ← self_attention · projection · transformer · (random)
      k       ← self_attention · transformer · (random)
      v       ← self_attention · transformer · (random)
      score   ← self_attention · transformer · (random)
      mix     ← self_attention · transformer · (random)
      merge   ← transformer · (random)
      mlp     ← mlp · transformer · (random)
      output  ← output · softmax · (random)

    Returns ``(genome, resolution)`` where ``resolution`` is a list of
    dicts the UI uses to show which component each rule came from.
    """
    from .ga import FULL_STACK_NAMES
    from .models import ComponentChampion
    from .primitives import random_rule_table

    # rule_name → ordered list of (component_slug, sub_rule_in_bundle)
    # Per-rule resolution priority: try the joint-evolved bundle first
    # (because it's been co-tuned), fall back to solo specialists, then
    # transformer-composite, then random.
    RULE_SOURCES = {
        'embed':  [('embedding',      'embed')],
        'norm':   [('layer_norm',     'norm')],
        'q':      [('self_attention', 'q'),
                   ('q_proj',         'q'),
                   ('projection',     'q'),
                   ('transformer',    'q')],
        'k':      [('self_attention', 'k'),
                   ('k_proj',         'k'),
                   ('transformer',    'k')],
        'v':      [('self_attention', 'v'),
                   ('v_proj',         'v'),
                   ('transformer',    'v')],
        'score':  [('self_attention', 'score'),
                   ('score_solo',     'score'),
                   ('transformer',    'score')],
        'mix':    [('self_attention', 'mix'),
                   ('mix_solo',       'mix'),
                   ('transformer',    'mix')],
        'merge':  [('merge_solo',     'merge'),
                   ('transformer',    'merge')],
        'mlp':    [('mlp',            'mlp'),
                   ('transformer',    'mlp')],
        'output': [('output',         'output'),
                   ('softmax',        'output')],
    }

    genome: dict = {}
    resolution: list = []
    for rule_name in FULL_STACK_NAMES:
        sources = RULE_SOURCES.get(rule_name, [])
        chosen = None
        for component_slug, sub_rule in sources:
            champ = ComponentChampion.best_for(component_slug)
            if champ is None:
                continue
            bundle = (champ.rule_names_csv or '').split(',')
            if sub_rule not in bundle:
                continue
            genome[rule_name] = champ.rule_table(sub_rule)
            chosen = {
                'rule':       rule_name,
                'source':     component_slug,
                'sub_rule':   sub_rule,
                'champion_pk': champ.pk,
                'fitness':    champ.fitness,
                'generation': champ.generation,
                'random':     False,
            }
            break
        if chosen is None:
            # Stable seed per rule so reruns produce the same fallback.
            genome[rule_name] = random_rule_table(
                seed ^ (sum(ord(c) for c in rule_name) * 2654435761))
            chosen = {
                'rule':       rule_name,
                'source':     '(random)',
                'sub_rule':   None,
                'champion_pk': None,
                'fitness':    None,
                'generation': 0,
                'random':     True,
            }
        resolution.append(chosen)
    return genome, resolution


def run_autotournament(cfg: Optional[ComponentTournamentConfig] = None,
                         on_event: Optional[Callable[[str, dict], None]] = None,
                         ) -> TournamentReport:
    """Run the autotournament loop.  Stops when any budget cap fires."""
    import time
    cfg = cfg or ComponentTournamentConfig()
    fire = on_event or (lambda *_a, **_kw: None)
    components = _components_for(cfg)

    report = TournamentReport()
    t_start = time.time()
    fire('tournament_begin', {
        'pop_size': cfg.pop_size, 'generations': cfg.generations,
        'max_cycles': cfg.max_cycles, 'max_seconds': cfg.max_seconds,
        'components': [s.slug for s in components],
        'run_label': cfg.run_label,
    })

    cycle_idx = 0
    while True:
        if cfg.max_cycles and cycle_idx >= cfg.max_cycles:
            break
        if cfg.max_seconds and (time.time() - t_start) >= cfg.max_seconds:
            break
        for spec in components:
            if (cfg.max_seconds
                    and (time.time() - t_start) >= cfg.max_seconds):
                break
            r = _run_one_cycle(spec, cfg, cycle_idx, on_event=on_event)
            report.cycles.append(r)
        cycle_idx += 1

    report.total_seconds = time.time() - t_start
    fire('tournament_end', {
        'cycles_completed': cycle_idx,
        'evaluations':      sum(c.elapsed_seconds for c in report.cycles),
        'improvements':     sum(1 for c in report.cycles if c.improved),
        'total_seconds':    report.total_seconds,
    })
    return report
