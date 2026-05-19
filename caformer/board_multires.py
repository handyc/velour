"""Generic small-board training for the multi-resolution ladder.

Mirrors caformer/board128.py at arbitrary smaller board sides from
LADDER_SIDES (128, 64, 32, 16, 8).  All tiers use the same K=4 7→1
hex CA rule (16,384-entry LUT) — only the BOARD shrinks, which means
fewer cells to update per tick and fewer ticks needed for signal to
propagate across the board.

User framing 2026-05-19: "small tables fix small errors in larger
tables".  A board8 rule trained for one byte at one position can act
as an error-corrector that runs alongside the big board128 chain and
overrides specifically at the failing position.

Concrete cost comparison (per tick, per generation):
  board128: 16,384 cell updates × 128 ticks = 2,097,152 cell-updates
  board64:   4,096 cell updates ×  64 ticks =   262,144  (8× cheaper)
  board32:   1,024 cell updates ×  32 ticks =    32,768  (64×)
  board16:     256 cell updates ×  16 ticks =     4,096  (512×)
  board8:       64 cell updates ×   8 ticks =       512  (4096×)

If a small board can satisfy a single-byte constraint with similar
search-space exploration, the corrector approach delivers thousand-
fold training speedups over the big-rule patch trainer.  This module
is the experimental harness for finding out.
"""
from __future__ import annotations

import random
import time

import numpy as np


# ── Resolution-aware geometry ───────────────────────────────────────

def tier_geometry(side: int) -> dict:
    """Compute the board geometry for a given side length.  The same
    'top half prompt / bottom half response, 4 cells per byte' scheme
    as board128, just scaled."""
    cells           = side * side
    bytes_per_block = 4
    max_bytes       = cells // bytes_per_block
    prompt_bytes_max   = max_bytes // 2
    response_bytes_max = max_bytes // 2
    prompt_cells_start = 0
    prompt_cells_end   = prompt_bytes_max * bytes_per_block
    response_cells_start = prompt_cells_end
    response_cells_end   = max_bytes * bytes_per_block
    return {
        'side':                 side,
        'cells':                cells,
        'max_bytes':            max_bytes,
        'prompt_bytes_max':     prompt_bytes_max,
        'response_bytes_max':   response_bytes_max,
        'prompt_cells_start':   prompt_cells_start,
        'prompt_cells_end':     prompt_cells_end,
        'response_cells_start': response_cells_start,
        'response_cells_end':   response_cells_end,
        'n_ticks_default':      side,
    }


def embed_prompt_tier(prompt: str, side: int) -> np.ndarray:
    """Embed a prompt into a (side, side) K=4 board."""
    g = tier_geometry(side)
    raw = prompt.encode('utf-8')[:g['prompt_bytes_max']]
    flat = np.zeros(g['cells'], dtype=np.uint8)
    for i, b in enumerate(raw):
        base = i * 4
        flat[base + 0] = (b >> 6) & 3
        flat[base + 1] = (b >> 4) & 3
        flat[base + 2] = (b >> 2) & 3
        flat[base + 3] =  b       & 3
    return flat.reshape(side, side)


def decode_byte_at_position_tier(board: np.ndarray, position: int,
                                       side: int) -> int:
    """Decode the byte at the i-th 4-cell block of the response region
    on a (side, side) board."""
    g = tier_geometry(side)
    flat = board.ravel()
    base = g['response_cells_start'] + position * 4
    return (((int(flat[base + 0]) & 3) << 6)
              | ((int(flat[base + 1]) & 3) << 4)
              | ((int(flat[base + 2]) & 3) << 2)
              |  (int(flat[base + 3]) & 3))


def cell_match_for_position_tier(prompt: str, target_byte: int,
                                       position: int,
                                       rule_table: np.ndarray,
                                       side: int, n_ticks: int) -> float:
    """Per-cell match fraction for one byte at one position on a tier
    board.  Smoother gradient signal than byte-exact."""
    from .primitives import hex_ca_step
    g = tier_geometry(side)
    base = g['response_cells_start'] + position * 4
    target_cells = [(target_byte >> (6 - 2 * i)) & 3 for i in range(4)]
    state = embed_prompt_tier(prompt, side)
    for _ in range(n_ticks):
        state = hex_ca_step(state, rule_table)
    flat = state.ravel()
    actual = [int(flat[base + i]) & 3 for i in range(4)]
    return sum(1 for a, t in zip(actual, target_cells) if a == t) / 4.0


# ── Single-position byte trainer at arbitrary tier ──────────────────

def train_position_tier(prompt: str, target_byte: int, position: int,
                              side: int, *,
                              n_ticks: int = None,
                              max_seconds: float = 60.0,
                              pop_size: int = 8,
                              generations_per_burst: int = 8,
                              mutation_rate: float = 0.005,
                              seed: int = 0xB04A,
                              on_event=None) -> dict:
    """Train one 16,384-byte 7→1 rule whose forward run on a (side,
    side) board produces `target_byte` at the i-th response block.

    Same GA structure as train_position_board128 — just generalized
    to arbitrary board side.  Default n_ticks = side."""
    from .primitives import hex_ca_step, random_rule_table

    if n_ticks is None:
        n_ticks = side
    fire = on_event or (lambda *_a, **_kw: None)
    rng = random.Random(seed)
    t0 = time.time()

    def _byte_match(rule):
        state = embed_prompt_tier(prompt, side)
        for _ in range(n_ticks):
            state = hex_ca_step(state, rule)
        return decode_byte_at_position_tier(state, position, side) == target_byte

    def _fitness(rule):
        cf = cell_match_for_position_tier(prompt, target_byte, position,
                                                 rule, side, n_ticks)
        return cf + (1.0 if _byte_match(rule) else 0.0)

    # Initial population.
    pop = []
    for i in range(pop_size):
        r = random_rule_table(seed ^ (i * 7919))
        pop.append((r, _fitness(r)))
    pop.sort(key=lambda rf: -rf[1])
    best_rule, best_fit = pop[0]
    matched = _byte_match(best_rule)
    fire('init', {'best_fit': best_fit, 'matched': matched,
                    'elapsed_s': time.time() - t0})
    if matched:
        return {'rule_table': best_rule, 'byte_match': True,
                'wall': time.time() - t0, 'phase': 'init',
                'side': side, 'n_ticks': n_ticks,
                'generations': 0}

    burst = 0
    n_gens = 0
    while time.time() - t0 < max_seconds and not matched:
        burst += 1
        for _gen in range(generations_per_burst):
            n_gens += 1
            if time.time() - t0 >= max_seconds:
                break
            parent = pop[rng.randrange(max(1, len(pop) // 2))][0]
            child  = parent.copy()
            n_flips = max(1, int(mutation_rate * 16_384))
            for _ in range(n_flips):
                idx = rng.randrange(16_384)
                cur = int(child[idx])
                new = rng.randint(0, 3)
                while new == cur:
                    new = rng.randint(0, 3)
                child[idx] = new
            cf = _fitness(child)
            worst_idx = min(range(len(pop)), key=lambda i: pop[i][1])
            if cf > pop[worst_idx][1]:
                pop[worst_idx] = (child, cf)
                if cf > best_fit:
                    best_rule, best_fit = child, cf
                    matched = _byte_match(best_rule)
                    fire('improved', {'burst': burst, 'best_fit': cf,
                                          'matched': matched,
                                          'elapsed_s': time.time() - t0})
                    if matched:
                        break
        if matched:
            break
    return {'rule_table': best_rule, 'byte_match': matched,
            'wall': time.time() - t0,
            'phase': 'matched' if matched else 'budget_out',
            'side': side, 'n_ticks': n_ticks,
            'generations': n_gens}


# ── Corrector composition: big rule + small overriding rule ──────────

def compose_corrector_output(prompt: str, big_rule: np.ndarray,
                                 small_rule: np.ndarray, position: int, *,
                                 big_side: int = 128,
                                 big_ticks: int = 128,
                                 small_side: int = 8,
                                 small_ticks: int = None) -> dict:
    """Run the big rule on its native board, the small (corrector)
    rule on its native board, and return both produced bytes at
    `position` plus the 'composed' byte (small overrides big).

    This is the dispatch primitive for tier-aware response generation:
    the big rule produces most of the response; the small corrector
    fires only at the position it was trained for, overriding the
    big rule's byte at exactly that index."""
    from .primitives import hex_ca_step
    if small_ticks is None:
        small_ticks = small_side

    # Big rule on big board.
    state_big = embed_prompt_tier(prompt, big_side)
    for _ in range(big_ticks):
        state_big = hex_ca_step(state_big, big_rule)
    big_byte = decode_byte_at_position_tier(state_big, position, big_side)

    # Small corrector rule on small board.
    state_small = embed_prompt_tier(prompt, small_side)
    for _ in range(small_ticks):
        state_small = hex_ca_step(state_small, small_rule)
    small_byte = decode_byte_at_position_tier(state_small, position, small_side)

    return {
        'big_byte':       big_byte,
        'small_byte':     small_byte,
        'composed_byte':  small_byte,    # override semantics
        'position':       position,
        'big_side':       big_side,
        'small_side':     small_side,
    }
