"""slots.py — derive App slot values from a Pact's CA bytes.

Pure function, no LLM dependency yet — the v1 design pulls bytes from
``spoeqi.keystream.tap`` and maps them to slot payloads through a
hand-written table.  The minGPT step (CA bytes → prompt → text → slot
values) lands in v2; the wire-format from this module won't change
when that swap happens.

Determinism: same (Pact, tick, slot_index) → same bytes → same slot
values → byte-identical ELF.
"""

from __future__ import annotations
import struct

from .builder import (
    APP_BYTES, Template, load_caview, load_greeter, load_mandel, patch,
)
from .. import keystream


# ─── colour palette (16 ANSI fg+bg combinations) ────────────────────
# Each entry is a complete `\033[1;FG;BGm` opener exactly 16 bytes long
# (padded with trailing spaces so ANSI parsing stops at `m`).  Picked
# for legibility on a default black/grey terminal.
_PALETTE = [
    b'\x1b[1;31;40m   ', b'\x1b[1;32;40m   ', b'\x1b[1;33;40m   ',
    b'\x1b[1;34;40m   ', b'\x1b[1;35;40m   ', b'\x1b[1;36;40m   ',
    b'\x1b[1;37;40m   ', b'\x1b[1;30;47m   ',
    b'\x1b[1;33;41m   ', b'\x1b[1;37;41m   ', b'\x1b[1;33;42m   ',
    b'\x1b[1;30;43m   ', b'\x1b[1;37;44m   ', b'\x1b[1;33;44m   ',
    b'\x1b[1;30;45m   ', b'\x1b[1;33;45m   ',
]


# ─── greeting / footer phrase tables ────────────────────────────────
# Hand-written; CA bytes pick an index.  These are the v1 stand-ins
# for what minGPT will eventually compose from CA-derived prompts.

_GREETING_VERBS = [
    'hello from', 'salutations to', 'welcome from', 'a sign from',
    'transmission from', 'pact-greeting to', 'a glyph from', 'beacon from',
]
_GREETING_NOUNS = [
    'the substrate', 'a quiet pact', 'the deterministic floor',
    'a sealed pact', 'the rule library', 'an entangled set',
    'the spoeqi grid', 'the slot tail',
]

# Each footer is exactly 16 bytes — the slot width.  The builder will
# truncate or pad, but spelling them out keeps the verification output
# legible without relying on patcher behaviour.
_FOOTERS = [
    b'~ byte-identical',
    b'~ same-seed/same',
    b'~ no entropy in ',
    b'~ deterministic ',
    b'~ verified-tap  ',
    b'~ pact-confirmed',
    b'~ tick reprised ',
    b'~ all-zero RNG  ',
]


def _pick(byte: int, table: list) -> object:
    """Index into a table by a single CA-derived byte."""
    return table[byte % len(table)]


def derive_greeter_values(pact, tick: int, slot_index: int = 0) -> dict[str, bytes]:
    """CA bytes → slot payloads for app0_greeter.

    Tap `pact` for the (slot_index, tick) stream and use 4 bytes to
    pick from the palette / phrase tables.  The pact_id slot embeds
    the pact slug + tick as a verifiable label researchers can compare.
    """
    raw = keystream.tap(pact, slot_index, tick, 8)
    color    = _PALETTE[raw[0] % len(_PALETTE)]
    verb     = _pick(raw[1], _GREETING_VERBS)
    noun     = _pick(raw[2], _GREETING_NOUNS)
    footer   = _pick(raw[3], _FOOTERS)

    greeting = f'{verb} {noun}'.encode('ascii')[:32]
    pact_id  = f'pact={pact.slug[:8]:<8} tick={tick:05d}'.encode('ascii')[:24]

    return {
        'color':    color,
        'greeting': greeting,
        'pact_id':  pact_id,
        'footer':   footer,
    }


def render_greeter_elf(pact, tick: int, slot_index: int = 0) -> bytes:
    """End-to-end: pact + tick → 4096-byte runnable ELF."""
    template = load_greeter()
    values   = derive_greeter_values(pact, tick, slot_index)
    elf      = patch(template, values)
    assert len(elf) == APP_BYTES
    return elf


# ─── App 1 (mandelbrot) ─────────────────────────────────────────────
#
# Curated zoom presets — same set loupe seeds in its UI.  CA byte 0
# picks one; later iterations can layer in CA-derived jitter on
# (cx, cy, span) so every tick is a slightly different vista.

_PRESETS = [
    # (cx,         cy,        span,    iter)
    (-0.5,         0.0,       3.0,     192),   # whole set
    (-0.75,        0.11,      0.16,    256),   # seahorse valley
    ( 0.275,       0.0,       0.07,    320),   # elephant valley
    (-0.7453,      0.1127,    0.0034,  512),   # triple spiral
    (-1.768,       0.0,       0.04,    320),   # period-3 minibrot
    (-1.99975,     0.0,       0.001,  1024),   # lightning
    (-1.25,        0.0,       0.04,    256),   # left bulb
    (-0.16,        1.04,      0.04,    256),   # north tendril
]

# Conservative defaults that fit a typical 100×30 terminal without
# making the render too slow.  Researcher's actual term size still
# clamps these down at runtime.
_TERM_W = 100
_TERM_H = 30


def derive_mandel_values(pact, tick: int, slot_index: int = 0) -> dict[str, bytes]:
    """CA bytes → (cx, cy, span, iter) for app1_mandel.

    Byte 0 picks one of the 8 presets; each tick of the same pact
    visits the next preset in the orbit so the workspace cycles
    through interesting locations.
    """
    raw = keystream.tap(pact, slot_index, tick, 4)
    cx, cy, span, iter_cap = _PRESETS[raw[0] % len(_PRESETS)]
    return {
        'cx':     struct.pack('<d', cx),
        'cy':     struct.pack('<d', cy),
        'span':   struct.pack('<d', span),
        'iter':   struct.pack('<I', iter_cap),
        'term_w': struct.pack('<I', _TERM_W),
        'term_h': struct.pack('<I', _TERM_H),
    }


def render_mandel_elf(pact, tick: int, slot_index: int = 0) -> bytes:
    template = load_mandel()
    values   = derive_mandel_values(pact, tick, slot_index)
    elf      = patch(template, values)
    assert len(elf) == APP_BYTES
    return elf


# ─── App 2 (hex CA viewer) ──────────────────────────────────────────
#
# Self-referential: the substrate's keystream picks the rule + initial
# state for the substrate the rendered ELF will run.  The same
# Park-Miller LCG (state * 1103515245 + 12345) the C app uses to
# expand seeds is also used in spoeqi.keystream itself, so the chain
# is deterministic end-to-end.

def derive_caview_values(pact, tick: int, slot_index: int = 0) -> dict[str, bytes]:
    raw = keystream.tap(pact, slot_index, tick, 24)
    rule_seed = int.from_bytes(raw[0:8],  'little')
    init_seed = int.from_bytes(raw[8:16], 'little')
    # Ticks: tap byte 16 → 8..56 in steps of 4 (12 buckets).  Keeps
    # render time bounded while letting different ticks reach quite
    # different fixed-points.
    n_ticks   = 8 + 4 * (raw[16] % 12)
    # Size: tap byte 17 → 16..40 in steps of 2 (12 buckets).
    side      = 16 + 2 * (raw[17] % 12)
    return {
        'rule_seed': rule_seed.to_bytes(8, 'little'),
        'init_seed': init_seed.to_bytes(8, 'little'),
        'ticks':     n_ticks.to_bytes(4, 'little'),
        'size':      side.to_bytes(4, 'little'),
    }


def render_caview_elf(pact, tick: int, slot_index: int = 0) -> bytes:
    template = load_caview()
    values   = derive_caview_values(pact, tick, slot_index)
    elf      = patch(template, values)
    assert len(elf) == APP_BYTES
    return elf
