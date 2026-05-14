"""Sign similarity over fixed-size pose signatures.

Each Sign carries a ``signature`` — ``K_SIGNATURE_KEYFRAMES``
evenly-spaced frame poses flattened to ``[rx, ry, rz] × 30`` and
L2-normalised across the whole vector. Distance between two Signs
is the Euclidean distance between their (unit-length) signatures,
which is equivalent to ``sqrt(2 · (1 − cos θ))`` — small means
similar.

Why this and not full DTW: we have 1198 signs × ~100 frames each.
A pairwise dynamic-time-warp over per-frame vectors would be
~10^10 inner ops to rank one query, too slow for live UI. A
fixed-length signature gets near-DTW quality for handshape /
coarse-motion similarity at O(N) cost per ranking.
"""

from __future__ import annotations
import math
from typing import Iterable, List, Sequence, Tuple


# Bumping this widens the temporal sample. 8 keyframes is enough to
# capture the start / approach / hold / release shape of typical
# lexical signs in the GSL corpus.
K_SIGNATURE_KEYFRAMES = 8

POSE_DIM = 90  # 30 cylinders × 3 axes
SIGNATURE_DIM = K_SIGNATURE_KEYFRAMES * POSE_DIM


def _flatten_pose(pose: Sequence[Sequence[float]]) -> List[float]:
    """30 × [rx, ry, rz] → flat list of 90 floats. Tolerant of
    partial / missing data: pads with zeros, truncates extras."""
    flat: List[float] = []
    for triple in pose[:30]:
        rx = float(triple[0]) if len(triple) > 0 else 0.0
        ry = float(triple[1]) if len(triple) > 1 else 0.0
        rz = float(triple[2]) if len(triple) > 2 else 0.0
        flat.extend([rx, ry, rz])
    while len(flat) < POSE_DIM:
        flat.append(0.0)
    return flat


def _pick_keyframe_indices(n_frames: int,
                           k: int = K_SIGNATURE_KEYFRAMES) -> List[int]:
    """``k`` evenly-spaced frame indices over ``[0, n_frames-1]``."""
    if n_frames <= 0:
        return []
    if n_frames == 1:
        return [0] * k
    return [int(round(i * (n_frames - 1) / (k - 1))) for i in range(k)]


def _l2_normalise(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm < 1e-9:
        return vec[:]  # all-zeros stays all-zeros
    return [v / norm for v in vec]


def compute_signature(frame_rotations: Iterable[Sequence[Sequence[float]]],
                      k: int = K_SIGNATURE_KEYFRAMES) -> List[float]:
    """Build a unit-length signature from an ordered iterable of
    per-frame ``cylinder_rotations`` lists. Skipped silently if
    the iterable yields no frames (returns ``[]``)."""
    frames = list(frame_rotations)
    n = len(frames)
    if n == 0:
        return []
    indices = _pick_keyframe_indices(n, k)
    sig: List[float] = []
    for i in indices:
        sig.extend(_flatten_pose(frames[i]))
    return _l2_normalise(sig)


def distance(sig_a: Sequence[float], sig_b: Sequence[float]) -> float:
    """Euclidean distance between two same-length signatures.

    Returns ``+inf`` if either signature is empty or wrong-length,
    so the similarity ranker filters them to the bottom."""
    if not sig_a or not sig_b or len(sig_a) != len(sig_b):
        return float('inf')
    s = 0.0
    for a, b in zip(sig_a, sig_b):
        d = a - b
        s += d * d
    return math.sqrt(s)


def nearest(query_sig: Sequence[float],
            candidates: Iterable[Tuple[int, Sequence[float]]],
            *, n: int = 10) -> List[Tuple[int, float]]:
    """Rank ``candidates`` by distance to ``query_sig``. Each
    candidate is a ``(sign_id, signature)`` tuple; returns the
    top-N as ``(sign_id, distance)``, distance ascending. Missing
    or wrong-shape signatures land at the bottom (distance inf)."""
    scored = [(sid, distance(query_sig, sig)) for sid, sig in candidates]
    scored.sort(key=lambda t: t[1])
    return scored[:n]
