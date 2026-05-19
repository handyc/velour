"""Self-describing on-disk format for shipping trained CA rules between
machines (home box ↔ ALICE ↔ collaborator boxes).

The architecture is "embarrassingly parallel" at three granularities:
per-pair, per-position within a pair, per-seed.  The training side
writes append-only rule files; the ingest side iterates records and
upserts them into the QRPair database.  Last-write-wins per
(pair_pk, rule_shape, position, port_src) tuple, but since each
worker is assigned a disjoint slice of the corpus, there's no
expected conflict.

## Record format (little-endian throughout)

    offset  size  name        notes
    0       4     magic       0xC411E8B0  (CAFE_B256 ish)
    4       1     version     1
    5       4     pair_pk     u32 — the QRPair primary key on the
                              home DB this rule belongs to
    9       1     position    u8 — output-byte position within the
                              pair's expected response
    10      2     n_ticks     u16 — n_ticks the rule was trained at
    12      1     port_src    u8 enum: 0=off, 1=dmn, 2=router,
                              3=prev_byte  (matches QRPair
                              .cell8_input_source choices)
    13      1     rule_shape  u8 enum: 0=cell8 (65,536 B),
                              1=7to1  (16,384 B)
    14      4     rule_len    u32 — must equal 65,536 or 16,384
                              consistent with rule_shape
    18      <L>   rule_blob   raw little-endian bytes (L=rule_len)
    18+L    4     crc32       u32 over [magic .. rule_blob)

So a cell8 record is 18 + 65,536 + 4 = 65,558 bytes.
A 7→1 record is  18 + 16,384 + 4 = 16,406 bytes.

A file is just a concatenation of records.  No header, no footer, no
index — append-only so a kill mid-write at worst loses the in-progress
record (caught by CRC on read).

## CRC

Standard zlib.crc32, init=0, over the full record except the trailing
4 bytes (which hold the CRC itself).  Mismatch = skip + warn.
"""
from __future__ import annotations

import io
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


MAGIC      = 0xC411E8B0
VERSION    = 1

PORT_SRC = {'off': 0, 'dmn': 1, 'router': 2, 'prev_byte': 3}
PORT_SRC_REV = {v: k for k, v in PORT_SRC.items()}

SHAPE_CELL8 = 0    # 65,536 bytes (8→1)
SHAPE_7TO1  = 1    # 16,384 bytes (7→1)
SHAPE_LEN = {SHAPE_CELL8: 65_536, SHAPE_7TO1: 16_384}
SHAPE_NAME = {SHAPE_CELL8: 'cell8', SHAPE_7TO1: '7to1'}
SHAPE_BY_LEN = {65_536: SHAPE_CELL8, 16_384: SHAPE_7TO1}

HEADER_FMT = '<IBIBHBBI'    # magic, version, pair_pk, position,
                              # n_ticks, port_src, rule_shape, rule_len
HEADER_SIZE = struct.calcsize(HEADER_FMT)   # 18 bytes
CRC_SIZE = 4


@dataclass(frozen=True)
class RuleRecord:
    """One (pair, position, rule) record."""
    pair_pk:    int
    position:   int
    n_ticks:    int
    port_src:   str             # 'off' | 'dmn' | 'router' | 'prev_byte'
    rule_shape: int             # SHAPE_CELL8 or SHAPE_7TO1
    rule_blob:  bytes           # 65,536 or 16,384 bytes

    def __post_init__(self):
        expected = SHAPE_LEN[self.rule_shape]
        if len(self.rule_blob) != expected:
            raise ValueError(
                f'shape={SHAPE_NAME[self.rule_shape]} expects {expected} B; '
                f'got {len(self.rule_blob)}')
        if self.port_src not in PORT_SRC:
            raise ValueError(f'unknown port_src {self.port_src!r}')


def write_record(fh: io.IOBase, rec: RuleRecord) -> int:
    """Serialize `rec` into `fh`; returns bytes written."""
    header = struct.pack(
        HEADER_FMT,
        MAGIC, VERSION, rec.pair_pk, rec.position,
        rec.n_ticks, PORT_SRC[rec.port_src],
        rec.rule_shape, SHAPE_LEN[rec.rule_shape])
    payload = header + rec.rule_blob
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    fh.write(payload)
    fh.write(struct.pack('<I', crc))
    return len(payload) + CRC_SIZE


def append_records(path: Path, records) -> int:
    """Append-only writer.  Returns total bytes appended."""
    n = 0
    with open(path, 'ab') as fh:
        for rec in records:
            n += write_record(fh, rec)
    return n


def read_records(path: Path, *,
                     skip_bad: bool = True) -> Iterator[RuleRecord]:
    """Iterate records from `path`.  `skip_bad=True` quietly drops
    malformed / CRC-bad / partial-tail records (logs them via the
    caller's own logger if attached); `skip_bad=False` raises."""
    with open(path, 'rb') as fh:
        idx = 0
        while True:
            header = fh.read(HEADER_SIZE)
            if not header:
                return
            if len(header) < HEADER_SIZE:
                msg = f'{path.name}: truncated header at record {idx}'
                if skip_bad: return
                raise ValueError(msg)
            try:
                (magic, version, pair_pk, position,
                  n_ticks, port_src_e, shape, rule_len) = struct.unpack(
                    HEADER_FMT, header)
            except struct.error as e:
                msg = f'{path.name}: bad header at record {idx}: {e}'
                if skip_bad: return
                raise ValueError(msg)
            if magic != MAGIC:
                msg = (f'{path.name}: bad magic 0x{magic:08x} at record {idx}'
                       f' (expected 0x{MAGIC:08x})')
                if skip_bad: return
                raise ValueError(msg)
            if version != VERSION:
                msg = f'{path.name}: version {version} not supported (want {VERSION})'
                if skip_bad: return
                raise ValueError(msg)
            if shape not in SHAPE_LEN or SHAPE_LEN[shape] != rule_len:
                msg = (f'{path.name}: rule_shape {shape} / rule_len {rule_len} '
                       f'inconsistent')
                if skip_bad: return
                raise ValueError(msg)
            rule_blob = fh.read(rule_len)
            crc_b     = fh.read(CRC_SIZE)
            if len(rule_blob) != rule_len or len(crc_b) != CRC_SIZE:
                msg = f'{path.name}: truncated body at record {idx}'
                if skip_bad: return
                raise ValueError(msg)
            (got_crc,) = struct.unpack('<I', crc_b)
            want_crc = zlib.crc32(header + rule_blob) & 0xFFFFFFFF
            if got_crc != want_crc:
                msg = (f'{path.name}: CRC mismatch at record {idx} '
                       f'(got 0x{got_crc:08x}, want 0x{want_crc:08x})')
                if skip_bad:
                    idx += 1
                    continue
                raise ValueError(msg)
            yield RuleRecord(
                pair_pk=pair_pk, position=position, n_ticks=n_ticks,
                port_src=PORT_SRC_REV.get(port_src_e, 'off'),
                rule_shape=shape, rule_blob=rule_blob)
            idx += 1


def shape_for(rule_blob_or_len) -> int:
    """SHAPE_CELL8 (65,536 B) or SHAPE_7TO1 (16,384 B).  Accepts either
    a bytes-like object or its length as an int."""
    n = (rule_blob_or_len if isinstance(rule_blob_or_len, int)
         else len(rule_blob_or_len))
    if n not in SHAPE_BY_LEN:
        raise ValueError(f'rule_len {n} not a known shape (need 16384 or 65536)')
    return SHAPE_BY_LEN[n]
