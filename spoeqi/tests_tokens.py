"""Tests for spoeqi.tokens — token-level primitives."""

from django.test import SimpleTestCase

from spoeqi import tokens as t


class TokenizeTest(SimpleTestCase):
    def test_basic_words(self):
        self.assertEqual(t.tokenize('the quick brown fox'),
                         ['the', 'quick', 'brown', 'fox'])

    def test_keeps_apostrophe_clitics(self):
        # don't, can't, it's — kept as single tokens
        self.assertIn("don't", t.tokenize("Why don't you?"))
        self.assertIn("it's", t.tokenize("it's fine"))

    def test_punctuation_as_tokens(self):
        toks = t.tokenize('hello, world!')
        self.assertEqual(toks, ['hello', ',', 'world', '!'])

    def test_empty(self):
        self.assertEqual(t.tokenize(''), [])
        self.assertEqual(t.tokenize(None), [])


class PorterStemTest(SimpleTestCase):
    def test_classic_cases(self):
        cases = [('running', 'run'), ('national', 'nation'),
                 ('relations', 'relat'), ('organization', 'organ'),
                 ('happiness', 'happi'), ('cats', 'cat')]
        for word, expected in cases:
            self.assertEqual(t.porter_stem(word), expected,
                              f'{word!r} → expected {expected!r}, got {t.porter_stem(word)!r}')

    def test_non_alpha_passes(self):
        self.assertEqual(t.porter_stem('42'), '42')
        self.assertEqual(t.porter_stem('!'), '!')

    def test_short_words_pass(self):
        self.assertEqual(t.porter_stem('an'), 'an')
        self.assertEqual(t.porter_stem(''), '')


class SoundexTest(SimpleTestCase):
    def test_known_codes(self):
        # Soundex collisions (canonical Russell & Odell examples)
        self.assertEqual(t.soundex('Robert'),  'R163')
        self.assertEqual(t.soundex('Rupert'),  'R163')
        self.assertEqual(t.soundex('Rubin'),   'R150')
        self.assertEqual(t.soundex('Tymczak'), 'T520')

    def test_pads_to_4_chars(self):
        self.assertEqual(len(t.soundex('Lee')), 4)
        self.assertEqual(len(t.soundex('A')),   4)

    def test_non_alpha_passes(self):
        self.assertEqual(t.soundex('123'),  '123')
        self.assertEqual(t.soundex('!!!'),  '!!!')


class MetaphoneTest(SimpleTestCase):
    def test_distinct_from_soundex(self):
        # Metaphone should differ from Soundex on at least one common name.
        sx_t = t.soundex('Thompson')
        mp_t = t.metaphone('Thompson')
        self.assertNotEqual(sx_t, mp_t)

    def test_th_collapses_to_0(self):
        # Internal 'th' → 0 (zero) marker in our minimal metaphone.
        self.assertIn('0', t.metaphone('Thompson'))


class StopwordTest(SimpleTestCase):
    def test_drop_common(self):
        self.assertEqual(t.drop_stopword('the'),  '')
        self.assertEqual(t.drop_stopword('and'),  '')
        self.assertEqual(t.drop_stopword('fox'),  'fox')

    def test_case_insensitive(self):
        self.assertEqual(t.drop_stopword('The'), '')
        self.assertEqual(t.drop_stopword('AND'), '')

    def test_keep_inverse(self):
        self.assertEqual(t.keep_stopword('the'), 'the')
        self.assertEqual(t.keep_stopword('fox'), '')


class PrimitivesRegistryTest(SimpleTestCase):
    def test_expected_primitives_present(self):
        for name in ('pass','drop','lower','upper','mask','sentinel',
                     'stopdrop','stopkeep','stem','soundex','metaphone'):
            self.assertIn(name, t.PRIMITIVES, f'missing primitive {name!r}')
