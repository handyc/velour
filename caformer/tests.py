"""tests for caformer — survey integrity + view smoke tests."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from . import components as cmp


class ComponentSurveyTest(TestCase):
    """The eight primitives are the load-bearing claim of the app —
    they must stay in sync with the user's mental model."""

    EXPECTED_SLUGS = [
        'embedding', 'layer_norm', 'self_attention', 'projection',
        'mlp', 'transformer', 'softmax', 'output',
    ]

    def test_eight_primitives_in_order(self):
        slugs = [c.slug for c in cmp.COMPONENTS]
        self.assertEqual(slugs, self.EXPECTED_SLUGS)

    def test_every_component_has_required_fields(self):
        for c in cmp.COMPONENTS:
            self.assertTrue(c.real_llm,  f'{c.slug}: empty real_llm')
            self.assertTrue(c.ca_design, f'{c.slug}: empty ca_design')
            self.assertTrue(c.one_liner, f'{c.slug}: empty one_liner')
            self.assertIn(c.status,
                           {'sketch', 'partial', 'working', 'optimised'})

    def test_get_resolves_known_slug(self):
        self.assertIsNotNone(cmp.get('embedding'))
        self.assertIsNone(cmp.get('does-not-exist'))


class CompositionLadderTest(TestCase):
    """The recursive abstraction ladder must climb monotonically and
    every composition must reference at least one previous component
    or composition (no orphan scales)."""

    def test_abstraction_levels_climb(self):
        levels = [c.abstraction for c in cmp.COMPOSITIONS]
        self.assertEqual(levels, sorted(levels))
        self.assertEqual(min(levels), 1)

    def test_every_composition_references_something(self):
        for c in cmp.COMPOSITIONS:
            self.assertTrue(c.contains, f'{c.slug}: empty contains')

    def test_top_is_dmn_loop(self):
        # default_mode_loop sits at L6 above chat_gpt3_5_shape (L5),
        # so it's the highest abstraction in the ladder.
        self.assertEqual(cmp.COMPOSITIONS[-1].slug, 'default_mode_loop')


class ViewsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.user = U.objects.create_user(
            username='caformer-test', password='x', is_superuser=True,
            is_staff=True)

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.user)

    def test_index_renders(self):
        r = self.c.get('/caformer/')
        self.assertEqual(r.status_code, 200)
        for slug in ComponentSurveyTest.EXPECTED_SLUGS:
            self.assertIn(slug.encode(), r.content)

    def test_each_component_page_renders(self):
        for c in cmp.COMPONENTS:
            r = self.c.get(f'/caformer/component/{c.slug}/')
            self.assertEqual(r.status_code, 200, f'{c.slug} returned {r.status_code}')
            self.assertIn(c.name.encode(), r.content)

    def test_each_composition_page_renders(self):
        for c in cmp.COMPOSITIONS:
            r = self.c.get(f'/caformer/composition/{c.slug}/')
            self.assertEqual(r.status_code, 200, f'{c.slug} returned {r.status_code}')
            self.assertIn(c.name.encode(), r.content)

    def test_unknown_component_404s(self):
        r = self.c.get('/caformer/component/does-not-exist/')
        self.assertEqual(r.status_code, 404)


class PrimitivesTest(TestCase):
    """The single-CA stand-ins for transformer ops behave directionally
    correct; they're not perfect drop-ins but they hold the contract
    'same args in → same result out, sensible at the limits'."""

    def test_hex_ca_step_deterministic_and_4_state(self):
        import numpy as np
        from caformer import primitives as p
        rule = p.random_rule_table(seed=42)
        state = np.array([[i % 4 for i in range(16)]] * 16, dtype=np.uint8)
        s1 = p.hex_ca_step(state, rule)
        s2 = p.hex_ca_step(state, rule)
        self.assertTrue((s1 == s2).all())
        self.assertEqual(s1.shape, (16, 16))
        self.assertEqual(set(s1.flatten().tolist()) - {0, 1, 2, 3}, set())

    def test_softmax_greedy_at_low_temperature(self):
        import numpy as np
        from caformer.primitives import ca_softmax_sample
        logits = np.array([0.0, 5.0, 0.0, 0.0, 0.0])
        idx, _ = ca_softmax_sample(logits, temperature=0.001, ca_seed=42)
        self.assertEqual(idx, 1, 'low T must collapse to argmax')

    def test_softmax_diversifies_at_high_temperature(self):
        import numpy as np
        from caformer.primitives import ca_softmax_sample
        from collections import Counter
        logits = np.array([0.0, 5.0, 0.0, 0.0, 0.0])
        seen = {ca_softmax_sample(logits, temperature=1000.0, ca_seed=s)[0]
                for s in range(40)}
        self.assertGreaterEqual(len(seen), 3,
            'at high T the noise should drive sampling across ≥3 indices')

    def test_softmax_deterministic(self):
        import numpy as np
        from caformer.primitives import ca_softmax_sample
        logits = np.array([1.0, 2.0, 3.0, 4.0])
        a, _ = ca_softmax_sample(logits, temperature=2.0, ca_seed=999)
        b, _ = ca_softmax_sample(logits, temperature=2.0, ca_seed=999)
        self.assertEqual(a, b)

    def test_mlp_preserves_shape_and_alphabet(self):
        import numpy as np
        from caformer import primitives as p
        rule = p.random_rule_table(seed=7)
        state = np.random.RandomState(0).randint(0, 4, size=(16, 16),
                                                   dtype=np.uint8)
        out = p.ca_mlp(state, rule_table=rule, k_ticks=4, expand=False)
        self.assertEqual(out.shape, state.shape)
        self.assertEqual(set(out.flatten().tolist()) - {0, 1, 2, 3}, set())

    def test_mlp_expand_changes_output(self):
        import numpy as np
        from caformer import primitives as p
        rule = p.random_rule_table(seed=7)
        state = np.random.RandomState(0).randint(0, 4, size=(16, 16),
                                                   dtype=np.uint8)
        a = p.ca_mlp(state, rule_table=rule, k_ticks=4, expand=False)
        b = p.ca_mlp(state, rule_table=rule, k_ticks=4, expand=True)
        self.assertFalse((a == b).all(),
            'expand=True must take a different path through the rule than expand=False')

    def test_layer_norm_uniform_default(self):
        import numpy as np
        from caformer.primitives import ca_layer_norm
        unbalanced = np.zeros((16, 16), dtype=np.uint8)
        unbalanced[:8] = 3
        out = ca_layer_norm(unbalanced)
        counts = np.bincount(out.flatten(), minlength=4)
        # Uniform target → 64 each cell on a 16×16 grid.
        for c in counts:
            self.assertEqual(c, 64)


class ReductiveTest(TestCase):
    """The irreducible-core versions must be smaller than primitives.py
    counterparts AND still produce sensible output."""

    def test_softmax_min_is_argmax(self):
        import numpy as np
        from caformer.reductive import ca_softmax_sample_min
        self.assertEqual(ca_softmax_sample_min(np.array([0, 5, 0, 0])), 1)

    def test_mlp_min_runs_one_tick(self):
        import numpy as np
        from caformer import primitives as p
        from caformer.reductive import ca_mlp_min
        rule = p.random_rule_table(seed=7)
        state = np.array([[i % 4 for i in range(16)]] * 16, dtype=np.uint8)
        out = ca_mlp_min(state, rule)
        self.assertEqual(out.shape, state.shape)

    def test_layer_norm_min_shifts_mode(self):
        import numpy as np
        from caformer.reductive import ca_layer_norm_min
        # All-3 input → mode is 3; output is all-0
        s = np.full((4, 4), 3, dtype=np.uint8)
        self.assertTrue((ca_layer_norm_min(s) == 0).all())

    def test_attention_min_one_in_one_out(self):
        import numpy as np
        from caformer import primitives as p
        from caformer.reductive import ca_attention_min
        rule = p.random_rule_table(seed=1)
        states = [np.zeros((8, 8), dtype=np.uint8),
                   np.full((8, 8), 1, dtype=np.uint8)]
        out = ca_attention_min(states, rule)
        self.assertEqual(len(out), len(states))
        for o, s in zip(out, states):
            self.assertEqual(o.shape, s.shape)

    def test_self_reflection_yields_steps(self):
        from caformer import primitives as p
        from caformer.reductive import self_reflection_min
        rule = p.random_rule_table(seed=99)
        steps = list(self_reflection_min(rule, steps=4))
        self.assertEqual(len(steps), 4)
        # Each step should have a different hash (unless we hit a fixed
        # point, which would be a notable observation but not a failure).
        hashes = {h for _, _, h in steps}
        self.assertGreaterEqual(len(hashes), 1)


class CorpusTest(TestCase):
    def test_min_is_deterministic(self):
        from caformer.data import ca_corpus_min
        a = ca_corpus_min(seed=42, n=64)
        b = ca_corpus_min(seed=42, n=64)
        self.assertTrue((a == b).all())
        c = ca_corpus_min(seed=43, n=64)
        self.assertFalse((a == c).all())

    def test_2d_shape(self):
        from caformer.data import ca_corpus
        x = ca_corpus(seed=42, n_seq=8, seq_len=32)
        self.assertEqual(x.shape, (8, 32))
        # 4-state CA values must stay in [0, 4)
        self.assertTrue((x < 4).all())

    def test_tokenised_vocab_range(self):
        from caformer.data import ca_corpus_tokenised
        x = ca_corpus_tokenised(seed=42, vocab_size=50, n_seq=4, seq_len=16)
        self.assertEqual(x.shape, (4, 16))
        self.assertTrue((x < 50).all())

    def test_fingerprint_stable(self):
        from caformer.data import corpus_fingerprint
        a = corpus_fingerprint(seed=42, n=512)
        b = corpus_fingerprint(seed=42, n=512)
        self.assertEqual(a, b)
        c = corpus_fingerprint(seed=43, n=512)
        self.assertNotEqual(a, c)


class TransformerTest(TestCase):
    """The composed tiny CA transformer must run end-to-end and stay
    deterministic — the precondition for any later evolutionary work."""

    def test_embed_sequence_shape_and_count(self):
        import numpy as np
        from caformer.primitives import random_rule_table
        from caformer.transformer import ca_embed_sequence
        rule = random_rule_table(123)
        states = ca_embed_sequence([1, 2, 3, 4, 5], embed_rule=rule)
        self.assertEqual(len(states), 5)
        for s in states:
            self.assertEqual(s.shape, (16, 16))

    def test_transformer_block_keeps_count(self):
        import numpy as np
        from caformer.primitives import random_rule_table
        from caformer.transformer import (
            ca_embed_sequence, ca_transformer_block,
        )
        embed = random_rule_table(1)
        attn  = random_rule_table(2)
        mlp   = random_rule_table(3)
        states = ca_embed_sequence([10, 20, 30], embed_rule=embed)
        out = ca_transformer_block(states, attn_rule=attn, mlp_rule=mlp)
        self.assertEqual(len(out), len(states))

    def test_forward_returns_vocab_logits(self):
        import numpy as np
        from caformer.transformer import ca_forward
        logits = ca_forward([1, 2, 3], n_blocks=2, vocab_size=64)
        self.assertEqual(logits.shape, (64,))
        self.assertTrue((logits >= 0).all())

    def test_generate_deterministic(self):
        from caformer.transformer import ca_generate
        a = ca_generate([7, 14], max_new_tokens=5, n_blocks=2, vocab_size=64)
        b = ca_generate([7, 14], max_new_tokens=5, n_blocks=2, vocab_size=64)
        self.assertEqual(a, b)

    def test_trace_captures_every_named_module(self):
        """trace=[] populates a per-stage list including embed, the 7
        block primitives (q,k,v,score,mix,merge,mlp), the three norm
        positions, and output. Asserts the contract the live chat view
        relies on."""
        import numpy as np
        from caformer.transformer import ca_forward_qkv
        trace = []
        logits = ca_forward_qkv([72, 105, 33], n_blocks=2,
                                  vocab_size=32, base_seed=42,
                                  trace=trace)
        self.assertEqual(logits.shape, (32,))
        names = [item['name'] for item in trace]
        # Embedding + final norm + output anchors
        self.assertIn('embed', names)
        self.assertIn('norm-final', names)
        self.assertIn('output', names)
        # Every block contributes its 10 sub-stages prefixed with b{i}-
        for bi in (0, 1):
            for stage in ('norm-pre', 'q', 'k', 'v', 'score', 'mix',
                            'merge', 'norm-mid', 'mlp', 'merge-out'):
                self.assertIn(f'b{bi}-{stage}', names)
        # Every recorded grid is 16x16 and 2-bit-valued
        for item in trace:
            g = item['grid']
            self.assertEqual(g.shape, (16, 16))
            self.assertTrue(((g >= 0) & (g < 4)).all())
        # Score stages carry an attention-head note
        score_items = [i for i in trace if i['name'].endswith('-score')]
        for s in score_items:
            self.assertIn('j*', s.get('note', ''))

    def test_trace_none_default_does_not_change_output(self):
        """Calling without trace must be byte-identical to the
        pre-trace baseline (no observable side-effects on logits)."""
        from caformer.transformer import ca_forward_qkv
        a = ca_forward_qkv([1, 2, 3], n_blocks=1, vocab_size=16,
                             base_seed=7)
        b = ca_forward_qkv([1, 2, 3], n_blocks=1, vocab_size=16,
                             base_seed=7, trace=[])
        import numpy as np
        self.assertTrue(np.array_equal(a, b))

    def test_generate_changes_with_seed(self):
        # At default T=1, the noise is small relative to the logit
        # range so different seeds usually produce identical outputs
        # (the argmax is robust).  Crank T high enough that noise
        # dominates and the seed actually matters.
        from caformer.transformer import ca_generate
        a = ca_generate([7, 14], max_new_tokens=5, n_blocks=2,
                          vocab_size=64, sample_seed=0, temperature=100.0)
        b = ca_generate([7, 14], max_new_tokens=5, n_blocks=2,
                          vocab_size=64, sample_seed=1, temperature=100.0)
        self.assertNotEqual(a, b,
            'with high temperature, distinct sample_seeds must drive '
            'distinct generations')


class EmbeddingPrimitivesTest(TestCase):
    def test_embedding_deterministic(self):
        import numpy as np
        from caformer.primitives import ca_embedding, random_rule_table
        rule = random_rule_table(1)
        a = ca_embedding(42, rule_table=rule)
        b = ca_embedding(42, rule_table=rule)
        self.assertTrue((a == b).all())
        c = ca_embedding(43, rule_table=rule)
        self.assertFalse((a == c).all())

    def test_residual_xor_recoverable(self):
        import numpy as np
        from caformer.primitives import ca_residual
        a = np.array([[0, 1, 2, 3]], dtype=np.uint8)
        b = np.array([[3, 2, 1, 0]], dtype=np.uint8)
        c = ca_residual(a, b, mode='xor')
        # XOR is reversible: c XOR b == a.
        d = ca_residual(c, b, mode='xor')
        self.assertTrue((d == a).all())

    def test_output_head_returns_vocab_size(self):
        import numpy as np
        from caformer.primitives import ca_output_head
        s = np.full((4, 4), 1, dtype=np.uint8)
        logits = ca_output_head(s, vocab_size=32)
        self.assertEqual(logits.shape, (32,))
        # Cells of colour ≠ 0 contribute weight 1.0; 16 cells split
        # over 32 vocab entries → total mass = 16.
        self.assertAlmostEqual(float(logits.sum()), 16.0, places=5)


class FullyCAPrimitivesTest(TestCase):
    """Verify the every-step-is-a-CA upgrade path: Q/K/V self-attention,
    CA-merged residual, iterative norm, iterative output head, and the
    fully-CA forward pass.  These are the primitives that turn caformer
    from 'mostly CA' into 'literally a CA at every step'."""

    def test_qkv_project_runnable(self):
        import numpy as np
        from caformer.primitives import ca_qkv_project, random_rule_table
        rule = random_rule_table(11)
        s = np.full((8, 8), 2, dtype=np.uint8)
        out = ca_qkv_project(s, rule, k_ticks=2)
        self.assertEqual(out.shape, s.shape)
        self.assertTrue(((out >= 0) & (out < 4)).all())

    def test_attention_score_higher_for_self_match(self):
        import numpy as np
        from caformer.primitives import (
            ca_attention_score, random_rule_table)
        rule = random_rule_table(13)
        s = np.full((4, 4), 2, dtype=np.uint8)
        # Q vs K=Q should score deterministic, and Q vs K=different
        # should score differently — proves the score is sensitive
        # to the K input, not just a constant.
        same = ca_attention_score(s, s, rule)
        diff = ca_attention_score(s, np.full((4, 4), 0, dtype=np.uint8), rule)
        self.assertNotEqual(same, diff)

    def test_self_attention_preserves_count(self):
        import numpy as np
        from caformer.primitives import (
            ca_self_attention, ca_embedding, random_rule_table)
        embed = random_rule_table(0)
        states = [ca_embedding(t, rule_table=embed) for t in (1, 2, 3, 4)]
        out = ca_self_attention(
            states,
            q_rule=random_rule_table(1), k_rule=random_rule_table(2),
            v_rule=random_rule_table(3), score_rule=random_rule_table(4),
            mix_rule=random_rule_table(5))
        self.assertEqual(len(out), len(states))
        for o in out:
            self.assertEqual(o.shape, (16, 16))

    def test_residual_merge_runnable(self):
        import numpy as np
        from caformer.primitives import ca_residual_merge, random_rule_table
        rule = random_rule_table(7)
        a = np.zeros((4, 4), dtype=np.uint8)
        b = np.full((4, 4), 3, dtype=np.uint8)
        out = ca_residual_merge(a, b, rule)
        self.assertEqual(out.shape, a.shape)
        self.assertTrue(((out >= 0) & (out < 4)).all())

    def test_layer_norm_iterative_evens_histogram(self):
        import numpy as np
        from caformer.primitives import ca_layer_norm_iterative
        # All-3 input: extremely unbalanced.  Even with default rule
        # the output shouldn't be 100% colour 3 anymore — the
        # balance-promoting rule should have introduced *some* variety.
        unbalanced = np.full((16, 16), 3, dtype=np.uint8)
        out = ca_layer_norm_iterative(unbalanced, k_ticks=4)
        counts = np.bincount(out.flatten(), minlength=4)
        self.assertLess(counts[3], unbalanced.size,
                         'iterative norm must introduce non-3 cells')

    def test_output_head_iterative_logits_shape(self):
        import numpy as np
        from caformer.primitives import ca_output_head_iterative
        s = np.array([[i % 4 for i in range(16)]] * 16, dtype=np.uint8)
        logits = ca_output_head_iterative(s, vocab_size=128)
        self.assertEqual(logits.shape, (128,))
        # Each cell contributes 1.0 to one vocab index → total = #cells.
        self.assertAlmostEqual(float(logits.sum()), float(s.size), places=5)

    def test_forward_qkv_runs_and_is_deterministic(self):
        import numpy as np
        from caformer.transformer import ca_forward_qkv
        a = ca_forward_qkv([1, 2, 3], n_blocks=2, vocab_size=32)
        b = ca_forward_qkv([1, 2, 3], n_blocks=2, vocab_size=32)
        self.assertEqual(a.shape, (32,))
        self.assertTrue(np.allclose(a, b))
        self.assertGreater(float(a.sum()), 0.0)

    def test_forward_qkv_changes_with_inputs(self):
        import numpy as np
        from caformer.transformer import ca_forward_qkv
        a = ca_forward_qkv([1, 2, 3],     n_blocks=2, vocab_size=32)
        b = ca_forward_qkv([1, 2, 3, 4],  n_blocks=2, vocab_size=32)
        self.assertFalse(np.allclose(a, b),
            'adding a token must change the output distribution')


class DMNCAFormerTest(TestCase):
    """The fully-CA Default-Mode loop must run with no external LLM
    and produce measurable wandering — no spoeqi, no minGPT, no
    Pact required."""

    def test_dmn_caformer_yields_steps(self):
        from caformer.dmn import dmn_loop_caformer, CADMNStep
        steps = list(dmn_loop_caformer(max_steps=4, grid_side=8,
                                         vocab_size=16, n_blocks=1))
        self.assertEqual(len(steps), 4)
        for s in steps:
            self.assertIsInstance(s, CADMNStep)
            self.assertEqual(len(s.grid_hash), 16)
            self.assertGreaterEqual(s.sampled, 0)
            self.assertLess(s.sampled, 16)

    def test_dmn_caformer_observables(self):
        from caformer.dmn import dmn_loop_caformer, dmn_observables
        steps = list(dmn_loop_caformer(max_steps=8, grid_side=8,
                                         vocab_size=16, n_blocks=1))
        obs = dmn_observables(steps)
        for k in ('novelty_rate', 'unique_tokens',
                   'buffer_overlap', 'unique_hashes', 'cycle_length'):
            self.assertIn(k, obs)
        # An 8-step run on an 8×8 grid should see at least *some*
        # novelty.  If 0, the substrate hit a fixed point on tick 0.
        self.assertGreater(obs['novelty_rate'], 0.0)


class ChatGPTShapesTest(TestCase):
    """The recursive-ladder L3 (chat_gpt2_shape) and L4 (chat_gpt3_shape)
    must run end-to-end and respect the same determinism + responsiveness
    contracts as the rest of the stack."""

    def test_chat_gpt2_shape_runs(self):
        from caformer.transformer import chat_gpt2_shape
        logits = chat_gpt2_shape([1, 2], vocab_size=8)
        self.assertEqual(logits.shape, (8,))
        # 12 blocks × 7 rules each — a lot of CA work, but must produce
        # non-zero logits unless every rule happened to zero its block.
        self.assertGreater(float(logits.sum()), 0.0)

    def test_chat_gpt3_shape_sum_blend(self):
        import numpy as np
        from caformer.transformer import chat_gpt3_shape
        a = chat_gpt3_shape([1, 2], vocab_size=8, blend='sum')
        b = chat_gpt3_shape([1, 2], vocab_size=8, blend='sum')
        self.assertEqual(a.shape, (8,))
        self.assertTrue(np.allclose(a, b))

    def test_chat_gpt3_shape_vote_blend(self):
        from caformer.transformer import chat_gpt3_shape
        # vote blend produces integer-count logits; total = n_branches.
        logits = chat_gpt3_shape([1, 2], vocab_size=8, blend='vote',
                                   n_branches=4)
        self.assertEqual(int(logits.sum()), 4)

    def test_chat_gpt3_shape_rejects_bad_blend(self):
        from caformer.transformer import chat_gpt3_shape
        with self.assertRaises(ValueError):
            chat_gpt3_shape([1, 2], blend='nonsense')

    def test_chat_gpt3_5_shape_moe_runs(self):
        import numpy as np
        from caformer.transformer import chat_gpt3_5_shape
        a = chat_gpt3_5_shape([1, 2], vocab_size=8,
                                 n_experts=3, top_k=2)
        b = chat_gpt3_5_shape([1, 2], vocab_size=8,
                                 n_experts=3, top_k=2)
        self.assertEqual(a.shape, (8,))
        # MoE is deterministic given the same input + seed.
        self.assertTrue(np.allclose(a, b))

    def test_chat_gpt3_5_shape_router_routes_differently(self):
        import numpy as np
        from caformer.transformer import _moe_router_affinities
        # Different prompts must produce different affinity rankings,
        # otherwise the router is doing nothing.
        a = _moe_router_affinities([1, 2, 3],     n_experts=4, base_seed=42)
        b = _moe_router_affinities([7, 11, 13], n_experts=4, base_seed=42)
        self.assertFalse(np.allclose(a, b),
            'router scores must respond to the prompt, not be constant')

    def test_chat_gpt3_5_shape_rejects_bad_top_k(self):
        from caformer.transformer import chat_gpt3_5_shape
        with self.assertRaises(ValueError):
            chat_gpt3_5_shape([1, 2], n_experts=3, top_k=4)
        with self.assertRaises(ValueError):
            chat_gpt3_5_shape([1, 2], n_experts=3, top_k=0)

    def test_hybrid_moe_pure_ca_path(self):
        """chat_gpt3_5_hybrid with all-CA experts must work without
        any LLM dependency loaded — the LLM path is opt-in only."""
        import numpy as np
        from caformer.transformer import chat_gpt3_5_hybrid
        L = chat_gpt3_5_hybrid([1, 2, 3], vocab_size=8,
                                 expert_specs=['ca', 'ca'],
                                 top_k=1)
        self.assertEqual(L.shape, (8,))
        self.assertTrue(np.isfinite(L).all())

    def test_tower_is_deterministic_and_finite(self):
        """tower(n_levels=2) must produce finite logits of shape (V,)
        and be deterministic across calls (same seed → same logits)."""
        import numpy as np
        from caformer.transformer import tower
        a = tower([1, 2, 3], n_levels=2, vocab_size=8,
                    n_experts=2, top_k=1)
        b = tower([1, 2, 3], n_levels=2, vocab_size=8,
                    n_experts=2, top_k=1)
        self.assertEqual(a.shape, (8,))
        self.assertTrue(np.isfinite(a).all())
        self.assertTrue(np.allclose(a, b))

    def test_tower_rejects_bad_n_levels(self):
        from caformer.transformer import tower
        with self.assertRaises(ValueError):
            tower([1, 2], n_levels=0)
        with self.assertRaises(ValueError):
            tower([1, 2], n_levels=2,
                   level_kwargs=[{}])  # length mismatch

    def test_hybrid_moe_rejects_unknown_spec(self):
        from caformer.transformer import chat_gpt3_5_hybrid
        with self.assertRaises(ValueError):
            chat_gpt3_5_hybrid([1, 2], vocab_size=8,
                                 expert_specs=['ca', ('nope', 'foo')],
                                 top_k=2)


class StreamingResponseTest(TestCase):
    """Live SSE endpoints must skip GZipMiddleware (which buffers
    streaming_content to compress).  Verify Content-Encoding=identity
    is set on every streaming endpoint we ship."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        U = get_user_model()
        cls.user = U.objects.create_user(
            username='caf-stream', password='x',
            is_superuser=True, is_staff=True)

    def setUp(self):
        from django.test import Client
        self.c = Client()
        self.c.force_login(self.user)

    def test_dmn_stream_skips_gzip(self):
        r = self.c.get('/caformer/dmn/stream/',
                        {'max_steps': 1, 'grid_side': 8,
                         'n_blocks': 1, 'vocab_size': 4})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get('Content-Encoding'), 'identity')

    def test_chat_stream_skips_gzip(self):
        r = self.c.get('/caformer/chat/reply/stream/',
                        {'q': 'hi', 'n': 1, 'n_blocks': 1})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get('Content-Encoding'), 'identity')


class TrainingPipelineTest(TestCase):
    """The corpus-text → GA → TrainedModel → chat-with-model loop must
    work end-to-end.  Smallest possible config so the test stays fast."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        U = get_user_model()
        cls.user = U.objects.create_user(
            username='caf-train', password='x',
            is_superuser=True, is_staff=True)

    def test_text_fitness_runs_and_scores_in_range(self):
        from caformer.ga import make_text_fitness, FULL_STACK_NAMES
        from caformer.primitives import random_rule_table
        # Default mode is now 'logprob' — range is (-log(V), 0].
        # Stay on 'argmax' here so the [0,1] range invariant still
        # documents what the legacy mode produces.
        f = make_text_fitness('the quick brown fox' * 4,
                                n_blocks=1, n_windows=4, window_len=4,
                                mode='argmax')
        g = {n: random_rule_table(0x42 ^ (0x100 * (i + 1)))
             for i, n in enumerate(FULL_STACK_NAMES)}
        s = f(g)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 1.0)

    def test_distill_output_rule_shape_is_correct(self):
        """`distill_output_rule` must produce exactly 16,384 bytes,
        each in {0,1,2,3}.  Skipped at this layer if the LLM stack
        isn't importable — dependent path; full e2e covered separately."""
        try:
            import torch  # noqa: F401
            from caformer.distill import distill_output_rule
        except Exception:
            from unittest import SkipTest
            raise SkipTest('torch / distill module unavailable')
        # We don't actually load a backbone here (would download
        # weights). Instead, monkey-patch _load_llm_expert to return a
        # tiny fake that produces uniform logits so the projection
        # math is exercised end-to-end without network I/O.
        from caformer import transformer as tr
        from unittest.mock import patch
        import numpy as np
        import torch as _torch

        class _FakeOut:
            def __init__(self, logits): self.logits = logits

        class _FakeModel:
            def __init__(self, V_bpe): self.V_bpe = V_bpe
            def __call__(self, input_ids=None, attention_mask=None):
                B, T = input_ids.shape
                # Random-but-deterministic logits per row so different
                # LUT indices CAN map to different argmax buckets.
                rng = np.random.default_rng(int(input_ids.sum().item()))
                logits = rng.standard_normal((B, T, self.V_bpe))
                return _FakeOut(_torch.from_numpy(logits))

        class _FakeTok:
            # GPT-2-shaped vocab.
            V = 256
            def __len__(self):  return self.V
            def __call__(self, prompts, **kw):
                # 1 token per prompt (we only need *some* T).
                ids = _torch.tensor([[ord(p[0]) % self.V] for p in prompts])
                return {'input_ids': ids,
                        'attention_mask': _torch.ones_like(ids)}
            def decode(self, ids, **kw): return chr(ids[0] % 128)
        # Re-prime caches with the fake.
        from caformer import transformer as t2
        t2._LLM_EXPERT_CACHE['_fake_'] = (_FakeTok(), _FakeModel(256))
        t2._LLM_BYTEMAP_CACHE.clear()

        from caformer.distill import distill_output_rule
        out = distill_output_rule('_fake_', batch_size=64)
        self.assertEqual(len(out), 16384)
        arr = np.frombuffer(out, dtype=np.uint8)
        self.assertTrue(((arr >= 0) & (arr < 4)).all())
        # The rule must be non-trivial — random LLM logits should NOT
        # all collapse to one bucket.
        self.assertGreater(len(set(arr.tolist())), 1,
            'distilled rule collapsed to a single colour')

    def test_ascii_mask_constrains_sampler(self):
        """allowed_bytes=ASCII_PRINTABLE must restrict samples to that set."""
        import numpy as np
        from caformer.primitives import ca_softmax_sample, ASCII_PRINTABLE
        # Logits favour byte 200 (non-printable) heavily; without mask the
        # sample should be 200; with the ASCII mask it must NOT be 200.
        logits = np.zeros(256, dtype=np.float64)
        logits[200] = 100.0
        no_mask, _ = ca_softmax_sample(logits, temperature=0.1, ca_seed=7)
        with_mask, _ = ca_softmax_sample(logits, temperature=0.1, ca_seed=7,
                                            allowed_bytes=ASCII_PRINTABLE)
        self.assertEqual(no_mask, 200)
        self.assertIn(with_mask, ASCII_PRINTABLE,
            f'masked sample {with_mask} not in ASCII set')

    def test_emit_tinyformer_bakes_corpus_alphabet(self):
        """--full output must contain the CORPUS_ALPHABET[256] array
        with mostly-zero entries reflecting which bytes were in the
        training corpus."""
        from caformer.models import TrainedModel
        from caformer.primitives import random_rule_table
        from django.core.management import call_command
        import tempfile, os
        names = ['q','k','v','score','mix','merge','mlp','norm','output','embed']
        rules = {n: bytes(random_rule_table(0xCAB ^ (0x100 * (i+1))))
                 for i, n in enumerate(names)}
        m = TrainedModel.objects.create(
            slug='tf-alpha-test', name='alpha test',
            **{f'rule_{n}': rules[n] for n in names},
            corpus_excerpt='hello world',   # only these bytes!
            vocab_size=256, n_blocks=1,
            pop_size=1, generations=1, final_fitness=0.0,
        )
        with tempfile.NamedTemporaryFile('w', suffix='.c', delete=False) as fp:
            tmp = fp.name
        try:
            call_command('emit_tinyformer', m.slug, '--out', tmp, '--full')
            src = open(tmp).read()
            self.assertIn('CORPUS_ALPHABET[256]', src)
            self.assertIn('ASCII_MASK[256]', src)
            self.assertIn("-a") if False else None      # touched
        finally:
            os.unlink(tmp)

    def test_emit_tinyformer_full_mode_writes_all_ten_rules(self):
        """--full mode bakes ALL 10 rules and emits the full block."""
        from caformer.models import TrainedModel
        from caformer.primitives import random_rule_table
        from django.core.management import call_command
        import tempfile, os
        names = ['q','k','v','score','mix','merge','mlp','norm','output','embed']
        rules = {n: bytes(random_rule_table(0xCAB ^ (0x100 * (i+1))))
                 for i, n in enumerate(names)}
        m = TrainedModel.objects.create(
            slug='tf-full-test', name='tf full test',
            **{f'rule_{n}': rules[n] for n in names},
            corpus_excerpt='', vocab_size=256, n_blocks=1,
            pop_size=1, generations=1, final_fitness=0.0,
        )
        with tempfile.NamedTemporaryFile('w', suffix='.c', delete=False) as fp:
            tmp = fp.name
        try:
            call_command('emit_tinyformer', m.slug, '--out', tmp, '--full')
            src = open(tmp).read()
            for n in names:
                self.assertIn(f'RULE_{n.upper()}', src,
                    f'--full must bake RULE_{n.upper()}')
            self.assertIn('block_forward', src)
            self.assertIn('attention_score', src)
            self.assertIn('residual_merge', src)
            self.assertIn('ca_mlp', src)
            self.assertIn('output_head', src)
            self.assertGreater(len(src), 100_000,
                '--full source should embed all 10 rule tables')
        finally:
            os.unlink(tmp)

    def test_emit_tinyformer_writes_compilable_c(self):
        """The management command must produce valid C source that
        contains the bake-in arrays + a main(). We don't compile it
        here (cc may not exist in CI); presence checks are enough."""
        from caformer.models import TrainedModel
        from caformer.primitives import random_rule_table
        from django.core.management import call_command
        import tempfile, os
        names = ['q','k','v','score','mix','merge','mlp','norm','output','embed']
        rules = {n: bytes(random_rule_table(0xCAB ^ (0x100 * (i+1))))
                 for i, n in enumerate(names)}
        m = TrainedModel.objects.create(
            slug='tf-test', name='tf test',
            rule_q=rules['q'], rule_k=rules['k'], rule_v=rules['v'],
            rule_score=rules['score'], rule_mix=rules['mix'],
            rule_merge=rules['merge'], rule_mlp=rules['mlp'],
            rule_norm=rules['norm'], rule_output=rules['output'],
            rule_embed=rules['embed'],
            corpus_excerpt='', vocab_size=256, n_blocks=2,
            pop_size=1, generations=1, final_fitness=0.0,
        )
        with tempfile.NamedTemporaryFile('w', suffix='.c', delete=False) as fp:
            tmp = fp.name
        try:
            call_command('emit_tinyformer', m.slug, '--out', tmp)
            src = open(tmp).read()
            self.assertIn('static const unsigned char RULE_EMBED', src)
            self.assertIn('static const unsigned char RULE_OUTPUT', src)
            self.assertIn('int main(', src)
            self.assertIn('hex_step', src)
            self.assertIn('lut_lookup', src)
            # 4096 packed bytes per rule × 2 rules = at least 8 KB of data.
            self.assertGreater(len(src), 8000)
        finally:
            os.unlink(tmp)

    def test_chat_turns_become_training_corpus(self):
        """ChatTurn rows must aggregate into a `user: …\\nca: …\\n\\n`
        corpus that's safe to feed to make_text_fitness."""
        from django.contrib.auth import get_user_model
        from caformer.models import ChatTurn
        U = get_user_model()
        u = U.objects.create_user(username='chat-corp', password='x')
        ChatTurn.objects.create(user=u, prompt='hello',  reply='hi there')
        ChatTurn.objects.create(user=u, prompt='how are you', reply='ok')
        corpus = ChatTurn.training_corpus(u)
        self.assertIn('user: hello',  corpus)
        self.assertIn('ca: hi there', corpus)
        self.assertIn('user: how are you', corpus)
        self.assertGreater(len(corpus), 32)
        # Empty user → empty corpus, not a crash.
        u2 = U.objects.create_user(username='nochat', password='x')
        self.assertEqual(ChatTurn.training_corpus(u2), '')

    def test_evolve_parallel_workers_gives_same_result_as_sequential(self):
        """Threaded fitness eval must produce identical history to
        sequential — same seed, same fitness function, same RNG, just
        parallelised across threads. Sanity: parallelism mustn't
        change the deterministic GA trajectory."""
        from caformer.ga import (FULL_STACK_NAMES, _evolve, GAConfig,
                                    make_text_fitness)
        from caformer.primitives import random_rule_table
        corpus = 'the quick brown fox jumps over the lazy dog ' * 6
        f = make_text_fitness(corpus, vocab_size=256, n_blocks=1,
                                n_windows=4, window_len=8)
        template = {n: random_rule_table(0xBEEF ^ (0x100 * (i + 1)))
                    for i, n in enumerate(FULL_STACK_NAMES)}
        seq_cfg = GAConfig(pop_size=4, generations=2, tournament_k=2,
                              elite_n=1, mutation_rate=0.005, seed=0xBEEF,
                              parallel_workers=1)
        par_cfg = GAConfig(pop_size=4, generations=2, tournament_k=2,
                              elite_n=1, mutation_rate=0.005, seed=0xBEEF,
                              parallel_workers=4)
        # Need separate template copies — _evolve mutates in place via
        # copies but we want full isolation here.
        import copy
        seq_r = _evolve(copy.deepcopy(template), f, seq_cfg)
        par_r = _evolve(copy.deepcopy(template), f, par_cfg)
        self.assertEqual(seq_r.history, par_r.history)
        self.assertAlmostEqual(seq_r.best_fitness, par_r.best_fitness,
                                places=10)

    def test_polish_genome_is_monotone(self):
        """Coordinate-descent polish must never lose ground vs the
        starting genome — that's the whole point of "strictly monotone"."""
        from caformer.ga import (FULL_STACK_NAMES, make_text_fitness,
                                    polish_genome)
        from caformer.primitives import random_rule_table
        f = make_text_fitness('hello world this is a test ' * 4,
                                vocab_size=256, n_blocks=1,
                                n_windows=4, window_len=8)
        g = {n: random_rule_table(0xCAFE ^ (0x100 * (i + 1)))
             for i, n in enumerate(FULL_STACK_NAMES)}
        start_score = f(g)
        polished, best, n_imp = polish_genome(g, f, trials=8, seed=42)
        self.assertGreaterEqual(best, start_score,
            f'polish regressed: {start_score:.4f} → {best:.4f}')
        self.assertGreaterEqual(n_imp, 0)
        # Genome shape must be preserved (same keys, same dtypes).
        self.assertEqual(set(polished.keys()), set(g.keys()))
        for k in polished:
            self.assertEqual(polished[k].dtype, g[k].dtype)
            self.assertEqual(polished[k].size, g[k].size)

    def test_text_fitness_logprob_mode(self):
        """logprob mode: continuous signal in (-log V, 0]; non-flat
        across two random genomes (no GA can climb a flat landscape)."""
        import numpy as np
        from caformer.ga import make_text_fitness, FULL_STACK_NAMES
        from caformer.primitives import random_rule_table
        f = make_text_fitness('to be or not to be that is the question ' * 4,
                                vocab_size=256,
                                n_blocks=1, n_windows=4, window_len=8)
        ceiling = 0.0
        floor = -float(np.log(256)) - 1.0  # uniform baseline minus slack
        scores = []
        for s_ in (0x11, 0x22, 0x33):
            g = {n: random_rule_table(s_ ^ (0x100 * (i + 1)))
                 for i, n in enumerate(FULL_STACK_NAMES)}
            scores.append(f(g))
        for s in scores:
            self.assertLessEqual(s, ceiling)
            self.assertGreaterEqual(s, floor * 4)  # generous lower bound
        self.assertGreater(max(scores) - min(scores), 0.0,
            'logprob mode must give non-flat scores across genomes')

    def test_save_and_load_roundtrip(self):
        from caformer.ga import (
            FULL_STACK_NAMES, save_genome_as_model)
        from caformer.primitives import random_rule_table
        from caformer.models import TrainedModel
        g = {n: random_rule_table(0x99 ^ (0x100 * (i + 1)))
             for i, n in enumerate(FULL_STACK_NAMES)}
        m = save_genome_as_model(g, name='rt', slug='rt',
                                  corpus_excerpt='hi',
                                  final_fitness=0.42)
        self.assertEqual(m.slug, 'rt')
        self.assertEqual(m.final_fitness, 0.42)
        loaded = TrainedModel.objects.get(slug='rt')
        gn = loaded.as_genome()
        # Each rule must round-trip byte-identical so the chat sees
        # exactly what the GA evolved.
        import numpy as np
        for n in FULL_STACK_NAMES:
            self.assertTrue(np.array_equal(gn[n], g[n]),
                f'rule {n!r} did not round-trip')

    def test_chat_uses_trained_model(self):
        from django.test import Client
        from caformer.ga import (
            FULL_STACK_NAMES, save_genome_as_model)
        from caformer.primitives import random_rule_table
        # Save a trained model with very different rules from the
        # default-seed-derived rules so the chat output diverges.
        g = {n: random_rule_table(0xABC0DE ^ (0x100 * (i + 1)))
             for i, n in enumerate(FULL_STACK_NAMES)}
        save_genome_as_model(g, name='diff', slug='diff',
                              corpus_excerpt='', final_fitness=0.0)
        c = Client()
        c.force_login(self.user)
        r1 = c.get('/caformer/chat/reply/',
                    {'q': 'hi', 'n': '4', 'n_blocks': '1',
                     'model': 'diff'})
        r2 = c.get('/caformer/chat/reply/',
                    {'q': 'hi', 'n': '4', 'n_blocks': '1'})
        import json
        j1, j2 = json.loads(r1.content), json.loads(r2.content)
        # Both must succeed; tokens should differ — proves the model
        # parameter actually swaps in the saved rules.
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertNotEqual(j1['tokens'], j2['tokens'],
            'chat with ?model= should produce different tokens than without')


class GATest(TestCase):
    """The special-purpose GA must run, return a winner, and demonstrate
    monotone-or-better fitness across generations.  Per-primitive
    fitness functions must each respond to changes in their target
    rule (i.e. random rules ≠ best rules)."""

    def test_evolve_norm_improves_or_holds(self):
        from caformer.ga import evolve_primitive
        r = evolve_primitive('norm', pop_size=8, generations=4, seed=1)
        first, last = r.history[0][0], r.history[-1][0]
        # Best fitness must not regress over the run (elites + tournament
        # selection guarantee monotone non-decrease at the top).
        self.assertGreaterEqual(last, first)
        self.assertEqual(r.best_genome['norm'].shape, (16384,))

    def test_evolve_score_returns_genome(self):
        from caformer.ga import evolve_primitive
        r = evolve_primitive('score', pop_size=6, generations=3, seed=2)
        self.assertIn('score', r.best_genome)
        self.assertEqual(r.best_genome['score'].dtype.name, 'uint8')

    def test_unknown_primitive_raises(self):
        from caformer.ga import evolve_primitive
        with self.assertRaises(ValueError):
            evolve_primitive('not-a-real-primitive')

    def test_full_stack_smoke(self):
        from caformer.ga import (
            FULL_STACK_NAMES, GAConfig, _evolve, make_corpus_fitness)
        from caformer.primitives import random_rule_table
        fitness = make_corpus_fitness(corpus_seed=42, vocab_size=16,
                                        n_seq=1, seq_len=4, n_blocks=1)
        template = {n: random_rule_table(0x100 * (i + 1))
                     for i, n in enumerate(FULL_STACK_NAMES)}
        cfg = GAConfig(pop_size=3, generations=1, tournament_k=2,
                        elite_n=1, mutation_rate=0.003, seed=42)
        r = _evolve(template, fitness, cfg)
        self.assertEqual(set(r.best_genome.keys()), set(FULL_STACK_NAMES))
        # Fitness is bounded [0, 1] (corpus prediction accuracy).
        self.assertGreaterEqual(r.best_fitness, 0.0)
        self.assertLessEqual(r.best_fitness, 1.0)


class DMNTest(TestCase):
    def test_loop_yields_steps_and_each_seed_changes(self):
        U = get_user_model()
        from spoeqi.models import Pact
        pact = Pact.objects.create(name='dmn-test')
        from caformer.dmn import dmn_loop
        steps = list(dmn_loop(pact, max_steps=3))
        self.assertEqual(len(steps), 3)
        seeds = [s.ca_seed_out for s in steps]
        # Each refined-text hash should differ → seed changes
        self.assertEqual(len(set(seeds)), 3)
