"""Tests for Phase 2a substrate — deterministic CA → LoRA pipeline.

Does not load an actual LLM (covered by manual smoke test of
``spoeqi_generate``). These pin the byte→float→LoRA shape and
prove the substrate is byte-deterministic.
"""

import numpy as np
import torch

from django.test import TestCase

from spoeqi.models import Pact
from spoeqi import llm_lora


def _make_pact(name='test-pact'):
    return Pact.objects.create(name=name)


class KeystreamUniformsTest(TestCase):
    def test_shape_and_range(self):
        pact = _make_pact()
        u = llm_lora.keystream_uniforms(pact, 0, 0, 100)
        self.assertEqual(u.shape, (100,))
        self.assertTrue(np.all((0.0 <= u) & (u < 1.0)))

    def test_deterministic_same_args(self):
        pact = _make_pact()
        u1 = llm_lora.keystream_uniforms(pact, 0, 0, 50)
        u2 = llm_lora.keystream_uniforms(pact, 0, 0, 50)
        np.testing.assert_array_equal(u1, u2)

    def test_different_generation_differs(self):
        pact = _make_pact()
        u0 = llm_lora.keystream_uniforms(pact, 0, 0, 32)
        u1 = llm_lora.keystream_uniforms(pact, 0, 1, 32)
        self.assertFalse(np.array_equal(u0, u1))

    def test_different_component_differs(self):
        pact = _make_pact()
        a = llm_lora.keystream_uniforms(pact, 0, 0, 32)
        b = llm_lora.keystream_uniforms(pact, 1, 0, 32)
        self.assertFalse(np.array_equal(a, b))

    def test_different_pacts_differ(self):
        pa = _make_pact('pact-a')
        pb = _make_pact('pact-b')
        a = llm_lora.keystream_uniforms(pa, 0, 0, 32)
        b = llm_lora.keystream_uniforms(pb, 0, 0, 32)
        self.assertFalse(np.array_equal(a, b))


class KeystreamGaussiansTest(TestCase):
    def test_shape_and_determinism(self):
        pact = _make_pact()
        z1 = llm_lora.keystream_gaussians(pact, 0, 0, 200)
        z2 = llm_lora.keystream_gaussians(pact, 0, 0, 200)
        self.assertEqual(z1.shape, (200,))
        np.testing.assert_array_equal(z1, z2)

    def test_odd_count_returns_exact_size(self):
        pact = _make_pact()
        z = llm_lora.keystream_gaussians(pact, 0, 0, 7)
        self.assertEqual(z.shape, (7,))

    def test_zero_count_is_empty(self):
        pact = _make_pact()
        z = llm_lora.keystream_gaussians(pact, 0, 0, 0)
        self.assertEqual(z.shape, (0,))

    def test_standard_normal_moments(self):
        pact = _make_pact()
        z = llm_lora.keystream_gaussians(pact, 0, 0, 10_000)
        self.assertLess(abs(z.mean()), 0.1)
        self.assertLess(abs(z.std() - 1.0), 0.1)


class DeriveLoraTest(TestCase):
    def test_shapes(self):
        pact = _make_pact()
        A, B = llm_lora.derive_lora(pact, 0, 0, (768, 768), rank=4)
        self.assertEqual(A.shape, (4, 768))
        self.assertEqual(B.shape, (768, 4))
        self.assertEqual(A.dtype, torch.float32)

    def test_delta_shape_matches_target(self):
        pact = _make_pact()
        rows, cols = 64, 256
        A, B = llm_lora.derive_lora(pact, 0, 0, (rows, cols), rank=3)
        delta = B @ A
        self.assertEqual(delta.shape, (rows, cols))

    def test_deterministic_across_calls(self):
        pact = _make_pact()
        A1, B1 = llm_lora.derive_lora(pact, 7, 42, (32, 32), rank=2)
        A2, B2 = llm_lora.derive_lora(pact, 7, 42, (32, 32), rank=2)
        torch.testing.assert_close(A1, A2, rtol=0, atol=0)
        torch.testing.assert_close(B1, B2, rtol=0, atol=0)

    def test_different_generation_differs(self):
        pact = _make_pact()
        A1, _ = llm_lora.derive_lora(pact, 0, 0, (32, 32), rank=2)
        A2, _ = llm_lora.derive_lora(pact, 0, 1, (32, 32), rank=2)
        self.assertFalse(torch.equal(A1, A2))


class ApplyLoraInplaceTest(TestCase):
    def test_adds_scaled_delta(self):
        W = torch.zeros(8, 8)
        A = torch.ones(2, 8)
        B = torch.ones(8, 2)
        llm_lora.apply_lora_inplace(W, A, B, scale=0.5)
        torch.testing.assert_close(W, torch.ones(8, 8))

    def test_preserves_shape_and_dtype(self):
        W = torch.randn(16, 32, dtype=torch.float32)
        A = torch.randn(3, 32)
        B = torch.randn(16, 3)
        before = W.dtype
        llm_lora.apply_lora_inplace(W, A, B, scale=1e-3)
        self.assertEqual(W.shape, (16, 32))
        self.assertEqual(W.dtype, before)

    def test_scale_zero_is_noop(self):
        W = torch.randn(4, 4)
        W0 = W.clone()
        A = torch.randn(2, 4)
        B = torch.randn(4, 2)
        llm_lora.apply_lora_inplace(W, A, B, scale=0.0)
        torch.testing.assert_close(W, W0)


class DefaultTargetWeightTest(TestCase):
    def test_known_models(self):
        self.assertEqual(
            llm_lora.default_target_weight('distilgpt2'),
            'transformer.h.5.attn.c_proj.weight')
        self.assertEqual(
            llm_lora.default_target_weight('TinyLlama/TinyLlama-1.1B-Chat-v1.0'),
            'model.layers.21.self_attn.o_proj.weight')

    def test_tinyllama_prefix_fallback(self):
        # Unlisted TinyLlama variant should still get a default.
        self.assertEqual(
            llm_lora.default_target_weight('TinyLlama/some-future-variant'),
            'model.layers.21.self_attn.o_proj.weight')

    def test_unknown_raises(self):
        with self.assertRaises(ValueError):
            llm_lora.default_target_weight('made-up/never-existed')


class KeystreamDomainTest(TestCase):
    def test_different_domains_produce_different_bytes(self):
        from spoeqi import keystream
        pact = _make_pact()
        a = keystream.tap(pact, 0, 0, 64)  # default domain
        b = keystream.tap(pact, 0, 0, 64, domain=keystream.DOMAIN_ROUTER)
        self.assertNotEqual(a, b)

    def test_default_domain_preserves_legacy_bytes(self):
        # The existing tap endpoint (and any saved test fixtures) rely on
        # the historical b'spoeqi-tap/1' domain. Make sure that's still
        # what you get when no domain is passed.
        from spoeqi import keystream
        pact = _make_pact()
        a = keystream.tap(pact, 0, 0, 64)
        b = keystream.tap(pact, 0, 0, 64, domain=keystream.DOMAIN_DEFAULT)
        self.assertEqual(a, b)


class FindWeightTest(TestCase):
    def test_dotted_path_resolves(self):
        m = torch.nn.Sequential(
            torch.nn.Linear(4, 8),
            torch.nn.Linear(8, 2),
        )
        w = llm_lora.find_weight(m, '0.weight')
        self.assertIs(w, m[0].weight)

    def test_non_tensor_raises(self):
        m = torch.nn.Linear(4, 8)
        with self.assertRaises((TypeError, AttributeError)):
            llm_lora.find_weight(m, 'nonexistent')
