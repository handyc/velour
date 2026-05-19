"""Funnel architecture toy: gathered-board → combiner-CA validation.

Tests the smallest version of the funnel architecture the user
sketched:

  Layer 0 (wide):   N base "chains" each emit 1 byte
                    (deterministic for the toy — would be real
                    per-position/per-pair origin chains in production)
  Layer 1 (gather): the N bytes lay out as a side×side board
                    (16 bytes → 4×4 for the toy; 16,384 → 128×128 at full scale)
  Layer 2 (combiner): K=4 hex CA with its own ruleset runs on the
                    gathered board for `ticks` steps
  Layer 3 (decode): read one cell of the final state as the prediction

Question the toy answers:
  Can a GA-trained combiner CA reliably classify N_classes distinct
  input boards into N_classes target classes?

If yes — even at toy scale — the funnel architecture is structurally
sound and the scale-up story (4×4 → 128×128, 4 classes → 65K
classes) is just bigger search but the same shape.

Usage::

    manage.py caformer_funnel_toy
    manage.py caformer_funnel_toy --classes 4 --ticks 8 --pop 32 --gens 200
"""
from __future__ import annotations

import random
import sys
import time

import numpy as np
from django.core.management.base import BaseCommand


SIDE      = 4                    # 4×4 toy board
N_CELLS   = SIDE * SIDE          # 16
N_STATES  = 4                    # K=4 colours
LUT_SIZE  = N_STATES ** 7        # 16,384 = 4^7 (also = 128² but we use 4×4 here)


def _make_stimuli(n_classes: int, rng: random.Random,
                     noise_level: float = 0.30
                     ) -> list[np.ndarray]:
    """Build N distinct 4×4 input boards.

    Class 0 = a base pattern.  Classes 1..N-1 are perturbations of
    that base — 30 % of cells differ.  Deliberately keeping them
    close in Hamming space so the combiner has to amplify subtle
    initial differences into distinct attractor behaviour, which is
    exactly the load the real per-token chain ensemble would put on
    the combiner.
    """
    base = np.array(
        [[rng.randint(0, N_STATES - 1) for _ in range(SIDE)]
         for _ in range(SIDE)], dtype=np.uint8)
    out = [base]
    n_diff = max(1, int(round(noise_level * N_CELLS)))
    for c in range(1, n_classes):
        perturbed = base.copy()
        idxs = rng.sample(range(N_CELLS), n_diff)
        for idx in idxs:
            cur = perturbed.flat[idx]
            new = rng.randint(0, N_STATES - 1)
            while new == cur:
                new = rng.randint(0, N_STATES - 1)
            perturbed.flat[idx] = new
        out.append(perturbed)
    return out


def _run_combiner(lut: bytes, state0: np.ndarray, ticks: int) -> np.ndarray:
    from caformer.primitives import hex_ca_step
    rule_arr = np.frombuffer(lut, dtype=np.uint8) & 3
    state = state0.copy()
    for _ in range(ticks):
        state = hex_ca_step(state, rule_arr)
    return state


def _classify(lut: bytes, stim: np.ndarray, ticks: int,
                read_row: int = 0, read_col: int = 0) -> int:
    """Run combiner CA on stim for `ticks` ticks, return the value of
    cell (read_row, read_col) as the predicted class in 0..3."""
    final = _run_combiner(lut, stim, ticks)
    return int(final[read_row, read_col])


def _fitness(lut: bytes, stimuli: list[np.ndarray], targets: list[int],
                ticks: int) -> tuple[float, int]:
    """Returns (fraction_correct, n_correct)."""
    n_correct = 0
    for stim, tgt in zip(stimuli, targets):
        if _classify(lut, stim, ticks) == tgt:
            n_correct += 1
    return n_correct / len(targets), n_correct


def _mutate(lut: bytes, rng: random.Random, n_flips: int) -> bytes:
    arr = bytearray(lut)
    for _ in range(n_flips):
        idx = rng.randrange(LUT_SIZE)
        cur = arr[idx] & 3
        new = rng.randint(0, 3)
        while new == cur:
            new = rng.randint(0, 3)
        arr[idx] = new
    return bytes(arr)


def _random_lut(rng: random.Random) -> bytes:
    return bytes(rng.randint(0, 3) for _ in range(LUT_SIZE))


def _evolve(stimuli: list[np.ndarray], targets: list[int],
              ticks: int, pop: int, gens: int, seed: int,
              mut_min: int, mut_max: int, log) -> dict:
    rng = random.Random(seed)
    # Initial random population
    population: list[tuple[bytes, float, int]] = []
    for _ in range(pop):
        lut = _random_lut(rng)
        frac, n = _fitness(lut, stimuli, targets, ticks)
        population.append((lut, frac, n))
    population.sort(key=lambda x: -x[1])
    best_lut, best_frac, best_n = population[0]
    history: list[float] = [best_frac]

    log(f'  gen   0: pop best={best_frac:.3f} ({best_n}/{len(targets)})')
    for g in range(gens):
        parents = population[:max(1, pop // 3)]
        children: list[tuple[bytes, float, int]] = []
        for _ in range(pop - len(parents)):
            parent_lut, _, _ = rng.choice(parents)
            n_flips = rng.randint(mut_min, mut_max)
            child_lut = _mutate(parent_lut, rng, n_flips)
            frac, n = _fitness(child_lut, stimuli, targets, ticks)
            children.append((child_lut, frac, n))
        population = parents + children
        population.sort(key=lambda x: -x[1])
        if population[0][1] > best_frac:
            best_lut, best_frac, best_n = population[0]
        history.append(population[0][1])
        if (g + 1) % 10 == 0 or g == gens - 1 or best_frac >= 0.9999:
            log(f'  gen {g+1:>3}: pop best={best_frac:.3f} '
                f'({best_n}/{len(targets)})')
        if best_frac >= 0.9999:
            log(f'  → CONVERGED at gen {g+1}')
            break
    return {
        'best_lut':   best_lut,
        'best_frac':  best_frac,
        'best_n':     best_n,
        'history':    history,
        'final_gen':  len(history) - 1,
    }


class Command(BaseCommand):
    help = ('Toy funnel test: gathered-board → combiner-CA → '
              'cell-as-class.  Validates that a GA-trained CA can act as '
              'a classifier on small input variations.')

    def add_arguments(self, parser):
        parser.add_argument('--classes', type=int, default=4,
                              help='number of distinct input boards (1..4)')
        parser.add_argument('--ticks',   type=int, default=8)
        parser.add_argument('--pop',     type=int, default=32)
        parser.add_argument('--gens',    type=int, default=200)
        parser.add_argument('--mut-min', type=int, default=20)
        parser.add_argument('--mut-max', type=int, default=400)
        parser.add_argument('--noise',   type=float, default=0.30,
                              help='Hamming-space distance between '
                                   'class-0 base and the others (0..1)')
        parser.add_argument('--n-trials', type=int, default=3,
                              help='re-run with new stim seeds; mean accuracy')
        parser.add_argument('--seed',    type=int, default=0xF00D_BEEF)

    def handle(self, *, classes, ticks, pop, gens, mut_min, mut_max,
                 noise, n_trials, seed, **opts):
        def _log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        assert 1 <= classes <= N_STATES, 'classes must be 1..4 (decode is 1 cell)'

        _log(f'=== Funnel architecture toy ===')
        _log(f'  board side:     {SIDE}×{SIDE} = {N_CELLS} cells')
        _log(f'  K=4 LUT size:   {LUT_SIZE} bytes')
        _log(f'  classes:        {classes}')
        _log(f'  combiner ticks: {ticks}')
        _log(f'  pop × gens:     {pop} × {gens}')
        _log(f'  noise:          {noise:.2f} (Hamming separation between classes)')
        _log(f'  trials:         {n_trials}')

        trial_results = []
        for trial in range(n_trials):
            t_rng = random.Random(seed + trial * 7919)
            stimuli = _make_stimuli(classes, t_rng, noise_level=noise)
            # Permute targets so identity isn't a solution
            targets = list(range(classes))
            t_rng.shuffle(targets)
            _log('')
            _log(f'== Trial {trial+1}/{n_trials} ==')
            _log(f'  stim/target map:')
            for i, (stim, tgt) in enumerate(zip(stimuli, targets)):
                _log(f'    input {i} (target class {tgt}): {stim.flatten().tolist()}')

            t0 = time.time()
            res = _evolve(stimuli, targets, ticks,
                              pop=pop, gens=gens,
                              mut_min=mut_min, mut_max=mut_max,
                              seed=seed ^ (trial * 0xDEAD),
                              log=_log)
            wall = time.time() - t0
            _log(f'  final: {res["best_frac"]:.3f} '
                 f'({res["best_n"]}/{classes})  '
                 f'gen {res["final_gen"]}  wall {wall:.1f}s')
            trial_results.append(res)

        # Summary across trials
        _log('')
        _log('=== Summary across trials ===')
        fracs = [r['best_frac'] for r in trial_results]
        ns    = [r['best_n']    for r in trial_results]
        gens_to_converge = [r['final_gen'] for r in trial_results]
        n_perfect = sum(1 for f in fracs if f >= 0.9999)
        _log(f'  perfect trials:  {n_perfect}/{n_trials}')
        _log(f'  mean accuracy:   {np.mean(fracs):.3f} '
              f'(min {min(fracs):.3f}, max {max(fracs):.3f})')
        _log(f'  mean correct:    {np.mean(ns):.2f}/{classes}')
        _log(f'  mean gens:       {np.mean(gens_to_converge):.0f}')

        # Headline call
        _log('')
        if n_perfect == n_trials:
            _log(self.style.SUCCESS(
                '== VALIDATED == combiner CA reliably classifies in all trials.'))
            _log('  → funnel architecture is structurally viable; scale up.')
        elif n_perfect > 0:
            _log(self.style.WARNING(
                f'== PARTIAL == {n_perfect}/{n_trials} trials reached 100%.'))
            _log('  → CAs can do this task but GA convergence is unreliable.')
            _log('  → try bumping gens, pop, or noise (higher = easier).')
        else:
            _log(self.style.ERROR(
                '== FAILED == no trial reached 100% classification.'))
            _log('  → either the task is too hard at this scale, or the')
            _log('    decoder (single cell) is too narrow.  Try --classes 2')
            _log('    first, or increase --noise to make classes more distinct.')
