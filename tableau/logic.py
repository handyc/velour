"""First-order-logic engine for tableau.

Three pieces:

1. **Tokenizer + parser**.  Surface syntax follows LPL conventions:
   ``∀x P(x)`` / ``∃x P(x)`` for quantifiers (ASCII fallbacks ``forall``
   and ``exists`` accepted too); ``¬`` / ``!``, ``∧`` / ``&&``, ``∨`` /
   ``||``, ``→`` / ``->``, ``↔`` / ``<->`` for connectives; ``=`` for
   identity; predicate names are case-sensitive identifiers followed by
   parenthesised argument lists; variables are unbound identifiers; the
   six canonical Tarski names (``a`` .. ``f``) and any block name on
   the world resolve as constants.

2. **AST**.  Tuples, JSON-serialisable.  See ``parse`` docstring.

3. **Evaluator**.  ``evaluate(ast, world, env=None)`` returns ``True`` /
   ``False`` / a string error message.  Walks the AST against a
   ``World`` and the world's loaded ``Block`` rows; quantifiers iterate
   over those blocks (the domain is the populated blocks, matching
   LPL's "the world is the named objects" reading); predicates resolve
   through ``PREDICATES_SQUARE`` / ``PREDICATES_HEX`` / ``PREDICATES``
   keyed by the world's mode.

The mode-tagged predicate split is the load-bearing design choice — a
sentence written for a square board may reference ``LeftOf``, which is
ill-defined on a hex grid; evaluating it on a hex world yields a clean
"unknown predicate" error rather than a silent wrong answer.
"""
from __future__ import annotations

import re
from typing import Any, Iterable


# ── tokens ──────────────────────────────────────────────────────────

# Unicode operator → canonical token name.  ASCII fallbacks register
# the same canonical name so the parser is symbol-agnostic.
_OPS = {
    '∀': 'FORALL', '∃': 'EXISTS',
    '¬': 'NOT',   '∧': 'AND',  '∨': 'OR',
    '→': 'IMPL',  '↔': 'IFF',
    '(': 'LP', ')': 'RP', ',': 'COMMA', '=': 'EQ',
}
_ASCII_KEYWORDS = {
    'forall': 'FORALL', 'exists': 'EXISTS',
    'not': 'NOT', 'and': 'AND', 'or': 'OR',
}
_ASCII_MULTI = [
    ('<->', 'IFF'),
    ('->',  'IMPL'),
    ('&&',  'AND'),
    ('||',  'OR'),
    ('!',   'NOT'),
]


def tokenize(src: str):
    """Yield (kind, value, col) tuples.  Raises ValueError on bad input."""
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if c in _OPS:
            yield (_OPS[c], c, i)
            i += 1
            continue
        # Multi-char ASCII operators.
        matched = False
        for lit, kind in _ASCII_MULTI:
            if src.startswith(lit, i):
                yield (kind, lit, i)
                i += len(lit)
                matched = True
                break
        if matched:
            continue
        # Identifier (predicate / constant / variable / keyword).
        m = re.match(r'[A-Za-z_][A-Za-z_0-9]*', src[i:])
        if m:
            word = m.group(0)
            low = word.lower()
            if low in _ASCII_KEYWORDS:
                yield (_ASCII_KEYWORDS[low], word, i)
            else:
                yield ('IDENT', word, i)
            i += len(word)
            continue
        raise ValueError(f'unexpected character {c!r} at col {i}')
    yield ('EOF', '', n)


# ── parser ──────────────────────────────────────────────────────────
#
# AST node shapes (all JSON-serialisable):
#
#   ('pred', name, [args...])           — atomic predicate, args = str
#   ('eq',   t1, t2)                    — t1 = t2  (strings)
#   ('not',  inner)
#   ('and',  left, right)
#   ('or',   left, right)
#   ('impl', left, right)
#   ('iff',  left, right)
#   ('all',  var_name, body)
#   ('exists', var_name, body)
#
# Precedence (loosest → tightest):
#   ↔   →   ∨   ∧   ¬   ∀/∃   atomic


class ParseError(Exception):
    pass


class _Parser:
    def __init__(self, src: str):
        self.toks = list(tokenize(src))
        self.i = 0

    def _peek(self):
        return self.toks[self.i]

    def _eat(self, kind):
        k, v, col = self.toks[self.i]
        if k != kind:
            raise ParseError(f'expected {kind}, got {k} {v!r} at col {col}')
        self.i += 1
        return v

    def parse(self):
        sent = self._iff()
        k, v, col = self._peek()
        if k != 'EOF':
            raise ParseError(f'unexpected {k} {v!r} at col {col}')
        return sent

    def _iff(self):
        left = self._impl()
        while self._peek()[0] == 'IFF':
            self.i += 1
            right = self._impl()
            left = ('iff', left, right)
        return left

    def _impl(self):
        left = self._or()
        # Right-associative: A → B → C  ≡  A → (B → C)
        if self._peek()[0] == 'IMPL':
            self.i += 1
            right = self._impl()
            return ('impl', left, right)
        return left

    def _or(self):
        left = self._and()
        while self._peek()[0] == 'OR':
            self.i += 1
            right = self._and()
            left = ('or', left, right)
        return left

    def _and(self):
        left = self._unary()
        while self._peek()[0] == 'AND':
            self.i += 1
            right = self._unary()
            left = ('and', left, right)
        return left

    def _unary(self):
        k, _, _ = self._peek()
        if k == 'NOT':
            self.i += 1
            return ('not', self._unary())
        if k in ('FORALL', 'EXISTS'):
            self.i += 1
            var = self._eat('IDENT')
            body = self._unary()
            return ('all' if k == 'FORALL' else 'exists', var, body)
        return self._atom()

    def _atom(self):
        k, v, col = self._peek()
        if k == 'LP':
            self.i += 1
            inner = self._iff()
            self._eat('RP')
            return inner
        if k != 'IDENT':
            raise ParseError(f'expected predicate or paren, got {k} {v!r} at col {col}')
        self.i += 1
        # Term followed by '=' is an identity, no parens.
        if self._peek()[0] == 'EQ':
            self.i += 1
            rhs = self._eat('IDENT')
            return ('eq', v, rhs)
        # Predicate application.
        self._eat('LP')
        args = []
        if self._peek()[0] != 'RP':
            args.append(self._eat('IDENT'))
            while self._peek()[0] == 'COMMA':
                self.i += 1
                args.append(self._eat('IDENT'))
        self._eat('RP')
        return ('pred', v, args)


def parse(src: str):
    """Parse one FOL sentence into an AST tuple.  Raises ParseError."""
    return _Parser(src).parse()


# ── predicates ──────────────────────────────────────────────────────
#
# Each predicate is a callable taking ``(world, *blocks)`` and returning
# a bool.  Blocks are the model rows already loaded by the evaluator —
# operating on rows (not ids) keeps everything in memory and lets the
# tests use lightweight ad-hoc namespaces (see tests for the dummy
# Block dataclass).
#
# The registry is split by world mode so an attempt to use a square-
# only predicate against a hex world is caught at lookup time.

from .models import Block as _BlockModel  # type: ignore  # only for size order


_SIZE_ORDER = {'small': 0, 'medium': 1, 'large': 2}


def _shape(b, want):
    return b.shape == want

def _size(b, want):
    return b.size == want


# Shared predicates — geometry-free.
PREDICATES_SHARED = {
    'Cube':      (1, lambda w, x: _shape(x, 'cube')),
    'Tet':       (1, lambda w, x: _shape(x, 'tet')),
    'Dodec':     (1, lambda w, x: _shape(x, 'dodec')),
    'Small':     (1, lambda w, x: _size(x, 'small')),
    'Medium':    (1, lambda w, x: _size(x, 'medium')),
    'Large':     (1, lambda w, x: _size(x, 'large')),
    'Larger':    (2, lambda w, x, y: _SIZE_ORDER[x.size] >  _SIZE_ORDER[y.size]),
    'Smaller':   (2, lambda w, x, y: _SIZE_ORDER[x.size] <  _SIZE_ORDER[y.size]),
    'SameSize':  (2, lambda w, x, y: x.size  == y.size),
    'SameShape': (2, lambda w, x, y: x.shape == y.shape),
}


# Square-only.  Convention follows LPL: rows count from "front" (low y)
# to "back" (high y).  LeftOf means strictly less x.  Adjoins is
# 4-neighbour adjacency.
def _square_leftof  (w, a, b): return a.x <  b.x
def _square_rightof (w, a, b): return a.x >  b.x
def _square_frontof (w, a, b): return a.y >  b.y  # "front" = higher y per LPL convention
def _square_backof  (w, a, b): return a.y <  b.y
def _square_samerow (w, a, b): return a.y == b.y
def _square_samecol (w, a, b): return a.x == b.x
def _square_adjoins (w, a, b):
    dx, dy = abs(a.x - b.x), abs(a.y - b.y)
    return (dx + dy) == 1

def _square_between(w, a, b, c):
    """Between(a, b, c) — a is strictly between b and c, both on the
    same line (row, col, or diagonal).  Matches LPL semantics."""
    if (a.x, a.y) in ((b.x, b.y), (c.x, c.y)):
        return False
    if (b.x, b.y) == (c.x, c.y):
        return False
    bx, by = b.x - a.x, b.y - a.y
    cx, cy = c.x - a.x, c.y - a.y
    # Same line: parallel + opposite direction.  bx·cy - by·cx == 0 and
    # the dot product is negative.
    if bx * cy - by * cx != 0:
        return False
    return bx * cx + by * cy < 0

PREDICATES_SQUARE = {
    'LeftOf':   (2, _square_leftof),
    'RightOf':  (2, _square_rightof),
    'FrontOf':  (2, _square_frontof),
    'BackOf':   (2, _square_backof),
    'SameRow':  (2, _square_samerow),
    'SameCol':  (2, _square_samecol),
    'Adjoins':  (2, _square_adjoins),
    'Between':  (3, _square_between),
}


# Hex-only.  Axial coords (q, r) stored as (x, y).  Six neighbours
# around (q, r): (+1,0), (-1,0), (0,+1), (0,-1), (+1,-1), (-1,+1).
# NorthOf / SouthOf use the r axis: smaller r is "north" in a pointy-
# top layout that mirrors the screen.  Three axis predicates check
# alignment along each of the three hex axes.
def _hex_adjacent(w, a, b):
    dq, dr = a.x - b.x, a.y - b.y
    return (dq, dr) in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1))

def _hex_northof(w, a, b): return a.y <  b.y
def _hex_southof(w, a, b): return a.y >  b.y

def _hex_same_qaxis (w, a, b): return a.x == b.x                       # constant q column
def _hex_same_raxis (w, a, b): return a.y == b.y                       # constant r row
def _hex_same_saxis (w, a, b): return (-a.x - a.y) == (-b.x - b.y)     # constant s = -q-r

def _hex_between(w, a, b, c):
    """BetweenHex(a, b, c) — a lies on the straight axial line from b
    to c, strictly between them.  Works on any of the three hex axes."""
    if (a.x, a.y) in ((b.x, b.y), (c.x, c.y)):
        return False
    if (b.x, b.y) == (c.x, c.y):
        return False
    bx, by = b.x - a.x, b.y - a.y
    cx, cy = c.x - a.x, c.y - a.y
    # Same axial line: (b-a) and (c-a) point in opposite directions
    # along a hex axis.  Axes: q-axis (Δr=0), r-axis (Δq=0), s-axis
    # (Δq=-Δr).  Cross-product test in axial coords plus opposite
    # direction.
    if bx * cy - by * cx != 0:
        return False
    return bx * cx + by * cy < 0

PREDICATES_HEX = {
    'Adjacent':   (2, _hex_adjacent),
    'NorthOf':    (2, _hex_northof),
    'SouthOf':    (2, _hex_southof),
    'SameQAxis':  (2, _hex_same_qaxis),
    'SameRAxis':  (2, _hex_same_raxis),
    'SameSAxis':  (2, _hex_same_saxis),
    'BetweenHex': (3, _hex_between),
}


def predicates_for_mode(mode: str):
    """Return the predicate dict in effect for a world's mode."""
    out = dict(PREDICATES_SHARED)
    if mode == 'square':
        out.update(PREDICATES_SQUARE)
    elif mode == 'hex':
        out.update(PREDICATES_HEX)
    return out


# ── evaluator ───────────────────────────────────────────────────────


class EvalError(Exception):
    pass


def evaluate(ast, world, blocks=None, env=None) -> bool:
    """Evaluate ``ast`` against ``world``.

    ``blocks`` is an iterable of Block-like rows; if None the world's
    own ``.blocks.all()`` queryset is used.  ``env`` is an internal
    map var-name → block-row used by quantifiers.

    Domain of quantification is exactly the loaded blocks — that's the
    LPL "world = the named individuals" semantics.  An unbound name in
    a sentence resolves through the env first (for bound variables),
    then through the block names in the world; if neither match, that's
    a referent error.

    Returns True / False.  Raises ``EvalError`` for predicate-arity
    mismatches, unknown predicates, or unbound names.
    """
    if blocks is None:
        blocks = list(world.blocks.all())
    else:
        blocks = list(blocks)
    name_index = {b.name: b for b in blocks if b.name}
    preds = predicates_for_mode(world.mode)
    return _eval(ast, world, blocks, name_index, preds, env or {})


def _resolve(term, env, name_index):
    if term in env:
        return env[term]
    if term in name_index:
        return name_index[term]
    raise EvalError(f'unbound name {term!r}')


def _eval(node, world, blocks, name_index, preds, env):
    kind = node[0]
    if kind == 'pred':
        _, pname, args = node
        if pname not in preds:
            raise EvalError(f'unknown predicate {pname!r} for {world.mode} mode')
        arity, fn = preds[pname]
        if len(args) != arity:
            raise EvalError(
                f'{pname} expects {arity} arg(s), got {len(args)}')
        resolved = [_resolve(a, env, name_index) for a in args]
        return bool(fn(world, *resolved))
    if kind == 'eq':
        _, t1, t2 = node
        b1 = _resolve(t1, env, name_index)
        b2 = _resolve(t2, env, name_index)
        return b1.id == b2.id if hasattr(b1, 'id') else b1 is b2
    if kind == 'not':
        return not _eval(node[1], world, blocks, name_index, preds, env)
    if kind == 'and':
        return (_eval(node[1], world, blocks, name_index, preds, env)
                and _eval(node[2], world, blocks, name_index, preds, env))
    if kind == 'or':
        return (_eval(node[1], world, blocks, name_index, preds, env)
                or  _eval(node[2], world, blocks, name_index, preds, env))
    if kind == 'impl':
        return ((not _eval(node[1], world, blocks, name_index, preds, env))
                or  _eval(node[2], world, blocks, name_index, preds, env))
    if kind == 'iff':
        a = _eval(node[1], world, blocks, name_index, preds, env)
        b = _eval(node[2], world, blocks, name_index, preds, env)
        return a == b
    if kind == 'all':
        _, var, body = node
        for b in blocks:
            sub = dict(env)
            sub[var] = b
            if not _eval(body, world, blocks, name_index, preds, sub):
                return False
        return True
    if kind == 'exists':
        _, var, body = node
        for b in blocks:
            sub = dict(env)
            sub[var] = b
            if _eval(body, world, blocks, name_index, preds, sub):
                return True
        return False
    raise EvalError(f'bad AST node kind {kind!r}')


# ── convenience: parse_and_eval ─────────────────────────────────────


def parse_and_eval(src: str, world, blocks=None):
    """Return ``(ok, value_or_error, ast_or_none)``.

    ``ok`` is True if both parse and evaluation succeeded; ``value_or_error``
    is the bool result on success, else a human-readable string.
    """
    try:
        ast = parse(src)
    except (ParseError, ValueError) as e:
        return (False, f'parse error: {e}', None)
    try:
        v = evaluate(ast, world, blocks=blocks)
    except EvalError as e:
        return (False, f'eval error: {e}', ast)
    return (True, v, ast)
