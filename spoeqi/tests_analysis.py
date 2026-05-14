"""Tests for the bottom-out fingerprint diagnostic."""

from __future__ import annotations

from django.test import TestCase

from spoeqi import analysis, keystream
from spoeqi.models import COMPONENTS, RULE_TABLE_SIZE, Pact


def _identity_rule() -> bytes:
    """Rule where each cell's next state equals its own current state
    (the bottom 2 bits of the 14-bit key are n5, not self — the self
    occupies bits 12-13 of the key).  Constructed by hand so the
    behaviour is exactly 'state unchanged'."""
    out = bytearray(RULE_TABLE_SIZE)
    for k in range(RULE_TABLE_SIZE):
        out[k] = (k >> 12) & 3       # self bits
    return bytes(out)


def _const_rule(v: int) -> bytes:
    return bytes([v & 3]) * RULE_TABLE_SIZE


class ConvergenceFingerprintTest(TestCase):
    def setUp(self):
        analysis.cache_clear()

    def test_const_rule_bottoms_out_to_that_value(self):
        """Every entry of the rule table returns the same colour, so in
        a single step every component flattens to that colour."""
        pact = Pact(
            name='const-2',
            rule_snapshot=_const_rule(2),
        )
        pact.save()
        r = analysis.convergence_fingerprint(pact, max_steps=8)
        self.assertEqual(r['n_uniform'], COMPONENTS)
        self.assertEqual(r['n_cycling'], 0)
        for entry in r['components']:
            self.assertEqual(entry['status'], 'uniform')
            self.assertEqual(entry['colour'], 2)
            self.assertLessEqual(entry['step'], 1)

    def test_identity_rule_stable_when_seed_nonuniform(self):
        """Identity rule never changes the state.  With the default
        xoshiro-expanded seed, most components are *not* uniform but
        ARE stable (period-1)."""
        pact = Pact(
            name='identity',
            rule_snapshot=_identity_rule(),
        )
        pact.save()
        r = analysis.convergence_fingerprint(pact, max_steps=8)
        # The xoshiro expansion of seed_matrix[c] is very unlikely to
        # produce a 256-cell all-same component, but stable should hit
        # every component (state == prev_state after every step).
        self.assertGreaterEqual(r['n_stable'] + r['n_uniform'], COMPONENTS - 4)
        for entry in r['components']:
            self.assertIn(entry['status'], ('uniform', 'stable'))

    def test_uniform_initial_grids_recorded_at_step_zero(self):
        """Album-seeded pact whose initial_grids are already flat
        records every component as 'uniform' at step 0 — no CA tick
        needed."""
        # All 64 components, each a 16×16 grid filled with one colour.
        ig = [[c & 3] * (16 * 16) for c in range(COMPONENTS)]
        pact = Pact(
            name='flat-init',
            initial_grids=ig,
            rule_snapshot=_identity_rule(),
        )
        pact.save()
        r = analysis.convergence_fingerprint(pact, max_steps=4)
        self.assertEqual(r['n_uniform'], COMPONENTS)
        for c, entry in enumerate(r['components']):
            self.assertEqual(entry['step'], 0)
            self.assertEqual(entry['colour'], c & 3)

    def test_bitmap_shape_is_8x8(self):
        pact = Pact(name='bitmap-shape', rule_snapshot=_const_rule(1))
        pact.save()
        r = analysis.convergence_fingerprint(pact, max_steps=4)
        self.assertEqual(len(r['bitmap']), 8)
        for row in r['bitmap']:
            self.assertEqual(len(row), 8)
        # Component c lives at bitmap[c//8][c%8].
        for c in range(COMPONENTS):
            self.assertEqual(r['bitmap'][c // 8][c % 8]['component'], c)

    def test_cache_returns_same_object(self):
        pact = Pact(name='cache-test', rule_snapshot=_const_rule(0))
        pact.save()
        a = analysis.convergence_fingerprint(pact, max_steps=4)
        b = analysis.convergence_fingerprint(pact, max_steps=4)
        self.assertIs(a, b)
        # Different max_steps → fresh result.
        c = analysis.convergence_fingerprint(pact, max_steps=8)
        self.assertIsNot(a, c)

    def test_step_matches_keystream_advance(self):
        """The vectorised step in analysis must produce the same bytes
        as keystream._step for at least the first few generations.
        This is a load-bearing invariant: if the GA evaluates one
        candidate via the vectorised path and the seal uses the
        scalar path, results must still agree."""
        pact = Pact(name='step-equiv', rule_snapshot=_const_rule(0))
        pact.save()
        # Build a non-trivial rule.
        rule = bytearray(RULE_TABLE_SIZE)
        for k in range(RULE_TABLE_SIZE):
            rule[k] = (k ^ (k >> 5)) & 3
        pact.rule_snapshot = bytes(rule)
        pact.save()

        import numpy as np
        side = pact.component_grid
        area = side * side
        initial = keystream.initial_multi_grid(pact)
        state_np = np.frombuffer(initial, dtype=np.uint8).reshape(COMPONENTS, area).copy()
        rules_np = np.frombuffer(pact.per_component_rules(),
                                  dtype=np.uint8).reshape(COMPONENTS, RULE_TABLE_SIZE)
        nbr = analysis._hex_neighbour_indices(side)

        scalar = initial
        for _ in range(3):
            scalar = keystream._step(scalar, side, pact.per_component_rules())
            state_np = analysis._step_all(state_np, rules_np, nbr)
            self.assertEqual(bytes(state_np.tobytes()), scalar,
                              'vectorised step diverged from scalar step')
