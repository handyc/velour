"""Concept dataclass + encoding / decoding.

A Concept is a (preverb_id, verb_id, suffix_id) triple where each
field is 0 = "none" or an ID into the respective data table.

Surface-form rules (simplified — real Sanskrit has sandhi, ablaut,
guna/vrddhi, etc.; this is the romanised-concatenation baseline):

  preverb + verb + suffix → preverb-verb-suffix

  Examples:
    (0,  1, 0)  → 'gam'                (bare root)
    (1,  1, 0)  → 'ā-gam'              (preverb modifies)
    (0,  1, 2)  → 'gam-ana' / 'gamana' (nominalised)
    (1,  1, 2)  → 'ā-gam-ana'          (both)
    (1, 27, 4)  → 'ā-kṛ-tṛ'  (agent: one who 'does toward', maker)

Glosses compose as: preverb-gloss + verb-gloss + suffix-sense.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import data as _data


@dataclass(frozen=True)
class Concept:
    preverb_id: int = 0
    verb_id: int = 0
    suffix_id: int = 0

    def __post_init__(self):
        # Bounds check — invalid IDs default to 0 (= none).
        object.__setattr__(self, 'preverb_id',
                           self.preverb_id if 0 <= self.preverb_id
                           <= len(_data.PREVERBS) else 0)
        object.__setattr__(self, 'verb_id',
                           self.verb_id if 0 <= self.verb_id
                           <= len(_data.VERB_ROOTS) else 0)
        object.__setattr__(self, 'suffix_id',
                           self.suffix_id if 0 <= self.suffix_id
                           <= len(_data.KRIT_SUFFIXES) else 0)

    # ─── surface rendering ──────────────────────────────────────

    def surface(self) -> str:
        """Render as a hyphen-separated IAST form."""
        parts: list[str] = []
        if self.preverb_id:
            p = _data.preverb_by_id(self.preverb_id)
            if p is not None:
                parts.append(p.form)
        if self.verb_id:
            v = _data.verb_by_id(self.verb_id)
            if v is not None:
                parts.append(v.root)
        if self.suffix_id:
            s = _data.suffix_by_id(self.suffix_id)
            if s is not None:
                # kṛt suffixes are written with leading hyphen in the
                # data table; strip it when joining so we get
                # 'gam-ana' not 'gam--ana'.
                parts.append(s.form.lstrip('-'))
        return '-'.join(parts) if parts else ''

    def gloss(self) -> str:
        """Render as a compositional English gloss."""
        parts: list[str] = []
        if self.preverb_id:
            p = _data.preverb_by_id(self.preverb_id)
            if p is not None:
                parts.append(f'[{p.gloss}]')
        if self.verb_id:
            v = _data.verb_by_id(self.verb_id)
            if v is not None:
                parts.append(v.gloss)
        if self.suffix_id:
            s = _data.suffix_by_id(self.suffix_id)
            if s is not None:
                parts.append(f'({s.sense})')
        return ' '.join(parts) if parts else '(empty concept)'

    def is_empty(self) -> bool:
        return self.preverb_id == 0 and self.verb_id == 0 \
               and self.suffix_id == 0

    def is_nominal(self) -> bool:
        return self.suffix_id != 0

    # ─── pack / unpack ──────────────────────────────────────────

    # Bit layout (LSB → MSB):
    #   [verb_id : 11 bits] [preverb_id : 5 bits] [suffix_id : 5 bits]
    # = 21 bits per concept → 3 bytes per concept on disk.
    _VERB_BITS    = 11        # supports up to 2047 verbs
    _PREVERB_BITS = 5         # supports up to 31 preverbs
    _SUFFIX_BITS  = 5         # supports up to 31 suffixes
    _VERB_MASK    = (1 << _VERB_BITS) - 1
    _PREVERB_MASK = (1 << _PREVERB_BITS) - 1
    _SUFFIX_MASK  = (1 << _SUFFIX_BITS) - 1

    def pack(self) -> int:
        return ((self.verb_id    & self._VERB_MASK)
                | ((self.preverb_id & self._PREVERB_MASK)
                       << self._VERB_BITS)
                | ((self.suffix_id  & self._SUFFIX_MASK)
                       << (self._VERB_BITS + self._PREVERB_BITS)))

    @classmethod
    def unpack(cls, packed: int) -> 'Concept':
        v = packed & cls._VERB_MASK
        p = (packed >> cls._VERB_BITS) & cls._PREVERB_MASK
        s = (packed >> (cls._VERB_BITS + cls._PREVERB_BITS)) & cls._SUFFIX_MASK
        return cls(preverb_id=p, verb_id=v, suffix_id=s)

    def to_bytes(self) -> bytes:
        """Concept → 3 bytes (little-endian).  Fits cleanly in a
        4096-byte buffer: 4096 / 3 = 1365 concepts per buffer."""
        n = self.pack()
        return bytes([n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF])

    @classmethod
    def from_bytes(cls, b: bytes) -> 'Concept':
        if len(b) < 3:
            raise ValueError(f'need 3 bytes, got {len(b)}')
        n = b[0] | (b[1] << 8) | (b[2] << 16)
        return cls.unpack(n)

    def __str__(self) -> str:
        return f'<Concept {self.surface()} = {self.gloss()}>'
