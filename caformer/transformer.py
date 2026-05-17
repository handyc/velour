"""caformer/transformer.py — compose primitives into a tiny CA transformer.

This is the load-bearing piece: it shows that the eight primitives
plug together into something with the *shape* of a transformer
forward pass.  Whether the resulting model is meaningful is what the
GA evolves toward.

Pipeline (matches caformer/nanogpt_reference.py step numbers):

    embed:        token_ids → list of T per-token CA states
    + pos embed:  add positional CA states cell-wise (xor)
    block × N:
        ln_1 + self_attention + residual
        ln_2 + mlp + residual
    final ln + output_head:  last token's CA → vocab logits → sample

`ca_generate` does autoregressive sampling for max_new_tokens.
"""

from __future__ import annotations
import numpy as np
from typing import List, Optional
# (Optional explicitly used by ca_forward_qkv block_rules / norm_rule
#  arguments — keep this import even if a linter says it's unused.)

from .primitives import (
    ca_embedding, ca_positional_embedding, ca_residual, ca_layer_norm,
    ca_mlp, ca_output_head, ca_softmax_sample, hex_ca_step,
    random_rule_table,
    # Fully-CA upgrade path: every op below this comment is a
    # `hex_ca_step` composition with a rule table — no Python
    # permutations, no modular arithmetic, no float math.
    ca_self_attention, ca_residual_merge,
    ca_layer_norm_iterative, ca_output_head_iterative,
    default_norm_rule, default_output_rule,
)
from .reductive import ca_attention_min


def ca_transformer_block(states: List[np.ndarray], *,
                          attn_rule: np.ndarray,
                          mlp_rule:  np.ndarray,
                          do_norm:     bool = True,
                          do_residual: bool = True,
                          residual_mode: str = 'xor',
                          ) -> List[np.ndarray]:
    """One transformer block over a list of T per-token CA states.

    Pre-norm, attention sub-block, residual, pre-norm, MLP sub-block,
    residual — exactly the GPT-2/nanoGPT structure.  Each sub-block
    can be turned off independently via `do_norm` / `do_residual` so
    you can ablate components when debugging or evolving.

    Uses the *reductive* attention (XOR-with-neighbour) for backwards
    compatibility with existing tests; the upgrade path with full
    Q/K/V structure is `ca_transformer_block_qkv` below."""
    T = len(states)
    if T == 0:
        return []
    # Attention sub-block.
    if do_norm:
        normed = [ca_layer_norm(s) for s in states]
    else:
        normed = states
    attended = ca_attention_min(normed, attn_rule)
    if do_residual:
        states_a = [ca_residual(orig, attn, mode=residual_mode)
                     for orig, attn in zip(states, attended)]
    else:
        states_a = attended
    # MLP sub-block (per-token).
    if do_norm:
        normed2 = [ca_layer_norm(s) for s in states_a]
    else:
        normed2 = states_a
    mlped = [ca_mlp(s, rule_table=mlp_rule, k_ticks=2, expand=False)
              for s in normed2]
    if do_residual:
        states_b = [ca_residual(orig, m, mode=residual_mode)
                     for orig, m in zip(states_a, mlped)]
    else:
        states_b = mlped
    return states_b


def ca_transformer_block_qkv(states: List[np.ndarray], *,
                              q_rule: np.ndarray,
                              k_rule: np.ndarray,
                              v_rule: np.ndarray,
                              score_rule: np.ndarray,
                              mix_rule: np.ndarray,
                              merge_rule: np.ndarray,
                              mlp_rule:  np.ndarray,
                              norm_rule: Optional[np.ndarray] = None,
                              norm_ticks: int = 2,
                              causal: bool = True,
                              trace: Optional[list] = None,
                              ) -> List[np.ndarray]:
    """One transformer block, every sub-step a CA tick.

    Sub-block topology = standard GPT-2 (pre-norm), but each piece is
    now a CA-rule application:

        norm    →  k ticks of norm_rule           (ca_layer_norm_iterative)
        attn    →  Q/K/V via 3 rules + score_rule
                   + mix_rule for the readout     (ca_self_attention)
        residual →  one tick of merge_rule         (ca_residual_merge)
        norm    →  k ticks of norm_rule
        mlp     →  k ticks of mlp_rule + 2× expand (ca_mlp)
        residual →  one tick of merge_rule

    Seven distinct rule tables per block (Q/K/V/score/mix/merge/MLP),
    plus a shared norm_rule.  Every one of them is a 16,384-byte
    table the GA can evolve.  This is the literal-everything-is-a-CA
    realisation of the architecture."""
    T = len(states)
    if T == 0:
        return []
    # Attention sub-block, fully CA.
    normed = [ca_layer_norm_iterative(s, norm_rule, k_ticks=norm_ticks)
               for s in states]
    if trace is not None:
        trace.append({'name': 'norm-pre', 'grid': normed[-1]})
    attended = ca_self_attention(normed,
                                   q_rule=q_rule, k_rule=k_rule, v_rule=v_rule,
                                   score_rule=score_rule, mix_rule=mix_rule,
                                   causal=causal, trace=trace)
    states_a = [ca_residual_merge(orig, attn, merge_rule)
                 for orig, attn in zip(states, attended)]
    if trace is not None:
        trace.append({'name': 'merge', 'grid': states_a[-1]})
    # MLP sub-block, fully CA.
    normed2 = [ca_layer_norm_iterative(s, norm_rule, k_ticks=norm_ticks)
                for s in states_a]
    if trace is not None:
        trace.append({'name': 'norm-mid', 'grid': normed2[-1]})
    mlped = [ca_mlp(s, rule_table=mlp_rule, k_ticks=2, expand=True)
              for s in normed2]
    if trace is not None:
        trace.append({'name': 'mlp', 'grid': mlped[-1]})
    states_b = [ca_residual_merge(orig, m, merge_rule)
                 for orig, m in zip(states_a, mlped)]
    if trace is not None:
        trace.append({'name': 'merge-out', 'grid': states_b[-1]})
    return states_b


def ca_embed_sequence(token_ids: List[int], *,
                       embed_rule: np.ndarray,
                       side: int = 16,
                       ) -> List[np.ndarray]:
    """Token embedding + positional embedding for a whole sequence.
    Per token we XOR the token-CA with the position-CA (the residual
    mode of choice for additive embeddings)."""
    out = []
    for pos, tok in enumerate(token_ids):
        e_tok = ca_embedding(tok, rule_table=embed_rule, side=side)
        e_pos = ca_positional_embedding(pos, rule_table=embed_rule,
                                          side=side)
        out.append(ca_residual(e_tok, e_pos, mode='xor'))
    return out


def ca_forward(token_ids: List[int], *,
                n_blocks: int = 3,
                embed_rule: Optional[np.ndarray] = None,
                attn_rules: Optional[List[np.ndarray]] = None,
                mlp_rules:  Optional[List[np.ndarray]] = None,
                vocab_size: int = 256,
                side: int = 16,
                base_seed: int = 0xCAF0FE,
                ) -> np.ndarray:
    """Run one forward pass of the tiny CA transformer.  Returns the
    vocab-size logit vector for the *last* token position.

    Defaults: nanoGPT-shaped at 3 blocks; rules are auto-generated
    from `base_seed` (each block gets its own attention + MLP rule)."""
    if not token_ids:
        return np.zeros(vocab_size, dtype=np.float64)
    if embed_rule is None:
        embed_rule = random_rule_table(base_seed)
    if attn_rules is None:
        attn_rules = [random_rule_table(base_seed ^ (0x1000 + i))
                       for i in range(n_blocks)]
    if mlp_rules is None:
        mlp_rules  = [random_rule_table(base_seed ^ (0x2000 + i))
                       for i in range(n_blocks)]
    if len(attn_rules) != n_blocks or len(mlp_rules) != n_blocks:
        raise ValueError('rule lists must be length n_blocks')

    # 1. Embed.
    states = ca_embed_sequence(token_ids, embed_rule=embed_rule, side=side)
    # 2. Stack of N transformer blocks.
    for i in range(n_blocks):
        states = ca_transformer_block(
            states, attn_rule=attn_rules[i], mlp_rule=mlp_rules[i])
    # 3. Final layer norm on the last token.
    final_last = ca_layer_norm(states[-1])
    # 4. Output head → vocab logits.
    return ca_output_head(final_last, vocab_size=vocab_size)


def _moe_router_affinities(token_ids: List[int], n_experts: int,
                            base_seed: int) -> np.ndarray:
    """Cheap CA-derived router: for each expert, compute an affinity
    score by running 4 ticks of a small CA seeded by the input tokens
    XOR'd with the expert's identity.  The point of MoE is that
    routing is *fast* — much faster than running an expert — so the
    router uses an 8×8 grid (vs 16×16 for the experts) and a single
    rule application instead of a full forward pass.

    Returns a length-`n_experts` float64 array of affinity scores;
    higher = better match.  The actual scoring is the count of
    'fired' cells (colours 1..3) in the final state, normalised."""
    from .primitives import hex_ca_step, lcg_bytes, random_rule_table
    affinities = np.empty(n_experts, dtype=np.float64)
    side = 8
    # Token ids fold into the seed via a deterministic running hash so
    # different prompts route to different experts even at constant N.
    prompt_hash = 0
    for t in token_ids:
        prompt_hash = (prompt_hash * 1103515245 + int(t) + 12345) & 0xFFFFFFFF
    for i in range(n_experts):
        rule_seed = (base_seed ^ (0xA17 * (i + 1)) ^ prompt_hash) & 0xFFFFFFFF
        rule = random_rule_table(rule_seed ^ 0xCA77)
        state = (lcg_bytes(rule_seed, side * side) & 3
                  ).reshape(side, side)
        for _ in range(4):
            state = hex_ca_step(state, rule)
        affinities[i] = float((state > 0).sum()) / state.size
    return affinities


def chat_gpt3_5_shape(token_ids: List[int], *,
                       vocab_size: int = 256,
                       base_seed: int = 0xCAF35,
                       n_experts: int = 4,
                       top_k: int = 2,
                       refinement_blocks: int = 0,
                       **forward_kw) -> np.ndarray:
    """The L5 composition — Mixture-of-Experts on top of ChatGPT-3-shape.

    Pipeline:
      1. Cheap CA router scores all `n_experts` experts (8×8 grid +
         4 ticks per expert; cheap relative to one chat_gpt3_shape call).
      2. Top-k experts (by affinity) are chosen; the rest are *skipped*
         entirely — that's the MoE win.
      3. Each chosen expert runs `chat_gpt3_shape` with its own
         derived `base_seed`, producing a vocab logit vector.
      4. Logits are blended via softmax-weighted sum across the
         chosen experts (router-weights converted to probabilities).
      5. (Optional) `refinement_blocks` more transformer blocks run on
         a synthetic "logit-as-tokens" sequence to polish the output.
         Set to 0 by default — refinement is the slowest part and most
         useful only at scale.

    Cost: ``top_k × cost(chat_gpt3_shape)`` + cheap router + optional
    refinement.  The router is the structural difference between
    L4 (always run all 4 branches) and L5 (run only the best top_k).

    Wraps any other model — DMN around chat_gpt3_5_shape is the
    deepest-stack DMN we can construct in caformer today.
    """
    if not (1 <= top_k <= n_experts):
        raise ValueError(
            f'top_k must be in [1, n_experts]; got top_k={top_k}, '
            f'n_experts={n_experts}')
    affinities = _moe_router_affinities(token_ids, n_experts, base_seed)
    chosen = np.argsort(affinities)[::-1][:top_k]

    # Softmax over the chosen experts' affinities → blend weights.
    chosen_aff = affinities[chosen]
    chosen_aff = chosen_aff - chosen_aff.max()       # stability
    weights = np.exp(chosen_aff)
    weights /= weights.sum()

    blended = np.zeros(vocab_size, dtype=np.float64)
    for j, expert_idx in enumerate(chosen):
        expert_seed = (base_seed ^ (0x100 * (int(expert_idx) + 1))) & 0xFFFFFFFF
        L = chat_gpt3_shape(token_ids, vocab_size=vocab_size,
                              base_seed=expert_seed,
                              n_branches=4, blend='sum',
                              **forward_kw)
        blended += weights[j] * L

    # Refinement: feed the top-vocab indices of `blended` back through
    # ca_forward_qkv as a short token sequence, treating those token
    # ids as the next layer's input.  This is the literal interpretation
    # of "Sequence(refinement_block × M)" from the composition spec —
    # extra transformer depth applied AFTER the MoE blend.
    if refinement_blocks > 0:
        top_seq = np.argsort(blended)[::-1][:8].tolist()
        ref_logits = ca_forward_qkv(top_seq,
                                      n_blocks=refinement_blocks,
                                      vocab_size=vocab_size,
                                      base_seed=base_seed ^ 0xFEED)
        blended = blended + ref_logits

    return blended


def ca_forward_qkv(token_ids: List[int], *,
                    n_blocks: int = 3,
                    embed_rule: Optional[np.ndarray] = None,
                    block_rules: Optional[List[dict]] = None,
                    output_rule: Optional[np.ndarray] = None,
                    norm_rule: Optional[np.ndarray] = None,
                    vocab_size: int = 256,
                    side: int = 16,
                    base_seed: int = 0xCAF0FE,
                    output_ticks: int = 2,
                    trace: Optional[list] = None,
                    ) -> np.ndarray:
    """End-to-end fully-CA forward pass.  Every step is a CA tick:
    embedding (already CA), block (Q/K/V/score/mix/merge/MLP rules,
    all CA), final layer-norm (norm_rule, CA), output head (output_rule
    diffusion + cell counting, CA).

    `block_rules` is a list of n_blocks dicts, each with keys:
        q, k, v, score, mix, merge, mlp
    Each value is a 16,384-byte rule table.  Defaults (when None) are
    auto-generated from `base_seed` so the model is runnable out of the
    box; the GA picks better ones."""
    if not token_ids:
        return np.zeros(vocab_size, dtype=np.float64)
    if embed_rule is None:
        embed_rule = random_rule_table(base_seed)
    if block_rules is None:
        block_rules = []
        for i in range(n_blocks):
            block_rules.append({
                'q':     random_rule_table(base_seed ^ (0x1000 + i)),
                'k':     random_rule_table(base_seed ^ (0x2000 + i)),
                'v':     random_rule_table(base_seed ^ (0x3000 + i)),
                'score': random_rule_table(base_seed ^ (0x4000 + i)),
                'mix':   random_rule_table(base_seed ^ (0x5000 + i)),
                'merge': random_rule_table(base_seed ^ (0x6000 + i)),
                'mlp':   random_rule_table(base_seed ^ (0x7000 + i)),
            })
    if len(block_rules) != n_blocks:
        raise ValueError('block_rules must have length n_blocks')
    if norm_rule is None:
        norm_rule = default_norm_rule(base_seed ^ 0x8000)
    if output_rule is None:
        output_rule = default_output_rule(base_seed ^ 0x9000)

    # 1. Embed (CA).
    states = ca_embed_sequence(token_ids, embed_rule=embed_rule, side=side)
    if trace is not None:
        trace.append({'name': 'embed', 'grid': states[-1]})
    # 2. Stack of N transformer blocks (each = 7 rule tables, all CA).
    for bi, r in enumerate(block_rules):
        # Sub-trace per block so block-prefixed names roll up cleanly.
        block_trace = [] if trace is not None else None
        states = ca_transformer_block_qkv(states,
                                            q_rule=r['q'], k_rule=r['k'],
                                            v_rule=r['v'],
                                            score_rule=r['score'],
                                            mix_rule=r['mix'],
                                            merge_rule=r['merge'],
                                            mlp_rule=r['mlp'],
                                            norm_rule=norm_rule,
                                            trace=block_trace)
        if trace is not None:
            for item in block_trace:
                trace.append({**item,
                                'name': f'b{bi}-{item["name"]}'})
    # 3. Final layer-norm on the last token (CA).
    final_last = ca_layer_norm_iterative(states[-1], norm_rule)
    if trace is not None:
        trace.append({'name': 'norm-final', 'grid': final_last})
    # 4. Output head (CA): diffuse + count cells.
    if trace is not None:
        # Capture the post-diffusion grid the output head counts over;
        # gives the user a visual of where logits come from.
        from .primitives import hex_ca_step
        out_work = final_last.copy().astype(np.uint8) & 3
        for _ in range(output_ticks):
            out_work = hex_ca_step(out_work, output_rule)
        trace.append({'name': 'output', 'grid': out_work})
    return ca_output_head_iterative(final_last,
                                      output_rule=output_rule,
                                      vocab_size=vocab_size,
                                      k_ticks=output_ticks)


def nano_gpt(token_ids: List[int], *,
              vocab_size: int = 256,
              base_seed: int = 0xCAF0FE,
              **forward_kw) -> np.ndarray:
    """The L2 composition slot from caformer/components.py made literal:
    embedding → 3 transformer blocks → final layer-norm → output head,
    every step a CA tick.  Thin wrapper around `ca_forward_qkv` with
    ``n_blocks=3`` pinned so the *name* nano_gpt actually exists in
    code instead of being a docstring promise."""
    return ca_forward_qkv(token_ids, n_blocks=3, vocab_size=vocab_size,
                            base_seed=base_seed, **forward_kw)


def chat_gpt2_shape(token_ids: List[int], *,
                     vocab_size: int = 256,
                     base_seed: int = 0xCAF02,
                     **forward_kw) -> np.ndarray:
    """The L3 composition slot — "4 nanoGPTs in series", i.e. 12
    transformer blocks of CAs total.  Thin wrapper around
    ``ca_forward_qkv`` with ``n_blocks=12`` pinned.

    Sequential composition is just block-stacking from the GA's point
    of view (each block has its own 7 evolvable rule tables); the
    "4 nanoGPTs" framing is conceptual scaffolding.  ~12× the
    per-step cost of ``nano_gpt`` but not 12× wall-clock — the
    Python-side overhead per primitive call dominates the hex_ca_step
    arithmetic at small grid sizes."""
    return ca_forward_qkv(token_ids, n_blocks=12, vocab_size=vocab_size,
                            base_seed=base_seed, **forward_kw)


def chat_gpt3_shape(token_ids: List[int], *,
                     vocab_size: int = 256,
                     base_seed: int = 0xCAF03,
                     n_branches: int = 4,
                     blend: str = 'sum',
                     **forward_kw) -> np.ndarray:
    """The L4 composition — "4 ChatGPT-2s in parallel for 4 different
    attentions" with a final blend across the four logit vectors.
    Realised here as ``n_branches`` independent calls to
    ``chat_gpt2_shape`` (each gets its own ``base_seed`` so every
    branch evolves its own 12 × 7 rule tables) followed by a blend.

    Blend modes:
      ``sum``   — element-wise sum of the four logit vectors (default;
                  cheapest; the macro-scale analogue of multi-head
                  attention's concat→project step)
      ``vote``  — majority argmax across branches: each branch votes
                  for its top logit; the winning vocab index gets a
                  high logit in the output, others get zero.

    Cost is ``n_branches`` × the cost of ``chat_gpt2_shape`` —
    embarrassingly parallel in principle (the four branches share no
    state) but evaluated sequentially here for simplicity.  Run on a
    small ``vocab_size`` first; this is the slowest composition in
    the ladder.
    """
    if blend not in ('sum', 'vote'):
        raise ValueError(f'blend must be sum|vote, got {blend!r}')
    branch_logits = [
        chat_gpt2_shape(token_ids, vocab_size=vocab_size,
                          base_seed=base_seed ^ (0x10 * (i + 1)),
                          **forward_kw)
        for i in range(n_branches)
    ]
    stacked = np.stack(branch_logits, axis=0)        # (n_branches, V)
    if blend == 'sum':
        return stacked.sum(axis=0)
    # vote: each branch votes for its argmax; counts become the logits.
    out = np.zeros(vocab_size, dtype=np.float64)
    for L in branch_logits:
        out[int(L.argmax())] += 1.0
    return out


_LLM_EXPERT_CACHE: dict = {}
_LLM_BYTEMAP_CACHE: dict = {}


def _load_llm_expert(model_name: str):
    """Load + memoise a (tokenizer, model) pair. Heavy — call once."""
    cached = _LLM_EXPERT_CACHE.get(model_name)
    if cached is not None:
        return cached
    from spoeqi.llm_lora import load_backbone
    tok, model = load_backbone(model_name, device='cpu')
    _LLM_EXPERT_CACHE[model_name] = (tok, model)
    return tok, model


def _llm_byte_projection(tok, vocab_size: int) -> np.ndarray:
    """Build a (V_bpe → V_byte) projection matrix once per (tokenizer,
    vocab_size). Each BPE token's logit is added to the byte-bucket of
    its first decoded byte. Tokens with no decode go to byte 0."""
    cache_key = (id(tok), vocab_size)
    cached = _LLM_BYTEMAP_CACHE.get(cache_key)
    if cached is not None:
        return cached
    V_bpe = len(tok)
    proj = np.zeros((V_bpe,), dtype=np.int32)
    # `tok.decode([id])` does the right thing for every tokenizer
    # variant (GPT-2 fast/slow, BPE, sentencepiece): it returns the
    # actual decoded string of that single token, with whitespace,
    # special-char unrebasing, etc. all handled. Take its first UTF-8
    # byte. Slow (~50k calls) but only runs once per (tokenizer,V)
    # because of the outer cache.
    for tok_id in range(V_bpe):
        try:
            text = tok.decode([tok_id], skip_special_tokens=False)
        except Exception:
            proj[tok_id] = 0
            continue
        if not text:
            proj[tok_id] = 0
            continue
        b = text.encode('utf-8', errors='replace')
        proj[tok_id] = (b[0] if b else 0) % vocab_size
    _LLM_BYTEMAP_CACHE[cache_key] = proj
    return proj


def real_llm_expert_logits(token_ids: List[int], *,
                            model_name: str,
                            vocab_size: int = 256,
                            max_input_tokens: int = 64) -> np.ndarray:
    """Run a real LLM backbone on the byte sequence and project its
    last-token BPE logits down to the byte vocabulary.

    The CA chat layer speaks 256-byte tokens; real LLMs speak BPE.
    Bridge: bytes → str → BPE ids → forward → last-token logits over
    the BPE vocab → sum-project to byte buckets via each BPE token's
    first decoded byte. Lossy but cheap and deterministic.

    Cached: tokenizer + model load once; byte-projection table once
    per (tokenizer, vocab_size). Subsequent calls are just one forward.
    """
    import torch
    if not token_ids:
        return np.zeros(vocab_size, dtype=np.float64)
    tok, model = _load_llm_expert(model_name)
    proj = _llm_byte_projection(tok, vocab_size)
    # Bytes → str. Replace invalid UTF-8 with a placeholder so the
    # tokenizer never explodes on noise from a freshly-seeded CA.
    text = bytes(int(t) & 0xFF for t in token_ids).decode(
        'utf-8', errors='replace')
    enc = tok(text, return_tensors='pt', truncation=True,
              max_length=max_input_tokens)
    input_ids = enc['input_ids']
    if input_ids.shape[1] == 0:
        return np.zeros(vocab_size, dtype=np.float64)
    with torch.no_grad():
        out = model(input_ids=input_ids)
    # logits shape: (1, T, V_bpe). Take last position.
    bpe_logits = out.logits[0, -1].detach().cpu().numpy().astype(np.float64)
    # Marginalise BPE distribution down to bytes: softmax over BPE
    # vocab → sum probabilities into byte buckets via the projection
    # → log-back for return. Naive sum-of-logits leaves empty byte
    # buckets at 0 while populated ones sum to large negatives, so
    # argmax always picks an empty bucket and the LLM signal is lost.
    bpe_logits -= bpe_logits.max()                # numerical stability
    bpe_probs = np.exp(bpe_logits)
    bpe_probs /= bpe_probs.sum()
    byte_probs = np.zeros(vocab_size, dtype=np.float64)
    # `len(tok)` and `model.config.vocab_size` can disagree: some
    # backbones (pythia, llama) pad the embedding matrix to a multiple
    # of 64/128 for kernel efficiency, so logits.shape[-1] > len(tok).
    # Clip both sides to the common prefix — the extra padded slots
    # have no decode mapping anyway.
    n = min(int(proj.shape[0]), int(bpe_probs.shape[0]))
    np.add.at(byte_probs, proj[:n], bpe_probs[:n])
    # Log with a tiny floor so empty buckets become very negative
    # (rather than -inf which would break downstream sampling).
    return np.log(byte_probs + 1e-30)


def chat_gpt3_5_hybrid(token_ids: List[int], *,
                        expert_specs: Optional[List] = None,
                        vocab_size: int = 256,
                        base_seed: int = 0xCAF35,
                        top_k: int = 2,
                        **forward_kw) -> np.ndarray:
    """Hybrid MoE: experts can be either CA (`chat_gpt3_shape`) or a
    real LLM backbone (`real_llm_expert_logits`). The cheap CA router
    decides which top_k experts run per token.

    `expert_specs` is a list whose entries are one of:
      - the literal string 'ca' (use chat_gpt3_shape with derived seed)
      - a tuple ('llm', model_name) (call the named backbone)

    Default expert_specs: 3 CA experts + 1 distilgpt2 expert. The user
    can override to mix in more real-model experts; first call to a
    new model_name pays the load cost, subsequent calls are warm.

    The "cheat" here: the CA does ~all the work (cheap router + cheap
    CA experts), but when the router picks the LLM expert, the real
    model takes over for that one token. The blend is softmax-weighted
    over the chosen experts' router affinities, exactly as in
    `chat_gpt3_5_shape`.
    """
    if expert_specs is None:
        expert_specs = ['ca', 'ca', 'ca', ('llm', 'distilgpt2')]
    n_experts = len(expert_specs)
    if not (1 <= top_k <= n_experts):
        raise ValueError(
            f'top_k must be in [1, n_experts]; got top_k={top_k}, '
            f'n_experts={n_experts}')

    affinities = _moe_router_affinities(token_ids, n_experts, base_seed)
    chosen = np.argsort(affinities)[::-1][:top_k]

    chosen_aff = affinities[chosen]
    chosen_aff = chosen_aff - chosen_aff.max()
    weights = np.exp(chosen_aff)
    weights /= weights.sum()

    blended = np.zeros(vocab_size, dtype=np.float64)
    for j, expert_idx in enumerate(chosen):
        spec = expert_specs[int(expert_idx)]
        expert_seed = (base_seed ^ (0x100 * (int(expert_idx) + 1))) & 0xFFFFFFFF
        if spec == 'ca':
            L = chat_gpt3_shape(token_ids, vocab_size=vocab_size,
                                  base_seed=expert_seed,
                                  n_branches=4, blend='sum',
                                  **forward_kw)
        elif isinstance(spec, (tuple, list)) and len(spec) == 2 \
                and spec[0] == 'llm':
            L = real_llm_expert_logits(token_ids,
                                         model_name=spec[1],
                                         vocab_size=vocab_size)
        else:
            raise ValueError(f'unknown expert spec: {spec!r}')
        blended += weights[j] * L

    return blended


def tower(token_ids: List[int], *,
            n_levels: int = 2,
            vocab_size: int = 256,
            base_seed: int = 0xCAF7088,
            top_k_per_level: int = 8,
            level_kwargs: Optional[List[dict]] = None,
            **forward_kw) -> np.ndarray:
    """L7 — recursive stack of ``chat_gpt3_5_shape`` calls.

    Realises "more CAs = more abstraction" concretely: each level
    runs the L5 MoE-shaped forward, takes the top-k tokens from its
    output logits, feeds those tokens as input to the next level
    (with its own derived ``base_seed``), and so on for ``n_levels``.
    The final level returns vocab logits.

    Why top-k rather than logit-summing across levels: summing
    collapses the "abstraction" idea (every level sees the same
    distribution); top-k forces each level to commit to a few
    candidates and the next level to reason over those commitments
    — actual hierarchical refinement.

    ``level_kwargs[i]`` overrides ``base_seed`` etc. per level. Useful
    when later levels should have different `n_experts` / `top_k`
    than earlier ones (e.g. broad-low → narrow-high).

    Cost: ``n_levels × cost(chat_gpt3_5_shape)``. At 2 levels with
    default knobs this is ~2× the L5 cost; at 4 levels ~4×.
    """
    if n_levels < 1:
        raise ValueError(f'n_levels must be >= 1; got {n_levels}')
    if level_kwargs is not None and len(level_kwargs) != n_levels:
        raise ValueError(
            f'level_kwargs must have length n_levels; '
            f'got {len(level_kwargs)} vs {n_levels}')

    seq = list(token_ids)
    last_logits = None
    for level in range(n_levels):
        kw = dict(forward_kw)
        if level_kwargs is not None:
            kw.update(level_kwargs[level])
        seed = (base_seed ^ (0x10000 * (level + 1))) & 0xFFFFFFFF
        last_logits = chat_gpt3_5_shape(
            seq, vocab_size=vocab_size,
            base_seed=kw.pop('base_seed', seed), **kw)
        if level < n_levels - 1:
            # Distil this level's logits into the next level's input
            # by taking the top-k tokens — a hard commitment that
            # forces the next level to actually re-process them.
            top = np.argsort(last_logits)[::-1][:top_k_per_level]
            seq = list(map(int, top))
    return last_logits


def ca_generate_qkv(prompt_ids: List[int], *,
                     max_new_tokens: int = 8,
                     n_blocks: int = 3,
                     vocab_size: int = 256,
                     temperature: float = 1.0,
                     sample_seed: int = 0,
                     allowed_bytes=None,
                     **forward_kw) -> List[int]:
    """Autoregressive generation through the fully-CA forward pass.
    Every step in every iteration is a ``hex_ca_step`` invocation.
    Significantly slower than ``ca_generate`` (which uses the
    reductive forward path) — measure before scaling.

    ``allowed_bytes`` (optional set/iterable of ints) constrains the
    sampler to those bytes only — pass ``ASCII_PRINTABLE`` for legible
    output, or a corpus-derived alphabet to only emit what the model
    has actually seen during training."""
    from .primitives import ca_softmax_sample
    seq = list(prompt_ids)
    out = []
    for step in range(max_new_tokens):
        logits = ca_forward_qkv(seq, n_blocks=n_blocks,
                                  vocab_size=vocab_size, **forward_kw)
        next_id, _ = ca_softmax_sample(
            logits, temperature=temperature, ca_seed=sample_seed ^ step,
            allowed_bytes=allowed_bytes)
        seq.append(next_id)
        out.append(next_id)
    return out


def ca_generate(prompt_ids: List[int], *,
                 max_new_tokens: int = 16,
                 n_blocks: int = 3,
                 vocab_size: int = 256,
                 temperature: float = 1.0,
                 sample_seed: int = 0,
                 allowed_bytes=None,
                 **forward_kw) -> List[int]:
    """Autoregressive generation: at each step run `ca_forward`, sample
    the next token via `ca_softmax_sample`, append, repeat.  Returns
    the generated continuation only (not the prompt).

    See ``ca_generate_qkv`` for ``allowed_bytes``."""
    seq = list(prompt_ids)
    out = []
    for step in range(max_new_tokens):
        logits = ca_forward(seq, n_blocks=n_blocks,
                              vocab_size=vocab_size, **forward_kw)
        next_id, _ = ca_softmax_sample(
            logits, temperature=temperature,
            ca_seed=sample_seed ^ step,
            allowed_bytes=allowed_bytes)
        seq.append(next_id)
        out.append(next_id)
    return out
