"""Dense flat-genome representation for hex CA rulesets.

For a K-colour, 7-cell-neighbourhood (self + 6 neighbours) hex CA,
every cell at every step is in one of ``K**7`` distinct situations.
A deterministic ruleset must assign exactly one output colour to
each. We pack those outputs into ``ceil(log2(K))`` bits each and
store the whole ruleset as a single byte-string.

For the user's canonical 4-colour case the math is ideal:

  * 4**7 = 16,384 situations
  * 2 bits per cell output (exactly fits 0..3, no waste)
  * 4 cells per byte (clean alignment)
  * total: 4,096 bytes per complete ruleset

Generalising: this module supports K in {2, 3, 4, 5..16}. K=2 packs
into 1 bit/cell, K=3 and 4 into 2 bits/cell, K=5..16 into 4 bits/cell
(so 5-colour wastes 3 encodings, 3-colour wastes 1, 9-colour wastes
7; none of that matters for correctness).

Addressing: the 7-tuple ``(self, n0, n1, n2, n3, n4, n5)`` is read
as a 7-digit base-K number. The base-K index is the offset into the
packed array.

The genome is mutable in place but this class also provides the
higher-level evolutionary operators (mutate, crossover, hamming)
that Det's GA needs.
"""

from __future__ import annotations

import math
import random
from typing import Iterable, List, Tuple


def bits_per_cell(n_colors: int) -> int:
    """Smallest clean power-of-2 bit width holding all K output states."""
    if n_colors <= 2:
        return 1
    if n_colors <= 4:
        return 2
    if n_colors <= 16:
        return 4
    raise ValueError(f'n_colors={n_colors} unsupported (max 16)')


class PackedRuleset:
    """Flat-genome hex CA ruleset. Bit-packed, byte-aligned.

    Addressing: index = self * K^6 + n0 * K^5 + … + n5 * K^0.
    Lookup cost: 1 memory fetch + constant-time bit extraction.
    """

    __slots__ = ('n_colors', 'bits_per_cell', 'n_situations',
                 'cells_per_byte', 'total_bytes', 'data',
                 '_powers')

    def __init__(self, n_colors: int = 4, data: bytes | None = None):
        if not 2 <= n_colors <= 16:
            raise ValueError('n_colors must be between 2 and 16')
        self.n_colors = n_colors
        self.bits_per_cell = bits_per_cell(n_colors)
        self.n_situations = n_colors ** 7
        self.cells_per_byte = 8 // self.bits_per_cell
        total_bits = self.n_situations * self.bits_per_cell
        self.total_bytes = (total_bits + 7) // 8
        if data is None:
            self.data = bytearray(self.total_bytes)
        else:
            if len(data) != self.total_bytes:
                raise ValueError(
                    f'data is {len(data)} bytes, expected {self.total_bytes}'
                )
            self.data = bytearray(data)
        # Precompute K^0..K^6 for the index walk.
        self._powers = tuple(n_colors ** i for i in range(6, -1, -1))

    # ── Situation addressing ──────────────────────────────────────

    def index_of(self, self_color: int, neighbours: Iterable[int]) -> int:
        """Compute the flat situation index for a 7-tuple."""
        # Walk s, n0..n5 and build the base-K number.
        parts = (self_color, *neighbours)
        idx = 0
        for p, weight in zip(parts, self._powers):
            idx += p * weight
        return idx

    def situation_at(self, index: int) -> Tuple[int, Tuple[int, ...]]:
        """Inverse of index_of — decode a flat index back into
        (self, (n0, n1, n2, n3, n4, n5))."""
        parts = []
        rem = index
        for weight in self._powers:
            parts.append(rem // weight)
            rem = rem % weight
        return parts[0], tuple(parts[1:])

    # ── Core get/set ──────────────────────────────────────────────

    def _bit_slot(self, index: int) -> Tuple[int, int]:
        """Return (byte_offset, bit_offset_within_byte)."""
        total_bit = index * self.bits_per_cell
        return total_bit >> 3, total_bit & 7

    def get_by_index(self, index: int) -> int:
        byte_i, bit_i = self._bit_slot(index)
        mask = (1 << self.bits_per_cell) - 1
        return (self.data[byte_i] >> bit_i) & mask

    def set_by_index(self, index: int, output: int) -> None:
        byte_i, bit_i = self._bit_slot(index)
        mask = (1 << self.bits_per_cell) - 1
        self.data[byte_i] = (
            (self.data[byte_i] & ~(mask << bit_i) & 0xFF)
            | ((output & mask) << bit_i)
        )

    def get(self, self_color: int, neighbours: Iterable[int]) -> int:
        return self.get_by_index(self.index_of(self_color, neighbours))

    def set(self, self_color: int, neighbours: Iterable[int],
            output: int) -> None:
        self.set_by_index(self.index_of(self_color, neighbours), output)

    # ── Population init ───────────────────────────────────────────

    @classmethod
    def random(cls, n_colors: int = 4,
               rng: random.Random | None = None) -> 'PackedRuleset':
        """A ruleset where every situation maps to a uniformly-random
        output colour. Starting point for GA initial populations."""
        rng = rng or random
        r = cls(n_colors)
        for i in range(r.n_situations):
            r.set_by_index(i, rng.randrange(n_colors))
        return r

    @classmethod
    def identity(cls, n_colors: int = 4) -> 'PackedRuleset':
        """A ruleset where every cell retains its own colour regardless
        of its neighbours — the "do nothing" baseline."""
        r = cls(n_colors)
        # For each self colour, every neighbour configuration → self.
        for self_c in range(n_colors):
            # Walk every neighbour configuration for this self-colour.
            for neigh_idx in range(n_colors ** 6):
                idx = self_c * (n_colors ** 6) + neigh_idx
                r.set_by_index(idx, self_c)
        return r

    # ── Evolutionary operators ────────────────────────────────────

    def mutate(self, rate: float = 0.001,
               rng: random.Random | None = None) -> 'PackedRuleset':
        """Return a copy with each situation's output reassigned to a
        uniformly-random colour with probability ``rate``.

        At rate=0.001 a K=4 genome sees ~16 flips per call on average —
        standard GA territory.
        """
        rng = rng or random
        child = PackedRuleset(self.n_colors, bytes(self.data))
        for i in range(self.n_situations):
            if rng.random() < rate:
                child.set_by_index(i, rng.randrange(self.n_colors))
        return child

    def crossover(self, other: 'PackedRuleset',
                  rng: random.Random | None = None) -> 'PackedRuleset':
        """Single-point byte-slice crossover. Keep the prefix of
        ``self`` and the suffix of ``other``, split at a random byte
        boundary.

        A byte boundary is always 2–4 cells (depending on K) so the
        crossover is genuinely shuffling meaningful rule groups, not
        cutting across a half-encoded cell.
        """
        if self.n_colors != other.n_colors:
            raise ValueError('crossover between different K is nonsensical')
        rng = rng or random
        cut = rng.randrange(1, self.total_bytes)
        mixed = bytes(self.data[:cut]) + bytes(other.data[cut:])
        return PackedRuleset(self.n_colors, mixed)

    def hamming(self, other: 'PackedRuleset') -> int:
        """Count situations where this and other disagree on output.

        A structural diversity metric for tournament breeding. Two
        genomes with ``hamming == 0`` are identical; with
        ``hamming == n_situations`` they agree on nothing.
        """
        if self.n_colors != other.n_colors:
            raise ValueError('hamming between different K is nonsensical')
        diff = 0
        for i in range(self.n_situations):
            if self.get_by_index(i) != other.get_by_index(i):
                diff += 1
        return diff

    # ── Interop with the existing wildcard/exact rule format ──────

    def to_explicit(self, skip_identity: bool = True) -> List[dict]:
        """Materialise to a list of ``{s, n, r}`` dicts matching
        automaton.detector.step_exact's format.

        With ``skip_identity=True`` (default), situations whose output
        equals the cell's own colour — the identity default — are
        omitted. That's almost always what you want: the explicit rule
        list is compressed; the packed form is ground truth.
        """
        out = []
        for idx in range(self.n_situations):
            self_c, nbs = self.situation_at(idx)
            r = self.get_by_index(idx)
            if skip_identity and r == self_c:
                continue
            out.append({'s': self_c, 'n': list(nbs), 'r': r})
        return out

    @classmethod
    def from_explicit(cls, exact_rules: Iterable[dict],
                      n_colors: int = 4) -> 'PackedRuleset':
        """Build a packed ruleset from a list of explicit (possibly
        wildcarded) rules, using the same match precedence as
        ``step_exact``: exact match first, then wildcard fallback,
        then identity default.
        """
        r = cls.identity(n_colors)

        # Separate exact and wildcard rules — match step_exact's
        # behaviour: exact match wins over wildcard match.
        exact_by_key: dict = {}
        wildcards: List[dict] = []
        for er in exact_rules:
            if er['s'] == -1 or any(x == -1 for x in er['n']):
                wildcards.append(er)
            else:
                exact_by_key[(er['s'], tuple(er['n']))] = er['r']

        for idx in range(r.n_situations):
            self_c, nbs = r.situation_at(idx)
            key = (self_c, nbs)
            if key in exact_by_key:
                r.set_by_index(idx, exact_by_key[key])
                continue
            # Walk wildcards in list order (first match wins)
            matched_r = None
            for er in wildcards:
                if er['s'] >= 0 and er['s'] != self_c:
                    continue
                ok = True
                for j in range(6):
                    if er['n'][j] >= 0 and er['n'][j] != nbs[j]:
                        ok = False
                        break
                if ok:
                    matched_r = er['r']
                    break
            if matched_r is not None:
                r.set_by_index(idx, matched_r)
            # else leaves identity-default (r == self_c from identity())
        return r

    # ── Serialisation ─────────────────────────────────────────────

    def to_bytes(self) -> bytes:
        return bytes(self.data)

    @classmethod
    def from_bytes(cls, data: bytes, n_colors: int = 4) -> 'PackedRuleset':
        return cls(n_colors=n_colors, data=data)

    def to_hex(self) -> str:
        return self.data.hex()

    @classmethod
    def from_hex(cls, hex_str: str, n_colors: int = 4) -> 'PackedRuleset':
        return cls(n_colors=n_colors, data=bytes.fromhex(hex_str))


# ── genome.bin (s3lab + ESP32-S3 firmware) ──────────────────────────
#
# Wire format used by s3lab's "Download genome.bin" button and the
# ESP32-S3 sketch's winner.bin: 4-byte "HXC4" magic + 4-byte palette
# + 4,096-byte K=4 packed genome = 4,104 bytes total. The 4,096-byte
# payload is byte-identical to PackedRuleset.data.

GENOME_BIN_MAGIC = b'HXC4'
GENOME_BIN_PALETTE_BYTES = 4
# K=4 packed: 4^7 = 16,384 entries × 2 bits each = 32,768 bits = 4,096 bytes.
GENOME_BIN_GENOME_BYTES = (4 ** 7 * 2) // 8
GENOME_BIN_TOTAL = (
    len(GENOME_BIN_MAGIC) + GENOME_BIN_PALETTE_BYTES + GENOME_BIN_GENOME_BYTES
)


# ANSI-256 colour table — matches s3lab's engine.mjs exactly so a
# rule imported from /s3lab/ renders with the same cell colours in
# automaton's canvas.

_ANSI_STD = [
    (0, 0, 0),       (128, 0, 0),     (0, 128, 0),     (128, 128, 0),
    (0, 0, 128),     (128, 0, 128),   (0, 128, 128),   (192, 192, 192),
    (128, 128, 128), (255, 0, 0),     (0, 255, 0),     (255, 255, 0),
    (0, 0, 255),     (255, 0, 255),   (0, 255, 255),   (255, 255, 255),
]
_ANSI_LVL = (0, 95, 135, 175, 215, 255)


def ansi256_to_rgb(idx: int) -> Tuple[int, int, int]:
    """Convert an ANSI-256 colour index to (r, g, b) in 0..255."""
    idx = int(idx) & 0xFF
    if idx < 16:
        return _ANSI_STD[idx]
    if idx < 232:
        i = idx - 16
        return (_ANSI_LVL[i // 36], _ANSI_LVL[(i % 36) // 6], _ANSI_LVL[i % 6])
    v = 8 + (idx - 232) * 10
    if v > 255:
        v = 255
    return (v, v, v)


def ansi256_to_hex(idx: int) -> str:
    """Convert an ANSI-256 colour index to a CSS ``#rrggbb`` string."""
    r, g, b = ansi256_to_rgb(idx)
    return f'#{r:02x}{g:02x}{b:02x}'


def parse_genome_bin(data: bytes) -> Tuple[bytes, 'PackedRuleset']:
    """Decode an s3lab / ESP32-S3 ``genome.bin`` into ``(palette, ruleset)``.

    Raises ``ValueError`` on a bad magic, wrong length, or anything else
    that would land an unintended payload in the database.
    """
    if len(data) != GENOME_BIN_TOTAL:
        raise ValueError(
            f'genome.bin must be {GENOME_BIN_TOTAL} bytes, got {len(data)}'
        )
    magic = data[:len(GENOME_BIN_MAGIC)]
    if magic != GENOME_BIN_MAGIC:
        raise ValueError(
            f'genome.bin magic must be {GENOME_BIN_MAGIC!r}, got {magic!r}'
        )
    palette = bytes(data[
        len(GENOME_BIN_MAGIC):
        len(GENOME_BIN_MAGIC) + GENOME_BIN_PALETTE_BYTES
    ])
    genome = bytes(data[
        len(GENOME_BIN_MAGIC) + GENOME_BIN_PALETTE_BYTES:
    ])
    return palette, PackedRuleset(n_colors=4, data=genome)


def encode_genome_bin(palette_ansi: bytes, ruleset: 'PackedRuleset') -> bytes:
    """Inverse of :func:`parse_genome_bin` — emit the 4,104-byte file."""
    if len(palette_ansi) != GENOME_BIN_PALETTE_BYTES:
        raise ValueError(
            f'palette must be {GENOME_BIN_PALETTE_BYTES} bytes, '
            f'got {len(palette_ansi)}'
        )
    if ruleset.n_colors != 4 or len(ruleset.data) != GENOME_BIN_GENOME_BYTES:
        raise ValueError('only K=4 rulesets fit the s3lab genome format')
    return GENOME_BIN_MAGIC + bytes(palette_ansi) + bytes(ruleset.data)


def hex_to_rgb(css: str) -> Tuple[int, int, int]:
    """``'#rrggbb'`` → ``(r, g, b)``. Tolerates ``#rgb``, lowercase, no
    leading hash. Returns black on anything unparseable so callers can
    fall through without raising on user-edited palette JSON."""
    s = (css or '').strip().lstrip('#').lower()
    if len(s) == 3:
        s = ''.join(c + c for c in s)
    if len(s) != 6:
        return (0, 0, 0)
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return (0, 0, 0)


def nearest_ansi256(rgb: Tuple[int, int, int]) -> int:
    """Closest ANSI-256 index to an (r, g, b) triple by squared
    Euclidean distance. Used when an Automaton RuleSet has a CSS
    palette but no recorded ANSI codes (e.g. one that wasn't imported
    from s3lab — a hand-authored or merged ruleset)."""
    r, g, b = rgb
    best_idx, best_d = 0, 1 << 30
    for idx in range(256):
        ar, ag, ab = ansi256_to_rgb(idx)
        d = (ar - r) ** 2 + (ag - g) ** 2 + (ab - b) ** 2
        if d < best_d:
            best_idx, best_d = idx, d
            if d == 0:
                break
    return best_idx

    def __len__(self) -> int:
        return self.n_situations

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, PackedRuleset)
                and self.n_colors == other.n_colors
                and self.data == other.data)

    def __repr__(self) -> str:
        return (f'PackedRuleset(n_colors={self.n_colors}, '
                f'{self.total_bytes}B, '
                f'sha1={__import__("hashlib").sha1(self.data).hexdigest()[:10]}…)')
