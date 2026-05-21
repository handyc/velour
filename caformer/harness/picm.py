"""PICM — Per-Intent Character Map.

Vocabulary store for boardstack4 agents.  Each routing colour (0..3
mapping to personality / information / command / meta) gets its own
PICMVocab row with a list of short token strings.

The 128×128 K=4 "board" view is *derived* from the token list: each
token packs into ``bytes_per_token × 4`` cells (2 bits per cell)
inside a 16,384-cell board.  Token i lives at cell-offsets
[i*cells_per_token, (i+1)*cells_per_token).

Defaults: 1024 tokens × 4 bytes (= 16 cells per token = 16,384 cells
exactly).  Other valid shapes: 512 × 8 bytes (32 cells), 256 × 16
bytes (64 cells), etc.

For Phase-1 generation, an agent matches its tokens against the
incoming prompt as substring keywords (longest-first, case-insensitive).
A matched token signals "this agent has something to say about
this input".  Future phases may run a CA on the board and emit
tokens from hot cells, but the simple substring match is the
deterministic, debuggable baseline.
"""
from __future__ import annotations

import re
from typing import Sequence


BOARD_SIDE = 128
BOARD_CELLS = BOARD_SIDE * BOARD_SIDE          # 16,384


def cells_per_token(bytes_per_token: int) -> int:
    """Each byte = 8 bits = 4 K=4 cells.  4 bytes → 16 cells."""
    return int(bytes_per_token) * 4


def board_capacity(bytes_per_token: int) -> int:
    """How many tokens fit in a 128×128 K=4 board at this token size."""
    return BOARD_CELLS // cells_per_token(bytes_per_token)


def pack_board(tokens: Sequence[str], bytes_per_token: int = 4,
                  board_cells: int = BOARD_CELLS) -> bytes:
    """Pack ``tokens`` into a ``board_cells``-long bytearray of K=4
    values (0..3 per byte for readability — wasteful but simple).

    Tokens longer than ``bytes_per_token`` are truncated.  Tokens
    shorter than ``bytes_per_token`` are zero-padded.  The vocab is
    silently truncated if it overflows the board.

    Returns: bytes object of length ``board_cells``, each byte ∈ {0..3}.
    The 128×128 layout is row-major; row r covers cells [r*128, (r+1)*128).
    """
    cpt = cells_per_token(bytes_per_token)
    capacity = board_cells // cpt
    out = bytearray(board_cells)               # zero-filled
    for tok_idx, raw in enumerate(tokens[:capacity]):
        s = (raw or '')[:bytes_per_token].encode('utf-8',
                                                 errors='replace')
        # Pad with null bytes to bytes_per_token.
        padded = s + b'\x00' * (bytes_per_token - len(s))
        base = tok_idx * cpt
        for byte_idx, b in enumerate(padded):
            # Each byte → 4 cells, MSB first (matches router.embed_prompt).
            cell_base = base + byte_idx * 4
            out[cell_base + 0] = (b >> 6) & 3
            out[cell_base + 1] = (b >> 4) & 3
            out[cell_base + 2] = (b >> 2) & 3
            out[cell_base + 3] =  b       & 3
    return bytes(out)


def unpack_token(board: bytes, idx: int,
                    bytes_per_token: int = 4) -> str:
    """Reverse of pack_board for a single token slot.  Strips trailing
    NULs so 'hi\\x00\\x00' reads back as 'hi'."""
    cpt = cells_per_token(bytes_per_token)
    base = idx * cpt
    if base + cpt > len(board):
        return ''
    raw = bytearray(bytes_per_token)
    for byte_idx in range(bytes_per_token):
        cb = base + byte_idx * 4
        raw[byte_idx] = ((board[cb + 0] & 3) << 6
                          | (board[cb + 1] & 3) << 4
                          | (board[cb + 2] & 3) << 2
                          | (board[cb + 3] & 3))
    return raw.rstrip(b'\x00').decode('utf-8', errors='replace')


def match_keywords(text: str, tokens: Sequence[str]) -> list[tuple[int, str]]:
    """Find each (idx, token) pair from ``tokens`` that appears in
    ``text`` on **word boundaries**, case-insensitive.

    Word-boundary matching prevents 'ok' from firing inside 'look',
    'me' inside 'memory', 'ref' inside 'reflect', etc.  A token must
    sit between non-word characters (or at the start/end of input).

    Longest tokens first within a category so a longer phrase wins
    over a shorter one whose span it covers — e.g. 'what is' over
    'what'.  Returns (token_index, token_string) pairs in order of
    first occurrence in the text."""
    if not text or not tokens:
        return []
    lowered = text.lower()
    indexed = [(i, (t or '').strip())
               for i, t in enumerate(tokens) if (t or '').strip()]
    indexed.sort(key=lambda it: -len(it[1]))
    claimed = bytearray(len(lowered))
    hits: list[tuple[int, int, str]] = []
    for idx, tok in indexed:
        tlow = tok.lower()
        if not tlow:
            continue
        # \b only matches between \w and \W transitions; tokens whose
        # first/last char is non-word (rare for vocab) need a looser
        # boundary.  re.escape handles regex metacharacters safely.
        pattern = re.compile(r'\b' + re.escape(tlow) + r'\b')
        for m in pattern.finditer(lowered):
            j, e = m.start(), m.end()
            if any(claimed[k] for k in range(j, e)):
                continue
            for k in range(j, e):
                claimed[k] = 1
            hits.append((j, idx, tok))
    hits.sort(key=lambda h: h[0])
    return [(idx, tok) for (_pos, idx, tok) in hits]


# ─── Convenience: load vocab tokens for an agent colour ────────────


def vocab_for(agent_color: int) -> list[str]:
    """Return the token list for the given agent colour, or [] if no
    PICMVocab row exists yet.  Soft-fail so agents work pre-seed."""
    try:
        from caformer.models import PICMVocab
        row = PICMVocab.objects.filter(agent_color=int(agent_color) & 3).first()
        if row is None:
            return []
        return row.tokens()
    except Exception:                                  # noqa: BLE001
        return []
