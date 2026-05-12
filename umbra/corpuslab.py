"""Linguistic CSV → Concrete TFHE round-trip pipeline.

Where csvlab.py does CKKS arithmetic on numeric cells, this module does
TFHE programmable-bootstrapping (PBS) on the *bytes* of every cell.
The point: humanities/linguistic research at Leiden works with CSVs
where each cell holds one linguistic form (a word, a morpheme, a gloss)
in a low-resource language.  This pipeline lets researchers send those
forms through a sealed pipeline and perform per-cell character-level
analyses without the operating party seeing the bytes.

Same threat model as csvlab.py: key, encrypt, ops, decrypt all happen
in one Django request.  Demonstration of the sealed shape, not a
privacy boundary.  A two-process split lands later.

Wire shape: a CorpusLabSession stores the raw CSV plus a JSON queue of
per-cell ops.  run_session() pads every non-empty cell to a common
length, encodes each byte as a uint, compiles one Concrete circuit
per op-kind, runs the circuit on the padded byte tensor, and decodes
the output back into a CSV grid.

Ops queue is a list of dicts; coordinates are 0-indexed.

  {"op": "char_class_map", "col": C}
      -> for every row, replace cell at column C with a string where
         each character has been mapped to its class digit:
         0=other/non-ASCII, 1=vowel, 2=consonant, 3=digit, 4=punct.

  {"op": "count_class", "col": C, "target": 1, "dst_col": null}
      -> for every row, count chars in cell[col] whose class matches
         target.  Result rendered as an integer.  If dst_col is null
         the count overwrites the source cell; otherwise it's written
         to that column (which must exist — use the form to append a
         fresh column up front).

  {"op": "length", "col": C, "dst_col": null}
      -> count non-zero (padding sentinel) bytes per cell.

Honest caveat: per-byte classification works on ASCII.  Non-ASCII bytes
(e.g. Devanagari for Hindi/Sanskrit) classify as 'other' for now.  A
follow-up will replace ASCII LUTs with codepoint LUTs that respect
NFKC-normalized Unicode.
"""
import csv
import io
import json
import time

import numpy as np
from concrete import fhe


OP_CHAR_CLASS_MAP = 'char_class_map'
OP_COUNT_CLASS    = 'count_class'
OP_LENGTH         = 'length'

OP_CHOICES = [
    (OP_CHAR_CLASS_MAP, 'replace each char with its class digit'),
    (OP_COUNT_CLASS,    'count chars matching a target class'),
    (OP_LENGTH,         'cell length (non-padding bytes)'),
]

CLASS_OTHER     = 0
CLASS_VOWEL     = 1
CLASS_CONSONANT = 2
CLASS_DIGIT     = 3
CLASS_PUNCT     = 4

CLASS_CHOICES = [
    (CLASS_VOWEL,     'vowel (a e i o u, ASCII)'),
    (CLASS_CONSONANT, 'consonant (ASCII letter, non-vowel)'),
    (CLASS_DIGIT,     'digit (0-9)'),
    (CLASS_PUNCT,     'punctuation/space'),
    (CLASS_OTHER,     'other / non-ASCII'),
]

# Conservative caps for in-request runs.  Concrete PBS is ~200 ms per
# byte on this machine; one Run keeps a Django worker busy for the
# duration.  At 8 × 8 = 64 bytes a single op finishes in ~13 s, leaving
# room under the 25-second runner wall.  ALICE-scale batching lands as
# a `manage.py corpuslab_run` command in a follow-up.
MAX_CELLS         = 8
MAX_CELL_LEN      = 8
SENTINEL          = 0  # padding byte; classifies as CLASS_OTHER

_VOWELS = set(ord(c) for c in 'aeiouAEIOU')
_PUNCT  = set(map(ord, ' !"\',.:;?\t-—'))


def _classify_byte(b: int) -> int:
    if b == SENTINEL:                                   return CLASS_OTHER
    if b in _VOWELS:                                    return CLASS_VOWEL
    if (97 <= b <= 122) or (65 <= b <= 90):             return CLASS_CONSONANT
    if 48 <= b <= 57:                                   return CLASS_DIGIT
    if b in _PUNCT:                                     return CLASS_PUNCT
    return CLASS_OTHER


# 128-entry LUT covering 7-bit ASCII; anything outside that range
# classifies as OTHER.  Concrete's PBS table has to be a flat numpy
# array, so we materialise it once at import.
_CLASS_LUT = np.array([_classify_byte(i) for i in range(128)], dtype=np.int64)


def parse_csv(text: str):
    """Return (grid, rows, cols)."""
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


def _encode_cell(text: str, length: int) -> np.ndarray:
    """Truncate to length, encode as ASCII bytes (non-ASCII → SENTINEL),
    pad with SENTINEL to exactly length."""
    out = np.full(length, SENTINEL, dtype=np.int64)
    for i, ch in enumerate(text[:length]):
        b = ord(ch)
        out[i] = b if 0 < b < 128 else SENTINEL
    return out


def _decode_class_cell(arr) -> str:
    """Render a row of class digits as a compact string, dropping the
    trailing padding zeros."""
    s = ''.join(str(int(x)) for x in arr)
    return s.rstrip('0')


def _select_cells(grid, col: int):
    """Pick (row_index, cell_text) pairs for the target column, up to
    MAX_CELLS, skipping empty cells and the header row.  Returns the
    list of selections and the row indices in `grid` they came from."""
    sel = []
    for r in range(1, len(grid)):  # skip header
        if col >= len(grid[r]):
            continue
        cell = grid[r][col]
        if not cell.strip():
            continue
        sel.append((r, cell))
        if len(sel) >= MAX_CELLS:
            break
    return sel


def _pad_to_max(sel, cell_len: int) -> np.ndarray:
    """Stack the selected cells as a (N_CELLS, cell_len) int64 array,
    padding the cell list itself to MAX_CELLS with zero-rows so every
    compile shares a single fixed input shape."""
    arr = np.zeros((MAX_CELLS, cell_len), dtype=np.int64)
    for i, (_, text) in enumerate(sel):
        arr[i] = _encode_cell(text, cell_len)
    return arr


def _build_class_map_circuit(cell_len: int):
    """Compile a Concrete circuit that maps each byte in an (M, L) tensor
    of bytes to its class digit via PBS.  Inputset spans the full byte
    range so the compiler picks parameters that cover every legal value."""
    table = fhe.LookupTable(_CLASS_LUT.tolist())

    @fhe.compiler({'cells': 'encrypted'})
    def circuit(cells):
        return table[cells]

    inputset = [
        np.random.randint(0, 128, size=(MAX_CELLS, cell_len), dtype=np.int64)
        for _ in range(8)
    ]
    return circuit.compile(inputset)


def _build_count_class_circuit(cell_len: int, target: int):
    """Map each byte to (class == target ? 1 : 0) via PBS, then sum
    along the cell axis to get a (MAX_CELLS,) tensor of counts.  Sum
    fits in 4 bits (cell_len <= 8 → max count 8)."""
    indicator = np.array(
        [1 if _classify_byte(i) == target else 0 for i in range(128)],
        dtype=np.int64,
    )
    table = fhe.LookupTable(indicator.tolist())

    @fhe.compiler({'cells': 'encrypted'})
    def circuit(cells):
        return np.sum(table[cells], axis=1)

    inputset = [
        np.random.randint(0, 128, size=(MAX_CELLS, cell_len), dtype=np.int64)
        for _ in range(8)
    ]
    return circuit.compile(inputset)


def _build_length_circuit(cell_len: int):
    """Per-byte 'is non-padding' indicator, then sum per cell."""
    indicator = np.array([0 if i == SENTINEL else 1 for i in range(128)],
                         dtype=np.int64)
    table = fhe.LookupTable(indicator.tolist())

    @fhe.compiler({'cells': 'encrypted'})
    def circuit(cells):
        return np.sum(table[cells], axis=1)

    inputset = [
        np.random.randint(0, 128, size=(MAX_CELLS, cell_len), dtype=np.int64)
        for _ in range(8)
    ]
    return circuit.compile(inputset)


def _apply_char_class_map(grid, op, timing):
    col = int(op['col'])
    sel = _select_cells(grid, col)
    if not sel:
        raise ValueError(f'no non-empty cells in column {col} (rows 1..)')
    cell_len = min(MAX_CELL_LEN, max(len(text) for _, text in sel) or 1)

    t0 = time.monotonic()
    circuit  = _build_class_map_circuit(cell_len)
    timing['compile_ms'] += int((time.monotonic() - t0) * 1000)

    t1 = time.monotonic()
    plain_in = _pad_to_max(sel, cell_len)
    out      = circuit.encrypt_run_decrypt(plain_in)
    timing['ops_ms'] += int((time.monotonic() - t1) * 1000)

    for i, (r, _) in enumerate(sel):
        grid[r][col] = _decode_class_cell(out[i])


def _apply_count_class(grid, op, timing):
    col    = int(op['col'])
    target = int(op.get('target', CLASS_VOWEL))
    if target not in {c[0] for c in CLASS_CHOICES}:
        raise ValueError(f'bad target class {target}')
    sel = _select_cells(grid, col)
    if not sel:
        raise ValueError(f'no non-empty cells in column {col} (rows 1..)')
    cell_len = min(MAX_CELL_LEN, max(len(text) for _, text in sel) or 1)

    t0 = time.monotonic()
    circuit  = _build_count_class_circuit(cell_len, target)
    timing['compile_ms'] += int((time.monotonic() - t0) * 1000)

    t1 = time.monotonic()
    plain_in = _pad_to_max(sel, cell_len)
    counts   = circuit.encrypt_run_decrypt(plain_in)
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


def _apply_length(grid, op, timing):
    col = int(op['col'])
    sel = _select_cells(grid, col)
    if not sel:
        raise ValueError(f'no non-empty cells in column {col} (rows 1..)')
    cell_len = min(MAX_CELL_LEN, max(len(text) for _, text in sel) or 1)

    t0 = time.monotonic()
    circuit  = _build_length_circuit(cell_len)
    timing['compile_ms'] += int((time.monotonic() - t0) * 1000)

    t1 = time.monotonic()
    plain_in = _pad_to_max(sel, cell_len)
    lengths  = circuit.encrypt_run_decrypt(plain_in)
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


def apply_ops(grid, ops):
    """Replay ops on the grid in order, mutating in place.  Returns a
    list of (op_index, error_message) for ops that couldn't be applied.
    Per-op status is stamped onto each op dict so the UI can show
    applied/error badges."""
    errors = []
    timing = {'compile_ms': 0, 'ops_ms': 0}
    for i, op in enumerate(ops):
        op.pop('status', None)
        op.pop('error',  None)
        kind = op.get('op')
        try:
            if   kind == OP_CHAR_CLASS_MAP: _apply_char_class_map(grid, op, timing)
            elif kind == OP_COUNT_CLASS:    _apply_count_class(grid, op, timing)
            elif kind == OP_LENGTH:         _apply_length(grid, op, timing)
            else: raise ValueError(f'unknown op {kind!r}')
            op['status'] = 'ok'
        except Exception as exc:
            op['status'] = 'error'
            op['error']  = str(exc)
            errors.append((i, str(exc)))
    return errors, timing


def run_session(session):
    """Run the full encrypt → apply → decrypt round trip.  Concrete
    folds encrypt and decrypt into the .encrypt_run_decrypt call inside
    each op, so we attribute time to compile/ops rather than the three
    discrete phases CKKS uses."""
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

    errs, timing = apply_ops(grid, ops)
    session.compile_ms = timing['compile_ms']
    session.ops_ms     = timing['ops_ms']
    session.encrypt_ms = 0   # folded into ops_ms by Concrete
    session.decrypt_ms = 0

    session.result_csv = emit_csv(grid)
    session.ops_json = json.dumps(ops)
    if errs:
        session.last_error = '\n'.join(f'op#{i}: {msg}' for i, msg in errs)
    else:
        session.last_error = ''
    return session
