/* soulgen.c — evolve per-tensor scale shifts of a trained soul.bin.
 *
 * The 25 K-parameter soul has 24 tensors; each carries a single
 * signed int8 "shift" that determines how its int8 values map back
 * to floats during matmul (`acc >> (s + post_shift)`).  Those 24
 * bytes are the entire genome here.  A small GA — population N,
 * tournament-2 selection, ±1 point mutation, single-cut crossover —
 * searches over shift adjustments for ones that improve generated-
 * text quality on a held-out test corpus.  Fitness for each
 * individual is the sum of longest-common-substring lengths between
 * its generated reply and the expected substring for each prompt.
 *
 * No GPU, no PyTorch, no gradient anything — just integer inference
 * + tournament breed.  Closes the loop with hxhnt's GA pattern:
 * same tournament-2, same breed-bottom-half, same point mutation.
 *
 * Build:
 *   cc -Os -Wall -Wextra -o soulgen soulgen.c -lm
 * Run:
 *   ./soulgen                            # defaults
 *   ./soulgen --soul soul.bin --tests soul_tests.txt --out evolved.bin
 *   ./soulgen --pop 32 --gens 100 --mut-rate 0.20 --seed 7
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include <time.h>

/* ── architecture (must match numerics.py + soulplayer.c) ───── */
#define VS 128
#define ED 32
#define NH 4
#define HD 8
#define FF 64
#define NL 2
#define SL 64
#define ACT_SHIFT 8

#define PAD 0
#define SEP 1
#define UNK 2
#define END 3

#define N_SHIFTS 24    /* tensors with a tunable shift */

/* ── tensor metadata ────────────────────────────────────────── */
typedef struct {
    const int8_t  *q8;        /* int8  payload (or NULL) */
    const int16_t *q16;       /* int16 payload (or NULL) */
    int            base_s;    /* shift as found in the file */
    int            rows, cols;
} TM;

static TM   T_te, T_pe, T_norm, T_out;
typedef struct {
    TM n1, q, k, v, proj, n2, fc1_w, fc2_w, fc1_b, fc2_b;
} Lyr;
static Lyr  Lyrs[NL];

/* g_shift[i] = current shift for tensor i (= base_s + delta).  The
 * GA mutates this array; forward() reads it. */
static int  g_shift[N_SHIFTS];
static int  g_base [N_SHIFTS];

/* Helpers to address a tensor by its position in [0..23). */
static TM *tensor_by_idx(int i) {
    static TM *idx_to_tm[N_SHIFTS];
    static int  built = 0;
    if (!built) {
        int k = 0;
        idx_to_tm[k++] = &T_te;
        idx_to_tm[k++] = &T_pe;
        for (int L = 0; L < NL; L++) {
            idx_to_tm[k++] = &Lyrs[L].n1;
            idx_to_tm[k++] = &Lyrs[L].q;
            idx_to_tm[k++] = &Lyrs[L].k;
            idx_to_tm[k++] = &Lyrs[L].v;
            idx_to_tm[k++] = &Lyrs[L].proj;
            idx_to_tm[k++] = &Lyrs[L].n2;
            idx_to_tm[k++] = &Lyrs[L].fc1_w;
            idx_to_tm[k++] = &Lyrs[L].fc1_b;
            idx_to_tm[k++] = &Lyrs[L].fc2_w;
            idx_to_tm[k++] = &Lyrs[L].fc2_b;
        }
        idx_to_tm[k++] = &T_norm;
        idx_to_tm[k++] = &T_out;
        built = 1;
    }
    return idx_to_tm[i];
}

/* ── soul.bin v3 reader ────────────────────────────────────── */
static unsigned char  G_soul[40000];
static int            G_soul_n;
static int            G_shift_offsets[N_SHIFTS];   /* into G_soul */

static int read_u8 (FILE *f)  { return fgetc(f); }
static int read_u16le(FILE *f){ int lo=fgetc(f); int hi=fgetc(f); return lo|(hi<<8); }
static int read_i8 (FILE *f)  { int c=fgetc(f); return c>=128 ? c-256 : c; }

static int load_soul(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); return -1; }
    fseek(f, 0, SEEK_END);
    G_soul_n = (int)ftell(f);
    if (G_soul_n > (int)sizeof G_soul) {
        fprintf(stderr, "soul too large: %d\n", G_soul_n);
        fclose(f); return -1;
    }
    fseek(f, 0, SEEK_SET);
    if (fread(G_soul, 1, G_soul_n, f) != (size_t)G_soul_n) { fclose(f); return -1; }
    fclose(f);

    /* Walk the bytes, populate every tensor's metadata + record
     * the byte offset of its shift within G_soul so the GA can
     * later patch it. */
    int off = 0;
    int idx = 0;
    struct tspec { int rows, cols; int kind; TM *m; };
    struct tspec spec[64];
    int nspec = 0;
    spec[nspec++] = (struct tspec){VS, ED, 0, &T_te};
    spec[nspec++] = (struct tspec){SL, ED, 0, &T_pe};
    for (int L = 0; L < NL; L++) {
        Lyr *ly = &Lyrs[L];
        spec[nspec++] = (struct tspec){ED,  1, 0, &ly->n1};
        spec[nspec++] = (struct tspec){ED, ED, 0, &ly->q};
        spec[nspec++] = (struct tspec){ED, ED, 0, &ly->k};
        spec[nspec++] = (struct tspec){ED, ED, 0, &ly->v};
        spec[nspec++] = (struct tspec){ED, ED, 0, &ly->proj};
        spec[nspec++] = (struct tspec){ED,  1, 0, &ly->n2};
        spec[nspec++] = (struct tspec){FF, ED, 0, &ly->fc1_w};
        spec[nspec++] = (struct tspec){FF,  1, 1, &ly->fc1_b};
        spec[nspec++] = (struct tspec){ED, FF, 0, &ly->fc2_w};
        spec[nspec++] = (struct tspec){ED,  1, 1, &ly->fc2_b};
    }
    spec[nspec++] = (struct tspec){ED,  1, 0, &T_norm};
    spec[nspec++] = (struct tspec){VS, ED, 0, &T_out};

    for (int t = 0; t < nspec; t++) {
        int kind = G_soul[off++];
        int rows = G_soul[off] | (G_soul[off+1] << 8); off += 2;
        int cols = G_soul[off] | (G_soul[off+1] << 8); off += 2;
        int shift_off = off;
        int s = (int8_t)G_soul[off++];
        if (kind != spec[t].kind || rows != spec[t].rows || cols != spec[t].cols) {
            fprintf(stderr, "tensor %d shape/kind mismatch\n", t);
            return -1;
        }
        spec[t].m->base_s = s;
        spec[t].m->rows   = rows;
        spec[t].m->cols   = cols;
        if (kind == 0) {
            spec[t].m->q8  = (const int8_t *)(G_soul + off);
            spec[t].m->q16 = NULL;
            off += rows * cols;
        } else {
            spec[t].m->q8  = NULL;
            spec[t].m->q16 = (const int16_t *)(G_soul + off);
            off += rows * cols * 2;
        }
        G_shift_offsets[idx] = shift_off;
        g_base [idx] = s;
        g_shift[idx] = s;
        idx++;
    }
    return 0;
}

/* Save G_soul to disk after patching shifts at the recorded offsets
 * with whatever's in g_shift[].  Preserves all weights as-is. */
static int save_soul(const char *path) {
    /* Patch in place. */
    for (int i = 0; i < N_SHIFTS; i++) {
        int s = g_shift[i];
        if (s < -128) s = -128;
        if (s >  127) s =  127;
        G_soul[G_shift_offsets[i]] = (unsigned char)(int8_t)s;
    }
    FILE *f = fopen(path, "wb");
    if (!f) { perror(path); return -1; }
    if (fwrite(G_soul, 1, G_soul_n, f) != (size_t)G_soul_n) { fclose(f); return -1; }
    fclose(f);
    return 0;
}

/* ── tokenizer ──────────────────────────────────────────────── */
#define MAX_TOKLEN 16
static char    vocab_str[VS][MAX_TOKLEN];
static uint8_t vocab_len[VS];
#define MAX_MERGES 256
typedef struct { int a, b, id; } Merge;
static Merge merges[MAX_MERGES];
static int   n_merges;

static int vocab_lookup(const char *s, int len) {
    for (int i = 0; i < VS; i++) {
        if (vocab_len[i] != len) continue;
        if (memcmp(vocab_str[i], s, len) == 0) return i;
    }
    return -1;
}

static int json_parse_str(const char *s, int p, int n, char *out, int cap) {
    if (p >= n || s[p] != '"') return -1;
    p++; int o = 0;
    while (p < n && s[p] != '"' && o < cap - 1) {
        if (s[p] == '\\' && p + 1 < n) {
            char e = s[p+1];
            if      (e == 'n')  out[o++] = '\n';
            else if (e == 't')  out[o++] = '\t';
            else if (e == '"')  out[o++] = '"';
            else if (e == '\\') out[o++] = '\\';
            else                out[o++] = e;
            p += 2;
        } else { out[o++] = s[p++]; }
    }
    out[o] = 0;
    if (p < n && s[p] == '"') p++;
    return p << 16 | (o & 0xffff);
}
static int json_parse_int(const char *s, int p, int n) {
    int sign = 1;
    if (p < n && s[p] == '-') { sign = -1; p++; }
    int v = 0;
    while (p < n && s[p] >= '0' && s[p] <= '9') { v = v * 10 + (s[p] - '0'); p++; }
    return p << 16 | (((sign * v) & 0xffff));
}
static int load_tokenizer(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); return -1; }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    char *s = (char *)malloc(n + 1);
    if (!s) { fclose(f); return -1; }
    if (fread(s, 1, n, f) != (size_t)n) { free(s); fclose(f); return -1; }
    s[n] = 0; fclose(f);

    char *vp = strstr(s, "\"vocab\"");
    if (!vp) { free(s); return -1; }
    vp = strchr(vp, '{');
    int p = (int)(vp - s) + 1, depth = 1;
    while (p < n && depth > 0) {
        while (p < n && (s[p] == ' ' || s[p] == '\t' || s[p] == '\n' || s[p] == ',' || s[p] == '\r')) p++;
        if (p >= n) break;
        if (s[p] == '}') { depth--; p++; continue; }
        char key[MAX_TOKLEN];
        int k = json_parse_str(s, p, n, key, MAX_TOKLEN);
        if (k < 0) { free(s); return -1; }
        p = k >> 16;
        int klen = k & 0xffff;
        while (p < n && (s[p] == ' ' || s[p] == ':')) p++;
        int vk = json_parse_int(s, p, n);
        p = vk >> 16;
        int id = (int16_t)(vk & 0xffff);
        if (id >= 0 && id < VS && klen < MAX_TOKLEN) {
            memcpy(vocab_str[id], key, klen);
            vocab_str[id][klen] = 0;
            vocab_len[id] = (uint8_t)klen;
        }
    }
    char *mp = strstr(s, "\"merges\"");
    if (mp) {
        mp = strchr(mp, '[');
        int q = (int)(mp - s) + 1;
        while (q < n) {
            while (q < n && (s[q] == ' ' || s[q] == '\t' || s[q] == '\n' || s[q] == ',' || s[q] == '\r')) q++;
            if (q >= n || s[q] == ']') break;
            if (s[q] != '[') { q++; continue; }
            q++;
            char a[MAX_TOKLEN], b[MAX_TOKLEN];
            while (q < n && (s[q] == ' ' || s[q] == ',')) q++;
            int ka = json_parse_str(s, q, n, a, MAX_TOKLEN);
            if (ka < 0) break;
            q = ka >> 16; int alen = ka & 0xffff;
            while (q < n && (s[q] == ' ' || s[q] == ',')) q++;
            int kb = json_parse_str(s, q, n, b, MAX_TOKLEN);
            if (kb < 0) break;
            q = kb >> 16; int blen = kb & 0xffff;
            while (q < n && s[q] != ']' && s[q] != '\n') q++;
            if (q < n && s[q] == ']') q++;
            int aid = vocab_lookup(a, alen);
            int bid = vocab_lookup(b, blen);
            if (aid < 0 || bid < 0) continue;
            char merged[MAX_TOKLEN * 2];
            int mlen = alen + blen;
            if (mlen >= (int)sizeof merged) continue;
            memcpy(merged, a, alen); memcpy(merged + alen, b, blen);
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
    free(s);
    return 0;
}

static int encode(const char *text, int *ids, int cap) {
    int n = 0;
    for (int i = 0; text[i] && n < cap; i++) {
        char c = text[i];
        if (c >= 'A' && c <= 'Z') c = (char)(c + 32);
        int id = vocab_lookup(&c, 1);
        if (id >= 0) ids[n++] = id;
    }
    for (int m = 0; m < n_merges; m++) {
        int a = merges[m].a, b = merges[m].b, id = merges[m].id;
        int w = 0;
        for (int r = 0; r < n; ) {
            if (r + 1 < n && ids[r] == a && ids[r+1] == b) { ids[w++] = id; r += 2; }
            else { ids[w++] = ids[r++]; }
        }
        n = w;
    }
    return n;
}

/* ── inference (uses g_shift[]) ─────────────────────────────── */
static int sat16(int v) { if (v>32767) return 32767; if (v<-32768) return -32768; return v; }
static int sar32(int v, int sh) { if (sh >= 0) return v >> sh; return v << (-sh); }
static unsigned isqrt_u32(unsigned v) {
    if (v == 0) return 0;
    unsigned r = 0, b = 1u << 30;
    while (b > v) b >>= 2;
    while (b) { if (v >= r + b) { v -= r + b; r = (r >> 1) + b; } else r >>= 1; b >>= 2; }
    return r;
}

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

/* shift_idx: index into g_shift[] for this tensor.  Pass -1 to use
 * tm->base_s unchanged (used for tensors without a tunable shift,
 * but in our genome every tensor is tunable so this is just a safety
 * net). */
static void matvec(const TM *tm, int shift_idx, const int16_t *x,
                   int rows, int cols, int post_shift, int16_t *out) {
    int s = (shift_idx >= 0) ? g_shift[shift_idx] : tm->base_s;
    int total = s + post_shift;
    for (int r = 0; r < rows; r++) {
        const int8_t *row = tm->q8 + r * cols;
        int acc = 0;
        for (int c = 0; c < cols; c++) acc += (int)row[c] * (int)x[c];
        out[r] = (int16_t)sat16(sar32(acc, total));
    }
}
static void matvec_b(const TM *Wm, int shift_idx, const TM *bm,
                     const int16_t *x, int rows, int cols,
                     int post_shift, int16_t *out) {
    int s = (shift_idx >= 0) ? g_shift[shift_idx] : Wm->base_s;
    int total = s + post_shift;
    for (int r = 0; r < rows; r++) {
        const int8_t *row = Wm->q8 + r * cols;
        int acc = bm->q16[r];
        for (int c = 0; c < cols; c++) acc += (int)row[c] * (int)x[c];
        out[r] = (int16_t)sat16(sar32(acc, total));
    }
}
static void rms_norm(const int16_t *x, const TM *gain, int gain_idx,
                     int n, int16_t *out) {
    int s_g = (gain_idx >= 0) ? g_shift[gain_idx] : gain->base_s;
    int sum_sq = 0;
    for (int i = 0; i < n; i++) {
        int xs = ((int)x[i]) >> 4;
        sum_sq += xs * xs;
    }
    int mean_sq = sum_sq / n;
    if (mean_sq < 1) mean_sq = 1;
    unsigned rms = isqrt_u32((unsigned)mean_sq);
    if (rms < 1) rms = 1;
    unsigned inv = (1u << 19) / rms;
    if (inv > 32767) inv = 32767;
    for (int i = 0; i < n; i++) {
        int y_raw = (((int)x[i]) * (int)inv) >> 15;
        int y = (y_raw * (int)gain->q8[i]) >> s_g;
        out[i] = (int16_t)sat16(y);
    }
}
static void softmax_ws(const int *scores, int n, const int16_t *vals,
                       int hd, int16_t *out) {
    int sf[SL]; int max_sf = -2000000000;
    for (int i = 0; i < n; i++) { sf[i] = scores[i] >> 14; if (sf[i] > max_sf) max_sf = sf[i]; }
    uint8_t w[SL]; int w_sum = 0;
    for (int i = 0; i < n; i++) {
        int d = max_sf - sf[i]; if (d < 0) d = 0; if (d > 127) d = 127;
        w[i] = EXP_LUT[d]; w_sum += w[i];
    }
    if (w_sum == 0) w_sum = 1;
    for (int j = 0; j < hd; j++) {
        int acc = 0;
        for (int i = 0; i < n; i++) acc += (int)w[i] * (int)vals[i * hd + j];
        out[j] = (int16_t)sat16(acc / w_sum);
    }
}

/* Tensor index map for matvec calls.  These match the order used
 * in tensor_by_idx() / load_soul. */
static int idx_te(void)         { return 0; }
static int idx_pe(void)         { return 1; }
static int idx_n1(int L)        { return 2 + L * 10; }
static int idx_q (int L)        { return 3 + L * 10; }
static int idx_k (int L)        { return 4 + L * 10; }
static int idx_v (int L)        { return 5 + L * 10; }
static int idx_proj(int L)      { return 6 + L * 10; }
static int idx_n2(int L)        { return 7 + L * 10; }
static int idx_fc1w(int L)      { return 8 + L * 10; }
static int idx_fc1b(int L)      { return 9 + L * 10; }
static int idx_fc2w(int L)      { return 10 + L * 10; }
static int idx_fc2b(int L)      { return 11 + L * 10; }
static int idx_norm(void)       { return 22; }
static int idx_out(void)        { return 23; }

static int deshift(int v, int s) {
    int diff = ACT_SHIFT - s;
    if (diff >= 0) return v << diff;
    return v >> (-diff);
}

static int16_t H_buf [SL][ED];
static int16_t Q_all [SL][ED];
static int16_t K_all [SL][ED];
static int16_t V_all [SL][ED];
static int16_t Att_n [SL][ED];

static int forward_argmax(const int *ids, int T) {
    int s_te = g_shift[idx_te()], s_pe = g_shift[idx_pe()];
    for (int t = 0; t < T; t++) {
        int tok = ids[t];
        for (int d = 0; d < ED; d++) {
            int v = deshift(T_te.q8[tok * ED + d], s_te) +
                    deshift(T_pe.q8[t   * ED + d], s_pe);
            H_buf[t][d] = (int16_t)sat16(v);
        }
    }
    for (int L = 0; L < NL; L++) {
        Lyr *ly = &Lyrs[L];
        for (int t = 0; t < T; t++) {
            int16_t xn[ED];
            rms_norm(H_buf[t], &ly->n1, idx_n1(L), ED, xn);
            matvec(&ly->q, idx_q(L), xn, ED, ED, 1, Q_all[t]);
            matvec(&ly->k, idx_k(L), xn, ED, ED, 1, K_all[t]);
            matvec(&ly->v, idx_v(L), xn, ED, ED, 1, V_all[t]);
        }
        for (int tq = 0; tq < T; tq++) {
            for (int head = 0; head < NH; head++) {
                int off = head * HD; int n_keys = tq + 1;
                int scores[SL];
                int16_t v_head[SL * HD];
                for (int tk = 0; tk < n_keys; tk++) {
                    int s = 0;
                    for (int d = 0; d < HD; d++) s += (int)Q_all[tq][off+d] * (int)K_all[tk][off+d];
                    scores[tk] = s;
                    for (int d = 0; d < HD; d++) v_head[tk*HD + d] = V_all[tk][off+d];
                }
                int16_t out_head[HD];
                softmax_ws(scores, n_keys, v_head, HD, out_head);
                for (int d = 0; d < HD; d++) Att_n[tq][off+d] = out_head[d];
            }
        }
        for (int t = 0; t < T; t++) {
            int16_t att_proj[ED];
            matvec(&ly->proj, idx_proj(L), Att_n[t], ED, ED, 1, att_proj);
            for (int d = 0; d < ED; d++)
                H_buf[t][d] = (int16_t)sat16((int)H_buf[t][d] + (int)att_proj[d]);
        }
        for (int t = 0; t < T; t++) {
            int16_t yn[ED], z[FF], w2[ED];
            rms_norm(H_buf[t], &ly->n2, idx_n2(L), ED, yn);
            matvec_b(&ly->fc1_w, idx_fc1w(L), &ly->fc1_b, yn, FF, ED, 1, z);
            for (int i = 0; i < FF; i++) if (z[i] < 0) z[i] = 0;
            matvec_b(&ly->fc2_w, idx_fc2w(L), &ly->fc2_b, z, ED, FF, 1, w2);
            for (int d = 0; d < ED; d++)
                H_buf[t][d] = (int16_t)sat16((int)H_buf[t][d] + (int)w2[d]);
        }
    }
    int16_t y[ED], logits[VS];
    rms_norm(H_buf[T-1], &T_norm, idx_norm(), ED, y);
    matvec(&T_out, idx_out(), y, VS, ED, 0, logits);
    int best = 4, best_v = logits[4];
    for (int i = 5; i < VS; i++) if (logits[i] > best_v) { best_v = logits[i]; best = i; }
    return best;
}

/* Generate up to max_new tokens for a prompt, into a flat string. */
static void generate(const char *prompt, char *out, int out_cap, int max_new) {
    int ids[SL]; int n = 0;
    ids[n++] = SEP;
    int body[SL]; int bn = encode(prompt, body, SL - 2);
    for (int i = 0; i < bn && n < SL - 1; i++) ids[n++] = body[i];
    ids[n++] = SEP;
    int o = 0;
    for (int g = 0; g < max_new && n < SL; g++) {
        int tok = forward_argmax(ids, n);
        if (tok == PAD || tok == SEP || tok == END) break;
        int len = vocab_len[tok];
        if (o + len >= out_cap - 1) break;
        memcpy(out + o, vocab_str[tok], len);
        o += len;
        ids[n++] = tok;
    }
    out[o] = 0;
}

/* ── tests ──────────────────────────────────────────────────── */
typedef struct { char prompt[64]; char expected[64]; } TestCase;
static TestCase G_tests[64];
static int      G_n_tests;

static int load_tests(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); return -1; }
    char ln[256];
    G_n_tests = 0;
    while (fgets(ln, sizeof ln, f)) {
        size_t L = strlen(ln);
        while (L > 0 && (ln[L-1] == '\n' || ln[L-1] == '\r' || ln[L-1] == ' ')) ln[--L] = 0;
        if (L == 0 || ln[0] == '#') continue;
        char *sep = strstr(ln, "=>>");
        if (!sep) continue;
        *sep = 0;
        if (G_n_tests >= 64) break;
        TestCase *tc = &G_tests[G_n_tests++];
        strncpy(tc->prompt, ln, sizeof tc->prompt - 1);
        tc->prompt[sizeof tc->prompt - 1] = 0;
        strncpy(tc->expected, sep + 3, sizeof tc->expected - 1);
        tc->expected[sizeof tc->expected - 1] = 0;
    }
    fclose(f);
    return G_n_tests;
}

/* Score = max contiguous substring of `expected` found in `actual`,
 * case-insensitive.  Returns 0 if expected is empty. */
static int substr_overlap(const char *expected, const char *actual) {
    int el = (int)strlen(expected), al = (int)strlen(actual);
    if (el == 0 || al == 0) return 0;
    int best = 0;
    for (int len = el; len >= 1 && len > best; len--) {
        for (int i = 0; i + len <= el; i++) {
            for (int j = 0; j + len <= al; j++) {
                int k = 0;
                while (k < len) {
                    char a = expected[i+k], b = actual[j+k];
                    if (a >= 'A' && a <= 'Z') a += 32;
                    if (b >= 'A' && b <= 'Z') b += 32;
                    if (a != b) break;
                    k++;
                }
                if (k == len) { if (len > best) best = len; goto found; }
            }
        }
        found: ;
    }
    return best;
}

static int fitness(int max_new) {
    int score = 0;
    for (int i = 0; i < G_n_tests; i++) {
        char actual[256];
        generate(G_tests[i].prompt, actual, sizeof actual, max_new);
        int s = substr_overlap(G_tests[i].expected, actual);
        score += s;
    }
    return score;
}

/* ── GA ─────────────────────────────────────────────────────── */
typedef struct { int8_t delta[N_SHIFTS]; int score; } Indiv;

static unsigned G_rng = 1;
static unsigned rnd(void) {
    G_rng ^= G_rng << 13; G_rng ^= G_rng >> 17; G_rng ^= G_rng << 5;
    return G_rng;
}
static int rnd_range(int n) { return (int)(rnd() % (unsigned)n); }

static void apply_genome(const Indiv *g) {
    for (int i = 0; i < N_SHIFTS; i++) {
        int s = g_base[i] + g->delta[i];
        if (s < g_base[i] - 4) s = g_base[i] - 4;
        if (s > g_base[i] + 4) s = g_base[i] + 4;
        g_shift[i] = s;
    }
}

static void mutate(Indiv *g, int n_hits) {
    for (int h = 0; h < n_hits; h++) {
        int i = rnd_range(N_SHIFTS);
        int delta = (int)(rnd() % 3) - 1;    /* -1, 0, +1 */
        int v = g->delta[i] + delta;
        if (v < -4) v = -4;
        if (v >  4) v =  4;
        g->delta[i] = (int8_t)v;
    }
}

static void crossover(const Indiv *a, const Indiv *b, Indiv *out) {
    int cut = rnd_range(N_SHIFTS);
    for (int i = 0; i < N_SHIFTS; i++) {
        out->delta[i] = (i < cut) ? a->delta[i] : b->delta[i];
    }
}

static int cmp_indiv_desc(const void *aa, const void *bb) {
    const Indiv *a = (const Indiv *)aa, *b = (const Indiv *)bb;
    return b->score - a->score;
}


/* ── main ─────────────────────────────────────────────────── */
int main(int argc, char **argv) {
    const char *soul_path = "soul.bin";
    const char *tok_path  = "tokenizer.json";
    const char *tests_path = "soul_tests.txt";
    const char *out_path = "evolved.bin";
    int pop = 32;
    int gens = 50;
    int max_new = 16;
    unsigned seed = 42;

    for (int i = 1; i < argc; i++) {
        if      (strcmp(argv[i], "--soul")    == 0 && i+1 < argc) soul_path = argv[++i];
        else if (strcmp(argv[i], "--tok")     == 0 && i+1 < argc) tok_path  = argv[++i];
        else if (strcmp(argv[i], "--tokenizer") == 0 && i+1 < argc) tok_path = argv[++i];
        else if (strcmp(argv[i], "--tests")   == 0 && i+1 < argc) tests_path = argv[++i];
        else if (strcmp(argv[i], "--out")     == 0 && i+1 < argc) out_path = argv[++i];
        else if (strcmp(argv[i], "--pop")     == 0 && i+1 < argc) pop = atoi(argv[++i]);
        else if (strcmp(argv[i], "--gens")    == 0 && i+1 < argc) gens = atoi(argv[++i]);
        else if (strcmp(argv[i], "--max-new") == 0 && i+1 < argc) max_new = atoi(argv[++i]);
        else if (strcmp(argv[i], "--seed")    == 0 && i+1 < argc) seed = (unsigned)atoi(argv[++i]);
    }
    if (pop < 4) pop = 4;
    if (pop > 128) pop = 128;
    G_rng = seed ? seed : 1;

    init_exp_lut();
    if (load_soul(soul_path) < 0) return 1;
    if (load_tokenizer(tok_path) < 0) return 1;
    if (load_tests(tests_path) <= 0) {
        fprintf(stderr, "no tests loaded from %s\n", tests_path);
        return 1;
    }
    printf("seed soul: %s (%d B), %d tests, pop=%d, gens=%d, max_new=%d\n",
           soul_path, G_soul_n, G_n_tests, pop, gens, max_new);

    /* Baseline fitness with zero deltas. */
    Indiv zero;
    memset(&zero, 0, sizeof zero);
    apply_genome(&zero);
    zero.score = fitness(max_new);
    printf("baseline (no shifts): score=%d\n", zero.score);
    {
        char actual[256];
        for (int i = 0; i < G_n_tests; i++) {
            generate(G_tests[i].prompt, actual, sizeof actual, max_new);
            printf("  %-22s -> %s\n", G_tests[i].prompt, actual);
        }
    }

    Indiv *P = calloc(pop, sizeof(Indiv));
    Indiv *N = calloc(pop, sizeof(Indiv));
    Indiv  best = zero;

    /* Seed population: first individual = baseline (zeros), rest =
     * small random perturbations. */
    P[0] = zero;
    for (int i = 1; i < pop; i++) {
        memset(&P[i], 0, sizeof P[i]);
        mutate(&P[i], 2);
    }

    for (int g = 0; g < gens; g++) {
        for (int i = 0; i < pop; i++) {
            apply_genome(&P[i]);
            P[i].score = fitness(max_new);
            if (P[i].score > best.score) {
                best = P[i];
                printf("gen %3d: new best %d (delta sum=", g, best.score);
                int sum = 0;
                for (int k = 0; k < N_SHIFTS; k++) sum += best.delta[k] < 0 ? -best.delta[k] : best.delta[k];
                printf("%d)\n", sum);
            }
        }
        qsort(P, pop, sizeof(Indiv), cmp_indiv_desc);
        /* Keep top half, breed bottom half by tournament-2 crossover. */
        int keep = pop / 2;
        for (int i = 0; i < keep; i++) N[i] = P[i];
        for (int i = keep; i < pop; i++) {
            int a = rnd_range(keep), b = rnd_range(keep);
            int parent_a = P[a].score >= P[b].score ? a : b;
            int c = rnd_range(keep), d = rnd_range(keep);
            int parent_b = P[c].score >= P[d].score ? c : d;
            crossover(&P[parent_a], &P[parent_b], &N[i]);
            mutate(&N[i], 1 + rnd_range(2));
        }
        memcpy(P, N, pop * sizeof(Indiv));
    }

    /* Finalize: apply best genome and write evolved.bin. */
    apply_genome(&best);
    printf("\nfinal best score: %d (baseline was %d)\n", best.score, zero.score);
    {
        char actual[256];
        for (int i = 0; i < G_n_tests; i++) {
            generate(G_tests[i].prompt, actual, sizeof actual, max_new);
            printf("  %-22s -> %s\n", G_tests[i].prompt, actual);
        }
    }
    printf("\nwriting %s ... ", out_path);
    fflush(stdout);
    if (save_soul(out_path) == 0) printf("ok (%d B)\n", G_soul_n);
    else printf("FAILED\n");

    free(P); free(N);
    return 0;
}
