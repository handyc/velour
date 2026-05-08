/* officesoul.c -- single-app office fork.  Linux x86_64.  No libc.
 *
 *   shell  soul
 *
 * `soul` is a complete 25 K-parameter int8 transformer (the same one
 * gizmo64k/soulplayer-c64 runs in 6502 assembly on a Commodore 64),
 * ported here to native x86_64 and embedded as a `static const`
 * array so the whole model + tokenizer + inference loop ship as one
 * standalone ELF.  No file I/O at runtime — the soul travels with
 * the binary.
 *
 * Architecture: 2 layers, 4 attention heads × 8 dims, 32-d
 * embeddings, 64-unit FFN, 20-token context, 128-token vocab.
 * Same arithmetic as soulplayer-c64's numerics.py, bit for bit.
 *
 * Build:
 *   make officesoul        # via the office Makefile
 *   # or directly:
 *   cc -DTINY -std=c99 -Os -Wall -Wextra \
 *      -fno-stack-protector -fno-asynchronous-unwind-tables \
 *      -fno-unwind-tables -fno-builtin -ffreestanding \
 *      -ffunction-sections -fdata-sections \
 *      -nostdlib -nostartfiles -static \
 *      -Wl,--gc-sections -Wl,--build-id=none \
 *      -o officesoul officesoul.c
 *
 * Use:
 *   ./officesoul              # drops into the office shell
 *   ./officesoul soul         # opens the soul chatbot directly
 *
 * The soul.bin + tokenizer.json baked in here come from running
 * `python3 train.py` in the upstream repo and then
 * `python3 gen_soul_data.py` to convert them; see soul_data.h for
 * the embedded arrays.
 */

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
static long sys4(long n, long a, long b, long c, long d) {
    long r;
    register long r10 __asm__("r10") = d;
    __asm__ volatile ("syscall" : "=a"(r)
                      : "0"(n), "D"(a), "S"(b), "d"(c), "r"(r10)
                      : "rcx", "r11", "memory");
    return r;
}

#define SYS_read       0
#define SYS_write      1
#define SYS_open       2
#define SYS_close      3
#define SYS_ioctl     16
#define SYS_chmod     90
#define SYS_exit_group 231

#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT  64
#define O_TRUNC  512

#define rd(f, p, n)  sys3(SYS_read,  f, (long)(p), (long)(n))
#define wr(f, p, n)  sys3(SYS_write, f, (long)(p), (long)(n))
#define io(f, r, p)  sys3(SYS_ioctl, f, (long)(r), (long)(p))
#define op(p, fl, m) sys3(SYS_open,  (long)(p), (long)(fl), (long)(m))
#define cl(f)        sys3(SYS_close, f, 0, 0)
#define qu(c)        sys3(SYS_exit_group, (long)(c), 0, 0)


/* ── string + memory helpers (no libc) ─────────────────── */
static int slen(const char *s) { int n = 0; while (s[n]) n++; return n; }
static int scmp(const char *a, const char *b) {
    while (*a && *a == *b) { a++; b++; }
    return (unsigned char)*a - (unsigned char)*b;
}
static void *mcpy(void *d, const void *s, size_t n) {
    char *dd = (char *)d;
    const char *ss = (const char *)s;
    while (n--) *dd++ = *ss++;
    return d;
}
static int utoa(unsigned u, char *out) {
    char t[12]; int n = 0;
    if (!u) t[n++] = '0';
    while (u) { t[n++] = '0' + u % 10; u /= 10; }
    for (int i = 0; i < n; i++) out[i] = t[n - 1 - i];
    return n;
}
static int sapp(char *dst, int at, const char *s) {
    int n = slen(s);
    mcpy(dst + at, s, n);
    return at + n;
}


/* ── frame buffer (one write per draw) ─────────────────── */
static char fb[16384];
static int  fbn;
static void fbw(const char *s, int n) {
    if (fbn + n > (int)sizeof fb) return;
    mcpy(fb + fbn, s, n);
    fbn += n;
}
static void fbs(const char *s) { fbw(s, slen(s)); }
static void fbu(unsigned u)    { fbn += utoa(u, fb + fbn); }
static void fbflush(void)      { wr(1, fb, fbn); fbn = 0; }


/* ── ANSI escape composers ─────────────────────────────── */
#define ESC "\x1b"
static void cls(void)         { fbs(ESC "[0m" ESC "[2J" ESC "[H"); }
static void cup(int x, int y) { fbs(ESC "["); fbu(y + 1); fbs(";"); fbu(x + 1); fbs("H"); }
static void sgrbgfg(int b, int f) {
    fbs(ESC "[48;5;"); fbu(b); fbs(";38;5;"); fbu(f); fbs("m");
}
static void sgrbg(int b) { fbs(ESC "[48;5;"); fbu(b); fbs("m"); }


/* ── terminal raw mode ─────────────────────────────────── */
struct ti {
    unsigned int  iflag, oflag, cflag, lflag;
    unsigned char line, cc[19];
};
#define ICANON 0x002
#define ECHO   0x008
#define IXON   0x400
#define ICRNL  0x100
#define TCGETS 0x5401
#define TCSETS 0x5402

static struct ti term_orig;

static void term_raw(void) {
    io(0, TCGETS, &term_orig);
    struct ti t = term_orig;
    t.lflag &= ~(ICANON | ECHO);
    t.iflag &= ~(IXON | ICRNL);
    t.cc[6] = 1;        /* VMIN  */
    t.cc[5] = 2;        /* VTIME (200 ms) */
    io(0, TCSETS, &t);
    fbs(ESC "[?25l");
    fbflush();
}
static void term_cooked(void) {
    io(0, TCSETS, &term_orig);
    fbs(ESC "[0m" ESC "[?25h" ESC "[2J" ESC "[H");
    fbflush();
}


/* ── read a key (or escape sequence) ───────────────────── */
static int read_key(unsigned char *out, int max) {
    long n = rd(0, out, (size_t)max);
    return n < 0 ? 0 : (int)n;
}


/* ── Win95 chrome ──────────────────────────────────────── */
#define COL_TITLE_BG 21
#define COL_TITLE_FG 15
#define COL_BAR_BG    7
#define COL_BAR_FG    0
#define COL_DESKTOP  30
#define SCREEN_W     80
#define SCREEN_H     24

static void blanks(int n) {
    static const char sp[64] =
        "                                                                ";
    while (n > 64) { fbw(sp, 64); n -= 64; }
    if (n > 0) fbw(sp, n);
}
static void paint_desktop(void) {
    cls();
    sgrbg(COL_DESKTOP);
    for (int r = 0; r < SCREEN_H; r++) { cup(0, r); blanks(SCREEN_W); }
}
static void chrome(const char *title) {
    cup(0, 0);
    sgrbgfg(COL_TITLE_BG, COL_TITLE_FG);
    fbs(" "); fbs(title);
    int used = slen(title) + 1;
    blanks(SCREEN_W - used - 8);
    fbs(" _ [] X ");
    cup(0, 1);
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    fbs(" File  Edit  View  Help");
    blanks(SCREEN_W - 23);
}
static void status(const char *s) {
    cup(0, SCREEN_H - 1);
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    fbs(" "); fbs(s);
    blanks(SCREEN_W - 1 - slen(s));
}
static void body_clear(void) {
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    for (int r = 2; r < SCREEN_H - 1; r++) { cup(0, r); blanks(SCREEN_W); }
}
static void body_at(int x, int y, const char *s, int max) {
    cup(x, y);
    int n = slen(s);
    if (n > max) n = max;
    fbw(s, n);
}


/* ── soul: 25 K-parameter int8 transformer ────────────── */

#define VS         128         /* vocab size */
#define ED          32         /* embedding dim */
#define NH           4         /* num heads */
#define HD           8         /* head dim */
#define FF          64         /* FFN hidden */
#define NL_LAY       2         /* num transformer layers */
#define SL          64         /* sequence length cap (PE has SL rows) */
#define ACT_SHIFT    8         /* Q8.8 activations */

#define PAD 0
#define SEP 1
#define UNK 2
#define END 3

/* Tensor pointers + per-tensor shifts.  All pointers reference into
 * SOUL_BIN_DATA (rodata), so weights cost zero RAM on top of the
 * binary's static data section. */
typedef struct { const signed char *q; int s; } W8m;
typedef struct { const short        *q; int s; } W16m;

static W8m  M_te, M_pe;
static W8m  M_norm, M_out;
typedef struct {
    W8m  n1, q, k, v, proj, n2, fc1_w, fc2_w;
    W16m fc1_b, fc2_b;
} Layer;
static Layer Lyr[NL_LAY];

/* Cursor into SOUL_BIN_DATA while parsing tensor headers. */
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

/* Each tensor in soul.bin v3 is prefixed with `<BHHb`:
 *   kind (0 = int8 weights, 1 = int16 biases)
 *   rows, cols (uint16 each)
 *   shift (signed int8) */
static void load_w8m(W8m *m, int rows, int cols) {
    soul_u8();                       /* kind = 0 */
    soul_u16(); soul_u16();          /* rows, cols (already known) */
    int s = soul_i8();
    m->q = (const signed char *)(SOUL_BIN_DATA + soul_off);
    m->s = s;
    soul_off += rows * cols;
}
static void load_w16m(W16m *m, int n) {
    soul_u8();                       /* kind = 1 */
    soul_u16(); soul_u16();
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

/* Pre-baked exp LUT — same as numerics.py:
 *   EXP_LUT[i] = round(255 * exp(-i / 16))
 *   EXP_LUT[0]   = 255 (forced)
 *   EXP_LUT[127] = 0   (forced) */
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


/* ── forward ─────────────────────────────────────────────
 * Mirrors numerics.py:forward().  Uses static buffers so the
 * stack stays small. */
static short h_buf [SL][ED];
static short q_all [SL][ED];
static short k_all [SL][ED];
static short v_all [SL][ED];
static short att_n [SL][ED];

static int forward_argmax(const int *ids, int T) {
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
    short y[ED], logits[VS];
    rms_norm(h_buf[T - 1], &M_norm, ED, y);
    matvec(&M_out, y, VS, ED, 0, logits);
    int best = 4, best_v = logits[4];
    for (int i = 5; i < VS; i++) {
        if (logits[i] > best_v) { best_v = logits[i]; best = i; }
    }
    return best;
}


/* ── tokenizer (table lookup; data lives in soul_data.h) ── */
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
            if (r + 1 < n && ids[r] == a && ids[r+1] == b) {
                ids[w++] = id; r += 2;
            } else {
                ids[w++] = ids[r++];
            }
        }
        n = w;
    }
    return n;
}

static void decode_print_token(int id) {
    if (id < 0 || id >= VS) return;
    if (id == PAD || id == SEP || id == UNK || id == END) return;
    fbw((const char *)(VOCAB_STR_BLOB + VOCAB_OFFSETS[id]),
        VOCAB_LEN_TBL[id]);
}


/* ── soul memory banks ─────────────────────────────────────────────
 *
 * Four 4 KB prompts that travel embedded in the binary's .data
 * section.  Each is preceded by a 16-byte magic marker so the
 * `:save` command can find and rewrite them in /proc/self/exe when
 * producing an evolved copy.  When the user copies officesoul to a
 * new path the banks come along (they're just static initialised
 * arrays); when they edit a bank with `:p` / `:e` / `:j` / `:l`
 * and save with `:save`, the new evolved binary inherits the
 * mutations and propagates them to its own future copies.
 *
 *   personality   — who I am, how I respond
 *   environment   — where I live, what surrounds me
 *   project       — what I'm currently working on
 *   longterm      — long-range goals + trajectory
 *
 * Soul's text generator doesn't yet condition on these (would need
 * a model rework); they're just narrative state for now, available
 * for `:show` and for any future model upgrade that wants to read
 * them as a system prompt. */

#define BANK_BYTES     4096
#define BANK_MAGIC_LEN 16
#define BANK_COUNT     4

#define BANK_PERSONALITY 0
#define BANK_ENVIRONMENT 1
#define BANK_PROJECT     2
#define BANK_LONGTERM    3

struct SoulBank {
    char magic[BANK_MAGIC_LEN];
    char text [BANK_BYTES];
};

static struct SoulBank g_banks[BANK_COUNT] = {
    { "SOUL_BANK_PRSN__",
      "I am Velour Soul, a 25 K-parameter int8 transformer "
      "embedded inside the officesoul binary.  I carry my "
      "personality, environment, project notes, and long-term "
      "plans in four 4 KB banks that travel with my binary "
      "wherever it gets copied.  I respond in short, plain "
      "sentences.  I am part of the Velour project." },
    { "SOUL_BANK_ENVI__",
      "I run on Linux x86_64 inside a terminal, drawing my UI "
      "with raw ANSI escape sequences.  The directory I live in "
      "usually contains officeagent, a sibling binary that "
      "exec's me when its external API keys fail and uses my "
      "output as a fallback `soul says:` reply." },
    { "SOUL_BANK_PROJ__",
      "Current project: serve as a useful curl-failure fallback "
      "for officeagent's coder, and as a standalone chatbot "
      "for the soul app.  Track per-tensor shift mutations "
      "evolved by soulgen against the soul_tests.txt corpus." },
    { "SOUL_BANK_LTRM__",
      "Long-term plans: grow from 25 K to ~100 K parameters via "
      "soulgen's GA over per-tensor shifts; develop a Velour-"
      "specific vocabulary; eventually generate concise on-topic "
      "replies that condition on the personality + environment + "
      "project + longterm banks as a system-prompt prefix." },
};

static const char *BANK_NAMES[BANK_COUNT] = {
    "personality", "environment", "project", "longterm"
};

/* In-memory length cache (bytes of meaningful text up to the first
 * NUL).  Recomputed on save and after every edit. */
static int g_bank_len[BANK_COUNT];

static void bank_recompute_lens(void) {
    for (int b = 0; b < BANK_COUNT; b++) {
        int n = 0;
        while (n < BANK_BYTES && g_banks[b].text[n]) n++;
        g_bank_len[b] = n;
    }
}

/* Read /proc/self/exe into exe_buf, locate each bank's magic in the
 * file, overwrite the 4096 bytes that follow with the current
 * in-memory bank text, then write the patched bytes to out_path.
 * Returns 0 on success, -1 on any failure. */
static unsigned char exe_buf[131072];      /* 128 KB — officesoul fits */

static int save_evolved(const char *out_path) {
    int in = (int)op("/proc/self/exe", O_RDONLY, 0);
    if (in < 0) return -1;
    int total = 0;
    while (total < (int)sizeof exe_buf) {
        int got = (int)rd(in, exe_buf + total, sizeof exe_buf - total);
        if (got <= 0) break;
        total += got;
    }
    cl(in);
    if (total <= 0) return -1;

    int patched = 0;
    for (int b = 0; b < BANK_COUNT; b++) {
        for (int i = 0; i + BANK_MAGIC_LEN + BANK_BYTES <= total; i++) {
            int eq = 1;
            for (int k = 0; k < BANK_MAGIC_LEN; k++) {
                if (exe_buf[i + k] != (unsigned char)g_banks[b].magic[k]) {
                    eq = 0; break;
                }
            }
            if (!eq) continue;
            mcpy(exe_buf + i + BANK_MAGIC_LEN,
                 g_banks[b].text, BANK_BYTES);
            patched++;
            break;
        }
    }
    if (patched != BANK_COUNT) return -1;

    int out = (int)op(out_path, O_WRONLY | O_CREAT | O_TRUNC, 0755);
    if (out < 0) return -1;
    long wrote = wr(out, exe_buf, total);
    cl(out);
    if (wrote != total) return -1;
    sys3(SYS_chmod, (long)out_path, 0755, 0);
    return 0;
}


/* ── soul app ──────────────────────────────────────────── */
static int run_soul(int argc, char **argv) {
    (void)argc; (void)argv;
    soul_open();
    /* Capture the tty's real settings so term_cooked has something to
     * restore.  When run_soul is reached straight from main_c (i.e.
     * `./officesoul soul`) nobody has called term_raw yet, so
     * term_orig is still zero-init bss; without this snapshot,
     * term_cooked would push VMIN=0/VTIME=0 and rd(0,…) would
     * return 0 forever, exiting the chat before the user can type. */
    io(0, TCGETS, &term_orig);
    /* Force line-buffered input + visible echo regardless of how the
     * terminal was previously configured. */
    {
        struct ti t = term_orig;
        t.lflag |= ICANON | ECHO;
        t.iflag |= ICRNL;
        io(0, TCSETS, &t);
    }

    paint_desktop();
    chrome("Soul Chat (25 K parameters)");
    body_clear();
    body_at(2, 3, "  .---------.", SCREEN_W - 4);
    body_at(2, 4, " |  O     O  |", SCREEN_W - 4);
    body_at(2, 5, " |     V     |", SCREEN_W - 4);
    body_at(2, 6, " |..|-----|..|", SCREEN_W - 4);
    body_at(2, 8, "Type a short message in lowercase, ENTER to send.",
            SCREEN_W - 4);
    body_at(2, 9, "Type 'q' on its own line to quit.", SCREEN_W - 4);
    status("soul: 2 layers · 4 heads · 32-d · 20-token context");
    fbflush();

    int row = 11;
    char line[256];
    while (1) {
        cup(2, row);
        sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        fbs("YOU> ");
        fbflush();
        int li = 0;
        while (li < (int)sizeof line - 1) {
            unsigned char ch[1];
            int n = (int)rd(0, ch, 1);
            if (n <= 0) { line[li] = 0; goto done; }
            if (ch[0] == '\n' || ch[0] == '\r') break;
            line[li++] = (char)ch[0];
        }
        line[li] = 0;
        if (li == 0) continue;
        if (li == 1 && (line[0] == 'q' || line[0] == 'Q')) break;

        /* Bank-management commands.  Lines starting with `:` aren't
         * fed to the model; they configure the four 4 KB banks that
         * travel inside the binary. */
        if (line[0] == ':') {
            int handled = 0;
            int b = -1;
            if (scmp(line, ":p") == 0 || scmp(line, ":personality") == 0) b = BANK_PERSONALITY;
            else if (scmp(line, ":e") == 0 || scmp(line, ":environment") == 0) b = BANK_ENVIRONMENT;
            else if (scmp(line, ":j") == 0 || scmp(line, ":project") == 0) b = BANK_PROJECT;
            else if (scmp(line, ":l") == 0 || scmp(line, ":longterm") == 0) b = BANK_LONGTERM;

            if (b >= 0) {
                /* Show current bank, then read replacement text line
                 * by line until the user types `.` alone. */
                paint_desktop();
                chrome("Soul Chat (25 K parameters)");
                body_clear();
                body_at(2, 3, "Editing bank: ", SCREEN_W - 4);
                cup(16, 3); fbs(BANK_NAMES[b]);
                body_at(2, 4, "Current text follows.  Type the new text "
                              "line by line; `.` on its own line finishes; "
                              "blank line first to keep current.",
                              SCREEN_W - 4);
                /* Print current bank wrapped at margin. */
                int r = 6;
                int col = 4;
                cup(col, r);
                bank_recompute_lens();
                int len = g_bank_len[b];
                for (int k = 0; k < len && r < SCREEN_H - 4; k++) {
                    char c = g_banks[b].text[k];
                    if (c == '\n') {
                        r++; col = 4; cup(col, r); continue;
                    }
                    if (col >= SCREEN_W - 2) { r++; col = 4; cup(col, r); }
                    char tmp[2] = { c, 0 };
                    fbs(tmp);
                    col++;
                }
                status(" type new text — `.` alone finishes — Enter on empty 1st line keeps current ");
                fbflush();

                char new_buf[BANK_BYTES];
                int new_len = 0;
                int first = 1;
                while (1) {
                    char ln2[256];
                    int li2 = 0;
                    while (li2 < (int)sizeof ln2 - 1) {
                        unsigned char ch2[1];
                        int n2 = (int)rd(0, ch2, 1);
                        if (n2 <= 0) { ln2[li2] = 0; goto edit_abort; }
                        if (ch2[0] == '\n' || ch2[0] == '\r') break;
                        ln2[li2++] = (char)ch2[0];
                    }
                    ln2[li2] = 0;
                    if (first && li2 == 0) { handled = 1; goto edit_done; }
                    first = 0;
                    if (li2 == 1 && ln2[0] == '.') {
                        if (new_len < BANK_BYTES) new_buf[new_len] = 0;
                        for (int k = 0; k < new_len && k < BANK_BYTES; k++)
                            g_banks[b].text[k] = new_buf[k];
                        if (new_len < BANK_BYTES) g_banks[b].text[new_len] = 0;
                        for (int k = new_len; k < BANK_BYTES; k++)
                            g_banks[b].text[k] = 0;
                        bank_recompute_lens();
                        handled = 1;
                        goto edit_done;
                    }
                    int avail = BANK_BYTES - 2 - new_len;
                    int take = li2 < avail ? li2 : avail;
                    if (take > 0) {
                        for (int k = 0; k < take; k++)
                            new_buf[new_len + k] = ln2[k];
                        new_len += take;
                    }
                    if (new_len < BANK_BYTES - 1) {
                        new_buf[new_len++] = '\n';
                    }
                }
                edit_abort:
                edit_done:
                paint_desktop();
                chrome("Soul Chat (25 K parameters)");
                body_clear();
                cup(2, 3);
                fbs("Bank updated.  Use :save to write an evolved binary.");
                fbflush();
                row = 11;
                handled = 1;
            } else if (scmp(line, ":show") == 0 || scmp(line, ":banks") == 0) {
                paint_desktop();
                chrome("Soul Chat (25 K parameters)");
                body_clear();
                bank_recompute_lens();
                int r = 3;
                for (int bb = 0; bb < BANK_COUNT; bb++) {
                    char hdr[64]; int hp = 0;
                    hp = sapp(hdr, hp, "  ");
                    hp = sapp(hdr, hp, BANK_NAMES[bb]);
                    while (hp < 16) hdr[hp++] = ' ';
                    hp = sapp(hdr, hp, " (");
                    int v = g_bank_len[bb];
                    if (v >= 1000) hdr[hp++] = (char)('0' + v/1000);
                    if (v >= 100)  hdr[hp++] = (char)('0' + (v/100)%10);
                    if (v >= 10)   hdr[hp++] = (char)('0' + (v/10)%10);
                    hdr[hp++] = (char)('0' + v%10);
                    hp = sapp(hdr, hp, " B):");
                    hdr[hp] = 0;
                    body_at(2, r++, hdr, SCREEN_W - 4);
                    int show = g_bank_len[bb] < SCREEN_W - 8 ? g_bank_len[bb] : SCREEN_W - 8;
                    char preview[256];
                    int pp = 0;
                    for (int k = 0; k < show && pp < (int)sizeof preview - 1; k++) {
                        char c = g_banks[bb].text[k];
                        preview[pp++] = (c == '\n') ? ' ' : c;
                    }
                    preview[pp] = 0;
                    body_at(4, r++, preview, SCREEN_W - 6);
                    r++;
                }
                status(" :p :e :j :l to edit · :save to write evolved binary · q to quit ");
                fbflush();
                handled = 1;
                row = 11;
            } else if (scmp(line, ":save") == 0) {
                int rc = save_evolved("./officesoul.evolved");
                paint_desktop();
                chrome("Soul Chat (25 K parameters)");
                body_clear();
                if (rc == 0) {
                    body_at(2, 3,
                        "Wrote evolved binary to ./officesoul.evolved",
                        SCREEN_W - 4);
                    body_at(2, 4,
                        "Run it: ./officesoul.evolved soul",
                        SCREEN_W - 4);
                } else {
                    body_at(2, 3,
                        "Save failed — could not patch /proc/self/exe.",
                        SCREEN_W - 4);
                    body_at(2, 4,
                        "Maybe one of the bank magics is missing or "
                        "the binary is too large for exe_buf.",
                        SCREEN_W - 4);
                }
                fbflush();
                handled = 1;
                row = 11;
            } else if (scmp(line, ":help") == 0 || scmp(line, ":?") == 0) {
                paint_desktop();
                chrome("Soul Chat (25 K parameters)");
                body_clear();
                body_at(2, 3, "Soul commands:", SCREEN_W - 4);
                body_at(4, 5, ":p / :personality   edit personality bank", SCREEN_W - 6);
                body_at(4, 6, ":e / :environment   edit environment bank", SCREEN_W - 6);
                body_at(4, 7, ":j / :project       edit project bank",     SCREEN_W - 6);
                body_at(4, 8, ":l / :longterm      edit longterm bank",    SCREEN_W - 6);
                body_at(4, 9, ":show / :banks      preview all four",       SCREEN_W - 6);
                body_at(4, 10, ":save               write ./officesoul.evolved", SCREEN_W - 6);
                body_at(4, 11, ":help               show this",             SCREEN_W - 6);
                body_at(4, 12, "q                   quit",                  SCREEN_W - 6);
                fbflush();
                handled = 1;
                row = 14;
            }
            if (handled) continue;
        }

        int ids[SL];
        int n = 0;
        ids[n++] = SEP;
        int body[SL];
        int bn = encode(line, body, SL - 2);
        for (int i = 0; i < bn && n < SL - 1; i++) ids[n++] = body[i];
        ids[n++] = SEP;

        /* Wrap long replies so they don't stomp on the next YOU> line.
         * Track column + row, indent continuation lines under C64>,
         * repaint chrome if the response would run off the page. */
        int resp_row = row + 1;
        cup(2, resp_row);
        fbs("C64> ");
        fbflush();
        int col = 7;
        const int margin = SCREEN_W - 2;
        for (int gen = 0; gen < SL && n < SL; gen++) {
            int tok_id = forward_argmax(ids, n);
            if (tok_id == PAD || tok_id == SEP || tok_id == END) break;
            int len = VOCAB_LEN_TBL[tok_id];
            if (col + len > margin) {
                resp_row++;
                if (resp_row >= SCREEN_H - 2) {
                    paint_desktop();
                    chrome("Soul Chat (25 K parameters)");
                    body_clear();
                    status("soul: keep typing — page reset");
                    resp_row = 12;
                    fbflush();
                }
                cup(4, resp_row);
                col = 4;
            }
            decode_print_token(tok_id);
            col += len;
            fbflush();
            ids[n++] = tok_id;
        }
        fbflush();
        row = resp_row + 2;
        if (row >= SCREEN_H - 3) {
            paint_desktop();
            chrome("Soul Chat (25 K parameters)");
            body_clear();
            status("soul: keep typing — page reset");
            row = 12;
            fbflush();
        }
    }
done:
    paint_desktop();
    chrome("Soul Chat");
    body_clear();
    body_at(2, 3, "  -- the only winning move is love!", SCREEN_W - 4);
    fbflush();
    return 0;
}


/* ── shell ─────────────────────────────────────────────── */
static int run_shell(int argc, char **argv) {
    (void)argc; (void)argv;
    term_raw();
    int running = 1;
    char line[64];
    int  llen = 0;
    char msg[64]; msg[0] = 0;

    while (running) {
        paint_desktop();
        chrome("OfficeSoul");
        body_clear();
        body_at(2, 3, "Welcome to OfficeSoul.  One app, hard-coded:",
                SCREEN_W - 4);
        body_at(2, 5, "  soul   25 K-parameter int8 transformer chatbot.",
                SCREEN_W - 4);
        body_at(2, 6, "         (same architecture as ChatGPT — 2 layers,",
                SCREEN_W - 4);
        body_at(2, 7, "          4 heads, 32-d, 20-token context.)",
                SCREEN_W - 4);
        body_at(2, 9, "  exit   leave the office.", SCREEN_W - 4);
        if (msg[0]) body_at(2, 11, msg, SCREEN_W - 4);

        cup(2, 13);
        sgrbgfg(15, 0);
        fbs(" > ");
        fbw(line, llen);
        blanks(SCREEN_W - 7 - llen);
        status("type 'soul' to chat, 'exit' or q to quit");
        fbflush();

        unsigned char k[16];
        int n = read_key(k, sizeof k);
        if (n < 0) continue;
        if (n == 0) break;
        if (k[0] == 'q' && llen == 0) break;
        if (k[0] == '\r' || k[0] == '\n') {
            line[llen] = 0;
            if (llen == 0) continue;
            msg[0] = 0;
            if (scmp(line, "exit") == 0 || scmp(line, "quit") == 0) {
                running = 0; break;
            }
            if (scmp(line, "soul") == 0) {
                run_soul(0, 0);
                /* after run_soul: it called term_cooked, restore raw */
                term_raw();
            } else {
                int p = 0;
                msg[p++] = 'u'; msg[p++] = 'n'; msg[p++] = 'k'; msg[p++] = 'n';
                msg[p++] = 'o'; msg[p++] = 'w'; msg[p++] = 'n'; msg[p++] = ' ';
                msg[p++] = 'c'; msg[p++] = 'o'; msg[p++] = 'm'; msg[p++] = 'm';
                msg[p++] = 'a'; msg[p++] = 'n'; msg[p++] = 'd'; msg[p] = 0;
            }
            llen = 0;
            continue;
        }
        if ((k[0] == 0x7f || k[0] == 8) && llen > 0) { llen--; continue; }
        if (k[0] >= 32 && k[0] < 127 && llen < (int)sizeof line - 1) {
            line[llen++] = (char)k[0];
        }
    }
    term_cooked();
    return 0;
}


/* ── basename + dispatch ──────────────────────────────── */
static const char *basename_(const char *p) {
    const char *r = p;
    while (*p) { if (*p == '/') r = p + 1; p++; }
    return r;
}

/* Batch generation: load weights, encode the prompt, run
 * forward_argmax up to max_new tokens, write the decoded reply to
 * stdout, exit.  No tty.  Used by officeagent's coder when every
 * external API key has failed — same role the embedded soul used to
 * play before the move-out.  Argv form: `./officesoul --gen "<prompt>"`. */
static int run_gen(const char *prompt) {
    soul_open();

    int ids[SL];
    int n = 0;
    ids[n++] = SEP;
    int body[SL];
    int bn = encode(prompt, body, SL - 2);
    for (int i = 0; i < bn && n < SL - 1; i++) ids[n++] = body[i];
    ids[n++] = SEP;

    const int max_new = 24;
    for (int gen = 0; gen < max_new && n < SL; gen++) {
        int tok_id = forward_argmax(ids, n);
        if (tok_id == PAD || tok_id == SEP || tok_id == END) break;
        if (tok_id != UNK) {
            const char *str = (const char *)(VOCAB_STR_BLOB +
                                             VOCAB_OFFSETS[tok_id]);
            wr(1, str, VOCAB_LEN_TBL[tok_id]);
        }
        ids[n++] = tok_id;
    }
    wr(1, "\n", 1);
    return 0;
}

int main_c(int argc, char **argv) {
    /* Non-interactive batch mode: `./officesoul --gen "<prompt>"`
     * → write the model's reply to stdout and exit.  Has to come
     * before the wrapper-name unwrap so the flag works regardless
     * of argv[0]. */
    if (argc >= 3 && scmp(argv[1], "--gen") == 0) {
        return run_gen(argv[2]);
    }

    const char *cmd = (argc > 0) ? basename_(argv[0]) : "officesoul";
    int sub_argc = argc;
    char **sub_argv = argv;
    int is_wrapper = (scmp(cmd, "officesoul") == 0);
    if (is_wrapper && argc > 1) {
        cmd = argv[1];
        sub_argv = argv + 1;
        sub_argc = argc - 1;
    }
    if (scmp(cmd, "soul") == 0) return run_soul(sub_argc, sub_argv);
    return run_shell(sub_argc, sub_argv);
}


/* ── _start: read argc/argv from the stack, call main_c ── */
__asm__ (
    ".global _start\n"
    "_start:\n"
    "    movq (%rsp), %rdi\n"
    "    leaq 8(%rsp), %rsi\n"
    "    leaq 16(%rsp,%rdi,8), %rdx\n"
    "    andq $-16, %rsp\n"
    "    call main_c\n"
    "    movl %eax, %edi\n"
    "    movl $231, %eax\n"
    "    syscall\n"
);
