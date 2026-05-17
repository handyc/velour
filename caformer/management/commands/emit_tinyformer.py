"""manage.py emit_tinyformer <slug> [--out path] [--simple]

Emits a self-contained .c file that bakes in a TrainedModel's rule
tables and runs CA inference at the command line — no Python, no
deps. Compile with `cc -O2 -o tinyformer tinyformer.c -lm`.

Goal: a binary under 64 KB that generates text from CAs in memory
on the fly.  The 10 rule tables pack to 40,960 bytes at 2 bits/entry
(K=4 → 2 bits each; 4 entries per byte). The C code adds another
~3-4 KB stripped, leaving headroom under 64 KB.

Two modes:
  --simple  (default) Only embed + output, no transformer blocks.
            Smallest binary; demonstrates the CA-in-memory pipeline.
  --full    All 10 rules (embed/q/k/v/score/mix/merge/mlp/norm/output)
            via a faithful single-block forward pass. Larger binary.
"""
from __future__ import annotations
from pathlib import Path
import textwrap

from django.core.management.base import BaseCommand, CommandError

from caformer.models import TrainedModel


# ─── Pack 4 colour bytes (0..3) per byte ─────────────────────────
def _pack_2bit(rule: bytes) -> bytes:
    """16,384 K=4 entries → 4,096 bytes (2 bits per entry, big-end-first)."""
    if len(rule) != 16384:
        raise ValueError(f'rule must be 16,384 bytes; got {len(rule)}')
    out = bytearray(4096)
    for i in range(4096):
        b = 0
        for j in range(4):
            b = (b << 2) | (rule[i * 4 + j] & 3)
        out[i] = b
    return bytes(out)


def _c_array_decl(name: str, blob: bytes, per_line: int = 16) -> str:
    parts = [f'static const unsigned char {name}[{len(blob)}] = {{']
    for i in range(0, len(blob), per_line):
        chunk = blob[i:i + per_line]
        parts.append('  ' + ', '.join(f'0x{b:02x}' for b in chunk) + ',')
    parts.append('};')
    return '\n'.join(parts)


# ─── The C source template ───────────────────────────────────────

C_HEADER = r'''/* tinyformer — auto-generated from caformer.TrainedModel
 *   slug={slug}
 *   fitness={fitness:.4f}
 *   n_blocks={n_blocks}
 *
 * Build:  cc -Os -o tinyformer tinyformer.c -lm
 * Use:    echo "hello world" | ./tinyformer 24
 *         (number after argv[0] = max new tokens)
 *
 * Pure C, single file, no external data — the 10 K=4 hex CA rule
 * tables are baked in as 2-bit-packed static arrays (40,960 bytes).
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include <unistd.h>

#define GRID_SIDE 16
#define GRID_AREA (GRID_SIDE * GRID_SIDE)
#define VOCAB     256
#define LUT_SIZE  16384
#define EMBED_TICKS 6      /* token id → grid via this many CA ticks */
#define OUTPUT_TICKS 2

/* Unpack one entry from a 2-bit-packed LUT (4 entries per byte). */
static inline uint8_t lut_lookup(const uint8_t *lut, uint16_t idx) {{
    /* idx in [0, 16384). Byte = idx/4, shift = (3-idx%4)*2 */
    uint8_t b = lut[idx >> 2];
    uint8_t shift = (3u - (idx & 3u)) * 2u;
    return (b >> shift) & 3u;
}}

/* Hex CA step on (H, W) toroidal grid.  Uses parity-dependent
 * neighbours to match Python's hex_ca_step exactly. */
static void hex_step(const uint8_t *in, uint8_t *out,
                      int H, int W, const uint8_t *rule_lut) {{
    for (int y = 0; y < H; y++) {{
        int even = ((y & 1) == 0);
        int yu = (y - 1 + H) % H;
        int yd = (y + 1) % H;
        for (int x = 0; x < W; x++) {{
            int xl = (x - 1 + W) % W;
            int xr = (x + 1) % W;
            uint8_t self = in[y * W + x];
            /* Pointy-top hex: row-parity decides which two of the
             * four diagonals are actual neighbours. */
            uint8_t nw = even ? in[yu * W + xl] : in[yu * W + x];
            uint8_t ne = even ? in[yu * W + x ] : in[yu * W + xr];
            uint8_t sw = even ? in[yd * W + xl] : in[yd * W + x];
            uint8_t se = even ? in[yd * W + x ] : in[yd * W + xr];
            uint8_t nl = in[y  * W + xl];
            uint8_t nr = in[y  * W + xr];
            uint16_t key = (uint16_t)self << 12
                          | (uint16_t)nw   << 10
                          | (uint16_t)ne   << 8
                          | (uint16_t)nr   << 6
                          | (uint16_t)se   << 4
                          | (uint16_t)sw   << 2
                          | (uint16_t)nl;
            out[y * W + x] = lut_lookup(rule_lut, key);
        }}
    }}
}}

/* Embed a token id into a 16x16 grid: seed deterministically from
 * (token_id, position) via an LCG, then run EMBED_TICKS of embed_rule. */
static void embed_token(int token_id, int pos, uint8_t *grid) {{
    uint32_t state = (uint32_t)token_id * 1103515245u
                   + (uint32_t)pos      * 12345u
                   + 0xC0FFEEu;
    for (int i = 0; i < GRID_AREA; i++) {{
        state = state * 1664525u + 1013904223u;
        grid[i] = (state >> 16) & 3u;
    }}
    static uint8_t scratch[GRID_AREA];
    for (int t = 0; t < EMBED_TICKS; t++) {{
        hex_step(grid, scratch, GRID_SIDE, GRID_SIDE, RULE_EMBED);
        memcpy(grid, scratch, GRID_AREA);
    }}
}}

/* Output head: run output_rule for OUTPUT_TICKS, then count cells
 * of each colour. The 4 counts become the first 4 logits; the
 * remaining (VOCAB - 4) get the *minimum* count so a softmax
 * sampling at modest temperature picks from the top 4 buckets but
 * still has nonzero mass everywhere. */
static void output_head(uint8_t *grid, double *logits) {{
    static uint8_t scratch[GRID_AREA];
    for (int t = 0; t < OUTPUT_TICKS; t++) {{
        hex_step(grid, scratch, GRID_SIDE, GRID_SIDE, RULE_OUTPUT);
        memcpy(grid, scratch, GRID_AREA);
    }}
    int counts[4] = {{0, 0, 0, 0}};
    for (int i = 0; i < GRID_AREA; i++) counts[grid[i]]++;
    int min_c = counts[0];
    for (int c = 1; c < 4; c++) if (counts[c] < min_c) min_c = counts[c];
    for (int v = 0; v < VOCAB; v++) {{
        /* Map byte v → bucket (v / 64) for the first 4 buckets;
         * give every byte a chance proportional to its bucket count. */
        int bucket = v >> 6;          /* 0..3 */
        logits[v] = (double)counts[bucket];
    }}
}}

/* `allow[256]` is either NULL (no restriction) or a uint8 mask: 1 =
 * sample this byte is permitted, 0 = mask its logit to -inf. */
static int sample_byte(const double *logits, double temperature,
                         uint32_t *rng_state, const unsigned char *allow) {{
    double maxv = -1e300;
    for (int v = 0; v < VOCAB; v++) {{
        if (allow && !allow[v]) continue;
        if (logits[v] > maxv) maxv = logits[v];
    }}
    if (maxv == -1e300) maxv = 0.0;
    double sum = 0.0;
    static double probs[VOCAB];
    for (int v = 0; v < VOCAB; v++) {{
        if (allow && !allow[v]) {{ probs[v] = 0.0; continue; }}
        probs[v] = exp((logits[v] - maxv) / temperature);
        sum += probs[v];
    }}
    if (sum <= 0.0) return 0;
    uint32_t s = *rng_state;
    s ^= s << 13; s ^= s >> 17; s ^= s << 5;
    *rng_state = s;
    double u = ((double)s / (double)0xFFFFFFFFu) * sum;
    double acc = 0.0;
    for (int v = 0; v < VOCAB; v++) {{
        acc += probs[v];
        if (acc >= u) return v;
    }}
    return VOCAB - 1;
}}

/* ASCII printable + LF + CR = sampler-mask for -a. */
static const unsigned char ASCII_MASK[256] = {{
  /* 0..31 */   0,0,0,0,0,0,0,0,0,0, 1,0,0,1, 0,0, 0,0,0,0,0,0,0,0, 0,0,0,0,0,0,0,0,
  /* 32..63 */  1,1,1,1,1,1,1,1,1,1, 1,1,1,1, 1,1, 1,1,1,1,1,1,1,1, 1,1,1,1,1,1,1,1,
  /* 64..95 */  1,1,1,1,1,1,1,1,1,1, 1,1,1,1, 1,1, 1,1,1,1,1,1,1,1, 1,1,1,1,1,1,1,1,
  /* 96..127 */ 1,1,1,1,1,1,1,1,1,1, 1,1,1,1, 1,1, 1,1,1,1,1,1,1,1, 1,1,1,1,1,1,1,0,
  /* 128..255 */0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0, 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0, 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0, 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0, 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
}};

int main(int argc, char **argv) {{
    int max_new = 24;
    const unsigned char *allow = NULL;
    /* Parse: -a (ASCII only) / -c (corpus alphabet) / numeric tokens. */
    for (int ai = 1; ai < argc; ai++) {{
        if (argv[ai][0] == '-') {{
            for (const char *p = argv[ai] + 1; *p; p++) {{
                if      (*p == 'a') allow = ASCII_MASK;
                else if (*p == 'c') allow = CORPUS_ALPHABET;
            }}
        }} else {{
            int n = atoi(argv[ai]);
            if (n > 0) max_new = n;
        }}
    }}
    if (max_new <= 0 || max_new > 4096) max_new = 24;

    /* Read prompt from stdin (first line, up to 4 KB). */
    char prompt[4096];
    ssize_t plen = 0;
    while (plen < (ssize_t)sizeof(prompt) - 1) {{
        int n = read(0, prompt + plen, sizeof(prompt) - 1 - plen);
        if (n <= 0) break;
        plen += n;
    }}
    if (plen > 0 && prompt[plen - 1] == '\n') plen--;

    /* Build a synthetic state grid by embedding the *last* prompt
     * byte (autoregressive output's input) — a simplified version of
     * the Python pipeline's ca_embed_sequence which embeds every
     * position. Sufficient for smoke-grade output; the full embed
     * sequence requires the transformer blocks to run too. */
    static uint8_t grid[GRID_AREA];
    int last_byte = (plen > 0) ? (unsigned char)prompt[plen - 1] : 0;
    embed_token(last_byte, plen, grid);

    /* Generate. */
    static double logits[VOCAB];
    uint32_t rng = (uint32_t)plen * 2654435761u + 0xCA1ED175u;
    for (int i = 0; i < max_new; i++) {{
        output_head(grid, logits);
        int next = sample_byte(logits, 0.8, &rng, allow);
        putchar(next);
        embed_token(next, plen + i + 1, grid);
    }}
    putchar('\n');
    return 0;
}}
'''


C_FULL = r'''/* tinyformer-full — auto-generated from caformer.TrainedModel
 *   slug={slug}
 *   fitness={fitness:.4f}
 *   n_blocks={n_blocks}  (this binary runs ONE block; matches L2 nano_gpt-shape)
 *
 * Build:  cc -Os -o tinyformer tinyformer.c -lm
 * Use:    echo "the quick brown fox" | ./tinyformer 24
 *
 * Faithful single-block CA transformer in pure C, single file.
 * All 10 K=4 hex CA rule tables are baked in as 2-bit-packed static
 * arrays (40,960 bytes total). The forward pass mirrors
 * caformer.transformer.ca_forward_qkv at n_blocks=1:
 *   embed → norm → self-attention (q/k/v/score/mix) → merge
 *         → norm → mlp (with 2x expand) → merge → norm → output → sample
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include <unistd.h>

#define SIDE       16
#define AREA       (SIDE * SIDE)
#define EXP_SIDE   (SIDE * 2)
#define EXP_AREA   (EXP_SIDE * EXP_SIDE)
#define VOCAB      256
#define MAX_TOKENS 16
#define EMBED_TICKS  4
#define NORM_TICKS   4
#define QKV_TICKS    2
#define MLP_TICKS    2
#define OUTPUT_TICKS 2

/* Unpack one entry from a 2-bit-packed LUT. */
static inline uint8_t lut(const uint8_t *r, uint16_t idx) {{
    return (r[idx >> 2] >> ((3u - (idx & 3u)) * 2u)) & 3u;
}}

/* Generic hex CA step on (H,W) grid with toroidal wrap. */
static void hex_step(const uint8_t *in, uint8_t *out,
                      int H, int W, const uint8_t *rule) {{
    for (int y = 0; y < H; y++) {{
        int even = (y & 1) == 0;
        int yu = (y - 1 + H) % H;
        int yd = (y + 1) % H;
        for (int x = 0; x < W; x++) {{
            int xl = (x - 1 + W) % W;
            int xr = (x + 1) % W;
            uint8_t s  = in[y  * W + x ];
            uint8_t nw = even ? in[yu * W + xl] : in[yu * W + x ];
            uint8_t ne = even ? in[yu * W + x ] : in[yu * W + xr];
            uint8_t sw = even ? in[yd * W + xl] : in[yd * W + x ];
            uint8_t se = even ? in[yd * W + x ] : in[yd * W + xr];
            uint8_t nl = in[y  * W + xl];
            uint8_t nr = in[y  * W + xr];
            uint16_t k = (uint16_t)s  << 12 | (uint16_t)nw << 10
                       | (uint16_t)ne << 8  | (uint16_t)nr << 6
                       | (uint16_t)se << 4  | (uint16_t)sw << 2
                       | (uint16_t)nl;
            out[y * W + x] = lut(rule, k);
        }}
    }}
}}

/* Run k_ticks of `rule` on `grid` in place via a scratch buffer. */
static void apply_ticks(uint8_t *grid, int H, int W,
                          const uint8_t *rule, int k) {{
    static uint8_t scratch[EXP_AREA];   /* big enough for the MLP expand */
    for (int t = 0; t < k; t++) {{
        hex_step(grid, scratch, H, W, rule);
        memcpy(grid, scratch, (size_t)H * (size_t)W);
    }}
}}

/* Embed token id → SIDE×SIDE grid: LCG-seed + EMBED_TICKS of embed_rule. */
static void embed_token(int token_id, int pos, uint8_t *grid) {{
    uint32_t s = (uint32_t)token_id * 1103515245u
               + (uint32_t)pos      * 12345u + 0xC0FFEEu;
    for (int i = 0; i < AREA; i++) {{
        s = s * 1664525u + 1013904223u;
        grid[i] = (s >> 16) & 3u;
    }}
    apply_ticks(grid, SIDE, SIDE, RULE_EMBED, EMBED_TICKS);
}}

/* Stack two SIDE×SIDE grids vertically into a (2*SIDE,SIDE) grid;
 * used for ca_attention_score and ca_residual_merge. */
static void stack_v(const uint8_t *a, const uint8_t *b, uint8_t *out) {{
    memcpy(out,            a, AREA);
    memcpy(out + AREA,     b, AREA);
}}

/* CA attention score = #cells < 2 in the top half after one tick. */
static int attention_score(const uint8_t *q, const uint8_t *k) {{
    static uint8_t stack[2 * AREA], mixed[2 * AREA];
    stack_v(q, k, stack);
    hex_step(stack, mixed, 2 * SIDE, SIDE, RULE_SCORE);
    int n = 0;
    for (int i = 0; i < AREA; i++) if (mixed[i] < 2) n++;
    return n;
}}

/* Residual merge: stack (a,b) vertically, one tick of merge_rule, top half. */
static void residual_merge(const uint8_t *a, const uint8_t *b, uint8_t *out) {{
    static uint8_t stack[2 * AREA], mixed[2 * AREA];
    stack_v(a, b, stack);
    hex_step(stack, mixed, 2 * SIDE, SIDE, RULE_MERGE);
    memcpy(out, mixed, AREA);
}}

/* Tile a SIDE×SIDE grid 2x2 to EXP_SIDE×EXP_SIDE. */
static void tile_2x2(const uint8_t *in, uint8_t *out) {{
    for (int y = 0; y < EXP_SIDE; y++)
        for (int x = 0; x < EXP_SIDE; x++)
            out[y * EXP_SIDE + x] = in[(y % SIDE) * SIDE + (x % SIDE)];
}}

/* Majority-pool 2x2 → SIDE×SIDE: argmax-count colour per 2x2 block. */
static void majority_pool(const uint8_t *in, uint8_t *out) {{
    for (int y = 0; y < SIDE; y++) {{
        for (int x = 0; x < SIDE; x++) {{
            int counts[4] = {{0,0,0,0}};
            for (int dy = 0; dy < 2; dy++)
                for (int dx = 0; dx < 2; dx++)
                    counts[in[(y*2+dy) * EXP_SIDE + (x*2+dx)]]++;
            int best = 0;
            for (int c = 1; c < 4; c++) if (counts[c] > counts[best]) best = c;
            out[y * SIDE + x] = (uint8_t)best;
        }}
    }}
}}

/* MLP: tile 2x2 → MLP_TICKS of mlp_rule on the expanded grid → majority-pool back. */
static void ca_mlp(const uint8_t *in, uint8_t *out) {{
    static uint8_t big[EXP_AREA];
    tile_2x2(in, big);
    apply_ticks(big, EXP_SIDE, EXP_SIDE, RULE_MLP, MLP_TICKS);
    majority_pool(big, out);
}}

/* The full single-block forward.
 *
 * states[i] is the embedded CA grid for token i. Modifies in place.
 */
static void block_forward(uint8_t (*states)[AREA], int T) {{
    static uint8_t Qs[MAX_TOKENS][AREA];
    static uint8_t Ks[MAX_TOKENS][AREA];
    static uint8_t Vs[MAX_TOKENS][AREA];
    static uint8_t normed[AREA], orig[AREA], attended[AREA], xored[AREA];

    /* Pre-norm + Q/K/V projections per token. */
    for (int i = 0; i < T; i++) {{
        memcpy(normed, states[i], AREA);
        apply_ticks(normed, SIDE, SIDE, RULE_NORM, NORM_TICKS);
        memcpy(Qs[i], normed, AREA);
        apply_ticks(Qs[i], SIDE, SIDE, RULE_Q, QKV_TICKS);
        memcpy(Ks[i], normed, AREA);
        apply_ticks(Ks[i], SIDE, SIDE, RULE_K, QKV_TICKS);
        memcpy(Vs[i], normed, AREA);
        apply_ticks(Vs[i], SIDE, SIDE, RULE_V, QKV_TICKS);
    }}

    /* Hard causal attention + merge + MLP + merge per token. */
    for (int i = 0; i < T; i++) {{
        int best_j = 0, best_s = -1;
        for (int j = 0; j <= i; j++) {{
            int s = attention_score(Qs[i], Ks[j]);
            if (s > best_s) {{ best_s = s; best_j = j; }}
        }}
        /* attended = mix_rule(V[best_j] XOR state[i]). */
        for (int p = 0; p < AREA; p++)
            xored[p] = (Vs[best_j][p] ^ states[i][p]) & 3u;
        memcpy(attended, xored, AREA);
        apply_ticks(attended, SIDE, SIDE, RULE_MIX, 1);
        /* Residual 1: merge attended back into state[i]. */
        memcpy(orig, states[i], AREA);
        residual_merge(orig, attended, states[i]);
        /* Pre-norm + MLP + residual 2. */
        memcpy(normed, states[i], AREA);
        apply_ticks(normed, SIDE, SIDE, RULE_NORM, NORM_TICKS);
        ca_mlp(normed, attended);
        memcpy(orig, states[i], AREA);
        residual_merge(orig, attended, states[i]);
    }}
}}

/* Output head: norm + OUTPUT_TICKS of output_rule + cell-counts → logits. */
static void output_head(uint8_t *grid, double *logits) {{
    apply_ticks(grid, SIDE, SIDE, RULE_NORM, NORM_TICKS);
    apply_ticks(grid, SIDE, SIDE, RULE_OUTPUT, OUTPUT_TICKS);
    int counts[4] = {{0,0,0,0}};
    for (int i = 0; i < AREA; i++) counts[grid[i]]++;
    /* Bucket each byte v into v/64 (4 buckets); logit = count of that bucket. */
    for (int v = 0; v < VOCAB; v++) logits[v] = (double)counts[v >> 6];
}}

/* `allow[256]` is either NULL or a uint8 mask: 1 = sampling this
 * byte is permitted; 0 = mask its logit to -inf (zero probability). */
static int sample_byte(const double *logits, double T, uint32_t *rng,
                         const unsigned char *allow) {{
    double mx = -1e300;
    for (int v = 0; v < VOCAB; v++) {{
        if (allow && !allow[v]) continue;
        if (logits[v] > mx) mx = logits[v];
    }}
    if (mx == -1e300) mx = 0.0;
    double sum = 0.0;
    static double probs[VOCAB];
    for (int v = 0; v < VOCAB; v++) {{
        if (allow && !allow[v]) {{ probs[v] = 0.0; continue; }}
        probs[v] = exp((logits[v] - mx) / T); sum += probs[v];
    }}
    if (sum <= 0.0) return 0;
    uint32_t s = *rng; s ^= s << 13; s ^= s >> 17; s ^= s << 5; *rng = s;
    double u = ((double)s / (double)0xFFFFFFFFu) * sum;
    double acc = 0.0;
    for (int v = 0; v < VOCAB; v++) {{ acc += probs[v]; if (acc >= u) return v; }}
    return VOCAB - 1;
}}

/* ASCII printable + LF + CR sampler mask for `-a`. */
static const unsigned char ASCII_MASK[256] = {{
  /* 0..31 */   0,0,0,0,0,0,0,0,0,0, 1,0,0,1, 0,0, 0,0,0,0,0,0,0,0, 0,0,0,0,0,0,0,0,
  /* 32..63 */  1,1,1,1,1,1,1,1,1,1, 1,1,1,1, 1,1, 1,1,1,1,1,1,1,1, 1,1,1,1,1,1,1,1,
  /* 64..95 */  1,1,1,1,1,1,1,1,1,1, 1,1,1,1, 1,1, 1,1,1,1,1,1,1,1, 1,1,1,1,1,1,1,1,
  /* 96..127 */ 1,1,1,1,1,1,1,1,1,1, 1,1,1,1, 1,1, 1,1,1,1,1,1,1,1, 1,1,1,1,1,1,1,0,
  /* 128..255 */0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0, 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0, 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0, 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0, 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
}};

int main(int argc, char **argv) {{
    int max_new = 16;
    const unsigned char *allow = NULL;
    for (int ai = 1; ai < argc; ai++) {{
        if (argv[ai][0] == '-') {{
            for (const char *p = argv[ai] + 1; *p; p++) {{
                if      (*p == 'a') allow = ASCII_MASK;
                else if (*p == 'c') allow = CORPUS_ALPHABET;
            }}
        }} else {{
            int n = atoi(argv[ai]);
            if (n > 0) max_new = n;
        }}
    }}
    if (max_new <= 0 || max_new > 1024) max_new = 16;

    char prompt[4096];
    ssize_t plen = 0;
    while (plen < (ssize_t)sizeof(prompt) - 1) {{
        int n = read(0, prompt + plen, sizeof(prompt) - 1 - plen);
        if (n <= 0) break;
        plen += n;
    }}
    if (plen > 0 && prompt[plen - 1] == '\n') plen--;

    /* Embed each prompt byte (cap at MAX_TOKENS for the attention buffer). */
    static uint8_t states[MAX_TOKENS][AREA];
    int T = (plen > MAX_TOKENS) ? MAX_TOKENS : (int)plen;
    if (T == 0) {{ states[0][0] = 0; T = 1; }}
    int start = (plen > MAX_TOKENS) ? (plen - MAX_TOKENS) : 0;
    for (int i = 0; i < T; i++) {{
        embed_token((unsigned char)prompt[start + i], start + i, states[i]);
    }}

    /* Run the block forward. */
    block_forward(states, T);

    /* Generate. */
    static double logits[VOCAB];
    static uint8_t out_grid[AREA];
    uint32_t rng = (uint32_t)plen * 2654435761u + 0xCA1ED175u;
    for (int i = 0; i < max_new; i++) {{
        memcpy(out_grid, states[T - 1], AREA);
        output_head(out_grid, logits);
        int next = sample_byte(logits, 0.8, &rng, allow);
        putchar(next);
        /* Slide window: drop oldest if at cap, append new. */
        if (T == MAX_TOKENS) {{
            memmove(states, states + 1, (MAX_TOKENS - 1) * AREA);
            T = MAX_TOKENS - 1;
        }}
        embed_token(next, plen + i + 1, states[T]);
        T++;
        block_forward(states, T);
    }}
    putchar('\n');
    return 0;
}}
'''


def generate_c_source(model: TrainedModel, *, full: bool = True) -> str:
    """Return a self-contained .c source string for ``model``.

    Shared by the management command and the /caformer/export/ view so
    the UI download produces exactly what the CLI does.
    """
    corpus_bytes = set((model.corpus_excerpt or '').encode('utf-8',
                                                            errors='replace'))
    alphabet_init = ', '.join('0' if b not in corpus_bytes else '1'
                                for b in range(256))
    alphabet_decl = (
        f'/* 1 for each byte that appeared in the training corpus, '
        f'else 0. {len(corpus_bytes)} of 256 bytes seen. */\n'
        f'static const unsigned char CORPUS_ALPHABET[256] = {{\n  '
        + alphabet_init + '\n};')
    if full:
        rule_names = ['embed', 'q', 'k', 'v', 'score', 'mix',
                      'merge', 'mlp', 'norm', 'output']
        decls = []
        for n in rule_names:
            packed = _pack_2bit(bytes(getattr(model, f'rule_{n}')))
            decls.append(_c_array_decl(f'RULE_{n.upper()}', packed))
        decls_src = '\n\n'.join(decls) + '\n\n' + alphabet_decl
        return (decls_src + '\n\n'
                + C_FULL.format(slug=model.slug,
                                fitness=model.final_fitness,
                                n_blocks=model.n_blocks))
    embed_packed  = _pack_2bit(bytes(model.rule_embed))
    output_packed = _pack_2bit(bytes(model.rule_output))
    decls = (_c_array_decl('RULE_EMBED',  embed_packed) + '\n\n'
              + _c_array_decl('RULE_OUTPUT', output_packed) + '\n\n'
              + alphabet_decl)
    return (decls + '\n\n'
            + C_HEADER.format(slug=model.slug,
                              fitness=model.final_fitness,
                              n_blocks=model.n_blocks))


class Command(BaseCommand):
    help = ('Emit a self-contained C source for a TrainedModel; compile to '
            'get a tinyformer CLI binary.')

    def add_arguments(self, parser):
        parser.add_argument('slug', help='TrainedModel slug to export')
        parser.add_argument('--out', default=None,
                             help='Output .c file path (default: ./tinyformer-<slug>.c)')
        parser.add_argument('--full', action='store_true',
                             help='Emit the full single-block forward (all 10 '
                                  'rules baked in) instead of just embed+output. '
                                  'Bigger binary but actually a transformer.')

    def handle(self, slug, out=None, full=False, **opts):
        m = TrainedModel.objects.filter(slug=slug).first()
        if m is None:
            raise CommandError(f'no TrainedModel with slug={slug!r}')
        c_src = generate_c_source(m, full=full)
        mode_label = 'full' if full else 'simple'
        out_path = Path(out) if out else Path(f'tinyformer-{m.slug}.c')
        out_path.write_text(c_src)
        self.stdout.write(self.style.SUCCESS(
            f'wrote {out_path} ({len(c_src):,} bytes of C source, {mode_label} mode)'))
        self.stdout.write(
            f'compile:   cc -Os -o {out_path.stem} {out_path} -lm')
        self.stdout.write(
            f'run:       echo "hello" | ./{out_path.stem} 24')
