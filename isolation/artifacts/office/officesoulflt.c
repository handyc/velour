/* officesoulflt.c — float-precision soul inference, nostdlib.
 *
 * Sibling of officesoulmin.  Same I/O contract (read prompt from
 * stdin or argv, write generated tokens to stdout, support --seed
 * --temp --max --ids), but does forward-pass arithmetic in IEEE
 * float32 instead of int8 + per-tensor shifts.  Eliminates the
 * quantization mismatch we hit when training fresh souls — at the
 * cost of a larger binary (≈120 KB vs 33 KB).
 *
 * Includes soul_data_float.h: a header produced by bake_soul_float.py
 * that emits each tensor as a `static const float` array.
 *
 * sqrt: x86 SQRTSS via inline asm (no libm).
 * exp:  range-reduce x = n·ln2 + r, polynomial for exp(r), bit-hack
 *       2^n.  Accurate to ≈1e-6 — fine for softmax.
 */

#ifndef SOUL_HEADER
#define SOUL_HEADER "soul_data_float.h"
#endif
#include SOUL_HEADER

typedef long  ssize_t;
typedef unsigned long size_t;

static long sys3(long n, long a, long b, long c) {
    long r;
    __asm__ volatile ("syscall" : "=a"(r) : "0"(n), "D"(a), "S"(b), "d"(c)
                      : "rcx", "r11", "memory");
    return r;
}

#define SYS_read       0
#define SYS_write      1
#define SYS_exit_group 231

#define rd(f, p, n)  sys3(SYS_read,  f, (long)(p), (long)(n))
#define wr(f, p, n)  sys3(SYS_write, f, (long)(p), (long)(n))


/* ── string helpers ────────────────────────────────────── */
static int slen(const char *s) { int n = 0; while (s[n]) n++; return n; }
static int scmp(const char *a, const char *b) {
    while (*a && *a == *b) { a++; b++; }
    return (unsigned char)*a - (unsigned char)*b;
}
static void *mcpy(void *d, const void *s, size_t n) {
    char *dd = (char *)d; const char *ss = (const char *)s;
    while (n--) *dd++ = *ss++;
    return d;
}
static int atoi_(const char *s) {
    int sign = 1, n = 0;
    while (*s == ' ' || *s == '\t') s++;
    if (*s == '-') { sign = -1; s++; }
    else if (*s == '+') s++;
    while (*s >= '0' && *s <= '9') { n = n * 10 + (*s - '0'); s++; }
    return sign * n;
}


/* ── float helpers ─────────────────────────────────────── */
static float fsqrtf(float x) {
    float r;
    __asm__ ("sqrtss %1, %0" : "=x"(r) : "x"(x));
    return r;
}

/* exp(x) by range reduction + polynomial.  Clamps far-out values. */
static float fexpf(float x) {
    if (x > 80.0f)   return 5.5e34f;       /* effectively +∞ */
    if (x < -80.0f)  return 0.0f;
    /* x = n·ln2 + r, |r| ≤ ln2/2 */
    int n = (int)(x * 1.4426950408889634f + (x >= 0 ? 0.5f : -0.5f));
    float r = x - (float)n * 0.6931471805599453f;
    /* exp(r) Taylor at 0, 6 terms — accurate to ~1e-6 over |r|≤0.35 */
    float r2 = r * r;
    float r3 = r2 * r;
    float r4 = r2 * r2;
    float r5 = r4 * r;
    float exp_r = 1.0f + r + r2 * 0.5f
                + r3 * (1.0f / 6.0f)
                + r4 * (1.0f / 24.0f)
                + r5 * (1.0f / 120.0f);
    /* 2^n via IEEE float bit pattern: exp = n+127, mantissa = 0 */
    union { float f; int i; } u;
    u.i = (n + 127) << 23;
    return u.f * exp_r;
}


/* ── inference state ───────────────────────────────────── */
static float h_buf[SL][ED];
static float q_all[SL][ED];
static float k_all[SL][ED];
static float v_all[SL][ED];
static float att_n[SL][ED];

static void rms_norm(const float *x, const float *gain, int n, float *out) {
    float sum_sq = 0;
    for (int i = 0; i < n; i++) sum_sq += x[i] * x[i];
    float mean_sq = sum_sq / (float)n + 1e-6f;
    float rms = fsqrtf(mean_sq);
    for (int i = 0; i < n; i++) out[i] = x[i] / rms * gain[i];
}

static void matmul_w_x(const float *W, const float *x,
                       int rows, int cols, float *out) {
    /* out[r] = sum_c W[r,c] * x[c] */
    for (int r = 0; r < rows; r++) {
        const float *row = W + r * cols;
        float acc = 0.0f;
        for (int c = 0; c < cols; c++) acc += row[c] * x[c];
        out[r] = acc;
    }
}
static void matmul_w_x_b(const float *W, const float *b, const float *x,
                         int rows, int cols, float *out) {
    for (int r = 0; r < rows; r++) {
        const float *row = W + r * cols;
        float acc = b[r];
        for (int c = 0; c < cols; c++) acc += row[c] * x[c];
        out[r] = acc;
    }
}

/* Per-layer pointers indexed by L. */
static const float *L_N1[NL]   = { (const float *)W_N1_0,   (const float *)W_N1_1   };
static const float *L_QW[NL]   = { (const float *)W_QW_0,   (const float *)W_QW_1   };
static const float *L_KW[NL]   = { (const float *)W_KW_0,   (const float *)W_KW_1   };
static const float *L_VW[NL]   = { (const float *)W_VW_0,   (const float *)W_VW_1   };
static const float *L_PROJ[NL] = { (const float *)W_PROJ_0, (const float *)W_PROJ_1 };
static const float *L_N2[NL]   = { (const float *)W_N2_0,   (const float *)W_N2_1   };
static const float *L_FC1W[NL] = { (const float *)W_FC1W_0, (const float *)W_FC1W_1 };
static const float *L_FC1B[NL] = { (const float *)W_FC1B_0, (const float *)W_FC1B_1 };
static const float *L_FC2W[NL] = { (const float *)W_FC2W_0, (const float *)W_FC2W_1 };
static const float *L_FC2B[NL] = { (const float *)W_FC2B_0, (const float *)W_FC2B_1 };


static void forward_logits(const int *ids, int T, float *logits) {
    /* Embeddings. */
    for (int t = 0; t < T; t++) {
        int tok = ids[t];
        for (int d = 0; d < ED; d++) {
            h_buf[t][d] = ((const float *)W_TE)[tok * ED + d]
                        + ((const float *)W_PE)[t   * ED + d];
        }
    }
    for (int L = 0; L < NL; L++) {
        /* Attention: rms_norm → q/k/v → causal softmax → proj. */
        for (int t = 0; t < T; t++) {
            float xn[ED];
            rms_norm(h_buf[t], L_N1[L], ED, xn);
            matmul_w_x(L_QW[L], xn, ED, ED, q_all[t]);
            matmul_w_x(L_KW[L], xn, ED, ED, k_all[t]);
            matmul_w_x(L_VW[L], xn, ED, ED, v_all[t]);
        }
        for (int tq = 0; tq < T; tq++) {
            for (int head = 0; head < NH; head++) {
                int off = head * HD;
                int n_keys = tq + 1;
                float scores[SL];
                float max_s = -1e30f;
                for (int tk = 0; tk < n_keys; tk++) {
                    float s = 0.0f;
                    for (int d = 0; d < HD; d++)
                        s += q_all[tq][off + d] * k_all[tk][off + d];
                    scores[tk] = s;
                    if (s > max_s) max_s = s;
                }
                float w[SL];
                float w_sum = 0.0f;
                for (int tk = 0; tk < n_keys; tk++) {
                    w[tk] = fexpf(scores[tk] - max_s);
                    w_sum += w[tk];
                }
                for (int d = 0; d < HD; d++) {
                    float acc = 0.0f;
                    for (int tk = 0; tk < n_keys; tk++)
                        acc += w[tk] * v_all[tk][off + d];
                    att_n[tq][off + d] = acc / w_sum;
                }
            }
        }
        for (int t = 0; t < T; t++) {
            float att_proj[ED];
            matmul_w_x(L_PROJ[L], att_n[t], ED, ED, att_proj);
            for (int d = 0; d < ED; d++)
                h_buf[t][d] += att_proj[d];
        }
        /* FFN: rms_norm → fc1 + relu → fc2. */
        for (int t = 0; t < T; t++) {
            float yn[ED], z[FF], w2[ED];
            rms_norm(h_buf[t], L_N2[L], ED, yn);
            matmul_w_x_b(L_FC1W[L], L_FC1B[L], yn, FF, ED, z);
            for (int i = 0; i < FF; i++) if (z[i] < 0) z[i] = 0;
            matmul_w_x_b(L_FC2W[L], L_FC2B[L], z, ED, FF, w2);
            for (int d = 0; d < ED; d++) h_buf[t][d] += w2[d];
        }
    }
    float y[ED];
    rms_norm(h_buf[T - 1], (const float *)W_NORM, ED, y);
    matmul_w_x((const float *)W_OUT, y, VS, ED, logits);
}


/* ── sampling ──────────────────────────────────────────── */
static unsigned long g_rng = 1;

static unsigned int rng_next(void) {
    g_rng = g_rng * 6364136223846793005UL + 1442695040888963407UL;
    return (unsigned int)(g_rng >> 33);
}

static int sample_token(const float *logits, int temp_q8) {
    /* Skip special tokens 0..3. */
    if (temp_q8 <= 0) {
        int best = 4;
        float bv = logits[4];
        for (int i = 5; i < VS; i++)
            if (logits[i] > bv) { bv = logits[i]; best = i; }
        return best;
    }
    /* Top-K softmax sampling.  K=8, temp = temp_q8 / 256. */
    const int K = 8;
    int top_idx[8];
    float top_val[8];
    for (int i = 0; i < K; i++) { top_idx[i] = -1; top_val[i] = -1e30f; }
    for (int i = 4; i < VS; i++) {
        float v = logits[i];
        if (v <= top_val[K - 1]) continue;
        int pos = K - 1;
        while (pos > 0 && top_val[pos - 1] < v) {
            top_val[pos] = top_val[pos - 1];
            top_idx[pos] = top_idx[pos - 1];
            pos--;
        }
        top_val[pos] = v;
        top_idx[pos] = i;
    }
    float temp = (float)temp_q8 / 256.0f;
    if (temp < 1e-3f) temp = 1e-3f;
    float max_v = top_val[0];
    float w[8];
    float w_sum = 0.0f;
    for (int i = 0; i < K; i++) {
        if (top_idx[i] < 0) { w[i] = 0; continue; }
        w[i] = fexpf((top_val[i] - max_v) / temp);
        w_sum += w[i];
    }
    if (w_sum <= 0.0f) return top_idx[0];
    /* Sample: integer fraction of w_sum at 24-bit fixed point. */
    unsigned int r = rng_next() & 0xffffff;
    float r_f = ((float)r / 16777216.0f) * w_sum;
    float acc = 0.0f;
    for (int i = 0; i < K; i++) {
        acc += w[i];
        if (r_f < acc) return top_idx[i];
    }
    return top_idx[0];
}


/* ── tokenizer ─────────────────────────────────────────── */
#define PAD 0
#define SEP 1
#define UNK 2
#define END 3

static int vocab_lookup(const char *s, int len) {
    for (int i = 0; i < VS; i++) {
        if (VOCAB_LEN_TBL[i] != len) continue;
        const unsigned char *str = VOCAB_STR_BLOB + VOCAB_OFFSETS[i];
        int eq = 1;
        for (int j = 0; j < len; j++)
            if (str[j] != (unsigned char)s[j]) { eq = 0; break; }
        if (eq) return i;
    }
    return -1;
}

static int encode(const char *text, int *ids, int cap) {
    int n = 0;
    for (int i = 0; text[i] && n < cap; i++) {
        char c = text[i];
        if (c >= 'A' && c <= 'Z') c = (char)(c + 32);
        int id = vocab_lookup(&c, 1);
        if (id >= 0) ids[n++] = id;
    }
    for (int m = 0; m < MERGES_N; m++) {
        int a = MERGES_AB[m][0], b = MERGES_AB[m][1], id = MERGES_ID[m];
        int w = 0;
        for (int r = 0; r < n; ) {
            if (r + 1 < n && ids[r] == a && ids[r + 1] == b) {
                ids[w++] = id; r += 2;
            } else {
                ids[w++] = ids[r++];
            }
        }
        n = w;
    }
    return n;
}


/* ── main ──────────────────────────────────────────────── */
static char prompt_buf[4096];

int main_c(int argc, char **argv) {
    unsigned long seed = 0xdeadbeefUL;
    int temp_q8 = 0;
    int max_new = 24;
    int ids_mode = 0;
    const char *argv_prompt = 0;
    for (int i = 1; i < argc; i++) {
        if (scmp(argv[i], "--seed") == 0 && i + 1 < argc) {
            seed = (unsigned long)atoi_(argv[++i]);
        } else if (scmp(argv[i], "--temp") == 0 && i + 1 < argc) {
            temp_q8 = atoi_(argv[++i]);
        } else if (scmp(argv[i], "--max") == 0 && i + 1 < argc) {
            max_new = atoi_(argv[++i]);
        } else if (scmp(argv[i], "--ids") == 0) {
            ids_mode = 1;
        } else if (scmp(argv[i], "--help") == 0
                || scmp(argv[i], "-h") == 0) {
            static const char H[] =
                "officesoulflt — float soul (sibling of officesoulmin)\n"
                "  echo 'prompt' | ./officesoulflt\n"
                "  ./officesoulflt [--seed N] [--temp Q] [--max N] [--ids] [PROMPT]\n";
            wr(1, H, sizeof H - 1);
            return 0;
        } else if (argv[i][0] != '-') {
            argv_prompt = argv[i];
        }
    }
    if (max_new < 1)  max_new = 1;
    if (max_new > 63) max_new = 63;
    {
        unsigned long s = seed;
        if (s == 0) s = 1;
        g_rng = s * 0x9E3779B97F4A7C15UL ^ (s << 32);
        if (g_rng == 0) g_rng = 1;
    }

    int plen = 0;
    if (argv_prompt) {
        int n = slen(argv_prompt);
        if (n > (int)sizeof prompt_buf - 1) n = sizeof prompt_buf - 1;
        mcpy(prompt_buf, argv_prompt, n);
        plen = n;
    } else {
        long n;
        while (plen < (int)sizeof prompt_buf - 1
            && (n = rd(0, prompt_buf + plen,
                       sizeof prompt_buf - 1 - plen)) > 0) {
            plen += (int)n;
        }
    }
    while (plen > 0 && (prompt_buf[plen - 1] == '\n'
                     || prompt_buf[plen - 1] == '\r')) plen--;
    prompt_buf[plen] = 0;

    int ids[SL];
    int n = 0;
    ids[n++] = SEP;
    int body[SL];
    int bn = encode(prompt_buf, body, SL - 2);
    for (int i = 0; i < bn && n < SL - 1; i++) ids[n++] = body[i];
    ids[n++] = SEP;

    float logits[VS];
    for (int gen = 0; gen < max_new && n < SL; gen++) {
        forward_logits(ids, n, logits);
        int tok_id = sample_token(logits, temp_q8);
        if (tok_id == PAD || tok_id == SEP || tok_id == END) break;
        if (ids_mode) {
            char dec[16]; int dn = 0;
            if (gen > 0) dec[dn++] = ' ';
            char buf[12]; int bn2 = 0;
            int v = tok_id;
            if (v == 0) buf[bn2++] = '0';
            while (v) { buf[bn2++] = '0' + (v % 10); v /= 10; }
            while (bn2 > 0) dec[dn++] = buf[--bn2];
            wr(1, dec, dn);
        } else if (tok_id != UNK) {
            const char *str = (const char *)(VOCAB_STR_BLOB +
                                             VOCAB_OFFSETS[tok_id]);
            wr(1, str, VOCAB_LEN_TBL[tok_id]);
        }
        ids[n++] = tok_id;
    }
    if (ids_mode) wr(1, "\n", 1);
    return 0;
}


__asm__ (
    ".global _start\n"
    "_start:\n"
    "    movq (%rsp), %rdi\n"
    "    leaq 8(%rsp), %rsi\n"
    "    andq $-16, %rsp\n"
    "    call main_c\n"
    "    movl %eax, %edi\n"
    "    movl $231, %eax\n"
    "    syscall\n"
);
