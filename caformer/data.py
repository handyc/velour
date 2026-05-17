"""caformer/data.py — training data straight from a CA.

The bet: a deterministic CA stream can stand in for a tokenised text
corpus.  Two researchers with the same Pact + domain instantly hold
*identical* training data with no dataset shipping, no licensing
surface, no storage cost.

Three reduction levels:

  ca_corpus_min       — flat 1-D byte stream, the irreducible form
  ca_corpus           — same bytes shaped into (n_seq, seq_len) tensor
                         ready for a transformer's batch loader
  ca_corpus_tokenised — bytes mapped through a vocab table for use as
                         token IDs  (vocab_size ≤ 256 to fit one byte)

Usage:

    from caformer.data import ca_corpus, ca_corpus_min
    bytes_  = ca_corpus_min(seed=42, n=8192)
    tensor  = ca_corpus(seed=42, n_seq=64, seq_len=128)
"""

from __future__ import annotations
import hashlib
import numpy as np
from typing import Optional

from .primitives import hex_ca_step, random_rule_table, lcg_bytes


def ca_corpus_min(seed: int, n: int) -> np.ndarray:
    """The simplest possible CA-driven byte stream: a Park-Miller LCG
    seeded from `seed` produces `n` deterministic bytes.  No CA grid,
    no rule table — just an integer sequence.  Use as the
    irreducible baseline for any 'is this stream rich enough to learn
    from' experiment.  Returns shape (n,) uint8."""
    return lcg_bytes(int(seed), int(n))


def ca_corpus(seed: int, *,
              n_seq: int = 64,
              seq_len: int = 128,
              side: int = 16,
              rule_seed: Optional[int] = None,
              ticks_per_yield: int = 1,
              ) -> np.ndarray:
    """A 2-D training corpus produced by stepping a hex CA forward.

    Each row is one training sequence; cells of the CA grid are read
    out in raster order at every `ticks_per_yield` ticks until we
    have `n_seq * seq_len` bytes.  Same `seed` + `rule_seed` →
    byte-identical corpus across machines.

    Returns shape (n_seq, seq_len) uint8, values in 0..3.
    """
    if rule_seed is None:
        rule_seed = seed ^ 0x5A5A5A5A
    rule = random_rule_table(rule_seed)
    state = (lcg_bytes(seed, side * side) & 3).reshape(side, side)

    total_needed = n_seq * seq_len
    out = np.empty(total_needed, dtype=np.uint8)
    written = 0
    while written < total_needed:
        for _ in range(ticks_per_yield):
            state = hex_ca_step(state, rule)
        flat = state.flatten()
        take = min(flat.size, total_needed - written)
        out[written:written + take] = flat[:take]
        written += take
    return out.reshape(n_seq, seq_len)


def ca_corpus_tokenised(seed: int, *,
                          vocab_size: int = 256,
                          n_seq: int = 64,
                          seq_len: int = 128,
                          ) -> np.ndarray:
    """Same shape as `ca_corpus` but values are token IDs in
    [0, vocab_size).  Bytes are reduced into the vocab via
    `byte % vocab_size` so the distribution stays well-mixed.
    The 4-state grid output of the underlying CA is broadened to
    `vocab_size` distinct IDs by shifting per-cell with an LCG byte."""
    grid = ca_corpus(seed, n_seq=n_seq, seq_len=seq_len)
    # Stretch from {0..3} into vocab_size by mixing with a separate
    # LCG stream so we don't lose the CA structure but still cover the
    # vocabulary.
    mix = lcg_bytes(seed ^ 0xC3, n_seq * seq_len).reshape(n_seq, seq_len)
    return ((grid.astype(np.uint16) * 64 + mix) % vocab_size).astype(np.uint16)


def corpus_fingerprint(seed: int, n: int = 8192) -> str:
    """Stable SHA-256 of the first `n` bytes of `ca_corpus_min(seed)`.
    Two parties with the same seed should compute the same fingerprint
    — the cheapest possible "are we training on the same data" check."""
    return hashlib.sha256(ca_corpus_min(seed, n).tobytes()).hexdigest()
