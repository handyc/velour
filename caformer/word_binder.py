"""Word-level binder layer for hierarchical CA-LLM composition.

Mirrors caformer.funnel_serve / caformer_funnel_tokens (the validated
byte-level per-cell-chain layer) one level up: instead of each output
*position* emitting a *byte*, it emits a *word ID* from a static
vocab table.  The bytes for that word are looked up + concatenated
with spaces.

Architecture per output word position w in {0..W-1}:

  prompt → 4×4 K=4 embedding (top-left, 4 base-4 digits/byte)
  for each cell c in {0..K-1}:    # K = ceil(log4(V)), cells per word ID
    R[w, c] runs T ticks on the embedding → cell (0,0) = base-4 digit c
  word_id_w = (digit_0 << ((K-1)*2)) | (digit_1 << ((K-2)*2)) | ... | digit_{K-1}
  if word_id_w == STOP_ID: break
  emit vocab[word_id_w]

Decoded response = ' '.join(emitted words).

Vocab construction:
- STOP token at index 0 (all-zero output = empty response, conservative default)
- Followed by all unique whitespace-tokens from the training response set
- Optional UNK at index 1 (so out-of-vocab decodes don't crash)

Storage: W word positions × K cells × 16,384 B = small (e.g., 8 × 3 × 16 KB = 384 KB).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

import numpy as np


N_STATES = 4
LUT_SIZE = N_STATES ** 7
SIDE     = 8   # 8×8 K=4 grid = 64 cells = fits 16 bytes of prompt; 4×4 was
               # too small — multi-word prompts like 'look up bees' share
               # the first 4 bytes and become indistinguishable in a 4×4
               # embedding.
STOP_ID  = 0   # reserved — vocab[0] = '' (sentinel, never decoded as text)
UNK_ID   = 1   # reserved — vocab[1] = '?' (returned for out-of-vocab decodes)


def _embed_prompt(prompt: str, side: int = SIDE) -> np.ndarray:
    n_cells = side * side
    bytes_per_board = n_cells // 4
    raw = prompt.encode('utf-8')[:bytes_per_board]
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
    """Whitespace tokenizer.  Each non-empty whitespace-separated chunk
    is one token.  URLs / punctuation-bearing words are atomic."""
    return text.split()


def build_vocab(responses: list[str]) -> dict:
    """Build a vocab table from a list of response strings.

    Returns dict with:
      'words':    list of words (index = ID); index 0 = '' (STOP),
                  index 1 = '?' (UNK), rest = corpus words sorted.
      'id_of':    word → ID lookup.
      'k_cells':  number of base-4 cells needed to encode the vocab.
    """
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


def encode_response(resp: str, vocab: dict, max_positions: int) -> list[int]:
    """Tokenize a response → list of word IDs, padded with STOP_ID to
    max_positions.  Tokens not in vocab → UNK_ID."""
    ids = [vocab['id_of'].get(t, UNK_ID) for t in tokenize(resp)]
    return ids[:max_positions] + [STOP_ID] * max(0, max_positions - len(ids))


def cell_targets_for_position(word_ids: list[int], pos: int,
                                 cell: int, k_cells: int) -> int:
    """Returns the base-4 digit (0..3) that R[pos, cell] should produce
    for a given word ID at position pos.  cell ∈ {0..k_cells-1}, with
    cell 0 = most-significant digit."""
    wid = word_ids[pos]
    shift = (k_cells - 1 - cell) * 2
    return (wid >> shift) & 3


class WordBinderModel:
    """Loaded word-binder: chains + vocab + decode."""

    def __init__(self, model_dir: Path, ticks: int = 6):
        self.model_dir = Path(model_dir)
        self.ticks = ticks
        meta_path = self.model_dir / 'vocab.json'
        meta = json.loads(meta_path.read_text())
        self.vocab = {
            'words': meta['words'],
            'id_of': {w: i for i, w in enumerate(meta['words'])},
            'k_cells': meta['k_cells'],
            'size': len(meta['words']),
        }
        self.max_positions = meta['max_positions']
        self.k_cells = meta['k_cells']
        self.chains: dict[int, list[np.ndarray]] = {}
        for f in sorted(self.model_dir.glob('chain_w*_c*.lut')):
            stem = f.stem  # chain_wWW_cC
            parts = stem.split('_')
            w = int(parts[1][1:])
            c = int(parts[2][1:])
            arr = np.frombuffer(f.read_bytes(), dtype=np.uint8) & 3
            self.chains.setdefault(w, [None] * self.k_cells)[c] = arr
        for w, cells in self.chains.items():
            if any(c is None for c in cells):
                missing = [i for i, c in enumerate(cells) if c is None]
                raise ValueError(f'position {w}: missing cells {missing}')

    def generate(self, prompt: str,
                   max_positions: Optional[int] = None) -> dict:
        """Run the chains, decode, return dict with words, ids, text."""
        stim = _embed_prompt(prompt)
        n_pos = max_positions if max_positions is not None else self.max_positions
        ids: list[int] = []
        words: list[str] = []
        unk_count = 0
        for w in range(n_pos):
            if w not in self.chains:
                break
            cells = self.chains[w]
            wid = 0
            for c in range(self.k_cells):
                wid = (wid << 2) | int(_run(cells[c], stim, self.ticks)[0, 0])
            ids.append(wid)
            if wid == STOP_ID:
                break
            if 0 <= wid < self.vocab['size']:
                tok = self.vocab['words'][wid]
                if wid == UNK_ID:
                    unk_count += 1
                words.append(tok)
            else:
                unk_count += 1
                words.append(f'<{wid}>')   # out-of-table — show numeric
        return {
            'word_ids':  ids,
            'words':     words,
            'text':      ' '.join(w for w in words if w),
            'unk_count': unk_count,
            'stopped':   len(ids) > 0 and ids[-1] == STOP_ID,
        }


# Module-level cache (matches funnel_serve)
_CACHE: dict[tuple[str, int], WordBinderModel] = {}
_LOCK = threading.Lock()


def get_model(model_dir: str | Path, ticks: int = 6) -> WordBinderModel:
    key = (str(model_dir), ticks)
    with _LOCK:
        if key not in _CACHE:
            _CACHE[key] = WordBinderModel(Path(model_dir), ticks=ticks)
        return _CACHE[key]
