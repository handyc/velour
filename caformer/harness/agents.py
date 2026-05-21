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
        """Add a register-appropriate wrapper when the prompt is
        conversational, otherwise pass silently."""
        prompt = state.prompt.lower().strip()
        first_token = prompt.split()[0] if prompt else ''
        is_greeting = first_token in _GREETING_KEYWORDS or len(prompt) <= 4
        if is_greeting and not any(c.kind == 'wrapper'
                                   for c in state.contributions):
            persona = getattr(state.profile, 'persona_name', '') or ''
            wrapper = 'Hello.' if persona == '' else f'Hello, {persona} here.'
            state.contributions.append(Contribution(
                agent=self.name, kind='wrapper',
                content=wrapper, confidence=0.7))
            state.step_log.append({
                'agent': self.name, 'action': 'wrapper',
                'content': wrapper})
            return
        state.step_log.append({
            'agent': self.name, 'action': 'pass',
            'content': '(not conversational)'})


class InformationAgent:
    name = 'information'
    colour_code = 1

    def run(self, state: AgentState) -> None:
        """Try a cell8 QRPair dispatch.  When it lands, add a
        high-confidence 'reply' contribution.  Caches across repeated
        calls within the same chain by checking state.has_reply()."""
        if state.has_reply():
            state.step_log.append({
                'agent': self.name, 'action': 'pass',
                'content': '(reply already present, leaving it)'})
            return
        core = _cell8_dispatch(state.prompt)
        if core.get('reply'):
            state.contributions.append(Contribution(
                agent=self.name, kind='reply',
                content=core['reply'], confidence=0.95))
            state.step_log.append({
                'agent': self.name, 'action': 'reply',
                'content': core['reply'],
                'detail':  core.get('sub_label', '')})
            return
        state.step_log.append({
            'agent': self.name, 'action': 'pass',
            'content': core.get('sub_label', '(no QRPair match)')})


class CommandAgent:
    name = 'command'
    colour_code = 2

    def run(self, state: AgentState) -> None:
        """If the prompt is imperative ('write me X', 'make Y') and
        no reply exists yet, contribute an 'announce' acknowledging
        the request.  This is the seam where a real action layer
        would later plug in (the agent layer that produces
        programs / files / artifacts)."""
        if state.has_reply():
            state.step_log.append({
                'agent': self.name, 'action': 'pass',
                'content': '(reply already present)'})
            return
        prompt = state.prompt.lower().strip()
        first_token = prompt.split()[0] if prompt else ''
        if first_token in _COMMAND_VERBS:
            target = ' '.join(prompt.split()[1:])[:80] or '(unspecified target)'
            announce = (f"I'd produce: {target} — but the command "
                        f"agent isn't wired to an executor yet.")
            state.contributions.append(Contribution(
                agent=self.name, kind='announce',
                content=announce, confidence=0.4))
            state.step_log.append({
                'agent': self.name, 'action': 'announce',
                'content': announce})
            return
        state.step_log.append({
            'agent': self.name, 'action': 'pass',
            'content': '(not imperative)'})


class MetaAgent:
    name = 'meta'
    colour_code = 3

    def run(self, state: AgentState) -> None:
        """Add a hedge or clarification when:
          - the prompt is very short (< 3 tokens) AND no reply yet, OR
          - the prompt asks 'why/how/what does' AND no reply yet.
        Otherwise pass."""
        prompt = state.prompt.strip()
        tokens = prompt.split()
        if state.has_reply():
            # Once we have a reply, meta may still add a hedge for
            # low-confidence answers.
            best = max((c.confidence for c in state.replies()), default=1.0)
            if best < 0.6 and not state.first('hedge'):
                hedge = "I'm not entirely sure about that, though."
                state.contributions.append(Contribution(
                    agent=self.name, kind='hedge',
                    content=hedge, confidence=0.5))
                state.step_log.append({
                    'agent': self.name, 'action': 'hedge',
                    'content': hedge})
                return
            state.step_log.append({
                'agent': self.name, 'action': 'pass',
                'content': '(reply confident, no hedge needed)'})
            return
        looks_meta = (len(tokens) <= 2 or any(
            prompt.lower().startswith(m) for m in _META_MARKERS))
        if looks_meta:
            clarify = ("Could you say a bit more about what you're "
                       "looking for?")
            state.contributions.append(Contribution(
                agent=self.name, kind='clarify',
                content=clarify, confidence=0.6))
            state.step_log.append({
                'agent': self.name, 'action': 'clarify',
                'content': clarify})
            return
        state.step_log.append({
            'agent': self.name, 'action': 'pass',
            'content': '(prompt looks specific enough)'})


AGENTS_BY_COLOUR: dict[int, object] = {
    0: PersonalityAgent(),
    1: InformationAgent(),
    2: CommandAgent(),
    3: MetaAgent(),
}


# ─── Cell8 dispatch helper (shared with composer's fallback) ───────


def _cell8_dispatch(prompt: str) -> dict:
    """Single-prompt cell8 QRPair lookup.  Reused by both
    InformationAgent and the composer's non-chain fallback path."""
    from django.db.models import Q
    from caformer.models import QRPair
    from caformer import board256 as _b256
    from caformer.cell8_multires import (forward_pair_cell8_at_side,
                                                   TIER_SIDES,
                                                   cell8_tier_geometry)

    pair = (QRPair.objects.filter(prompt=prompt).filter(
        Q(cell8_b008_exact=True) | Q(cell8_b016_exact=True) |
        Q(cell8_b032_exact=True) | Q(cell8_b064_exact=True) |
        Q(cell8_b128_exact=True) | Q(cell8_b256_exact=True)).first())
    if pair is None:
        return {'reply': '', 'sub_label': 'no exact QRPair match'}
    tier = (pair.best_cell8_tier()
            if hasattr(pair, 'best_cell8_tier') else None)
    if tier is None:
        tier = 'b256' if pair.is_cell8_b256() else None
    if tier is None:
        return {'reply': '', 'sub_label': 'no tier exact'}
    rules = pair.cell8_rules_at_tier(tier)
    n_bytes = len(pair.expected.encode('utf-8'))
    if tier == 'b256':
        side, n_ticks = 256, _b256.DEFAULT_N_TICKS_256
        produced = _b256.forward_pair_board256_positional(
            prompt, rules, n_bytes, n_ticks=n_ticks, port_value=0)
    else:
        side = TIER_SIDES[tier]
        n_ticks = cell8_tier_geometry(side)['n_ticks_default']
        produced = forward_pair_cell8_at_side(
            prompt, rules, n_bytes, side, n_ticks=n_ticks, port_value=0)
    try:
        reply = produced.decode('utf-8')
    except UnicodeDecodeError:
        reply = produced.decode('latin-1', errors='replace')
    return {
        'reply':      reply,
        'sub_label':  f'cell8/{tier} side={side} ticks={n_ticks}',
        'qrpair_pk':  pair.pk,
        'tier':       tier,
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
