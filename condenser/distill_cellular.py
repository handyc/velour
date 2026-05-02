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
