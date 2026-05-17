"""caformer/primitives.py — runnable CA stand-ins for transformer ops.

The escalation strategy: try replacing each transformer op with a
*single class-4 hex CA*; if that doesn't preserve enough of the op's
behaviour, scale up to a chain or network of CAs.  This module is the
"single CA tried first" layer.

Currently runnable:
    ca_softmax_sample  — replaces softmax + multinomial sampling
    ca_mlp             — replaces an MLP block (per-token nonlinearity)
    hex_ca_step        — the underlying 4-state, 7-cell-neighbourhood step

All deterministic given their numeric inputs — same args in → same
result out, no float drift, no entropy from the OS.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Tuple

import numpy as np


# ─── Park-Miller LCG: byte source for rule tables and noise ────────
# Same constants as isolation/artifacts/hexhunter/hexhunter.c so any
# port (C / Python / JS / ESP) generates byte-identical streams.

def lcg_bytes(seed: int, n: int) -> np.ndarray:
    """`n` deterministic bytes from a Park-Miller-style LCG.  Plain
    Python ints inside the loop so numpy's uint32-overflow warnings
    don't fire on the natural wraparound.  Distinct seeds always
    produce distinct streams (no `seed | 1` collision)."""
    state = int(seed) & 0xFFFFFFFF
    if state == 0:                          # only the all-zero fixed point matters
        state = 1
    out = np.empty(n, dtype=np.uint8)
    mult = 1103515245
    add  = 12345
    mask = 0xFFFFFFFF
    for i in range(n):
        state = (state * mult + add) & mask
        out[i] = (state >> 16) & 0xFF
    return out


@lru_cache(maxsize=512)
def _random_rule_table_cached(seed: int) -> bytes:
    """Cache-key carrier: returns immutable bytes so the cache can't be
    mutated by callers.  Wrap with random_rule_table() for an array view."""
    return bytes(lcg_bytes(seed, 16384) & np.uint8(3))


def random_rule_table(seed: int) -> np.ndarray:
    """A 16,384-entry K=4 hex-CA rule table seeded from `seed`.
    Each entry holds the next-state colour (0..3) for one 7-cell
    configuration (self + 6 hex neighbours).

    Cached by seed: previously this rebuilt the rule from scratch on
    every forward pass (lcg_bytes is a Python loop over 16,384 bytes,
    ~2 ms each), so a tiny chat with n_blocks=2 wasted ~150 ms
    regenerating the same 7×n_blocks + 3 rules every iteration.  The
    cache returns a fresh ndarray view onto the cached bytes so callers
    can still mutate it locally without poisoning the cache."""
    return np.frombuffer(_random_rule_table_cached(int(seed)),
                          dtype=np.uint8).copy()


# ─── Hex CA step — one tick, K=4, 7-cell pointy-top neighbourhood ──
#
# Same indexing scheme as spoeqi.keystream._step and the workspace
# app2_caview.c, so byte-streams stay cross-component compatible.

def hex_ca_step(state: np.ndarray, rule_table: np.ndarray) -> np.ndarray:
    """One generation.  `state` is a (H, W) uint8 array of 0..3 colours;
    `rule_table` is the 16,384-entry table.  Returns a new array of
    the same shape with toroidal boundary conditions."""
    if state.dtype != np.uint8:
        state = state.astype(np.uint8)
    H, W = state.shape
    out = np.empty_like(state)
    # Pre-compute axis rolls — vectorised hex neighbourhood.
    # Row-parity-dependent NW/NE neighbours (pointy-top).
    n_up   = np.roll(state, 1, axis=0)
    n_dn   = np.roll(state, -1, axis=0)
    n_l    = np.roll(state, 1, axis=1)
    n_r    = np.roll(state, -1, axis=1)
    n_up_l = np.roll(n_up, 1, axis=1)
    n_up_r = np.roll(n_up, -1, axis=1)
    n_dn_l = np.roll(n_dn, 1, axis=1)
    n_dn_r = np.roll(n_dn, -1, axis=1)

    # Even rows: NW = up-left,  NE = up.        SW = down-left,  SE = down.
    # Odd rows:  NW = up,        NE = up-right.  SW = down,       SE = down-right.
    rows = np.arange(H)[:, None]
    even = (rows & 1) == 0
    n_nw = np.where(even, n_up_l, n_up)
    n_ne = np.where(even, n_up,   n_up_r)
    n_sw = np.where(even, n_dn_l, n_dn)
    n_se = np.where(even, n_dn,   n_dn_r)

    key = ((state.astype(np.uint16) << 12)
            | (n_nw.astype(np.uint16) << 10)
            | (n_ne.astype(np.uint16) << 8)
            | (n_r.astype(np.uint16) << 6)
            | (n_se.astype(np.uint16) << 4)
            | (n_sw.astype(np.uint16) << 2)
            | n_l.astype(np.uint16))
    out = rule_table[key]
    return out.astype(np.uint8)


# ─── ca_softmax_sample — softmax + multinomial via CA-derived noise ──
#
# Replacing softmax in the transformer's output head.  The classical
# operation is `argmax(softmax(logits / T) + Gumbel-noise)` for
# temperature sampling — equivalent to multinomial sampling from
# softmax(logits/T).  Here we provide the Gumbel noise from CA bytes,
# making the whole chain deterministic given (logits, T, ca_seed).
#
# This is the "single CA per op" version.  If a richer distribution
# is needed, scale up: run multiple CA grids in parallel and average.

def gumbel_from_bytes(b: np.ndarray, n: int) -> np.ndarray:
    """`n` Gumbel(0, 1) samples derived from `b` (uint8 array, repeated
    if too short).  Inverse-CDF: G = -log(-log(U)), U ∈ (0, 1)."""
    if b.size == 0:
        raise ValueError('need at least one byte')
    # Tile bytes to length n; convert to uniforms in (0, 1) avoiding 0.
    reps = (n + b.size - 1) // b.size
    tile = np.tile(b.astype(np.float64), reps)[:n]
    # Map 0..255 → (1/512, 511/512) so log() is finite.
    u = (tile + 0.5) / 256.0
    return -np.log(-np.log(u))


ASCII_PRINTABLE = frozenset(range(32, 127)) | {10, 13}    # + LF + CR


def ca_softmax_sample(logits: np.ndarray, *,
                       temperature: float = 1.0,
                       ca_seed: int = 42,
                       ca_ticks: int = 8,
                       grid_side: int = 16,
                       allowed_bytes=None,
                       ) -> Tuple[int, np.ndarray]:
    """CA-noised softmax sampling.  Returns (sampled_index, gumbel_noise).

    Pipeline:
      1. Run a hex CA from `ca_seed` for `ca_ticks` steps to produce a
         deterministic byte stream.
      2. Convert the bytes into Gumbel(0, 1) noise.
      3. argmax(logits / T  +  noise)  —  Gumbel-max trick = sampling.

    `temperature → 0` collapses to argmax(logits) (greedy decoding);
    `temperature → ∞` collapses to argmax(noise) (uniform sampling).

    ``allowed_bytes`` (optional iterable of ints in [0, n)): if given,
    every index NOT in this set has its logit forced to -inf before
    sampling — so the sampler can only pick from the allowed set.
    Use ``ASCII_PRINTABLE`` to constrain to readable bytes, or a
    corpus-derived alphabet to constrain to what the model has seen.

    The CA-as-noise-source is the *single-CA* implementation called out
    in the design notes.  More elaborate variants (multiple CA grids
    voting, attention-conditioned noise) are the "scale up" path.
    """
    n = logits.shape[0]
    if n == 0:
        raise ValueError('logits is empty')

    # Optional alphabet mask: force disallowed positions to -inf so the
    # softmax assigns them zero probability and the Gumbel-max trick
    # cannot pick them. Done BEFORE temperature scaling so -inf survives.
    if allowed_bytes is not None:
        allowed_set = (allowed_bytes if isinstance(allowed_bytes, (set, frozenset))
                        else frozenset(int(b) for b in allowed_bytes))
        masked = logits.astype(np.float64).copy()
        for i in range(n):
            if i not in allowed_set:
                masked[i] = -np.inf
        logits = masked

    # 1. Step a CA from the seed.
    rule = random_rule_table(ca_seed)
    state = (lcg_bytes(ca_seed ^ 0xA5A5A5A5, grid_side * grid_side) & 3
              ).reshape(grid_side, grid_side)
    for _ in range(ca_ticks):
        state = hex_ca_step(state, rule)

    # 2. Noise from the final CA state.
    noise = gumbel_from_bytes(state.flatten(), n)

    # 3. Gumbel-max sampling. With -inf logits, those positions stay
    # at -inf after + noise (finite + -inf = -inf) so argmax skips them.
    if temperature <= 0:
        return int(np.argmax(logits)), noise
    scaled = logits.astype(np.float64) / temperature
    sampled = int(np.argmax(scaled + noise))
    return sampled, noise


# ─── ca_mlp — per-token MLP via multi-tick CA evolution ──────────────
#
# Real MLP: y = W_2 · GELU(W_1 · x + b_1) + b_2  (hidden dim = 4·C)
# Single-CA replacement:
#     y = state-after-k-ticks-of-fixed-rule(x)
# The CA rule plays the combined role of W_1, GELU non-linearity, and
# W_2 (the multi-tick computation gives effective depth).
#
# `expand=True` adds a 4× hidden expansion: tile input 2×2 to a wider
# grid before iteration, then majority-pool back.  This is the analogue
# of GPT's 4× FFN dim expansion.

def _tile_2x2(state: np.ndarray) -> np.ndarray:
    """Each cell expanded to a 2×2 block of the same colour."""
    return np.repeat(np.repeat(state, 2, axis=0), 2, axis=1)


def _majority_pool_2x2(state: np.ndarray) -> np.ndarray:
    """Reduce by majority vote in each 2×2 block.  Ties broken by min
    colour so the operation is deterministic.

    Vectorised: was a Python double loop calling `np.unique` per tile
    (22% of `ca_forward_qkv` time per profile).  Now we count colour
    occurrences across the four cells in each block by stacking
    one-hot indicators, then `argmax` along the colour axis — argmax
    returns the first maximum, so ties break by smaller colour for
    free.  ~30× faster on a 32×32 grid."""
    H, W = state.shape
    if H % 2 or W % 2:
        raise ValueError('state must have even dimensions for 2×2 pool')
    tiles = state.reshape(H // 2, 2, W // 2, 2).astype(np.uint8) & 3
    # counts[..., c] = number of cells in this 2×2 block with colour c
    counts = np.stack([(tiles == c).sum(axis=(1, 3)) for c in range(4)],
                       axis=-1)
    return np.argmax(counts, axis=-1).astype(np.uint8)


def ca_mlp(state: np.ndarray, *,
            rule_table: np.ndarray,
            k_ticks: int = 4,
            expand: bool = True,
            ) -> np.ndarray:
    """Apply `k_ticks` of the given rule to `state`.  When `expand`,
    tile the input 2×2 to a wider grid first (the 4× FFN-dim analogue),
    then majority-pool back to the original shape.

    Returns: array of the same shape as input `state`."""
    if state.dtype != np.uint8:
        state = state.astype(np.uint8) & 3
    work = _tile_2x2(state) if expand else state.copy()
    for _ in range(k_ticks):
        work = hex_ca_step(work, rule_table)
    if expand:
        work = _majority_pool_2x2(work)
    return work


# ─── ca_layer_norm — colour-histogram re-balancing ─────────────────
#
# A first-cut LayerNorm replacement: re-pack the cells so the colour
# histogram matches a target (default = uniform).  Preserves spatial
# rank — the cell that was the highest-colour stays the highest.
#
# This is much weaker than real LayerNorm but it does the load-bearing
# job: re-centre the activation distribution before downstream layers.

# ─── ca_embedding — token ID → CA state ────────────────────────────
#
# Real LLM: x = wte[token_id]; one row of the V × C learned table.
# CA replacement: each token ID seeds a CA from a deterministic byte
# stream (LCG keyed by token_id), which is then iterated for n_ticks
# under a fixed rule.  The post-iteration state IS the embedding.
#
# Properties this gives us:
#   - identical token IDs always produce identical embeddings (good)
#   - similar token IDs produce *different* embeddings (chaotic CA)
#   - no learned table — the rule + LCG IS the embedding function
# The "learning" lives in the rule choice; same place as in MLP/attn.

def ca_embedding(token_id: int, *,
                  rule_table: np.ndarray,
                  side: int = 16,
                  n_ticks: int = 4,
                  domain: int = 0xE7BED1,
                  ) -> np.ndarray:
    """Deterministic CA-state embedding for `token_id`.

    `domain` lets you carve disjoint embedding spaces — pass a
    different domain for positional embeddings vs. token embeddings
    so the bytes don't collide."""
    seed = (int(token_id) ^ int(domain)) & 0xFFFFFFFF
    state = (lcg_bytes(seed, side * side) & 3).reshape(side, side)
    for _ in range(n_ticks):
        state = hex_ca_step(state, rule_table)
    return state


def ca_positional_embedding(position: int, *,
                              rule_table: np.ndarray,
                              side: int = 16,
                              n_ticks: int = 4,
                              ) -> np.ndarray:
    """Positional embedding via a separate-domain CA tap.  Same shape
    as ca_embedding so they can be combined cell-wise."""
    return ca_embedding(position, rule_table=rule_table, side=side,
                         n_ticks=n_ticks, domain=0x9051710)


# ─── ca_residual — combine two CA states (the skip connection) ─────
#
# Real LLM: h = h + sublayer(h).
# CA replacement: blend two CA states cell-wise.  Two operators are
# meaningful and we provide both:
#   xor       — information-preserving, commutative; "remembers both"
#   majority  — picks the modal colour; "smoothes both"

def ca_residual(state_a: np.ndarray, state_b: np.ndarray, *,
                 mode: str = 'xor') -> np.ndarray:
    """Residual blend of two CA states.  `mode='xor'` is the default
    because it preserves bit-information (you can recover one input
    from the other if you have the result), which is closer in spirit
    to the additive residual used in real Transformers."""
    if state_a.shape != state_b.shape:
        raise ValueError(f'shape mismatch: {state_a.shape} vs {state_b.shape}')
    a = state_a.astype(np.uint8) & 3
    b = state_b.astype(np.uint8) & 3
    if mode == 'xor':
        return (a ^ b) & 3
    if mode == 'majority':
        # Count occurrences of each colour at each position across both
        # inputs and pick the more frequent one.  Ties → smaller colour
        # so the operation is deterministic.
        out = np.where(a == b, a, np.minimum(a, b))
        return out.astype(np.uint8)
    if mode == 'add':
        return ((a.astype(np.int32) + b.astype(np.int32)) % 4).astype(np.uint8)
    raise ValueError(f'unknown residual mode {mode!r}')


# ─── ca_output_head — final state → vocab logits ───────────────────
#
# Real LLM: logits = h_final · W_outᵀ.
# CA replacement: hash each cell's (position, colour) into a vocab
# index and accumulate.  The resulting per-vocab counts are the
# "logits"; their argmax is the next-token prediction.

def ca_output_head(state: np.ndarray, vocab_size: int = 256) -> np.ndarray:
    """Map a CA state to a length-`vocab_size` logit vector.

    Each cell contributes 1.0 to the vocab index `(position * 4 + colour)
    mod vocab_size`.  Cells of colour 0 are weighted lower (×0.25) so
    a state that's mostly background contributes less than one
    saturated with non-zero colours.  Returns float64 array."""
    H, W = state.shape
    logits = np.zeros(vocab_size, dtype=np.float64)
    flat = state.flatten().astype(np.uint16)
    positions = np.arange(flat.size, dtype=np.uint16)
    indices = (positions * 4 + flat) % vocab_size
    weights = np.where(flat == 0, 0.25, 1.0)
    np.add.at(logits, indices, weights)
    return logits


def ca_layer_norm(state: np.ndarray,
                   target: Tuple[float, float, float, float] = (0.25, 0.25, 0.25, 0.25),
                   ) -> np.ndarray:
    """Permute cell colours so the output histogram matches `target`.
    Cells are sorted by their original colour (with position as tie-
    break) and reassigned to colours according to the target quantile
    boundaries.

    This is the *idealised* layer-norm — exact histogram match, not a
    CA.  See `ca_layer_norm_iterative` for a CA-only approximation
    that runs `k_ticks` of a balance-promoting CA rule and approaches
    this target over time."""
    if abs(sum(target) - 1.0) > 1e-6:
        raise ValueError(f'target probabilities must sum to 1, got {sum(target)}')
    flat = state.flatten().astype(np.uint8)
    n = flat.size
    # Stable rank: original colour, then linear position.
    order = np.lexsort((np.arange(n), flat))
    out = np.empty_like(flat)
    cum = 0
    for c, frac in enumerate(target):
        upto = round(n * (cum + frac))
        out[order[int(round(n * cum)):upto]] = c
        cum += frac
    return out.reshape(state.shape)


# ──────────────────────────────────────────────────────────────────
# Fully-CA layer.  Everything below this line is a `hex_ca_step`
# composition — no Python permutations, no modular arithmetic, no
# float math except for the CA-noise-derived Gumbel sample.  This is
# what makes caformer's claim "everything is a CA" literal rather
# than aspirational.
# ──────────────────────────────────────────────────────────────────


@lru_cache(maxsize=64)
def _default_norm_rule_cached(seed: int) -> bytes:
    """Vectorised builder for the balance-promoting norm rule.

    Was a 16,384-iteration Python loop with `[].count()` and `np.argmin`
    inside (47% of `ca_forward_qkv` time per profile).  Now: build the
    7-digit base-4 indices as a single int array, count colour
    occurrences with bincount-style indexing, pick the least-represented
    colour with `np.lexsort` so ties break by smaller colour for
    determinism.  Result cached by seed."""
    keys = np.arange(16384, dtype=np.uint16)
    # Each key encodes 7 cells, 2 bits each: shifts (12, 10, 8, 6, 4, 2, 0).
    shifts = np.array([12, 10, 8, 6, 4, 2, 0], dtype=np.uint16)
    cells = (keys[:, None] >> shifts) & 3       # (16384, 7)
    # counts[k, c] = how many of the 7 cells in key k have colour c.
    counts = np.zeros((16384, 4), dtype=np.int8)
    for c in range(4):
        counts[:, c] = (cells == c).sum(axis=1)
    # Tie-break by smaller colour: argmin returns the first minimum.
    rule = np.argmin(counts, axis=1).astype(np.uint8)
    # Light jitter so distinct seeds give distinct rules (GA dimension).
    jitter = lcg_bytes(seed, 64)
    for i in range(64):
        slot = (int(jitter[i]) << 6) | (i & 0x3F)
        rule[slot & 0x3FFF] = jitter[i] & 3
    return bytes(rule)


def default_norm_rule(seed: int = 0xBA1A11CE) -> np.ndarray:
    """Deterministic 16,384-entry rule designed to push toward
    histogram balance.  For each (self, n0..n5) configuration we pick
    the colour least represented in the 7-cell neighbourhood — over
    many ticks this rule encourages cells to differentiate from
    their neighbours, which in expectation flattens the global
    histogram toward uniform.

    `seed` lets you generate a *family* of balance-promoting rules
    by jittering one slot in 256 with a random colour, useful when
    the GA wants diversity in the norm-rule population.
    """
    return np.frombuffer(_default_norm_rule_cached(int(seed)),
                          dtype=np.uint8).copy()


def default_output_rule(seed: int = 0xCAFEFEED) -> np.ndarray:
    """Rule for the output head's spread phase.  Same shape as any
    other rule table.  Seeded from a deterministic LCG so reproducibility
    is guaranteed, and the GA can evolve it as just-another-rule once
    the rest of the stack works."""
    return random_rule_table(seed)


def ca_qkv_project(state: np.ndarray, rule_table: np.ndarray, *,
                    k_ticks: int = 1) -> np.ndarray:
    """Apply `k_ticks` of `rule_table` to `state` to produce a Q, K, or V
    representation.  In a real transformer Q/K/V come from three
    different learned linear maps; in CA-land they come from three
    different CA rules applied to the same input grid.  The "learning"
    is choosing the rule (which the GA evolves)."""
    if state.dtype != np.uint8:
        state = state.astype(np.uint8) & 3
    work = state.copy()
    for _ in range(k_ticks):
        work = hex_ca_step(work, rule_table)
    return work


def ca_attention_score(q_state: np.ndarray, k_state: np.ndarray,
                        score_rule: np.ndarray) -> int:
    """CA-derived pair similarity score.  Stack Q above K as a (2H, W)
    grid, run one tick of `score_rule`, count "low" cells (colours 0+1)
    in the top half.  More matches → higher score.  Returns int ≥ 0."""
    if q_state.shape != k_state.shape:
        raise ValueError(
            f'Q/K shape mismatch: {q_state.shape} vs {k_state.shape}')
    stacked = np.vstack([q_state.astype(np.uint8) & 3,
                          k_state.astype(np.uint8) & 3])
    mixed = hex_ca_step(stacked, score_rule)
    H, _ = q_state.shape
    top = mixed[:H]
    return int(np.sum(top < 2))


def ca_self_attention(states, *,
                       q_rule: np.ndarray,
                       k_rule: np.ndarray,
                       v_rule: np.ndarray,
                       score_rule: np.ndarray,
                       mix_rule: np.ndarray,
                       causal: bool = True,
                       trace: Optional[list] = None):
    """Full CA Q/K/V self-attention.

    For each token i:
      Q_i = ca_qkv_project(states[i], q_rule)
      K_i = ca_qkv_project(states[i], k_rule)
      V_i = ca_qkv_project(states[i], v_rule)
      For each j (≤ i if causal): w_ij = ca_attention_score(Q_i, K_j, score_rule)
      j*  = argmax_j w_ij                          # hard attention
      out_i = hex_ca_step(V_{j*} XOR states[i], mix_rule)

    Hard attention (argmax) is the simpler attention used by
    early sparse-attention papers; it makes the whole attention layer
    a deterministic function of the rule tables, which is what the GA
    needs to evolve a stable attention specialist.

    When ``trace`` is a list, records the Q/K/V/score/mix grids for the
    *last* token position (the one the next-token prediction depends on)
    as ``{'name': ..., 'grid': ndarray}`` dicts. The trace is a side
    channel; the returned states are unchanged.

    Returns: list of T attended states, same shape as inputs."""
    T = len(states)
    if T == 0:
        return []
    Qs = [ca_qkv_project(s, q_rule) for s in states]
    Ks = [ca_qkv_project(s, k_rule) for s in states]
    Vs = [ca_qkv_project(s, v_rule) for s in states]
    out = []
    last_j_star = None
    last_score_grid = None
    for i in range(T):
        end = i + 1 if causal else T
        scores = [ca_attention_score(Qs[i], Ks[j], score_rule)
                   for j in range(end)]
        # Hard attention: pick the j with the highest score.  Ties broken
        # by the smallest index (most distant past) so the choice is
        # deterministic and the sequence walk reproducible.
        j_star = int(np.argmax(scores))
        attended = (Vs[j_star] ^ states[i].astype(np.uint8)) & 3
        out.append(hex_ca_step(attended, mix_rule))
        last_j_star = j_star
        # Capture the score grid for the chosen j (the one the readout
        # actually used). ca_attention_score returns a scalar in the
        # current primitive set; we replay it as a state-shaped grid
        # so the live panel has something visual to render.
        if trace is not None and i == T - 1:
            last_score_grid = hex_ca_step(
                (Qs[i] ^ Ks[j_star]) & 3, score_rule)
    if trace is not None:
        trace.append({'name': 'q',      'grid': Qs[-1]})
        trace.append({'name': 'k',      'grid': Ks[-1]})
        trace.append({'name': 'v',      'grid': Vs[-1]})
        trace.append({'name': 'score',  'grid': last_score_grid,
                       'note': f'j*={last_j_star}/{T - 1}'})
        trace.append({'name': 'mix',    'grid': out[-1]})
    return out


def ca_residual_merge(state_a: np.ndarray, state_b: np.ndarray,
                       merge_rule: np.ndarray) -> np.ndarray:
    """CA-merged residual.  Stacks (a, b) into a (2H, W) grid, runs one
    tick of `merge_rule`, returns the top half.  This makes the residual
    a *neighbourhood-aware* merge — the rule sees both inputs at every
    cell when picking the output — instead of a cell-wise XOR.

    XOR-residual is still available as `ca_residual(a, b, mode='xor')`
    for the GA to compare against; this is the rule-driven alternative
    that the broader rule-evolution machinery can also tune."""
    if state_a.shape != state_b.shape:
        raise ValueError(
            f'shape mismatch: {state_a.shape} vs {state_b.shape}')
    stacked = np.vstack([state_a.astype(np.uint8) & 3,
                          state_b.astype(np.uint8) & 3])
    mixed = hex_ca_step(stacked, merge_rule)
    H, _ = state_a.shape
    return mixed[:H]


def ca_layer_norm_iterative(state: np.ndarray,
                              norm_rule: Optional[np.ndarray] = None,
                              k_ticks: int = 4) -> np.ndarray:
    """CA-iterated layer norm.  Run `k_ticks` of `norm_rule` (defaults
    to `default_norm_rule`, which encourages cells to differ from their
    neighbours) on `state` and return the result.

    Unlike `ca_layer_norm` (which forces an exact uniform histogram via
    a sort+permute), this is a *pure CA* operation — same kind of step
    every other primitive uses.  After enough ticks the histogram is
    near-uniform; the rule is what determines how fast and how stably
    that balance is reached.  This is the version the GA can tune by
    evolving the rule."""
    if state.dtype != np.uint8:
        state = state.astype(np.uint8) & 3
    rule = norm_rule if norm_rule is not None else default_norm_rule()
    work = state.copy()
    for _ in range(k_ticks):
        work = hex_ca_step(work, rule)
    return work


def ca_output_head_iterative(state: np.ndarray, *,
                               output_rule: Optional[np.ndarray] = None,
                               vocab_size: int = 256,
                               k_ticks: int = 2) -> np.ndarray:
    """CA-iterated output head.  Run `k_ticks` of `output_rule` to let
    the cells diffuse spatially, then count occurrences of each
    (position mod vocab_size, colour) pair.  The accumulated counts are
    the logits.

    Why this is "CA-only": the diffusion step IS the projection from
    hidden state to vocab, with the rule playing the role of the
    unembedding matrix.  The final histogram readout is just a count —
    no matrix multiply, no float arithmetic until the cells are
    counted."""
    if state.dtype != np.uint8:
        state = state.astype(np.uint8) & 3
    rule = output_rule if output_rule is not None else default_output_rule()
    work = state.copy()
    for _ in range(k_ticks):
        work = hex_ca_step(work, rule)
    flat = work.flatten().astype(np.uint16)
    positions = np.arange(flat.size, dtype=np.uint16)
    indices = (positions * 4 + flat) % vocab_size
    logits = np.zeros(vocab_size, dtype=np.float64)
    np.add.at(logits, indices, 1.0)
    return logits


def ca_softmax_sample_iterative(logits: np.ndarray, *,
                                  temperature: float = 1.0,
                                  noise_rule: Optional[np.ndarray] = None,
                                  ca_seed: int = 42,
                                  ca_ticks: int = 8,
                                  grid_side: int = 16,
                                  ) -> Tuple[int, np.ndarray]:
    """CA-noised softmax that uses an *evolvable* CA rule for the noise
    source rather than the default-random rule baked into
    `ca_softmax_sample`.  Otherwise identical Gumbel-max trick.

    This is the version the GA tunes when sampling temperature
    behaviour matters — e.g. the noise distribution is the only
    knob between greedy decoding and high-entropy exploration."""
    n = logits.shape[0]
    if n == 0:
        raise ValueError('logits is empty')
    rule = noise_rule if noise_rule is not None else random_rule_table(ca_seed)
    state = (lcg_bytes(ca_seed ^ 0xA5A5A5A5, grid_side * grid_side) & 3
              ).reshape(grid_side, grid_side)
    for _ in range(ca_ticks):
        state = hex_ca_step(state, rule)
    noise = gumbel_from_bytes(state.flatten(), n)
    if temperature <= 0:
        return int(np.argmax(logits)), noise
    return int(np.argmax(logits.astype(np.float64) / temperature + noise)), noise



# ─── ca_bank_step — composition: CA-as-index over an array of CAs ───
#
# At each cell, the selector_rule's output (a value 0..3) picks which
# of K=4 bank rules to apply for that cell's next-state.  Per-cell
# branching — the CA gets a router built in.
#
# Both the selector and the bank rules use the same 7-cell hex
# neighbourhood, so the look-up keys are pre-computed once and reused
# K+1 times.  Cost is ~(K+1)× a regular hex_ca_step.
#
# Use cases: a routed MLP where four "experts" specialise on different
# input distributions; a switching attention where the selector_rule
# decides whether to amplify or dampen a region; a meta-rule whose
# evolution-target is the *combination* of the 5 rules.

def ca_bank_step(state: np.ndarray,
                   selector_rule: np.ndarray,
                   bank_rules,                       # list/tuple of 4 rules
                   ) -> np.ndarray:
    """One tick of a routed CA: selector_rule decides per cell, then
    bank_rules[selector] decides the new colour.  Result shape same
    as input."""
    if state.dtype != np.uint8:
        state = state.astype(np.uint8)
    if len(bank_rules) != 4:
        raise ValueError(f'bank_rules must have 4 entries; got {len(bank_rules)}')
    # Compute selector and each bank in parallel (shape: H × W per).
    selector = hex_ca_step(state, selector_rule)
    bank_outs = np.stack(
        [hex_ca_step(state, r) for r in bank_rules], axis=0)
    # Per-cell pick: out[y,x] = bank_outs[selector[y,x], y, x]
    H, W = state.shape
    ys = np.arange(H)[:, None]
    xs = np.arange(W)[None, :]
    return bank_outs[selector, ys, xs].astype(np.uint8)
