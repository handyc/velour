"""Tests for the loupe app — interactive Mandelbrot zoom + agent walks."""

from __future__ import annotations

import json

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from loupe.models import Walk


class IndexTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='lp-i', password='x')
        self.client.force_login(self.user)

    def test_index_renders(self):
        r = self.client.get(reverse('loupe:index'))
        self.assertEqual(r.status_code, 200)
        # The canvas + loupe.js asset must be present.
        self.assertIn(b'id="loupe-canvas"', r.content)
        self.assertIn(b'loupe/loupe.js', r.content)

    def test_walks_index_when_empty(self):
        r = self.client.get(reverse('loupe:walks'))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'no walks saved yet', r.content)


class SaveWalkTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='lp-s', password='x')
        self.client.force_login(self.user)

    def _post(self, body: dict):
        return self.client.post(reverse('loupe:save_walk'),
                                  data=json.dumps(body),
                                  content_type='application/json')

    def test_manual_single_step_save(self):
        r = self._post({
            'name': 'seahorse',
            'method': 'manual',
            'gene': [{'cx': -0.75, 'cy': 0.11, 'span': 0.16,
                      'iter': 256, 'fitness': 3.21}],
            'thumbnail_b64': 'YWJj',
            'thumbnail_w': 64, 'thumbnail_h': 64,
        })
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        w = Walk.objects.get(slug=payload['slug'])
        self.assertEqual(w.name, 'seahorse')
        self.assertEqual(w.method, 'manual')
        self.assertEqual(w.n_steps, 0)        # 1-entry gene = 0 moves
        self.assertAlmostEqual(w.fitness_final, 3.21)
        self.assertAlmostEqual(w.end_span, 0.16)

    def test_empty_gene_rejected(self):
        r = self._post({'gene': []})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Walk.objects.count(), 0)

    def test_invalid_json_rejected(self):
        r = self.client.post(reverse('loupe:save_walk'),
                              data='not json', content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_summary_picks_max_and_mean(self):
        gene = [
            {'cx': 0, 'cy': 0, 'span': 3.0, 'fitness': 1.0},
            {'cx': 0, 'cy': 0, 'span': 2.0, 'fitness': 2.0},
            {'cx': 0, 'cy': 0, 'span': 1.0, 'fitness': 3.5},
            {'cx': 0, 'cy': 0, 'span': 0.5, 'fitness': 2.5},
        ]
        r = self._post({'name': 'multi', 'gene': gene, 'method': 'agent'})
        self.assertEqual(r.status_code, 200)
        w = Walk.objects.get(slug=r.json()['slug'])
        self.assertEqual(w.n_steps, 3)
        self.assertAlmostEqual(w.fitness_max, 3.5)
        self.assertAlmostEqual(w.fitness_mean, (1.0 + 2.0 + 3.5 + 2.5) / 4)
        self.assertAlmostEqual(w.fitness_final, 2.5)
        self.assertAlmostEqual(w.end_span, 0.5)


class SaveWalksTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='lp-pop', password='x')
        self.client.force_login(self.user)

    def test_population_save_creates_many(self):
        body = {
            'population_id': 'pop-abcd1234',
            'name_prefix': 'agent',
            'walks': [
                {'gene': [{'cx': 0, 'cy': 0, 'span': 3.0, 'fitness': 1.0},
                          {'cx': 0.1, 'cy': 0, 'span': 2.0, 'fitness': 1.5}]},
                {'gene': [{'cx': 0, 'cy': 0, 'span': 3.0, 'fitness': 1.0},
                          {'cx': -0.1, 'cy': 0.1, 'span': 1.8, 'fitness': 1.8}]},
                {'gene': []},   # empty → skipped
            ],
        }
        r = self.client.post(reverse('loupe:save_walks'),
                              data=json.dumps(body),
                              content_type='application/json')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d['population_id'], 'pop-abcd1234')
        self.assertEqual(len(d['created']), 2)
        for slug in d['created']:
            w = Walk.objects.get(slug=slug)
            self.assertEqual(w.method, 'agent')
            self.assertEqual(w.population_id, 'pop-abcd1234')

    def test_auto_population_id(self):
        body = {'walks': [{
            'gene': [{'cx': 0, 'cy': 0, 'span': 3.0, 'fitness': 1.0}],
        }]}
        r = self.client.post(reverse('loupe:save_walks'),
                              data=json.dumps(body),
                              content_type='application/json')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d['population_id'].startswith('pop-'))


class WalkDetailTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='lp-d', password='x')
        self.client.force_login(self.user)
        self.walk = Walk.objects.create(
            slug='test-walk', name='Test',
            gene_json=[{'cx': 0, 'cy': 0, 'span': 3.0, 'fitness': 1.0},
                        {'cx': 0.1, 'cy': 0, 'span': 2.0, 'fitness': 1.5}],
            method='agent', n_steps=1,
            fitness_final=1.5, fitness_max=1.5, fitness_mean=1.25,
            end_cx=0.1, end_cy=0, end_span=2.0,
        )

    def test_detail_renders(self):
        r = self.client.get(reverse('loupe:walk_detail',
                                      kwargs={'slug': 'test-walk'}))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('test-walk', body)
        # Gene must be JSON-embedded for the replay JS.
        self.assertIn('"fitness": 1.0', body)
        self.assertIn('"fitness": 1.5', body)

    def test_walk_404_when_missing(self):
        r = self.client.get(reverse('loupe:walk_detail',
                                      kwargs={'slug': 'no-such'}))
        self.assertEqual(r.status_code, 404)

    def test_delete_removes_walk(self):
        r = self.client.post(reverse('loupe:walk_delete',
                                       kwargs={'slug': 'test-walk'}))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Walk.objects.filter(slug='test-walk').exists())


class SpoeqiPaletteTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='lp-pal', password='x')
        self.client.force_login(self.user)
        from spoeqi.models import Pact, RULE_TABLE_SIZE
        self.shared_pact = Pact(name='shared-pal',
                                  rule_snapshot=bytes([0] * RULE_TABLE_SIZE),
                                  palette=[[10, 20, 30],
                                            [200, 50, 50],
                                            [50, 200, 50],
                                            [50, 50, 200]])
        self.shared_pact.save()

    def test_shared_palette_endpoint(self):
        r = self.client.get(reverse('loupe:spoeqi_palette',
                                       kwargs={'slug': self.shared_pact.slug}))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        # Five entries: 1 sentinel black + 4 pact colours.
        self.assertEqual(len(data['palette']), 5)
        self.assertEqual(data['palette'][0], [0, 0, 0])
        self.assertEqual(data['palette'][1], [10, 20, 30])
        self.assertEqual(data['palette'][4], [50, 50, 200])
        self.assertEqual(data['source'], f'spoeqi:{self.shared_pact.slug}')

    def test_404_on_unknown_pact(self):
        r = self.client.get(reverse('loupe:spoeqi_palette',
                                       kwargs={'slug': 'no-such-pact'}))
        self.assertEqual(r.status_code, 404)

    def test_per_component_palette(self):
        from spoeqi.models import Pact, RULE_TABLE_SIZE, COMPONENTS
        per_comp = [
            [[c, c, c], [(c + 10) % 256, 0, 0], [0, c, 0], [0, 0, c]]
            for c in range(COMPONENTS)
        ]
        p = Pact(name='per-comp-pal',
                  rule_snapshot=bytes([0] * RULE_TABLE_SIZE),
                  palette=per_comp)
        p.save()
        r = self.client.get(reverse('loupe:spoeqi_palette',
                                       kwargs={'slug': p.slug}),
                             {'component': '7'})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data['palette']), 5)
        self.assertEqual(data['palette'][1], [7, 7, 7])
        self.assertIn('component:7', data['source'])

    def test_component_clamped_to_valid_range(self):
        """Out-of-range component values clamp into 0..63 — endpoint
        doesn't 500 on a bogus number."""
        from spoeqi.models import Pact, RULE_TABLE_SIZE, COMPONENTS
        per_comp = [
            [[c, c, c], [(c + 10) % 256, 0, 0], [0, c, 0], [0, 0, c]]
            for c in range(COMPONENTS)
        ]
        p = Pact(name='clamp-pal',
                  rule_snapshot=bytes([0] * RULE_TABLE_SIZE),
                  palette=per_comp)
        p.save()
        r = self.client.get(reverse('loupe:spoeqi_palette',
                                       kwargs={'slug': p.slug}),
                             {'component': '999'})
        self.assertEqual(r.status_code, 200)
        # 999 → clamped to 63.
        self.assertIn('component:63', r.json()['source'])
