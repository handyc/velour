/* win95term.c — Win95/98 look-and-feel in an ANSI terminal.
 *
 * MVP: 100×30 desktop with one window (title bar, menu bar, content,
 * status bar), a Start-button taskbar with a clock, a File menu with
 * an About dialog, and a hex-direction cursor controlled by:
 *
 *     w  e        (NW)  (NE)
 *      \/
 *   a -- d       (W) -- (E)
 *      /\
 *     z  x        (SW)  (SE)
 *
 *     s = click / activate
 *     f = right-click (context menu)
 *     q = quit
 *     G = toggle hex/square cursor model (square is default)
 *
 * Build (no TINY constraints — debug-friendly, unlimited size):
 *     cc -O2 -g -Wall -Wextra -o win95term win95term.c
 *
 * Run interactively:
 *     ./win95term
 * One-shot frame dump (for visual verification or piping to less -R):
 *     ./win95term --once
 *     ./win95term --once | sed 's/\x1b\[[0-9;?]*[mHJlh]//g'    # ASCII-only
 */
#define _DEFAULT_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <termios.h>
#include <signal.h>
#include <time.h>
#include <sys/select.h>
#include <sys/ioctl.h>

/* ── Geometry ────────────────────────────────────────────── *
 *
 * SCR_W/SCR_H are the framebuffer's MAXIMUM size (used as static
 * array dimensions).  VIS_W/VIS_H are what the real terminal can
 * show; cells outside that range are computed but never emitted,
 * which prevents the wrap/scroll storm that occurs when a 100x30
 * layout meets an 80x24 terminal.
 *
 * The main window and taskbar positions are RUNTIME variables — at
 * startup we measure the terminal with TIOCGWINSZ and recompute
 * them so the layout always fits and looks reasonable. */
#define SCR_W  120
#define SCR_H   40

static int VIS_W = 100;
static int VIS_H =  30;

/* Main window (filled in by layout_for_size()). */
static int WIN_R0 = 6,  WIN_R1 = 21;
static int WIN_C0 = 25, WIN_C1 = 74;
static int TASK_R = 29;

/* ── 256-color palette (xterm slots picked to match Win95 system colors). ─ */
enum {
    C_DESK_DEFAULT = 23, /* desktop teal (Win95 default-ish) */
    C_BTN       = 251,   /* button face #c6c6c6 ~ Win95 silver */
    C_BTN_HL    =  15,   /* button highlight (white) */
    C_BTN_SH    = 240,   /* button shadow (dark gray) */
    C_BTN_DK    = 236,   /* deeper shadow / window outline */
    C_TEXT      =  16,   /* default text (black) */
    C_TITLE_BG  =  18,   /* active title bar (Win95 navy) */
    C_TITLE_FG  =  15,   /* active title text (white) */
    C_INACT_BG  = 244,   /* inactive title bar (gray) */
    C_FIELD_BG  =  15,   /* white field background (text area) */
    C_HL_BG     =  20,   /* menu selection blue */
    C_HL_FG     =  15,   /* menu selection white */
    C_LINK      =  21    /* hyperlink-ish accent */
};

/* ── Terminal I/O helpers ────────────────────────────────── */
static struct termios g_saved_tios;
static int g_tios_saved = 0;

static void term_reset(void) {
    /* Show cursor, default colors, move to bottom row, newline. */
    fputs("\033[?25h\033[0m\033[" "30" ";1H\n", stdout);
    if (g_tios_saved) tcsetattr(STDIN_FILENO, TCSANOW, &g_saved_tios);
    fflush(stdout);
}

/* Measure the terminal, set VIS_W/VIS_H, and place the main window +
 * taskbar so the layout fits.  Window is centered horizontally, sits
 * a few rows below the top, and the taskbar always pins to the last
 * visible row.  Clamps to a sane minimum so tiny terminals still
 * render *something*. */
static void layout_for_size(void) {
    struct winsize ws;
    if (ioctl(STDOUT_FILENO, TIOCGWINSZ, &ws) == 0 && ws.ws_col && ws.ws_row) {
        VIS_W = ws.ws_col;
        VIS_H = ws.ws_row;
    } else {
        VIS_W = 80; VIS_H = 24;
    }
    if (VIS_W > SCR_W) VIS_W = SCR_W;
    if (VIS_H > SCR_H) VIS_H = SCR_H;
    if (VIS_W < 40)    VIS_W = 40;
    if (VIS_H < 12)    VIS_H = 12;

    /* Taskbar always at bottom row of visible area. */
    TASK_R = VIS_H - 1;

    /* Main window: target 60-70% of available area, centered, with a
     * little margin at top and a 2-row gap above the taskbar. */
    int target_w = VIS_W - 8;
    int target_h = VIS_H - 6;
    if (target_w > 60) target_w = 60;     /* don't grow unbounded */
    if (target_h > 18) target_h = 18;
    if (target_w < 30) target_w = 30;
    if (target_h <  8) target_h =  8;

    WIN_C0 = (VIS_W - target_w) / 2;
    WIN_C1 = WIN_C0 + target_w - 1;
    WIN_R0 = (VIS_H - target_h - 2) / 2;  /* -2 leaves room above taskbar */
    if (WIN_R0 < 1) WIN_R0 = 1;
    WIN_R1 = WIN_R0 + target_h - 1;
    if (WIN_R1 > TASK_R - 2) WIN_R1 = TASK_R - 2;
}

/* SIGWINCH: terminal resize.  Re-measure, set a "needs repaint" flag,
 * and let the main loop pick it up (we can't safely touch many
 * globals from a signal handler).  Cursor clamping happens on the
 * next paint. */
static volatile sig_atomic_t g_winch_dirty = 0;
static void on_winch(int sig) { (void)sig; g_winch_dirty = 1; }

static void term_setup_raw(void) {
    layout_for_size();
    if (tcgetattr(STDIN_FILENO, &g_saved_tios) == 0) {
        g_tios_saved = 1;
        struct termios t = g_saved_tios;
        t.c_lflag &= ~(ICANON | ECHO);
        t.c_cc[VMIN] = 0;
        t.c_cc[VTIME] = 1;          /* 100 ms read timeout for clock refresh */
        tcsetattr(STDIN_FILENO, TCSANOW, &t);
    }
    /* Alt screen, hide cursor, clear. */
    fputs("\033[?1049h\033[?25l\033[2J\033[H", stdout);
    fflush(stdout);
}

static void term_teardown(void) {
    fputs("\033[?25h\033[?1049l\033[0m", stdout);
    term_reset();
}

static void on_signal(int sig) { (void)sig; term_teardown(); _exit(0); }

/* ── Frame buffer ────────────────────────────────────────── */
typedef struct {
    unsigned char ch;       /* ASCII glyph (we use box-drawing later via lookup) */
    unsigned char fg;       /* xterm 256 fg */
    unsigned char bg;       /* xterm 256 bg */
    unsigned char attr;     /* bit 0 = bold, bit 1 = underline, bit 2 = inverse */
} cell_t;

#define ATTR_BOLD  0x01
#define ATTR_UNDER 0x02
#define ATTR_INV   0x04

static cell_t g_fb[SCR_H][SCR_W];

/* Shadow of the last fully-rendered frame.  Cells that match prev are
 * skipped during emission so the wire only carries differences — huge
 * flicker reduction vs. repainting all 3000 cells per keystroke. */
static cell_t g_fb_prev[SCR_H][SCR_W];
static int    g_fb_prev_valid = 0;
/* Remember where the cursor was on the previous frame so we can force
 * a re-emit of that cell (otherwise the diff skips it and the old
 * inverted cursor stays visible). */
static int    g_prev_cur_r = -1;
static int    g_prev_cur_c = -1;

static void fb_clear(int bg) {
    for (int r = 0; r < SCR_H; r++)
        for (int c = 0; c < SCR_W; c++) {
            g_fb[r][c].ch   = ' ';
            g_fb[r][c].fg   = C_TEXT;
            g_fb[r][c].bg   = (unsigned char)bg;
            g_fb[r][c].attr = 0;
        }
}

static void fb_put(int r, int c, char ch, int fg, int bg, int attr) {
    if (r < 0 || r >= SCR_H || c < 0 || c >= SCR_W) return;
    g_fb[r][c].ch   = (unsigned char)ch;
    g_fb[r][c].fg   = (unsigned char)fg;
    g_fb[r][c].bg   = (unsigned char)bg;
    g_fb[r][c].attr = (unsigned char)attr;
}

static void fb_text(int r, int c, const char *s, int fg, int bg, int attr) {
    for (int i = 0; s[i]; i++) fb_put(r, c + i, s[i], fg, bg, attr);
}

/* Fill a rectangle [r0..r1] × [c0..c1] inclusive. */
static void fb_fill(int r0, int c0, int r1, int c1, char ch, int fg, int bg) {
    for (int r = r0; r <= r1; r++)
        for (int c = c0; c <= c1; c++)
            fb_put(r, c, ch, fg, bg, 0);
}

/* ── Win95-style 3D etched borders ────────────────────────
 *
 * outset = highlight on top/left, shadow on bottom/right (raised button)
 * inset  = shadow on top/left, highlight on bottom/right (sunken field) */
static void draw_outset(int r0, int c0, int r1, int c1, int face) {
    /* Top + left edges = highlight */
    for (int c = c0; c <= c1; c++) fb_put(r0, c, ' ', C_TEXT, C_BTN_HL, 0);
    for (int r = r0; r <= r1; r++) fb_put(r, c0, ' ', C_TEXT, C_BTN_HL, 0);
    /* Bottom + right edges = shadow */
    for (int c = c0; c <= c1; c++) fb_put(r1, c, ' ', C_TEXT, C_BTN_SH, 0);
    for (int r = r0; r <= r1; r++) fb_put(r, c1, ' ', C_TEXT, C_BTN_SH, 0);
    /* Bottom-right outer = darker shadow (the Win95 double-thick edge) */
    fb_put(r1, c1, ' ', C_TEXT, C_BTN_DK, 0);
    /* Interior fill */
    if (r1 - r0 >= 2 && c1 - c0 >= 2)
        fb_fill(r0 + 1, c0 + 1, r1 - 1, c1 - 1, ' ', C_TEXT, face);
}

static void draw_inset(int r0, int c0, int r1, int c1, int face) {
    for (int c = c0; c <= c1; c++) fb_put(r0, c, ' ', C_TEXT, C_BTN_SH, 0);
    for (int r = r0; r <= r1; r++) fb_put(r, c0, ' ', C_TEXT, C_BTN_SH, 0);
    for (int c = c0; c <= c1; c++) fb_put(r1, c, ' ', C_TEXT, C_BTN_HL, 0);
    for (int r = r0; r <= r1; r++) fb_put(r, c1, ' ', C_TEXT, C_BTN_HL, 0);
    if (r1 - r0 >= 2 && c1 - c0 >= 2)
        fb_fill(r0 + 1, c0 + 1, r1 - 1, c1 - 1, ' ', C_TEXT, face);
}

/* A small etched button on one row.  `label` is centered.  When
 * `pressed`, the highlight/shadow flip to mimic the depressed look. */
static void draw_button(int r, int c0, int c1, const char *label, int pressed) {
    if (pressed) draw_inset(r, c0, r, c1, C_BTN);
    else         draw_outset(r, c0, r, c1, C_BTN);
    int w = c1 - c0 - 1;
    int len = (int)strlen(label);
    if (len > w) len = w;
    int pad = (w - len) / 2;
    fb_text(r, c0 + 1 + pad, label, C_TEXT, C_BTN, 0);
}

/* Title-bar mini-button: like the _ / [] / X cluster on the right of
 * a Win95 title bar.  A single-row 3D etch can't render properly
 * (top + bottom edges collapse onto the same line), so we paint a
 * flat face-color cell with the label centered.  Surrounding navy
 * title-bar background gives the implied edge. */
static void draw_titlebar_button(int r, int c0, int c1, const char *label) {
    int w = c1 - c0 + 1;
    int len = (int)strlen(label);
    if (len > w) len = w;
    int pad = (w - len) / 2;
    for (int c = c0; c <= c1; c++) {
        int rel = c - c0;
        char ch = (rel >= pad && rel < pad + len) ? label[rel - pad] : ' ';
        fb_put(r, c, ch, C_TEXT, C_BTN, 0);
    }
}

/* ── Compositor: emit frame buffer with ANSI escapes ──────
 *
 * Three flicker-reduction tricks:
 *   1. DEC private mode 2026 (\033[?2026h…l) wraps the whole frame so
 *      a compliant terminal commits the update atomically — no tearing
 *      while the bytes are still streaming.
 *   2. A shadow buffer (g_fb_prev) lets us skip cells that haven't
 *      changed since last frame; only differences are emitted.
 *   3. Runs of unchanged cells are bridged with a single \033[<r>;<c>H
 *      cursor move instead of "\b" or per-cell rewrites. */
static void render_to_stdout(int cursor_r, int cursor_c, int cursor_visible) {
    static char buf[1 << 17];
    int p = 0;
    int prev_fg = -1, prev_bg = -1, prev_attr = -1;
    int last_r = -1, last_c = -1;
    int diff = g_fb_prev_valid;                 /* second frame onward */

    /* Begin synchronized update; reset SGR. */
    p += snprintf(buf + p, sizeof buf - p, "\033[?2026h\033[0m");

    /* Iterate only within the terminal's actual visible window.  Cells
     * beyond VIS_W / VIS_H are computed in g_fb but never emitted —
     * this keeps wrap/scroll out of an 80x24 terminal that's hosting
     * a 120x40-capable framebuffer. */
    for (int r = 0; r < VIS_H; r++) {
        for (int c = 0; c < VIS_W; c++) {
            cell_t cell = g_fb[r][c];
            int inv = cursor_visible && cursor_r == r && cursor_c == c;
            int was_cursor_prev = g_fb_prev_valid &&
                /* previous cursor cell needs re-emit even if g_fb unchanged */
                0; /* simpler approach: always emit cursor + neighbors below */
            (void)was_cursor_prev;

            cell_t prev = diff ? g_fb_prev[r][c] : (cell_t){0,0,0,0};
            int was_prev_cursor = (r == g_prev_cur_r && c == g_prev_cur_c);
            /* Re-emit a cell if its contents changed, OR it's the new
             * cursor (so we apply inversion), OR it WAS the old cursor
             * (so we strip the previous inversion). */
            int same = diff &&
                       prev.ch   == cell.ch &&
                       prev.fg   == cell.fg &&
                       prev.bg   == cell.bg &&
                       prev.attr == cell.attr &&
                       !inv &&
                       !was_prev_cursor;
            if (same) continue;

            /* Cursor cell: render as the Win95 selection highlight
             * (white text on navy blue), NOT a raw fg/bg swap.  A swap
             * collapses to a solid black square in white-bg areas
             * (which dominate the window content), making it look like
             * the cursor is eating the UI.  The highlight is also
             * authentic — Win95 menus light up exactly this way on
             * keyboard focus. */
            int fg = inv ? C_HL_FG : cell.fg;
            int bg = inv ? C_HL_BG : cell.bg;
            int at = cell.attr;

            /* Move cursor if we skipped any cells since last emit. */
            if (last_r != r || last_c != c - 0) {
                if (last_r == r && c == last_c + 1) {
                    /* contiguous — no move needed */
                } else {
                    p += snprintf(buf + p, sizeof buf - p,
                                  "\033[%d;%dH", r + 1, c + 1);
                    prev_fg = prev_bg = prev_attr = -1;
                }
            }
            if (fg != prev_fg || bg != prev_bg || at != prev_attr) {
                p += snprintf(buf + p, sizeof buf - p, "\033[0");
                if (at & ATTR_BOLD)  p += snprintf(buf + p, sizeof buf - p, ";1");
                if (at & ATTR_UNDER) p += snprintf(buf + p, sizeof buf - p, ";4");
                if (at & ATTR_INV)   p += snprintf(buf + p, sizeof buf - p, ";7");
                p += snprintf(buf + p, sizeof buf - p, ";38;5;%d;48;5;%dm", fg, bg);
                prev_fg = fg; prev_bg = bg; prev_attr = at;
            }
            buf[p++] = (char)cell.ch;
            last_r = r; last_c = c;

            if (p > (int)sizeof buf - 128) { fwrite(buf, 1, p, stdout); p = 0; }
        }
    }
    p += snprintf(buf + p, sizeof buf - p, "\033[0m\033[?2026l");
    fwrite(buf, 1, p, stdout);
    fflush(stdout);

    /* Snapshot for next frame's diff. */
    memcpy(g_fb_prev, g_fb, sizeof g_fb_prev);
    g_fb_prev_valid = 1;
    g_prev_cur_r = cursor_visible ? cursor_r : -1;
    g_prev_cur_c = cursor_visible ? cursor_c : -1;
}

/* ── UI state ────────────────────────────────────────────── */
enum { MODE_DESKTOP = 0, MODE_FILE_MENU, MODE_HELP_MENU, MODE_ABOUT,
       MODE_START, MODE_CONTEXT, MODE_DP, MODE_PROGRAMS };

/* What app is "open" inside the main window.  Switches title bar and
 * content body.  NONE = the original welcome screen. */
enum app_kind { APP_WELCOME = 0, APP_NOTEPAD, APP_CALC, APP_PAINT, APP_DOS };
static int g_current_app = APP_WELCOME;

/* Notepad's tiny text buffer.  Insert-only on the end (no internal
 * cursor movement yet) — chars typed in Notepad mode append; Backspace
 * removes the last char.  Plenty of room for "real Notepad" later. */
#define NOTEPAD_CAP 4096
static char g_notepad_buf[NOTEPAD_CAP];
static int  g_notepad_len = 0;
static int  g_notepad_editing = 0;

/* Context-menu anchor in screen coordinates (set when `f` fires). */
static int g_ctx_r = 0;
static int g_ctx_c = 0;

/* Display Properties settings — mutable at runtime via the dialog. */
static int g_desk_color  = C_DESK_DEFAULT;   /* xterm 256 slot */
static int g_show_icons  = 1;
static int g_show_clock  = 1;
/* g_hex_grid is declared further down already. */

/* Window state for the main window's title-bar _ / o / x buttons. */
static int g_win_minimized = 0;
static int g_win_maximized = 0;
static int g_win_saved_r0  = 0;
static int g_win_saved_c0  = 0;
static int g_win_saved_r1  = 0;
static int g_win_saved_c1  = 0;

static int g_mode = MODE_DESKTOP;
/* Cursor: positioned by layout_for_size() onto the center of the
 * main window once geometry is known.  Initial value is just a safe
 * within-bounds fallback. */
static int g_cur_r = 5;
static int g_cur_c = 10;
static int g_menu_sel = 0;          /* index within open menu */
static int g_hex_grid = 0;          /* 0 = square, 1 = hex (deferred) */

/* Menu bar items: positions and hotkey letters. */
typedef struct { const char *label; char hot; int col_off; int mode; } menu_t;
static menu_t g_menubar[] = {
    { "File", 'F', 2,  MODE_FILE_MENU },
    { "Help", 'H', 9,  MODE_HELP_MENU },
};
static const int g_menubar_n = sizeof g_menubar / sizeof g_menubar[0];

static const char *g_file_items[] = { "About win95term", "Exit" };
static const int   g_file_n       = 2;

static const char *g_help_items[] = { "Keyboard help", "About win95term" };
static const int   g_help_n       = 2;

/* ── Painters ────────────────────────────────────────────── */
static void paint_desktop(void) {
    fb_clear(g_desk_color);
    /* Decorative icons down the left side.  Skip if there's not even
     * room for the 3-char glyph + a 1-col gap before the window;
     * otherwise truncate the label to the desktop strip width so it
     * doesn't bleed under the window's left edge. */
    static const char *icons[][2] = {
        { "[#]", "My Computer" },
        { "[?]", "Help"        },
        { "[X]", "Recycle Bin" },
    };
    if (!g_show_icons) return;   /* user toggled icons off */
    int strip_w = WIN_C0 - 1;   /* available cols from col 1 to window-1 */
    if (strip_w < 4) return;     /* not enough room — skip icons */
    int label_max = strip_w - 1; /* labels start at col 1 */
    for (unsigned i = 0; i < sizeof icons / sizeof icons[0]; i++) {
        int r = 2 + (int)i * 3;
        if (r + 1 >= TASK_R - 1) break;   /* would collide with taskbar */
        fb_text(r, 2, icons[i][0], C_BTN_HL, g_desk_color, ATTR_BOLD);
        /* Truncate label to fit. */
        const char *lbl = icons[i][1];
        char buf[32];
        int ll = (int)strlen(lbl);
        if (ll > label_max) ll = label_max;
        if (ll < 0) ll = 0;
        memcpy(buf, lbl, ll);
        buf[ll] = 0;
        fb_text(r + 1, 1, buf, C_BTN_HL, g_desk_color, 0);
    }
}

static void paint_taskbar(void) {
    /* Taskbar across the entire bottom row.  One-row highlight above
     * to mimic the Win95 3D-raised edge. */
    fb_fill(TASK_R, 0, TASK_R, VIS_W - 1, ' ', C_TEXT, C_BTN);
    for (int c = 0; c < VIS_W; c++) fb_put(TASK_R - 1, c, ' ', C_TEXT, C_BTN_HL, 0);
    /* Start button. */
    draw_button(TASK_R, 0, 9, "Start", g_mode == MODE_START);
    /* Window-on-taskbar pill — depressed when the window is foreground
     * (matching Win95: an open active window shows its taskbar entry
     * "pressed in") and raised when minimized. */
    if (VIS_W >= 40) {
        int pill_c1 = (VIS_W - 8) - 2;
        if (pill_c1 > 30) pill_c1 = 30;
        const char *pill_label =
              g_current_app == APP_NOTEPAD ? "Untitled - Notepad"
            : g_current_app == APP_CALC    ? "Calculator"
            : g_current_app == APP_PAINT   ? "Paint"
            : g_current_app == APP_DOS     ? "MS-DOS Prompt"
            : "win95term";
        draw_button(TASK_R, 11, pill_c1, pill_label, !g_win_minimized);
    }
    /* Clock on the right (if user hasn't hidden it). */
    if (g_show_clock) {
        time_t now = time(NULL);
        struct tm tm; localtime_r(&now, &tm);
        char clock[16];
        snprintf(clock, sizeof clock, "%02d:%02d", tm.tm_hour, tm.tm_min);
        fb_text(TASK_R, VIS_W - 7, clock, C_TEXT, C_BTN, 0);
    }
}

static void paint_main_window(void) {
    /* Window frame: outset border around (WIN_R0..WIN_R1, WIN_C0..WIN_C1). */
    draw_outset(WIN_R0, WIN_C0, WIN_R1, WIN_C1, C_BTN);

    /* Title bar (one row inside the frame). */
    int tr = WIN_R0 + 1;
    fb_fill(tr, WIN_C0 + 1, tr, WIN_C1 - 1, ' ', C_TITLE_FG, C_TITLE_BG);
    /* Title text reflects the currently-open app. */
    const char *title;
    switch (g_current_app) {
    case APP_NOTEPAD: title = "Untitled - Notepad"; break;
    case APP_CALC:    title = "Calculator";         break;
    case APP_PAINT:   title = "untitled - Paint";   break;
    case APP_DOS:     title = "MS-DOS Prompt";      break;
    default:          title = "win95term";          break;
    }
    fb_text(tr, WIN_C0 + 2, title, C_TITLE_FG, C_TITLE_BG, ATTR_BOLD);
    /* [_] [o] [x] window buttons on the right side of the title bar.
     * Mini-buttons are flat-face (see draw_titlebar_button comment). */
    draw_titlebar_button(tr, WIN_C1 - 9, WIN_C1 - 7, "_");
    draw_titlebar_button(tr, WIN_C1 - 6, WIN_C1 - 4, "o");   /* maximize */
    draw_titlebar_button(tr, WIN_C1 - 3, WIN_C1 - 1, "x");

    /* Menu bar (one row below title). */
    int mr = WIN_R0 + 2;
    fb_fill(mr, WIN_C0 + 1, mr, WIN_C1 - 1, ' ', C_TEXT, C_BTN);
    for (int i = 0; i < g_menubar_n; i++) {
        int hot_col = WIN_C0 + g_menubar[i].col_off + 1;
        int bg = (g_mode == g_menubar[i].mode) ? C_HL_BG : C_BTN;
        int fg = (g_mode == g_menubar[i].mode) ? C_HL_FG : C_TEXT;
        for (int j = 0; g_menubar[i].label[j]; j++) {
            int a = (g_menubar[i].label[j] == g_menubar[i].hot) ? ATTR_UNDER : 0;
            fb_put(mr, hot_col + j, g_menubar[i].label[j], fg, bg, a);
        }
    }

    /* Content area: sunken field. */
    int br = WIN_R0 + 3;            /* body start row */
    int sr = WIN_R1 - 1;            /* status row */
    draw_inset(br, WIN_C0 + 1, sr - 1, WIN_C1 - 1, C_FIELD_BG);
    switch (g_current_app) {
    case APP_NOTEPAD: {
        /* Render the notepad buffer wrapped at the content width. */
        int x = WIN_C0 + 3, y = br + 2;
        int max_x = WIN_C1 - 2;
        for (int i = 0; i < g_notepad_len; i++) {
            char c = g_notepad_buf[i];
            if (c == '\n' || x > max_x) {
                x = WIN_C0 + 3;
                y++;
                if (y >= sr - 1) break;
                if (c == '\n') continue;
            }
            fb_put(y, x++, c, C_TEXT, C_FIELD_BG, 0);
        }
        /* Blinking caret approximation: a solid block at the insertion point. */
        if (g_notepad_editing && y < sr - 1)
            fb_put(y, x, '_', C_TEXT, C_FIELD_BG, ATTR_BOLD);
        else if (!g_notepad_editing && g_notepad_len == 0)
            fb_text(br + 2, WIN_C0 + 4, "Press s in the body to start typing.",
                    C_BTN_SH, C_FIELD_BG, 0);
        break;
    }
    case APP_CALC: {
        /* A static fake calc keypad — just for the look. */
        fb_text(br + 1, WIN_C0 + 3, "                          0.", C_TEXT, C_FIELD_BG, ATTR_BOLD);
        static const char *rows[] = {
            "  Backspace   CE     C   ",
            "   MC   7   8   9   /  sqrt",
            "   MR   4   5   6   *   %  ",
            "   MS   1   2   3   -  1/x ",
            "   M+   0  +/-  .   +   =  ",
        };
        for (int i = 0; i < 5; i++) {
            int rr = br + 3 + i;
            if (rr >= sr - 1) break;
            fb_text(rr, WIN_C0 + 3, rows[i], C_TEXT, C_FIELD_BG, 0);
        }
        break;
    }
    case APP_PAINT:
        fb_text(br + 2, WIN_C0 + 4, "Paint canvas (placeholder)",
                C_BTN_SH, C_FIELD_BG, 0);
        fb_text(br + 4, WIN_C0 + 4, "Real raster editor on a future commit.",
                C_BTN_SH, C_FIELD_BG, 0);
        break;
    case APP_DOS:
        /* Black background DOS prompt look — paint over the field. */
        fb_fill(br + 1, WIN_C0 + 2, sr - 2, WIN_C1 - 2, ' ', 15, 16);
        fb_text(br + 1, WIN_C0 + 3, "Microsoft(R) Windows 95",        15, 16, 0);
        fb_text(br + 2, WIN_C0 + 3, "(C)Copyright Microsoft Corp 1981-1995.", 15, 16, 0);
        fb_text(br + 4, WIN_C0 + 3, "C:\\WINDOWS>_",                  15, 16, ATTR_BOLD);
        break;
    default:
        fb_text(br + 2, WIN_C0 + 4, "Welcome to win95term.",          C_TEXT, C_FIELD_BG, ATTR_BOLD);
        fb_text(br + 4, WIN_C0 + 4, "Move the cursor with:",          C_TEXT, C_FIELD_BG, 0);
        fb_text(br + 5, WIN_C0 + 6, " w  e        a/d  left/right",   C_TEXT, C_FIELD_BG, 0);
        fb_text(br + 6, WIN_C0 + 6, " z  x        s  click, f  rclick",C_TEXT, C_FIELD_BG, 0);
        fb_text(br + 8, WIN_C0 + 4, "Try: Start > Programs > Notepad.", C_TEXT, C_FIELD_BG, 0);
        break;
    }

    /* Status bar (one row above the frame's bottom edge). */
    fb_fill(sr, WIN_C0 + 1, sr, WIN_C1 - 1, ' ', C_TEXT, C_BTN);
    char st[64];
    snprintf(st, sizeof st, "cursor: (%d,%d)  grid: %s  mode: %s",
             g_cur_r, g_cur_c,
             g_hex_grid ? "hex" : "square",
             g_mode == MODE_DESKTOP    ? "desktop"
             : g_mode == MODE_FILE_MENU ? "File menu"
             : g_mode == MODE_HELP_MENU ? "Help menu"
             : g_mode == MODE_ABOUT     ? "About dialog"
             : g_mode == MODE_START     ? "Start menu"
             : g_mode == MODE_PROGRAMS  ? "Programs"
             : g_mode == MODE_CONTEXT   ? "Context menu"
             : g_mode == MODE_DP        ? "Display Properties" : "?");
    fb_text(sr, WIN_C0 + 2, st, C_TEXT, C_BTN, 0);
}

static void paint_dropdown(int mode, int anchor_col, const char **items, int n) {
    int r0 = WIN_R0 + 3;
    int c0 = anchor_col;
    int w  = 22;
    int r1 = r0 + n + 1;
    int c1 = c0 + w;
    draw_outset(r0, c0, r1, c1, C_BTN);
    for (int i = 0; i < n; i++) {
        int rr = r0 + 1 + i;
        int sel = (i == g_menu_sel);
        int bg = sel ? C_HL_BG : C_BTN;
        int fg = sel ? C_HL_FG : C_TEXT;
        fb_fill(rr, c0 + 1, rr, c1 - 1, ' ', fg, bg);
        fb_text(rr, c0 + 2, items[i], fg, bg, 0);
    }
    (void)mode;
}

/* Compute the About dialog's geometry — centered on the main window,
 * sized to fit, clamped to a sane min/max.  Used by paint and
 * hit-test so they can't disagree. */
static void about_geom(int *r0, int *c0, int *r1, int *c1) {
    int dw = 40, dh = 10;
    int win_w = WIN_C1 - WIN_C0 + 1;
    int win_h = WIN_R1 - WIN_R0 + 1;
    if (dw > win_w - 4) dw = win_w - 4;
    if (dh > win_h - 4) dh = win_h - 4;
    if (dw < 24) dw = 24;
    if (dh < 7)  dh = 7;
    *c0 = (WIN_C0 + WIN_C1) / 2 - dw / 2;
    *r0 = (WIN_R0 + WIN_R1) / 2 - dh / 2;
    *c1 = *c0 + dw - 1;
    *r1 = *r0 + dh - 1;
}

/* ── Start menu flyout ───────────────────────────────────
 *
 * Pops up ABOVE the Start button.  Left side has a 2-column navy
 * stripe with "Windows 95" stacked vertically (the iconic look).
 * Items list runs down the right side; cursor over an item lights
 * it up via the standard C_HL_BG / C_HL_FG selection palette. */
static const char *g_start_items[] = {
    " Programs           ", /* >'s deferred — no submenu yet */
    " Help              ",
    " Settings...       ", /* Was "Run..." — now opens Display Properties */
    " About win95term   ",
    "───────────────────",     /* separator */
    " Shut Down...      ",
};
static const int g_start_n = sizeof g_start_items / sizeof g_start_items[0];

static void start_geom(int *r0, int *c0, int *r1, int *c1) {
    int w  = 22;
    int h  = g_start_n + 2;       /* +2 for top/bottom 3D frame */
    *c0 = 0;
    *r1 = TASK_R - 1;             /* sit on the highlight row above taskbar */
    *r0 = *r1 - h + 1;
    if (*r0 < 0) *r0 = 0;
    *c1 = *c0 + w - 1;
    if (*c1 >= VIS_W) *c1 = VIS_W - 1;
}

static void paint_start_menu(void) {
    int r0, c0, r1, c1;
    start_geom(&r0, &c0, &r1, &c1);
    draw_outset(r0, c0, r1, c1, C_BTN);

    /* Left stripe: 2 cols wide, navy.  "Windows 95" stacked
     * top-down so it reads naturally even though it's vertical. */
    int sr0 = r0 + 1, sr1 = r1 - 1, sc0 = c0 + 1, sc1 = c0 + 2;
    fb_fill(sr0, sc0, sr1, sc1, ' ', C_TITLE_FG, C_TITLE_BG);
    static const char stripe[] = "Windows95";
    int stripe_len = (int)(sizeof stripe - 1);
    int stripe_rows = sr1 - sr0 + 1;
    int start_r = sr0 + (stripe_rows - stripe_len) / 2;
    if (start_r < sr0) start_r = sr0;
    for (int i = 0; i < stripe_len; i++) {
        int rr = start_r + i;
        if (rr > sr1) break;
        fb_put(rr, sc0 + 1, stripe[i], C_TITLE_FG, C_TITLE_BG, ATTR_BOLD);
    }

    /* Items, with cursor-row selection.  Item rows start two cols
     * inside the stripe. */
    for (int i = 0; i < g_start_n; i++) {
        int rr = r0 + 1 + i;
        if (rr > r1 - 1) break;
        int sel = (g_cur_r == rr && g_cur_c >= c0 + 3 && g_cur_c <= c1 - 1);
        int bg = sel ? C_HL_BG : C_BTN;
        int fg = sel ? C_HL_FG : C_TEXT;
        fb_fill(rr, c0 + 3, rr, c1 - 1, ' ', fg, bg);
        fb_text(rr, c0 + 3, g_start_items[i], fg, bg, 0);
    }
}

/* ── Programs cascading submenu ──────────────────────────
 *
 * Pops out to the right of the Start menu when the user clicks
 * "Programs".  Same hover-highlight visual as the parent.  Items
 * map to g_current_app values; selecting one swaps the main
 * window's title and content. */
static const char *g_programs_items[] = {
    " Notepad           ",
    " Calculator        ",
    " Paint             ",
    " MS-DOS Prompt     ",
    "───────────────────",
    " Windows Explorer  ",
};
static const int g_programs_n = sizeof g_programs_items / sizeof g_programs_items[0];

static void programs_geom(int *r0, int *c0, int *r1, int *c1) {
    int sr0, sc0, sr1, sc1;
    start_geom(&sr0, &sc0, &sr1, &sc1);
    int w = 22;
    int h = g_programs_n + 2;
    *r0 = sr0 + 1;          /* "Programs" is item index 0 → row sr0 + 1 */
    *c0 = sc1 + 1;
    *r1 = *r0 + h - 1;
    *c1 = *c0 + w - 1;
    if (*c1 >= VIS_W) {
        /* Not enough room on the right — pop to the LEFT of the
         * Start menu instead (rare; happens in very narrow terms). */
        *c0 = sc0 - w; if (*c0 < 0) *c0 = 0;
        *c1 = *c0 + w - 1;
    }
    if (*r1 >= TASK_R) *r1 = TASK_R - 1;
}

static void paint_programs_submenu(void) {
    int r0, c0, r1, c1;
    programs_geom(&r0, &c0, &r1, &c1);
    draw_outset(r0, c0, r1, c1, C_BTN);
    for (int i = 0; i < g_programs_n; i++) {
        int rr = r0 + 1 + i;
        if (rr > r1 - 1) break;
        int sel = (g_cur_r == rr && g_cur_c >= c0 + 1 && g_cur_c <= c1 - 1);
        int bg = sel ? C_HL_BG : C_BTN;
        int fg = sel ? C_HL_FG : C_TEXT;
        fb_fill(rr, c0 + 1, rr, c1 - 1, ' ', fg, bg);
        fb_text(rr, c0 + 1, g_programs_items[i], fg, bg, 0);
    }
}

/* ── Right-click context menu ────────────────────────────
 *
 * Pops up at the cursor's position when `f` is pressed.  Clamped to
 * stay within the visible area.  Re-uses the dropdown look. */
static const char *g_ctx_items[] = {
    " View             ",
    " Refresh          ",
    "──────────────────",
    " New              ",
    " Properties       ",
};
static const int g_ctx_n = sizeof g_ctx_items / sizeof g_ctx_items[0];

static void context_geom(int *r0, int *c0, int *r1, int *c1) {
    int w = 20;
    int h = g_ctx_n + 2;
    *r0 = g_ctx_r;
    *c0 = g_ctx_c;
    if (*r0 + h > VIS_H) *r0 = VIS_H - h;
    if (*c0 + w > VIS_W) *c0 = VIS_W - w;
    if (*r0 < 0) *r0 = 0;
    if (*c0 < 0) *c0 = 0;
    *r1 = *r0 + h - 1;
    *c1 = *c0 + w - 1;
}

static void paint_context_menu(void) {
    int r0, c0, r1, c1;
    context_geom(&r0, &c0, &r1, &c1);
    draw_outset(r0, c0, r1, c1, C_BTN);
    for (int i = 0; i < g_ctx_n; i++) {
        int rr = r0 + 1 + i;
        if (rr > r1 - 1) break;
        int sel = (g_cur_r == rr && g_cur_c >= c0 + 1 && g_cur_c <= c1 - 1);
        int bg = sel ? C_HL_BG : C_BTN;
        int fg = sel ? C_HL_FG : C_TEXT;
        fb_fill(rr, c0 + 1, rr, c1 - 1, ' ', fg, bg);
        fb_text(rr, c0 + 1, g_ctx_items[i], fg, bg, 0);
    }
}

static void paint_about_dialog(void) {
    int r0, c0, r1, c1;
    about_geom(&r0, &c0, &r1, &c1);
    draw_outset(r0, c0, r1, c1, C_BTN);
    /* Title bar */
    fb_fill(r0 + 1, c0 + 1, r0 + 1, c1 - 1, ' ', C_TITLE_FG, C_TITLE_BG);
    fb_text(r0 + 1, c0 + 2, "About win95term", C_TITLE_FG, C_TITLE_BG, ATTR_BOLD);
    draw_titlebar_button(r0 + 1, c1 - 3, c1 - 1, "x");
    /* Body */
    fb_text(r0 + 3, c0 + 4, "win95term v0.1",         C_TEXT, C_BTN, ATTR_BOLD);
    fb_text(r0 + 4, c0 + 4, "Win95/98 look-and-feel,", C_TEXT, C_BTN, 0);
    fb_text(r0 + 5, c0 + 4, "rendered in 256-color ANSI.", C_TEXT, C_BTN, 0);
    fb_text(r0 + 7, c0 + 4, "Cursor: w/e/a/d/z/x.",    C_TEXT, C_BTN, 0);
    fb_text(r0 + 8, c0 + 4, "Click: s.   Right-click: f.", C_TEXT, C_BTN, 0);
    /* OK button (centered, depressed look if cursor is on it) */
    int btn_r = r1 - 1;
    int btn_c0 = (c0 + c1) / 2 - 4;
    int btn_c1 = btn_c0 + 8;
    int hovering = (g_cur_r == btn_r && g_cur_c >= btn_c0 && g_cur_c <= btn_c1);
    draw_button(btn_r, btn_c0, btn_c1, "OK", hovering);
}

/* ── Widget primitives ──────────────────────────────────── *
 *
 * Checkbox, radio button, group box.  All paint inline at (r, c)
 * onto the framebuffer using the C_FIELD_BG (white) for the bullet
 * and C_BTN (silver) for the surrounding label area.  Hit-testing
 * uses the same anchor coordinates.
 *
 * Checkbox glyphs: "[x]" filled, "[ ]" empty.
 * Radio glyphs:    "(*)" filled, "( )" empty. */
static void draw_checkbox(int r, int c, int checked, const char *label, int focused) {
    int bg = focused ? C_HL_BG : C_BTN;
    int fg = focused ? C_HL_FG : C_TEXT;
    fb_put(r, c,     '[', fg, bg, 0);
    fb_put(r, c + 1, checked ? 'x' : ' ', fg, bg, ATTR_BOLD);
    fb_put(r, c + 2, ']', fg, bg, 0);
    fb_put(r, c + 3, ' ', fg, bg, 0);
    fb_text(r, c + 4, label, fg, bg, 0);
}

static void draw_radio(int r, int c, int filled, const char *label, int focused) {
    int bg = focused ? C_HL_BG : C_BTN;
    int fg = focused ? C_HL_FG : C_TEXT;
    fb_put(r, c,     '(', fg, bg, 0);
    fb_put(r, c + 1, filled ? '*' : ' ', fg, bg, ATTR_BOLD);
    fb_put(r, c + 2, ')', fg, bg, 0);
    fb_put(r, c + 3, ' ', fg, bg, 0);
    fb_text(r, c + 4, label, fg, bg, 0);
}

/* Group box: an etched rectangle with a label inserted into the top
 * edge.  In Win95 this is the "─── Color scheme ─────" pattern
 * around a cluster of related controls.  Uses ASCII '─' / '│'
 * substitutes (terminal box-drawing) to keep the source ASCII-safe. */
static void draw_groupbox(int r0, int c0, int r1, int c1, const char *label) {
    /* Top edge */
    fb_put(r0, c0, '+', C_BTN_SH, C_BTN, 0);
    for (int c = c0 + 1; c < c1; c++) fb_put(r0, c, '-', C_BTN_SH, C_BTN, 0);
    fb_put(r0, c1, '+', C_BTN_SH, C_BTN, 0);
    /* Bottom edge */
    fb_put(r1, c0, '+', C_BTN_SH, C_BTN, 0);
    for (int c = c0 + 1; c < c1; c++) fb_put(r1, c, '-', C_BTN_SH, C_BTN, 0);
    fb_put(r1, c1, '+', C_BTN_SH, C_BTN, 0);
    /* Side edges */
    for (int r = r0 + 1; r < r1; r++) {
        fb_put(r, c0, '|', C_BTN_SH, C_BTN, 0);
        fb_put(r, c1, '|', C_BTN_SH, C_BTN, 0);
    }
    /* Label embedded in the top edge — pad with spaces so it doesn't
     * touch the surrounding dashes. */
    if (label && *label) {
        int label_len = (int)strlen(label);
        int lc = c0 + 2;
        fb_put(r0, lc - 1, ' ', C_TEXT, C_BTN, 0);
        fb_text(r0, lc, label, C_TEXT, C_BTN, ATTR_BOLD);
        fb_put(r0, lc + label_len, ' ', C_TEXT, C_BTN, 0);
    }
}

/* ── Display Properties dialog ──────────────────────────── *
 *
 * A real applied dialog using the new widgets.  Checkboxes toggle
 * g_show_icons / g_show_clock / g_hex_grid; radio buttons pick the
 * desktop color (g_desk_color).  Cursor over a widget highlights
 * it; pressing s on a widget changes its value.  OK applies (no-op,
 * since state is mutated live) and closes; Cancel reverts and closes. */

/* Color presets for the radio group. */
static const struct { int slot; const char *name; } g_color_presets[] = {
    { 23,  "Win95 Teal"   },
    { 18,  "Navy Solid"   },
    { 53,  "Plum"         },
    { 230, "Cream Linen"  },
};
static const int g_n_color_presets = sizeof g_color_presets / sizeof g_color_presets[0];

/* Snapshot of state at dialog open — used to roll back on Cancel. */
static int g_dp_saved_color = 0;
static int g_dp_saved_icons = 0;
static int g_dp_saved_clock = 0;
static int g_dp_saved_hex   = 0;

static void dp_geom(int *r0, int *c0, int *r1, int *c1) {
    int dw = 44, dh = 16;
    int win_w = WIN_C1 - WIN_C0 + 1;
    int win_h = WIN_R1 - WIN_R0 + 1;
    if (dw > win_w - 2) dw = win_w - 2;
    if (dh > win_h - 2) dh = win_h - 2;
    if (dw < 30) dw = 30;
    if (dh < 12) dh = 12;
    *c0 = (WIN_C0 + WIN_C1) / 2 - dw / 2;
    *r0 = (WIN_R0 + WIN_R1) / 2 - dh / 2;
    *c1 = *c0 + dw - 1;
    *r1 = *r0 + dh - 1;
}

/* Per-widget hit boxes computed from the dialog rect.  Returns the
 * widget row baseline so the painter and hit-test can agree. */
static int dp_row_color(int r0, int i) { return r0 + 3 + i; }       /* radio row */
static int dp_row_check(int r0, int i) { return r0 + 9 + i; }       /* checkbox row */
static int dp_row_ok(int r1)           { return r1 - 1; }           /* OK/Cancel row */

static void paint_dp_dialog(void) {
    int r0, c0, r1, c1;
    dp_geom(&r0, &c0, &r1, &c1);
    draw_outset(r0, c0, r1, c1, C_BTN);

    /* Title bar */
    fb_fill(r0 + 1, c0 + 1, r0 + 1, c1 - 1, ' ', C_TITLE_FG, C_TITLE_BG);
    fb_text(r0 + 1, c0 + 2, "Display Properties", C_TITLE_FG, C_TITLE_BG, ATTR_BOLD);
    draw_titlebar_button(r0 + 1, c1 - 3, c1 - 1, "x");

    /* Group: Color scheme (radio buttons) */
    draw_groupbox(r0 + 2, c0 + 2, r0 + 7, c1 - 2, "Color scheme");
    for (int i = 0; i < g_n_color_presets; i++) {
        int rr = dp_row_color(r0, i);
        if (rr >= r0 + 7) break;
        int focused = (g_cur_r == rr && g_cur_c >= c0 + 4 && g_cur_c <= c1 - 4);
        int filled  = (g_desk_color == g_color_presets[i].slot);
        draw_radio(rr, c0 + 4, filled, g_color_presets[i].name, focused);
    }

    /* Group: Options (checkboxes) */
    draw_groupbox(r0 + 8, c0 + 2, r1 - 3, c1 - 2, "Options");
    {
        int rr = dp_row_check(r0, 0);
        int focused = (g_cur_r == rr && g_cur_c >= c0 + 4 && g_cur_c <= c1 - 4);
        draw_checkbox(rr, c0 + 4, g_show_icons, "Show desktop icons", focused);
    }
    {
        int rr = dp_row_check(r0, 1);
        int focused = (g_cur_r == rr && g_cur_c >= c0 + 4 && g_cur_c <= c1 - 4);
        draw_checkbox(rr, c0 + 4, g_show_clock, "Show taskbar clock", focused);
    }
    {
        int rr = dp_row_check(r0, 2);
        int focused = (g_cur_r == rr && g_cur_c >= c0 + 4 && g_cur_c <= c1 - 4);
        draw_checkbox(rr, c0 + 4, g_hex_grid, "Hex-grid cursor", focused);
    }

    /* OK / Cancel buttons */
    int btn_r = dp_row_ok(r1);
    int ok_c0 = c1 - 22, ok_c1 = c1 - 13;
    int cn_c0 = c1 - 10, cn_c1 = c1 - 2;
    int ok_hover = (g_cur_r == btn_r && g_cur_c >= ok_c0 && g_cur_c <= ok_c1);
    int cn_hover = (g_cur_r == btn_r && g_cur_c >= cn_c0 && g_cur_c <= cn_c1);
    draw_button(btn_r, ok_c0, ok_c1, "OK",     ok_hover);
    draw_button(btn_r, cn_c0, cn_c1, "Cancel", cn_hover);
}

static void paint_frame(void) {
    paint_desktop();
    /* Skip the main window entirely when minimized — the taskbar pill
     * is the only handle left. */
    if (!g_win_minimized) paint_main_window();
    if (g_mode == MODE_FILE_MENU) {
        int anchor = WIN_C0 + g_menubar[0].col_off;
        paint_dropdown(MODE_FILE_MENU, anchor, g_file_items, g_file_n);
    } else if (g_mode == MODE_HELP_MENU) {
        int anchor = WIN_C0 + g_menubar[1].col_off;
        paint_dropdown(MODE_HELP_MENU, anchor, g_help_items, g_help_n);
    } else if (g_mode == MODE_ABOUT) {
        paint_about_dialog();
    } else if (g_mode == MODE_DP) {
        paint_dp_dialog();
    }
    paint_taskbar();
    /* Overlays paint AFTER the taskbar so they stack on top. */
    if (g_mode == MODE_START || g_mode == MODE_PROGRAMS) paint_start_menu();
    if (g_mode == MODE_PROGRAMS) paint_programs_submenu();
    if (g_mode == MODE_CONTEXT)  paint_context_menu();
}

/* ── Cursor movement ─────────────────────────────────────── */
static void move_cursor(int dr, int dc) {
    int nr = g_cur_r + dr;
    int nc = g_cur_c + dc;
    if (nr < 0) nr = 0;
    if (nr >= VIS_H) nr = VIS_H - 1;
    if (nc < 0) nc = 0;
    if (nc >= VIS_W) nc = VIS_W - 1;
    g_cur_r = nr;
    g_cur_c = nc;
}

/* Map w/e/a/d/z/x to (dr, dc) deltas.
 *
 * Square mode (default): six classical compass-ish moves.  W/E up,
 * A/D side, Z/X down, all diagonal where applicable.
 *
 * Hex mode (G toggles): pointy-top offset coordinates.  On odd rows
 * the column deltas for NW/NE/SW/SE shift by +1 so that w/e/z/x
 * traverse the actual hex neighborhood.  W/E remain row-aligned. */
static void handle_movement(char k) {
    int dr = 0, dc = 0;
    if (g_hex_grid) {
        int odd = (g_cur_r & 1);
        switch (k) {
        case 'w': dr = -1; dc = odd ?  0 : -1; break;  /* NW */
        case 'e': dr = -1; dc = odd ?  1 :  0; break;  /* NE */
        case 'a': dr =  0; dc = -1;            break;  /* W  */
        case 'd': dr =  0; dc =  1;            break;  /* E  */
        case 'z': dr =  1; dc = odd ?  0 : -1; break;  /* SW */
        case 'x': dr =  1; dc = odd ?  1 :  0; break;  /* SE */
        }
    } else {
        switch (k) {
        case 'w': dr = -1; dc = -1; break;
        case 'e': dr = -1; dc =  1; break;
        case 'a': dr =  0; dc = -1; break;
        case 'd': dr =  0; dc =  1; break;
        case 'z': dr =  1; dc = -1; break;
        case 'x': dr =  1; dc =  1; break;
        }
    }
    move_cursor(dr, dc);
}

/* What's under the cursor right now?  Returns a small integer code for
 * the click handler to act on. */
enum { HIT_NONE, HIT_MENU_FILE, HIT_MENU_HELP, HIT_FILE_ABOUT, HIT_FILE_EXIT,
       HIT_HELP_KEYS, HIT_HELP_ABOUT, HIT_DIALOG_OK, HIT_TITLE_X,
       /* Main-window title-bar mini-buttons (in addition to TITLE_X). */
       HIT_TITLE_MIN, HIT_TITLE_MAX,
       /* Click on the taskbar pill restores a minimized window. */
       HIT_TASKBAR_PILL,
       HIT_START,
       /* Start-menu items (in order). */
       HIT_START_PROGRAMS, HIT_START_HELP, HIT_START_RUN,
       HIT_START_ABOUT, HIT_START_SEP, HIT_START_SHUTDOWN,
       /* Context-menu items (in order). */
       HIT_CTX_VIEW, HIT_CTX_REFRESH, HIT_CTX_SEP,
       HIT_CTX_NEW, HIT_CTX_PROPERTIES,
       /* Display Properties widgets. */
       HIT_DP_COLOR_0, HIT_DP_COLOR_1, HIT_DP_COLOR_2, HIT_DP_COLOR_3,
       HIT_DP_CHECK_ICONS, HIT_DP_CHECK_CLOCK, HIT_DP_CHECK_HEX,
       HIT_DP_OK, HIT_DP_CANCEL, HIT_DP_TITLE_X,
       /* Programs submenu items. */
       HIT_PROG_NOTEPAD, HIT_PROG_CALC, HIT_PROG_PAINT, HIT_PROG_DOS,
       HIT_PROG_SEP, HIT_PROG_EXPLORER };

static int hit_test(void) {
    int r = g_cur_r, c = g_cur_c;
    if (g_mode == MODE_ABOUT) {
        int r0, c0, r1, c1;
        about_geom(&r0, &c0, &r1, &c1);
        int btn_r = r1 - 1;
        int btn_c0 = (c0 + c1) / 2 - 4;
        int btn_c1 = btn_c0 + 8;
        if (r == btn_r && c >= btn_c0 && c <= btn_c1) return HIT_DIALOG_OK;
        if (r == r0 + 1 && c >= c1 - 3 && c <= c1 - 1) return HIT_DIALOG_OK;  /* x button closes */
        return HIT_NONE;
    }
    /* Title bar mini-buttons.  Order on the right: _ then o then x. */
    if (r == WIN_R0 + 1) {
        if (c >= WIN_C1 - 9 && c <= WIN_C1 - 7) return HIT_TITLE_MIN;
        if (c >= WIN_C1 - 6 && c <= WIN_C1 - 4) return HIT_TITLE_MAX;
        if (c >= WIN_C1 - 3 && c <= WIN_C1 - 1) return HIT_TITLE_X;
    }
    /* Taskbar pill restores a minimized window. */
    if (r == TASK_R && c >= 11 && c <= 30 && g_win_minimized)
        return HIT_TASKBAR_PILL;
    /* Menu bar items. */
    if (r == WIN_R0 + 2) {
        for (int i = 0; i < g_menubar_n; i++) {
            int c0 = WIN_C0 + g_menubar[i].col_off + 1;
            int c1 = c0 + (int)strlen(g_menubar[i].label) - 1;
            if (c >= c0 && c <= c1) {
                return (i == 0) ? HIT_MENU_FILE : HIT_MENU_HELP;
            }
        }
    }
    /* File dropdown items. */
    if (g_mode == MODE_FILE_MENU) {
        int r0 = WIN_R0 + 3;
        int c0 = WIN_C0 + g_menubar[0].col_off;
        if (r >= r0 + 1 && r <= r0 + g_file_n && c >= c0 && c <= c0 + 22) {
            int idx = r - (r0 + 1);
            if (idx == 0) return HIT_FILE_ABOUT;
            if (idx == 1) return HIT_FILE_EXIT;
        }
    }
    /* Help dropdown items. */
    if (g_mode == MODE_HELP_MENU) {
        int r0 = WIN_R0 + 3;
        int c0 = WIN_C0 + g_menubar[1].col_off;
        if (r >= r0 + 1 && r <= r0 + g_help_n && c >= c0 && c <= c0 + 22) {
            int idx = r - (r0 + 1);
            if (idx == 0) return HIT_HELP_KEYS;
            if (idx == 1) return HIT_HELP_ABOUT;
        }
    }
    /* Start button. */
    if (r == TASK_R && c <= 9) return HIT_START;

    /* Programs submenu items. */
    if (g_mode == MODE_PROGRAMS) {
        int pr0, pc0, pr1, pc1;
        programs_geom(&pr0, &pc0, &pr1, &pc1);
        if (r >= pr0 + 1 && r <= pr0 + g_programs_n &&
            c >= pc0 + 1 && c <= pc1 - 1) {
            int idx = r - (pr0 + 1);
            static const int map[] = {
                HIT_PROG_NOTEPAD, HIT_PROG_CALC, HIT_PROG_PAINT,
                HIT_PROG_DOS, HIT_PROG_SEP, HIT_PROG_EXPLORER
            };
            if (idx >= 0 && idx < (int)(sizeof map / sizeof map[0]))
                return map[idx];
        }
        /* Click outside the submenu in PROGRAMS mode falls through to
         * Start-menu hit-testing below so the user can navigate back. */
    }

    /* Start menu items (also applies when in PROGRAMS mode so the
     * cursor can hop back into the parent menu). */
    if (g_mode == MODE_START || g_mode == MODE_PROGRAMS) {
        int sr0, sc0, sr1, sc1;
        start_geom(&sr0, &sc0, &sr1, &sc1);
        if (r >= sr0 + 1 && r <= sr0 + g_start_n &&
            c >= sc0 + 3 && c <= sc1 - 1) {
            int idx = r - (sr0 + 1);
            static const int map[] = {
                HIT_START_PROGRAMS, HIT_START_HELP, HIT_START_RUN,
                HIT_START_ABOUT, HIT_START_SEP, HIT_START_SHUTDOWN
            };
            if (idx >= 0 && idx < (int)(sizeof map / sizeof map[0]))
                return map[idx];
        }
    }

    /* Display Properties widgets. */
    if (g_mode == MODE_DP) {
        int dr0, dc0, dr1, dc1;
        dp_geom(&dr0, &dc0, &dr1, &dc1);
        /* Title bar × */
        if (r == dr0 + 1 && c >= dc1 - 3 && c <= dc1 - 1) return HIT_DP_TITLE_X;
        /* Color radios */
        for (int i = 0; i < g_n_color_presets; i++) {
            int rr = dp_row_color(dr0, i);
            if (rr >= dr0 + 7) break;
            if (r == rr && c >= dc0 + 4 && c <= dc1 - 4)
                return HIT_DP_COLOR_0 + i;
        }
        /* Option checkboxes */
        if (r == dp_row_check(dr0, 0) && c >= dc0 + 4 && c <= dc1 - 4) return HIT_DP_CHECK_ICONS;
        if (r == dp_row_check(dr0, 1) && c >= dc0 + 4 && c <= dc1 - 4) return HIT_DP_CHECK_CLOCK;
        if (r == dp_row_check(dr0, 2) && c >= dc0 + 4 && c <= dc1 - 4) return HIT_DP_CHECK_HEX;
        /* OK / Cancel buttons */
        int btn_r = dp_row_ok(dr1);
        int ok_c0 = dc1 - 22, ok_c1 = dc1 - 13;
        int cn_c0 = dc1 - 10, cn_c1 = dc1 - 2;
        if (r == btn_r && c >= ok_c0 && c <= ok_c1) return HIT_DP_OK;
        if (r == btn_r && c >= cn_c0 && c <= cn_c1) return HIT_DP_CANCEL;
        return HIT_NONE;
    }

    /* Context menu items. */
    if (g_mode == MODE_CONTEXT) {
        int xr0, xc0, xr1, xc1;
        context_geom(&xr0, &xc0, &xr1, &xc1);
        if (r >= xr0 + 1 && r <= xr0 + g_ctx_n &&
            c >= xc0 + 1 && c <= xc1 - 1) {
            int idx = r - (xr0 + 1);
            static const int map[] = {
                HIT_CTX_VIEW, HIT_CTX_REFRESH, HIT_CTX_SEP,
                HIT_CTX_NEW, HIT_CTX_PROPERTIES
            };
            if (idx >= 0 && idx < (int)(sizeof map / sizeof map[0]))
                return map[idx];
        }
    }
    return HIT_NONE;
}

/* ── Click handlers ──────────────────────────────────────── */
static int handle_click(void) {
    int hit = hit_test();
    switch (hit) {
    case HIT_MENU_FILE:
        g_mode = (g_mode == MODE_FILE_MENU) ? MODE_DESKTOP : MODE_FILE_MENU;
        g_menu_sel = 0;
        break;
    case HIT_MENU_HELP:
        g_mode = (g_mode == MODE_HELP_MENU) ? MODE_DESKTOP : MODE_HELP_MENU;
        g_menu_sel = 0;
        break;
    case HIT_FILE_ABOUT:
    case HIT_HELP_ABOUT: {
        g_mode = MODE_ABOUT;
        int r0, c0, r1, c1;
        about_geom(&r0, &c0, &r1, &c1);
        g_cur_r = r1 - 1;
        g_cur_c = (c0 + c1) / 2;          /* land on the OK button */
        break;
    }
    case HIT_FILE_EXIT:
        return 1;
    case HIT_HELP_KEYS:
        /* Future: keyboard-help dialog.  For now collapse to About. */
        g_mode = MODE_ABOUT;
        break;
    case HIT_DIALOG_OK:
        g_mode = MODE_DESKTOP;
        break;
    case HIT_TITLE_X:
        /* Close the running app — revert to the welcome screen and
         * any modal back to desktop. */
        g_current_app = APP_WELCOME;
        g_notepad_editing = 0;
        g_mode = MODE_DESKTOP;
        break;
    case HIT_TITLE_MIN:
        /* Minimize: stash current window rect, mark minimized.  The
         * taskbar pill is the only way back. */
        g_win_saved_r0 = WIN_R0; g_win_saved_c0 = WIN_C0;
        g_win_saved_r1 = WIN_R1; g_win_saved_c1 = WIN_C1;
        g_win_minimized = 1;
        g_mode = MODE_DESKTOP;
        break;
    case HIT_TITLE_MAX:
        /* Maximize toggle: fill the visible area (minus taskbar) on
         * first click; restore the prior rect on second. */
        if (!g_win_maximized) {
            g_win_saved_r0 = WIN_R0; g_win_saved_c0 = WIN_C0;
            g_win_saved_r1 = WIN_R1; g_win_saved_c1 = WIN_C1;
            WIN_R0 = 0;          WIN_C0 = 0;
            WIN_R1 = TASK_R - 2; WIN_C1 = VIS_W - 1;
            g_win_maximized = 1;
        } else {
            WIN_R0 = g_win_saved_r0; WIN_C0 = g_win_saved_c0;
            WIN_R1 = g_win_saved_r1; WIN_C1 = g_win_saved_c1;
            g_win_maximized = 0;
        }
        g_fb_prev_valid = 0;   /* force full repaint at new size */
        g_mode = MODE_DESKTOP;
        break;
    case HIT_TASKBAR_PILL:
        g_win_minimized = 0;
        g_mode = MODE_DESKTOP;
        break;
    case HIT_START: {
        if (g_mode == MODE_START) { g_mode = MODE_DESKTOP; break; }
        g_mode = MODE_START;
        int sr0, sc0, sr1, sc1;
        start_geom(&sr0, &sc0, &sr1, &sc1);
        g_cur_r = sr0 + 1;            /* land on first item */
        g_cur_c = sc0 + 4;
        break;
    }
    case HIT_START_SHUTDOWN:
        /* Win95's "Shut Down" doesn't fool around — quit. */
        return 1;
    case HIT_START_ABOUT: {
        g_mode = MODE_ABOUT;
        int r0, c0, r1, c1;
        about_geom(&r0, &c0, &r1, &c1);
        g_cur_r = r1 - 1; g_cur_c = (c0 + c1) / 2;
        break;
    }
    case HIT_START_PROGRAMS: {
        /* Open the cascading Programs submenu and land the cursor on
         * its first item. */
        g_mode = MODE_PROGRAMS;
        int pr0, pc0, pr1, pc1;
        programs_geom(&pr0, &pc0, &pr1, &pc1);
        (void)pr1; (void)pc1;
        g_cur_r = pr0 + 1;
        g_cur_c = pc0 + 2;
        break;
    }
    case HIT_PROG_NOTEPAD: g_current_app = APP_NOTEPAD; g_mode = MODE_DESKTOP; break;
    case HIT_PROG_CALC:    g_current_app = APP_CALC;    g_mode = MODE_DESKTOP; break;
    case HIT_PROG_PAINT:   g_current_app = APP_PAINT;   g_mode = MODE_DESKTOP; break;
    case HIT_PROG_DOS:     g_current_app = APP_DOS;     g_mode = MODE_DESKTOP; break;
    case HIT_PROG_EXPLORER:
        /* Explorer is a future phase — close menu for now. */
        g_mode = MODE_DESKTOP;
        break;
    case HIT_PROG_SEP:
        break;
    case HIT_START_HELP:
    case HIT_CTX_VIEW:
    case HIT_CTX_NEW:
        /* Other stubs: just close.  Submenus are a future phase. */
        g_mode = MODE_DESKTOP;
        break;
    case HIT_CTX_REFRESH:
        /* Force a full repaint: invalidate the diff buffer. */
        g_fb_prev_valid = 0;
        g_mode = MODE_DESKTOP;
        break;
    case HIT_START_RUN:
    case HIT_CTX_PROPERTIES: {
        /* Open Display Properties.  Snapshot state for Cancel-rollback,
         * then land cursor on the first widget so it highlights. */
        g_dp_saved_color = g_desk_color;
        g_dp_saved_icons = g_show_icons;
        g_dp_saved_clock = g_show_clock;
        g_dp_saved_hex   = g_hex_grid;
        g_mode = MODE_DP;
        int dr0, dc0, dr1, dc1;
        dp_geom(&dr0, &dc0, &dr1, &dc1);
        (void)dr1; (void)dc1;
        g_cur_r = dp_row_color(dr0, 0);
        g_cur_c = dc0 + 6;
        break;
    }
    case HIT_DP_COLOR_0:
    case HIT_DP_COLOR_1:
    case HIT_DP_COLOR_2:
    case HIT_DP_COLOR_3:
        g_desk_color = g_color_presets[hit - HIT_DP_COLOR_0].slot;
        break;
    case HIT_DP_CHECK_ICONS: g_show_icons = !g_show_icons; break;
    case HIT_DP_CHECK_CLOCK: g_show_clock = !g_show_clock; break;
    case HIT_DP_CHECK_HEX:   g_hex_grid   = !g_hex_grid;   break;
    case HIT_DP_OK:
    case HIT_DP_TITLE_X:
        g_mode = MODE_DESKTOP;
        break;
    case HIT_DP_CANCEL:
        /* Roll back. */
        g_desk_color = g_dp_saved_color;
        g_show_icons = g_dp_saved_icons;
        g_show_clock = g_dp_saved_clock;
        g_hex_grid   = g_dp_saved_hex;
        g_mode = MODE_DESKTOP;
        break;
    case HIT_START_SEP:
    case HIT_CTX_SEP:
        /* Separators do nothing. */
        break;
    default:
        /* Click on empty space closes any open menu (but NOT modal
         * dialogs — those need an explicit OK/Cancel/×). */
        if (g_mode == MODE_FILE_MENU || g_mode == MODE_HELP_MENU ||
            g_mode == MODE_START      || g_mode == MODE_PROGRAMS ||
            g_mode == MODE_CONTEXT)
            g_mode = MODE_DESKTOP;
        /* Click inside the Notepad body area starts/stops editing. */
        if (g_mode == MODE_DESKTOP && g_current_app == APP_NOTEPAD) {
            int br = WIN_R0 + 3, sr = WIN_R1 - 1;
            if (g_cur_r > br && g_cur_r < sr &&
                g_cur_c > WIN_C0 + 1 && g_cur_c < WIN_C1 - 1) {
                g_notepad_editing = !g_notepad_editing;
            }
        }
        break;
    }
    return 0;
}

static int handle_rclick(void) {
    /* Right-click opens a context menu anchored at the cursor.  Only
     * available from the desktop (not from inside other modal menus). */
    if (g_mode == MODE_DESKTOP) {
        g_ctx_r = g_cur_r;
        g_ctx_c = g_cur_c;
        g_mode = MODE_CONTEXT;
        /* Land cursor on first item so it highlights immediately. */
        int xr0, xc0, xr1, xc1;
        context_geom(&xr0, &xc0, &xr1, &xc1);
        g_cur_r = xr0 + 1;
        g_cur_c = xc0 + 2;
    } else if (g_mode == MODE_CONTEXT) {
        /* Second right-click closes the menu. */
        g_mode = MODE_DESKTOP;
    }
    return 0;
}

/* ── Main loop ───────────────────────────────────────────── */
int main(int argc, char **argv) {
    int once = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--once")) once = 1;
        else if (!strcmp(argv[i], "--hex"))  g_hex_grid = 1;
    }

    if (once) {
        /* Paint a single frame to stdout and exit.  No raw mode, no
         * alt-screen — caller pipes this somewhere (e.g. `| less -R`
         * or `| sed` to strip escapes). */
        layout_for_size();
        /* Clamp the initial cursor to the visible area so the --once
         * dump always shows a cursor cell on a fresh terminal. */
        if (g_cur_r >= VIS_H) g_cur_r = VIS_H / 2;
        if (g_cur_c >= VIS_W) g_cur_c = VIS_W / 2;
        paint_frame();
        render_to_stdout(g_cur_r, g_cur_c, 1);
        fputs("\033[0m\n", stdout);
        return 0;
    }

    term_setup_raw();
    signal(SIGINT,  on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGWINCH, on_winch);
    atexit(term_teardown);
    /* Drop the initial cursor into the freshly-laid-out window. */
    g_cur_r = (WIN_R0 + WIN_R1) / 2;
    g_cur_c = (WIN_C0 + WIN_C1) / 2;
    g_fb_prev_valid = 0;            /* full repaint on first frame */

    int dirty = 1;
    int last_minute = -1;
    while (1) {
        if (g_winch_dirty) {
            g_winch_dirty = 0;
            layout_for_size();
            g_fb_prev_valid = 0;
            if (g_cur_r >= VIS_H) g_cur_r = VIS_H - 1;
            if (g_cur_c >= VIS_W) g_cur_c = VIS_W - 1;
            dirty = 1;
        }
        if (dirty) {
            paint_frame();
            render_to_stdout(g_cur_r, g_cur_c, 1);
            dirty = 0;
        }
        unsigned char c;
        int n = read(STDIN_FILENO, &c, 1);
        if (n <= 0) {
            /* No input within VTIME — only repaint if the wall clock
             * minute has rolled over.  Otherwise sit silent and let
             * the terminal stay perfectly still. */
            time_t now = time(NULL);
            struct tm tm; localtime_r(&now, &tm);
            if (tm.tm_min != last_minute) {
                last_minute = tm.tm_min;
                dirty = 1;
            }
            continue;
        }

        /* Notepad editing intercepts most keys.  Esc exits editing,
         * Backspace deletes the last char, Enter inserts a newline,
         * Ctrl-C still quits.  Printable bytes append to the buffer. */
        if (g_notepad_editing && g_current_app == APP_NOTEPAD) {
            if (c == 0x03) break;                     /* Ctrl-C */
            if (c == 0x1b) { g_notepad_editing = 0; dirty = 1; continue; }
            if (c == 0x7f || c == 8) {                /* DEL or Backspace */
                if (g_notepad_len > 0) g_notepad_len--;
                dirty = 1; continue;
            }
            if (c == '\r' || c == '\n') {
                if (g_notepad_len < NOTEPAD_CAP - 1)
                    g_notepad_buf[g_notepad_len++] = '\n';
                dirty = 1; continue;
            }
            if (c >= 32 && c < 127 && g_notepad_len < NOTEPAD_CAP - 1) {
                g_notepad_buf[g_notepad_len++] = (char)c;
                dirty = 1; continue;
            }
            continue;                                 /* swallow everything else */
        }

        if (c == 'q' || c == 'Q' || c == 0x03) break;   /* q or Ctrl-C */
        if (c == 'G') { g_hex_grid = !g_hex_grid; dirty = 1; continue; }
        if (c == 0x1b) {                                /* ESC closes menus */
            if (g_mode != MODE_DESKTOP) g_mode = MODE_DESKTOP;
            dirty = 1; continue;
        }
        if (c == 's' || c == '\r' || c == '\n') {
            if (handle_click()) break;
            dirty = 1; continue;
        }
        if (c == 'f') {
            handle_rclick();
            dirty = 1; continue;
        }
        if (c == 'w' || c == 'e' || c == 'a' || c == 'd' ||
            c == 'z' || c == 'x') {
            handle_movement((char)c);
            dirty = 1; continue;
        }
    }
    return 0;
}
