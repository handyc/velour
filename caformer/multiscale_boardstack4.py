"""multiscale_boardstack4 — multi-resolution wrapper around BoardStack4.

The single-resolution BoardStack4 sees an 8×8 K=4 grid of the
prompt's first 16 bytes.  This module loads multiple BoardStack4
artifacts at different sides (e.g. 4×4 / 8×8 / 16×16 / 32×32) and
combines their cascade paths into one fingerprint.

Different sides see different windows of the input:
  side=4   → 4 bytes  (tight local pattern)
  side=8   → 16 bytes (default — phrase-level)
  side=16  → 64 bytes (sentence-level)
  side=32  → 256 bytes (whole-prompt for most chats)

Each stack produces a 4-symbol K=4 path.  Combination by XOR per
position yields a single 4-symbol fingerprint that integrates all
scales.  Each individual stack's path is also exposed so the
harness UI can show which scales agreed.

Storage cost: each BoardStack4 = 4 × 16 KB = 64 KB.  Four scales =
256 KB total.  Trivial.

Phase 1 here loads existing stack artifacts from .artifacts/.
Train sides one at a time via:

    manage.py caformer_train_boardstack4 --side 4  \\
              --out-dir .artifacts/boardstack4_side4
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Sequence

from caformer.boardstack4 import BoardStack4, N_BOARDS


DEFAULT_SIDES = (4, 8, 16, 32)
DEFAULT_DIR_TEMPLATE = '.artifacts/boardstack4_side{side}'


class MultiScaleBoardStack4:
    """Loads multiple BoardStack4 instances at different sides and
    combines their cascade paths."""

    def __init__(self, stacks: dict[int, BoardStack4]):
        if not stacks:
            raise ValueError('MultiScaleBoardStack4 needs ≥ 1 stack')
        self.stacks = dict(stacks)            # {side: BoardStack4}

    @classmethod
    def load(cls, sides: Sequence[int] = DEFAULT_SIDES,
                  dir_template: str = DEFAULT_DIR_TEMPLATE,
                  fallback_side_8: str | Path | None = None,
                  ) -> 'MultiScaleBoardStack4':
        """Load BoardStack4 artifacts for each requested side from
        ``dir_template.format(side=N)``.  Missing sides are silently
        skipped — soft-fail so partial deployments still work.

        ``fallback_side_8``: if set and the side=8 path is missing,
        try this directory instead (e.g. .artifacts/boardstack4_v3
        from the main training pipeline)."""
        loaded: dict[int, BoardStack4] = {}
        for side in sides:
            path = Path(dir_template.format(side=side))
            if not (path / 'boardstack4_meta.json').exists():
                if side == 8 and fallback_side_8 is not None:
                    path = Path(fallback_side_8)
                    if not (path / 'boardstack4_meta.json').exists():
                        continue
                else:
                    continue
            try:
                stack = BoardStack4(path)
            except (FileNotFoundError, ValueError):
                continue
            # Verify the stack's stored side matches what we expected.
            if stack.side != side:
                # The artifact dir's name implied one side but its
                # meta says another — trust the meta and key by it.
                loaded[stack.side] = stack
            else:
                loaded[side] = stack
        if not loaded:
            raise FileNotFoundError(
                f'no boardstack4 artifacts found at any side under '
                f'{dir_template!r}')
        return cls(loaded)

    def cascade(self, prompt: str) -> dict:
        """Run every loaded stack and return:
          - per_scale: {side: 4-tuple} — each scale's own path
          - combined:  4-tuple — bitwise XOR per position across scales
          - n_scales:  how many stacks contributed
        """
        per_scale: dict[int, tuple[int, ...]] = {}
        for side, stack in self.stacks.items():
            per_scale[side] = stack.cascade(prompt)
        combined = [0, 0, 0, 0]
        for path in per_scale.values():
            for i in range(N_BOARDS):
                combined[i] ^= int(path[i]) & 3
        return {
            'per_scale': per_scale,
            'combined':  tuple(combined),
            'n_scales':  len(per_scale),
            'sides':     sorted(per_scale.keys()),
        }


_CACHE: dict[str, MultiScaleBoardStack4] = {}
_LOCK = threading.Lock()


def get_multiscale(sides: Sequence[int] = DEFAULT_SIDES,
                        dir_template: str = DEFAULT_DIR_TEMPLATE,
                        fallback_side_8: str | Path | None = None,
                        ) -> MultiScaleBoardStack4:
    """Cached loader.  Soft-fails to caller's exception when no
    stacks are available."""
    key = f'{dir_template}|{tuple(sides)}|{fallback_side_8}'
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        m = MultiScaleBoardStack4.load(
            sides=sides, dir_template=dir_template,
            fallback_side_8=fallback_side_8)
        _CACHE[key] = m
        return m
