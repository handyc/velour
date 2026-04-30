"""Rule-as-filter scan — sweep one rule across a SequenceRecord.

The "motif detector" use case: an evolved Class-IV rule is a 4 KB
ab-initio scanner. We slide a fixed-size window across the record,
map each window to the 16×16 board, evolve under the rule, score the
trajectory, and emit a per-window richness array.

The result is small enough to lay alongside Helix's existing
annotation tracks: ~10 k windows for a 1 Mb chromosome at stride 128,
each row a 3-tuple of ``[start, end, score]``.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

import numpy as np

from helix.models import RuleFilterScan, SequenceRecord

from . import engine
from .mapping import dna_to_board


@dataclass
class ScanResult:
    track: List[List[float]]              # [[start, end, score], ...]
    n_windows: int
    score_min: float
    score_max: float
    score_mean: float
    elapsed_s: float


def scan_record(record: SequenceRecord,
                rule_table: np.ndarray,
                window_size: int = 256,
                stride: int = 128,
                start: int = 0,
                end: Optional[int] = None,
                steps: int = engine.TOTAL_STEPS,
                scoring_fn: str = 'edge',
                on_progress: Optional[Callable[[int, int], None]] = None,
                progress_every: int = 200,
                ) -> ScanResult:
    """Slide the rule across ``record.sequence[start:end]`` and score every
    window. Returns the track plus summary stats. Pure function — caller
    persists the result."""
    seq = record.sequence
    if end is None:
        end = len(seq)
    end = min(end, len(seq))
    span = end - start - window_size
    if span < 0:
        return ScanResult(track=[], n_windows=0, score_min=0.0, score_max=0.0,
                          score_mean=0.0, elapsed_s=0.0)
    n_windows = span // stride + 1

    track: List[List[float]] = []
    t0 = time.time()
    for i in range(n_windows):
        a = start + i * stride
        b = a + window_size
        board = dna_to_board(seq[a:b], seed=a)
        spacetime = engine.evolve(board, rule_table, steps=steps)
        s = engine.score(spacetime, scoring_fn)
        track.append([a, b, round(s, 5)])
        if on_progress and (i % progress_every == 0):
            on_progress(i, n_windows)

    scores = np.fromiter((row[2] for row in track), dtype=np.float64,
                         count=len(track))
    return ScanResult(
        track=track,
        n_windows=len(track),
        score_min=float(scores.min()) if len(scores) else 0.0,
        score_max=float(scores.max()) if len(scores) else 0.0,
        score_mean=float(scores.mean()) if len(scores) else 0.0,
        elapsed_s=time.time() - t0,
    )


def estimate_runtime_seconds(record_length_bp: int,
                             window_size: int,
                             stride: int,
                             ms_per_window: float = 2.7) -> float:
    """Back-of-envelope: number of windows × per-window cost."""
    n = max(0, (record_length_bp - window_size) // stride + 1)
    return (n * ms_per_window) / 1000.0
