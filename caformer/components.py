"""caformer/components.py — the 8 LLM layers, surveyed as CA networks.

Each Component is a *workshop slot* in the caformer app.  The fields
capture both the real-LLM behaviour (so the design stays grounded in
what an actual transformer does) and the CA-based replacement we're
building toward.  Status:

  sketch   — design notes only, no code yet
  partial  — some code exists somewhere in Velour, not yet wired
  working  — runnable here in the workshop
  optimised — running fast enough to compose into the full stack

Architectural target: a nanoGPT-shaped stack of **3 transformer blocks**,
each block built from CA networks rather than tensor ops.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Component:
    slug:        str
    name:        str
    one_liner:   str
    real_llm:    str          # what this layer does in a real transformer
    ca_design:   str          # how we'd build it from CAs
    grid:        str          # the grid / network structure proposal
    inputs:      str          # what flows in
    outputs:     str          # what flows out
    status:      str          # sketch | partial | working | optimised
    related:     List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)


# Order matches data flow through a forward pass.
COMPONENTS: List[Component] = [

    Component(
        slug='embedding',
        name='Embedding',
        one_liner='Token IDs and positions → continuous vectors a network can mix.',
        real_llm=(
            "GPT keeps two learned tables: token-embedding (vocab × d_model) "
            "and positional-embedding (max_seq_len × d_model).  Forward pass: "
            "embed[token_id] + pos_embed[position] for every token in the "
            "input sequence.  d_model is typically 768–1536 for nanoGPT-class."
        ),
        ca_design=(
            "Each token ID seeds one component-CA; the CA is iterated for "
            "k ticks, and its 16×16×2-bit state is read as a 64-byte = 512-"
            "dimensional vector (or two components → 1024-dim).  Determinism "
            "of the CA gives us a deterministic, learnable-via-rule "
            "embedding without floats.  Position embedding works the same "
            "way but seeded from the position index in a separate domain "
            "so token-embed and pos-embed don't collide.  Final embedding "
            "= XOR or majority-blend of the two grid states."
        ),
        grid='1 component-CA per token + 1 per position, both read after k ticks.',
        inputs='token_id (int), position (int)',
        outputs='1024-bit (or larger) bit vector treated as the activation',
        status='working',
        related=[
            'caformer.primitives.ca_embedding (token → CA state via LCG seed + k ticks)',
            'caformer.primitives.ca_positional_embedding (separate domain so token+pos do not collide)',
            'caformer.transformer.ca_embed_sequence (XOR-blend token+pos for the whole sequence)',
            'spoeqi.keystream.tap',
        ],
        open_questions=[
            'Is XOR the right blend?  Concat + reduce CA?',
            'How many ticks k gives a useful embedding without oversaturating?',
            'Does the same vocab-CA generalise across pacts, or is it pact-local?',
        ],
    ),

    Component(
        slug='layer_norm',
        name='Layer normalization',
        one_liner='Re-centre + rescale activations so downstream ops stay in range.',
        real_llm=(
            "For each token vector x: y = γ ⊙ (x − μ)/σ + β, where μ, σ "
            "are the per-token mean and std-dev across d_model, and γ, β "
            "are learned per-channel parameters.  Stabilises gradients."
        ),
        ca_design=(
            "Treat each component-CA's state as a histogram over its 4 "
            "colours.  'Normalise' = re-pack the state so the colour "
            "histogram matches a target distribution (the γ/β analogue).  "
            "Implementable as a fixed deterministic permutation of cells "
            "keyed by the rank of their colour at this generation, then "
            "a scalar shift by the median rank."
        ),
        grid='1 component-CA in, 1 component-CA out (same shape, re-balanced).',
        inputs='component-CA state (16×16×2-bit grid)',
        outputs='component-CA state with target colour histogram',
        status='working',
        related=[
            'caformer.primitives.ca_layer_norm (idealised — exact uniform)',
            'caformer.primitives.ca_layer_norm_iterative (CA-only — k ticks of norm_rule)',
            'caformer.primitives.default_norm_rule (least-represented-colour rule)',
            'spoeqi.analysis (color_histogram)',
        ],
        open_questions=[
            'Does re-binning preserve the spatial structure enough?  Or do '
            'we want a CA-rule-based normaliser that runs k=1 ticks?',
            'Are γ, β baked into the CA rule, or applied as a post-step shift?',
        ],
    ),

    Component(
        slug='self_attention',
        name='Self-attention',
        one_liner='Each token gathers info from every other token, weighted by relevance.',
        real_llm=(
            "Q = X W_q;  K = X W_k;  V = X W_v;  "
            "Attn = softmax(Q K^T / √d_k);  Out = Attn V.  "
            "GPT splits the d_model dimension into n_head=12 groups so each "
            "head learns a different attention pattern in parallel."
        ),
        ca_design=(
            "For a sequence of T tokens we have T component-CAs (one per "
            "token, from embedding).  The attention operation is:\n\n"
            "  1. Each pair (i, j) gets an attention weight derived from "
            "applying a *fixed CA rule* to the concatenated states of "
            "CA_i and CA_j.  The output's colour-0 fraction = attention "
            "weight (softmax-equivalent across j by normalising the row).\n"
            "  2. The new state of token i = weighted majority-vote of "
            "the V-CAs of all tokens, weighted by attention.\n\n"
            "Multi-head = 12 different fixed rules running in parallel; "
            "concat the resulting CAs across components for the output."
        ),
        grid='T × T pairwise CA evaluations per head; 12 heads in parallel.',
        inputs='T component-CAs (one per token)',
        outputs='T component-CAs (mixed across the sequence)',
        status='working',
        related=[
            'caformer.primitives.ca_self_attention (full Q/K/V, all CA)',
            'caformer.primitives.ca_qkv_project (Q/K/V each = one CA tick)',
            'caformer.primitives.ca_attention_score (pair-wise CA score)',
            'caformer.reductive.ca_attention_min (XOR-with-neighbour reductive form)',
            'spoeqi.textmask.attention (matrix-producing leaf op)',
            'spoeqi.textmask.derive_chain_gene + chain GA — heads as gene-coded specialists',
            'spoeqi.llm_lora — perturbing real attention weights with CA bytes',
        ],
        open_questions=[
            'How is "softmax across j" represented when colours are discrete?  '
            'Quantile-rank-then-keep-top-k?',
            'Where do Q, K, V come from?  Three different fixed CA rules '
            'applied to the same input grid?',
            'Causal mask: enforce i ≥ j by zeroing future-pair CAs before the vote.',
        ],
    ),

    Component(
        slug='projection',
        name='Projection (Q/K/V/Out)',
        one_liner='Linear maps that reshape activations into roles for attention.',
        real_llm=(
            "Four learned linears per attention block: W_q, W_k, W_v "
            "(d_model → d_head), and W_o (d_head·n_head → d_model).  "
            "Determines what each head 'asks for' and how outputs combine."
        ),
        ca_design=(
            "A 'projection' = a fixed CA rule applied for one tick.  The "
            "rule IS the learned weight matrix.  Different projections = "
            "different rules.  Q-rule, K-rule, V-rule, Out-rule are each "
            "16,384-byte tables; the 'learning' is choosing them (we'll "
            "evolve via the existing GA infrastructure).\n\n"
            "Out-projection blends multiple head outputs into one CA "
            "via stacked majority votes — equivalent to W_o."
        ),
        grid='4 fixed rules (Q, K, V, Out) per attention block.',
        inputs='1 CA state',
        outputs='1 CA state',
        status='working',
        related=[
            'caformer.primitives.ca_qkv_project (the projection IS one CA tick)',
            'caformer.primitives.ca_residual_merge (per-block merge rule)',
            'spoeqi.envelope (rule-as-key)',
            'helix.hexhunt (evolve rules)',
        ],
        open_questions=[
            'Are Q/K/V/Out shared across all heads or per-head?  GPT shares '
            'the input to all heads but has per-head projection weights.',
        ],
    ),

    Component(
        slug='mlp',
        name='MLP (feed-forward)',
        one_liner='Per-token nonlinearity — the "memory store" of the transformer.',
        real_llm=(
            "Per-token: y = W_2 · GELU(W_1 · x + b_1) + b_2, with the "
            "hidden dim 4× larger than d_model.  This is where most of "
            "the model's parameters live and where 'facts' are stored."
        ),
        ca_design=(
            "Run the token's CA forward by k ticks (where the CA rule "
            "plays the role of W_1, the rule's nonlinear lookup plays "
            "GELU, and the rest of the k ticks act as W_2).  Hidden dim "
            "expansion = use a CA with a larger grid (32×32 instead of "
            "16×16) for the inner layer, then reduce by majority-pooling "
            "back to 16×16 for the output."
        ),
        grid='Per-token CA stepped k ticks; inner stage on a wider grid.',
        inputs='1 CA state per token',
        outputs='1 CA state per token (same outer shape)',
        status='working',
        related=[
            'caformer.primitives.ca_mlp (single CA, k ticks, optional 2× tile→majority-pool for the 4× FFN-dim analogue)',
            'caformer.ga.MLP_FITNESS (GA target: high cell-change without colour collapse)',
            'spoeqi.textmask token-mode mappings (per-token transforms)',
        ],
        open_questions=[
            'How many ticks k = "one MLP layer"?',
            'Inner expansion via larger grid vs via more CA rule ticks?',
            'GELU equivalent: the rule-table lookup is already non-linear, '
            'but is it the *right* non-linearity?',
        ],
    ),

    Component(
        slug='transformer',
        name='Transformer block',
        one_liner='One stack: norm → attention → residual → norm → MLP → residual.',
        real_llm=(
            "  x1 = LayerNorm(x)\n"
            "  x2 = x + SelfAttention(x1)        # residual #1\n"
            "  x3 = LayerNorm(x2)\n"
            "  out = x2 + MLP(x3)                 # residual #2\n\n"
            "nanoGPT stacks **3** of these.  Bigger models stack 12 / 24 / 96."
        ),
        ca_design=(
            "A transformer block is a *grid* of CAs wired into the topology "
            "above.  Concretely:\n\n"
            "  • T input CAs (one per token in the sequence)\n"
            "  • a layer-norm pass over each\n"
            "  • a T×T attention sub-grid producing T mixed CAs\n"
            "  • residual: per-token, blend (input CA, attention output CA) "
            "    via XOR or majority-vote\n"
            "  • another layer-norm\n"
            "  • per-token MLP — independent CAs running k ticks each\n"
            "  • residual #2\n\n"
            "**Stack of 3** = three of these grids end-to-end, output of "
            "block N feeds block N+1's input CAs.  Each block has its own "
            "rule set (Q/K/V/Out + MLP rule), all evolved jointly."
        ),
        grid='T tokens × (12 heads × T pair-CAs + T MLP CAs); ×3 in nanoGPT.',
        inputs='T CAs',
        outputs='T CAs (same count, transformed)',
        status='working',
        related=[
            'caformer.transformer.ca_transformer_block (with reductive attention)',
            'caformer.transformer.ca_transformer_block_qkv (full Q/K/V, every step a CA)',
            'caformer.transformer.ca_forward_qkv (end-to-end fully-CA forward pass)',
            'spoeqi.textmask.apply_chain (sequential CA composition)',
            'spoeqi.chain_evolution (evolve gene-coded chains)',
        ],
        open_questions=[
            'How do residuals combine two CAs?  XOR is information-preserving '
            'but commutative; majority-vote loses information but smoothes.',
            'Are the 3 blocks identical (weight-tied) or each independently '
            'evolved?  GPT does independent.',
        ],
    ),

    Component(
        slug='softmax',
        name='Softmax',
        one_liner='Logits → probability distribution that sums to 1.',
        real_llm=(
            "softmax(z)_i = exp(z_i) / Σ_j exp(z_j).  Used inside attention "
            "(over the sequence axis) and at the output (over vocabulary)."
        ),
        ca_design=(
            "For a CA state representing logits across V vocab entries:\n\n"
            "  • Map each cell to a vocab index by hash-rank of its colour\n"
            "  • Count occurrences per vocab → 'frequency' = unnormalised\n"
            "  • Output: rank-sorted frequencies, then top-k for sampling\n\n"
            "This *is* an argmax-y / temperature-zero softmax.  For "
            "sampling-temperature > 0 we add CA-derived noise to the "
            "frequencies before ranking."
        ),
        grid='1 CA → ranked vocab distribution (no further CA structure).',
        inputs='1 CA state interpreted as logits',
        outputs='probability distribution over vocab (or sampled token)',
        status='working',
        related=[
            'caformer.primitives.ca_softmax_sample (Gumbel-max trick, noise sourced from CA byte stream)',
            'caformer.primitives.ca_softmax_sample_iterative (evolvable noise rule)',
            'caformer.reductive.ca_softmax_sample_min (irreducible argmax fallback)',
            'spoeqi.envelope (deterministic randomness for temperature)',
        ],
        open_questions=[
            'Does the rank-based softmax preserve enough signal, or do '
            'we want a continuous-valued surrogate from cell counts?',
            'Sampling temperature = how much CA noise we mix in; calibrate.',
        ],
    ),

    Component(
        slug='output',
        name='Output head',
        one_liner='Final hidden state → vocab logits → next-token sample.',
        real_llm=(
            "y = LayerNorm(x_final);  logits = y · W_out  (W_out shares "
            "weights with the input embedding in many models — 'tied "
            "embeddings').  Softmax + argmax / temperature-sample for the "
            "next token.  Repeat autoregressively."
        ),
        ca_design=(
            "Last layer-norm + a final 'unembed' CA rule applied to each "
            "token's CA → vocab-logits CA (one per token).  Pull the "
            "*last* token's logit CA, run softmax (above), sample.  Append "
            "the sampled token to the sequence and re-run the whole stack.\n\n"
            "Tied embeddings = the unembed rule is the *inverse* of the "
            "embed rule (or just the same rule run in reverse, if the rule "
            "is reversible).  Reversible CA rules are well-studied — pick "
            "from the existing class-2 / margolus-neighbourhood library."
        ),
        grid='1 final CA per token; project last to vocab via fixed unembed rule.',
        inputs='T CAs (final block output)',
        outputs='1 sampled token id per autoregressive step',
        status='working',
        related=[
            'caformer.primitives.ca_output_head_iterative (k ticks of output_rule + cell-count logits)',
            'caformer.primitives.default_output_rule',
            'caformer.transformer.ca_forward_qkv (end-to-end fully-CA path)',
            'spoeqi.envelope sampling',
            'helix.hexhunt for evolving the unembed rule',
        ],
        open_questions=[
            'Are tied embeddings worth the constraint?  GPT-2 ties; we get '
            'half the parameters but force inverse-rule pairing.',
            'How long can autoregression run before we need a fresh seed?',
        ],
    ),
]


def get(slug: str) -> Component | None:
    for c in COMPONENTS:
        if c.slug == slug:
            return c
    return None


# ── C-source snippets shown alongside each Component in the UI ────────
#
# These are the parts of the emit_tinyformer.py output that implement
# each component.  Kept tight and self-contained — when the user
# inspects a component on /caformer/component/<slug>/, the template
# renders this snippet so they can see what made it into the 24-58 KB
# standalone binary.  Compare against caformer/management/commands/
# emit_tinyformer.py for the full file.

_C_PRELUDE = '''/* Hex CA step — shared by every component below.
 * Pointy-top hex, K=4 cells, 7-neighborhood key.  The rule LUT is a
 * 2-bit-packed 16,384-entry table baked in at compile time.  */
static inline uint8_t lut_lookup(const uint8_t *lut, uint16_t idx) {
    uint8_t b = lut[idx >> 2];
    return (b >> ((3u - (idx & 3u)) * 2u)) & 3u;
}
static void hex_step(const uint8_t *in, uint8_t *out,
                       int H, int W, const uint8_t *rule_lut) {
    for (int y = 0; y < H; y++) {
        int even = ((y & 1) == 0);
        int yu = (y - 1 + H) % H, yd = (y + 1) % H;
        for (int x = 0; x < W; x++) {
            int xl = (x - 1 + W) % W, xr = (x + 1) % W;
            uint8_t self = in[y*W + x];
            uint8_t nw = even ? in[yu*W+xl] : in[yu*W+x ];
            uint8_t ne = even ? in[yu*W+x ] : in[yu*W+xr];
            uint8_t sw = even ? in[yd*W+xl] : in[yd*W+x ];
            uint8_t se = even ? in[yd*W+x ] : in[yd*W+xr];
            uint8_t nl = in[y *W+xl], nr = in[y *W+xr];
            uint16_t key = ((uint16_t)self<<12) | ((uint16_t)nw<<10)
                         | ((uint16_t)ne<<8)   | ((uint16_t)nr<<6)
                         | ((uint16_t)se<<4)   | ((uint16_t)sw<<2)
                         | (uint16_t)nl;
            out[y*W + x] = lut_lookup(rule_lut, key);
        }
    }
}'''


_C_SNIPPETS = {
    'embedding': '''/* embedding — token id → 16x16 K=4 grid.
 * LCG-seeds the grid from (token_id, position), then runs EMBED_TICKS
 * applications of the embed rule LUT.  Deterministic; no floats. */
static void embed_token(int token_id, int pos, uint8_t *grid) {
    uint32_t s = (uint32_t)token_id * 1103515245u
               + (uint32_t)pos      * 12345u + 0xC0FFEEu;
    for (int i = 0; i < GRID_AREA; i++) {
        s = s * 1664525u + 1013904223u;
        grid[i] = (s >> 16) & 3u;
    }
    static uint8_t scratch[GRID_AREA];
    for (int t = 0; t < EMBED_TICKS; t++) {
        hex_step(grid, scratch, GRID_SIDE, GRID_SIDE, RULE_EMBED);
        memcpy(grid, scratch, GRID_AREA);
    }
}''',

    'layer_norm': '''/* layer_norm — iterative CA-based normalisation.
 * Real LN computes a per-token mean and variance and rescales.  We
 * approximate with NORM_TICKS applications of the norm_rule LUT,
 * which the GA trains to redistribute the colour histogram toward
 * a target.  No mean, no variance, no divisions — just CA dynamics. */
static void layer_norm(uint8_t *grid) {
    static uint8_t scratch[GRID_AREA];
    for (int t = 0; t < NORM_TICKS; t++) {
        hex_step(grid, scratch, GRID_SIDE, GRID_SIDE, RULE_NORM);
        memcpy(grid, scratch, GRID_AREA);
    }
}''',

    'projection': '''/* projection — the Q linear in attention (V/K analogous).
 * Real Q = Wq · x is a (d_model × d_model) matmul.  Here every "matmul"
 * is replaced by PROJ_TICKS ticks of a rule LUT that the GA evolves to
 * approximate the desired linear behaviour through CA dynamics. */
static void projection_q(const uint8_t *in, uint8_t *out) {
    memcpy(out, in, GRID_AREA);
    static uint8_t scratch[GRID_AREA];
    for (int t = 0; t < PROJ_TICKS; t++) {
        hex_step(out, scratch, GRID_SIDE, GRID_SIDE, RULE_Q);
        memcpy(out, scratch, GRID_AREA);
    }
}
/* Same shape for projection_k (RULE_K) and projection_v (RULE_V). */''',

    'self_attention': '''/* self_attention — softmax(Q K^T) V via CA composition.
 * Replaces the three matmuls + softmax + matmul with: project to
 * Q/K/V grids, "score" them with RULE_SCORE (a CA proxy for dot-product
 * + softmax), then "mix" with RULE_MIX (proxy for the V-weighting). */
static void self_attention(uint8_t *grid) {
    static uint8_t q[GRID_AREA], k[GRID_AREA], v[GRID_AREA], scratch[GRID_AREA];
    projection_q(grid, q);
    projection_k(grid, k);
    projection_v(grid, v);
    /* Score: hex-step q against k via RULE_SCORE. */
    for (int t = 0; t < SCORE_TICKS; t++) {
        hex_step(q, scratch, GRID_SIDE, GRID_SIDE, RULE_SCORE);
        memcpy(q, scratch, GRID_AREA);
    }
    /* Mix: blend the scored grid into v via RULE_MIX. */
    for (int i = 0; i < GRID_AREA; i++) grid[i] = (q[i] ^ v[i]) & 3;
    for (int t = 0; t < MIX_TICKS; t++) {
        hex_step(grid, scratch, GRID_SIDE, GRID_SIDE, RULE_MIX);
        memcpy(grid, scratch, GRID_AREA);
    }
}''',

    'mlp': '''/* mlp — the feed-forward block.
 * Real MLP = Linear → GELU → Linear.  We approximate with MLP_TICKS
 * iterations of RULE_MLP — a single CA rule the GA trains to act like
 * a nonlinear projection.  No weights, no activation function, just
 * the rule table doing the same job through hex CA dynamics. */
static void mlp_block(uint8_t *grid) {
    static uint8_t scratch[GRID_AREA];
    for (int t = 0; t < MLP_TICKS; t++) {
        hex_step(grid, scratch, GRID_SIDE, GRID_SIDE, RULE_MLP);
        memcpy(grid, scratch, GRID_AREA);
    }
}''',

    'transformer': '''/* transformer block — full Pre-LN block, CA-style.
 * Stitches the components together in the order Pre-LN GPT uses:
 *   norm → attn → residual-merge → norm → mlp → residual-merge */
static void transformer_block(uint8_t *grid) {
    static uint8_t residual[GRID_AREA], scratch[GRID_AREA];
    /* Pre-LN, attention path */
    memcpy(residual, grid, GRID_AREA);
    layer_norm(grid);
    self_attention(grid);
    /* Residual merge: XOR blend via RULE_MERGE. */
    for (int i = 0; i < GRID_AREA; i++) grid[i] ^= residual[i];
    for (int t = 0; t < MERGE_TICKS; t++) {
        hex_step(grid, scratch, GRID_SIDE, GRID_SIDE, RULE_MERGE);
        memcpy(grid, scratch, GRID_AREA);
    }
    /* Pre-LN, MLP path */
    memcpy(residual, grid, GRID_AREA);
    layer_norm(grid);
    mlp_block(grid);
    for (int i = 0; i < GRID_AREA; i++) grid[i] ^= residual[i];
    for (int t = 0; t < MERGE_TICKS; t++) {
        hex_step(grid, scratch, GRID_SIDE, GRID_SIDE, RULE_MERGE);
        memcpy(grid, scratch, GRID_AREA);
    }
}''',

    'softmax': '''/* softmax (in sampler) — temperature-softmax over logits.
 * Real softmax = exp(x_i / T) / sum_j exp(x_j / T).  We compute it
 * literally in C; the "CA" part is upstream in output_head where the
 * logits come from cell counts in the post-output_rule grid. */
static int sample_byte(const double *logits, double temperature,
                         uint32_t *rng_state, const unsigned char *allow) {
    double maxv = -1e300;
    for (int v = 0; v < VOCAB; v++)
        if (!allow || allow[v]) if (logits[v] > maxv) maxv = logits[v];
    double sum = 0.0;
    static double probs[VOCAB];
    for (int v = 0; v < VOCAB; v++) {
        if (allow && !allow[v]) { probs[v] = 0.0; continue; }
        probs[v] = exp((logits[v] - maxv) / temperature);
        sum += probs[v];
    }
    uint32_t s = *rng_state;
    s ^= s << 13; s ^= s >> 17; s ^= s << 5;
    *rng_state = s;
    double u = ((double)s / (double)0xFFFFFFFFu) * sum;
    double acc = 0.0;
    for (int v = 0; v < VOCAB; v++) {
        acc += probs[v];
        if (acc >= u) return v;
    }
    return VOCAB - 1;
}''',

    'output': '''/* output head — grid → vocab logits.
 * Real LM output head = Linear(d_model → vocab).  We run OUTPUT_TICKS
 * of RULE_OUTPUT to "spread" the final grid, then count cells per
 * colour.  The 4 counts become logits for 4 byte-buckets of size 64,
 * so byte v gets the count of bucket (v >> 6).  Cheap; coarse. */
static void output_head(uint8_t *grid, double *logits) {
    static uint8_t scratch[GRID_AREA];
    for (int t = 0; t < OUTPUT_TICKS; t++) {
        hex_step(grid, scratch, GRID_SIDE, GRID_SIDE, RULE_OUTPUT);
        memcpy(grid, scratch, GRID_AREA);
    }
    int counts[4] = {0, 0, 0, 0};
    for (int i = 0; i < GRID_AREA; i++) counts[grid[i]]++;
    for (int v = 0; v < VOCAB; v++)
        logits[v] = (double)counts[v >> 6];
}''',
}


def c_source_for_component(slug: str) -> str | None:
    """Return the C snippet that implements ``slug`` in the standalone
    tinyformer binary, or None if no snippet is defined.  Prepends the
    shared hex_step prelude so the snippet is self-contained-ish.

    Used by /caformer/component/<slug>/ to show the user exactly what
    distilled C this component compiled into.  For the full file, see
    caformer/management/commands/emit_tinyformer.py."""
    snip = _C_SNIPPETS.get(slug)
    if snip is None:
        return None
    return _C_PRELUDE + '\n\n' + snip


# ──────────────────────────────────────────────────────────────────
# Compositions — the recursive abstraction ladder.
#
# Note: these are *our compositional scaffolds*, not literal copies of
# OpenAI's GPT-2/3 internals.  Real GPT-3 is just deeper-and-wider, not
# 4-in-parallel.  The user's framing — wrap N of the previous scale at
# every level — is what we actually want to evolve, regardless of how
# the OpenAI lineage happens to be shaped.  The numbers are nominal
# anchors; the pattern is what matters.

@dataclass(frozen=True)
class Composition:
    slug:         str
    name:         str
    abstraction:  int      # 0 = leaf, 1 = block, 2 = nano, 3 = gpt2, 4 = gpt3, 5 = 3.5
    structure:    str      # nested-list / ascii sketch of how this is built
    ca_count:     str      # rough CA-count budget so we know when it's infeasible
    notes:        str
    status:       str
    contains:     List[str] = field(default_factory=list)


COMPOSITIONS: List[Composition] = [

    Composition(
        slug='transformer_block',
        name='Transformer block',
        abstraction=1,
        structure=(
            "Sequence(\n"
            "  layer_norm,\n"
            "  Parallel([self_attention × 12 heads]) → projection_out,\n"
            "  Residual(input),\n"
            "  layer_norm,\n"
            "  mlp,\n"
            "  Residual(input),\n"
            ")"
        ),
        ca_count='~T × 12 attention CAs + T MLP CAs + 2 norms ≈ O(T·100)',
        notes=(
            "The leaf-level composition every higher scale wraps.  Inputs T "
            "token-CAs, outputs T transformed token-CAs.  Every weight in "
            "the real transformer = a CA rule (16,384 bytes) we'll evolve. "
            "Runnable as caformer.transformer.ca_transformer_block_qkv "
            "with seven rule tables per block (Q/K/V/score/mix/merge/MLP)."
        ),
        status='working',
        contains=['layer_norm', 'self_attention', 'projection', 'mlp'],
    ),

    Composition(
        slug='nano_gpt',
        name='nanoGPT-shape',
        abstraction=2,
        structure=(
            "Sequence(\n"
            "  embedding,\n"
            "  transformer_block × 3,\n"
            "  layer_norm,\n"
            "  output,\n"
            ")"
        ),
        ca_count='~3 × O(T·100) + embed + output ≈ O(T·300) CAs',
        notes=(
            "First scale that can autoregressively complete a sequence.  "
            "Three blocks in series — output of block N feeds block N+1.  "
            "Runnable as caformer.transformer.nano_gpt (single forward pass) "
            "or caformer.transformer.ca_generate_qkv (autoregressive "
            "generation).  Both wrap ca_forward_qkv with n_blocks=3.  "
            "If we can evolve this and get coherent text, the recursive "
            "scale-up to GPT-2/3-shape is just more of the same."
        ),
        status='working',
        contains=['embedding', 'transformer_block', 'layer_norm', 'output'],
    ),

    Composition(
        slug='chat_gpt2_shape',
        name='ChatGPT-2-shape (4 nanoGPTs in series)',
        abstraction=3,
        structure=(
            "Sequence(\n"
            "  nano_gpt × 4,   # output of each feeds the next\n"
            ")"
        ),
        ca_count='~4 × O(T·300) ≈ O(T·1200) CAs',
        notes=(
            "Stack-of-stacks.  Each nanoGPT is itself a 3-block tower; this "
            "puts four of them in series, so the model has 12 transformer-"
            "block-equivalents of effective depth.  Runnable as "
            "caformer.transformer.chat_gpt2_shape (single forward pass) "
            "— a thin wrapper that pins ca_forward_qkv to n_blocks=12.  "
            "Cost: per-step CA evaluation budget grows linearly with depth."
        ),
        status='working',
        contains=['nano_gpt'],
    ),

    Composition(
        slug='chat_gpt3_shape',
        name='ChatGPT-3-shape (4 ChatGPT-2s in parallel for 4 attentions)',
        abstraction=4,
        structure=(
            "Sequence(\n"
            "  Parallel(chat_gpt2_shape × 4),    # 4 independent attention paths\n"
            "  blend_outputs,                     # vote / concat / softmax\n"
            ")"
        ),
        ca_count='~4 × O(T·1200) ≈ O(T·4800) CAs per forward pass',
        notes=(
            "The fan-out scale.  Four independent ChatGPT-2-shape towers "
            "produce four candidate continuations; a final 'blend' CA "
            "(majority vote, attention-weighted average, or softmax over "
            "the four logit-CAs) picks the actual next token.  This is "
            "the macro-scale analogue of multi-head attention — at the "
            "tower level instead of the token level.  Runnable as "
            "caformer.transformer.chat_gpt3_shape with blend ∈ {sum, vote}.  "
            "The blend rule is itself something we'd evolve."
        ),
        status='working',
        contains=['chat_gpt2_shape'],
    ),

    Composition(
        slug='chat_gpt3_5_shape',
        name='ChatGPT-3.5-shape (further abstraction)',
        abstraction=5,
        structure=(
            "Sequence(\n"
            "  Parallel(chat_gpt3_shape × N),\n"
            "  router,                            # CA-derived MoE-style routing\n"
            "  Sequence(refinement_block × M),    # post-routing fine-tune layers\n"
            ")"
        ),
        ca_count='~top_k × 4 × O(T·1200) ≈ O(top_k · T·4800) CAs',
        notes=(
            "The 'keep abstracting' point.  At this scale we're no longer "
            "building one circuit — we're building a *meta-circuit* that "
            "routes between sub-circuits.  Realised as MoE: a cheap "
            "CA router (8×8 grid, 4 ticks per expert) scores all N "
            "experts; only the top_k actually run their full "
            "chat_gpt3_shape pass; outputs blended by softmax over the "
            "router scores.  Optional refinement_blocks=M layer runs on "
            "the blended logits.  Runnable as "
            "caformer.transformer.chat_gpt3_5_shape with knobs "
            "n_experts / top_k / refinement_blocks.  Recursion target: "
            "every level above 3.5 is another wrap of (Parallel + Router "
            "+ Refinement)."
        ),
        status='working',
        contains=['chat_gpt3_shape'],
    ),

    Composition(
        slug='default_mode_loop',
        name='Default-Mode loop (CA ↔ tinyLLM feedback, no external input)',
        abstraction=6,
        structure=(
            "Loop forever:\n"
            "  ca_state  = step(ca_state, k_ticks)\n"
            "  thought   = gene_chain(ca_state)         # CA → candidate text\n"
            "  refined   = tiny_llm.complete(thought)   # LLM polishes it\n"
            "  thoughts.append(refined)                  # rumination buffer\n"
            "  ca_state  = perturb(ca_state, hash(refined))\n"
            "  yield refined"
        ),
        ca_count='one model + a tinyLLM in a feedback loop — small, but runs forever.',
        notes=(
            "An analogue of the brain's Default Mode Network — what the "
            "system 'thinks about' when there's no external prompt.  No "
            "input enters the loop; the only signal is the CA substrate "
            "ticking forward and the LLM's interpretation of it.  Topics "
            "should drift, return, mutate, and surface fragments of the "
            "rumination buffer in unexpected combinations.\n\n"
            "Reductive variant in caformer/reductive.py: dmn_loop_min "
            "(no LLM, just CA → hash → CA) and self_reflection_min "
            "(the irreducible looping-back that Hofstadter / Gödel "
            "argue is where self-reference lives).\n\n"
            "Wraps any other model — DMN around nano_gpt is a curious "
            "miniature; DMN around chat_gpt3_shape is more interesting."
        ),
        status='working',
        contains=['nano_gpt', 'chat_gpt2_shape', 'chat_gpt3_shape',
                   'chat_gpt3_5_shape'],
    ),
]


def get_composition(slug: str) -> Composition | None:
    for c in COMPOSITIONS:
        if c.slug == slug:
            return c
    return None


# ──────────────────────────────────────────────────────────────────
# The recursive composition primitives — what the workshop is
# actually evolving against.
#
# A `Module` is either a leaf CA or a composition of Modules.  The
# evolution engine searches over (rules-at-each-leaf) and optionally
# over (topology) too.

@dataclass(frozen=True)
class ModuleSpec:
    kind:         str               # 'leaf' | 'sequence' | 'parallel' | 'residual'
    children:     List              # list[ModuleSpec]; empty for leaf
    rule:         str               # for 'leaf': name of CA rule (or 'evolved')
    note:         str = ''          # human description


def leaf(rule='evolved', note=''):
    return ModuleSpec(kind='leaf', children=[], rule=rule, note=note)


def sequence(*children, note=''):
    return ModuleSpec(kind='sequence', children=list(children), rule='', note=note)


def parallel(*children, note=''):
    return ModuleSpec(kind='parallel', children=list(children), rule='', note=note)


def residual(child, note=''):
    return ModuleSpec(kind='residual', children=[child], rule='', note=note)

