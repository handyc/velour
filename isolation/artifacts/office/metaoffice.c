/* metaoffice.c — assembled by hand from tinyagentjail's Phase-3
 * decomposed output (commit 35cf0ac).  See /tmp/metaoffice_session.txt
 * for the full session: depth=1 fanout=4 produced four VERIFIED-C-OK
 * leaf functions which are pasted verbatim below.  The Win95 desktop
 * wrapper (cls/desktop banner + menu/dispatch) is the human-side
 * integration layer until tinyagentjail Phase 4 adds synthesis.
 *
 *   build:  cc -O2 -o metaoffice metaoffice.c
 *   run:    ./metaoffice            (1=rpg 2=hxhunt 3=notepad 4=sheet q=quit)
 */

#include <stdio.h>
#include <stdlib.h>
#include <termios.h>
#include <unistd.h>


/* ── leaf 0 (subtask 0): rpg_screen — verbatim from tinyagentjail ── */
void rpg_screen(void)
{
    static const char *colors[4] = {
        "\033[41m", /* red */
        "\033[42m", /* green */
        "\033[43m", /* yellow */
        "\033[44m"  /* blue */
    };

    int row;
    int col;

    printf("\033[2J\033[H");

    printf("\033[44;37mRPG\033[0m\n");

    for (row = 0; row < 8; row++) {
        if (row % 2) {
            printf(" ");
        }

        for (col = 0; col < 16; col++) {
            printf("%s  \033[0m", colors[(row + col) % 4]);
        }

        printf("\n");
    }
}


/* ── leaf 1 (subtask 1): hxhunt_screen — verbatim from tinyagentjail ── */
void hxhunt_screen(void)
{
    printf("\033[2J\033[H");
    printf("\033[32mDNA Hex Hunt\033[0m\n\n");

    printf("4A 7C 2F E1 9B 03 5D B7\n");
    printf("C8 11 A4 6E 0F D2 88 3B\n");
    printf("7F 20 9C 44 E6 1A B0 5E\n");
    printf("02 DA 73 8B 31 F9 C5 6D\n");
    printf("AE 54 0C 97 22 BB 4F D1\n");
    printf("69 E3 15 CA 80 3D F6 28\n");
    printf("B4 09 DE 61 7A C2 35 8F\n");
    printf("5B F0 47 AC 19 E8 92 0D\n");
}


/* ── leaf 2 (subtask 2): notepad_screen — verbatim from tinyagentjail ── */
void notepad_screen(void)
{
    int row;

    printf("\033[2J");      /* Clear screen */
    printf("\033[H");       /* Move cursor to top-left */

    printf("\033[37;44m");  /* White text on blue background */
    printf("Notepad - untitled.txt");
    printf("\033[0m\n");    /* Reset colors */

    for (row = 1; row <= 18; row++) {
        printf("%3d |\n", row);
    }
}


/* ── leaf 3 (subtask 3): sheet_screen — verbatim from tinyagentjail ── */
void sheet_screen(void)
{
    int row, col;

    printf("\033[2J\033[H");

    printf("\033[33mSheet1\033[0m\n");

    for (row = 0; row < 5; row++) {
        for (col = 0; col < 5; col++) {
            int i;
            printf("+");
            for (i = 0; i < 10; i++) {
                printf("-");
            }
        }
        printf("+\n");

        for (col = 0; col < 5; col++) {
            int i;
            printf("|");
            for (i = 0; i < 10; i++) {
                printf(" ");
            }
        }
        printf("|\n");
    }

    for (col = 0; col < 5; col++) {
        int i;
        printf("+");
        for (i = 0; i < 10; i++) {
            printf("-");
        }
    }
    printf("+\n");
}


/* ── Win95 desktop chrome + dispatcher (human-written wrapper) ── */

static void desktop_paint(void)
{
    /* teal field + 'metaoffice' titlebar + Start-style bottom bar */
    printf("\033[2J\033[H");
    printf("\033[48;5;30m\033[2J\033[H");         /* teal background */

    /* Title bar */
    printf("\033[48;5;21;38;5;15m metaoffice — assembled from "
           "tinyagentjail Phase-3 leaves                              "
           "       _ [] X\033[0m\n");
    /* Menu bar */
    printf("\033[48;5;7;38;5;0m  \033[4mF\033[24mile  "
           "\033[4mE\033[24mdit  \033[4mV\033[24miew  "
           "\033[4mH\033[24melp                                       "
           "                                       \033[0m\n");

    /* Body: app icons */
    printf("\033[48;5;30m\033[38;5;15m\n");
    printf("    [1] rpg          (hex-CA mini-RPG)\n");
    printf("    [2] hxhunt       (DNA hex scanner)\n");
    printf("    [3] notepad      (text editor)\n");
    printf("    [4] sheet        (spreadsheet)\n");
    printf("\n");
    printf("    [q] quit\n");
    printf("\n");
    printf("\033[0m");

    /* Status bar */
    printf("\033[48;5;7;38;5;0m  Start   |   "
           "metaoffice ready                                          "
           "                            \033[0m\n");

    printf("\nChoose: ");
    fflush(stdout);
}

static void wait_key(void)
{
    printf("\n\n\033[37mPress any key to return to desktop...\033[0m");
    fflush(stdout);
    getchar();
}

int main(void)
{
    int ch;
    while (1) {
        desktop_paint();
        ch = getchar();
        if (ch == EOF || ch == 'q' || ch == 'Q') break;
        if (ch == '\n') continue;
        /* Drain rest of line so the next getchar() blocks for a fresh key */
        int c;
        while ((c = getchar()) != '\n' && c != EOF) { /* discard */ }
        switch (ch) {
            case '1': rpg_screen();     wait_key(); break;
            case '2': hxhunt_screen();  wait_key(); break;
            case '3': notepad_screen(); wait_key(); break;
            case '4': sheet_screen();   wait_key(); break;
            default: break;
        }
    }
    printf("\033[0m\033[2J\033[H");
    return 0;
}
