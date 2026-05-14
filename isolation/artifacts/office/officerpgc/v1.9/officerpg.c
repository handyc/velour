/* officerpg v1.9 — half-block hex world (officemandel-style rendering)
 *
 * What's new vs v1.8:
 *
 *   v1.8 painted each hex cell as an 8×3 char block — 24 char-cells
 *   per tile.  v1.9 uses officemandel's ▀ U+2580 trick (foreground =
 *   upper-half pixel, background = lower-half pixel) so each terminal
 *   char-cell now holds two vertically-stacked "pixels".  The per-tile
 *   footprint shrinks to 4 chars wide × 2 chars tall — 8 char-cells
 *   per tile (1/3 of v1.8) — while still containing 4×4 = 16 distinct
 *   colour pixels (vs v1.8's 24 colour patches, but at finer
 *   resolution).  Net: ~3× more visible tiles on the same terminal,
 *   and tile aspect is more square so the world reads more like a
 *   map and less like flattened mosaic.
 *
 * Cell layout on screen (one tile = 4 chars wide × 2 chars tall):
 *
 *     ▀▀▀▀          char (0,0)  fg = pixel(0,0)  bg = pixel(0,1)
 *     ▀▀▀▀          char (1,0)  fg = pixel(0,2)  bg = pixel(0,3)
 *     │└── 4 char columns, 4 pixel rows total (2 chars × 2 px/char)
 *
 * Hex offset (offset-r, pointy-top): odd rows shift +2 chars.
 *
 * World: 128×128 hex cells (16,384 tiles).  Viewport is centred on
 * the player and scrolls as they move; off-map cells render black.
 * Terrain is hash-derived from world (x, y) so the map is the same
 * on every run — like procedural noise but stateless.
 *
 * Keys:
 *   w  NW    e  NE
 *   a  W           d  E       (offset-r hex move, wadezx layout)
 *   z  SW    x  SE
 *   r  recentre on (0, 0)
 *   q / ESC / Ctrl-C / Ctrl-D   quit
 *
 * Build (in this dir):
 *
 *   cc -DTINY -std=c99 -Os -Wall \
 *      -fno-builtin -ffreestanding -nostdlib -nostartfiles -static \
 *      -Wl,--gc-sections -s -o officerpg officerpg.c
 *
 * No libc, no dynamic alloc, no global mutable arrays past the BSS
 * blocks declared at file scope.  GCC 12+ on x86-64 Linux.
 */

typedef long          ssize_t;
typedef unsigned long size_t;

static long sys3(long n, long a, long b, long c) {
    long r;
    __asm__ volatile ("syscall" : "=a"(r) : "0"(n), "D"(a), "S"(b), "d"(c)
                      : "rcx", "r11", "memory");
    return r;
}
#define SYS_read       0
#define SYS_write      1
#define SYS_ioctl      16
#define SYS_exit_group 231

#define TCGETS     0x5401
#define TCSETS     0x5402
#define TIOCGWINSZ 0x5413

/* Termios subset (Linux x86-64 struct termios layout — same shape
 * the rest of the office tree uses).  Constants: ISIG=1, ICANON=2,
 * ECHO=8, IXON=0x400, ICRNL=0x100. */
struct ti { unsigned iflag, oflag, cflag, lflag;
            unsigned char line, cc[19]; };
struct ws { unsigned short row, col, x, y; };

static struct ti tio_orig;

/* ── buffered stdout ────────────────────────────────────────── */
static char obuf[1 << 17];                  /* 128 KiB — one big frame */
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
static void ou(unsigned v) {                        /* 0..9999 */
    if (v >= 1000) { oc('0' + v/1000); v %= 1000;
                     oc('0' + v/100);  v %= 100;
                     oc('0' + v/10);   oc('0' + v%10); }
    else if (v >= 100) { oc('0' + v/100); v %= 100;
                          oc('0' + v/10);  oc('0' + v%10); }
    else if (v >=  10) { oc('0' + v/10);   oc('0' + v%10); }
    else oc('0' + v);
}
static void emit_sgr_fg(int c) { os("\x1b[38;5;"); ou(c); oc('m'); }
static void emit_sgr_bg(int c) { os("\x1b[48;5;"); ou(c); oc('m'); }
static void emit_block_top(void) {      /* ▀ U+2580 = E2 96 80 */
    oc(0xE2); oc(0x96); oc(0x80);
}
static void cup(int x, int y) {
    os("\x1b["); ou(y + 1); oc(';'); ou(x + 1); oc('H');
}

/* ── world ──────────────────────────────────────────────────── */
#define MAP_W       128       /* hex cells across the world */
#define MAP_H       128

#define CELL_CHARS_W  4       /* char-cells per tile horizontally */
#define CELL_CHARS_H  2       /* char-cells per tile vertically */
#define CELL_PIX_W    CELL_CHARS_W      /* 4 distinct colour columns */
#define CELL_PIX_H   (CELL_CHARS_H * 2) /* 4 pixel rows (halves stacked) */

/* Player position in world space. */
static int player_x = MAP_W / 2;
static int player_y = MAP_H / 2;

/* Screen / viewport — recomputed every TIOCGWINSZ. */
static int screen_w = 80, screen_h = 24;
static int vis_w = 16, vis_h = 10;        /* tiles fully visible */
static int origin_x = 0, origin_y = 0;    /* px offset into terminal */

static void recompute_viewport(void) {
    /* Reserve one row at the top for the HUD and one at the bottom
     * for the prompt.  Tiles fully inside that strip. */
    int playfield_w = screen_w;
    int playfield_h = screen_h - 2;
    if (playfield_h < CELL_CHARS_H) playfield_h = CELL_CHARS_H;
    /* Hex offset eats CELL_CHARS_W / 2 extra chars on odd rows; budget
     * for the shift so the rightmost tile in odd rows still fits. */
    vis_w = (playfield_w - CELL_CHARS_W / 2) / CELL_CHARS_W;
    vis_h =  playfield_h                    / CELL_CHARS_H;
    if (vis_w < 1) vis_w = 1;
    if (vis_h < 1) vis_h = 1;
    if (vis_w > MAP_W) vis_w = MAP_W;
    if (vis_h > MAP_H) vis_h = MAP_H;
    /* Centre the playfield horizontally; HUD stays on row 0. */
    int used_w = vis_w * CELL_CHARS_W + CELL_CHARS_W / 2;
    origin_x = (playfield_w - used_w) / 2;
    if (origin_x < 0) origin_x = 0;
    origin_y = 1;   /* below HUD */
}

/* ── terrain ────────────────────────────────────────────────── */

/* Splittable-style hash: deterministic per (x, y), no global state.
 * Suitable for stateless procedural terrain — every run produces the
 * same world. */
static unsigned hash2(int x, int y) {
    unsigned h = (unsigned)(x * 73856093) ^ (unsigned)(y * 19349663);
    h ^= h >> 13;
    h *= 0x5bd1e995U;
    h ^= h >> 15;
    return h;
}
static unsigned hash3(int x, int y, int k) {
    unsigned h = hash2(x, y) ^ (unsigned)(k * 83492791);
    h ^= h >> 13;
    h *= 0x5bd1e995U;
    h ^= h >> 15;
    return h;
}

/* Four biomes selected by a coarse hash of the tile's world position.
 * Each biome owns a (base, accent) colour pair; the inner pixel is
 * the base most of the time, accent on a low-probability sprinkle so
 * the tile has visible texture, not a flat fill. */
enum { B_GRASS, B_DIRT, B_WATER, B_ROCK, B_COUNT };

struct biome {
    unsigned char base;       /* xterm 256 colour index */
    unsigned char accent;
    unsigned char sprinkle;   /* 0..255, threshold for hash byte */
};
static const struct biome biomes[B_COUNT] = {
    /* base   accent  sprinkle (higher = busier texture) */
    {  34,    22,     46  },     /* grass:  green / dark green */
    { 137,    94,     40  },     /* dirt:   tan   / brown      */
    {  27,    20,     32  },     /* water:  blue  / deep blue  */
    { 244,   239,     36  },     /* rock:   light / dark gray  */
};

/* Pick a biome for tile (wx, wy).  Blends a low-frequency component
 * (so biomes cluster) with a per-cell hash (so edges aren't perfectly
 * straight).  Wraps biome by hash mod B_COUNT. */
static int tile_biome(int wx, int wy) {
    unsigned a = hash2(wx >> 3, wy >> 3);
    unsigned b = hash2(wx >> 1, wy >> 1);
    return (int)((a + (b >> 4)) & 3U);
}

/* Pixel colour for sub-pixel (px, py) inside tile (wx, wy).  Result
 * is an xterm 256-colour index.  Off-map returns 0 (black). */
static unsigned char tile_pixel(int wx, int wy, int px, int py) {
    if (wx < 0 || wx >= MAP_W || wy < 0 || wy >= MAP_H) return 0;
    int bi = tile_biome(wx, wy);
    const struct biome *B = &biomes[bi];
    unsigned h = hash3(wx, wy, py * 8 + px);
    unsigned char roll = (unsigned char)(h & 0xFF);
    return roll < B->sprinkle ? B->accent : B->base;
}

/* ── render ─────────────────────────────────────────────────── */

/* Repaint the whole screen.  Sync-output is used so partial frames
 * don't show through on terminals that support DEC 2026. */
static void draw(void) {
    /* Frame begin: clear screen, hide cursor, sync-on, home. */
    os("\x1b[?2026h\x1b[H");

    /* HUD row 0: world position + viewport size. */
    emit_sgr_fg(15);
    emit_sgr_bg(0);
    cup(0, 0);
    /* Left aligned: "officerpg v1.9 · pos X,Y · view CxR" */
    os(" officerpg v1.9 · pos ");
    ou((unsigned)player_x);
    oc(',');
    ou((unsigned)player_y);
    os(" · view ");
    ou((unsigned)vis_w);
    oc('x');
    ou((unsigned)vis_h);
    os(" tiles");
    /* Pad to end of line. */
    int used = 33;   /* approximate; doesn't matter, terminal clips */
    while (used++ < screen_w) oc(' ');
    os("\x1b[0m");

    /* Pre-paint the playfield strip black so off-map cells and hex
     * gaps don't show prior frame content or the terminal default. */
    emit_sgr_bg(0);
    for (int r = origin_y; r < origin_y + vis_h * CELL_CHARS_H; r++) {
        cup(0, r);
        for (int c = 0; c < screen_w; c++) oc(' ');
    }

    /* Centre the viewport on the player. */
    int vp_cx = vis_w / 2;
    int vp_cy = vis_h / 2;

    /* Draw each tile.  Tiles render row-by-row, line-by-line; within
     * each char row we emit half-block ▀ characters with fg=upper
     * pixel and bg=lower pixel.  SGR state is tracked so we only
     * re-emit ESC sequences when the colour pair changes. */
    int lf = -1, lb = -1;
    for (int vy = 0; vy < vis_h; vy++) {
        int row_shift = (vy & 1) ? (CELL_CHARS_W / 2) : 0;
        for (int line = 0; line < CELL_CHARS_H; line++) {
            int sy = origin_y + vy * CELL_CHARS_H + line;
            cup(origin_x + row_shift, sy);
            for (int vx = 0; vx < vis_w; vx++) {
                int wx = player_x + vx - vp_cx;
                int wy = player_y + vy - vp_cy;
                int sub_top = line * 2;
                int sub_bot = line * 2 + 1;
                for (int col = 0; col < CELL_CHARS_W; col++) {
                    int top = tile_pixel(wx, wy, col, sub_top);
                    int bot = tile_pixel(wx, wy, col, sub_bot);
                    /* Player overlay: paint a bright yellow head at
                     * the top-centre pixel and a magenta body just
                     * below.  Drawn here (not in a separate pass)
                     * since it only touches two char-cells per
                     * frame. */
                    if (vx == vp_cx && vy == vp_cy) {
                        int cx = CELL_CHARS_W / 2;
                        if (col == cx) {
                            if (sub_top == 0) top = 226;   /* head */
                            if (sub_bot == 1) bot = 201;   /* body */
                        }
                    }
                    if (top != lf) { emit_sgr_fg(top); lf = top; }
                    if (bot != lb) { emit_sgr_bg(bot); lb = bot; }
                    emit_block_top();
                }
            }
            os("\x1b[0m");
            lf = lb = -1;
        }
    }

    /* Bottom prompt. */
    emit_sgr_fg(245);
    emit_sgr_bg(0);
    cup(0, screen_h - 1);
    os(" wadezx: move · r: recentre · q/ESC: quit");
    {
        int u = 42;
        while (u++ < screen_w) oc(' ');
    }
    os("\x1b[0m");

    /* Frame end: sync-off, flush. */
    os("\x1b[?2026l");
    oflush();
}

/* ── input + movement ──────────────────────────────────────── */

/* Offset-r pointy-top hex neighbours.  Odd rows shift +1 in x for
 * NE/SE, even rows shift -1 in x for NW/SW.  Standard wadezx maps:
 *   w = NW, e = NE, a = W, d = E, z = SW, x = SE. */
static void hex_step(int *x, int *y, int dir) {
    int odd = (*y) & 1;
    switch (dir) {
    case 'a': (*x)--;                       break;     /* W  */
    case 'd': (*x)++;                       break;     /* E  */
    case 'w': (*y)--; if (!odd) (*x)--;     break;     /* NW */
    case 'e': (*y)--; if ( odd) (*x)++;     break;     /* NE */
    case 'z': (*y)++; if (!odd) (*x)--;     break;     /* SW */
    case 'x': (*y)++; if ( odd) (*x)++;     break;     /* SE */
    }
    if (*x < 0) *x = 0;
    if (*y < 0) *y = 0;
    if (*x >= MAP_W) *x = MAP_W - 1;
    if (*y >= MAP_H) *y = MAP_H - 1;
}

/* ── raw mode ──────────────────────────────────────────────── */
static void raw(void) {
    struct ti t;
    sys3(SYS_ioctl, 0, TCGETS, (long)&tio_orig);
    t = tio_orig;
    t.lflag &= ~0xBU;       /* ~(ISIG | ICANON | ECHO)  → Ctrl-C is a byte */
    t.iflag &= ~0x500U;     /* ~(IXON  | ICRNL)         → Ctrl-S/CR pass  */
    t.cc[6] = 1; t.cc[5] = 0;                   /* VMIN=1 VTIME=0, blocking */
    sys3(SYS_ioctl, 0, TCSETS, (long)&t);
    os("\x1b[?25l\x1b[2J");                     /* hide cursor, clear */
    oflush();
}
static void cooked(void) {
    sys3(SYS_ioctl, 0, TCSETS, (long)&tio_orig);
    os("\x1b[?25h\x1b[0m\x1b[2J\x1b[H\n");
    oflush();
}

int main_c(void) {
    struct ws ws = { 24, 80, 0, 0 };
    sys3(SYS_ioctl, 1, TIOCGWINSZ, (long)&ws);
    if (ws.col) screen_w = ws.col;
    if (ws.row) screen_h = ws.row;
    if (screen_w > 320) screen_w = 320;
    if (screen_h > 120) screen_h = 120;
    recompute_viewport();

    raw();
    draw();

    unsigned char k[16];
    for (;;) {
        long n = sys3(SYS_read, 0, (long)k, sizeof k);
        if (n <= 0) continue;
        int c = k[0];
        /* Decode arrow keys → wadezx equivalents (cardinal only;
         * diagonals need a chorded key anyway). */
        if (c == 0x1b && n >= 3 && k[1] == '[') {
            int a = k[2];
            c = a == 'A' ? 'w' : a == 'B' ? 'x'
              : a == 'C' ? 'd' : a == 'D' ? 'a' : 0x1b;
        }
        if (c == 'q' || c == 0x1b || c == 3 || c == 4) {
            cooked();
            return 0;
        }
        if (c == 'r') {
            player_x = 0;
            player_y = 0;
            draw();
            continue;
        }
        if (c == 'a' || c == 'd' || c == 'w' || c == 'e'
            || c == 'z' || c == 'x') {
            hex_step(&player_x, &player_y, c);
            /* Re-probe window size each frame so terminal resize
             * recomputes the viewport without a restart. */
            struct ws ws2 = { 24, 80, 0, 0 };
            sys3(SYS_ioctl, 1, TIOCGWINSZ, (long)&ws2);
            if (ws2.col && (ws2.col != screen_w || ws2.row != screen_h)) {
                screen_w = ws2.col;
                screen_h = ws2.row;
                if (screen_w > 320) screen_w = 320;
                if (screen_h > 120) screen_h = 120;
                recompute_viewport();
                os("\x1b[2J");
            }
            draw();
        }
    }
}

__asm__ (
    ".global _start\n"
    "_start:\n"
    "    andq $-16, %rsp\n"
    "    call main_c\n"
    "    movl %eax, %edi\n"
    "    movl $231, %eax\n"
    "    syscall\n"
);
