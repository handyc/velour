"""Particle-as-token experiment (overnight 2026-05-18 b).

Tests whether class-4 substrate dynamics can carry token identity via
small (≤32 cell) particle patterns instead of dense 4096-byte
per-token origin LUTs.  The bet: gliders/flowers/rotators in a
class-4 rule's particle zoo can serve as distinguishable token
representations whose collision dynamics implement compositional
semantics.

Pipeline per token::

    1. Initialise a 64×64 quiescent grid (all zeros).
    2. Inject the candidate particle (PARTICLE_SIDE × PARTICLE_SIDE
       cells, K=4 values) at the centre.
    3. Run the substrate (R★ from ouroboros #124 by default) for
       SUBSTRATE_TICKS ticks.
    4. Extract a SIGNATURE_SIDE × SIGNATURE_SIDE region around the
       centre — this is the token's "behavioural signature".

Fitness for a candidate particle::

    distinctness:   mean Hamming distance to every other token's
                    current best particle's signature  (higher = better)
    persistence:    fraction of non-zero cells in the signature region
                    (avoid the "particle dies" failure mode; 0 = bad)
    locality:       penalty if the signature has spread to all four
                    edges of the substrate (i.e. the particle exploded
                    into space-filling chaos)

GA: μ+λ tournament, per-token, with fire-mask-restricted mutation
where 'fire mask' = cells that changed at least once during the
substrate evolution.

Logs every generation to stdout; persists the best particle per token
to .artifacts/overnight_2026_05_18/b_particle_tokens.json.

Usage::

    manage.py caformer_particle_tokens
    manage.py caformer_particle_tokens --tokens "h,e,l,o, " --pop 24 --gens 40
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


SUBSTRATE_SIDE   = 64           # whole grid the particle plays in
PARTICLE_SIDE    = 5            # 5x5 = 25 cells; bumpable
SIGNATURE_SIDE   = 16           # post-evolution region we read
SUBSTRATE_TICKS  = 16           # how long the substrate runs


def _load_substrate(slug_or_pk: str | int) -> bytes:
    """Look up a ComponentChampion's rule_bytes (16,384 B) by pk."""
    from caformer.models import ComponentChampion
    pk = int(slug_or_pk)
    c = ComponentChampion.objects.get(pk=pk, component_slug='class4_quine')
    seed = bytes(c.rules_blob)
    if len(seed) != 16384:
        raise CommandError(f'substrate #{pk} has unexpected length {len(seed)}')
    return seed


def _run_substrate(substrate_lut: bytes, initial: np.ndarray,
                     ticks: int) -> np.ndarray:
    """Run the K=4 hex CA defined by substrate_lut on `initial` for
    `ticks` steps.  initial: (side, side) uint8 in 0..3.  Returns
    final state, same shape.
    """
    from spoeqi.metachain import hex_ca_step
    rule_arr = np.frombuffer(substrate_lut, dtype=np.uint8) & 3
    state = initial.copy()
    for _ in range(ticks):
        state = hex_ca_step(state, rule_arr)
    return state


def _inject_particle(particle: np.ndarray) -> np.ndarray:
    """Place a (PARTICLE_SIDE × PARTICLE_SIDE) particle at the centre
    of an otherwise-quiescent SUBSTRATE_SIDE × SUBSTRATE_SIDE grid.
    """
    grid = np.zeros((SUBSTRATE_SIDE, SUBSTRATE_SIDE), dtype=np.uint8)
    ofs = (SUBSTRATE_SIDE - PARTICLE_SIDE) // 2
    grid[ofs:ofs + PARTICLE_SIDE, ofs:ofs + PARTICLE_SIDE] = particle
    return grid


def _signature(final_state: np.ndarray) -> np.ndarray:
    """Extract the SIGNATURE_SIDE × SIGNATURE_SIDE central region."""
    ofs = (SUBSTRATE_SIDE - SIGNATURE_SIDE) // 2
    return final_state[ofs:ofs + SIGNATURE_SIDE,
                          ofs:ofs + SIGNATURE_SIDE].copy()


def _evaluate(particle: np.ndarray, substrate_lut: bytes,
                others_signatures: list[np.ndarray]) -> dict:
    grid = _inject_particle(particle)
    final = _run_substrate(substrate_lut, grid, SUBSTRATE_TICKS)
    sig = _signature(final)
    # Distinctness: mean Hamming distance to every other token's sig.
    if others_signatures:
        diffs = [float((sig != other).mean()) for other in others_signatures]
        distinctness = float(np.mean(diffs))
    else:
        distinctness = 0.0
    # Persistence: fraction of non-zero cells in the signature.
    persistence = float((sig != 0).mean())
    # Locality: penalise reaching the substrate edges (sign of chaos).
    edges = np.concatenate([
        final[0, :], final[-1, :], final[:, 0], final[:, -1]
    ])
    locality_penalty = float((edges != 0).mean())
    # Composite fitness: distinct + persistence - locality_penalty.
    # Weights chosen so the easy "everything dead" attractor (persistence=0)
    # and the easy "fill the grid" attractor (locality_penalty=1) both
    # score badly.
    fitness = (1.5 * distinctness + 0.7 * persistence
                  - 1.2 * locality_penalty)
    return {
        'fitness':    fitness,
        'sig':        sig,
        'distinct':   distinctness,
        'persist':    persistence,
        'loc_pen':    locality_penalty,
    }


def _random_particle(rng: random.Random) -> np.ndarray:
    return np.array(
        [[rng.randint(0, 3) for _ in range(PARTICLE_SIDE)]
         for _ in range(PARTICLE_SIDE)], dtype=np.uint8)


def _mutate(particle: np.ndarray, rng: random.Random,
              n_flips: int) -> np.ndarray:
    out = particle.copy()
    n = PARTICLE_SIDE * PARTICLE_SIDE
    for _ in range(n_flips):
        idx = rng.randrange(n)
        new_val = rng.randint(0, 3)
        # Smart mutation: only flip to a DIFFERENT value
        cur = out.flat[idx]
        while new_val == cur:
            new_val = rng.randint(0, 3)
        out.flat[idx] = new_val
    return out


def _evolve_token(token: str, substrate_lut: bytes,
                    others_signatures: list[np.ndarray],
                    pop: int, gens: int, seed: int, log) -> dict:
    rng = random.Random(seed ^ (ord(token) << 8))
    # Initialise: pop random particles + evaluate
    population: list[tuple[np.ndarray, dict]] = []
    for _ in range(pop):
        p = _random_particle(rng)
        r = _evaluate(p, substrate_lut, others_signatures)
        population.append((p, r))
    population.sort(key=lambda kv: -kv[1]['fitness'])
    best_p, best_r = population[0]
    best_history = [best_r['fitness']]
    for g in range(gens):
        # μ+λ — keep top half, mutate them to refill
        parents = population[:max(1, pop // 2)]
        children: list[tuple[np.ndarray, dict]] = []
        for _ in range(pop - len(parents)):
            parent_p, _ = rng.choice(parents)
            n_flips = rng.randint(1, max(2, PARTICLE_SIDE))
            child_p = _mutate(parent_p, rng, n_flips)
            child_r = _evaluate(child_p, substrate_lut, others_signatures)
            children.append((child_p, child_r))
        population = parents + children
        population.sort(key=lambda kv: -kv[1]['fitness'])
        if population[0][1]['fitness'] > best_r['fitness']:
            best_p, best_r = population[0]
        best_history.append(population[0][1]['fitness'])
        if g == 0 or (g + 1) % 5 == 0 or g == gens - 1:
            log(f'    gen {g+1:>3}/{gens}: best={population[0][1]["fitness"]:.4f} '
                  f'(distinct={population[0][1]["distinct"]:.3f} '
                  f'persist={population[0][1]["persist"]:.3f} '
                  f'loc_pen={population[0][1]["loc_pen"]:.3f})')
    return {
        'particle': best_p,
        'fitness': best_r['fitness'],
        'distinct': best_r['distinct'],
        'persist': best_r['persist'],
        'loc_pen': best_r['loc_pen'],
        'signature': best_r['sig'],
        'history': best_history,
    }


class Command(BaseCommand):
    help = 'GA-evolve a 5×5 particle per token on a class-4 substrate.'

    def add_arguments(self, parser):
        parser.add_argument('--tokens', type=str, default='h,e,l,o, ,y,b,i,p,s',
                              help='comma-separated single-char tokens')
        parser.add_argument('--substrate', type=str, default='124',
                              help='ComponentChampion pk for the substrate '
                                   '(default 124 = R★)')
        parser.add_argument('--pop', type=int, default=24)
        parser.add_argument('--gens', type=int, default=40)
        parser.add_argument('--seed', type=int, default=0xCAFE_BABE)
        parser.add_argument('--out', type=str,
            default='.artifacts/overnight_2026_05_18/b_particle_tokens.json',
            help='output JSON path')

    def handle(self, *, tokens, substrate, pop, gens, seed, out, **opts):
        token_list = tokens.split(',')
        if not token_list:
            raise CommandError('--tokens required')
        substrate_lut = _load_substrate(substrate)
        self.stdout.write(self.style.NOTICE(
            f'particle-as-token experiment ({len(token_list)} tokens):'))
        self.stdout.write(f'  substrate: ComponentChampion #{substrate}, '
                              f'{SUBSTRATE_SIDE}×{SUBSTRATE_SIDE} grid')
        self.stdout.write(f'  particles: {PARTICLE_SIDE}×{PARTICLE_SIDE} '
                              f'= {PARTICLE_SIDE**2} cells, K=4')
        self.stdout.write(f'  ticks per substrate run: {SUBSTRATE_TICKS}')
        self.stdout.write(f'  per-token GA: pop={pop}, gens={gens}')

        def _log(msg):
            sys.stdout.write(str(msg) + '\n')
            sys.stdout.flush()

        # Two-pass: first pass with no other signatures (just persistence
        # + locality), second pass with each token's first-pass best as
        # the "other" reference (real distinctness pressure).
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        pass1_results: dict[str, dict] = {}
        _log('')
        _log('== PASS 1: persistence/locality only (no distinctness) ==')
        for token in token_list:
            _log(f'  token {token!r}:')
            t0 = time.time()
            r = _evolve_token(token, substrate_lut, [], pop, gens, seed, _log)
            _log(f'    pass-1 best fit={r["fitness"]:.4f}  ({time.time()-t0:.1f}s)')
            pass1_results[token] = r

        _log('')
        _log('== PASS 2: with cross-token distinctness pressure ==')
        # Use pass-1 signatures as the "other" references in pass 2.
        pass1_sigs = [r['signature'] for r in pass1_results.values()]
        pass2_results: dict[str, dict] = {}
        for i, token in enumerate(token_list):
            _log(f'  token {token!r}:')
            t0 = time.time()
            # Exclude this token's own pass-1 sig from the "others" list
            others = pass1_sigs[:i] + pass1_sigs[i + 1:]
            r = _evolve_token(token, substrate_lut, others, pop, gens,
                                 seed ^ 0xBEEF, _log)
            _log(f'    pass-2 best fit={r["fitness"]:.4f}  '
                 f'(distinct={r["distinct"]:.4f})  ({time.time()-t0:.1f}s)')
            pass2_results[token] = r

        # Compute pairwise Hamming-distance matrix on the final
        # signatures — this is the headline "are tokens distinguishable"
        # metric.
        _log('')
        _log('== Pairwise distinctness matrix (pass 2) ==')
        sigs = [pass2_results[t]['signature'] for t in token_list]
        _log('      ' + '  '.join(f'{t!r:>5}' for t in token_list))
        dist_matrix: list[list[float]] = []
        for i, ti in enumerate(token_list):
            row = []
            for j, tj in enumerate(token_list):
                d = float((sigs[i] != sigs[j]).mean()) if i != j else 0.0
                row.append(d)
            dist_matrix.append(row)
            _log(f'  {ti!r:<4}' + ' '.join(f'  {d:.3f}' for d in row))

        # Headline numbers
        off_diag = [d for i, row in enumerate(dist_matrix)
                       for j, d in enumerate(row) if i != j]
        mean_distinct = float(np.mean(off_diag)) if off_diag else 0.0
        min_distinct  = float(np.min(off_diag))  if off_diag else 0.0
        max_distinct  = float(np.max(off_diag))  if off_diag else 0.0
        _log('')
        _log(f'== Summary ==')
        _log(f'  mean pairwise distinctness: {mean_distinct:.4f}')
        _log(f'  min:  {min_distinct:.4f}  (least-distinct pair)')
        _log(f'  max:  {max_distinct:.4f}  (most-distinct pair)')
        _log(f'  random K=4 baseline would be ~0.75 '
              f'(3/4 of cells differ between two random grids)')

        # Persist the best particles + signatures.
        out_blob = {
            'config': {
                'substrate_pk':     int(substrate),
                'tokens':           token_list,
                'substrate_side':   SUBSTRATE_SIDE,
                'particle_side':    PARTICLE_SIDE,
                'signature_side':   SIGNATURE_SIDE,
                'substrate_ticks':  SUBSTRATE_TICKS,
                'pop':              pop,
                'gens':             gens,
            },
            'tokens': {
                t: {
                    'particle':  r['particle'].tolist(),
                    'signature': r['signature'].tolist(),
                    'fitness':   r['fitness'],
                    'distinct':  r['distinct'],
                    'persist':   r['persist'],
                    'history':   r['history'],
                }
                for t, r in pass2_results.items()
            },
            'distinctness_matrix': dist_matrix,
            'mean_distinctness':   mean_distinct,
        }
        out_path.write_text(json.dumps(out_blob, indent=2))
        _log(f'  wrote: {out_path}')
