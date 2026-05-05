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
    status("  arrows | enter | bksp | ^S save | ^Q quit");
    cup(cur_sx, cur_sy);
    fbs(ESC "[?25h");
    fbflush();
}

static int notepad_loop(const char *title, int word_wrap) {
    term_raw();
    bcur = 0; btop = 0;
    while (1) {
        adjust_btop(SCREEN_H - 4);
        notepad_draw(title, word_wrap);
        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;
        if (k[0] == 0x11) break;                 /* Ctrl-Q */
        if (k[0] == 0x13) { save_file(fname); continue; }    /* Ctrl-S */
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
    char L = *fp;
    int col = -1;
    if (L >= 'a' && L <= 'h') col = L - 'a';
    else if (L >= 'A' && L <= 'H') col = L - 'A';
    if (col >= 0) {
        fp++;
        int row = 0;
        while (*fp >= '0' && *fp <= '9') { row = row * 10 + (*fp - '0'); fp++; }
        row--;
        if (row < 0 || row >= SHEET_ROWS || col >= SHEET_COLS) return 0;
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


/* ── paint: ASCII canvas, per-cell colour ─────────────── */
#define PAINT_W 60
#define PAINT_H 16
static char           canvas[PAINT_H][PAINT_W];
static unsigned char  canvas_fg[PAINT_H][PAINT_W];
static int  px, py;
static int  brush = 1;     /* foreground colour (xterm-256) */
static char brush_char = '#';

static int run_paint(int argc, char **argv) {
    (void)argc; (void)argv;
    mset(canvas, ' ', sizeof canvas);
    mset(canvas_fg, 0, sizeof canvas_fg);
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
            canvas_fg[py][px] = (unsigned char)brush;
        }
    }
    return 0;
}


/* ── hex editor: 16 bytes/line view + nibble write ─────── */
static int run_hex(int argc, char **argv) {
    if (argc > 1 && argv[1][0]) load_file(argv[1]);
    else { blen = 0; fname[0] = 0; }
    bcur = 0; btop = 0;
    int nibhi = 1;            /* next digit goes to high nibble */
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
            int  an = 0;
            for (int j = 0; j < 16; j++) {
                int oo = o + j;
                int is_cur = (oo == bcur);
                if (oo >= blen) {
                    sgrbgfg(is_cur ? 15 : 7, 8);
                    fbw("__ ", 3);
                    asc[an++] = ' ';
                    continue;
                }
                unsigned u8 = (unsigned char)buf[oo];
                int hi = (u8 >> 4) & 0xf, lo = u8 & 0xf;
                char hh = (char)(hi < 10 ? '0' + hi : 'a' + hi - 10);
                char ll = (char)(lo < 10 ? '0' + lo : 'a' + lo - 10);
                sgrbgfg(is_cur && nibhi ? 15 : 7, 0); fbw(&hh, 1);
                sgrbgfg(is_cur && !nibhi ? 15 : 7, 0); fbw(&ll, 1);
                sgrbgfg(7, 0); fbw(" ", 1);
                asc[an++] = (u8 >= 32 && u8 < 127) ? (char)u8 : '.';
            }
            fbw(" ", 1);
            fbw(asc, an);
        }
        status("  arrows move | 0-9 a-f write | i ins | x del | ^S save | q back");
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;
        if (k[0] == 'q') break;
        if (k[0] == 0x13) { save_file(fname); continue; }
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
    if ((scmp(cmd, "office") == 0 || scmp(cmd, "office2") == 0) && argc > 1) {
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
