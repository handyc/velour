"""HXNN — nearest-neighbour hex-CA wire format.

Independent of the K=4 positional ``HXC4`` blob — different magic,
different layout, different engine. They never share code; a HXNN
file cannot be loaded as HXC4 or vice versa.

::

    Header  (8 bytes)
        4: magic 'HXNN'
        1: K          (number of colours, 2..255)
        1: N_log2     (entries are 2**N_log2; 14 = 16,384)
        2: reserved (zero)

    Palette (K bytes of ANSI-256 indices, same convention as HXC4)

    Body    (entries × 8 bytes per entry, K ≤ 256)
        For each entry i in 0..(2**N_log2 - 1):
            7 bytes: key 7-tuple (self, n0, n1, n2, n3, n4, n5)
            1 byte:  output colour

The engine treats the body as a list of prototypes. At lookup time
the cell's actual neighbourhood is matched to the *closest* prototype
by Euclidean distance, restricted to the bin of prototypes whose
self-coordinate equals the cell's self colour. Output of the winning
prototype is the cell's next colour.

This file is the canonical reference; ``engine.py`` and the JS
companion mirror it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


MAGIC          = b'HXNN'
HEADER_BYTES   = 8
ENTRY_BYTES    = 8        # 7 key bytes + 1 output byte (K ≤ 256)
DEFAULT_N_LOG2 = 14       # → 16,384 prototypes, matches the K=4 positional family
DEFAULT_K      = 4

# Allowed K values. The engine itself works for any K in 2..255 but
# the UI exposes a sensible discrete dial.
K_CHOICES = (4, 8, 16, 32, 64, 128, 256)


@dataclass
class Genome:
    """Decoded HXNN genome — palette + 16,384 prototypes."""

    k:             int
    n_log2:        int
    palette:       bytes                  # K bytes ANSI-256 indices
    keys:          List[Tuple[int, ...]]  # length 2**n_log2, each a 7-tuple
    outputs:       List[int]              # length 2**n_log2, each 0..K-1

    @property
    def n_entries(self) -> int:
        return len(self.keys)


def encode(g: Genome) -> bytes:
    """Serialise a Genome to the wire format."""
    if not (2 <= g.k <= 256):
        raise ValueError(f'K out of range: {g.k}')
    if g.n_log2 < 1 or g.n_log2 > 16:
        raise ValueError(f'N_log2 out of range: {g.n_log2}')
    if len(g.palette) != g.k:
        raise ValueError(
            f'palette length {len(g.palette)} must equal K={g.k}'
        )
    n_entries = 1 << g.n_log2
    if len(g.keys) != n_entries or len(g.outputs) != n_entries:
        raise ValueError(
            f'keys/outputs length must be {n_entries}'
        )

    out = bytearray(HEADER_BYTES + g.k + n_entries * ENTRY_BYTES)
    out[0:4] = MAGIC
    out[4]   = g.k
    out[5]   = g.n_log2
    out[6]   = 0
    out[7]   = 0
    out[HEADER_BYTES:HEADER_BYTES + g.k] = g.palette
    base = HEADER_BYTES + g.k
    for i, key in enumerate(g.keys):
        if len(key) != 7:
            raise ValueError(f'key {i} must be a 7-tuple')
        for j, v in enumerate(key):
            if not (0 <= v < 256):
                raise ValueError(f'key {i}.{j} out of byte range: {v}')
            out[base + i * ENTRY_BYTES + j] = v
        out[base + i * ENTRY_BYTES + 7] = g.outputs[i] & 0xFF
    return bytes(out)


def decode(buf: bytes) -> Genome:
    """Inverse of :func:`encode`. Raises ``ValueError`` on a bad blob."""
    if len(buf) < HEADER_BYTES + 1:
        raise ValueError('blob too short for header')
    if buf[0:4] != MAGIC:
        raise ValueError(f'bad magic: {buf[0:4]!r}')
    k = buf[4]
    n_log2 = buf[5]
    if not (2 <= k <= 256):
        raise ValueError(f'K out of range: {k}')
    if not (1 <= n_log2 <= 16):
        raise ValueError(f'N_log2 out of range: {n_log2}')
    n_entries = 1 << n_log2
    expected = HEADER_BYTES + k + n_entries * ENTRY_BYTES
    if len(buf) != expected:
        raise ValueError(f'blob length {len(buf)}, expected {expected}')

    palette = bytes(buf[HEADER_BYTES:HEADER_BYTES + k])
    base = HEADER_BYTES + k
    keys: List[Tuple[int, ...]] = []
    outputs: List[int] = []
    for i in range(n_entries):
        off = base + i * ENTRY_BYTES
        keys.append(tuple(buf[off:off + 7]))
        outputs.append(buf[off + 7])
    return Genome(k=k, n_log2=n_log2, palette=palette,
                  keys=keys, outputs=outputs)
