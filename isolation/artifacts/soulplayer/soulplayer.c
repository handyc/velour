/* soulplayer.c — C port of soulchat.py from gizmo64k/soulplayer-c64.
 *
 * Standalone integer-only inference for the 25 K-parameter 2-layer
 * decoder-only transformer trained by that project.  Loads the same
 * `soul.bin` (v3 file format) + `tokenizer.json` shipped in the
 * upstream repo and runs the same forward() pass numerics.py
 * specifies, bit-for-bit, just compiled to native code.
 *
 * Build:
 *   cc -Os -Wall -Wextra -o soulplayer soulplayer.c
 *
 * Run (from the directory holding soul.bin + tokenizer.json):
 *   ./soulplayer
 *   ./soulplayer path/to/soul.bin path/to/tokenizer.json
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>

/* ── architecture constants (must match numerics.py) ─────────── */
#define VS 128         /* vocab size */
#define ED 32          /* embedding dim */
#define NH 4           /* num heads */
#define HD 8           /* head dim (ED / NH) */
#define FF 64          /* FFN hidden */
#define NL 2           /* num layers */
#define SL 64          /* sequence length cap (PE has SL rows) */
#define ACT_SHIFT 8    /* Q8.8 activations */

#define PAD 0
#define SEP 1
#define UNK 2
#define END 3

/* ── weights ─────────────────────────────────────────────────── */
typedef struct { int8_t *q; int s; int rows; int cols; } W8;
typedef struct { int16_t *q; int s; int rows; int cols; } W16;

static W8  te, pe;
typedef struct {
    W8 n1, q, k, v, proj, n2, fc1_w, fc2_w;
    W16 fc1_b, fc2_b;
} Layer;
static Layer Lyr[NL];
static W8  norm_w, out_w;

/* Static storage for the actual int8/int16 arrays — sized for this
 * exact architecture.  No mallocs needed. */
static int8_t  te_data[VS * ED];
static int8_t  pe_data[SL * ED];
static int8_t  norm_data[ED];
static int8_t  out_data[VS * ED];
static int8_t  L_n1[NL][ED];
static int8_t  L_q [NL][ED * ED];
static int8_t  L_k [NL][ED * ED];
static int8_t  L_v [NL][ED * ED];
static int8_t  L_proj[NL][ED * ED];
static int8_t  L_n2[NL][ED];
static int8_t  L_fc1w[NL][FF * ED];
static int8_t  L_fc2w[NL][ED * FF];
static int16_t L_fc1b[NL][FF];
static int16_t L_fc2b[NL][ED];

/* ── tokenizer ───────────────────────────────────────────────── */
#define MAX_TOKLEN 16
static char     vocab_str[VS][MAX_TOKLEN];
static uint8_t  vocab_len[VS];

#define MAX_MERGES 256
typedef struct { int a, b, id; } Merge;
static Merge merges[MAX_MERGES];
static int   n_merges = 0;

/* Lookup a token-string → id (linear scan; VS = 128). */
static int vocab_lookup(const char *s, int len) {
    for (int i = 0; i < VS; i++) {
        if (vocab_len[i] != len) continue;
        if (memcmp(vocab_str[i], s, len) == 0) return i;
    }
    return -1;
}

/* ── int helpers ─────────────────────────────────────────────── */
static int sat16(int v) {
    if (v >  32767) return  32767;
    if (v < -32768) return -32768;
    return v;
}
static int32_t sar32(int32_t v, int sh) {
    if (sh >= 0) return v >> sh;
    return v << (-sh);
}
static uint32_t isqrt_u32(uint32_t v) {
    if (v == 0) return 0;
    uint32_t result = 0;
    uint32_t bit = 1u << 30;
    while (bit > v) bit >>= 2;
    while (bit) {
        if (v >= result + bit) {
            v -= result + bit;
            result = (result >> 1) + bit;
        } else {
            result >>= 1;
        }
        bit >>= 2;
    }
    return result;
}

/* ── soul.bin v3 reader ──────────────────────────────────────── */
static int read_u8 (FILE *f) { int c = fgetc(f); return c; }
static int read_u16le(FILE *f) { int lo = fgetc(f); int hi = fgetc(f); return lo | (hi << 8); }
static int read_i8 (FILE *f) { int c = fgetc(f); return c >= 128 ? c - 256 : c; }

static int load_w8(FILE *f, int8_t *dst, int rows, int cols, W8 *meta) {
    int kind = read_u8(f);
    int r = read_u16le(f);
    int c = read_u16le(f);
    int s = read_i8(f);
    if (kind != 0) { fprintf(stderr, "expected w-tensor, got kind=%d\n", kind); return -1; }
    if (r != rows || c != cols) {
        fprintf(stderr, "shape mismatch: got %dx%d, expected %dx%d\n", r, c, rows, cols);
        return -1;
    }
    if (fread(dst, 1, rows * cols, f) != (size_t)(rows * cols)) return -1;
    meta->q = dst; meta->s = s; meta->rows = rows; meta->cols = cols;
    return 0;
}

static int load_w16(FILE *f, int16_t *dst, int n, W16 *meta) {
    int kind = read_u8(f);
    int r = read_u16le(f);
    int c = read_u16le(f);
    int s = read_i8(f);
    if (kind != 1) { fprintf(stderr, "expected b-tensor, got kind=%d\n", kind); return -1; }
    if (r * c != n) {
        fprintf(stderr, "bias shape mismatch: %d*%d != %d\n", r, c, n);
        return -1;
    }
    if (fread(dst, 2, n, f) != (size_t)n) return -1;
    meta->q = dst; meta->s = s; meta->rows = r; meta->cols = c;
    return 0;
}

static int load_soul(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); return -1; }
    if (load_w8(f, te_data, VS, ED, &te)   < 0) goto fail;
    if (load_w8(f, pe_data, SL, ED, &pe)   < 0) goto fail;
    for (int L = 0; L < NL; L++) {
        Layer *ly = &Lyr[L];
        if (load_w8 (f, L_n1[L],   ED,  1, &ly->n1)   < 0) goto fail;
        if (load_w8 (f, L_q [L],   ED, ED, &ly->q)    < 0) goto fail;
        if (load_w8 (f, L_k [L],   ED, ED, &ly->k)    < 0) goto fail;
        if (load_w8 (f, L_v [L],   ED, ED, &ly->v)    < 0) goto fail;
        if (load_w8 (f, L_proj[L], ED, ED, &ly->proj) < 0) goto fail;
        if (load_w8 (f, L_n2[L],   ED,  1, &ly->n2)   < 0) goto fail;
        if (load_w8 (f, L_fc1w[L], FF, ED, &ly->fc1_w) < 0) goto fail;
        if (load_w16(f, L_fc1b[L], FF, &ly->fc1_b)    < 0) goto fail;
        if (load_w8 (f, L_fc2w[L], ED, FF, &ly->fc2_w) < 0) goto fail;
        if (load_w16(f, L_fc2b[L], ED, &ly->fc2_b)    < 0) goto fail;
    }
    if (load_w8(f, norm_data, ED,  1, &norm_w) < 0) goto fail;
    if (load_w8(f, out_data,  VS, ED, &out_w)  < 0) goto fail;
    fclose(f);
    return 0;
fail:
    fclose(f);
    return -1;
}

/* ── tokenizer.json parser ──────────────────────────────────────
 * Hand-written, just enough for this file's exact layout.  Walks
 * the byte stream looking for "vocab": { ... } and "merges": [ ... ]
 * and parses the entries.  Robust enough for the upstream file;
 * not a general JSON parser. */

static int json_skip_ws(const char *s, int p, int n) {
    while (p < n && (s[p] == ' ' || s[p] == '\t' || s[p] == '\n' || s[p] == '\r' || s[p] == ','))
        p++;
    return p;
}

static int json_parse_str(const char *s, int p, int n, char *out, int cap) {
    if (p >= n || s[p] != '"') return -1;
    p++;
    int o = 0;
    while (p < n && s[p] != '"' && o < cap - 1) {
        if (s[p] == '\\' && p + 1 < n) {
            char e = s[p+1];
            if      (e == 'n') out[o++] = '\n';
            else if (e == 't') out[o++] = '\t';
            else if (e == '"') out[o++] = '"';
            else if (e == '\\') out[o++] = '\\';
            else               out[o++] = e;
            p += 2;
        } else {
            out[o++] = s[p++];
        }
    }
    out[o] = 0;
    if (p < n && s[p] == '"') p++;
    return p << 16 | (o & 0xffff);
}

static int json_parse_int(const char *s, int p, int n) {
    int sign = 1;
    if (p < n && s[p] == '-') { sign = -1; p++; }
    int v = 0;
    while (p < n && s[p] >= '0' && s[p] <= '9') {
        v = v * 10 + (s[p] - '0'); p++;
    }
    return p << 16 | (((sign * v) & 0xffff));
}

static int load_tokenizer(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); return -1; }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *s = (char *)malloc(n + 1);
    if (!s) { fclose(f); return -1; }
    if (fread(s, 1, n, f) != (size_t)n) { free(s); fclose(f); return -1; }
    s[n] = 0;
    fclose(f);

    /* Find "vocab": { */
    char *vp = strstr(s, "\"vocab\"");
    if (!vp) { free(s); return -1; }
    vp = strchr(vp, '{');
    if (!vp) { free(s); return -1; }
    int p = (int)(vp - s) + 1;
    /* Each entry: "<key>": <id>, ... until matching '}' */
    int depth = 1;
    while (p < n && depth > 0) {
        p = json_skip_ws(s, p, n);
        if (p >= n) break;
        if (s[p] == '}') { depth--; p++; continue; }
        if (s[p] == '{') { depth++; p++; continue; }
        char key[MAX_TOKLEN];
        int k = json_parse_str(s, p, n, key, MAX_TOKLEN);
        if (k < 0) { free(s); return -1; }
        p = k >> 16;
        int klen = k & 0xffff;
        p = json_skip_ws(s, p, n);
        if (p < n && s[p] == ':') p++;
        p = json_skip_ws(s, p, n);
        int vk = json_parse_int(s, p, n);
        p = vk >> 16;
        int id = (int16_t)(vk & 0xffff);
        if (id >= 0 && id < VS && klen < MAX_TOKLEN) {
            memcpy(vocab_str[id], key, klen);
            vocab_str[id][klen] = 0;
            vocab_len[id] = (uint8_t)klen;
        }
    }

    /* Find "merges": [ */
    char *mp = strstr(s, "\"merges\"");
    if (mp) {
        mp = strchr(mp, '[');
        if (mp) {
            int q = (int)(mp - s) + 1;
            while (q < n) {
                q = json_skip_ws(s, q, n);
                if (q >= n || s[q] == ']') break;
                if (s[q] != '[') { q++; continue; }
                q++;
                /* Parse two strings inside [ "a", "b" ] */
                char a[MAX_TOKLEN], b[MAX_TOKLEN];
                q = json_skip_ws(s, q, n);
                int ka = json_parse_str(s, q, n, a, MAX_TOKLEN);
                if (ka < 0) break;
                q = ka >> 16;
                int alen = ka & 0xffff;
                q = json_skip_ws(s, q, n);
                int kb = json_parse_str(s, q, n, b, MAX_TOKLEN);
                if (kb < 0) break;
                q = kb >> 16;
                int blen = kb & 0xffff;
                q = json_skip_ws(s, q, n);
                if (q < n && s[q] == ']') q++;
                /* Resolve ids; merged token = a+b looked up by string. */
                int aid = vocab_lookup(a, alen);
                int bid = vocab_lookup(b, blen);
                if (aid < 0 || bid < 0) continue;
                char merged[MAX_TOKLEN * 2];
                int mlen = alen + blen;
                if (mlen >= (int)sizeof merged) continue;
                memcpy(merged,        a, alen);
                memcpy(merged + alen, b, blen);
                int mid = vocab_lookup(merged, mlen);
                if (mid < 0) continue;
                if (n_merges < MAX_MERGES) {
                    merges[n_merges].a  = aid;
                    merges[n_merges].b  = bid;
                    merges[n_merges].id = mid;
                    n_merges++;
                }
            }
        }
    }
    free(s);
    return 0;
}

/* ── encode/decode ───────────────────────────────────────────── */
static int encode(const char *text, int *ids, int cap) {
    int n = 0;
    for (int i = 0; text[i] && n < cap; i++) {
        char c = text[i];
        if (c >= 'A' && c <= 'Z') c = (char)(c + 32);
        int id = vocab_lookup(&c, 1);
        if (id >= 0) ids[n++] = id;
    }
    /* Apply BPE merges in order. */
    for (int m = 0; m < n_merges; m++) {
        int a = merges[m].a, b = merges[m].b, id = merges[m].id;
        int w = 0;
        for (int r = 0; r < n; ) {
            if (r + 1 < n && ids[r] == a && ids[r+1] == b) {
                ids[w++] = id;
                r += 2;
            } else {
                ids[w++] = ids[r++];
            }
        }
        n = w;
    }
    return n;
}

static void decode_print(int id) {
    if (id < 0 || id >= VS) return;
    /* Skip special tokens. */
    if (id == PAD || id == SEP || id == UNK || id == END) return;
    fwrite(vocab_str[id], 1, vocab_len[id], stdout);
    fflush(stdout);
}

/* ── inference primitives ────────────────────────────────────── */
static int32_t deshift(int8_t v, int s) {
    int diff = ACT_SHIFT - s;
    if (diff >= 0) return ((int32_t)v) << diff;
    return ((int32_t)v) >> (-diff);
}

static void matvec(const W8 *Wm, const int16_t *x, int rows, int cols,
                   int post_shift, int16_t *out) {
    int total = Wm->s + post_shift;
    for (int r = 0; r < rows; r++) {
        const int8_t *row = Wm->q + r * cols;
        int32_t acc = 0;
        for (int c = 0; c < cols; c++) acc += (int32_t)row[c] * (int32_t)x[c];
        int32_t y = sar32(acc, total);
        out[r] = (int16_t)sat16(y);
    }
}

static void matvec_bias16(const W8 *Wm, const W16 *bm, const int16_t *x,
                          int rows, int cols, int post_shift, int16_t *out) {
    int total = Wm->s + post_shift;
    for (int r = 0; r < rows; r++) {
        const int8_t *row = Wm->q + r * cols;
        int32_t acc = (int32_t)bm->q[r];
        for (int c = 0; c < cols; c++) acc += (int32_t)row[c] * (int32_t)x[c];
        int32_t y = sar32(acc, total);
        out[r] = (int16_t)sat16(y);
    }
}

static void rms_norm(const int16_t *x, const W8 *gain, int n, int16_t *out) {
    int32_t sum_sq = 0;
    for (int i = 0; i < n; i++) {
        int32_t xs = ((int32_t)x[i]) >> 4;
        sum_sq += xs * xs;
    }
    int32_t mean_sq = sum_sq / n;
    if (mean_sq < 1) mean_sq = 1;
    uint32_t rms = isqrt_u32((uint32_t)mean_sq);
    if (rms < 1) rms = 1;
    uint32_t inv = (1u << 19) / rms;
    if (inv > 32767) inv = 32767;
    for (int i = 0; i < n; i++) {
        int32_t y_raw = (((int32_t)x[i]) * (int32_t)inv) >> 15;
        int32_t y = (y_raw * (int32_t)gain->q[i]) >> gain->s;
        out[i] = (int16_t)sat16(y);
    }
}

/* Exp LUT: EXP_LUT[i] = round(255 * exp(-i/16)) for i in 0..127, with
 * EXP_LUT[0] forced to 255 and EXP_LUT[127] forced to 0. */
static uint8_t EXP_LUT[128];
static void init_exp_lut(void) {
    for (int i = 0; i < 128; i++) {
        double v = 255.0 * exp(-i / 16.0);
        int q = (int)(v + 0.5);
        if (q < 1) q = 1;
        if (q > 255) q = 255;
        EXP_LUT[i] = (uint8_t)(i == 0 ? 255 : q);
    }
    EXP_LUT[127] = 0;
}

/* Softmax + weighted sum:
 *   sf = scores >> 14 (int64 → int16)
 *   max_sf = max(sf)
 *   weights[i] = EXP_LUT[clamp(max_sf - sf[i], 0, 127)]
 *   out[j] = (Σ weights[i] * v[i,j]) / Σ weights[i]
 */
static void softmax_weighted_sum(const int32_t *scores, int n,
                                 const int16_t *vals, int hd, int16_t *out) {
    int32_t sf[SL];
    int32_t max_sf = -2000000000;
    for (int i = 0; i < n; i++) {
        sf[i] = scores[i] >> 14;
        if (sf[i] > max_sf) max_sf = sf[i];
    }
    uint8_t w[SL];
    int32_t w_sum = 0;
    for (int i = 0; i < n; i++) {
        int32_t d = max_sf - sf[i];
        if (d < 0) d = 0;
        if (d > 127) d = 127;
        w[i] = EXP_LUT[d];
        w_sum += w[i];
    }
    if (w_sum == 0) w_sum = 1;
    for (int j = 0; j < hd; j++) {
        int32_t acc = 0;
        for (int i = 0; i < n; i++) acc += (int32_t)w[i] * (int32_t)vals[i * hd + j];
        int32_t q = acc / w_sum;
        out[j] = (int16_t)sat16(q);
    }
}

/* ── forward ─────────────────────────────────────────────────── */
static int16_t h_buf[SL][ED];
static int16_t q_all[SL][ED];
static int16_t k_all[SL][ED];
static int16_t v_all[SL][ED];
static int16_t att_new[SL][ED];

static int forward_argmax(const int *ids, int T, int16_t *logits_out) {
    /* Embedding + position. */
    for (int t = 0; t < T; t++) {
        int tok = ids[t];
        for (int d = 0; d < ED; d++) {
            int32_t v = deshift(te.q[tok * ED + d], te.s) +
                        deshift(pe.q[t   * ED + d], pe.s);
            h_buf[t][d] = (int16_t)sat16(v);
        }
    }
    for (int L = 0; L < NL; L++) {
        Layer *ly = &Lyr[L];
        /* Per-position pre-norm + Q/K/V projections. */
        for (int t = 0; t < T; t++) {
            int16_t xn[ED];
            rms_norm(h_buf[t], &ly->n1, ED, xn);
            matvec(&ly->q, xn, ED, ED, 1, q_all[t]);
            matvec(&ly->k, xn, ED, ED, 1, k_all[t]);
            matvec(&ly->v, xn, ED, ED, 1, v_all[t]);
        }
        /* Causal multi-head attention. */
        for (int tq = 0; tq < T; tq++) {
            for (int head = 0; head < NH; head++) {
                int off = head * HD;
                int n_keys = tq + 1;
                int32_t scores[SL];
                int16_t v_head[SL * HD];
                for (int tk = 0; tk < n_keys; tk++) {
                    int32_t s = 0;
                    for (int d = 0; d < HD; d++) {
                        s += (int32_t)q_all[tq][off + d] *
                             (int32_t)k_all[tk][off + d];
                    }
                    scores[tk] = s;
                    for (int d = 0; d < HD; d++)
                        v_head[tk * HD + d] = v_all[tk][off + d];
                }
                int16_t out_head[HD];
                softmax_weighted_sum(scores, n_keys, v_head, HD, out_head);
                for (int d = 0; d < HD; d++)
                    att_new[tq][off + d] = out_head[d];
            }
        }
        /* Output projection + residual. */
        for (int t = 0; t < T; t++) {
            int16_t att_proj[ED];
            matvec(&ly->proj, att_new[t], ED, ED, 1, att_proj);
            for (int d = 0; d < ED; d++)
                h_buf[t][d] = (int16_t)sat16((int32_t)h_buf[t][d] + (int32_t)att_proj[d]);
        }
        /* FFN: y = relu(fc1(rmsnorm(h))) ; h += fc2(y). */
        for (int t = 0; t < T; t++) {
            int16_t yn[ED], z[FF], w2[ED];
            rms_norm(h_buf[t], &ly->n2, ED, yn);
            matvec_bias16(&ly->fc1_w, &ly->fc1_b, yn, FF, ED, 1, z);
            for (int i = 0; i < FF; i++) if (z[i] < 0) z[i] = 0;
            matvec_bias16(&ly->fc2_w, &ly->fc2_b, z, ED, FF, 1, w2);
            for (int d = 0; d < ED; d++)
                h_buf[t][d] = (int16_t)sat16((int32_t)h_buf[t][d] + (int32_t)w2[d]);
        }
    }
    /* Final norm + logits, argmax over [4, VS). */
    int16_t y[ED];
    rms_norm(h_buf[T - 1], &norm_w, ED, y);
    int16_t logits[VS];
    matvec(&out_w, y, VS, ED, 0, logits);
    if (logits_out) memcpy(logits_out, logits, sizeof logits);
    int best = 4;
    int best_v = logits[4];
    for (int i = 5; i < VS; i++) {
        if (logits[i] > best_v) { best_v = logits[i]; best = i; }
    }
    return best;
}

/* ── REPL ─────────────────────────────────────────────────────── */
int main(int argc, char **argv) {
    const char *soul = (argc > 1) ? argv[1] : "soul.bin";
    const char *tok  = (argc > 2) ? argv[2] : "tokenizer.json";

    init_exp_lut();
    if (load_soul(soul) < 0) {
        fprintf(stderr, "Failed to load soul: %s\n", soul);
        return 1;
    }
    if (load_tokenizer(tok) < 0) {
        fprintf(stderr, "Failed to load tokenizer: %s\n", tok);
        return 1;
    }

    fputs("\n   .---------. \n", stdout);
    fputs("  |  O     O  |\n", stdout);
    fputs("  |     V     |\n", stdout);
    fputs("  |..|-----|..|\n\n", stdout);
    fputs("  SOUL CHAT (C port)\n  type a message. lowercase only.\n", stdout);
    fputs("  type 'q' to quit.\n\n", stdout);

    char line[1024];
    while (1) {
        fputs("YOU> ", stdout);
        fflush(stdout);
        if (!fgets(line, sizeof line, stdin)) break;
        size_t ln = strlen(line);
        while (ln > 0 && (line[ln-1] == '\n' || line[ln-1] == '\r')) line[--ln] = 0;
        if (ln == 0) continue;
        if (ln == 1 && (line[0] == 'q' || line[0] == 'Q')) break;

        int ids[SL];
        int n = 0;
        ids[n++] = SEP;
        int body[SL];
        int bn = encode(line, body, SL - 2);
        for (int i = 0; i < bn && n < SL - 1; i++) ids[n++] = body[i];
        ids[n++] = SEP;

        fputs("C64> ", stdout);
        fflush(stdout);
        for (int gen = 0; gen < SL && n < SL; gen++) {
            int tok_id = forward_argmax(ids, n, NULL);
            if (tok_id == PAD || tok_id == SEP || tok_id == END) break;
            decode_print(tok_id);
            ids[n++] = tok_id;
        }
        fputc('\n', stdout);
    }
    fputs("\n  -- the only winning move is love!\n\n", stdout);
    return 0;
}
