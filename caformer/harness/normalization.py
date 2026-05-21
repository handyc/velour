"""Input reductions — deterministic projections of a prompt that
generalize matching across surface variants.

The simplest reduction is ``lower_no_punct``: lowercase, strip
all punctuation, collapse whitespace.  At dispatch time, when the
exact-prompt lookup misses, the harness tries this reduced form
against every QRPair's reduced prompt.  Cheap (one regex + one
string compare) and dramatically expands coverage:

    "Shall I compare thee to a summer's day?" — exact match miss
    → lower_no_punct →
    "shall i compare thee to a summer s day"
    matches the reduced form of every common-case variant
    ("Shall I compare thee...", "shall i compare thee...",
     "SHALL I COMPARE THEE!", etc.).

Phase 2 generalization (TODO): multiple reductions per input
(vowels-only, consonants-only, first-letters, length bucket,
byte histogram), each producing a *view* of the prompt that can
be matched against an independent index.  Different boards in
boardstack4 / byte_router could process different reductions to
produce a multidimensional fingerprint.

The reductions here are pure functions — same input always
produces the same output, no state, no model — so they compose
cleanly with the rest of the deterministic harness.
"""
from __future__ import annotations

import re
import unicodedata


# Match anything that isn't a letter, digit, or whitespace.
_NON_ALNUM = re.compile(r"[^\w\s]+", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def lower_no_punct(text: str) -> str:
    """Lowercase + strip punctuation + collapse whitespace.

    Unicode-aware: 'Café' → 'café' (lowercase) and surface punctuation
    like fancy quotes ("don't" → "don t") gets stripped uniformly.
    Returns the empty string for empty input.

    Reduction is *lossy* — distinct prompts may collapse to the
    same reduced form ("Hi!" and "hi" both → "hi") — that's the
    point: matching coverage > exactness."""
    if not text:
        return ''
    # NFC normalisation so visually-identical forms compare equal.
    s = unicodedata.normalize('NFC', text)
    s = s.lower()
    s = _NON_ALNUM.sub(' ', s)
    s = _WHITESPACE.sub(' ', s).strip()
    return s


# Stable list of all reductions the harness knows about.  Each entry
# is (name, function).  At dispatch time the harness can try them
# in priority order; the first one that finds a match wins.
ALL_REDUCTIONS: list[tuple[str, callable]] = [
    ('lower_no_punct', lower_no_punct),
]


def reduce(text: str, name: str = 'lower_no_punct') -> str:
    """Look up a reduction by name and apply it.  Raises ValueError
    on unknown name to surface authoring errors visibly."""
    for n, fn in ALL_REDUCTIONS:
        if n == name:
            return fn(text)
    raise ValueError(f'unknown reduction {name!r}; '
                     f'available: {[n for n, _ in ALL_REDUCTIONS]}')
