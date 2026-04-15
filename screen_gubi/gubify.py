"""Gubify: deterministic mapping from a 2000-UTF-8-character input to
a set of typed variables.

The input is normalised to exactly 2000 code points (padded with
space or truncated). The schema names a slice of the input for each
variable and a decoder that turns the slice into a typed value. Every
decoder is total — any UTF-8 input yields a valid value — so the
pipeline never raises on exotic inputs.

Regions:
  - shared   [0..400]   general variables any Velour app may consume
  - lsystem  [400..2000] parameters for the L-System tree scene

If a future app wants its own region, carve it from the tail of the
lsystem region (and coordinate here) — the total length is fixed.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, List

PAD = ' '
TOTAL = 2000
LSYS_ALPHABET = list('FFFFFF+-[]X+-[]<>L')


def normalize(text: str) -> str:
    if len(text) >= TOTAL:
        return text[:TOTAL]
    return text + PAD * (TOTAL - len(text))


def _slice_sum(text: str, start: int, end: int) -> int:
    return sum(ord(c) for c in text[start:end])


# ---------- Decoders -------------------------------------------------
# Each decoder has signature (text, start, end) -> value.

def int_mod(n: int):
    def _d(text, s, e):
        return _slice_sum(text, s, e) % n
    return _d


def int_range(lo: int, hi: int):
    span = hi - lo + 1
    def _d(text, s, e):
        return lo + (_slice_sum(text, s, e) % span)
    return _d


def float_unit():
    """Float in [0, 1) via FNV-1a-ish mix of code points."""
    def _d(text, s, e):
        h = 2166136261
        for ch in text[s:e]:
            h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
        return h / 0x100000000
    return _d


def float_range(lo: float, hi: float):
    fu = float_unit()
    def _d(text, s, e):
        return lo + fu(text, s, e) * (hi - lo)
    return _d


def rgb_hex():
    """'#rrggbb' built by hashing three subslices (FNV-1a). Uses the
    slice *offsets* as well as content so pad-dominated slices at
    different positions still produce varied colors."""
    def _hash(text, s, e, salt):
        h = (2166136261 ^ salt) & 0xFFFFFFFF
        for i in range(s, e):
            h = ((h ^ ord(text[i])) * 16777619) & 0xFFFFFFFF
            h = ((h ^ i) * 16777619) & 0xFFFFFFFF
        return h

    def _d(text, s, e):
        n = max(1, e - s)
        third = n // 3 or 1
        r = _hash(text, s,             s + third,       0x52) & 0xFF
        g = _hash(text, s + third,     s + 2 * third,   0x47) & 0xFF
        b = _hash(text, s + 2 * third, e,               0x42) & 0xFF
        return '#{:02x}{:02x}{:02x}'.format(r, g, b)
    return _d


def choice_from(options: List[Any]):
    def _d(text, s, e):
        return options[_slice_sum(text, s, e) % len(options)]
    return _d


def str_printable(max_len: int = 32):
    """Distil a short printable string from the slice."""
    def _d(text, s, e):
        out = []
        for ch in text[s:e]:
            if ch.isprintable() and not ch.isspace():
                out.append(ch)
                if len(out) >= max_len:
                    break
        return ''.join(out)
    return _d


def array_of(decoder, n: int):
    def _d(text, s, e):
        step = (e - s) // n if n > 0 else 0
        result = []
        for i in range(n):
            a = s + i * step
            b = s + (i + 1) * step if i < n - 1 else e
            result.append(decoder(text, a, b))
        return result
    return _d


def lsys_rhs(max_len: int = 18):
    """Build a balanced-bracket L-system RHS from the slice.

    If the generated rule would be degenerate (no branches), fall back
    to a canonical branching rule so even padding-filled inputs still
    produce recognisable trees.
    """
    # Canonical branching rules seeded by the slice offset.
    FALLBACKS = [
        'F[+FL][-FL]F',
        'FF[+F][-F]',
        'F[+F[-FL]][-F[+FL]]',
        'F[<F][>F]F',
        'F[+FX]F[-FX]FX',
    ]

    def _d(text, s, e):
        seg = text[s:e]
        if not seg:
            return FALLBACKS[0]
        target = 4 + (_slice_sum(text, s, e) % max(1, max_len - 4))
        out, depth = [], 0
        for i in range(min(target, len(seg))):
            ch = LSYS_ALPHABET[ord(seg[i]) % len(LSYS_ALPHABET)]
            if ch == '[':
                depth += 1
            elif ch == ']' and depth == 0:
                ch = 'F'
            elif ch == ']':
                depth -= 1
            out.append(ch)
        out.extend([']'] * depth)
        rule = ''.join(out)
        if '[' not in rule:
            # Degenerate — inject a branching fallback, picked by the
            # slice offset so different rule slots differ.
            rule = FALLBACKS[s % len(FALLBACKS)]
        return rule or FALLBACKS[0]
    return _d


# ---------- Schema ---------------------------------------------------

@dataclass
class Var:
    name: str
    start: int
    end: int
    decoder: Callable
    region: str
    doc: str = ''


# Branch-draw strategies are named; the three.js side dispatches on
# the name. Python only needs the list.
BRANCH_DRAW_STRATEGIES = ['straight', 'curl', 'fan', 'jitter']


SHARED: List[Var] = [
    Var('seed',        0,    8, int_range(1, 999_999), 'shared'),
    Var('mood',        8,   24, choice_from(
        ['calm', 'bright', 'stormy', 'playful', 'solemn', 'wild']), 'shared'),
    Var('palette',    24,   60, array_of(rgb_hex(), 4), 'shared',
        '4-color palette for any consumer'),
    Var('bg_color',   60,   80, rgb_hex(), 'shared'),
    Var('fg_color',   80,  100, rgb_hex(), 'shared'),
    Var('title_hint', 100, 160, str_printable(24), 'shared'),
    Var('tags',       160, 240, array_of(str_printable(8), 4), 'shared'),
    Var('booleans',   240, 272, array_of(int_mod(2), 8), 'shared'),
    Var('rng_stream', 272, 400, array_of(int_mod(256), 16), 'shared',
        '16 bytes of noise'),
]


LSYSTEM: List[Var] = [
    Var('n_trees',         400,  408, int_range(1, 7), 'lsystem'),
    Var('tree_positions',  408,  520, array_of(
        array_of(float_range(-8.0, 8.0), 2), 7), 'lsystem'),
    Var('trunk_colors',    520,  604, array_of(rgb_hex(), 7), 'lsystem'),
    Var('leaf_colors',     604,  688, array_of(rgb_hex(), 7), 'lsystem'),
    Var('trunk_thickness', 688,  730, array_of(
        float_range(0.10, 0.32), 7), 'lsystem'),
    Var('tree_scales',     730,  772, array_of(
        float_range(0.8, 2.0), 7), 'lsystem'),
    Var('axiom',           772,  792, choice_from(
        ['F', 'FX', 'X', 'FFX', 'F[X]']), 'lsystem'),
    Var('rules',           792, 1200, array_of(lsys_rhs(18), 3), 'lsystem',
        'three production RHS for F, X, Y'),
    Var('iterations',     1200, 1208, int_range(3, 5), 'lsystem'),
    Var('branch_angle',   1208, 1240, float_range(14.0, 40.0), 'lsystem'),
    Var('length_factor',  1240, 1272, float_range(0.65, 0.88), 'lsystem'),
    Var('start_length',   1272, 1304, float_range(0.8, 1.4), 'lsystem'),
    Var('taper',          1304, 1336, float_range(0.55, 0.85), 'lsystem'),
    Var('droop',          1336, 1368, float_range(0.0, 0.15), 'lsystem'),
    Var('branch_draw',    1368, 1400, choice_from(BRANCH_DRAW_STRATEGIES),
        'lsystem'),
    Var('ground_color',   1400, 1420, rgb_hex(), 'lsystem'),
    Var('sky_top',        1420, 1440, rgb_hex(), 'lsystem'),
    Var('sky_bottom',     1440, 1460, rgb_hex(), 'lsystem'),
    Var('fog_near',       1460, 1480, float_range(8.0, 20.0), 'lsystem'),
    Var('fog_far',        1480, 1500, float_range(25.0, 60.0), 'lsystem'),
    Var('reserved',       1500, 2000, str_printable(16), 'lsystem',
        'unused tail — available for future L-system tweaks'),
]


SCHEMA: List[Var] = SHARED + LSYSTEM


def gubify(text: str) -> dict:
    """Return {var_name: value} plus 'text_normalized' and 'regions'."""
    norm = normalize(text)
    regions: dict = {'shared': {}, 'lsystem': {}}
    flat: dict = {}
    for v in SCHEMA:
        val = v.decoder(norm, v.start, v.end)
        regions[v.region][v.name] = val
        flat[v.name] = val
    return {'text_normalized': norm, 'regions': regions, **flat}


def lsystem_scene(vars_: dict) -> dict:
    """Turn gubified variables into a three.js-friendly scene spec."""
    n = vars_['n_trees']
    positions = vars_['tree_positions'][:n]
    trunk_colors = vars_['trunk_colors'][:n]
    leaf_colors = vars_['leaf_colors'][:n]
    thickness = vars_['trunk_thickness'][:n]
    scales = vars_['tree_scales'][:n]

    rules_list = vars_['rules']
    rules = {
        'F': rules_list[0] or 'F',
        'X': rules_list[1] or 'F[+FX][-FX]',
        'Y': rules_list[2] or 'F[-F][+F]',
    }

    trees = []
    for i in range(n):
        x, z = positions[i]
        trees.append({
            'x': x,
            'z': z,
            'trunk_color': trunk_colors[i],
            'leaf_color': leaf_colors[i],
            'trunk_thickness': thickness[i],
            'scale': scales[i],
        })

    return {
        'trees': trees,
        'axiom': vars_['axiom'],
        'rules': rules,
        'iterations': vars_['iterations'],
        'branch_angle_deg': vars_['branch_angle'],
        'length_factor': vars_['length_factor'],
        'start_length': vars_['start_length'],
        'taper': vars_['taper'],
        'droop': vars_['droop'],
        'branch_draw': vars_['branch_draw'],
        'ground_color': vars_['ground_color'],
        'sky_top': vars_['sky_top'],
        'sky_bottom': vars_['sky_bottom'],
        'fog_near': vars_['fog_near'],
        'fog_far': vars_['fog_far'],
        'seed': vars_['seed'],
    }
