"""Tests for Phase 2b substrate — 4-expert MoE router derivation.

Does not load an LLM (covered by manual smoke test of
``spoeqi_generate_moe``).
"""

import numpy as np
import torch

from django.test import TestCase

from spoeqi.models import Pact
from spoeqi import llm_moe


def _make_pact(name='moe-test'):
    return Pact.objects.create(name=name)


class DeriveExpertLorasTest(TestCase):
    def test_returns_one_per_component(self):
        pact = _make_pact()
        experts = llm_moe.derive_expert_loras(
            pact, components=(0, 1, 2, 3), shape=(64, 128), rank=2)
        self.assertEqual(len(experts), 4)
        for A, B in experts:
            self.assertEqual(A.shape, (2, 128))
            self.assertEqual(B.shape, (64, 2))

    def test_experts_distinct(self):
        pact = _make_pact()
        experts = llm_moe.derive_expert_loras(
            pact, components=(0, 1, 2, 3), shape=(32, 32), rank=2)
        # Each (A, B) should differ from every other.
        for i in range(4):
            for j in range(i + 1, 4):
                self.assertFalse(torch.equal(experts[i][0], experts[j][0]),
                                 f'expert A{i} should differ from A{j}')

    def test_deterministic(self):
        pact = _make_pact()
        e1 = llm_moe.derive_expert_loras(
            pact, components=(0, 1, 2, 3), shape=(16, 16), rank=2)
        e2 = llm_moe.derive_expert_loras(
            pact, components=(0, 1, 2, 3), shape=(16, 16), rank=2)
        for (A1, B1), (A2, B2) in zip(e1, e2):
            torch.testing.assert_close(A1, A2, rtol=0, atol=0)
            torch.testing.assert_close(B1, B2, rtol=0, atol=0)


class DeriveRouterWeightsTest(TestCase):
    def test_shape(self):
        pact = _make_pact()
        w = llm_moe.derive_router_weights(pact, routing_component=4,
                                          generation=0, n_tokens=20, n_experts=4)
        self.assertEqual(w.shape, (20, 4))

    def test_rows_sum_to_one(self):
        pact = _make_pact()
        w = llm_moe.derive_router_weights(pact, routing_component=4,
                                          generation=0, n_tokens=50, n_experts=4)
        np.testing.assert_allclose(w.sum(axis=1), 1.0, atol=1e-12)

    def test_all_nonnegative(self):
        pact = _make_pact()
        w = llm_moe.derive_router_weights(pact, routing_component=4,
                                          generation=0, n_tokens=50, n_experts=4)
        self.assertTrue((w >= 0.0).all())

    def test_deterministic(self):
        pact = _make_pact()
        w1 = llm_moe.derive_router_weights(pact, 4, 0, 30, 4)
        w2 = llm_moe.derive_router_weights(pact, 4, 0, 30, 4)
        np.testing.assert_array_equal(w1, w2)

    def test_zero_tokens_is_empty(self):
        pact = _make_pact()
        w = llm_moe.derive_router_weights(pact, 4, 0, 0, 4)
        self.assertEqual(w.shape, (0, 4))

    def test_different_routing_component_differs(self):
        pact = _make_pact()
        w0 = llm_moe.derive_router_weights(pact, 4, 0, 10, 4)
        w1 = llm_moe.derive_router_weights(pact, 5, 0, 10, 4)
        self.assertFalse(np.array_equal(w0, w1))


class MixedDeltaTest(TestCase):
    def test_one_hot_equals_single_expert(self):
        # If gate weights are [1, 0, 0, 0], the mixed delta equals B0 @ A0.
        experts = [(torch.ones(2, 4), torch.ones(8, 2) * (i + 1))
                   for i in range(4)]
        w = np.array([1.0, 0.0, 0.0, 0.0])
        d = llm_moe._mixed_delta(experts, w)
        torch.testing.assert_close(d, experts[0][1] @ experts[0][0])

    def test_uniform_weights_is_mean(self):
        experts = [(torch.full((2, 4), float(i + 1)),
                    torch.full((8, 2), float(i + 1))) for i in range(4)]
        w = np.full(4, 0.25)
        d = llm_moe._mixed_delta(experts, w)
        expected = sum(0.25 * (B @ A) for A, B in experts)
        torch.testing.assert_close(d, expected)
