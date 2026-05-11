/* officemangel6.c — live mangler that also exports random screen blocks.
 *
 * Fork of officemangel5.c.  Inherits the 4-base-colour truecolour
 * palette + dominant-slot transparency + 1-shot-per-second loop +
 * 'q' exit.  Adds: on every tick, after dropping a fresh mangel, a
 * random 64×64-cell block of the screen is exported to a file
 * `mangel-YYYYMMDD-HHMMSS.ans` in the current directory.  The file
 * holds the same truecolour SGR + half-block bytes used on-screen,
 * so `cat mangel-*.ans` in a truecolour terminal renders it back
 * exactly as it appeared.
 *
 * Because terminals can't be read, the program keeps its own shadow
 * buffer (`shadow[H][W][2][3]`, ≤113 KB BSS at the 240×80 max) of the
 * RGB value of every painted half-pixel.  render_block updates the
 * shadow as it writes; the export walker reads it back row by row.
 * Skipped (transparent) cells retain their prior shadow value, so a
 * mangel pasted on top of older art exports the composite correctly.
 *
 *     officemangel6       # one shot/sec until you press q,
 *                         # plus one .ans file written per tick
 *
 * Build:
 *     make officemangel6
 */

typedef long  ssize_t;
typedef unsigned long size_t;

static long sys3(long n, long a, long b, long c) {
    long r;
    __asm__ volatile ("syscall" : "=a"(r) : "0"(n), "D"(a), "S"(b), "d"(c)
                      : "rcx", "r11", "memory");
    return r;
}
#define SYS_read          0
#define SYS_write         1
#define SYS_open          2
#define SYS_close         3
#define SYS_ioctl        16
#define SYS_clock_gettime 228
#define SYS_getrandom    318
#define SYS_exit_group   231
#define TCGETS         0x5401
#define TCSETS         0x5402
#define TIOCGWINSZ     0x5413
/* open(2) flags */
#define O_WRONLY    1
#define O_CREAT     64
#define O_TRUNC     512

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

/* ── buffered output ────────────────────────────────────
 *
 * Default target is stdout (fd 1); export_random_block() flips it to
 * a freshly-open()d .ans file, drains, then flips it back so the
 * regular live render keeps painting the terminal.  Single shared
 * buffer + single set of emit routines — no duplicate machinery. */
static char obuf[1 << 16];
static int  olen;
static int  obuf_fd = 1;
static void oflush(void) {
    if (olen) sys3(SYS_write, obuf_fd, (long)obuf, olen);
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
/* Plain iter count.  Caller compares to Iter to detect "in set" and
 * routes the rest through the per-shot palette. */
static int mandel(double cx, double cy, int Iter) {
    double zx = 0, zy = 0, x2 = 0, y2 = 0;
    int i;
    for (i = 0; i < Iter && x2 + y2 < 4.0; i++) {
        zy = 2*zx*zy + cy;
        zx = x2 - y2 + cx;
        x2 = zx*zx; y2 = zy*zy;
    }
    return i;
}

/* Per-shot palette: 4 random RGB base colours stamped into a 256-entry
 * truecolour table.  Slots 0/64/128/192 are the 4 bases; the 252
 * entries between them are integer lerps along the four ring segments
 * b0→b1, b1→b2, b2→b3, b3→b0.  mult/offset spread iter counts across
 * the table without collapsing into bands. */
typedef struct {
    int           mult;
    int           offset;
    unsigned char rgb[256][3];
} Shot;

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

/* Pick a random center + log-span + jitter + per-shot Shot palette. */
static void pick_view(double *Cx, double *Cy, double *Span, int *Iter,
                      Shot *sh) {
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
    sh->mult   = PALETTE_MULTS[rng() % (unsigned long)NMULTS];
    sh->offset = (int)(rng() % 256);

    /* 4 random RGB bases.  No brightness floor on purpose — the
     * occasional very dim or very washed shot is part of the charm. */
    unsigned char base[4][3];
    for (int i = 0; i < 4; i++) {
        unsigned long w = rng();
        base[i][0] = (unsigned char)( w        & 0xff);
        base[i][1] = (unsigned char)((w >>  8) & 0xff);
        base[i][2] = (unsigned char)((w >> 16) & 0xff);
    }
    /* 4 circular ramps of 64 entries each.  Slot k*64 = base[k]; the
     * 63 entries that follow walk via integer lerp toward base[k+1]
     * (mod 4).  Total = 4 base + 252 derived = 256. */
    for (int k = 0; k < 4; k++) {
        const unsigned char *a = base[k];
        const unsigned char *b = base[(k + 1) & 3];
        for (int j = 0; j < 64; j++) {
            unsigned slot = (unsigned)(k * 64 + j);
            sh->rgb[slot][0] = (unsigned char)((a[0]*(63 - j) + b[0]*j) / 63);
            sh->rgb[slot][1] = (unsigned char)((a[1]*(63 - j) + b[1]*j) / 63);
            sh->rgb[slot][2] = (unsigned char)((a[2]*(63 - j) + b[2]*j) / 63);
        }
    }
}

/* Emit one truecolour SGR; role is "\x1b[38;2;" for fg, "\x1b[48;2;"
 * for bg.  slot < 0 means "in the set" → black. */
static void emit_truecolour(const char *role, int slot, const Shot *sh) {
    os(role);
    if (slot < 0) { oc('0'); oc(';'); oc('0'); oc(';'); oc('0'); }
    else {
        ou(sh->rgb[slot][0]); oc(';');
        ou(sh->rgb[slot][1]); oc(';');
        ou(sh->rgb[slot][2]);
    }
    oc('m');
}

/* Map an iter count to a palette slot (or -1 for "in the set"). */
static int slot_for_iter(int iter, int Iter, const Shot *sh) {
    if (iter == Iter) return -1;
    return (int)(((unsigned)iter * (unsigned)sh->mult
                 + (unsigned)sh->offset) & 0xff);
}

/* ── shadow buffer (mangel6) ─────────────────────────────
 *
 * Per-cell RGB of the top + bottom half-pixel as last painted on the
 * terminal.  Terminals can't be read back, so this is the only source
 * of truth the export walker has.  Sized for the maximum we ever
 * paint (240 cols × 80 rows); only the in-use prefix matters at
 * runtime.  Skipped (transparent) cells keep their prior value, so
 * a mangel over older art exports a faithful composite.
 *
 * Indexing: shadow[row * 240 + col][half][rgb], where half=0 is the
 * top half-pixel and half=1 is the bottom.  black == "in set" rendered. */
#define SHADOW_W 240
#define SHADOW_H 80
static unsigned char shadow[SHADOW_H * SHADOW_W][2][3];

static void shadow_set(int col, int row, int half, int slot, const Shot *sh) {
    if (col < 0 || col >= SHADOW_W || row < 0 || row >= SHADOW_H) return;
    unsigned char *p = shadow[row * SHADOW_W + col][half];
    if (slot < 0) { p[0] = p[1] = p[2] = 0; return; }
    p[0] = sh->rgb[slot][0];
    p[1] = sh->rgb[slot][1];
    p[2] = sh->rgb[slot][2];
}

/* Render a block of half-block cells starting at (destCol, destRow)
 * (0-based).  Width/height in *cells*; one cell = 1 char wide × 2
 * mandel rows tall.  Uses absolute cursor moves per row so the block
 * can sit anywhere on the screen.  Truecolour SGR (CSI 38;2;r;g;b m
 * + CSI 48;2;r;g;b m) — works on kitty/alacritty/wezterm/iTerm2/foot
 * /modern xterm.
 *
 * ev mangel5: pre-pass tallies slot frequency; the most populated
 * slot is the *transparent* slot.  Cells where both halves land on
 * that slot are skipped (emit CSI 1C only, leaving the underlying
 * pixels untouched) so the mangel becomes a colour-keyed cutout.
 *
 * ev mangel6: same render path also mirrors each painted half-pixel
 * into the shadow buffer; skipped cells leave shadow untouched. */
static int hist[257];      /* [0] = "in set" (slot -1), [1..256] = slots 0..255 */
static void render_block(int destCol, int destRow, int destW, int destH,
                         double Cx, double Cy, double Span, int Iter,
                         const Shot *sh) {
    if (destW < 2 || destH < 1) return;
    int PW = destW;
    double s  = Span / PW;
    double ox = Cx - s * PW * 0.5;
    double oy = Cy - s * (destH * 2) * 0.5;

    /* Pre-pass — slot histogram across the entire block. */
    for (int i = 0; i < 257; i++) hist[i] = 0;
    for (int r = 0; r < destH; r++) {
        for (int c = 0; c < destW; c++) {
            int iT = mandel(ox + c*s, oy + (2*r    )*s, Iter);
            int iB = mandel(ox + c*s, oy + (2*r + 1)*s, Iter);
            hist[slot_for_iter(iT, Iter, sh) + 1]++;
            hist[slot_for_iter(iB, Iter, sh) + 1]++;
        }
    }
    int maxIdx = 0;
    for (int i = 1; i < 257; i++) if (hist[i] > hist[maxIdx]) maxIdx = i;
    int transparent = maxIdx - 1;   /* -1 = "in set", else 0..255 */

    /* Render pass. */
    for (int r = 0; r < destH; r++) {
        os("\x1b[");
        ou((unsigned)(destRow + r + 1)); oc(';');
        ou((unsigned)(destCol + 1));     oc('H');
        int lf = -2, lb = -2;
        for (int c = 0; c < destW; c++) {
            int iT = mandel(ox + c*s, oy + (2*r    )*s, Iter);
            int iB = mandel(ox + c*s, oy + (2*r + 1)*s, Iter);
            int slotT = slot_for_iter(iT, Iter, sh);
            int slotB = slot_for_iter(iB, Iter, sh);
            if (slotT == transparent && slotB == transparent) {
                /* Both halves are the dominant slot → leave whatever
                 * was at (destCol+c, destRow+r) on screen untouched.
                 * Reset styling so prior FG/BG don't bleed into the
                 * cursor-only move (some terminals scroll-region the
                 * SGR state across CUF).  Shadow also stays as-is. */
                os("\x1b[0m\x1b[1C");
                lf = -2; lb = -2;
                continue;
            }
            if (slotT != lf) { emit_truecolour("\x1b[38;2;", slotT, sh); lf = slotT; }
            if (slotB != lb) { emit_truecolour("\x1b[48;2;", slotB, sh); lb = slotB; }
            oc(0xE2); oc(0x96); oc(0x80);
            /* Mirror this paint into the shadow buffer so the export
             * walker can read it back later. */
            shadow_set(destCol + c, destRow + r, 0, slotT, sh);
            shadow_set(destCol + c, destRow + r, 1, slotB, sh);
        }
        os("\x1b[0m");
    }
}

/* ── time + date formatting (mangel6) ────────────────────
 *
 * clock_gettime(CLOCK_REALTIME) gives whole seconds since the Unix
 * epoch; we then walk year/month/day arithmetic by subtracting
 * year-and-month-day counts directly.  No libc.  UTC only — local
 * tz offset would mean parsing /etc/localtime, well beyond budget. */
struct ts { long sec, nsec; };

static long now_unix(void) {
    struct ts t = { 0, 0 };
    sys3(SYS_clock_gettime, 0 /* CLOCK_REALTIME */, (long)&t, 0);
    return t.sec;
}

/* Write 15 characters: "YYYYMMDD-HHMMSS" + a terminating NUL at out[15]. */
static void fmt_datetime(long t, char *out) {
    long days = t / 86400;
    long sod  = t % 86400;
    int hh = (int)( sod / 3600);
    int mm = (int)((sod / 60) % 60);
    int ss = (int)( sod % 60);
    int year = 1970;
    for (;;) {
        int leap = (year % 4 == 0 && (year % 100 != 0 || year % 400 == 0));
        long ydays = leap ? 366 : 365;
        if (days < ydays) break;
        days -= ydays;
        year++;
    }
    int leap = (year % 4 == 0 && (year % 100 != 0 || year % 400 == 0));
    static const int mdays[12] = {31,28,31,30,31,30,31,31,30,31,30,31};
    int month = 0;
    for (; month < 12; month++) {
        int dm = mdays[month] + ((month == 1) ? leap : 0);
        if (days < dm) break;
        days -= dm;
    }
    int day = (int)days + 1;
    month++;
    out[ 0] = (char)('0' + (year / 1000) % 10);
    out[ 1] = (char)('0' + (year / 100 ) % 10);
    out[ 2] = (char)('0' + (year / 10  ) % 10);
    out[ 3] = (char)('0' +  year         % 10);
    out[ 4] = (char)('0' + month / 10);
    out[ 5] = (char)('0' + month % 10);
    out[ 6] = (char)('0' + day   / 10);
    out[ 7] = (char)('0' + day   % 10);
    out[ 8] = '-';
    out[ 9] = (char)('0' + hh / 10);
    out[10] = (char)('0' + hh % 10);
    out[11] = (char)('0' + mm / 10);
    out[12] = (char)('0' + mm % 10);
    out[13] = (char)('0' + ss / 10);
    out[14] = (char)('0' + ss % 10);
    out[15] = 0;
}

/* ── main ─────────────────────────────────────────────── */
static int W = 80, H = 24;

/* Export a random BLOCK_W × BLOCK_H cells from the shadow buffer to
 * `mangel-YYYYMMDD-HHMMSS.ans` in cwd.  Output format is identical
 * to what we write to stdout — truecolour FG+BG SGR + ▀ half-block,
 * one terminal-row per file-line, terminated with CSI 0m + LF.  So
 * `cat mangel-...ans` in a truecolour terminal renders it back. */
#define EXPORT_BLOCK 64
static void export_random_block(void) {
    int bw = EXPORT_BLOCK; if (bw > W) bw = W;
    int bh = EXPORT_BLOCK; if (bh > H) bh = H;
    int col0 = (W > bw) ? (int)(rng() % (unsigned long)(W - bw + 1)) : 0;
    int row0 = (H > bh) ? (int)(rng() % (unsigned long)(H - bh + 1)) : 0;

    /* Build the path.  fmt_datetime writes exactly 15 chars + NUL. */
    char path[40];
    int  p = 0;
    static const char prefix[] = "mangel-";
    for (int i = 0; prefix[i]; i++) path[p++] = prefix[i];
    fmt_datetime(now_unix(), path + p);
    p += 15;
    path[p++] = '.'; path[p++] = 'a'; path[p++] = 'n'; path[p++] = 's';
    path[p]   = 0;

    /* Re-use obuf for the file write; restore stdout target afterward. */
    oflush();                                       /* drain pending screen writes */
    long fd = sys3(SYS_open, (long)path,
                   O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return;
    obuf_fd = (int)fd;

    /* Reset SGR at the top so cat'ing a partial file doesn't inherit
     * shell colours. */
    os("\x1b[0m");
    for (int r = 0; r < bh; r++) {
        int lfR = -1, lfG = -1, lfB = -1;
        int lbR = -1, lbG = -1, lbB = -1;
        for (int c = 0; c < bw; c++) {
            unsigned char *t = shadow[(row0 + r) * SHADOW_W + (col0 + c)][0];
            unsigned char *b = shadow[(row0 + r) * SHADOW_W + (col0 + c)][1];
            if ((int)t[0] != lfR || (int)t[1] != lfG || (int)t[2] != lfB) {
                os("\x1b[38;2;");
                ou(t[0]); oc(';'); ou(t[1]); oc(';'); ou(t[2]); oc('m');
                lfR = t[0]; lfG = t[1]; lfB = t[2];
            }
            if ((int)b[0] != lbR || (int)b[1] != lbG || (int)b[2] != lbB) {
                os("\x1b[48;2;");
                ou(b[0]); oc(';'); ou(b[1]); oc(';'); ou(b[2]); oc('m');
                lbR = b[0]; lbG = b[1]; lbB = b[2];
            }
            oc(0xE2); oc(0x96); oc(0x80);
        }
        os("\x1b[0m\n");
    }
    oflush();
    sys3(SYS_close, fd, 0, 0);
    obuf_fd = 1;                                    /* back to stdout */
}

/* Drop one fresh mangel (rerolled view + palette) somewhere on screen.
 * Called once per tick from the main loop. */
static void drop_one_mangel(void) {
    int wPct = 15 + (int)(rng() % 61);
    int hPct = 15 + (int)(rng() % 61);
    int dW = (W * wPct) / 100; if (dW < 4) dW = 4; if (dW > W) dW = W;
    int dH = (H * hPct) / 100; if (dH < 2) dH = 2; if (dH > H) dH = H;
    int cx = (W > dW) ? (int)(rng() % (unsigned long)(W - dW + 1)) : 0;
    int cy = (H > dH) ? (int)(rng() % (unsigned long)(H - dH + 1)) : 0;
    double Cx, Cy, Span; int Iter;
    static Shot sh;
    pick_view(&Cx, &Cy, &Span, &Iter, &sh);
    render_block(cx, cy, dW, dH, Cx, Cy, Span, Iter, &sh);
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

    /* Initial full-screen shot (random 4-base-colour palette built in
     * pick_view → Shot).  Flushed before the loop so the first frame
     * lands immediately rather than waiting on tick 1. */
    {
        double Cx, Cy, Span; int Iter;
        static Shot sh;
        pick_view(&Cx, &Cy, &Span, &Iter, &sh);
        render_block(0, 0, W, H, Cx, Cy, Span, Iter, &sh);
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
        /* Then grab a random 64×64-cell slice of the shadow buffer
         * and stash it on disk as a fresh datestamped .ans file. */
        export_random_block();
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
