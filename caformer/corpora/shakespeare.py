"""Extract (prompt, response) pairs from Shakespearean text.

Two text shapes the extractor knows about:

  - **Sonnets / prose** (verse-only, no speaker markup): pairs are
    line-by-line *continuations* — given line N, predict line N+1.
    Useful as a smoke corpus; the entire SHAKESPEARE_SONNETS bundled
    in caformer/internalize.py produces ~80 continuation pairs.

  - **Plays** (Folger / Project Gutenberg format with speaker lines
    in ALL CAPS at the start of speeches): pairs are *speaker turns*
    — (last speech, this speaker's next line).  Useful for "talk to
    Hamlet" because the prompt is whoever just spoke and the
    response is in-character.

Output is always a list of dicts:

    [{'prompt':   'Shall I compare thee to a summer\\'s day?',
      'expected': 'Thou art more lovely and more temperate:',
      'source':   'sonnets',
      'strategy': 'continuation',
      'label':    'shakespeare-sonnets'}, ...]

Each pair has a `label` so downstream `caformer_import_corpus` can
tag the QRPair rows and bulk-filter / bulk-delete them later.
"""
from __future__ import annotations

import re
from typing import List


# ── Strategy A: line-by-line continuation ──────────────────────────

def extract_continuation_pairs(text: str, *,
                                     label: str = 'shakespeare-sonnets',
                                     min_line_len: int = 8,
                                     max_line_len: int = 200) -> List[dict]:
    """Pair each non-empty line with the next non-empty line.  Skips
    short fragments and headers (e.g. 'Sonnet 18')."""
    out = []
    # Split into lines, strip whitespace, drop empties and tiny fragments.
    lines = [l.strip() for l in text.splitlines()]
    lines = [l for l in lines
                if l and min_line_len <= len(l) <= max_line_len
                and not _is_section_header(l)]
    for i in range(len(lines) - 1):
        out.append({
            'prompt':   lines[i],
            'expected': lines[i + 1],
            'source':   'shakespeare',
            'strategy': 'continuation',
            'label':    label,
        })
    return out


def _is_section_header(line: str) -> bool:
    """Heuristic for 'Sonnet 18' / 'ACT I' / 'SCENE 1' style headers."""
    s = line.strip()
    if re.match(r'^Sonnet\s+\d+', s):
        return True
    if re.match(r'^ACT\s+[IVXLC]+$', s):
        return True
    if re.match(r'^SCENE\s+[IVXLC0-9]+', s):
        return True
    return False


# ── Strategy B: speaker → reply (plays) ────────────────────────────
#
# Folger / Gutenberg play text alternates between a SPEAKER line (in
# ALL CAPS, often followed by a period or just the name on its own
# line) and dialogue lines that follow.  We extract pairs as
# (previous speech's last line, this speaker's first line) — gives
# the model the conversational hand-off.

SPEAKER_LINE_RE = re.compile(r'^([A-Z][A-Z .]+?)\.\s*$')
SPEAKER_INLINE_RE = re.compile(r'^([A-Z][A-Z .]{2,30})\.\s+(\S.*)$')


def extract_speaker_pairs(text: str, *,
                                label: str = 'shakespeare-play',
                                min_line_len: int = 8) -> List[dict]:
    """Walk a play's text; for each speaker change, emit a pair
    (previous speaker's last line of dialogue, new speaker's first
    line).  Lossy on stage directions but doesn't need a parser."""
    out = []
    speeches = []   # [(speaker_name, [line, line, ...]), ...]
    current_speaker = None
    current_lines = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _is_section_header(line):
            continue
        # Stage direction in brackets — skip.
        if line.startswith('[') and line.endswith(']'):
            continue
        # Speaker on its own line (Folger style: "HAMLET.").
        m = SPEAKER_LINE_RE.match(line)
        if m:
            if current_speaker is not None and current_lines:
                speeches.append((current_speaker, current_lines))
            current_speaker = m.group(1).strip().rstrip('.')
            current_lines = []
            continue
        # Speaker inline (Gutenberg style: "Hamlet. To be, or not to be").
        m = SPEAKER_INLINE_RE.match(line)
        if m:
            if current_speaker is not None and current_lines:
                speeches.append((current_speaker, current_lines))
            current_speaker = m.group(1).strip().rstrip('.')
            current_lines = [m.group(2).strip()]
            continue
        # Dialogue line — attach to current speaker.
        if current_speaker is not None and len(line) >= min_line_len:
            current_lines.append(line)
    if current_speaker is not None and current_lines:
        speeches.append((current_speaker, current_lines))

    # Now emit pairs at speaker hand-offs.
    for i in range(1, len(speeches)):
        prev_spkr, prev_lines = speeches[i - 1]
        this_spkr, this_lines = speeches[i]
        prev_last = prev_lines[-1]
        this_first = this_lines[0]
        if min_line_len <= len(prev_last) <= 200 \
                and min_line_len <= len(this_first) <= 200:
            out.append({
                'prompt':       prev_last,
                'expected':     this_first,
                'source':       'shakespeare',
                'strategy':     'speaker',
                'label':        f'{label}-{this_spkr.lower()}',
                'speaker':      this_spkr,
                'prev_speaker': prev_spkr,
            })
    return out


# ── Strategy C: in-speaker continuation (e.g. "Hamlet" speaking) ───

def extract_speaker_continuation_pairs(text: str, *,
                                                speaker_filter: str = None,
                                                label: str = 'shakespeare-play',
                                                min_line_len: int = 8) -> List[dict]:
    """Like continuation, but only WITHIN a single speaker's speeches.
    If speaker_filter is set (e.g. 'HAMLET'), only that speaker's
    lines pair up — gives a model of their voice specifically.
    Otherwise emits intra-speech continuation for every speech."""
    out = []
    current_speaker = None
    current_lines = []

    def flush_speech(spkr, lines):
        if not lines or len(lines) < 2:
            return
        if speaker_filter and spkr.upper() != speaker_filter.upper():
            return
        for i in range(len(lines) - 1):
            if (min_line_len <= len(lines[i]) <= 200
                    and min_line_len <= len(lines[i + 1]) <= 200):
                out.append({
                    'prompt':   lines[i],
                    'expected': lines[i + 1],
                    'source':   'shakespeare',
                    'strategy': 'speaker_continuation',
                    'label':    (f'{label}-{spkr.lower()}'
                                    if spkr else label),
                    'speaker':  spkr,
                })

    for raw in text.splitlines():
        line = raw.strip()
        if not line or _is_section_header(line):
            continue
        if line.startswith('[') and line.endswith(']'):
            continue
        m = SPEAKER_LINE_RE.match(line) or SPEAKER_INLINE_RE.match(line)
        if m:
            flush_speech(current_speaker, current_lines)
            current_speaker = m.group(1).strip().rstrip('.')
            # Inline form has a second group — first line of dialogue.
            current_lines = [m.group(2).strip()] if m.lastindex == 2 else []
            continue
        if current_speaker is not None and len(line) >= min_line_len:
            current_lines.append(line)
    flush_speech(current_speaker, current_lines)
    return out


# ── All-in-one entry point ─────────────────────────────────────────

def extract_pairs(text: str, *,
                     strategy: str = 'continuation',
                     label: str = 'shakespeare',
                     speaker_filter: str = None) -> List[dict]:
    """Dispatch to the right extractor.

    Strategies:
      continuation         — line N → line N+1 (works for sonnets + plays)
      speaker              — last speech end → next speaker's first line
      speaker_continuation — within-speech continuation (optionally
                              filtered to one speaker)
      all                  — concatenate all three (deduped on
                              (prompt, expected))
    """
    if strategy == 'continuation':
        return extract_continuation_pairs(text, label=label)
    if strategy == 'speaker':
        return extract_speaker_pairs(text, label=label)
    if strategy == 'speaker_continuation':
        return extract_speaker_continuation_pairs(
            text, speaker_filter=speaker_filter, label=label)
    if strategy == 'all':
        a = extract_continuation_pairs(text, label=label)
        b = extract_speaker_pairs(text, label=label)
        c = extract_speaker_continuation_pairs(
            text, speaker_filter=speaker_filter, label=label)
        # Dedup on (prompt, expected).
        seen, out = set(), []
        for p in a + b + c:
            key = (p['prompt'], p['expected'])
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
        return out
    raise ValueError(f'unknown strategy {strategy!r}')
