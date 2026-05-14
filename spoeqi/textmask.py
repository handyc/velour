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
