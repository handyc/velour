"""256×256 K=4 single-board forward + per-position cell8 training.

Scaled-up sibling of board128.  Two reasons it's not just board128 with
a bigger constant:

  1. **Ouroboros symmetry.**  A cell8 (8→1) rule LUT is 4^8 = 65,536
     entries — exactly one 256×256 K=4 board.  At 128×128 that match
     is broken (board=16,384 cells, LUT=65,536 bytes), and we lose
     mandelhunt-style fractal-derived rule seeding, strict-L0 quine
     search, metapact recursive chains, and everything else that
     depends on a rule being runnable on its own representation.
     256×256 puts cell8 in the same self-mapping symmetry that
     7→1 enjoys at 128×128.

  2. **Capacity.**  4× more cells = 4× the joint embedding bandwidth.
     Prompt + response can each grow to 8,192 bytes (vs 2,048 at the
     128×128 tier), so longer dialogue context fits in one board.

Same per-position training scheme as board128: one cell8 rule per
output byte, each trained independently.  Phase A: input port held
at 0 across the board (no conditional output yet); Phase B will
wire the port to a router category or DMN tick.

Default n_ticks=256 (signal needs more time to propagate across the
wider grid; 128 ticks at 256-cell-wide barely covers half the
diameter).  Per-position inference is ~8× the board128 cost (4×
cells × 2× ticks).
"""
from __future__ import annotations

import numpy as np

from .cell8 import (LUT_SIZE_8, broadcast_input, hex_ca_step_cell8,
                       random_rule_table_8)
from .primitives import hex_ca_step


# ── 7→1 ↔ 8→1 LUT conversion ───────────────────────────────────────
#
# The 7→1 and 8→1 hex CA rules share the same 7 cells (self + 6 hex
# neighbours).  The 8→1 key just prepends a 2-bit "port" value in
# the top 2 bits:
#
#     7→1 key (14 bits):       self | nw | ne | r | se | sw | l
#     8→1 key (16 bits): port | self | nw | ne | r | se | sw | l
#
# So upcasting 7→1 → 8→1 is lossless: tile the 16,384-entry LUT
# four times (once per port value).  The resulting 8→1 rule behaves
# byte-identically to the original 7→1 rule for ANY port broadcast.
# This means every existing board128 rule is a free warm-start for
# cell8 training — the GA never starts from random.
#
# The reverse direction (8→1 → 7→1) is only lossless if the rule
# never used the port (all 4 quarters agree); otherwise lossy.


def upcast_7to1_to_cell8(lut_7to1) -> np.ndarray:
    """Promote a 16,384-byte 7→1 LUT to a 65,536-byte cell8 LUT by
    tiling it 4 times — once per port value.  Output port behaviour
    is identical across all 4 port values (the rule "ignores" the
    port), so running this cell8 rule with any port broadcast
    reproduces the 7→1 rule's step exactly."""
    if isinstance(lut_7to1, (bytes, bytearray, memoryview)):
        arr = np.frombuffer(lut_7to1, dtype=np.uint8)
    else:
        arr = np.asarray(lut_7to1, dtype=np.uint8)
    if arr.size != 16_384:
        raise ValueError(
            f'7→1 LUT must be 16,384 bytes; got {arr.size}')
    return np.tile(arr & 3, 4)        # 65,536 bytes


def is_port_agnostic(cell8_lut: np.ndarray) -> bool:
    """True iff the 4 port quarters of an 8→1 LUT are byte-identical
    — i.e. the rule's output never depends on the port value.  These
    are the cell8 rules that can be losslessly downcast to 7→1."""
    arr = np.asarray(cell8_lut, dtype=np.uint8).ravel()
    if arr.size != LUT_SIZE_8:
        raise ValueError(f'cell8 LUT must be {LUT_SIZE_8} bytes; got {arr.size}')
    q0 = arr[0:16_384]
    return (bool(np.array_equal(q0, arr[16_384:32_768]))
            and bool(np.array_equal(q0, arr[32_768:49_152]))
            and bool(np.array_equal(q0, arr[49_152:65_536])))


def downcast_cell8_to_7to1(cell8_lut: np.ndarray) -> bytes:
    """Reverse of upcast_7to1_to_cell8.  Only lossless when the rule
    is port-agnostic; otherwise raises ValueError (caller can pick a
    specific quarter manually if a lossy downcast is acceptable)."""
    arr = np.asarray(cell8_lut, dtype=np.uint8).ravel()
    if not is_port_agnostic(arr):
        raise ValueError(
            'cell8 LUT is not port-agnostic — port quarters differ; '
            'downcast would be lossy.  Slice arr[port*16384:(port+1)*16384] '
            'manually if you want to keep one specific port behaviour.')
    return bytes(arr[0:16_384])


# ── Board geometry ─────────────────────────────────────────────────

BOARD_SIDE_256   = 256
BOARD_CELLS_256  = BOARD_SIDE_256 * BOARD_SIDE_256       # 65,536
BYTES_PER_CELL_BLOCK = 4                                    # 4 base-4 digits = 1 byte
MAX_BYTES_TOTAL_256 = BOARD_CELLS_256 // BYTES_PER_CELL_BLOCK   # 16,384

PROMPT_BYTES_MAX_256   = MAX_BYTES_TOTAL_256 // 2           # 8,192
RESPONSE_BYTES_MAX_256 = MAX_BYTES_TOTAL_256 // 2           # 8,192
PROMPT_CELLS_START_256   = 0
PROMPT_CELLS_END_256     = PROMPT_BYTES_MAX_256 * BYTES_PER_CELL_BLOCK   # 32,768
RESPONSE_CELLS_START_256 = PROMPT_CELLS_END_256
RESPONSE_CELLS_END_256   = MAX_BYTES_TOTAL_256 * BYTES_PER_CELL_BLOCK    # 65,536

DEFAULT_N_TICKS_256 = 256


# ── Embedding / decoding ───────────────────────────────────────────

def embed_prompt_256(prompt: str) -> np.ndarray:
    """Embed up to PROMPT_BYTES_MAX_256 bytes of `prompt` into a
    256×256 K=4 board.  Same scheme as board128.embed_prompt — 4
    base-4 digits per byte starting at cell 0."""
    raw = prompt.encode('utf-8')[:PROMPT_BYTES_MAX_256]
    flat = np.zeros(BOARD_CELLS_256, dtype=np.uint8)
    for i, b in enumerate(raw):
        flat[i * 4 + 0] = (b >> 6) & 3
        flat[i * 4 + 1] = (b >> 4) & 3
        flat[i * 4 + 2] = (b >> 2) & 3
        flat[i * 4 + 3] =  b       & 3
    return flat.reshape(BOARD_SIDE_256, BOARD_SIDE_256)


def embed_pair_256(prompt: str, response: str) -> np.ndarray:
    """Embed both prompt and (target) response — used for fitness
    teacher-forcing."""
    board = embed_prompt_256(prompt)
    flat = board.ravel().copy()
    raw = response.encode('utf-8')[:RESPONSE_BYTES_MAX_256]
    for i, b in enumerate(raw):
        base = RESPONSE_CELLS_START_256 + i * 4
        flat[base + 0] = (b >> 6) & 3
        flat[base + 1] = (b >> 4) & 3
        flat[base + 2] = (b >> 2) & 3
        flat[base + 3] =  b       & 3
    return flat.reshape(BOARD_SIDE_256, BOARD_SIDE_256)


def decode_response_256(board: np.ndarray, n_bytes: int) -> bytes:
    flat = board.ravel()
    out = bytearray()
    n = min(n_bytes, RESPONSE_BYTES_MAX_256)
    for i in range(n):
        base = RESPONSE_CELLS_START_256 + i * 4
        b = ((int(flat[base + 0]) & 3) << 6) \
          | ((int(flat[base + 1]) & 3) << 4) \
          | ((int(flat[base + 2]) & 3) << 2) \
          | ( int(flat[base + 3]) & 3)
        out.append(b)
    return bytes(out)


def decode_byte_at_position_256(board: np.ndarray, position: int) -> int:
    flat = board.ravel()
    base = RESPONSE_CELLS_START_256 + position * 4
    return (((int(flat[base + 0]) & 3) << 6)
          | ((int(flat[base + 1]) & 3) << 4)
          | ((int(flat[base + 2]) & 3) << 2)
          |  (int(flat[base + 3]) & 3))


# ── Forward inference ──────────────────────────────────────────────

def forward_board_cell8(prompt: str, rule_table: np.ndarray, *,
                            n_ticks: int = DEFAULT_N_TICKS_256,
                            port_value: int = 0,
                            response_bytes: int) -> bytes:
    """Run one cell8 forward pass on a 256×256 board seeded with the
    embedded prompt.  Input port broadcast to `port_value` across the
    whole grid."""
    state = embed_prompt_256(prompt)
    inp = broadcast_input(BOARD_SIDE_256, port_value)
    for _ in range(n_ticks):
        state = hex_ca_step_cell8(state, inp, rule_table)
    return decode_response_256(state, response_bytes)


def cell_match_for_position_256(prompt: str, target_byte: int,
                                       position: int,
                                       rule_table: np.ndarray, *,
                                       n_ticks: int = DEFAULT_N_TICKS_256,
                                       port_value: int = 0) -> float:
    """Fraction of the 4 target-cells at `position` that match after
    n_ticks.  Smooth gradient signal for the GA."""
    state = embed_prompt_256(prompt)
    inp = broadcast_input(BOARD_SIDE_256, port_value)
    for _ in range(n_ticks):
        state = hex_ca_step_cell8(state, inp, rule_table)
    flat = state.ravel()
    base = RESPONSE_CELLS_START_256 + position * 4
    target_cells = [(target_byte >> (6 - 2 * i)) & 3 for i in range(4)]
    matches = sum(1 for i in range(4)
                       if (int(flat[base + i]) & 3) == target_cells[i])
    return matches / 4.0


# ── Per-position GA training ───────────────────────────────────────
#
# Phase A: port held at 0.  The cell8 rule's port-0 quarter (entries
# 0..16,383) is the only part the GA explores; the port-1 quarter
# stays random and unused.  Once Phase A validates the pipeline, the
# trainer in this file gets a port_source kwarg that toggles between
# port-0 (Phase A behaviour) and a modulation source (Phase B).

def train_position_board256(prompt: str, target_byte: int,
                                  position: int, *,
                                  n_ticks: int = DEFAULT_N_TICKS_256,
                                  max_seconds: float = 120.0,
                                  pop_size: int = 8,
                                  generations_per_burst: int = 8,
                                  polish_trials: int = 80,
                                  mutation_rate: float = 0.005,
                                  seed: int = 0xB256A1E,
                                  seed_rule: bytes = None,
                                  port_value: int = 0,
                                  on_event=None) -> dict:
    """Train one cell8 rule for a single (prompt, byte-at-position)
    target on a 256×256 board.  Mirrors train_position_board128's
    GA loop but with the 8→1 LUT (65,536 entries) and a fixed
    input-port broadcast.

    `seed_rule`: optional 65,536-byte cell8 LUT for warm-start
    (half the population starts as small perturbations of it).
    `port_value`: K=4 colour broadcast to every cell's input port.
    Phase A keeps this at 0 throughout.

    Returns {'rule_table': np.ndarray(65536, uint8),
             'byte_match': bool, 'wall': float,
             'phase': 'init'|'matched'|'budget_out'}."""
    import random
    import time
    from .ga import polish_genome

    fire = on_event or (lambda *_a, **_kw: None)
    t0 = time.time()
    rng = random.Random(seed)
    inp = broadcast_input(BOARD_SIDE_256, port_value)

    def _run(rule, prm, ticks):
        st = embed_prompt_256(prm)
        for _ in range(ticks):
            st = hex_ca_step_cell8(st, inp, rule)
        return st

    def _byte_match(rule):
        b = decode_byte_at_position_256(_run(rule, prompt, n_ticks), position)
        return b == target_byte

    def _fitness(rule):
        cf = cell_match_for_position_256(prompt, target_byte, position,
                                                rule, n_ticks=n_ticks,
                                                port_value=port_value)
        bonus = 1.0 if _byte_match(rule) else 0.0
        return cf + bonus

    # Initial population — warm-start handling.  seed_rule can be a
    # 65,536-byte cell8 LUT (used as-is) or a 16,384-byte 7→1 LUT
    # (auto-upcasted via tile-4×, port-agnostic).
    pop = []
    seed_arr = None
    if seed_rule is not None:
        sr_len = len(seed_rule)
        if sr_len == 16_384:
            seed_arr = upcast_7to1_to_cell8(seed_rule)
        elif sr_len == LUT_SIZE_8:
            seed_arr = np.frombuffer(seed_rule, dtype=np.uint8).copy() & 3
        else:
            raise ValueError(
                f'seed_rule must be 16,384 (7→1) or {LUT_SIZE_8} (cell8) bytes; '
                f'got {sr_len}')
    for i in range(pop_size):
        if seed_arr is not None and i < (pop_size + 1) // 2:
            r = seed_arr.copy()
            if i > 0:
                jit_rng = random.Random(seed ^ (i * 31337))
                n_flips = max(1, int(0.001 * LUT_SIZE_8))   # ~65 entries
                for _ in range(n_flips):
                    idx = jit_rng.randrange(LUT_SIZE_8)
                    cur = int(r[idx])
                    new = jit_rng.randint(0, 3)
                    while new == cur:
                        new = jit_rng.randint(0, 3)
                    r[idx] = new
        else:
            r = random_rule_table_8(seed ^ (i * 7919))
        pop.append((r, _fitness(r)))
    pop.sort(key=lambda rf: -rf[1])
    best_rule, best_fit = pop[0]
    matched = _byte_match(best_rule)
    fire('init', {'best_fit': best_fit, 'matched': matched,
                    'elapsed_s': time.time() - t0})
    if matched:
        return {'rule_table': best_rule, 'byte_match': True,
                'wall': time.time() - t0, 'phase': 'init'}

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
        if time.time() - t0 >= max_seconds:
            break
        def _polish_fitness(g):
            return _fitness(g['output'])
        polished, polished_fit, n_imp = polish_genome(
            {'output': best_rule.copy()}, _polish_fitness,
            trials=polish_trials,
            seed=seed ^ 0xC0FFEE ^ (burst * 31))
        if polished_fit > best_fit:
            best_rule = polished['output']
            best_fit = polished_fit
            matched = _byte_match(best_rule)
            fire('polish', {'burst': burst, 'best_fit': best_fit,
                                'matched': matched, 'n_imp': n_imp,
                                'elapsed_s': time.time() - t0})

    return {'rule_table': best_rule, 'byte_match': matched,
            'wall': time.time() - t0,
            'phase': 'matched' if matched else 'budget_out'}


def train_pair_board256(prompt: str, expected: str, *,
                              n_ticks: int = DEFAULT_N_TICKS_256,
                              per_position_seconds: float = 120.0,
                              seed: int = 0xB256A1E,
                              port_value: int = 0,
                              on_event=None) -> dict:
    """Train one cell8 rule per byte of `expected`.  Sequential per
    position; total wall = N × per_position_seconds at worst."""
    import time
    fire = on_event or (lambda *_a, **_kw: None)
    target_bytes = expected.encode('utf-8')[:RESPONSE_BYTES_MAX_256]
    t0 = time.time()
    rules, matches = [], []
    for pos, tb in enumerate(target_bytes):
        fire('position_start', {'pos': pos, 'target_byte': tb,
                                    'target_char': chr(tb) if 32 <= tb < 127
                                       else f'\\x{tb:02x}',
                                    'elapsed_s': time.time() - t0})
        r = train_position_board256(
            prompt, tb, pos,
            n_ticks=n_ticks,
            max_seconds=per_position_seconds,
            seed=seed ^ (pos * 4099),
            port_value=port_value,
            on_event=lambda k, p, _pos=pos: fire(f'pos{_pos}_{k}', p))
        rules.append(r['rule_table'])
        matches.append(bool(r['byte_match']))
        fire('position_done', {'pos': pos,
                                    'matched': r['byte_match'],
                                    'phase': r['phase'],
                                    'pos_wall': r['wall'],
                                    'elapsed_s': time.time() - t0})
    return {'rules': rules, 'matches': matches,
            'exact': all(matches),
            'wall': time.time() - t0}


# ── Modulated per-position training: two targets, two port values ─

def _cell_match_at_port(prompt, target_byte, position, rule,
                            n_ticks, port_value):
    state = embed_prompt_256(prompt)
    inp = broadcast_input(BOARD_SIDE_256, port_value)
    for _ in range(n_ticks):
        state = hex_ca_step_cell8(state, inp, rule)
    flat = state.ravel()
    base = RESPONSE_CELLS_START_256 + position * 4
    cells = [(target_byte >> (6 - 2 * i)) & 3 for i in range(4)]
    return (sum(1 for i in range(4)
                       if (int(flat[base + i]) & 3) == cells[i]) / 4.0,
            decode_byte_at_position_256(state, position))


def train_position_board256_modulated(
        prompt: str, target_base: int, target_alt: int,
        position: int, *,
        n_ticks: int = DEFAULT_N_TICKS_256,
        max_seconds: float = 120.0,
        pop_size: int = 8,
        generations_per_burst: int = 8,
        mutation_rate: float = 0.005,
        seed: int = 0xB256A1E,
        warm_start_base=None,           # 16,384 B (7→1) or 65,536 B (cell8)
        freeze_port0: bool = False,
        on_event=None) -> dict:
    """Train one cell8 rule whose port=0 / port=1 outputs at `position`
    are `target_base` and `target_alt` respectively (256×256 board).

    Warm-start: `warm_start_base` accepts either format — a 7→1 LUT
    gets upcasted, a cell8 LUT is used as-is.  When upcasted from
    7→1, the port=0 quarter ALREADY produces target_base byte-exactly
    (assuming the 7→1 rule was trained for it), so `freeze_port0=True`
    restricts mutations to the port=1 quarter (entries 16,384..32,767)
    and the GA only has to learn the alt behaviour.

    Returns {'rule_table', 'matches': (base, alt), 'wall', 'phase'}."""
    import random
    import time

    fire = on_event or (lambda *_a, **_kw: None)
    rng = random.Random(seed)
    t0 = time.time()

    def _fitness(rule):
        cf0, b0 = _cell_match_at_port(prompt, target_base, position, rule,
                                              n_ticks, 0)
        cf1, b1 = _cell_match_at_port(prompt, target_alt,  position, rule,
                                              n_ticks, 1)
        bonus = (1.0 if b0 == target_base else 0.0) \
              + (1.0 if b1 == target_alt  else 0.0)
        return cf0 + cf1 + bonus

    def _matches(rule):
        _, b0 = _cell_match_at_port(prompt, target_base, position, rule,
                                          n_ticks, 0)
        _, b1 = _cell_match_at_port(prompt, target_alt,  position, rule,
                                          n_ticks, 1)
        return (b0 == target_base, b1 == target_alt)

    # Build seed rule.
    if warm_start_base is not None:
        wsl = len(warm_start_base)
        if wsl == 16_384:
            seed_arr = upcast_7to1_to_cell8(warm_start_base)
        elif wsl == LUT_SIZE_8:
            seed_arr = (np.frombuffer(warm_start_base, dtype=np.uint8).copy()
                            if isinstance(warm_start_base, (bytes, bytearray,
                                                                  memoryview))
                            else np.asarray(warm_start_base, dtype=np.uint8).copy()) & 3
        else:
            raise ValueError(
                f'warm_start_base must be 16,384 or {LUT_SIZE_8} bytes; got {wsl}')
    else:
        seed_arr = None

    pop = []
    for i in range(pop_size):
        if seed_arr is not None and i < (pop_size + 1) // 2:
            r = seed_arr.copy()
            if i > 0:
                jit_rng = random.Random(seed ^ (i * 31337))
                n_flips = max(1, int(0.001 * LUT_SIZE_8))
                # Even initial perturbations respect freeze_port0.
                jit_lo = 16_384 if freeze_port0 else 0
                jit_hi = 32_768 if freeze_port0 else LUT_SIZE_8
                for _ in range(n_flips):
                    idx = jit_rng.randrange(jit_lo, jit_hi)
                    cur = int(r[idx])
                    new = jit_rng.randint(0, 3)
                    while new == cur: new = jit_rng.randint(0, 3)
                    r[idx] = new
        else:
            r = random_rule_table_8(seed ^ (i * 7919))
        pop.append((r, _fitness(r)))
    pop.sort(key=lambda rf: -rf[1])
    best_rule, best_fit = pop[0]
    matches = _matches(best_rule)
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
            mut_lo = 16_384 if freeze_port0 else 0
            mut_hi = 32_768 if freeze_port0 else LUT_SIZE_8
            for _ in range(n_flips):
                idx = rng.randrange(mut_lo, mut_hi)
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
                    matches = _matches(best_rule)
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


# ── Pool-as-context: paint a class-4 LUT into the board init state ─
#
# The board256 layout has lots of unused cells: prompts in the corpus
# are 2-30 bytes (8-120 cells), leaving ~32K cells in the prompt
# region as zero padding.  Rather than waste them, we paint a class-4
# LUT (e.g. a mandelhunt-derived rule) into those cells as part of
# the initial state.  The cell8 rule trains to produce its target
# byte *regardless* of which class-4 LUT was painted — i.e. it learns
# to be context-invariant.  At inference time, swapping the painted
# context changes the intermediate CA dynamics (visually) without
# changing the output byte.  This is the substrate for Phase 3
# (where the context selects different output bytes).
#
# Context region: cells [CONTEXT_OFFSET .. CONTEXT_OFFSET+CONTEXT_LEN)
# = cells 8192..24575 (16,384 cells = exactly one 7→1 LUT or one
# quarter of a cell8 LUT).  Sits between the prompt (which fills the
# first few hundred cells) and the response region (which starts at
# RESPONSE_CELLS_START_256 = 32,768).  No collision with prompt or
# response for any corpus pair (longest prompt is ~30 bytes = 120
# cells).

CONTEXT_OFFSET_256 = 8192     # cells 8192..24575 = context region
CONTEXT_LEN_256    = 16384    # exactly one 16K LUT


def paint_context_into_state(state: np.ndarray, context_bytes: bytes,
                                   offset: int = CONTEXT_OFFSET_256,
                                   length: int = CONTEXT_LEN_256) -> np.ndarray:
    """Overlay `context_bytes` (must be >= length bytes) into the
    flat-cell range [offset .. offset+length).  Each byte's lower
    2 bits becomes the cell value (K=4).  Non-destructive — returns
    a new array."""
    if len(context_bytes) < length:
        raise ValueError(
            f'context_bytes must have >= {length} bytes; got {len(context_bytes)}')
    arr = np.asarray(state, dtype=np.uint8).copy()
    flat = arr.ravel()
    ctx = np.frombuffer(context_bytes[:length], dtype=np.uint8) & 3
    flat[offset:offset + length] = ctx
    return arr.reshape(state.shape)


def train_position_b256_pool_context(
        prompt: str, target_byte: int, position: int, *,
        context_pool,                  # list of bytes objects, each >=16384 B
        n_ticks: int = DEFAULT_N_TICKS_256,
        max_seconds: float = 300.0,
        pop_size: int = 8,
        generations_per_burst: int = 8,
        mutation_rate: float = 0.005,
        seed: int = 0xC02E7E47,
        seed_rule=None,
        port_value: int = 0,
        on_event=None) -> dict:
    """Train one cell8 rule to produce `target_byte` at `position`
    INVARIANT TO which member of `context_pool` is painted into the
    board's context region.

    Fitness averages cell-match across all pool members; byte-match
    requires ALL pool members to produce the target byte.  Cost
    scales with len(context_pool).  Typical K=2..4 keeps wall time
    sane.

    `context_pool` is a list of >=16,384-byte blobs (mandelhunt LUTs,
    julia LUTs, etc. — anything class-4-ish).  Pool is fixed across
    training; new pool members can be tested at inference time."""
    import random
    import time

    fire = on_event or (lambda *_a, **_kw: None)
    rng = random.Random(seed)
    t0 = time.time()
    inp = broadcast_input(BOARD_SIDE_256, port_value)
    K = len(context_pool)
    if K == 0:
        raise ValueError('context_pool must not be empty')
    target_cells = [(target_byte >> (6 - 2 * i)) & 3 for i in range(4)]
    base_offset = RESPONSE_CELLS_START_256 + position * 4

    def _run_with_context(rule, ctx_idx):
        state = embed_prompt_256(prompt)
        state = paint_context_into_state(state, context_pool[ctx_idx])
        for _ in range(n_ticks):
            state = hex_ca_step_cell8(state, inp, rule)
        return state

    def _fitness(rule):
        total_cell_match = 0.0
        bonus = 0.0
        for k in range(K):
            st = _run_with_context(rule, k)
            flat = st.ravel()
            cm = sum(1 for i in range(4)
                          if (int(flat[base_offset + i]) & 3) == target_cells[i])
            total_cell_match += cm / 4.0
            byte = ((int(flat[base_offset + 0]) & 3) << 6) \
                 | ((int(flat[base_offset + 1]) & 3) << 4) \
                 | ((int(flat[base_offset + 2]) & 3) << 2) \
                 |  (int(flat[base_offset + 3]) & 3)
            if byte == target_byte:
                bonus += 1.0
        return total_cell_match + bonus

    def _byte_match_all(rule):
        for k in range(K):
            st = _run_with_context(rule, k)
            flat = st.ravel()
            byte = ((int(flat[base_offset + 0]) & 3) << 6) \
                 | ((int(flat[base_offset + 1]) & 3) << 4) \
                 | ((int(flat[base_offset + 2]) & 3) << 2) \
                 |  (int(flat[base_offset + 3]) & 3)
            if byte != target_byte:
                return False, k
        return True, -1

    # Initial population.
    pop = []
    seed_arr = None
    if seed_rule is not None:
        sr_len = len(seed_rule)
        if sr_len == 16_384:
            seed_arr = upcast_7to1_to_cell8(seed_rule)
        elif sr_len == LUT_SIZE_8:
            seed_arr = (np.frombuffer(seed_rule, dtype=np.uint8).copy()
                          if isinstance(seed_rule, (bytes, bytearray, memoryview))
                          else np.asarray(seed_rule, dtype=np.uint8).copy()) & 3
        else:
            raise ValueError(
                f'seed_rule must be 16,384 or {LUT_SIZE_8} bytes; got {sr_len}')
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
    matched, miss_ctx = _byte_match_all(best_rule)
    fire('init', {'best_fit': best_fit, 'matched': matched,
                    'miss_ctx': miss_ctx, 'K': K,
                    'elapsed_s': time.time() - t0})
    if matched:
        return {'rule_table': best_rule, 'byte_match_all': True,
                'K': K, 'wall': time.time() - t0, 'phase': 'init'}

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
                    matched, miss_ctx = _byte_match_all(best_rule)
                    fire('improved', {'burst': burst, 'best_fit': cf,
                                          'matched': matched,
                                          'miss_ctx': miss_ctx,
                                          'elapsed_s': time.time() - t0})
                    if matched:
                        break

    return {'rule_table': best_rule, 'byte_match_all': matched,
            'K': K, 'wall': time.time() - t0,
            'phase': 'matched' if matched else 'budget_out'}


def forward_byte_with_context(prompt: str, rule: np.ndarray,
                                     context_bytes: bytes, position: int, *,
                                     n_ticks: int = DEFAULT_N_TICKS_256,
                                     port_value: int = 0) -> int:
    """Inference helper: run cell8 `rule` on a board seeded with
    `prompt` + `context_bytes` painted; return the byte decoded at
    `position`.  Use to confirm context-invariance at inference."""
    inp = broadcast_input(BOARD_SIDE_256, port_value)
    state = embed_prompt_256(prompt)
    state = paint_context_into_state(state, context_bytes)
    for _ in range(n_ticks):
        state = hex_ca_step_cell8(state, inp, rule)
    return decode_byte_at_position_256(state, position)


def forward_pair_board256_positional(prompt: str, rules,
                                            n_bytes: int, *,
                                            n_ticks: int = DEFAULT_N_TICKS_256,
                                            port_value: int = 0) -> bytes:
    """Inference: each per-position rule runs independently on the
    embedded prompt for n_ticks, decodes its byte, concatenated."""
    out = bytearray()
    base_board = embed_prompt_256(prompt)
    inp = broadcast_input(BOARD_SIDE_256, port_value)
    for pos in range(min(n_bytes, len(rules))):
        state = base_board.copy()
        rule = rules[pos]
        for _ in range(n_ticks):
            state = hex_ca_step_cell8(state, inp, rule)
        out.append(decode_byte_at_position_256(state, pos))
    return bytes(out)
