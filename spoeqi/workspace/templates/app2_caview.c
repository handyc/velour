/* app2_caview.c — workspace App 2: hex CA viewer, self-referential.
 *
 * The substrate viewing itself.  The pact's CA bytes pick a rule_seed
 * + init_seed; the app expands those seeds into a 4-state K=4 hex CA
 * (7-cell pointy-top neighbourhood), runs `ticks` steps, prints the
 * final grid in 4 ANSI colours.
 *
 * Same RNG as isolation/artifacts/hexhunter/hexhunter.c
 * (state = state * 1103515245 + 12345) so the table generation is
 * cross-language deterministic.
 *
 * Square-offset layout — odd rows are visually indented by one space
 * to suggest the hex tiling without paying for true hex glyph
 * rendering.  Cell glyph: two ANSI-coloured 0xE2 0x96 0x88 (█).
 */

typedef long          ssize_t;
typedef unsigned long size_t;
typedef unsigned int  uint32_t;

#define SYS_write       1
#define SYS_exit_group 231

static long sys3(long n, long a, long b, long c) {
    long r;
    __asm__ volatile ("syscall" : "=a"(r) : "0"(n), "D"(a), "S"(b), "d"(c)
                      : "rcx", "r11", "memory");
    return r;
}

/* ── slots ─────────────────────────────────────────────── */
#define SLOT(name, id, n) \
    __attribute__((used, section(".rodata.workspace_slots"), aligned(8))) \
    static const volatile unsigned char name[8 + n] = \
        { 0xCA, 0xFE, 0xBA, 0xBE, 0x00, 0x00, 0x00, id,

SLOT(SLOT_RULE_SEED, 0x21, 8)
        0x42, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
};
SLOT(SLOT_INIT_SEED, 0x22, 8)
        0x07, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
};
SLOT(SLOT_TICKS,     0x23, 4)
        0x10, 0x00, 0x00, 0x00      /* default: 16 ticks */
};
SLOT(SLOT_SIZE,      0x24, 4)
        0x1c, 0x00, 0x00, 0x00      /* default: 28 cells per side */
};

/* ── reads ─────────────────────────────────────────────── */
typedef unsigned long long u64;

static u64 read_u64(const volatile unsigned char *p) {
    u64 v = 0;
    for (int i = 0; i < 8; i++) v |= ((u64)p[8 + i]) << (i * 8);
    return v;
}
static uint32_t read_u32(const volatile unsigned char *p) {
    uint32_t v = 0;
    for (int i = 0; i < 4; i++) v |= ((uint32_t)p[8 + i]) << (i * 8);
    return v;
}

/* ── buffered stdout ───────────────────────────────────── */
static char obuf[1 << 14];
static int  olen;
static void oflush(void) {
    if (olen) sys3(SYS_write, 1, (long)obuf, olen);
    olen = 0;
}
static void oc(unsigned char c) {
    if (olen >= (int)sizeof obuf) oflush();
    obuf[olen++] = (char)c;
}
static void os(const char *s) { while (*s) oc((unsigned char)*s++); }
static void ou(unsigned v) {
    if (v >= 100) { oc('0' + v/100); v %= 100; oc('0' + v/10); oc('0' + v%10); }
    else if (v >= 10) { oc('0' + v/10); oc('0' + v%10); }
    else oc('0' + v);
}

/* ── tables (BSS — no ELF cost) ────────────────────────── */
#define MAX_SIDE  64
static unsigned char rule[16384];                  /* 4^7 entries, 0..3 */
static unsigned char grid[MAX_SIDE][MAX_SIDE];     /* current state */
static unsigned char nxt [MAX_SIDE][MAX_SIDE];     /* next state */

/* 4-colour ANSI 256 swatch — picked for clear separation against a
 * black terminal and from each other. */
static const unsigned char colour[4] = { 0, 33, 196, 226 };

/* Park-Miller-style LCG, same constants as hexhunter.c so cross-
 * language tools can recompute rule tables byte-identical. */
static unsigned lcg_state;
static unsigned lcg(void) {
    lcg_state = lcg_state * 1103515245u + 12345u;
    return lcg_state;
}

/* Hex 7-neighbourhood offsets for pointy-top, even/odd rows. */
static const int nbr_dx_even[6] = { -1,  0, -1,  1, -1,  0 };
static const int nbr_dy_even[6] = { -1, -1,  0,  0,  1,  1 };
static const int nbr_dx_odd [6] = {  0,  1, -1,  1,  0,  1 };
static const int nbr_dy_odd [6] = { -1, -1,  0,  0,  1,  1 };

int _start(void) {
    u64 rule_seed = read_u64(SLOT_RULE_SEED);
    u64 init_seed = read_u64(SLOT_INIT_SEED);
    int ticks     = (int)read_u32(SLOT_TICKS);
    int side      = (int)read_u32(SLOT_SIZE);
    if (side > MAX_SIDE) side = MAX_SIDE;
    if (side < 4)        side = 4;
    if (ticks < 0)       ticks = 0;
    if (ticks > 200)     ticks = 200;

    /* Rule table from rule_seed. */
    lcg_state = (unsigned)(rule_seed | 1);
    for (int i = 0; i < 16384; i++) rule[i] = (unsigned char)((lcg() >> 16) & 3);

    /* Initial state from init_seed. */
    lcg_state = (unsigned)(init_seed | 1);
    for (int r = 0; r < side; r++)
        for (int c = 0; c < side; c++)
            grid[r][c] = (unsigned char)((lcg() >> 16) & 3);

    /* Iterate. Rule index packs 7 cells × 2 bits = 14-bit value:
     *   bits 0..1   : self
     *   bits 2..13  : 6 neighbours, scanned in nbr_d{x,y} order
     * Out-of-bounds neighbours wrap (toroidal). */
    for (int t = 0; t < ticks; t++) {
        for (int r = 0; r < side; r++) {
            const int *dx = (r & 1) ? nbr_dx_odd : nbr_dx_even;
            const int *dy = (r & 1) ? nbr_dy_odd : nbr_dy_even;
            for (int c = 0; c < side; c++) {
                unsigned idx = grid[r][c] & 3;
                for (int k = 0; k < 6; k++) {
                    int nr = r + dy[k];
                    int nc = c + dx[k];
                    if (nr < 0)     nr += side;
                    if (nr >= side) nr -= side;
                    if (nc < 0)     nc += side;
                    if (nc >= side) nc -= side;
                    idx |= ((unsigned)(grid[nr][nc] & 3)) << (2 + 2 * k);
                }
                nxt[r][c] = rule[idx & 0x3FFF];
            }
        }
        /* Swap. */
        for (int r = 0; r < side; r++)
            for (int c = 0; c < side; c++)
                grid[r][c] = nxt[r][c];
    }

    /* Render. Each cell = two █ chars (so columns stay roughly square
     * in a typical font); odd rows shifted right by one space. */
    int last_c = -1;
    for (int r = 0; r < side; r++) {
        if (r & 1) oc(' ');
        for (int c = 0; c < side; c++) {
            int v = grid[r][c] & 3;
            if (v != last_c) {
                os("\x1b[38;5;"); ou(colour[v]); oc('m');
                last_c = v;
            }
            /* █ U+2588 = 0xE2 0x96 0x88, twice for ~square aspect */
            oc(0xE2); oc(0x96); oc(0x88);
            oc(0xE2); oc(0x96); oc(0x88);
        }
        os("\x1b[0m\n");
        last_c = -1;
    }
    oflush();
    sys3(SYS_exit_group, 0, 0, 0);
    return 0;
}
