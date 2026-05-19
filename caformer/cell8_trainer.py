"""cell8 per-position trainer with external input-port modulation.

The cell8 primitive (8→1 hex CA) has an external input port — one
extra K=4 cell of input beyond the standard 7-cell hex neighbourhood.
This file implements per-position training where a single 65,536-entry
LUT must produce TWO different bytes at the target position depending
on the value broadcast into the input port:

  - input port broadcast = 0  →  produce target_base byte
  - input port broadcast = 1  →  produce target_alt  byte

The 14th key bit (input port) cleanly partitions the LUT into two
32,768-entry halves, one per port value, so the two constraints don't
fight each other — each half learns its own mapping independently of
the other.

Use case: DMN heartbeat parity (lub = 0, dub = 1) modulates the
caformer response.  Same prompt, two different conditional outputs.
Established by `caformer_cell8_phase1` management command.
"""
from __future__ import annotations

import random
import time

import numpy as np

from .board128 import (BOARD_SIDE, RESPONSE_CELLS_START,
                              decode_byte_at_position, embed_prompt)
from .cell8 import LUT_SIZE_8, broadcast_input, hex_ca_step_cell8


# ── Single-position byte-match under both input port values ─────────

def _run_cell8(rule: np.ndarray, prompt: str, port_value: int,
                  n_ticks: int) -> np.ndarray:
    """Run one cell8 CA forward pass with the input port broadcast
    to `port_value` (0 or 1) across the entire board."""
    state = embed_prompt(prompt)
    inp = broadcast_input(BOARD_SIDE, port_value)
    for _ in range(n_ticks):
        state = hex_ca_step_cell8(state, inp, rule)
    return state


def _byte_match_both(rule: np.ndarray, prompt: str, position: int,
                        target_base: int, target_alt: int,
                        n_ticks: int) -> tuple:
    """Returns (base_match, alt_match) booleans for both port values."""
    s0 = _run_cell8(rule, prompt, 0, n_ticks)
    s1 = _run_cell8(rule, prompt, 1, n_ticks)
    b0 = decode_byte_at_position(s0, position)
    b1 = decode_byte_at_position(s1, position)
    return (b0 == target_base, b1 == target_alt)


def _cell_fitness_both(rule: np.ndarray, prompt: str, position: int,
                          target_base: int, target_alt: int,
                          n_ticks: int) -> float:
    """Fitness in [0, 4]: 0..2 for matching cells under each port mode,
    plus a +1 bonus per byte-exact match.  Splits cleanly so the GA
    can climb each constraint independently."""
    s0 = _run_cell8(rule, prompt, 0, n_ticks)
    s1 = _run_cell8(rule, prompt, 1, n_ticks)
    base_cells = [(target_base >> (6 - 2 * i)) & 3 for i in range(4)]
    alt_cells  = [(target_alt  >> (6 - 2 * i)) & 3 for i in range(4)]
    base_offset = RESPONSE_CELLS_START + position * 4
    f0 = sum(1 for i in range(4)
                if int(s0.ravel()[base_offset + i]) & 3 == base_cells[i]) / 4.0
    f1 = sum(1 for i in range(4)
                if int(s1.ravel()[base_offset + i]) & 3 == alt_cells[i]) / 4.0
    b0 = decode_byte_at_position(s0, position) == target_base
    b1 = decode_byte_at_position(s1, position) == target_alt
    return f0 + f1 + (1.0 if b0 else 0.0) + (1.0 if b1 else 0.0)


# ── GA training of one cell8 rule for one position, both port modes ──

def train_position_cell8_modulated(prompt: str, target_base: int,
                                          target_alt:  int,
                                          position: int, *,
                                          n_ticks: int = 128,
                                          max_seconds: float = 120.0,
                                          pop_size: int = 8,
                                          generations_per_burst: int = 8,
                                          mutation_rate: float = 0.005,
                                          seed: int = 0xCE118A1E,
                                          warm_start_base: np.ndarray = None,
                                          freeze_port0: bool = False,
                                          on_event=None) -> dict:
    """Train one cell8 rule whose port=0 / port=1 outputs at `position`
    are `target_base` and `target_alt` respectively.

    `warm_start_base` optionally supplies a 16,384-byte 7→1 rule that
    already produces target_base from the prompt; it gets copied into
    the cell8 LUT's port=0 quarter (entries 0..16,383) so the GA only
    has to evolve the port=1 quarter (16,384..32,767) for target_alt.
    When `freeze_port0=True`, mutations are restricted to the port=1
    quarter — the port=0 behaviour is guaranteed-preserved.

    Returns {'rule_table': np.ndarray of LUT_SIZE_8 uint8,
             'matches': (base_match, alt_match),
             'wall': float,
             'phase': 'init' | 'matched' | 'budget_out'}."""
    fire = on_event or (lambda *_a, **_kw: None)
    rng = random.Random(seed)
    t0 = time.time()

    def _rand_rule(s):
        from .cell8 import random_rule_table_8
        return random_rule_table_8(s)

    def _seed_rule(s):
        r = _rand_rule(s)
        if warm_start_base is not None:
            if len(warm_start_base) != 16_384:
                raise ValueError(
                    f'warm_start_base must be 16,384 B; got {len(warm_start_base)}')
            if isinstance(warm_start_base, (bytes, bytearray, memoryview)):
                base_arr = np.frombuffer(warm_start_base, dtype=np.uint8)
            else:
                base_arr = np.asarray(warm_start_base, dtype=np.uint8)
            r[0:16_384] = base_arr & 3
        return r

    pop = []
    for i in range(pop_size):
        r = _seed_rule(seed ^ (i * 7919))
        f = _cell_fitness_both(r, prompt, position, target_base,
                                     target_alt, n_ticks)
        pop.append((r, f))
    pop.sort(key=lambda rf: -rf[1])
    best_rule, best_fit = pop[0]
    matches = _byte_match_both(best_rule, prompt, position,
                                       target_base, target_alt, n_ticks)
    fire('init', {'best_fit': best_fit, 'matches': matches,
                    'elapsed_s': time.time() - t0})
    if all(matches):
        return {'rule_table': best_rule, 'matches': matches,
                'wall': time.time() - t0, 'phase': 'init'}

    burst = 0
    while time.time() - t0 < max_seconds and not all(matches):
        burst += 1
        for _gen in range(generations_per_burst):
            if time.time() - t0 >= max_seconds:
                break
            parent = pop[rng.randrange(max(1, len(pop) // 2))][0]
            child  = parent.copy()
            n_flips = max(1, int(mutation_rate * LUT_SIZE_8))
            # When freeze_port0, only flip entries in the port=1
            # quarter (indices 16,384..32,767) so the warm-started
            # base behaviour stays preserved across generations.
            mut_lo = 16_384 if freeze_port0 else 0
            mut_hi = (32_768 if freeze_port0 else LUT_SIZE_8)
            for _ in range(n_flips):
                idx = rng.randrange(mut_lo, mut_hi)
                cur = int(child[idx])
                new = rng.randint(0, 3)
                while new == cur:
                    new = rng.randint(0, 3)
                child[idx] = new
            cf = _cell_fitness_both(child, prompt, position, target_base,
                                              target_alt, n_ticks)
            worst_idx = min(range(len(pop)), key=lambda i: pop[i][1])
            if cf > pop[worst_idx][1]:
                pop[worst_idx] = (child, cf)
                if cf > best_fit:
                    best_rule, best_fit = child, cf
                    matches = _byte_match_both(best_rule, prompt, position,
                                                       target_base, target_alt,
                                                       n_ticks)
                    fire('improved', {'burst': burst, 'best_fit': cf,
                                          'matches': matches,
                                          'elapsed_s': time.time() - t0})
                    if all(matches):
                        break
        if all(matches):
            break

    return {'rule_table': best_rule, 'matches': matches,
            'wall': time.time() - t0,
            'phase': 'matched' if all(matches) else 'budget_out'}


def train_pair_cell8_modulated(prompt: str, expected_base: str,
                                      expected_alt: str, *,
                                      n_ticks: int = 128,
                                      per_position_seconds: float = 120.0,
                                      seed: int = 0xCE118A1E,
                                      warm_start_rules: list = None,
                                      freeze_port0: bool = False,
                                      on_event=None) -> dict:
    """Per-position cell8 training for a whole (prompt, base, alt)
    triple.  Both responses must be the same byte-length; the shorter
    one is right-padded with NUL for the GA to learn explicit padding.

    Returns {'rules': [np.ndarray, …],
             'matches_base': [bool, …], 'matches_alt': [bool, …],
             'exact_base': bool, 'exact_alt': bool, 'wall': float}."""
    fire = on_event or (lambda *_a, **_kw: None)
    base_bytes = expected_base.encode('utf-8')
    alt_bytes  = expected_alt.encode('utf-8')
    n = max(len(base_bytes), len(alt_bytes))
    base_bytes = base_bytes.ljust(n, b'\x00')
    alt_bytes  = alt_bytes.ljust(n, b'\x00')

    t0 = time.time()
    rules         = []
    matches_base  = []
    matches_alt   = []
    for pos in range(n):
        fire('position_start', {'pos': pos,
                                    'target_base': base_bytes[pos],
                                    'target_alt':  alt_bytes[pos],
                                    'elapsed_s': time.time() - t0})
        wsb = None
        if warm_start_rules and pos < len(warm_start_rules):
            wsb = warm_start_rules[pos]
        result = train_position_cell8_modulated(
            prompt, base_bytes[pos], alt_bytes[pos], pos,
            n_ticks=n_ticks,
            max_seconds=per_position_seconds,
            warm_start_base=wsb,
            freeze_port0=freeze_port0,
            seed=seed ^ (pos * 4099),
            on_event=lambda k, p: fire(f'pos{pos}_{k}', p))
        rules.append(result['rule_table'])
        m_base, m_alt = result['matches']
        matches_base.append(m_base)
        matches_alt.append(m_alt)
        fire('position_done', {'pos': pos, 'matches': result['matches'],
                                    'phase': result['phase'],
                                    'pos_wall': result['wall'],
                                    'elapsed_s': time.time() - t0})
    return {'rules': rules,
            'matches_base': matches_base,
            'matches_alt':  matches_alt,
            'exact_base':   all(matches_base),
            'exact_alt':    all(matches_alt),
            'wall':         time.time() - t0}
