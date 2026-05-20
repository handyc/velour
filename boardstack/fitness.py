"""Fitness: byte-stream pair match.

Given a (prompt_byte, response_byte) test set, score a stack
genome by how many of those pairs it produces correctly with NO
per-pair training — one fixed gene must handle every pair.

This is intentionally a hard task.  A random gene baselines at
~1/256 per byte (random guessing).  Anything above floor is signal.
"""
from __future__ import annotations

import random
from typing import Dict, List, Tuple

from .engine import run_stack


# Test set v1: 16 (p, q) byte pairs sampled across the ASCII space.
TEST_SET_V1 = [
    (ord('a'), ord('b')), (ord('b'), ord('c')),
    (ord('h'), ord('i')), (ord('i'), ord('j')),
    (ord('1'), ord('2')), (ord('2'), ord('3')),
    (ord('A'), ord('Z')), (ord('Z'), ord('A')),
    (ord(' '), ord('.')), (ord('.'), ord(' ')),
    (ord('?'), ord('!')), (ord('!'), ord('?')),
    (ord('o'), ord('o')), (ord('e'), ord('e')),
    (ord('x'), ord('y')), (ord('y'), ord('x')),
]


TEST_SETS = {
    'v1':   TEST_SET_V1,
    'incr': [(b, (b + 1) & 0xFF) for b in range(0, 256, 8)],  # byte → byte+1
    'echo': [(b, b) for b in range(0, 256, 8)],               # byte → same
}


def evaluate(genome: Dict, test_set_id: str = 'v1',
                 personality: int = 0,
                 pool_cache: dict = None) -> dict:
    """Run the stack on every test pair, return per-pair results
    + aggregate fitness.  `pool_cache` is an optional cross-call
    dict {pool_idx: upcasted_cell8_lut} — the GA threads one
    through so successive genomes don't re-upcast shared LUTs."""
    pairs = TEST_SETS.get(test_set_id)
    if pairs is None:
        raise ValueError(f'unknown test set {test_set_id!r}; '
                            f'pick from {list(TEST_SETS)}')
    if pool_cache is None:
        pool_cache = {}
    n_match = 0
    bits_match = 0
    results = []
    for p, q in pairs:
        out = run_stack(genome, p, personality=personality,
                            pool_lut_cache=pool_cache)
        match = (out == q)
        if match: n_match += 1
        # Partial credit: count matching bits (Hamming-style)
        # so the GA has a smoother gradient than 0/1 per pair.
        xor = out ^ q
        bm = 8 - bin(xor).count('1')
        bits_match += bm
        results.append({'p': p, 'q': q, 'out': out, 'match': match,
                          'bits_match': bm})
    return {
        'test_set_id':  test_set_id,
        'n_pairs':      len(pairs),
        'byte_match':   n_match,
        'byte_match_rate':   n_match / len(pairs),
        'bit_match':    bits_match,
        'bit_match_rate':    bits_match / (8 * len(pairs)),
        'fitness':      bits_match / (8 * len(pairs))
                          + 0.1 * (n_match / len(pairs)),  # bias toward byte-match
        'results':      results,
    }
