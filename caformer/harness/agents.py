"""Phase 2 of boardstack4: the 4-colour path treated as an ordered
chain of sub-agent calls instead of a single category.

Four agents, one per K=4 colour:

    0 PersonalityAgent  — register / greeting / closing wrappers
    1 InformationAgent  — factual recall via cell8 QRPair dispatch
    2 CommandAgent      — action / artifact-production announcements
    3 MetaAgent         — hedging / clarification when underspecified

Each agent in the chain looks at the prompt and at what previous
agents have already contributed.  It either adds its own contribution
or passes.  Repeats in the path mean an agent gets called more than
once — its second call sees the state after the first contribution.

The chain is deterministic for a given (path, prompt, profile):
the agents themselves are pure functions of state.  Same path on
the same prompt twice produces byte-identical traces.

Assembly: the highest-priority `reply` contribution forms the core
of the response.  Wrapper / announce / hedge contributions decorate
it.  If no agent produces a reply, the most confident `announce` or
`clarify` falls through.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from . import picm as _picm
from . import templates as _tpl


# ─── Contribution + state ──────────────────────────────────────────


@dataclass
class Contribution:
    """One agent's deposit in the chain.

    ``kind`` drives the assembler:

      reply    — the byte-substance of the response (cell8 QRPair, etc.)
      wrapper  — short prefix/suffix in the persona's voice (greeting,
                  acknowledgement)
      announce — "I'd produce X" notice from the command agent when it
                  can't actually execute, or the result of a stubbed
                  action
      hedge    — calibrated uncertainty marker
      clarify  — "Could you say more about X?" — meta's specialty"""

    agent: str
    kind: str
    content: str
    confidence: float = 0.5


@dataclass
class AgentState:
    prompt: str
    profile: object                          # HarnessProfile (duck)
    contributions: list[Contribution] = field(default_factory=list)
    step_log: list[dict] = field(default_factory=list)
                                              # one dict per step in the
                                              # chain — for UI tracing

    def has_reply(self) -> bool:
        return any(c.kind == 'reply' for c in self.contributions)

    def replies(self) -> list[Contribution]:
        return [c for c in self.contributions if c.kind == 'reply']

    def first(self, kind: str) -> Contribution | None:
        for c in self.contributions:
            if c.kind == kind:
                return c
        return None


# ─── Agents ────────────────────────────────────────────────────────


_GREETING_KEYWORDS = {
    'hi', 'hello', 'hey', 'howdy', 'sup', 'yo', 'greetings',
    'morning', 'evening', 'afternoon',
}

_COMMAND_VERBS = {
    'write', 'make', 'create', 'build', 'generate', 'produce',
    'compose', 'draft', 'design', 'paint', 'draw', 'list',
    'show', 'give', 'run', 'execute', 'fix', 'rename', 'rewrite',
}

_META_MARKERS = {
    'why', 'how', 'what does', 'what is', 'consider', 'think about',
    'reason', 'explain', 'meaning of', 'philosophy', 'should i',
}


class PersonalityAgent:
    name = 'personality'
    colour_code = 0

    def run(self, state: AgentState) -> None:
        """Wrap conversational prompts.  Tries template patterns
        first (e.g. 'thanks [X]' → "you're welcome, [X]"), then PICM
        keyword presence, then the hardcoded greeting check."""
        tokens = _picm.vocab_for(self.colour_code)
        matches = _picm.match_keywords(state.prompt, tokens)
        picm_strs = [t for (_i, t) in matches]
        tpl = _tpl.match_table(state.prompt, self.colour_code)

        if tpl is not None and not any(c.kind == 'wrapper'
                                       for c in state.contributions):
            state.contributions.append(Contribution(
                agent=self.name, kind='wrapper',
                content=tpl.output, confidence=tpl.confidence))
            state.step_log.append({
                'agent': self.name, 'action': 'wrapper',
                'content': tpl.output,
                'template':  tpl.pattern,
                'slots':     tpl.slots,
                'handler':   tpl.handler_name or '',
                'picm_matches': picm_strs})
            return

        prompt = state.prompt.lower().strip()
        first_token = prompt.split()[0] if prompt else ''
        is_greeting = (bool(matches)
                       or first_token in _GREETING_KEYWORDS
                       or len(prompt) <= 4)
        if is_greeting and not any(c.kind == 'wrapper'
                                   for c in state.contributions):
            persona = getattr(state.profile, 'persona_name', '') or ''
            wrapper = 'Hello.' if persona == '' else f'Hello, {persona} here.'
            state.contributions.append(Contribution(
                agent=self.name, kind='wrapper',
                content=wrapper, confidence=0.7))
            state.step_log.append({
                'agent': self.name, 'action': 'wrapper',
                'content': wrapper,
                'picm_matches': picm_strs})
            return
        state.step_log.append({
            'agent': self.name, 'action': 'pass',
            'content': '(not conversational)',
            'picm_matches': picm_strs})


class InformationAgent:
    name = 'information'
    colour_code = 1

    def run(self, state: AgentState) -> None:
        """Three paths, in priority order:

          1. cell8 QRPair byte-exact dispatch (highest confidence);
          2. template-pattern match (parametric — 'look up [X]');
          3. PICM keyword acknowledgement (lowest — 'how many' etc.).

        Caches across repeated chain calls via state.has_reply()."""
        tokens = _picm.vocab_for(self.colour_code)
        matches = _picm.match_keywords(state.prompt, tokens)
        matched_strs = [t for (_i, t) in matches]
        if state.has_reply():
            state.step_log.append({
                'agent': self.name, 'action': 'pass',
                'content': '(reply already present, leaving it)',
                'picm_matches': matched_strs})
            return
        core = _cell8_dispatch(state.prompt)
        if core.get('reply'):
            state.contributions.append(Contribution(
                agent=self.name, kind='reply',
                content=core['reply'], confidence=0.95))
            state.step_log.append({
                'agent': self.name, 'action': 'reply',
                'content': core['reply'],
                'detail':  core.get('sub_label', ''),
                'picm_matches': matched_strs})
            return
        tpl = _tpl.match_table(state.prompt, self.colour_code)
        if tpl is not None:
            state.contributions.append(Contribution(
                agent=self.name, kind='reply',
                content=tpl.output, confidence=tpl.confidence))
            state.step_log.append({
                'agent': self.name, 'action': 'reply',
                'content':  tpl.output,
                'detail':   f'template {tpl.pattern!r} '
                            f'spec={tpl.specificity}',
                'template': tpl.pattern,
                'slots':    tpl.slots,
                'handler':  tpl.handler_name or '',
                'picm_matches': matched_strs})
            return
        if matches and not state.first('announce'):
            announce = (f"Recognised query stem(s): "
                        f"{', '.join(matched_strs)} — but no "
                        f"byte-exact answer in the QRPair store yet.")
            state.contributions.append(Contribution(
                agent=self.name, kind='announce',
                content=announce, confidence=0.35))
            state.step_log.append({
                'agent': self.name, 'action': 'announce',
                'content': announce,
                'picm_matches': matched_strs})
            return
        state.step_log.append({
            'agent': self.name, 'action': 'pass',
            'content': core.get('sub_label', '(no QRPair match)'),
            'picm_matches': matched_strs})


class CommandAgent:
    name = 'command'
    colour_code = 2

    def run(self, state: AgentState) -> None:
        """Three paths:

          1. template-pattern match (e.g. 'run [X]' → 'I would run
             [X]') — highest priority for commands;
          2. PICM keyword match (shell/C tokens present);
          3. imperative-verb heuristic.

        All produce an 'announce' contribution — the command agent
        doesn't have an actual executor yet, so it's an "I would do
        X" signal until the seam is wired."""
        tokens = _picm.vocab_for(self.colour_code)
        matches = _picm.match_keywords(state.prompt, tokens)
        matched_strs = [t for (_i, t) in matches]
        if state.has_reply():
            state.step_log.append({
                'agent': self.name, 'action': 'pass',
                'content': '(reply already present)',
                'picm_matches': matched_strs})
            return
        tpl = _tpl.match_table(state.prompt, self.colour_code)
        if tpl is not None:
            state.contributions.append(Contribution(
                agent=self.name, kind='announce',
                content=tpl.output, confidence=tpl.confidence))
            state.step_log.append({
                'agent': self.name, 'action': 'announce',
                'content':  tpl.output,
                'detail':   f'template {tpl.pattern!r}',
                'template': tpl.pattern,
                'slots':    tpl.slots,
                'handler':  tpl.handler_name or '',
                'picm_matches': matched_strs})
            return
        prompt = state.prompt.lower().strip()
        first_token = prompt.split()[0] if prompt else ''
        is_imperative = (first_token in _COMMAND_VERBS) or bool(matches)
        if is_imperative:
            if matches:
                announce = (f"Command tokens recognised: "
                            f"{', '.join(matched_strs)} — but the "
                            f"command agent isn't wired to an "
                            f"executor yet.")
            else:
                target = ' '.join(prompt.split()[1:])[:80] or '(unspecified target)'
                announce = (f"I'd produce: {target} — but the command "
                            f"agent isn't wired to an executor yet.")
            state.contributions.append(Contribution(
                agent=self.name, kind='announce',
                content=announce, confidence=0.4))
            state.step_log.append({
                'agent': self.name, 'action': 'announce',
                'content': announce,
                'picm_matches': matched_strs})
            return
        state.step_log.append({
            'agent': self.name, 'action': 'pass',
            'content': '(not imperative)',
            'picm_matches': matched_strs})


class MetaAgent:
    name = 'meta'
    colour_code = 3

    def run(self, state: AgentState) -> None:
        """Adds hedge / clarify contributions, plus template-driven
        introspection output ('reflect on [X]' → meta template
        outputs)."""
        prompt = state.prompt.strip()
        tokens_in = prompt.split()
        picm_tokens = _picm.vocab_for(self.colour_code)
        matches = _picm.match_keywords(state.prompt, picm_tokens)
        matched_strs = [t for (_i, t) in matches]
        tpl = _tpl.match_table(state.prompt, self.colour_code)

        if state.has_reply():
            best = max((c.confidence for c in state.replies()), default=1.0)
            if best < 0.6 and not state.first('hedge'):
                hedge = "I'm not entirely sure about that, though."
                state.contributions.append(Contribution(
                    agent=self.name, kind='hedge',
                    content=hedge, confidence=0.5))
                state.step_log.append({
                    'agent': self.name, 'action': 'hedge',
                    'content': hedge,
                    'picm_matches': matched_strs})
                return
            state.step_log.append({
                'agent': self.name, 'action': 'pass',
                'content': '(reply confident, no hedge needed)',
                'picm_matches': matched_strs})
            return
        # Template match takes priority — emit as reply not clarify,
        # because a matched meta-template (e.g. 'reflect on [X]') is
        # giving a structured introspective response, not asking for
        # more info.
        if tpl is not None and not state.has_reply():
            state.contributions.append(Contribution(
                agent=self.name, kind='reply',
                content=tpl.output, confidence=tpl.confidence))
            state.step_log.append({
                'agent': self.name, 'action': 'reply',
                'content':  tpl.output,
                'detail':   f'template {tpl.pattern!r}',
                'template': tpl.pattern,
                'slots':    tpl.slots,
                'handler':  tpl.handler_name or '',
                'picm_matches': matched_strs})
            return
        looks_meta = (
            len(tokens_in) <= 2
            or bool(matches)
            or any(prompt.lower().startswith(m) for m in _META_MARKERS))
        if looks_meta:
            if matches:
                clarify = (f"Picked up introspective markers "
                           f"({', '.join(matched_strs)}) — could you "
                           f"say a bit more about what you're looking for?")
            else:
                clarify = ("Could you say a bit more about what you're "
                           "looking for?")
            state.contributions.append(Contribution(
                agent=self.name, kind='clarify',
                content=clarify, confidence=0.6))
            state.step_log.append({
                'agent': self.name, 'action': 'clarify',
                'content': clarify,
                'picm_matches': matched_strs})
            return
        state.step_log.append({
            'agent': self.name, 'action': 'pass',
            'content': '(prompt looks specific enough)',
            'picm_matches': matched_strs})


AGENTS_BY_COLOUR: dict[int, object] = {
    0: PersonalityAgent(),
    1: InformationAgent(),
    2: CommandAgent(),
    3: MetaAgent(),
}


# ─── Cell8 dispatch helper (shared with composer's fallback) ───────


def _cell8_dispatch(prompt: str) -> dict:
    """Single-prompt cell8 QRPair lookup.  Two-tier match:

      1. Exact prompt match (byte-identical) — preferred, highest
         confidence.
      2. Reduced-form match (lower_no_punct) — fallback that covers
         capitalisation / punctuation variants of trained prompts.

    Reused by both InformationAgent and the composer's non-chain
    fallback path."""
    from django.db.models import Q
    from caformer.models import QRPair
    from caformer import board256 as _b256
    from caformer.cell8_multires import (forward_pair_cell8_at_side,
                                                   TIER_SIDES,
                                                   cell8_tier_geometry)
    from . import normalization as _norm

    exact_filter = (Q(cell8_b008_exact=True) | Q(cell8_b016_exact=True) |
                    Q(cell8_b032_exact=True) | Q(cell8_b064_exact=True) |
                    Q(cell8_b128_exact=True) | Q(cell8_b256_exact=True))
    match_kind = 'exact'
    matched_prompt: str = prompt
    pair = (QRPair.objects.filter(prompt=prompt).filter(exact_filter).first())
    if pair is None:
        # Three-tier fallback when exact match misses.  Reduced lookup
        # tries normalised equality; substring tries containment.
        # Both share a single pass over the candidate set.
        reduced_user = _norm.lower_no_punct(prompt)
        if reduced_user:
            best_substring_pair = None
            best_substring_len = -1
            for cand in QRPair.objects.filter(exact_filter).only(
                    'pk', 'prompt'):
                cand_norm = _norm.lower_no_punct(cand.prompt)
                if not cand_norm:
                    continue
                if cand_norm == reduced_user:
                    # Tier 2: normalised equality — preferred over
                    # substring, break immediately.
                    pair = cand
                    matched_prompt = cand.prompt
                    match_kind = 'lower_no_punct'
                    break
                if cand_norm in reduced_user:
                    # Tier 3: substring match — keep the LONGEST
                    # candidate, so 'capital of france' beats
                    # 'france' when both are present.
                    if len(cand_norm) > best_substring_len:
                        best_substring_pair = cand
                        best_substring_len = len(cand_norm)
            if pair is None and best_substring_pair is not None:
                pair = best_substring_pair
                matched_prompt = best_substring_pair.prompt
                match_kind = 'substring'
    if pair is None:
        return {'reply': '', 'sub_label':
                'no exact / reduced / substring QRPair match'}
    tier = (pair.best_cell8_tier()
            if hasattr(pair, 'best_cell8_tier') else None)
    if tier is None:
        tier = 'b256' if pair.is_cell8_b256() else None
    if tier is None:
        return {'reply': '', 'sub_label': 'no tier exact'}
    rules = pair.cell8_rules_at_tier(tier)
    n_bytes = len(pair.expected.encode('utf-8'))
    # Use the QRPair's *trained* prompt for the forward pass, not the
    # raw user prompt — the rules are byte-exact only against the
    # exact training input, so a normalized match must still cascade
    # the canonical training prompt to produce the byte-exact reply.
    forward_prompt = matched_prompt
    if tier == 'b256':
        side, n_ticks = 256, _b256.DEFAULT_N_TICKS_256
        produced = _b256.forward_pair_board256_positional(
            forward_prompt, rules, n_bytes,
            n_ticks=n_ticks, port_value=0)
    else:
        side = TIER_SIDES[tier]
        n_ticks = cell8_tier_geometry(side)['n_ticks_default']
        produced = forward_pair_cell8_at_side(
            forward_prompt, rules, n_bytes, side,
            n_ticks=n_ticks, port_value=0)
    try:
        reply = produced.decode('utf-8')
    except UnicodeDecodeError:
        reply = produced.decode('latin-1', errors='replace')
    sub_label = f'cell8/{tier} side={side} ticks={n_ticks}'
    if match_kind != 'exact':
        sub_label = f'{sub_label}  ←  match via {match_kind}'
    return {
        'reply':      reply,
        'sub_label':  sub_label,
        'qrpair_pk':  pair.pk,
        'tier':       tier,
        'match_kind': match_kind,
    }


# ─── Chain runner + assembler ──────────────────────────────────────


def run_chain(path: Sequence[int], prompt: str, profile) -> AgentState:
    """Walk ``path`` and invoke each agent in order.  Path repeats
    mean an agent is called more than once — its later calls see the
    state after earlier contributions."""
    state = AgentState(prompt=prompt, profile=profile)
    for step_idx, colour in enumerate(path):
        agent = AGENTS_BY_COLOUR.get(int(colour) & 3)
        if agent is None:
            continue
        state.step_log.append({
            'step':   step_idx,
            'colour': int(colour) & 3,
            'agent':  agent.name,
            'enter':  True,
        })
        agent.run(state)
    return state


def assemble_reply(state: AgentState) -> str:
    """Pick the assembled reply string from the chain's contributions.

    Priority for the body:
      1. highest-confidence ``reply``
      2. highest-confidence ``announce``
      3. highest-confidence ``clarify``
      4. empty string (caller decides what to surface)

    A ``wrapper`` is prepended if present; a ``hedge`` is appended."""
    body = ''
    body_kind = ''

    replies = sorted(state.replies(), key=lambda c: -c.confidence)
    if replies:
        body = replies[0].content
        body_kind = 'reply'
    else:
        announces = sorted(
            (c for c in state.contributions if c.kind == 'announce'),
            key=lambda c: -c.confidence)
        clarifies = sorted(
            (c for c in state.contributions if c.kind == 'clarify'),
            key=lambda c: -c.confidence)
        if announces:
            body = announces[0].content
            body_kind = 'announce'
        elif clarifies:
            body = clarifies[0].content
            body_kind = 'clarify'

    wrapper = next(
        (c for c in state.contributions if c.kind == 'wrapper'), None)
    hedge = next(
        (c for c in state.contributions if c.kind == 'hedge'), None)

    parts: list[str] = []
    if wrapper and wrapper.content:
        parts.append(wrapper.content)
    if body:
        parts.append(body)
    if hedge and hedge.content:
        parts.append(hedge.content)
    text = ' '.join(parts).strip()
    return text, body_kind
