/* officemandel.c — Mandelbrot zoomer in the office no-libc style.
 *
 *   wasd  / arrows   pan          +/=   zoom in
 *   r                reset         -/_   zoom out
 *   q / Ctrl-C       quit
 *
 * Half-block rendering (U+2580 ▀) packs two vertical pixels per cell
 * so coordinates stay square. Auto-fits to the real terminal.
 *
 * Build (alongside the other office forks):
 *     make officemandel
 * or manually:
 *     cc -DTINY -std=c99 -Os -fno-builtin -ffreestanding \
 *        -nostdlib -nostartfiles -static -Wl,--gc-sections -s \
 *        -o officemandel officemandel.c
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
#define SYS_exit_group 231

#define TCGETS     0x5401
#define TCSETS     0x5402
#define TIOCGWINSZ 0x5413

/* termios subset — matches Linux struct termios layout used elsewhere
 * in the office tree. ISIG=1, ICANON=2, ECHO=8; IXON=0x400, ICRNL=0x100. */
struct ti { unsigned iflag, oflag, cflag, lflag;
            unsigned char line, cc[19]; };
struct ws { unsigned short row, col, x, y; };

static struct ti tio_orig;

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

/* ── view ──────────────────────────────────────────────── */
static double Cx = -0.5, Cy = 0.0, Span = 3.0;
static int    W = 80, H = 24, Iter = 192;

/* Iter ramps as you zoom in so deep regions don't go solid black. */
static void retune(void) {
    Iter = 192;
    double s = Span;
    while (s < 1.0 && Iter < 4096) { Iter += 64; s *= 2.0; }
}

static int mandel(double cx, double cy) {
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

static void draw(void) {
    int PW = W, PH = H * 2;
    double s  = Span / PW;
    double ox = Cx - s * PW * 0.5;
    double oy = Cy - s * PH * 0.5;
    os("\x1b[?2026h\x1b[H");                    /* sync-output begin + home */
    int lf = -1, lb = -1;
    for (int r = 0; r < H; r++) {
        for (int c = 0; c < W; c++) {
            int t = mandel(ox + c*s, oy + (2*r    )*s);
            int b = mandel(ox + c*s, oy + (2*r + 1)*s);
            if (t != lf) { emit_sgr("\x1b[38;5;", t); lf = t; }
            if (b != lb) { emit_sgr("\x1b[48;5;", b); lb = b; }
            oc(0xE2); oc(0x96); oc(0x80);       /* ▀ U+2580 upper-half block */
        }
        os("\x1b[0m\n");
        lf = lb = -1;
    }
    os("\x1b[?2026l");                          /* sync-output end */
    oflush();
}

/* ── raw mode ──────────────────────────────────────────── */
static void raw(void) {
    struct ti t;
    sys3(SYS_ioctl, 0, TCGETS, (long)&tio_orig);
    t = tio_orig;
    t.lflag &= ~0xBU;       /* ~(ISIG | ICANON | ECHO)  → Ctrl-C is a byte */
    t.iflag &= ~0x500U;     /* ~(IXON  | ICRNL)         → Ctrl-S/CR pass  */
    t.cc[6] = 1; t.cc[5] = 0;                   /* VMIN=1 VTIME=0, blocking */
    sys3(SYS_ioctl, 0, TCSETS, (long)&t);
    os("\x1b[?25l\x1b[2J");
    oflush();
}
static void cooked(void) {
    sys3(SYS_ioctl, 0, TCSETS, (long)&tio_orig);
    os("\x1b[?25h\x1b[0m\n");
    oflush();
}

int main_c(void) {
    struct ws ws = { 24, 80, 0, 0 };
    sys3(SYS_ioctl, 1, TIOCGWINSZ, (long)&ws);
    if (ws.col) W = ws.col;
    if (ws.row) H = ws.row;
    if (W > 240) W = 240;
    if (H >  80) H =  80;

    raw();
    draw();

    unsigned char k[8];
    for (;;) {
        long n = sys3(SYS_read, 0, (long)k, 8);
        if (n <= 0) continue;
        int c = k[0];
        if (c == 0x1b && n >= 3 && k[1] == '[') {
            int a = k[2];
            c = a == 'A' ? 'w' : a == 'B' ? 's'
              : a == 'C' ? 'd' : a == 'D' ? 'a' : 0;
        }
        double pan = Span * 0.1;
        if (c == 'q' || c == 3 || c == 4) { cooked(); return 0; }
        else if (c == '+' || c == '=') { Span /= 1.5; retune(); }
        else if (c == '-' || c == '_') { Span *= 1.5; retune(); }
        else if (c == 'w') Cy -= pan;
        else if (c == 's') Cy += pan;
        else if (c == 'a') Cx -= pan;
        else if (c == 'd') Cx += pan;
        else if (c == 'r') { Cx = -0.5; Cy = 0; Span = 3.0; retune(); }
        else continue;
        draw();
    }
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
