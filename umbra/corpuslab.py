"""Linguistic CSV → Concrete TFHE round-trip pipeline.

Where csvlab.py does CKKS arithmetic on numeric cells, this module does
TFHE programmable-bootstrapping (PBS) on the *codepoints* of every
cell.  The point: humanities/linguistic research at Leiden works with
CSVs where each cell holds one linguistic form (a word, a morpheme, a
gloss) in a low-resource language.  This pipeline lets researchers
send those forms through a sealed pipeline and perform per-cell
character-level analyses without the operating party seeing the bytes.

Same threat model as csvlab.py: key, encrypt, ops, decrypt all happen
in one Django request.  Demonstration of the sealed shape, not a
privacy boundary.  A two-process split lands later.

Codepoint encoding: each cell is encoded as a fixed-length sequence of
alphabet *indices*, not raw bytes.  A LanguageProfile owns the mapping
from Unicode codepoint to alphabet index and the class-of-index LUT.
This is what lets the same pipeline classify Hindi (Devanagari) and
ASCII (Latin) without growing the LUT to 65 536+ entries — we keep
alphabet size at 128 (7-bit PBS) by curating per-language alphabets.

Wire shape: a CorpusLabSession stores the raw CSV plus a JSON queue of
per-cell ops and the active language profile.  run_session() picks the
profile, pads every non-empty cell to a common length, encodes each
char as an alphabet index, compiles one Concrete circuit per op-kind,
runs the circuit on the padded index tensor, and decodes the output
back into a CSV grid.

Ops queue is a list of dicts; coordinates are 0-indexed.

  {"op": "char_class_map", "col": C}
      -> for every row, replace cell at column C with a string where
         each character has been mapped to its class digit.

  {"op": "count_class", "col": C, "target": 1, "dst_col": null}
      -> for every row, count chars in cell[col] whose class matches
         target.  If dst_col is null the count overwrites the source
         cell; otherwise it's written to that column.

  {"op": "length", "col": C, "dst_col": null}
      -> count non-padding alphabet indices per cell.
"""
import csv
import io
import json
import time

import numpy as np
from concrete import fhe


# ── Op identifiers ──────────────────────────────────────────────────

OP_CHAR_CLASS_MAP = 'char_class_map'
OP_COUNT_CLASS    = 'count_class'
OP_LENGTH         = 'length'

OP_CHOICES = [
    (OP_CHAR_CLASS_MAP, 'replace each char with its class digit'),
    (OP_COUNT_CLASS,    'count chars matching a target class'),
    (OP_LENGTH,         'cell length (non-padding chars)'),
]


# ── Class digits (unified across profiles where possible) ──────────
# CLASS_HALANT is Devanagari-specific (the virama); ASCII collapses
# it into CLASS_OTHER.  Researchers wanting a sharper breakdown can
# add follow-up ops (match_codepoint, transliterate) without changing
# this digit space.

CLASS_OTHER     = 0
CLASS_VOWEL     = 1
CLASS_CONSONANT = 2
CLASS_DIGIT     = 3
CLASS_PUNCT     = 4
CLASS_HALANT    = 5

# ── Per-circuit caps ────────────────────────────────────────────────
# Concrete PBS at 7-bit alphabet → ~200 ms per encrypted index on this
# machine.  At 8 cells × 8 chars = 64 ops, a single run finishes in
# ~13 s, comfortably under the runner's 60 s wall.  ALICE-scale work
# uses a Slurm-array follow-up (`manage.py corpuslab_run`).

MAX_CELLS    = 8
MAX_CELL_LEN = 8
ALPHABET_SIZE = 128       # PBS bit width = 7
PAD_INDEX     = 0         # padding sentinel: classified as CLASS_OTHER


# ── Language profiles ───────────────────────────────────────────────

class LanguageProfile:
    """Maps Unicode codepoints to a small (alphabet_size) index space
    that fits comfortably under TFHE PBS.  Each profile owns:
      • a codepoint→index encoder + index→codepoint decoder
      • a class LUT (np.ndarray of length alphabet_size)
      • a list of (class_id, human_label) pairs for UI choices
    Profiles are stateless singletons constructed at import."""

    slug:  str = ''
    name:  str = ''
    description: str = ''
    alphabet_size: int = ALPHABET_SIZE
    pad_index: int = PAD_INDEX

    def encode_char(self, ch: str) -> int:
        """Return alphabet index for `ch`, or some non-pad index whose
        class is CLASS_OTHER for codepoints outside this profile's
        alphabet.  Empty / null input maps to pad_index."""
        raise NotImplementedError

    def decode_index(self, idx: int) -> str:
        """Inverse of encode_char.  Returns '' for the pad index."""
        raise NotImplementedError

    def class_for_index(self, idx: int) -> int:
        """Class digit for an alphabet index."""
        raise NotImplementedError

    def class_lut(self) -> np.ndarray:
        return np.array([self.class_for_index(i)
                         for i in range(self.alphabet_size)],
                        dtype=np.int64)

    def indicator_lut(self, target_class: int) -> np.ndarray:
        return np.array([1 if self.class_for_index(i) == target_class else 0
                         for i in range(self.alphabet_size)],
                        dtype=np.int64)

    def nonpad_lut(self) -> np.ndarray:
        return np.array([0 if i == self.pad_index else 1
                         for i in range(self.alphabet_size)],
                        dtype=np.int64)

    def class_choices(self):
        """UI labels.  Default lineup; profiles may override to hide
        or rename classes (e.g. ASCII hides halant)."""
        return [
            (CLASS_VOWEL,     'vowel'),
            (CLASS_CONSONANT, 'consonant'),
            (CLASS_DIGIT,     'digit'),
            (CLASS_PUNCT,     'punctuation/space'),
            (CLASS_OTHER,     'other / non-alphabet'),
        ]


# ── ASCII (Latin) profile ───────────────────────────────────────────

_ASCII_VOWELS = set(ord(c) for c in 'aeiouAEIOU')
_ASCII_PUNCT  = set(map(ord, ' !"\',.:;?\t-—'))


class _AsciiProfile(LanguageProfile):
    slug = 'ascii'
    name = 'ASCII (Latin)'
    description = (
        'Plain 7-bit ASCII.  Codepoints map to their byte values; '
        'index 0 is the padding sentinel.  English, romanised Konso, '
        'romanised Hindi/Sanskrit transliterations all fit here.'
    )

    def encode_char(self, ch: str) -> int:
        if not ch:
            return self.pad_index
        cp = ord(ch[0])
        # Bytes 1..127 round-trip cleanly; the pad sentinel and anything
        # outside ASCII collapse onto index 0 (OTHER).
        return cp if 0 < cp < 128 else self.pad_index

    def decode_index(self, idx: int) -> str:
        return chr(idx) if 0 < idx < 128 else ''

    def class_for_index(self, idx: int) -> int:
        if idx == self.pad_index:                          return CLASS_OTHER
        if idx in _ASCII_VOWELS:                           return CLASS_VOWEL
        if (97 <= idx <= 122) or (65 <= idx <= 90):        return CLASS_CONSONANT
        if 48 <= idx <= 57:                                return CLASS_DIGIT
        if idx in _ASCII_PUNCT:                            return CLASS_PUNCT
        return CLASS_OTHER


# ── Devanagari (Hindi + most Sanskrit) profile ──────────────────────
#
# Index layout:
#   0       = padding sentinel (class OTHER)
#   1..126  = U+0900 + (i - 1)   i.e. covers U+0900..U+097D
#   127     = "unknown" catch-all (class OTHER)
#
# This loses U+097E (extended ext.) but no common Hindi/Sanskrit text
# uses it.  We pay a 1-codepoint precision cost to keep alphabet_size
# at exactly 128 so PBS stays 7-bit.

_DEVA_OFFSET = 0x0900

# Independent vowels in Devanagari: U+0904 to U+0914, plus extra
# vowels at U+0960..U+0963.  We classify these AND their matras
# (vowel signs) as CLASS_VOWEL since both represent vowel sounds —
# linguistically what researchers usually want to count.  Researchers
# who need to distinguish can use the OTHER class breakdown later.
_DEVA_VOWELS_INDEP = set(range(0x0904, 0x0915)) | set(range(0x0960, 0x0964))
_DEVA_VOWEL_SIGNS  = (set(range(0x093A, 0x094D))      # matras + ai/au signs
                      | set(range(0x0955, 0x0958)))   # uue + rri signs
# Consonants: U+0915..U+0939 (main row) and U+0958..U+095F (nukta extras).
_DEVA_CONSONANTS   = set(range(0x0915, 0x093A)) | set(range(0x0958, 0x0960))
# Halant (virama) kills the inherent 'a' on the preceding consonant.
_DEVA_HALANT       = {0x094D}
# Digits.
_DEVA_DIGITS       = set(range(0x0966, 0x0970))
# Punctuation: danda + double danda, plus a few signs commonly used.
_DEVA_PUNCT        = {0x0964, 0x0965}


def _deva_class_of_codepoint(cp: int) -> int:
    if cp in _DEVA_VOWELS_INDEP:                       return CLASS_VOWEL
    if cp in _DEVA_VOWEL_SIGNS:                        return CLASS_VOWEL
    if cp in _DEVA_CONSONANTS:                         return CLASS_CONSONANT
    if cp in _DEVA_HALANT:                             return CLASS_HALANT
    if cp in _DEVA_DIGITS:                             return CLASS_DIGIT
    if cp in _DEVA_PUNCT:                              return CLASS_PUNCT
    return CLASS_OTHER


class _DevanagariProfile(LanguageProfile):
    slug = 'devanagari'
    name = 'Devanagari (Hindi / Sanskrit)'
    description = (
        'Unicode block U+0900-U+097D.  Independent vowels and matras '
        'both classify as vowels; halant (virama) gets its own class; '
        'consonants, digits and dandas as usual.  Codepoints outside '
        'the Devanagari block collapse to the unknown index (class '
        'OTHER).'
    )

    _UNKNOWN_INDEX = 127

    def encode_char(self, ch: str) -> int:
        if not ch:
            return self.pad_index
        cp = ord(ch[0])
        if _DEVA_OFFSET <= cp <= _DEVA_OFFSET + 125:
            return (cp - _DEVA_OFFSET) + 1   # offset to leave index 0 for pad
        return self._UNKNOWN_INDEX

    def decode_index(self, idx: int) -> str:
        if idx == self.pad_index or idx == self._UNKNOWN_INDEX:
            return ''
        return chr(_DEVA_OFFSET + idx - 1)

    def class_for_index(self, idx: int) -> int:
        if idx == self.pad_index:        return CLASS_OTHER
        if idx == self._UNKNOWN_INDEX:   return CLASS_OTHER
        return _deva_class_of_codepoint(_DEVA_OFFSET + idx - 1)

    def class_choices(self):
        return [
            (CLASS_VOWEL,     'vowel (independent + matra)'),
            (CLASS_CONSONANT, 'consonant'),
            (CLASS_HALANT,    'halant / virama'),
            (CLASS_DIGIT,     'digit'),
            (CLASS_PUNCT,     'punctuation (danda)'),
            (CLASS_OTHER,     'other / non-Devanagari'),
        ]


# ── Profile registry ────────────────────────────────────────────────

PROFILES = {
    'ascii':       _AsciiProfile(),
    'devanagari':  _DevanagariProfile(),
}
DEFAULT_PROFILE = 'ascii'


def get_profile(slug: str) -> LanguageProfile:
    return PROFILES.get(slug or DEFAULT_PROFILE) or PROFILES[DEFAULT_PROFILE]


def profile_choices():
    return [(p.slug, p.name) for p in PROFILES.values()]


# Back-compat alias for the existing view import path.  Drops once the
# profile-aware op form lands.
CLASS_CHOICES = _AsciiProfile().class_choices()


# ── CSV plumbing (profile-independent) ──────────────────────────────

def parse_csv(text: str):
    reader = csv.reader(io.StringIO(text))
    grid   = [list(row) for row in reader]
    rows   = len(grid)
    cols   = max((len(r) for r in grid), default=0)
    for r in grid:
        while len(r) < cols:
            r.append('')
    return grid, rows, cols


def emit_csv(grid) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    for row in grid:
        w.writerow(row)
    return buf.getvalue()


def count_nonempty(grid) -> int:
    return sum(1 for row in grid for cell in row if cell.strip())


def _select_cells(grid, col: int):
    """Pick (row_index, cell_text) for the target column, up to
    MAX_CELLS, skipping empty cells and the header row (row 0)."""
    sel = []
    for r in range(1, len(grid)):
        if col >= len(grid[r]):
            continue
        cell = grid[r][col]
        if not cell.strip():
            continue
        sel.append((r, cell))
        if len(sel) >= MAX_CELLS:
            break
    return sel


def _encode_cell(profile: LanguageProfile, text: str, length: int) -> np.ndarray:
    """Encode `text` as a fixed-length array of alphabet indices,
    padded with `profile.pad_index`."""
    out = np.full(length, profile.pad_index, dtype=np.int64)
    for i, ch in enumerate(text[:length]):
        out[i] = profile.encode_char(ch)
    return out


def _decode_class_cell(arr) -> str:
    """Render a row of class digits as a compact string, dropping the
    trailing OTHER (class 0) padding."""
    s = ''.join(str(int(x)) for x in arr)
    return s.rstrip('0')


def _pad_to_max(profile: LanguageProfile, sel, cell_len: int) -> np.ndarray:
    """Stack the selected cells as a (MAX_CELLS, cell_len) int64 array,
    padding the selection itself to MAX_CELLS with pad-only rows so
    one fixed-shape circuit covers every run."""
    arr = np.full((MAX_CELLS, cell_len), profile.pad_index, dtype=np.int64)
    for i, (_, text) in enumerate(sel):
        arr[i] = _encode_cell(profile, text, cell_len)
    return arr


# ── Circuit builders (one per op-kind, profile-driven LUT) ─────────

def _inputset(cell_len: int, alphabet_size: int):
    return [
        np.random.randint(0, alphabet_size,
                          size=(MAX_CELLS, cell_len),
                          dtype=np.int64)
        for _ in range(8)
    ]


def _build_class_map_circuit(profile: LanguageProfile, cell_len: int):
    table = fhe.LookupTable(profile.class_lut().tolist())

    @fhe.compiler({'cells': 'encrypted'})
    def circuit(cells):
        return table[cells]

    return circuit.compile(_inputset(cell_len, profile.alphabet_size))


def _build_count_class_circuit(profile: LanguageProfile, cell_len: int,
                               target: int):
    table = fhe.LookupTable(profile.indicator_lut(target).tolist())

    @fhe.compiler({'cells': 'encrypted'})
    def circuit(cells):
        return np.sum(table[cells], axis=1)

    return circuit.compile(_inputset(cell_len, profile.alphabet_size))


def _build_length_circuit(profile: LanguageProfile, cell_len: int):
    table = fhe.LookupTable(profile.nonpad_lut().tolist())

    @fhe.compiler({'cells': 'encrypted'})
    def circuit(cells):
        return np.sum(table[cells], axis=1)

    return circuit.compile(_inputset(cell_len, profile.alphabet_size))


# ── Op implementations ─────────────────────────────────────────────

def _apply_char_class_map(profile, grid, op, timing):
    col = int(op['col'])
    sel = _select_cells(grid, col)
    if not sel:
        raise ValueError(f'no non-empty cells in column {col} (rows 1..)')
    cell_len = min(MAX_CELL_LEN, max(len(text) for _, text in sel) or 1)

    t0 = time.monotonic()
    circuit = _build_class_map_circuit(profile, cell_len)
    timing['compile_ms'] += int((time.monotonic() - t0) * 1000)

    t1 = time.monotonic()
    plain_in = _pad_to_max(profile, sel, cell_len)
    out = circuit.encrypt_run_decrypt(plain_in)
    timing['ops_ms'] += int((time.monotonic() - t1) * 1000)

    for i, (r, _) in enumerate(sel):
        grid[r][col] = _decode_class_cell(out[i])


def _apply_count_class(profile, grid, op, timing):
    col    = int(op['col'])
    target = int(op.get('target', CLASS_VOWEL))
    if target not in {0, 1, 2, 3, 4, 5}:
        raise ValueError(f'bad target class {target}')
    sel = _select_cells(grid, col)
    if not sel:
        raise ValueError(f'no non-empty cells in column {col} (rows 1..)')
    cell_len = min(MAX_CELL_LEN, max(len(text) for _, text in sel) or 1)

    t0 = time.monotonic()
    circuit = _build_count_class_circuit(profile, cell_len, target)
    timing['compile_ms'] += int((time.monotonic() - t0) * 1000)

    t1 = time.monotonic()
    plain_in = _pad_to_max(profile, sel, cell_len)
    counts = circuit.encrypt_run_decrypt(plain_in)
    timing['ops_ms'] += int((time.monotonic() - t1) * 1000)

    dst_col = op.get('dst_col')
    for i, (r, _) in enumerate(sel):
        cell = str(int(counts[i]))
        if dst_col is None:
            grid[r][col] = cell
        else:
            dc = int(dst_col)
            while len(grid[r]) <= dc:
                grid[r].append('')
            grid[r][dc] = cell


def _apply_length(profile, grid, op, timing):
    col = int(op['col'])
    sel = _select_cells(grid, col)
    if not sel:
        raise ValueError(f'no non-empty cells in column {col} (rows 1..)')
    cell_len = min(MAX_CELL_LEN, max(len(text) for _, text in sel) or 1)

    t0 = time.monotonic()
    circuit = _build_length_circuit(profile, cell_len)
    timing['compile_ms'] += int((time.monotonic() - t0) * 1000)

    t1 = time.monotonic()
    plain_in = _pad_to_max(profile, sel, cell_len)
    lengths = circuit.encrypt_run_decrypt(plain_in)
    timing['ops_ms'] += int((time.monotonic() - t1) * 1000)

    dst_col = op.get('dst_col')
    for i, (r, _) in enumerate(sel):
        cell = str(int(lengths[i]))
        if dst_col is None:
            grid[r][col] = cell
        else:
            dc = int(dst_col)
            while len(grid[r]) <= dc:
                grid[r].append('')
            grid[r][dc] = cell


def apply_ops(profile, grid, ops):
    errors = []
    timing = {'compile_ms': 0, 'ops_ms': 0}
    for i, op in enumerate(ops):
        op.pop('status', None)
        op.pop('error',  None)
        kind = op.get('op')
        try:
            if   kind == OP_CHAR_CLASS_MAP: _apply_char_class_map(profile, grid, op, timing)
            elif kind == OP_COUNT_CLASS:    _apply_count_class(profile, grid, op, timing)
            elif kind == OP_LENGTH:         _apply_length(profile, grid, op, timing)
            else: raise ValueError(f'unknown op {kind!r}')
            op['status'] = 'ok'
        except Exception as exc:
            op['status'] = 'error'
            op['error']  = str(exc)
            errors.append((i, str(exc)))
    return errors, timing


def run_session(session):
    try:
        ops = json.loads(session.ops_json or '[]')
        if not isinstance(ops, list):
            raise ValueError('ops_json must be a JSON list')
    except Exception as exc:
        session.last_error = f'bad ops_json: {exc!r}'
        session.result_csv = ''
        return session

    grid, rows, cols = parse_csv(session.original_csv or '')
    session.rows = rows
    session.cols = cols
    session.cells = count_nonempty(grid)
    session.max_cell_len = MAX_CELL_LEN
    session.chars_total = MAX_CELLS * MAX_CELL_LEN

    if rows <= 1:
        session.last_error = ('CSV needs a header row plus at least one '
                              'data row.')
        session.result_csv = ''
        return session

    profile = get_profile(session.language_profile)

    errs, timing = apply_ops(profile, grid, ops)
    session.compile_ms = timing['compile_ms']
    session.ops_ms     = timing['ops_ms']
    session.encrypt_ms = 0
    session.decrypt_ms = 0

    session.result_csv = emit_csv(grid)
    session.ops_json = json.dumps(ops)
    if errs:
        session.last_error = '\n'.join(f'op#{i}: {msg}' for i, msg in errs)
    else:
        session.last_error = ''
    return session
