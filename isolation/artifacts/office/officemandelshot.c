/* officemandelshot.c — one-shot random Mandelbrot snapshot.
 *
 * Fork of officemandel.c that drops the interactive zoomer:
 *   - seeds an xorshift from getrandom(2);
 *   - picks a center from a curated list of "interesting" points
 *     (seahorse valley, antenna, mini-mandel, spirals, ...) and
 *     perturbs it by ±span/4;
 *   - picks a span as 2^e for e ∈ {-10..0} (so ~0.001..1.0);
 *   - renders one frame at terminal size and exits.
 *
 * Build (alongside the other office forks):
 *     make officemandelshot
 * or manually:
 *     cc -DTINY -std=c99 -Os -fno-builtin -ffreestanding \
 *        -nostdlib -nostartfiles -static -Wl,--gc-sections -s \
 *        -o officemandelshot officemandelshot.c
 *
 * No keyboard reads, no raw-mode toggle, no termios — just one full
 * paint into a 64 KB output buffer + a single write(2).
 */

typedef long  ssize_t;
typedef unsigned long size_t;

static long sys3(long n, long a, long b, long c) {
    long r;
    __asm__ volatile ("syscall" : "=a"(r) : "0"(n), "D"(a), "S"(b), "d"(c)
                      : "rcx", "r11", "memory");
    return r;
}
#define SYS_write      1
#define SYS_ioctl      16
#define SYS_getrandom  318
#define SYS_exit_group 231
#define TIOCGWINSZ     0x5413

struct ws { unsigned short row, col, x, y; };

/* ── buffered stdout ───────────────────────────────────── */
static char obuf[1 << 16];
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
static void ou(unsigned v) {                        /* 0..999 */
    if (v >= 100) { oc('0' + v/100); v %= 100; oc('0' + v/10); oc('0' + v%10); }
    else if (v >= 10) { oc('0' + v/10); oc('0' + v%10); }
    else oc('0' + v);
}

/* ── RNG ──────────────────────────────────────────────── */
static unsigned long rng_state;
static unsigned long rng(void) {
    /* xorshift64 — plenty of entropy for picking a center + perturb. */
    unsigned long x = rng_state;
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    rng_state = x;
    return x;
}

/* ── mandel + view ────────────────────────────────────── */
static int W = 80, H = 24;

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

static double pow2i(int e) {
    /* Integer power-of-two — avoids pulling in any libm.  e ∈ [-30, 30]. */
    double v = 1.0;
    if (e >= 0) while (e--) v *= 2.0;
    else        while (e++) v *= 0.5;
    return v;
}

/* Curated "interesting" centers — boundary points where the set's
 * filigree is dense at zoom.  Picked so a random log-span doesn't
 * land on solid black or featureless escape. */
static const double centers[][2] = {
    {-0.75,     0.10000 },     /* seahorse valley */
    {-1.25,     0.0     },     /* west antenna */
    {-0.16,     1.04    },     /* upper mini-mandel */
    {-0.7269,   0.1889  },     /* tendril spiral */
    { 0.275,    0.0     },     /* east bulb tip */
    {-0.55,     0.5641  },     /* julia-like upper mini */
    {-1.7493,   0.0     },     /* island chain */
    {-0.70,     0.27015 },     /* tendril hub */
    {-0.74543,  0.11301 },     /* deep seahorse */
    {-0.10109, -0.95628 },     /* south scroll */
    {-1.401155, 0.0     },     /* Feigenbaum point neighbourhood */
    {-0.39,     0.59    },     /* north filigree */
};
#define NCENTERS ((int)(sizeof centers / sizeof centers[0]))

int main_c(void) {
    /* Auto-fit to the terminal; cap at 240×80 so the output buffer
     * + the SGR runs comfortably fit inside obuf. */
    struct ws ws = { 24, 80, 0, 0 };
    sys3(SYS_ioctl, 1, TIOCGWINSZ, (long)&ws);
    if (ws.col) W = ws.col;
    if (ws.row) H = ws.row;
    if (W > 240) W = 240;
    if (H >  80) H =  80;

    /* Seed RNG.  getrandom can return short (we ask for 8 bytes), but
     * with flags=0 on a normal box it fills synchronously.  Fallback
     * to a fixed splitmix-style constant if the call fails. */
    sys3(SYS_getrandom, (long)&rng_state, sizeof rng_state, 0);
    if (!rng_state) rng_state = 0x9E3779B97F4A7C15UL;

    /* Pick a center + log-span. */
    int ci = (int)(rng() % (unsigned long)NCENTERS);
    double Cx = centers[ci][0];
    double Cy = centers[ci][1];
    int    e   = -(int)(rng() % 11);                  /* 0..-10 */
    double Span = pow2i(e);
    /* Perturb by ±Span/4 in each axis (signed 11-bit jitter). */
    long jxr = (long)(rng() % 2048) - 1024;
    long jyr = (long)(rng() % 2048) - 1024;
    Cx += ((double)jxr / 4096.0) * Span;
    Cy += ((double)jyr / 4096.0) * Span;

    /* Iter ramps with depth — same recipe as officemandel.c. */
    int Iter = 192;
    {
        double s = Span;
        while (s < 1.0 && Iter < 4096) { Iter += 64; s *= 2.0; }
    }

    int PW = W, PH = H * 2;
    double s  = Span / PW;
    double ox = Cx - s * PW * 0.5;
    double oy = Cy - s * PH * 0.5;

    /* DEC 2026 sync-output begin + clear + home — keeps the snapshot
     * from tearing if the terminal supports it; harmless if not. */
    os("\x1b[?2026h\x1b[2J\x1b[H");

    int lf = -1, lb = -1;
    for (int r = 0; r < H; r++) {
        for (int c = 0; c < W; c++) {
            int t = mandel(ox + c*s, oy + (2*r    )*s, Iter);
            int b = mandel(ox + c*s, oy + (2*r + 1)*s, Iter);
            if (t != lf) { os("\x1b[38;5;"); ou(t); oc('m'); lf = t; }
            if (b != lb) { os("\x1b[48;5;"); ou(b); oc('m'); lb = b; }
            oc(0xE2); oc(0x96); oc(0x80);     /* ▀ U+2580 upper half */
        }
        os("\x1b[0m\n");
        lf = lb = -1;
    }
    os("\x1b[?2026l");
    oflush();
    return 0;
}

__asm__ (
    ".global _start\n"
    "_start:\n"
    "    andq $-16, %rsp\n"
    "    call main_c\n"
    "    movl %eax, %edi\n"
    "    movl $231, %eax\n"
    "    syscall\n"
);
