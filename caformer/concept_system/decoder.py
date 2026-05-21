"""Concept(s) → text decoder.

Phase-1 implementation: compose the gloss strings of the concept's
parts into a readable English phrase.  Suffix overrides verb's bare
gloss with a nominalised reading.

A more sophisticated decoder would generate grammatical English
(article + noun, conjugated verb, agreeing pronouns).  Phase-1 just
renders the compositional sense legibly enough that a human can
verify the encoding.
"""
from __future__ import annotations

from typing import Sequence

from . import data as _data
from .concept import Concept


# Per-suffix verb→noun rendering templates.  The {gloss} is the
# verb's plain gloss; the template wraps it in a nominal reading.
_NOMINAL_TEMPLATES: dict[str, str] = {
    '-a':     'the {gloss}',                   # gama → 'the going'
    '-ana':   'the {gloss} (process or place)',
    '-ya':    'what must be {gloss}-ed',
    '-tṛ':    'one who {gloss}s',
    '-ti':    '{gloss}ing (as state)',
    '-aka':   'one who causes {gloss}',
    '-in':    'one having {gloss}',
    '-man':   '{gloss}-hood',
    '-ja':    'born of {gloss}',
    '-ta':    'one who has {gloss}',
    '-tum':   'to {gloss}',
    '-tvā':   'having {gloss}-ed',
    '-itva':  '{gloss}-ness',
    '-tavya': 'that which should be {gloss}-ed',
}


def decode(c: Concept) -> str:
    """Single-concept → English phrase."""
    if c.is_empty():
        return '(empty concept)'
    parts: list[str] = []
    pre_gloss = ''
    verb_gloss = ''
    if c.preverb_id:
        p = _data.preverb_by_id(c.preverb_id)
        if p is not None:
            pre_gloss = p.gloss
    if c.verb_id:
        v = _data.verb_by_id(c.verb_id)
        if v is not None:
            verb_gloss = v.gloss
    if c.suffix_id:
        s = _data.suffix_by_id(c.suffix_id)
        if s is not None:
            tmpl = _NOMINAL_TEMPLATES.get(s.form,
                                          '{gloss} (' + s.sense + ')')
            base = verb_gloss or 'do'
            nominal = tmpl.format(gloss=base)
            if pre_gloss:
                return f'{nominal} [{pre_gloss}]'
            return nominal
    # No suffix — verbal reading.
    if pre_gloss and verb_gloss:
        return f'{verb_gloss} [{pre_gloss}]'
    return verb_gloss or pre_gloss or '(unknown)'


def decode_all(concepts: Sequence[Concept]) -> str:
    """List of concepts → comma-joined English phrase."""
    parts = [decode(c) for c in concepts if not c.is_empty()]
    return '; '.join(parts) if parts else '(no concepts)'


def surface(c: Concept) -> str:
    """Render the IAST surface form via the Concept method."""
    return c.surface()
