/* officemangel3.c — live mangler, paced + interactive.
 *
 * Fork of officemangel2.c.  Renders the initial random full-screen
 * shot (random palette, like its parent), then enters a one-mangel-
 * per-second loop until the user presses 'q' (or Ctrl-C).  No argv
 * count — the run length is decided live, by holding 'q'.
 *
 * Pacing is done in termios itself: VMIN=0 + VTIME=10 makes read(2)
 * block for at most 1 second, returning either the pressed byte or
 * an empty buffer.  No nanosleep, no poll — just the existing kernel
 * tty timer.
 *
 *     officemangel3       # streams a new shrunken paste every second
 *                         # until you press q
 *
 * Build:
 *     make officemangel3
 */

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
#define SYS_ioctl      16
#define SYS_getrandom  318
#define SYS_exit_group 231
#define TCGETS         0x5401
#define TCSETS         0x5402
#define TIOCGWINSZ     0x5413

struct ws { unsigned short row, col, x, y; };

/* termios subset — Linux struct termios layout used elsewhere in the
 * office tree.  cc[6] is VMIN, cc[5] is VTIME (decisecond timeout). */
struct ti { unsigned iflag, oflag, cflag, lflag;
            unsigned char line, cc[19]; };
static struct ti tio_orig;

/* Switch stdin to raw + 1-second blocking read.  ISIG off so Ctrl-C
 * comes through as byte 0x03; ECHO off so the 'q' keystroke doesn't
 * scribble into our cursor-positioned output. */
static void raw_1sec(void) {
    struct ti t;
    sys3(SYS_ioctl, 0, TCGETS, (long)&tio_orig);
    t = tio_orig;
    t.lflag &= ~0xBU;       /* ~(ISIG | ICANON | ECHO) */
    t.iflag &= ~0x500U;     /* ~(IXON  | ICRNL)        */
    t.cc[6] = 0;            /* VMIN  = 0 — return on timeout */
    t.cc[5] = 10;           /* VTIME = 10 deciseconds = 1 s */
    sys3(SYS_ioctl, 0, TCSETS, (long)&t);
}
static void cooked(void) {
    sys3(SYS_ioctl, 0, TCSETS, (long)&tio_orig);
}

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

/* ── RNG ──────────────────────────────────────────────── */
static unsigned long rng_state;
static unsigned long rng(void) {
    unsigned long x = rng_state;
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    rng_state = x;
    return x;
}

/* ── mandel ───────────────────────────────────────────── */
/* Iterate; then map iter→ANSI256-cube via the per-shot palette.
 * Black (the "stayed inside" case) is colour 0 regardless of palette,
 * so the body of the set always reads as the dark backdrop. */
static int mandel(double cx, double cy, int Iter, int mult, int offset) {
    double zx = 0, zy = 0, x2 = 0, y2 = 0;
    int i;
    for (i = 0; i < Iter && x2 + y2 < 4.0; i++) {
        zy = 2*zx*zy + cy;
        zx = x2 - y2 + cx;
        x2 = zx*zx; y2 = zy*zy;
    }
    if (i == Iter) return 0;
    return 16 + ((unsigned)(i * (unsigned)mult + (unsigned)offset) % 216);
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

/* Multipliers for the iter→colour map.  Picked to be small primes
 * coprime-ish with 216 (= 2³·3³); these spread an iter range across
 * the 6×6×6 ANSI cube without collapsing into 2-or-3-tone bands. */
static const unsigned char PALETTE_MULTS[] = {
    5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59,
};
#define NMULTS ((int)(sizeof PALETTE_MULTS / sizeof PALETTE_MULTS[0]))

/* Pick a random center + log-span + jitter + per-shot palette. */
static void pick_view(double *Cx, double *Cy, double *Span, int *Iter,
                      int *paletteMult, int *paletteOffset) {
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
    *paletteMult   = PALETTE_MULTS[rng() % (unsigned long)NMULTS];
    *paletteOffset = (int)(rng() % 216);
}

/* Render a block of half-block cells starting at (destCol, destRow)
 * (0-based).  Width/height in *cells*; one cell = 1 char wide × 2
 * mandel rows tall.  Uses absolute cursor moves per row so the block
 * can sit anywhere on the screen. */
static void render_block(int destCol, int destRow, int destW, int destH,
                         double Cx, double Cy, double Span, int Iter,
                         int paletteMult, int paletteOffset) {
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
            int t = mandel(ox + c*s, oy + (2*r    )*s, Iter,
                           paletteMult, paletteOffset);
            int b = mandel(ox + c*s, oy + (2*r + 1)*s, Iter,
                           paletteMult, paletteOffset);
            if (t != lf) { os("\x1b[38;5;"); ou(t); oc('m'); lf = t; }
            if (b != lb) { os("\x1b[48;5;"); ou(b); oc('m'); lb = b; }
            oc(0xE2); oc(0x96); oc(0x80);
        }
        os("\x1b[0m");
    }
}

/* ── main ─────────────────────────────────────────────── */
static int W = 80, H = 24;

/* Drop one fresh mangel (rerolled view + palette) somewhere on screen.
 * Called once per tick from the main loop. */
static void drop_one_mangel(void) {
    int wPct = 15 + (int)(rng() % 61);
    int hPct = 15 + (int)(rng() % 61);
    int dW = (W * wPct) / 100; if (dW < 4) dW = 4; if (dW > W) dW = W;
    int dH = (H * hPct) / 100; if (dH < 2) dH = 2; if (dH > H) dH = H;
    int cx = (W > dW) ? (int)(rng() % (unsigned long)(W - dW + 1)) : 0;
    int cy = (H > dH) ? (int)(rng() % (unsigned long)(H - dH + 1)) : 0;
    double Cx, Cy, Span; int Iter, pm, po;
    pick_view(&Cx, &Cy, &Span, &Iter, &pm, &po);
    render_block(cx, cy, dW, dH, Cx, Cy, Span, Iter, pm, po);
}

int main_c(void) {
    struct ws ws = { 24, 80, 0, 0 };
    sys3(SYS_ioctl, 1, TIOCGWINSZ, (long)&ws);
    if (ws.col) W = ws.col;
    if (ws.row) H = ws.row;
    if (W > 240) W = 240;
    if (H >  80) H =  80;

    sys3(SYS_getrandom, (long)&rng_state, sizeof rng_state, 0);
    if (!rng_state) rng_state = 0x9E3779B97F4A7C15UL;

    raw_1sec();
    /* Hide cursor + clear + home + sync-output begin. */
    os("\x1b[?25l\x1b[?2026h\x1b[2J\x1b[H");

    /* Initial full-screen shot (random palette inherited from
     * officemangel2 / pick_view).  Flushed before the loop so the
     * first frame lands immediately rather than waiting on tick 1. */
    {
        double Cx, Cy, Span; int Iter, pm, po;
        pick_view(&Cx, &Cy, &Span, &Iter, &pm, &po);
        render_block(0, 0, W, H, Cx, Cy, Span, Iter, pm, po);
    }
    /* End sync-output so the first frame is visible while we wait. */
    os("\x1b[?2026l");
    oflush();

    /* Live loop: every read(2) blocks for at most 1 s thanks to
     * VMIN=0 VTIME=10.  A returning byte that's 'q' / 'Q' / Ctrl-C
     * / EOT ends the run; anything else (including arrow keys etc.)
     * is ignored.  After every tick we drop one fresh mangel. */
    for (;;) {
        unsigned char k = 0;
        long n = sys3(SYS_read, 0, (long)&k, 1);
        if (n > 0 && (k == 'q' || k == 'Q' || k == 3 || k == 4)) break;
        /* Sync-output around each paste keeps it from tearing. */
        os("\x1b[?2026h");
        drop_one_mangel();
        os("\x1b[?2026l");
        oflush();
    }

    /* Park cursor below the screen, restore styling, show cursor,
     * cooked-mode tty.  Newline so the shell prompt lands on its own
     * line below the last row of the collage. */
    os("\x1b[");
    ou((unsigned)H); oc(';'); oc('1'); oc('H');
    os("\x1b[0m\x1b[?25h\n");
    oflush();
    cooked();
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
