"""Composer — orchestrates one harness turn end-to-end.

Pipeline:

  1. **Prefilter**.  Classify the prompt into PERSONALITY / INFO /
     ACTION / META using the CA router.
  2. **Context block**.  Render the cwd / time / persona / git /
     mood block from the HarnessProfile's toggles.
  3. **Spinner verb**.  Pick a category-appropriate waiting verb.
  4. **Dispatch**.  Hand the *original* prompt to the deterministic
     core (cell8 QRPair dispatch for now).  The composed system
     prompt + context are emitted for UI display but the core itself
     remains byte-exact on raw prompts so it can match QRPairs.
  5. **Post-process**.  Currently a no-op; later phases will add
     hedging language, register matching, repair phrases.

Returning a structured ``HarnessReply`` keeps the harness honest:
every decision (category, verb, context block, dispatched slug) is
visible to the caller so the UI can show *what the harness did* in
addition to the reply itself.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import context as _context
from . import prefilter as _prefilter
from . import verbs as _verbs


@dataclass
class HarnessReply:
    prompt: str                              # user input
    reply: str                               # final reply text
    category: int = 0
    category_name: str = 'personality'
    category_colour: str = 'ffffff'
    router_available: bool = False
    spinner_verb: str = ''
    persona_name: str = ''
    context_block: str = ''                  # rendered context text
    system_prompt: str = ''                  # composed system prompt
    dispatched: str = ''                     # what the core decided
    engine: str = ''                         # cell8 | board128 | …
    tier: str = ''                           # cell8 tier when relevant
    sub_label: str = ''                      # core's own sub-label
    pure_ca: bool = True
    error: str = ''
    extra: dict = field(default_factory=dict)


def _compose_system_prompt(profile, context_block_text: str,
                              category_name: str) -> str:
    """Stitch the profile's persona description + per-category cue
    + rendered context into a single system prompt string.

    The string is rendered for *display only* in this phase — the
    deterministic core still sees the raw user prompt so QRPair
    matching stays byte-exact.  Future phases may feed this to a
    LLM-side fallback or distill it into the CA chain."""
    parts: list[str] = []
    if profile.persona_name:
        parts.append(f'You are {profile.persona_name}.')
    if profile.persona_description:
        parts.append(profile.persona_description.strip())
    if profile.system_prompt_extra:
        parts.append(profile.system_prompt_extra.strip())
    if context_block_text:
        parts.append('## Context')
        parts.append(context_block_text)
    parts.append(f'## Intent: {category_name}')
    return '\n\n'.join(parts)


def _core_dispatch(profile, prompt: str) -> dict:
    """Call into the deterministic caformer core.  Currently routes
    to the cell8 dispatcher when the prompt has a matching QRPair,
    else returns a benign empty reply (the harness should still
    return *something*, with the reasoning surfaced)."""
    from django.db.models import Q
    from caformer.models import QRPair

    cell8_q = QRPair.objects.filter(prompt=prompt).filter(
        Q(cell8_b008_exact=True) | Q(cell8_b016_exact=True) |
        Q(cell8_b032_exact=True) | Q(cell8_b064_exact=True) |
        Q(cell8_b128_exact=True) | Q(cell8_b256_exact=True))
    pair = cell8_q.first()
    if pair is None:
        return {
            'reply':      '',
            'dispatched': '',
            'engine':     '',
            'tier':       '',
            'sub_label':  'no exact QRPair match',
            'pure_ca':    True,
        }
    # Run the cheapest exact tier.  Reuses caformer.cell8_multires
    # via the same path the funnel-chat UI uses.
    from caformer import board256 as _b256
    from caformer.cell8_multires import (forward_pair_cell8_at_side,
                                                   TIER_SIDES,
                                                   cell8_tier_geometry)
    tier = pair.best_cell8_tier() if hasattr(pair, 'best_cell8_tier') \
                                  else None
    if tier is None:
        tier = 'b256' if pair.is_cell8_b256() else None
    if tier is None:
        return {'reply': '', 'dispatched': '', 'engine': '',
                'tier': '', 'sub_label': 'no tier exact', 'pure_ca': True}
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
        reply_text = produced.decode('utf-8')
    except UnicodeDecodeError:
        reply_text = produced.decode('latin-1', errors='replace')
    return {
        'reply':       reply_text,
        'dispatched':  f'qrpair-cell8:{pair.pk}',
        'engine':      'cell8',
        'tier':        tier,
        'sub_label':   f'cell8/{tier} side={side} ticks={n_ticks}',
        'pure_ca':     True,
    }


def run_turn(profile, prompt: str,
                rng: random.Random | None = None) -> HarnessReply:
    """End-to-end harness turn.  ``profile`` is a HarnessProfile row;
    ``prompt`` is the user's input string."""
    rng = rng or random.Random()
    prompt = (prompt or '').strip()

    reply = HarnessReply(prompt=prompt, reply='',
                         persona_name=profile.persona_name or '')

    if not prompt:
        reply.error = 'empty prompt'
        return reply

    # 1. Prefilter.
    pre = _prefilter.classify(prompt)
    reply.category        = pre.category
    reply.category_name   = pre.name
    reply.category_colour = pre.colour
    reply.router_available = pre.available

    # 2. Context block.
    cb = _context.build(profile)
    reply.context_block = cb.text

    # 3. Spinner verb (category-tuned).
    pool = profile.spinner_verbs_by_category()
    reply.spinner_verb = _verbs.pick(pre.category, rng=rng, pool=pool)

    # 4. System prompt (for display + future LLM-side fallback).
    reply.system_prompt = _compose_system_prompt(
        profile, cb.text, pre.name)

    # 5. Dispatch.
    core = _core_dispatch(profile, prompt)
    reply.reply      = core['reply']
    reply.dispatched = core['dispatched']
    reply.engine     = core['engine']
    reply.tier       = core['tier']
    reply.sub_label  = core['sub_label']
    reply.pure_ca    = core['pure_ca']

    # 6. Post-process (placeholder — phases ahead add hedging, repair,
    #    register matching).  For now we just record the verb prefix
    #    that the UI might want to display before the reply lands.

    return reply
