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
    prefilter_mode: str = 'router'           # which prefilter ran
    path: tuple[int, ...] | None = None      # boardstack4 4-colour path
    spinner_verb: str = ''
    persona_name: str = ''
    context_block: str = ''                  # rendered context text
    system_prompt: str = ''                  # composed system prompt
    dispatched: str = ''                     # what the core decided
    engine: str = ''                         # cell8 | board128 | …
    tier: str = ''                           # cell8 tier when relevant
    sub_label: str = ''                      # core's own sub-label
    pure_ca: bool = True
    chain_used: bool = False                 # Phase 2 path-as-chain
    chain_steps: list[dict] = field(default_factory=list)
    chain_body_kind: str = ''                # reply|announce|clarify|''
    # Hierarchical PICM tree descent (runs alongside boardstack4 when
    # the latter is active; both produce a 4-colour path).
    tree_path: str = ''                      # e.g. '1.0.2'
    tree_label_chain: list[str] = field(default_factory=list)
    tree_depth: int = 0
    tree_stopped_reason: str = ''
    tree_matches_per_level: list[list[str]] = field(default_factory=list)
    tree_leaf_node_id: int | None = None
    tree_vs_boardstack: dict = field(default_factory=dict)
                                              # {'agree_per_level', 'all_agree', ...}
    # Third deterministic prefilter: byte_router (cell8 byte-chunk
    # cascade).  Independent of both boardstack4 and PICM tree.
    byte_router_fingerprint: tuple[int, ...] | None = None
    byte_router_byte_in:  int | None = None
    byte_router_byte_chain: list[int] = field(default_factory=list)
                                              # one byte per layer transition
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

    # 1. Prefilter (router or boardstack4, depending on profile).
    pre = _prefilter.classify(prompt,
                                  mode=getattr(profile, 'prefilter_mode',
                                                 'router'))
    reply.category        = pre.category
    reply.category_name   = pre.name
    reply.category_colour = pre.colour
    reply.router_available = pre.available
    reply.prefilter_mode  = pre.mode
    reply.path            = pre.path

    # 2. Context block.
    cb = _context.build(profile)
    reply.context_block = cb.text

    # 3. Spinner verb (category-tuned).
    pool = profile.spinner_verbs_by_category()
    reply.spinner_verb = _verbs.pick(pre.category, rng=rng, pool=pool)

    # 4. System prompt (for display + future LLM-side fallback).
    reply.system_prompt = _compose_system_prompt(
        profile, cb.text, pre.name)

    # 4b. PICM tree descent — runs alongside boardstack4 when the
    #     latter is active so both prefilters' paths can be compared.
    if pre.path is not None:
        from . import picm_tree as _tree
        descent = _tree.descend(prompt)
        reply.tree_path           = descent.path
        reply.tree_label_chain    = list(descent.label_chain)
        reply.tree_depth          = descent.depth
        reply.tree_stopped_reason = descent.stopped_reason
        reply.tree_matches_per_level = list(descent.matches_per_level)
        reply.tree_leaf_node_id   = descent.leaf_node_id
        reply.tree_vs_boardstack  = _tree.compare_paths(
            descent.path_tuple(), pre.path)

    # 4c. byte_router — third prefilter (cell8 byte-chunk cascade).
    #     Always runs when boardstack4 is active.  Independent CA
    #     substrate; surfaces a 4-symbol fingerprint per prompt.
    if pre.path is not None:
        try:
            from caformer import byte_router as _br
            br = _br.get_router()
            br_result = br.route_prompt(prompt)
            if br_result is not None:
                reply.byte_router_fingerprint = br_result['fingerprint']
                reply.byte_router_byte_in     = br_result['first_byte']
                reply.byte_router_byte_chain  = list(
                    br_result['bytes_intermediate'])
        except Exception:                              # noqa: BLE001
            pass

    # 5. Dispatch.  Two paths:
    #
    #  - boardstack4 + path present  → run the 4-step agent chain
    #    (Phase 2): each colour in the path triggers one sub-agent,
    #    and the assembler stitches their contributions into one
    #    reply.
    #  - otherwise (router, or boardstack4 with no path)  → original
    #    single-step cell8 dispatch.
    if pre.path is not None:
        from . import agents as _agents
        chain_state = _agents.run_chain(pre.path, prompt, profile)
        # Safety-net fallback: when the chain produced NO reply
        # contribution (because boardstack4 routing missed the info
        # agent, but a QRPair partial / fuzzy match exists), try
        # cell8 dispatch and templates in InformationAgent's priority
        # order: strict cell8 → template → loose cell8.  Replicating
        # the order here keeps the template handlers (mood, corpus
        # state, etc.) from being drowned by noisy fuzzy QRPair
        # matches at the fallback stage.
        if not chain_state.has_reply():
            from . import templates as _tpl
            # Tier 1: strict cell8.
            core_fb = _agents._cell8_dispatch(prompt, strict_only=True)
            kind = 'strict'
            if not core_fb.get('reply'):
                # Tier 2: template — fallback searches ALL 4 agent
                # colours, since boardstack4 routing might have
                # missed the right agent's templates.  This is the
                # safety-net stage: anything that matches counts.
                best_tpl = None
                best_spec = -1
                for color in (0, 1, 2, 3):
                    tpl = _tpl.match_table(prompt, color)
                    if tpl is not None and tpl.specificity > best_spec:
                        best_tpl = tpl
                        best_spec = tpl.specificity
                if best_tpl is not None:
                    core_fb = {'reply': best_tpl.output,
                               'sub_label': f'template {best_tpl.pattern!r}'}
                    kind = 'template'
                else:
                    # Tier 3: loose cell8 (substring + fuzzy).
                    core_fb = _agents._cell8_dispatch(prompt,
                                                          strict_only=False)
                    kind = 'loose'
            if core_fb.get('reply'):
                chain_state.contributions.append(_agents.Contribution(
                    agent='information', kind='reply',
                    content=core_fb['reply'], confidence=0.85))
                chain_state.step_log.append({
                    'agent':  'composer-fallback',
                    'action': f'reply ({kind})',
                    'content': core_fb['reply'],
                    'detail':  core_fb.get('sub_label', ''),
                })
        assembled, body_kind = _agents.assemble_reply(chain_state)
        reply.reply = assembled
        reply.chain_used = True
        reply.chain_steps = list(chain_state.step_log)
        reply.chain_body_kind = body_kind
        # Tag the dispatched/engine fields from any cell8 reply
        # contribution so the existing UI still shows the substrate
        # being used.
        info = next((c for c in chain_state.contributions
                     if c.agent == 'information'
                     and c.kind == 'reply'), None)
        if info is not None:
            # We need to know which QRPair / tier was used; re-look up
            # from the agents.dispatch detail.
            info_step = next((s for s in chain_state.step_log
                              if s.get('agent') == 'information'
                              and s.get('action') == 'reply'), None)
            if info_step and info_step.get('detail'):
                reply.sub_label = info_step['detail']
            reply.engine = 'cell8'
            reply.dispatched = 'qrpair-chain'
        else:
            reply.sub_label = f'chain body_kind={body_kind or "empty"}'
    else:
        core = _core_dispatch(profile, prompt)
        reply.reply      = core['reply']
        reply.dispatched = core['dispatched']
        reply.engine     = core['engine']
        reply.tier       = core['tier']
        reply.sub_label  = core['sub_label']
        reply.pure_ca    = core['pure_ca']

    return reply
