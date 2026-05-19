"""Dual-interpretation funnel: stage-1 output IS a rule for stage 2.

Tests the user's metaprogramming hypothesis: a 128×128 board can be
read either as initial-state (run a CA on it) or as a rule LUT (use
it AS the dynamics).  At 128² = 16,384 cells = exactly the LUT size,
the bijection holds and a stage-1 output can become a stage-2 rule.

Pipeline (mode='dual')::

  prompt → 128×128 embedding (stage-1 state)
  combiner CA (stage-1 rule, GA-evolved) runs K1 ticks on the state
                                                   → 128×128 output
  stage-2 rule = stage-1 output (REINTERPRET as 16,384-byte LUT)
  stage-2 CA runs K2 ticks on a fixed probe state
                                                   → 128×128 output
  decode N cells → predicted class

Pipeline (mode='single'), as baseline::

  prompt → 128×128 embedding
  combiner CA runs K1 ticks
  decode N cells

Question: does the dual stage add expressive power vs single?

Usage::

    manage.py caformer_funnel_dual --mode dual --pairs 2,3,4,5,6,9,10,11,12,13,15
    manage.py caformer_funnel_dual --mode single ... (control)
"""
from __future__ import annotations

import random
import sys
import time

import numpy as np
from django.core.management.base import BaseCommand


N_STATES   = 4
LUT_SIZE   = N_STATES ** 7   # 16,384
SIDE       = 128             # 128² = LUT_SIZE → enables dual-interp


def _embed_prompt(prompt: str, side: int = SIDE) -> np.ndarray:
    """Embed prompt bytes at top-left of a side×side grid (else zero).

    4 base-4 digits per byte (lossless within first 4096 prompt bytes).
    """
    n_cells = side * side
    bytes_per_board = n_cells // 4
    raw = prompt.encode('utf-8')[:bytes_per_board]
    out = np.zeros(n_cells, dtype=np.uint8)
    for i, b in enumerate(raw):
        out[i * 4 + 0] = (b >> 6) & 3
        out[i * 4 + 1] = (b >> 4) & 3
        out[i * 4 + 2] = (b >> 2) & 3
        out[i * 4 + 3] =  b       & 3
    return out.reshape(side, side)


def _run_ca(lut: bytes, state0: np.ndarray, ticks: int) -> np.ndarray:
    from caformer.primitives import hex_ca_step
    rule_arr = np.frombuffer(lut, dtype=np.uint8) & 3
    state = state0.copy()
    for _ in range(ticks):
        state = hex_ca_step(state, rule_arr)
    return state


def _make_probe(side: int) -> np.ndarray:
    """Fixed probe state for stage 2 — a small seed at the centre.

    Same pattern for every test stimulus, so the only thing that
    varies between stimuli is the stage-1 output (and therefore the
    stage-2 rule).  Forces the stage-1 rule to encode all
    classification information into its output LUT, with the stage-2
    "decoder" being a uniform probe."""
    state = np.zeros((side, side), dtype=np.uint8)
    c = side // 2
    state[c, c] = 1
    state[c, c - 1] = 2
    state[c, c + 1] = 3
    state[c - 1, c] = 2
    state[c + 1, c] = 3
    return state


def _classify_single(lut: bytes, stim: np.ndarray, ticks: int,
                       decode_cells: int) -> int:
    final = _run_ca(lut, stim, ticks)
    val = 0
    for c in range(decode_cells):
        val = val * N_STATES + int(final[0, c])
    return val


def _classify_dual(lut: bytes, stim: np.ndarray, ticks1: int, ticks2: int,
                     probe: np.ndarray, decode_cells: int) -> int:
    # Stage 1: combiner CA runs on prompt embedding
    s1_final = _run_ca(lut, stim, ticks1)
    # Stage 2: stage-1 final state reinterpreted AS a rule LUT
    s2_rule = bytes(s1_final.flatten().tolist())
    # Run the new rule on the fixed probe
    s2_final = _run_ca(s2_rule, probe, ticks2)
    val = 0
    for c in range(decode_cells):
        val = val * N_STATES + int(s2_final[0, c])
    return val


def _fitness(lut: bytes, stimuli, targets, ticks1, ticks2,
                probe, decode_cells, mode):
    n = 0
    for stim, tgt in zip(stimuli, targets):
        if mode == 'dual':
            pred = _classify_dual(lut, stim, ticks1, ticks2, probe, decode_cells)
        else:
            pred = _classify_single(lut, stim, ticks1, decode_cells)
        if pred == tgt:
            n += 1
    return n / len(targets), n


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


def _evolve(stimuli, targets, ticks1, ticks2, probe, decode_cells,
              mode, pop, gens, seed, mut_min, mut_max, log):
    rng = random.Random(seed)
    population = []
    for _ in range(pop):
        lut = _random_lut(rng)
        frac, n = _fitness(lut, stimuli, targets, ticks1, ticks2,
                              probe, decode_cells, mode)
        population.append((lut, frac, n))
    population.sort(key=lambda x: -x[1])
    best_lut, best_frac, best_n = population[0]
    log(f'  gen   0: best={best_frac:.3f} ({best_n}/{len(targets)})')
    for g in range(gens):
        parents = population[:max(1, pop // 3)]
        children = []
        for _ in range(pop - len(parents)):
            parent_lut, _, _ = rng.choice(parents)
            n_flips = rng.randint(mut_min, mut_max)
            child_lut = _mutate(parent_lut, rng, n_flips)
            frac, n = _fitness(child_lut, stimuli, targets, ticks1, ticks2,
                                  probe, decode_cells, mode)
            children.append((child_lut, frac, n))
        population = parents + children
        population.sort(key=lambda x: -x[1])
        if population[0][1] > best_frac:
            best_lut, best_frac, best_n = population[0]
        if (g + 1) % 5 == 0 or best_frac >= 0.9999 or g == gens - 1:
            log(f'  gen {g+1:>3}: best={best_frac:.3f} '
                f'({best_n}/{len(targets)})')
        if best_frac >= 0.9999:
            log(f'  → CONVERGED at gen {g+1}')
            break
    return {'best_lut': best_lut, 'best_frac': best_frac, 'best_n': best_n}


class Command(BaseCommand):
    help = ('Funnel with optional dual interpretation: stage-1 output '
              'becomes stage-2 rule.  Requires side=128 for the bijection.')

    def add_arguments(self, parser):
        parser.add_argument('--pairs', type=str, default='2,3,4,5,6,9,10,11,12,13,15')
        parser.add_argument('--mode',  type=str, default='dual',
                              choices=['single', 'dual'])
        parser.add_argument('--ticks1', type=int, default=4)
        parser.add_argument('--ticks2', type=int, default=4)
        parser.add_argument('--pop',    type=int, default=16)
        parser.add_argument('--gens',   type=int, default=40)
        parser.add_argument('--mut-min', type=int, default=100)
        parser.add_argument('--mut-max', type=int, default=2000)
        parser.add_argument('--decode-cells', type=int, default=2)
        parser.add_argument('--target-bytes', type=int, default=2)
        parser.add_argument('--n-trials', type=int, default=2)
        parser.add_argument('--seed', type=int, default=0xC0FFEE)

    def handle(self, *, pairs, mode, ticks1, ticks2, pop, gens, mut_min,
                 mut_max, decode_cells, target_bytes, n_trials, seed, **opts):
        from caformer.models import QRPair
        pair_ids = [int(x) for x in pairs.split(',')]
        pairs_obj = [QRPair.objects.get(pk=pk) for pk in pair_ids]

        def _log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        max_classes = N_STATES ** decode_cells
        stimuli = []
        target_prefixes = []
        for p in pairs_obj:
            stimuli.append(_embed_prompt(p.prompt))
            raw = p.expected.encode('utf-8')[:target_bytes]
            target_prefixes.append(raw)
        unique_targets = sorted(set(target_prefixes))
        if len(unique_targets) > max_classes:
            self.stdout.write(self.style.ERROR(
                f'{len(unique_targets)} prefixes > {max_classes} max classes'))
            return
        prefix_to_class = {pref: i for i, pref in enumerate(unique_targets)}
        targets = [prefix_to_class[pref] for pref in target_prefixes]

        probe = _make_probe(SIDE)

        _log(f'=== Funnel (mode={mode}) ===')
        _log(f'  side:        {SIDE}×{SIDE}  ({SIDE*SIDE} cells = LUT size)')
        _log(f'  ticks1/2:    {ticks1} / {ticks2}')
        _log(f'  pop×gens:    {pop}×{gens}')
        _log(f'  trials:      {n_trials}')
        _log(f'  decoder:     {decode_cells} cells → max {max_classes} classes')
        _log(f'  corpus:      {len(targets)} pairs, '
              f'{len(unique_targets)} distinct target prefixes')
        for p, pref, c in zip(pairs_obj, target_prefixes, targets):
            _log(f'    pair {p.pk}: {p.prompt!r:18} → {pref!r:8} → class {c}')

        results = []
        for trial in range(n_trials):
            _log('')
            _log(f'== Trial {trial+1}/{n_trials} (mode={mode}) ==')
            t0 = time.time()
            res = _evolve(stimuli, targets, ticks1, ticks2, probe,
                              decode_cells, mode, pop, gens,
                              seed ^ (trial * 0xCAFE_BABE),
                              mut_min, mut_max, _log)
            wall = time.time() - t0
            _log(f'  final: {res["best_frac"]:.3f} '
                 f'({res["best_n"]}/{len(targets)})  wall {wall:.1f}s')
            results.append(res)

        _log('')
        _log(f'=== Summary (mode={mode}) ===')
        fracs = [r['best_frac'] for r in results]
        ns    = [r['best_n']    for r in results]
        n_perfect = sum(1 for f in fracs if f >= 0.9999)
        _log(f'  perfect:        {n_perfect}/{n_trials}')
        _log(f'  mean accuracy:  {np.mean(fracs):.3f}')
        _log(f'  mean correct:   {np.mean(ns):.2f}/{len(targets)}')
        if n_perfect == n_trials:
            _log(self.style.SUCCESS(
                f'== VALIDATED ({mode}) =='))
        elif n_perfect > 0:
            _log(self.style.WARNING(
                f'== PARTIAL ({mode}): {n_perfect}/{n_trials} =='))
        else:
            _log(self.style.ERROR(
                f'== FAILED ({mode}) =='))
