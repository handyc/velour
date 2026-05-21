"""Train the 4-board K=4 cascade prefilter.

Joint training: the 4 LUTs are co-evolved so that the *cascade's*
final cell (0,0) predicts the category, while encouraging the path
across the 4 boards to be informative (different paths for
different categories) rather than degenerate (all four boards
voting the same colour).

Two-stage approach for tractability:

  Stage A — independent classifiers.  Train each board as a
            standalone single-LUT router (the existing router's GA
            shape).  Gets us 4 mediocre classifiers fast.

  Stage B — cascade fine-tune.  Treat the 4 LUTs as a joint
            genome and do a short GA that optimises *cascade*
            final-cell accuracy + path-diversity bonus.

  manage.py caformer_train_boardstack4
  manage.py caformer_train_boardstack4 --cell-iters 4000 --joint-iters 1500
"""
from __future__ import annotations

import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

from django.conf import settings
from django.core.management.base import BaseCommand

from caformer.boardstack4 import N_BOARDS, path_to_category
from caformer.router import LUT_SIZE, N_STATES, TICKS, embed_prompt, _run
from caformer.router_corpus import CATEGORY_NAMES, CORPUS, by_category


def _const_lut(val):
    return bytes([val & 3]) * LUT_SIZE


def _random_lut(rng):
    return bytes(rng.randint(0, 3) for _ in range(LUT_SIZE))


def _mutate(lut, rng, n_flips):
    arr = bytearray(lut)
    for _ in range(n_flips):
        idx = rng.randrange(LUT_SIZE)
        cur = arr[idx] & 3
        nu = rng.randint(0, 3)
        while nu == cur:
            nu = rng.randint(0, 3)
        arr[idx] = nu
    return bytes(arr)


# ─── Stage A: independent per-board classifier ────────────────────


def _fitness_single(lut_arr, stims, targets, ticks):
    n = 0
    for stim, tgt in zip(stims, targets):
        if int(_run(lut_arr, stim, ticks)[0, 0]) == tgt:
            n += 1
    return n


def _evolve_single(stims, targets, ticks, iters, pop,
                      flips_min, flips_max, seed, log, label):
    """Evolve one independent classifier LUT.  Logs at three cadences:

      - INIT progress: every N candidates evaluated during pool seeding
      - ACCEPT: whenever a new global best fitness is recorded
      - HEARTBEAT: every N iters with current best + iters/sec + ETA
        — so flat stretches still feel alive.

    All cadences scale with pop/iters so the log doesn't drown the
    terminal at small runs or fall silent on large ones."""
    import time

    rng = random.Random(seed)
    M = len(targets)
    pop_list = []
    log(f'    {label} init: seeding {pop} candidates …')
    t0_init = time.time()
    init_log_every = max(1, pop // 16)
    # const-LUT seeds first (one per K=4 value)
    for v in range(N_STATES):
        lut = _const_lut(v)
        arr = np.frombuffer(lut, dtype=np.uint8) & 3
        pop_list.append((lut, _fitness_single(arr, stims, targets, ticks)))
    # random filler
    for i in range(max(0, pop - N_STATES)):
        lut = _random_lut(rng)
        arr = np.frombuffer(lut, dtype=np.uint8) & 3
        pop_list.append((lut, _fitness_single(arr, stims, targets, ticks)))
        n_done = len(pop_list)
        if n_done % init_log_every == 0 or n_done == pop:
            elapsed = time.time() - t0_init
            rate = n_done / max(elapsed, 1e-6)
            remaining = (pop - n_done) / max(rate, 1e-6)
            best_so_far = max(p[1] for p in pop_list)
            log(f'    {label} init: {n_done:>5}/{pop} '
                f'({100*n_done/pop:5.1f}%)  '
                f'best={best_so_far}/{M}  '
                f'{rate:.1f} cand/s  '
                f'ETA {remaining:.0f}s')
    pop_list.sort(key=lambda x: -x[1])
    best_lut, best_n = pop_list[0]
    init_wall = time.time() - t0_init
    log(f'    {label} init done in {init_wall:.1f}s · best={best_n}/{M}')

    last_accept_it = 0
    t0_loop = time.time()
    heartbeat_every = max(50, iters // 40)   # ~40 heartbeats per run
    next_heartbeat = heartbeat_every
    for it in range(iters):
        if best_n >= M:
            log(f'    {label} it {it:>5}: PERFECT {best_n}/{M} — '
                f'stopping early')
            break
        parent = pop_list[rng.randrange(max(1, pop // 2))]
        child = _mutate(parent[0], rng,
                        rng.randint(flips_min, flips_max))
        carr = np.frombuffer(child, dtype=np.uint8) & 3
        fit = _fitness_single(carr, stims, targets, ticks)
        worst_idx = 0
        for i, (_, f) in enumerate(pop_list):
            if f < pop_list[worst_idx][1]:
                worst_idx = i
        if fit > pop_list[worst_idx][1]:
            pop_list[worst_idx] = (child, fit)
            if fit > best_n:
                best_lut, best_n = child, fit
                if it - last_accept_it >= 100:
                    log(f'    {label} it {it:>5}: ACCEPT {best_n}/{M}')
                    last_accept_it = it
        if it >= next_heartbeat:
            elapsed = time.time() - t0_loop
            rate = (it + 1) / max(elapsed, 1e-6)
            remaining = (iters - it - 1) / max(rate, 1e-6)
            log(f'    {label} hb {it:>5}/{iters} '
                f'({100*it/iters:4.1f}%)  best={best_n}/{M}  '
                f'{rate:.0f} it/s  ETA {remaining:.0f}s')
            next_heartbeat += heartbeat_every
    return best_lut, best_n


# ─── Stage B: joint cascade fine-tune ──────────────────────────────


def _cascade_path(luts_arr, stim, ticks):
    """Run the 4-board cascade on one stim, return (path_tuple,
    final_cell)."""
    state = stim
    path = []
    for rule in luts_arr:
        state = _run(rule, state, ticks)
        path.append(int(state[0, 0]))
    return tuple(path), path[-1]


def _fitness_joint(luts_arr, stims, targets, ticks,
                       diversity_weight=0.15):
    """Joint cascade fitness.

    Primary signal: accuracy of *final* cell prediction (board 3's
    output equals the target category).

    Secondary signal: path diversity across categories.  We compute,
    per (category, board), the dominant colour and reward the
    cascade when distinct categories have distinct (board → colour)
    fingerprints.  Prevents the degenerate solution where all boards
    just echo board 0."""
    n_correct = 0
    paths_by_cat: dict[int, list[tuple[int, ...]]] = {}
    for stim, tgt in zip(stims, targets):
        path, last = _cascade_path(luts_arr, stim, ticks)
        if last == tgt:
            n_correct += 1
        paths_by_cat.setdefault(tgt, []).append(path)
    # Diversity: for each category, the dominant colour at each board
    # position should be distinguishable across categories.
    M = len(targets)
    base = n_correct / max(1, M)
    cat_signatures: list[tuple[int, ...]] = []
    for cat in sorted(paths_by_cat.keys()):
        paths = paths_by_cat[cat]
        sig = tuple(
            Counter(p[b] for p in paths).most_common(1)[0][0]
            for b in range(N_BOARDS))
        cat_signatures.append(sig)
    unique_sigs = len(set(cat_signatures))
    # diversity term in [0, 1]: 1 if all category sigs are unique.
    diversity = unique_sigs / max(1, len(cat_signatures))
    return base + diversity_weight * diversity


def _evolve_joint(luts, stims, targets, ticks, iters, flips_min,
                      flips_max, seed, diversity_weight, log):
    """Joint cascade fine-tune.  Single-genome hill climb (no pop),
    one board mutated per iter.  Same logging shape as _evolve_single:
    ACCEPT on improvement, heartbeat at fixed intervals so flat
    stretches still report progress."""
    import time

    rng = random.Random(seed)
    luts_arr = [np.frombuffer(l, dtype=np.uint8).copy() & 3 for l in luts]
    best_luts = [bytes(l) for l in luts]
    best_fit = _fitness_joint(luts_arr, stims, targets, ticks,
                                  diversity_weight=diversity_weight)
    log(f'  joint init: fit={best_fit:.4f}')
    last_accept_it = 0
    t0 = time.time()
    heartbeat_every = max(50, iters // 40)
    next_heartbeat = heartbeat_every
    for it in range(iters):
        which = rng.randrange(N_BOARDS)
        n_flips = rng.randint(flips_min, flips_max)
        new_lut = _mutate(best_luts[which], rng, n_flips)
        cand = list(best_luts)
        cand[which] = new_lut
        cand_arr = [np.frombuffer(l, dtype=np.uint8).copy() & 3
                    for l in cand]
        fit = _fitness_joint(cand_arr, stims, targets, ticks,
                                 diversity_weight=diversity_weight)
        if fit > best_fit:
            best_luts = cand
            best_fit = fit
            if it - last_accept_it >= 50:
                log(f'  joint it {it:>5}: ACCEPT board {which}, '
                    f'fit={best_fit:.4f}')
                last_accept_it = it
        if it >= next_heartbeat:
            elapsed = time.time() - t0
            rate = (it + 1) / max(elapsed, 1e-6)
            remaining = (iters - it - 1) / max(rate, 1e-6)
            log(f'  joint hb {it:>5}/{iters} '
                f'({100*it/iters:4.1f}%)  fit={best_fit:.4f}  '
                f'{rate:.0f} it/s  ETA {remaining:.0f}s')
            next_heartbeat += heartbeat_every
    return best_luts, best_fit


class Command(BaseCommand):
    help = 'Train the 4-board K=4 cascade prefilter.'

    def add_arguments(self, parser):
        parser.add_argument('--ticks', type=int, default=TICKS)
        parser.add_argument('--side', type=int, default=8,
                              help='grid side N for the N×N K=4 board '
                                     '(default 8).  Smaller boards train '
                                     'faster; larger boards see more of '
                                     'the prompt (side²/4 bytes).')
        parser.add_argument('--pop', type=int, default=16)
        parser.add_argument('--cell-iters', type=int, default=8000,
                              help='per-board independent-classifier '
                                     'iterations (Stage A)')
        parser.add_argument('--joint-iters', type=int, default=3000,
                              help='joint-cascade fine-tune iterations '
                                     '(Stage B)')
        parser.add_argument('--flips-min', type=int, default=4)
        parser.add_argument('--flips-max', type=int, default=200)
        parser.add_argument('--diversity-weight', type=float, default=0.15)
        parser.add_argument('--out-dir', type=str,
                              default='.artifacts/boardstack4_v1')
        parser.add_argument('--seed', type=int, default=0xB04D5AC4)

    def handle(self, *, ticks, side, pop, cell_iters, joint_iters,
                 flips_min, flips_max, diversity_weight, out_dir, seed,
                 **opts):
        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        out = Path(settings.BASE_DIR) / out_dir
        out.mkdir(parents=True, exist_ok=True)

        log(f'=== boardstack4 train ===')
        log(f'  corpus: {len(CORPUS)} pairs')
        for cat, names in by_category().items():
            log(f'    {cat} ({CATEGORY_NAMES[cat]:12}): {len(names)} ex')
        log(f'  side={side}  ticks={ticks}  cell-iters={cell_iters}  '
            f'joint-iters={joint_iters}')

        stims = [embed_prompt(p, side=side) for (p, _) in CORPUS]
        targets = [c for (_, c) in CORPUS]
        M = len(targets)

        t_global = time.time()

        # Stage A: 4 independent classifiers, different seeds.
        log('')
        log('-- Stage A: independent per-board classifiers --')
        luts = []
        stage_a_acc = []
        for b in range(N_BOARDS):
            best_lut, best_n = _evolve_single(
                stims, targets, ticks,
                iters=cell_iters, pop=pop,
                flips_min=flips_min, flips_max=flips_max,
                seed=seed ^ (b * 0x1234ABCD),
                log=log, label=f'board{b}')
            luts.append(best_lut)
            stage_a_acc.append(best_n / M)
            log(f'  board {b}: {best_n}/{M} = {best_n/M:.3f}')

        # Stage B: joint cascade fine-tune.
        log('')
        log('-- Stage B: joint cascade fine-tune --')
        luts, joint_fit = _evolve_joint(
            luts, stims, targets, ticks,
            iters=joint_iters,
            flips_min=flips_min, flips_max=flips_max,
            seed=seed ^ 0xA0F1B2C3,
            diversity_weight=diversity_weight,
            log=log)

        wall = time.time() - t_global

        # Save LUTs.
        for i, lut in enumerate(luts):
            (out / f'board_{i}.lut').write_bytes(lut)

        # Evaluate the final cascade.
        from caformer.boardstack4 import BoardStack4
        meta = {
            'ticks':       ticks,
            'side':        side,
            'wall_seconds': wall,
            'stage_a_per_board_accuracy': stage_a_acc,
            'joint_final_fitness': joint_fit,
            'diversity_weight':    diversity_weight,
            'n_corpus':            M,
        }
        (out / 'boardstack4_meta.json').write_text(
            json.dumps(meta, indent=2))

        stack = BoardStack4(out, ticks=ticks)
        confusion = [[0] * 4 for _ in range(4)]
        paths_by_cat: dict[int, list[tuple]] = {}
        n_correct = 0
        for (prompt, expected) in CORPUS:
            path = stack.cascade(prompt)
            got = path_to_category(path)
            paths_by_cat.setdefault(expected, []).append(path)
            confusion[expected][got] += 1
            if got == expected:
                n_correct += 1

        log('')
        log(f'  cascade mode-projected accuracy: {n_correct}/{M} = '
            f'{n_correct/M:.3f}')
        log(f'  joint final fitness:             {joint_fit:.4f}')
        log(f'  total wall: {wall:.0f}s')

        log('')
        log('  confusion (rows=expected, cols=mode-projected):')
        log('         ' + ' '.join(f'{CATEGORY_NAMES[c][:4]:>5}'
                                       for c in range(4)))
        for e in range(4):
            log(f'    {CATEGORY_NAMES[e][:4]:<5} ' +
                ' '.join(f'{confusion[e][p]:>5}' for p in range(4)))

        log('')
        log('  dominant path per category (board-0 → board-3):')
        for cat in sorted(paths_by_cat.keys()):
            paths = paths_by_cat[cat]
            sig = tuple(
                Counter(p[b] for p in paths).most_common(1)[0][0]
                for b in range(N_BOARDS))
            log(f'    {CATEGORY_NAMES[cat]:12}: '
                f'{"-".join(str(c) for c in sig)} '
                f'(from {len(paths)} examples)')

        # Quick probes.
        novel = [
            'hey', 'how big is mars', 'write me some HTML',
            'what does it mean to know', 'sup',
            'when was jazz invented', 'paint a landscape',
            'consider this carefully',
        ]
        log('')
        log('  novel probes:')
        for p in novel:
            path = stack.cascade(p)
            cat = path_to_category(path)
            log(f'    {p!r:38} → path {"-".join(str(c) for c in path)} '
                f'→ {CATEGORY_NAMES[cat]}')
