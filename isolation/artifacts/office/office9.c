/* office9.c — Win95-style 13-app suite. Linux x86_64. No libc.
 *
 *   shell  notepad  word  mail  sheet  paint  hex  bfc  files
 *   find  calc  mines  ask   garden
 *
 * Same apps as office8 plus garden's V key — interactive view.
 *
 * V on a thumbnail launches a real isolated office9 (jail child)
 * with that genome applied, dropping the user into the suite shell
 * so they can actually open notepad / sheet / paint / etc. and see
 * the chrome under input + cursor + selection.  Pressing Q in the
 * shell tears down the jail and returns to garden.  Files written
 * during V mode live inside the jail dir and vanish on exit, so V
 * is non-destructive — purely for "what does this colour scheme
 * feel like in real use" exploration.
 *
 * Implementation: new `office9 view-genome <hex>` subcommand parses
 * the genome and dispatches to run_shell. jail.c is generalised to
 * take any subcommand (`jail OFFICE_PATH SUBCOMMAND ARGS...`); the
 * seccomp BPF allowlist is widened to cover every syscall the
 * suite uses (open/close/lseek/getdents64/time/fork/wait4 in
 * addition to the preview-only set) so the apps actually work
 * inside the jail.  Backward-compat: `jail PATH HEX` (3 args) still
 * means preview-genome, so office7's existing call shape keeps
 * working.
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

#define SYS_read  0
#define SYS_write 1
#define SYS_open  2
#define SYS_close 3
#define SYS_ioctl 16
#define SYS_fork  57
#define SYS_execve 59
#define SYS_wait4  61
#define SYS_time   201
#define SYS_getdents64 217
#define SYS_exit_group 231

#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT  64
#define O_TRUNC  512

#define rd(f, p, n)        sys3(SYS_read,  f, (long)(p), (long)(n))
#define wr(f, p, n)        sys3(SYS_write, f, (long)(p), (long)(n))
#define op(p, fl, m)       sys3(SYS_open,  (long)(p), (long)(fl), (long)(m))
#define cl(f)              sys3(SYS_close, f, 0, 0)
#define io(f, r, p)        sys3(SYS_ioctl, f, (long)(r), (long)(p))
#define qu(c)              sys3(SYS_exit_group, (long)(c), 0, 0)
#define forkk()            sys3(SYS_fork, 0, 0, 0)
#define execvee(p, a, e)   sys3(SYS_execve, (long)(p), (long)(a), (long)(e))
#define wait4_(s)          sys4(SYS_wait4, -1, (long)(s), 0, 0)


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

static void *mset(void *d, int v, size_t n) {
    char *dd = (char *)d;
    while (n--) *dd++ = (char)v;
    return d;
}


/* ── itoa for small unsigned ints ──────────────────────── */
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
static void sgrfg(int f) { fbs(ESC "[38;5;"); fbu(f); fbs("m"); }
static void sgr0(void)   { fbs(ESC "[0m"); }


/* ── terminal raw mode ─────────────────────────────────── */
struct ti {
    unsigned int  iflag, oflag, cflag, lflag;
    unsigned char line, cc[19];
};
#define ICANON 0x002
#define ECHO   0x008
#define IXON   0x400         /* iflag: ^S/^Q flow-control intercept */
#define ICRNL  0x100         /* iflag: CR→NL translation */
#define TCGETS 0x5401
#define TCSETS 0x5402

static struct ti term_orig;

static void term_raw(void) {
    io(0, TCGETS, &term_orig);
    struct ti t = term_orig;
    t.lflag &= ~(ICANON | ECHO);
    t.iflag &= ~(IXON | ICRNL); /* let Ctrl-S/Ctrl-Q + CR pass through */
    t.cc[6] = 1;        /* VMIN  */
    t.cc[5] = 2;        /* VTIME (200 ms) */
    io(0, TCSETS, &t);
    fbs(ESC "[?25l");   /* hide cursor */
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


/* ── Win95 chrome around the active app ────────────────── *
 * Colours (and a couple of layout flags) live in a 16-byte Genome
 * struct so the garden app can breed UI variants by mutating bytes.
 * Default values match office6 exactly, so apps that don't touch
 * g_genome render identically to the previous fork. */
struct Genome {
    unsigned char title_bg;      /* 0  default 21 (blue) */
    unsigned char title_fg;      /* 1  default 15 (white) */
    unsigned char bar_bg;        /* 2  default  7 (light grey) */
    unsigned char bar_fg;        /* 3  default  0 (black) */
    unsigned char desktop;       /* 4  default 30 (teal) */
    unsigned char select_bg;     /* 5  default 15 (white) */
    unsigned char select_fg;     /* 6  default  0 (black) */
    unsigned char shadow_bg;     /* 7  default  0 (black) */
    unsigned char shadow_fg;     /* 8  default  8 (dim grey) */
    unsigned char accent;        /* 9  for thumbnail title trim */
    unsigned char clock_corner;  /* 10 0=TL 1=TR 2=BL 3=BR */
    unsigned char show_clock;    /* 11 0=off, 1=on */
    unsigned char border;        /* 12 0='-' 1='=' 2='_' 3='~' */
    unsigned char menu_under;    /* 13 underline mnemonic letter */
    unsigned char reserved[2];   /* 14-15 */
};
static struct Genome g_genome = {
    21, 15, 7, 0, 30, 15, 0, 0, 8, 21, 1, 0, 0, 1, {0, 0}
};

#define COL_TITLE_BG  (g_genome.title_bg)
#define COL_TITLE_FG  (g_genome.title_fg)
#define COL_BAR_BG    (g_genome.bar_bg)
#define COL_BAR_FG    (g_genome.bar_fg)
#define COL_DESKTOP   (g_genome.desktop)
#define COL_SEL_BG    (g_genome.select_bg)
#define COL_SEL_FG    (g_genome.select_fg)
#define COL_SHADOW_BG (g_genome.shadow_bg)
#define COL_SHADOW_FG (g_genome.shadow_fg)

/* Terminal dimensions — queried once at startup via TIOCGWINSZ.  All
 * existing call-sites read SCREEN_W / SCREEN_H, which now resolve to
 * runtime variables instead of compile-time constants, so the suite
 * paints to the actual terminal size and we don't wrap the rightmost
 * (80 - termwidth) cols of the status row onto line 25.  Fall back
 * to 80×24 when the ioctl fails or the terminal is too small. */
#define TIOCGWINSZ 0x5413
struct winsize { unsigned short ws_row, ws_col, ws_xpx, ws_ypx; };

static int screen_w = 80;
static int screen_h = 24;
#define SCREEN_W screen_w
#define SCREEN_H screen_h

static void term_init(void) {
    struct winsize ws = { 0, 0, 0, 0 };
    long r = io(0, TIOCGWINSZ, &ws);
    if (r >= 0 && ws.ws_col >= 40 && ws.ws_row >= 10) {
        screen_w = ws.ws_col;
        screen_h = ws.ws_row;
    }
}

static void blanks(int n) {
    static const char sp[64] =
        "                                                                ";
    while (n > 64) { fbw(sp, 64); n -= 64; }
    if (n > 0) fbw(sp, n);
}

/* Paint the desktop teal. */
static void paint_desktop(void) {
    cls();
    sgrbg(COL_DESKTOP);
    for (int r = 0; r < SCREEN_H; r++) {
        cup(0, r);
        blanks(SCREEN_W);
    }
}

/* The active app's menu spec, set at the top of each run_* function.
 * menu_bar reads this so it can dim titles for menus that have no
 * entries in the current app (so Edit looks faint in paint, etc.). */
typedef struct MS_t MS;
static const MS *current_ms;
static int ms_count(const MS *m, int idx);   /* fwd decl */

/* Win95 title bar + menu bar across the top of the screen.
 * Mnemonic letters (F/E/V/H) are underlined with SGR 4 / 24 so the
 * user can see which Alt+letter opens which menu. Titles whose menu
 * is empty for the current app render in dim grey (fg=8). */
static void menu_bar(int active_idx) {
    static const char *titles[4] = { "File", "Edit", "View", "Help" };
    cup(0, 1);
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    fbs(" ");
    int used = 1;
    for (int i = 0; i < 4; i++) {
        int empty = current_ms && ms_count(current_ms, i) == 0;
        if (i == active_idx) sgrbgfg(COL_SEL_BG, COL_SEL_FG);
        else if (empty)      sgrbgfg(COL_BAR_BG, 8);     /* dim fg */
        else                 sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        fbs(" ");
        fbs(ESC "[4m");                 /* underline mnemonic */
        fbw(titles[i], 1);
        fbs(ESC "[24m");
        fbs(titles[i] + 1);
        fbs(" ");
        used += slen(titles[i]) + 2;    /* per-title actual width */
        sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    }
    blanks(SCREEN_W - used);
}

static void chrome(const char *title) {
    cup(0, 0);
    sgrbgfg(COL_TITLE_BG, COL_TITLE_FG);
    fbs(" ");
    fbs(title);
    int used = slen(title) + 1;
    blanks(SCREEN_W - used - 8);
    fbs(" _ [] X ");
    menu_bar(-1);
}

/* Status line at the bottom. */
static void status(const char *s) {
    cup(0, SCREEN_H - 1);
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    fbs(" ");
    fbs(s);
    blanks(SCREEN_W - 1 - slen(s));
}

/* Body area — clear it to grey. */
static void body_clear(void) {
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    for (int r = 2; r < SCREEN_H - 1; r++) {
        cup(0, r);
        blanks(SCREEN_W);
    }
}

/* Print str into the body at (x, y) up to max chars (no wrap). */
static void body_at(int x, int y, const char *s, int max) {
    cup(x, y);
    int n = slen(s);
    if (n > max) n = max;
    fbw(s, n);
}


/* ── shared buffer (text + hex + paint + sheet) ────────── */
#define BUF_CAP 65536
static char  buf[BUF_CAP];
static int   blen;
static int   bcur;     /* cursor offset */
static int   btop;     /* top-of-view byte offset */
static char  fname[256];

static int load_file(const char *path) {
    /* Always remember the path so a subsequent save targets it,
     * even if the file doesn't exist yet (new-file case). */
    int i = 0;
    while (i < (int)sizeof fname - 1 && path[i]) { fname[i] = path[i]; i++; }
    fname[i] = 0;
    int fd = (int)op(path, O_RDONLY, 0);
    if (fd < 0) { blen = 0; return 0; }
    blen = (int)rd(fd, buf, BUF_CAP - 1);
    if (blen < 0) blen = 0;
    cl(fd);
    return blen;
}

static int save_file(const char *path) {
    int fd = (int)op(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return -1;
    long n = wr(fd, buf, (size_t)blen);
    cl(fd);
    return (int)n;
}

static void buf_insert(int at, char ch) {
    if (blen >= BUF_CAP - 1) return;
    if (at < 0) at = 0;
    if (at > blen) at = blen;
    for (int i = blen; i > at; i--) buf[i] = buf[i - 1];
    buf[at] = ch;
    blen++;
}

static void buf_erase(int at) {
    if (at < 0 || at >= blen) return;
    for (int i = at; i < blen - 1; i++) buf[i] = buf[i + 1];
    blen--;
}


/* ── shared clipboard ─────────────────────────────────── */
/* All apps that participate in copy/paste read and write the same
 * buffer. ^C/^X/^V map onto cb_copy / cb_cut / cb_paste with app-
 * specific notions of "selection" (line for notepad/word, cell for
 * sheet, 16-byte row for hex). Survives across app launches because
 * .bss is module-static. */
#define CB_CAP 4096
static char cb[CB_CAP];
static int  cb_n;

static void cb_set(const char *s, int n) {
    if (n > CB_CAP) n = CB_CAP;
    mcpy(cb, s, n);
    cb_n = n;
}


/* ── menu engine (Alt+letter / F10 activates) ──────────── */
/* Action codes reuse the corresponding control byte where one
 * exists, so most actions slot back into the apps' existing
 * keypress handlers. Specials use 0xA0+ — apps handle separately. */
typedef struct { const char *label; unsigned char act; } MI;

#define MA_NEW    0x0e   /* ^N */
#define MA_SAVE   0x13   /* ^S */
#define MA_QUIT   0x11   /* ^Q */
#define MA_CUT    0x18   /* ^X */
#define MA_COPY   0x03   /* ^C */
#define MA_PASTE  0x16   /* ^V */
#define MA_REFLOW 0x0a   /* ^J */
#define MA_HEXTOG 0x09   /* tab */
#define MA_ABOUT  0xa0
#define MA_RESET  0xa5

struct MS_t {
    const MI *fi; int fn;
    const MI *ei; int en;
    const MI *vi; int vn;
    const MI *hi; int hn;
};

static int ms_count(const MS *m, int idx) {
    if (!m) return 1;
    switch (idx) {
    case 0: return m->fn;
    case 1: return m->en;
    case 2: return m->vn;
    case 3: return m->hn;
    }
    return 0;
}

static const MI mF_full[]   = {{"New     ^N", MA_NEW},
                               {"Save    ^S", MA_SAVE},
                               {"Quit    ^Q", MA_QUIT}};
static const MI mF_save[]   = {{"Save    ^S", MA_SAVE},
                               {"Quit    q ", MA_QUIT}};
static const MI mF_quit[]   = {{"Quit    q ", MA_QUIT}};
static const MI mF_mines[]  = {{"Reset   r ", MA_RESET},
                               {"Quit    q ", MA_QUIT}};
static const MI mE_full[]   = {{"Cut     ^X", MA_CUT},
                               {"Copy    ^C", MA_COPY},
                               {"Paste   ^V", MA_PASTE}};
static const MI mE_paste[]  = {{"Paste   ^V", MA_PASTE}};
static const MI mV_word[]   = {{"Reflow  ^J", MA_REFLOW}};
static const MI mV_hex[]    = {{"Hex/ASC Tab", MA_HEXTOG}};
static const MI mH_about[]  = {{"About...  ", MA_ABOUT}};

#define NA(a) ((int)(sizeof(a)/sizeof((a)[0])))

static const MS ms_notepad = { mF_full, NA(mF_full), mE_full, NA(mE_full),
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_word    = { mF_full, NA(mF_full), mE_full, NA(mE_full),
                               mV_word, NA(mV_word), mH_about, NA(mH_about) };
static const MS ms_sheet   = { mF_save, NA(mF_save), mE_full, NA(mE_full),
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_hex     = { mF_save, NA(mF_save), mE_full, NA(mE_full),
                               mV_hex, NA(mV_hex), mH_about, NA(mH_about) };
static const MS ms_mail    = { mF_save, NA(mF_save), mE_paste, NA(mE_paste),
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_paint   = { mF_save, NA(mF_save), 0, 0,
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_calc    = { mF_quit, NA(mF_quit), mE_paste, NA(mE_paste),
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_files   = { mF_quit, NA(mF_quit), 0, 0,
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_find    = { mF_quit, NA(mF_quit), 0, 0,
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_mines   = { mF_mines, NA(mF_mines), 0, 0,
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_shell   = { mF_quit, NA(mF_quit), 0, 0,
                               0, 0, mH_about, NA(mH_about) };
#define MA_SETTINGS 0xa6
#define MA_BREED    0xa7   /* garden: ENTER */
#define MA_PREVIEW  0xa8   /* garden: P */
#define MA_RANDOM   0xa9   /* garden: R */
#define MA_VIEW     0xaa   /* garden: V */
/* ask: New = clear chat, Settings = edit api_key/endpoint/model, Quit. */
static const MI mF_ask[]   = {{"New     ^N", MA_NEW},
                              {"Settings^E", MA_SETTINGS},
                              {"Quit    ^Q", MA_QUIT}};
static const MS ms_ask     = { mF_ask, NA(mF_ask), 0, 0,
                               0, 0, mH_about, NA(mH_about) };
/* garden: File = Save/Random/Quit; Edit = Breed/Preview/View. */
static const MI mF_garden[] = {{"Save    ^S", MA_SAVE},
                               {"Random  ^R", MA_RANDOM},
                               {"Quit    ^Q", MA_QUIT}};
static const MI mE_garden[] = {{"Breed   ENT", MA_BREED},
                               {"Preview P  ", MA_PREVIEW},
                               {"View    V  ", MA_VIEW}};
static const MS ms_garden  = { mF_garden, NA(mF_garden),
                               mE_garden, NA(mE_garden),
                               0, 0, mH_about, NA(mH_about) };

/* Read a key into k[]. Returns -1 if k is not a menu-activation
 * (Alt+f/e/v/h or F10), else the menu index 0..3 to start at. */
static int menu_activation(const unsigned char *k, int kn) {
    if (kn < 2 || k[0] != 0x1b) return -1;
    if (kn >= 5 && k[1] == '[' && k[2] == '2' && k[3] == '1' && k[4] == '~')
        return 0;                  /* F10 */
    char c = (char)k[1];
    if (c >= 'A' && c <= 'Z') c = (char)(c + 32);
    if (c == 'f') return 0;
    if (c == 'e') return 1;
    if (c == 'v') return 2;
    if (c == 'h') return 3;
    return -1;
}

/* Drop down the chosen menu; returns the action byte the user picked,
 * or 0 if they cancelled (or the start menu was empty — Alt+V on an
 * app without a View menu is a no-op, not a silent jump elsewhere).
 *
 * Layout: each title in the bar takes slen+2 cols (1 leading + slen
 * + 1 trailing), so pulldown column for menu mi is
 *   1 + sum_{j<mi} (slen(names[j]) + 2)
 * which puts the pulldown's own leading space directly under the
 * title's leading space, and the label letter directly under the
 * title's first letter. */
static int menu_run(const MS *m, int start) {
    const MI *items[4] = { m->fi, m->ei, m->vi, m->hi };
    int        n[4]    = { m->fn, m->en, m->vn, m->hn };
    static const char *names[4] = { "File", "Edit", "View", "Help" };
    if (n[start] == 0) return 0;          /* don't auto-advance */
    int mi = start;
    int sel = 0;
    while (1) {
        /* Wipe the body area each iteration so the previous menu's
         * pulldown is gone before the new one draws. Without this,
         * arrowing right from File to Edit leaves File's pulldown on
         * screen — two menus visible at once. We can clobber the
         * app's body freely; it'll redraw when menu_run returns. */
        sgrbg(COL_DESKTOP);
        for (int r = 2; r < SCREEN_H - 1; r++) {
            cup(0, r);
            blanks(SCREEN_W);
        }

        menu_bar(mi);

        int x = 1;
        for (int j = 0; j < mi; j++) x += slen(names[j]) + 2;
        int max_w = 0;
        for (int i = 0; i < n[mi]; i++) {
            int w = slen(items[mi][i].label);
            if (w > max_w) max_w = w;
        }
        int box_w = max_w + 2;            /* leading + trailing space */

        for (int i = 0; i < n[mi]; i++) {
            cup(x, 2 + i);
            sgrbgfg(i == sel ? COL_SEL_BG : COL_BAR_BG,
                    i == sel ? COL_SEL_FG : COL_BAR_FG);
            fbs(" ");
            int w = slen(items[mi][i].label);
            fbw(items[mi][i].label, w);
            blanks(max_w - w + 1);
        }
        /* drop shadow: 1-cell dark band on the right and bottom. */
        sgrbgfg(COL_SHADOW_BG, COL_SHADOW_FG);
        for (int i = 0; i < n[mi]; i++) {
            cup(x + box_w, 2 + i);
            fbs(" ");
        }
        cup(x + 1, 2 + n[mi]);
        for (int i = 0; i < box_w; i++) fbs(" ");

        /* menu-mode status line — overrides whatever the app set. */
        sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        status("  ESC cancel  |  ARROWS navigate  |  ENTER select");
        fbflush();

        unsigned char k[8];
        int kn = read_key(k, sizeof k);
        if (kn <= 0) continue;
        if (k[0] == 0x1b && kn == 1) return 0;
        if (k[0] == '\r' || k[0] == '\n' || k[0] == ' ')
            return items[mi][sel].act;
        if (kn >= 3 && k[0] == 0x1b && k[1] == '[') {
            switch (k[2]) {
            case 'A': if (sel > 0) sel--; break;
            case 'B': if (sel < n[mi] - 1) sel++; break;
            case 'C': {
                int t = 0;
                do { mi = (mi + 1) % 4; } while (n[mi] == 0 && ++t < 4);
                sel = 0;
                break;
            }
            case 'D': {
                int t = 0;
                do { mi = (mi - 1 + 4) % 4; } while (n[mi] == 0 && ++t < 4);
                sel = 0;
                break;
            }
            }
            continue;
        }
    }
}

/* Suite-wide About — shown by every app's Help->About so that we
 * pay for the body text exactly once. The active app's title is
 * still shown in the title bar. */
static void show_about(const char *title) {
    paint_desktop();
    chrome(title);
    body_clear();
    body_at(2, 3, "office7 — Win95-style suite, no libc.", SCREEN_W - 4);
    body_at(2, 5, "  notepad word mail sheet paint hex bfc", SCREEN_W - 4);
    body_at(2, 6, "  files find calc mines ask garden", SCREEN_W - 4);
    body_at(2, 8, "  Alt+F / F10 opens menus everywhere.", SCREEN_W - 4);
    body_at(2, 9, "  ^X / ^C / ^V copy across editors.", SCREEN_W - 4);
    status(" press any key ");
    fbflush();
    unsigned char k[4];
    read_key(k, 4);
}


/* ── forward declarations of apps ──────────────────────── */
static int run_shell(int, char**);
static int run_notepad(int, char**);
static int run_word(int, char**);
static int run_mail(int, char**);
static int run_sheet(int, char**);
static int run_paint(int, char**);
static int run_hex(int, char**);
static int run_bfc(int, char**);
static int run_files(int, char**);
static int run_find(int, char**);
static int run_calc(int, char**);
static int run_mines(int, char**);
static int run_ask(int, char**);
static int run_garden(int, char**);

/* Captured at startup so the ask app can hand curl an inherited
 * environment (PATH, HOME, SSL_CERT_FILE, etc). _start passes envp
 * as the third arg. */
static char **g_envp;

/* notepad lets a caller (find) request "open at line N" */
static int npad_target_line;


/* ── shell: run apps by name + a few built-ins ─────────── */
static int run_shell(int argc, char **argv) {
    current_ms = &ms_shell;
    (void)argc; (void)argv;
    term_raw();
    int running = 1;
    char line[256];
    int  llen = 0;
    int  cur_y = 3;
    int  msg_kind = 0;       /* 0 = none, 1 = ok, 2 = err */
    char msg[64];
    msg[0] = 0;

    while (running) {
        paint_desktop();
        chrome("Office Shell");
        body_clear();
        body_at(2, 3, "Welcome to Office. Built-in commands:", SCREEN_W - 4);
        body_at(2, 4, "  notepad  word  mail  sheet  paint  hex  bfc",
                SCREEN_W - 4);
        body_at(2, 5, "  files  find  calc  mines  ask  garden  exit",
                SCREEN_W - 4);
        body_at(2, 6, "  (Alt+F / F10 opens menus in every app)", SCREEN_W - 4);
        if (msg[0]) {
            sgrbgfg(COL_BAR_BG, msg_kind == 2 ? 88 : 22);
            body_at(2, 7, msg, SCREEN_W - 4);
            sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        }
        cup(2, cur_y + 6);
        sgrbgfg(15, 0);
        fbs(" > ");
        fbw(line, llen);
        blanks(SCREEN_W - 7 - llen);
        status("type a command, ENTER to run, q to quit");
        fbflush();

        unsigned char k[16];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, ami = menu_activation(k, n);
        if (ami >= 0) act = menu_run(&ms_shell, ami);
        if (act == MA_ABOUT) {
            show_about("Office Shell");
            continue;
        }
        if (act == MA_QUIT) { running = 0; break; }

        if (k[0] == '\r' || k[0] == '\n') {
            line[llen] = 0;
            msg[0] = 0; msg_kind = 0;
            if (llen == 0) { continue; }
            if (scmp(line, "exit") == 0 || scmp(line, "quit") == 0) {
                running = 0;
                break;
            }
            /* Tokenise by spaces (just first arg) */
            int sp = 0;
            while (sp < llen && line[sp] != ' ') sp++;
            char cmd[32];
            int cn = sp < (int)sizeof cmd - 1 ? sp : (int)sizeof cmd - 1;
            mcpy(cmd, line, cn); cmd[cn] = 0;
            char *path = (sp < llen) ? line + sp + 1 : (char *)"";
            char *sub_argv[3] = { cmd, path, 0 };
            int sub_argc = (sp < llen) ? 2 : 1;

            int rc = -1;
            if (scmp(cmd, "notepad") == 0) rc = run_notepad(sub_argc, sub_argv);
            else if (scmp(cmd, "word") == 0)  rc = run_word(sub_argc, sub_argv);
            else if (scmp(cmd, "mail") == 0)  rc = run_mail(sub_argc, sub_argv);
            else if (scmp(cmd, "sheet") == 0) rc = run_sheet(sub_argc, sub_argv);
            else if (scmp(cmd, "paint") == 0) rc = run_paint(sub_argc, sub_argv);
            else if (scmp(cmd, "hex") == 0)   rc = run_hex(sub_argc, sub_argv);
            else if (scmp(cmd, "bfc") == 0)   rc = run_bfc(sub_argc, sub_argv);
            else if (scmp(cmd, "files") == 0) rc = run_files(sub_argc, sub_argv);
            else if (scmp(cmd, "find") == 0)  rc = run_find(sub_argc, sub_argv);
            else if (scmp(cmd, "calc") == 0)  rc = run_calc(sub_argc, sub_argv);
            else if (scmp(cmd, "mines") == 0) rc = run_mines(sub_argc, sub_argv);
            else if (scmp(cmd, "ask") == 0)   rc = run_ask(sub_argc, sub_argv);
            else if (scmp(cmd, "garden") == 0) rc = run_garden(sub_argc, sub_argv);
            else { mcpy(msg, "unknown command", 16); msg_kind = 2; }

            (void)rc;
            llen = 0;
            term_raw();
            continue;
        }
        if (k[0] == 0x7f || k[0] == 8) {  /* backspace */
            if (llen > 0) llen--;
            continue;
        }
        if (k[0] == 'q' && llen == 0) { running = 0; break; }
        if (k[0] >= 32 && k[0] < 127 && llen < (int)sizeof line - 1) {
            line[llen++] = (char)k[0];
        }
    }

    term_cooked();
    return 0;
}


/* ── notepad: cursor-driven edit ───────────────────────── */
/* Helpers over `buf`/`blen` for line navigation. */
static int line_start_at(int p) {
    while (p > 0 && buf[p - 1] != '\n') p--;
    return p;
}
static int line_start_after(int p) {
    while (p < blen && buf[p] != '\n') p++;
    if (p < blen) p++;
    return p;
}
static int line_count_between(int a, int b) {
    int n = 0;
    if (a > b) { int t = a; a = b; b = t; }
    for (int i = a; i < b; i++) if (buf[i] == '\n') n++;
    return n;
}

static int col_of(int p) { return p - line_start_at(p); }

static int move_up(int p) {
    int ls = line_start_at(p);
    if (ls == 0) return p;
    int col = p - ls;
    int prev_start = line_start_at(ls - 1);
    int prev_end = ls - 1;
    int prev_len = prev_end - prev_start;
    if (col > prev_len) col = prev_len;
    return prev_start + col;
}
static int move_down(int p) {
    int next_start = line_start_after(p);
    if (next_start > blen) return p;
    int col = col_of(p);
    int next_end = next_start;
    while (next_end < blen && buf[next_end] != '\n') next_end++;
    int next_len = next_end - next_start;
    if (col > next_len) col = next_len;
    return next_start + col;
}

/* Keep btop so that bcur is visible. */
static void adjust_btop(int rows) {
    if (bcur < btop) btop = line_start_at(bcur);
    while (line_count_between(btop, bcur) >= rows && btop < blen) {
        btop = line_start_after(btop);
    }
}

static int cur_sx, cur_sy;

static void notepad_draw(const char *title, int word_wrap) {
    paint_desktop();
    chrome(title);
    body_clear();
    cur_sx = -1; cur_sy = -1;
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    int y = 2;
    int o = btop;
    int maxw = SCREEN_W - 4;
    while (y < SCREEN_H - 1) {
        cup(2, y);
        int xil = 0;
        if (o == bcur) { cur_sx = 2 + xil; cur_sy = y; }
        while (o < blen && buf[o] != '\n') {
            if (xil >= maxw) {
                if (word_wrap) {
                    y++;
                    if (y >= SCREEN_H - 1) goto rendered;
                    cup(2, y);
                    xil = 0;
                    if (o == bcur) { cur_sx = 2 + xil; cur_sy = y; }
                } else {
                    while (o < blen && buf[o] != '\n') o++;
                    break;
                }
            }
            char c = buf[o];
            if (c == '\t') c = ' ';
            if (c >= 32 && c < 127) fbw(&c, 1);
            else fbw(".", 1);
            xil++;
            o++;
            if (o == bcur && cur_sx < 0) { cur_sx = 2 + xil; cur_sy = y; }
        }
        if (o < blen && buf[o] == '\n') o++;
        else if (o >= blen) { y++; break; }
        y++;
    }
rendered:
    if (cur_sx < 0) {
        cur_sx = 2;
        cur_sy = y < SCREEN_H - 1 ? y : SCREEN_H - 2;
    }
    if (cur_sy >= SCREEN_H - 1) cur_sy = SCREEN_H - 2;
    status(word_wrap
        ? "  arrows | enter | bksp | ^J reflow | ^S save | ^Q quit"
        : "  arrows | enter | bksp | ^S save | ^Q quit");
    cup(cur_sx, cur_sy);
    fbs(ESC "[?25h");
    fbflush();
}

/* Reflow paragraph (bounded by \n\n) to `width`: collapse whitespace,
 * break at last space. Static scratch keeps logic simple. */
static char rscratch[4096];
static void reflow_paragraph(int width) {
    int s = bcur;
    while (s > 0) {
        if (s >= 2 && buf[s - 1] == '\n' && buf[s - 2] == '\n') break;
        s--;
    }
    int e = bcur;
    while (e < blen) {
        if (e + 1 < blen && buf[e] == '\n' && buf[e + 1] == '\n') break;
        e++;
    }
    int olen = 0, col = 0, last_sp = -1, saw_sp = 1;
    for (int i = s; i < e && olen < (int)sizeof rscratch - 1; i++) {
        char c = buf[i];
        if (c == ' ' || c == '\t' || c == '\n') {
            if (!saw_sp && olen > 0) {
                rscratch[olen] = ' ';
                last_sp = olen;
                olen++; col++;
                saw_sp = 1;
            }
        } else {
            rscratch[olen++] = c;
            col++;
            saw_sp = 0;
        }
        if (col >= width && last_sp >= 0) {
            rscratch[last_sp] = '\n';
            col = olen - last_sp - 1;
            last_sp = -1;
        }
    }
    while (olen > 0 && rscratch[olen - 1] == ' ') olen--;
    int new_blen = blen - (e - s) + olen;
    if (new_blen > BUF_CAP - 1) return;
    int delta = olen - (e - s);
    if (delta > 0)
        for (int i = blen - 1; i >= e; i--) buf[i + delta] = buf[i];
    else if (delta < 0)
        for (int i = e; i < blen; i++) buf[i + delta] = buf[i];
    for (int i = 0; i < olen; i++) buf[s + i] = rscratch[i];
    blen = new_blen;
    if (bcur > blen) bcur = blen;
}

/* Copy / cut the current line (start..\n) into the clipboard.
 * "Cut" also removes the line from the buffer. */
static void notepad_yank_line(int cut) {
    int s = line_start_at(bcur);
    int e = s;
    while (e < blen && buf[e] != '\n') e++;
    cb_set(buf + s, e - s);
    if (cut) {
        int span = e - s;
        if (e < blen) span++;            /* swallow the trailing \n too */
        for (int i = s; i + span < blen; i++) buf[i] = buf[i + span];
        blen -= span;
        if (bcur > blen) bcur = blen;
        if (bcur > s)    bcur = s;
    }
}

/* Paste raw clipboard bytes at cursor. */
static void cb_paste_at_cur(void) {
    for (int i = 0; i < cb_n; i++) {
        if (blen >= BUF_CAP - 1) break;
        buf_insert(bcur, cb[i]);
        bcur++;
    }
}

static int notepad_loop(const char *title, int word_wrap) {
    term_raw();
    while (1) {
        adjust_btop(SCREEN_H - 4);
        notepad_draw(title, word_wrap);
        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, mi = menu_activation(k, n);
        if (mi >= 0) act = menu_run(word_wrap ? &ms_word : &ms_notepad, mi);
        if (act == MA_ABOUT) {
            show_about(title);
            continue;
        }
        if (act > 0) { k[0] = (unsigned char)act; n = 1; }

        if (k[0] == 0x11) break;                              /* ^Q */
        if (k[0] == 0x13) { save_file(fname); continue; }     /* ^S */
        if (k[0] == 0x0e) { blen = 0; bcur = 0; btop = 0; fname[0] = 0; continue; }  /* ^N */
        if (k[0] == 0x03) { notepad_yank_line(0); continue; } /* ^C */
        if (k[0] == 0x18) { notepad_yank_line(1); continue; } /* ^X */
        if (k[0] == 0x16) { cb_paste_at_cur(); continue; }    /* ^V */
        if (k[0] == 0x0a && word_wrap) { reflow_paragraph(SCREEN_W - 4); continue; }
        if (k[0] == 0x7f || k[0] == 8) {
            if (bcur > 0) { buf_erase(bcur - 1); bcur--; }
            continue;
        }
        if (k[0] == '\r' || k[0] == '\n') {
            buf_insert(bcur, '\n');
            bcur++;
            continue;
        }
        if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
            switch (k[2]) {
            case 'A': bcur = move_up(bcur);     break;
            case 'B': bcur = move_down(bcur);   break;
            case 'C': if (bcur < blen) bcur++;  break;
            case 'D': if (bcur > 0)    bcur--;  break;
            }
            continue;
        }
        if (k[0] >= 32 && k[0] < 127) {
            buf_insert(bcur, (char)k[0]);
            bcur++;
        }
    }
    fbs(ESC "[?25l");
    fbflush();
    return 0;
}

static int run_notepad(int argc, char **argv) {
    current_ms = &ms_notepad;
    if (argc > 1 && argv[1][0]) load_file(argv[1]);
    else { blen = 0; fname[0] = 0; }
    bcur = 0; btop = 0;
    /* find may have set a target line: walk to it. */
    if (npad_target_line > 1) {
        int p = 0, ln = 1;
        while (p < blen && ln < npad_target_line) {
            if (buf[p] == '\n') ln++;
            p++;
        }
        bcur = p;
        npad_target_line = 0;
    }
    return notepad_loop("Notepad", 0);
}

static int run_word(int argc, char **argv) {
    current_ms = &ms_word;
    if (argc > 1 && argv[1][0]) load_file(argv[1]);
    else { blen = 0; fname[0] = 0; }
    bcur = 0; btop = 0;
    return notepad_loop("Word", 1);
}


/* ── mail: compose to ./outbox.txt ─────────────────────── */
static int run_mail(int argc, char **argv) {
    current_ms = &ms_mail;
    (void)argc; (void)argv;
    term_raw();
    char to_[80]    = {0};
    char subj[80]   = {0};
    char body[1024] = {0};
    int  field = 0;     /* 0=to, 1=subject, 2=body */
    int  to_n = 0, subj_n = 0, body_n = 0;
    int  done = 0, sent = 0;

    while (!done) {
        paint_desktop();
        chrome("Mail");
        body_clear();
        body_at(2, 3, "To:      ", SCREEN_W - 4);
        body_at(11, 3, to_, SCREEN_W - 14);
        body_at(2, 4, "Subject: ", SCREEN_W - 4);
        body_at(11, 4, subj, SCREEN_W - 14);
        body_at(2, 6, "Body:", SCREEN_W - 4);
        /* render body across lines 7..16 */
        {
            int x = 2, y = 7;
            cup(x, y);
            for (int i = 0; i < body_n; i++) {
                if (body[i] == '\n' || x >= SCREEN_W - 2) {
                    y++; x = 2;
                    if (y >= SCREEN_H - 4) break;
                    cup(x, y);
                    if (body[i] == '\n') continue;
                }
                fbw(body + i, 1);
                x++;
            }
        }
        cup(2, SCREEN_H - 3);
        sgrbgfg(COL_BAR_BG, 88);
        fbs(field == 0 ? "[To]    " :
            field == 1 ? "[Subj]  " : "[Body]  ");
        sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        if (sent) fbs(" — saved to ./outbox.txt");
        status(" tab switch field | enter newline in body | "
               "ctrl-s save | q quit");
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, mi = menu_activation(k, n);
        if (mi >= 0) act = menu_run(&ms_mail, mi);
        if (act == MA_ABOUT) {
            show_about("Mail");
            continue;
        }
        if (act > 0) { k[0] = (unsigned char)act; n = 1; }

        if (k[0] == 0x16 && field == 2) {            /* ^V paste in body */
            for (int i = 0; i < cb_n && body_n < (int)sizeof body - 1; i++) {
                body[body_n++] = cb[i];
            }
            continue;
        }
        if (k[0] == 'q' && field != 2) break;
        if (k[0] == '\t')   { field = (field + 1) % 3; continue; }
        if (k[0] == 0x13) {                /* Ctrl-S */
            /* Build outbox content into buf and save */
            blen = 0;
            const char *t = "To: ";
            for (int i = 0; t[i]; i++) buf[blen++] = t[i];
            for (int i = 0; i < to_n; i++) buf[blen++] = to_[i];
            buf[blen++] = '\n';
            t = "Subject: ";
            for (int i = 0; t[i]; i++) buf[blen++] = t[i];
            for (int i = 0; i < subj_n; i++) buf[blen++] = subj[i];
            buf[blen++] = '\n';
            buf[blen++] = '\n';
            for (int i = 0; i < body_n; i++) buf[blen++] = body[i];
            mcpy(fname, "outbox.txt", 11);
            save_file(fname);
            sent = 1;
            continue;
        }
        if (k[0] == 0x7f || k[0] == 8) {
            if (field == 0 && to_n   > 0) to_  [--to_n  ] = 0;
            if (field == 1 && subj_n > 0) subj [--subj_n] = 0;
            if (field == 2 && body_n > 0) body [--body_n] = 0;
            continue;
        }
        if (k[0] == '\r' || k[0] == '\n') {
            if (field == 2 && body_n < (int)sizeof body - 1)
                body[body_n++] = '\n';
            else
                field = (field + 1) % 3;
            continue;
        }
        if (k[0] >= 32 && k[0] < 127) {
            if (field == 0 && to_n   < (int)sizeof to_  - 1) to_ [to_n++ ] = (char)k[0];
            if (field == 1 && subj_n < (int)sizeof subj - 1) subj[subj_n++] = (char)k[0];
            if (field == 2 && body_n < (int)sizeof body - 1) body[body_n++] = (char)k[0];
        }
    }
    return 0;
}


/* ── sheet: CSV view + arrow-key navigation, single-cell edit ── */
#define SHEET_COLS 8
#define SHEET_ROWS 12
#define CELL_W     9

static char  cell[SHEET_ROWS][SHEET_COLS][16];
static int   cellrow, cellcol;

/* tiny formula evaluator: =EXPR with + - * /, parens, cell refs A1..H12 */
static const char *fp;
static int feval_expr(int depth);

static void fskip_ws(void) { while (*fp == ' ' || *fp == '\t') fp++; }

static int parse_int_literal(const char *s) {
    int v = 0, neg = 0;
    if (*s == '-') { neg = 1; s++; }
    while (*s >= '0' && *s <= '9') { v = v * 10 + (*s - '0'); s++; }
    return neg ? -v : v;
}

static int feval_cell(int row, int col, int depth) {
    if (row < 0 || row >= SHEET_ROWS || col < 0 || col >= SHEET_COLS) return 0;
    if (depth <= 0) return 0;
    const char *t = cell[row][col];
    if (t[0] == '=') {
        const char *save = fp;
        fp = t + 1;
        int v = feval_expr(depth - 1);
        fp = save;
        return v;
    }
    return parse_int_literal(t);
}

/* Try to parse a cell ref at *fp. Returns 1 + advances fp on success. */
static int try_cellref(int *row, int *col) {
    char L = *fp;
    int c = -1;
    if (L >= 'a' && L <= 'h') c = L - 'a';
    else if (L >= 'A' && L <= 'H') c = L - 'A';
    if (c < 0) return 0;
    if (!(fp[1] >= '0' && fp[1] <= '9')) return 0;
    fp++;
    int r = 0;
    while (*fp >= '0' && *fp <= '9') { r = r * 10 + (*fp - '0'); fp++; }
    *col = c;
    *row = r - 1;
    return 1;
}

/* Match a 3-letter uppercase keyword followed by '(' . On match, fp
 * advances past the opening paren and returns 1. Otherwise unchanged. */
static int match_func(const char *kw) {
    int i = 0;
    while (kw[i]) {
        char c = fp[i];
        if (c >= 'a' && c <= 'z') c = (char)(c - 32);
        if (c != kw[i]) return 0;
        i++;
    }
    if (fp[i] != '(') return 0;
    fp += i + 1;
    return 1;
}

/* Reduce a SUM/AVG/MIN/MAX range to a single int. kind: 0 sum, 1 avg, 2 min, 3 max */
static int range_reduce(int kind, int depth) {
    int r1, c1, r2, c2;
    fskip_ws();
    if (!try_cellref(&r1, &c1)) { /* swallow until ')' */
        while (*fp && *fp != ')') fp++;
        if (*fp == ')') fp++;
        return 0;
    }
    fskip_ws();
    if (*fp != ':') {
        /* single cell */
        if (*fp == ')') fp++;
        return feval_cell(r1, c1, depth);
    }
    fp++;
    fskip_ws();
    if (!try_cellref(&r2, &c2)) {
        if (*fp == ')') fp++;
        return feval_cell(r1, c1, depth);
    }
    fskip_ws();
    if (*fp == ')') fp++;
    if (r2 < r1) { int t = r1; r1 = r2; r2 = t; }
    if (c2 < c1) { int t = c1; c1 = c2; c2 = t; }
    if (r1 < 0) r1 = 0;
    if (c1 < 0) c1 = 0;
    if (r2 >= SHEET_ROWS) r2 = SHEET_ROWS - 1;
    if (c2 >= SHEET_COLS) c2 = SHEET_COLS - 1;
    long acc = 0;
    int  count = 0;
    int  best = 0, has = 0;
    for (int r = r1; r <= r2; r++) {
        for (int c = c1; c <= c2; c++) {
            int v = feval_cell(r, c, depth);
            acc += v; count++;
            if (!has) { best = v; has = 1; }
            else if (kind == 2 && v < best) best = v;
            else if (kind == 3 && v > best) best = v;
        }
    }
    if (kind == 0) return (int)acc;
    if (kind == 1) return count ? (int)(acc / count) : 0;
    return best;
}

static int feval_atom(int depth) {
    fskip_ws();
    if (*fp == '(') {
        fp++;
        int v = feval_expr(depth);
        fskip_ws();
        if (*fp == ')') fp++;
        return v;
    }
    if (*fp == '-') { fp++; return -feval_atom(depth); }
    if (*fp == '+') { fp++; return  feval_atom(depth); }
    if (*fp >= '0' && *fp <= '9') {
        int v = 0;
        while (*fp >= '0' && *fp <= '9') { v = v * 10 + (*fp - '0'); fp++; }
        return v;
    }
    if (match_func("SUM")) return range_reduce(0, depth);
    if (match_func("AVG")) return range_reduce(1, depth);
    if (match_func("MIN")) return range_reduce(2, depth);
    if (match_func("MAX")) return range_reduce(3, depth);
    int row, col;
    if (try_cellref(&row, &col)) return feval_cell(row, col, depth);
    return 0;
}

static int feval_term(int depth) {
    int v = feval_atom(depth);
    while (1) {
        fskip_ws();
        if (*fp == '*') { fp++; v *= feval_atom(depth); }
        else if (*fp == '/') { fp++; int d = feval_atom(depth); v = d ? v / d : 0; }
        else break;
    }
    return v;
}

static int feval_expr(int depth) {
    int v = feval_term(depth);
    while (1) {
        fskip_ws();
        if (*fp == '+') { fp++; v += feval_term(depth); }
        else if (*fp == '-') { fp++; v -= feval_term(depth); }
        else break;
    }
    return v;
}

static int sheet_eval(const char *formula) {
    fp = formula + 1;
    return feval_expr(8);
}

static int itoa_(int v, char *out) {
    int n = 0;
    if (v < 0) {
        out[n++] = '-';
        n += utoa((unsigned)(-(long)v), out + n);
    } else {
        n = utoa((unsigned)v, out);
    }
    return n;
}

static void sheet_load_csv(void) {
    mset(cell, 0, sizeof cell);
    int r = 0, c = 0, i = 0;
    for (int o = 0; o < blen && r < SHEET_ROWS; o++) {
        char ch = buf[o];
        if (ch == ',') {
            cell[r][c][i] = 0;
            if (c < SHEET_COLS - 1) c++;
            i = 0;
        } else if (ch == '\n') {
            cell[r][c][i] = 0;
            r++; c = 0; i = 0;
        } else if (i < 15) {
            cell[r][c][i++] = ch;
        }
    }
}

static void sheet_save_csv(void) {
    blen = 0;
    for (int r = 0; r < SHEET_ROWS; r++) {
        for (int c = 0; c < SHEET_COLS; c++) {
            int n = slen(cell[r][c]);
            for (int i = 0; i < n && blen < BUF_CAP - 2; i++) buf[blen++] = cell[r][c][i];
            if (c < SHEET_COLS - 1 && blen < BUF_CAP - 1) buf[blen++] = ',';
        }
        if (blen < BUF_CAP - 1) buf[blen++] = '\n';
    }
    save_file(fname);
}

static int run_sheet(int argc, char **argv) {
    current_ms = &ms_sheet;
    if (argc > 1 && argv[1][0]) {
        load_file(argv[1]);
        sheet_load_csv();
    } else {
        mset(cell, 0, sizeof cell);
        fname[0] = 0;
    }
    cellrow = 0; cellcol = 0;
    term_raw();

    int editing = 0;
    int eidx = 0;

    while (1) {
        paint_desktop();
        chrome("Sheet");
        body_clear();
        /* Column headers */
        cup(2, 2);
        sgrbgfg(7, 8);
        fbs("    ");
        for (int c = 0; c < SHEET_COLS; c++) {
            char h = 'A' + c;
            fbw(" ", 1);
            fbw(&h, 1);
            for (int j = 0; j < CELL_W - 2; j++) fbw(" ", 1);
        }
        for (int r = 0; r < SHEET_ROWS && r + 3 < SCREEN_H - 1; r++) {
            cup(2, 3 + r);
            sgrbgfg(7, 8);
            char rh[3] = { ' ', (char)('1' + r % 9), ' ' };
            fbw(rh, 3);
            fbw(" ", 1);
            for (int c = 0; c < SHEET_COLS; c++) {
                int sel = (r == cellrow && c == cellcol);
                if (sel) sgrbgfg(15, 0);
                else     sgrbgfg(7, 0);
                char shown[16];
                int  len;
                int  is_formula = (cell[r][c][0] == '=');
                if (is_formula && !(editing && sel)) {
                    int v = sheet_eval(cell[r][c]);
                    len = itoa_(v, shown);
                    if (len > CELL_W - 1) len = CELL_W - 1;
                    sgrbgfg(sel ? 15 : 7, sel ? 0 : 21);   /* blue fg = formula */
                    fbw(shown, len);
                } else {
                    len = slen(cell[r][c]);
                    if (len > CELL_W - 1) len = CELL_W - 1;
                    fbw(cell[r][c], len);
                }
                sgrbgfg(sel ? 15 : 7, 0);
                blanks(CELL_W - len);
            }
        }
        char hint[80] = { 0 };
        int hn = 0;
        const char *h = editing
            ? "  editing — enter commits, esc cancels  (=A1+B2 for formulas)"
            : "  arrows move | e edit | s save csv | q back";
        while (h[hn]) { hint[hn] = h[hn]; hn++; }
        status(hint);
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        if (editing) {
            if (k[0] == '\r' || k[0] == '\n') {
                cell[cellrow][cellcol][eidx] = 0;
                editing = 0;
                continue;
            }
            if (k[0] == 0x1b && n == 1) {
                editing = 0;
                continue;
            }
            if (k[0] == 0x7f || k[0] == 8) {
                if (eidx > 0) cell[cellrow][cellcol][--eidx] = 0;
                continue;
            }
            if (k[0] == 0x16) {                          /* ^V paste in edit */
                for (int i = 0; i < cb_n && eidx < 15; i++) {
                    if (cb[i] >= 32 && cb[i] < 127)
                        cell[cellrow][cellcol][eidx++] = cb[i];
                }
                cell[cellrow][cellcol][eidx] = 0;
                continue;
            }
            if (k[0] >= 32 && k[0] < 127 && eidx < 15) {
                cell[cellrow][cellcol][eidx++] = (char)k[0];
            }
            continue;
        }

        int act = -1, ami = menu_activation(k, n);
        if (ami >= 0) act = menu_run(&ms_sheet, ami);
        if (act == MA_ABOUT) {
            show_about("Sheet");
            continue;
        }
        if (act > 0) { k[0] = (unsigned char)act; n = 1; }

        if (k[0] == 'q' || k[0] == MA_QUIT) break;
        if (k[0] == 's' || k[0] == MA_SAVE) sheet_save_csv();
        if (k[0] == 'e') {
            editing = 1;
            eidx = slen(cell[cellrow][cellcol]);
        }
        if (k[0] == 0x03 || k[0] == 0x18) {              /* copy / cut cell */
            cb_set(cell[cellrow][cellcol], slen(cell[cellrow][cellcol]));
            if (k[0] == 0x18) cell[cellrow][cellcol][0] = 0;
        }
        if (k[0] == 0x16) {                              /* paste cell */
            int put = cb_n; if (put > 15) put = 15;
            int j = 0;
            for (int i = 0; i < put; i++) {
                if (cb[i] >= 32 && cb[i] < 127) cell[cellrow][cellcol][j++] = cb[i];
            }
            cell[cellrow][cellcol][j] = 0;
        }
        if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
            switch (k[2]) {
            case 'A': if (cellrow > 0) cellrow--; break;
            case 'B': if (cellrow < SHEET_ROWS - 1) cellrow++; break;
            case 'C': if (cellcol < SHEET_COLS - 1) cellcol++; break;
            case 'D': if (cellcol > 0) cellcol--; break;
            }
        }
    }
    return 0;
}


/* ── paint: ASCII canvas, per-cell colour ─────────────── */
#define PAINT_W 60
#define PAINT_H 16
static char           canvas[PAINT_H][PAINT_W];
static unsigned char  canvas_fg[PAINT_H][PAINT_W];
static int  px, py;
static int  brush = 1;     /* foreground colour (xterm-256) */
static char brush_char = '#';

static int paint_load(const char *path) {
    int fd = (int)op(path, O_RDONLY, 0);
    if (fd < 0) return 0;
    int n = (int)rd(fd, buf, BUF_CAP - 1);
    cl(fd);
    if (n <= 0) return 0;
    /* Format: "<hex><char> <hex><char> ... \n" per row. */
    int o = 0, r = 0;
    while (r < PAINT_H && o + 1 < n) {
        int c = 0;
        while (c < PAINT_W && o + 1 < n && buf[o] != '\n') {
            char hx = buf[o++];
            int fg = (hx >= 'a' && hx <= 'f') ? hx - 'a' + 10
                   : (hx >= 'A' && hx <= 'F') ? hx - 'A' + 10
                   : (hx >= '0' && hx <= '9') ? hx - '0' : 0;
            canvas_fg[r][c] = (unsigned char)fg;
            canvas[r][c] = buf[o++];
            c++;
        }
        if (o < n && buf[o] == '\n') o++;
        r++;
    }
    return 1;
}

static int run_paint(int argc, char **argv) {
    current_ms = &ms_paint;
    mset(canvas, ' ', sizeof canvas);
    mset(canvas_fg, 0, sizeof canvas_fg);
    if (argc > 1 && argv[1][0]) {
        int i = 0;
        while (i < (int)sizeof fname - 1 && argv[1][i]) {
            fname[i] = argv[1][i]; i++;
        }
        fname[i] = 0;
        paint_load(fname);
    } else {
        mcpy(fname, "canvas.txt", 11);
    }
    px = PAINT_W / 2; py = PAINT_H / 2;
    term_raw();
    while (1) {
        paint_desktop();
        chrome("Paint");
        body_clear();
        int prev_fg = -1;
        for (int r = 0; r < PAINT_H; r++) {
            cup(2, 3 + r);
            for (int c = 0; c < PAINT_W; c++) {
                int fg = canvas_fg[r][c];
                if (fg != prev_fg) { sgrbgfg(15, fg); prev_fg = fg; }
                fbw(&canvas[r][c], 1);
            }
        }
        cup(2 + px, 3 + py);
        sgrbgfg(brush, 0);
        fbw(&canvas[py][px], 1);
        char info[40] = { 0 };
        int n = 0;
        const char *l = "  arrows move | letters paint | 0-7 colour | s save | q back";
        while (l[n]) { info[n] = l[n]; n++; }
        status(info);
        fbflush();

        unsigned char k[8];
        int rn = read_key(k, sizeof k);
        if (rn <= 0) continue;

        int act = -1, mi = menu_activation(k, rn);
        if (mi >= 0) act = menu_run(&ms_paint, mi);
        if (act == MA_ABOUT) {
            show_about("Paint");
            continue;
        }
        if (act > 0) { k[0] = (unsigned char)act; rn = 1; }

        if (k[0] == 'q' || k[0] == MA_QUIT) break;
        if (k[0] == 's' || k[0] == MA_SAVE) {
            blen = 0;
            for (int r = 0; r < PAINT_H && blen < BUF_CAP - 1; r++) {
                for (int c = 0; c < PAINT_W && blen + 2 < BUF_CAP - 1; c++) {
                    int fg = canvas_fg[r][c] & 0xf;
                    buf[blen++] = (char)(fg < 10 ? '0' + fg : 'a' + fg - 10);
                    buf[blen++] = canvas[r][c];
                }
                if (blen < BUF_CAP - 1) buf[blen++] = '\n';
            }
            if (!fname[0]) mcpy(fname, "canvas.txt", 11);
            save_file(fname);
        }
        if (k[0] >= '0' && k[0] <= '7') brush = k[0] - '0';
        if (rn >= 3 && k[0] == 0x1b && k[1] == '[') {
            switch (k[2]) {
            case 'A': if (py > 0) py--; break;
            case 'B': if (py < PAINT_H - 1) py++; break;
            case 'C': if (px < PAINT_W - 1) px++; break;
            case 'D': if (px > 0) px--; break;
            }
        }
        if (k[0] >= 32 && k[0] < 127 && k[0] != 'q' && k[0] != 's' &&
            !(k[0] >= '0' && k[0] <= '7')) {
            brush_char = (char)k[0];
            canvas[py][px] = brush_char;
            canvas_fg[py][px] = (unsigned char)brush;
        }
    }
    return 0;
}


/* ── hex editor: 16 bytes/line view + nibble write ─────── */
static int run_hex(int argc, char **argv) {
    current_ms = &ms_hex;
    if (argc > 1 && argv[1][0]) load_file(argv[1]);
    else { blen = 0; fname[0] = 0; }
    bcur = 0; btop = 0;
    int nibhi = 1;            /* next digit goes to high nibble */
    int ascii_pane = 0;       /* 0 = hex side, 1 = ascii side */
    term_raw();
    while (1) {
        int rows = SCREEN_H - 4;
        if (bcur < btop) btop = (bcur / 16) * 16;
        if (bcur >= btop + rows * 16) btop = ((bcur / 16) - rows + 1) * 16;
        if (btop < 0) btop = 0;

        paint_desktop();
        chrome("Hex");
        body_clear();
        for (int r = 0; r < rows; r++) {
            int o = btop + r * 16;
            cup(2, 3 + r);
            sgrbgfg(7, 8);
            char hx[8];
            unsigned u = (unsigned)o;
            for (int s = 16, i = 0; s; s -= 4, i++) {
                int v = (u >> (s - 4)) & 0xf;
                hx[i] = (char)(v < 10 ? '0' + v : 'a' + v - 10);
            }
            fbw(hx, 8);
            fbw("  ", 2);
            char asc[16];
            int  cur_in_row = -1;
            int  an = 0;
            for (int j = 0; j < 16; j++) {
                int oo = o + j;
                int is_cur = (oo == bcur);
                if (is_cur) cur_in_row = j;
                if (oo >= blen) {
                    sgrbgfg(is_cur && !ascii_pane ? 15 : 7, 8);
                    fbw("__ ", 3);
                    asc[an++] = ' ';
                    continue;
                }
                unsigned u8 = (unsigned char)buf[oo];
                int hi = (u8 >> 4) & 0xf, lo = u8 & 0xf;
                char hh = (char)(hi < 10 ? '0' + hi : 'a' + hi - 10);
                char ll = (char)(lo < 10 ? '0' + lo : 'a' + lo - 10);
                int hex_hi_hi = is_cur && !ascii_pane && nibhi;
                int hex_hi_lo = is_cur && !ascii_pane && !nibhi;
                sgrbgfg(hex_hi_hi ? 15 : 7, 0); fbw(&hh, 1);
                sgrbgfg(hex_hi_lo ? 15 : 7, 0); fbw(&ll, 1);
                sgrbgfg(7, 0); fbw(" ", 1);
                asc[an++] = (u8 >= 32 && u8 < 127) ? (char)u8 : '.';
            }
            fbw(" ", 1);
            /* render ascii column with selective highlight */
            for (int j = 0; j < an; j++) {
                int hl = (ascii_pane && cur_in_row == j);
                sgrbgfg(hl ? 15 : 7, 0);
                fbw(asc + j, 1);
            }
        }
        status(ascii_pane
            ? "  ASCII mode | tab→hex | printable overwrites | ^S save | q"
            : "  HEX mode | tab→ASCII | 0-9 a-f write | i ins | x del | ^S save | q");
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, mi = menu_activation(k, n);
        if (mi >= 0) act = menu_run(&ms_hex, mi);
        if (act == MA_ABOUT) {
            show_about("Hex");
            continue;
        }
        if (act > 0) { k[0] = (unsigned char)act; n = 1; }

        if (k[0] == 0x13) { save_file(fname); continue; }
        if (k[0] == '\t' || k[0] == MA_HEXTOG) {
            ascii_pane = !ascii_pane; nibhi = 1; continue;
        }
        if (k[0] == 0x03 || k[0] == 0x18) {                 /* copy/cut row */
            int s = (bcur / 16) * 16;
            int e = s + 16; if (e > blen) e = blen;
            cb_set(buf + s, e - s);
            if (k[0] == 0x18) {
                int span = e - s;
                for (int i = s; i + span < blen; i++) buf[i] = buf[i + span];
                blen -= span;
                if (bcur > blen) bcur = blen;
            }
            nibhi = 1;
            continue;
        }
        if (k[0] == 0x16) {                                  /* paste */
            for (int i = 0; i < cb_n; i++) {
                if (blen >= BUF_CAP - 1) break;
                for (int j = blen; j > bcur; j--) buf[j] = buf[j - 1];
                buf[bcur] = cb[i];
                blen++; bcur++;
            }
            nibhi = 1;
            continue;
        }
        if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
            switch (k[2]) {
            case 'A': if (bcur >= 16) bcur -= 16; nibhi = 1; break;
            case 'B': if (bcur + 16 <= blen) bcur += 16;
                      else if (bcur < blen) bcur = blen;
                      nibhi = 1; break;
            case 'C': if (bcur < blen) bcur++; nibhi = 1; break;
            case 'D': if (bcur > 0) bcur--; nibhi = 1; break;
            }
            continue;
        }
        if (ascii_pane) {
            if (k[0] == 'q' || k[0] == 0x11) break;     /* q or Ctrl-Q */
            if (k[0] >= 32 && k[0] < 127) {
                if (bcur >= blen) {
                    if (blen >= BUF_CAP - 1) continue;
                    buf[blen++] = 0;
                }
                buf[bcur] = (char)k[0];
                if (bcur < BUF_CAP - 1 && bcur + 1 <= blen) bcur++;
            }
            continue;
        }
        if (k[0] == 'q') break;
        if (k[0] == 'i') {
            if (blen < BUF_CAP - 1) {
                for (int i = blen; i > bcur; i--) buf[i] = buf[i - 1];
                buf[bcur] = 0; blen++; nibhi = 1;
            }
            continue;
        }
        if (k[0] == 'x') {
            if (bcur < blen) {
                buf_erase(bcur);
                if (bcur >= blen && bcur > 0) bcur--;
                nibhi = 1;
            }
            continue;
        }
        int hv = -1;
        if (k[0] >= '0' && k[0] <= '9') hv = k[0] - '0';
        else if (k[0] >= 'a' && k[0] <= 'f') hv = k[0] - 'a' + 10;
        else if (k[0] >= 'A' && k[0] <= 'F') hv = k[0] - 'A' + 10;
        if (hv >= 0) {
            if (bcur >= blen) {
                if (blen >= BUF_CAP - 1) continue;
                buf[blen++] = 0;
            }
            unsigned char b = (unsigned char)buf[bcur];
            if (nibhi) {
                buf[bcur] = (char)((b & 0x0f) | (hv << 4));
                nibhi = 0;
            } else {
                buf[bcur] = (char)((b & 0xf0) | hv);
                if (bcur < BUF_CAP - 1) bcur++;
                nibhi = 1;
            }
        }
    }
    return 0;
}


/* ── bfc: brainfuck compiler/interpreter — runs the program ── */
#define TAPE_LEN 4096
static unsigned char tape[TAPE_LEN];

static int run_bfc(int argc, char **argv) {
    current_ms = &ms_files;
    if (argc < 2 || !argv[1][0]) return 1;
    load_file(argv[1]);
    term_raw();
    /* Run BF program: emit output to a captured buffer, then show. */
    char out[4096];
    int  on = 0;
    int  ip = 0, dp = 0;
    mset(tape, 0, sizeof tape);
    while (ip < blen && on < (int)sizeof out - 1) {
        char c = buf[ip++];
        if (c == '+') tape[dp]++;
        else if (c == '-') tape[dp]--;
        else if (c == '>') { if (dp < TAPE_LEN - 1) dp++; }
        else if (c == '<') { if (dp > 0) dp--; }
        else if (c == '.') out[on++] = (char)tape[dp];
        else if (c == ',') { /* no input */ tape[dp] = 0; }
        else if (c == '[' && tape[dp] == 0) {
            int d = 1;
            while (ip < blen && d) {
                if (buf[ip] == '[') d++;
                else if (buf[ip] == ']') d--;
                ip++;
            }
        }
        else if (c == ']' && tape[dp] != 0) {
            int d = 1;
            ip -= 2;
            while (ip >= 0 && d) {
                if (buf[ip] == ']') d++;
                else if (buf[ip] == '[') d--;
                if (d) ip--;
            }
        }
    }
    out[on] = 0;
    /* Render */
    while (1) {
        paint_desktop();
        chrome("BF Compiler — output");
        body_clear();
        int x = 2, y = 3;
        cup(x, y);
        for (int i = 0; i < on; i++) {
            char c = out[i];
            if (c == '\n' || x >= SCREEN_W - 2) {
                y++; x = 2;
                if (y >= SCREEN_H - 2) break;
                cup(x, y);
                if (c == '\n') continue;
            }
            fbw(&c, 1);
            x++;
        }
        char st[80] = { 0 };
        int  sn = 0;
        const char *t = "  q to quit";
        while (t[sn]) { st[sn] = t[sn]; sn++; }
        status(st);
        fbflush();
        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;
        int ami = menu_activation(k, n);
        if (ami >= 0) {
            int act = menu_run(&ms_files, ami);
            if (act == MA_ABOUT) {
                show_about("BFC");
                continue;
            }
            if (act == MA_QUIT) break;
            continue;
        }
        if (k[0] == 'q') break;
    }
    return 0;
}


/* ── files: directory browser ─────────────────────────── */
struct linux_dirent64 {
    long          d_ino;
    long          d_off;
    unsigned short d_reclen;
    unsigned char  d_type;
    char           d_name[];
};

#define FILES_MAX 64
static char files_name[FILES_MAX][64];
static unsigned char files_type[FILES_MAX];   /* 4 = dir, 8 = file */
static int  files_count;

static int files_scan(const char *path) {
    files_count = 0;
    int fd = (int)op(path, O_RDONLY, 0);
    if (fd < 0) return 0;
    char db[4096];
    while (files_count < FILES_MAX) {
        long n = sys3(SYS_getdents64, fd, (long)db, (long)sizeof db);
        if (n <= 0) break;
        long o = 0;
        while (o < n && files_count < FILES_MAX) {
            struct linux_dirent64 *de = (struct linux_dirent64 *)(db + o);
            const char *nm = de->d_name;
            if (!(nm[0] == '.' && nm[1] == 0)) {
                int i = 0;
                while (i < 63 && nm[i]) { files_name[files_count][i] = nm[i]; i++; }
                files_name[files_count][i] = 0;
                files_type[files_count] = de->d_type;
                files_count++;
            }
            o += de->d_reclen;
        }
    }
    cl(fd);
    return files_count;
}

static int run_files(int argc, char **argv) {
    current_ms = &ms_files;
    (void)argc; (void)argv;
    files_scan(".");
    int sel = 0;
    term_raw();
    while (1) {
        paint_desktop();
        chrome("Files");
        body_clear();
        body_at(2, 2, "  ./", SCREEN_W - 4);
        int top = sel < SCREEN_H - 7 ? 0 : sel - (SCREEN_H - 7);
        for (int i = 0; i < SCREEN_H - 5 && top + i < files_count; i++) {
            int idx = top + i;
            cup(2, 4 + i);
            if (idx == sel) sgrbgfg(15, 0); else sgrbgfg(7, 0);
            char tag = files_type[idx] == 4 ? '/' : ' ';
            fbw(" ", 1);
            fbw(&tag, 1);
            fbw(" ", 1);
            int nl = slen(files_name[idx]);
            if (nl > SCREEN_W - 8) nl = SCREEN_W - 8;
            fbw(files_name[idx], nl);
            blanks(SCREEN_W - 8 - nl);
        }
        status("  arrows | enter open in notepad | h hex | q back");
        fbflush();
        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, ami = menu_activation(k, n);
        if (ami >= 0) act = menu_run(&ms_files, ami);
        if (act == MA_ABOUT) {
            show_about("Files");
            continue;
        }
        if (k[0] == 'q' || act == MA_QUIT) break;
        if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
            if (k[2] == 'A' && sel > 0) sel--;
            if (k[2] == 'B' && sel + 1 < files_count) sel++;
            continue;
        }
        if (k[0] == '\r' || k[0] == '\n') {
            if (sel >= 0 && sel < files_count) {
                if (files_type[sel] == 4) {
                    /* descend not supported in v1 — would need cwd tracking */
                    continue;
                }
                char *sub_argv[3] = { (char *)"notepad", files_name[sel], 0 };
                run_notepad(2, sub_argv);
                term_raw();
            }
            continue;
        }
        if (k[0] == 'h') {
            if (sel >= 0 && sel < files_count && files_type[sel] != 4) {
                char *sub_argv[3] = { (char *)"hex", files_name[sel], 0 };
                run_hex(2, sub_argv);
                term_raw();
            }
            continue;
        }
    }
    return 0;
}


/* ── find: grep across files in cwd ───────────────────── */
#define FIND_MAX 80
static char find_q[80];
static int  find_qn;
static char find_path[FIND_MAX][64];
static int  find_line[FIND_MAX];
static char find_text[FIND_MAX][64];
static int  find_count;

/* Append matches from `path` to the find_* arrays. Reads via the
 * shared `buf` scratch; that means find clobbers any in-memory
 * notepad buffer, but find always runs as its own app instance. */
static void find_in_file(const char *path) {
    int fd = (int)op(path, O_RDONLY, 0);
    if (fd < 0) return;
    int n = (int)rd(fd, buf, BUF_CAP - 1);
    cl(fd);
    if (n <= 0) return;
    int line_no = 1, line_start = 0;
    for (int i = 0; i <= n; i++) {
        if (i == n || buf[i] == '\n') {
            int line_end = i;
            int matched = 0;
            for (int s = line_start; s + find_qn <= line_end; s++) {
                int ok = 1;
                for (int j = 0; j < find_qn; j++)
                    if (buf[s + j] != find_q[j]) { ok = 0; break; }
                if (ok) { matched = 1; break; }
            }
            if (matched && find_count < FIND_MAX) {
                int p = 0; while (p < 63 && path[p]) { find_path[find_count][p] = path[p]; p++; }
                find_path[find_count][p] = 0;
                find_line[find_count] = line_no;
                int len = line_end - line_start;
                if (len > 63) len = 63;
                for (int j = 0; j < len; j++)
                    find_text[find_count][j] = buf[line_start + j];
                find_text[find_count][len] = 0;
                find_count++;
            }
            line_no++;
            line_start = i + 1;
        }
    }
}

static int run_find(int argc, char **argv) {
    current_ms = &ms_find;
    (void)argc; (void)argv;
    term_raw();
    find_qn = 0; find_count = 0;
    int phase = 0;       /* 0 = entering query, 1 = browsing results */
    int sel = 0;
    while (1) {
        paint_desktop();
        chrome("Find");
        body_clear();
        body_at(2, 3, "Search for:", SCREEN_W - 4);
        cup(2, 5);
        sgrbgfg(phase == 0 ? 15 : 7, 0);
        fbs(" "); fbw(find_q, find_qn);
        blanks(40 - find_qn);
        if (phase == 1) {
            int top = sel < SCREEN_H - 9 ? 0 : sel - (SCREEN_H - 9);
            for (int i = 0; i < SCREEN_H - 8 && top + i < find_count; i++) {
                int idx = top + i;
                cup(2, 7 + i);
                sgrbgfg(idx == sel ? 15 : 7, 0);
                fbs(" ");
                int pn = slen(find_path[idx]);
                fbw(find_path[idx], pn);
                fbw(":", 1);
                char ln[8]; int ln_n = utoa(find_line[idx], ln);
                fbw(ln, ln_n);
                fbs(": ");
                int tn = slen(find_text[idx]);
                if (tn > SCREEN_W - 8 - pn - ln_n) tn = SCREEN_W - 8 - pn - ln_n;
                fbw(find_text[idx], tn);
            }
            if (find_count == 0) body_at(2, 7, "  (no matches)", 40);
        }
        status(phase == 0
            ? "  type query | enter search | q back"
            : "  arrows | enter open hit | / new query | q back");
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, ami = menu_activation(k, n);
        if (ami >= 0) act = menu_run(&ms_find, ami);
        if (act == MA_ABOUT) {
            show_about("Find");
            continue;
        }
        if (act == MA_QUIT) break;

        if (phase == 0) {
            if (k[0] == 'q' && find_qn == 0) break;
            if (k[0] == '\r' || k[0] == '\n') {
                if (find_qn == 0) continue;
                find_count = 0;
                files_scan(".");
                for (int i = 0; i < files_count && find_count < FIND_MAX; i++) {
                    if (files_type[i] == 8) find_in_file(files_name[i]);
                }
                phase = 1;
                sel = 0;
                continue;
            }
            if (k[0] == 0x7f || k[0] == 8) {
                if (find_qn) find_qn--;
                continue;
            }
            if (k[0] >= 32 && k[0] < 127 && find_qn < 79)
                find_q[find_qn++] = (char)k[0];
        } else {
            if (k[0] == 'q') break;
            if (k[0] == '/') { phase = 0; continue; }
            if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
                if (k[2] == 'A' && sel > 0) sel--;
                if (k[2] == 'B' && sel + 1 < find_count) sel++;
                continue;
            }
            if (k[0] == '\r' || k[0] == '\n') {
                if (sel < find_count) {
                    char *sub_argv[3] = { (char *)"notepad", find_path[sel], 0 };
                    npad_target_line = find_line[sel];
                    run_notepad(2, sub_argv);
                    npad_target_line = 0;
                    term_raw();
                }
            }
        }
    }
    return 0;
}


/* ── calc: single-line expression input ────────────────── */
static int run_calc(int argc, char **argv) {
    current_ms = &ms_calc;
    (void)argc; (void)argv;
    term_raw();
    char line[80]; int llen = 0;
    int has_result = 0; int result = 0;
    /* Calc reuses the sheet's formula engine, which references
     * `cell[][]`. Zero-init keeps cell refs evaluating to 0. */
    mset(cell, 0, sizeof cell);
    while (1) {
        paint_desktop();
        chrome("Calc");
        body_clear();
        body_at(2, 3, "Expression (e.g. 2*(3+4) or =5+6):", SCREEN_W - 4);
        cup(2, 5);
        sgrbgfg(15, 0);
        fbs(" "); fbw(line, llen); fbs(" ");
        blanks(40 - llen);
        if (has_result) {
            cup(2, 7);
            sgrbgfg(COL_BAR_BG, 22);
            fbs(" = ");
            char r[16]; int rn = itoa_(result, r);
            fbw(r, rn);
        }
        status("  enter compute | ^V paste | q back");
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, ami = menu_activation(k, n);
        if (ami >= 0) act = menu_run(&ms_calc, ami);
        if (act == MA_ABOUT) {
            show_about("Calc");
            continue;
        }
        if (act == MA_QUIT) break;
        if (act > 0) k[0] = (unsigned char)act;

        if (k[0] == 'q' && llen == 0) break;
        if (k[0] == 0x16) {                                /* ^V paste */
            for (int i = 0; i < cb_n && llen < 79; i++)
                if (cb[i] >= 32 && cb[i] < 127) line[llen++] = cb[i];
            continue;
        }
        if (k[0] == '\r' || k[0] == '\n') {
            line[llen] = 0;
            fp = (line[0] == '=') ? line + 1 : line;
            result = feval_expr(8);
            has_result = 1;
            continue;
        }
        if (k[0] == 0x7f || k[0] == 8) { if (llen) llen--; continue; }
        if (k[0] >= 32 && k[0] < 127 && llen < 79) line[llen++] = (char)k[0];
    }
    return 0;
}


/* ── mines: 16x16 Minesweeper ─────────────────────────── */
#define M_W 16
#define M_H 16
#define M_COUNT 40

/* per-cell bits: 0x10=mine, 0x20=revealed, 0x40=flagged, low4=neighbours */
static unsigned char m_grid[M_H][M_W];
static int m_cx, m_cy, m_lost, m_won, m_first;

static unsigned long rdtsc_(void) {
    unsigned int hi, lo;
    __asm__ volatile ("rdtsc" : "=a"(lo), "=d"(hi));
    return ((unsigned long)hi << 32) | lo;
}

static void mines_layout(int avoid_r, int avoid_c) {
    unsigned long s = rdtsc_();
    int placed = 0;
    while (placed < M_COUNT) {
        s = s * 6364136223846793005UL + 1442695040888963407UL;
        int idx = (int)((s >> 16) % (M_W * M_H));
        int r = idx / M_W, c = idx % M_W;
        if (r == avoid_r && c == avoid_c) continue;
        if (m_grid[r][c] & 0x10) continue;
        m_grid[r][c] |= 0x10;
        placed++;
    }
    for (int r = 0; r < M_H; r++)
        for (int c = 0; c < M_W; c++) {
            if (m_grid[r][c] & 0x10) continue;
            int n = 0;
            for (int dr = -1; dr <= 1; dr++)
                for (int dc = -1; dc <= 1; dc++) {
                    int nr = r + dr, nc = c + dc;
                    if (nr < 0 || nr >= M_H || nc < 0 || nc >= M_W) continue;
                    if (m_grid[nr][nc] & 0x10) n++;
                }
            m_grid[r][c] |= (unsigned char)n;
        }
}

static void mines_init(void) {
    mset(m_grid, 0, sizeof m_grid);
    m_lost = 0; m_won = 0; m_first = 1;
    m_cx = M_W / 2; m_cy = M_H / 2;
}

/* Iterative flood-fill via a local queue (avoids deep recursion). */
static void mines_reveal(int r0, int c0) {
    static unsigned short q[M_W * M_H];
    int head = 0, tail = 0;
    q[tail++] = (unsigned short)(r0 * M_W + c0);
    while (head < tail) {
        int idx = q[head++];
        int r = idx / M_W, c = idx % M_W;
        if (m_grid[r][c] & 0x20) continue;
        if (m_grid[r][c] & 0x40) continue;
        m_grid[r][c] |= 0x20;
        if (m_grid[r][c] & 0x10) { m_lost = 1; return; }
        if ((m_grid[r][c] & 0x0f) == 0) {
            for (int dr = -1; dr <= 1; dr++)
                for (int dc = -1; dc <= 1; dc++) {
                    int nr = r + dr, nc = c + dc;
                    if (nr < 0 || nr >= M_H || nc < 0 || nc >= M_W) continue;
                    if (m_grid[nr][nc] & 0x20) continue;
                    q[tail++] = (unsigned short)(nr * M_W + nc);
                }
        }
    }
}

static void mines_check_win(void) {
    int unrevealed = 0;
    for (int r = 0; r < M_H; r++)
        for (int c = 0; c < M_W; c++)
            if (!(m_grid[r][c] & 0x20)) unrevealed++;
    if (unrevealed == M_COUNT) m_won = 1;
}

static int run_mines(int argc, char **argv) {
    current_ms = &ms_mines;
    (void)argc; (void)argv;
    mines_init();
    term_raw();
    while (1) {
        paint_desktop();
        chrome("Mines");
        body_clear();
        for (int r = 0; r < M_H; r++) {
            cup(2, 3 + r);
            for (int c = 0; c < M_W; c++) {
                int sel = (r == m_cy && c == m_cx);
                unsigned char g = m_grid[r][c];
                if (g & 0x20) {
                    if (g & 0x10) {
                        sgrbgfg(sel ? 15 : 7, 88);
                        fbs("*");
                    } else {
                        int nb = g & 0x0f;
                        sgrbgfg(sel ? 15 : 8, nb ? 16 + nb : 8);
                        char ch = nb ? (char)('0' + nb) : ' ';
                        fbw(&ch, 1);
                    }
                } else if (g & 0x40) {
                    sgrbgfg(sel ? 15 : 7, 196);
                    fbs("F");
                } else {
                    sgrbgfg(sel ? 15 : 8, 0);
                    fbs(".");
                }
                fbs(" ");
            }
        }
        sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        const char *s = m_lost ? "  BOOM — r reset | q back"
                       : m_won  ? "  YOU WIN — r reset | q back"
                                : "  arrows | space reveal | f flag | r reset | q back";
        status(s);
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, ami = menu_activation(k, n);
        if (ami >= 0) act = menu_run(&ms_mines, ami);
        if (act == MA_ABOUT) {
            show_about("Mines");
            continue;
        }
        if (act == MA_QUIT) break;
        if (act == MA_RESET) { mines_init(); continue; }

        if (k[0] == 'q') break;
        if (k[0] == 'r') { mines_init(); continue; }
        if (m_lost || m_won) continue;
        if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
            if (k[2] == 'A' && m_cy > 0) m_cy--;
            if (k[2] == 'B' && m_cy < M_H - 1) m_cy++;
            if (k[2] == 'C' && m_cx < M_W - 1) m_cx++;
            if (k[2] == 'D' && m_cx > 0) m_cx--;
            continue;
        }
        if (k[0] == ' ') {
            if (m_first) { mines_layout(m_cy, m_cx); m_first = 0; }
            mines_reveal(m_cy, m_cx);
            mines_check_win();
        }
        if (k[0] == 'f') {
            if (!(m_grid[m_cy][m_cx] & 0x20))
                m_grid[m_cy][m_cx] ^= 0x40;
        }
    }
    return 0;
}


/* ── ask: dual-pane LLM chat (HTTPS via execve curl) ─────
 *
 * Layout:
 *   row 0       title bar
 *   row 1       menu bar
 *   rows 2..N-4 history (alternating you>/ai>, hard-wrap)
 *   row N-3     thin grey separator
 *   row N-2     single-line input (horizontal scroll)
 *   row N-1     status
 *
 * The conversation is sent to an OpenAI-compatible endpoint
 *   POST <endpoint>
 *   Authorization: Bearer <api_key>
 *   { "model": "<model>", "messages": [...] }
 * via fork+execve("curl"). The response goes to /tmp/office7_resp.json;
 * we slurp it back and grep "content":"..." for the assistant's reply.
 */

#define ASK_CONF       "office7.conf"
#define ASK_REQ_FILE   "/tmp/office7_req.json"
#define ASK_RESP_FILE  "/tmp/office7_resp.json"
#define ASK_INPUT_CAP  4096
#define ASK_MAX_MSGS   64
#define ASK_BUF_CAP    16384
#define ASK_KEY_CAP    256
#define ASK_URL_CAP    256
#define ASK_MODEL_CAP  64
#define ASK_REQ_CAP    20480
#define ASK_RESP_CAP   20480

static char ask_api_key[ASK_KEY_CAP];
static char ask_endpoint[ASK_URL_CAP] =
    "https://api.openai.com/v1/chat/completions";
static char ask_model[ASK_MODEL_CAP] = "gpt-4o-mini";

static char ask_buf[ASK_BUF_CAP];
static int  ask_buf_use;
static int  ask_msg_off[ASK_MAX_MSGS];
static int  ask_msg_len[ASK_MAX_MSGS];
static int  ask_msg_role[ASK_MAX_MSGS];   /* 0=user, 1=assistant */
static int  ask_n_msgs;

static int sapp(char *dst, int at, const char *s) {
    int n = slen(s);
    mcpy(dst + at, s, n);
    return at + n;
}

static void ask_msg_add(int role, const char *text, int tlen) {
    if (tlen > ASK_BUF_CAP - 16) tlen = ASK_BUF_CAP - 16;
    /* drop oldest until it fits */
    while ((ask_buf_use + tlen > ASK_BUF_CAP || ask_n_msgs >= ASK_MAX_MSGS)
            && ask_n_msgs > 0) {
        int dlen = ask_msg_len[0];
        for (int i = 0; i < ask_buf_use - dlen; i++)
            ask_buf[i] = ask_buf[i + dlen];
        ask_buf_use -= dlen;
        for (int i = 1; i < ask_n_msgs; i++) {
            ask_msg_off[i-1]  = ask_msg_off[i] - dlen;
            ask_msg_len[i-1]  = ask_msg_len[i];
            ask_msg_role[i-1] = ask_msg_role[i];
        }
        ask_n_msgs--;
    }
    ask_msg_off[ask_n_msgs]  = ask_buf_use;
    ask_msg_len[ask_n_msgs]  = tlen;
    ask_msg_role[ask_n_msgs] = role;
    mcpy(ask_buf + ask_buf_use, text, tlen);
    ask_buf_use += tlen;
    ask_n_msgs++;
}

/* line-oriented "key=value" lookup. */
static int ask_conf_find(const char *txt, int tn, const char *key,
                         char *out, int cap) {
    int klen = slen(key);
    for (int i = 0; i < tn; i++) {
        if (i != 0 && txt[i-1] != '\n') continue;
        int j = 0;
        while (j < klen && i + j < tn && txt[i+j] == key[j]) j++;
        if (j == klen && i + j < tn && txt[i+j] == '=') {
            int k = i + j + 1, o = 0;
            while (k < tn && txt[k] != '\n' && o < cap - 1) out[o++] = txt[k++];
            out[o] = 0;
            return 1;
        }
    }
    return 0;
}

static void ask_load_conf(void) {
    int fd = (int)op(ASK_CONF, O_RDONLY, 0);
    if (fd < 0) return;
    static char tmp[4096];
    int n = (int)rd(fd, tmp, sizeof tmp - 1);
    cl(fd);
    if (n <= 0) return;
    tmp[n] = 0;
    ask_conf_find(tmp, n, "api_key",  ask_api_key,  sizeof ask_api_key);
    ask_conf_find(tmp, n, "endpoint", ask_endpoint, sizeof ask_endpoint);
    ask_conf_find(tmp, n, "model",    ask_model,    sizeof ask_model);
}

static void ask_save_conf(void) {
    int fd = (int)op(ASK_CONF, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) return;
    static char tmp[ASK_KEY_CAP + ASK_URL_CAP + ASK_MODEL_CAP + 64];
    int n = 0;
    n = sapp(tmp, n, "api_key=");  n = sapp(tmp, n, ask_api_key);
    tmp[n++] = '\n';
    n = sapp(tmp, n, "endpoint="); n = sapp(tmp, n, ask_endpoint);
    tmp[n++] = '\n';
    n = sapp(tmp, n, "model=");    n = sapp(tmp, n, ask_model);
    tmp[n++] = '\n';
    wr(fd, tmp, n);
    cl(fd);
}

static int ask_json_esc(char *out, int at, const char *s, int n) {
    for (int i = 0; i < n; i++) {
        unsigned char c = (unsigned char)s[i];
        if      (c == '"')  { out[at++] = '\\'; out[at++] = '"'; }
        else if (c == '\\') { out[at++] = '\\'; out[at++] = '\\'; }
        else if (c == '\n') { out[at++] = '\\'; out[at++] = 'n'; }
        else if (c == '\r') { out[at++] = '\\'; out[at++] = 'r'; }
        else if (c == '\t') { out[at++] = '\\'; out[at++] = 't'; }
        else if (c < 0x20)  { /* drop */ }
        else                { out[at++] = (char)c; }
    }
    return at;
}

static int ask_build_request(char *out, int cap) {
    (void)cap;
    int at = 0;
    at = sapp(out, at, "{\"model\":\"");
    at = ask_json_esc(out, at, ask_model, slen(ask_model));
    at = sapp(out, at, "\",\"messages\":[");
    for (int i = 0; i < ask_n_msgs; i++) {
        if (i > 0) out[at++] = ',';
        at = sapp(out, at, "{\"role\":\"");
        at = sapp(out, at, ask_msg_role[i] ? "assistant" : "user");
        at = sapp(out, at, "\",\"content\":\"");
        at = ask_json_esc(out, at, ask_buf + ask_msg_off[i], ask_msg_len[i]);
        at = sapp(out, at, "\"}");
    }
    at = sapp(out, at, "]}");
    return at;
}

/* Find first "content":"..." string in JSON, decoding \" \n \t \\ \/ \uXXXX. */
static int ask_extract_content(const char *src, int sn, char *out, int cap) {
    static const char needle[] = "\"content\":";
    int nl = (int)sizeof needle - 1;
    for (int i = 0; i + nl < sn; i++) {
        int j = 0;
        while (j < nl && src[i+j] == needle[j]) j++;
        if (j != nl) continue;
        int k = i + nl;
        while (k < sn && (src[k] == ' ' || src[k] == '\t' || src[k] == '\n')) k++;
        if (k >= sn || src[k] != '"') continue;
        k++;
        int o = 0;
        while (k < sn && o < cap - 1) {
            char c = src[k];
            if (c == '"') { out[o] = 0; return o; }
            if (c == '\\' && k + 1 < sn) {
                char e = src[k+1];
                if      (e == 'n')  { out[o++] = '\n'; k += 2; }
                else if (e == 't')  { out[o++] = '\t'; k += 2; }
                else if (e == 'r')  { k += 2; }
                else if (e == '"')  { out[o++] = '"';  k += 2; }
                else if (e == '\\') { out[o++] = '\\'; k += 2; }
                else if (e == '/')  { out[o++] = '/';  k += 2; }
                else if (e == 'u')  { out[o++] = '?';  k += 6; }
                else                { out[o++] = e;    k += 2; }
            } else {
                out[o++] = c; k++;
            }
        }
        out[o] = 0;
        return o;
    }
    return -1;
}

static int ask_extract_error(const char *src, int sn, char *out, int cap) {
    static const char needle[] = "\"message\":";
    int nl = (int)sizeof needle - 1;
    for (int i = 0; i + nl < sn; i++) {
        int j = 0;
        while (j < nl && src[i+j] == needle[j]) j++;
        if (j != nl) continue;
        int k = i + nl;
        while (k < sn && (src[k] == ' ' || src[k] == '\t' || src[k] == '\n')) k++;
        if (k >= sn || src[k] != '"') continue;
        k++;
        int o = 0;
        while (k < sn && src[k] != '"' && o < cap - 1) {
            if (src[k] == '\\' && k + 1 < sn) k += 2;
            else out[o++] = src[k++];
        }
        out[o] = 0;
        return o;
    }
    return -1;
}

static int ask_call_curl(void) {
    int fd = (int)op(ASK_REQ_FILE, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) return -1;
    static char req[ASK_REQ_CAP];
    int rn = ask_build_request(req, sizeof req);
    wr(fd, req, rn);
    cl(fd);

    static char auth[ASK_KEY_CAP + 32];
    int an = 0;
    an = sapp(auth, an, "Authorization: Bearer ");
    an = sapp(auth, an, ask_api_key);
    auth[an] = 0;

    char *argv_[16];
    int ai = 0;
    argv_[ai++] = (char *)"curl";
    argv_[ai++] = (char *)"-sS";
    argv_[ai++] = (char *)"-X"; argv_[ai++] = (char *)"POST";
    argv_[ai++] = (char *)"-H"; argv_[ai++] = (char *)"Content-Type: application/json";
    argv_[ai++] = (char *)"-H"; argv_[ai++] = auth;
    argv_[ai++] = (char *)"--data-binary";
    argv_[ai++] = (char *)"@" ASK_REQ_FILE;
    argv_[ai++] = (char *)"-o"; argv_[ai++] = (char *)ASK_RESP_FILE;
    argv_[ai++] = ask_endpoint;
    argv_[ai++] = 0;

    long pid = forkk();
    if (pid < 0) return -1;
    if (pid == 0) {
        execvee("/usr/bin/curl",       argv_, g_envp);
        execvee("/bin/curl",           argv_, g_envp);
        execvee("/usr/local/bin/curl", argv_, g_envp);
        qu(127);
    }
    int status = 0;
    wait4_(&status);
    return 0;
}

static void ask_render_history(int hist_top, int hist_h) {
    int line_w = SCREEN_W - 4 - 5;     /* width minus role prefix */

    /* count wrapped lines first so we can scroll-pin to bottom */
    int total = 0;
    for (int i = 0; i < ask_n_msgs; i++) {
        int tlen = ask_msg_len[i];
        if (tlen == 0) { total++; continue; }
        int pos = 0;
        while (pos < tlen) {
            int rem = tlen - pos;
            int take = rem < line_w ? rem : line_w;
            int nl = -1;
            for (int k = 0; k < take; k++)
                if (ask_buf[ask_msg_off[i] + pos + k] == '\n') { nl = k; break; }
            if (nl >= 0) take = nl;
            total++;
            pos += take;
            if (nl >= 0) pos++;
        }
    }
    int skip = total > hist_h ? total - hist_h : 0;
    int line = 0, row = 0;

    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    for (int i = 0; i < ask_n_msgs && row < hist_h; i++) {
        const char *prefix = ask_msg_role[i] ? "ai>  " : "you> ";
        int role = ask_msg_role[i];
        int tlen = ask_msg_len[i];
        int first = 1, pos = 0;
        if (tlen == 0) {
            if (line >= skip) {
                cup(2, hist_top + row);
                sgrbgfg(COL_BAR_BG, role ? 24 : COL_BAR_FG);
                fbw(prefix, 5);
                sgrbgfg(COL_BAR_BG, COL_BAR_FG);
                blanks(line_w);
                row++;
            }
            line++;
            continue;
        }
        while (pos < tlen && row < hist_h) {
            int rem = tlen - pos;
            int take = rem < line_w ? rem : line_w;
            int nl = -1;
            for (int k = 0; k < take; k++)
                if (ask_buf[ask_msg_off[i] + pos + k] == '\n') { nl = k; break; }
            if (nl >= 0) take = nl;
            if (line >= skip) {
                cup(2, hist_top + row);
                sgrbgfg(COL_BAR_BG, role ? 24 : COL_BAR_FG);
                if (first) fbw(prefix, 5); else fbw("     ", 5);
                sgrbgfg(COL_BAR_BG, COL_BAR_FG);
                fbw(ask_buf + ask_msg_off[i] + pos, take);
                blanks(line_w - take);
                row++;
            }
            line++;
            pos += take;
            if (nl >= 0) pos++;
            first = 0;
        }
    }
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    while (row < hist_h) {
        cup(2, hist_top + row);
        blanks(SCREEN_W - 4);
        row++;
    }
}

static void ask_settings_modal(void) {
    int sel = 0;
    char *fields[3] = { ask_api_key, ask_endpoint, ask_model };
    int   caps[3]   = { ASK_KEY_CAP, ASK_URL_CAP, ASK_MODEL_CAP };
    static const char *labels[3] = { "API key  ", "Endpoint ", "Model    " };
    int editing = 0;

    while (1) {
        paint_desktop();
        chrome("Ask · Settings");
        body_clear();
        body_at(2, 3, "Edit OpenAI-compatible chat settings.", SCREEN_W - 4);
        body_at(2, 4, "Up/Down select; ENTER edit; ESC save+close.",
                SCREEN_W - 4);
        for (int i = 0; i < 3; i++) {
            cup(2, 6 + i * 2);
            sgrbgfg(COL_BAR_BG, COL_BAR_FG);
            if (i == sel && !editing) sgrbgfg(15, 0);
            if (i == sel &&  editing) sgrbgfg(0, 15);
            fbw(labels[i], slen(labels[i]));
            sgrbgfg(COL_BAR_BG, COL_BAR_FG);
            fbw(": ", 2);
            int sl = slen(fields[i]);
            int max = SCREEN_W - 4 - slen(labels[i]) - 2;
            if (i == 0 && !editing) {
                if (sl > 0) {
                    int show = sl < 6 ? sl : 6;
                    for (int j = 0; j < sl - show; j++) fbw("*", 1);
                    fbw(fields[i] + sl - show, show);
                    blanks(max - sl);
                } else {
                    blanks(max);
                }
            } else if (sl > max) {
                fbw("...", 3);
                fbw(fields[i] + (sl - max + 3), max - 3);
            } else {
                fbw(fields[i], sl);
                blanks(max - sl);
            }
        }
        status(editing ? "type ... ENTER done | ESC cancel"
                       : "UP/DOWN select | ENTER edit | ESC save+close");
        fbflush();

        unsigned char k[16];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        if (!editing) {
            if (k[0] == 0x1b && n == 1) { ask_save_conf(); return; }
            if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
                if (k[2] == 'A' && sel > 0) sel--;
                if (k[2] == 'B' && sel < 2) sel++;
            }
            if (k[0] == '\r' || k[0] == '\n') editing = 1;
        } else {
            if (k[0] == '\r' || k[0] == '\n') { editing = 0; continue; }
            if (k[0] == 0x1b && n == 1)        { editing = 0; continue; }
            if (k[0] == 0x7f || k[0] == 8) {
                int sl = slen(fields[sel]);
                if (sl > 0) fields[sel][sl - 1] = 0;
                continue;
            }
            if (k[0] >= 32 && k[0] < 127) {
                int sl = slen(fields[sel]);
                if (sl < caps[sel] - 1) {
                    fields[sel][sl] = (char)k[0];
                    fields[sel][sl + 1] = 0;
                }
            }
        }
    }
}

static int run_ask(int argc, char **argv) {
    (void)argc; (void)argv;
    current_ms = &ms_ask;
    ask_load_conf();

    static char input[ASK_INPUT_CAP];
    int inlen = 0;
    static char errmsg[256];
    errmsg[0] = 0;

    term_raw();
    int hist_top = 2;
    int hist_h   = SCREEN_H - 5;

    while (1) {
        paint_desktop();
        chrome("Ask");
        body_clear();
        ask_render_history(hist_top, hist_h);

        cup(0, SCREEN_H - 3);
        sgrbgfg(COL_BAR_BG, 8);
        for (int x = 0; x < SCREEN_W; x++) fbs("-");

        cup(0, SCREEN_H - 2);
        sgrbgfg(15, 0);
        fbs(" > ");
        int max_show = SCREEN_W - 4;
        int show_from = inlen > max_show ? inlen - max_show : 0;
        fbw(input + show_from, inlen - show_from);
        blanks(max_show - (inlen - show_from));

        sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        if (errmsg[0]) {
            sgrbgfg(COL_BAR_BG, 88);
            status(errmsg);
            sgrbgfg(COL_BAR_BG, COL_BAR_FG);
            errmsg[0] = 0;
        } else if (!ask_api_key[0]) {
            status("no api_key set — File > Settings (Alt+F)");
        } else {
            status("ENTER send | ^N clear | ^E settings | ^Q quit");
        }
        fbflush();

        unsigned char k[64];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, ami = menu_activation(k, n);
        if (ami >= 0) act = menu_run(&ms_ask, ami);
        if (act == MA_ABOUT)    { show_about("Ask"); continue; }
        if (act == MA_QUIT)     break;
        if (act == MA_NEW)      { ask_n_msgs = 0; ask_buf_use = 0; continue; }
        if (act == MA_SETTINGS) { ask_settings_modal(); continue; }

        if (k[0] == 0x11) break;                                     /* ^Q */
        if (k[0] == 0x0e) { ask_n_msgs = 0; ask_buf_use = 0; continue; } /* ^N */
        if (k[0] == 0x05) { ask_settings_modal(); continue; }            /* ^E */

        if (k[0] == '\r' || k[0] == '\n') {
            if (inlen == 0) continue;
            if (!ask_api_key[0]) {
                int el = sapp(errmsg, 0, "no api_key set — open Settings");
                errmsg[el] = 0;
                continue;
            }
            ask_msg_add(0, input, inlen);
            inlen = 0;
            input[0] = 0;

            paint_desktop();
            chrome("Ask");
            body_clear();
            ask_render_history(hist_top, hist_h);
            cup(0, SCREEN_H - 3);
            sgrbgfg(COL_BAR_BG, 8);
            for (int x = 0; x < SCREEN_W; x++) fbs("-");
            cup(0, SCREEN_H - 2);
            sgrbgfg(15, 0);
            fbs(" > ");
            blanks(SCREEN_W - 3);
            sgrbgfg(COL_BAR_BG, COL_BAR_FG);
            status("sending ...");
            fbflush();

            int rc = ask_call_curl();

            static char resp[ASK_RESP_CAP];
            int rn = -1;
            int fd = (int)op(ASK_RESP_FILE, O_RDONLY, 0);
            if (fd >= 0) {
                rn = (int)rd(fd, resp, sizeof resp - 1);
                cl(fd);
            }
            if (rc < 0 || rn < 0) {
                int el = sapp(errmsg, 0,
                              "curl failed — install curl or check network");
                errmsg[el] = 0;
            } else {
                resp[rn] = 0;
                static char content[ASK_BUF_CAP];
                int cn = ask_extract_content(resp, rn, content, sizeof content);
                if (cn >= 0) {
                    ask_msg_add(1, content, cn);
                } else {
                    static char emsg[256];
                    int en = ask_extract_error(resp, rn, emsg, sizeof emsg);
                    if (en > 0) {
                        int p = sapp(errmsg, 0, "api: ");
                        for (int i = 0; i < en && p < (int)sizeof errmsg - 1; i++)
                            errmsg[p++] = emsg[i];
                        errmsg[p] = 0;
                    } else {
                        int el = sapp(errmsg, 0, "no content in response");
                        errmsg[el] = 0;
                    }
                }
            }
            continue;
        }
        if (k[0] == 0x7f || k[0] == 8) {
            if (inlen > 0) inlen--;
            input[inlen] = 0;
            continue;
        }
        if (k[0] == 0x16) {                  /* ^V paste from suite clipboard */
            int avail = ASK_INPUT_CAP - 1 - inlen;
            int take = cb_n < avail ? cb_n : avail;
            mcpy(input + inlen, cb, take);
            inlen += take;
            input[inlen] = 0;
            continue;
        }
        if (k[0] >= 32 && k[0] < 127 && inlen < ASK_INPUT_CAP - 1) {
            input[inlen++] = (char)k[0];
            input[inlen] = 0;
        }
    }

    term_cooked();
    return 0;
}


/* ── garden: interactive-evolution colour/layout breeder ──
 *
 * 64 Genome instances (1 KB total) shown as an 8x8 grid of
 * thumbnails. The user marks favourites with SPACE and ENTER
 * advances the generation: marked genomes survive, unmarked
 * slots are filled by uniform crossover of two random marked
 * parents, then per-byte mutation. P previews the cursor's
 * genome full-screen with the suite chrome painted in those
 * colours. S saves the population to ./garden.bin (1024 B);
 * the file is auto-loaded on next launch.
 *
 * Layout: default 80x24 packs 8x8 thumbs at 10 cols x 3 rows
 * each, no chrome. If TIOCGWINSZ reports a larger terminal we
 * grow each thumb up to the available cell budget and reserve
 * the spare rows for a top status line + bottom help line.
 */

/* TIOCGWINSZ + struct winsize hoisted to the top of the file (the
 * suite-wide term_init() needs them) — garden's own resize-aware
 * loop still calls io(0, TIOCGWINSZ, ...) below for live resizes. */

#define GARDEN_FILE  "garden.bin"
#define GARDEN_MAGIC 0x47524431u   /* "GRD1" little-endian */

static struct Genome g_pop[64];
static unsigned long long g_marked;     /* 1 bit per slot */
static int g_generation;

static unsigned long long g_rng_state;

static unsigned long long garden_rdtsc(void) {
    unsigned long h, l;
    __asm__ volatile ("rdtsc" : "=d"(h), "=a"(l));
    return ((unsigned long long)h << 32) | l;
}
static void garden_rng_seed_if_unset(void) {
    if (!g_rng_state) g_rng_state = garden_rdtsc() | 1ULL;
}
static unsigned int garden_rng(void) {
    g_rng_state = g_rng_state * 6364136223846793005ULL +
                  1442695040888963407ULL;
    return (unsigned int)(g_rng_state >> 32);
}

static void garden_random_genome(struct Genome *g) {
    /* Pick from a pleasing palette range so initial pop isn't all neon. */
    g->title_bg     = (unsigned char)(garden_rng() & 0xff);
    g->title_fg     = (unsigned char)(garden_rng() & 0xff);
    g->bar_bg       = (unsigned char)(garden_rng() & 0xff);
    g->bar_fg       = (unsigned char)(garden_rng() & 0xff);
    g->desktop      = (unsigned char)(garden_rng() & 0xff);
    g->select_bg    = (unsigned char)(garden_rng() & 0xff);
    g->select_fg    = (unsigned char)(garden_rng() & 0xff);
    g->shadow_bg    = (unsigned char)(garden_rng() & 0xff);
    g->shadow_fg    = (unsigned char)(garden_rng() & 0xff);
    g->accent       = (unsigned char)(garden_rng() & 0xff);
    g->clock_corner = (unsigned char)(garden_rng() & 3);
    g->show_clock   = (unsigned char)(garden_rng() & 1);
    g->border       = (unsigned char)(garden_rng() & 3);
    g->menu_under   = (unsigned char)(garden_rng() & 1);
    g->reserved[0]  = 0;
    g->reserved[1]  = 0;
}

static void garden_init_pop(void) {
    garden_rng_seed_if_unset();
    for (int i = 0; i < 64; i++) garden_random_genome(&g_pop[i]);
    /* Seed slot 0 with the office6 defaults so the user always has
     * a "boring but recognisable" starting point to breed from. */
    g_pop[0] = (struct Genome){
        21, 15, 7, 0, 30, 15, 0, 0, 8, 21, 1, 0, 0, 1, {0, 0}
    };
    g_marked = 0;
    g_generation = 0;
}

static void garden_mutate(struct Genome *g) {
    unsigned char *b = (unsigned char *)g;
    int n = (int)sizeof *g;
    for (int i = 0; i < n; i++) {
        unsigned int r = garden_rng();
        if ((r & 0xff) < 24) {                /* ~9% per byte mutates */
            if (i <= 9) {                     /* colour bytes drift */
                int delta = (int)((r >> 8) & 7) - 3;   /* -3..+3 */
                b[i] = (unsigned char)((int)b[i] + delta);
            } else if (i == 10) {             /* clock_corner 0..3 */
                b[i] = (unsigned char)((r >> 8) & 3);
            } else if (i == 11 || i == 13) {  /* booleans */
                b[i] ^= 1;
            } else if (i == 12) {             /* border 0..3 */
                b[i] = (unsigned char)((r >> 8) & 3);
            }
        }
    }
}

static void garden_breed(void) {
    int parents[64], np = 0;
    for (int i = 0; i < 64; i++)
        if ((g_marked >> i) & 1) parents[np++] = i;
    if (np == 0) return;

    struct Genome next[64];
    for (int i = 0; i < 64; i++) {
        if ((g_marked >> i) & 1) {
            next[i] = g_pop[i];               /* survive untouched */
            continue;
        }
        int a = parents[garden_rng() % np];
        int b = parents[garden_rng() % np];
        unsigned char *pa = (unsigned char *)&g_pop[a];
        unsigned char *pb = (unsigned char *)&g_pop[b];
        unsigned char *po = (unsigned char *)&next[i];
        unsigned int mask = garden_rng();
        for (int k = 0; k < (int)sizeof next[i]; k++) {
            po[k] = (mask & 1) ? pa[k] : pb[k];
            mask >>= 1;
            if (k % 32 == 31) mask = garden_rng();
        }
        garden_mutate(&next[i]);
    }
    for (int i = 0; i < 64; i++) g_pop[i] = next[i];
    g_marked = 0;
    g_generation++;
}

static int garden_save(void) {
    int fd = (int)op(GARDEN_FILE, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return -1;
    unsigned int hdr[4];
    hdr[0] = GARDEN_MAGIC;
    hdr[1] = (unsigned int)g_generation;
    hdr[2] = (unsigned int)(g_marked & 0xffffffffu);
    hdr[3] = (unsigned int)(g_marked >> 32);
    wr(fd, hdr, sizeof hdr);
    wr(fd, g_pop, sizeof g_pop);
    cl(fd);
    return 0;
}

static int garden_load(void) {
    int fd = (int)op(GARDEN_FILE, O_RDONLY, 0);
    if (fd < 0) return 0;
    unsigned int hdr[4];
    long n = rd(fd, hdr, sizeof hdr);
    if (n != (long)sizeof hdr || hdr[0] != GARDEN_MAGIC) {
        cl(fd); return 0;
    }
    n = rd(fd, g_pop, sizeof g_pop);
    cl(fd);
    if (n != (long)sizeof g_pop) return 0;
    g_generation = (int)hdr[1];
    g_marked = (unsigned long long)hdr[2] | ((unsigned long long)hdr[3] << 32);
    return 1;
}

static int garden_term_size(int *cols, int *rows) {
    struct winsize ws = { 0, 0, 0, 0 };
    long r = io(0, TIOCGWINSZ, &ws);
    if (r < 0 || ws.ws_col == 0 || ws.ws_row == 0) {
        *cols = 80; *rows = 24; return 0;
    }
    *cols = ws.ws_col; *rows = ws.ws_row;
    return 1;
}

/* Render one thumbnail at screen pos (x,y), w x h cells.
 * w is at least 10, h at least 3. The cursor and marked flags
 * draw distinguishing borders. */
static void garden_render_thumb(int idx, int x, int y, int w, int h,
                                int is_cursor, int is_marked) {
    struct Genome *g = &g_pop[idx];
    static const char border_chars[4] = { '-', '=', '_', '~' };
    char bc = border_chars[g->border & 3];

    /* row 0: title bar */
    cup(x, y);
    sgrbgfg(g->title_bg, g->title_fg);
    fbs(" O7");
    int slots = w - 6;
    for (int i = 0; i < slots; i++) fbw(" ", 1);
    fbs("_X ");

    /* row 1: menu bar — always exactly 1 row */
    cup(x, y + 1);
    sgrbgfg(g->bar_bg, g->bar_fg);
    if (w >= 10) {
        fbs(" F E V H");
        blanks(w - 8);
    } else {
        fbs(" FEVH");
        blanks(w - 5);
    }

    /* rows 2..h-2: desktop body */
    for (int r = 2; r < h - 1; r++) {
        cup(x, y + r);
        sgrbg(g->desktop);
        blanks(w);
    }
    /* clock pip — only in body rows, so hidden in MVP h=3 thumbs */
    if (g->show_clock && h >= 4) {
        int cx = x + ((g->clock_corner & 1) ? w - 6 : 1);
        int cy = y + ((g->clock_corner & 2) ? h - 2 : 2);
        cup(cx, cy);
        sgrbgfg(g->desktop, g->accent);
        fbs("12:00");
    }

    /* status row (last row) — used for marked/cursor indicators */
    cup(x, y + h - 1);
    sgrbgfg(g->bar_bg, g->bar_fg);
    char bcs[2] = { bc, 0 };
    for (int i = 0; i < w; i++) fbs(bcs);

    /* overlay cursor + marked — border highlights drawn last */
    if (is_marked) {
        cup(x, y);
        sgrbgfg(226, 0);                  /* yellow bg, black fg */
        fbs("*");
    }
    if (is_cursor) {
        /* invert title row first cell as a cursor caret */
        cup(x + w - 1, y);
        sgrbgfg(15, 0);
        fbs(">");
        cup(x, y);
        sgrbgfg(15, 0);
        fbs("<");
    }
}

static void garden_render_grid(int cursor, int cols, int rows) {
    /* Compute thumb size — clip down so 8x8 fits. Reserve at most
     * 2 rows for header/footer when there's spare height. */
    int chrome_top = 0, chrome_bot = 0;
    int thumb_w = cols / 8;
    int thumb_h = rows / 8;
    if (thumb_w < 10) thumb_w = 10;
    if (thumb_h < 3)  thumb_h = 3;
    if (thumb_w * 8 > cols) thumb_w = cols / 8;
    if (thumb_h * 8 > rows) thumb_h = rows / 8;
    if (thumb_w < 10) thumb_w = 10;       /* MVP minimum */
    if (thumb_h < 3)  thumb_h = 3;

    if (rows >= 8 * thumb_h + 2) { chrome_top = 1; chrome_bot = 1; }

    /* Optional top chrome */
    if (chrome_top) {
        cup(0, 0);
        sgrbgfg(COL_TITLE_BG, COL_TITLE_FG);
        fbs(" Garden — interactive evolution");
        char buf[32];
        int bn = sapp(buf, 0, "  gen ");
        bn += utoa((unsigned)g_generation, buf + bn);
        bn = sapp(buf, bn, "  ");
        int marks = 0;
        for (int i = 0; i < 64; i++) if ((g_marked >> i) & 1) marks++;
        bn += utoa((unsigned)marks, buf + bn);
        bn = sapp(buf, bn, " marked");
        buf[bn] = 0;
        fbw(buf, bn);
        blanks(cols - 32 - bn);
    }

    int origin_y = chrome_top ? 1 : 0;
    int origin_x = (cols - thumb_w * 8) / 2;
    if (origin_x < 0) origin_x = 0;

    for (int gy = 0; gy < 8; gy++) {
        for (int gx = 0; gx < 8; gx++) {
            int idx = gy * 8 + gx;
            int marked = (int)((g_marked >> idx) & 1);
            int is_cursor = (idx == cursor);
            garden_render_thumb(idx,
                                origin_x + gx * thumb_w,
                                origin_y + gy * thumb_h,
                                thumb_w, thumb_h,
                                is_cursor, marked);
        }
    }

    if (chrome_bot) {
        cup(0, rows - 1);
        sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        fbs(" SPC mark | ENT breed | P preview | V view | R random | "
            "S save | Q quit");
        /* Hint is 73 cols.  Pre-office8 this called blanks(cols),
         * wrapping 73 spaces onto the row below. */
        blanks(cols > 73 ? cols - 73 : 0);
    }
}

/* Render the preview screen using whatever's in g_genome and wait
 * for one keystroke. Caller is responsible for genome bookkeeping;
 * called both by the in-process fallback (garden_preview) and by
 * the jailed child (run_preview_genome). */
static void garden_preview_render(const char *footer) {
    paint_desktop();
    chrome("Preview");
    body_clear();
    body_at(2, 3, "this is what the suite looks like with this genome.",
            SCREEN_W - 4);
    body_at(2, 5, "  notepad word mail sheet paint hex bfc files",
            SCREEN_W - 4);
    body_at(2, 6, "  find calc mines ask garden", SCREEN_W - 4);
    body_at(2, 8, "  Alt+F / F10 opens the menu — try it.",
            SCREEN_W - 4);
    body_at(2, 9, "  selected items use the genome's select_bg/fg.",
            SCREEN_W - 4);
    body_at(2, 11, "  press any key to return to the garden.",
            SCREEN_W - 4);
    /* draw a fake selected menu title to show the SEL colours */
    cup(0, 1);
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    fbs(" ");
    sgrbgfg(COL_SEL_BG, COL_SEL_FG);
    fbs(" File ");
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    fbs(" Edit  View  Help");
    blanks(SCREEN_W - 24);
    status(footer);
    fbflush();
    unsigned char k[8];
    read_key(k, sizeof k);
}

/* Encode a 16-byte genome into 32 lowercase hex chars + NUL. */
static void garden_genome_hex(const struct Genome *g, char *out33) {
    static const char garden_hx[] = "0123456789abcdef";
    const unsigned char *b = (const unsigned char *)g;
    for (int i = 0; i < (int)sizeof *g; i++) {
        out33[i*2]     = garden_hx[(b[i] >> 4) & 0xf];
        out33[i*2 + 1] = garden_hx[ b[i]       & 0xf];
    }
    out33[32] = 0;
}

/* Spawn the namespace jail launcher with an arbitrary office9
 * subcommand.  Used by both garden_preview_jail and garden_view_jail.
 * Returns 0 on a clean child exit, non-zero if anything broke. */
static int garden_jail_spawn(const char *subcmd, const char *hex) {
    char *jargv[] = { "./jail", "./office9",
                      (char *)subcmd, (char *)hex, 0 };
    long pid = forkk();
    if (pid < 0) return -1;
    if (pid == 0) {
        execvee("./jail", jargv, g_envp);
        qu(127);
    }
    int st = 0;
    wait4_(&st);
    return (st & 0x7f) ? -1 : 0;
}

static int garden_preview_jail(int idx) {
    char hex[33];
    garden_genome_hex(&g_pop[idx], hex);
    return garden_jail_spawn("preview-genome", hex);
}

/* Preview the cursor's genome.  Tries the namespace jail first
 * (real isolated child paints the screen); if that fails — jail
 * binary missing, kernel without unprivileged user namespaces, etc.
 * — falls back to the in-process g_genome swap so the feature still
 * works on hardened hosts. */
static void garden_preview(int idx) {
    if (garden_preview_jail(idx) == 0) return;

    struct Genome saved = g_genome;
    g_genome = g_pop[idx];
    garden_preview_render(" PREVIEW · any key returns ");
    g_genome = saved;
}

/* V key — drop the user into the suite shell with the cursor's
 * genome applied, inside a jail.  Files saved during V live inside
 * the jail dir and vanish on exit, so this is non-destructive. */
static int garden_view_jail(int idx) {
    char hex[33];
    garden_genome_hex(&g_pop[idx], hex);
    return garden_jail_spawn("view-genome", hex);
}

static void garden_view(int idx) {
    if (garden_view_jail(idx) == 0) return;
    /* Jail unavailable — degrade to the static preview so the user
     * at least sees the chrome under that genome. */
    garden_preview(idx);
}

/* `office7 preview-genome <32-hex>` — the in-jail entry point.
 * Parses 16 bytes into g_genome and renders the preview screen.
 * The parent already put the tty in raw mode and we inherit its
 * fd 0/1/2, so we don't touch tcsetattr; one read for any key,
 * then exit (the parent regains the terminal automatically). */
static int garden_hexv(int c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}
static int garden_load_genome_hex(const char *h) {
    unsigned char *g = (unsigned char *)&g_genome;
    for (int i = 0; i < (int)sizeof g_genome; i++) {
        int hi = garden_hexv(h[i*2]);
        int lo = garden_hexv(h[i*2 + 1]);
        if (hi < 0 || lo < 0) return -1;
        g[i] = (unsigned char)((hi << 4) | lo);
    }
    return 0;
}

static int run_preview_genome(int argc, char **argv) {
    if (argc < 2) return 2;
    if (garden_load_genome_hex(argv[1]) < 0) return 2;
    garden_preview_render(" PREVIEW · jailed · any key returns ");
    return 0;
}

/* `office9 view-genome <32-hex>` — the in-jail entry point for V.
 * Loads the genome and drops into run_shell, so the user can type
 * `notepad`, `sheet`, etc. and see them with the chosen colours.
 * Pressing Q in the shell tears down the jail and returns to garden. */
static int run_view_genome(int argc, char **argv) {
    if (argc < 2) return 2;
    if (garden_load_genome_hex(argv[1]) < 0) return 2;
    return run_shell(0, 0);
}

static int run_garden(int argc, char **argv) {
    (void)argc; (void)argv;
    current_ms = &ms_garden;

    if (!garden_load()) garden_init_pop();
    garden_rng_seed_if_unset();

    term_raw();
    int cursor = 0;
    int last_msg_ttl = 0;
    static char last_msg[64];
    last_msg[0] = 0;

    while (1) {
        int cols, rows;
        garden_term_size(&cols, &rows);
        cls();
        garden_render_grid(cursor, cols, rows);

        if (last_msg[0] && last_msg_ttl > 0) {
            cup(0, rows - 1);
            sgrbgfg(COL_BAR_BG, 22);
            fbs(" ");
            fbs(last_msg);
            blanks(cols - 1 - slen(last_msg));
            last_msg_ttl--;
            if (last_msg_ttl == 0) last_msg[0] = 0;
        }
        fbflush();

        unsigned char k[16];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, ami = menu_activation(k, n);
        if (ami >= 0) act = menu_run(&ms_garden, ami);
        if (act == MA_ABOUT)   { show_about("Garden"); continue; }
        if (act == MA_QUIT)    break;
        if (act == MA_SAVE)    {
            if (garden_save() == 0) {
                int ml = sapp(last_msg, 0, "saved garden.bin");
                last_msg[ml] = 0; last_msg_ttl = 1;
            }
            continue;
        }
        if (act == MA_RANDOM)  { garden_init_pop(); continue; }
        if (act == MA_BREED)   { garden_breed(); continue; }
        if (act == MA_PREVIEW) { garden_preview(cursor); continue; }
        if (act == MA_VIEW)    { garden_view(cursor); term_raw(); continue; }

        if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
            int gx = cursor % 8, gy = cursor / 8;
            switch (k[2]) {
            case 'A': if (gy > 0) cursor -= 8; break;
            case 'B': if (gy < 7) cursor += 8; break;
            case 'C': if (gx < 7) cursor++;    break;
            case 'D': if (gx > 0) cursor--;    break;
            }
            continue;
        }
        if (k[0] == ' ')              { g_marked ^= (1ULL << cursor); continue; }
        if (k[0] == '\r' || k[0] == '\n') { garden_breed(); continue; }
        if (k[0] == 'p' || k[0] == 'P') { garden_preview(cursor); continue; }
        if (k[0] == 'v' || k[0] == 'V') { garden_view(cursor); term_raw(); continue; }
        if (k[0] == 'r' || k[0] == 'R') { garden_init_pop(); continue; }
        if (k[0] == 's' || k[0] == 'S') {
            if (garden_save() == 0) {
                int ml = sapp(last_msg, 0, "saved garden.bin");
                last_msg[ml] = 0; last_msg_ttl = 1;
            }
            continue;
        }
        if (k[0] == 'l' || k[0] == 'L') {
            if (garden_load()) {
                int ml = sapp(last_msg, 0, "loaded garden.bin");
                last_msg[ml] = 0; last_msg_ttl = 1;
            }
            continue;
        }
        if (k[0] == 'q' || k[0] == 0x11) break;
    }

    term_cooked();
    return 0;
}


/* ── dispatch ─────────────────────────────────────────── */
static const char *basename_(const char *p) {
    const char *b = p;
    for (const char *q = p; *q; q++) if (*q == '/') b = q + 1;
    return b;
}

int main_c(int argc, char **argv, char **envp) {
    g_envp = envp;
    term_init();
    const char *cmd = (argc > 0) ? basename_(argv[0]) : "office";
    int sub_argc = argc;
    char **sub_argv = argv;
    if ((scmp(cmd, "office")  == 0 ||
         scmp(cmd, "office2") == 0 ||
         scmp(cmd, "office3") == 0 ||
         scmp(cmd, "office4") == 0 ||
         scmp(cmd, "office5") == 0 ||
         scmp(cmd, "office6") == 0 ||
         scmp(cmd, "office7") == 0 ||
         scmp(cmd, "office8") == 0 ||
         scmp(cmd, "office9") == 0) && argc > 1) {
        cmd = argv[1];
        sub_argv = argv + 1;
        sub_argc = argc - 1;
    }
    if (scmp(cmd, "notepad") == 0) return run_notepad(sub_argc, sub_argv);
    if (scmp(cmd, "word")    == 0) return run_word   (sub_argc, sub_argv);
    if (scmp(cmd, "mail")    == 0) return run_mail   (sub_argc, sub_argv);
    if (scmp(cmd, "sheet")   == 0) return run_sheet  (sub_argc, sub_argv);
    if (scmp(cmd, "paint")   == 0) return run_paint  (sub_argc, sub_argv);
    if (scmp(cmd, "hex")     == 0) return run_hex    (sub_argc, sub_argv);
    if (scmp(cmd, "bfc")     == 0) return run_bfc    (sub_argc, sub_argv);
    if (scmp(cmd, "files")   == 0) return run_files  (sub_argc, sub_argv);
    if (scmp(cmd, "find")    == 0) return run_find   (sub_argc, sub_argv);
    if (scmp(cmd, "calc")    == 0) return run_calc   (sub_argc, sub_argv);
    if (scmp(cmd, "mines")   == 0) return run_mines  (sub_argc, sub_argv);
    if (scmp(cmd, "ask")     == 0) return run_ask    (sub_argc, sub_argv);
    if (scmp(cmd, "garden")  == 0) return run_garden (sub_argc, sub_argv);
    if (scmp(cmd, "preview-genome") == 0) return run_preview_genome(sub_argc, sub_argv);
    if (scmp(cmd, "view-genome")    == 0) return run_view_genome   (sub_argc, sub_argv);
    return run_shell(sub_argc, sub_argv);
}


/* ── _start: read argc/argv/envp from rsp, dispatch, exit ─
 * Stack at entry: argc, argv[0..argc-1], NULL, envp[0..], NULL, ...
 * envp starts at rsp + 16 + argc*8. */
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
