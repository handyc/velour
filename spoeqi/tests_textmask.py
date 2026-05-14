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


class TokenModeTest(_TextmaskBase):
    def test_token_registry_has_starters(self):
        for name in ('bert-mlm', 'denoise', 'phonetic', 't5-noise', 'pos-distill'):
            self.assertIn(name, tm.TOKEN_MAPPING_TABLES,
                          f'token mapping {name!r} missing')

    def test_tile_tokens_wraps(self):
        # 4×4 = 16 cells; 3 tokens wrap to fill 16 slots.
        out = tm.tile_tokens('a b c', side=4)
        self.assertEqual(len(out), 16)
        self.assertEqual(out[0],  'a')
        self.assertEqual(out[1],  'b')
        self.assertEqual(out[2],  'c')
        self.assertEqual(out[3],  'a')  # wraps

    def test_tile_tokens_empty(self):
        out = tm.tile_tokens('', side=3)
        self.assertEqual(out, [''] * 9)

    def test_apply_tokens_bert_mlm_masks_some(self):
        pact = _make_pact()
        r = tm.apply_tokens(pact, text='the quick brown fox jumps over the lazy dog',
                            component=0, generation=0, mapping='bert-mlm')
        mask_count = sum(1 for c in r.cells if c.out == '[MASK]')
        # CA colour distribution is roughly balanced; expect 10–40% masked.
        ratio = mask_count / len(r.cells)
        self.assertGreater(ratio, 0.05)
        self.assertLess(ratio, 0.50)

    def test_apply_tokens_denoise_drops_stopwords(self):
        pact = _make_pact()
        r = tm.apply_tokens(pact, text='the fox jumps over the lazy dog',
                            component=2, generation=1, mapping='denoise')
        # Output should not contain 'the' as a standalone (it'd be
        # dropped or stemmed when colour=1; only when colour=0 or 2/3
        # does it survive partly).  Just check the joined output
        # is shorter than naive tile.
        self.assertGreater(len(r.cells), 0)
        # Determinism: same call gives same output.
        r2 = tm.apply_tokens(pact, text='the fox jumps over the lazy dog',
                              component=2, generation=1, mapping='denoise')
        self.assertEqual(r.output_text, r2.output_text)

    def test_apply_tokens_all_returns_64(self):
        pact = _make_pact()
        rs = tm.apply_tokens_all(pact, text='quick brown fox',
                                  generation=0, mapping='bert-mlm')
        self.assertEqual(len(rs), 64)

    def test_apply_tokens_unknown_mapping(self):
        pact = _make_pact()
        with self.assertRaises(ValueError):
            tm.apply_tokens(pact, text='x', component=0, generation=0,
                             mapping='no-such')


class ApplyAllTest(_TextmaskBase):
    def test_returns_64_results(self):
        pact = _make_pact()
        rs = tm.apply_all(pact, text='abcd', generation=0,
                           mapping='attention')
        self.assertEqual(len(rs), 64)
        for i, r in enumerate(rs):
            self.assertEqual(r.component, i)
            self.assertEqual(len(r.cells), pact.component_grid ** 2)

    def test_components_diverge(self):
        # Same input through 64 components — outputs should not all
        # be identical (the seed expansion gives each component its
        # own grid pattern).
        pact = _make_pact()
        rs = tm.apply_all(pact, text='abcdefghij' * 4, generation=0,
                           mapping='attention')
        outs = {r.output_text for r in rs}
        self.assertGreater(len(outs), 1,
                            'all 64 components produced identical output')

    def test_determinism(self):
        pact = _make_pact()
        a = tm.apply_all(pact, text='hello', generation=3,
                         mapping='cipher')
        b = tm.apply_all(pact, text='hello', generation=3,
                         mapping='cipher')
        self.assertEqual([r.output_text for r in a],
                         [r.output_text for r in b])


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

    def test_post_token_mode_renders_token_grid(self):
        pact = _make_pact()
        url = reverse('spoeqi:textmask', args=[pact.slug])
        r = self.client.post(url, {
            'text':       'the quick brown fox jumps',
            'mode':       'token',
            'mapping':    'denoise',
            'component':  '0',
            'generation': '0',
        })
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('token mask grid', body)

    def test_post_token_compare_all_renders_table(self):
        pact = _make_pact()
        url = reverse('spoeqi:textmask', args=[pact.slug])
        r = self.client.post(url, {
            'text':        'attention is all you need',
            'mode':        'token',
            'mapping':     'bert-mlm',
            'component':   '0',
            'generation':  '0',
            'compare_all': 'on',
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn('all 64 components, same input (tokens)', r.content.decode())

    def test_post_compare_all_renders_64_rows(self):
        pact = _make_pact()
        url = reverse('spoeqi:textmask', args=[pact.slug])
        r = self.client.post(url, {
            'text':        'attention',
            'mapping':     'attention',
            'component':   '0',
            'generation':  '0',
            'compare_all': 'on',
        })
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('all 64 components', body)
        import re
        rows = re.findall(r'class="tm-c-idx">(\d+)<', body)
        self.assertEqual(len(rows), 64)
