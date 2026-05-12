"""SealedLex split-process protocol — the honest privacy boundary.

The in-process pipeline (`sealedlex.run_session`) holds the secret key,
encryption, ops, and decryption all in one Django request.  That's a
demo of the *shape* of sealed computation, but it provides no actual
privacy: the compute provider sees the secret key.

This module implements the three-stage protocol that earns the
"sealed" in SealedLex:

  1. ENCRYPT (researcher's laptop) — parses CSV, compiles the circuit
     for the chosen op + profile + cell-len, generates fresh keys,
     encrypts each chunk, packages everything *except* the secret key
     into a portable archive.  Secret key is written to a separate
     local file that never leaves the laptop.

  2. EVALUATE (compute provider, e.g. Leiden ALICE) — receives only
     the package: server-side circuit, evaluation keys (public),
     encrypted input chunks.  Runs the circuit on the encrypted
     inputs.  Has no secret key, cannot decrypt anything.  Emits a
     results package containing encrypted outputs.

  3. DECRYPT (researcher's laptop) — using the original package
     (for the client specs) and the local secret-key file, decrypts
     each output chunk and reconstructs the result CSV.

The wire format is a tar.gz with one shape for input packages
(`*.sealedpack`) and a sister shape for output packages
(`*.sealedresult`).  Each is self-describing via a manifest.json.

Input package layout (`*.sealedpack`):
    manifest.json          — version, profile, op, cell_len, chunk
                             count, source CSV row count, selection
                             mapping (which CSV rows each chunk
                             corresponds to)
    server.zip             — Concrete Server artefact (the executable
                             circuit; no secret material)
    eval.keys              — serialised Concrete EvaluationKeys (public)
    inputs/chunk_<N>.ct    — one ciphertext per chunk

Output package layout (`*.sealedresult`):
    manifest.json          — version, source package manifest digest,
                             chunk count
    outputs/chunk_<N>.ct   — one output ciphertext per chunk

Local secret-key file (NEVER ships):
    bytes from Concrete Keys.serialize() / .save()

The protocol is currently single-op per package.  Multi-op chaining
under seal is future work and requires sharing key schedules across
ops (Concrete's `composition` feature).

This protocol replaces the privacy theatre of the original in-process
pipeline.  See [[feedback_rewrite_over_keep_and_adapt]] for why this
gets a fresh module rather than extending sealedlex.run_session.
"""
import hashlib
import io
import json
import pathlib
import tarfile
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
from concrete import fhe
from concrete.fhe.compilation import Client, Server
from concrete.fhe.compilation.evaluation_keys import EvaluationKeys
from concrete.fhe.compilation.keys import Keys

from . import sealedlex


PROTOCOL_VERSION = 1


# ── Manifest helpers ────────────────────────────────────────────────

def _now_iso() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Encrypt: CSV + op + profile → (package_bytes, secret_keys_bytes) ─

def encrypt(csv_text: str, op: dict, profile_slug: str,
            chunk_cap: Optional[int] = None) -> dict:
    """Build an input package + local secret-key file.

    Returns a dict with:
        'package_bytes':    bytes of the .sealedpack tar.gz
        'keys_bytes':       bytes of the local-only secret-keys file
        'manifest':         the parsed manifest (for callers that want
                            to display stats without re-opening the tar)

    `chunk_cap` is optional: pass None for uncapped (default — let the
    full corpus through) or an integer to cap the selection at N cells
    (mostly useful for quick demos).
    """
    profile = sealedlex.get_profile(profile_slug)

    grid, rows, _ = sealedlex.parse_csv(csv_text)
    if rows <= 1:
        raise ValueError('CSV needs a header row plus at least one data row.')

    col = int(op.get('col', 0))
    sel = sealedlex._select_cells(grid, col, cap=chunk_cap)
    if not sel:
        raise ValueError(f'no non-empty cells in column {col} (rows 1..)')

    cell_len = sealedlex.required_cell_len(op, sel)
    circuit  = sealedlex.compile_op(profile, cell_len, op)
    circuit.keys.generate()

    # Materialise server artefact + eval keys (public).  Server.save
    # writes a zip to disk and refuses to overwrite an existing file,
    # so round-trip through a NamedTemporaryFile we pre-delete.
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as fp:
        server_zip_path = fp.name
    try:
        os.unlink(server_zip_path)
        circuit.server.save(server_zip_path)
        with open(server_zip_path, 'rb') as fp:
            server_zip_bytes = fp.read()
    finally:
        try: os.unlink(server_zip_path)
        except OSError: pass

    eval_bytes = circuit.keys.evaluation.serialize()

    # Chunk + encrypt.
    chunk_size = sealedlex.MAX_CELLS
    chunks_meta = []
    chunk_blobs = []
    for ci, chunk_sel in sealedlex._chunks(sel, chunk_size):
        plain = sealedlex.encode_chunk(profile, chunk_sel, cell_len)
        ct = circuit.client.encrypt(plain)
        chunk_bytes = ct.serialize()
        chunk_blobs.append(chunk_bytes)
        chunks_meta.append({
            'index':       ci,
            'cells':       len(chunk_sel),
            'row_indices': [r for r, _ in chunk_sel],
            'bytes':       len(chunk_bytes),
        })

    manifest = {
        'protocol_version': PROTOCOL_VERSION,
        'created_at':       _now_iso(),
        'profile':          profile.slug,
        'profile_alphabet': profile.alphabet_size,
        'op':               op,
        'cell_len':         cell_len,
        'max_cells_per_chunk': chunk_size,
        'n_chunks':         len(chunks_meta),
        'n_cells':          len(sel),
        'csv_rows':         rows,
        'concrete_version': getattr(fhe, '__version__', None) or 'unknown',
        'chunks':           chunks_meta,
        'sizes': {
            'server_zip': len(server_zip_bytes),
            'eval_keys':  len(eval_bytes),
            'total_inputs_bytes': sum(len(b) for b in chunk_blobs),
        },
    }

    # Secret keys file — saved separately by the caller.
    keys_bytes = circuit.keys.serialize()

    # Pack the input package.
    pkg_buf = io.BytesIO()
    with tarfile.open(fileobj=pkg_buf, mode='w:gz') as tar:
        _add_bytes(tar, 'manifest.json',
                   json.dumps(manifest, indent=2).encode('utf-8'))
        _add_bytes(tar, 'server.zip',  server_zip_bytes)
        _add_bytes(tar, 'eval.keys',   eval_bytes)
        for ci, blob in enumerate(chunk_blobs):
            _add_bytes(tar, f'inputs/chunk_{ci}.ct', blob)
    pkg_bytes = pkg_buf.getvalue()

    return {
        'package_bytes': pkg_bytes,
        'keys_bytes':    keys_bytes,
        'manifest':      manifest,
    }


# ── Evaluate: package_bytes → results_bytes (no secret key involved) ─

def evaluate(package_bytes: bytes, progress_cb=None) -> dict:
    """Run the encrypted ops in `package_bytes`, return a results
    package.  This function MUST NOT have access to a secret key —
    that's the whole privacy property.  If you find yourself reaching
    for the keys file here, stop.

    Returns dict with:
        'results_bytes':  bytes of the .sealedresult tar.gz
        'manifest':       the result-package manifest
        'source_manifest': the input package's manifest, for context
    """
    src_manifest = None
    server_zip_bytes = None
    eval_bytes = None
    chunk_bytes = {}

    with tarfile.open(fileobj=io.BytesIO(package_bytes), mode='r:gz') as tar:
        for member in tar.getmembers():
            if member.name == 'manifest.json':
                src_manifest = json.loads(_read_member(tar, member))
            elif member.name == 'server.zip':
                server_zip_bytes = _read_member(tar, member)
            elif member.name == 'eval.keys':
                eval_bytes = _read_member(tar, member)
            elif member.name.startswith('inputs/chunk_'):
                idx = int(member.name.split('chunk_')[1].split('.')[0])
                chunk_bytes[idx] = _read_member(tar, member)

    if src_manifest is None or server_zip_bytes is None or eval_bytes is None:
        raise ValueError('package is missing required members')

    # Hash the source manifest into the output manifest — lets the
    # decrypt side verify the results came from the package it sent.
    src_manifest_hash = _hash_bytes(
        json.dumps(src_manifest, sort_keys=True).encode('utf-8'))

    # Load server + eval keys.
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as fp:
        sp = fp.name
        fp.write(server_zip_bytes)
    try:
        server = Server.load(sp)
    finally:
        try: os.unlink(sp)
        except OSError: pass

    eval_keys = EvaluationKeys.deserialize(eval_bytes)

    # Run each chunk.  Order by chunk index.
    out_chunks = {}
    n_chunks = len(chunk_bytes)
    for idx in sorted(chunk_bytes.keys()):
        ct_in = fhe.Value.deserialize(chunk_bytes[idx])
        ct_out = server.run(ct_in, evaluation_keys=eval_keys)
        out_chunks[idx] = ct_out.serialize()
        if progress_cb:
            progress_cb(idx + 1, n_chunks)

    results_manifest = {
        'protocol_version':  PROTOCOL_VERSION,
        'created_at':        _now_iso(),
        'source_manifest_sha256': src_manifest_hash,
        'op':                src_manifest['op'],
        'profile':           src_manifest['profile'],
        'n_chunks':          n_chunks,
        'cell_len':           src_manifest['cell_len'],
        'max_cells_per_chunk': src_manifest['max_cells_per_chunk'],
        'concrete_version':  getattr(fhe, '__version__', None) or 'unknown',
        'sizes': {
            'total_output_bytes': sum(len(b) for b in out_chunks.values()),
        },
    }

    results_buf = io.BytesIO()
    with tarfile.open(fileobj=results_buf, mode='w:gz') as tar:
        _add_bytes(tar, 'manifest.json',
                   json.dumps(results_manifest, indent=2).encode('utf-8'))
        for idx in sorted(out_chunks):
            _add_bytes(tar, f'outputs/chunk_{idx}.ct', out_chunks[idx])

    return {
        'results_bytes':   results_buf.getvalue(),
        'manifest':        results_manifest,
        'source_manifest': src_manifest,
    }


# ── Decrypt: package + results + secret keys → CSV ──────────────────

def decrypt(package_bytes: bytes, results_bytes: bytes,
            keys_bytes: bytes,
            original_csv: Optional[str] = None) -> dict:
    """Decrypt the results using the local secret-keys file.  Needs the
    original package for the client specs (server.zip).  If
    `original_csv` is supplied, the decrypted values overlay it (so the
    output CSV preserves columns the op didn't touch); otherwise a
    minimal CSV is emitted with one column per chunk row.

    Returns dict with:
        'output_csv': str
        'plain_chunks': list of per-chunk decoded cell lists (for
                        inspection / testing)
    """
    src_manifest = None
    server_zip_bytes = None
    with tarfile.open(fileobj=io.BytesIO(package_bytes), mode='r:gz') as tar:
        for m in tar.getmembers():
            if m.name == 'manifest.json':
                src_manifest = json.loads(_read_member(tar, m))
            elif m.name == 'server.zip':
                server_zip_bytes = _read_member(tar, m)

    res_manifest = None
    out_chunk_bytes = {}
    with tarfile.open(fileobj=io.BytesIO(results_bytes), mode='r:gz') as tar:
        for m in tar.getmembers():
            if m.name == 'manifest.json':
                res_manifest = json.loads(_read_member(tar, m))
            elif m.name.startswith('outputs/chunk_'):
                idx = int(m.name.split('chunk_')[1].split('.')[0])
                out_chunk_bytes[idx] = _read_member(tar, m)

    if src_manifest is None or res_manifest is None or server_zip_bytes is None:
        raise ValueError('package or results is missing required members')

    # Sanity: results manifest must reference this package.
    expected_hash = _hash_bytes(
        json.dumps(src_manifest, sort_keys=True).encode('utf-8'))
    if res_manifest.get('source_manifest_sha256') != expected_hash:
        raise ValueError(
            'results manifest source_manifest_sha256 does not match this '
            'package — wrong results file?')

    # Load client + attach the local secret keys.
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as fp:
        sp = fp.name
        fp.write(server_zip_bytes)
    with tempfile.NamedTemporaryFile(suffix='.keys', delete=False) as fp:
        kp = fp.name
        fp.write(keys_bytes)
    try:
        client = Client.load(sp)
        client.keys = Keys.deserialize(pathlib.Path(kp))
    finally:
        for path in (sp, kp):
            try: os.unlink(path)
            except OSError: pass

    op = src_manifest['op']
    chunks_meta = {c['index']: c for c in src_manifest['chunks']}

    # Build a flat (row_index → cell_str) map by decrypting + decoding.
    cell_for_row = {}
    plain_chunks = []
    for idx in sorted(out_chunk_bytes.keys()):
        raw = client.decrypt(fhe.Value.deserialize(out_chunk_bytes[idx]))
        decoded = sealedlex.decode_op_chunk_output(op, raw)
        plain_chunks.append(decoded)
        meta = chunks_meta.get(idx, {})
        for i, r in enumerate(meta.get('row_indices', [])):
            cell_for_row[r] = decoded[i]

    # Build the output CSV.  If we got the original CSV passed in, we
    # overlay the op's results onto it (so columns the op didn't touch
    # survive); otherwise emit a minimal csv with row index + result.
    dst_col = op.get('dst_col')
    src_col = int(op.get('col', 0))
    if original_csv is not None:
        grid, _, _ = sealedlex.parse_csv(original_csv)
        for r, cell in cell_for_row.items():
            if dst_col is None:
                grid[r][src_col] = cell
            else:
                dc = int(dst_col)
                while len(grid[r]) <= dc:
                    grid[r].append('')
                grid[r][dc] = cell
        out_csv = sealedlex.emit_csv(grid)
    else:
        out_lines = ['row,value']
        for r in sorted(cell_for_row):
            out_lines.append(f'{r},{cell_for_row[r]}')
        out_csv = '\n'.join(out_lines) + '\n'

    return {
        'output_csv':   out_csv,
        'plain_chunks': plain_chunks,
    }


# ── tar plumbing ────────────────────────────────────────────────────

def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = int(time.time())
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(data))


def _read_member(tar: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    fp = tar.extractfile(member)
    if fp is None:
        return b''
    return fp.read()
