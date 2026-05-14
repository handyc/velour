"""Tests for the OpenPose → 30-cylinder retargeting.

Synthetic inputs only; no actual OpenPose data file is required.
"""

import json
import math
import numpy as np

from django.test import TestCase

from signs import openpose


# ─────────────────────── helpers ───────────────────────────────────

def _rest_pose_xyz(spread=1.0) -> np.ndarray:
    """21-joint rest pose: wrist at origin, every finger extended
    along +Y, with MCP-to-tip spaced by 1 unit per segment. Finger
    bases (MCPs) are spread across X.

    With this input the retargeter should return ~zero rotations
    everywhere — every cylinder already points along +Y in world
    space and each parent total rotation is identity."""
    xyz = np.zeros((21, 3))
    # Wrist at origin.
    xyz[0] = [0.0, 0.0, 0.0]
    chains = [
        ('thumb',  (1, 2, 3, 4),    -2.0 * spread),
        ('index',  (5, 6, 7, 8),    -1.0 * spread),
        ('middle', (9, 10, 11, 12),  0.0),
        ('ring',   (13, 14, 15, 16), 1.0 * spread),
        ('pinky',  (17, 18, 19, 20), 2.0 * spread),
    ]
    for _, idxs, x in chains:
        # First MCP/CMC at y=1, then each subsequent joint at y+1.
        for k, j in enumerate(idxs):
            xyz[j] = [x, 1.0 + k, 0.0]
    return xyz


def _bent_index_xyz() -> np.ndarray:
    """Like the rest pose, but the *left* index finger's tip
    (joint 8) is bent so the distal segment points along +Z
    instead of +Y. The proximal and intermediate stay along +Y."""
    xyz = _rest_pose_xyz()
    # Index chain joints are 5, 6, 7, 8. Keep 5, 6, 7 along Y.
    # Bend the (7→8) segment to point along +Z instead of +Y.
    xyz[8] = xyz[7] + np.array([0.0, 0.0, 1.0])
    return xyz


# ─────────────────────── quaternion-math sanity ───────────────────

class QuaternionMathTest(TestCase):
    def test_identity_for_aligned_vectors(self):
        q = openpose.quat_from_vectors(np.array([0.0, 1.0, 0.0]),
                                       np.array([0.0, 1.0, 0.0]))
        np.testing.assert_allclose(q, [1, 0, 0, 0], atol=1e-9)

    def test_180_flip(self):
        q = openpose.quat_from_vectors(np.array([0.0, 1.0, 0.0]),
                                       np.array([0.0, -1.0, 0.0]))
        # 180° around any axis perpendicular to Y is correct.
        self.assertAlmostEqual(q[0], 0.0, places=6)
        rotated = openpose.rotate_vec(np.array([0.0, 1.0, 0.0]), q)
        np.testing.assert_allclose(rotated, [0, -1, 0], atol=1e-6)

    def test_quaternion_inverse_round_trip(self):
        q = openpose.quat_from_vectors(np.array([0.0, 1.0, 0.0]),
                                       np.array([0.6, 0.8, 0.0]))
        v = np.array([1.0, 2.0, 3.0])
        rotated = openpose.rotate_vec(v, q)
        back = openpose.rotate_vec(rotated, openpose.quat_inv(q))
        np.testing.assert_allclose(back, v, atol=1e-6)

    def test_euler_round_trip_via_matrix(self):
        # Construct a known quaternion, extract Euler XYZ, build
        # the matrix from those Euler angles, and check it matches.
        q = openpose.quat_from_vectors(np.array([0.0, 1.0, 0.0]),
                                       np.array([0.6, 0.8, 0.0]))
        rx, ry, rz = openpose.quat_to_euler_xyz(q)
        # Build the same rotation by composing X, Y, Z elementaries
        # in 'XYZ' intrinsic order — matches Three.js.
        cx, sx = math.cos(rx), math.sin(rx)
        cy, sy = math.cos(ry), math.sin(ry)
        cz, sz = math.cos(rz), math.sin(rz)
        Rx = np.array([[1,0,0],[0,cx,-sx],[0,sx,cx]])
        Ry = np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]])
        Rz = np.array([[cz,-sz,0],[sz,cz,0],[0,0,1]])
        M_from_euler = Rx @ Ry @ Rz
        M_from_quat  = openpose.quat_to_matrix(q)
        np.testing.assert_allclose(M_from_euler, M_from_quat, atol=1e-6)


# ─────────────────────── topology sanity ───────────────────────────

class TopologyTest(TestCase):
    def test_thirty_cylinders(self):
        self.assertEqual(len(openpose.CYLINDER_SEGMENTS), 30)

    def test_finger_order_matches_viewer(self):
        # Left hand first, then right; thumb, index, middle, ring, pinky.
        expected_finger_order = list(openpose.FINGER_ORDER) * 2
        actual = []
        for seg in openpose.CYLINDER_SEGMENTS:
            if seg['segment'] == 0:
                actual.append(seg['finger'])
        # 10 fingers total
        self.assertEqual(actual, expected_finger_order)

    def test_segments_skip_wrist_edge(self):
        # First cylinder of each finger is chain[1]→chain[2], NOT
        # chain[0]→chain[1] (the wrist-to-MCP edge that the viewer
        # represents as the palm).
        for seg in openpose.CYLINDER_SEGMENTS:
            chain = openpose.FINGER_CHAIN[seg['finger']]
            self.assertEqual(seg['joint_a'], chain[seg['segment'] + 1])
            self.assertEqual(seg['joint_b'], chain[seg['segment'] + 2])


# ─────────────────────── retargeter behavior ──────────────────────

class RetargetTest(TestCase):
    def test_rest_pose_yields_zero_rotations(self):
        # Every cylinder already points along +Y, so all local
        # rotations should be ~0.
        rest = _rest_pose_xyz()
        rotations = openpose.retarget_hands(rest, rest)
        self.assertEqual(len(rotations), 30)
        for i, rxyz in enumerate(rotations):
            for ax, v in zip('xyz', rxyz):
                self.assertAlmostEqual(
                    v, 0.0, places=5,
                    msg=f'cylinder {i} axis r{ax} = {v}, expected 0')

    def test_bent_index_tip_changes_only_distal_segment(self):
        # Bending the left index distal cylinder (joint 7→8) should
        # produce a non-trivial rotation on that one cylinder only,
        # while the proximal (cyl 3) and intermediate (cyl 4) of the
        # left index stay at zero.
        bent = _bent_index_xyz()
        rest = _rest_pose_xyz()
        rotations = openpose.retarget_hands(bent, rest)

        # L_Index_1 is cylinder 3, L_Index_2 is 4, L_Index_3 is 5.
        # First two should be ~0.
        np.testing.assert_allclose(rotations[3], [0, 0, 0], atol=1e-5)
        np.testing.assert_allclose(rotations[4], [0, 0, 0], atol=1e-5)
        # Distal should be a 90° bend onto the Z axis. That maps to
        # Y→Z, which is a rotation of +π/2 around the X axis under
        # the XYZ Euler convention.
        rx, ry, rz = rotations[5]
        self.assertAlmostEqual(rx, math.pi / 2, places=5)
        self.assertAlmostEqual(ry, 0.0, places=5)
        self.assertAlmostEqual(rz, 0.0, places=5)

    def test_other_hand_unaffected(self):
        bent_left = _bent_index_xyz()
        rest_right = _rest_pose_xyz()
        rotations = openpose.retarget_hands(bent_left, rest_right)
        # Cylinders 15..29 are the right hand.
        for i in range(15, 30):
            np.testing.assert_allclose(rotations[i], [0, 0, 0], atol=1e-5)

    def test_overlapping_joints_yield_zero(self):
        # Pathological input: all joints at origin. Every segment
        # has zero length so the retargeter should fall through to
        # identity-rotation cleanly rather than NaN-ing.
        zeros = np.zeros((21, 3))
        rotations = openpose.retarget_hands(zeros, zeros)
        for rxyz in rotations:
            for v in rxyz:
                self.assertEqual(v, 0.0)

    def test_chain_locality_holds(self):
        # Bending the middle segment of left middle finger should
        # leave the proximal cylinder of left middle (cyl 6) at zero
        # but produce a non-zero rotation on the middle (cyl 7) and
        # potentially a *compensating* rotation on the distal (cyl 8)
        # — because the distal's parent is now rotated, but the
        # distal's target direction in world is still +Y.
        xyz = _rest_pose_xyz()
        # Bend middle finger's intermediate so joints 10→11 points +Z.
        xyz[11] = xyz[10] + np.array([0.0, 0.0, 1.0])
        # And tip still extends +Y from there.
        xyz[12] = xyz[11] + np.array([0.0, 1.0, 0.0])
        rotations = openpose.retarget_hands(xyz, _rest_pose_xyz())
        # L_Middle_1 (cyl 6) — proximal — unchanged.
        np.testing.assert_allclose(rotations[6], [0, 0, 0], atol=1e-5)
        # L_Middle_2 (cyl 7) — intermediate — π/2 about X.
        self.assertAlmostEqual(rotations[7][0], math.pi / 2, places=5)
        # L_Middle_3 (cyl 8) — distal — local +Y in its parent frame
        # means world +Z (because parent is now Y→Z rotated).
        # But the actual joint-to-joint direction in world is +Y, so
        # the local rotation must undo the parent: -π/2 about X.
        self.assertAlmostEqual(rotations[8][0], -math.pi / 2, places=5)


# ─────────────────────── OpenPose JSON parsing ─────────────────────

class ParseFrameTest(TestCase):
    def _frame(self, l_keys=None, r_keys=None):
        l = l_keys or [0.0] * 63
        r = r_keys or [0.0] * 63
        return {
            'people': [{
                'hand_left_keypoints_2d':  l,
                'hand_right_keypoints_2d': r,
            }]
        }

    def test_parse_empty_hand_keypoints_returns_zeros(self):
        l_xyz, l_c, r_xyz, r_c = openpose.parse_openpose_frame(self._frame())
        self.assertEqual(l_xyz.shape, (21, 3))
        self.assertEqual(r_xyz.shape, (21, 3))
        np.testing.assert_array_equal(l_xyz, np.zeros((21, 3)))
        np.testing.assert_array_equal(l_c, np.zeros(21))

    def test_parse_unpacks_xy_and_confidence(self):
        keys = [1.0, 2.0, 0.9] + [0.0] * 60  # joint 0 at (1, 2) conf 0.9
        l_xyz, l_c, _, _ = openpose.parse_openpose_frame(
            self._frame(l_keys=keys))
        np.testing.assert_allclose(l_xyz[0], [1.0, 2.0, 0.0])
        self.assertAlmostEqual(l_c[0], 0.9)

    def test_wrong_keypoint_count_raises(self):
        bad = {'people': [{'hand_left_keypoints_2d': [0.0] * 30,
                           'hand_right_keypoints_2d': [0.0] * 63}]}
        with self.assertRaises(ValueError):
            openpose.parse_openpose_frame(bad)

    def test_no_people_raises(self):
        with self.assertRaises(ValueError):
            openpose.parse_openpose_frame({'people': []})

    def test_end_to_end_retarget_from_dict(self):
        # Build a frame where both hands are in the rest pose.
        rest_flat = []
        rest = _rest_pose_xyz()
        for j in range(21):
            rest_flat.extend([rest[j, 0], rest[j, 1], 1.0])
        frame = {'people': [{
            'hand_left_keypoints_2d':  rest_flat,
            'hand_right_keypoints_2d': rest_flat,
        }]}
        rotations = openpose.retarget_openpose_frame(frame)
        self.assertEqual(len(rotations), 30)
        for rxyz in rotations:
            for v in rxyz:
                self.assertAlmostEqual(v, 0.0, places=5)
