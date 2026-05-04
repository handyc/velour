/* wnnr.c — a single Windows-95-style window in a terminal.
 *
 * One window. Royal-blue title bar with white text, light-grey menu
 * bar with black File/Edit/View/Help, light-grey content area with
 * a 3D bevel (white top/left, dark-grey bottom/right). Arrow keys
 * drag the window around. r recolours the title bar. s saves the
 * window position to ./savepoint. q quits.
 *
 * Lean and mean: libc + POSIX termios + ANSI 256-colour escapes.
 * No curses, no third-party libs, no SLURM.
 *
 * Build:
 *   make            (or:  cc -std=c99 -O2 -Wall -Wextra -o wnnr wnnr.c)
 *
 * Run:
 *   ./wnnr
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <termios.h>
#include <signal.h>
#include <sys/select.h>
#include <sys/ioctl.h>


/* ── Win95 palette (xterm-256 indexes) ─────────────────────── */
#define COL_TITLE_BG    21      /* royal blue ~ #0000ff */
#define COL_TITLE_FG    15      /* white */
#define COL_TITLE_INACT 8       /* dark grey for inactive (unused) */
#define COL_BAR_BG      7       /* Win95 grey #c0c0c0 */
#define COL_BAR_FG      0       /* black */
#define COL_FRAME_HI    15      /* white bevel highlight */
#define COL_FRAME_LO    8       /* dark-grey bevel shadow */
#define COL_DESKTOP     30      /* teal-ish desktop */

#define WIN_W           42
#define WIN_H           12
#define KEY_TIMEOUT_S   5

#define CANVAS_W_FALLBACK   80
#define CANVAS_H_FALLBACK   24


/* ── terminal state ────────────────────────────────────────── */
static struct termios saved_termios;
static int term_was_raw = 0;

static void cooked(void) {
    if (term_was_raw) {
        tcsetattr(STDIN_FILENO, TCSANOW, &saved_termios);
        term_was_raw = 0;
    }
    fputs("\x1b[0m\x1b[?25h\x1b[2J\x1b[H", stdout);
    fflush(stdout);
}
static void on_signal(int sig) { cooked(); _exit(128 + sig); }
static void raw(void) {
    if (tcgetattr(STDIN_FILENO, &saved_termios) != 0) {
        perror("tcgetattr"); exit(1);
    }
    struct termios t = saved_termios;
    t.c_lflag &= ~(ICANON | ECHO);
    t.c_cc[VMIN]  = 0;
    t.c_cc[VTIME] = 0;
    if (tcsetattr(STDIN_FILENO, TCSANOW, &t) != 0) {
        perror("tcsetattr"); exit(1);
    }
    term_was_raw = 1;
    atexit(cooked);
    signal(SIGINT,  on_signal);
    signal(SIGTERM, on_signal);
    fputs("\x1b[?25l", stdout);
    fflush(stdout);
}


/* ── input ─────────────────────────────────────────────────── */
static int read_key(unsigned char *out, int max, long timeout_us) {
    fd_set fds; struct timeval tv; int got = 0;
    FD_ZERO(&fds); FD_SET(STDIN_FILENO, &fds);
    tv.tv_sec = timeout_us / 1000000; tv.tv_usec = timeout_us % 1000000;
    if (select(STDIN_FILENO + 1, &fds, NULL, NULL, &tv) <= 0) return 0;
    if (read(STDIN_FILENO, &out[got], 1) != 1) return 0;
    got++;
    while (got < max) {
        FD_ZERO(&fds); FD_SET(STDIN_FILENO, &fds);
        tv.tv_sec = 0; tv.tv_usec = 200;
        if (select(STDIN_FILENO + 1, &fds, NULL, NULL, &tv) <= 0) break;
        if (read(STDIN_FILENO, &out[got], 1) != 1) break;
        got++;
    }
    return got;
}


/* ── ANSI escape helpers ───────────────────────────────────── */
static void cls(void)         { fputs("\x1b[2J\x1b[H", stdout); }
static void cup(int x, int y) { printf("\x1b[%d;%dH", y + 1, x + 1); }
static void setab(int c)      { printf("\x1b[48;5;%dm", c & 0xff); }
static void setaf(int c)      { printf("\x1b[38;5;%dm", c & 0xff); }
static void sgr0(void)        { fputs("\x1b[0m", stdout); }


/* ── canvas size detection ────────────────────────────────── */
static void canvas_size(int *cw, int *ch) {
    struct winsize ws;
    if (ioctl(STDOUT_FILENO, TIOCGWINSZ, &ws) == 0
        && ws.ws_col > 0 && ws.ws_row > 0) {
        *cw = ws.ws_col;
        *ch = ws.ws_row;
        return;
    }
    *cw = CANVAS_W_FALLBACK;
    *ch = CANVAS_H_FALLBACK;
}


/* ── helpers: print N spaces, print a fixed-width string ──── */
static void blanks(int n) { while (n-- > 0) fputc(' ', stdout); }

static void put_padded(const char *s, int w) {
    int len = (int)strlen(s);
    if (len > w) { fwrite(s, 1, w, stdout); return; }
    fputs(s, stdout);
    blanks(w - len);
}


/* ── Win95 window draw ────────────────────────────────────── */
static void draw_window(int wx, int wy, int title_bg, int n_moves) {
    /* Top bevel-highlight (white). */
    cup(wx, wy);
    setab(COL_FRAME_HI); setaf(COL_BAR_FG);
    blanks(WIN_W);

    /* Title bar (blue bg, white fg). One row, padded. */
    cup(wx, wy + 1);
    setab(title_bg); setaf(COL_TITLE_FG);
    fputs(" wnnr - window", stdout);
    int title_used = 14;
    blanks(WIN_W - title_used - 8);
    fputs("_ [] X ", stdout);
    fputc(' ', stdout);

    /* Menu bar (grey bg, black fg). */
    cup(wx, wy + 2);
    setab(COL_BAR_BG); setaf(COL_BAR_FG);
    fputs(" File  Edit  View  Help", stdout);
    blanks(WIN_W - 23);

    /* Separator under menu (1 row of grey + 1 row dark to imply
     * shadow). Keeps the menu visually separate from the content. */
    cup(wx, wy + 3);
    setab(COL_BAR_BG); blanks(WIN_W);

    /* Content rows (grey bg, black fg). */
    char line1[64], line2[64];
    snprintf(line1, sizeof line1, "Position: (%2d, %2d)", wx, wy);
    time_t now = time(NULL);
    struct tm *tm = localtime(&now);
    strftime(line2, sizeof line2, "%a %b %e %T %Y", tm);

    cup(wx, wy + 4);
    setab(COL_BAR_BG); setaf(COL_BAR_FG);
    fputs("  ", stdout); put_padded(line1, WIN_W - 2);

    cup(wx, wy + 5);
    fputs("  ", stdout); put_padded(line2, WIN_W - 2);

    cup(wx, wy + 6);
    char line3[64];
    snprintf(line3, sizeof line3, "Moves: %d", n_moves);
    fputs("  ", stdout); put_padded(line3, WIN_W - 2);

    /* Empty content rows. */
    for (int r = 7; r < WIN_H - 2; r++) {
        cup(wx, wy + r);
        setab(COL_BAR_BG); blanks(WIN_W);
    }

    /* Penultimate row: hint line. */
    cup(wx, wy + WIN_H - 2);
    setab(COL_BAR_BG); setaf(COL_FRAME_LO);
    fputs("  arrow keys move | r recolour | s save | q quit", stdout);
    int hint_used = 50;
    blanks(WIN_W - hint_used);

    /* Bottom bevel-shadow (dark grey). */
    cup(wx, wy + WIN_H - 1);
    setab(COL_FRAME_LO); blanks(WIN_W);

    /* Left-edge highlight + right-edge shadow (single column
     * each). Drawn after the rows above so they sit on top. */
    for (int r = 1; r < WIN_H - 1; r++) {
        cup(wx, wy + r);
        setab(COL_FRAME_HI); fputc(' ', stdout);
        cup(wx + WIN_W - 1, wy + r);
        setab(COL_FRAME_LO); fputc(' ', stdout);
    }
    sgr0();
}


/* ── savepoint: position + title-bar colour ──────────────── */
static void save_state(int wx, int wy, int title_bg) {
    FILE *f = fopen("savepoint", "w");
    if (!f) { perror("savepoint"); return; }
    fprintf(f, "%d %d %d\n", wx, wy, title_bg);
    fclose(f);
}


/* ── main ────────────────────────────────────────────────── */
int main(void) {
    srand((unsigned)(time(NULL) ^ getpid()));

    int cw, ch;
    canvas_size(&cw, &ch);
    int wx = (cw - WIN_W) / 2;
    int wy = (ch - WIN_H) / 2;
    if (wx < 0) wx = 0;
    if (wy < 0) wy = 0;

    /* Try to load a savepoint. */
    {
        FILE *f = fopen("savepoint", "r");
        if (f) {
            int sx, sy, sc;
            if (fscanf(f, "%d %d %d", &sx, &sy, &sc) == 3) {
                if (sx >= 0 && sx + WIN_W <= cw) wx = sx;
                if (sy >= 0 && sy + WIN_H <= ch) wy = sy;
            }
            fclose(f);
        }
    }

    int title_bg = COL_TITLE_BG;
    int n_moves = 0;

    raw();

    int dirty = 1;
    while (1) {
        if (dirty) {
            cls();
            /* Paint the desktop. */
            setab(COL_DESKTOP);
            for (int r = 0; r < ch; r++) {
                cup(0, r);
                blanks(cw);
            }
            draw_window(wx, wy, title_bg, n_moves);
            cup(0, ch - 1);
            sgr0();
            fflush(stdout);
            dirty = 0;
        }

        unsigned char key[8] = { 0 };
        int got = read_key(key, sizeof key,
                           (long)KEY_TIMEOUT_S * 1000000);
        if (got == 0) {
            /* Refresh the clock line on idle. */
            dirty = 1;
            continue;
        }

        if (got >= 3 && key[0] == 0x1b && key[1] == '[') {
            int moved = 1;
            switch (key[2]) {
            case 'A': if (wy > 0)               wy--; else moved = 0; break;
            case 'B': if (wy + WIN_H < ch)      wy++; else moved = 0; break;
            case 'C': if (wx + WIN_W < cw)      wx++; else moved = 0; break;
            case 'D': if (wx > 0)               wx--; else moved = 0; break;
            default: moved = 0; break;
            }
            if (moved) { n_moves++; dirty = 1; }
            continue;
        }

        switch (key[0]) {
        case 'r':
            /* Random title bar from a small Win95-friendly set so
             * it always reads as a "highlight" colour. */
            { static const int choices[] = {
                21, 19, 20, 17, 18, 27, 33, 56, 88, 124,
              };
              title_bg = choices[rand() % (int)(sizeof choices / sizeof *choices)];
              dirty = 1; }
            break;
        case 's':
            save_state(wx, wy, title_bg);
            return 0;
        case 'q':
            return 0;
        default: break;
        }
    }
}
