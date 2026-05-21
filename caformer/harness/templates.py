"""Slot-templated pattern matching for harness agents.

Pattern syntax: literal text with ``[SlotName]`` markers.
Slot names are alphanumeric (underscore allowed); slot values match
``.+`` (greedy, then trimmed of leading/trailing whitespace).

  pattern = 'look up [X]'
  prompt  = 'look up dogs'   → {'X': 'dogs'}
  prompt  = 'tell me jokes'  → None  (literal 'look up ' not present)

  pattern = 'how many [thing] in [container]'
  prompt  = 'how many bees in a hive'
         → {'thing': 'bees', 'container': 'a hive'}

Output is filled by substituting ``[SlotName]`` markers with the
captured values:

  output = 'https://en.wikipedia.org/wiki/[X]'
  with X='dogs' → 'https://en.wikipedia.org/wiki/dogs'

Specificity score: when several patterns match the same prompt, the
harness picks the most specific one.  Specificity = literal-char count
minus a penalty per slot.  Falls back to ``priority`` for ties.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence


_SLOT_RE = re.compile(r'\[(?P<name>[A-Za-z_][A-Za-z_0-9]*)\]')
# [handler:foo] markers in template output — must be checked BEFORE
# the slot regex so the colon-bearing form doesn't get mis-parsed as
# a slot.  Pattern compiles greedily for the [handler:name] form.
_HANDLER_RE = re.compile(
    r'\[handler:(?P<name>[A-Za-z_][A-Za-z_0-9]*)\]')


@dataclass(frozen=True)
class CompiledPattern:
    raw:        str                       # original pattern string
    regex:      re.Pattern               # compiled match pattern
    slot_names: tuple[str, ...]
    literal_chars: int                    # for specificity scoring


def compile_pattern(raw: str) -> CompiledPattern:
    """Compile a raw pattern (with [Slot] markers) into a regex that
    captures each slot.  Whitespace around the pattern is treated as
    flexible (``\\s+``) so 'look up [X]' matches 'look  up  dogs' too.
    Matching is case-insensitive.

    Raises ValueError on a duplicate slot name (we'd silently lose
    the second one otherwise) or an empty pattern."""
    raw = (raw or '').strip()
    if not raw:
        raise ValueError('empty pattern')
    parts: list[str] = []
    slot_names: list[str] = []
    last = 0
    literal_chars = 0
    for m in _SLOT_RE.finditer(raw):
        lit = raw[last:m.start()]
        for chunk in re.split(r'(\s+)', lit):
            if not chunk:
                continue
            if chunk.isspace():
                parts.append(r'\s+')
            else:
                parts.append(re.escape(chunk))
                literal_chars += len(chunk.strip())
        name = m.group('name')
        if name in slot_names:
            raise ValueError(
                f'duplicate slot {name!r} in pattern {raw!r}')
        slot_names.append(name)
        parts.append(rf'(?P<{name}>.+?)')
        last = m.end()
    tail = raw[last:]
    for chunk in re.split(r'(\s+)', tail):
        if not chunk:
            continue
        if chunk.isspace():
            parts.append(r'\s+')
        else:
            parts.append(re.escape(chunk))
            literal_chars += len(chunk.strip())
    # Allow leading/trailing whitespace; case-insensitive matching.
    body = ''.join(parts)
    regex = re.compile(rf'^\s*{body}\s*$', re.IGNORECASE | re.DOTALL)
    return CompiledPattern(
        raw=raw, regex=regex,
        slot_names=tuple(slot_names),
        literal_chars=literal_chars)


def match(cp: CompiledPattern, prompt: str) -> dict[str, str] | None:
    """Match ``prompt`` against compiled pattern.  Returns the
    captured slot → value dict on hit, or None on miss.  Slot values
    are stripped of leading/trailing whitespace."""
    m = cp.regex.match(prompt or '')
    if not m:
        return None
    out: dict[str, str] = {}
    for name in cp.slot_names:
        v = (m.group(name) or '').strip()
        if not v:
            return None                          # empty slot disqualifies
        out[name] = v
    return out


def fill(template: str, slots: dict[str, str]) -> str:
    """Substitute markers in ``template``:

      [handler:name]  — call the named live-data handler; insert its
                        return string.  Handlers receive the slots
                        dict in case they want input context.
      [SlotName]      — substitute the matched slot value.

    Handler markers are processed first (so a handler returning
    ``"[X]"``-ish text doesn't accidentally trigger slot substitution).
    Unknown slot names are left literal so authoring errors surface
    visibly rather than silently."""
    out = template or ''
    # 1. Handler markers — call into the registry.  Soft-fail (the
    #    handler returns an error string) rather than raise.
    from . import handlers as _h
    def _hrepl(m):
        return _h.invoke(m.group('name'), slots)
    out = _HANDLER_RE.sub(_hrepl, out)
    # 2. Slot markers — substitute captured values.
    def _srepl(m):
        name = m.group('name')
        return slots.get(name, m.group(0))
    out = _SLOT_RE.sub(_srepl, out)
    return out


def specificity(cp: CompiledPattern) -> int:
    """Higher = more specific.  ``literal_chars - n_slots * 4`` works
    well: a 12-char literal with 1 slot (8) outranks a 6-char literal
    with 0 slots (6); a 6-char literal with 2 slots (-2) loses to
    everything."""
    return cp.literal_chars - len(cp.slot_names) * 4


# ─── Match-against-table helpers ───────────────────────────────────


@dataclass
class TemplateMatch:
    pattern_id: int
    pattern: str
    output: str             # filled output
    slots: dict[str, str]
    specificity: int
    confidence: float
    handler_name: str = ''  # handler invoked (if any)
    handler_used: bool = False


def match_table(prompt: str, agent_color: int) -> TemplateMatch | None:
    """Try every active TemplatePattern row for the given agent_color.
    Returns the highest-specificity match, breaking ties by priority
    (lower priority number wins), then by most recently updated.

    Soft-fails to None if no rows match or the table is empty."""
    from caformer.models import TemplatePattern

    rows = list(
        TemplatePattern.objects.filter(
            agent_color=int(agent_color) & 3,
            is_active=True,
        ).order_by('priority', '-updated_at'))
    if not rows:
        return None
    best: TemplateMatch | None = None
    best_score: tuple[int, int] | None = None
    for r in rows:
        try:
            cp = compile_pattern(r.pattern)
        except ValueError:
            continue
        slots = match(cp, prompt)
        if slots is None:
            continue
        spec = specificity(cp)
        # Lower priority wins ties; for sort, we want (spec desc, prio asc).
        score = (spec, -int(r.priority))
        if best_score is None or score > best_score:
            # Option A: explicit handler_name on the row replaces
            #           the entire output with the handler's return.
            # Option B: [handler:name] markers inside output are
            #           expanded by fill().  Both can be active on
            #           the same row — A wins if both are set.
            from . import handlers as _h
            handler_used = False
            if r.handler_name:
                handler_used = True
                produced = _h.invoke(r.handler_name, slots)
            else:
                produced = fill(r.output, slots)
            best = TemplateMatch(
                pattern_id=r.pk,
                pattern=r.pattern,
                output=produced,
                slots=slots,
                specificity=spec,
                confidence=float(r.confidence),
                handler_name=r.handler_name or '',
                handler_used=handler_used,
            )
            best_score = score
    return best
