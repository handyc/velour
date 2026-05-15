"""Tests for spoeqi.evolution — GA over textmask head ensembles."""

import random

from django.test import TestCase

from spoeqi import evolution as ev
from spoeqi import keystream, textmask as tm
from spoeqi.models import Pact


def _make_pact(name='evolution-test'):
    pact = Pact(name=name)
    pact.save()
    return pact


class _Base(TestCase):
    def setUp(self):
        keystream.cache_clear()


class HeadTest(TestCase):
    def test_head_is_hashable_and_frozen(self):
        h = ev.Head(mode='char', table_name='attention',
                    component=3, generation=2)
        # Frozen dataclass: assignment fails.
        with self.assertRaises(Exception):
            h.component = 4   # type: ignore[misc]
        # Hashable: use as dict key.
        d = {h: True}
        self.assertTrue(d[h])

    def test_random_head_uses_only_registered_tables(self):
        rng = random.Random(0)
        for _ in range(50):
            h = ev.random_head(rng)
            self.assertIn(h.mode, ('char', 'token'))
            registry = (tm.MAPPING_TABLES if h.mode == 'char'
                        else tm.TOKEN_MAPPING_TABLES)
            self.assertIn(h.table_name, registry)
            self.assertTrue(0 <= h.component < 64)
            self.assertTrue(0 <= h.generation <= 16)

    def test_random_head_respects_modes_filter(self):
        rng = random.Random(0)
        seen = {ev.random_head(rng, modes=['char']).mode for _ in range(20)}
        self.assertEqual(seen, {'char'})

    def test_random_head_rejects_empty_modes(self):
        rng = random.Random(0)
        with self.assertRaises(ValueError):
            ev.random_head(rng, modes=['attention'])  # not in pool

    def test_mutate_changes_at_most_one_field(self):
        rng = random.Random(1)
        h = ev.Head(mode='char', table_name='attention',
                    component=3, generation=2)
        diffs = 0
        for _ in range(200):
            h2 = ev.mutate_head(h, rng)
            tup_a = h.as_tuple()
            tup_b = h2.as_tuple()
            # Allow mode mutations to also flip table_name (the resampled
            # mode comes with its own table); count that as one logical
            # mutation.
            differing = sum(int(a != b) for a, b in zip(tup_a, tup_b))
            if h.mode != h2.mode:
                self.assertLessEqual(differing, 2)
            else:
                self.assertLessEqual(differing, 1)
            if differing:
                diffs += 1
        # Most mutations should actually mutate something.
        self.assertGreater(diffs, 100)


class ApplyEnsembleTest(_Base):
    def test_apply_ensemble_returns_one_per_head(self):
        pact = _make_pact()
        heads = [
            ev.Head('char',  'attention', 0, 0),
            ev.Head('char',  'cipher',    1, 1),
            ev.Head('token', 'denoise',   2, 0),
        ]
        r = ev.apply_ensemble(pact, heads, 'The quick brown fox')
        self.assertEqual(len(r.per_head), 3)
        self.assertEqual(len(r.stack),    3)
        # Concat is the joined stack.
        self.assertEqual(r.concat, ev.SEP.join(r.stack))
        # Each head's reported head matches the input order.
        self.assertEqual([p.head for p in r.per_head], heads)

    def test_apply_head_rejects_attention_mode(self):
        pact = _make_pact()
        h = ev.Head('attention', 'causal', 0, 0)
        with self.assertRaises(ValueError):
            ev.apply_head(pact, h, 'hi')


class FitnessTest(TestCase):
    def test_lexical_diversity_zero_on_empty(self):
        self.assertEqual(ev.lexical_diversity(None, [], []), 0.0)

    def test_length_target_negative_when_far(self):
        f = ev.length_target(50)
        # Forge minimal EnsembleResult-likes; only `concat` is read.
        from types import SimpleNamespace as NS
        r = NS(concat='x' * 200, stack=['x' * 200])
        self.assertLess(f(None, [r], ['_']), 0.0)

    def test_length_target_better_when_closer(self):
        f = ev.length_target(50)
        from types import SimpleNamespace as NS
        far  = [NS(concat='x' * 200,  stack=['x' * 200])]
        near = [NS(concat='x' * 60,   stack=['x' * 60])]
        self.assertGreater(f(None, near, ['_']), f(None, far, ['_']))


class EvolveTest(_Base):
    """End-to-end GA on a real pact.  Small numbers keep the test fast."""

    def test_deterministic_with_explicit_seed(self):
        pact = _make_pact()
        kwargs = dict(inputs=['hello world', 'the cat sat'],
                       ensemble_size=3, n_population=4, n_generations=3,
                       rng_seed=42)
        a = ev.evolve(pact, **kwargs)
        keystream.cache_clear()
        b = ev.evolve(pact, **kwargs)
        # Final populations identical, head-by-head.
        self.assertEqual(
            [[h.as_tuple() for h in indv] for indv in a.final_population],
            [[h.as_tuple() for h in indv] for indv in b.final_population])
        self.assertEqual(a.final_scores, b.final_scores)
        # History trajectories identical.
        self.assertEqual(
            [(g.gen, g.best_score, g.mean_score) for g in a.history],
            [(g.gen, g.best_score, g.mean_score) for g in b.history])

    def test_default_seed_derives_from_pact(self):
        """Two evolve runs with no rng_seed but same pact give the same
        result; the seed is reproducible from pact.seed_matrix[8:16]."""
        pact = _make_pact()
        a = ev.evolve(pact, inputs=['hi'], ensemble_size=2,
                      n_population=2, n_generations=1)
        keystream.cache_clear()
        b = ev.evolve(pact, inputs=['hi'], ensemble_size=2,
                      n_population=2, n_generations=1)
        self.assertEqual(a.rng_seed, b.rng_seed)
        self.assertEqual(a.final_scores, b.final_scores)

    def test_cache_hits_when_elite_carries_over(self):
        pact = _make_pact()
        r = ev.evolve(pact, inputs=['hi'], ensemble_size=2,
                      n_population=4, n_generations=4,
                      n_elite=1, rng_seed=7)
        # Elites get re-scored next generation; that's a pure cache hit.
        self.assertGreater(r.cache_hits, 0)
        self.assertGreater(r.cache_misses, 0)

    def test_history_length_matches_generations(self):
        pact = _make_pact()
        r = ev.evolve(pact, inputs=['hi'], ensemble_size=2,
                      n_population=2, n_generations=5, rng_seed=0)
        self.assertEqual(len(r.history), 5)

    def test_validation_errors(self):
        pact = _make_pact()
        with self.assertRaises(ValueError):
            ev.evolve(pact, inputs=[], ensemble_size=2,
                      n_population=2, n_generations=1)
        with self.assertRaises(ValueError):
            ev.evolve(pact, inputs=['x'], ensemble_size=0,
                      n_population=2, n_generations=1)
        with self.assertRaises(ValueError):
            ev.evolve(pact, inputs=['x'], ensemble_size=2,
                      n_population=1, n_generations=1)
        with self.assertRaises(ValueError):
            ev.evolve(pact, inputs=['x'], ensemble_size=2,
                      n_population=2, n_generations=0)
        with self.assertRaises(ValueError):
            ev.evolve(pact, inputs=['x'], ensemble_size=2,
                      n_population=2, n_generations=1,
                      mutation_rate=2.0)
        with self.assertRaises(ValueError):
            ev.evolve(pact, inputs=['x'], ensemble_size=2,
                      n_population=2, n_generations=1,
                      n_elite=99)
        with self.assertRaises(ValueError):
            ev.evolve(pact, inputs=['x'], ensemble_size=2,
                      n_population=2, n_generations=1,
                      gen_window=(5, 2))

    def test_length_target_finds_better_solution(self):
        """Smoke test that the GA actually optimises: best score should
        not get worse from gen 0 to the final generation under elitism."""
        pact = _make_pact()
        r = ev.evolve(pact, inputs=['the quick brown fox'],
                      ensemble_size=3, n_population=6, n_generations=5,
                      n_elite=1,
                      fitness=ev.length_target(80), rng_seed=11)
        self.assertGreaterEqual(r.history[-1].best_score,
                                 r.history[0].best_score)
