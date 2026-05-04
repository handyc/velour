/* wnnr.c — terminal duck toy in C
 *
 * Faithful translation of advanced/wnnr from the ALICE workshop.
 * N coloured "ducks" (text boxes) sit at random positions on the
 * terminal; arrow keys move duck 0; r randomises foreground +
 * background colour; s saves state to ./savepoint and exits; q
 * quits; k and l shell out to commands (SLURM by default — set
 * $WNNR_K / $WNNR_L env vars to override).
 *
 * The original uses tput; this version writes ANSI escape codes
 * directly so it has no library dependencies beyond libc + POSIX
 * termios. No ncurses, no third-party headers. Compiles clean
 * under -std=c99 -Wall -Wextra on Linux/macOS/BSD.
 *
 * Build:
 *   cc -std=c99 -O2 -Wall -Wextra -o wnnr wnnr.c
 *
 * Use:
 *   ./wnnr           # 1..5 random ducks
 *   ./wnnr 8         # exactly 8 ducks
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <termios.h>
#include <signal.h>
#include <sys/select.h>


#define MAX_DUCKS      32
#define KEY_TIMEOUT_S  60
#define DRAIN_US       200    /* µs to wait for ESC-sequence follow-on */

typedef struct { int x, y, color; } duck_t;


/* ── terminal state ──────────────────────────────────────── */
static struct termios saved_termios;
static int term_was_raw = 0;

static void cooked(void)
{
    if (term_was_raw) {
        tcsetattr(STDIN_FILENO, TCSANOW, &saved_termios);
        term_was_raw = 0;
    }
    fputs("\x1b[0m", stdout);          /* reset SGR */
    fputs("\x1b[?25h", stdout);        /* show cursor */
    fflush(stdout);
}

static void on_signal(int sig)
{
    cooked();
    _exit(128 + sig);
}

static void raw(void)
{
    if (tcgetattr(STDIN_FILENO, &saved_termios) != 0) {
        perror("tcgetattr");
        exit(1);
    }
    struct termios t = saved_termios;
    t.c_lflag &= ~(ICANON | ECHO);
    t.c_cc[VMIN]  = 0;
    t.c_cc[VTIME] = 0;
    if (tcsetattr(STDIN_FILENO, TCSANOW, &t) != 0) {
        perror("tcsetattr");
        exit(1);
    }
    term_was_raw = 1;
    atexit(cooked);
    signal(SIGINT,  on_signal);
    signal(SIGTERM, on_signal);
    fputs("\x1b[?25l", stdout);        /* hide cursor */
    fflush(stdout);
}


/* ── input: blocking read with 60 s wait + drain follow-ons ── */
static int read_key(unsigned char *out, int max, long timeout_us)
{
    fd_set fds;
    struct timeval tv;
    int got = 0;

    FD_ZERO(&fds); FD_SET(STDIN_FILENO, &fds);
    tv.tv_sec  = timeout_us / 1000000;
    tv.tv_usec = timeout_us % 1000000;
    if (select(STDIN_FILENO + 1, &fds, NULL, NULL, &tv) <= 0) return 0;
    if (read(STDIN_FILENO, &out[got], 1) != 1) return 0;
    got++;
    /* ESC sequences (e.g. arrow keys) arrive as ESC '[' 'A' across
     * a few hundred microseconds. Drain any immediate follow-ups so
     * we see the whole sequence before dispatching. */
    while (got < max) {
        FD_ZERO(&fds); FD_SET(STDIN_FILENO, &fds);
        tv.tv_sec = 0; tv.tv_usec = DRAIN_US;
        if (select(STDIN_FILENO + 1, &fds, NULL, NULL, &tv) <= 0) break;
        if (read(STDIN_FILENO, &out[got], 1) != 1) break;
        got++;
    }
    return got;
}


/* ── ANSI escape helpers (no tput, no ncurses) ──────────── */
static void cls(void)         { fputs("\x1b[2J\x1b[H", stdout); }
static void cup(int x, int y) { printf("\x1b[%d;%dH", y + 1, x + 1); }
static void setab(int c)      { printf("\x1b[48;5;%dm", c & 0xff); }
static void setaf(int c)      { printf("\x1b[38;5;%dm", c & 0xff); }
static void sgr0(void)        { fputs("\x1b[0m", stdout); }


/* ── one duck render ─────────────────────────────────────── */
static void draw_duck(const duck_t *d)
{
    cup(d->x, d->y);
    setab(d->color);
    printf("%d %d", d->x, d->y);
    cup(d->x, d->y + 3);
    time_t now = time(NULL);
    struct tm *tm = localtime(&now);
    char buf[64];
    strftime(buf, sizeof buf, "%a %b %e %T %Y", tm);
    fputs(buf, stdout);
}


/* ── savepoint: positions + colours ──────────────────────── */
static void save_state(const duck_t *d, int n)
{
    FILE *f = fopen("savepoint", "w");
    if (!f) { perror("savepoint"); return; }
    for (int i = 0; i < n; i++) fprintf(f, "%d ", d[i].x);
    for (int i = 0; i < n; i++) fprintf(f, "%d ", d[i].y);
    for (int i = 0; i < n; i++) fprintf(f, "%d ", d[i].color);
    fputc('\n', f);
    fclose(f);
    fputs("saving", stdout);
    fflush(stdout);
}


/* ── shell out for k and l (SLURM-aware in the ALICE original;
 *    let the user override via env). Restore cooked tty before so
 *    the child program can do its own line buffering. ── */
static void run_cmd(const char *envvar, const char *fallback)
{
    const char *cmd = getenv(envvar);
    if (!cmd) cmd = fallback;
    cooked();
    int r = system(cmd);
    (void)r;
}


/* ── main loop ───────────────────────────────────────────── */
int main(int argc, char *argv[])
{
    srand((unsigned)(time(NULL) ^ getpid()));

    int n;
    if (argc > 1) {
        n = atoi(argv[1]);
        if (n < 1) n = 1;
    } else {
        n = 1 + rand() % 5;
    }
    if (n > MAX_DUCKS) n = MAX_DUCKS;

    duck_t ducks[MAX_DUCKS];
    for (int i = 0; i < n; i++) {
        ducks[i].x     = 1 + rand() % 70;
        ducks[i].y     = 1 + rand() % 20;
        ducks[i].color = rand() % 256;
    }
    int af = rand() % 256;
    int ab = rand() % 256;

    raw();

    while (1) {
        cls();
        setaf(af);
        for (int i = 0; i < n; i++) {
            setab(ducks[i].color);
            draw_duck(&ducks[i]);
        }
        setab(ab);
        cup(0, 23);
        fflush(stdout);

        unsigned char key[8] = { 0 };
        int got = read_key(key, sizeof key,
                           (long)KEY_TIMEOUT_S * 1000000);
        if (got == 0) continue;          /* timeout — just repaint */

        /* Arrow keys: ESC [ A/B/C/D — move duck 0. */
        if (got >= 3 && key[0] == 0x1b && key[1] == '[') {
            switch (key[2]) {
            case 'A': if (ducks[0].y > 0)  ducks[0].y--; break;   /* up */
            case 'B': if (ducks[0].y < 30) ducks[0].y++; break;   /* down */
            case 'C': if (ducks[0].x < 78) ducks[0].x++; break;   /* right */
            case 'D': if (ducks[0].x > 0)  ducks[0].x--; break;   /* left */
            default: break;
            }
            continue;
        }

        switch (key[0]) {
        case 'r':
            af = rand() % 256;
            ab = rand() % 256;
            break;
        case 's':
            cls();
            save_state(ducks, n);
            sgr0();
            return 0;
        case 'k':
            cls();
            puts("Kwak...");
            run_cmd("WNNR_K",
                    "squeue -u \"$USER\" 2>/dev/null || true");
            sgr0();
            return 0;
        case 'l':
            cls();
            puts("Kwak2...");
            run_cmd("WNNR_L", "squeue 2>/dev/null || true");
            sgr0();
            return 0;
        case 'q':
            cls();
            puts("Bye!");
            sgr0();
            return 0;
        default:
            break;
        }
    }
}
