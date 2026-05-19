"""4-way intent router for the CA-LLM chat.

Architecture (the minimum that fits the K=4 alphabet):

    prompt → 8×8 K=4 embedding (first 16 bytes, 4 base-4 digits/byte)
    chain runs T ticks on the embedded board
    cell (0, 0) of the final state ∈ {0, 1, 2, 3} = category

One chain, one cell.  16 KB of LUT.  Trains in seconds via the same
per-cell GA used everywhere else; const-LUT seed handles trivial cases.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

import numpy as np


N_STATES = 4
LUT_SIZE = N_STATES ** 7
SIDE     = 8
TICKS    = 6


def embed_prompt(prompt: str, side: int = SIDE) -> np.ndarray:
    """Top-left layout; 4 base-4 digits per byte; first side²/4 = 16
    bytes fit.  Truncates longer prompts."""
    n_cells = side * side
    bytes_per_board = n_cells // 4
    raw = prompt.encode('utf-8')[:bytes_per_board]
    out = np.zeros(n_cells, dtype=np.uint8)
    for i, b in enumerate(raw):
        out[i * 4 + 0] = (b >> 6) & 3
        out[i * 4 + 1] = (b >> 4) & 3
        out[i * 4 + 2] = (b >> 2) & 3
        out[i * 4 + 3] =  b       & 3
    return out.reshape(side, side)


def _run(rule_arr: np.ndarray, state0: np.ndarray, ticks: int) -> np.ndarray:
    from caformer.primitives import hex_ca_step
    state = state0.copy()
    for _ in range(ticks):
        state = hex_ca_step(state, rule_arr)
    return state


class RouterModel:
    """N-chain router with majority-vote decoding.

    Each chain independently emits a cell ∈ {0..3} for the same
    embedded prompt.  Decode = majority vote over chains, with chain-0
    as the tiebreaker.  N=1 collapses to the original single-chain
    router; N≥3 (with odd N) gives genuine error correction when
    chain errors are uncorrelated."""

    def __init__(self, model_dir: Path, ticks: int = TICKS):
        self.model_dir = Path(model_dir)
        self.ticks = ticks
        meta_path = self.model_dir / 'router_meta.json'
        meta = json.loads(meta_path.read_text())
        self.ticks = meta.get('ticks', ticks)

        # v1: single 'router_chain.lut'.  v2: router_chain_0..N.lut.
        self.rules: list[np.ndarray] = []
        # Try multi-chain first, fall back to single.
        i = 0
        while True:
            p = self.model_dir / f'router_chain_{i}.lut'
            if not p.exists():
                break
            self.rules.append(
                np.frombuffer(p.read_bytes(), dtype=np.uint8).copy() & 3)
            i += 1
        if not self.rules:
            p = self.model_dir / 'router_chain.lut'
            if not p.exists():
                raise FileNotFoundError(
                    f'no router chains in {self.model_dir}')
            self.rules.append(
                np.frombuffer(p.read_bytes(), dtype=np.uint8).copy() & 3)
        for r in self.rules:
            if r.size != LUT_SIZE:
                raise ValueError(
                    f'router LUT must be {LUT_SIZE} bytes; '
                    f'got {r.size}')

    def route(self, prompt: str) -> int:
        """Returns category 0..3 via per-chain run + majority vote
        (chain-0 tiebreak)."""
        votes = self.route_votes(prompt)
        return self._majority(votes)

    def route_votes(self, prompt: str) -> list[int]:
        """Returns the per-chain cell-(0,0) outputs without aggregation."""
        stim = embed_prompt(prompt)
        out = []
        for rule in self.rules:
            final = _run(rule, stim, self.ticks)
            out.append(int(final[0, 0]))
        return out

    @staticmethod
    def _majority(votes: list[int]) -> int:
        counts = [0, 0, 0, 0]
        for v in votes:
            if 0 <= v < 4:
                counts[v] += 1
        best = max(counts)
        # Tie: prefer the value chain 0 voted for if it's in the tied set.
        tied = [v for v in range(4) if counts[v] == best]
        if len(tied) == 1:
            return tied[0]
        if votes and votes[0] in tied:
            return votes[0]
        return tied[0]


_CACHE: dict[str, RouterModel] = {}
_LOCK = threading.Lock()


def get_router(model_dir: str | Path | None = None,
                  ticks: int = TICKS) -> RouterModel:
    """Get a router model.  If model_dir is None, prefer v2 (multi-chain)
    when present, fall back to v1."""
    if model_dir is None:
        for candidate in ('.artifacts/router_v2', '.artifacts/router_v1'):
            p = Path(candidate)
            if (p / 'router_meta.json').exists():
                model_dir = candidate
                break
        else:
            raise FileNotFoundError('no router model trained yet')
    key = str(model_dir)
    with _LOCK:
        if key not in _CACHE:
            _CACHE[key] = RouterModel(Path(model_dir), ticks=ticks)
        return _CACHE[key]
