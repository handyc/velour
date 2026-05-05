/* wnnr — Win95-style window in a terminal. Linux x86_64.
 *
 * Two build paths from one source:
 *
 *   cc wnnr.c -o wnnr             # easy mode, ~14 KB binary
 *                                 # (links libc; main() is the entry)
 *
 *   make                          # no-libc mode, ~1.5 KB binary
 *                                 # (raw syscalls, _start is the entry)
 *
 * Same Win95 visuals either way: royal-blue title bar, grey menu
 * bar. Arrow keys move the window. q quits.
 *
 * Pass -DTINY -nostdlib -nostartfiles to compile by hand into the
 * tiny variant; the Makefile does this automatically.
 */

/* ── syscalls ────────────────────────────────────────────── */
static long sys3(long n, long a, long b, long c) {
    long r;
    __asm__ volatile ("syscall"
        : "=a"(r) : "0"(n), "D"(a), "S"(b), "d"(c)
        : "rcx", "r11", "memory");
    return r;
}
#define wr(fd, p, n)  sys3(1,  fd, (long)(p), (long)(n))
#define rd(fd, p, n)  sys3(0,  fd, (long)(p), (long)(n))
#define io(fd, r, p)  sys3(16, fd, r, (long)(p))
#define qu(c)         sys3(231, c, 0, 0)

/* ── termios (minimal Linux x86_64 layout) ──────────────── */
struct ti {
    unsigned int  iflag, oflag, cflag, lflag;
    unsigned char line, cc[19];
};
#define ICANON 0x002
#define ECHO   0x008
#define TCGETS 0x5401
#define TCSETS 0x5402

/* ── tiny string helpers ────────────────────────────────── */
static int sl(const char *s) { int n = 0; while (s[n]) n++; return n; }
static void ws(const char *s) { wr(1, s, sl(s)); }

/* itoa: write decimal digits of u into out, return count. */
static int ut(unsigned u, char *out) {
    char t[12]; int n = 0;
    if (!u) t[n++] = '0';
    while (u) { t[n++] = '0' + u % 10; u /= 10; }
    for (int i = 0; i < n; i++) out[i] = t[n - 1 - i];
    return n;
}

/* ── output buffer (one frame coalesced, then one write) ─ */
static char buf[4096];
static int  blen;
static void bs(const char *s) {
    int n = sl(s);
    for (int i = 0; i < n; i++) buf[blen++] = s[i];
}
static void bu(unsigned u) { blen += ut(u, buf + blen); }
static void bflush(void)   { wr(1, buf, blen); blen = 0; }

/* ── ANSI escape composers ──────────────────────────────── */
static void cup(int x, int y) {            /* ESC[Y;XH */
    bs("\x1b["); bu(y + 1); bs(";"); bu(x + 1); bs("H");
}
static void sgrbg(int c) {                 /* ESC[48;5;Cm */
    bs("\x1b[48;5;"); bu(c); bs("m");
}
static void sgrbgfg(int b, int f) {        /* ESC[48;5;B;38;5;Fm */
    bs("\x1b[48;5;"); bu(b); bs(";38;5;"); bu(f); bs("m");
}

#define W   36
#define H   12

/* Pad src out to width w columns into the frame buffer. */
static void pad(const char *s, int w) {
    int n = sl(s);
    for (int i = 0; i < n && i < w; i++) buf[blen++] = s[i];
    for (int i = n; i < w; i++) buf[blen++] = ' ';
}

static void draw(int x, int y) {
    bs("\x1b[0m\x1b[2J");

    cup(x, y);     sgrbgfg(21, 15);
    pad(" wnnr - window         _ [] X ", W);

    cup(x, y + 1); sgrbgfg(7, 0);
    pad(" File  Edit  View  Help",        W);

    sgrbg(7);
    for (int j = 2; j < H; j++) {
        cup(x, y + j);
        for (int k = 0; k < W; k++) buf[blen++] = ' ';
    }
    bflush();
}

/* ── shared body ────────────────────────────────────────── */
static struct ti orig;

static void run(void) {
    io(0, TCGETS, &orig);
    struct ti t = orig;
    t.lflag &= ~(ICANON | ECHO);
    /* Non-canonical: wait for at least one byte, then accumulate up
     * to a 200 ms inter-byte gap. Lets ESC '[' 'A' arrive whole. */
    t.cc[6] = 1;   /* VMIN */
    t.cc[5] = 2;   /* VTIME (× 100 ms) */
    io(0, TCSETS, &t);
    ws("\x1b[?25l");

    int x = 5, y = 2;
    draw(x, y);

    unsigned char k[8];
    for (;;) {
        long n = rd(0, k, 8);
        if (n <= 0) break;
        if (k[0] == 'q') break;
        if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
            switch (k[2]) {
            case 'A': if (y > 0) y--; break;
            case 'B':           y++; break;
            case 'C':           x++; break;
            case 'D': if (x > 0) x--; break;
            }
            draw(x, y);
        }
    }

    io(0, TCSETS, &orig);
    ws("\x1b[0m\x1b[?25h\x1b[2J\x1b[H");
}


/* ── entry point ────────────────────────────────────────── */
#ifdef TINY
/* No-libc build: linker calls _start directly. Raw syscall to exit. */
__attribute__((noreturn))
void _start(void) {
    run();
    qu(0);
    __builtin_unreachable();
}
#else
/* Default build: libc provides crt0 and main is the entry. */
int main(void) {
    run();
    return 0;
}
#endif
