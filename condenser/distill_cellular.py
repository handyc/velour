"""s3lab Cellular sublab → standalone C99.

The cellular sublab is a 16×16 hex tiling where every cell holds
its own K=4 hex CA genome + palette + live grid, and a tournament
GA picks pairs to compete every ~500 ms. The loser is replaced
by a mutated winner; palettes inherit. Watch evolutionary waves
sweep regions.

This distillation emits a single self-contained C99 program that
runs that whole pipeline on a host CPU with zero deps beyond libc.
The "canvas" is replaced with ANSI-256 terminal output — each
population cell renders as a 1×2 colored block using its current
dominant cell colour, refreshed every tick. Stats footer reports
round count + last winner/loser.

Output sizing (defaults: 16×16 pop, 16×16 CA, K=4):
  Per population cell: 4096 (genome) + 4 (palette) + 256 (grid A)
                       + 256 (grid B) + 8 (score+ts) ≈ 4620 bytes.
  Total static BSS: 256 cells × 4620 ≈ 1.13 MB. Comfortable on any
  modern host; would NOT fit in 320 KB SRAM — that's why the ESP32
  port (Phase 2) needs PSRAM. Documented in CONDENSER markers.

Algorithm parity with engine.mjs (the JS reference):
  * PRNG: xorshift32 with the same seed_prng entry point.
  * Grid seed: Park-Miller LCG, same constants (1103515245, 12345).
  * step_grid: identical 6-neighbour table + edge-zero padding.
  * fitness: same 25-tick activity model + same 0.12 / 0.75
    activity-reward inflection.
  * mutate / palette_inherit: same byte-level semantics.

CONDENSER markers throughout describe what shifted vs. the JS:
  * No canvas → terminal ANSI-256
  * No setInterval → blocking nanosleep loop
  * No DOM controls → CLI flags
  * Single-threaded; no Web Worker design space lost
"""

from __future__ import annotations


def distill_cellular_c(
    *,
    grid_cols: int = 16,
    grid_rows: int = 16,
    ca_w: int = 16,
    ca_h: int = 16,
    K: int = 4,
    horizon: int = 25,
    n_rounds: int = 0,
    mut_rate: float = 0.005,
    tick_ms: int = 200,
    round_ms: int = 500,
    seed: int = 0,
) -> str:
    """Emit a self-contained C99 program for the Cellular sublab.

    Parameters mirror the JS sublab's tunables:
      grid_cols/rows : population grid dimensions (16×16 default)
      ca_w/ca_h      : per-cell CA grid (16×16 default; do NOT change
                       without re-validating the genome lookup math)
      K              : colour count; only K=4 is fully validated
      horizon        : fitness horizon in ticks (25 = engine default)
      n_rounds       : run for this many tournament rounds then exit;
                       0 means "loop forever" (Ctrl-C to stop)
      mut_rate       : winner→loser mutation rate (0.005 default)
      tick_ms        : CA step interval (per population cell)
      round_ms       : tournament interval
      seed           : RNG seed; 0 → derive from time(NULL)
    """
    if K != 4:
        raise ValueError('cellular-c distillation only validated for K=4')
    n_cells = grid_cols * grid_rows
    nsit = K ** 7
    gbytes = (nsit * 2 + 7) // 8
    pal_bytes = K
    cell_bytes = gbytes + pal_bytes + 2 * (ca_w * ca_h) + 8
    total_bss = n_cells * cell_bytes

    return f"""\
/* cellular_c.c — distilled from s3lab Cellular sublab.
 *
 * SOURCE  : static/s3lab/js/sublabs/cellular.mjs (438 LOC) +
 *           static/s3lab/js/engine.mjs (276 LOC, kernel)
 * TARGET  : C99, host CPU, libc only
 * PARITY  : algorithm + scoring identical to the JS reference at
 *           the same seed; render is ANSI-256 terminal blocks
 *           instead of a canvas.
 *
 * BUILD   : cc -O2 -std=c99 -o cellular cellular_c.c
 * RUN     : ./cellular           (loops forever; Ctrl-C to quit)
 *           ./cellular -r 200    (200 rounds then exit)
 *           ./cellular -s 1234   (deterministic seed)
 *           ./cellular -h        (help)
 *
 * CONDENSER : sized at distill time:
 *   pop = {grid_cols}×{grid_rows} = {n_cells} cells
 *   per-cell BSS = {cell_bytes} bytes
 *   total BSS = ~{total_bss//1024} KiB
 *   This program is too big for ESP32-S3 SRAM (320 KiB). The
 *   ESP32 port (Phase 2) must allocate the population in PSRAM
 *   (8 MiB) — see condenser.distill_cellular.distill_cellular_esp.
 */

/* getopt + usleep need POSIX 2008 visibility under -std=c99. */
#define _POSIX_C_SOURCE 200809L
#define _DEFAULT_SOURCE

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <signal.h>

/* ── compile-time constants ──────────────────────────────────────── */

#define K           {K}
#define NSIT        {nsit}     /* K^7 */
#define GBYTES      {gbytes}   /* NSIT * 2 bits / 8 */
#define PAL_BYTES   {pal_bytes}
#define CA_W        {ca_w}
#define CA_H        {ca_h}
#define HORIZON     {horizon}
#define GRID_COLS   {grid_cols}
#define GRID_ROWS   {grid_rows}
#define N_CELLS     (GRID_COLS * GRID_ROWS)

#define TICK_MS     {tick_ms}
#define ROUND_MS    {round_ms}
#define DEFAULT_MUT_RATE  {mut_rate}

typedef uint8_t  u8;
typedef uint32_t u32;

/* hex offset deltas, mirror engine.mjs's DY/DXE/DXO */
static const int DY[6]  = {{ -1, -1,  0,  0,  1,  1 }};
static const int DXE[6] = {{  0,  1, -1,  1, -1,  0 }};
static const int DXO[6] = {{ -1,  0, -1,  1,  0,  1 }};

/* ── PRNG: xorshift32 (matches engine.mjs::prng exactly) ─────────── */

static u32 prng_state = 0x9E3779B9u;

static void seed_prng(u32 s) {{
    prng_state = s ? s : 1u;
}}

static inline u32 prng(void) {{
    u32 x = prng_state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    prng_state = x;
    return x;
}}

static inline double prng_unit(void) {{
    return (double)prng() / 4294967296.0;
}}

/* Park-Miller LCG for deterministic grid seeding (mirrors engine.mjs::lcg). */
static u32 lcg_state = 0;
static void lcg_seed(u32 s) {{ lcg_state = s ? s : 1u; }}
static u32 lcg_step(void) {{
    lcg_state = lcg_state * 1103515245u + 12345u;
    return lcg_state >> 16;
}}

/* ── packed-genome accessors (mirror engine.mjs::g_get / g_set) ──── */

static inline int g_get(const u8 *g, int idx) {{
    return (g[idx >> 2] >> ((idx & 3) * 2)) & 3;
}}

static inline void g_set(u8 *g, int idx, int v) {{
    int b = idx >> 2, o = (idx & 3) * 2;
    g[b] = (g[b] & ~(3 << o)) | ((v & 3) << o);
}}

static inline int sit_idx(int self_c, const int *n) {{
    int i = self_c;
    for (int k = 0; k < 6; k++) i = i * K + n[k];
    return i;
}}

/* ── grid stepping (mirror engine.mjs::step_grid line-for-line) ──── */

static void seed_grid_at(u8 *g, u32 s) {{
    lcg_seed(s);
    for (int i = 0; i < CA_W * CA_H; i++) g[i] = (u8)(lcg_step() & 3);
}}

static void step_grid(const u8 *genome, const u8 *in, u8 *out) {{
    int n[6];
    for (int y = 0; y < CA_H; y++) {{
        const int *dx = (y & 1) ? DXO : DXE;
        for (int x = 0; x < CA_W; x++) {{
            int self_c = in[y * CA_W + x];
            for (int k = 0; k < 6; k++) {{
                int yy = y + DY[k], xx = x + dx[k];
                n[k] = (yy >= 0 && yy < CA_H && xx >= 0 && xx < CA_W)
                     ? in[yy * CA_W + xx] : 0;
            }}
            out[y * CA_W + x] = (u8)g_get(genome, sit_idx(self_c, n));
        }}
    }}
}}

/* ── fitness (mirror engine.mjs::fitness EXACTLY) ────────────────── */

static u8 fit_a[CA_W * CA_H];
static u8 fit_b[CA_W * CA_H];

static double fitness(const u8 *genome, u32 grid_seed) {{
    seed_grid_at(fit_a, grid_seed);
    double act[HORIZON];
    int colour_counts[K] = {{0}};
    for (int t = 0; t < HORIZON; t++) {{
        step_grid(genome, fit_a, fit_b);
        int changed = 0;
        for (int i = 0; i < CA_W * CA_H; i++)
            if (fit_a[i] != fit_b[i]) changed++;
        act[t] = (double)changed / (CA_W * CA_H);
        memcpy(fit_a, fit_b, CA_W * CA_H);
    }}
    int uniform = 1;
    for (int i = 1; i < CA_W * CA_H; i++)
        if (fit_a[i] != fit_a[0]) {{ uniform = 0; break; }}
    for (int i = 0; i < CA_W * CA_H; i++) colour_counts[fit_a[i]]++;
    int diversity = 0;
    for (int c = 0; c < K; c++)
        if (colour_counts[c] * 100 >= CA_W * CA_H) diversity++;
    int tail_n = HORIZON / 3;
    if (tail_n < 1) tail_n = 1;
    double avg = 0;
    for (int i = HORIZON - tail_n; i < HORIZON; i++) avg += act[i];
    avg /= tail_n;
    double score = 0;
    if (!uniform) score += 1.0;
    int aperiodic = 0;
    for (int i = HORIZON - tail_n; i < HORIZON; i++)
        if (act[i] > 0.001) {{ aperiodic = 1; break; }}
    if (aperiodic) score += 1.5;
    double activity_reward;
    if (avg <= 0.12) activity_reward = avg / 0.12;
    else             activity_reward = (0.75 - avg) / 0.63;
    if (activity_reward < 0) activity_reward = 0;
    score += 2.0 * activity_reward;
    if (diversity >= 2) score += 0.25 * (diversity < K ? diversity : K);
    return score;
}}

/* ── GA ops (mirror engine.mjs::mutate / palette_inherit) ────────── */

static void random_genome(u8 *g) {{
    for (int i = 0; i < GBYTES; i++) g[i] = (u8)(prng() & 0xFF);
}}

static void invent_palette(u8 *pal) {{
    int written = 0;
    while (written < K) {{
        u32 c = ((prng() % 10) < 9) ? (16  + (prng() % 216))
                                     : (232 + (prng() % 24));
        int dup = 0;
        for (int j = 0; j < written; j++) if (pal[j] == c) {{ dup = 1; break; }}
        if (!dup) pal[written++] = (u8)c;
    }}
}}

static void mutate(u8 *dst, const u8 *src, double rate) {{
    memcpy(dst, src, GBYTES);
    for (int i = 0; i < NSIT; i++)
        if (prng_unit() < rate) g_set(dst, i, (int)(prng() & 3));
}}

static void palette_inherit(u8 *dst, const u8 *a, const u8 *b) {{
    const u8 *src = (prng() & 1) ? a : b;
    memcpy(dst, src, PAL_BYTES);
    if ((prng() % 100) < 8) {{
        int slot = prng() % K;
        u32 c = ((prng() % 10) < 9) ? (16  + (prng() % 216))
                                     : (232 + (prng() % 24));
        dst[slot] = (u8)c;
    }}
}}

/* ── topology: toroidal pointy-top hex (mirror engine.mjs::neighbourIdx) */

static const int NB_DC_EVEN[6] = {{ -1, +1, -1,  0, -1,  0 }};
static const int NB_DC_ODD [6] = {{ -1, +1,  0, +1,  0, +1 }};
static const int NB_DR     [6] = {{  0,  0, -1, -1, +1, +1 }};

static int neighbour_idx(int i, int dir) {{
    int r = i / GRID_COLS, c = i - r * GRID_COLS;
    int dc = (r & 1) ? NB_DC_ODD[dir] : NB_DC_EVEN[dir];
    int dr = NB_DR[dir];
    int nr = (r + dr + GRID_ROWS) % GRID_ROWS;
    int nc = (c + dc + GRID_COLS) % GRID_COLS;
    return nr * GRID_COLS + nc;
}}

/* ── population state — all in BSS so we don't malloc 1+ MiB ─────── */

typedef struct {{
    u8     genome[GBYTES];
    u8     palette[PAL_BYTES];
    u8     grid_a[CA_W * CA_H];
    u8     grid_b[CA_W * CA_H];
    double score;
    u32    refined_at_round;
}} Cell;

static Cell pop[N_CELLS];

/* ── render: ANSI-256 terminal blocks ────────────────────────────── */

/* Dominant cell colour from the current grid — same idea as the
 * canvas which colours each tile by its mode palette index. */
static int dominant_palette_idx(const Cell *c) {{
    int counts[K] = {{0}};
    for (int i = 0; i < CA_W * CA_H; i++) counts[c->grid_a[i]]++;
    int best = 0, best_n = counts[0];
    for (int i = 1; i < K; i++) if (counts[i] > best_n) {{
        best_n = counts[i]; best = i;
    }}
    return c->palette[best];
}}

static void render(u32 round) {{
    /* Clear screen + home cursor */
    fputs("\\x1b[H\\x1b[2J", stdout);
    /* For each population row, emit two terminal rows of half-blocks
     * so cells appear roughly square; offset odd rows by one column
     * to mirror the pointy-top tile stagger. */
    for (int r = 0; r < GRID_ROWS; r++) {{
        if (r & 1) fputc(' ', stdout);
        for (int c = 0; c < GRID_COLS; c++) {{
            int ansi = dominant_palette_idx(&pop[r * GRID_COLS + c]);
            /* Two-character block: bg = palette colour; \\u2588 = █ */
            printf("\\x1b[48;5;%dm  \\x1b[0m", ansi);
        }}
        fputc('\\n', stdout);
    }}
    printf("round %u  pop=%dx%d  mut_rate=%.4f  ", round,
           GRID_COLS, GRID_ROWS, DEFAULT_MUT_RATE);
    fflush(stdout);
}}

/* ── tick: step every cell's CA grid one frame ───────────────────── */

static void tick_all(void) {{
    static u8 tmp[CA_W * CA_H];
    for (int i = 0; i < N_CELLS; i++) {{
        Cell *c = &pop[i];
        step_grid(c->genome, c->grid_a, c->grid_b);
        memcpy(tmp, c->grid_a, CA_W * CA_H);
        memcpy(c->grid_a, c->grid_b, CA_W * CA_H);
        memcpy(c->grid_b, tmp, CA_W * CA_H);
    }}
}}

/* ── round: tournament between random cell + random hex neighbour ─ */

static u32 g_rounds = 0;
static int last_winner = -1, last_loser = -1;

static void run_round(double mut_rate) {{
    int ci  = (int)(prng() % N_CELLS);
    int dir = (int)(prng() % 6);
    int ni  = neighbour_idx(ci, dir);
    if (ci == ni) return;
    u32 shared_seed = prng();
    double fc = fitness(pop[ci].genome, shared_seed);
    double fn = fitness(pop[ni].genome, shared_seed);
    pop[ci].score = fc; pop[ni].score = fn;
    int winner = (fc >= fn) ? ci : ni;
    int loser  = (winner == ci) ? ni : ci;
    Cell *W = &pop[winner], *L = &pop[loser];
    mutate(L->genome, W->genome, mut_rate);
    palette_inherit(L->palette, W->palette, W->palette);
    L->score = W->score;
    L->refined_at_round = g_rounds;
    seed_grid_at(L->grid_a, prng());
    last_winner = winner; last_loser = loser;
    g_rounds++;
}}

/* ── boot: random init for every population cell ─────────────────── */

static void bootstrap(u32 seed) {{
    seed_prng(seed);
    for (int i = 0; i < N_CELLS; i++) {{
        seed_prng((seed ^ (u32)i * 2654435761u) ? : 1u);
        random_genome(pop[i].genome);
        invent_palette(pop[i].palette);
        seed_grid_at(pop[i].grid_a, prng());
        memset(pop[i].grid_b, 0, CA_W * CA_H);
        pop[i].score = 0;
        pop[i].refined_at_round = 0;
    }}
    /* Restore master PRNG so subsequent draws (round selection, fitness
     * seeds) come from the same shared stream. */
    seed_prng(seed ^ 0xDEADBEEFu);
}}

/* ── main loop ───────────────────────────────────────────────────── */

static volatile sig_atomic_t want_quit = 0;
static void on_sigint(int s) {{ (void)s; want_quit = 1; }}

static void usage(const char *argv0) {{
    fprintf(stderr,
        "usage: %s [-r N] [-m RATE] [-s SEED] [-t TICK_MS] [-R ROUND_MS]\\n"
        "  -r N         run for N rounds then exit (default: forever)\\n"
        "  -m RATE      mutation rate (default %.4f)\\n"
        "  -s SEED      PRNG seed (default: time(NULL))\\n"
        "  -t TICK_MS   CA step period (default %d ms)\\n"
        "  -R ROUND_MS  tournament round period (default %d ms)\\n"
        "  -h           this help\\n",
        argv0, DEFAULT_MUT_RATE, TICK_MS, ROUND_MS);
}}

int main(int argc, char **argv) {{
    int   max_rounds = {n_rounds};
    double mut_rate  = DEFAULT_MUT_RATE;
    u32   seed       = {seed};
    int   tick_ms    = TICK_MS;
    int   round_ms   = ROUND_MS;

    int opt;
    while ((opt = getopt(argc, argv, "r:m:s:t:R:h")) != -1) {{
        switch (opt) {{
            case 'r': max_rounds = atoi(optarg); break;
            case 'm': mut_rate   = atof(optarg); break;
            case 's': seed       = (u32)strtoul(optarg, NULL, 0); break;
            case 't': tick_ms    = atoi(optarg); break;
            case 'R': round_ms   = atoi(optarg); break;
            case 'h': default:    usage(argv[0]); return 0;
        }}
    }}
    if (!seed) seed = (u32)time(NULL);

    signal(SIGINT, on_sigint);
    bootstrap(seed);
    fprintf(stderr, "cellular-c: seed=%u  pop=%dx%d  rounds=%d  mut=%.4f\\n",
            seed, GRID_COLS, GRID_ROWS,
            max_rounds ? max_rounds : -1, mut_rate);

    /* Two clocks: tick (CA stepping) and round (tournament). We poll
     * a 10 ms sleep-quantum and fire each on its own deadline. */
    long t_us = 0;
    long next_tick_us  = tick_ms  * 1000;
    long next_round_us = round_ms * 1000;
    int frames_since_render = 0;

    while (!want_quit) {{
        if (t_us >= next_tick_us) {{
            tick_all();
            next_tick_us += tick_ms * 1000;
            if (++frames_since_render >= 1) {{
                render(g_rounds);
                frames_since_render = 0;
            }}
        }}
        if (t_us >= next_round_us) {{
            run_round(mut_rate);
            next_round_us += round_ms * 1000;
            if (max_rounds > 0 && (int)g_rounds >= max_rounds) break;
        }}
        usleep(10 * 1000);
        t_us += 10 * 1000;
    }}

    fprintf(stderr, "\\ncellular-c: %u rounds completed.\\n", g_rounds);
    return 0;
}}
"""


# Supported ST7735 panel variants. Each preset picks an Adafruit
# initR token, the effective WxH (post-setRotation), and a default
# tile size sized to fit the 16×16 population. Add more presets here
# when a new panel turns up; the rest of distill_cellular_esp keys
# off these values.
TFT_VARIANTS = {
    '80x160': {
        'init':     'INITR_MINI160x80',
        'rotation': 3,
        'panel_w':  160,
        'panel_h':  80,
        'tile_px':  5,    # 16*5 + 2 = 82 wide; 16*4 = 64 tall
        'sub_w':    4,    # live-mode sub-tile: 16×4 = 64 wide × 64 tall, centred
        'sub_h':    4,
    },
    '128x128': {
        'init':     'INITR_144GREENTAB',
        'rotation': 0,
        'panel_w':  128,
        'panel_h':  128,
        'tile_px':  7,    # 16*7 + 3 = 115 wide; 16*6 = 96 tall
        'sub_w':    8,    # live-mode sub-tile: 16×8 = 128 wide × 128 tall, exact
        'sub_h':    8,
    },
}


def distill_cellular_esp(
    *,
    grid_cols: int = 16,
    grid_rows: int = 16,
    ca_w: int = 16,
    ca_h: int = 16,
    K: int = 4,
    horizon: int = 25,
    mut_rate: float = 0.005,
    tick_ms: int = 200,
    round_ms: int = 500,
    panel_variant: str = '80x160',
) -> str:
    """Emit an ESP32-S3 SuperMini firmware that runs the full Cellular
    sublab on-device: 256-cell population in PSRAM, ST7735 render of
    the 16×16 hex-offset tile grid, WiFi + HTTP for live status.

    ``panel_variant`` selects between the supported ST7735 panels in
    ``TFT_VARIANTS`` — currently ``80x160`` (the original supermini
    1.8" panel, INITR_MINI160x80 + setRotation(3)) and ``128x128`` (a
    1.44" square panel, INITR_144GREENTAB + setRotation(0)). The
    population layout, tile size, and Adafruit init token all change
    accordingly; algorithm, BSS layout, and HTTP API are identical.

    Reuses the chassis pattern from
    ``isolation/artifacts/hex_ca_class4/esp32_s3_xcc/`` (WiFi STA from
    /wifi.txt, AP fallback, mDNS, WebServer). The big change is the
    population: 256 cells × 4620 B = 1.13 MiB does not fit in 320 KB
    SRAM. We allocate it in PSRAM via
    ``heap_caps_malloc(size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)``.

    The hunt phase from esp32_s3_xcc/ is gone — cellular doesn't run
    a single-genome GA hunt, it runs a per-cell tournament instead.
    Boot just bootstraps the random population and starts the
    two-clock loop (tick + round).
    """
    if K != 4:
        raise ValueError('cellular-esp distillation only validated for K=4')
    if panel_variant not in TFT_VARIANTS:
        raise ValueError(
            f'panel_variant {panel_variant!r} not in '
            f'{sorted(TFT_VARIANTS.keys())!r}')
    panel = TFT_VARIANTS[panel_variant]
    panel_init     = panel['init']
    panel_rotation = panel['rotation']
    panel_w_px     = panel['panel_w']
    panel_h_px     = panel['panel_h']
    sub_w          = panel['sub_w']
    sub_h          = panel['sub_h']
    n_cells = grid_cols * grid_rows
    nsit = K ** 7
    gbytes = (nsit * 2 + 7) // 8
    pal_bytes = K
    cell_bytes = gbytes + pal_bytes + 2 * (ca_w * ca_h) + 8

    # Tile size baked at distill time. Each panel preset picks a value
    # that fits 16×16 cells with a small margin; users override by
    # passing a different panel_variant.
    tile_px = panel['tile_px']
    return f"""\
// cellular_esp.cpp — distilled from s3lab Cellular sublab.
//
// SOURCE   : static/s3lab/js/sublabs/cellular.mjs (438 LOC)
//            + static/s3lab/js/engine.mjs (276 LOC)
//            + isolation/artifacts/hex_ca_class4/esp32_s3_xcc/src/main.cpp
//              (WiFi/HTTP chassis pattern)
// TARGET   : ESP32-S3 SuperMini, Arduino-ESP32 framework, ST7735S 80×160
// PARITY   : algorithm + scoring identical to the JS reference at the same
//            seed. Render is ST7735S TFT instead of HTML5 canvas.
//
// CONDENSER : population BSS would be ~{n_cells * cell_bytes // 1024} KiB
//             (256 cells × {cell_bytes} B each). Does NOT fit in 320 KB
//             SRAM, so the population is allocated in PSRAM via
//             heap_caps_malloc(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT). The
//             ESP32-S3 SuperMini ships with 8 MiB PSRAM — comfortable.

#include <Arduino.h>
#include <LittleFS.h>
#include <esp_system.h>
#include <esp_heap_caps.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <SPI.h>

#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>

// ── compile-time constants ──────────────────────────────────────────

#define K           {K}
#define NSIT        {nsit}     // K^7
#define GBYTES      {gbytes}   // NSIT*2/8
#define PAL_BYTES   {pal_bytes}
#define CA_W        {ca_w}
#define CA_H        {ca_h}
#define HORIZON     {horizon}

#define GRID_COLS   {grid_cols}
#define GRID_ROWS   {grid_rows}
#define N_CELLS     (GRID_COLS * GRID_ROWS)

#define TICK_MS     {tick_ms}
#define ROUND_MS    {round_ms}
#define MUT_RATE    {mut_rate}

#define TILE_PX     {tile_px}

// Panel pixel dimensions baked at distill time. Different panels use
// different INITR_* tokens + setRotation values, so the post-rotation
// effective WxH is what render_pop_diff centres into.
#define PANEL_W_PX  {panel_w_px}
#define PANEL_H_PX  {panel_h_px}

// Live-mode sub-tile geometry. Each cell's 16×16 internal CA gets
// subsampled down to SUB_W × SUB_H pixels — every rendered pixel
// represents a (CA_W/SUB_W) × (CA_H/SUB_H) region of the actual grid.
// On the 128×128 panel that's 8×8 per cell (16 cells × 8 px = 128 px,
// exact fit). On the 80×160 panel it's 4×4 (population area = 64×64
// centred, leaving margin).
#define SUB_W       {sub_w}
#define SUB_H       {sub_h}
#define SUB_DX      (CA_W / SUB_W)        // grid stride per rendered px
#define SUB_DY      (CA_H / SUB_H)

// ST7735S pin map (matches esp32_s3_xcc and esp32_s3_full).
#define PIN_SCK   12
#define PIN_MOSI  11
#define PIN_DC     4
#define PIN_CS     5
#define PIN_RST    6
#define PIN_BL     7
#define SPI_HZ    27000000UL

#define WIFI_CRED_PATH    "/wifi.txt"
#define AP_FALLBACK_SSID  "hexca-cellular-setup"
#define AP_FALLBACK_PASS  "helloboard"
#define HTTP_PORT         80

typedef uint8_t  u8;
typedef uint32_t u32;

static const int DY[6]  = {{ -1, -1,  0,  0,  1,  1 }};
static const int DXE[6] = {{  0,  1, -1,  1, -1,  0 }};
static const int DXO[6] = {{ -1,  0, -1,  1,  0,  1 }};

static const int NB_DC_EVEN[6] = {{ -1, +1, -1,  0, -1,  0 }};
static const int NB_DC_ODD [6] = {{ -1, +1,  0, +1,  0, +1 }};
static const int NB_DR     [6] = {{  0,  0, -1, -1, +1, +1 }};

// ── PRNG: xorshift32 (matches engine.mjs::prng) ─────────────────────

static u32 prng_state = 0x9E3779B9u;
static inline u32 prng() {{
    u32 x = prng_state;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    prng_state = x;
    return x;
}}
static inline double prng_unit() {{ return (double)prng() / 4294967296.0; }}
static void seed_prng(u32 s) {{ prng_state = s ? s : 1u; }}

static u32 lcg_state = 0;
static void lcg_seed(u32 s) {{ lcg_state = s ? s : 1u; }}
static u32 lcg_step() {{
    lcg_state = lcg_state * 1103515245u + 12345u;
    return lcg_state >> 16;
}}

// ── packed-genome accessors ─────────────────────────────────────────

static inline int g_get(const u8 *g, int idx) {{
    return (g[idx >> 2] >> ((idx & 3) * 2)) & 3;
}}
static inline void g_set(u8 *g, int idx, int v) {{
    int b = idx >> 2, o = (idx & 3) * 2;
    g[b] = (g[b] & ~(3 << o)) | ((v & 3) << o);
}}
static inline int sit_idx(int self_c, const int *n) {{
    int i = self_c;
    for (int k = 0; k < 6; k++) i = i * K + n[k];
    return i;
}}

// ── grid stepping (mirror engine.mjs::step_grid) ────────────────────

static void seed_grid_at(u8 *g, u32 s) {{
    lcg_seed(s);
    for (int i = 0; i < CA_W * CA_H; i++) g[i] = (u8)(lcg_step() & 3);
}}

static void step_grid(const u8 *genome, const u8 *in, u8 *out) {{
    int n[6];
    for (int y = 0; y < CA_H; y++) {{
        const int *dx = (y & 1) ? DXO : DXE;
        for (int x = 0; x < CA_W; x++) {{
            int self_c = in[y * CA_W + x];
            for (int k = 0; k < 6; k++) {{
                int yy = y + DY[k], xx = x + dx[k];
                n[k] = (yy >= 0 && yy < CA_H && xx >= 0 && xx < CA_W)
                     ? in[yy * CA_W + xx] : 0;
            }}
            out[y * CA_W + x] = (u8)g_get(genome, sit_idx(self_c, n));
        }}
    }}
}}

// ── fitness (mirror engine.mjs::fitness) ────────────────────────────

static u8 fit_a[CA_W * CA_H];
static u8 fit_b[CA_W * CA_H];

static double fitness(const u8 *genome, u32 grid_seed) {{
    seed_grid_at(fit_a, grid_seed);
    double act[HORIZON];
    int colour_counts[K] = {{0}};
    for (int t = 0; t < HORIZON; t++) {{
        step_grid(genome, fit_a, fit_b);
        int changed = 0;
        for (int i = 0; i < CA_W * CA_H; i++)
            if (fit_a[i] != fit_b[i]) changed++;
        act[t] = (double)changed / (CA_W * CA_H);
        memcpy(fit_a, fit_b, CA_W * CA_H);
    }}
    int uniform = 1;
    for (int i = 1; i < CA_W * CA_H; i++)
        if (fit_a[i] != fit_a[0]) {{ uniform = 0; break; }}
    for (int i = 0; i < CA_W * CA_H; i++) colour_counts[fit_a[i]]++;
    int diversity = 0;
    for (int c = 0; c < K; c++)
        if (colour_counts[c] * 100 >= CA_W * CA_H) diversity++;
    int tail_n = HORIZON / 3;
    if (tail_n < 1) tail_n = 1;
    double avg = 0;
    for (int i = HORIZON - tail_n; i < HORIZON; i++) avg += act[i];
    avg /= tail_n;
    double score = 0;
    if (!uniform) score += 1.0;
    int aperiodic = 0;
    for (int i = HORIZON - tail_n; i < HORIZON; i++)
        if (act[i] > 0.001) {{ aperiodic = 1; break; }}
    if (aperiodic) score += 1.5;
    double activity_reward = (avg <= 0.12) ? avg / 0.12 : (0.75 - avg) / 0.63;
    if (activity_reward < 0) activity_reward = 0;
    score += 2.0 * activity_reward;
    if (diversity >= 2) score += 0.25 * (diversity < K ? diversity : K);
    return score;
}}

// ── GA ops ───────────────────────────────────────────────────────────

static void random_genome_into(u8 *g) {{
    for (int i = 0; i < GBYTES; i++) g[i] = (u8)(prng() & 0xFF);
}}

static void invent_palette_into(u8 *pal) {{
    int n = 0;
    while (n < K) {{
        u32 c = ((prng() % 10) < 9) ? (16  + (prng() % 216))
                                     : (232 + (prng() % 24));
        bool dup = false;
        for (int j = 0; j < n; j++) if (pal[j] == c) {{ dup = true; break; }}
        if (!dup) pal[n++] = (u8)c;
    }}
}}

static void mutate_into(u8 *dst, const u8 *src, double rate) {{
    memcpy(dst, src, GBYTES);
    for (int i = 0; i < NSIT; i++)
        if (prng_unit() < rate) g_set(dst, i, (int)(prng() & 3));
}}

static void palette_inherit_into(u8 *dst, const u8 *a, const u8 *b) {{
    const u8 *src = (prng() & 1) ? a : b;
    memcpy(dst, src, PAL_BYTES);
    if ((prng() % 100) < 8) {{
        int slot = prng() % K;
        u32 c = ((prng() % 10) < 9) ? (16  + (prng() % 216))
                                     : (232 + (prng() % 24));
        dst[slot] = (u8)c;
    }}
}}

// ── topology ─────────────────────────────────────────────────────────

static int neighbour_idx(int i, int dir) {{
    int r = i / GRID_COLS, c = i - r * GRID_COLS;
    int dc = (r & 1) ? NB_DC_ODD[dir] : NB_DC_EVEN[dir];
    int dr = NB_DR[dir];
    int nr = (r + dr + GRID_ROWS) % GRID_ROWS;
    int nc = (c + dc + GRID_COLS) % GRID_COLS;
    return nr * GRID_COLS + nc;
}}

// ── ANSI-256 → RGB565 (matches esp32_s3_xcc::ansi256_to_rgb565) ─────

static const u8 ANSI_LVL[6]  = {{ 0, 95, 135, 175, 215, 255 }};
static const u8 ANSI_STD[16][3] = {{
    {{0,0,0}},      {{128,0,0}},   {{0,128,0}},   {{128,128,0}},
    {{0,0,128}},    {{128,0,128}}, {{0,128,128}}, {{192,192,192}},
    {{128,128,128}},{{255,0,0}},   {{0,255,0}},   {{255,255,0}},
    {{0,0,255}},    {{255,0,255}}, {{0,255,255}}, {{255,255,255}},
}};

static uint16_t ansi256_to_rgb565(u8 idx) {{
    int r = 0, g = 0, b = 0;
    if (idx < 16) {{
        r = ANSI_STD[idx][0]; g = ANSI_STD[idx][1]; b = ANSI_STD[idx][2];
    }} else if (idx < 232) {{
        int i = idx - 16;
        r = ANSI_LVL[(i / 36)];
        g = ANSI_LVL[((i % 36) / 6)];
        b = ANSI_LVL[i % 6];
    }} else {{
        int v = 8 + (idx - 232) * 10;
        if (v > 255) v = 255;
        r = g = b = v;
    }}
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
}}

// ── population state — allocated in PSRAM ───────────────────────────

struct Cell {{
    u8     genome[GBYTES];
    u8     palette[PAL_BYTES];
    u8     grid_a[CA_W * CA_H];
    u8     grid_b[CA_W * CA_H];
    double score;
    u32    refined_at_round;
}};

static Cell *pop = nullptr;     // PSRAM

// Cached "dominant palette index" per cell so render() doesn't have
// to recount every frame. Updated when the cell's grid_a changes.
static u8 dom_cache[N_CELLS];
static uint16_t dom_rgb_cache[N_CELLS];

static void update_dom_cache(int idx) {{
    Cell &c = pop[idx];
    int counts[K] = {{0}};
    for (int i = 0; i < CA_W * CA_H; i++) counts[c.grid_a[i]]++;
    int best = 0, best_n = counts[0];
    for (int i = 1; i < K; i++) if (counts[i] > best_n) {{
        best_n = counts[i]; best = i;
    }}
    u8 ansi = c.palette[best];
    if (dom_cache[idx] != ansi) {{
        dom_cache[idx] = ansi;
        dom_rgb_cache[idx] = ansi256_to_rgb565(ansi);
    }}
}}

// ── TFT ─────────────────────────────────────────────────────────────

static Adafruit_ST7735 tft(PIN_CS, PIN_DC, PIN_MOSI, PIN_SCK, PIN_RST);

// Render the population grid as small hex-offset tiles. Only redraw
// tiles whose dominant color changed since last frame — keeps SPI
// traffic bounded.
static u8 last_drawn[N_CELLS];

// Render mode — flipped at runtime via POST /render-mode.
//   false: dominant-colour-per-cell (cheap, the original render)
//   true : live sub-CA per cell (every rendered pixel = a sample of
//          the actual grid). Costs ~16k pixel writes per tick (~10
//          ms SPI at 27 MHz on a 128×128 panel) but shows real CA
//          motion within every population tile.
static volatile bool g_render_live = false;

static void render_pop_full() {{
    tft.fillScreen(ST77XX_BLACK);
    memset(last_drawn, 0xFF, N_CELLS);
}}

// Live render — paint every cell's grid_a as a SUB_W × SUB_H subsample
// of its 16×16 internal CA. Each cell builds its tile in a stack
// buffer then drawRGBBitmap-blits it (one SPI burst per cell).
//
// No diff cache: at SUB_W=8 and 256 cells we push 16K pixels per
// frame ≈ 32 KB SPI ≈ 10 ms at 27 MHz. Comfortable inside TICK_MS.
//
// Layout: a 2D grid of stride SUB_W × SUB_H, no hex stagger (the
// rendered area is too small to benefit from stagger when a cell is
// only 8×8 px). Centre into the panel.
static void render_pop_live() {{
    const int total_w = GRID_COLS * SUB_W;
    const int total_h = GRID_ROWS * SUB_H;
    const int x0 = (PANEL_W_PX - total_w) / 2;
    const int y0 = (PANEL_H_PX - total_h) / 2;
    uint16_t tile_buf[SUB_W * SUB_H];
    for (int r = 0; r < GRID_ROWS; r++) {{
        for (int c = 0; c < GRID_COLS; c++) {{
            const Cell &cell = pop[r * GRID_COLS + c];
            for (int sy = 0; sy < SUB_H; sy++) {{
                int gy = sy * SUB_DY;
                for (int sx = 0; sx < SUB_W; sx++) {{
                    int gx = sx * SUB_DX;
                    uint8_t v = cell.grid_a[gy * CA_W + gx] % K;
                    tile_buf[sy * SUB_W + sx] =
                        ansi256_to_rgb565(cell.palette[v]);
                }}
            }}
            tft.drawRGBBitmap(x0 + c * SUB_W, y0 + r * SUB_H,
                              tile_buf, SUB_W, SUB_H);
        }}
    }}
}}

static void render_pop_diff() {{
    int total_w = GRID_COLS * TILE_PX + TILE_PX / 2;
    int total_h = (GRID_ROWS * TILE_PX * 866) / 1000;     // hex pack
    int x0 = (PANEL_W_PX - total_w) / 2;
    int y0 = (PANEL_H_PX - total_h) / 2;
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    for (int r = 0; r < GRID_ROWS; r++) {{
        for (int c = 0; c < GRID_COLS; c++) {{
            int idx = r * GRID_COLS + c;
            if (last_drawn[idx] == dom_cache[idx]) continue;
            int x = x0 + c * TILE_PX + ((r & 1) ? (TILE_PX / 2) : 0);
            int y = y0 + (r * TILE_PX * 866) / 1000;
            tft.fillRect(x, y, TILE_PX - 1, TILE_PX - 1, dom_rgb_cache[idx]);
            last_drawn[idx] = dom_cache[idx];
        }}
    }}
}}

// ── tick + round ────────────────────────────────────────────────────

static void tick_all() {{
    for (int i = 0; i < N_CELLS; i++) {{
        Cell &c = pop[i];
        step_grid(c.genome, c.grid_a, c.grid_b);
        // swap A/B
        u8 tmp[CA_W * CA_H];
        memcpy(tmp, c.grid_a, CA_W * CA_H);
        memcpy(c.grid_a, c.grid_b, CA_W * CA_H);
        memcpy(c.grid_b, tmp, CA_W * CA_H);
        update_dom_cache(i);
    }}
}}

static u32 g_rounds = 0;
static int last_winner = -1, last_loser = -1;

static void run_round() {{
    int ci  = (int)(prng() % N_CELLS);
    int dir = (int)(prng() % 6);
    int ni  = neighbour_idx(ci, dir);
    if (ci == ni) return;
    u32 shared_seed = prng();
    double fc = fitness(pop[ci].genome, shared_seed);
    double fn = fitness(pop[ni].genome, shared_seed);
    pop[ci].score = fc; pop[ni].score = fn;
    int winner = (fc >= fn) ? ci : ni;
    int loser  = (winner == ci) ? ni : ci;
    Cell &W = pop[winner], &L = pop[loser];
    mutate_into(L.genome, W.genome, MUT_RATE);
    palette_inherit_into(L.palette, W.palette, W.palette);
    L.score = W.score;
    L.refined_at_round = g_rounds;
    seed_grid_at(L.grid_a, prng());
    last_winner = winner; last_loser = loser;
    g_rounds++;
    update_dom_cache(loser);
}}

// ── bootstrap ───────────────────────────────────────────────────────

static void bootstrap_pop(u32 seed) {{
    seed_prng(seed);
    for (int i = 0; i < N_CELLS; i++) {{
        seed_prng((seed ^ (u32)i * 2654435761u) ? : 1u);
        random_genome_into(pop[i].genome);
        invent_palette_into(pop[i].palette);
        seed_grid_at(pop[i].grid_a, prng());
        memset(pop[i].grid_b, 0, CA_W * CA_H);
        pop[i].score = 0;
        pop[i].refined_at_round = 0;
        update_dom_cache(i);
    }}
    seed_prng(seed ^ 0xDEADBEEFu);
}}

// ── WiFi + HTTP (chassis pattern from esp32_s3_xcc) ─────────────────

static WebServer server(HTTP_PORT);
static String wifi_ip_str = "", wifi_ssid_str = "";
static bool wifi_sta_connected = false;
static volatile bool g_paused = false;

static bool read_wifi_creds(String &ssid, String &pass) {{
    if (!LittleFS.exists(WIFI_CRED_PATH)) return false;
    File f = LittleFS.open(WIFI_CRED_PATH, "r");
    if (!f) return false;
    ssid = f.readStringUntil('\\n'); ssid.trim();
    pass = f.readStringUntil('\\n'); pass.trim();
    f.close();
    return ssid.length() > 0 && pass.length() > 0;
}}

static bool write_wifi_creds(const String &ssid, const String &pass) {{
    File f = LittleFS.open(WIFI_CRED_PATH, "w");
    if (!f) return false;
    f.printf("%s\\n%s\\n", ssid.c_str(), pass.c_str());
    f.close();
    return true;
}}

static void start_ap_fallback() {{
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_FALLBACK_SSID, AP_FALLBACK_PASS);
    wifi_ip_str = WiFi.softAPIP().toString();
    wifi_ssid_str = AP_FALLBACK_SSID;
    Serial.printf("WiFi AP '%s' at %s\\n", AP_FALLBACK_SSID, wifi_ip_str.c_str());
}}

static void try_connect_sta(const String &ssid, const String &pass) {{
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid.c_str(), pass.c_str());
    Serial.printf("WiFi joining '%s' ", ssid.c_str());
    uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - t0) < 12000) {{
        delay(200); Serial.print(".");
    }}
    Serial.println();
    if (WiFi.status() == WL_CONNECTED) {{
        wifi_sta_connected = true;
        wifi_ip_str = WiFi.localIP().toString();
        wifi_ssid_str = ssid;
        Serial.printf("WiFi joined IP %s\\n", wifi_ip_str.c_str());
        if (MDNS.begin("hexca-cellular")) {{
            MDNS.addService("http", "tcp", HTTP_PORT);
            Serial.println("mDNS: http://hexca-cellular.local/");
        }}
    }} else {{
        Serial.println("STA failed; falling back to AP");
        start_ap_fallback();
    }}
}}

static void handle_root() {{
    String html;
    html.reserve(1500);
    html += F("<!doctype html><html><head><title>cellular</title>"
              "<style>body{{font-family:ui-monospace,Menlo,monospace;"
              "max-width:640px;margin:1rem auto;padding:0 1rem;"
              "background:#0d1117;color:#c9d1d9;line-height:1.4}}"
              "table{{border-collapse:collapse;width:100%}}"
              "td{{padding:4px 8px;border-bottom:1px solid #30363d}}"
              "td:first-child{{color:#8b949e}}"
              "code{{background:#161b22;padding:1px 4px;border-radius:3px}}</style>"
              "</head><body>");
    html += F("<h1>cellular</h1><p>ESP32-S3 supermini · 16×16 hex CA population GA</p>");
    html += F("<table>");
    html += "<tr><td>uptime</td><td>" + String(millis() / 1000) + " s</td></tr>";
    html += "<tr><td>free heap</td><td>" + String(ESP.getFreeHeap()) + " B</td></tr>";
    html += "<tr><td>free PSRAM</td><td>" + String(ESP.getFreePsram()) + " B</td></tr>";
    html += "<tr><td>WiFi</td><td>" + String(wifi_sta_connected ? "STA" : "AP") +
            " · " + wifi_ssid_str + " · " + wifi_ip_str + "</td></tr>";
    html += "<tr><td>rounds</td><td>" + String(g_rounds) + "</td></tr>";
    html += "<tr><td>state</td><td>" + String(g_paused ? "PAUSED" : "running") + "</td></tr>";
    html += "<tr><td>render mode</td><td>" + String(g_render_live ? "live (8×8 sub-CA)" : "dominant") + "</td></tr>";
    html += "<tr><td>last winner</td><td>" + String(last_winner) + "</td></tr>";
    html += "<tr><td>last loser</td><td>" + String(last_loser) + "</td></tr>";
    html += F("</table>");
    html += F("<h2>endpoints</h2><ul>"
              "<li><code>GET /info</code> — JSON status</li>"
              "<li><code>POST /wifi</code> — body <code>ssid=…&amp;password=…</code></li>"
              "<li><code>POST /reset</code> — bootstrap a fresh population</li>"
              "<li><code>POST /pause</code>, <code>POST /resume</code></li>"
              "<li><code>POST /render-mode</code> — body <code>mode=dominant</code> "
                  "or <code>mode=live</code> (live = subsampled CA per cell)</li>"
              "</ul></body></html>");
    server.send(200, "text/html", html);
}}

static void handle_info() {{
    String j;
    j.reserve(360);
    j += "{{\\"uptime_s\\":" + String(millis() / 1000);
    j += ",\\"free_heap\\":" + String(ESP.getFreeHeap());
    j += ",\\"free_psram\\":" + String(ESP.getFreePsram());
    j += ",\\"wifi_mode\\":\\"" + String(wifi_sta_connected ? "STA" : "AP") + "\\"";
    j += ",\\"ssid\\":\\"" + wifi_ssid_str + "\\"";
    j += ",\\"ip\\":\\"" + wifi_ip_str + "\\"";
    j += ",\\"rounds\\":" + String(g_rounds);
    j += ",\\"paused\\":" + String(g_paused ? "true" : "false");
    j += ",\\"last_winner\\":" + String(last_winner);
    j += ",\\"last_loser\\":" + String(last_loser);
    j += ",\\"grid_cols\\":" + String(GRID_COLS);
    j += ",\\"grid_rows\\":" + String(GRID_ROWS);
    j += ",\\"render_mode\\":\\"" + String(g_render_live ? "live" : "dominant") + "\\"" + "}}";
    server.send(200, "application/json", j);
}}

static void handle_wifi() {{
    String ssid = server.arg("ssid"), pass = server.arg("password");
    if (ssid.length() == 0) {{
        server.send(400, "text/plain", "missing ssid"); return;
    }}
    if (!write_wifi_creds(ssid, pass)) {{
        server.send(500, "text/plain", "write failed"); return;
    }}
    server.send(200, "text/plain", "saved; rebooting in 2 s\\n");
    delay(2000); ESP.restart();
}}

static void handle_reset() {{
    bootstrap_pop((u32)esp_random());
    g_rounds = 0; last_winner = -1; last_loser = -1;
    render_pop_full();
    if (g_render_live) render_pop_live(); else render_pop_diff();
    server.send(200, "text/plain", "fresh population\\n");
    Serial.println("[reset] fresh population");
}}

static void handle_pause()  {{ g_paused = true;  server.send(200, "text/plain", "paused\\n"); }}
static void handle_resume() {{ g_paused = false; server.send(200, "text/plain", "resumed\\n"); }}

// POST /render-mode body: mode=dominant or mode=live. Flips the
// per-tick render path and forces an immediate full repaint so the
// switch is visible without waiting for the next tick.
static void handle_render_mode() {{
    String m = server.arg("mode");
    if (m == "live") {{
        g_render_live = true;
    }} else if (m == "dominant") {{
        g_render_live = false;
    }} else {{
        server.send(400, "text/plain",
                    "mode must be \\"dominant\\" or \\"live\\"\\n");
        return;
    }}
    render_pop_full();
    if (g_render_live) render_pop_live(); else render_pop_diff();
    server.send(200, "text/plain",
                String("render mode: ") + (g_render_live ? "live" : "dominant") + "\\n");
}}

static void comms_setup() {{
    String ssid, pass;
    if (read_wifi_creds(ssid, pass)) try_connect_sta(ssid, pass);
    else {{ Serial.println("no /wifi.txt; AP-mode setup"); start_ap_fallback(); }}
    server.on("/",            HTTP_GET,  handle_root);
    server.on("/info",        HTTP_GET,  handle_info);
    server.on("/wifi",        HTTP_POST, handle_wifi);
    server.on("/reset",       HTTP_POST, handle_reset);
    server.on("/pause",       HTTP_POST, handle_pause);
    server.on("/resume",      HTTP_POST, handle_resume);
    server.on("/render-mode", HTTP_POST, handle_render_mode);
    server.begin();
    Serial.printf("HTTP on :%d\\n", HTTP_PORT);
}}

// ── setup / loop ────────────────────────────────────────────────────

void setup() {{
    Serial.begin(115200);
    uint32_t t0 = millis();
    while (!Serial && (millis() - t0) < 2000) delay(10);
    Serial.println("\\n=== cellular ESP32-S3 (PSRAM-backed population) ===");

    if (!LittleFS.begin(true)) Serial.println("LittleFS mount failed");
    if (!psramInit())          Serial.println("PSRAM init FAILED — population will not fit!");

    size_t need = (size_t)N_CELLS * sizeof(Cell);
    pop = (Cell *)heap_caps_malloc(need,
            MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!pop) {{
        Serial.printf("PSRAM allocation of %u B FAILED\\n", (unsigned)need);
        while (1) delay(1000);
    }}
    Serial.printf("PSRAM: allocated %u B (%u KiB) for population\\n",
                  (unsigned)need, (unsigned)(need / 1024));

    pinMode(PIN_BL, OUTPUT); digitalWrite(PIN_BL, HIGH);
    tft.initR({panel_init});
    tft.setSPISpeed(SPI_HZ);
    tft.setRotation({panel_rotation});
    tft.invertDisplay(true);
    tft.fillScreen(ST77XX_BLACK);

    u32 seed = esp_random() ^ (u32)esp_timer_get_time();
    bootstrap_pop(seed);
    render_pop_full();
    if (g_render_live) render_pop_live(); else render_pop_diff();
    Serial.printf("bootstrapped with seed %u (render mode: %s)\\n",
                  seed, g_render_live ? "live" : "dominant");

    comms_setup();
    Serial.println("=== running tournament GA + TFT ===");
}}

static uint32_t next_tick_ms  = 0;
static uint32_t next_round_ms = 0;

void loop() {{
    server.handleClient();
    if (g_paused) {{ delay(20); return; }}
    uint32_t now = millis();
    if (now >= next_tick_ms) {{
        tick_all();
        if (g_render_live) render_pop_live();
        else                render_pop_diff();
        next_tick_ms = now + TICK_MS;
    }}
    if (now >= next_round_ms) {{
        run_round();
        next_round_ms = now + ROUND_MS;
        if (g_rounds % 30 == 0) {{
            Serial.printf("round %u  free_heap=%u  free_psram=%u\\n",
                          g_rounds, ESP.getFreeHeap(), ESP.getFreePsram());
        }}
    }}
    delay(5);
}}
"""


def distill_cellular_esp_pio() -> str:
    """platformio.ini for the ESP32-S3 firmware variant."""
    return """\
; cellular — ESP32-S3 SuperMini variant of s3lab Cellular sublab.
;
; Build & flash:
;   pio run -t upload
;   pio device monitor
;
; The 256-cell population (~1.13 MiB) is allocated in PSRAM via
; heap_caps_malloc(MALLOC_CAP_SPIRAM). PSRAM must be enabled in
; build flags for the runtime to map it.

[platformio]
default_envs = esp32_s3_supermini

[env:esp32_s3_supermini]
platform   = espressif32
board      = esp32-s3-devkitc-1
framework  = arduino
monitor_speed = 115200

build_flags =
    -DARDUINO_USB_CDC_ON_BOOT=1
    -DARDUINO_USB_MODE=1
    -DCORE_DEBUG_LEVEL=0
    -DBOARD_HAS_PSRAM
    -mfix-esp32-psram-cache-issue

board_build.filesystem = littlefs
board_build.arduino.memory_type = qio_opi

lib_deps =
    adafruit/Adafruit GFX Library
    adafruit/Adafruit ST7735 and ST7789 Library
"""


def distill_cellular_esp_readme() -> str:
    """Operator-facing README for the ESP32-S3 variant."""
    return """\
# cellular — ESP32-S3 SuperMini port of the s3lab Cellular sublab

The full Cellular sublab on a stick. 16×16 hex-tiled population of
K=4 hex CA genomes, tournament GA every 500 ms, ST7735S 80×160
TFT showing the population grid as colored tiles.

## Why PSRAM

Per population cell:
  * 4096 B genome (K=4 packed)
  * 4 B palette
  * 256 B grid_a + 256 B grid_b
  * 8 B score + timestamp

Total: ~4620 B per cell × 256 cells = ~1.13 MiB.

The supermini has 320 KB SRAM and 8 MB PSRAM. Population goes in
PSRAM via `heap_caps_malloc(MALLOC_CAP_SPIRAM)`. SRAM is reserved
for the GA's working buffers, the WiFi stack, and the TFT framebuffer.

## Build + flash

```
pio run -t upload
pio device monitor
```

## Provision WiFi (first boot)

Without `/wifi.txt`, the board comes up as `hexca-cellular-setup`
(password `helloboard`, IP 192.168.4.1). From a phone or laptop:

```
curl -X POST http://192.168.4.1/wifi -d 'ssid=YOUR_SSID&password=YOUR_PASS'
```

After it joins, find it at `http://hexca-cellular.local/`.

## Endpoints

| method | path        | what                                    |
|--------|-------------|-----------------------------------------|
| GET    | /           | status HTML                             |
| GET    | /info       | JSON status (uptime, heap, PSRAM, rounds) |
| POST   | /wifi       | provision WiFi (ssid + password)        |
| POST   | /reset      | bootstrap a fresh random population     |
| POST   | /pause      | freeze the GA (TFT keeps last frame)    |
| POST   | /resume     | resume the GA                           |

## Generated by

`condenser/distill_cellular.py:distill_cellular_esp` — see CONDENSER
markers in `cellular_esp.cpp` for what shifted vs the JS reference.
"""


def distill_cellular_makefile() -> str:
    """A trivial Makefile for the C distillation."""
    return """\
# Build the cellular distillation. cc -O2 is the only requirement.
CC      ?= cc
CFLAGS  ?= -O2 -std=c99 -Wall

cellular: cellular_c.c
\t$(CC) $(CFLAGS) -o $@ $<

clean:
\trm -f cellular

run: cellular
\t./cellular

.PHONY: clean run
"""


def distill_cellular_readme() -> str:
    """Operator-facing README for the artifact directory."""
    return """\
# cellular — host C99 distillation of s3lab Cellular sublab

Standalone C99 program that runs the same 16×16 spatial-GA hex CA
the JS sublab runs in the browser, but renders to a 256-color
terminal instead of a canvas. Algorithm + scoring + RNG are all
byte-identical to the reference at the same seed.

## Build + run

```
make            # builds ./cellular via cc -O2
./cellular      # loops forever; Ctrl-C to quit
./cellular -r 200 -s 1234     # 200 rounds, deterministic seed
```

## What you should see

A 16×16 grid of colored 2-cell terminal blocks. Each block is one
population cell, coloured by the dominant palette colour of its
current 16×16 internal CA grid. Run for ~30-60 seconds and regions
of related palettes emerge as winning rules out-breed losing ones.

A footer line prints round count + parameters.

## Memory

This is a HOST distillation — total population state is ~1.13 MiB.
The ESP32-S3 SuperMini's 320 KiB SRAM cannot hold it. The Phase 2
ESP port (planned) will allocate the population in PSRAM.

## Generated by

`condenser/distill_cellular.py` — see CONDENSER markers in the
emitted source for what shifted vs. the JS reference.
"""
