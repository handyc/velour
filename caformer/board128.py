"""128×128 K=4 single-board forward + per-pair training.

The architecture pivot from per-position chains:

  - Old: an N-byte response trains N chains, each running the
    transformer stack over a growing context.  Cost scales O(N²)
    with response length.  Tops out at ~5-char responses on long
    prompts because each position's per-byte teacher-forced fitness
    eats most of the budget.

  - New: the entire prompt (up to 4096 bytes) and entire response
    (up to 4096 bytes) live in a single 128×128 K=4 board, 4 base-4
    digits per byte.  One CA rule runs for N ticks; the response is
    decoded from a designated region of the final board.  Cost is
    O(1) in response length — the whole answer materialises in
    parallel.

Board layout (mirrors the router embedding scheme):
  - Cells 0..(LEN_INPUT*4-1)  = prompt bytes, 4 cells per byte
  - Cells (LEN_INPUT*4)..(LEN_INPUT*4 + LEN_OUTPUT*4 - 1)
                              = response bytes (target), 4 cells/byte
  - Remaining cells           = padding (zeros)

At 128×128 = 16,384 cells total, dedicating 8,192 cells to prompt
(2,048 bytes) and 8,192 cells to response (2,048 bytes) gives us
the spec'd 4096-char total input + output bandwidth.

One rule learned per pair.  Storage: 16 KB per pair (vs N × 16 KB
in the per-position scheme).  Training uses GA with fire-mask-
restricted mutation (essential at 128×128 — the LUT can have many
more queried entries than at 8×8 but still <5% of the full 16,384).
"""
from __future__ import annotations

import numpy as np

from .primitives import (compute_fire_mask, hex_ca_step,
                          random_rule_table)


# ── Board geometry ─────────────────────────────────────────────────

BOARD_SIDE   = 128                       # 128×128 K=4 hex grid
BOARD_CELLS  = BOARD_SIDE * BOARD_SIDE   # 16,384
BYTES_PER_CELL_BLOCK = 4                  # 4 base-4 digits = 1 byte
MAX_BYTES_TOTAL = BOARD_CELLS // BYTES_PER_CELL_BLOCK   # 4,096

# Top half = prompt, bottom half = response.  Each gets 2,048 bytes
# of capacity (8,192 cells).  Pad with zeros at the boundary.
PROMPT_BYTES_MAX = MAX_BYTES_TOTAL // 2     # 2,048
RESPONSE_BYTES_MAX = MAX_BYTES_TOTAL // 2   # 2,048
PROMPT_CELLS_START   = 0
PROMPT_CELLS_END     = PROMPT_BYTES_MAX * BYTES_PER_CELL_BLOCK   # 8,192
RESPONSE_CELLS_START = PROMPT_CELLS_END
RESPONSE_CELLS_END   = MAX_BYTES_TOTAL * BYTES_PER_CELL_BLOCK    # 16,384


def embed_prompt(prompt: str) -> np.ndarray:
    """Embed a prompt of up to PROMPT_BYTES_MAX bytes into a 128×128
    K=4 board.  Layout: top-left to mid, 4 base-4 digits per byte;
    response region stays zero (the CA fills it in during forward)."""
    raw = prompt.encode('utf-8')[:PROMPT_BYTES_MAX]
    flat = np.zeros(BOARD_CELLS, dtype=np.uint8)
    for i, b in enumerate(raw):
        flat[i * 4 + 0] = (b >> 6) & 3
        flat[i * 4 + 1] = (b >> 4) & 3
        flat[i * 4 + 2] = (b >> 2) & 3
        flat[i * 4 + 3] =  b       & 3
    return flat.reshape(BOARD_SIDE, BOARD_SIDE)


def embed_pair(prompt: str, response: str) -> np.ndarray:
    """Embed both prompt and (target) response — used for training
    fire-mask computation and for fitness teacher-forcing."""
    board = embed_prompt(prompt)
    flat = board.ravel().copy()
    raw = response.encode('utf-8')[:RESPONSE_BYTES_MAX]
    for i, b in enumerate(raw):
        base = RESPONSE_CELLS_START + i * 4
        flat[base + 0] = (b >> 6) & 3
        flat[base + 1] = (b >> 4) & 3
        flat[base + 2] = (b >> 2) & 3
        flat[base + 3] =  b       & 3
    return flat.reshape(BOARD_SIDE, BOARD_SIDE)


def decode_response(board: np.ndarray, n_bytes: int) -> bytes:
    """Decode `n_bytes` bytes from the response region of a 128×128
    board.  Inverse of embed_pair() for the response region."""
    flat = board.ravel()
    out = bytearray()
    n = min(n_bytes, RESPONSE_BYTES_MAX)
    for i in range(n):
        base = RESPONSE_CELLS_START + i * 4
        b = ((int(flat[base + 0]) & 3) << 6) \
          | ((int(flat[base + 1]) & 3) << 4) \
          | ((int(flat[base + 2]) & 3) << 2) \
          | ( int(flat[base + 3]) & 3)
        out.append(b)
    return bytes(out)


def forward_board(prompt: str, rule_table: np.ndarray, *,
                    n_ticks: int = 128, response_bytes: int) -> bytes:
    """Run one CA forward pass on a 128×128 board seeded with the
    embedded prompt.  Returns `response_bytes` bytes decoded from
    the response region of the final board."""
    state = embed_prompt(prompt)
    for _ in range(n_ticks):
        state = hex_ca_step(state, rule_table)
    return decode_response(state, response_bytes)


def cell_match_fraction(prompt: str, target_response: str,
                          rule_table: np.ndarray, *,
                          n_ticks: int = 128) -> float:
    """Fraction of response-region CELLS that match the target's
    embedding after n_ticks of running the rule on the prompt.
    Smoother gradient signal than byte-exact matching."""
    target_board = embed_pair(prompt, target_response).ravel()
    state = embed_prompt(prompt)
    for _ in range(n_ticks):
        state = hex_ca_step(state, rule_table)
    flat = state.ravel()
    n_target = len(target_response.encode('utf-8')[:RESPONSE_BYTES_MAX])
    n_cells = n_target * 4
    if n_cells == 0:
        return 1.0
    matches = int(((flat[RESPONSE_CELLS_START
                             : RESPONSE_CELLS_START + n_cells]
                       & 3) ==
                       (target_board[RESPONSE_CELLS_START
                                          : RESPONSE_CELLS_START + n_cells]
                          & 3)).sum())
    return matches / n_cells


def byte_match_count(prompt: str, target_response: str,
                       rule_table: np.ndarray, *,
                       n_ticks: int = 128) -> int:
    """Count of byte-exact matches in the decoded response."""
    target_bytes = target_response.encode('utf-8')[:RESPONSE_BYTES_MAX]
    produced = forward_board(prompt, rule_table, n_ticks=n_ticks,
                                response_bytes=len(target_bytes))
    return sum(1 for a, b in zip(produced, target_bytes) if a == b)


# ── Per-position single-byte training on 128×128 boards ─────────────
#
# The single-rule architecture above plateaus on multi-byte joint
# constraint satisfaction (validated 2026-05-18: 1-byte trains EXACT
# in ~20s but 5-byte target plateaus at 2/5 after 30 min).
#
# The fix that actually works: one rule per OUTPUT POSITION.  Each
# rule trains independently against its own single-byte target —
# exactly the trivially-solvable case.  No teacher-forcing, no
# context growth across positions; the entire 4096-char prompt
# embeds once into a 128×128 board and every position's rule
# reads from that same starting state.
#
# Storage: N × 16 KB per pair (vs N × 16 KB for the legacy per-
# position chains; same cost, much bigger context bandwidth).

def decode_byte_at_position(board: np.ndarray, position: int) -> int:
    """Decode one byte from `position`th 4-cell block of the response
    region.  Inverse of the embed scheme."""
    flat = board.ravel()
    base = RESPONSE_CELLS_START + position * 4
    return (((int(flat[base + 0]) & 3) << 6)
              | ((int(flat[base + 1]) & 3) << 4)
              | ((int(flat[base + 2]) & 3) << 2)
              |  (int(flat[base + 3]) & 3))


def cell_match_for_position(prompt: str, target_byte: int,
                              position: int, rule_table: np.ndarray, *,
                              n_ticks: int = 128) -> float:
    """Fraction of the 4 cells at `position` that match the target
    byte's 4 base-4 digits after running rule for n_ticks ticks."""
    state = embed_prompt(prompt)
    for _ in range(n_ticks):
        state = hex_ca_step(state, rule_table)
    flat = state.ravel()
    base = RESPONSE_CELLS_START + position * 4
    target_cells = [(target_byte >> (6 - 2 * i)) & 3 for i in range(4)]
    actual = [int(flat[base + i]) & 3 for i in range(4)]
    return sum(1 for a, t in zip(actual, target_cells) if a == t) / 4.0


def train_position_board128(prompt: str, target_byte: int,
                              position: int, *,
                              n_ticks: int = 128,
                              max_seconds: float = 60.0,
                              pop_size: int = 8,
                              generations_per_burst: int = 8,
                              polish_trials: int = 80,
                              mutation_rate: float = 0.005,
                              seed: int = 0xB128A1E,
                              seed_rule: bytes = None,
                              on_event=None) -> dict:
    """Train one rule for a single (prompt, byte-at-position) target.
    This is the per-position primitive — call N times to train a full
    pair, one rule per byte of the expected response.

    Each call is independent and short (~20-60s in practice).  Returns
    {'rule_table': np.ndarray, 'byte_match': bool, 'wall': float}."""
    import random
    import time
    from .ga import polish_genome

    fire = on_event or (lambda *_a, **_kw: None)
    t0 = time.time()
    rng = random.Random(seed)

    def _byte_match(rule):
        b = decode_byte_at_position(
            _run(rule, prompt, n_ticks), position)
        return b == target_byte

    def _run(rule, prm, ticks):
        st = embed_prompt(prm)
        for _ in range(ticks):
            st = hex_ca_step(st, rule)
        return st

    def _fitness(rule):
        cf = cell_match_for_position(prompt, target_byte, position,
                                           rule, n_ticks=n_ticks)
        bonus = 1.0 if _byte_match(rule) else 0.0
        return cf + bonus

    # Initial population.
    # If `seed_rule` is provided, half the population starts as
    # mutations of it (warm-start prior); the other half stays random
    # so the search keeps diversity if the seed rule is a poor fit.
    pop = []
    seed_arr = None
    if seed_rule is not None:
        if len(seed_rule) != 16_384:
            raise ValueError(
                f'seed_rule must be 16,384 bytes; got {len(seed_rule)}')
        seed_arr = np.frombuffer(seed_rule, dtype=np.uint8).copy() & 3
    for i in range(pop_size):
        if seed_arr is not None and i < (pop_size + 1) // 2:
            # Tiny perturbation of the seed rule so the initial pop has
            # a few variations to climb from.
            r = seed_arr.copy()
            if i > 0:
                jit_rng = random.Random(seed ^ (i * 31337))
                n_flips = max(1, int(0.001 * 16_384))    # ~16 entries
                for _ in range(n_flips):
                    idx = jit_rng.randrange(16_384)
                    cur = int(r[idx])
                    new = jit_rng.randint(0, 3)
                    while new == cur:
                        new = jit_rng.randint(0, 3)
                    r[idx] = new
        else:
            r = random_rule_table(seed ^ (i * 7919))
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
            # Pick parent from top half, mutate, replace worst if better.
            parent = pop[rng.randrange(max(1, len(pop) // 2))][0]
            child = parent.copy()
            n_flips = max(1, int(mutation_rate * 16384))
            for _ in range(n_flips):
                idx = rng.randrange(16384)
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

        # Polish — single-byte target = coordinate descent often
        # flips the right entry in tens of trials.
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


def forward_pair_board128_positional(prompt: str, rules,
                                          n_bytes: int, *,
                                          n_ticks: int = 128) -> bytes:
    """Inference: run each per-position rule on the embedded prompt
    for n_ticks ticks, decode that position's byte, concatenate.
    Returns up to n_bytes of output (one per provided rule)."""
    out = bytearray()
    base_board = embed_prompt(prompt)
    for pos in range(min(n_bytes, len(rules))):
        state = base_board.copy()
        rule = rules[pos]
        for _ in range(n_ticks):
            state = hex_ca_step(state, rule)
        out.append(decode_byte_at_position(state, pos))
    return bytes(out)


def train_pair_board128_positional(prompt: str, expected: str, *,
                                       n_ticks: int = 128,
                                       per_position_seconds: float = 60.0,
                                       seed: int = 0xB128A1E,
                                       on_event=None) -> dict:
    """Train one rule per byte of the expected response.  Each
    position is an independent train_position_board128 call; total
    cost = N × per_position_seconds (sequential) or N × per_position_
    seconds / n_workers (if parallelized externally).

    Returns {'rules': [np.ndarray, …], 'matches': [bool, …],
             'exact': bool, 'wall': float}."""
    import time
    fire = on_event or (lambda *_a, **_kw: None)
    target_bytes = expected.encode('utf-8')[:RESPONSE_BYTES_MAX]
    t0 = time.time()
    rules = []
    matches = []
    for pos, tb in enumerate(target_bytes):
        fire('position_start', {'pos': pos, 'target_byte': tb,
                                    'target_char': chr(tb) if 32 <= tb < 127
                                       else f'\\x{tb:02x}',
                                    'elapsed_s': time.time() - t0})
        result = train_position_board128(
            prompt, tb, pos,
            n_ticks=n_ticks,
            max_seconds=per_position_seconds,
            seed=seed ^ (pos * 4099),
            on_event=lambda k, p: fire(f'pos{pos}_{k}', p))
        rules.append(result['rule_table'])
        matches.append(bool(result['byte_match']))
        fire('position_done', {'pos': pos,
                                  'matched': result['byte_match'],
                                  'phase': result['phase'],
                                  'pos_wall': result['wall'],
                                  'elapsed_s': time.time() - t0})
    return {'rules': rules, 'matches': matches,
            'exact': all(matches),
            'wall': time.time() - t0}


def initial_fire_mask(prompt: str, target_response: str,
                        rule_table: np.ndarray, *,
                        n_ticks: int = 128) -> np.ndarray:
    """Compute the union of LUT entries queried over n_ticks steps
    starting from the embedded prompt.  Used by GA mutation to avoid
    flipping entries that never affect the rule's behaviour on this
    input.  At 128×128 the queried set is much larger than at 8×8
    (more cells = more diverse 7-cell configurations) but still
    typically <10% of the 16,384 entries."""
    state = embed_prompt(prompt)
    mask = np.zeros(16384, dtype=bool)
    for _ in range(n_ticks):
        _, keys = hex_ca_step(state, rule_table, return_keys=True)
        mask[keys.ravel().astype(np.int64)] = True
        state = hex_ca_step(state, rule_table)
    return mask


# ── GA training ────────────────────────────────────────────────────

def train_pair_board128(prompt: str, expected: str, *,
                          n_ticks: int = 128,    # 128 unifies side/LUT/ticks
                          max_seconds: float = 600.0,
                          pop_size: int = 8,     # smaller pop since per-eval is now ~150ms
                          generations_per_burst: int = 8,
                          polish_trials: int = 60,
                          mutation_rate: float = 0.01,
                          seed: int = 0xB128A1E,
                          on_event=None) -> dict:
    """Evolve a single 16,384-byte rule that maps prompt → expected
    response on a 128×128 K=4 board.  Returns a dict with the best
    rule, the final byte-match count, and timing info.

    Strategy:
      1. Random init: pop_size rules from `seed`-derived seeds.
      2. Compute fire mask from the best initial rule's run.
      3. Run GA bursts of `generations_per_burst` generations,
         mutating only fire-mask entries.
      4. Polish the best with stochastic coordinate descent on the
         same fire mask.
      5. Re-compute fire mask between bursts (the mask shifts as
         the rule evolves and gates different regions of the LUT).
      6. Stop when byte-match == len(expected) OR budget elapses.
    """
    import random
    import time
    from .ga import polish_genome

    fire = on_event or (lambda *_a, **_kw: None)
    t0 = time.time()
    rng = random.Random(seed)

    target_bytes = expected.encode('utf-8')[:RESPONSE_BYTES_MAX]
    n_target = len(target_bytes)

    def _fitness(rule):
        """Cell-level match fraction + byte-exact bonus.  The cell
        signal is smoother; the byte bonus pushes the GA the last
        mile when most cells already match."""
        cf = cell_match_fraction(prompt, expected, rule,
                                       n_ticks=n_ticks)
        bf = byte_match_count(prompt, expected, rule,
                                  n_ticks=n_ticks)
        # Bonus: large step per matched byte once we're near
        # the cell-match ceiling.
        return cf + 0.5 * bf

    # Phase 1: initial population.
    pop = []
    for i in range(pop_size):
        r = random_rule_table(seed ^ (i * 7919))
        pop.append((r, _fitness(r)))
    pop.sort(key=lambda rf: -rf[1])
    best_rule, best_fit = pop[0]
    best_bytes = byte_match_count(prompt, expected, best_rule,
                                       n_ticks=n_ticks)
    fire('init_done', {
        'best_fit':   best_fit,
        'best_bytes': best_bytes,
        'n_target':   n_target,
        'elapsed_s':  time.time() - t0,
    })

    burst = 0
    while time.time() - t0 < max_seconds and best_bytes < n_target:
        burst += 1
        # Recompute fire mask from current best.
        mask = initial_fire_mask(prompt, expected, best_rule,
                                       n_ticks=n_ticks)
        mask_size = int(mask.sum())
        masked_idx = np.flatnonzero(mask)
        fire('burst_begin', {
            'burst':        burst,
            'mask_size':    mask_size,
            'mask_frac':    mask_size / 16384.0,
            'best_fit':     best_fit,
            'best_bytes':   best_bytes,
            'elapsed_s':    time.time() - t0,
        })

        # GA burst: mutate population using fire-mask, replace worst.
        for _gen in range(generations_per_burst):
            if time.time() - t0 >= max_seconds:
                break
            # Pick parent from top half.
            parent_idx = rng.randrange(max(1, len(pop) // 2))
            parent_rule = pop[parent_idx][0]
            # Mutate via fire-mask.
            child = parent_rule.copy()
            n_flips = max(1, int(mutation_rate * mask_size))
            flip_choices = rng.sample(range(mask_size),
                                          min(n_flips, mask_size))
            for k in flip_choices:
                idx = int(masked_idx[k])
                cur = int(child[idx])
                # New colour different from current.
                new = rng.randint(0, 3)
                while new == cur:
                    new = rng.randint(0, 3)
                child[idx] = new
            child_fit = _fitness(child)
            # Replace worst if child is better.
            worst_idx = max(range(len(pop)),
                                 key=lambda i: -pop[i][1])
            worst_idx = min(range(len(pop)), key=lambda i: pop[i][1])
            if child_fit > pop[worst_idx][1]:
                pop[worst_idx] = (child, child_fit)
                if child_fit > best_fit:
                    best_rule, best_fit = child, child_fit
                    best_bytes = byte_match_count(prompt, expected,
                                                       best_rule,
                                                       n_ticks=n_ticks)
                    fire('improved', {
                        'burst':      burst,
                        'best_fit':   best_fit,
                        'best_bytes': best_bytes,
                        'n_target':   n_target,
                        'elapsed_s':  time.time() - t0,
                    })

        # Polish phase: coordinate descent on the same fire mask.
        if time.time() - t0 < max_seconds:
            def _polish_fitness(g):    # polish_genome expects genome dict
                return _fitness(g['output'])
            polished, polished_fit, n_imp = polish_genome(
                {'output': best_rule.copy()}, _polish_fitness,
                trials=polish_trials,
                seed=seed ^ 0xC0FFEE ^ (burst * 31),
                fire_mask=mask)
            if polished_fit > best_fit:
                best_rule = polished['output']
                best_fit = polished_fit
                best_bytes = byte_match_count(prompt, expected,
                                                   best_rule,
                                                   n_ticks=n_ticks)
                fire('polish_improved', {
                    'burst':         burst,
                    'best_fit':      best_fit,
                    'best_bytes':    best_bytes,
                    'n_target':      n_target,
                    'n_improvements': n_imp,
                    'elapsed_s':     time.time() - t0,
                })

    final_bytes = forward_board(prompt, best_rule,
                                  n_ticks=n_ticks,
                                  response_bytes=n_target)
    exact = (final_bytes == target_bytes)
    fire('done', {
        'best_fit':   best_fit,
        'best_bytes': best_bytes,
        'n_target':   n_target,
        'exact':      exact,
        'sampled':    final_bytes.decode('utf-8', errors='replace'),
        'target':     expected,
        'elapsed_s':  time.time() - t0,
    })
    return {
        'rule_table':  best_rule,
        'best_bytes':  best_bytes,
        'n_target':    n_target,
        'exact':       exact,
        'sampled':     final_bytes,
        'wall':        time.time() - t0,
    }
