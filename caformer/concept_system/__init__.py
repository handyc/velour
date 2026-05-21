"""caformer.concept_system — Sanskrit verb-preverb-suffix concept
substrate.

A ~4 KB on-disk vocabulary of:
  - ~2000 verb roots (dhātus)             — Phase 1 seeds 64
  - 20 preverbs (upasargas)               — full
  - 16 kṛt nominalising suffixes          — full

Forms a compositional concept space of ~640,000 (preverb × verb ×
suffix) tuples while storing only the components.  Acts as an
interlingua: English text → Concept(s) → English text.

Public API:
    encode(text) -> list[Concept]
    decode(c)    -> str
    Concept(preverb_id, verb_id, suffix_id) — packs to 3 bytes
"""
from __future__ import annotations

from .concept import Concept
from .data import (VerbRoot, Preverb, KritSuffix,
                            VERB_ROOTS, PREVERBS, KRIT_SUFFIXES,
                            verb_by_id, preverb_by_id, suffix_by_id,
                            verb_by_root, preverb_by_form, suffix_by_form,
                            bit_budget)
from .encoder import encode, VERB_ALIASES, PREVERB_ALIASES, SUFFIX_ALIASES
from .decoder import decode, decode_all, surface

__all__ = [
    'Concept',
    'VerbRoot', 'Preverb', 'KritSuffix',
    'VERB_ROOTS', 'PREVERBS', 'KRIT_SUFFIXES',
    'verb_by_id', 'preverb_by_id', 'suffix_by_id',
    'verb_by_root', 'preverb_by_form', 'suffix_by_form',
    'bit_budget',
    'encode', 'decode', 'decode_all', 'surface',
    'VERB_ALIASES', 'PREVERB_ALIASES', 'SUFFIX_ALIASES',
]
