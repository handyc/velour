#include <stdio.h>

void rpg_screen(void)
{
    int r, c;
    const int bg[4] = {41, 42, 43, 45};

    printf("\033[2J\033[H");
    printf("\033[1;34mRPG\033[0m\n\n");

    for (r = 0; r < 8; ++r) {
        if (r % 2)
            printf("  ");

        for (c = 0; c < 16; ++c) {
            int color = bg[(r + c) % 4];
            printf("\033[%dm  \033[0m ", color);
        }

        printf("\n");
    }

    printf("\033[0m");
}

void hxhunt_screen(void)
{
    printf("\033[2J\033[H");
    printf("\033[32mDNA Hex Hunt\033[0m\n\n");

    printf("   A1 C3 7F 00 B9 4D E2 18\n");
    printf("  5A 9C D0 3E 72 F1 0B A6\n");
    printf("   CC 14 8E F7 29 60 DB 35\n");
    printf("  1F E4 93 6A B0 2C 7D C8\n");
    printf("   44 AF 02 D9 81 5E F3 6B\n");
    printf("  BA 07 5C E1 3D 90 26 CF\n");
    printf("   68 D2 B7 0A F5 31 9E 4C\n");
    printf("  ED 12 70 A9 C4 56 8B 03\n");
}

void notepad_screen(void)
{
    int i;

    printf("\033[2J\033[H");
    printf("\033[37;44m Notepad - untitled.txt \033[0m\n");

    for (i = 1; i <= 18; ++i) {
        printf("%02d | \n", i);
    }
}

void sheet_screen(void)
{
    int row, col;

    printf("\033[2J\033[H");
    printf("\033[33mSheet1\033[0m\n");

    for (row = 0; row < 5; row++) {
        for (col = 0; col < 5; col++) {
            printf("+-----");
        }
        printf("+\n");

        for (col = 0; col < 5; col++) {
            printf("|     ");
        }
        printf("|\n");
    }

    for (col = 0; col < 5; col++) {
        printf("+-----");
    }
    printf("+\n");
}

int main(void)
{
    int ch, sel;

    for (;;) {
        printf("\033[2J\033[H");
        printf("\033[37;44m Tiny Win95 Office TUI \033[0m\n\n");
        printf("1. RPG\n");
        printf("2. DNA Hex Hunt\n");
        printf("3. Notepad\n");
        printf("4. Sheet1\n");
        printf("q. Quit\n\n");
        printf("Select: ");
        fflush(stdout);

        sel = getchar();

        if (sel == EOF || sel == 'q' || sel == 'Q') {
            break;
        }

        ch = sel;
        while (ch != '\n' && ch != EOF) {
            ch = getchar();
        }

        switch (sel) {
        case '1':
            rpg_screen();
            break;
        case '2':
            hxhunt_screen();
            break;
        case '3':
            notepad_screen();
            break;
        case '4':
            sheet_screen();
            break;
        default:
            printf("\nUnknown selection.\n");
            break;
        }

        printf("\nPress Enter to return to menu...");
        while ((ch = getchar()) != '\n' && ch != EOF) {
            ;
        }
    }

    printf("\033[0m\033[2J\033[H");
    return 0;
}
