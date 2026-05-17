/* app1_mandel.c — workspace App 1: one-shot Mandelbrot frame.
 *
 * Adapted from isolation/artifacts/office/officemandel.c — no raw
 * mode, no input loop, no animation.  Reads (cx, cy, span, iter) from
 * patched slots, renders a single half-block frame, exits.
 *
 * Each tick of the pact yields a different (cx, cy, span) preset so a
 * researcher running the same pact at the same tick sees the same
 * frame.
 */

typedef long          ssize_t;
typedef unsigned long size_t;
typedef unsigned int  uint32_t;

#define SYS_write       1
#define SYS_ioctl      16
#define SYS_exit_group 231
#define TIOCGWINSZ     0x5413

static long sys3(long n, long a, long b, long c) {
    long r;
    __asm__ volatile ("syscall" : "=a"(r) : "0"(n), "D"(a), "S"(b), "d"(c)
                      : "rcx", "r11", "memory");
    return r;
}

struct ws { unsigned short row, col, x, y; };

/* ── slots ─────────────────────────────────────────────── */
#define SLOT(name, id, n) \
    __attribute__((used, section(".rodata.workspace_slots"), aligned(8))) \
    static const volatile unsigned char name[8 + n] = \
        { 0xCA, 0xFE, 0xBA, 0xBE, 0x00, 0x00, 0x00, id,

SLOT(SLOT_CX,   0x11, 8)
        /* IEEE 754 double LE; default = -0.5 (whole-set centre) */
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xe0, 0xbf
};
SLOT(SLOT_CY,   0x12, 8)
        /* default = 0.0 */
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
};
SLOT(SLOT_SPAN, 0x13, 8)
        /* default = 3.0 */
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x08, 0x40
};
SLOT(SLOT_ITER, 0x14, 4)
        /* default iter cap = 192 */
        0xc0, 0x00, 0x00, 0x00
};
SLOT(SLOT_TERMW, 0x15, 4)
        /* default width = 100 chars */
        0x64, 0x00, 0x00, 0x00
};
SLOT(SLOT_TERMH, 0x16, 4)
        /* default height = 30 chars */
        0x1e, 0x00, 0x00, 0x00
};

/* ── byte-aligned reads of slot payloads ─────────────────── */
static double read_double(const volatile unsigned char *p) {
    double v;
    unsigned char *d = (unsigned char *)&v;
    for (int i = 0; i < 8; i++) d[i] = p[8 + i];
    return v;
}
static uint32_t read_u32(const volatile unsigned char *p) {
    uint32_t v;
    unsigned char *d = (unsigned char *)&v;
    for (int i = 0; i < 4; i++) d[i] = p[8 + i];
    return v;
}

/* ── buffered stdout ─────────────────────────────────────── */
static char obuf[1 << 15];
static int  olen;
static void oflush(void) {
    if (olen) sys3(SYS_write, 1, (long)obuf, olen);
    olen = 0;
}
static void oc(unsigned char c) {
    if (olen >= (int)sizeof obuf) oflush();
    obuf[olen++] = (char)c;
}
static void os(const char *s) { while (*s) oc((unsigned char)*s++); }
static void ou(unsigned v) {                    /* 0..999 */
    if (v >= 100) { oc('0' + v/100); v %= 100; oc('0' + v/10); oc('0' + v%10); }
    else if (v >= 10) { oc('0' + v/10); oc('0' + v%10); }
    else oc('0' + v);
}

/* ── mandelbrot ──────────────────────────────────────────── */
static int mandel(double cx, double cy, int Iter) {
    double zx = 0, zy = 0, x2 = 0, y2 = 0;
    int i;
    for (i = 0; i < Iter && x2 + y2 < 4.0; i++) {
        zy = 2*zx*zy + cy;
        zx = x2 - y2 + cx;
        x2 = zx*zx; y2 = zy*zy;
    }
    return i == Iter ? 0 : 16 + ((unsigned)(i * 13) % 216);
}

static void emit_sgr(const char *role, int c) {
    os(role); ou(c); oc('m');
}

int _start(void) {
    double Cx = read_double(SLOT_CX);
    double Cy = read_double(SLOT_CY);
    double Sp = read_double(SLOT_SPAN);
    int Iter  = (int)read_u32(SLOT_ITER);
    int W     = (int)read_u32(SLOT_TERMW);
    int H     = (int)read_u32(SLOT_TERMH);

    /* Auto-fit to the real terminal — but the slot values cap us. */
    struct ws ws = { 0, 0, 0, 0 };
    sys3(SYS_ioctl, 1, TIOCGWINSZ, (long)&ws);
    if (ws.col && ws.col < (unsigned short)W) W = ws.col;
    if (ws.row && ws.row < (unsigned short)H) H = ws.row;
    if (W < 4)   W = 4;
    if (H < 2)   H = 2;
    if (W > 240) W = 240;
    if (H > 80)  H = 80;
    if (Iter < 32)   Iter = 32;
    if (Iter > 4096) Iter = 4096;

    int PW = W, PH = H * 2;
    double s  = Sp / PW;
    double ox = Cx - s * PW * 0.5;
    double oy = Cy - s * PH * 0.5;

    int lf = -1, lb = -1;
    for (int r = 0; r < H; r++) {
        for (int c = 0; c < W; c++) {
            int t = mandel(ox + c*s, oy + (2*r    )*s, Iter);
            int b = mandel(ox + c*s, oy + (2*r + 1)*s, Iter);
            if (t != lf) { emit_sgr("\x1b[38;5;", t); lf = t; }
            if (b != lb) { emit_sgr("\x1b[48;5;", b); lb = b; }
            oc(0xE2); oc(0x96); oc(0x80);   /* ▀ U+2580 upper-half block */
        }
        os("\x1b[0m\n");
        lf = lb = -1;
    }
    oflush();
    sys3(SYS_exit_group, 0, 0, 0);
    return 0;
}
