"""spoeqi/tests_metachain — Metapact + metachain expansion smoke tests."""
from __future__ import annotations
import numpy as np
from django.test import TestCase
from django.contrib.auth import get_user_model

from spoeqi.metachain import (
    metachain_expand, classify_rule, quick_class4_score,
    metachain_to_caformer_genome, caformer_kwargs_from_chain,
    CAFORMER_RULE_ORDER, GRID_AREA, RULE_SIZE,
)


class MetachainCoreTest(TestCase):
    def test_size_invariants(self):
        self.assertEqual(GRID_AREA, RULE_SIZE)
        self.assertEqual(RULE_SIZE, 16384)

    def test_classify_rule_returns_class_and_score(self):
        rng = np.random.default_rng(7)
        rule = bytes(rng.integers(0, 4, size=RULE_SIZE, dtype=np.uint8))
        cls, score = classify_rule(rule)
        self.assertIn(cls, (1, 2, 3, 4))
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_classify_rule_is_deterministic(self):
        rng = np.random.default_rng(11)
        rule = bytes(rng.integers(0, 4, size=RULE_SIZE, dtype=np.uint8))
        a = classify_rule(rule)
        b = classify_rule(rule)
        self.assertEqual(a, b)

    def test_metachain_expand_depth_and_byte_count(self):
        rng = np.random.default_rng(42)
        seed = bytes(rng.integers(0, 4, size=RULE_SIZE, dtype=np.uint8))
        chain = metachain_expand(seed, depth=5, chain_ticks=8)
        self.assertEqual(chain.depth, 5)
        self.assertEqual(len(chain.states), 5)
        self.assertEqual(len(chain.classes), 5)
        self.assertEqual(len(chain.scores), 5)
        for s in chain.states:
            self.assertEqual(len(s), RULE_SIZE)
        # as_bytes flat stream
        blob = chain.as_bytes()
        self.assertEqual(len(blob), 5 * RULE_SIZE)
        # chain_quality is sum of per-level scores
        self.assertAlmostEqual(chain.chain_quality,
            sum(chain.scores), places=6)

    def test_metachain_expand_is_byte_identical_across_calls(self):
        """The seal invariant — two parties with the same seed must
        get byte-identical states at every level."""
        rng = np.random.default_rng(99)
        seed = bytes(rng.integers(0, 4, size=RULE_SIZE, dtype=np.uint8))
        a = metachain_expand(seed, depth=4, chain_ticks=6)
        b = metachain_expand(seed, depth=4, chain_ticks=6)
        for sa, sb in zip(a.states, b.states):
            self.assertEqual(sa, sb)

    def test_genome_mapping_has_all_caformer_rules(self):
        rng = np.random.default_rng(13)
        seed = bytes(rng.integers(0, 4, size=RULE_SIZE, dtype=np.uint8))
        chain = metachain_expand(seed, depth=10, chain_ticks=6)
        g = metachain_to_caformer_genome(chain.states)
        self.assertEqual(set(g.keys()), set(CAFORMER_RULE_ORDER))
        for name, arr in g.items():
            self.assertEqual(arr.shape, (RULE_SIZE,))
            self.assertEqual(arr.dtype, np.uint8)
            self.assertTrue(((arr >= 0) & (arr < 4)).all())

    def test_shallow_chain_wraps_into_genome(self):
        """Depth < 10 → genome still has 10 entries (wraps from start)."""
        rng = np.random.default_rng(17)
        seed = bytes(rng.integers(0, 4, size=RULE_SIZE, dtype=np.uint8))
        chain = metachain_expand(seed, depth=3, chain_ticks=6)
        g = metachain_to_caformer_genome(chain.states)
        self.assertEqual(len(g), 10)

    def test_caformer_kwargs_keys(self):
        rng = np.random.default_rng(21)
        seed = bytes(rng.integers(0, 4, size=RULE_SIZE, dtype=np.uint8))
        chain = metachain_expand(seed, depth=10, chain_ticks=6)
        kw = caformer_kwargs_from_chain(chain, n_blocks=2)
        self.assertIn('embed_rule',  kw)
        self.assertIn('block_rules', kw)
        self.assertIn('norm_rule',   kw)
        self.assertIn('output_rule', kw)
        self.assertEqual(len(kw['block_rules']), 2)
        # All block_rules entries share the same 7 keys
        for br in kw['block_rules']:
            self.assertEqual(set(br.keys()),
                {'q','k','v','score','mix','merge','mlp'})


class MetapactModelTest(TestCase):
    def test_round_trip_via_db(self):
        from spoeqi.models import Metapact
        rng = np.random.default_rng(0xCAB)
        seed = bytes(rng.integers(0, 4, size=RULE_SIZE, dtype=np.uint8))
        m = Metapact.objects.create(
            name='roundtrip', slug='roundtrip',
            seed_state=seed, depth=4, chain_ticks=6,
            leaf_probe='hello world',
        )
        chain_a = m.expand()
        loaded = Metapact.objects.get(slug='roundtrip')
        chain_b = loaded.expand()
        # Determinism through DB round-trip
        self.assertEqual(chain_a.as_bytes(), chain_b.as_bytes())
        # caformer_kwargs runnable
        kw = loaded.caformer_kwargs(n_blocks=1)
        from caformer.transformer import ca_forward_qkv
        logits = ca_forward_qkv([72, 105], n_blocks=1, vocab_size=8,
                                  embed_rule=kw['embed_rule'],
                                  block_rules=kw['block_rules'],
                                  norm_rule=kw['norm_rule'],
                                  output_rule=kw['output_rule'])
        self.assertEqual(logits.shape, (8,))
        self.assertTrue(np.isfinite(logits).all())


class MetachainGATest(TestCase):
    def test_evolve_returns_a_better_or_equal_seed(self):
        from spoeqi.metachain_ga import evolve_metapact, MetaGAConfig
        cfg = MetaGAConfig(pop_size=4, generations=2, depth=4,
                              chain_ticks=6, seed=1)
        result = evolve_metapact(
            corpus='hello world test corpus for metapact GA ' * 4,
            cfg=cfg)
        self.assertEqual(len(result.best_seed), RULE_SIZE)
        self.assertEqual(len(result.history), 2)
        # All-time best fitness should match the first column of history's max
        max_hist_best = max(h[0] for h in result.history)
        self.assertGreaterEqual(result.best_fitness + 1e-9, max_hist_best)


class MetapactViewsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.user = U.objects.create_user(
            username='mp-test', password='x',
            is_staff=True, is_superuser=True)

    def setUp(self):
        self.client.login(username='mp-test', password='x')

    def test_list_renders(self):
        r = self.client.get('/spoeqi/metapact/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Metapacts')

    def test_create_post_and_detail(self):
        r = self.client.post('/spoeqi/metapact/new/', {
            'name': 'My Metapact', 'slug': 'my-mp',
            'seed': '123456789', 'depth': '4', 'chain_ticks': '6',
            'leaf_probe': 'tiny probe ' * 8,
        })
        self.assertEqual(r.status_code, 302)
        from spoeqi.models import Metapact
        self.assertTrue(Metapact.objects.filter(slug='my-mp').exists())
        r2 = self.client.get('/spoeqi/metapact/my-mp/')
        self.assertEqual(r2.status_code, 200)

    def test_bytes_endpoint_returns_depth_times_16384(self):
        from spoeqi.models import Metapact
        rng = np.random.default_rng(0xF00D)
        seed = bytes(rng.integers(0, 4, size=RULE_SIZE, dtype=np.uint8))
        Metapact.objects.create(
            name='b', slug='b', seed_state=seed,
            depth=3, chain_ticks=6, leaf_probe='x')
        r = self.client.get('/spoeqi/metapact/b/bytes')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/octet-stream')
        self.assertEqual(len(r.content), 3 * RULE_SIZE)
        self.assertEqual(r['X-Metachain-Depth'], '3')
