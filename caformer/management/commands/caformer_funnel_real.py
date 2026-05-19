"""Real-input funnel: prompt → 4×4 embedding → combiner CA → first-token class.

Same architecture as caformer_funnel_toy but the 4 "stimulus" boards
come from REAL QRPair prompts instead of random patterns.  Tests
whether the GA-trained combiner CA can perform a meaningful
classification task on the actual CA-LLM corpus.

Default test: 4 pairs (2, 3, 5, 6), each with a distinct first-target
token ('h', 'b', 't', 'y' → classes 0..3).  Combiner CA decodes
cell (0,0) of the post-evolution 4×4 board as the predicted class.

Pipeline::

  prompt_bytes → first 16 bytes mod 4 (zero-padded) → 4×4 board (Layer 1
                                                                  gather)
  combiner CA runs K ticks                                       (Layer 2
                                                                  combine)
  read cell (0,0) → class 0..3 → mapped back to expected first token
                                                                 (Layer 3
                                                                  decode)

The voters in this version are just the prompt bytes themselves — no
separate base-chain stage.  That's the simplest non-toy version of
the funnel; once it works, the next step is to replace the embedding
with N actual per-token chain outputs gathered into the board.

Usage::

    manage.py caformer_funnel_real
    manage.py caformer_funnel_real --pairs 2,3,5,6 --ticks 8 --pop 64 --gens 600
"""
from __future__ import annotations

import random
import sys
import time

import numpy as np
from django.core.management.base import BaseCommand


N_STATES  = 4                    # K=4 colours
LUT_SIZE  = N_STATES ** 7        # 16,384 = 4^7
DEFAULT_SIDE = 4                 # default toy size; CLI override possible


def _embed_prompt(prompt: str, side: int = DEFAULT_SIDE) -> np.ndarray:
    """Embed prompt bytes into a side×side board.

    Each byte is split into 4 base-4 digits (top 2 bits, next 2,
    next 2, bottom 2) and laid out left-to-right, top-to-bottom.
    For a 4×4 board this fits exactly 4 prompt bytes — enough to
    distinguish prompts that differ in their first 4 chars (including
    case, which the older mod-4 scheme collapsed).

    Padding: zero-pad short prompts; truncate long ones.
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


def _run_combiner(lut: bytes, state0: np.ndarray, ticks: int) -> np.ndarray:
    from caformer.primitives import hex_ca_step
    rule_arr = np.frombuffer(lut, dtype=np.uint8) & 3
    state = state0.copy()
    for _ in range(ticks):
        state = hex_ca_step(state, rule_arr)
    return state


def _classify(lut: bytes, stim: np.ndarray, ticks: int,
                decode_cells: int = 1) -> int:
    """Run combiner CA, decode the first `decode_cells` of row 0 as a
    base-4 number → class index in [0, 4^decode_cells).  decode_cells=1
    gives 4 classes; =2 gives 16; =3 gives 64; =4 gives 256."""
    final = _run_combiner(lut, stim, ticks)
    val = 0
    for c in range(decode_cells):
        val = val * N_STATES + int(final[0, c])
    return val


def _fitness(lut: bytes, stimuli: list[np.ndarray], targets: list[int],
                ticks: int, decode_cells: int = 1) -> tuple[float, int]:
    n_correct = sum(1 for stim, tgt in zip(stimuli, targets)
                       if _classify(lut, stim, ticks, decode_cells) == tgt)
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


def _evolve(stimuli, targets, ticks, pop, gens, seed,
              mut_min, mut_max, decode_cells, log) -> dict:
    rng = random.Random(seed)
    population = []
    for _ in range(pop):
        lut = _random_lut(rng)
        frac, n = _fitness(lut, stimuli, targets, ticks, decode_cells)
        population.append((lut, frac, n))
    population.sort(key=lambda x: -x[1])
    best_lut, best_frac, best_n = population[0]
    history = [best_frac]
    log(f'  gen   0: best={best_frac:.3f} ({best_n}/{len(targets)})')
    for g in range(gens):
        parents = population[:max(1, pop // 3)]
        children = []
        for _ in range(pop - len(parents)):
            parent_lut, _, _ = rng.choice(parents)
            n_flips = rng.randint(mut_min, mut_max)
            child_lut = _mutate(parent_lut, rng, n_flips)
            frac, n = _fitness(child_lut, stimuli, targets, ticks, decode_cells)
            children.append((child_lut, frac, n))
        population = parents + children
        population.sort(key=lambda x: -x[1])
        if population[0][1] > best_frac:
            best_lut, best_frac, best_n = population[0]
        history.append(population[0][1])
        if (g + 1) % 25 == 0 or best_frac >= 0.9999 or g == gens - 1:
            log(f'  gen {g+1:>3}: best={best_frac:.3f} ({best_n}/{len(targets)})')
        if best_frac >= 0.9999:
            log(f'  → CONVERGED at gen {g+1}')
            break
    return {'best_lut': best_lut, 'best_frac': best_frac, 'best_n': best_n,
              'history': history, 'final_gen': len(history) - 1}


class Command(BaseCommand):
    help = ('Real-input funnel: classify first target token of each pair '
              'via prompt-embedding → combiner CA → cell decode.')

    def add_arguments(self, parser):
        parser.add_argument('--pairs', type=str, default='2,3,5,6')
        parser.add_argument('--ticks', type=int, default=8)
        parser.add_argument('--pop',   type=int, default=64)
        parser.add_argument('--gens',  type=int, default=600)
        parser.add_argument('--mut-min', type=int, default=20)
        parser.add_argument('--mut-max', type=int, default=400)
        parser.add_argument('--n-trials', type=int, default=5)
        parser.add_argument('--decode-cells', type=int, default=1,
            help='How many output cells to combine as base-4 class index. '
                 '1→4 classes, 2→16, 3→64, 4→256.')
        parser.add_argument('--target-bytes', type=int, default=1,
            help='How many target bytes to encode as the class. '
                 '1=just first byte, 2=first 2 bytes, etc.')
        parser.add_argument('--side', type=int, default=DEFAULT_SIDE,
            help='Board side length.  128 makes board=LUT (dual-interpretation '
                 'capable).')
        parser.add_argument('--seed',  type=int, default=0xC0FFEE)

    def handle(self, *, pairs, ticks, pop, gens, mut_min, mut_max,
                 n_trials, decode_cells, target_bytes, side, seed, **opts):
        from caformer.models import QRPair
        pair_ids = [int(x) for x in pairs.split(',')]
        pairs_obj = [QRPair.objects.get(pk=pk) for pk in pair_ids]

        def _log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        max_classes = N_STATES ** decode_cells
        # Embed prompts; first `target_bytes` of expected response → class.
        stimuli = []
        target_prefixes = []
        for p in pairs_obj:
            stimuli.append(_embed_prompt(p.prompt, side=side))
            raw = p.expected.encode('utf-8')[:target_bytes]
            target_prefixes.append(raw)
        unique_targets = sorted(set(target_prefixes))
        if len(unique_targets) > max_classes:
            self.stdout.write(self.style.ERROR(
                f'have {len(unique_targets)} distinct target prefixes '
                f'but {decode_cells}-cell decoder only carries '
                f'{max_classes} classes; bump --decode-cells'))
            return
        prefix_to_class = {pref: i for i, pref in enumerate(unique_targets)}
        targets = [prefix_to_class[pref] for pref in target_prefixes]

        _log(f'=== Real-input funnel ===')
        _log(f'  board:        {side}×{side}, K={N_STATES}, LUT {LUT_SIZE} B')
        _log(f'  ticks:        {ticks}')
        _log(f'  pop×gens:     {pop}×{gens}')
        _log(f'  trials:       {n_trials}')
        _log(f'  target_bytes: {target_bytes}  ({len(unique_targets)} distinct prefixes)')
        _log(f'  decode_cells: {decode_cells}  ({max_classes} max classes)')
        _log('')
        _log('  pair → target-prefix → class:')
        for p, pref, c in zip(pairs_obj, target_prefixes, targets):
            _log(f'    pair {p.pk}: {p.prompt!r:18} '
                 f'→ {pref!r:8} → class {c}')

        trial_results = []
        for trial in range(n_trials):
            _log('')
            _log(f'== Trial {trial+1}/{n_trials} ==')
            t0 = time.time()
            res = _evolve(stimuli, targets, ticks,
                              pop=pop, gens=gens,
                              mut_min=mut_min, mut_max=mut_max,
                              decode_cells=decode_cells,
                              seed=seed ^ (trial * 0xCAFE_BABE),
                              log=_log)
            wall = time.time() - t0
            _log(f'  final: {res["best_frac"]:.3f} '
                 f'({res["best_n"]}/{len(targets)})  gen {res["final_gen"]}  '
                 f'wall {wall:.1f}s')
            trial_results.append(res)

        _log('')
        _log('=== Summary across trials ===')
        fracs = [r['best_frac'] for r in trial_results]
        ns    = [r['best_n']    for r in trial_results]
        gens_to_converge = [r['final_gen'] for r in trial_results]
        n_perfect = sum(1 for f in fracs if f >= 0.9999)
        _log(f'  perfect trials:  {n_perfect}/{n_trials}')
        _log(f'  mean accuracy:   {np.mean(fracs):.3f}')
        _log(f'  mean correct:    {np.mean(ns):.2f}/{len(targets)}')
        _log(f'  mean gens:       {np.mean(gens_to_converge):.0f}')
        if n_perfect == n_trials:
            _log(self.style.SUCCESS(
                '== VALIDATED == real-input funnel reaches 100% in all trials.'))
        elif n_perfect > 0:
            _log(self.style.WARNING(
                f'== PARTIAL == {n_perfect}/{n_trials} trials reached 100%.'))
        else:
            _log(self.style.ERROR(
                '== FAILED == no trial reached 100%.'))
