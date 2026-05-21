"""boardstack4 — a sequential cascade of 4 K=4 CA boards used as
a deterministic prefilter for the caformer harness.

Architecture:

    state_0 = embed_prompt(prompt)               # 8×8 K=4 stim
    state_1 = run(LUT_0, state_0, T)             # board 0
    state_2 = run(LUT_1, state_1, T)             # board 1
    state_3 = run(LUT_2, state_2, T)             # board 2
    state_4 = run(LUT_3, state_3, T)             # board 3
    path    = (state_1[0,0], state_2[0,0],
               state_3[0,0], state_4[0,0])       # 4-symbol path

The path is a 4-tuple over the K=4 alphabet — 256 distinct values.
For Phase-1 compatibility with the existing harness, the path can
be projected to a single category by mode (with board-0 tiebreak).
For Phase 2, the harness will use the path as an ordered chain of
sub-agent calls (personality / information / command / meta).

Why 4 boards × K=4 colours: the input byte can traverse any
ordered combination of 4 colours, including the same colour
repeated.  256 distinct paths means much more signal than a
single-category router can express.

Reuses caformer.router.embed_prompt + _run so the stim/embedding
remains identical to the existing single-LUT router (lets
boardstack4 and router share training corpora and live side by side).
"""
from __future__ import annotations

import json
import threading
from collections import Counter
from pathlib import Path
from typing import Sequence

import numpy as np

from caformer.router import LUT_SIZE, SIDE, TICKS, embed_prompt, _run


N_BOARDS = 4               # the K=4 ↔ 4-board structural match


class BoardStack4:
    """4 sequential K=4 LUTs forming a cascade prefilter."""

    def __init__(self, model_dir: Path, ticks: int = TICKS):
        self.model_dir = Path(model_dir)
        meta_path = self.model_dir / 'boardstack4_meta.json'
        meta = json.loads(meta_path.read_text())
        self.ticks = int(meta.get('ticks', ticks))
        # side defaults to the module's SIDE (8) for back-compat with
        # artifacts written before multiscale; new artifacts persist
        # their own side in meta so different-resolution stacks can
        # be loaded in parallel.
        self.side = int(meta.get('side', SIDE))
        self.rules: list[np.ndarray] = []
        for i in range(N_BOARDS):
            p = self.model_dir / f'board_{i}.lut'
            if not p.exists():
                raise FileNotFoundError(
                    f'boardstack4 missing board {i}: {p}')
            arr = np.frombuffer(p.read_bytes(), dtype=np.uint8).copy() & 3
            if arr.size != LUT_SIZE:
                raise ValueError(
                    f'boardstack4 board {i} LUT must be {LUT_SIZE} bytes; '
                    f'got {arr.size}')
            self.rules.append(arr)

    def cascade(self, prompt: str) -> tuple[int, int, int, int]:
        """Run the cascade and return the 4-colour path."""
        state = embed_prompt(prompt, side=self.side)
        path: list[int] = []
        for rule in self.rules:
            state = _run(rule, state, self.ticks)
            path.append(int(state[0, 0]))
        return (path[0], path[1], path[2], path[3])

    def cascade_states(self, prompt: str) -> list[np.ndarray]:
        """Run the cascade and return all intermediate boards' final
        states (length N_BOARDS).  Useful for visualisation."""
        state = embed_prompt(prompt, side=self.side)
        out = []
        for rule in self.rules:
            state = _run(rule, state, self.ticks)
            out.append(state.copy())
        return out


def path_to_category(path: Sequence[int]) -> int:
    """Project the 4-colour path to a single K=4 category.

    Mode (most common colour) with board-0 tiebreak.  Phase-1 only —
    once the harness uses the path directly, this projection is just
    a debugging convenience."""
    counts = Counter(int(c) & 3 for c in path)
    if not counts:
        return 0
    best_count = max(counts.values())
    tied = sorted(c for c, n in counts.items() if n == best_count)
    if len(tied) == 1:
        return tied[0]
    # Board-0 tiebreak: if board 0's colour is in the tied set,
    # prefer it (matches the router's tiebreak shape).
    if path and int(path[0]) in tied:
        return int(path[0])
    return tied[0]


def path_label(path: Sequence[int]) -> str:
    """Render a 4-colour path as a compact string, e.g. '2-1-1-0'.
    Used in logs + UI badges."""
    return '-'.join(str(int(c) & 3) for c in path)


_CACHE: dict[str, BoardStack4] = {}
_LOCK = threading.Lock()


def get_stack(model_dir: str | Path | None = None,
                 ticks: int = TICKS) -> BoardStack4:
    """Load a BoardStack4 from disk, cached.  If model_dir is None,
    looks under .artifacts/boardstack4_v1/."""
    if model_dir is None:
        model_dir = '.artifacts/boardstack4_v1'
    key = str(model_dir)
    with _LOCK:
        if key not in _CACHE:
            _CACHE[key] = BoardStack4(Path(model_dir), ticks=ticks)
        return _CACHE[key]
