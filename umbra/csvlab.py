"""CSV → CKKS round-trip pipeline.

The Django request is responsible for the secret key, the
encryption, the ops, and the decryption — so this is a *pedagogical*
demonstration of homomorphic manipulation, not a privacy boundary.

Wire shape: a CsvLabSession stores the raw CSV plus a JSON queue of
ops.  run_session() builds a fresh CKKS context, encrypts every
parseable numeric cell into its own ciphertext, replays the ops on
the ciphertext grid, decrypts, then re-emits a CSV.

The ops queue (ops_json on the session) is a list of dicts.
Coordinates are 0-indexed (header row is row 0 if present).

  {"op": "add_const",  "row": R, "col": C, "value": V}
      -> grid[R][C] += V

  {"op": "mul_const",  "row": R, "col": C, "value": V}
      -> grid[R][C] *= V

  {"op": "sum_cells",  "a": [R,C], "b": [R,C], "dst": [R,C]}
      -> grid[dst] = grid[a] + grid[b]

  {"op": "col_total",  "col": C, "dst": [R,C], "skip_header": true}
      -> grid[dst] = sum(grid[r][C] for r in column, skipping header
                         row 0 when skip_header is true)

Non-numeric cells (including headers) are left as plaintext strings.
Ops that name a non-numeric cell or a missing coordinate are
recorded in last_error and skipped.
"""
import csv
import io
import json
import time

import tenseal as ts


OP_ADD_CONST  = 'add_const'
OP_MUL_CONST  = 'mul_const'
OP_SUM_CELLS  = 'sum_cells'
OP_COL_TOTAL  = 'col_total'

OP_CHOICES = [
    (OP_ADD_CONST, 'add constant to cell'),
    (OP_MUL_CONST, 'multiply cell by constant'),
    (OP_SUM_CELLS, 'sum two cells into a third'),
    (OP_COL_TOTAL, 'column total into a cell'),
]


POLY_MODULUS_DEGREE = 8192
COEFF_MOD_BIT_SIZES = [60, 40, 40, 60]
GLOBAL_SCALE        = 2 ** 40


def _new_context():
    ctx = ts.context(
        ts.SCHEME_TYPE.CKKS,
        poly_modulus_degree=POLY_MODULUS_DEGREE,
        coeff_mod_bit_sizes=COEFF_MOD_BIT_SIZES,
    )
    ctx.global_scale = GLOBAL_SCALE
    ctx.generate_galois_keys()
    return ctx


def parse_csv(text: str):
    """Return (grid, rows, cols).  grid is a list of lists of strings."""
    reader = csv.reader(io.StringIO(text))
    grid   = [list(row) for row in reader]
    rows   = len(grid)
    cols   = max((len(r) for r in grid), default=0)
    for r in grid:
        while len(r) < cols:
            r.append('')
    return grid, rows, cols


def _try_float(s: str):
    if s is None:
        return None
    s2 = s.strip()
    if not s2:
        return None
    try:
        return float(s2)
    except ValueError:
        return None


def _fmt(x: float) -> str:
    """Render a decrypted float as a CSV cell.  CKKS is approximate, so
    very-near-integer values are rendered as ints, otherwise we keep
    six significant decimals and strip trailing zeros."""
    if abs(x - round(x)) < 1e-4:
        return str(int(round(x)))
    s = f'{x:.6f}'.rstrip('0').rstrip('.')
    return s or '0'


def _in_bounds(grid, r, c):
    return 0 <= r < len(grid) and 0 <= c < (len(grid[0]) if grid else 0)


def encrypt_grid(ctx, grid):
    """Returns (cipher_grid, byte_total).  cipher_grid is the same shape
    as grid; numeric cells become CKKS vectors (one slot), others None."""
    cipher_grid = []
    byte_total  = 0
    for row in grid:
        crow = []
        for cell in row:
            v = _try_float(cell)
            if v is None:
                crow.append(None)
            else:
                ct = ts.ckks_vector(ctx, [v])
                crow.append(ct)
                try:
                    byte_total += len(ct.serialize())
                except Exception:
                    pass
        cipher_grid.append(crow)
    return cipher_grid, byte_total


def apply_ops(cipher_grid, ops):
    """Replay ops on the ciphertext grid in order.  Returns a list of
    (op_index, error_message) for ops that couldn't be applied."""
    errors = []
    for i, op in enumerate(ops):
        kind = op.get('op')
        try:
            if kind == OP_ADD_CONST:
                r, c, v = int(op['row']), int(op['col']), float(op['value'])
                if not _in_bounds(cipher_grid, r, c) or cipher_grid[r][c] is None:
                    raise ValueError(f'cell ({r},{c}) is not numeric')
                cipher_grid[r][c] = cipher_grid[r][c] + v
            elif kind == OP_MUL_CONST:
                r, c, v = int(op['row']), int(op['col']), float(op['value'])
                if not _in_bounds(cipher_grid, r, c) or cipher_grid[r][c] is None:
                    raise ValueError(f'cell ({r},{c}) is not numeric')
                cipher_grid[r][c] = cipher_grid[r][c] * v
            elif kind == OP_SUM_CELLS:
                ar, ac = (int(x) for x in op['a'])
                br, bc = (int(x) for x in op['b'])
                dr, dc = (int(x) for x in op['dst'])
                for (rr, cc) in [(ar, ac), (br, bc), (dr, dc)]:
                    if not _in_bounds(cipher_grid, rr, cc):
                        raise ValueError(f'cell ({rr},{cc}) out of bounds')
                if cipher_grid[ar][ac] is None or cipher_grid[br][bc] is None:
                    raise ValueError('source cell is not numeric')
                cipher_grid[dr][dc] = cipher_grid[ar][ac] + cipher_grid[br][bc]
            elif kind == OP_COL_TOTAL:
                col = int(op['col'])
                dr, dc = (int(x) for x in op['dst'])
                skip_header = bool(op.get('skip_header', True))
                start_row = 1 if skip_header else 0
                if not _in_bounds(cipher_grid, dr, dc):
                    raise ValueError(f'dst ({dr},{dc}) out of bounds')
                acc = None
                for rr in range(start_row, len(cipher_grid)):
                    cell = cipher_grid[rr][col] if col < len(cipher_grid[rr]) else None
                    if cell is None:
                        continue
                    acc = cell if acc is None else acc + cell
                if acc is None:
                    raise ValueError(f'column {col} has no numeric cells')
                cipher_grid[dr][dc] = acc
            else:
                raise ValueError(f'unknown op {kind!r}')
        except Exception as exc:
            errors.append((i, str(exc)))
    return errors


def decrypt_grid(cipher_grid, original_grid):
    """Return a fresh grid of strings: numeric cells decrypted +
    formatted, non-numeric cells copied through from the original."""
    out = []
    for r, row in enumerate(cipher_grid):
        orow = []
        for c, cell in enumerate(row):
            if cell is None:
                orow.append(original_grid[r][c] if c < len(original_grid[r]) else '')
            else:
                v = cell.decrypt()[0]
                orow.append(_fmt(v))
        out.append(orow)
    return out


def emit_csv(grid) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    for row in grid:
        w.writerow(row)
    return buf.getvalue()


def run_session(session):
    """Run the full encrypt → apply → decrypt round trip and write
    timings, sizes, result_csv, last_error back onto the session.
    Returns the session unsaved-elsewhere; caller must .save()."""
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

    ctx = _new_context()

    t0 = time.monotonic()
    cipher_grid, byte_total = encrypt_grid(ctx, grid)
    session.encrypt_ms = int((time.monotonic() - t0) * 1000)
    session.ciphertext_bytes = byte_total
    session.numeric_cells = sum(1 for row in cipher_grid for x in row if x is not None)

    t1 = time.monotonic()
    errs = apply_ops(cipher_grid, ops)
    session.ops_ms = int((time.monotonic() - t1) * 1000)

    t2 = time.monotonic()
    out_grid = decrypt_grid(cipher_grid, grid)
    session.decrypt_ms = int((time.monotonic() - t2) * 1000)

    session.result_csv = emit_csv(out_grid)
    if errs:
        session.last_error = '\n'.join(f'op#{i}: {msg}' for i, msg in errs)
    else:
        session.last_error = ''
    return session
