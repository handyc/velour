"""Phrase layer — one level above the word binder.

Recursive architecture, exactly the same shape as word_binder_v2:

  chain[s, p, c]  takes the s-th prompt-word (alone) as input,
                  emits cell c of phrase-ID at output position p.
  phrase ID → look up in phrase vocab → list of word IDs
  word ID   → look up in word vocab → string token
  output    = ' '.join(string tokens) across all (slot, pos, expansion)

Phrase vocab = unique whole responses from the training corpus.  Each
phrase is stored as a *list of word IDs* (from the underlying word
vocab), so the expansion really walks two levels: phrase → words →
bytes.  The compositional power comes from one chain firing emitting
a multi-word atom in one step.

The point of this layer in the recursive stack:
- byte:   one ID = one byte (256 atoms, 4 cells per ID)
- word:   one ID = one word in vocab (~20 atoms, 3 cells per ID)
- phrase: one ID = one whole response in vocab (~14 atoms, 3 cells per ID)

Storage scales sub-linearly because the per-slot chains stay the
same size at every level — only the vocab grows.  Recursive stacking
(metaphrase, discourse, …) is just "add another vocab + train chains
on it"; the architecture doesn't change.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from caformer.word_binder_v2 import (
    LUT_SIZE, N_STATES, STOP_ID, UNK_ID, MAX_INPUT_SLOTS, MAX_OUT_PER_SLOT,
    _embed_word, _run, tokenize,
)


def build_phrase_vocab(responses: list[str], word_vocab: dict) -> dict:
    """Phrase vocab from unique whole responses; each phrase stores the
    list of word IDs that compose it.  Index 0 = '' (STOP), index 1 =
    '?' (UNK)."""
    seen_phrases: list[str] = []
    seen_set = set()
    for resp in responses:
        if resp not in seen_set:
            seen_set.add(resp)
            seen_phrases.append(resp)
    seen_phrases.sort()
    phrases = ['', '?'] + seen_phrases
    # Build expansion table: phrase ID → list of word IDs.
    expansions: list[list[int]] = []
    for phrase in phrases:
        if not phrase:
            expansions.append([])
        else:
            word_ids = [word_vocab['id_of'].get(t, UNK_ID)
                          for t in tokenize(phrase)]
            expansions.append(word_ids)
    v = len(phrases)
    k_cells = 1
    while N_STATES ** k_cells < v:
        k_cells += 1
    return {
        'phrases':     phrases,
        'expansions':  expansions,
        'id_of':       {p: i for i, p in enumerate(phrases)},
        'k_cells':     k_cells,
        'size':        v,
    }


def training_targets(prompt: str, response: str, phrase_vocab: dict,
                       max_slots: int = MAX_INPUT_SLOTS) -> dict:
    """One phrase ID per pair → goes into the last input slot."""
    p_words = tokenize(prompt)[:max_slots]
    last_slot = len(p_words) - 1
    targets = {}
    if last_slot < 0:
        return targets
    for s in range(last_slot):
        targets[(s, 0)] = STOP_ID
    pid = phrase_vocab['id_of'].get(response, UNK_ID)
    targets[(last_slot, 0)] = pid
    # Optional STOP at next pos so decode terminates cleanly:
    targets[(last_slot, 1)] = STOP_ID
    return targets


class PhraseBinder:
    def __init__(self, model_dir: Path, ticks: int = 6):
        self.model_dir = Path(model_dir)
        self.ticks = ticks
        meta = json.loads((self.model_dir / 'phrase_vocab.json').read_text())
        self.vocab = {
            'phrases':    meta['phrases'],
            'expansions': meta['expansions'],
            'id_of':      {p: i for i, p in enumerate(meta['phrases'])},
            'k_cells':    meta['k_cells'],
            'size':       len(meta['phrases']),
        }
        self.word_vocab = meta.get('word_vocab', {})
        self.k_cells = meta['k_cells']
        self.max_slots = meta.get('max_slots', MAX_INPUT_SLOTS)
        self.max_out = meta.get('max_out', MAX_OUT_PER_SLOT)
        self.chains: dict[tuple[int, int], list[np.ndarray]] = {}
        for f in sorted(self.model_dir.glob('chain_s*_p*_c*.lut')):
            stem = f.stem
            parts = stem.split('_')
            s = int(parts[1][1:]); p = int(parts[2][1:]); c = int(parts[3][1:])
            arr = np.frombuffer(f.read_bytes(), dtype=np.uint8) & 3
            self.chains.setdefault((s, p), [None] * self.k_cells)[c] = arr
        for (s, p), cells in self.chains.items():
            if any(c is None for c in cells):
                missing = [i for i, c in enumerate(cells) if c is None]
                raise ValueError(f'(slot {s}, pos {p}): missing cells {missing}')

    def generate(self, prompt: str) -> dict:
        prompt_words = tokenize(prompt)[:self.max_slots]
        all_phrase_ids: list[int] = []
        all_phrases:    list[str] = []
        all_text_parts: list[str] = []
        per_slot: list[dict] = []
        unk = 0
        for s, pw in enumerate(prompt_words):
            stim = _embed_word(pw)
            slot_phrases: list[str] = []
            slot_ids: list[int] = []
            for p in range(self.max_out):
                key = (s, p)
                if key not in self.chains:
                    break
                cells = self.chains[key]
                pid = 0
                for c in range(self.k_cells):
                    pid = (pid << 2) | int(_run(cells[c], stim, self.ticks)[0, 0])
                slot_ids.append(pid); all_phrase_ids.append(pid)
                if pid == STOP_ID:
                    break
                if 0 <= pid < self.vocab['size']:
                    phrase = self.vocab['phrases'][pid]
                    if pid == UNK_ID: unk += 1
                    slot_phrases.append(phrase)
                    all_phrases.append(phrase)
                    if phrase:
                        all_text_parts.append(phrase)
                else:
                    unk += 1
                    slot_phrases.append(f'<phrase:{pid}>')
                    all_phrases.append(f'<phrase:{pid}>')
            per_slot.append({'input_word': pw,
                               'output_phrases': slot_phrases,
                               'output_ids': slot_ids})
        return {
            'phrase_ids':     all_phrase_ids,
            'phrases':        all_phrases,
            'text':           ' '.join(p for p in all_text_parts if p),
            'unk_count':      unk,
            'per_slot':       per_slot,
            'n_input_slots':  len(prompt_words),
            'vocab_size':     self.vocab['size'],
        }


_CACHE: dict[tuple[str, int], PhraseBinder] = {}
_LOCK = threading.Lock()


def get_model(model_dir: str | Path, ticks: int = 6) -> PhraseBinder:
    key = (str(model_dir), ticks)
    with _LOCK:
        if key not in _CACHE:
            _CACHE[key] = PhraseBinder(Path(model_dir), ticks=ticks)
        return _CACHE[key]
