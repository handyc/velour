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
#define SYS_ioctl     16
#define SYS_exit_group 231

#define rd(f, p, n)  sys3(SYS_read,  f, (long)(p), (long)(n))
#define wr(f, p, n)  sys3(SYS_write, f, (long)(p), (long)(n))
#define io(f, r, p)  sys3(SYS_ioctl, f, (long)(r), (long)(p))
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

int main_c(int argc, char **argv) {
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
