"""caformer/reductive.py — irreducible-core versions of each CA op.

For every richer primitive in caformer/primitives.py, this module
ships the *simplest possible* working version.  When you're trying to
prove the whole stack composes, start with the reductive ones — fewer
moving parts, easier to debug, faster to evolve.

Pattern: every reductive function mirrors a `primitives.py` function
with the same name + `_min` suffix.  If it can't get any smaller and
still do its job, it's the right size.
"""

from __future__ import annotations
import numpy as np
from typing import Tuple


# ─── softmax: drop the noise, pick the largest logit ───────────────
def ca_softmax_sample_min(logits: np.ndarray) -> int:
    """Reductive softmax = argmax.  No CA, no noise, no temperature.
    The CA-sampled version (`primitives.ca_softmax_sample`) wraps this
    by adding deterministic Gumbel-style noise — strip the noise and
    you get the irreducible core."""
    return int(np.argmax(logits))


# ─── MLP: one CA tick, no hidden expansion ─────────────────────────
def ca_mlp_min(state: np.ndarray, rule_table: np.ndarray) -> np.ndarray:
    """Reductive MLP = one tick of the CA rule.  No 4× hidden grid,
    no multi-step composition.  This is the smallest non-trivial
    transformation a CA can apply per layer."""
    from .primitives import hex_ca_step
    return hex_ca_step(state.astype(np.uint8), rule_table)


# ─── layer norm: shift colour 0 to mean ─────────────────────────────
def ca_layer_norm_min(state: np.ndarray) -> np.ndarray:
    """Reductive layer-norm = subtract the modal colour from every cell
    (clamped to 0..3).  Replaces real LN's centring step; skips
    rescaling entirely.  Trivially fast, deterministic."""
    flat = state.flatten().astype(np.int32)
    if flat.size == 0:
        return state
    counts = np.bincount(flat, minlength=4)
    mode = int(counts.argmax())
    out = (flat - mode) % 4
    return out.astype(np.uint8).reshape(state.shape)


# ─── attention: nearest-cell only ───────────────────────────────────
def ca_attention_min(states: list, rule_table: np.ndarray) -> list:
    """Reductive self-attention: each token's new state = one CA tick
    applied to (its own state XOR the next token's state).  No Q/K/V,
    no softmax over the sequence, no weighted aggregation — just
    look-at-your-neighbour.  T tokens in, T tokens out.

    `states[i]` is a 16×16 uint8 grid (one component-CA per token)."""
    from .primitives import hex_ca_step
    if not states:
        return []
    n = len(states)
    out = []
    for i, s in enumerate(states):
        nxt = states[(i + 1) % n]
        mixed = (s.astype(np.uint8) ^ nxt.astype(np.uint8)) & 3
        out.append(hex_ca_step(mixed, rule_table))
    return out


# ─── transformer block: attention then MLP, no norms, no residuals ──
def transformer_block_min(states: list,
                            attn_rule: np.ndarray,
                            mlp_rule:  np.ndarray) -> list:
    """Reductive transformer block: attention_min then mlp_min on each
    output state.  No layer-norms, no residuals.  Composes the smallest
    possible "block" that still has the attention-then-MLP shape."""
    after_attn = ca_attention_min(states, attn_rule)
    return [ca_mlp_min(s, mlp_rule) for s in after_attn]


# ─── nanoGPT: one block, not three ──────────────────────────────────
def nano_gpt_min(states: list,
                   attn_rule: np.ndarray,
                   mlp_rule:  np.ndarray) -> Tuple[list, np.ndarray]:
    """Reductive nanoGPT = embedding (assumed pre-built as `states`) +
    one transformer block + read out the last state's argmax-per-cell
    as the "logits".  Real nanoGPT stacks 3 blocks; this stacks 1.

    Returns (final_states, logits_for_last_token)."""
    final = transformer_block_min(states, attn_rule, mlp_rule)
    if not final:
        return [], np.zeros(0, dtype=np.uint8)
    last = final[-1]
    # Reductive "lm_head": flatten the last token's grid and treat as logits.
    logits = last.flatten().astype(np.int32)
    return final, logits


# ─── DMN: no buffer, no LLM, just CA → text-hash → CA ──────────────
# ─── self-reflection: the looping-back primitive ───────────────────
#
# Hofstadter / Gödel: the self-referential loop is where the
# meaningful self-reference lives.  This is the irreducible version
# — a CA whose next input is a function of its own prior output,
# with no external signal.  If meaningful structure can emerge from
# *this*, the same loop wrapped around any larger model is doing the
# same trick at a different scale.

def self_reflection_min(rule_table: np.ndarray, *,
                          side: int = 16,
                          starting_seed: int = 0xCAFEBABE,
                          steps: int = 32,
                          ):
    """The smallest possible "system reflecting on itself" loop.  At
    every tick the CA's *own state* is hashed and that hash is folded
    back into a perturbation of the next tick — there is literally no
    other input.

    Yields (tick, state_copy, hash_hex_short).  Caller can watch for:
      - cycles (state at tick T == state at tick T+k)
      - drifts (state slowly migrates through state space)
      - attractors (state stabilises after some ticks)

    All three are interesting; the hardest is the drift, which is what
    we'd expect a 'thinking' system to do."""
    import hashlib
    from .primitives import hex_ca_step, lcg_bytes
    state = (lcg_bytes(starting_seed, side * side) & 3).reshape(side, side)
    for tick in range(steps):
        state = hex_ca_step(state, rule_table)
        h = hashlib.sha256(state.tobytes()).digest()
        # Loop back: every CA cell is XOR'd with one bit of the hash
        # of its own state.  Hash is only 32 bytes — tile it to cover
        # the full grid so the entire state participates in the
        # reflection (otherwise larger grids would only "reflect" on
        # their first 32 cells).
        h_arr = np.frombuffer(h, dtype=np.uint8)
        n = state.size
        reps = (n + h_arr.size - 1) // h_arr.size
        h_bits = np.tile(h_arr, reps)[:n] & 3
        state = (state.flatten() ^ h_bits).reshape(state.shape) & 3
        yield tick, state.copy(), h.hex()[:16]


def dmn_loop_min(rule_table: np.ndarray, *,
                   side: int = 16,
                   starting_seed: int = 0xDEADBEEF,
                   max_steps: int = 16):
    """Reductive default-mode loop: a single CA evolves, its state hash
    seeds the next initial perturbation, no LLM, no chain, no buffer.
    Yields (tick, ca_state_hash) for `max_steps` iterations.

    The interesting question this lets you ask without any other
    machinery: does the loop fall into a short cycle, or wander
    indefinitely?"""
    import hashlib
    from .primitives import hex_ca_step, lcg_bytes
    seed = starting_seed
    state = (lcg_bytes(seed, side * side) & 3).reshape(side, side)
    for tick in range(max_steps):
        state = hex_ca_step(state, rule_table)
        h = hashlib.sha256(state.tobytes()).digest()
        new_seed = int.from_bytes(h[:4], 'big')
        # Perturb a single cell using the seed-derived index/colour so
        # the hash actually drives subsequent dynamics (without a
        # perturbation, the CA would just iterate its own rule cycle).
        idx = new_seed % (side * side)
        colour = (new_seed >> 16) & 3
        flat = state.flatten()
        flat[idx] = colour
        state = flat.reshape(side, side)
        yield tick, h.hex()[:16]
        seed = new_seed
