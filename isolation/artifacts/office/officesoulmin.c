/* officesoulmin.c — headless soul.  Linux x86_64.  No libc.
 *
 * Strip of officesoul.c: same int8 transformer, no Win95 chrome,
 * no BANK_* prompt blobs, no tdb, no run_shell, no run_soul TUI.
 * Just: read prompt from stdin (or argv), generate up to N tokens
 * with optional temperature sampling, write decoded tokens to
 * stdout.
 *
 * Architecture (unchanged from officesoul):
 *   VS=128, ED=32, NH=4, HD=8, FF=64, NL_LAY=2, SL=64.  ~27 K
 *   int8 params, Q8.8 activations.
 *
 * Build:
 *   cc -DTINY -std=c99 -Os -Wall -Wextra \
 *      -fno-stack-protector -fno-asynchronous-unwind-tables \
 *      -fno-unwind-tables -fno-builtin -ffreestanding \
 *      -ffunction-sections -fdata-sections \
 *      -nostdlib -nostartfiles -static \
 *      -Wl,--gc-sections -Wl,--build-id=none \
 *      -Wl,-z,noseparate-code -Wl,-z,common-page-size=512 -s \
 *      -o officesoulmin officesoulmin.c
 *
 * Use:
 *   echo "the cat sat" | ./officesoulmin
 *   ./officesoulmin --seed 42 --temp 192 --max 32 < prompt.txt
 *   ./officesoulmin "the cat sat"          # prompt as argv
 *
 * Flags:
 *   --seed  N   PRNG seed (default 0xdeadbeef).  Different seeds
 *               give different samples — this is the knob the
 *               64-agent ensemble varies per child.
 *   --temp  Q   temperature in Q8.8 (256 = 1.0; 0 = greedy argmax;
 *               128 = 0.5, peakier; 512 = 2.0, flatter).
 *   --max   N   max tokens to generate (1..63, default 24).
 *
 * Output: raw bytes of generated tokens.  No trailing newline.
 * Stops on PAD/SEP/END or after --max tokens. */

#include "soul_data.h"


/* ── syscalls ──────────────────────────────────────────── */
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
#define qu(c)        sys3(SYS_exit_group, (long)(c), 0, 0)


/* ── string + memory helpers ───────────────────────────── */
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


/* ── model architecture (matches officesoul.c) ─────────── */
#define VS         128
#define ED          32
#define NH           4
#define HD           8
#define FF          64
#define NL_LAY       2
#define SL          64
#define ACT_SHIFT    8

#define PAD 0
#define SEP 1
#define UNK 2
#define END 3


/* ── soul tensors ──────────────────────────────────────── */
typedef struct { const signed char *q; int s; } W8m;
typedef struct { const short        *q; int s; } W16m;

static W8m  M_te, M_pe;
static W8m  M_norm, M_out;
typedef struct {
    W8m  n1, q, k, v, proj, n2, fc1_w, fc2_w;
    W16m fc1_b, fc2_b;
} Layer;
static Layer Lyr[NL_LAY];

static int soul_off;
static int soul_u8 (void) { return SOUL_BIN_DATA[soul_off++]; }
static int soul_u16(void) {
    int lo = SOUL_BIN_DATA[soul_off++];
    int hi = SOUL_BIN_DATA[soul_off++];
    return lo | (hi << 8);
}
static int soul_i8 (void) {
    int v = SOUL_BIN_DATA[soul_off++];
    return v >= 128 ? v - 256 : v;
}
static void load_w8m(W8m *m, int rows, int cols) {
    soul_u8(); soul_u16(); soul_u16();
    int s = soul_i8();
    m->q = (const signed char *)(SOUL_BIN_DATA + soul_off);
    m->s = s;
    soul_off += rows * cols;
}
static void load_w16m(W16m *m, int n) {
    soul_u8(); soul_u16(); soul_u16();
    int s = soul_i8();
    m->q = (const short *)(SOUL_BIN_DATA + soul_off);
    m->s = s;
    soul_off += n * 2;
}
static void soul_open(void) {
    soul_off = 0;
    load_w8m(&M_te, VS, ED);
    load_w8m(&M_pe, SL, ED);
    for (int L = 0; L < NL_LAY; L++) {
        Layer *ly = &Lyr[L];
        load_w8m (&ly->n1,    ED, 1);
        load_w8m (&ly->q,     ED, ED);
        load_w8m (&ly->k,     ED, ED);
        load_w8m (&ly->v,     ED, ED);
        load_w8m (&ly->proj,  ED, ED);
        load_w8m (&ly->n2,    ED, 1);
        load_w8m (&ly->fc1_w, FF, ED);
        load_w16m(&ly->fc1_b, FF);
        load_w8m (&ly->fc2_w, ED, FF);
        load_w16m(&ly->fc2_b, ED);
    }
    load_w8m(&M_norm, ED, 1);
    load_w8m(&M_out,  VS, ED);
}


/* ── int helpers ───────────────────────────────────────── */
static int sat16(int v) {
    if (v >  32767) return  32767;
    if (v < -32768) return -32768;
    return v;
}
static int sar32(int v, int sh) {
    if (sh >= 0) return v >> sh;
    return v << (-sh);
}
static unsigned isqrt_u32(unsigned v) {
    if (v == 0) return 0;
    unsigned result = 0;
    unsigned bit = 1u << 30;
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

/* EXP_LUT[i] = round(255 * exp(-i / 16)) — matches numerics.py. */
static const unsigned char EXP_LUT[128] = {
    255, 240, 225, 212, 199, 187, 175, 165,
    155, 146, 137, 128, 121, 113, 107, 100,
     94,  88,  83,  78,  73,  69,  64,  60,
     57,  53,  50,  47,  44,  41,  39,  36,
     34,  32,  30,  28,  26,  25,  23,  22,
     21,  19,  18,  17,  16,  15,  14,  13,
     12,  12,  11,  10,  10,   9,   8,   8,
      8,   7,   7,   6,   6,   5,   5,   5,
      5,   4,   4,   4,   4,   3,   3,   3,
      3,   3,   3,   2,   2,   2,   2,   2,
      2,   2,   2,   2,   2,   1,   1,   1,
      1,   1,   1,   1,   1,   1,   1,   1,
      1,   1,   1,   1,   1,   1,   1,   1,
      1,   1,   1,   1,   1,   1,   1,   1,
      1,   1,   1,   1,   1,   1,   1,   1,
      1,   1,   1,   1,   1,   1,   1,   0,
};


/* ── inference primitives ──────────────────────────────── */
static int deshift(int v, int s) {
    int diff = ACT_SHIFT - s;
    if (diff >= 0) return v << diff;
    return v >> (-diff);
}
static void matvec(const W8m *Wm, const short *x, int rows, int cols,
                   int post_shift, short *out) {
    int total = Wm->s + post_shift;
    for (int r = 0; r < rows; r++) {
        const signed char *row = Wm->q + r * cols;
        int acc = 0;
        for (int c = 0; c < cols; c++) acc += (int)row[c] * (int)x[c];
        out[r] = (short)sat16(sar32(acc, total));
    }
}
static void matvec_bias16(const W8m *Wm, const W16m *bm, const short *x,
                          int rows, int cols, int post_shift, short *out) {
    int total = Wm->s + post_shift;
    for (int r = 0; r < rows; r++) {
        const signed char *row = Wm->q + r * cols;
        int acc = bm->q[r];
        for (int c = 0; c < cols; c++) acc += (int)row[c] * (int)x[c];
        out[r] = (short)sat16(sar32(acc, total));
    }
}
static void rms_norm(const short *x, const W8m *gain, int n, short *out) {
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
        int y = (y_raw * (int)gain->q[i]) >> gain->s;
        out[i] = (short)sat16(y);
    }
}
static void softmax_weighted_sum(const int *scores, int n,
                                 const short *vals, int hd, short *out) {
    int sf[SL];
    int max_sf = -2000000000;
    for (int i = 0; i < n; i++) {
        sf[i] = scores[i] >> 14;
        if (sf[i] > max_sf) max_sf = sf[i];
    }
    unsigned char w[SL];
    int w_sum = 0;
    for (int i = 0; i < n; i++) {
        int d = max_sf - sf[i];
        if (d < 0) d = 0;
        if (d > 127) d = 127;
        w[i] = EXP_LUT[d];
        w_sum += w[i];
    }
    if (w_sum == 0) w_sum = 1;
    for (int j = 0; j < hd; j++) {
        int acc = 0;
        for (int i = 0; i < n; i++) acc += (int)w[i] * (int)vals[i * hd + j];
        out[j] = (short)sat16(acc / w_sum);
    }
}


/* ── forward → fills logits[] ──────────────────────────── */
static short h_buf [SL][ED];
static short q_all [SL][ED];
static short k_all [SL][ED];
static short v_all [SL][ED];
static short att_n [SL][ED];

static void forward_logits(const int *ids, int T, short *logits) {
    for (int t = 0; t < T; t++) {
        int tok = ids[t];
        for (int d = 0; d < ED; d++) {
            int v = deshift(M_te.q[tok * ED + d], M_te.s) +
                    deshift(M_pe.q[t   * ED + d], M_pe.s);
            h_buf[t][d] = (short)sat16(v);
        }
    }
    for (int L = 0; L < NL_LAY; L++) {
        Layer *ly = &Lyr[L];
        for (int t = 0; t < T; t++) {
            short xn[ED];
            rms_norm(h_buf[t], &ly->n1, ED, xn);
            matvec(&ly->q, xn, ED, ED, 1, q_all[t]);
            matvec(&ly->k, xn, ED, ED, 1, k_all[t]);
            matvec(&ly->v, xn, ED, ED, 1, v_all[t]);
        }
        for (int tq = 0; tq < T; tq++) {
            for (int head = 0; head < NH; head++) {
                int off = head * HD;
                int n_keys = tq + 1;
                int scores[SL];
                short v_head[SL * HD];
                for (int tk = 0; tk < n_keys; tk++) {
                    int s = 0;
                    for (int d = 0; d < HD; d++) {
                        s += (int)q_all[tq][off + d] *
                             (int)k_all[tk][off + d];
                    }
                    scores[tk] = s;
                    for (int d = 0; d < HD; d++)
                        v_head[tk * HD + d] = v_all[tk][off + d];
                }
                short out_head[HD];
                softmax_weighted_sum(scores, n_keys, v_head, HD, out_head);
                for (int d = 0; d < HD; d++)
                    att_n[tq][off + d] = out_head[d];
            }
        }
        for (int t = 0; t < T; t++) {
            short att_proj[ED];
            matvec(&ly->proj, att_n[t], ED, ED, 1, att_proj);
            for (int d = 0; d < ED; d++)
                h_buf[t][d] = (short)sat16((int)h_buf[t][d] + (int)att_proj[d]);
        }
        for (int t = 0; t < T; t++) {
            short yn[ED], z[FF], w2[ED];
            rms_norm(h_buf[t], &ly->n2, ED, yn);
            matvec_bias16(&ly->fc1_w, &ly->fc1_b, yn, FF, ED, 1, z);
            for (int i = 0; i < FF; i++) if (z[i] < 0) z[i] = 0;
            matvec_bias16(&ly->fc2_w, &ly->fc2_b, z, ED, FF, 1, w2);
            for (int d = 0; d < ED; d++)
                h_buf[t][d] = (short)sat16((int)h_buf[t][d] + (int)w2[d]);
        }
    }
    short y[ED];
    rms_norm(h_buf[T - 1], &M_norm, ED, y);
    matvec(&M_out, y, VS, ED, 0, logits);
}


/* ── sampler ────────────────────────────────────────────── */
static unsigned long g_rng;

static unsigned int rng_next(void) {
    g_rng = g_rng * 6364136223846793005UL + 1442695040888963407UL;
    return (unsigned int)(g_rng >> 33);
}

/* Pick the next token from logits.
 *   temp_q8 == 0: greedy argmax (deterministic, ignores rng)
 *   temp_q8 >  0: softmax-sample via top-K=8 + EXP_LUT-weighted
 *                 cumulative draw.  Higher temp_q8 (Q8.8) = flatter
 *                 distribution.  Special tokens (PAD/SEP/UNK/END)
 *                 are excluded from the candidate set. */
static int sample_token(const short *logits, int temp_q8) {
    if (temp_q8 <= 0) {
        int best = 4, bv = logits[4];
        for (int i = 5; i < VS; i++)
            if (logits[i] > bv) { bv = logits[i]; best = i; }
        return best;
    }
    /* Top-K=8 by simple sorted insertion. */
    const int K = 8;
    int top_idx[8];
    int top_val[8];
    for (int i = 0; i < K; i++) { top_idx[i] = -1; top_val[i] = -32768; }
    for (int i = 4; i < VS; i++) {
        int v = logits[i];
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
    /* Build EXP_LUT weights with temperature.  d = (max - val) /
     * temp_scale, where temp_scale grows with temp_q8 so larger
     * temp = smaller d = flatter weights. */
    int max_v = top_val[0];
    int weights[8];
    int w_sum = 0;
    for (int i = 0; i < K; i++) {
        if (top_idx[i] < 0) { weights[i] = 0; continue; }
        int d_raw = max_v - top_val[i];
        /* temp_q8 = 256 → temp = 1.0 → divisor ~= 16
         * temp_q8 = 128 → temp = 0.5 → divisor  = 8  (peakier)
         * temp_q8 = 512 → temp = 2.0 → divisor  = 32 (flatter) */
        int divisor = temp_q8 >> 4;
        if (divisor < 1) divisor = 1;
        int d = d_raw / divisor;
        if (d < 0) d = 0;
        if (d > 127) d = 127;
        weights[i] = EXP_LUT[d];
        w_sum += weights[i];
    }
    if (w_sum == 0) return top_idx[0];
    int r = (int)(rng_next() % (unsigned)w_sum);
    int acc = 0;
    for (int i = 0; i < K; i++) {
        acc += weights[i];
        if (r < acc) return top_idx[i];
    }
    return top_idx[0];
}


/* ── tokenizer ─────────────────────────────────────────── */
static int vocab_lookup(const char *s, int len) {
    for (int i = 0; i < VS; i++) {
        if (VOCAB_LEN_TBL[i] != len) continue;
        const unsigned char *str = VOCAB_STR_BLOB + VOCAB_OFFSETS[i];
        int eq = 1;
        for (int j = 0; j < len; j++) {
            if (str[j] != (unsigned char)s[j]) { eq = 0; break; }
        }
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
    int temp_q8 = 0;        /* 0 = greedy, 256 = temp 1.0 */
    int max_new = 24;
    int ids_mode = 0;       /* --ids: output decimal token IDs */
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
                "officesoulmin — headless soul (port of officesoul)\n"
                "  echo 'prompt' | ./officesoulmin\n"
                "  ./officesoulmin [--seed N] [--temp Q] [--max N] [--ids] [PROMPT]\n"
                "    --seed N   PRNG seed (default 0xdeadbeef)\n"
                "    --temp Q   temperature in Q8.8: 0=greedy, 256=1.0\n"
                "    --max N    max generated tokens (default 24, max 63)\n"
                "    --ids      output space-separated decimal token IDs\n"
                "               instead of decoded bytes\n"
                "  default output: raw bytes, no trailing newline\n";
            wr(1, H, sizeof H - 1);
            return 0;
        } else if (argv[i][0] != '-') {
            argv_prompt = argv[i];
        }
    }
    if (max_new < 1)  max_new = 1;
    if (max_new > 63) max_new = 63;
    /* Mix the seed across all 64 bits so consecutive --seed values
     * (1, 2, 3, …) actually produce distinct streams.  Plain
     * `seed | 1` collapses adjacent even/odd pairs because the LCG
     * is deterministic from any given state. */
    {
        unsigned long s = seed;
        if (s == 0) s = 1;
        g_rng = s * 0x9E3779B97F4A7C15UL ^ (s << 32);
        if (g_rng == 0) g_rng = 1;
    }

    /* Acquire prompt: argv[i] takes priority; else slurp stdin. */
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
    /* Trim trailing newline from stdin so single-line shell input
     * doesn't introduce a bogus token at the end. */
    while (plen > 0 && (prompt_buf[plen - 1] == '\n'
                     || prompt_buf[plen - 1] == '\r')) plen--;
    prompt_buf[plen] = 0;

    soul_open();

    int ids[SL];
    int n = 0;
    ids[n++] = SEP;
    int body[SL];
    int bn = encode(prompt_buf, body, SL - 2);
    for (int i = 0; i < bn && n < SL - 1; i++) ids[n++] = body[i];
    ids[n++] = SEP;

    short logits[VS];
    for (int gen = 0; gen < max_new && n < SL; gen++) {
        forward_logits(ids, n, logits);
        int tok_id = sample_token(logits, temp_q8);
        if (tok_id == PAD || tok_id == SEP || tok_id == END) break;
        if (ids_mode) {
            char dec[16];
            int dn = 0;
            if (gen > 0) dec[dn++] = ' ';
            {
                char buf[12];
                int bn = 0;
                int v = tok_id;
                if (v == 0) buf[bn++] = '0';
                while (v) { buf[bn++] = '0' + (v % 10); v /= 10; }
                while (bn > 0) dec[dn++] = buf[--bn];
            }
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
