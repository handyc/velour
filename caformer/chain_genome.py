"""Quine-chain → caformer genome assembly.

Picks 10 consecutive levels of a spoeqi metachain and maps them onto
the 10 components a caformer block needs:
``q, k, v, score, mix, merge, mlp, norm, output, embed`` (the order
of ``caformer.ga.FULL_STACK_NAMES``).

The motivation, in one line: instead of 10 independent random rules
spread across 163,840 bytes of search space, take a single 16,384-byte
seed and let its metachain dynamics give you 10 *related* rules — same
genealogy, sibling dynamics.  If the chain attractor contains useful
caformer configurations, training collapses from per-rule GA to
per-seed GA.
"""
from __future__ import annotations

from typing import Iterable, List, Optional

import numpy as np

from .ga import FULL_STACK_NAMES


def walk_metachain(seed_bytes: bytes, depth: int,
                       ticks_per_level: int = 16) -> List[bytes]:
    """Walk ``depth`` levels of the metachain starting at ``seed_bytes``.

    Returns a list of length ``depth`` where ``out[0] == seed_bytes`` and
    ``out[i+1] = CA^16 applied to out[i] as a 128×128 image, using
    out[i] as the rule LUT``.  Pure numpy; safe to call from anywhere.
    """
    from spoeqi.metachain import hex_ca_step
    seed = bytes(seed_bytes)
    if len(seed) != 16384:
        raise ValueError(f'seed must be 16,384 bytes; got {len(seed)}')
    levels: List[bytes] = [seed]
    current = np.frombuffer(seed, dtype=np.uint8).copy() & 3
    for _ in range(depth - 1):
        state = current.reshape(128, 128).copy()
        for _ in range(ticks_per_level):
            state = hex_ca_step(state, current)
        nxt = state.flatten() & 3
        levels.append(bytes(nxt.tobytes()))
        current = nxt
    return levels


def genome_from_chain(seed_bytes: bytes, *,
                         offsets: Optional[Iterable[int]] = None,
                         component_order: Optional[Iterable[str]] = None
                         ) -> dict:
    """Assemble a caformer genome from levels of ``seed_bytes``'s
    metachain.

    Args:
        seed_bytes:  16,384-byte K=4 hex CA rule LUT.
        offsets:     one chain level per component, default ``[0..9]``
                      i.e. the first 10 consecutive levels.
        component_order: the keys to populate, default
                              ``caformer.ga.FULL_STACK_NAMES`` (length 10).

    Returns a dict ``{component_name: np.ndarray(uint8, shape=(16384,))}``
    suitable for passing to ``caformer.transformer.ca_forward_qkv``."""
    comps = list(component_order) if component_order is not None \
              else list(FULL_STACK_NAMES)
    offs = list(offsets) if offsets is not None else list(range(len(comps)))
    if len(offs) != len(comps):
        raise ValueError(
            f'offsets length {len(offs)} != component count {len(comps)}')
    depth = max(offs) + 1
    levels = walk_metachain(seed_bytes, depth=depth)
    genome = {}
    for comp, off in zip(comps, offs):
        arr = np.frombuffer(levels[off], dtype=np.uint8).copy() & 3
        genome[comp] = arr
    return genome


def genome_from_chain_shifted(seed_bytes: bytes,
                                 start: int = 0) -> dict:
    """Convenience: consecutive 10 levels starting at ``start``."""
    return genome_from_chain(
        seed_bytes,
        offsets=range(start, start + len(FULL_STACK_NAMES)))
