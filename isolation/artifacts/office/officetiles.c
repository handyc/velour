/* officetiles.c — Wang tile generator + tessellator.  Linux x86_64.
 *                  No libc, sub-64KB target.
 *
 * Sibling to officesoul/officeagent.  Generates random Wang tile sets
 * for square (4-sided) and hexagonal (6-sided) tiles, brute-force
 * tests whether a set can tile a 16x16 region, and renders the
 * resulting tessellation in ANSI.  Tile sets persist to
 * `tiles.bin` in cwd.
 *
 * v1 scope: square Wang tiles (2 + 4 colors), tessellation backtracker,
 * mutation, save/load, `:dwell` stub that exec's ./officesoul --gen
 * with a description of the current tile set.  Hex tiles + CA wiring
 * live in follow-ups.
 *
 *   ./officetiles            # drops into the tile shell
 *
 * Hotkeys (in tile shell):
 *   g   generate a new random square Wang tile set
 *   m   mutate the current set (swap one tile)
 *   t   try to tessellate; renders if successful
 *   c   cycle color count (2 → 4 → 2)
 *   n   cycle tile count (8/12/16/20/24)
 *   s   save current set to tiles.bin
 *   l   load tiles.bin
 *   d   dwell — pass set description to ./officesoul --gen
 *   q   quit
 */

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
#define SYS_lseek      8
#define SYS_ioctl     16
#define SYS_fork      57
#define SYS_execve    59
#define SYS_wait4     61
#define SYS_dup2      33
#define SYS_time      201
#define SYS_getpid    39
#define SYS_exit_group 231

#define O_RDONLY 0
#define O_WRONLY 1
#define O_RDWR   2
#define O_CREAT  64
#define O_TRUNC  512

#define rd(f, p, n)     sys3(SYS_read,  f, (long)(p), (long)(n))
#define wr(f, p, n)     sys3(SYS_write, f, (long)(p), (long)(n))
#define io(f, r, p)     sys3(SYS_ioctl, f, (long)(r), (long)(p))
#define op(p, fl, m)    sys3(SYS_open,  (long)(p), (long)(fl), (long)(m))
#define cl(f)           sys3(SYS_close, f, 0, 0)
#define lseek_(f, o, w) sys3(SYS_lseek, f, (long)(o), (long)(w))
#define qu(c)           sys3(SYS_exit_group, (long)(c), 0, 0)
#define forkk()         sys3(SYS_fork, 0, 0, 0)
#define execvee(p,a,e)  sys3(SYS_execve, (long)(p), (long)(a), (long)(e))
#define wait4_(s)       sys4(SYS_wait4, -1, (long)(s), 0, 0)
#define dup2_(a, b)     sys3(SYS_dup2, a, b, 0)
#define time_()         sys3(SYS_time, 0, 0, 0)
#define getpid_()       sys3(SYS_getpid, 0, 0, 0)


/* ── string + memory helpers ───────────────────────────── */
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
static void *mset(void *d, int v, size_t n) {
    unsigned char *dd = (unsigned char *)d;
    while (n--) *dd++ = (unsigned char)v;
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


/* ── frame buffer ──────────────────────────────────────── */
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


/* ── ANSI ──────────────────────────────────────────────── */
#define ESC "\x1b"
static void cls(void)         { fbs(ESC "[0m" ESC "[2J" ESC "[H"); }
static void cup(int x, int y) { fbs(ESC "["); fbu(y + 1); fbs(";"); fbu(x + 1); fbs("H"); }
static void sgrbgfg(int b, int f) {
    fbs(ESC "[48;5;"); fbu(b); fbs(";38;5;"); fbu(f); fbs("m");
}
static void sgrbg(int b) { fbs(ESC "[48;5;"); fbu(b); fbs("m"); }
static void sgr0(void)   { fbs(ESC "[0m"); }


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
    t.cc[6] = 1;
    t.cc[5] = 2;
    io(0, TCSETS, &t);
    fbs(ESC "[?25l");
    fbflush();
}
static void term_cooked(void) {
    io(0, TCSETS, &term_orig);
    fbs(ESC "[0m" ESC "[?25h" ESC "[2J" ESC "[H");
    fbflush();
}

static int read_key(unsigned char *out, int max) {
    long n = rd(0, out, (size_t)max);
    return n < 0 ? 0 : (int)n;
}


/* ── chrome ────────────────────────────────────────────── */
#define COL_TITLE_BG 21
#define COL_TITLE_FG 15
#define COL_BAR_BG    7
#define COL_BAR_FG    0
#define COL_DESKTOP  30
#define SCREEN_W     80
#define SCREEN_H     24

static char **g_envp;

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


/* ── RNG (xorshift64) ──────────────────────────────────── */
static unsigned long long g_rng = 0;

static void rng_seed_if_unset(void) {
    if (g_rng) return;
    unsigned long long t = (unsigned long long)time_();
    unsigned long long p = (unsigned long long)getpid_();
    g_rng = (t * 6364136223846793005ULL) ^ (p * 1442695040888963407ULL);
    if (!g_rng) g_rng = 0xCAFEBABE12345678ULL;
}
static unsigned int rng_next(void) {
    unsigned long long x = g_rng;
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    g_rng = x;
    return (unsigned int)(x >> 32);
}
static int rng_range(int n) { return n > 0 ? (int)(rng_next() % (unsigned)n) : 0; }


/* ── square Wang tiles ─────────────────────────────────────────────
 *
 * A square Wang tile is a 4-tuple of edge colors (N, E, S, W).  A
 * tile set is a list of such tuples.  A tessellation places tiles in
 * row-major order such that adjacent edges match.  Aperiodicity is
 * not enforced in v1 — we just check that ANY tessellation of the
 * configured WxH region exists.
 *
 * v1 caps:
 *   - up to 24 tiles per set
 *   - up to 4 colors per edge
 *   - 16x12 tessellation grid (fits comfortably in body area)
 */

#define WSQ_MAX_TILES   24
#define WSQ_MAX_COLORS  4
#define WSQ_GRID_W      16
#define WSQ_GRID_H      12

struct WangSq {
    unsigned char n, e, s, w;
};

static struct WangSq g_set[WSQ_MAX_TILES];
static int           g_set_count = 12;
static int           g_set_colors = 2;
static unsigned char g_grid[WSQ_GRID_H][WSQ_GRID_W];   /* tile index per cell */
static int           g_grid_valid = 0;                  /* 1 if last tessellation succeeded */

static const int CYCLE_COUNTS[]  = { 8, 12, 16, 20, 24 };
static const int CYCLE_COLORS[]  = { 2, 3, 4 };
static int g_cycle_count_idx  = 1;   /* default 12 */
static int g_cycle_colors_idx = 0;   /* default 2  */

/* Generate a fresh random Wang tile set.  Each tile gets random
 * edge colors in [0, g_set_colors).  Duplicates are allowed in v1
 * but we try to avoid exact repeats by retrying up to 4 times per
 * tile. */
static void wsq_random(void) {
    rng_seed_if_unset();
    for (int t = 0; t < g_set_count; t++) {
        for (int retry = 0; retry < 4; retry++) {
            g_set[t].n = (unsigned char)rng_range(g_set_colors);
            g_set[t].e = (unsigned char)rng_range(g_set_colors);
            g_set[t].s = (unsigned char)rng_range(g_set_colors);
            g_set[t].w = (unsigned char)rng_range(g_set_colors);
            int dup = 0;
            for (int p = 0; p < t; p++) {
                if (g_set[p].n == g_set[t].n && g_set[p].e == g_set[t].e &&
                    g_set[p].s == g_set[t].s && g_set[p].w == g_set[t].w) {
                    dup = 1; break;
                }
            }
            if (!dup) break;
        }
    }
    g_grid_valid = 0;
}

/* Mutate exactly one tile by replacing it with a random new one. */
static void wsq_mutate(void) {
    rng_seed_if_unset();
    if (g_set_count <= 0) return;
    int t = rng_range(g_set_count);
    g_set[t].n = (unsigned char)rng_range(g_set_colors);
    g_set[t].e = (unsigned char)rng_range(g_set_colors);
    g_set[t].s = (unsigned char)rng_range(g_set_colors);
    g_set[t].w = (unsigned char)rng_range(g_set_colors);
    g_grid_valid = 0;
}

/* Backtracking tessellator.  At each cell, walk the tile list and try
 * each tile whose W-edge matches the previous cell's E-edge (if any)
 * and whose N-edge matches the cell-above's S-edge (if any).  A
 * shuffled tile-order makes successive runs explore different
 * tessellations from the same set.
 *
 * Capped at WSQ_TESS_BUDGET tile placements to keep failure cases
 * bounded — a non-tileable set bottoms out after a few thousand
 * misses, well below a millisecond. */
#define WSQ_TESS_BUDGET 200000

static int g_tess_attempts;
static unsigned char g_tile_order[WSQ_MAX_TILES];

static void wsq_shuffle_order(void) {
    for (int i = 0; i < g_set_count; i++) g_tile_order[i] = (unsigned char)i;
    for (int i = g_set_count - 1; i > 0; i--) {
        int j = rng_range(i + 1);
        unsigned char tmp = g_tile_order[i];
        g_tile_order[i] = g_tile_order[j];
        g_tile_order[j] = tmp;
    }
}

static int wsq_tile_fits(int t, int r, int c) {
    if (c > 0) {
        unsigned char left = g_grid[r][c - 1];
        if (g_set[left].e != g_set[t].w) return 0;
    }
    if (r > 0) {
        unsigned char above = g_grid[r - 1][c];
        if (g_set[above].s != g_set[t].n) return 0;
    }
    return 1;
}

static int wsq_solve(int r, int c) {
    if (++g_tess_attempts > WSQ_TESS_BUDGET) return 0;
    if (r >= WSQ_GRID_H) return 1;
    int nr = r, nc = c + 1;
    if (nc >= WSQ_GRID_W) { nr = r + 1; nc = 0; }
    for (int i = 0; i < g_set_count; i++) {
        int t = g_tile_order[i];
        if (!wsq_tile_fits(t, r, c)) continue;
        g_grid[r][c] = (unsigned char)t;
        if (wsq_solve(nr, nc)) return 1;
    }
    return 0;
}

static int wsq_tessellate(void) {
    rng_seed_if_unset();
    wsq_shuffle_order();
    g_tess_attempts = 0;
    mset(g_grid, 0, sizeof g_grid);
    int ok = wsq_solve(0, 0);
    g_grid_valid = ok;
    return ok;
}


/* ── render ────────────────────────────────────────────────────────
 *
 * Each tile is drawn as a 3×2 block: top-half coloured by N+E
 * average, bottom-half by S+W average.  In practice we just colour
 * the whole cell by the average of its 4 edges so the eye reads
 * "tile family" rather than individual edges.  A 16-wide grid at
 * 3 cols per cell = 48 cols, fits in SCREEN_W=80 with 16 margin.
 */
static const int EDGE_PALETTE[4] = {
    /* xterm-256: 4 well-separated swatches for up to 4 colors. */
    52,   /* dark red */
    22,   /* dark green */
    19,   /* dark blue */
    136,  /* mustard */
};

static void wsq_render(void) {
    int x0 = 6;
    int y0 = 4;
    for (int r = 0; r < WSQ_GRID_H; r++) {
        for (int sub = 0; sub < 2; sub++) {
            cup(x0, y0 + r * 2 + sub);
            for (int c = 0; c < WSQ_GRID_W; c++) {
                int t = g_grid[r][c];
                int top = (g_set[t].n + g_set[t].e) / 2;
                int bot = (g_set[t].s + g_set[t].w) / 2;
                int col = sub == 0 ? top : bot;
                if (col < 0) col = 0; if (col > 3) col = 3;
                sgrbg(EDGE_PALETTE[col]);
                fbs("   ");
            }
        }
    }
    sgr0();
}

static void render_tileset_glyph(int x, int y) {
    /* Show each tile as a mini 3-cell horizontal: [N|E|S] colour
     * preview, so the user can scan the full set at a glance.  Drawn
     * on the right margin while the grid lives on the left. */
    cup(x, y);
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    fbs("set: ");
    char nb[12]; int nn = utoa(g_set_count, nb);
    fbw(nb, nn);
    fbs("t × ");
    nn = utoa(g_set_colors, nb);
    fbw(nb, nn);
    fbs("c");

    for (int t = 0; t < g_set_count && y + 2 + t < SCREEN_H - 2; t++) {
        cup(x, y + 2 + t);
        sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        char buf[12];
        int p = utoa((unsigned)t, buf);
        if (p < 2) buf[p++] = ' ';
        buf[p++] = ':';
        buf[p++] = ' ';
        buf[p] = 0;
        fbs(buf);
        sgrbg(EDGE_PALETTE[g_set[t].n & 3]); fbs(" ");
        sgrbg(EDGE_PALETTE[g_set[t].e & 3]); fbs(" ");
        sgrbg(EDGE_PALETTE[g_set[t].s & 3]); fbs(" ");
        sgrbg(EDGE_PALETTE[g_set[t].w & 3]); fbs(" ");
        sgr0();
    }
}


/* ── persistence ───────────────────────────────────────────────────
 *
 * tiles.bin v1 layout:
 *   magic "OFCT1\0\0\0"  (8 B)
 *   uint32 set_count
 *   uint32 set_colors
 *   set_count × WangSq (4 B each)
 * Total 16 + 4*set_count bytes — trivial. */

static void store_u32(unsigned char *p, unsigned int v) {
    p[0] = (unsigned char)(v & 0xff);
    p[1] = (unsigned char)((v >> 8) & 0xff);
    p[2] = (unsigned char)((v >> 16) & 0xff);
    p[3] = (unsigned char)((v >> 24) & 0xff);
}
static unsigned int load_u32(const unsigned char *p) {
    return (unsigned int)p[0] | ((unsigned int)p[1] << 8) |
           ((unsigned int)p[2] << 16) | ((unsigned int)p[3] << 24);
}

static int wsq_save(const char *path) {
    int fd = (int)op(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return -1;
    unsigned char hdr[16];
    mset(hdr, 0, 16);
    mcpy(hdr, "OFCT1", 5);
    store_u32(hdr + 8, (unsigned)g_set_count);
    store_u32(hdr + 12, (unsigned)g_set_colors);
    wr(fd, hdr, 16);
    wr(fd, g_set, sizeof(struct WangSq) * (size_t)g_set_count);
    cl(fd);
    return 0;
}

static int wsq_load(const char *path) {
    int fd = (int)op(path, O_RDONLY, 0);
    if (fd < 0) return -1;
    unsigned char hdr[16];
    int n = (int)rd(fd, hdr, 16);
    if (n != 16 || hdr[0] != 'O' || hdr[1] != 'F' || hdr[2] != 'C' ||
        hdr[3] != 'T' || hdr[4] != '1') {
        cl(fd); return -1;
    }
    unsigned int cnt = load_u32(hdr + 8);
    unsigned int cols = load_u32(hdr + 12);
    if (cnt > WSQ_MAX_TILES || cols > WSQ_MAX_COLORS || cols < 1) {
        cl(fd); return -1;
    }
    g_set_count = (int)cnt;
    g_set_colors = (int)cols;
    rd(fd, g_set, sizeof(struct WangSq) * (size_t)cnt);
    cl(fd);
    g_grid_valid = 0;
    return 0;
}


/* ── dwell ─────────────────────────────────────────────────────────
 * Pass a short text description of the current tile set to
 * ./officesoul --gen and capture the reply.  Output displayed in a
 * panel below the tessellation.  No file mounts, no IPC magic — just
 * the same fork+exec pattern officeagent uses. */

static char g_dwell_reply[512];
static int  g_dwell_reply_len;

static int dwell_describe(char *out, int cap) {
    int p = 0;
    p = sapp(out, p, "wang tile set: ");
    char nb[12]; int nn = utoa((unsigned)g_set_count, nb);
    for (int i = 0; i < nn && p < cap - 1; i++) out[p++] = nb[i];
    p = sapp(out, p, " tiles, ");
    nn = utoa((unsigned)g_set_colors, nb);
    for (int i = 0; i < nn && p < cap - 1; i++) out[p++] = nb[i];
    p = sapp(out, p, " colors, ");
    p = sapp(out, p, g_grid_valid ? "tessellated " : "no tessellation ");
    /* Edge histogram. */
    int hist[WSQ_MAX_COLORS] = {0};
    for (int t = 0; t < g_set_count; t++) {
        hist[g_set[t].n]++;
        hist[g_set[t].e]++;
        hist[g_set[t].s]++;
        hist[g_set[t].w]++;
    }
    p = sapp(out, p, "edges: ");
    for (int c = 0; c < g_set_colors; c++) {
        nn = utoa((unsigned)hist[c], nb);
        for (int i = 0; i < nn && p < cap - 1; i++) out[p++] = nb[i];
        if (c + 1 < g_set_colors && p < cap - 1) out[p++] = '/';
    }
    if (p < cap) out[p] = 0;
    return p;
}

static void dwell_invoke(void) {
    char prompt[256];
    int pn = dwell_describe(prompt, sizeof prompt);
    /* Write prompt to a sentinel file the soul process can read. */
    int fd = (int)op("/tmp/officetiles_prompt.txt",
                     O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd >= 0) { wr(fd, prompt, pn); cl(fd); }

    long pid = forkk();
    if (pid < 0) {
        g_dwell_reply_len = 0;
        return;
    }
    if (pid == 0) {
        int out = (int)op("/tmp/officetiles_dwell.txt",
                          O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (out >= 0) { dup2_(out, 1); cl(out); }
        char *av[]  = { (char *)"./officesoul",
                        (char *)"--gen", prompt, 0 };
        execvee("./officesoul",          av, g_envp);
        execvee("/usr/local/bin/officesoul", av, g_envp);
        execvee("/usr/bin/officesoul",       av, g_envp);
        qu(127);
    }
    int status = 0;
    wait4_(&status);

    int rfd = (int)op("/tmp/officetiles_dwell.txt", O_RDONLY, 0);
    if (rfd < 0) { g_dwell_reply_len = 0; return; }
    int got = (int)rd(rfd, g_dwell_reply, sizeof g_dwell_reply - 1);
    cl(rfd);
    if (got < 0) got = 0;
    g_dwell_reply[got] = 0;
    while (got > 0 && (g_dwell_reply[got-1] == '\n' || g_dwell_reply[got-1] == '\r')) {
        got--;
        g_dwell_reply[got] = 0;
    }
    g_dwell_reply_len = got;
}


/* ── shell ─────────────────────────────────────────────── */
static void paint(const char *msg) {
    paint_desktop();
    chrome("officetiles");
    body_clear();

    char hdr[80];
    int p = 0;
    p = sapp(hdr, p, "Wang tile set · ");
    char nb[12]; int nn = utoa((unsigned)g_set_count, nb);
    for (int i = 0; i < nn; i++) hdr[p++] = nb[i];
    p = sapp(hdr, p, " tiles · ");
    nn = utoa((unsigned)g_set_colors, nb);
    for (int i = 0; i < nn; i++) hdr[p++] = nb[i];
    p = sapp(hdr, p, " colors · ");
    p = sapp(hdr, p, g_grid_valid ? "tessellated" : "(press t to tessellate)");
    hdr[p] = 0;
    body_at(2, 2, hdr, SCREEN_W - 4);

    if (g_grid_valid) {
        wsq_render();
    } else {
        body_at(6, 6, "no tessellation yet — press t to attempt", SCREEN_W - 8);
    }

    /* Tile-set glyphs in the right margin. */
    render_tileset_glyph(56, 3);

    if (g_dwell_reply_len > 0) {
        sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        body_at(2, SCREEN_H - 4, "dwell:", 8);
        char buf[80];
        int n = g_dwell_reply_len < (int)sizeof buf - 1 ? g_dwell_reply_len : (int)sizeof buf - 1;
        for (int i = 0; i < n; i++) buf[i] = g_dwell_reply[i];
        buf[n] = 0;
        body_at(9, SCREEN_H - 4, buf, SCREEN_W - 11);
    }

    if (msg) status(msg);
    else     status(" g=gen m=mutate t=tessellate c=colors n=count s=save l=load d=dwell q=quit ");
    fbflush();
}

static int run_tiles(void) {
    g_set_colors = CYCLE_COLORS[g_cycle_colors_idx];
    g_set_count  = CYCLE_COUNTS[g_cycle_count_idx];
    wsq_random();

    term_raw();
    paint(0);
    while (1) {
        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;
        if (k[0] == 'q' || k[0] == 'Q' || k[0] == 0x1b) break;
        if (k[0] == 'g' || k[0] == 'G') {
            wsq_random();
            paint("regenerated random set");
            continue;
        }
        if (k[0] == 'm' || k[0] == 'M') {
            wsq_mutate();
            paint("mutated one tile");
            continue;
        }
        if (k[0] == 't' || k[0] == 'T') {
            int ok = wsq_tessellate();
            if (ok) paint("tessellation succeeded");
            else    paint("tessellation FAILED — set is not valid");
            continue;
        }
        if (k[0] == 'c' || k[0] == 'C') {
            g_cycle_colors_idx = (g_cycle_colors_idx + 1) % (int)(sizeof CYCLE_COLORS / sizeof CYCLE_COLORS[0]);
            g_set_colors = CYCLE_COLORS[g_cycle_colors_idx];
            wsq_random();
            paint("cycled color count");
            continue;
        }
        if (k[0] == 'n' || k[0] == 'N') {
            g_cycle_count_idx = (g_cycle_count_idx + 1) % (int)(sizeof CYCLE_COUNTS / sizeof CYCLE_COUNTS[0]);
            g_set_count = CYCLE_COUNTS[g_cycle_count_idx];
            wsq_random();
            paint("cycled tile count");
            continue;
        }
        if (k[0] == 's' || k[0] == 'S') {
            int rc = wsq_save("tiles.bin");
            paint(rc == 0 ? "saved tiles.bin" : "save failed");
            continue;
        }
        if (k[0] == 'l' || k[0] == 'L') {
            int rc = wsq_load("tiles.bin");
            paint(rc == 0 ? "loaded tiles.bin" : "load failed (no file or bad header)");
            continue;
        }
        if (k[0] == 'd' || k[0] == 'D') {
            paint("dwelling — running ./officesoul --gen ...");
            dwell_invoke();
            paint("dwell complete");
            continue;
        }
    }
    term_cooked();
    return 0;
}


/* ── basename + dispatch ───────────────────────────────── */
static const char *basename_(const char *p) {
    const char *r = p;
    while (*p) { if (*p == '/') r = p + 1; p++; }
    return r;
}

int main_c(int argc, char **argv, char **envp) {
    g_envp = envp;
    (void)argc;
    const char *cmd = (argc > 0) ? basename_(argv[0]) : "officetiles";
    (void)cmd;
    return run_tiles();
}


/* ── _start ────────────────────────────────────────────── */
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
