"""8-cell-input hex CA primitive (cell8).

The 7→1 rules used elsewhere in caformer take self + 6 hex neighbours
as input.  cell8 adds an EIGHTH input cell — an external "input port"
fed from outside the local neighbourhood.  This unlocks:

  - Chain composition:  rule B's input port = rule A's output cell.
  - Modulation:         a global signal (mood, heartbeat, sensor)
                        gates local behaviour cheaply.
  - Attention primitives: a "query" cell selects which of K source
                        cells flows into the next computation.

LUT size: 4^8 = 65,536 entries (vs 16,384 for 7→1).  Packed:
65,536 × 2 bits / 8 = 16,384 bytes (same as 7→1 *unpacked*, which
is a nice coincidence).  Unpacked: 65,536 bytes.

Natural Ouroboros board: 256×256 = 65,536 cells = exactly one LUT
treated as a board.  The same self-mapping relationship that gave
the 7→1 system its 128×128 quines now plays out one scale larger.
"""
from __future__ import annotations

import numpy as np


LUT_SIZE_8 = 65_536    # 4^8
BOARD_SIDE_8 = 256     # natural Ouroboros board side for 8→1
PACKED_BYTES_8 = 16_384


def random_rule_table_8(seed: int) -> np.ndarray:
    """An 8-cell-neighbourhood K=4 hex-CA rule table seeded from
    `seed`.  Each entry holds the next-state colour (0..3) for one
    8-cell configuration (self + 6 hex neighbours + 1 input port)."""
    # Reuse the LCG byte generator from the 7→1 path so a given seed
    # produces a deterministic table across the codebase.
    from .primitives import lcg_bytes
    return lcg_bytes(seed, LUT_SIZE_8) & np.uint8(3)


# ── Hex stepping with external input port ───────────────────────────
#
# Same hex topology as hex_ca_step.  The external input is an
# (H, W) array of K=4 cells representing what value to feed into
# the input port AT EACH CELL.  Common patterns:
#
#   - Broadcast scalar: input_grid = np.full((H, W), v) where v is
#     a single K=4 colour.  Every cell sees the same input bit.
#   - Cell-to-cell wiring: input_grid = source_grid (the output
#     of a previous CA step).  Each cell reads the corresponding
#     cell of another CA's state.
#   - Sparse signal: input_grid = zeros except one cell set to
#     a value, e.g. for attention focus.

def hex_ca_step_cell8(state: np.ndarray, input_grid: np.ndarray,
                        rule_table: np.ndarray, *,
                        return_keys: bool = False):
    """One generation of an 8→1 hex CA.  `state` and `input_grid`
    are both (H, W) uint8 arrays of K=4 colours; `rule_table` has
    LUT_SIZE_8 = 65,536 entries.  Returns the new state with
    toroidal boundaries.  When `return_keys=True`, also returns
    the per-cell 16-bit key array so callers can derive a fire mask."""
    if state.dtype != np.uint8:
        state = state.astype(np.uint8)
    if input_grid.dtype != np.uint8:
        input_grid = input_grid.astype(np.uint8)
    if state.shape != input_grid.shape:
        raise ValueError(
            f'state {state.shape} and input_grid {input_grid.shape} '
            f'must have the same shape')
    H, W = state.shape

    # Same hex neighbourhood as the 7→1 version.
    n_up   = np.roll(state, 1, axis=0)
    n_dn   = np.roll(state, -1, axis=0)
    n_l    = np.roll(state, 1, axis=1)
    n_r    = np.roll(state, -1, axis=1)
    n_up_l = np.roll(n_up, 1, axis=1)
    n_up_r = np.roll(n_up, -1, axis=1)
    n_dn_l = np.roll(n_dn, 1, axis=1)
    n_dn_r = np.roll(n_dn, -1, axis=1)

    rows = np.arange(H)[:, None]
    even = (rows & 1) == 0
    n_nw = np.where(even, n_up_l, n_up)
    n_ne = np.where(even, n_up,   n_up_r)
    n_sw = np.where(even, n_dn_l, n_dn)
    n_se = np.where(even, n_dn,   n_dn_r)

    # 8-cell key: same 7 cells as before, plus the external input
    # cell in the top 2 bits.  Bit layout (high → low, 2 bits each):
    #   input_port | self | nw | ne | r | se | sw | l
    key = ((input_grid.astype(np.uint32) << 14)
            | (state.astype(np.uint32) << 12)
            | (n_nw.astype(np.uint32) << 10)
            | (n_ne.astype(np.uint32) << 8)
            | (n_r.astype(np.uint32) << 6)
            | (n_se.astype(np.uint32) << 4)
            | (n_sw.astype(np.uint32) << 2)
            | n_l.astype(np.uint32))
    out = rule_table[key]
    if return_keys:
        return out.astype(np.uint8), key
    return out.astype(np.uint8)


def compute_fire_mask_cell8(rule_table: np.ndarray,
                              sample_state: np.ndarray,
                              sample_input: np.ndarray, *,
                              n_ticks: int = 1) -> np.ndarray:
    """Fire mask for an 8→1 rule on a given (state, input_grid).
    Same idea as the 7→1 compute_fire_mask: returns a length-65,536
    bool array marking which LUT entries actually fire."""
    mask = np.zeros(LUT_SIZE_8, dtype=bool)
    s = sample_state.astype(np.uint8)
    g = sample_input.astype(np.uint8)
    for _ in range(max(1, int(n_ticks))):
        _, keys = hex_ca_step_cell8(s, g, rule_table, return_keys=True)
        mask[keys.ravel().astype(np.int64)] = True
        s = hex_ca_step_cell8(s, g, rule_table)
    return mask


# ── Convenience: broadcast vs wired input grids ─────────────────────

def broadcast_input(side: int, value: int) -> np.ndarray:
    """Build an input_grid of shape (side, side) filled with one K=4
    colour.  Common case: 'turn the input port off' = broadcast(0)."""
    return np.full((side, side), int(value) & 3, dtype=np.uint8)


def wire_input(source_grid: np.ndarray) -> np.ndarray:
    """Build an input_grid wired cell-for-cell from another CA's
    state.  Just returns the source (alias for clarity)."""
    return source_grid.astype(np.uint8) & 3


# ── Demo / smoke entry points used by the cell8 subpage ──────────────

def smoke_two_chain_composition(*, n_ticks: int = 16,
                                  rng_seed: int = 42
                                  ) -> dict:
    """Tiny smoke test: rule A runs as a 7→1 CA, rule B runs as a
    8→1 CA with input port wired to A's state.  Verifies that the
    output of (A + B-wired-to-A) is genuinely different from
    (A + B-wired-to-zero), proving the input port carries signal.

    Cheap (~10 ms) so the subpage can invoke it on each pageload."""
    from .primitives import hex_ca_step, random_rule_table

    side = 8
    state_a = np.zeros((side, side), dtype=np.uint8)
    state_a[3, 3] = 1   # single live cell at the centre
    rule_a = random_rule_table(rng_seed)
    rule_b = random_rule_table_8(rng_seed ^ 0xCAFE)

    # Path 1: rule A alone for n_ticks.
    s = state_a.copy()
    for _ in range(n_ticks):
        s = hex_ca_step(s, rule_a)
    final_a = s.copy()

    # Path 2: rule B with input port broadcast 0 (baseline).
    s = state_a.copy()
    inp_zero = broadcast_input(side, 0)
    for _ in range(n_ticks):
        s = hex_ca_step_cell8(s, inp_zero, rule_b)
    final_b_zero = s.copy()

    # Path 3: rule B with input port wired to rule A's state.
    s = state_a.copy()
    s_a = state_a.copy()
    for _ in range(n_ticks):
        s = hex_ca_step_cell8(s, wire_input(s_a), rule_b)
        s_a = hex_ca_step(s_a, rule_a)
    final_b_wired = s.copy()

    # How different are the two B paths?  If the input port is
    # carrying real signal, the wired path should differ substantially
    # from the broadcast-0 path on most cells.
    diff_zero_vs_wired = int((final_b_zero != final_b_wired).sum())
    diff_frac = diff_zero_vs_wired / (side * side)

    return {
        'side':              side,
        'n_ticks':           n_ticks,
        'final_a':           final_a.tolist(),
        'final_b_zero':      final_b_zero.tolist(),
        'final_b_wired':     final_b_wired.tolist(),
        'cells_differing':   diff_zero_vs_wired,
        'cells_total':       side * side,
        'diff_fraction':     diff_frac,
        'input_port_works':  diff_frac > 0.10,
    }
