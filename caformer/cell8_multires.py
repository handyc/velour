"""Multi-resolution cell8 (8→1) training & inference at arbitrary
board sizes — analog of caformer/board_multires.py for the 7→1
multires tier ladder.

Same K=4 hex topology and "top half prompt / bottom half response,
4 cells per byte" embedding scheme as the 7→1 multires; what changes
is the rule shape (8→1 LUT, 65,536 bytes) and the stepper
(caformer.cell8.hex_ca_step_cell8).

The natural ouroboros tier for cell8 is b256 (4^8 = 65,536 = 256×256
cells), already covered in caformer/board256.py.  This module
provides the smaller tiers — cell8_b008, cell8_b016, cell8_b032,
cell8_b064, cell8_b128 — for fast cell8 inference dispatch (mirroring
how board128's tier-auto buys ~30× wall speedup on most prompts).

Schema fields these write to (migration 0010):
    QRPair.cell8_b008_rules_blob, cell8_b016_rules_blob, …,
    cell8_b128_rules_blob — each = N per-position 65,536-byte rules.
    Each tier has its own exact flag (cell8_b008_exact …).
"""
from __future__ import annotations

import random
import time

import numpy as np

from .cell8 import (LUT_SIZE_8, broadcast_input, hex_ca_step_cell8,
                       random_rule_table_8)


# ── Tier geometry: same scheme as board_multires but parameterized ─

def cell8_tier_geometry(side: int) -> dict:
    """Same shape as board_multires.tier_geometry — exposed for
    callers that want the cell layout without computing it.

    For cell8: the ONLY thing that changes from the 7→1 version is
    that inference uses hex_ca_step_cell8 (with an input grid) and
    the LUT is 65,536 bytes."""
    cells           = side * side
    bytes_per_block = 4
    max_bytes       = cells // bytes_per_block
    prompt_bytes_max   = max_bytes // 2
    response_bytes_max = max_bytes // 2
    prompt_cells_start = 0
    prompt_cells_end   = prompt_bytes_max * bytes_per_block
    response_cells_start = prompt_cells_end
    return {
        'side':                 side,
        'cells':                cells,
        'max_bytes':            max_bytes,
        'prompt_bytes_max':     prompt_bytes_max,
        'response_bytes_max':   response_bytes_max,
        'prompt_cells_start':   prompt_cells_start,
        'prompt_cells_end':     prompt_cells_end,
        'response_cells_start': response_cells_start,
        # Default ticks scale with side — bigger board needs more
        # ticks for signal to propagate across the diameter.
        'n_ticks_default':      side,
    }


def embed_prompt_cell8_tier(prompt: str, side: int) -> np.ndarray:
    """Embed a prompt into a (side, side) K=4 board.  Identical to
    board_multires.embed_prompt_tier — included here so callers
    can stay in one module."""
    g = cell8_tier_geometry(side)
    raw = prompt.encode('utf-8')[:g['prompt_bytes_max']]
    flat = np.zeros(g['cells'], dtype=np.uint8)
    for i, b in enumerate(raw):
        base = i * 4
        flat[base + 0] = (b >> 6) & 3
        flat[base + 1] = (b >> 4) & 3
        flat[base + 2] = (b >> 2) & 3
        flat[base + 3] =  b       & 3
    return flat.reshape(side, side)


def decode_byte_at_position_cell8_tier(board: np.ndarray, position: int,
                                              side: int) -> int:
    g = cell8_tier_geometry(side)
    flat = board.ravel()
    base = g['response_cells_start'] + position * 4
    return (((int(flat[base + 0]) & 3) << 6)
              | ((int(flat[base + 1]) & 3) << 4)
              | ((int(flat[base + 2]) & 3) << 2)
              |  (int(flat[base + 3]) & 3))


# ── Inference at arbitrary tier ────────────────────────────────────

def forward_byte_cell8_at_side(prompt: str, rule: np.ndarray,
                                       position: int, side: int, *,
                                       n_ticks: int = None,
                                       port_value: int = 0) -> int:
    """Run a cell8 rule on a (side, side) board with constant
    port_value broadcast, return the decoded byte at `position`."""
    if n_ticks is None:
        n_ticks = side
    state = embed_prompt_cell8_tier(prompt, side)
    inp = broadcast_input(side, port_value)
    for _ in range(n_ticks):
        state = hex_ca_step_cell8(state, inp, rule)
    return decode_byte_at_position_cell8_tier(state, position, side)


def forward_pair_cell8_at_side(prompt: str, rules,
                                       n_bytes: int, side: int, *,
                                       n_ticks: int = None,
                                       port_value: int = 0) -> bytes:
    """Inference: each per-position cell8 rule runs on its own
    (side, side) board, decode the byte."""
    if n_ticks is None:
        n_ticks = side
    out = bytearray()
    base_board = embed_prompt_cell8_tier(prompt, side)
    inp = broadcast_input(side, port_value)
    for pos in range(min(n_bytes, len(rules))):
        state = base_board.copy()
        for _ in range(n_ticks):
            state = hex_ca_step_cell8(state, inp, rules[pos])
        out.append(decode_byte_at_position_cell8_tier(state, pos, side))
    return bytes(out)


# ── Per-position GA training at arbitrary tier ─────────────────────

def train_position_cell8_at_side(prompt: str, target_byte: int,
                                       position: int, side: int, *,
                                       n_ticks: int = None,
                                       max_seconds: float = 60.0,
                                       pop_size: int = 8,
                                       generations_per_burst: int = 8,
                                       mutation_rate: float = 0.005,
                                       seed: int = 0xC81E5,
                                       seed_rule=None,
                                       port_value: int = 0,
                                       on_event=None) -> dict:
    """Train one cell8 rule for a (prompt, byte-at-position) target
    on a (side, side) board with port_value held constant.  Output
    is a 65,536-byte cell8 LUT.

    `seed_rule` can be 16,384 bytes (7→1, gets upcasted) or
    65,536 bytes (cell8, used as-is).

    Returns {'rule_table', 'byte_match', 'wall', 'phase'}."""
    if n_ticks is None:
        n_ticks = side

    fire = on_event or (lambda *_a, **_kw: None)
    t0 = time.time()
    rng = random.Random(seed)
    g = cell8_tier_geometry(side)
    base_offset = g['response_cells_start'] + position * 4
    # Bail early if the position doesn't fit on this tier's board —
    # caller should pick a larger tier.  Returns a "too_small" phase
    # so corpus scripts can pivot without crashing.
    if base_offset + 4 > g['cells']:
        return {'rule_table': None, 'byte_match': False,
                'side': side, 'wall': 0.0,
                'phase': 'too_small',
                'reason': (f'position {position} needs cell {base_offset + 3}'
                              f' but board only has {g["cells"]}')}
    target_cells = [(target_byte >> (6 - 2 * i)) & 3 for i in range(4)]
    inp = broadcast_input(side, port_value)

    def _run(rule):
        st = embed_prompt_cell8_tier(prompt, side)
        for _ in range(n_ticks):
            st = hex_ca_step_cell8(st, inp, rule)
        return st

    def _byte_match(rule):
        st = _run(rule)
        return decode_byte_at_position_cell8_tier(st, position, side) == target_byte

    def _fitness(rule):
        st = _run(rule)
        flat = st.ravel()
        cf = sum(1 for i in range(4)
                       if (int(flat[base_offset + i]) & 3) == target_cells[i]) / 4.0
        bonus = 1.0 if _byte_match(rule) else 0.0
        return cf + bonus

    # Seed (cell8 or 7→1 upcast).
    seed_arr = None
    if seed_rule is not None:
        sr_len = len(seed_rule)
        if sr_len == 16_384:
            from .board256 import upcast_7to1_to_cell8
            seed_arr = upcast_7to1_to_cell8(seed_rule)
        elif sr_len == LUT_SIZE_8:
            seed_arr = (np.frombuffer(seed_rule, dtype=np.uint8).copy()
                          if isinstance(seed_rule, (bytes, bytearray, memoryview))
                          else np.asarray(seed_rule, dtype=np.uint8).copy()) & 3
        else:
            raise ValueError(f'seed_rule must be 16,384 or {LUT_SIZE_8} bytes')

    pop = []
    for i in range(pop_size):
        if seed_arr is not None and i < (pop_size + 1) // 2:
            r = seed_arr.copy()
            if i > 0:
                jit_rng = random.Random(seed ^ (i * 31337))
                for _ in range(max(1, int(0.001 * LUT_SIZE_8))):
                    idx = jit_rng.randrange(LUT_SIZE_8)
                    cur = int(r[idx])
                    new = jit_rng.randint(0, 3)
                    while new == cur: new = jit_rng.randint(0, 3)
                    r[idx] = new
        else:
            r = random_rule_table_8(seed ^ (i * 7919))
        pop.append((r, _fitness(r)))
    pop.sort(key=lambda rf: -rf[1])
    best_rule, best_fit = pop[0]
    matched = _byte_match(best_rule)
    fire('init', {'best_fit': best_fit, 'matched': matched,
                    'side': side, 'elapsed_s': time.time() - t0})
    if matched:
        return {'rule_table': best_rule, 'byte_match': True,
                'side': side, 'wall': time.time() - t0, 'phase': 'init'}

    burst = 0
    while time.time() - t0 < max_seconds and not matched:
        burst += 1
        for _gen in range(generations_per_burst):
            if time.time() - t0 >= max_seconds:
                break
            parent = pop[rng.randrange(max(1, len(pop) // 2))][0]
            child = parent.copy()
            n_flips = max(1, int(mutation_rate * LUT_SIZE_8))
            for _ in range(n_flips):
                idx = rng.randrange(LUT_SIZE_8)
                cur = int(child[idx])
                new = rng.randint(0, 3)
                while new == cur: new = rng.randint(0, 3)
                child[idx] = new
            cf = _fitness(child)
            worst_idx = min(range(len(pop)), key=lambda i: pop[i][1])
            if cf > pop[worst_idx][1]:
                pop[worst_idx] = (child, cf)
                if cf > best_fit:
                    best_rule, best_fit = child, cf
                    matched = _byte_match(best_rule)
                    fire('improved', {'burst': burst, 'best_fit': cf,
                                          'matched': matched, 'side': side,
                                          'elapsed_s': time.time() - t0})
                    if matched:
                        break

    return {'rule_table': best_rule, 'byte_match': matched,
            'side': side, 'wall': time.time() - t0,
            'phase': 'matched' if matched else 'budget_out'}


def train_pair_cell8_at_side(prompt: str, expected: str, side: int, *,
                                    n_ticks: int = None,
                                    per_position_seconds: float = 60.0,
                                    seed: int = 0xC81E5,
                                    port_value: int = 0,
                                    on_event=None) -> dict:
    """Per-position cell8 training at arbitrary tier."""
    fire = on_event or (lambda *_a, **_kw: None)
    g = cell8_tier_geometry(side)
    target_bytes = expected.encode('utf-8')[:g['response_bytes_max']]
    t0 = time.time()
    rules, matches = [], []
    for pos, tb in enumerate(target_bytes):
        fire('position_start', {'pos': pos, 'side': side,
                                    'target_byte': tb,
                                    'elapsed_s': time.time() - t0})
        r = train_position_cell8_at_side(
            prompt, tb, pos, side,
            n_ticks=n_ticks,
            max_seconds=per_position_seconds,
            seed=seed ^ (pos * 4099),
            port_value=port_value,
            on_event=lambda k, p, _pos=pos: fire(f'pos{_pos}_{k}', p))
        rules.append(r['rule_table'])
        matches.append(bool(r['byte_match']))
        fire('position_done', {'pos': pos, 'side': side,
                                    'matched': r['byte_match'],
                                    'phase': r['phase'],
                                    'pos_wall': r['wall'],
                                    'elapsed_s': time.time() - t0})
    return {'rules': rules, 'matches': matches,
            'exact': all(matches), 'side': side,
            'wall': time.time() - t0}


# Tier name → side conversion used by the schema fields.
TIER_SIDES = {
    'b008': 8, 'b016': 16, 'b032': 32, 'b064': 64, 'b128': 128,
}
