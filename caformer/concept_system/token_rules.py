"""Phase-1 experiment: token-as-CA-ruleset.

User daydream 2026-05-21: instead of tokens being string identifiers
into a vocabulary, each token IS a K=4 CA rule.  Combining tokens
becomes a rule cascade.

This module ships the minimal substrate to test the idea:

- ``generate_rule(seed)`` — produce one K=4 7-neighbour LUT
  (16,384 entries) from a deterministic seed.
- ``fire(rule, init_state, n_ticks)`` — run the rule on a
  starting grid, return the final grid.
- ``fingerprint(state)`` — summarise the final grid as a stable
  4-int tuple (the count of each K=4 colour) + the 4 corner cells.
- ``cascade(rules_in_order, init_state, n_ticks_per)`` — fire
  multiple rules in sequence; each subsequent rule sees the
  previous one's final state.

No persistence yet — Phase 1 only generates rules from seeds
deterministically.  The management command
``caformer_token_rules_experiment`` exercises the full
distinctness / composition / decodability checks against the
first N Sanskrit verb roots.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from caformer.router import LUT_SIZE, SIDE
from caformer.primitives import hex_ca_step


# Canonical asymmetric initial state — breaks the symmetry that
# would otherwise let two distinct rules produce identical outputs
# from a uniform start.  Same shape used in byte_router._BASE_STATE
# so the experiment is comparable.
_BASE_STATE = (np.arange(SIDE * SIDE, dtype=np.uint8)
                   .reshape(SIDE, SIDE) & 3)


def generate_rule(seed: int) -> np.ndarray:
    """Produce a deterministic K=4 LUT for the given seed.
    Returns a numpy uint8 array of length LUT_SIZE (16,384)."""
    rng = random.Random(seed)
    arr = np.empty(LUT_SIZE, dtype=np.uint8)
    for i in range(LUT_SIZE):
        arr[i] = rng.randint(0, 3)
    return arr


def fire(rule: np.ndarray, init_state: np.ndarray | None = None,
              n_ticks: int = 4) -> np.ndarray:
    """Fire a rule for ``n_ticks`` on ``init_state`` (or _BASE_STATE
    if None).  Returns the final grid."""
    state = (init_state if init_state is not None else _BASE_STATE).copy()
    for _ in range(n_ticks):
        state = hex_ca_step(state, rule)
    return state


def cascade(rules: Sequence[np.ndarray],
                 init_state: np.ndarray | None = None,
                 n_ticks_per: int = 4) -> np.ndarray:
    """Apply ``rules`` in sequence — each rule sees the previous
    rule's final state as its initial state.  Non-commutative by
    construction."""
    state = (init_state if init_state is not None else _BASE_STATE).copy()
    for rule in rules:
        state = fire(rule, state, n_ticks=n_ticks_per)
    return state


@dataclass(frozen=True)
class Fingerprint:
    """Two stable summaries of a final state:

      histogram — (count_of_0, _1, _2, _3) over the grid.  Sums to
                   side² (64 for 8×8).  Stable across symmetric
                   rotations; not unique per state.
      corners   — (cell00, cell0R, cellC0, cellCR) where R=side-1
                   and C=side-1.  Position-sensitive.

    The combined tuple (histogram + corners) is the experiment's
    distinctness key."""
    histogram: tuple[int, int, int, int]
    corners:   tuple[int, int, int, int]

    def key(self) -> tuple:
        return self.histogram + self.corners


def fingerprint(state: np.ndarray) -> Fingerprint:
    """Compute the (histogram, corners) signature of a final state."""
    flat = state.flatten()
    hist = (int((flat == 0).sum()),
            int((flat == 1).sum()),
            int((flat == 2).sum()),
            int((flat == 3).sum()))
    h, w = state.shape
    corners = (int(state[0, 0]),
               int(state[0, w - 1]),
               int(state[h - 1, 0]),
               int(state[h - 1, w - 1]))
    return Fingerprint(histogram=hist, corners=corners)
