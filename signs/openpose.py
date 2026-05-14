"""OpenPose → 30-cylinder retargeting.

OpenPose emits 21 hand keypoints per hand per frame (wrist + 5
fingers × 4 joints = 20 finger joints + wrist). The viewer renders
a hierarchical skeleton of 30 cylinders (5 fingers × 3 segments
× 2 hands), each with a local Euler XYZ rotation in radians
relative to its parent.

This module performs the inverse-kinematic retargeting: given the
21+21 joint world positions, compute the 30 local rotations such
that the rendered skeleton points in the same per-segment direction
as the source keypoints.

The output Euler angles follow Three.js's 'XYZ' convention exactly
(the in-Velour viewer feeds them straight into
``new THREE.Euler(rx, ry, rz, 'XYZ')``), so we use the same
matrix-extraction formula Three.js uses internally.

Joint→cylinder mapping
----------------------
OpenPose hand chain (indices into the 21-keypoint array):

  thumb:  [wrist=0, CMC=1, MCP=2, IP=3, tip=4]
  index:  [wrist=0, MCP=5,  PIP=6,  DIP=7,  tip=8]
  middle: [wrist=0, MCP=9,  PIP=10, DIP=11, tip=12]
  ring:   [wrist=0, MCP=13, PIP=14, DIP=15, tip=16]
  pinky:  [wrist=0, MCP=17, PIP=18, DIP=19, tip=20]

Viewer skeleton (3 cylinders per finger, root attached to palm):

  proximal  (segment 0):  chain[1] → chain[2]
  middle    (segment 1):  chain[2] → chain[3]
  distal    (segment 2):  chain[3] → chain[4]

The wrist-to-CMC/MCP edge (chain[0] → chain[1]) is *not* a
cylinder; it represents the palm itself, which the viewer renders
as a static attachment point.
"""

from __future__ import annotations
import json
import math
from typing import List, Sequence, Tuple

import numpy as np


# ─────────────────────── Joint topology ────────────────────────────

FINGER_ORDER = ('thumb', 'index', 'middle', 'ring', 'pinky')

FINGER_CHAIN = {
    'thumb':  (0, 1, 2, 3, 4),
    'index':  (0, 5, 6, 7, 8),
    'middle': (0, 9, 10, 11, 12),
    'ring':   (0, 13, 14, 15, 16),
    'pinky':  (0, 17, 18, 19, 20),
}


def cylinder_segments() -> List[dict]:
    """Return one dict per cylinder, in HAND_STRUCTURE order
    (L_Thumb_1..L_Pinky_3, then R_Thumb_1..R_Pinky_3)."""
    segs: List[dict] = []
    for hand in ('left', 'right'):
        for finger in FINGER_ORDER:
            chain = FINGER_CHAIN[finger]
            for s in range(3):
                segs.append({
                    'hand':    hand,
                    'finger':  finger,
                    'segment': s,
                    'joint_a': chain[s + 1],   # base of this cylinder
                    'joint_b': chain[s + 2],   # tip
                })
    return segs


CYLINDER_SEGMENTS = cylinder_segments()
assert len(CYLINDER_SEGMENTS) == 30


# ─────────────────────── Quaternion math ───────────────────────────
# Convention: (w, x, y, z), unit length. Built to match Three.js's
# internal quaternion math so the round-trip euler→quat→matrix
# behaves the same way the viewer expects.

def quat_from_vectors(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Shortest-arc quaternion rotating unit vector ``a`` to ``b``."""
    a = a / (np.linalg.norm(a) + 1e-30)
    b = b / (np.linalg.norm(b) + 1e-30)
    d = float(np.dot(a, b))
    if d > 1.0 - 1e-9:
        return np.array([1.0, 0.0, 0.0, 0.0])
    if d < -1.0 + 1e-9:
        # 180° flip; pick any perpendicular axis
        axis = np.cross(a, np.array([1.0, 0.0, 0.0]))
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, np.array([0.0, 1.0, 0.0]))
        axis = axis / np.linalg.norm(axis)
        return np.array([0.0, axis[0], axis[1], axis[2]])
    s = math.sqrt((1.0 + d) * 2.0)
    inv_s = 1.0 / s
    axis = np.cross(a, b) * inv_s
    return np.array([s * 0.5, axis[0], axis[1], axis[2]])


def quat_mul(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Hamilton product ``p * q`` (rotation p applied after q)."""
    w1, x1, y1, z1 = p
    w2, x2, y2, z2 = q
    return np.array([
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    ])


def quat_inv(q: np.ndarray) -> np.ndarray:
    """Inverse of a unit quaternion."""
    return np.array([q[0], -q[1], -q[2], -q[3]])


def rotate_vec(v: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Apply quaternion rotation ``q`` to vector ``v``."""
    qw, qx, qy, qz = q
    qvec = np.array([qx, qy, qz])
    t = 2.0 * np.cross(qvec, v)
    return v + qw * t + np.cross(qvec, t)


def quat_to_matrix(q: np.ndarray) -> np.ndarray:
    """3×3 rotation matrix from a unit quaternion."""
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y*y + z*z),     2 * (x*y - z*w),     2 * (x*z + y*w)],
        [    2 * (x*y + z*w), 1 - 2 * (x*x + z*z),     2 * (y*z - x*w)],
        [    2 * (x*z - y*w),     2 * (y*z + x*w), 1 - 2 * (x*x + y*y)],
    ])


def quat_to_euler_xyz(q: np.ndarray) -> Tuple[float, float, float]:
    """Extract Three.js-compatible 'XYZ' Euler angles (radians).

    Matches three.js's ``Euler.setFromRotationMatrix(m, 'XYZ')``
    exactly so the viewer's ``new THREE.Euler(rx, ry, rz, 'XYZ')``
    round-trips this quaternion (up to numeric tolerance).
    """
    m = quat_to_matrix(q)
    # Three.js elements (column-major, but we use row-major here):
    # te[ 0,4,8 ] = m11, m12, m13
    # te[ 1,5,9 ] = m21, m22, m23
    # te[ 2,6,10] = m31, m32, m33
    m11, m12, m13 = m[0, 0], m[0, 1], m[0, 2]
    m21, m22, m23 = m[1, 0], m[1, 1], m[1, 2]
    m31, m32, m33 = m[2, 0], m[2, 1], m[2, 2]

    # 'XYZ' order, per Three.js (src/math/Euler.js):
    #   y = asin(clamp(m13, -1, 1))
    ry = math.asin(max(-1.0, min(1.0, m13)))
    if abs(m13) < 0.9999999:
        rx = math.atan2(-m23, m33)
        rz = math.atan2(-m12, m11)
    else:
        # Gimbal-lock singularity.
        rx = math.atan2(m32, m22)
        rz = 0.0
    return rx, ry, rz


# ─────────────────────── OpenPose parsing ──────────────────────────

def parse_openpose_frame(data: dict, person_index: int = 0
                         ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Parse a single OpenPose JSON dict.

    Returns ``(left_xyz, left_conf, right_xyz, right_conf)`` where
    each ``*_xyz`` is a ``(21, 3)`` float array. OpenPose's 2D
    output has Z = 0 (confidence is returned separately).
    """
    people = data.get('people', [])
    if not people:
        raise ValueError('OpenPose frame has no people')
    person = people[person_index]

    def _unpack(key: str) -> Tuple[np.ndarray, np.ndarray]:
        flat = person.get(key, [])
        if not flat:
            return np.zeros((21, 3)), np.zeros(21)
        a = np.asarray(flat, dtype=np.float64).reshape(-1, 3)
        if a.shape[0] != 21:
            raise ValueError(f'{key}: expected 21 keypoints, got {a.shape[0]}')
        xy   = a[:, :2]
        conf = a[:, 2].copy()
        xyz  = np.concatenate([xy, np.zeros((21, 1))], axis=1)
        return xyz, conf

    # OpenPose writes both `*_2d` and `*_3d` keys whether or not 3D
    # data is present; the 3D variants are empty lists when the
    # capture was monocular. Only switch to the 3D path when the
    # array actually contains data.
    if person.get('hand_left_keypoints_3d'):
        l = np.asarray(person['hand_left_keypoints_3d'], dtype=np.float64).reshape(21, 4)
        r = np.asarray(person['hand_right_keypoints_3d'], dtype=np.float64).reshape(21, 4)
        return l[:, :3], l[:, 3], r[:, :3], r[:, 3]

    left_xyz,  left_conf  = _unpack('hand_left_keypoints_2d')
    right_xyz, right_conf = _unpack('hand_right_keypoints_2d')
    return left_xyz, left_conf, right_xyz, right_conf


def parse_openpose_frame_file(path) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Convenience: read an OpenPose JSON file from disk."""
    with open(path) as f:
        return parse_openpose_frame(json.load(f))


# ─────────────────────── Retargeting ───────────────────────────────

def retarget_hands(left_xyz: np.ndarray,
                   right_xyz: np.ndarray) -> List[List[float]]:
    """Convert two ``(21, 3)`` joint arrays to 30 local Euler XYZ
    rotations (radians) in the viewer's cylinder order.

    Each cylinder's local rotation is computed in the frame of its
    parent cylinder (with identity at the finger root, which the
    viewer combines with the static palm baseRot). Coordinate system
    follows the OpenPose input directly — we do *not* apply any
    coordinate flip; the caller is responsible for ensuring the
    joint positions are in a frame compatible with the viewer's
    Y-up cylinder orientation.
    """
    if left_xyz.shape != (21, 3):
        raise ValueError(f'left_xyz must be (21, 3); got {left_xyz.shape}')
    if right_xyz.shape != (21, 3):
        raise ValueError(f'right_xyz must be (21, 3); got {right_xyz.shape}')

    rotations: List[List[float]] = [[0.0, 0.0, 0.0]] * 30
    parent_total: List[np.ndarray] = [None] * 30  # type: ignore

    for i, seg in enumerate(CYLINDER_SEGMENTS):
        joints = left_xyz if seg['hand'] == 'left' else right_xyz
        ja = joints[seg['joint_a']]
        jb = joints[seg['joint_b']]
        d = jb - ja
        d_norm = np.linalg.norm(d)
        if d_norm < 1e-9:
            rotations[i] = [0.0, 0.0, 0.0]
            parent_total[i] = (parent_total[i - 1] if seg['segment'] > 0
                               else np.array([1.0, 0.0, 0.0, 0.0]))
            continue
        d_world = d / d_norm

        if seg['segment'] == 0:
            p_total = np.array([1.0, 0.0, 0.0, 0.0])
        else:
            p_total = parent_total[i - 1]

        d_local = rotate_vec(d_world, quat_inv(p_total))
        local_q = quat_from_vectors(np.array([0.0, 1.0, 0.0]), d_local)
        rotations[i] = list(quat_to_euler_xyz(local_q))
        parent_total[i] = quat_mul(p_total, local_q)

    return rotations


def retarget_openpose_frame(data: dict, person_index: int = 0
                            ) -> List[List[float]]:
    """End-to-end: OpenPose frame dict → 30 cylinder rotations."""
    l_xyz, _l_conf, r_xyz, _r_conf = parse_openpose_frame(data, person_index)
    return retarget_hands(l_xyz, r_xyz)
