"""Tests for the tableau FOL engine.

The block-like rows here are bare dataclasses, so the engine can be
exercised without spinning up Django's ORM.  See `logic.evaluate`
docstring — anything with ``.shape``, ``.size``, ``.name``, ``.x``,
``.y`` and a stable identity is a valid block-row.
"""
from dataclasses import dataclass
from django.test import SimpleTestCase

from . import logic


@dataclass(eq=False)
class B:
    shape: str
    size:  str
    name:  str
    x:     int
    y:     int
    # id used by the equality predicate; auto-incremented per instance.
    id:    int = 0
    _next_id: int = 0

    def __post_init__(self):
        B._next_id += 1
        self.id = B._next_id


@dataclass
class FakeWorld:
    mode: str = 'square'
    dim:  int = 8


class _Helper(SimpleTestCase):
    def check(self, src, w, blocks, expected):
        ok, val, _ast = logic.parse_and_eval(src, w, blocks=blocks)
        self.assertTrue(ok, f'parse/eval failed: {val}')
        self.assertEqual(
            val, expected,
            f'{src} → {val}, expected {expected}')


class ParserTests(_Helper):
    """Smoke-tests for tokenizer + parser surface syntax."""

    def test_basic_atomic(self):
        ast = logic.parse('Cube(a)')
        self.assertEqual(ast, ('pred', 'Cube', ['a']))

    def test_equality(self):
        ast = logic.parse('a = b')
        self.assertEqual(ast, ('eq', 'a', 'b'))

    def test_quantifier_unicode(self):
        ast = logic.parse('∀x Cube(x)')
        self.assertEqual(ast, ('all', 'x', ('pred', 'Cube', ['x'])))

    def test_quantifier_ascii(self):
        ast = logic.parse('forall x Cube(x)')
        self.assertEqual(ast, ('all', 'x', ('pred', 'Cube', ['x'])))

    def test_connectives_unicode(self):
        ast = logic.parse('Cube(a) → Small(a)')
        self.assertEqual(
            ast, ('impl',
                  ('pred', 'Cube', ['a']),
                  ('pred', 'Small', ['a'])))

    def test_connectives_ascii(self):
        ast = logic.parse('Cube(a) -> Small(a)')
        self.assertEqual(
            ast, ('impl',
                  ('pred', 'Cube', ['a']),
                  ('pred', 'Small', ['a'])))

    def test_negation_and_paren(self):
        ast = logic.parse('¬(Cube(a) ∧ Small(a))')
        self.assertEqual(
            ast, ('not',
                  ('and',
                   ('pred', 'Cube', ['a']),
                   ('pred', 'Small', ['a']))))

    def test_precedence(self):
        # ¬ binds tighter than ∧, which binds tighter than ∨, which
        # binds tighter than →, which binds tighter than ↔.
        ast = logic.parse('¬Cube(a) ∧ Tet(b) ∨ Dodec(c) → Small(a) ↔ Large(b)')
        # Expected: ((((¬Cube(a)) ∧ Tet(b)) ∨ Dodec(c)) → Small(a)) ↔ Large(b)
        self.assertEqual(ast[0], 'iff')
        self.assertEqual(ast[1][0], 'impl')

    def test_parse_error(self):
        with self.assertRaises(logic.ParseError):
            logic.parse('Cube(')


class SharedPredicateTests(_Helper):
    def setUp(self):
        self.w = FakeWorld(mode='square')
        self.a = B('cube',  'small',  'a', 0, 0)
        self.b = B('tet',   'medium', 'b', 1, 0)
        self.c = B('dodec', 'large',  'c', 2, 0)
        self.blocks = [self.a, self.b, self.c]

    def test_shape(self):
        self.check('Cube(a)',  self.w, self.blocks, True)
        self.check('Cube(b)',  self.w, self.blocks, False)
        self.check('Tet(b)',   self.w, self.blocks, True)
        self.check('Dodec(c)', self.w, self.blocks, True)

    def test_size(self):
        self.check('Small(a)',  self.w, self.blocks, True)
        self.check('Medium(b)', self.w, self.blocks, True)
        self.check('Large(c)',  self.w, self.blocks, True)

    def test_larger_smaller(self):
        self.check('Larger(c, a)',  self.w, self.blocks, True)
        self.check('Larger(a, c)',  self.w, self.blocks, False)
        self.check('Smaller(a, c)', self.w, self.blocks, True)
        self.check('SameSize(a, b)', self.w, self.blocks, False)
        self.check('SameShape(a, b)', self.w, self.blocks, False)


class SquarePredicateTests(_Helper):
    def setUp(self):
        self.w = FakeWorld(mode='square')
        # Layout:  a . b
        #          . c .
        #          . . .
        self.a = B('cube',  'small',  'a', 0, 0)
        self.b = B('cube',  'small',  'b', 2, 0)
        self.c = B('cube',  'small',  'c', 1, 1)
        self.blocks = [self.a, self.b, self.c]

    def test_leftof_rightof(self):
        self.check('LeftOf(a, b)',  self.w, self.blocks, True)
        self.check('RightOf(b, a)', self.w, self.blocks, True)
        self.check('LeftOf(b, a)',  self.w, self.blocks, False)

    def test_samerow_samecol(self):
        self.check('SameRow(a, b)', self.w, self.blocks, True)
        self.check('SameCol(a, c)', self.w, self.blocks, False)
        self.check('SameRow(a, c)', self.w, self.blocks, False)

    def test_adjoins(self):
        self.check('Adjoins(a, c)', self.w, self.blocks, False)  # diagonal
        d = B('cube', 'small', 'd', 1, 0)
        self.check('Adjoins(a, d)', self.w, self.blocks + [d], True)

    def test_between(self):
        d = B('cube', 'small', 'd', 1, 0)
        # d at (1,0), a at (0,0), b at (2,0): d strictly between a and b.
        self.check('Between(d, a, b)', self.w, self.blocks + [d], True)
        self.check('Between(a, d, b)', self.w, self.blocks + [d], False)


class HexPredicateTests(_Helper):
    def setUp(self):
        self.w = FakeWorld(mode='hex')
        # Hexagonal layout in axial coords.
        # Origin a at (0,0); neighbour b at (1,0); non-neighbour c at (2,0).
        self.a = B('cube', 'small', 'a',  0,  0)
        self.b = B('tet',  'small', 'b',  1,  0)
        self.c = B('dodec','small', 'c',  2,  0)
        self.blocks = [self.a, self.b, self.c]

    def test_adjacent(self):
        self.check('Adjacent(a, b)', self.w, self.blocks, True)
        self.check('Adjacent(a, c)', self.w, self.blocks, False)
        self.check('Adjacent(b, c)', self.w, self.blocks, True)

    def test_north_south(self):
        d = B('cube', 'small', 'd', 0, -1)  # r < a's r → "north"
        self.check('NorthOf(d, a)', self.w, self.blocks + [d], True)
        self.check('SouthOf(a, d)', self.w, self.blocks + [d], True)

    def test_axes(self):
        # Three points on the q-axis (same q): vary r.
        self.check('SameRAxis(a, b)', self.w, self.blocks, True)   # both r=0
        self.check('SameRAxis(a, c)', self.w, self.blocks, True)
        self.check('SameQAxis(a, b)', self.w, self.blocks, False)  # different q

    def test_between(self):
        # a-b-c collinear on r=0 with b strictly between.
        self.check('BetweenHex(b, a, c)', self.w, self.blocks, True)
        self.check('BetweenHex(a, b, c)', self.w, self.blocks, False)

    def test_square_predicate_unavailable_on_hex(self):
        ok, msg, _ = logic.parse_and_eval(
            'LeftOf(a, b)', self.w, blocks=self.blocks)
        self.assertFalse(ok)
        self.assertIn('unknown predicate', msg)


class QuantifierTests(_Helper):
    def setUp(self):
        self.w = FakeWorld(mode='square')
        self.a = B('cube',  'small', 'a', 0, 0)
        self.b = B('cube',  'small', 'b', 1, 0)
        self.c = B('cube',  'small', 'c', 2, 0)

    def test_universal_true(self):
        self.check('∀x Cube(x)', self.w, [self.a, self.b, self.c], True)

    def test_universal_false(self):
        d = B('tet', 'medium', 'd', 3, 0)
        self.check('∀x Cube(x)', self.w, [self.a, self.b, self.c, d], False)

    def test_existential_true(self):
        d = B('tet', 'medium', 'd', 3, 0)
        self.check('∃x Tet(x)', self.w, [self.a, self.b, self.c, d], True)

    def test_existential_false(self):
        self.check('∃x Dodec(x)', self.w, [self.a, self.b, self.c], False)

    def test_nested_implication(self):
        # Every cube is small.
        self.check(
            '∀x (Cube(x) → Small(x))',
            self.w, [self.a, self.b, self.c], True)
        d = B('cube', 'large', 'd', 3, 0)
        self.check(
            '∀x (Cube(x) → Small(x))',
            self.w, [self.a, self.b, self.c, d], False)

    def test_equality(self):
        self.check('a = a', self.w, [self.a], True)
        self.check('a = b', self.w, [self.a, B('cube', 'small', 'b', 0, 0)],
                   False)
