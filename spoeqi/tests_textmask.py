"""Tests for spoeqi.textmask — CA-as-attention-mask over input text."""

from django.test import TestCase
from django.urls import reverse

from spoeqi import keystream, textmask as tm
from spoeqi.models import Pact


def _make_pact(name='textmask-test'):
    pact = Pact(name=name)
    pact.save()
    return pact


class _TextmaskBase(TestCase):
    """The keystream cache is process-level; clear it before every test."""
    def setUp(self):
        keystream.cache_clear()


class RegistryTest(TestCase):
    def test_starter_mappings_present(self):
        for name in ('attention', 'drop', 'cipher', 'vowels', 'emphasis'):
            self.assertIn(name, tm.MAPPING_TABLES,
                          f'starter mapping {name!r} missing')

    def test_each_mapping_has_4_functions_and_4_labels(self):
        for m in tm.MAPPING_TABLES.values():
            self.assertEqual(len(m.table), 4,
                              f'{m.name}: table must have 4 functions')
            self.assertEqual(len(m.labels), 4,
                              f'{m.name}: labels must have 4 entries')

    def test_attention_table_behaviour(self):
        # The canonical four-head set: pass / mask / upper / lower.
        pass_, mask, upper, lower = tm.MAPPING_TABLES['attention'].table
        self.assertEqual(pass_('a'), 'a')
        self.assertEqual(mask('a'),  '·')
        self.assertEqual(upper('a'), 'A')
        self.assertEqual(lower('B'), 'b')

    def test_drop_table_drops(self):
        _, drop, _, _ = tm.MAPPING_TABLES['drop'].table
        self.assertEqual(drop('a'), '')

    def test_register_rejects_duplicates(self):
        with self.assertRaises(ValueError):
            tm.register('attention', description='x',
                        table=(lambda c: c,) * 4,
                        labels=('a', 'b', 'c', 'd'))


class TileTextTest(TestCase):
    def test_tiles_to_grid_area(self):
        # 4×4 = 16 cells; "ab" tiles to "ababababababab" + 2.
        out = tm.tile_text('ab', side=4)
        self.assertEqual(len(out), 16)
        self.assertEqual(out[0],  'a')
        self.assertEqual(out[1],  'b')
        self.assertEqual(out[2],  'a')
        self.assertEqual(out[15], 'b')

    def test_empty_text_pads_with_spaces(self):
        out = tm.tile_text('', side=3)
        self.assertEqual(out, [' '] * 9)


class ApplyTest(_TextmaskBase):
    def test_returns_grid_with_one_cell_per_position(self):
        pact = _make_pact()
        res = tm.apply(pact, text='abcdefgh',
                        component=0, generation=0, mapping='attention')
        self.assertEqual(res.side, pact.component_grid)
        self.assertEqual(len(res.cells), pact.component_grid ** 2)
        # Each cell has a colour 0..3.
        for c in res.cells:
            self.assertIn(c.color, (0, 1, 2, 3))

    def test_determinism_across_calls(self):
        # Same pact / component / generation / text / mapping must yield
        # the exact same cell sequence.  This is the load-bearing
        # property for Alice/Bob agreement.
        pact = _make_pact()
        a = tm.apply(pact, text='hello world',
                      component=3, generation=2, mapping='cipher')
        b = tm.apply(pact, text='hello world',
                      component=3, generation=2, mapping='cipher')
        self.assertEqual(a.output_text, b.output_text)
        self.assertEqual([(c.color, c.char, c.out) for c in a.cells],
                         [(c.color, c.char, c.out) for c in b.cells])

    def test_different_generation_yields_different_mask(self):
        # The whole point: the CA evolves, so two different gens almost
        # surely give different output.  We use the 'attention' mapping
        # (pass/mask/upper/lower) so any colour churn shows up.
        pact = _make_pact()
        a = tm.apply(pact, text='abcdefghijklmnop' * 8,
                      component=0, generation=0, mapping='attention')
        b = tm.apply(pact, text='abcdefghijklmnop' * 8,
                      component=0, generation=5, mapping='attention')
        self.assertNotEqual(a.output_text, b.output_text)

    def test_unknown_mapping_raises(self):
        pact = _make_pact()
        with self.assertRaises(ValueError):
            tm.apply(pact, text='x', component=0, generation=0,
                      mapping='no-such-mapping')

    def test_out_of_range_component_raises(self):
        pact = _make_pact()
        with self.assertRaises(ValueError):
            tm.apply(pact, text='x', component=999, generation=0,
                      mapping='attention')


class ViewTest(_TextmaskBase):
    def test_get_renders_form(self):
        pact = _make_pact()
        url = reverse('spoeqi:textmask', args=[pact.slug])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('text mask', body)
        # The starter mapping names appear in the dropdown.
        self.assertIn('attention', body)
        self.assertIn('cipher',    body)

    def test_post_renders_grid(self):
        pact = _make_pact()
        url = reverse('spoeqi:textmask', args=[pact.slug])
        r = self.client.post(url, {
            'text':       'hello attention',
            'mapping':    'attention',
            'component':  '0',
            'generation': '0',
        })
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('mask grid', body)
        self.assertIn('output text', body)

    def test_post_with_bad_component_shows_error(self):
        pact = _make_pact()
        url = reverse('spoeqi:textmask', args=[pact.slug])
        r = self.client.post(url, {
            'text':       'x',
            'mapping':    'attention',
            'component':  '999',
            'generation': '0',
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn('bad input', r.content.decode())
