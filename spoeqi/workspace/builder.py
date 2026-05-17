"""builder.py — load template ELFs and patch their sentinel slots.

A template ELF is a no-libc Linux x86_64 binary with `static const`
arrays carrying an 8-byte magic prefix `CAFE BABE 00 00 00 NN` followed
by `n` placeholder bytes.  The patcher locates each magic prefix and
overwrites the next `n` bytes with caller-supplied values.  Patched
output is padded with NUL up to exactly 4096 bytes.

Determinism guarantees:
  - Same template + same slot map → same 4096 byte output. Bit-identical.
  - The template ELF is checked into git so reproducibility doesn't
    depend on the local toolchain version.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SLOT_MAGIC = b'\xca\xfe\xba\xbe\x00\x00\x00'   # 7 bytes; full magic = MAGIC + id
APP_BYTES  = 4096                              # one hexhunter slot

TEMPLATES_DIR = Path(__file__).parent / 'templates'


@dataclass(frozen=True)
class Slot:
    """One patchable region in a template ELF."""
    id: int          # the NN byte appended to SLOT_MAGIC
    width: int       # bytes available after the 8-byte prefix
    name: str        # human-readable label (for diagnostics)


@dataclass(frozen=True)
class Template:
    """A compiled template + its slot inventory.  Slots are indexed by
    name so the slot derivation logic doesn't have to know wire IDs."""
    name: str
    elf_bytes: bytes
    slots: dict[str, Slot]

    @classmethod
    def load(cls, name: str, slots: list[Slot]) -> 'Template':
        path = TEMPLATES_DIR / f'{name}.elf'
        elf  = path.read_bytes()
        if len(elf) != APP_BYTES:
            raise ValueError(
                f'template {name!r} is {len(elf)} B, expected {APP_BYTES}')
        slot_map = {s.name: s for s in slots}
        # Sanity: each slot magic must appear exactly once in the ELF.
        for s in slots:
            magic = SLOT_MAGIC + bytes([s.id])
            occ = elf.count(magic)
            if occ != 1:
                raise ValueError(
                    f'template {name!r}: slot {s.name!r} (id={s.id:#04x}) '
                    f'matched {occ} times in ELF, expected exactly 1')
        return cls(name=name, elf_bytes=elf, slots=slot_map)

    def offset_of(self, slot_name: str) -> int:
        """Byte offset of the slot's *data* (skipping the 8-byte magic)."""
        s = self.slots[slot_name]
        magic = SLOT_MAGIC + bytes([s.id])
        return self.elf_bytes.index(magic) + 8


def patch(template: Template, values: dict[str, bytes]) -> bytes:
    """Return a 4096-byte ELF with each slot in `values` overwritten.

    Values longer than the slot width are truncated; shorter values are
    padded on the right with spaces (so ANSI sequences stay parseable
    and ASCII text stays readable).  Slots not mentioned in `values`
    keep their template default.
    """
    out = bytearray(template.elf_bytes)
    for slot_name, payload in values.items():
        s = template.slots[slot_name]
        if len(payload) > s.width:
            payload = payload[:s.width]
        elif len(payload) < s.width:
            payload = payload + b' ' * (s.width - len(payload))
        offset = template.offset_of(slot_name)
        out[offset:offset + s.width] = payload
    if len(out) != APP_BYTES:
        raise AssertionError(f'patched ELF is {len(out)} B, expected {APP_BYTES}')
    return bytes(out)


# ─── Concrete template registry ────────────────────────────────────

# Slot widths must match the C source declarations in templates/<name>.c.
# Keep this in sync with the SLOT(...) macros there.

GREETER_SLOTS = [
    Slot(id=0x01, width=16, name='color'),
    Slot(id=0x02, width=32, name='greeting'),
    Slot(id=0x03, width=24, name='pact_id'),
    Slot(id=0x04, width=16, name='footer'),
]


def load_greeter() -> Template:
    return Template.load('app0_greeter', GREETER_SLOTS)


# App 1 — mandelbrot: cx/cy/span as IEEE 754 doubles, iter/W/H as u32.
MANDEL_SLOTS = [
    Slot(id=0x11, width=8, name='cx'),
    Slot(id=0x12, width=8, name='cy'),
    Slot(id=0x13, width=8, name='span'),
    Slot(id=0x14, width=4, name='iter'),
    Slot(id=0x15, width=4, name='term_w'),
    Slot(id=0x16, width=4, name='term_h'),
]


def load_mandel() -> Template:
    return Template.load('app1_mandel', MANDEL_SLOTS)


# App 2 — hex CA viewer (self-referential).
CAVIEW_SLOTS = [
    Slot(id=0x21, width=8, name='rule_seed'),
    Slot(id=0x22, width=8, name='init_seed'),
    Slot(id=0x23, width=4, name='ticks'),
    Slot(id=0x24, width=4, name='size'),
]


def load_caview() -> Template:
    return Template.load('app2_caview', CAVIEW_SLOTS)
