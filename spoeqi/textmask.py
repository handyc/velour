"""Text-through-CA-mask.

Take a user's text, tile it across a hex-CA component's cell grid,
look up each cell's 4-state colour, and route the character through
one of four functions in a named *mapping table*.  The CA acts as a
deterministic-but-evolving attention stencil over the input.

The output of this module is a ``MaskResult`` carrying:

- the row-major ``cells`` (list of {char, color, out, idx}) so a
  template can paint a tinted grid with the character glyph inside
  each cell, and
- the assembled ``output_text`` for callers that want the flat
  transformed string.

Mapping tables are registered by name; new ones can be added by
appending to ``MAPPING_TABLES`` or calling ``register()``.  Each
table is a 4-tuple of callables ``f(ch) -> str``; the returned string
*may* differ in length from the input character (e.g. drop → '',
double → 'aa') — the grid renderer truncates per-cell output back
to one glyph for display while ``output_text`` preserves every
returned byte.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

from .models import Pact, COMPONENTS
from . import keystream


# A mapping table is exactly 4 functions, indexed by the cell's CA
# colour 0..3.  Each function maps one input char to a (possibly
# differently-sized) output string.
MappingFunc  = Callable[[str], str]
MappingTable = Tuple[MappingFunc, MappingFunc, MappingFunc, MappingFunc]


def _identity(ch: str) -> str: return ch
def _drop(_ch: str) -> str:    return ''
def _mask(_ch: str) -> str:    return '·'
def _upper(ch: str) -> str:    return ch.upper()
def _lower(ch: str) -> str:    return ch.lower()
def _rot13(ch: str) -> str:
    if 'a' <= ch <= 'z':
        return chr((ord(ch) - 97 + 13) % 26 + 97)
    if 'A' <= ch <= 'Z':
        return chr((ord(ch) - 65 + 13) % 26 + 65)
    return ch
def _double(ch: str) -> str:   return ch + ch
def _space(_ch: str) -> str:   return ' '

_VOWELS = set('aeiouAEIOU')
def _drop_vowels(ch: str) -> str: return '' if ch in _VOWELS else ch
def _keep_vowels(ch: str) -> str: return ch if ch in _VOWELS else ''


# ─── Registry ──────────────────────────────────────────────────────
# Each table is the 4 functions plus a short description.  Order in
# the dict is preserved (Python 3.7+) so dropdowns pick this up.

@dataclass(frozen=True)
class _Mapping:
    name:        str
    description: str
    table:       MappingTable
    # Per-colour glyph labels for the UI legend (what the function
    # *does*, not what it outputs).
    labels:      Tuple[str, str, str, str]


MAPPING_TABLES: Dict[str, _Mapping] = {}


def register(name: str, *, description: str,
             table: MappingTable, labels: Tuple[str, str, str, str]) -> None:
    """Register a new mapping table.  Names are case-sensitive and
    must be unique."""
    if name in MAPPING_TABLES:
        raise ValueError(f'mapping {name!r} already registered')
    MAPPING_TABLES[name] = _Mapping(name=name, description=description,
                                    table=table, labels=labels)


# Starter mappings — the four attention-analogous moves the user
# asked for, plus a couple of useful variants.

register('attention',
    description='attend / mask / amplify / dampen — the canonical four-head set',
    table=(_identity, _mask, _upper, _lower),
    labels=('pass',   'mask', 'UPPER', 'lower'))

register('drop',
    description='pass / drop / upper / lower — like attention but mask drops the cell entirely',
    table=(_identity, _drop, _upper, _lower),
    labels=('pass',   '∅',    'UPPER', 'lower'))

register('cipher',
    description='pass / rot13 / upper / drop — a tiny stream cipher driven by the CA',
    table=(_identity, _rot13, _upper, _drop),
    labels=('pass',   'rot13', 'UPPER', '∅'))

register('vowels',
    description='pass / drop-vowels / keep-vowels / mask — partitions text by phonemic class',
    table=(_identity, _drop_vowels, _keep_vowels, _mask),
    labels=('pass',   '−vow',         '+vow',         'mask'))

register('emphasis',
    description='lower / pass / upper / double — four ramping levels of "loudness"',
    table=(_lower, _identity, _upper, _double),
    labels=('lower', 'pass',   'UPPER', 'xx'))


# ─── Token-mode registry ────────────────────────────────────────────
# Token-level mappings: each function takes a token, returns a token
# (or '' to drop).  Lifted into a separate dict so the char-mode
# registry stays one-glyph-in / one-glyph-out for the live JS engine.

from . import tokens as _tokens

# Primitives that have a JS mirror in the live engine.  Tables built
# from only these primitives can run live on the client without a
# server round-trip per CA tick.  POS / lemma need spaCy and so a
# table that uses them is flagged ``live_capable=False`` and the JS
# engine skips its boot.
_CLIENT_FEASIBLE_PRIMITIVES = frozenset({
    'pass', 'drop', 'lower', 'upper', 'mask', 'sentinel',
    'stopdrop', 'stopkeep', 'stem', 'soundex', 'metaphone',
})


@dataclass(frozen=True)
class _TokenMapping:
    name:           str
    description:    str
    table:          tuple   # 4 callables (str -> str)
    primitives:     tuple   # 4 primitive *names* (used by the JS engine)
    labels:         tuple   # 4 short ui labels
    live_capable:   bool    # all 4 primitives have JS mirrors?


TOKEN_MAPPING_TABLES: Dict[str, _TokenMapping] = {}


def register_token(name: str, *, description: str,
                   primitives: tuple, labels: tuple) -> None:
    if name in TOKEN_MAPPING_TABLES:
        raise ValueError(f'token mapping {name!r} already registered')
    if len(primitives) != 4 or len(labels) != 4:
        raise ValueError('token mapping needs exactly 4 primitives and 4 labels')
    for p in primitives:
        if p not in _tokens.PRIMITIVES:
            raise ValueError(f'unknown primitive {p!r}; '
                              f'register it in tokens.PRIMITIVES first')
    table = tuple(_tokens.PRIMITIVES[p] for p in primitives)
    live_capable = all(p in _CLIENT_FEASIBLE_PRIMITIVES for p in primitives)
    TOKEN_MAPPING_TABLES[name] = _TokenMapping(
        name=name, description=description,
        table=table, primitives=tuple(primitives),
        labels=tuple(labels), live_capable=live_capable)


register_token('bert-mlm',
    description='BERT pretraining: ~15 % of tokens become [MASK]; rest pass',
    primitives=('pass', 'mask', 'pass', 'pass'),
    labels=('pass', '[MASK]', 'pass', 'pass'))

register_token('denoise',
    description='IR-style: pass / drop stopwords / Porter stem / lowercase',
    primitives=('pass', 'stopdrop', 'stem', 'lower'),
    labels=('pass', '−stop', 'stem', 'lower'))

register_token('phonetic',
    description='pass / Soundex / Metaphone / mask — dialect-tolerant fingerprints',
    primitives=('pass', 'soundex', 'metaphone', 'mask'),
    labels=('pass', 'soundex', 'meta', 'mask'))

register_token('t5-noise',
    description='T5 span-corruption analogue: 1/4 tokens become a sentinel',
    primitives=('pass', 'sentinel', 'pass', 'pass'),
    labels=('pass', '<extra_id>', 'pass', 'pass'))

register_token('pos-distill',
    description='Server-only (spaCy): pass / POS tag / lemma / stem — live disabled',
    primitives=('pass', 'pos', 'lemma', 'stem'),
    labels=('pass', 'POS', 'lemma', 'stem'))


# ─── Tiling ─────────────────────────────────────────────────────────

def tile_text(text: str, side: int) -> List[str]:
    """Tile ``text`` into a flat ``side²``-element list of single
    characters, row-major.  Empty input → list of spaces."""
    n = side * side
    if not text:
        return [' '] * n
    out = []
    i = 0
    L = len(text)
    while len(out) < n:
        out.append(text[i % L])
        i += 1
    return out


# ─── Apply ──────────────────────────────────────────────────────────

@dataclass
class Cell:
    idx:   int   # 0..side²-1, row-major
    row:   int
    col:   int
    char:  str   # input glyph at this cell
    color: int   # 0..3 from the CA
    out:   str   # mapping_table[color](char)


@dataclass
class MaskResult:
    side:         int
    component:    int
    generation:   int
    mapping:      str
    cells:        List[Cell]
    output_text:  str   # all `out` strings concatenated, row-major


def apply(pact: Pact, *, text: str, component: int, generation: int,
          mapping: str) -> MaskResult:
    """Run the text-through-CA-mask transform.  Tile ``text`` to fill
    one component's ``side × side`` grid at the requested generation,
    look each cell up in the chosen mapping table, return the cells
    + the flattened output string.
    """
    if mapping not in MAPPING_TABLES:
        raise ValueError(f'unknown mapping {mapping!r}')
    if not (0 <= component < 64):
        raise ValueError(f'component must be 0..63, got {component}')
    if generation < 0:
        raise ValueError(f'generation must be ≥ 0')

    side = pact.component_grid
    state = keystream.get_state_at(pact, generation)
    area  = side * side
    base  = component * area
    grid  = state[base:base + area]

    glyphs = tile_text(text, side)
    table  = MAPPING_TABLES[mapping].table

    cells: List[Cell] = []
    chunks: List[str] = []
    for idx in range(area):
        color = grid[idx]
        ch    = glyphs[idx]
        out   = table[color](ch)
        cells.append(Cell(idx=idx, row=idx // side, col=idx % side,
                          char=ch, color=color, out=out))
        chunks.append(out)

    return MaskResult(side=side, component=component,
                      generation=generation, mapping=mapping,
                      cells=cells, output_text=''.join(chunks))


def apply_all(pact: Pact, *, text: str, generation: int,
              mapping: str) -> List[MaskResult]:
    """Apply the mask through every one of the 64 components at the
    same generation.  One CA state read, 64 slices — same cost as a
    single ``apply()`` call plus 64 cheap loops.  Returns a list of
    ``MaskResult`` indexed by component (0..63), good for line-by-line
    comparison in the UI.

    Components share the (text, generation, mapping); only the
    colour pattern differs.  That's the experiment: "what does the
    same input look like, masked by 64 different evolving stencils?"
    """
    if mapping not in MAPPING_TABLES:
        raise ValueError(f'unknown mapping {mapping!r}')
    if generation < 0:
        raise ValueError('generation must be ≥ 0')

    side = pact.component_grid
    state = keystream.get_state_at(pact, generation)
    area = side * side
    glyphs = tile_text(text, side)
    table  = MAPPING_TABLES[mapping].table

    results: List[MaskResult] = []
    for c in range(COMPONENTS):
        base = c * area
        grid = state[base:base + area]
        cells: List[Cell] = []
        chunks: List[str] = []
        for idx in range(area):
            color = grid[idx]
            ch    = glyphs[idx]
            out   = table[color](ch)
            cells.append(Cell(idx=idx, row=idx // side, col=idx % side,
                              char=ch, color=color, out=out))
            chunks.append(out)
        results.append(MaskResult(side=side, component=c,
                                   generation=generation, mapping=mapping,
                                   cells=cells,
                                   output_text=''.join(chunks)))
    return results


# ─── Token mode ────────────────────────────────────────────────────
# Same grid, but each cell holds an entire token (or '') instead of
# a single character.  Token-mode tables operate on whole tokens so
# we can do real preprocessing: stop-word removal, Porter stemming,
# Soundex / Metaphone, POS / lemma, BERT-style MLM masking.

def tile_tokens(text: str, side: int) -> List[str]:
    """Tile the *tokens* of ``text`` (regex word-tokenizer) into the
    ``side × side`` grid in row-major order, wrapping if the token
    count is less than the cell count.  Empty input → list of empty
    strings."""
    n = side * side
    toks = _tokens.tokenize(text or '')
    if not toks:
        return [''] * n
    out = []
    L = len(toks)
    for i in range(n):
        out.append(toks[i % L])
    return out


@dataclass
class TokenCell:
    idx:   int
    row:   int
    col:   int
    token: str   # the token tiled into this cell
    color: int   # CA colour 0..3
    out:   str   # token after the chosen primitive


@dataclass
class TokenMaskResult:
    side:         int
    component:    int
    generation:   int
    mapping:      str
    cells:        List[TokenCell]
    output_text:  str   # space-joined non-empty outputs


def _token_apply_grid(glyphs: List[str], grid: bytes, side: int,
                       component: int, generation: int, mapping_name: str,
                       table: tuple) -> TokenMaskResult:
    area = side * side
    cells: List[TokenCell] = []
    chunks: List[str] = []
    for idx in range(area):
        color = grid[idx]
        tok   = glyphs[idx]
        out   = table[color](tok) if tok else ''
        cells.append(TokenCell(idx=idx, row=idx // side, col=idx % side,
                                token=tok, color=color, out=out))
        if out: chunks.append(out)
    return TokenMaskResult(side=side, component=component,
                            generation=generation, mapping=mapping_name,
                            cells=cells, output_text=' '.join(chunks))


def apply_tokens(pact: Pact, *, text: str, component: int, generation: int,
                  mapping: str) -> TokenMaskResult:
    """Token-mode mask: tile tokens into one component's grid, apply
    the per-colour token primitive, return cells + space-joined output."""
    if mapping not in TOKEN_MAPPING_TABLES:
        raise ValueError(f'unknown token mapping {mapping!r}')
    if not (0 <= component < 64):
        raise ValueError(f'component must be 0..63, got {component}')
    if generation < 0:
        raise ValueError('generation must be ≥ 0')

    side = pact.component_grid
    state = keystream.get_state_at(pact, generation)
    area = side * side
    base = component * area
    grid = state[base:base + area]
    glyphs = tile_tokens(text, side)
    table = TOKEN_MAPPING_TABLES[mapping].table
    return _token_apply_grid(glyphs, grid, side, component, generation,
                              mapping, table)


def apply_tokens_all(pact: Pact, *, text: str, generation: int,
                     mapping: str) -> List[TokenMaskResult]:
    """Token-mode mask across all 64 components — same input, 64
    stencils.  Same shape as ``apply_all`` but with tokens."""
    if mapping not in TOKEN_MAPPING_TABLES:
        raise ValueError(f'unknown token mapping {mapping!r}')
    if generation < 0:
        raise ValueError('generation must be ≥ 0')

    side = pact.component_grid
    state = keystream.get_state_at(pact, generation)
    area = side * side
    glyphs = tile_tokens(text, side)
    table = TOKEN_MAPPING_TABLES[mapping].table
    out: List[TokenMaskResult] = []
    for c in range(COMPONENTS):
        base = c * area
        grid = state[base:base + area]
        out.append(_token_apply_grid(glyphs, grid, side, c, generation,
                                      mapping, table))
    return out


# ─── Attention mode ────────────────────────────────────────────────
# The component's side×side cell grid IS the attention matrix:
# rows = query positions (tokens), cols = key positions (tokens).
# Each cell's CA colour selects an attention-pattern primitive that
# decides the cell's weight given (row, col).  Output is the matrix
# of float weights — ready to multiply against attention logits.

# An attention primitive: float fn(row, col, color, side) -> float.
# Returns the *weight contribution* for that cell.

@dataclass(frozen=True)
class _AttentionMapping:
    name:        str
    description: str
    # 4 primitives, one per colour 0..3.  Each is f(row, col, side) -> float.
    table:       tuple
    labels:      tuple


ATTENTION_TABLES: Dict[str, _AttentionMapping] = {}


def register_attention(name: str, *, description: str,
                       table: tuple, labels: tuple) -> None:
    if name in ATTENTION_TABLES:
        raise ValueError(f'attention mapping {name!r} already registered')
    if len(table) != 4 or len(labels) != 4:
        raise ValueError('attention mapping needs 4 functions + 4 labels')
    ATTENTION_TABLES[name] = _AttentionMapping(
        name=name, description=description,
        table=tuple(table), labels=tuple(labels))


# Primitives.  All take (row, col, side) and return a weight 0..1.

def _att_attend(_r, _c, _s):  return 1.0
def _att_mask  (_r, _c, _s):  return 0.0
def _att_causal(r, c, _s):    return 1.0 if c <= r else 0.0
def _att_anti_causal(r, c, _s): return 1.0 if c >= r else 0.0
def _att_diag  (r, c, _s):    return 1.0 if r == c else 0.0
def _att_neighbours(r, c, s):
    """Sliding window: attend within ±2 along the diagonal."""
    return 1.0 if abs(r - c) <= 2 else 0.0
def _att_global_row(_r, c, _s):
    """A single column attends to everything (column 0 = [CLS])."""
    return 1.0 if c == 0 else 0.0
def _att_random_keep(r, c, s):
    """Sparse: keep ~10 % of cells, deterministically via (r,c)."""
    return 1.0 if ((r * 31 + c) * 17) % 10 == 0 else 0.0
def _att_weak(_r, _c, _s):   return 0.3
def _att_strong(_r, _c, _s): return 1.5
def _att_negative(_r, _c, _s): return -1.0    # attention-bias style


register_attention('causal',
    description='GPT-style causal: 0=attend / 1=mask / 2=causal-only / 3=mask — texture-by-CA',
    table=(_att_attend, _att_mask, _att_causal, _att_mask),
    labels=('attend', 'mask', 'causal', 'mask'))

register_attention('bert',
    description='Bidirectional: 0/1=attend, 2/3=mask — fully visible but CA picks cells',
    table=(_att_attend, _att_attend, _att_mask, _att_mask),
    labels=('attend', 'attend', 'mask', 'mask'))

register_attention('window',
    description='Longformer sliding window + global col 0: 0=window / 1=global col / 2=mask / 3=window',
    table=(_att_neighbours, _att_global_row, _att_mask, _att_neighbours),
    labels=('window', 'global₀', 'mask', 'window'))

register_attention('sparse',
    description='BigBird-style sparse: 0=attend / 1=random 10% / 2=causal / 3=mask',
    table=(_att_attend, _att_random_keep, _att_causal, _att_mask),
    labels=('attend', 'rnd10%', 'causal', 'mask'))

register_attention('weights',
    description='4 colours → 4 weights: (1.0, 0.0, +0.3, +1.5) — ready to multiply into logits',
    table=(_att_attend, _att_mask, _att_weak, _att_strong),
    labels=('×1.0', '×0.0', '×0.3', '×1.5'))

register_attention('biased',
    description='Like weights, but colour 3 emits a NEGATIVE bias (attention suppression)',
    table=(_att_attend, _att_mask, _att_strong, _att_negative),
    labels=('×1.0', '×0.0', '×1.5', '×−1'))


@dataclass
class AttentionCell:
    idx:   int
    row:   int
    col:   int
    color: int
    weight: float


@dataclass
class AttentionResult:
    side:       int
    component:  int
    generation: int
    mapping:    str
    cells:      List[AttentionCell]
    # Convenience: row-major flat list of weights for JSON export.
    matrix:     List[List[float]]


def apply_attention(pact: Pact, *, component: int, generation: int,
                    mapping: str) -> AttentionResult:
    """Build the attention matrix for one component at one generation.
    The grid IS the attention matrix; we don't tile any text — the
    output is a (side × side) float matrix the caller can pipe into
    a real attention layer."""
    if mapping not in ATTENTION_TABLES:
        raise ValueError(f'unknown attention mapping {mapping!r}')
    if not (0 <= component < 64):
        raise ValueError(f'component must be 0..63, got {component}')
    if generation < 0:
        raise ValueError('generation must be ≥ 0')

    side = pact.component_grid
    state = keystream.get_state_at(pact, generation)
    area = side * side
    base = component * area
    grid = state[base:base + area]
    table = ATTENTION_TABLES[mapping].table

    cells: List[AttentionCell] = []
    matrix: List[List[float]] = [[0.0] * side for _ in range(side)]
    for idx in range(area):
        r, c = idx // side, idx % side
        color = grid[idx]
        w = float(table[color](r, c, side))
        matrix[r][c] = w
        cells.append(AttentionCell(idx=idx, row=r, col=c,
                                    color=color, weight=w))
    return AttentionResult(side=side, component=component,
                            generation=generation, mapping=mapping,
                            cells=cells, matrix=matrix)


# ─── Chain ─────────────────────────────────────────────────────────
# Sequential pipeline of textmask stages: stage K's output_text
# becomes stage K+1's input_text.  Only char + token modes can sit
# in the middle of a chain — attention produces a matrix, not text,
# so it can only appear as a leaf (we don't support that yet either,
# since attention-as-leaf is best handled by the next phase: actually
# wiring the matrix into LoRA inference).

@dataclass(frozen=True)
class ChainStage:
    mode:       str       # 'char' or 'token'
    mapping:    str
    component:  int
    generation: int


@dataclass
class ChainStageResult:
    stage:       int      # 0-based position in the chain
    mode:        str
    mapping:     str
    component:   int
    generation:  int
    input_text:  str
    output_text: str
    # The cell breakdown is optional — for char mode it's the same
    # shape as MaskResult.cells; for token mode TokenMaskResult.cells.
    # Stored as raw dicts so the template doesn't have to branch on
    # dataclass type.
    cells:       List[dict]


def apply_chain(pact: Pact, stages: List[ChainStage], text: str
                ) -> List[ChainStageResult]:
    """Apply each stage in order; the output_text of stage K becomes
    the input_text of stage K+1.  Returns one ChainStageResult per
    stage.  Raises ValueError on invalid stages."""
    out: List[ChainStageResult] = []
    current = text
    for i, st in enumerate(stages):
        if st.mode == 'char':
            r = apply(pact, text=current, component=st.component,
                       generation=st.generation, mapping=st.mapping)
            cells = [{'char':  c.char, 'color': c.color, 'out': c.out,
                       'row':   c.row,  'col':   c.col}
                      for c in r.cells]
            out.append(ChainStageResult(
                stage=i, mode='char', mapping=st.mapping,
                component=st.component, generation=st.generation,
                input_text=current, output_text=r.output_text,
                cells=cells))
            current = r.output_text
        elif st.mode == 'token':
            r = apply_tokens(pact, text=current, component=st.component,
                              generation=st.generation, mapping=st.mapping)
            cells = [{'token': c.token, 'color': c.color, 'out': c.out,
                       'row':   c.row,   'col':   c.col}
                      for c in r.cells]
            out.append(ChainStageResult(
                stage=i, mode='token', mapping=st.mapping,
                component=st.component, generation=st.generation,
                input_text=current, output_text=r.output_text,
                cells=cells))
            current = r.output_text
        else:
            raise ValueError(
                f'chain stage {i}: mode {st.mode!r} not allowed in a '
                f'chain (only char + token transform text → text). '
                f'Attention mode produces a matrix and is a leaf op.')
    return out


def apply_attention_all(pact: Pact, *, generation: int,
                         mapping: str) -> List[AttentionResult]:
    """Attention matrices for all 64 components at the same generation."""
    if mapping not in ATTENTION_TABLES:
        raise ValueError(f'unknown attention mapping {mapping!r}')
    if generation < 0:
        raise ValueError('generation must be ≥ 0')

    side = pact.component_grid
    state = keystream.get_state_at(pact, generation)
    area = side * side
    table = ATTENTION_TABLES[mapping].table
    out: List[AttentionResult] = []
    for cnum in range(COMPONENTS):
        base = cnum * area
        grid = state[base:base + area]
        cells: List[AttentionCell] = []
        matrix = [[0.0] * side for _ in range(side)]
        for idx in range(area):
            r, c = idx // side, idx % side
            color = grid[idx]
            w = float(table[color](r, c, side))
            matrix[r][c] = w
            cells.append(AttentionCell(idx=idx, row=r, col=c,
                                        color=color, weight=w))
        out.append(AttentionResult(side=side, component=cnum,
                                    generation=generation, mapping=mapping,
                                    cells=cells, matrix=matrix))
    return out
