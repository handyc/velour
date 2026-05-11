/* officemangel.c — mangler of mandelbrot snapshots.
 *
 * Fork of officemandelshot.c.  Does the initial full-screen snapshot,
 * then N times:
 *   - pick a new random center / span / iter (same recipe as the
 *     parent program);
 *   - shrink horizontally + vertically by a random percentage;
 *   - paste at a random (col, row) on the screen, overwriting whatever
 *     was there.
 *
 * N comes from argv[1].  No argument → 10 mangels.
 * Exits after the last paste.
 *
 *     officemangel        # 1 full + 10 mangels
 *     officemangel 100    # 1 full + 100 mangels
 *
 * Build (alongside the other office forks):
 *     make officemangel
 * or manually:
 *     cc -DTINY -std=c99 -Os -fno-builtin -ffreestanding \
 *        -nostdlib -nostartfiles -static -Wl,--gc-sections -s \
 *        -o officemangel officemangel.c
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
static void ou(unsigned v) {                        /* 0..9999 */
    if (v >= 1000) { oc('0' + v/1000); v %= 1000;
                     oc('0' + v/100);  v %= 100;
                     oc('0' + v/10);   oc('0' + v%10); }
    else if (v >= 100) { oc('0' + v/100); v %= 100; oc('0' + v/10); oc('0' + v%10); }
    else if (v >= 10)  { oc('0' + v/10); oc('0' + v%10); }
    else oc('0' + v);
}

/* ── argv parsing (no libc) ────────────────────────────── */
static int atoi_(const char *s) {
    int v = 0;
    if (!s) return 0;
    while (*s == ' ' || *s == '\t') s++;
    while (*s >= '0' && *s <= '9') { v = v * 10 + (*s - '0'); s++; }
    return v;
}

/* ── RNG ──────────────────────────────────────────────── */
static unsigned long rng_state;
static unsigned long rng(void) {
    unsigned long x = rng_state;
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    rng_state = x;
    return x;
}

/* ── mandel ───────────────────────────────────────────── */
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
    double v = 1.0;
    if (e >= 0) while (e--) v *= 2.0;
    else        while (e++) v *= 0.5;
    return v;
}

static const double centers[][2] = {
    {-0.75,     0.10000 },
    {-1.25,     0.0     },
    {-0.16,     1.04    },
    {-0.7269,   0.1889  },
    { 0.275,    0.0     },
    {-0.55,     0.5641  },
    {-1.7493,   0.0     },
    {-0.70,     0.27015 },
    {-0.74543,  0.11301 },
    {-0.10109, -0.95628 },
    {-1.401155, 0.0     },
    {-0.39,     0.59    },
};
#define NCENTERS ((int)(sizeof centers / sizeof centers[0]))

/* Pick a random center + log-span + jitter.  Same recipe as
 * officemandelshot — kept inline here so the mangle loop can reroll
 * per shot cheaply. */
static void pick_view(double *Cx, double *Cy, double *Span, int *Iter) {
    int ci = (int)(rng() % (unsigned long)NCENTERS);
    *Cx = centers[ci][0];
    *Cy = centers[ci][1];
    int e = -(int)(rng() % 11);                     /* 0..-10 */
    double sp = pow2i(e);
    long jxr = (long)(rng() % 2048) - 1024;
    long jyr = (long)(rng() % 2048) - 1024;
    *Cx += ((double)jxr / 4096.0) * sp;
    *Cy += ((double)jyr / 4096.0) * sp;
    *Span = sp;
    int it = 192;
    double s = sp;
    while (s < 1.0 && it < 4096) { it += 64; s *= 2.0; }
    *Iter = it;
}

/* Render a block of half-block cells starting at (destCol, destRow)
 * (0-based).  Width/height in *cells*; one cell = 1 char wide × 2
 * mandel rows tall.  Uses absolute cursor moves per row so the block
 * can sit anywhere on the screen. */
static void render_block(int destCol, int destRow, int destW, int destH,
                         double Cx, double Cy, double Span, int Iter) {
    if (destW < 2 || destH < 1) return;
    int PW = destW;
    double s  = Span / PW;
    double ox = Cx - s * PW * 0.5;
    double oy = Cy - s * (destH * 2) * 0.5;
    for (int r = 0; r < destH; r++) {
        /* Cursor → 1-based (row, col) at the start of this strip. */
        os("\x1b[");
        ou((unsigned)(destRow + r + 1)); oc(';');
        ou((unsigned)(destCol + 1));     oc('H');
        int lf = -1, lb = -1;
        for (int c = 0; c < destW; c++) {
            int t = mandel(ox + c*s, oy + (2*r    )*s, Iter);
            int b = mandel(ox + c*s, oy + (2*r + 1)*s, Iter);
            if (t != lf) { os("\x1b[38;5;"); ou(t); oc('m'); lf = t; }
            if (b != lb) { os("\x1b[48;5;"); ou(b); oc('m'); lb = b; }
            oc(0xE2); oc(0x96); oc(0x80);
        }
        os("\x1b[0m");
    }
}

/* ── main ─────────────────────────────────────────────── */
static int W = 80, H = 24;

int main_c(int argc, char **argv) {
    struct ws ws = { 24, 80, 0, 0 };
    sys3(SYS_ioctl, 1, TIOCGWINSZ, (long)&ws);
    if (ws.col) W = ws.col;
    if (ws.row) H = ws.row;
    if (W > 240) W = 240;
    if (H >  80) H =  80;

    int N = 10;
    if (argc >= 2) {
        int v = atoi_(argv[1]);
        if (v > 0) N = v;
        if (N > 99999) N = 99999;
    }

    sys3(SYS_getrandom, (long)&rng_state, sizeof rng_state, 0);
    if (!rng_state) rng_state = 0x9E3779B97F4A7C15UL;

    /* DEC 2026 sync-output begin + clear screen + home. */
    os("\x1b[?2026h\x1b[2J\x1b[H");

    /* Initial full-screen shot. */
    {
        double Cx, Cy, Span; int Iter;
        pick_view(&Cx, &Cy, &Span, &Iter);
        render_block(0, 0, W, H, Cx, Cy, Span, Iter);
    }

    /* N mangels: each is a fresh view, shrunk + placed at random. */
    for (int k = 0; k < N; k++) {
        /* Shrink factors in [15%, 75%] of the screen per axis. */
        int wPct = 15 + (int)(rng() % 61);
        int hPct = 15 + (int)(rng() % 61);
        int dW = (W * wPct) / 100; if (dW < 4) dW = 4; if (dW > W) dW = W;
        int dH = (H * hPct) / 100; if (dH < 2) dH = 2; if (dH > H) dH = H;
        int cx = (W > dW) ? (int)(rng() % (unsigned long)(W - dW + 1)) : 0;
        int cy = (H > dH) ? (int)(rng() % (unsigned long)(H - dH + 1)) : 0;
        double Cx, Cy, Span; int Iter;
        pick_view(&Cx, &Cy, &Span, &Iter);
        render_block(cx, cy, dW, dH, Cx, Cy, Span, Iter);
    }

    /* Park cursor below the screen and end sync-output so the next
     * prompt lands cleanly and doesn't overwrite the bottom row. */
    os("\x1b[");
    ou((unsigned)H); oc(';'); oc('1'); oc('H');
    os("\x1b[0m\n\x1b[?2026l");
    oflush();
    return 0;
}

__asm__ (
    ".global _start\n"
    "_start:\n"
    "    movq (%rsp), %rdi\n"      /* argc → arg0 */
    "    leaq 8(%rsp), %rsi\n"     /* argv → arg1 */
    "    andq $-16, %rsp\n"
    "    call main_c\n"
    "    movl %eax, %edi\n"
    "    movl $231, %eax\n"
    "    syscall\n"
);
