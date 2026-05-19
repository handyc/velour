"""Word-binder v2 — per-INPUT-SLOT chains for compositional binding.

v1 was: per-OUTPUT-position chains taking the *whole prompt* as input.
That memorises (prompt → response sequence) but has no inductive bias
toward compositional generalisation.

v2 is:    chain[s, p, c]    where
            s = input slot      (0 = first word of prompt, 1 = second, …)
            p = output sub-position (0 = first response word for this slot, …)
            c = decoder cell    (cell c of the K-cell base-4 word ID)

Input to chain[s, p, c] = embedded(prompt_words[s]) ONLY — one word
at a time, not the whole prompt.  This forces each slot's output to
depend only on the word at that slot.  At inference:

    prompt → tokenize → [pw_0, ..., pw_M-1]
    for s in 0..M-1:
        for p in 0..MAX_OUT_PER_SLOT-1:
            wid = decode(chain[s, p, *], embed(pw_s))
            if wid == STOP: break
            else: emit vocab[wid]

Compositional payoff: 'look up wolves' routes wolves through chain
slot 2, which was trained on {bees, cats, dogs, ants} → URLs.  Even
though wolves wasn't trained, the slot-2 chain has the inductive bias
that "whatever word is here, emit a URL-like token."  Likely produces
one of the trained URLs (closest embedding); won't synthesize URL_WOLF
(vocab is fixed) but demonstrates compositional structure.

Training assignment heuristic:
- prompt_words, response_words = tokenize(prompt), tokenize(response)
- last_slot = len(prompt_words) - 1
- For s in 0..last_slot-1: chain[s, 0] target = STOP (silent slots)
- For s == last_slot: chain[s, p] target = response_words[p] (or STOP if past end)
- Result: the LAST input word carries the whole response.

Why last_slot: matches the natural reading "the response is determined
by the last meaningful word of the prompt" (subject/object of imperative).
For 'look up bees': 'look' and 'up' route silent, 'bees' produces URL.

Storage: S slots × P positions × K cells × 16 KB.  Defaults
(8 × 4 × 3 × 16 KB) ≈ 1.5 MB.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

import numpy as np


N_STATES         = 4
LUT_SIZE         = N_STATES ** 7
SIDE             = 8
STOP_ID          = 0
UNK_ID           = 1
MAX_INPUT_SLOTS  = 8     # tokenizes prompts up to 8 words; rest truncated
MAX_OUT_PER_SLOT = 6     # up to 6 response words emitted per input slot


def _embed_word(word: str, side: int = SIDE) -> np.ndarray:
    """Embed a single word into a side×side K=4 board (top-left,
    4 base-4 digits per byte).  Word is truncated to side²/4 bytes."""
    n_cells = side * side
    bytes_per_board = n_cells // 4
    raw = word.encode('utf-8')[:bytes_per_board]
    out = np.zeros(n_cells, dtype=np.uint8)
    for i, b in enumerate(raw):
        out[i * 4 + 0] = (b >> 6) & 3
        out[i * 4 + 1] = (b >> 4) & 3
        out[i * 4 + 2] = (b >> 2) & 3
        out[i * 4 + 3] =  b       & 3
    return out.reshape(side, side)


def _run(rule_arr: np.ndarray, state0: np.ndarray, ticks: int) -> np.ndarray:
    from caformer.primitives import hex_ca_step
    state = state0.copy()
    for _ in range(ticks):
        state = hex_ca_step(state, rule_arr)
    return state


def tokenize(text: str) -> list[str]:
    return text.split()


def build_vocab(responses: list[str]) -> dict:
    seen = set()
    for resp in responses:
        for tok in tokenize(resp):
            seen.add(tok)
    sorted_words = sorted(seen)
    words = ['', '?'] + sorted_words
    id_of = {w: i for i, w in enumerate(words)}
    v = len(words)
    k_cells = 1
    while N_STATES ** k_cells < v:
        k_cells += 1
    return {'words': words, 'id_of': id_of, 'k_cells': k_cells, 'size': v}


def training_targets(prompt: str, response: str, vocab: dict,
                       max_slots: int = MAX_INPUT_SLOTS,
                       max_out: int = MAX_OUT_PER_SLOT) -> dict:
    """Returns dict[(slot, pos)] = word_id (target for chain[slot, pos]).
    Slots not in the dict have no target for this pair (don't train on it).

    Heuristic: response goes into the LAST input slot's output sequence.
    Other input slots emit STOP at position 0 (silent slots)."""
    p_words = tokenize(prompt)[:max_slots]
    r_words = tokenize(response)
    last_slot = len(p_words) - 1
    targets = {}
    if last_slot < 0:
        return targets
    for s in range(last_slot):
        targets[(s, 0)] = STOP_ID   # silent
    # Last slot carries the response
    for p in range(max_out):
        if p < len(r_words):
            targets[(last_slot, p)] = vocab['id_of'].get(r_words[p], UNK_ID)
        elif p == len(r_words):
            targets[(last_slot, p)] = STOP_ID
        # past STOP: no target (don't constrain)
    return targets


class WordBinderV2:
    def __init__(self, model_dir: Path, ticks: int = 6):
        self.model_dir = Path(model_dir)
        self.ticks = ticks
        meta = json.loads((self.model_dir / 'vocab.json').read_text())
        self.vocab = {
            'words': meta['words'],
            'id_of': {w: i for i, w in enumerate(meta['words'])},
            'k_cells': meta['k_cells'],
            'size': len(meta['words']),
        }
        self.k_cells = meta['k_cells']
        self.max_slots = meta.get('max_slots', MAX_INPUT_SLOTS)
        self.max_out = meta.get('max_out', MAX_OUT_PER_SLOT)
        self.chains: dict[tuple[int, int], list[np.ndarray]] = {}
        for f in sorted(self.model_dir.glob('chain_s*_p*_c*.lut')):
            stem = f.stem  # chain_sSS_pPP_cC
            parts = stem.split('_')
            s = int(parts[1][1:])
            p = int(parts[2][1:])
            c = int(parts[3][1:])
            arr = np.frombuffer(f.read_bytes(), dtype=np.uint8) & 3
            self.chains.setdefault((s, p), [None] * self.k_cells)[c] = arr
        for (s, p), cells in self.chains.items():
            if any(c is None for c in cells):
                missing = [i for i, c in enumerate(cells) if c is None]
                raise ValueError(f'(slot {s}, pos {p}): missing cells {missing}')

    def generate(self, prompt: str) -> dict:
        prompt_words = tokenize(prompt)[:self.max_slots]
        all_words: list[str] = []
        all_ids: list[int] = []
        per_slot_words: list[dict] = []
        unk = 0
        for s, pw in enumerate(prompt_words):
            slot_words: list[str] = []
            slot_ids: list[int] = []
            stim = _embed_word(pw)
            for p in range(self.max_out):
                key = (s, p)
                if key not in self.chains:
                    break
                cells = self.chains[key]
                wid = 0
                for c in range(self.k_cells):
                    wid = (wid << 2) | int(_run(cells[c], stim, self.ticks)[0, 0])
                slot_ids.append(wid)
                all_ids.append(wid)
                if wid == STOP_ID:
                    break
                if 0 <= wid < self.vocab['size']:
                    tok = self.vocab['words'][wid]
                    if wid == UNK_ID: unk += 1
                    slot_words.append(tok)
                    all_words.append(tok)
                else:
                    unk += 1
                    slot_words.append(f'<{wid}>')
                    all_words.append(f'<{wid}>')
            per_slot_words.append({'input_word': pw,
                                     'output_words': slot_words,
                                     'output_ids': slot_ids})
        return {
            'word_ids':       all_ids,
            'words':          all_words,
            'text':           ' '.join(w for w in all_words if w),
            'unk_count':      unk,
            'per_slot':       per_slot_words,
            'n_input_slots':  len(prompt_words),
        }


_CACHE: dict[tuple[str, int], WordBinderV2] = {}
_LOCK = threading.Lock()


def get_model(model_dir: str | Path, ticks: int = 6) -> WordBinderV2:
    key = (str(model_dir), ticks)
    with _LOCK:
        if key not in _CACHE:
            _CACHE[key] = WordBinderV2(Path(model_dir), ticks=ticks)
        return _CACHE[key]
