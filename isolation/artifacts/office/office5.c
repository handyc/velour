/* office5.c — Win95-style 12-app suite. Linux x86_64. No libc.
 *
 *   shell  notepad  word  mail  sheet  paint  hex  bfc  files
 *   find  calc  mines
 *
 * Same apps as office4. Fixes the menu display bugs:
 *   - pulldown columns now align with their title letter (was off by
 *     1 per menu — Edit pulldown was 1 col right of "Edit", View was
 *     2 right, Help was 3 right). Per-title step is slen+2, not slen+3.
 *   - menu bar now blanks all 80 cols (was leaving 4 trailing cols of
 *     the teal desktop visible at the right end of row 1).
 *   - Alt+letter on an empty menu is now a no-op instead of silently
 *     auto-advancing to the next non-empty menu (e.g. Alt+V on notepad
 *     no longer opens Help).
 *   - menu titles for menus the current app doesn't have are dimmed
 *     in the bar (gray foreground), so the user can see Edit isn't
 *     available in paint at a glance.
 *   - status line during menu navigation reads "ESC cancel | ARROWS |
 *     ENTER select", overriding whatever the app had set.
 *   - pulldowns now have a 1-cell drop shadow on the right and bottom
 *     for that classic Win95 chrome look.
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


/* ── Win95 chrome around the active app ────────────────── */
#define COL_TITLE_BG 21
#define COL_TITLE_FG 15
#define COL_BAR_BG    7
#define COL_BAR_FG    0
#define COL_DESKTOP  30

#define SCREEN_W 80
#define SCREEN_H 24

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
        if (i == active_idx) sgrbgfg(15, 0);
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
            sgrbgfg(i == sel ? 15 : COL_BAR_BG, i == sel ? 0 : COL_BAR_FG);
            fbs(" ");
            int w = slen(items[mi][i].label);
            fbw(items[mi][i].label, w);
            blanks(max_w - w + 1);
        }
        /* drop shadow: 1-cell dark band on the right and bottom. */
        sgrbgfg(0, 8);
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
    body_at(2, 3, "office4 — Win95-style suite, no libc.", SCREEN_W - 4);
    body_at(2, 5, "  notepad word mail sheet paint hex bfc", SCREEN_W - 4);
    body_at(2, 6, "  files find calc mines", SCREEN_W - 4);
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
        body_at(2, 5, "  files  find  calc  mines  exit", SCREEN_W - 4);
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


/* ── dispatch ─────────────────────────────────────────── */
static const char *basename_(const char *p) {
    const char *b = p;
    for (const char *q = p; *q; q++) if (*q == '/') b = q + 1;
    return b;
}

int main_c(int argc, char **argv) {
    const char *cmd = (argc > 0) ? basename_(argv[0]) : "office";
    int sub_argc = argc;
    char **sub_argv = argv;
    if ((scmp(cmd, "office")  == 0 ||
         scmp(cmd, "office2") == 0 ||
         scmp(cmd, "office3") == 0 ||
         scmp(cmd, "office4") == 0 ||
         scmp(cmd, "office5") == 0) && argc > 1) {
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
    return run_shell(sub_argc, sub_argv);
}


/* ── _start: read argc/argv from rsp, dispatch, exit ──── */
__asm__ (
    ".global _start\n"
    "_start:\n"
    "    movq (%rsp), %rdi\n"
    "    leaq 8(%rsp), %rsi\n"
    "    andq $-16, %rsp\n"
    "    call main_c\n"
    "    movl %eax, %edi\n"
    "    movl $231, %eax\n"
    "    syscall\n"
);
