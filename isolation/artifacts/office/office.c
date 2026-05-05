/* office.c — Win95-style 8-app suite in a single ELF. Linux x86_64.
 *
 *   shell  notepad  word  mail  sheet  paint  hex  bfc
 *
 * Build:  make
 * Use:    ./office              (shell)
 *         ./office notepad foo  (open a file in notepad)
 *         ./office hex bar.bin
 *         ./office bfc fizz.bf
 *         ./office sheet data.csv
 *
 * No libc, raw syscalls. _start dispatches on argv[1].
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
#define TCGETS 0x5401
#define TCSETS 0x5402

static struct ti term_orig;

static void term_raw(void) {
    io(0, TCGETS, &term_orig);
    struct ti t = term_orig;
    t.lflag &= ~(ICANON | ECHO);
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

/* Win95 title bar + menu bar across the top of the screen. */
static void chrome(const char *title) {
    cup(0, 0);
    sgrbgfg(COL_TITLE_BG, COL_TITLE_FG);
    fbs(" ");
    fbs(title);
    int used = slen(title) + 1;
    blanks(SCREEN_W - used - 8);
    fbs(" _ [] X ");

    cup(0, 1);
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    fbs(" File  Edit  View  Help");
    blanks(SCREEN_W - 23);
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
    int fd = (int)op(path, O_RDONLY, 0);
    if (fd < 0) { blen = 0; return 0; }
    blen = (int)rd(fd, buf, BUF_CAP - 1);
    if (blen < 0) blen = 0;
    cl(fd);
    int i = 0;
    while (i < (int)sizeof fname - 1 && path[i]) { fname[i] = path[i]; i++; }
    fname[i] = 0;
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


/* ── forward declarations of apps ──────────────────────── */
static int run_shell(int, char**);
static int run_notepad(int, char**);
static int run_word(int, char**);
static int run_mail(int, char**);
static int run_sheet(int, char**);
static int run_paint(int, char**);
static int run_hex(int, char**);
static int run_bfc(int, char**);


/* ── shell: run apps by name + a few built-ins ─────────── */
static int run_shell(int argc, char **argv) {
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
        body_at(2, 5, "  exit", SCREEN_W - 4);
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


/* ── notepad: line-oriented editor with arrow scrolling ─ */
/* Find offset of byte at the start of the n-th visible line, given
 * btop is the offset of the first visible line. */
static int line_start(int from, int up_or_down) {
    /* up_or_down > 0 = move forward `up_or_down` lines; < 0 = back */
    int o = from;
    if (up_or_down >= 0) {
        for (int i = 0; i < up_or_down && o < blen; ) {
            if (buf[o++] == '\n') i++;
        }
    } else {
        int back = -up_or_down;
        if (o > 0) o--;
        for (int i = 0; i < back && o > 0; ) {
            o--;
            if (buf[o] == '\n') i++;
        }
        if (o > 0 && buf[o] == '\n') o++;
        if (o < 0) o = 0;
    }
    return o;
}

static void notepad_draw(const char *title, int word_wrap) {
    paint_desktop();
    chrome(title);
    body_clear();
    int y = 2, x = 2;
    int o = btop;
    int maxw = SCREEN_W - 4;
    while (y < SCREEN_H - 1 && o < blen) {
        cup(x, y);
        int line_w = 0;
        while (o < blen && buf[o] != '\n') {
            if (line_w >= maxw) {
                if (word_wrap) {
                    y++;
                    if (y >= SCREEN_H - 1) break;
                    cup(x, y);
                    line_w = 0;
                } else {
                    /* skip the rest of this line */
                    while (o < blen && buf[o] != '\n') o++;
                    break;
                }
            }
            char c = buf[o];
            if (c == '\t') c = ' ';
            if (c >= 32 && c < 127) fbw(&c, 1);
            else fbw(".", 1);
            line_w++;
            o++;
        }
        if (o < blen && buf[o] == '\n') o++;
        y++;
    }
    char hint[80];
    int hn = 0;
    const char *h = "  arrows scroll | s save | q back to shell";
    while (h[hn]) { hint[hn] = h[hn]; hn++; }
    hint[hn] = 0;
    status(hint);
    fbflush();
}

static int notepad_loop(const char *title, int word_wrap) {
    term_raw();
    btop = 0; bcur = 0;
    while (1) {
        notepad_draw(title, word_wrap);
        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;
        if (k[0] == 'q') break;
        if (k[0] == 's') save_file(fname);
        if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
            switch (k[2]) {
            case 'A': btop = line_start(btop, -1); break;
            case 'B': btop = line_start(btop, +1); break;
            case 'C': /* page right not impl */ break;
            case 'D': /* page left  not impl */ break;
            }
        }
        if (k[0] == ' ') btop = line_start(btop, +(SCREEN_H - 4));
    }
    return 0;
}

static int run_notepad(int argc, char **argv) {
    if (argc > 1 && argv[1][0]) load_file(argv[1]);
    else { blen = 0; fname[0] = 0; }
    return notepad_loop("Notepad", 0);
}

static int run_word(int argc, char **argv) {
    if (argc > 1 && argv[1][0]) load_file(argv[1]);
    else { blen = 0; fname[0] = 0; }
    return notepad_loop("Word", 1);
}


/* ── mail: compose to ./outbox.txt ─────────────────────── */
static int run_mail(int argc, char **argv) {
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
                if (r == cellrow && c == cellcol) sgrbgfg(15, 0);
                else                              sgrbgfg(7, 0);
                int len = slen(cell[r][c]);
                if (len > CELL_W - 1) len = CELL_W - 1;
                fbw(cell[r][c], len);
                blanks(CELL_W - len);
            }
        }
        char hint[80] = { 0 };
        int hn = 0;
        const char *h = editing
            ? "  editing — enter commits, esc cancels"
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
            if (k[0] == 0x1b) {
                editing = 0;
                continue;
            }
            if (k[0] == 0x7f || k[0] == 8) {
                if (eidx > 0) cell[cellrow][cellcol][--eidx] = 0;
                continue;
            }
            if (k[0] >= 32 && k[0] < 127 && eidx < 15) {
                cell[cellrow][cellcol][eidx++] = (char)k[0];
            }
            continue;
        }
        if (k[0] == 'q') break;
        if (k[0] == 's') sheet_save_csv();
        if (k[0] == 'e') {
            editing = 1;
            eidx = slen(cell[cellrow][cellcol]);
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


/* ── paint: ASCII canvas, brush is current keystroke ───── */
#define PAINT_W 60
#define PAINT_H 16
static char canvas[PAINT_H][PAINT_W];
static int  px, py;
static int  brush = 7;     /* foreground colour */
static char brush_char = '#';

static int run_paint(int argc, char **argv) {
    (void)argc; (void)argv;
    mset(canvas, ' ', sizeof canvas);
    px = PAINT_W / 2; py = PAINT_H / 2;
    term_raw();
    while (1) {
        paint_desktop();
        chrome("Paint");
        body_clear();
        for (int r = 0; r < PAINT_H; r++) {
            cup(2, 3 + r);
            sgrbgfg(15, brush);
            for (int c = 0; c < PAINT_W; c++) fbw(&canvas[r][c], 1);
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
        if (k[0] == 'q') break;
        if (k[0] == 's') {
            blen = 0;
            for (int r = 0; r < PAINT_H && blen < BUF_CAP - 1; r++) {
                for (int c = 0; c < PAINT_W && blen < BUF_CAP - 2; c++) buf[blen++] = canvas[r][c];
                if (blen < BUF_CAP - 1) buf[blen++] = '\n';
            }
            mcpy(fname, "canvas.txt", 11);
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
        }
    }
    return 0;
}


/* ── hex editor: 16 bytes/line view of a file ─────────── */
static int run_hex(int argc, char **argv) {
    if (argc > 1 && argv[1][0]) load_file(argv[1]);
    else { blen = 0; fname[0] = 0; }
    bcur = 0; btop = 0;
    term_raw();
    while (1) {
        paint_desktop();
        chrome("Hex");
        body_clear();
        int rows = SCREEN_H - 4;
        for (int r = 0; r < rows; r++) {
            int o = btop + r * 16;
            if (o >= blen) break;
            cup(2, 3 + r);
            sgrbgfg(7, 8);
            char hx[9];
            int  hn = 0;
            unsigned u = (unsigned)o;
            for (int s = 16; s; s -= 4) {
                int v = (u >> (s - 4)) & 0xf;
                hx[hn++] = (char)(v < 10 ? '0' + v : 'a' + v - 10);
            }
            hx[hn] = 0;
            fbw(hx, 8);
            fbw("  ", 2);
            sgrbgfg(7, 0);
            char asc[17];
            int  an = 0;
            for (int j = 0; j < 16; j++) {
                int oo = o + j;
                if (oo >= blen) { fbw("   ", 3); asc[an++] = ' '; continue; }
                unsigned u8 = (unsigned char)buf[oo];
                char hb[3];
                int hi = (u8 >> 4) & 0xf;
                int lo = u8 & 0xf;
                hb[0] = (char)(hi < 10 ? '0' + hi : 'a' + hi - 10);
                hb[1] = (char)(lo < 10 ? '0' + lo : 'a' + lo - 10);
                hb[2] = ' ';
                fbw(hb, 3);
                asc[an++] = (u8 >= 32 && u8 < 127) ? (char)u8 : '.';
            }
            asc[an] = 0;
            fbw(" ", 1);
            fbw(asc, an);
        }
        char st[80] = {0};
        int  sn = 0;
        const char *t = "  arrows scroll | space page | q back";
        while (t[sn]) { st[sn] = t[sn]; sn++; }
        status(st);
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;
        if (k[0] == 'q') break;
        if (k[0] == ' ') { btop += (rows - 2) * 16; if (btop > blen) btop = blen; continue; }
        if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
            switch (k[2]) {
            case 'A': if (btop >= 16) btop -= 16; break;
            case 'B': if (btop + 16 < blen) btop += 16; break;
            }
        }
    }
    return 0;
}


/* ── bfc: brainfuck compiler/interpreter — runs the program ── */
#define TAPE_LEN 4096
static unsigned char tape[TAPE_LEN];

static int run_bfc(int argc, char **argv) {
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
        if (n > 0 && k[0] == 'q') break;
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
    if (scmp(cmd, "office") == 0 && argc > 1) {
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
