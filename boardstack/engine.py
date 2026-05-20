"""Stack runner — given a genome, an input prompt byte, and a
personality, produce a response byte.

Each board:
  - has side×side cells (K=4)
  - holds an UPCASTED cell8 LUT (from a 7→1 mandelhunt LUT, tile-4)
  - reads its input port from a gene-encoded source (previous
    board's cell, prompt-byte register, or personality constant)
  - runs `ticks[k]` cell8 steps per stack-step
  - exposes its current state for downstream boards to read

The whole stack runs `stack_ticks` rounds; at the end, the final
output byte is decoded from the gene-encoded (r, c) cell on
board N-1 (read 4 cells horizontally to pack into one byte).
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np

from caformer.cell8 import broadcast_input, hex_ca_step_cell8
from caformer.board256 import upcast_7to1_to_cell8

from .population import load_pool_lut


def _build_board_state(side: int, prompt_byte: int) -> np.ndarray:
    """Seed a board with prompt-byte embedded in its top-left
    4 cells (4 cells per byte, MSB-first)."""
    state = np.zeros((side, side), dtype=np.uint8)
    flat = state.ravel()
    flat[0] = (prompt_byte >> 6) & 3
    flat[1] = (prompt_byte >> 4) & 3
    flat[2] = (prompt_byte >> 2) & 3
    flat[3] =  prompt_byte       & 3
    return state


def _port_value_for(board_idx: int, wiring_entry: tuple,
                        prompt_byte: int, personality: int,
                        boards: List[np.ndarray], side: int) -> int:
    """Resolve a wiring entry to a single K=4 colour value to
    broadcast onto board K's input port."""
    src, r, c = wiring_entry
    if src == -1:
        # Prompt-byte register — use the low 2 bits of the prompt
        # byte as the port value.
        return prompt_byte & 3
    if src in (-2, -3, -4, -5):
        # Personality constant.
        return (-src - 2) & 3
    if 0 <= src < board_idx:
        b = boards[src]
        return int(b[r % side, c % side]) & 3
    # Fallback (shouldn't happen with a valid gene).
    return personality & 3


def run_stack(genome: Dict, prompt_byte: int, personality: int = 0,
                  pool_lut_cache: dict = None) -> int:
    """Run the stack on one (prompt_byte, personality) input and
    return the decoded output byte from board N-1.

    `pool_lut_cache` is an optional dict {idx: upcasted_cell8_lut}
    the caller can pre-warm to avoid the upcast in the inner loop.
    """
    n      = genome['n_boards']
    side   = genome['board_side']
    sticks = genome['stack_ticks']
    rule_idx_list = genome['rule_idx']
    ticks_list    = genome['ticks']
    wiring_list   = genome['wiring']
    out_r, out_c  = genome['output_cell']

    if pool_lut_cache is None:
        pool_lut_cache = {}

    # Initialize boards: each starts seeded with the prompt byte.
    # (Could be all-zeros if we want the prompt to enter ONLY via
    # board 0's port; we choose seeded for now so signal carries.)
    boards = [_build_board_state(side, prompt_byte) for _ in range(n)]

    for stack_step in range(sticks):
        # Compute next state for every board.  Read inputs from
        # the CURRENT boards (so the wiring sees the state at the
        # start of this stack-step — like a synchronous register
        # update in hardware).
        next_boards = []
        for k in range(n):
            # Load + upcast the LUT for this board (cache).
            idx = rule_idx_list[k]
            if idx not in pool_lut_cache:
                lut7 = load_pool_lut(idx)
                pool_lut_cache[idx] = upcast_7to1_to_cell8(lut7)
            lut8 = pool_lut_cache[idx]
            # Resolve port value from wiring.
            port_val = _port_value_for(k, tuple(wiring_list[k]),
                                                prompt_byte, personality,
                                                boards, side)
            inp = broadcast_input(side, port_val)
            # Run this board's internal ticks.
            st = boards[k]
            for _ in range(ticks_list[k]):
                st = hex_ca_step_cell8(st, inp, lut8)
            next_boards.append(st)
        boards = next_boards

    # Decode the output byte from board N-1.
    final = boards[-1]
    r, c = out_r % side, out_c % side
    # Read 4 consecutive cells starting at (r, c) wrapping horizontally.
    c0 = c
    c1 = (c + 1) % side
    c2 = (c + 2) % side
    c3 = (c + 3) % side
    byte = ((int(final[r, c0]) & 3) << 6) \
         | ((int(final[r, c1]) & 3) << 4) \
         | ((int(final[r, c2]) & 3) << 2) \
         |  (int(final[r, c3]) & 3)
    return byte
